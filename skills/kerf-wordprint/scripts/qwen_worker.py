#!/usr/bin/env python3
"""Local adapter for installed Qwen/ForcedAligner and Community-1 backends; writes normalized-run.json."""
import argparse
import dataclasses
import hashlib
import importlib.util
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import wave

ACTIVE_PROCESS = None


class Cancelled(Exception):
    pass


def cancel(_signum, _frame):
    if ACTIVE_PROCESS is not None and ACTIVE_PROCESS.poll() is None:
        ACTIVE_PROCESS.terminate()
        try:
            ACTIVE_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ACTIVE_PROCESS.kill()
            ACTIVE_PROCESS.wait()
    raise Cancelled("使用者已取消；已完成的原始輸出仍保留。")


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def progress(text):
    print("progress:" + text, flush=True)


def command(arguments, directory, name, input_text=None, timeout=None):
    global ACTIVE_PROCESS
    with (directory / (name + ".stdout.log")).open("wb") as out, (directory / (name + ".stderr.log")).open("wb") as err:
        ACTIVE_PROCESS = subprocess.Popen(arguments, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                          stdout=out, stderr=err, env=os.environ.copy())
        try:
            try:
                ACTIVE_PROCESS.communicate(input_text.encode("utf-8") if input_text is not None else None, timeout=timeout)
            except subprocess.TimeoutExpired:
                ACTIVE_PROCESS.terminate()
                try:
                    ACTIVE_PROCESS.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ACTIVE_PROCESS.kill()
                    ACTIVE_PROCESS.wait()
                raise RuntimeError(f"{name} 超過 {timeout:.0f} 秒；原始文字與對齊資料已保留。")
            code = ACTIVE_PROCESS.returncode
        finally:
            if ACTIVE_PROCESS.poll() is None:
                ACTIVE_PROCESS.terminate()
                ACTIVE_PROCESS.wait()
            ACTIVE_PROCESS = None
    if code:
        raise RuntimeError(f"{name} 失敗（{code}）；請查看 {name}.stdout.log／{name}.stderr.log")
    return (directory / (name + ".stdout.log")).read_text(encoding="utf-8")


def snapshot(home, model_id):
    root = home / ".cache/huggingface/hub" / ("models--" + model_id.replace("/", "--"))
    refs = root / "refs/main"
    candidates = []
    if refs.is_file():
        revision = refs.read_text().strip()
        if revision and "/" not in revision and ".." not in revision:
            candidates.append(root / "snapshots" / revision)
    candidates.extend(sorted((root / "snapshots").glob("*")))
    for path in candidates:
        if not all((path / name).is_file() for name in ("config.json", "tokenizer_config.json", "vocab.json", "merges.txt")):
            continue
        weights = list(path.glob("*.safetensors"))
        index = path / "model.safetensors.index.json"
        if index.is_file():
            index_data = json.loads(index.read_text())
            if not all((path / name).is_file() for name in set(index_data["weight_map"].values())):
                continue
        if weights and all(p.stat().st_size > 0 for p in weights):
            return path
    raise RuntimeError(f"本機快取缺少完整 {model_id}；本工作流程不會下載模型。")


def check_chunks(chunks, duration):
    if not chunks:
        raise ValueError("ASR 沒有完整 chunk 記錄。")
    cursor = 0.0
    for item in chunks:
        start, end = item.get("start"), item.get("end")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or abs(start - cursor) > .02 or end <= start or end > duration + .02):
            raise ValueError("ASR chunk 時間不連續或超出 PCM 範圍。")
        if item.get("truncated") is not False or item.get("finish_reason") not in ("eos", "repetition"):
            raise ValueError("ASR 含截斷或缺少停止原因；保留 raw.json。")
        cursor = end
    if abs(cursor - duration) > .02:
        raise ValueError("ASR 未覆蓋 PCM 結尾。")


def parse_json(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[index:])
                if (isinstance(value, dict) and isinstance(value.get("segments"), list)
                        and type(value.get("num_speakers")) is int and value["num_speakers"] >= 0):
                    return value
            except json.JSONDecodeError:
                pass
    raise ValueError("說話者工具沒有有效 JSON。")


def check_alignment(chunks, duration, normalize):
    check_chunks(chunks, duration)
    for chunk in chunks:
        previous_start = previous_end = chunk["start"]
        words = chunk["words"]
        character_ends, characters, aligned_characters = set(), 0, 0
        for char in chunk["text"]:
            characters += len(normalize(char))
            character_ends.add(characters)
        for word in words:
            start, end = word.get("start"), word.get("end")
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end)
                    or not chunk["start"] - .02 <= start <= end <= chunk["end"] + .02
                    or start < previous_start - .02 or end < previous_end - .02):
                raise ValueError("對齊詞時間超出原始 chunk 或順序不符。")
            previous_start, previous_end = start, end
            token = normalize(word["text"])
            aligned_characters += len(token)
            if not token or aligned_characters not in character_ends:
                raise ValueError("對齊詞拆開原始字元或包含未附屬的標點。")
        if normalize("".join(word["text"] for word in words)) != normalize(chunk["text"]):
            raise ValueError("ForcedAligner 文字與原始 ASR 不一致；未編造缺少的詞時間。")


def speaker_cache_ready(home):
    root = home / "Library/Caches/qwen3-speech/models/aufklarer/Pyannote-Community-1-CoreML"
    for name in ("segmentation.mlmodelc", "embedding.mlmodelc"):
        bundle = root / name
        if not all((bundle / file).is_file() and (bundle / file).stat().st_size > 0
                   for file in ("model.mil", "coremldata.bin", "weights/weight.bin")):
            return False
    return all((root / name).is_file() and (root / name).stat().st_size > 0
               for name in ("config.json", "plda.safetensors"))


def read_helper():
    path = Path(__file__).with_name("transcript.py")
    if not path.is_file():
        raise RuntimeError("找不到同目錄的 transcript.py。")
    spec = importlib.util.spec_from_file_location("wordprint_transcript", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


BRIDGE = Path(__file__).with_name("community1-bridge") / "build/community1-bridge"
SANDBOX = "/usr/bin/sandbox-exec"


def diarization_backend(home):
    """Bridge under sandbox-exec when built; otherwise the installed speech CLI (network not blocked)."""
    bridge = BRIDGE if BRIDGE.is_file() and os.access(BRIDGE, os.X_OK) else None
    speech = shutil.which("speech")
    if not speaker_cache_ready(home):
        raise RuntimeError("Community-1 本機快取不完整；未下載或執行說話者模型。")
    if bridge is not None and not Path(SANDBOX).is_file():
        raise RuntimeError("缺少逐程序網路阻擋工具，已跳過說話者推論。")
    if bridge is None and speech is None:
        raise RuntimeError("找不到 community1-bridge 或 speech CLI；請先執行 sh scripts/community1-bridge/build.sh。")
    if bridge is not None:
        record = {"id": "aufklarer/Pyannote-Community-1-CoreML", "engine": "community1-bridge (speech-swift v0.0.27 fromLocal CoreML)",
                  "network": "sandbox deny network*"}
    else:
        record = {"id": "aufklarer/Pyannote-Community-1-CoreML", "engine": "speech diarize --engine community1 --community1-compute-units cpu",
                  "network": "diarization stage not network-blocked"}
    return bridge, speech, record


def diarize(pcm_bytes, directory, home, duration, state):
    bridge, speech, record = diarization_backend(home)
    # Persist the backend before any subprocess so failure, timeout and cancel all keep it.
    state["diarization"] = record
    state["network"] += "; diarization: " + record["network"]
    save(directory / "state.json", state)
    cache = home / "Library/Caches/qwen3-speech/models/aufklarer/Pyannote-Community-1-CoreML"
    turns = []
    total_samples = len(pcm_bytes) // 2
    window_samples = 20 * 60 * 16000
    starts = range(0, total_samples, window_samples)
    for index, start in enumerate(starts):
        end = min(start + window_samples, total_samples)
        offset, length = start / 16000, (end - start) / 16000
        file = directory / f"diarization-{index:03}.wav"
        with wave.open(str(file), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(pcm_bytes[start * 2:end * 2])
        progress(f"說話者分段 {index + 1}/{len(starts)}")
        if bridge is not None:
            arguments = [SANDBOX, "-p", "(version 1)(allow default)(deny network*)", str(bridge),
                         "--audio", str(file), "--cache-dir", str(cache)]
        else:
            arguments = [speech, "diarize", "--engine", "community1", "--community1-compute-units", "cpu", "--json", str(file)]
        output = command(arguments, directory, f"diarization-{index:03}", timeout=max(120, length * 2))
        result = parse_json(output)
        # Only the bridge reports its PCM clock; speech CLI JSON has segments and num_speakers alone.
        if bridge is not None and (result.get("sample_count") != end - start or result.get("sample_rate") != 16000):
            raise ValueError("離線說話者 bridge 的 PCM 樣本時鐘與輸入不一致。")
        save(directory / f"diarization-{index:03}.json", result)
        for segment in result.get("segments", []):
            a, b, speaker = segment.get("start"), segment.get("end"), segment.get("speaker")
            if (type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a)
                    or not math.isfinite(b) or not 0 <= a < b <= length + .02 or type(speaker) is not int):
                raise ValueError("Community-1 回傳無效時間或說話者 ID。")
            turns.append({"start": offset + a, "end": min(offset + b, duration), "speaker": (index, speaker)})
    return name_speakers(turns, len(starts)), record


def name_speakers(turns, windows):
    """One window: S1, S2… by first appearance; several windows keep local IDs apart until matched by acoustic evidence."""
    turns = sorted(turns, key=lambda turn: turn["start"])
    order = {}
    for turn in turns:
        order.setdefault(turn["speaker"], len(order) + 1)
    for turn in turns:
        window, speaker = turn["speaker"]
        turn["speaker"] = f"S{order[(window, speaker)]}" if windows == 1 else f"window-{window + 1}-speaker-{speaker + 1}"
    return turns


def combine(parts):
    """Concatenate decoded 16 kHz mono PCM in the given order; offsets come from sample counts."""
    records, offset_samples = [], 0
    for part in parts:
        count = len(part["pcm"]) // 2
        if count <= 0 or len(part["pcm"]) != count * 2:
            raise ValueError(f"PCM 解碼不完整或沒有音訊：{part['path']}")
        records.append({"path": part["path"], "sha256": part["sha256"], "sha256_before_decode": part["sha256"],
                        "sha256_after_decode": part["sha256"], "duration": count / 16000,  # decode_source proved them equal.
                        "offset": offset_samples / 16000, "sample_count": count, "sample_rate": 16000,
                        "probe_duration": part.get("probe_duration")})
        offset_samples += count
    return records, b"".join(part["pcm"] for part in parts)


def sha256(path):
    fingerprint = hashlib.sha256()
    with path.open("rb") as original:
        for block in iter(lambda: original.read(1024 * 1024), b""):
            fingerprint.update(block)
    return fingerprint.hexdigest()


def decode_source(source, index, directory, ffmpeg, ffprobe):
    """One source to 16 kHz mono PCM; the source must hash the same before and after decoding."""
    before = sha256(source)
    probe = json.loads(command([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
                               directory, f"probe-{index:03}"))
    save(directory / f"probe-{index:03}.json", probe)
    decoded = directory / f"decode-{index:03}.wav"
    command([ffmpeg, "-nostdin", "-v", "error", "-i", str(source), "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", "-n", str(decoded)], directory, f"decode-{index:03}")
    with wave.open(str(decoded), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("PCM 解碼格式不符。")
        frames = audio.getnframes()
        data = audio.readframes(frames)
    if frames <= 0 or len(data) != frames * 2:
        raise ValueError(f"PCM 解碼不完整或沒有音訊：header 宣告 {frames} frames，實讀 {len(data) // 2}。")
    after = sha256(source)
    if after != before:
        save(directory / "sources.json", [{"path": str(source), "sha256_before_decode": before, "sha256_after_decode": after}])
        raise RuntimeError(f"來源音檔在解碼期間被更動：{source}；兩個雜湊記在 sources.json，解碼輸出保留。")
    decoded.unlink()  # The concatenated canonical.wav is the retained copy.
    return {"path": str(source), "sha256": before, "pcm": data, "probe_duration": probe.get("format", {}).get("duration")}


def claim(directory):
    """Own a new or empty run directory; anything else is refused before a single byte is written there."""
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError(f"請使用新的或空的轉錄目錄；既有目錄未改動：{directory}")
    with (directory / "state.json").open("x", encoding="utf-8") as file:  # Exclusive create: a racing worker loses here.
        file.write('{"stage": "start"}\n')


def transcribe(arguments):
    directory, home = Path(arguments.run_directory).resolve(), Path.home()
    sources = [Path(path).resolve() for path in arguments.audio]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise RuntimeError("找不到本機音檔：" + "、".join(missing))
    model_id = "Qwen/Qwen3-ASR-" + arguments.model
    model_path = snapshot(home, model_id)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("缺少已安裝 ffmpeg／ffprobe。")
    state = {"stage": "decode", "model": model_id, "modelRevision": model_path.name,
             "backend": "mlx-qwen3-asr", "backendVersion": importlib.metadata.version("mlx-qwen3-asr"),
             "network": "Hugging Face offline (HF_HUB_OFFLINE=1)", "warnings": []}
    save(directory / "state.json", state)
    parts = []
    for index, source in enumerate(sources):
        progress(f"解碼 {index + 1}/{len(sources)} 為單聲道 16 kHz PCM…")
        parts.append(decode_source(source, index, directory, ffmpeg, ffprobe))
    source_records, pcm_bytes = combine(parts)
    del parts
    count = len(pcm_bytes) // 2
    duration = count / 16000
    with wave.open(str(directory / "canonical.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm_bytes)
    with wave.open(str(directory / "canonical.wav"), "rb") as audio:
        if audio.getnframes() != sum(record["sample_count"] for record in source_records):
            raise ValueError("canonical.wav 樣本數不等於各檔之和。")
    save(directory / "sources.json", source_records)
    state["stage"] = "asr"
    save(directory / "state.json", state)
    import numpy as np
    from mlx_qwen3_asr import transcribe as qwen_transcribe, ForcedAligner
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    progress("Qwen 正在辨識；全部處理完成後會先保留原始 ASR。")
    def on_progress(item):
        if item.get("event") == "chunk_completed":
            progress(f"ASR {item.get('chunk_index')}/{item.get('total_chunks')}")
            save(directory / "asr-progress.json", item)
    result = qwen_transcribe(audio=(samples, 16000), model=str(model_path), return_chunks=True,
                             return_timestamps=False, on_progress=on_progress)
    raw = dataclasses.asdict(result)
    save(directory / "raw.json", raw)
    chunks, warnings = raw.get("chunks") or [], state["warnings"]
    normalized = {"schema_version": 1, "sources": source_records, "pcm": "canonical.wav",
                  "model": {"id": model_id, "size": arguments.model, "revision": model_path.name},
                  "chunks": [], "turns": [], "diarization_complete": False, "speakers": {}}
    alignment_complete = False
    try:
        check_chunks(chunks, duration)
        if any(chunk.get("finish_reason") == "repetition" for chunk in chunks):
            warnings.append("ASR 曾以重複偵測停止；請人工檢查該段文字。")
        aligner_path = snapshot(home, "Qwen/Qwen3-ForcedAligner-0.6B")
        normalized["alignment_model"] = {"id": "Qwen/Qwen3-ForcedAligner-0.6B", "revision": aligner_path.name}
        aligner = ForcedAligner(model_path=str(aligner_path), backend="mlx")
        state["stage"] = "alignment"
        save(directory / "state.json", state)
        for index, chunk in enumerate(chunks):
            progress(f"逐詞對齊 {index + 1}/{len(chunks)}")
            start, end = round(chunk["start"] * 16000), round(chunk["end"] * 16000)
            aligned = aligner.align(samples[start:end], chunk["text"], chunk.get("language") or raw.get("language") or "Chinese") if chunk["text"].strip() else []
            words = [{"text": word.text, "start": word.start_time + chunk["start"],
                      "end": word.end_time + chunk["start"]} for word in aligned]
            normalized["chunks"].append({**chunk, "words": words, "complete": True})
            save(directory / "alignment.json", normalized["chunks"])
        alignment_complete = True
        state["stage"] = "diarization"
        normalized["turns"], normalized["diarization_model"] = diarize(pcm_bytes, directory, home, duration, state)
        normalized["speakers"] = {item["speaker"]: {} for item in normalized["turns"]}
        normalized["diarization_complete"] = True
        save(directory / "speaker-turns.json", normalized["turns"])
        if duration > 1200:
            warnings.append("長錄音的每個 20 分鐘視窗使用獨立說話者 ID，未跨窗推定身分。")
    except Cancelled:
        raise
    except Exception as error:
        warnings.append(f"{state['stage']} 未完成：{error}")
    save(directory / "normalized-run.json", normalized)
    is_complete = False
    if alignment_complete:
        try:
            helper = read_helper()
            check_alignment(normalized["chunks"], duration, helper.normalized)
            if normalized["diarization_complete"]:
                _, report = helper.validate(directory / "normalized-run.json")
            else:
                report = {"ok": True, "scope": "alignment only", "duration": duration,
                          "words": sum(len(chunk["words"]) for chunk in normalized["chunks"]),
                          "text_match": True, "diarization_complete": False}
            save(directory / "validation.json", report)
            is_complete = normalized["diarization_complete"] and not any(chunk.get("finish_reason") == "repetition" for chunk in chunks)
        except Cancelled:
            raise
        except Exception as error:
            warnings.append(f"時間／文字驗證未通過：{error}")
    state.update(stage="complete" if is_complete else "partial", warnings=warnings)
    save(directory / "state.json", state)
    progress("轉錄完成。" if is_complete else "原始文字已保存；部分階段待補完，請查看 state.json 警示。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, action="append", help="repeat to merge recordings in this order")
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--model", required=True, choices=["0.6B", "1.7B"])
    args = parser.parse_args()
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[key] = "1"
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    directory = Path(args.run_directory).resolve()
    try:
        claim(directory)
    except OSError as error:
        print(str(error) if isinstance(error, FileExistsError) else f"無法建立轉錄目錄：{error}", file=sys.stderr, flush=True)
        return 1
    try:
        transcribe(args)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        state_path = directory / "state.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        state.update(stage="cancelled" if isinstance(error, (Cancelled, KeyboardInterrupt)) else "failed", error=str(error))
        save(state_path, state)
        print(str(error), file=sys.stderr, flush=True)
        return 130 if isinstance(error, (Cancelled, KeyboardInterrupt)) else 1


if __name__ == "__main__":
    sys.exit(main())

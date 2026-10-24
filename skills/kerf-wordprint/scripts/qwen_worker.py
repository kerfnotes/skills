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

_runtime_spec = importlib.util.spec_from_file_location("wordprint_runtime", Path(__file__).with_name("worker_runtime.py"))
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)


def interrupt(_signum, _frame):
    raise KeyboardInterrupt  # SIGTERM cleans up like Ctrl-C; subprocess.run kills the running child.


def save(path, value, *, allow_nan=False):
    if path.name == "state.json":
        return runtime.state(path.parent, value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=allow_nan) + "\n", encoding="utf-8")
    temporary.replace(path)


def progress(text):
    print("progress:" + text, flush=True)


def command(arguments, directory, name, timeout=None):
    with (directory / (name + ".stdout.log")).open("wb") as out, (directory / (name + ".stderr.log")).open("wb") as err:
        try:
            code = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{name} 超過 {timeout:.0f} 秒；原始文字與對齊資料已保留。")
    if code:
        reason = (directory / (name + ".stderr.log")).read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:]
        raise RuntimeError(f"{name} 失敗（{code}）{'：' + reason[0] if reason else ''}；請查看 {name}.stdout.log／{name}.stderr.log")
    return (directory / (name + ".stdout.log")).read_text(encoding="utf-8")


def snapshot(model_id):
    from huggingface_hub import snapshot_download
    try:
        return Path(snapshot_download(model_id, local_files_only=True, ignore_patterns=["*.md", ".gitattributes"]))
    except Exception as error:
        raise RuntimeError(f"本機快取缺少完整 {model_id}；本工作流程不會下載模型。（{error}）")


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
BOUNDARY_WARNING = "逐詞時間格邊界處理：已將包含音訊終點的最後模型時間格與實際 PCM 範圍取交集；這不代表對齊準確度已修復。原始預測與調整記錄已保留。"


def diarize(pcm_bytes, directory, home, duration, state):
    if not (BRIDGE.is_file() and os.access(BRIDGE, os.X_OK)):
        raise RuntimeError("找不到 community1-bridge；請先執行 sh SCRIPTS/community1-bridge/build.sh。")
    if not Path(SANDBOX).is_file():
        raise RuntimeError("缺少逐程序網路阻擋工具，已跳過說話者推論。")
    record = {"id": "aufklarer/Pyannote-Community-1-CoreML", "engine": "community1-bridge (speech-swift v0.0.27 fromLocal CoreML)",
              "network": "sandbox deny network*"}
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
        arguments = [SANDBOX, "-p", "(version 1)(allow default)(deny network*)", str(BRIDGE),
                     "--audio", str(file), "--cache-dir", str(cache)]
        result = json.loads(command(arguments, directory, f"diarization-{index:03}", timeout=max(120, length * 2)))
        if result.get("sample_count") != end - start or result.get("sample_rate") != 16000:
            raise ValueError("離線說話者 bridge 的 PCM 樣本時鐘與輸入不一致。")
        save(directory / f"diarization-{index:03}.json", result)
        for segment in result["segments"]:
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
        file.write('{"stage": "start", "status": "running", "warnings": [], "available_outputs": [], "retry_stage": null}\n')


def prepare(sources, directory, ffmpeg, ffprobe):
    """Decode every source, concatenate in order, write canonical.wav and sources.json; returns (records, PCM bytes)."""
    parts = []
    for index, source in enumerate(sources):
        progress(f"解碼 {index + 1}/{len(sources)} 為單聲道 16 kHz PCM…")
        parts.append(decode_source(source, index, directory, ffmpeg, ffprobe))
    source_records, pcm_bytes = combine(parts)
    del parts
    with wave.open(str(directory / "canonical.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm_bytes)
    with wave.open(str(directory / "canonical.wav"), "rb") as audio:
        if audio.getnframes() != sum(record["sample_count"] for record in source_records):
            raise ValueError("canonical.wav 樣本數不等於各檔之和。")
    save(directory / "sources.json", source_records)
    return source_records, pcm_bytes


def transcribe_sources(transcriber, samples, source_records, model_path, directory, state):
    """Recognize canonical PCM source slices; only validated local chunks enter the global clock."""
    counts = [source["sample_count"] for source in source_records]
    if any(type(count) is not int or count <= 0 for count in counts) or sum(counts) != len(samples):
        raise ValueError("ASR 來源樣本邊界與 canonical PCM 不符。")
    chunks, texts, languages = [], [], []
    cursor = 0
    for index, count in enumerate(counts):
        progress(f"Qwen 正在辨識來源 {index + 1}/{len(counts)}；每個來源完成後會保留原始 ASR。")
        source_progress = []

        def on_progress(item):
            if item.get("event") == "chunk_completed":
                save(directory / "asr-progress.json", {**item, "source_index": index})
                if isinstance(item.get("text"), str):
                    source_progress.append(item["text"])
                    runtime.raw_text(directory, texts + source_progress)
                    save(directory / "state.json", state)

        result = transcriber(audio=(samples[cursor:cursor + count], 16000), model=str(model_path),
                             return_chunks=True, return_timestamps=False, on_progress=on_progress)
        raw = dataclasses.asdict(result)
        # Preserve the untouched result and text before validation or the next model call.
        save(directory / f"raw-source-{index:03}.json", raw)
        local_chunks = raw.get("chunks") or []
        texts.append(raw.get("text") or "".join(chunk.get("text", "") for chunk in local_chunks))
        runtime.raw_text(directory, texts)
        save(directory / "state.json", state)
        length, offset = count / 16000, cursor / 16000
        check_chunks(local_chunks, length)
        for chunk in local_chunks:
            end = chunk["end"]
            # The backend adds two sample-derived durations. Restore only the same
            # PCM endpoint within their division/addition roundoff, not an audio tolerance.
            if (end > length and end - length <= 2 * math.ulp(length)
                    and round(end * 16000) == count):
                end = length
            if chunk["start"] < 0 or end > length:
                raise ValueError("ASR chunk 超出來源 PCM 範圍。")
            chunks.append({**chunk, "start": offset + chunk["start"], "end": offset + end,
                           "chunk_index": len(chunks)})
        languages.append(raw.get("language"))
        cursor += count
    return {"text": "\n".join(text for text in texts if text), "chunks": chunks,
            "language": languages[0] if all(language == languages[0] for language in languages) else None,
            "segments": None, "speaker_segments": None,
            "finish_reason": "repetition" if any(chunk["finish_reason"] == "repetition" for chunk in chunks) else "eos",
            "truncated": False}


def transcribe(arguments):
    directory, home = Path(arguments.run_directory).resolve(), Path.home()
    sources = [Path(path).resolve() for path in arguments.audio]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise RuntimeError("找不到本機音檔：" + "、".join(missing))
    model_id = "Qwen/Qwen3-ASR-" + arguments.model
    config = {"backend": "mlx-qwen3-asr", "model": model_id, "aligner": "Qwen/Qwen3-ForcedAligner-0.6B",
              "sample_rate": 16000, "diarization_window_seconds": 1200, "return_chunks": True}
    if len(sources) > 1:
        config["asr_partition"] = "source-v1"
    state = {"stage": "decode", "status": "running", "model": model_id, "backend": "mlx-qwen3-asr",
             "network": "Hugging Face offline (HF_HUB_OFFLINE=1)", "warnings": []}
    save(directory / "state.json", state)
    prior, stages = {}, []
    if getattr(arguments, "resume_from", None):
        source_records, pcm_bytes, prior, old_state = runtime.resume(arguments.resume_from, directory, sources, config)
        stages = prior["stages"]
        state.update(resumed_from=str(Path(arguments.resume_from).resolve()),
                     modelRevision=old_state.get("modelRevision"), backendVersion=old_state.get("backendVersion"))
        if BOUNDARY_WARNING in old_state.get("warnings", []):
            state["warnings"].append(BOUNDARY_WARNING)
    else:
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("缺少已安裝 ffmpeg／ffprobe。")
        source_records, pcm_bytes = prepare(sources, directory, ffmpeg, ffprobe)
        runtime.checkpoint(directory, config, source_records, "decode", ["canonical.wav", "sources.json"])
    duration = len(pcm_bytes) / 32000
    if "asr" in stages:
        raw = json.loads((directory / "raw.json").read_text(encoding="utf-8"))
        progress("重用已驗證的原始 ASR，不重新辨識。")
    else:
        state["stage"] = "asr"
        save(directory / "state.json", state)
        model_path = snapshot(model_id)
        state.update(modelRevision=model_path.name, backendVersion=importlib.metadata.version("mlx-qwen3-asr"))
        save(directory / "state.json", state)
        import numpy as np
        from mlx_qwen3_asr import transcribe as qwen_transcribe
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if len(sources) > 1:
            raw = transcribe_sources(qwen_transcribe, samples, source_records, model_path, directory, state)
        else:
            progress("Qwen 正在辨識；全部處理完成後會先保留原始 ASR。")
            def on_progress(item):
                if item.get("event") == "chunk_completed":
                    progress(f"ASR {item.get('chunk_index')}/{item.get('total_chunks')}")
                    save(directory / "asr-progress.json", item)
                    # A progress event is not a complete/resumable ASR checkpoint.
                    if isinstance(item.get("text"), str):
                        progress_text.append(item["text"])
                        runtime.raw_text(directory, progress_text)
                        save(directory / "state.json", state)
            progress_text = []
            result = qwen_transcribe(audio=(samples, 16000), model=str(model_path), return_chunks=True,
                                     return_timestamps=False, on_progress=on_progress)
            raw = dataclasses.asdict(result)
        save(directory / "raw.json", raw)
        runtime.raw_text(directory, [raw.get("text") or "".join(c.get("text", "") for c in raw.get("chunks", []))])
    chunks, warnings = raw.get("chunks") or [], state["warnings"]
    runtime.raw_text(directory, [raw.get("text") or "".join(c.get("text", "") for c in chunks)])
    normalized = {"schema_version": 1, "sources": source_records, "pcm": "canonical.wav",
                  "model": {"id": model_id, "size": arguments.model, "revision": state.get("modelRevision")},
                  "chunks": [{**chunk, "words": [], "complete": False} for chunk in chunks],
                  "turns": [], "diarization_complete": False, "speakers": {}}
    save(directory / "normalized-run.json", normalized)
    alignment_complete = False
    retry_stage = "asr"
    try:
        check_chunks(chunks, duration)
        raw_files = ["raw.json"]
        if len(sources) > 1:
            raw_files.extend(f"raw-source-{index:03}.json" for index in range(len(source_records)))
        runtime.checkpoint(directory, config, source_records, "asr", raw_files)
        if any(chunk.get("finish_reason") == "repetition" for chunk in chunks):
            warnings.append("ASR 曾以重複偵測停止；請人工檢查該段文字。")
        state["stage"] = retry_stage = "alignment"
        save(directory / "state.json", state)
        alignment_files = ["alignment.json", "alignment-model.json"]
        if "alignment" in stages:
            normalized["chunks"] = json.loads((directory / "alignment.json").read_text(encoding="utf-8"))
            normalized["alignment_model"] = json.loads((directory / "alignment-model.json").read_text(encoding="utf-8"))
            alignment_files.extend(name for name in prior["artifacts"]
                                   if name.startswith("alignment-raw-") or name == "alignment-boundary-report.json")
            if "alignment-boundary-report.json" in alignment_files:
                report = json.loads((directory / "alignment-boundary-report.json").read_text(encoding="utf-8"))
                if any(item["adjustments"] for item in report["chunks"]):
                    # Earlier adapter output may have passed the canonical
                    # rounding tolerance despite an inversion created by clipping.
                    if any(right["end"] < left["end"] for chunk in normalized["chunks"]
                           for left, right in zip(chunk["words"], chunk["words"][1:])):
                        raise ValueError("已保存的時間格調整含詞尾逆序，不能重用此對齊結果。")
                    if BOUNDARY_WARNING not in warnings:
                        warnings.append(BOUNDARY_WARNING)
        else:
            import numpy as np
            from mlx_qwen3_asr import ForcedAligner
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            aligner_path = snapshot(config["aligner"])
            normalized["alignment_model"] = {"id": config["aligner"], "revision": aligner_path.name}
            aligner = ForcedAligner(model_path=str(aligner_path), backend="mlx")
            normalized["chunks"] = []
            boundary_report = {"version": 1, "policy": "terminal-model-bin-v1", "chunks": []}
            alignment_files.append("alignment-boundary-report.json")
            for index, chunk in enumerate(chunks):
                progress(f"逐詞對齊 {index + 1}/{len(chunks)}")
                start, end = round(chunk["start"] * 16000), round(chunk["end"] * 16000)
                aligned = aligner.align(samples[start:end], chunk["text"], chunk.get("language") or raw.get("language") or "Chinese") if chunk["text"].strip() else []
                # The selected MLX backend reads this millisecond value from its model config.
                model_config = getattr(getattr(aligner, "_backend", None), "config", None)
                quantum_ms = getattr(model_config, "timestamp_segment_time", None)
                quantum = (quantum_ms / 1000 if type(quantum_ms) in (int, float)
                           and math.isfinite(quantum_ms) and quantum_ms > 0 else None)
                evidence = {"chunk_index": index, "sample_start": start, "sample_count": len(samples[start:end]),
                            "sample_rate": 16000, "chunk_start": chunk["start"], "chunk_end": chunk["end"],
                            "quantum_seconds": quantum}
                raw_name = f"alignment-raw-{index:04}.json"
                # Raw-only JSON permits NaN/Infinity to retain invalid provider evidence;
                # normalized output still rejects them, and never seals an alignment checkpoint.
                save(directory / raw_name, {**evidence, "words": [dataclasses.asdict(word)
                     if dataclasses.is_dataclass(word) else vars(word) for word in aligned]}, allow_nan=True)
                alignment_files.append(raw_name)
                local_words, adjustments = runtime.bound_alignment_terminal_bin(
                    [{"text": word.text, "start": word.start_time, "end": word.end_time} for word in aligned],
                    sample_count=evidence["sample_count"], sample_rate=16000, quantum_seconds=quantum)
                boundary_report["chunks"].append({**evidence, "adjustments": adjustments})
                save(directory / "alignment-boundary-report.json", boundary_report)
                if adjustments and BOUNDARY_WARNING not in warnings:
                    warnings.append(BOUNDARY_WARNING)
                save(directory / "state.json", state)
                words = [{**word, "start": word["start"] + chunk["start"],
                          "end": word["end"] + chunk["start"]} for word in local_words]
                # Validate JSON numeric representability before publishing this chunk.
                json.dumps(words, allow_nan=False)
                normalized["chunks"].append({**chunk, "words": words, "complete": True})
                save(directory / "alignment.json", normalized["chunks"])
            save(directory / "alignment-model.json", normalized["alignment_model"])
        save(directory / "normalized-run.json", normalized)
        read_helper().validate(directory / "normalized-run.json", require_speakers=False)
        runtime.checkpoint(directory, config, source_records, "alignment", alignment_files)
        alignment_complete = True
        save(directory / "normalized-run.json", normalized)
        state["stage"] = retry_stage = "diarization"
        save(directory / "state.json", state)
        normalized["turns"], normalized["diarization_model"] = diarize(pcm_bytes, directory, home, duration, state)
        normalized["speakers"] = {item["speaker"]: {} for item in normalized["turns"]}
        normalized["diarization_complete"] = True
        save(directory / "speaker-turns.json", normalized["turns"])
        if duration > 1200:
            warnings.append("長錄音的每個 20 分鐘視窗使用獨立說話者 ID，未跨窗推定身分。")
    except Exception as error:
        warnings.append(f"{state['stage']} 未完成：{error}")
    save(directory / "normalized-run.json", normalized)
    is_complete = False
    if alignment_complete:
        try:
            _, report = read_helper().validate(directory / "normalized-run.json", require_speakers=normalized["diarization_complete"])
            save(directory / "validation.json", report)
            is_complete = normalized["diarization_complete"] and not any(chunk.get("finish_reason") == "repetition" for chunk in chunks)
            if normalized["diarization_complete"] and not is_complete:
                retry_stage = None  # Repetition requires human review, not an automatic ASR retry.
        except Exception as error:
            warnings.append(f"時間／文字驗證未通過：{error}")
            retry_stage = "validation"
    state.update(stage="complete" if is_complete else "partial", status="complete" if is_complete else "partial",
                 retry_stage=None if is_complete else retry_stage, warnings=warnings)
    save(directory / "state.json", state)
    progress("轉錄完成。" if is_complete else "原始文字已保存；部分階段待補完，請查看 state.json 警示。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, action="append", help="repeat to merge recordings in this order")
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--model", required=True, choices=["0.6B", "1.7B"])
    parser.add_argument("--resume-from", help="validated checkpoint in a previous run; output must be new")
    args = parser.parse_args()
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[key] = "1"
    signal.signal(signal.SIGTERM, interrupt)
    directory = Path(args.run_directory).resolve()
    try:
        runtime.check_location(args.resume_from, directory)
        claim(directory)
    except (OSError, ValueError) as error:
        print(str(error) if isinstance(error, FileExistsError) else f"無法建立轉錄目錄：{error}", file=sys.stderr, flush=True)
        return 1
    try:
        transcribe(args)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        state_path = directory / "state.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        cancelled = isinstance(error, KeyboardInterrupt)
        message = "使用者已取消；已完成的原始輸出仍保留。" if cancelled else str(error)
        runtime.finish_error(directory, state, error)
        print(message, file=sys.stderr, flush=True)
        return 130 if cancelled else 1


if __name__ == "__main__":
    sys.exit(main())

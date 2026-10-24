#!/usr/bin/env python3
"""Gemini 3.5 Transcribe adapter: uploads canonical PCM parts to Google, writes the same normalized-run.json as the worker."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

API = "https://generativelanguage.googleapis.com"
MODEL = "gemini-3.5-transcribe"
PART_SAMPLES = 25 * 60 * 16000  # Diarization and word timestamps stop at 30 minutes per request.
KEYCHAIN = ["security", "find-generic-password", "-s", "kerf-wordprint-gemini", "-a", "wordprint", "-w"]


def load(name):
    spec = importlib.util.spec_from_file_location("wordprint_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker, transcript = load("qwen_worker"), load("transcript")


def api_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        try:
            found = subprocess.run(KEYCHAIN, capture_output=True, text=True)
            key = found.stdout.strip() if found.returncode == 0 else ""
        except OSError:  # No macOS `security`: only GEMINI_API_KEY works.
            pass
    if not key:
        raise SystemExit("找不到 Gemini API 金鑰。請在終端機自己執行（會提示輸入金鑰，不會留在指令紀錄）：\n"
                         "security add-generic-password -s kerf-wordprint-gemini -a wordprint -w")
    return key


def call(url, key, method="GET", body=None, headers=None, timeout=120, raw=False):
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"x-goog-api-key": key, "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response if raw else json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:  # Body is Google's error JSON; headers (with the key) are never printed.
        raise RuntimeError(f"Gemini API {error.code}：{error.read().decode(errors='replace')[:500]}".replace(key, "***")) from None


def wait(url, key, done, seconds=3600):
    for _ in range(seconds // 5):
        value = call(url, key)
        if done(value):
            return value
        time.sleep(5)
    raise RuntimeError(f"等待 Gemini 超過 {seconds} 秒：{url}")


def transcribe_part(path, key, state):
    """Files API resumable upload, then one interaction. Each Google resource is saved to state.json (beside the part) as soon
    as it exists and deleted on the way out, even on failure; a failed DELETE keeps its name plus a warning."""
    names, created = state["google_resources"], []
    save = lambda: worker.save(path.with_name("state.json"), state)
    try:
        size = path.stat().st_size
        upload_url = call(API + "/upload/v1beta/files", key, "POST", {"file": {"display_name": path.name}}, raw=True, headers={
            "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size), "X-Goog-Upload-Header-Content-Type": "audio/wav"}).headers["X-Goog-Upload-URL"]
        file = call(upload_url, key, "POST", path.read_bytes(), timeout=900,
                    headers={"Content-Length": str(size), "Content-Type": "audio/wav", "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"})["file"]
        names.append(file["name"]), created.append(file["name"]), save()
        if file.get("state") != "ACTIVE":
            file = wait(f"{API}/v1beta/{file['name']}", key, lambda f: f.get("state") in ("ACTIVE", "FAILED"))
            if file["state"] != "ACTIVE":
                raise RuntimeError(f"Gemini 檔案處理失敗：{file.get('error')}")
        interaction = call(API + "/v1beta/interactions", key, "POST", timeout=1800, body={
            "model": MODEL, "input": [{"type": "audio", "uri": file["uri"], "mime_type": "audio/wav"}],
            "generation_config": {"transcription_config": {"mode": {
                "type": "verbatim", "diarization_mode": "speaker", "timestamp_granularities": ["word"]}}}})
        if interaction.get("id"):
            name = "interactions/" + interaction["id"].removeprefix("interactions/")
            names.append(name), created.append(name), save()
        if interaction.get("status") in ("in_progress", "queued"):
            interaction = wait(f"{API}/v1beta/{names[-1]}", key, lambda i: i.get("status") not in ("in_progress", "queued"))
        worker.save(path.with_suffix(".json"), interaction)
        worker.runtime.raw_text(path.parent, response_texts(path.parent))
        save()
        return interaction
    finally:
        for name in list(created):
            try:  # Google keeps uploads 48 h and stored interactions up to 55 days unless deleted.
                call(f"{API}/v1beta/{name}", key, "DELETE")
                names.remove(name)
            except Exception as error:
                state["warnings"].append(f"無法刪除 Google 端的 {name}：{error}")
        save()


def convert(interactions, bounds):
    """Raw interactions + each part's (start, end) seconds → chunks, turns, speakers, flags, warnings; text stays output_text."""
    chunks, turns, warnings, trusted, normalize = [], [], [], True, transcript.normalized
    for number, (interaction, (start, end)) in enumerate(zip(interactions, bounds), 1):
        status = interaction.get("status")
        contents = [c for step in interaction.get("steps", []) if step.get("type") == "model_output"
                    for c in step.get("content", []) if c.get("type") == "text"]
        words, pending = [], ""
        for item in (a for c in contents for a in c.get("annotations", []) if a.get("type") == "word_info"):
            token = item.get("text", "")
            if not normalize(token):  # Punctuation-only token joins an adjacent word.
                if words:
                    words[-1]["text"] += token
                else:
                    pending += token
                continue
            words.append({"text": pending + token, "start": start + float(item["start_offset"].removesuffix("s")),
                          "end": start + float(item["end_offset"].removesuffix("s")), "speaker": item.get("speaker")})
            pending = ""
        text = "".join(c.get("text", "") for c in contents)
        if (normalize(text) != normalize("".join(w["text"] for w in words))
                or any(w["end"] > end + transcript.EPS for w in words)):
            trusted = False
            warnings.append(f"第 {number} 段 output_text 與逐詞不一致或逐詞時間超出該段；原樣保留，結果標為部分完成。")
        for word in words:
            if not word["speaker"]:
                trusted = False
                continue
            speaker = word["speaker"] if len(bounds) == 1 else f"part-{number}-{word['speaker']}"
            if turns and turns[-1]["speaker"] == speaker:  # Part-prefixed IDs never merge across parts.
                turns[-1]["end"] = max(turns[-1]["end"], word["end"])
            else:
                turns.append({"start": word["start"], "end": word["end"], "speaker": speaker})
        chunks.append({"start": start, "end": end, "text": text, "status": status,
                       "words": [{k: w[k] for k in ("text", "start", "end")} for w in words],
                       "complete": status in ("completed", "incomplete"), "truncated": status != "completed"})
    kept = [t for t in turns if t["end"] > t["start"]]
    if len(kept) < len(turns):
        warnings.append(f"{len(turns) - len(kept)} 個零長度說話者片段未列入 turns。")
    order = {}  # One part: S1, S2… in first-speech order; several parts keep part-N-spk_M apart, like the worker's windows.
    for turn in kept if len(bounds) == 1 else []:
        turn["speaker"] = order.setdefault(turn["speaker"], f"S{len(order) + 1}")
    complete = all(c["complete"] and not c["truncated"] for c in chunks)
    return {"chunks": chunks, "turns": kept, "speakers": {t["speaker"]: {} for t in kept},
            "diarization_complete": complete and trusted, "warnings": warnings}


def response_texts(directory):
    return [content.get("text", "") for path in sorted(directory.glob("part-*.json"))
            for step in json.loads(path.read_text(encoding="utf-8")).get("steps", []) if step.get("type") == "model_output"
            for content in step.get("content", []) if content.get("type") == "text"]


def reusable(interaction, duration):
    if interaction.get("status") != "completed":
        return False
    converted = convert([interaction], [(0, duration)])
    return converted["diarization_complete"] and all(
        all(math.isfinite(w[k]) for k in ("start", "end")) and 0 <= w["start"] <= w["end"] <= duration + transcript.EPS
        for c in converted["chunks"] for w in c["words"])


def transcribe(arguments, key):
    directory = Path(arguments.run_directory).resolve()
    sources = [Path(path).resolve() for path in arguments.audio]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise RuntimeError("找不到本機音檔：" + "、".join(missing))
    config = {"backend": "Gemini Interactions API v1beta", "model": MODEL, "part_samples": PART_SAMPLES,
              "mode": "verbatim", "diarization": "speaker", "timestamps": "word", "sample_rate": 16000}
    state = {"stage": "decode", "status": "running", "engine": MODEL, "model": MODEL,
             "network": "uploaded to Google Gemini API",
             "upload": "canonical 16 kHz WAV parts of ≤25 min via Files API; files and interactions deleted after transcription",
             "google_resources": [], "part_requests": {}, "warnings": []}
    worker.save(directory / "state.json", state)
    stages = []
    if getattr(arguments, "resume_from", None):
        source_records, pcm_bytes, checkpoint, old_state = worker.runtime.resume(arguments.resume_from, directory, sources, config)
        stages = checkpoint["stages"]
        state.update(resumed_from=str(Path(arguments.resume_from).resolve()), google_resources=old_state.get("google_resources", []),
                     part_requests=dict(old_state.get("part_requests", {})))
        if state["google_resources"]:
            state["warnings"].append("舊 run 仍有 Google 資源未刪除；名稱保留於 google_resources，續跑不會自動刪除舊資源。")
    else:
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("缺少已安裝 ffmpeg／ffprobe。")
        source_records, pcm_bytes = worker.prepare(sources, directory, ffmpeg, ffprobe)
        worker.runtime.checkpoint(directory, config, source_records, "decode", ["canonical.wav", "sources.json"])
    count = len(pcm_bytes) // 2
    bounds, interactions = [(a / 16000, min(a + PART_SAMPLES, count) / 16000) for a in range(0, count, PART_SAMPLES)], []
    state["stage"] = "gemini"
    worker.save(directory / "state.json", state)
    worker.runtime.raw_text(directory, response_texts(directory))
    # An attempted request without an intact completed response is ambiguous and must never be resent automatically.
    for number in state["part_requests"]:
        if f"part-{int(number):03}" not in stages:
            raise RuntimeError(f"第 {number} 段曾送出請求但沒有可重用的完成回應；停止自動重送，請先核對舊 run。")
    for number, (start, end) in enumerate(bounds, 1):
        label = f"part-{number:03}"
        part = directory / (label + ".wav")
        if label in stages:
            interaction = json.loads((directory / (label + ".json")).read_text(encoding="utf-8"))
            if not reusable(interaction, end - start):
                raise ValueError(f"第 {number} 段 checkpoint 回應未通過驗證；不會自動重新呼叫 Google。")
            interactions.append(interaction)
            worker.progress(f"重用第 {number}/{len(bounds)} 段完成回應。")
        else:
            worker.runtime.write_pcm(part, pcm_bytes[round(start * 16000) * 2:round(end * 16000) * 2])
            state["part_requests"][str(number)] = "started"
            worker.save(directory / "state.json", state)
            worker.progress(f"上傳並轉錄第 {number}/{len(bounds)} 段（Google Gemini）…")
            interactions.append(transcribe_part(part, key, state))
            worker.save(directory / (label + ".json"), interactions[-1])
            worker.runtime.raw_text(directory, response_texts(directory))
            if reusable(interactions[-1], end - start):
                worker.runtime.checkpoint(directory, config, source_records, label, [label + ".json"])
                state["part_requests"][str(number)] = "completed"
            else:
                state["part_requests"][str(number)] = "unusable"
            part.unlink()
        worker.runtime.raw_text(directory, response_texts(directory))
        partial = convert(interactions, bounds)
        partial.pop("warnings")
        partial["diarization_complete"] = partial["diarization_complete"] and len(interactions) == len(bounds)
        worker.save(directory / "normalized-run.json", {"schema_version": 1, "sources": source_records, "pcm": "canonical.wav",
                    "model": {"id": MODEL, "size": None, "backend": config["backend"]}, **partial})
        worker.save(directory / "state.json", state)
    converted = convert(interactions, bounds)
    state["warnings"] += converted.pop("warnings")
    normalized = {"schema_version": 1, "sources": source_records, "pcm": "canonical.wav",
                  "model": {"id": MODEL, "size": None, "backend": "Gemini Interactions API v1beta"}, **converted}
    worker.save(directory / "normalized-run.json", normalized)
    is_complete = False
    if normalized["diarization_complete"]:
        try:
            worker.save(directory / "validation.json", transcript.validate(directory / "normalized-run.json")[1])
            is_complete = True
        except Exception as error:
            state["warnings"].append(f"時間／文字驗證未通過：{error}")
    else:
        state["warnings"].append("Gemini 結果未完成或不一致（狀態、說話者、逐詞或時間）；請看 part-*.json。")
    state.update(stage="complete" if is_complete else "partial", status="complete" if is_complete else "partial", retry_stage=None)
    worker.save(directory / "state.json", state)
    worker.progress("轉錄完成。" if is_complete else "原始結果已保存；部分階段未完成，請查看 state.json 警示。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, action="append", help="repeat to merge recordings in this order")
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--resume-from", help="reuse verified completed parts; ambiguous requests are never resent")
    parser.add_argument("--model", choices=["0.6B", "1.7B", MODEL], help="compatibility hint; Gemini always uses gemini-3.5-transcribe")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, worker.interrupt)  # A killed run still deletes its Google files in finally.
    key = api_key()  # Before claim(), so a missing key leaves no run directory behind.
    directory = Path(args.run_directory).resolve()
    try:
        worker.runtime.check_location(args.resume_from, directory)
        worker.claim(directory)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    try:
        transcribe(args, key)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        state = json.loads((directory / "state.json").read_text())
        worker.runtime.finish_error(directory, state, error)
        print(str(error), file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    sys.exit(main())

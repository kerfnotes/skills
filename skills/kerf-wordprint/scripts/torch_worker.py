#!/usr/bin/env python3
"""PyTorch worker for machines without the MLX worker (Windows, Linux, Intel Mac) and for the Colab notebook.

Qwen3-ASR + ForcedAligner via qwen-asr, speakers via NVIDIA Nemotron-3-Diarization through NeMo (no Hugging Face
token). Writes one normalized-run.json (references/run-format.md). The Colab notebook embeds this file verbatim
(tests/test_notebook.py keeps them in sync). Runs in its own process so the qwen-asr pin on transformers never meets
another version already loaded in a notebook session.
"""
import argparse
import importlib.metadata
import importlib.util
import json
import subprocess
import signal
import shutil
import sys
import unicodedata
import wave
from pathlib import Path

_runtime_spec = importlib.util.spec_from_file_location("wordprint_runtime", Path(__file__).with_name("worker_runtime.py"))
runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(runtime)

_transcript_spec = importlib.util.spec_from_file_location("wordprint_transcript", Path(__file__).with_name("transcript.py"))
transcript = importlib.util.module_from_spec(_transcript_spec)
_transcript_spec.loader.exec_module(transcript)


ALIGNER = "Qwen/Qwen3-ForcedAligner-0.6B"
DIARIZER = "nvidia/Nemotron-3-Diarization"  # OpenMDW-1.1, not gated; up to 8 speakers.


def decode(name):
    """原始音檔 → 單聲道 16 kHz s16 PCM 位元組。"""
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", name, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                          check=True, capture_output=True).stdout


def gap(text):
    """對時器略過的空白、標點、符號原樣併入鄰詞（時間不變）；略過真的字則不併入、不借鄰詞時間，讓 validate 擋下。"""
    if any(not c.isspace() and unicodedata.category(c)[0] not in "PS" for c in text):  # transcript.py normalized，另略符號
        print(f"警告：對時漏掉「{text}」；這份結果驗證不會通過", flush=True)
        return ""
    return text


def transcribe(asr, names, model, max_new_tokens, platform, dtype, directory=None):
    """逐來源 ASR／對時，保留來源邊界；qwen-asr 自行切分來源內的長音訊。"""
    import numpy as np
    pcm, sources = b"", []
    for name in names:
        before = runtime.digest(name)
        data = decode(name)
        after = runtime.digest(name)
        if before != after:
            raise ValueError(f"來源音檔在解碼期間被更動：{name}")
        if not data or len(data) % 2:
            raise ValueError("PCM 解碼不完整或沒有音訊。")
        sources.append({"path": str(Path(name).resolve()), "sha256": before, "duration": len(data) / 32000,
                        "offset": len(pcm) / 32000, "sample_count": len(data) // 2, "sample_rate": 16000})
        pcm += data
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    if directory:
        runtime.write_pcm(directory / "canonical.wav", pcm)
        runtime.save(directory / "sources.json", sources)
    run = {"schema_version": 1, "sources": sources, "platform": platform,
           "model": {"id": model, "size": model.rsplit("-", 1)[1], "backend": "qwen-asr " + importlib.metadata.version("qwen-asr"),
                     "language": None, "dtype": str(dtype), "max_new_tokens": max_new_tokens},
           "alignment_model": {"id": ALIGNER},
           "chunks": [{"start": source["offset"], "end": source["offset"] + source["duration"],
                       "text": "", "words": [], "complete": False, "truncated": False, "generated_tokens": []}
                      for source in sources],
           "turns": [], "diarization_complete": False, "speakers": {}}
    generated = []  # 每來源獨立記錄生成長度；碰到上限仍標 truncated，不推測停止原因。
    original = asr.model.generate

    def generate(*args, **kwargs):
        output = original(*args, **kwargs)
        generated.append(output.sequences.shape[1] - kwargs["input_ids"].shape[1])
        return output

    asr.model.generate = generate
    try:
        sample_start = 0
        for index, (source, chunk) in enumerate(zip(sources, run["chunks"])):
            generated.clear()
            sample_end = sample_start + source["sample_count"]
            try:
                result = asr.transcribe((samples[sample_start:sample_end], 16000), return_time_stamps=True)[0]
                chunk["text"] = result.text
                if index == 0:
                    run["model"]["language"] = result.language
                if directory:
                    # Preserve provider text before alignment processing or the next source can fail.
                    runtime.raw_text(directory, [part["text"] for part in run["chunks"]])
                words, cursor = [], 0
                for item in result.time_stamps or []:
                    word = {"text": item.text, "start": source["offset"] + item.start_time,
                            "end": source["offset"] + item.end_time}
                    found = result.text.find(item.text, cursor)
                    if found >= 0:
                        word["text"] = gap(result.text[cursor:found]) + item.text
                        cursor = found + len(item.text)
                    # 不符時保留原樣，讓 validate 如實擋下；不借用另一來源的字或時間。
                    words.append(word)
                if words:
                    words[-1]["text"] += gap(result.text[cursor:])
                chunk.update(words=words, complete=True)
            finally:
                chunk.update(truncated=max(generated, default=0) >= max_new_tokens, generated_tokens=list(generated))
                if directory:
                    # Pending sources remain complete=False; this is never an ASR checkpoint by itself.
                    runtime.save(directory / "asr-run.json", run)
            sample_start = sample_end
    finally:
        asr.model.generate = original
    return run, samples, pcm


def diarize(run, samples, device):
    """Nemotron 一次處理整段（內部串流切塊），說話者依首次發言編成 S1、S2…；失敗時保留無說話者的結果並說明原因。"""
    import torch
    try:
        from nemo.collections.asr.models import SortformerEncLabelModel
        from nemo.collections.asr.modules import transformer_encoder_utils
        from torch.nn.attention.flex_attention import flex_attention
        # ponytail: NeMo compiles flex_attention on CUDA, and Triton needs more shared memory than a T4 has; eager is
        # slower but diarization is small next to ASR. Restore the compiled kernel if big GPUs ever need the speed.
        transformer_encoder_utils._flex_attention_compiled = flex_attention
        model = SortformerEncLabelModel.from_pretrained(DIARIZER, map_location=device).to(torch.float32).eval()
        modules = model.sortformer_modules  # 模型卡的離線設定
        modules.chunk_len, modules.chunk_right_context, modules.fifo_len, modules.spkcache_update_period = 340, 40, 40, 300
        model._check_streaming_parameters()
        segments = model.diarize(audio=[samples], batch_size=1, sample_rate=16000)[0]
    except Exception as error:
        print(f"這次不分說話者（{type(error).__name__}：{error}）。", flush=True)
        run.setdefault("warnings", []).append(f"diarization 未完成：{type(error).__name__}：{error}")
        return
    order, duration, turns = {}, len(samples) / 16000, []
    for segment in sorted(segments, key=lambda s: float(s.split()[0])):
        start, end, label = segment.split()
        start, end = float(start), min(float(end), duration)
        if end > start:
            turns.append({"start": start, "end": end, "speaker": order.setdefault(label, f"S{len(order) + 1}")})
    run.update(turns=turns, speakers={speaker: {} for speaker in order.values()}, diarization_complete=True,
               diarization_model={"id": DIARIZER, "backend": "nemo-toolkit " + importlib.metadata.version("nemo-toolkit")})


def interrupt(_signum, _frame):
    raise KeyboardInterrupt


def validation_error(path, require_speakers=False):
    """Use the delivery validator for both checkpoint admission and completion."""
    try:
        transcript.validate(path, require_speakers=require_speakers)
    except (ValueError, OSError) as error:
        return str(error)
    return None


def execute(args, directory):
    directory = Path(directory).resolve()
    state = {"stage": "asr", "status": "running", "warnings": [], "network": "model libraries may fetch missing models"}
    runtime.state(directory, state)
    import torch
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if args.fallback and device == "cpu" and args.model == "1.7B":
        args.model = "0.6B"
        print("沒有分配到 GPU：改用 0.6B（CPU 上 1.7B 太慢）；要 1.7B 請換成 GPU 執行階段後重跑。", flush=True)
    model, dtype = f"Qwen/Qwen3-ASR-{args.model}", torch.float16 if device != "cpu" else torch.float32
    config = {"backend": "qwen-asr", "model": model, "aligner": ALIGNER, "diarizer": DIARIZER,
              "max_new_tokens": args.max_new_tokens, "dtype": str(dtype), "sample_rate": 16000}
    if len(args.audio) > 1:
        config["asr_partition"] = "source-v1"
    state["model"] = model
    runtime.state(directory, state)
    if args.resume_from:
        sources, pcm, checkpoint, old_state = runtime.resume(args.resume_from, directory, args.audio, config)
        if "asr" not in checkpoint["stages"]:
            raise ValueError("PyTorch checkpoint 尚未完成 ASR／對齊，無法只續跑說話者。")
        run = json.loads((directory / "asr-run.json").read_text(encoding="utf-8"))
        run["sources"] = sources
        import numpy as np
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        state["resumed_from"] = str(Path(args.resume_from).resolve())
        print("重用既有 ASR／對齊，重新驗證後續跑說話者分析。", flush=True)
    else:
        from qwen_asr import Qwen3ASRModel
        asr = Qwen3ASRModel.from_pretrained(model, dtype=dtype, device_map=device, max_new_tokens=args.max_new_tokens,
                                            forced_aligner=ALIGNER, forced_aligner_kwargs={"dtype": dtype, "device_map": device})
        print("轉錄中…", flush=True)
        run, samples, pcm = transcribe(asr, args.audio, model, args.max_new_tokens, f"{args.platform} {device}", dtype, directory)
        run["pcm"] = str(directory / "canonical.wav")
        runtime.save(directory / "asr-run.json", run)
        runtime.checkpoint(directory, config, run["sources"], "decode", ["canonical.wav", "sources.json"])
        if validation_error(directory / "asr-run.json") is None:
            runtime.checkpoint(directory, config, run["sources"], "asr", ["asr-run.json"])
        del asr
    runtime.raw_text(directory, [chunk["text"] for chunk in run["chunks"]])
    run["pcm"] = str(directory / "canonical.wav")
    if args.pcm and Path(args.pcm).resolve() != directory / "canonical.wav":
        shutil.copyfile(directory / "canonical.wav", args.pcm)
        run["pcm"] = str(Path(args.pcm).resolve())
    # Publish the ASR result before any diarization work or cancellation.
    runtime.save(directory / "normalized-run.json", run)
    if Path(args.out).resolve() != directory / "normalized-run.json":
        runtime.save(Path(args.out), run)
    error = validation_error(directory / "normalized-run.json")
    if error is not None:
        state["warnings"].append(f"ASR／對齊驗證未通過：{error}")
        state.update(stage="partial", status="partial", retry_stage="asr")
        runtime.state(directory, state)
        return
    state["stage"] = "diarization"
    runtime.state(directory, state)
    print("分說話者中…", flush=True)
    diarize(run, samples, device)
    runtime.save(directory / "normalized-run.json", run)
    if Path(args.out).resolve() != directory / "normalized-run.json":
        runtime.save(Path(args.out), run)
    state["warnings"].extend(run.get("warnings", []))
    error = validation_error(directory / "normalized-run.json", require_speakers=True)
    complete = error is None
    if error is not None:
        state["warnings"].append(f"完整逐字稿驗證未通過：{error}")
    state.update(stage="complete" if complete else "partial", status="complete" if complete else "partial",
                 retry_stage=None if complete else "diarization")
    runtime.state(directory, state)
    print(args.out, "：", sum(len(chunk["words"]) for chunk in run["chunks"]), "詞，說話者", len(run["speakers"]) or "未標記", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, action="append", help="repeat to merge recordings in this order")
    parser.add_argument("--out", required=True, help="normalized-run.json to write")
    parser.add_argument("--model", default="0.6B", choices=["0.6B", "1.7B"])
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--platform", default=sys.platform)
    parser.add_argument("--pcm", help="also write the canonical 16 kHz WAV here (sets run.pcm)")
    parser.add_argument("--resume-from", help="previous run directory containing an ASR checkpoint")
    parser.add_argument("--cpu-falls-back-to-0.6b", dest="fallback", action="store_true")
    args = parser.parse_args()
    output = Path(args.out).resolve()
    # Historical CLI allows arbitrary filenames in a populated folder (including Colab).
    directory = output.parent if output.name == "normalized-run.json" else output.with_suffix(".run")
    try:
        runtime.check_location(args.resume_from, directory)
        runtime.check_location(args.resume_from, output.parent)
        if args.pcm:
            runtime.check_location(args.resume_from, Path(args.pcm).resolve().parent)
        if output.exists() or (args.pcm and Path(args.pcm).exists()):
            raise FileExistsError("輸出已存在；請使用新的輸出路徑，既有檔案未改動。")
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise FileExistsError("請使用新的或空的轉錄目錄；既有目錄未改動。")
        with (directory / "state.json").open("x", encoding="utf-8") as file:
            json.dump({"stage": "start", "status": "running", "warnings": [], "available_outputs": [], "retry_stage": None}, file)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    signal.signal(signal.SIGTERM, interrupt)
    try:
        execute(args, directory)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        state = json.loads((directory / "state.json").read_text())
        runtime.finish_error(directory, state, error)
        print(str(error), file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PyTorch worker for machines without the MLX worker (Windows, Linux, Intel Mac) and for the Colab notebook.

Qwen3-ASR + ForcedAligner via qwen-asr, speakers via NVIDIA Nemotron-3-Diarization through NeMo (no Hugging Face
token). Writes one normalized-run.json (references/run-format.md). The Colab notebook embeds this file verbatim
(tests/test_notebook.py keeps them in sync). Runs in its own process so the qwen-asr pin on transformers never meets
another version already loaded in a notebook session.
"""
import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import unicodedata
import wave
from pathlib import Path

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


def transcribe(asr, names, model, max_new_tokens, platform, dtype):
    """qwen-asr 自己把長音訊切成 ≤180 秒的段、逐段對時並換算成全段時間；這裡只把結果寫成 normalized run。"""
    import numpy as np
    generated = []  # transcribe() 不回傳停止原因；記下每批實際生成長度，碰到上限就標 truncated
    original = asr.model.generate

    def generate(*args, **kwargs):
        output = original(*args, **kwargs)
        generated.append(output.sequences.shape[1] - kwargs["input_ids"].shape[1])
        return output

    asr.model.generate = generate
    pcm, sources = b"", []
    for name in names:
        data = decode(name)
        sources.append({"path": name, "sha256": hashlib.sha256(Path(name).read_bytes()).hexdigest(), "duration": len(data) / 32000,
                        "offset": len(pcm) / 32000, "sample_count": len(data) // 2, "sample_rate": 16000})
        pcm += data
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    result = asr.transcribe((samples, 16000), return_time_stamps=True)[0]
    words, cursor = [], 0
    for item in result.time_stamps or []:
        found = result.text.find(item.text, cursor)
        if found < 0:  # 對時文字與原文不符：保留原樣，讓 validate 如實擋下
            words.append({"text": item.text, "start": item.start_time, "end": item.end_time})
            continue
        words.append({"text": gap(result.text[cursor:found]) + item.text, "start": item.start_time, "end": item.end_time})
        cursor = found + len(item.text)
    if words:
        words[-1]["text"] += gap(result.text[cursor:])
    duration = len(samples) / 16000
    run = {"schema_version": 1, "sources": sources, "platform": platform,
           "model": {"id": model, "size": model.rsplit("-", 1)[1], "backend": "qwen-asr " + importlib.metadata.version("qwen-asr"),
                     "language": result.language, "dtype": str(dtype), "max_new_tokens": max_new_tokens},
           "alignment_model": {"id": ALIGNER},
           "chunks": [{"start": 0, "end": duration, "text": result.text, "words": words, "complete": True,
                       "truncated": max(generated, default=0) >= max_new_tokens, "generated_tokens": list(generated)}],
           "turns": [], "diarization_complete": False, "speakers": {}}
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
        return
    order, duration, turns = {}, len(samples) / 16000, []
    for segment in sorted(segments, key=lambda s: float(s.split()[0])):
        start, end, label = segment.split()
        start, end = float(start), min(float(end), duration)
        if end > start:
            turns.append({"start": start, "end": end, "speaker": order.setdefault(label, f"S{len(order) + 1}")})
    run.update(turns=turns, speakers={speaker: {} for speaker in order.values()}, diarization_complete=True,
               diarization_model={"id": DIARIZER, "backend": "nemo-toolkit " + importlib.metadata.version("nemo-toolkit")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, action="append", help="repeat to merge recordings in this order")
    parser.add_argument("--out", required=True, help="normalized-run.json to write")
    parser.add_argument("--model", default="0.6B", choices=["0.6B", "1.7B"])
    parser.add_argument("--max-new-tokens", type=int, default=2048, help="per ≤3-minute segment; hitting it marks truncated")
    parser.add_argument("--platform", default=sys.platform)
    parser.add_argument("--pcm", help="also write the canonical 16 kHz WAV here (sets run.pcm)")
    parser.add_argument("--cpu-falls-back-to-0.6b", dest="fallback", action="store_true",
                        help="notebook default: without a GPU run 0.6B instead of 1.7B and say so")
    args = parser.parse_args()
    import torch
    from qwen_asr import Qwen3ASRModel
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    if args.fallback and device == "cpu" and args.model == "1.7B":
        args.model = "0.6B"
        print("沒有分配到 GPU：改用 0.6B（CPU 上 1.7B 太慢）；要 1.7B 請換成 GPU 執行階段後重跑。", flush=True)
    model, dtype = f"Qwen/Qwen3-ASR-{args.model}", torch.float16 if device != "cpu" else torch.float32  # T4 沒有 bf16
    asr = Qwen3ASRModel.from_pretrained(model, dtype=dtype, device_map=device, max_new_tokens=args.max_new_tokens,
                                        forced_aligner=ALIGNER, forced_aligner_kwargs={"dtype": dtype, "device_map": device})
    print("轉錄中…", flush=True)
    run, samples, pcm = transcribe(asr, args.audio, model, args.max_new_tokens, f"{args.platform} {device}", dtype)
    print("分說話者中…", flush=True)
    diarize(run, samples, device)
    if args.pcm:
        with wave.open(args.pcm, "wb") as out:
            out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000), out.writeframes(pcm)
        run["pcm"] = str(Path(args.pcm).resolve())
    Path(args.out).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out, "：", len(run["chunks"][0]["words"]), "詞，說話者", len(run["speakers"]) or "未標記", flush=True)


if __name__ == "__main__":
    main()

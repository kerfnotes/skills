#!/usr/bin/env python3
"""Process-boundary model substitute. Never imports a worker or loads a model."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import wave

args = sys.argv[1:]
if Path(args[0]).name not in ('qwen_worker.py', 'torch_worker.py'):
    os.execv(sys.executable, [sys.executable, *args])
source = Path(args[args.index('--audio') + 1])
directory = (Path(args[args.index('--run-directory') + 1]) if '--run-directory' in args
             else Path(args[args.index('--out') + 1]).parent)
directory.mkdir()
mode = os.environ.get('WORDPRINT_SYNTHETIC_MODE', 'complete')
size = args[args.index('--model') + 1]
with wave.open(str(source)) as wav:
    duration = wav.getnframes() / wav.getframerate()
sentences = [
    (5, '目前不發布新版本。'), (17, '先完成驗證。'),
    (25, '團隊檢視了測試結果，尚未確認正式日期。'),
    (62, '提議下週發布，未通過。'), (123, '核對失敗案例。'),
    (135, '負責人和期限待確認。'),
    (181, '不確定是否完成；重疊發言，不歸屬任何一人。'),
]
if mode == 'long':
    sentences = [(i * duration / 600, '長內容與 English 保留原文。' * 6) for i in range(600)]
chunks, turns = [], []
for i, (start, text) in enumerate(sentences):
    end = sentences[i + 1][0] if i + 1 < len(sentences) else duration
    chunks.append({'start': 0 if i == 0 else start, 'end': end,
                   'text': '' if mode == 'empty' else text, 'complete': True, 'truncated': False,
                   'words': [] if mode == 'empty' else [{'start': start, 'end': min(start + 3, end), 'text': text}]})
    if mode not in ('partial', 'empty'):
        turns.append({'start': start, 'end': min(start + 3, end), 'speaker': 'S1'})
        if start == 181:
            turns.append({'start': start, 'end': min(start + 3, end), 'speaker': 'S2'})
run = {'schema_version': 1, 'model': {'id': 'Qwen/Qwen3-ASR-' + size, 'size': size},
       'sources': [{'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'duration': duration, 'offset': 0}],
       'chunks': chunks, 'turns': turns,
       'speakers': {'S1': {'name': '林先生', 'status': 'possible', 'evidence': '合成測試候選線索'}, 'S2': {}},
       'diarization_complete': mode != 'partial', 'pcm': str(directory / 'canonical.wav')}
shutil.copyfile(source, directory / 'canonical.wav')
(directory / 'normalized-run.json').write_text(json.dumps(run, ensure_ascii=False))
(directory / 'raw-transcript.txt').write_text('\n'.join(c['text'] for c in chunks) + '\n')
status = 'cancelled' if mode == 'cancelled' else 'partial' if mode == 'partial' else 'complete'
(directory / 'state.json').write_text(json.dumps({'stage': status, 'status': status,
    'retry_stage': 'diarization' if mode == 'partial' else None, 'warnings': []}))
if mode == 'cancelled':
    os.kill(os.getppid(), __import__('signal').SIGTERM)

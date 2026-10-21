#!/usr/bin/env python3
"""Check what Wordprint can run on this machine and print the one next step for each missing piece.

Read-only: installs nothing, downloads nothing, never reads secrets. Prints JSON (`--json`) or one line per check:
`ok`, `agent` (a routine install the agent may run) or `you` (needs the user: an account, terms, a permission prompt).
Exit 0 when at least one transcription route is ready, 1 otherwise.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
HUB = Path(os.environ.get('HF_HUB_CACHE') or Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface')) / 'hub')


def run(*command, stdin=None):
    """Exit code 0 and stdout, or (False, '') when the command is missing or hangs."""
    try:
        result = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=20)
        return result.returncode == 0, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ''


def checks():
    mac_arm = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    brew = 'brew install' if shutil.which('brew') else 'install Homebrew (https://brew.sh), then brew install'
    items = [
        ('python', sys.version_info >= (3, 10), 'you', 'Python 3.10+ is needed'),
        ('ffmpeg', bool(shutil.which('ffmpeg') and shutil.which('ffprobe')), 'agent', f'{brew} ffmpeg'),
        ('opencc', run('opencc', '-c', 's2twp.json', stdin='测试') == (True, '測試'), 'agent', f'{brew} opencc (needs the CLI and s2twp.json)'),
    ]
    local = []
    if mac_arm:
        local = [
            ('mlx-qwen3-asr', bool(shutil.which('mlx-qwen3-asr')), 'agent', 'uv tool install mlx-qwen3-asr'),
            ('qwen-0.6b', (HUB / 'models--Qwen--Qwen3-ASR-0.6B').is_dir(), 'agent',
             'download Qwen/Qwen3-ASR-0.6B into the Hugging Face cache (check size and free space first)'),
            ('aligner', (HUB / 'models--Qwen--Qwen3-ForcedAligner-0.6B').is_dir(), 'agent',
             'download Qwen/Qwen3-ForcedAligner-0.6B into the Hugging Face cache'),
            ('xcode-clt', run('xcode-select', '-p')[0], 'you',
             'run xcode-select --install and click Install in the macOS dialog'),
            ('speaker-bridge', (SKILL / 'scripts/community1-bridge/build/community1-bridge').is_file(), 'agent',
             f'sh "{SKILL}/scripts/community1-bridge/build.sh" (speakers; without it runs end partial)'),
        ]
    voice_memos = Path.home() / 'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings'
    try:
        memos_ok = (voice_memos / 'CloudRecordings.db').exists() or not voice_memos.exists()
        os.listdir(voice_memos) if voice_memos.exists() else None
    except PermissionError:
        memos_ok = False
    extras = [('voice-memos-access', memos_ok, 'you',
               'System Settings → Privacy & Security → Full Disk Access → enable your terminal or agent app (optional; '
               'otherwise drag recordings into a folder)')] if platform.system() == 'Darwin' else []
    gemini = bool(os.environ.get('GEMINI_API_KEY')) or run('security', 'find-generic-password', '-s', 'kerf-wordprint-gemini',
                                                            '-a', 'wordprint')[0]  # Existence only; the key is never read.
    extras.append(('gemini-key', gemini, 'you', 'optional: create a key at https://aistudio.google.com/apikey, then run '
                   'security add-generic-password -s kerf-wordprint-gemini -a wordprint -w'))
    return items, local, extras


def main():
    items, local, extras = checks()
    base = all(ok for _, ok, _, _ in items)
    routes = {'local': base and bool(local) and all(ok for name, ok, _, _ in local if name != 'speaker-bridge'),
              'gemini': base and extras[-1][1], 'colab': base}
    rows = [{'check': name, 'ok': ok, 'who': None if ok else who, 'next': None if ok else step}
            for name, ok, who, step in items + local + extras]
    if '--json' in sys.argv:
        print(json.dumps({'routes': routes, 'checks': rows}, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{'ok' if row['ok'] else row['who']:<5} {row['check']}" + ('' if row['ok'] else f": {row['next']}"))
        print('routes ready:', ', '.join(k for k, v in routes.items() if v) or 'none')
    return 0 if any(routes.values()) else 1


if __name__ == '__main__':
    sys.exit(main())

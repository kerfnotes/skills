#!/usr/bin/env python3
"""Check what Wordprint can run on this machine; with --fix, also run the routine installs.

Each check is `ok`, `agent` (a routine install: --fix runs it) or `you` (needs the user: an account, terms, a password or
a permission prompt). Without --fix nothing is installed or downloaded. Secrets are never read. `--json` prints the
result as JSON. Exit 0 when at least one transcription route is ready, 1 otherwise.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
HUB = Path(os.environ.get('HF_HUB_CACHE') or Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface')) / 'hub')
SPEECH_CACHE = Path.home() / 'Library/Caches/qwen3-speech/models/aufklarer'
VOICE_MEMOS = Path.home() / 'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings'
MODELS = ['Qwen/Qwen3-ASR-0.6B', 'Qwen/Qwen3-ForcedAligner-0.6B']
NEED_FREE_GB = 6  # Two 0.6B models are about 3.5 GB in the Hugging Face cache.
# Windows, Linux and Intel Macs run scripts/torch_worker.py from this environment (also the Colab notebook's versions).
TORCH_VENV = Path(os.environ.get('WORDPRINT_TORCH_VENV') or Path.home() / '.wordprint' / 'torch-venv')
NEMO = 'nemo-toolkit[asr] @ https://github.com/NVIDIA/NeMo/archive/16b0ff2584c6355c53cbd6c28f0f431a76b24956.zip'
TORCH_PACKAGES = ['qwen-asr', 'transformers==4.57.6', 'Cython', 'packaging', 'opencc', NEMO]  # One resolve keeps the pin.


def run(*command, stdin=None, timeout=20):
    """Exit code 0 and stdout, or (False, '') when the command is missing or hangs."""
    try:
        result = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ''


def torch_python():
    return TORCH_VENV / ('Scripts/python.exe' if platform.system() == 'Windows' else 'bin/python')


def worker_python():
    """The interpreter where huggingface_hub is installed: the mlx-qwen3-asr shebang, else the torch environment."""
    if not (platform.system() == 'Darwin' and platform.machine() == 'arm64'):
        return str(torch_python())
    tool = shutil.which('mlx-qwen3-asr')
    first = Path(tool).read_text(errors='replace').splitlines()[0] if tool else ''
    return first[2:].strip() if first.startswith('#!') else None


def sample_wav():
    """Two short synthetic voices, only to make `speech` fetch its CoreML models once."""
    directory = Path(tempfile.mkdtemp(prefix='wordprint-doctor-'))
    subprocess.run(['say', '-o', str(directory / 'a.aiff'), 'Wordprint setup check.'], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(directory / 'a.aiff'), '-ac', '1', '-ar', '16000',
                    str(directory / 'a.wav')], check=True)
    return directory / 'a.wav'


def prefetch_speech():
    wav = sample_wav()
    subprocess.run(['speech', 'diarize', '--engine', 'community1', str(wav)], check=True)
    subprocess.run(['speech', 'embed-speaker', '--engine', 'coreml', '--json', str(wav)], check=True)
    shutil.rmtree(wav.parent, ignore_errors=True)


def download_models():
    free = shutil.disk_usage(Path.home()).free / 1e9
    if free < NEED_FREE_GB:
        raise SystemExit(f'only {free:.1f} GB free; the Qwen models need about {NEED_FREE_GB} GB')
    code = 'import sys\nfrom huggingface_hub import snapshot_download\nfor m in sys.argv[1:]: print(snapshot_download(m))'
    subprocess.run([worker_python(), '-c', code, *MODELS], check=True)


def build_torch_venv():
    free = shutil.disk_usage(Path.home()).free / 1e9
    if free < NEED_FREE_GB + 2:
        raise SystemExit(f'only {free:.1f} GB free; the environment and models need about {NEED_FREE_GB + 2} GB')
    subprocess.run(['uv', 'venv', '--python', '3.12', str(TORCH_VENV)], check=True)
    subprocess.run(['uv', 'pip', 'install', '--python', str(torch_python()), *TORCH_PACKAGES], check=True)


def checks():
    """(name, ok, who, next step, fix) in install order; fix is a callable or an argv list for `agent` items."""
    mac = platform.system() == 'Darwin'
    mac_arm = mac and platform.machine() == 'arm64'
    brew = shutil.which('brew')
    no_brew = (False, 'you', 'install Homebrew from https://brew.sh (asks for your password)', None)

    windows = platform.system() == 'Windows'
    winget = {'ffmpeg': 'Gyan.FFmpeg', 'uv': 'astral-sh.uv'}

    def formula(name):
        found = bool(shutil.which(name))
        if mac:
            return (found, 'agent', f'brew install {name}', ['brew', 'install', name]) if brew else no_brew
        if windows and name in winget:
            return found, 'agent', f'winget install -e --id {winget[name]} (then reopen the terminal)', \
                ['winget', 'install', '-e', '--id', winget[name], '--accept-source-agreements', '--accept-package-agreements']
        if name == 'uv':  # The official installer needs no administrator rights.
            return found, 'agent', 'install uv from https://astral.sh/uv', ['sh', '-c', 'curl -LsSf https://astral.sh/uv/install.sh | sh']
        return found, 'you', f'install {name} with your package manager (for example sudo apt install {name})', None
    items = [('python', sys.version_info >= (3, 10), 'you', 'Python 3.10+ is needed', None)]
    if mac:
        items.append(('homebrew', bool(brew), *no_brew[1:]))
    ffmpeg = formula('ffmpeg')
    items.append(('ffmpeg', bool(shutil.which('ffmpeg') and shutil.which('ffprobe')), *ffmpeg[1:]))
    if mac_arm:
        opencc = formula('opencc')
        items.append(('opencc', run('opencc', '-c', 's2twp.json', stdin='测试') == (True, '測試'), *opencc[1:]))
    if not mac_arm:
        ready = run(str(torch_python()), '-c', 'import qwen_asr, opencc, nemo.collections.asr', timeout=300)[0]
        items += [('uv', *formula('uv')),
                  ('torch-worker', ready, 'agent', f'create {TORCH_VENV} with qwen-asr, NeMo and OpenCC (about 1.7 GB)',
                   build_torch_venv),
                  ('qwen-models', all((HUB / ('models--' + m.replace('/', '--'))).is_dir() for m in MODELS), 'agent',
                   f'download {" and ".join(MODELS)} (about 3.5 GB; the 189 MB speaker model downloads on first run)',
                   download_models)]
    if mac_arm:
        items += [
            ('uv', *formula('uv')),
            ('mlx-qwen3-asr', bool(shutil.which('mlx-qwen3-asr')), 'agent', 'uv tool install mlx-qwen3-asr',
             ['uv', 'tool', 'install', 'mlx-qwen3-asr']),
            ('qwen-models', all((HUB / ('models--' + m.replace('/', '--'))).is_dir() for m in MODELS), 'agent',
             f'download {" and ".join(MODELS)} (about 3.5 GB)', download_models),
            ('speech', *formula('speech')),
            ('speaker-models', (SPEECH_CACHE / 'Pyannote-Community-1-CoreML').is_dir()
             and (SPEECH_CACHE / 'WeSpeaker-ResNet34-LM-CoreML').is_dir(), 'agent',
             'let `speech` fetch its CoreML speaker models once (about 45 MB)', prefetch_speech),
            ('xcode-clt', run('xcode-select', '-p')[0], 'you',
             'run xcode-select --install and click Install in the macOS dialog', None),
            ('speaker-bridge', (SKILL / 'scripts/community1-bridge/build/community1-bridge').is_file(), 'agent',
             'build the offline speaker bridge', ['sh', str(SKILL / 'scripts/community1-bridge/build.sh')]),
        ]
    if mac:
        try:
            memos_ok = not VOICE_MEMOS.exists() or os.listdir(VOICE_MEMOS) is not None
        except PermissionError:
            memos_ok = False
        items.append(('voice-memos-access', memos_ok, 'you', 'optional: System Settings → Privacy & Security → Full '
                      'Disk Access → enable your terminal or agent app (otherwise drag recordings into a folder)', None))
    key = bool(os.environ.get('GEMINI_API_KEY')) or mac and run('security', 'find-generic-password', '-s',
                                                                 'kerf-wordprint-gemini', '-a', 'wordprint')[0]  # Existence only.
    store = ('run security add-generic-password -s kerf-wordprint-gemini -a wordprint -w' if mac else
             'save it as the GEMINI_API_KEY user environment variable')
    items.append(('gemini-key', key, 'you', f'optional: create a key at https://aistudio.google.com/apikey, then {store}', None))
    return items, mac_arm


def report(items, mac_arm):
    ok = {name: good for name, good, *_ in items}
    if mac_arm:
        base = ok['python'] and ok['ffmpeg'] and ok['opencc']
        local = base and ok['mlx-qwen3-asr'] and ok['qwen-models']
        speakers = local and ok['speaker-models'] and ok['speaker-bridge']
    else:  # OpenCC comes with the torch environment; render with its python.
        base = ok['python'] and ok['ffmpeg'] and ok['torch-worker']
        local = speakers = base and ok['qwen-models']
    routes = {'local': local, 'local-speakers': speakers, 'gemini': base and ok['gemini-key'], 'colab': ok['python']}
    rows = [{'check': name, 'ok': good, 'who': None if good else who, 'next': None if good else step}
            for name, good, who, step, _ in items]
    return routes, rows


def main():
    fix = '--fix' in sys.argv
    items, mac_arm = checks()
    if fix:
        for name, good, who, step, action in items:
            if good or who != 'agent' or action is None:
                continue
            print(f'fix   {name}: {step}', flush=True)
            try:
                action() if callable(action) else subprocess.run(action, check=True)
            except (OSError, subprocess.CalledProcessError, SystemExit) as error:
                print(f'      failed: {error}', flush=True)
            items, mac_arm = checks()  # Later steps depend on earlier ones (brew → uv → mlx-qwen3-asr → models).
    routes, rows = report(items, mac_arm)
    if '--json' in sys.argv:
        print(json.dumps({'routes': routes, 'checks': rows}, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"{'ok' if row['ok'] else row['who']:<5} {row['check']}" + ('' if row['ok'] else f": {row['next']}"))
        print('routes ready:', ', '.join(k for k, v in routes.items() if v) or 'none')
    return 0 if any(routes.values()) else 1


if __name__ == '__main__':
    sys.exit(main())

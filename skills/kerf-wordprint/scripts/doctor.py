#!/usr/bin/env python3
"""Check what Wordprint can run on this machine; with --fix, also run the routine installs.

Each check is `ok`, `agent` (a routine install: --fix runs it) or `you` (needs the user: an account, terms, a password or
a permission prompt). Without --fix nothing is installed or downloaded. Secrets are never read. `--json` prints the
result as JSON. Exit 0 when at least one transcription route is ready, 1 otherwise.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from functools import partial

SKILL = Path(__file__).resolve().parents[1]
HUB = Path(os.environ.get('HF_HUB_CACHE') or Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface')) / 'hub')
SPEECH_CACHE = Path.home() / 'Library/Caches/qwen3-speech/models/aufklarer'
VOICE_MEMOS = Path.home() / 'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings'
DEFAULT_MODEL = '0.6B'
QWEN_CACHE_SCOPE = 'necessary cached files only; weight hashes and model loadability are not verified'
# Conservative free-space reservations, not measured download/cache sizes.
# Keep the original 6 GB allowance for 0.6B; reserve more for the larger ASR.
NEED_FREE_GB = {'0.6B': 6, '1.7B': 12}
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


def prefetch_speech(*, embeddings=False):
    wav = sample_wav()
    command = (['speech', 'embed-speaker', '--engine', 'coreml', '--json'] if embeddings
               else ['speech', 'diarize', '--engine', 'community1'])
    try:
        subprocess.run([*command, str(wav)], check=True)
    finally:
        shutil.rmtree(wav.parent, ignore_errors=True)


def model_ids(model):
    return [f'Qwen/Qwen3-ASR-{model}', 'Qwen/Qwen3-ForcedAligner-0.6B']


def qwen_cache_problem(model_id):
    """Check the three supported Qwen repos, without importing a model package or reading weights.

    Workers use HF's default revision (main); an arbitrary old snapshot does not count.
    Files are checked with stat/access, following normal HF blob symlinks or Windows
    direct files. Only small JSON metadata is read. This is not a hash/loadability check.
    """
    repo = HUB / ('models--' + model_id.replace('/', '--'))

    def file_ok(path):
        return path.is_file() and path.stat().st_size > 0 and os.access(path, os.R_OK)

    def metadata(path):
        if not file_ok(path) or path.stat().st_size > 1024 * 1024:
            raise ValueError(f'missing, unreadable, empty or oversized {path.name}')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or not value:
            raise ValueError(f'invalid {path.name}')
        return value

    def relative_file(name):
        return (isinstance(name, str) and bool(name) and '\\' not in name and ':' not in name
                and all(part not in ('', '.', '..') for part in name.split('/')))

    try:
        ref = repo / 'refs/main'
        if not file_ok(ref) or ref.stat().st_size != 40:
            return 'missing or invalid refs/main'
        revision = ref.read_text(encoding='utf-8')  # Do not strip: HF uses the exact ref contents.
        if any(char not in '0123456789abcdef' for char in revision):
            return 'invalid refs/main commit'
        snapshot = repo / 'snapshots' / revision
        # Released Qwen ASR/ForcedAligner files: native MLX uses vocab + merges;
        # processor/tokenizer metadata also serves the PyTorch route.
        for name in ('config.json', 'tokenizer_config.json', 'preprocessor_config.json', 'chat_template.json'):
            metadata(snapshot / name)
        required = {'vocab.json', 'merges.txt'}
        index = snapshot / 'model.safetensors.index.json'
        if index.exists() or index.is_symlink():
            weights = metadata(index).get('weight_map')
            if not isinstance(weights, dict) or not weights:
                return 'invalid or empty model.safetensors.index.json weight_map'
            for name in weights.values():
                if not relative_file(name) or '/' in name or not name.endswith('.safetensors'):
                    return 'invalid weight shard path'
                required.add(name)
        else:
            required.add('model.safetensors')
        # MLX loads every root safetensors file, including files outside the index.
        required.update(path.name for path in snapshot.glob('*.safetensors'))
        tree = repo / 'trees' / (revision + '.json')
        if tree.exists() or tree.is_symlink():
            listing = metadata(tree)
            if listing.get('format_version') != 1 or not isinstance(listing.get('files'), dict):
                return 'unsupported cached tree metadata'
            # huggingface_hub 1.24 checks this listing during local_files_only.
            # Match qwen_worker.snapshot's ignore_patterns, including nested Markdown.
            for name in listing['files']:
                if not relative_file(name):
                    return 'invalid cached tree path'
                if name != '.gitattributes' and not name.endswith('.md'):
                    required.add(name)
        for name in sorted(required):
            if not file_ok(snapshot / name):
                return f'missing, unreadable or empty {name}'
    except (OSError, ValueError, RuntimeError) as error:
        return f'cache metadata unavailable: {error}'
    return None


def speaker_cache_problem(bundle):
    """Check the published speech 0.0.27 CoreML bundles, without loading models.

    Community1BundleManifest.load/fromLocal supplies the paths and schema. The
    standalone WeSpeaker loader uses wespeaker.mlmodelc. These published MLProgram
    bundles contain model.mil, coremldata.bin and weights/weight.bin; this is not
    a generic CoreML validator, a weight hash check or proof of loadability.
    """
    root = SPEECH_CACHE / bundle

    def file_ok(path):
        if not (path.is_file() and path.stat().st_size > 0 and os.access(path, os.R_OK)):
            raise ValueError(f'missing, unreadable or empty {path.relative_to(root)}')

    def target(name):
        if (not isinstance(name, str) or not name or ':' in name or '\\' in name
                or any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('invalid manifest artifact path')
        return root / name

    def compiled(name):
        directory = target(name)
        if directory.suffix != '.mlmodelc':
            raise ValueError('unsupported compiled model format')
        for filename in ('model.mil', 'coremldata.bin', 'weights/weight.bin'):
            file_ok(directory / filename)

    try:
        path = root / 'config.json'
        file_ok(path)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('oversized config.json')
        config = json.loads(path.read_text(encoding='utf-8'))
        expected = {'Pyannote-Community-1-CoreML': 'pyannote-community-1-coreml',
                    'WeSpeaker-ResNet34-LM-CoreML': 'wespeaker-resnet34-lm-coreml'}
        if bundle not in expected or not isinstance(config, dict) or config.get('model_type') != expected[bundle]:
            raise ValueError('invalid config.json model_type')
        if type(config.get('sample_rate')) is not int or config['sample_rate'] != 16000:
            raise ValueError('config.json sample_rate must be 16000')
        if bundle == 'Pyannote-Community-1-CoreML':
            for section, fields in [('segmentation', ('model', 'input_name', 'output_name')),
                                    ('embedding', ('model', 'waveform_input_name', 'weights_input_name', 'output_name')),
                                    ('plda', ('weights',))]:
                data = config.get(section)
                if not isinstance(data, dict) or any(not isinstance(data.get(key), str) or not data[key] for key in fields):
                    raise ValueError(f'invalid config.json {section}')
            if type(config['plda'].get('dimension')) is not int or config['plda']['dimension'] != 128:
                raise ValueError('config.json PLDA dimension must be 128')
            compiled(config['segmentation']['model'])
            compiled(config['embedding']['model'])
            file_ok(target(config['plda']['weights']))
        else:
            compiled('wespeaker.mlmodelc')
    except (OSError, ValueError, RuntimeError) as error:
        return f'{bundle}: {error}'
    return None


def download_models(model=DEFAULT_MODEL):
    required = NEED_FREE_GB[model]
    free = shutil.disk_usage(Path.home()).free / 1e9
    if free < required:
        raise SystemExit(f'only {free:.1f} GB free; reserve {required} GB for ASR {model} + ForcedAligner '
                         '(conservative allowance, not a measured download size)')
    code = 'import sys\nfrom huggingface_hub import snapshot_download\nfor m in sys.argv[1:]: print(snapshot_download(m))'
    subprocess.run([worker_python(), '-c', code, *model_ids(model)], check=True)


def build_torch_venv(model=DEFAULT_MODEL):
    required = NEED_FREE_GB[model] + 2
    free = shutil.disk_usage(Path.home()).free / 1e9
    if free < required:
        raise SystemExit(f'only {free:.1f} GB free; reserve {required} GB for the environment and ASR {model} '
                         '+ ForcedAligner (conservative allowance, not a measured download size)')
    subprocess.run(['uv', 'venv', '--python', '3.12', str(TORCH_VENV)], check=True)
    subprocess.run(['uv', 'pip', 'install', '--python', str(torch_python()), *TORCH_PACKAGES], check=True)


def checks(model=DEFAULT_MODEL):
    """(name, ok, who, next step, fix) in install order; fix is a callable or an argv list for `agent` items."""
    mac = platform.system() == 'Darwin'
    mac_arm = mac and platform.machine() == 'arm64'
    models = model_ids(model)
    problems = [f'{name}: {problem}' for name in models if (problem := qwen_cache_problem(name))]
    models_ready = not problems
    model_step = (f'download {" and ".join(models)} (reserve {NEED_FREE_GB[model]} GB free; '
                  'conservative allowance, not a measured download size)')
    if problems:
        model_step = '; '.join(problems) + '; ' + model_step
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
                   partial(build_torch_venv, model)),
                  ('qwen-models', models_ready, 'agent',
                   model_step + '; the 189 MB speaker model downloads on first run',
                   partial(download_models, model))]
    if mac_arm:
        speaker_problem = speaker_cache_problem('Pyannote-Community-1-CoreML')
        embedding_problem = speaker_cache_problem('WeSpeaker-ResNet34-LM-CoreML')
        speaker_step = 'let `speech diarize --engine community1` fetch its required CoreML bundle'
        embedding_step = 'optional: let `speech embed-speaker --engine coreml` fetch the cross-window matching bundle'
        if speaker_problem:
            speaker_step = speaker_problem + '; ' + speaker_step
        if embedding_problem:
            embedding_step = embedding_problem + '; ' + embedding_step
        items += [
            ('uv', *formula('uv')),
            ('mlx-qwen3-asr', bool(shutil.which('mlx-qwen3-asr')), 'agent', 'uv tool install mlx-qwen3-asr',
             ['uv', 'tool', 'install', 'mlx-qwen3-asr']),
            ('qwen-models', models_ready, 'agent',
             model_step, partial(download_models, model)),
            ('speech', *formula('speech')),
            ('speaker-models', not speaker_problem, 'agent', speaker_step, prefetch_speech),
            ('speaker-embeddings', not embedding_problem, 'agent', embedding_step,
             partial(prefetch_speech, embeddings=True)),
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
    for row in rows:
        if row['check'] == 'qwen-models':
            row['scope'] = QWEN_CACHE_SCOPE
        elif row['check'] in ('speaker-models', 'speaker-embeddings'):
            row['scope'] = 'necessary cached files only; weight hashes and CoreML loadability are not verified'
    return routes, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=tuple(NEED_FREE_GB), default=DEFAULT_MODEL,
                        help='local ASR model to check/install (default: %(default)s)')
    parser.add_argument('--fix', action='store_true', help='install missing routine dependencies')
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    args = parser.parse_args(argv)
    items, mac_arm = checks(args.model)
    if args.fix:
        for name, good, who, step, action in items:
            if good or who != 'agent' or action is None:
                continue
            print(f'fix   {name}: {step}', flush=True)
            try:
                action() if callable(action) else subprocess.run(action, check=True)
            except (OSError, subprocess.CalledProcessError, SystemExit) as error:
                print(f'      failed: {error}', flush=True)
            items, mac_arm = checks(args.model)  # Later steps depend on earlier ones (brew → uv → mlx-qwen3-asr → models).
    routes, rows = report(items, mac_arm)
    if args.json:
        print(json.dumps({'model': args.model, 'routes': routes, 'checks': rows}, ensure_ascii=False, indent=2))
    else:
        print(f'local ASR model: {args.model}')
        for row in rows:
            print(f"{'ok' if row['ok'] else row['who']:<5} {row['check']}" + ('' if row['ok'] else f": {row['next']}")
                  + (f" ({row['scope']})" if 'scope' in row else ''))
        print('routes ready:', ', '.join(k for k, v in routes.items() if v) or 'none')
    return 0 if any(routes.values()) else 1


if __name__ == '__main__':
    sys.exit(main())

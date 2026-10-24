#!/usr/bin/env python3
"""Collect missing choices, dispatch a worker, validate and render into a fresh task directory.

Only an explicit engine selection enables a cloud route. Summaries and Mail drafts remain
agent handoffs recorded in delivery.json; this command never sends mail or installs models.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
AUDIO = {'.wav', '.m4a', '.qta', '.mp3', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff', '.mp4', '.wma'}


def load(name):
    spec = importlib.util.spec_from_file_location('wordprint_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


input_files = load('input_files')


def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def choices(request):
    """One canonical choice validator serves both the direct and form routes."""
    if not isinstance(request, dict):
        raise ValueError('request 必須是 JSON object')
    sources = request.get('sources', [])
    if not isinstance(sources, list):
        raise ValueError('sources 必須是陣列')
    normalized = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('path'), str):
            raise ValueError('每個來源需要 path')
        normalized.append({'kind': 'path', 'title': Path(source['path']).name, **source})
    return load('form').normalize_answers({**request, 'sources': normalized}, complete=False)


def missing(answers):
    fields = []
    if not answers['sources']:
        fields.append('sources')
    if answers['summary'] == 'custom' and not answers['summary_custom'].strip():
        fields.append('summary_custom')
    return fields


def expand_sources(sources):
    expanded = []
    for source in sources:
        if source['kind'] == 'voice_memo':
            original = Path(source['path']).expanduser()
            if original.is_symlink() or not original.is_file():
                raise ValueError('語音備忘錄目前無法讀取，請重新整理或匯出後加入。')
            # Keep the selected name intact; preserve_memos opens it relative to
            # a pinned parent with O_NOFOLLOW, even if this probe raced a swap.
            expanded.append({**source, 'path': os.path.abspath(original)})
            continue
        path = Path(source['path']).expanduser().resolve()
        paths = sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() in AUDIO),
                       key=lambda p: p.name) if path.is_dir() else [path]
        if not paths:
            raise ValueError(f'資料夾沒有支援的音檔：{path}')
        for item in paths:
            if not item.is_file():
                raise ValueError(f'找不到音檔：{item}')
            expanded.append({**source, 'path': str(item),
                             'title': item.name if path.is_dir() else source.get('title', item.name)})
    return expanded


def preserve_memos(sources, task):
    """Keep selected memo bytes in this job before a model can open them."""
    preserved = []
    for source in sources:
        if source['kind'] != 'voice_memo':
            preserved.append(source)
            continue
        original = Path(os.path.abspath(os.path.expanduser(source['path'])))
        if original.suffix.lower() not in AUDIO:
            raise ValueError('語音備忘錄音檔格式不支援，請匯出音檔後再加入。')
        with input_files.inputs_directory(task) as (destination_fd, verify_destination), \
                input_files.fixed_directory(original.parent) as (source_fd, verify_source):
            temporary = target = None
            try:
                descriptor = os.open(original.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=source_fd)
                with os.fdopen(descriptor, 'rb') as incoming:
                    before = os.fstat(incoming.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_size == 0:
                        raise ValueError('語音備忘錄不是可讀取的音檔。')
                    digest = hashlib.sha256()
                    name = 'memo-' + secrets.token_hex(16)
                    with input_files.create_file(destination_fd, name + '.part') as output:
                        temporary = name + '.part'
                        for block in iter(lambda: incoming.read(1024 * 1024), b''):
                            output.write(block)
                            digest.update(block)
                        output.flush()
                        os.fsync(output.fileno())
                    incoming.seek(0)
                    verified = hashlib.sha256()
                    for block in iter(lambda: incoming.read(1024 * 1024), b''):
                        verified.update(block)
                    stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    verify_source()
                    if (digest.digest() != verified.digest() or
                            stamp(before) != stamp(os.fstat(incoming.fileno())) or
                            stamp(before) != stamp(os.stat(original.name, dir_fd=source_fd, follow_symlinks=False))):
                        raise ValueError('語音備忘錄在匯入時發生變動，請重新整理後再試。')
                verify_destination()
                final_name = name + original.suffix.lower()
                os.replace(temporary, final_name, src_dir_fd=destination_fd, dst_dir_fd=destination_fd)
                target = final_name
                verify_source()
                verify_destination()
                preserved.append({**source, 'path': str(task / 'inputs' / target)})
                target = None
            finally:
                input_files.remove_file(destination_fd, temporary)
                input_files.remove_file(destination_fd, target)
    return preserved


def runtime(engine):
    if engine == 'gemini-3.5-transcribe':
        return [sys.executable], 'gemini_transcribe.py'
    if platform.system() == 'Darwin' and platform.machine() == 'arm64':
        binary = shutil.which('mlx-qwen3-asr')
        if not binary:
            raise ValueError('尚未安裝本機 Qwen；請先執行 doctor.py，不會自動改用雲端。')
        first = Path(binary).read_text(encoding='utf-8').splitlines()[0]
        if not first.startswith('#!'):
            raise ValueError('無法從 mlx-qwen3-asr 找到 worker Python')
        return shlex.split(first[2:]), 'qwen_worker.py'
    venv = Path(os.environ.get('WORDPRINT_TORCH_VENV') or Path.home() / '.wordprint' / 'torch-venv')
    python = venv / ('Scripts/python.exe' if platform.system() == 'Windows' else 'bin/python')
    if not python.is_file():
        raise ValueError('尚未建立 PyTorch 環境；請先執行 doctor.py，不會自動改用雲端。')
    return [str(python)], 'torch_worker.py'


def worker_command(python, script, sources, directory, engine, resume=None):
    command = [*python, str(SCRIPTS / script)]
    for source in sources:
        command += ['--audio', source['path']]
    if script == 'torch_worker.py':
        command += ['--out', str(directory / 'normalized-run.json'), '--pcm', str(directory / 'canonical.wav')]
    else:
        command += ['--run-directory', str(directory)]
    if engine.startswith('qwen-'):
        command += ['--model', '1.7B' if engine == 'qwen-1.7b' else '0.6B']
    if resume:
        command += ['--resume-from', str(Path(resume).resolve())]
    return command


def execute(command):
    with subprocess.Popen(command, stdout=sys.stderr) as process:
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise


def deliver(directory, output, python, answers, original_script=False, title=None, worker_exit_code=0):
    """A worker exit code alone never establishes complete transcription."""
    item = {'run_directory': str(directory), 'status': 'failed', 'outputs': [], 'warnings': [], 'next_steps': []}
    state_path, normalized = directory / 'state.json', directory / 'normalized-run.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.is_file() else {}
    item['warnings'] = list(state.get('warnings', []))
    if state.get('error'):
        item['warnings'].append(str(state['error']))
    if state.get('google_resources'):
        item['google_resources'] = state['google_resources']
    item['retry_stage'] = state.get('retry_stage')
    raw = directory / 'raw-transcript.txt'
    if raw.is_file():
        item['outputs'].append(str(raw))
        item['status'] = 'partial'
    if not normalized.is_file():
        return item
    run = json.loads(normalized.read_text(encoding='utf-8'))
    run['participant_candidates'] = answers['roster']
    save(normalized, run)
    item['outputs'].append(str(normalized))
    item['model'] = run.get('model')
    # A preserved raw text is useful even when timings/speakers are invalid.
    if not raw.exists():
        texts = [chunk['text'] for chunk in run.get('chunks', []) if isinstance(chunk.get('text'), str)]
        if texts:
            raw.write_text('\n'.join(texts) + '\n', encoding='utf-8')
            item['outputs'].append(str(raw))
            item['status'] = 'partial'
    if worker_exit_code != 0:
        item['warnings'].append(f'worker 非正常結束（{worker_exit_code}）；需要核對成果。')
        return item
    try:
        load('transcript').validate(normalized)
    except (ValueError, OSError, KeyError, TypeError) as error:
        item['warnings'].append(f'完整稿驗證未通過：{error}')
        return item
    if state.get('status', state.get('stage')) in ('failed', 'cancelled', 'partial'):
        item['warnings'].append('worker 尚未完整完成，保留原始成果。')
        return item
    command = [*python, str(SCRIPTS / 'transcript.py'), 'render', str(normalized), '--output', str(output)]
    if original_script:
        command.append('--original-script')
    if title:
        command += ['--title', title]
    if execute(command) != 0 or not (output / 'transcript.html').is_file():
        item['warnings'].append('閱讀頁尚未產生；原始逐字稿已保留，可修復輸出環境後重新 render。')
        item['retry_stage'] = 'render'
        return item
    item['status'] = 'complete'
    item['retry_stage'] = None
    item['outputs'] += [str(p) for p in sorted(output.iterdir()) if p.is_file()]
    report = json.loads((output / 'validation.json').read_text(encoding='utf-8'))
    if report.get('content_warning'):
        item['warnings'].append(report['content_warning'])
    if not report.get('srt_written'):
        item['warnings'].append('未輸出 SRT：' + report.get('srt_reason', '字幕時間未通過驗證'))
    if report.get('srt_grouping_note'):
        item['warnings'].append(report['srt_grouping_note'])
    if not report.get('playback_written'):
        item['warnings'].append('此份沒有音訊播放器。')
    if answers['summary'] != 'none':
        item['next_steps'].append({'stage': 'summary', 'template': answers['summary'],
                                   'custom': answers['summary_custom'], 'input': str(output / 'transcript.md')})
    if answers['mail']:
        item['next_steps'].append({'stage': 'mail_draft', 'recipients': answers['recipients']})
    return item


def collect(request, task, no_open, timeout):
    answers = choices(request)
    if not missing(answers):
        return answers
    # Preserve the resolved local default as well as explicit choices. Setup availability
    # must not turn a missing summary brief into implicit permission for cloud upload.
    result = load('form').serve([], task / 'answers.json', timeout, not no_open, prefill=answers)
    if result is None:
        raise TimeoutError('表單逾時；已知選項保留於 request.json，只補問缺少欄位：' + ', '.join(missing(answers)))
    answers = choices(result)
    if missing(answers):
        raise ValueError('仍缺少必要選項：' + ', '.join(missing(answers)))
    return answers


def run(args):
    request = json.loads(args.request.read_text(encoding='utf-8')) if args.request else {}
    choices(request)  # Reject malformed requests before creating any task directory.
    task = args.task_directory.expanduser().resolve()
    if args.resume_from:
        old = args.resume_from.expanduser().resolve()
        if task == old or old in task.parents:
            raise ValueError('續跑工作目錄必須在舊 run 以外，既有目錄未改動。')
    task.mkdir(parents=True, exist_ok=False)
    save(task / 'request.json', request)
    delivery = {'status': 'running', 'stage': 'choices', 'runs': []}
    save(task / 'delivery.json', delivery)
    try:
        answers = collect(request, task, args.no_open, args.timeout)
        answers['sources'] = expand_sources(answers['sources'])
        save(task / 'selected-sources.json', answers['sources'])
        answers['sources'] = preserve_memos(answers['sources'], task)
        save(task / 'answers.json', answers)
        if answers['engine'] == 'colab':
            delivery.update(status='waiting', stage='colab',
                            notebook='https://colab.research.google.com/github/kerfnotes/skills/blob/main/skills/kerf-wordprint/colab/wordprint.ipynb',
                            next_step='依 SKILL.md 的 Colab 匯入步驟核對下載結果與本機來源，再驗證及 render。')
            return delivery, 2
        groups = [answers['sources']] if answers['merge'] else [[source] for source in answers['sources']]
        if args.resume_from and len(groups) != 1:
            raise ValueError('一次續跑對應一份舊 run；請分別續跑，或提供原本合併的來源順序。')
        python, script = runtime(answers['engine'])
        if answers['engine'] == 'gemini-3.5-transcribe':
            print('音檔會上傳到 Google Gemini 並計費。', file=sys.stderr, flush=True)
        for index, sources in enumerate(groups, 1):
            directory = task / f'run-{index}'
            delivery.update(stage='transcribe', current_run=index)
            save(task / 'delivery.json', delivery)
            code = execute(worker_command(python, script, sources, directory, answers['engine'], args.resume_from))
            item = deliver(directory, task / f'output-{index}', python, answers, args.original_script, args.title, code)
            item['worker_exit_code'] = code
            if code != 0 and item['status'] == 'complete':
                item['status'] = 'partial'
                item['warnings'].append(f'worker 非正常結束（{code}）；需要核對成果。')
                item['next_steps'] = []
            delivery['runs'].append(item)
            save(task / 'delivery.json', delivery)
        states = [item['status'] for item in delivery['runs']]
        delivery.update(status='complete' if all(x == 'complete' for x in states) else
                        'partial' if any(x in ('complete', 'partial') for x in states) else 'failed', stage='delivery')
        # Complete here means transcription/render only; downstream agent work is explicitly pending.
        delivery['pending_agent_steps'] = [step for item in delivery['runs'] for step in item['next_steps']]
        return delivery, 0 if delivery['status'] == 'complete' else 1
    except (Exception, KeyboardInterrupt) as error:
        cancelled = isinstance(error, KeyboardInterrupt)
        index = delivery.get('current_run')
        if cancelled and index and len(delivery['runs']) < index:
            directory = task / f'run-{index}'
            if directory.exists():
                delivery['runs'].append(deliver(directory, task / f'output-{index}', python, answers,
                                                args.original_script, args.title, 130))
        delivery.update(status='cancelled' if cancelled else 'failed',
                        error='使用者已取消；請檢查保留成果及遠端資源紀錄。' if cancelled else str(error))
        return delivery, 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        save(task / 'delivery.json', delivery)


def interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, help='known choices in answers.json shape; omitted choices use defaults')
    parser.add_argument('--task-directory', required=True, type=Path, help='new directory outside the skill/repository')
    parser.add_argument('--resume-from', type=Path, help='old run directory; one run per invocation, old data stays intact')
    parser.add_argument('--no-open', action='store_true', help='print private form URL for the agent browser')
    parser.add_argument('--timeout', type=float, default=600, help='form wait in seconds')
    parser.add_argument('--original-script', action='store_true', help='only when original-script output was explicitly requested')
    parser.add_argument('--title')
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        result, code = run(args)
    except (OSError, ValueError) as error:
        result, code = {'status': 'failed', 'error': str(error)}, 1
    print(json.dumps(result, ensure_ascii=True))
    return code


if __name__ == '__main__':
    sys.exit(main())

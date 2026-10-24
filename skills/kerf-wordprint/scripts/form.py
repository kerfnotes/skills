#!/usr/bin/env python3
"""One-page local form that collects every Wordprint choice at once and writes answers.json.

Serves on 127.0.0.1 behind a random token, one request at a time, opens the browser, waits for one submit, prints the
answers JSON and exits 0. When the --timeout deadline passes, exits 2 and prints the same questions for a text fallback.
The tokened URL reaches stderr only with --no-open or when the browser fails to open.
"""
import argparse
import html
import hashlib
import importlib.util
import json
import os
import platform
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote

_input_spec = importlib.util.spec_from_file_location('wordprint_input_files', Path(__file__).with_name('input_files.py'))
input_files = importlib.util.module_from_spec(_input_spec)
_input_spec.loader.exec_module(input_files)

DEFAULT_ENGINE = 'qwen-0.6b'
ENGINES = {'qwen-0.6b': 'Qwen 0.6B',
           'qwen-1.7b': 'Qwen 1.7B',
           'gemini-3.5-transcribe': 'Gemini 3.5 Transcribe',
           'colab': 'Google Colab · Qwen'}
ENGINE_NOTES = {'qwen-0.6b': '預設本機模型，速度優先。',
                'qwen-1.7b': '可選用的較大本機模型。',
                'gemini-3.5-transcribe': '錄音會上傳 Google，並依 API 用量計費。',
                'colab': '錄音會上傳 Google Colab。需登入 Google 並操作筆記本。'}
SUMMARIES = {'meeting': '會議', 'interview': '訪談', 'lecture': '演講／課程', 'none': '不要摘要', 'custom': '自訂'}
QUESTIONS = """表單逾時，請改用文字逐題問使用者：
1. 要轉哪些錄音？（語音備忘錄最近幾則，或本機檔案／資料夾路徑；多個時問是否合併成一段）
2. 引擎：qwen-0.6b／qwen-1.7b（本機）／gemini-3.5-transcribe（會上傳 Google 並計費）／colab（會上傳 Google Colab，需登入並操作筆記本）
3. 參與者名單（可略；只當候選名單，不直接指派給說話者）
4. 摘要：meeting（預設）／interview／lecture／none／custom（請說明要什麼）
5. 收件人 email（可略）；要不要開 Mail 草稿（預設不要）"""
SPLIT = re.compile(r'[,，、;；\n]+')
MAX_BODY = 1024 * 1024
MAX_UPLOAD = 1024 * 1024 * 1024
READ_CHUNK = 64 * 1024
# Keep in sync with run.AUDIO, without importing the runner (which imports form).
AUDIO = {'.wav', '.m4a', '.mp3', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff', '.mp4', '.wma', '.qta'}


def theme_css():
    """Embed the active Clayprint tokens without requiring Node or network access.

    The standalone form keeps Clayprint defaults in CSS var() fallbacks. With a
    sibling install, it reads the same design layer as the reader and reports.
    """
    css = Path(__file__).with_name('form.css').read_text(encoding='utf-8')
    roots = (Path(__file__).resolve().parents[2], Path.cwd() / '.claude/skills', Path.cwd() / '.agents/skills')
    design = next((root / 'kerf-clayprint/design' for root in roots
                   if (root / 'kerf-clayprint/design/tokens.json').is_file()), None)
    override = os.environ.get('CLAYPRINT_TOKENS')
    if design is None and not override:
        return css
    path = Path(override) if override else design / 'tokens.json'
    try:
        tokens = json.loads(path.read_text(encoding='utf-8'))
        mode = os.environ.get('CLAYPRINT_MODE') or 'present'
        if mode not in ('present', 'read'):
            raise ValueError('unknown Clayprint mode')
        sizes = tokens['type']
        if mode == 'read':
            read = json.loads(((design or path.parent) / 'read.json').read_text(encoding='utf-8'))
            sizes = {**sizes, **{key: {'px': value} for key, value in read['type'].items()}}
        screen = (tokens.get('screen') or {}).get('type') or {}
        c = tokens['color']
        values = {'paper': c['onDark'][0], 'ink': c['text'], 'muted': c['textSecondary'],
                  'title': c['title'], 'line': c['grid'], 'accent': c['focus'],
                  'tint': c['tint'], 'soft': c['onDark'][1]}
        values['font'] = ', '.join(json.dumps(name, ensure_ascii=False)
                                  for name in tokens['font']['latin'] + tokens['font']['cjk']) + ', sans-serif'
        for prop, key, screen_key in (('body', 'body', 'body'), ('small', 'label', 'small'),
                                      ('sub', 'sub', 'sub'), ('title-size', 'title', 'title'),
                                      ('display', 'display', 'display')):
            size = screen.get(screen_key)
            if size is None:
                size = sizes[key]['px'] / 2
            values[prop] = f'{size:g}px'
        variables = ':root {\n' + ''.join(f'  --cp-{key}: {value};\n' for key, value in values.items()) + '}\n'
        # Design files are local configuration, but never let a string end <style>.
        return variables.replace('<', '\\3c ') + css
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('無法載入 Clayprint 設計層，請檢查本機設計檔') from error


def recommended_engine():
    """Cloud use requires an explicit choice, regardless of installed keys/runtimes."""
    return DEFAULT_ENGINE


def memo_id(path):
    """Identity follows the path, never the position in a refreshed listing."""
    return hashlib.sha256(os.fsencode(path)).hexdigest()


def file_status(path):
    """Probe metadata/read permission without reading recording contents."""
    try:
        info = Path(path).lstat()
        readable = (stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o444)
                    and os.access(path, os.R_OK, follow_symlinks=False))
        after = Path(path).lstat()
        unchanged = (info.st_dev, info.st_ino, info.st_mode) == (after.st_dev, after.st_ino, after.st_mode)
        return ('local', info.st_size) if readable and unchanged else ('unreadable', None)
    except FileNotFoundError:
        return 'missing', None
    except OSError:
        return 'unreadable', None


def memo_records(memos):
    records = []
    for memo in memos:
        path = memo['path']
        if not isinstance(path, str) or not path or '\x00' in path:
            raise ValueError('語音備忘錄路徑格式錯誤')
        availability, size = file_status(path)
        records.append({'id': memo_id(path), 'title': memo['title'], 'path': path,
                        'recorded_at': memo.get('recorded_at'), 'duration': memo.get('duration') or 0,
                        'availability': availability, 'byte_count': size})
    return records


def load_memos():
    """Load the sibling reader only on an explicit refresh request."""
    spec = importlib.util.spec_from_file_location('wordprint_voice_memos', Path(__file__).with_name('voice_memos.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.memos()


def memo_error(error):
    """Actionable categories without leaking database paths or raw SQLite errors."""
    if isinstance(error, FileNotFoundError):
        return '找不到語音備忘錄資料庫，請確認曾在此 Mac 建立或同步錄音'
    if isinstance(error, PermissionError):
        return '無權讀取語音備忘錄，請檢查完整磁碟取用權限，或匯出錄音後加入'
    if isinstance(error, ValueError):
        message = str(error)
        if any(word in message for word in ('正在寫入', '變動', '稍後')):
            return '語音備忘錄清單正在變動，請稍後重新整理'
        if any(word in message for word in ('符號連結', '不是一般')):
            return '語音備忘錄來源不是一般檔案或資料夾，不接受符號連結'
        if '建立' in message and '快照' in message:
            return '無法建立語音備忘錄清單快照，請檢查本機暫存空間與權限'
        return '讀不懂語音備忘錄清單格式，或資料庫模式不支援；請更新後重試或匯出錄音'
    return '無法讀取語音備忘錄清單，請稍後重試'


def require_readable(path):
    availability, _ = file_status(path)
    if availability != 'local':
        raise ValueError('錄音已不存在或無法讀取，請重新選擇')
    try:
        # Opening checks current permissions too; do not read audio here.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError('錄音已不存在或無法讀取，請重新選擇')
        finally:
            os.close(descriptor)
    except OSError as error:
        raise ValueError('錄音已不存在或無法讀取，請重新選擇') from error


def require_local_path(value):
    """Probe ordinary runner paths without reading audio or changing answers.

    Ordinary paths follow symlinks; Voice Memos keep their nofollow contract.
    Folder expansion is shallow, with the same extension filter as run.py.
    """
    message = '來源不存在、無法讀取，或資料夾沒有支援的音檔；請移除後重新選擇。'

    def check_file(path):
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444
                or not os.access(path, os.R_OK)):
            raise ValueError(message)
        # NONBLOCK protects against a file being swapped to a FIFO after stat.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError(message)
        finally:
            os.close(descriptor)

    try:
        path = Path(value).expanduser().resolve()
        info = path.stat()
        if stat.S_ISDIR(info.st_mode):
            if not info.st_mode & 0o444 or not info.st_mode & 0o111 or not os.access(path, os.R_OK | os.X_OK):
                raise ValueError(message)
            found = False
            for child in path.iterdir():
                if child.suffix.lower() in AUDIO and child.is_file():
                    check_file(child)
                    found = True
            if not found:
                raise ValueError(message)
        else:
            check_file(path)
    except (OSError, RuntimeError) as error:
        raise ValueError(message) from error


def _strings(value, pattern, label):
    if isinstance(value, str):
        value = pattern.split(value)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f'{label}格式錯誤')
    return [item.strip() for item in value if item.strip()]


def _answers(data, *, complete):
    if not isinstance(data, dict):
        raise ValueError('表單內容格式錯誤')
    raw_sources = data.get('sources', [])
    if not isinstance(raw_sources, list):
        raise ValueError('錄音來源格式錯誤')
    sources = []
    for source in raw_sources:
        if not isinstance(source, dict) or source.get('kind') not in ('path', 'voice_memo'):
            raise ValueError('錄音來源格式錯誤')
        path = source.get('path')
        if not isinstance(path, str) or not path.strip() or '\x00' in path:
            raise ValueError('錄音路徑格式錯誤')
        title = source.get('title', Path(path).name)
        if not isinstance(title, str):
            raise ValueError('錄音名稱格式錯誤')
        sources.append({'kind': source['kind'], 'path': path, 'title': title})
    if complete and not sources:
        raise ValueError('請至少選一個錄音或填一個路徑')
    engine, summary = data.get('engine', DEFAULT_ENGINE), data.get('summary', 'meeting')
    if not isinstance(engine, str) or not isinstance(summary, str) or engine not in ENGINES or summary not in SUMMARIES:
        raise ValueError('引擎或摘要選項無效')
    for key in ('merge', 'mail'):
        if key in data and type(data[key]) is not bool:
            raise ValueError(f'{key} 必須是 true 或 false')
    custom = data.get('summary_custom', '')
    if not isinstance(custom, str):
        raise ValueError('自訂摘要格式錯誤')
    if complete and summary == 'custom' and not custom.strip():
        raise ValueError('請填寫自訂摘要需求')
    # A single path may expand to several audio files in run.py. Preserve explicit
    # merge intent until that expansion, rather than clearing it in the form.
    return {'sources': sources, 'merge': data.get('merge', False) and
            (not complete or len(sources) > 1 or any(s['kind'] == 'path' for s in sources)),
            'engine': engine, 'roster': _strings(data.get('roster', []), SPLIT, '參與者'),
            'summary': summary, 'summary_custom': custom.strip() if summary == 'custom' else '',
            'recipients': _strings(data.get('recipients', []), re.compile(r'[\s,;，；]+'), '收件人'),
            'mail': data.get('mail', False)}


def normalize_answers(data, *, complete=True):
    """Validate canonical answers and fill defaults; requires sources and any custom brief.

    No filesystem probes or execution. Lists, explicit false/none and chosen models stay intact.
    """
    return _answers(data, complete=complete)


def normalize(data, memos, *, memo_registry=None, uploads=None):
    """Resolve mixed canonical/ID sources server-side, preserving their exact order.

    Legacy memo indices and typed paths are appended after the ordered sources.
    """
    if not isinstance(data, dict):
        raise ValueError('表單內容格式錯誤')
    raw_sources, indices, paths = data.get('sources', []), data.get('memos', []), data.get('paths', '')
    if not isinstance(raw_sources, list) or not isinstance(indices, list) or not isinstance(paths, str):
        raise ValueError('錄音來源格式錯誤')
    registry = memo_registry if memo_registry is not None else {memo_id(m['path']): m for m in memos}
    sources = []
    for source in raw_sources:
        if not isinstance(source, dict):
            raise ValueError('錄音來源格式錯誤')
        if 'memo_id' in source and 'upload_id' in source:
            raise ValueError('錄音來源格式錯誤')
        if 'memo_id' in source or 'upload_id' in source:
            is_memo = 'memo_id' in source
            identifier = source['memo_id' if is_memo else 'upload_id']
            records = registry if is_memo else (uploads or {})
            if not isinstance(identifier, str) or identifier not in records:
                raise ValueError('語音備忘錄選項無效' if is_memo else '上傳尚未完成或已失效')
            record = records[identifier]
            sources.append({'kind': 'voice_memo' if is_memo else 'path',
                            'path': record['path'], 'title': record['title']})
        else:
            sources.append(source)
    for index in indices:
        if type(index) is not int or not 0 <= index < len(memos):
            raise ValueError('語音備忘錄選項無效')
        sources.append({'kind': 'voice_memo', 'path': memos[index]['path'], 'title': memos[index]['title']})
    for line in paths.splitlines():
        if line.strip():
            path = line.strip()
            sources.append({'kind': 'path', 'path': path, 'title': Path(path).name})
    return normalize_answers({**data, 'sources': sources})


def browse(kind, timeout):
    """POSIX paths from the native picker; only explicit user cancellation is []."""
    script = ('POSIX path of (choose folder)' if kind == 'folder' else
              'set out to ""\nrepeat with f in (choose file with multiple selections allowed)\n'
              'set out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    if kind not in ('file', 'folder'):
        raise ValueError('選擇器類型無效')
    if platform.system() != 'Darwin':
        raise ValueError('此系統請直接填入本機路徑')
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('選擇器已逾時') from error
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line.strip()]
    if re.search(r'\(-128\)\s*$', result.stderr or ''):
        return []
    if re.search(r'\(-1743\)\s*$', result.stderr or ''):
        raise ValueError('系統未允許開啟選擇器，請改用「加入錄音」或填入本機路徑')
    raise ValueError('系統選擇器未能完成，請重試或改用「加入錄音」')


def page(memos, css, engine=DEFAULT_ENGINE, prefill=None, mode='collect'):
    """Render partial canonical answers without choosing an extra memo.

    css is retained for caller compatibility; the form uses the active Clayprint tokens.
    Only explicit prefilled sources are selected; available memos are separate state.
    mode changes presentation only and never enters canonical answers.
    """
    if mode not in ('collect', 'run'):
        raise ValueError('表單模式必須是 collect 或 run')
    supplied = {} if prefill is None else prefill
    if not isinstance(supplied, dict):
        raise ValueError('預填內容必須是 JSON 物件')
    values = _answers({'engine': engine, **supplied}, complete=False)
    esc = lambda value: html.escape(str(value), quote=True)
    checked = lambda value: ' checked' if value else ''
    state = {'mode': mode, 'sources': values['sources'], 'memos': memo_records(memos[:20]),
             'settings': {key: value for key, value in values.items() if key != 'sources'}}
    engines = ''.join(f'<label class="choice"><input type="radio" name="engine" value="{key}"{checked(key == values["engine"])}>'
                      f'<span><strong>{esc(label)}</strong><span class="hint">{esc(ENGINE_NOTES[key])}</span></span></label>'
                      for key, label in ENGINES.items())
    summaries = ''.join(f'<label class="choice"><input type="radio" name="summary" value="{key}"{checked(key == values["summary"])}> {esc(label)}</label>'
                        for key, label in SUMMARIES.items())
    fields = {
        'CSS': theme_css(), 'JS': Path(__file__).with_name('form.js').read_text(encoding='utf-8'),
        'PREFILL_NOTE': '<p class="prefill-note">已帶入你提供的設定，只需補齊或調整下方內容。</p>' if supplied else '',
        'SOURCES': '', 'MEMOS': '', 'STATE': json.dumps(state, ensure_ascii=False).replace('<', '\\u003c'),
        'ENGINES': engines, 'SUMMARIES': summaries,
        'SUBMIT': '送出設定' if mode == 'collect' else '準備 Colab' if values['engine'] == 'colab' else '開始整理',
        'MERGE': checked(values['merge']), 'MAIL': checked(values['mail']),
        'CUSTOM_HIDDEN': ' hidden' if values['summary'] != 'custom' else '',
        'CUSTOM': esc(values['summary_custom']), 'ROSTER': esc('、'.join(values['roster'])),
        'ROSTER_JSON': esc(json.dumps(values['roster'], ensure_ascii=False)),
        'RECIPIENTS': esc(', '.join(values['recipients'])),
    }
    template = Path(__file__).with_name('form.html').read_text(encoding='utf-8')
    # One pass: prefilled text resembling a template marker is never expanded.
    return re.sub(r'@@([A-Z_]+)@@', lambda match: fields[match[1]], template)


def serve(memos, out, timeout, open_browser=True, prefill=None, mode='collect'):
    deadline = time.monotonic() + timeout
    remaining = lambda: max(0.001, deadline - time.monotonic())
    token = secrets.token_urlsafe(16)
    engine = prefill['engine'] if isinstance(prefill, dict) and 'engine' in prefill else recommended_engine()
    form_page = page(memos, None, engine, prefill, mode).encode('utf-8')
    # Retain the original index snapshot for legacy callers; refresh only adds stable IDs.
    registry = {memo['id']: memo for memo in memo_records(memos)}
    uploads = {}  # Only atomically published, complete uploads enter this registry.
    partial_paths = set()  # Reject this session's staging files, not prior completed inputs.
    out = Path(out)
    answers = None

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.timeout = min(5, remaining())
            super().setup()

        def log_message(self, *_):
            pass

        def reply(self, code, body, kind='application/json; charset=utf-8'):
            body = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self, routes):
            authority = f'127.0.0.1:{self.server.server_address[1]}'
            hosts, origins = self.headers.get_all('Host', []), self.headers.get_all('Origin', [])
            if hosts != [authority] or (origins and origins != [f'http://{authority}']):
                self.reply(403, {'error': '不允許跨來源請求'})
                return False
            if self.path not in {f'/{token}/{route}' for route in routes}:
                self.reply(404, {'error': 'not found'})
                return False
            return True

        def check_deadline(self):
            if time.monotonic() >= deadline:
                raise TimeoutError('表單已逾時')

        def read_chunks(self, length):
            # read1 avoids a slow trickle extending a single read past the absolute deadline.
            while length:
                self.check_deadline()
                self.connection.settimeout(min(5, remaining()))
                chunk = self.rfile.read1(min(length, READ_CHUNK))
                if not chunk:
                    raise ValueError('傳輸中斷：內容長度不足')
                length -= len(chunk)
                self.check_deadline()
                yield chunk

        def content_length(self, upload):
            values = self.headers.get_all('Content-Length', [])
            if self.headers.get('Transfer-Encoding') is not None or len(values) > 1:
                raise ValueError('不支援的內容長度格式')
            if not values:
                if upload:
                    raise ValueError('上傳必須提供 Content-Length')
                return 0
            if not re.fullmatch(r'[0-9]+', values[0]):
                raise ValueError('內容長度格式錯誤')
            length = int(values[0])
            if upload and length < 1:
                raise ValueError('上傳檔案不可為空')
            return length

        def upload(self, length):
            names = self.headers.get_all('X-File-Name', [])
            if len(names) != 1 or re.search(r'%(?![0-9a-fA-F]{2})', names[0]):
                raise ValueError('上傳檔名格式錯誤')
            name = unquote(names[0], encoding='utf-8', errors='strict')
            # Windows/POSIX path components are display input only, never destination paths.
            title = name.replace('\\', '/').rsplit('/', 1)[-1]
            if not title or any(ord(c) < 32 or ord(c) == 127 for c in title):
                raise ValueError('上傳檔名格式錯誤')
            extension = Path(title).suffix.lower()
            if extension not in AUDIO:
                raise ValueError('不支援此錄音副檔名')
            directory = out.parent / 'inputs'
            identifier = secrets.token_hex(16)
            destination = f'{identifier}{extension}'
            partial = f'{identifier}.part'
            receipt = f'{identifier}.json'
            receipt_part = receipt + '.part'
            partial_paths.update(str((directory / name).absolute()) for name in (partial, receipt_part))
            digest = hashlib.sha256()
            count = 0
            with input_files.inputs_directory(out.parent) as (directory_fd, verify):
                owned = set()
                try:
                    with input_files.create_file(directory_fd, partial) as file:
                        owned.add(partial)
                        for chunk in self.read_chunks(length):
                            file.write(chunk)
                            digest.update(chunk)
                            count += len(chunk)
                        file.flush()
                        os.fsync(file.fileno())
                    self.check_deadline()
                    if count != length:
                        raise ValueError('傳輸內容長度不符')
                    result = {'id': identifier, 'title': title, 'byte_count': count, 'sha256': digest.hexdigest()}
                    with input_files.create_file(directory_fd, receipt_part) as file:
                        owned.add(receipt_part)
                        file.write((json.dumps({**result, 'basename': destination}, ensure_ascii=False) + '\n').encode('utf-8'))
                        file.flush()
                        os.fsync(file.fileno())
                    self.check_deadline()
                    verify()
                    for staging, final in ((partial, destination), (receipt_part, receipt)):
                        os.replace(staging, final, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                        owned.remove(staging)
                        owned.add(final)
                    verify()
                    uploads[identifier] = {**result, 'path': str((directory / destination).absolute())}
                    owned.clear()
                finally:
                    for name in owned:
                        input_files.remove_file(directory_fd, name)
            return result

        def do_GET(self):
            if self.authorized(['']):
                self.reply(200, form_page, 'text/html; charset=utf-8')

        def do_POST(self):
            nonlocal answers
            if not self.authorized(['submit', 'browse', 'memos', 'upload']):
                return
            try:
                self.check_deadline()
                upload = self.path.endswith('/upload')
                length = self.content_length(upload)
                if length > (MAX_UPLOAD if upload else MAX_BODY):
                    return self.reply(413, {'error': '上傳檔案過大' if upload else '表單內容過大'})
                if upload:
                    return self.reply(200, self.upload(length))
                data = json.loads(b''.join(self.read_chunks(length)) or b'{}')
                if not isinstance(data, dict):
                    raise ValueError('表單內容格式錯誤')
                self.check_deadline()
                if self.path.endswith('/browse'):
                    return self.reply(200, {'paths': browse(data.get('kind'), remaining())})
                if self.path.endswith('/memos'):
                    try:
                        refreshed = memo_records(load_memos())
                    except Exception as error:
                        return self.reply(500, {'error': memo_error(error)})
                    self.check_deadline()
                    registry.update({memo['id']: memo for memo in refreshed})
                    return self.reply(200, {'memos': refreshed[:20], 'total': len(refreshed)})
                result = normalize(data, memos, memo_registry=registry, uploads=uploads)
                uploaded_paths = {item['path'] for item in uploads.values()}
                for index, source in enumerate(result['sources']):
                    try:
                        # Older answers may legitimately reference completed copies in inputs.
                        candidate = os.path.abspath(os.path.expanduser(source['path']))
                        if candidate in partial_paths:
                            raise ValueError('上傳尚未完成或已失效')
                        if source['kind'] == 'voice_memo' or source['path'] in uploaded_paths:
                            require_readable(source['path'])
                        else:
                            require_local_path(source['path'])
                    except ValueError as error:
                        # Emitted only before any answers write begins.
                        return self.reply(400, {'error': f'第 {index + 1} 個來源：{error}',
                                                'code': 'invalid_source', 'saved': False,
                                                'source_index': index})
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=out.parent,
                                                     prefix='.wordprint-answers-', delete=False) as file:
                        temporary = Path(file.name)
                        file.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
                    self.check_deadline()
                    os.replace(temporary, out)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                answers = result
                self.reply(200, {'ok': True})
            except (ValueError, AttributeError) as error:
                self.reply(400, {'error': str(error)})
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except TimeoutError:
                self.reply(408, {'error': '讀取逾時或表單已逾時'})
            except OSError:
                message = ('無法保存錄音，請確認本機儲存空間與權限。' if self.path.endswith('/upload') else
                           '無法開啟系統選擇器，請改用「加入錄音」或填入本機路徑。' if self.path.endswith('/browse') else
                           '無法保存設定，請確認工作資料夾與權限。')
                self.reply(500, {'error': message})

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        url = f'http://127.0.0.1:{server.server_address[1]}/{token}/'
        if not open_browser:
            print(f'form: {url}', file=sys.stderr, flush=True)
        elif not webbrowser.open(url):
            print(f'瀏覽器沒有自動開啟，請手動開啟：{url}', file=sys.stderr, flush=True)
        while answers is None and deadline > time.monotonic():
            server.timeout = remaining()
            server.handle_request()
    if answers is None and uploads:
        print(f'表單逾時；已保留 {len(uploads)} 份完成上傳的錄音與 JSON receipt：'
              f'{(out.parent / "inputs").absolute()}', file=sys.stderr, flush=True)
    return answers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memos', type=Path, help='voice_memos.py output; omit when unavailable')
    parser.add_argument('--prefill', type=Path, help='partial canonical answers JSON to prefill')
    parser.add_argument('--out', type=Path, required=True, help='answers.json to write')
    parser.add_argument('--timeout', type=float, default=600, help='seconds to wait for submit')
    parser.add_argument('--no-open', action='store_true', help='print the URL (with its token) to stderr instead of opening a browser')
    parser.add_argument('--mode', choices=('collect', 'run'), default='collect', help='presentation only; standalone forms collect settings')
    args = parser.parse_args()
    memos = json.loads(args.memos.read_text(encoding='utf-8')) if args.memos else []
    prefill = json.loads(args.prefill.read_text(encoding='utf-8')) if args.prefill else None
    answers = serve(memos, args.out, args.timeout, not args.no_open, prefill, args.mode)
    if answers is None:
        print(QUESTIONS)
        return 2
    print(json.dumps(answers, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

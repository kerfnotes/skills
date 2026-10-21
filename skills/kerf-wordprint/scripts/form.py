#!/usr/bin/env python3
"""One-page local form that collects every Wordprint choice at once and writes answers.json.

Serves on 127.0.0.1 behind a random token, one request at a time, opens the browser, waits for one submit, prints the
answers JSON and exits 0. When the --timeout deadline passes, exits 2 and prints the same questions for a text fallback.
The tokened URL reaches stderr only with --no-open or when the browser fails to open.
"""
import argparse
import html
import importlib.util
import json
import re
import secrets
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ENGINES = {'qwen-0.6b': 'Qwen 0.6B：最快、堪用（本機）',
           'qwen-1.7b': 'Qwen 1.7B：慢 2～3 倍、較準（本機）',
           'gemini-3.5-transcribe': 'Gemini 3.5 Transcribe：最快最準；會上傳 Google 並計費；含說話者每段 30 分鐘，更長自動切段',
           'colab': 'Colab：在 Google Colab GPU 跑 Qwen；整段錄音一次分說話者，長的多人錄音 ID 前後一致（Gemini 每 25 分鐘、本機每 20 分鐘各自編號）；速度與準確度未實測；Google 登入、本機免安裝；分說話者需 Hugging Face token'}
SUMMARIES = {'meeting': '會議', 'interview': '訪談', 'lecture': '演講／課程', 'none': '不要摘要', 'custom': '自訂'}
QUESTIONS = """表單逾時，請改用文字逐題問使用者：
1. 要轉哪些錄音？（語音備忘錄最近幾則，或本機檔案／資料夾路徑；多個時問是否合併成一段）
2. 引擎：qwen-0.6b（預設；最快、堪用）／qwen-1.7b（慢 2～3 倍、較準）／gemini-3.5-transcribe（最快最準；會上傳 Google 並計費；含說話者每段 30 分鐘，更長自動切段）／colab（在 Google Colab GPU 跑 Qwen；整段一次分說話者，長的多人錄音 ID 前後一致；速度與準確度未實測；Google 登入、本機免安裝；分說話者需 Hugging Face token）
3. 參與者名單（可略；只當候選名單，不直接指派給說話者）
4. 摘要：meeting（預設）／interview／lecture／none／custom（請說明要什麼）
5. 收件人 email（可略）；要不要開 Mail 草稿（預設不要）"""
SPLIT = re.compile(r'[,，、;；\n]+')
MAX_BODY = 1024 * 1024


def theme_css():
    spec = importlib.util.spec_from_file_location('wordprint_transcript', Path(__file__).with_name('transcript.py'))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper.clayprint_css()


def normalize(data, memos):
    """Build the fixed answers.json shape; memo choices arrive as indices so paths come from the server's list."""
    if not isinstance(data, dict):
        raise ValueError('表單內容格式錯誤')
    sources = []
    for index in data.get('memos', []):
        if type(index) is not int or not 0 <= index < len(memos):
            raise ValueError('語音備忘錄選項無效')
        sources.append({'kind': 'voice_memo', 'path': memos[index]['path'], 'title': memos[index]['title']})
    for line in str(data.get('paths', '')).splitlines():
        if line.strip():
            path = line.strip()
            sources.append({'kind': 'path', 'path': path, 'title': Path(path).name})
    if not sources:
        raise ValueError('請至少選一個錄音或填一個路徑')
    engine, summary = data.get('engine', 'qwen-0.6b'), data.get('summary', 'meeting')
    if engine not in ENGINES or summary not in SUMMARIES:
        raise ValueError('引擎或摘要選項無效')
    return {'sources': sources, 'merge': bool(data.get('merge')) and len(sources) > 1, 'engine': engine,
            'roster': [n.strip() for n in SPLIT.split(str(data.get('roster', ''))) if n.strip()],
            'summary': summary, 'summary_custom': str(data.get('summary_custom', '')).strip() if summary == 'custom' else '',
            'recipients': [r for r in re.split(r'[\s,;，；]+', str(data.get('recipients', ''))) if r],
            'mail': bool(data.get('mail'))}


def browse(kind, timeout):
    """POSIX paths from the native macOS picker, or [] when the user cancels or the form's deadline closes it."""
    script = ('POSIX path of (choose folder)' if kind == 'folder' else
              'set out to ""\nrepeat with f in (choose file with multiple selections allowed)\n'
              'set out to out & POSIX path of f & linefeed\nend repeat\nreturn out')
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else []


def page(memos, css):
    rows = []
    for i, memo in enumerate(memos[:20]):
        minutes, seconds = divmod(round(memo.get('duration') or 0), 60)
        when = (memo.get('recorded_at') or '')[:16].replace('T', ' ')
        rows.append(f'<label class="memo"><input type="checkbox" name="memo" value="{i}"{" checked" if i == 0 else ""}>'
                    f'<span>{html.escape(memo["title"])}</span><small>{html.escape(when)}・{minutes}:{seconds:02}</small></label>')
    memo_html = '\n'.join(rows) or '<p class="hint">沒有讀到語音備忘錄；請用下方路徑。</p>'
    engines = ''.join(f'<label><input type="radio" name="engine" value="{k}"{" checked" if k == "qwen-0.6b" else ""}> {html.escape(v)}</label>'
                      for k, v in ENGINES.items())
    summaries = ''.join(f'<label><input type="radio" name="summary" value="{k}"{" checked" if k == "meeting" else ""}> {html.escape(v)}</label>'
                        for k, v in SUMMARIES.items())
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wordprint</title>
<style id="clayprint-theme">
{css}
</style>
<style>
fieldset {{ margin: 28px 0 0; padding: 0 0 20px; border: 0; border-bottom: 1px solid var(--cp-line); }}
legend {{ padding: 0; margin-bottom: 10px; color: var(--cp-title); font-size: var(--cp-sub); font-weight: 700; }}
[hidden] {{ display: none !important; }}
label {{ display: block; padding: 4px 0; }}
.memo {{ display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: baseline; border-bottom: 1px solid var(--cp-line); }}
.memo small, .hint {{ color: var(--cp-muted); font-size: var(--cp-small); }}
.memos {{ max-height: 320px; overflow-y: auto; }}
textarea, input[type=text], input[type=email] {{ box-sizing: border-box; width: 100%; font: inherit; padding: 8px; border: 1px solid var(--cp-line, #bbb); border-radius: 4px; background: #fff; }}
button {{ font: inherit; padding: 8px 16px; border: 1px solid var(--cp-accent, #C2553A); border-radius: 4px; background: none; color: var(--cp-accent, #C2553A); cursor: pointer; }}
button.primary {{ margin-top: 28px; background: var(--cp-accent, #C2553A); color: #fff; }}
.row {{ display: flex; gap: 10px; margin-top: 8px; }}
#error {{ color: var(--cp-accent); font-weight: 700; }}
</style>
</head>
<body>
<main>
<header class="report-cover"><p class="eyebrow">Wordprint</p><h1>這次要轉什麼？</h1>
<p>一次選好，送出後回到 agent 視窗即可。</p></header>
<form id="form">
<fieldset><legend>錄音</legend>
<div class="memos">{memo_html}</div>
<p class="hint">或填本機路徑，一行一個：</p>
<textarea id="paths" rows="3"></textarea>
<div class="row"><button type="button" data-browse="file">瀏覽檔案…</button><button type="button" data-browse="folder">瀏覽資料夾…</button></div>
<label id="merge-row" hidden><input type="checkbox" id="merge"> 合併成一段（依上方順序）</label>
</fieldset>
<fieldset><legend>引擎</legend>{engines}</fieldset>
<fieldset><legend>參與者（可略）</legend>
<input type="text" id="roster" placeholder="王小明, 陳大華">
<p class="hint">只當候選名單；不會直接把名字指派給某個聲音。</p></fieldset>
<fieldset><legend>摘要</legend>{summaries}
<textarea id="summary_custom" rows="2" placeholder="自訂時，說明要什麼樣的摘要" hidden></textarea></fieldset>
<fieldset><legend>寄送</legend>
<input type="text" id="recipients" placeholder="收件人 email，可多個">
<label><input type="checkbox" id="mail"> 開 Mail 草稿（只建草稿，不會寄出）</label></fieldset>
<p id="error" role="alert"></p>
<button type="submit" class="primary">送出</button>
</form>
</main>
<script>
const $ = (id) => document.getElementById(id);
const count = () => document.querySelectorAll('input[name=memo]:checked').length + $('paths').value.split('\\n').filter((l) => l.trim()).length;
const sync = () => {{
  $('merge-row').hidden = count() < 2;
  $('summary_custom').hidden = document.querySelector('input[name=summary]:checked').value !== 'custom';
}};
document.addEventListener('input', sync);
document.addEventListener('change', sync);
document.querySelectorAll('[data-browse]').forEach((button) => button.addEventListener('click', async () => {{
  const response = await fetch('browse', {{ method: 'POST', body: JSON.stringify({{ kind: button.dataset.browse }}) }});
  const {{ paths }} = await response.json();
  if (paths.length) $('paths').value = ($('paths').value.trim() ? $('paths').value.trim() + '\\n' : '') + paths.join('\\n');
  sync();
}}));
$('form').addEventListener('submit', async (event) => {{
  event.preventDefault();
  const answers = {{
    memos: [...document.querySelectorAll('input[name=memo]:checked')].map((box) => Number(box.value)),
    paths: $('paths').value, merge: $('merge').checked,
    engine: document.querySelector('input[name=engine]:checked').value,
    roster: $('roster').value, summary: document.querySelector('input[name=summary]:checked').value,
    summary_custom: $('summary_custom').value, recipients: $('recipients').value, mail: $('mail').checked,
  }};
  const response = await fetch('submit', {{ method: 'POST', body: JSON.stringify(answers) }});
  const result = await response.json();
  if (!response.ok) {{ $('error').textContent = result.error; return; }}
  document.body.innerHTML = '<main><header class="report-cover"><h1>已送出</h1><p>可以關閉這個分頁，回到 agent 視窗。</p></header></main>';
}});
sync();
</script>
</body>
</html>
"""


def serve(memos, out, timeout, open_browser=True):
    deadline = time.monotonic() + timeout
    remaining = lambda: max(0.05, deadline - time.monotonic())
    token = secrets.token_urlsafe(16)
    form_page = page(memos, theme_css()).encode('utf-8')
    answers = None

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            # Socket read timeout: an idle browser preconnect holds the single thread for at most 5 s.
            self.timeout = min(5, remaining())
            super().setup()

        def log_message(self, *_):
            pass

        def reply(self, code, body, kind='application/json; charset=utf-8'):
            body = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == f'/{token}/':
                self.reply(200, form_page, 'text/html; charset=utf-8')
            else:
                self.reply(404, {'error': 'not found'})

        def do_POST(self):
            nonlocal answers
            if self.path not in (f'/{token}/submit', f'/{token}/browse'):
                return self.reply(404, {'error': 'not found'})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 <= length <= MAX_BODY:
                    return self.reply(413, {'error': '表單內容過大'})
                data = json.loads(self.rfile.read(length) or b'{}')
                if self.path.endswith('/browse'):
                    return self.reply(200, {'paths': browse(data.get('kind'), remaining())})
                if time.monotonic() >= deadline:
                    raise ValueError('表單已逾時')
                result = normalize(data, memos)
                Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                answers = result
                self.reply(200, {'ok': True})
            except (ValueError, AttributeError) as error:
                self.reply(400, {'error': str(error)})
            except TimeoutError:
                self.close_connection = True

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        url = f'http://127.0.0.1:{server.server_address[1]}/{token}/'
        if not open_browser:
            print(f'form: {url}', file=sys.stderr, flush=True)
        elif not webbrowser.open(url):
            print(f'瀏覽器沒有自動開啟，請手動開啟：{url}', file=sys.stderr, flush=True)
        while answers is None and deadline > time.monotonic():
            server.timeout = remaining()
            server.handle_request()
    return answers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memos', type=Path, help='voice_memos.py output; omit when unavailable')
    parser.add_argument('--out', type=Path, required=True, help='answers.json to write')
    parser.add_argument('--timeout', type=float, default=600, help='seconds to wait for submit')
    parser.add_argument('--no-open', action='store_true', help='print the URL (with its token) to stderr instead of opening a browser')
    args = parser.parse_args()
    memos = json.loads(args.memos.read_text(encoding='utf-8')) if args.memos else []
    answers = serve(memos, args.out, args.timeout, not args.no_open)
    if answers is None:
        print(QUESTIONS)
        return 2
    print(json.dumps(answers, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

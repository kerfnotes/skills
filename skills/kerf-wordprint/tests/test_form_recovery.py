"""Recovery through the real localhost form and Chrome DOM; synthetic sources only."""
from contextlib import closing
import importlib.util
import http.client
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import unquote, urlsplit

CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
ROOT = Path(__file__).parents[1]
HAS_PLAYWRIGHT = importlib.util.find_spec('playwright') is not None


@unittest.skipUnless(HAS_PLAYWRIGHT and CHROME.is_file(), 'Installed Playwright and Chrome required')
class FormRecoveryTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        temp = tempfile.TemporaryDirectory(prefix='wordprint-recovery-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.audio = self.root / 'first.wav'
        self.audio.write_bytes(b'synthetic recording bytes')
        self.second = self.root / 'second.wav'
        self.second.write_bytes(b'second synthetic recording')
        self.folder = self.root / 'folder'
        self.folder.mkdir()
        (self.folder / 'part-one.wav').write_bytes(b'synthetic folder recording one')
        (self.folder / 'part-two.wav').write_bytes(b'synthetic folder recording two')
        self.out = self.root / 'answers.json'
        memos = self.root / 'synthetic-memos.json'
        memos.write_text(json.dumps([
            {'title': '合成備忘錄', 'path': str(self.second), 'duration': 67,
             'recorded_at': '2026-10-24T09:00:00+08:00'},
            {'title': '合成缺檔', 'path': str(self.root / 'absent.m4a'), 'duration': 0}]))
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / 'scripts/form.py'), '--out', str(self.out),
             '--memos', str(memos), '--no-open', '--timeout', '90'],
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_server)
        self.url = self.process.stderr.readline().strip().removeprefix('form: ')
        self.assertTrue(self.url.startswith('http://127.0.0.1:'))
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={'width': 390, 'height': 844})
        self.page.set_default_timeout(5000)
        # Fail closed at the external metadata boundary: never enumerate the real DB.
        self.page.route('**/memos', lambda route: route.fulfill(json={'memos': [], 'total': 0}))
        self.page.goto(self.url)
        self.assertEqual(self.page.evaluate('innerWidth'), 390)

    def stop_server(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.communicate(timeout=5)

    def add_path(self, path):
        self.page.locator('#more-sources').evaluate('(el) => el.open = true')
        self.page.locator('#paths').fill(str(path))
        self.page.locator('#add-paths').click()

    def wait_status(self, index, status):
        self.page.wait_for_function(
            '([index, status]) => document.querySelectorAll("#source-list li")[index]?.dataset.status === status',
            arg=[index, status])

    def capture(self, name):
        if directory := os.environ.get('WORDPRINT_RECOVERY_ARTIFACTS'):
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(target / f'{name}.png'), full_page=True)

    def test_partial_failure_blocks_submit_and_retries_only_failed_source(self):
        attempts = []

        def upload(route):
            name = unquote(route.request.headers['x-file-name'])
            attempts.append(name)
            if name == 'second.wav' and attempts.count(name) == 1:
                route.fulfill(status=500, json={'error': 'synthetic upload failure'})
            else:
                route.continue_()

        self.page.route('**/upload', upload)
        self.page.locator('#files').set_input_files([self.audio, self.second])
        self.wait_status(1, 'failed')
        self.assertTrue(self.page.locator('#submit').is_disabled())
        self.page.get_by_role('button', name='重試：second.wav', exact=True).click()
        self.wait_status(1, 'done')
        self.assertEqual(attempts, ['first.wav', 'second.wav', 'second.wav'])
        self.page.locator('#submit').click()
        self.page.locator('#success').wait_for(state='visible')
        answers = json.loads(self.out.read_text())
        self.assertEqual([Path(s['path']).read_bytes() for s in answers['sources']],
                         [self.audio.read_bytes(), self.second.read_bytes()])

    def test_uncertain_submit_requires_task_check_even_after_reload(self):
        self.add_path(self.audio)
        attempts = []

        def uncertain(route):
            attempts.append(route.request.post_data_json)
            route.abort('connectionreset')

        self.page.route('**/submit', uncertain)
        self.page.locator('#submit').click()
        self.page.locator('#error').filter(has_text='先查看 agent').wait_for()
        self.assertTrue(self.page.locator('#submit').is_disabled())
        self.assertIn('核對任務', self.page.locator('#submit-status').inner_text())
        self.page.reload()
        self.assertTrue(self.page.locator('#submit').is_disabled())
        self.assertIn('核對任務', self.page.locator('#submit-status').inner_text())
        self.page.locator('#form').evaluate('(el) => el.requestSubmit()')
        self.page.wait_for_timeout(100)
        self.assertEqual(len(attempts), 1)
        self.assertFalse(self.out.exists())

    def test_invalid_path_keeps_uploaded_copy_then_corrects_and_submits(self):
        attempts = []
        self.page.on('request', lambda request: attempts.append(request.url.rsplit('/', 1)[-1]))
        self.page.locator('#files').set_input_files(self.audio)
        self.wait_status(0, 'done')
        self.add_path(self.root / 'missing.wav')
        self.page.locator('input[name=engine][value="qwen-1.7b"]').check()
        self.page.locator('input[name=summary][value=none]').check()
        self.page.locator('#submit').click()
        self.page.locator('#sources-error').filter(has_text='第 2 個來源').wait_for()
        self.assertFalse(self.out.exists())
        self.assertTrue(self.page.locator('#form').is_visible())
        remove = self.page.get_by_role('button', name='移除：missing.wav', exact=True)
        self.assertTrue(remove.evaluate('(el) => document.activeElement === el'))
        self.capture('invalid-path-390')
        remove.click()
        self.add_path(self.second)
        self.capture('corrected-path-390')
        self.page.locator('#submit').click()
        self.page.locator('#success').wait_for(state='visible')
        self.capture('success-390')
        answers = json.loads(self.out.read_text())
        self.assertEqual((answers['engine'], answers['summary'], answers['mail']),
                         ('qwen-1.7b', 'none', False))
        self.assertEqual(len(answers['sources']), 2)
        self.assertEqual(Path(answers['sources'][0]['path']).read_bytes(), self.audio.read_bytes())
        self.assertEqual(answers['sources'][1]['path'], str(self.second))
        self.assertEqual(attempts.count('upload'), 1)
        self.assertEqual(self.page.evaluate('sessionStorage.length'), 0)

    def test_oversize_file_reveals_native_picker_without_uploading(self):
        large = self.root / 'large.wav'
        with large.open('wb') as file:
            file.truncate(1024 ** 3 + 1)
        self.page.locator('#files').set_input_files(large)
        self.assertIn('選擇本機檔案', self.page.locator('#upload-error').inner_text())
        native = self.page.locator('[data-browse=file]')
        self.assertTrue(native.is_visible())
        self.assertTrue(native.evaluate('(el) => el === document.activeElement'))
        self.assertEqual(self.page.locator('#source-list li').count(), 0)
        self.assertEqual(large.stat().st_size, 1024 ** 3 + 1)

    def test_transferred_bytes_wait_for_server_confirmation(self):
        # Real socket backpressure at the HTTP boundary. Browser routing holds the
        # request before transmission, so it cannot prove native upload progress.
        upstream = urlsplit(self.url)
        received, release = threading.Event(), threading.Event()

        class DelayUpload(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def relay(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if self.path.endswith('/upload'):
                    received.set()
                    if not release.wait(10):
                        self.send_error(504)
                        return
                headers = {**dict(self.headers), 'Host': upstream.netloc,
                           'Origin': f'http://{upstream.netloc}'}
                with closing(http.client.HTTPConnection(upstream.netloc, timeout=10)) as connection:
                    connection.request(self.command, self.path, body=body, headers=headers)
                    response = connection.getresponse()
                    data = response.read()
                    self.send_response(response.status)
                    for key in ('Content-Type', 'Cache-Control'):
                        if value := response.getheader(key):
                            self.send_header(key, value)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            do_GET = do_POST = relay

        proxy = HTTPServer(('127.0.0.1', 0), DelayUpload)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()

        def stop_proxy():
            release.set()
            proxy.shutdown()
            thread.join(timeout=5)
            proxy.server_close()

        self.addCleanup(stop_proxy)
        self.page.goto(f'http://127.0.0.1:{proxy.server_port}{upstream.path}')
        self.page.locator('#files').set_input_files(self.audio)
        self.page.wait_for_function('document.querySelector("progress")?.value === 100')
        self.assertTrue(received.is_set())
        self.assertIn('正在確認檔案', self.page.locator('.upload-detail').inner_text())
        self.assertTrue(self.page.locator('#submit').is_disabled())
        self.assertFalse(self.out.exists())
        self.capture('confirming-390')
        release.set()
        self.wait_status(0, 'done')
        self.assertFalse(self.page.locator('#submit').is_disabled())

    def test_reload_reselection_preserves_order_settings_and_saved_copy(self):
        self.add_path(self.folder)
        self.page.locator('#merge').check()
        self.page.locator('input[name=engine][value="qwen-1.7b"]').check()
        self.page.locator('input[name=summary][value=none]').check()
        self.page.route('**/upload', lambda route: route.fulfill(status=500, json={'error': 'synthetic failure'})
                        if unquote(route.request.headers['x-file-name']) == 'second.wav' else route.continue_())
        self.page.locator('#files').set_input_files([self.audio, self.second])
        self.wait_status(2, 'failed')
        saved_copies = list((self.root / 'inputs').glob('*.wav'))
        self.assertEqual(len(saved_copies), 1)
        self.page.reload()
        self.wait_status(2, 'needs-selection')
        self.assertTrue(self.page.locator('#submit').is_disabled())
        self.page.unroute('**/upload')
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button', name='重新選取：second.wav', exact=True).click()
        chooser.value.set_files(self.second)
        self.wait_status(2, 'done')
        self.assertIn('1. folder', self.page.locator('#source-list li').nth(0).inner_text())
        self.assertIn('2. first.wav', self.page.locator('#source-list li').nth(1).inner_text())
        self.assertIn('3. second.wav', self.page.locator('#source-list li').nth(2).inner_text())
        self.page.get_by_role('button', name='移除：first.wav', exact=True).click()
        self.page.get_by_role('button', name='移除：second.wav', exact=True).click()
        self.assertTrue(saved_copies[0].exists())
        self.assertTrue(self.page.locator('#merge-row').is_visible())
        self.assertTrue(self.page.locator('#merge').is_checked())
        self.page.locator('#submit').click()
        self.page.locator('#success').wait_for(state='visible')
        answers = json.loads(self.out.read_text())
        self.assertEqual((answers['merge'], answers['engine'], answers['summary'], answers['mail']),
                         (True, 'qwen-1.7b', 'none', False))
        self.assertEqual([source['path'] for source in answers['sources']], [str(self.folder)])

    def test_memo_states_mixed_order_and_stable_id_deduplication(self):
        self.page.locator('#read-memos').click()
        self.page.locator('#memo-status').filter(has_text='沒有可列出').wait_for()
        self.assertIn('沒有可列出', self.page.locator('#memo-status').inner_text())
        self.page.unroute('**/memos')
        self.page.route('**/memos', lambda route: route.fulfill(status=500, json={'error': '無權讀取語音備忘錄，請匯出錄音後加入'}))
        self.page.locator('#read-memos').click()
        self.page.locator('#memo-error').filter(has_text='無權讀取').wait_for()
        self.assertIn('無權讀取', self.page.locator('#memo-error').inner_text())
        metadata = [{'id': hashlib.sha256(os.fsencode(self.second)).hexdigest(), 'title': '合成備忘錄', 'path': str(self.second),
                     'availability': 'local', 'duration': 67, 'recorded_at': '2026-10-24T09:00:00+08:00'},
                    {'id': 'missing-stable', 'title': '合成缺檔', 'path': str(self.root / 'absent.m4a'),
                     'availability': 'missing', 'duration': 0}]
        self.page.unroute('**/memos')
        self.page.route('**/memos', lambda route: route.fulfill(json={'memos': metadata, 'total': 2}))
        self.page.locator('#read-memos').click()
        self.page.locator('#memo-status').filter(has_text='顯示最近 2').wait_for()
        self.assertIn('不在這台 Mac', self.page.locator('#memo-list').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='加入：合成缺檔', exact=True).is_disabled())
        self.add_path(self.folder)
        self.page.get_by_role('button', name='加入：合成備忘錄', exact=True).click()
        self.page.locator('#files').set_input_files(self.audio)
        self.wait_status(2, 'done')
        self.page.get_by_role('button', name='上移：first.wav', exact=True).focus()
        self.page.keyboard.press('Enter')
        self.page.locator('#read-memos').click()
        self.page.locator('#memo-status').filter(has_text='顯示最近 2').wait_for()
        self.assertTrue(self.page.get_by_role('button', name='加入：合成備忘錄', exact=True).is_disabled())
        self.page.reload()
        self.page.locator('#read-memos').click()
        self.page.locator('#memo-status').filter(has_text='顯示最近 2').wait_for()
        self.assertEqual(self.page.locator('#source-list li').count(), 3)
        self.assertTrue(self.page.get_by_role('button', name='加入：合成備忘錄', exact=True).is_disabled())
        self.page.locator('#submit').click()
        self.page.locator('#success').wait_for(state='visible')
        answers = json.loads(self.out.read_text())
        self.assertEqual(answers['sources'][0]['path'], str(self.folder))
        self.assertEqual(answers['sources'][2], {'kind': 'voice_memo', 'path': str(self.second), 'title': '合成備忘錄'})
        self.assertEqual(Path(answers['sources'][1]['path']).read_bytes(), self.audio.read_bytes())

    def test_blocked_storage_still_submits_and_source_layout_fits_viewports(self):
        self.page.add_init_script("Object.defineProperty(window, 'sessionStorage', {get() {throw new Error('blocked');}})")
        self.page.reload()
        self.add_path(self.folder)
        self.assertIn('無法恢復', self.page.locator('#draft-status').inner_text())
        long_audio = self.root / ('很長的合成錄音名稱 Long recording ' * 3 + '.wav')
        long_audio.write_bytes(b'synthetic long filename')
        self.page.locator('#files').set_input_files(long_audio)
        self.wait_status(1, 'done')
        measurements = []
        for width in (320, 375, 390, 728, 1280):
            self.page.set_viewport_size({'width': width, 'height': 844})
            measurement = self.page.evaluate('''() => ({width: innerWidth,
                overflow: document.documentElement.scrollWidth > innerWidth,
                bodySize: getComputedStyle(document.body).fontSize})''')
            self.assertEqual(measurement['width'], width)
            self.assertFalse(measurement['overflow'])
            self.assertEqual(measurement['bodySize'], '16px')
            measurements.append(measurement)
            if width in (320, 390, 1280):
                self.capture(f'sources-{width}')
        if directory := os.environ.get('WORDPRINT_RECOVERY_ARTIFACTS'):
            (Path(directory) / 'viewport-measurements.json').write_text(json.dumps(measurements, indent=2))
        self.page.locator('#submit').focus()
        self.page.keyboard.press('Enter')
        self.page.locator('#success').wait_for(state='visible')
        self.assertEqual(len(json.loads(self.out.read_text())['sources']), 2)


if __name__ == '__main__':
    unittest.main()

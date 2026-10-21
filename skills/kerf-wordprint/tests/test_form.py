"""Drive form.py over HTTP the way the browser page does."""
import contextlib
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'form.py'


def load_form():
    spec = importlib.util.spec_from_file_location('wordprint_form', SCRIPT)
    form = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(form)
    return form


class FormTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.memos = self.root / 'memos.json'
        self.memos.write_text(json.dumps([
            {'title': '週會 <新>', 'recorded_at': '2026-10-20T09:00:00+08:00', 'duration': 65.0, 'path': '/memos/a.m4a'},
            {'title': '訪談', 'recorded_at': '2026-10-19T09:00:00+08:00', 'duration': 30.0, 'path': '/memos/b.qta'},
        ], ensure_ascii=False), encoding='utf-8')
        self.out = self.root / 'answers.json'

    def start(self, timeout='30'):
        process = subprocess.Popen([sys.executable, str(SCRIPT), '--memos', str(self.memos), '--out', str(self.out),
                                    '--timeout', timeout, '--no-open'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(lambda: process.poll() is None and process.kill())
        url = process.stderr.readline().strip().removeprefix('form: ')
        return process, url

    def post(self, url, body):
        request = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_submit_writes_fixed_answers_shape(self):
        process, url = self.start()
        with urllib.request.urlopen(url, timeout=10) as response:
            page = response.read().decode()
        self.assertIn('週會 &lt;新&gt;', page)
        self.assertIn('value="0" checked', page)
        self.assertIn('--cp-accent', page)
        base = url.rsplit('/', 2)[0]
        self.assertEqual(self.post(base + '/wrong-token/submit', {})[0], 404)
        self.assertEqual(self.post(url + 'submit', {'memos': [], 'paths': ''})[0], 400)
        self.assertEqual(self.post(url + 'submit', {'memos': [9]})[0], 400)
        self.assertEqual(self.post(url + 'submit', {'memos': [0], 'engine': 'cloud'})[0], 400)
        oversized = urllib.request.Request(url + 'submit', data=b'{}', method='POST', headers={'Content-Length': str(2 << 20)})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(oversized, timeout=10)
        self.assertEqual(caught.exception.code, 413)
        caught.exception.close()
        status, _ = self.post(url + 'submit', {
            'memos': [1], 'paths': '/tmp/會議 錄音.wav\n\n', 'merge': True, 'engine': 'qwen-1.7b',
            'roster': '王小明，陳大華、 ', 'summary': 'custom', 'summary_custom': '只要行動項目',
            'recipients': 'a@example.com; b@example.com', 'mail': False})
        self.assertEqual(status, 200)
        stdout, _ = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        expected = {'sources': [{'kind': 'voice_memo', 'path': '/memos/b.qta', 'title': '訪談'},
                                {'kind': 'path', 'path': '/tmp/會議 錄音.wav', 'title': '會議 錄音.wav'}],
                    'merge': True, 'engine': 'qwen-1.7b', 'roster': ['王小明', '陳大華'], 'summary': 'custom',
                    'summary_custom': '只要行動項目', 'recipients': ['a@example.com', 'b@example.com'], 'mail': False}
        self.assertEqual(json.loads(self.out.read_text(encoding='utf-8')), expected)
        self.assertEqual(json.loads(stdout), expected)

    def test_single_source_never_merges(self):
        process, url = self.start()
        self.assertEqual(self.post(url + 'submit', {'memos': [0], 'merge': True})[0], 200)
        process.communicate(timeout=10)
        answers = json.loads(self.out.read_text(encoding='utf-8'))
        self.assertEqual((answers['merge'], answers['engine'], answers['summary']), (False, 'qwen-0.6b', 'meeting'))

    def test_timeout_prints_questions(self):
        process, _ = self.start(timeout='0.5')
        stdout, _ = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 2)
        self.assertIn('表單逾時', stdout)
        self.assertFalse(self.out.exists())

    def test_stalled_connection_does_not_block_a_later_submit(self):
        process, url = self.start()
        with socket.create_connection(('127.0.0.1', int(url.split(':')[2].split('/')[0]))) as stalled:
            stalled.sendall(b'POST /x HTTP/1.1\r\nContent-Len')  # Like an idle browser preconnect, queued first.
            started = time.monotonic()
            self.assertEqual(self.post(url + 'submit', {'memos': [0]})[0], 200)
        self.assertLess(time.monotonic() - started, 8)
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)

    def test_token_url_reaches_stderr_only_when_the_browser_fails(self):
        form = load_form()
        for opened in (True, False):
            with self.subTest(opened=opened), mock.patch.object(form.webbrowser, 'open', return_value=opened), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertIsNone(form.serve([], self.out, 0.2))
            self.assertEqual('http://127.0.0.1:' in stderr.getvalue(), not opened)
            self.assertEqual('請手動開啟' in stderr.getvalue(), not opened)

if __name__ == '__main__':
    unittest.main()

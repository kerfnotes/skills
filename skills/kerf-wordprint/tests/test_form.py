"""Drive form.py over HTTP the way the browser page does."""
import ast
import contextlib
import importlib.util
import io
import html.parser
import json
import socket
import hashlib
import http.client
import queue
import threading
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'form.py'


def load_form():
    spec = importlib.util.spec_from_file_location('wordprint_form', SCRIPT)
    form = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(form)
    return form


class LocalPathPlatformTests(unittest.TestCase):
    def test_regular_source_without_posix_nonblock_flag(self):
        form = load_form()
        real_os = form.os

        class WithoutNonblock:
            def __getattr__(self, name):
                if name == 'O_NONBLOCK':
                    raise AttributeError(name)
                return getattr(real_os, name)

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'source.wav'
            audio.write_bytes(b'synthetic source')
            with mock.patch.object(form, 'os', WithoutNonblock()):
                form.require_local_path(str(audio))
                form.require_local_path(directory)


class FormTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.memos = self.root / 'memos.json'
        self.audio_a = self.root / 'a.m4a'
        self.audio_b = self.root / 'b.qta'
        self.audio_a.write_bytes(b'synthetic audio a')
        self.audio_b.write_bytes(b'synthetic audio b')
        self.memos.write_text(json.dumps([
            {'title': '週會 <新>', 'recorded_at': '2026-10-20T09:00:00+08:00', 'duration': 65.0, 'path': str(self.audio_a)},
            {'title': '訪談', 'recorded_at': '2026-10-19T09:00:00+08:00', 'duration': 30.0, 'path': str(self.audio_b)},
        ], ensure_ascii=False), encoding='utf-8')
        self.out = self.root / 'answers.json'

    def start(self, timeout='30', prefill=None):
        extra = []
        if prefill is not None:
            prefill_file = self.root / 'request.json'
            prefill_file.write_text(json.dumps(prefill), encoding='utf-8')
            extra = ['--prefill', str(prefill_file)]
        process = subprocess.Popen([sys.executable, str(SCRIPT), '--memos', str(self.memos), '--out', str(self.out),
                                    '--timeout', timeout, '--no-open', *extra],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
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
        state = Controls(page).state
        self.assertEqual(state['memos'][0]['title'], '週會 <新>')
        self.assertEqual(state['sources'], [])
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
            'memos': [1], 'paths': str(self.audio_a) + '\n\n', 'merge': True, 'engine': 'qwen-1.7b',
            'roster': '王小明，陳大華、 ', 'summary': 'custom', 'summary_custom': '只要行動項目',
            'recipients': 'a@example.com; b@example.com', 'mail': False})
        self.assertEqual(status, 200)
        stdout, _ = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        expected = {'sources': [{'kind': 'voice_memo', 'path': str(self.audio_b), 'title': '訪談'},
                                {'kind': 'path', 'path': str(self.audio_a), 'title': self.audio_a.name}],
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

class RecommendedEngineTests(unittest.TestCase):
    def test_rendered_default_and_explicit_model_preserve_custom_sources(self):
        form = load_form()
        self.assertIn('value="qwen-0.6b" checked', form.page([], None))
        source = {'kind': 'path', 'path': '/synthetic/custom.wav', 'title': 'Custom'}
        explicit = {'sources': [source], 'engine': 'qwen-1.7b',
                    'summary': 'custom', 'summary_custom': '保留關鍵決議'}
        page = form.page([], None, prefill=explicit)
        self.assertIn('value="qwen-1.7b" checked', page)
        answer = form.normalize_answers(explicit, complete=False)
        self.assertEqual(answer['sources'], [source])
        self.assertEqual(answer['engine'], 'qwen-1.7b')
        self.assertEqual(answer['summary_custom'], '保留關鍵決議')

    def test_default_stays_local_without_keychain_or_runtime_probe(self):
        form = load_form()
        with mock.patch.dict(form.os.environ, {'GEMINI_API_KEY': 'synthetic-not-a-key'}), \
                mock.patch.object(form.subprocess, 'run', side_effect=AssertionError('unexpected probe')):
            self.assertEqual(form.recommended_engine(), 'qwen-0.6b')


class Controls(html.parser.HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.inputs = []
        self.tags = []
        self.state_text = ''
        self.in_state = False
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == 'script' and dict(attrs).get('id') == 'initial-state':
            self.in_state = True
            assert dict(attrs).get('type') == 'application/json'
        if tag == 'input':
            self.inputs.append(dict(attrs))

    def handle_data(self, data):
        if self.in_state:
            self.state_text += data

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_state = False

    @property
    def state(self):
        return json.loads(self.state_text)

    def checked(self, name):
        return [item for item in self.inputs if item.get('name') == name and 'checked' in item]

    def field(self, id):
        return next(item for item in self.inputs if item.get('id') == id)


class PrefillTests(unittest.TestCase):
    setUp, start, post = FormTests.setUp, FormTests.start, FormTests.post
    def test_canonical_prefill_survives_page_to_submit(self):
        supplied = {
            'sources': [{'kind': 'path', 'path': str(self.audio_a), 'title': '第二段'},
                        {'kind': 'voice_memo', 'path': str(self.audio_b), 'title': '指定訪談'}],
            'merge': False, 'engine': 'qwen-0.6b', 'roster': ['林依蓁', '吳柏翰'],
            'summary': 'none', 'summary_custom': '', 'recipients': ['a@example.com'], 'mail': False,
        }
        process, url = self.start(prefill=supplied)
        with urllib.request.urlopen(url, timeout=10) as response:
            controls = Controls(response.read().decode())
        state = controls.state
        self.assertEqual(state['sources'], supplied['sources'])
        self.assertEqual(state['settings']['engine'], 'qwen-0.6b')
        self.assertEqual(state['settings']['summary'], 'none')
        self.assertFalse(state['settings']['merge'])
        self.assertFalse(state['settings']['mail'])
        payload = {**state['settings'], 'sources': state['sources']}
        self.assertEqual(self.post(url + 'submit', payload)[0], 200)
        process.communicate(timeout=10)
        self.assertEqual(json.loads(self.out.read_text()), supplied)

    def test_custom_brief_missing_is_editable_but_cannot_submit(self):
        process, url = self.start(prefill={'summary': 'custom', 'sources': []})
        with urllib.request.urlopen(url, timeout=10) as response:
            page = response.read().decode()
        self.assertEqual(Controls(page).state['settings']['summary'], 'custom')
        self.assertEqual(Controls(page).state['sources'], [])
        self.assertEqual(self.post(url + 'submit', {'memos': [0], 'summary': 'custom'})[0], 400)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.post(url + 'submit', {'memos': [0], 'summary': 'custom', 'summary_custom': '決議'})[0], 200)
        process.communicate(timeout=10)

    def test_save_failure_can_retry_without_partial_answers(self):
        self.out.mkdir()
        process, url = self.start()
        self.assertEqual(self.post(url + 'submit', {'memos': [0]})[0], 500)
        self.assertTrue(self.out.is_dir())
        self.assertFalse(list(self.root.glob('.wordprint-answers-*')))
        self.out.rmdir()
        self.assertEqual(self.post(url + 'submit', {'memos': [0]})[0], 200)
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)


class NormalizationTests(unittest.TestCase):
    def test_normalization_remains_pure_for_missing_paths(self):
        form = load_form()
        data = {'sources': [{'kind': 'path', 'path': '~/missing-folder'}],
                'merge': True, 'engine': 'qwen-0.6b'}
        with mock.patch.object(Path, 'stat', side_effect=AssertionError('filesystem probe')), \
                mock.patch.object(Path, 'iterdir', side_effect=AssertionError('directory probe')):
            normalized = form.normalize_answers(data)
        self.assertEqual(normalized['sources'][0]['path'], '~/missing-folder')
        self.assertTrue(normalized['merge'])
        self.assertEqual(normalized['engine'], 'qwen-0.6b')

    def setUp(self):
        self.form = load_form()
        self.source = {'kind': 'path', 'path': '/tmp/test.wav', 'title': '測試'}

    def test_normalized_answers_are_idempotent(self):
        answer = self.form.normalize_answers({'sources': [self.source], 'roster': ['林依蓁'],
                                             'recipients': ['a@example.com'], 'engine': 'qwen-1.7b',
                                             'summary': 'none', 'merge': False, 'mail': False})
        self.assertEqual(self.form.normalize(answer, []), answer)
        self.assertEqual(self.form.normalize_answers(answer), answer)
        self.assertEqual(answer['roster'], ['林依蓁'])
        self.assertEqual(answer['engine'], 'qwen-1.7b')
        self.assertEqual(answer['summary'], 'none')

    def test_unchanged_roster_preserves_names_containing_delimiters(self):
        names = ['林依蓁, 主持人', '吳柏翰、紀錄']
        controls = Controls(self.form.page([], '', prefill={'roster': names}))
        self.assertEqual(json.loads(controls.field('roster')['data-values']), names)

    def test_explicit_engine_does_not_probe_machine(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(self.form, 'recommended_engine', side_effect=AssertionError('unneeded probe')), \
                mock.patch.object(self.form.webbrowser, 'open', return_value=True):
            self.assertIsNone(self.form.serve([], Path(directory) / 'answers.json', 0.01,
                                            prefill={'engine': 'qwen-1.7b'}))

    def test_mixed_sources_preserve_order(self):
        memo = {'path': '/memo.wav', 'title': '備忘錄'}
        answer = self.form.normalize({'sources': [self.source], 'memos': [0], 'paths': '/last.wav', 'merge': True}, [memo])
        self.assertEqual([s['path'] for s in answer['sources']], ['/tmp/test.wav', '/memo.wav', '/last.wav'])
        self.assertTrue(answer['merge'])

    def test_rejects_malformed_types_and_string_booleans(self):
        for patch in ({'sources': 'bad'}, {'sources': [1]}, {'sources': [{'kind': 'url', 'path': 'http://x'}]},
                      {'merge': 'false'}, {'mail': 0}, {'roster': [1]}, {'recipients': None},
                      {'engine': []}, {'summary': None}, {'summary_custom': 1}, {'memos': None}, {'paths': []}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.form.normalize({'sources': [self.source], **patch}, [])

    def test_empty_sources_are_not_silently_defaulted(self):
        memo = {'path': '/memo.wav', 'title': '最新錄音'}
        self.assertEqual(Controls(self.form.page([memo], '')).state['sources'], [])
        self.assertEqual(Controls(self.form.page([memo], '', prefill={'sources': []})).state['sources'], [])
        with self.assertRaises(ValueError):
            self.form.normalize_answers({'sources': []})

    def test_prefilled_source_outside_recent_twenty_stays_selected(self):
        memos = [{'path': f'/{i}.wav', 'title': str(i)} for i in range(30)]
        source = {'kind': 'voice_memo', **memos[29]}
        controls = Controls(self.form.page(memos, '', prefill={'sources': [source]}))
        self.assertEqual(controls.state['sources'], [source])
        self.assertEqual(len(controls.state['memos']), 20)

    def test_prefill_escapes_attributes_text_and_template_markers(self):
        attack = '\"/><script>alert(1)</script><textarea>@@CSS@@&'
        source = {'kind': 'path', 'path': '/tmp/' + attack, 'title': attack}
        page = self.form.page([], 'untrusted legacy CSS', prefill={
            'sources': [source], 'roster': [attack], 'summary': 'custom', 'summary_custom': attack,
            'recipients': [attack], 'mail': True,
        })
        controls = Controls(page)
        self.assertEqual(controls.state['sources'], [source])
        self.assertNotIn('<', controls.state_text)
        self.assertEqual(controls.field('roster')['value'], attack)
        self.assertEqual(controls.field('recipients')['value'], attack)
        self.assertEqual(sum(tag == 'script' and attrs.get('id') == 'initial-state'
                             for tag, attrs in controls.tags), 1)
        self.assertNotIn('<script>alert(1)', page)
        self.assertNotIn('untrusted legacy CSS', page)
        self.assertIn('@@CSS@@', page)

    def test_form_has_no_network_resources_and_one_submit(self):
        page = self.form.page([], '', 'gemini-3.5-transcribe')
        controls = Controls(page)
        self.assertEqual(sum(tag == 'button' and attrs.get('type') == 'submit' for tag, attrs in controls.tags), 1)
        self.assertFalse(any(attrs.get('src') or (tag == 'link' and attrs.get('href')) for tag, attrs in controls.tags))
        self.assertNotIn('最快', page)
        self.assertNotIn('最準', page)
        self.assertEqual(controls.state['settings']['engine'], 'gemini-3.5-transcribe')
        self.assertEqual(controls.checked('engine')[0]['value'], 'gemini-3.5-transcribe')

    def test_native_picker_cancel_and_failure_are_bounded(self):
        with mock.patch.object(self.form.platform, 'system', return_value='Darwin'):
            with mock.patch.object(self.form.subprocess, 'run', return_value=mock.Mock(
                    returncode=1, stdout='', stderr='execution error: User canceled. (-128)\n')):
                self.assertEqual(self.form.browse('file', 1), [])
            with mock.patch.object(self.form.subprocess, 'run', side_effect=subprocess.TimeoutExpired('osascript', 1)):
                with self.assertRaises(TimeoutError):
                    self.form.browse('folder', 1)
            with mock.patch.object(self.form.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    self.form.browse('invalid', 1)
                run.assert_not_called()

    def test_native_picker_reports_failure_without_exposing_stderr(self):
        with mock.patch.object(self.form.platform, 'system', return_value='Darwin'):
            for message in ('execution error: /private/synthetic Not authorized (-1743)',
                            'execution error: /private/synthetic Unknown error (-1708)', ''):
                with self.subTest(message=message), mock.patch.object(
                        self.form.subprocess, 'run', return_value=mock.Mock(
                            returncode=1, stdout='', stderr=message)):
                    with self.assertRaisesRegex(ValueError, '選擇器') as error:
                        self.form.browse('file', 1)
                    self.assertNotIn('/private', str(error.exception))


class SourceAPITests(unittest.TestCase):
    setUp, post = FormTests.setUp, FormTests.post

    def start_server(self, *, memos=None, reader=None, timeout=15, prefill=None):
        self.form = load_form()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        urls = queue.Queue()
        self.reader = stack.enter_context(mock.patch.object(
            self.form, 'load_memos', side_effect=reader or AssertionError('real memo access forbidden')))
        stack.enter_context(mock.patch.object(self.form.webbrowser, 'open',
                                             side_effect=lambda url: urls.put(url) or True))
        self.results, self.errors = [], []
        def run():
            try:
                self.results.append(self.form.serve(memos or [], self.out, timeout, prefill=prefill))
            except BaseException as error:
                self.errors.append(error)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            self.url = urls.get(timeout=3)
        except queue.Empty:
            thread.join(timeout=1)
            self.fail(f'synthetic server failed to start: {self.errors!r}')
        self.thread = thread
        def cleanup():
            if thread.is_alive():
                try:
                    self.post(self.url + 'submit', {'sources': [{'kind': 'path', 'path': str(self.audio_b)}]})
                except OSError:
                    pass
            thread.join(timeout=6)
            stack.close()
            self.assertFalse(thread.is_alive(), 'synthetic server did not stop')
            self.assertFalse(self.errors)
        self.addCleanup(cleanup)
        return self.url

    def request(self, route, data=b'', headers=None, method='POST'):
        target = urllib.parse.urlsplit(self.url)
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=8)
        try:
            connection.request(method, target.path + route, body=data, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if 'json' in response.getheader('Content-Type', '') else body
        finally:
            connection.close()

    def upload(self, data=b'synthetic audio', name='錄音.wav', headers=None):
        return self.request('upload', data, {'X-File-Name': urllib.parse.quote(name, safe=''), **(headers or {})})

    def test_missing_path_http_recovery_preserves_upload_and_settings(self):
        self.start_server()
        _, upload = self.upload()
        data = {'sources': [{'upload_id': upload['id']},
                            {'kind': 'path', 'path': str(self.root / 'missing.wav')}],
                'engine': 'qwen-0.6b', 'merge': True, 'summary': 'custom',
                'summary_custom': '待辦', 'roster': ['甲'], 'mail': False}
        status, body = self.post(self.url + 'submit', data)
        self.assertEqual(status, 400)
        self.assertEqual(body['code'], 'invalid_source')
        self.assertIs(body['saved'], False)
        self.assertEqual(body['source_index'], 1)
        self.assertFalse(self.out.exists())
        self.assertTrue(self.thread.is_alive())
        self.assertFalse(list(self.root.glob('.wordprint-answers-*')))
        data['sources'][1]['path'] = str(self.audio_a)
        self.assertEqual(self.post(self.url + 'submit', data)[0], 200)
        saved = json.loads(self.out.read_text())
        for key in ('engine', 'merge', 'summary', 'summary_custom', 'roster', 'mail'):
            self.assertEqual(saved[key], data[key])
        self.assertEqual(len(list((self.root / 'inputs').glob('*.wav'))), 1)
        self.assertEqual(saved['sources'][1]['path'], str(self.audio_a))

    def test_invalid_local_paths_never_save_or_block(self):
        self.start_server()
        empty = self.root / 'empty'
        empty.mkdir()
        (empty / 'notes.txt').write_text('synthetic')
        fifo = self.root / 'pipe.wav'
        self.form.os.mkfifo(fifo)
        unreadable = self.root / 'unreadable.wav'
        unreadable.write_bytes(b'synthetic')
        unreadable.chmod(0)
        sockpath = self.root / 'socket.wav'
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(sockpath))
            for path in (self.root / 'missing.wav', empty, fifo, unreadable, sockpath):
                with self.subTest(path=path.name):
                    started = time.monotonic()
                    status, body = self.post(self.url + 'submit', {'paths': str(path)})
                    self.assertEqual(status, 400)
                    self.assertLess(time.monotonic() - started, 2)
                    self.assertEqual((body['code'], body['saved']), ('invalid_source', False))
                    self.assertFalse(self.out.exists())
        # ACL/access denial is tested independently of the process's uid.
        with mock.patch.object(self.form.os, 'access', return_value=False):
            self.assertEqual(self.post(self.url + 'submit', {'paths': str(self.audio_a)})[0], 400)
        real_open = self.form.os.open
        def denied(path, *args, **kwargs):
            if Path(path) == self.audio_a.resolve():
                raise PermissionError('synthetic ACL denial')
            return real_open(path, *args, **kwargs)
        with mock.patch.object(self.form.os, 'open', side_effect=denied):
            self.assertEqual(self.post(self.url + 'submit', {'paths': str(self.audio_a)})[0], 400)
        self.assertFalse(self.out.exists())

    def test_folder_tilde_symlink_and_file_preserve_merge_intent(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'a.WAV').write_bytes(b'synthetic')
        (folder / 'b.qta').write_bytes(b'synthetic')
        (folder / 'ignored.txt').write_text('synthetic')
        linked = self.root / 'linked.wav'
        linked.symlink_to(self.audio_a)
        linked_folder = self.root / 'linked-folder'
        linked_folder.symlink_to(folder, target_is_directory=True)
        self.start_server()
        with mock.patch.dict(self.form.os.environ, {'HOME': str(self.root)}):
            data = {'sources': [{'kind': 'path', 'path': '~/folder'},
                                {'kind': 'path', 'path': str(linked)},
                                {'kind': 'path', 'path': str(linked_folder)},
                                {'kind': 'path', 'path': str(self.audio_b)}],
                    'merge': True, 'engine': 'qwen-1.7b'}
            self.assertEqual(self.post(self.url + 'submit', data)[0], 200)
        saved = json.loads(self.out.read_text())
        self.assertEqual([s['path'] for s in saved['sources']], [s['path'] for s in data['sources']])
        self.assertTrue(saved['merge'])

    def test_single_folder_merge_and_all_audio_readability(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'good.wav').write_bytes(b'synthetic')
        bad = folder / 'bad.wav'
        bad.write_bytes(b'synthetic')
        bad.chmod(0)
        self.start_server()
        data = {'paths': str(folder), 'merge': True}
        self.assertEqual(self.post(self.url + 'submit', data)[0], 400)
        bad.chmod(0o600)
        self.assertEqual(self.post(self.url + 'submit', data)[0], 200)
        self.assertTrue(json.loads(self.out.read_text())['merge'])

    def test_upload_stream_permissions_hash_and_ordered_submit(self):
        memo = {'path': str(self.audio_a), 'title': '備忘錄'}
        self.start_server(memos=[memo])
        self.reader.assert_not_called()
        content = b'synthetic-only' * 100000  # Exceeds the independent 1 MiB JSON limit.
        status, uploaded = self.upload(content, '../../outside\\惡意<檔名>.QTA')
        self.assertEqual(status, 200)
        self.assertEqual(set(uploaded), {'id', 'title', 'byte_count', 'sha256'})
        self.assertEqual(uploaded['title'], '惡意<檔名>.QTA')
        self.assertEqual(uploaded['byte_count'], len(content))
        self.assertEqual(uploaded['sha256'], hashlib.sha256(content).hexdigest())
        directory = self.root / 'inputs'
        files = list(directory.glob('*.qta'))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, uploaded['id'] + '.qta')
        self.assertEqual(files[0].read_bytes(), content)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        status, _ = self.post(self.url + 'submit', {'sources': [
            {'kind': 'path', 'path': str(self.audio_b), 'title': 'first'},
            {'upload_id': uploaded['id'], 'path': '/attacker.wav', 'title': 'forged', 'sha256': 'fake'},
            {'memo_id': self.form.memo_id(memo['path']), 'path': '/forged.wav'},
            {'kind': 'path', 'path': str(self.audio_a), 'title': 'last'}]})
        self.assertEqual(status, 200)
        result = json.loads(self.out.read_text())
        self.assertEqual([x['path'] for x in result['sources']],
                         [str(self.audio_b), str(files[0]), str(self.audio_a), str(self.audio_a)])
        self.assertEqual([x['kind'] for x in result['sources']], ['path', 'path', 'voice_memo', 'path'])
        self.assertEqual(result['sources'][1]['title'], uploaded['title'])
        self.assertTrue(all(set(x) == {'kind', 'path', 'title'} for x in result['sources']))
        self.assertTrue(files[0].exists())

    def test_upload_rejects_invalid_size_name_and_incomplete_ids(self):
        self.start_server()
        for name in ['x.exe', 'x', 'x.wav\x00', 'x.wav\n']:
            with self.subTest(name=name):
                self.assertEqual(self.upload(name=name)[0], 400)
        for length, expected in [('0', 400), ('-1', 400), ('bad', 400), (str(2**30 + 1), 413)]:
            with self.subTest(length=length):
                self.assertEqual(self.upload(b'', headers={'Content-Length': length})[0], expected)
        self.assertEqual(self.request('upload', b'x', {'X-File-Name': '%ZZ.wav'})[0], 400)
        self.assertEqual(self.request('upload', b'x', {'X-File-Name': '%FF.wav'})[0], 400)
        self.assertEqual(self.request('upload', b'x', {'X-File-Name': 'x.wav', 'Transfer-Encoding': 'chunked'})[0], 400)
        self.assertEqual(self.request('submit', b'{}', {'Content-Length': str(1024**2 + 1)})[0], 413)
        for source in [{'upload_id': 'unknown'}, {'upload_id': []}, {'memo_id': 'missing'},
                       {'upload_id': 'unknown', 'memo_id': 'missing'}]:
            self.assertEqual(self.post(self.url + 'submit', {'sources': [source]})[0], 400)
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('inputs/*')))

    def raw_upload(self, headers, content, shutdown=True, route='upload'):
        target = urllib.parse.urlsplit(self.url)
        client = socket.create_connection((target.hostname, target.port), timeout=5)
        client.sendall((f'POST {target.path}{route} HTTP/1.1\r\nHost: {target.netloc}\r\n'
                        'X-File-Name: test.wav\r\n' + headers + '\r\n').encode() + content)
        if shutdown:
            client.shutdown(socket.SHUT_WR)
        response = http.client.HTTPResponse(client)
        response.begin()
        body = response.read()
        status = response.status
        response.close()
        client.close()
        return status, json.loads(body)

    def test_upload_disconnect_and_duplicate_or_missing_length_leave_no_part(self):
        self.start_server()
        for headers, body in [('Content-Length: 999\r\n', b'partial'),
                              ('Content-Length: 3\r\nContent-Length: 4\r\n', b'test'), ('', b'')]:
            with self.subTest(headers=headers):
                self.assertEqual(self.raw_upload(headers, body)[0], 400)
                self.assertFalse(list(self.root.glob('inputs/*')))
        self.assertEqual(self.upload()[0], 200)

    def test_upload_storage_failure_leaves_no_partial_or_registered_upload(self):
        self.start_server()
        attempted, partials = [], []
        def failed_rename(source, destination, **kwargs):
            attempted.append(Path(destination).stem)
            partials.append(str(self.root / 'inputs' / source))
            raise OSError('synthetic rename failure')
        with mock.patch.object(self.form.os, 'replace', side_effect=failed_rename):
            self.assertEqual(self.upload()[0], 500)
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'upload_id': attempted[0]}]})[0], 400)
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'kind': 'path', 'path': partials[0]}]})[0], 400)
        self.assertFalse(list(self.root.glob('inputs/*')))
        self.assertEqual(self.upload()[0], 200)

    def test_upload_does_not_follow_inputs_symlink(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.root / 'inputs').symlink_to(elsewhere, target_is_directory=True)
        self.start_server()
        self.assertEqual(self.upload()[0], 400)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_upload_inputs_rebound_at_part_open_is_not_published(self):
        self.start_server()
        folder, kept, outside = self.root / 'inputs', self.root / 'kept', self.root / 'outside'
        folder.mkdir()
        outside.mkdir(mode=0o755)
        mode = outside.stat().st_mode
        original = self.audio_a.read_bytes()
        real_open = self.form.os.open
        switched = []
        def swap(path, flags, *args, **kwargs):
            if str(path).endswith('.part') and not switched:
                folder.rename(kept)
                folder.symlink_to(outside, target_is_directory=True)
                switched.append(True)
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(self.form.os, 'open', side_effect=swap):
            status, _ = self.upload()
        self.assertTrue(switched)
        self.assertNotEqual(status, 200)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(list(kept.iterdir()), [])
        self.assertEqual(outside.stat().st_mode, mode)
        self.assertEqual(self.audio_a.read_bytes(), original)

    def test_timeout_retains_completed_upload_receipt_and_reports_location(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.start_server(timeout=0.5)
            status, receipt = self.upload(b'synthetic retained recording', name='original title.wav')
            self.assertEqual(status, 200)
            self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.results, [None])
        folder = self.root / 'inputs'
        metadata = json.loads((folder / (receipt['id'] + '.json')).read_text())
        self.assertEqual(metadata['title'], 'original title.wav')
        content = (folder / metadata['basename']).read_bytes()
        self.assertEqual(content, b'synthetic retained recording')
        self.assertEqual(metadata['byte_count'], len(content))
        self.assertEqual(metadata['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual((folder / (receipt['id'] + '.json')).stat().st_mode & 0o777, 0o600)
        self.assertIn(str(folder), stderr.getvalue())
        self.assertIn('1', stderr.getvalue())
        self.assertFalse(self.out.exists())

    def test_upload_rebind_before_fchmod_never_changes_replacement_permissions(self):
        self.start_server()
        folder, kept, outside = self.root / 'inputs', self.root / 'kept', self.root / 'outside'
        folder.mkdir()
        outside.mkdir(mode=0o755)
        mode = outside.stat().st_mode
        real_fchmod = self.form.os.fchmod
        switched = []
        def swap(fd, permissions):
            if self.form.stat.S_ISDIR(self.form.os.fstat(fd).st_mode) and not switched:
                folder.rename(kept)
                folder.symlink_to(outside, target_is_directory=True)
                switched.append(True)
            return real_fchmod(fd, permissions)
        with mock.patch.object(self.form.os, 'fchmod', side_effect=swap):
            self.assertNotEqual(self.upload()[0], 200)
        self.assertTrue(switched)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(outside.stat().st_mode, mode)
        self.assertEqual(list(kept.iterdir()), [])

    def test_upload_rebound_after_rename_cleans_owned_files_only(self):
        self.start_server()
        folder, kept, outside = self.root / 'inputs', self.root / 'kept', self.root / 'outside'
        outside.mkdir(mode=0o755)
        mode = outside.stat().st_mode
        real_replace = self.form.os.replace
        switched = []
        def swap(source, destination, **kwargs):
            result = real_replace(source, destination, **kwargs)
            if not switched:
                folder.rename(kept)
                folder.symlink_to(outside, target_is_directory=True)
                # An unrelated same-name file must survive cleanup via the old fd.
                (outside / Path(destination).name).write_bytes(b'outside sentinel')
                switched.append(Path(destination).name)
            return result
        with mock.patch.object(self.form.os, 'replace', side_effect=swap):
            self.assertNotEqual(self.upload()[0], 200)
        self.assertEqual(len(switched), 1)
        self.assertEqual(list(kept.iterdir()), [])
        self.assertEqual(list(outside.iterdir()), [outside / switched[0]])
        self.assertEqual((outside / switched[0]).read_bytes(), b'outside sentinel')
        self.assertEqual(outside.stat().st_mode, mode)

    def test_receipt_publish_failure_rejects_upload_and_removes_audio(self):
        self.start_server()
        real_replace = self.form.os.replace
        attempted = []
        def fail_receipt(source, destination, **kwargs):
            if str(destination).endswith('.json'):
                attempted.append(Path(destination).stem)
                raise OSError('synthetic receipt publish failure')
            return real_replace(source, destination, **kwargs)
        with mock.patch.object(self.form.os, 'replace', side_effect=fail_receipt):
            self.assertEqual(self.upload()[0], 500)
        self.assertEqual(len(attempted), 1)
        self.assertEqual(list((self.root / 'inputs').iterdir()), [])
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'upload_id': attempted[0]}]})[0], 400)

    def test_upload_without_dir_fd_support_fails_closed(self):
        self.start_server()
        with mock.patch.object(self.form.os, 'supports_dir_fd', set()):
            status, response = self.upload()
        self.assertEqual(status, 400)
        self.assertIn('表單上傳已停用', response['error'])
        self.assertFalse((self.root / 'inputs').exists())

    def test_upload_deadline_cleans_partial_and_does_not_publish(self):
        self.start_server(timeout=0.4)
        status, _ = self.raw_upload('Content-Length: 999\r\n', b'partial', shutdown=False)
        self.assertEqual(status, 408)
        self.thread.join(timeout=2)
        self.assertEqual(self.results, [None])
        self.assertFalse(list(self.root.glob('inputs/*')))
        self.assertFalse(self.out.exists())

    def test_refresh_retains_stable_id_and_original_legacy_snapshot(self):
        original = {'path': str(self.audio_a), 'title': '舊選取'}
        new = {'path': str(self.audio_b), 'title': '新錄音'}
        many = [new] + [{'path': str(self.root / f'missing-{i}.wav'), 'title': str(i)} for i in range(24)]
        self.start_server(memos=[original], reader=iter([many, list(reversed(many))]).__next__)
        status, first = self.post(self.url + 'memos', {})
        self.assertEqual(status, 200)
        self.assertEqual(first['total'], 25)
        self.assertEqual(len(first['memos']), 20)
        self.assertEqual(first['memos'][0]['id'], self.form.memo_id(str(self.audio_b)))
        self.assertEqual(first['memos'][0]['availability'], 'local')
        self.assertEqual(first['memos'][0]['byte_count'], self.audio_b.stat().st_size)
        self.assertEqual(first['memos'][1]['availability'], 'missing')
        self.assertEqual(set(first['memos'][0]),
                         {'id', 'title', 'recorded_at', 'duration', 'path', 'availability', 'byte_count'})
        self.assertEqual(self.post(self.url + 'memos', {})[0], 200)
        self.assertEqual(self.post(self.url + 'submit', {'sources': [
            {'memo_id': self.form.memo_id(str(self.audio_a))}, {'memo_id': first['memos'][0]['id']}],
            'memos': [0]})[0], 200)
        sources = json.loads(self.out.read_text())['sources']
        self.assertEqual([x['path'] for x in sources], [str(self.audio_a), str(self.audio_b), str(self.audio_a)])

    def test_submit_rechecks_memo_and_upload_readability(self):
        self.start_server(memos=[{'path': str(self.audio_a), 'title': 'memo'}])
        self.audio_a.unlink()
        identifier = self.form.memo_id(str(self.audio_a))
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'memo_id': identifier}]})[0], 400)
        self.assertEqual(self.post(self.url + 'submit', {'memos': [0]})[0], 400)
        self.assertEqual(self.post(self.url + 'submit', {'sources': [
            {'kind': 'voice_memo', 'path': str(self.audio_a)}]})[0], 400)
        _, uploaded = self.upload()
        copy = self.root / 'inputs' / (uploaded['id'] + '.wav')
        copy.chmod(0)
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'upload_id': uploaded['id']}]})[0], 400)
        copy.chmod(0o600)
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'upload_id': uploaded['id']}]})[0], 200)

    def test_memo_errors_are_explicit_and_empty_success_is_distinct(self):
        results = iter([FileNotFoundError(), PermissionError(), ValueError('讀不懂語音備忘錄的錄音清單'),
                        ValueError('語音備忘錄正在寫入清單，請稍後重新整理（已嘗試 5 次）'), []])
        def read():
            value = next(results)
            if isinstance(value, Exception):
                raise value
            return value
        self.start_server(reader=read)
        messages = []
        for _ in range(4):
            status, body = self.post(self.url + 'memos', {})
            self.assertEqual(status, 500)
            self.assertTrue(body['error'])
            self.assertNotIn('memos', body)
            messages.append(body['error'])
        self.assertEqual(len(set(messages)), 4)
        for phrase, message in zip(['找不到', '權限', '格式', '變動'], messages):
            self.assertIn(phrase, message)
        self.assertEqual(self.post(self.url + 'memos', {}), (200, {'memos': [], 'total': 0}))

    def test_native_cancel_and_origin_host_token_checks(self):
        self.start_server()
        with mock.patch.object(self.form, 'browse', return_value=[]) as picker:
            self.assertEqual(self.post(self.url + 'browse', {'kind': 'file'}), (200, {'paths': []}))
            picker.assert_called_once()
        authority = urllib.parse.urlsplit(self.url).netloc
        for route in ['upload', 'memos', 'browse', 'submit']:
            for headers in [{'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Host': 'evil.example'},
                            {'Host': 'localhost:' + authority.split(':')[1]}]:
                self.assertEqual(self.request(route, b'{}', headers)[0], 403)
        self.assertEqual(self.request('', method='GET', headers={'Host': 'evil.example'})[0], 403)
        with mock.patch.object(self.form, 'browse', return_value=[]):
            self.assertEqual(self.request('browse', b'{"kind":"file"}', {'Origin': 'http://' + authority})[0], 200)
        base = self.url.rsplit('/', 2)[0]
        for route in ['memos', 'upload', 'browse', 'submit']:
            self.assertEqual(self.post(base + '/wrong/' + route, {})[0], 404)

    def test_native_failure_is_actionable_and_form_can_retry(self):
        self.start_server()
        with mock.patch.object(self.form.platform, 'system', return_value='Darwin'):
            with mock.patch.object(self.form.subprocess, 'run', return_value=mock.Mock(
                    returncode=1, stdout='', stderr='execution error: synthetic private path (-1743)')):
                status, body = self.post(self.url + 'browse', {'kind': 'file'})
                self.assertEqual(status, 400)
                self.assertIn('加入錄音', body['error'])
                self.assertNotIn('synthetic private path', body['error'])
                self.assertNotIn('paths', body)
            with mock.patch.object(self.form.subprocess, 'run', return_value=mock.Mock(
                    returncode=0, stdout=str(self.audio_a) + '\n', stderr='')):
                self.assertEqual(self.post(self.url + 'browse', {'kind': 'file'}),
                                 (200, {'paths': [str(self.audio_a)]}))
        self.reader.assert_not_called()

    def test_prior_completed_input_prefill_can_be_submitted_again(self):
        directory = self.root / 'inputs'
        directory.mkdir()
        previous = directory / 'prior-completed.wav'
        previous.write_bytes(b'previous synthetic completed upload')
        source = {'kind': 'path', 'path': str(previous), 'title': '前次錄音'}
        self.start_server(prefill={'sources': [source]})
        status, body = self.request('', method='GET')
        self.assertEqual(status, 200)
        state = Controls(body.decode()).state
        self.assertEqual(state['sources'], [source])
        self.assertEqual(self.post(self.url + 'submit', {**state['settings'], 'sources': state['sources']})[0], 200)
        self.assertEqual(json.loads(self.out.read_text())['sources'], [source])

    def test_memo_symlink_is_unreadable_in_state_refresh_and_submit(self):
        linked = self.root / 'linked.m4a'
        linked.symlink_to(self.audio_a)
        memo = {'path': str(linked), 'title': 'symlink', 'availability': 'unreadable'}
        self.start_server(memos=[memo], reader=lambda: [memo])
        state = Controls(self.form.page([memo], None)).state
        self.assertEqual(state['memos'][0]['availability'], 'unreadable')
        status, result = self.post(self.url + 'memos', {})
        self.assertEqual(status, 200)
        self.assertEqual(result['memos'][0]['availability'], 'unreadable')
        self.assertEqual(self.post(self.url + 'submit', {'sources': [{'memo_id': result['memos'][0]['id']}]})[0], 400)

    def test_json_partial_body_and_bad_types_do_not_save(self):
        self.start_server()
        for body in [b'[]', b'null', b'{bad', b'"text"']:
            self.assertEqual(self.request('submit', body)[0], 400)
        self.assertEqual(self.raw_upload('Content-Length: 999\r\n', b'{}', route='submit')[0], 400)
        self.assertFalse(self.out.exists())

    def test_json_deadline_rejects_partial_body_without_answers(self):
        self.start_server(timeout=0.3)
        self.assertEqual(self.raw_upload('Content-Length: 999\r\n', b'{}', shutdown=False, route='submit')[0], 408)
        self.thread.join(timeout=2)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.results, [None])

    def test_upload_length_boundary_and_supported_extensions_match_runner(self):
        self.start_server()
        assignments = ast.parse(SCRIPT.with_name('run.py').read_text()).body
        runner_audio = next(ast.literal_eval(node.value) for node in assignments
                            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'AUDIO'
                                                                    for t in node.targets))
        self.assertEqual(self.form.AUDIO, runner_audio)
        self.assertEqual(self.form.MAX_UPLOAD, 2**30)
        self.assertEqual(self.upload(b'x')[0], 200)
        with mock.patch.object(self.form, 'MAX_UPLOAD', 16):
            self.assertEqual(self.upload(b'x' * 16)[0], 200)
            self.assertEqual(self.upload(b'x' * 17)[0], 413)
        self.assertEqual(self.raw_upload(f'Content-Length: {2**30}\r\n', b'')[0], 400)
        self.assertFalse(list(self.root.glob('inputs/*.part')))

    def test_file_swapped_to_symlink_during_availability_probe_is_unreadable(self):
        form = load_form()
        def swap(*args, **kwargs):
            self.audio_a.unlink()
            self.audio_a.symlink_to(self.audio_b)
            return True
        with mock.patch.object(form.os, 'access', side_effect=swap):
            self.assertEqual(form.file_status(self.audio_a), ('unreadable', None))

    def test_memo_permissions_and_hash_ignore_client_ids(self):
        form = load_form()
        self.audio_a.chmod(0)
        try:
            record = form.memo_records([{'id': 'forged', 'path': str(self.audio_a), 'title': 'memo'}])[0]
            self.assertEqual(record['availability'], 'unreadable')
            self.assertEqual(record['id'], hashlib.sha256(str(self.audio_a).encode()).hexdigest())
        finally:
            self.audio_a.chmod(0o600)


if __name__ == '__main__':
    unittest.main()

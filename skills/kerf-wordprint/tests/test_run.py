"""Exercise orchestration with synthetic worker outputs, without models or network."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import urllib.parse
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'run.py'
spec = importlib.util.spec_from_file_location('wordprint_entry', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.audio = self.root / 'one.wav'
        self.audio.write_bytes(b'synthetic source identity')
        self.request = self.root / 'request.json'
        self.request.write_text(json.dumps({'sources': [{'path': str(self.audio)}],
                                            'engine': 'qwen-1.7b', 'summary': 'none', 'mail': False}))
        self.args = argparse.Namespace(request=self.request, task_directory=self.root / 'task',
                                       resume_from=None, no_open=True, timeout=1, original_script=True, title='Fixture')

    def worker(self, command, partial=False):
        if 'render' in command:
            return subprocess.run(command, capture_output=True).returncode
        self.assertIn('1.7B', command)
        directory = Path(command[command.index('--run-directory') + 1])
        directory.mkdir()
        run = {'schema_version': 1, 'model': {'id': 'Qwen/Qwen3-ASR-1.7B', 'size': '1.7B'},
               'sources': [{'path': str(self.audio), 'sha256': hashlib.sha256(self.audio.read_bytes()).hexdigest(),
                            'duration': 1, 'offset': 0}],
               'chunks': [{'start': 0, 'end': 1, 'text': '你好', 'complete': True, 'truncated': False,
                           'words': [{'text': '你好', 'start': 0, 'end': 1}]}],
               'turns': [] if partial else [{'start': 0, 'end': 1, 'speaker': 'S1'}],
               'speakers': {} if partial else {'S1': {}}, 'diarization_complete': not partial}
        m.save(directory / 'normalized-run.json', run)
        m.save(directory / 'state.json', {'stage': 'partial' if partial else 'complete',
                                         'status': 'partial' if partial else 'complete',
                                         'warnings': ['speaker failed'] if partial else [],
                                         'retry_stage': 'diarization' if partial else None})
        (directory / 'raw-transcript.txt').write_text('你好\n')
        return 0

    def test_complete_request_skips_form_preserves_model_and_none_and_renders(self):
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', side_effect=self.worker), \
                patch.object(m.subprocess, 'run', wraps=subprocess.run) as calls:
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (0, 'complete'))
        self.assertEqual(result['pending_agent_steps'], [])
        self.assertTrue((self.args.task_directory / 'output-1/transcript.html').exists())
        self.assertFalse(any('voice_memos.py' in str(c) for c in calls.call_args_list))
        saved = json.loads((self.args.task_directory / 'answers.json').read_text())
        self.assertEqual(saved['engine'], 'qwen-1.7b')
        self.assertEqual(saved['summary'], 'none')

    def test_partial_worker_keeps_raw_text_and_never_renders_complete(self):
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', side_effect=lambda cmd: self.worker(cmd, partial=True)):
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (1, 'partial'))
        self.assertIn(str(self.args.task_directory / 'run-1/raw-transcript.txt'), result['runs'][0]['outputs'])
        self.assertEqual(result['runs'][0]['retry_stage'], 'diarization')
        self.assertFalse((self.args.task_directory / 'output-1').exists())

    def test_delivery_preserves_actual_model_for_complete_and_partial(self):
        for size, partial in [('0.6B', False), ('0.6B', True), ('1.7B', False)]:
            with self.subTest(size=size, partial=partial):
                self.args.task_directory = self.root / f'job-{size}-{partial}'
                def worker(command):
                    code = self.worker(command, partial=partial)
                    if 'render' not in command:
                        path = Path(command[command.index('--run-directory') + 1]) / 'normalized-run.json'
                        data = json.loads(path.read_text())
                        data['model'] = {'id': f'Qwen/Qwen3-ASR-{size}', 'size': size}
                        m.save(path, data)
                    return code
                with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                        patch.object(m, 'execute', side_effect=worker):
                    result, code = m.run(self.args)
                self.assertEqual(code, 1 if partial else 0)
                self.assertEqual(result['runs'][0]['model']['size'], size)

    def test_raw_only_delivery_keeps_partial_result(self):
        directory = self.root / 'raw-only'
        directory.mkdir()
        (directory / 'raw-transcript.txt').write_text('合成文字')
        answers = m.choices({})
        with patch.object(m, 'execute') as execute:
            item = m.deliver(directory, self.root / 'output', [sys.executable], answers)
        self.assertEqual(item['status'], 'partial')
        self.assertIn(str(directory / 'raw-transcript.txt'), item['outputs'])
        execute.assert_not_called()

    def test_grouped_subtitle_warning_reaches_delivery(self):
        def worker(command):
            result = self.worker(command)
            if 'render' not in command:
                directory = Path(command[command.index('--run-directory') + 1])
                normalized = directory / 'normalized-run.json'
                run = json.loads(normalized.read_text())
                run['chunks'][0]['words'] = [{'text': '你', 'start': 0, 'end': 0.5},
                                             {'text': '好', 'start': 0.5, 'end': 0.5}]
                run['turns'][0]['end'] = 0.5
                m.save(normalized, run)
            return result
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', side_effect=worker):
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (0, 'complete'))
        output = self.args.task_directory / 'output-1'
        report = json.loads((output / 'validation.json').read_text())
        self.assertTrue(report['srt_written'])
        self.assertGreater(report['srt_grouped_rows'], 0)
        self.assertIn(report['srt_grouping_note'], result['runs'][0]['warnings'])

    def test_empty_transcript_warns_and_keeps_requested_summary_for_recovery(self):
        request = json.loads(self.request.read_text())
        request['summary'] = 'meeting'
        self.request.write_text(json.dumps(request))
        def worker(command):
            code = self.worker(command)
            if 'render' not in command:
                directory = Path(command[command.index('--run-directory') + 1])
                path = directory / 'normalized-run.json'
                run = json.loads(path.read_text())
                run['chunks'][0].update(text='', words=[])
                run.update(turns=[], speakers={})
                m.save(path, run)
                (directory / 'raw-transcript.txt').write_text('\n')
            return code
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', side_effect=worker):
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (0, 'complete'))
        self.assertTrue(any('未辨識到可用文字' in w for w in result['runs'][0]['warnings']))
        self.assertEqual(result['pending_agent_steps'][0]['template'], 'meeting')
        self.assertTrue(result['runs'][0]['empty_transcript'])
        self.assertEqual(result['pending_agent_steps'][0]['status'], 'unavailable')
        self.assertIn('未辨識到可用文字', result['pending_agent_steps'][0]['reason'])
        self.assertFalse((self.args.task_directory / 'output-1/transcript.srt').exists())

    def test_existing_task_is_never_overwritten(self):
        self.args.task_directory.mkdir()
        marker = self.args.task_directory / 'keep'
        marker.write_text('unchanged')
        with self.assertRaises(FileExistsError):
            m.run(self.args)
        self.assertEqual(list(self.args.task_directory.iterdir()), [marker])
        self.assertEqual(marker.read_text(), 'unchanged')

    def test_default_stays_local_even_when_cloud_key_exists(self):
        with patch.dict(m.os.environ, {'GEMINI_API_KEY': 'not-a-real-key'}):
            self.assertEqual(m.choices({})['engine'], 'qwen-0.6b')

    def test_folder_sources_sort_and_preserve_requested_merge(self):
        folder = self.root / 'recordings'
        folder.mkdir()
        for name in ('b.wav', 'a.m4a', 'c.qta', 'notes.txt'):
            (folder / name).write_bytes(b'fixture')
        answer = m.choices({'sources': [{'path': str(folder)}], 'merge': True})
        self.assertTrue(answer['merge'])
        self.assertEqual([Path(s['path']).name for s in m.expand_sources(answer['sources'])], ['a.m4a', 'b.wav', 'c.qta'])

    def test_missing_sources_are_read_only_after_form_action(self):
        form = m.load('form')
        answer = m.choices({'sources': [{'path': str(self.audio)}]})
        with patch.object(form, 'serve', return_value=answer) as serve, \
                patch.object(m, 'load', return_value=form), patch.object(m.subprocess, 'run') as external:
            self.assertEqual(m.collect({}, self.root, True, 1), answer)
        self.assertEqual(serve.call_args.args[0], [])
        external.assert_not_called()

    def test_localhost_run_form_continues_to_colab_waiting_without_worker(self):
        # Browser opening is the OS boundary; all collection and HTTP are real.
        import io
        pages = []
        visitors = []
        def browser_open(url):
            with urllib.request.urlopen(url, timeout=5) as response:
                pages.append(response.read().decode())
            payload = {'sources': [{'kind': 'path', 'path': str(self.audio)}], 'engine': 'colab',
                       'summary': 'meeting', 'mail': False}
            request = urllib.request.Request(url + 'submit', data=json.dumps(payload).encode(), method='POST')
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
            return True
        # serve() starts handling HTTP after the opener returns.
        import threading
        errors = []
        def open_async(url):
            def visit():
                try:
                    browser_open(url)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=visit)
            visitors.append(thread)
            thread.start()
            return True
        self.args.request = None
        self.args.no_open = False
        self.args.timeout = 5
        with patch('webbrowser.open', side_effect=open_async), contextlib.redirect_stderr(io.StringIO()):
            result, code = m.run(self.args)
        for thread in visitors:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual((code, result['status'], result['stage']), (2, 'waiting', 'colab'))
        state = json.loads(re.search(r'<script id="initial-state"[^>]*>(.*?)</script>', pages[0], re.S)[1])
        self.assertEqual(state['mode'], 'run')
        self.assertIn('>開始整理</button>', pages[0])
        saved = json.loads((self.args.task_directory / 'answers.json').read_text())
        self.assertNotIn('mode', saved)
        self.assertEqual(saved['summary'], 'meeting')
        self.assertEqual(json.loads((self.args.task_directory / 'delivery.json').read_text())['status'], 'waiting')
        self.assertFalse(list(self.args.task_directory.glob('run-*')))

    def test_uploaded_files_keep_display_order_through_form_and_runner(self):
        answers_path = self.root / 'import-answers.json'
        process = subprocess.Popen([sys.executable, str(SCRIPT.with_name('form.py')),
                                    '--out', str(answers_path), '--no-open', '--timeout', '20'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            url = process.stderr.readline().strip().removeprefix('form: ')
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            imported = []
            for name, content in [('甲.wav', b'first synthetic recording'), ('乙.qta', b'second synthetic recording')]:
                request = urllib.request.Request(url + 'upload', data=content,
                    headers={'X-File-Name': urllib.parse.quote(name)}, method='POST')
                with urllib.request.urlopen(request, timeout=5) as response:
                    receipt = json.load(response)
                self.assertEqual(receipt['sha256'], hashlib.sha256(content).hexdigest())
                imported.append(receipt)
            payload = {'sources': [{'upload_id': item['id']} for item in reversed(imported)],
                       'merge': True, 'engine': 'qwen-0.6b', 'summary': 'none', 'mail': False}
            request = urllib.request.Request(url + 'submit', data=json.dumps(payload).encode(), method='POST')
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.args.request = answers_path
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', return_value=1) as execute:
            m.run(self.args)
        command = execute.call_args.args[0]
        inputs = [Path(command[i + 1]) for i, arg in enumerate(command) if arg == '--audio']
        self.assertEqual([item.read_bytes() for item in inputs],
                         [b'second synthetic recording', b'first synthetic recording'])
        saved = json.loads((self.args.task_directory / 'answers.json').read_text())
        self.assertEqual([item['title'] for item in saved['sources']], ['乙.qta', '甲.wav'])
        self.assertTrue(saved['merge'])

    def test_selected_memo_is_preserved_before_worker_and_original_stays_unchanged(self):
        source = {'kind': 'voice_memo', 'path': str(self.audio), 'title': '合成備忘錄'}
        self.request.write_text(json.dumps({'sources': [source], 'summary': 'none'}))
        before = self.audio.read_bytes()
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', return_value=1) as execute:
            m.run(self.args)
        command = execute.call_args.args[0]
        copied = Path(command[command.index('--audio') + 1])
        self.assertEqual(copied.parent, self.args.task_directory / 'inputs')
        self.assertEqual(copied.read_bytes(), before)
        self.assertEqual(self.audio.read_bytes(), before)
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        self.assertEqual(copied.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((self.args.task_directory / 'selected-sources.json').read_text()), [source])
        saved = json.loads((self.args.task_directory / 'answers.json').read_text())
        self.assertEqual(saved['sources'][0]['path'], str(copied))

    def test_memo_symlink_and_missing_file_never_reach_worker(self):
        alias = self.root / 'alias.m4a'
        alias.symlink_to(self.audio)
        for path in (alias, self.root / 'absent.m4a'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, '目前無法讀取'):
                m.expand_sources([{'kind': 'voice_memo', 'path': str(path), 'title': 'fixture'}])

    def test_memo_swapped_after_file_probe_never_copies_redirected_bytes(self):
        other = self.root / 'other.wav'
        other.write_bytes(b'outside recording')
        original = self.audio.read_bytes()
        saved = self.audio.with_suffix('.saved')
        real_is_file = Path.is_file
        switched = []
        def swap(path):
            result = real_is_file(path)
            if path == self.audio and not switched:
                self.audio.rename(saved)
                self.audio.symlink_to(other)
                switched.append(True)
            return result
        self.args.task_directory.mkdir()
        with patch.object(Path, 'is_file', swap), self.assertRaises((ValueError, OSError)):
            sources = m.expand_sources([{'kind': 'voice_memo', 'path': str(self.audio)}])
            m.preserve_memos(sources, self.args.task_directory)
        self.assertTrue(switched)
        self.assertEqual(saved.read_bytes(), original)
        self.assertEqual(other.read_bytes(), b'outside recording')
        self.assertFalse(list((self.args.task_directory / 'inputs').glob('*')))

    def test_memo_parent_rebound_after_selection_is_rejected(self):
        parent, outside = self.root / 'recordings', self.root / 'outside'
        parent.mkdir()
        outside.mkdir()
        audio = parent / 'memo.wav'
        audio.write_bytes(b'original memo')
        (outside / audio.name).write_bytes(b'outside memo')
        sources = m.expand_sources([{'kind': 'voice_memo', 'path': str(audio)}])
        parent.rename(self.root / 'recordings-kept')
        parent.symlink_to(outside, target_is_directory=True)
        self.args.task_directory.mkdir()
        with self.assertRaises((ValueError, OSError)):
            m.preserve_memos(sources, self.args.task_directory)
        self.assertEqual((self.root / 'recordings-kept' / audio.name).read_bytes(), b'original memo')
        self.assertEqual((outside / audio.name).read_bytes(), b'outside memo')

    def test_inputs_rebound_at_part_open_cannot_write_outside(self):
        self.args.task_directory.mkdir()
        folder = self.args.task_directory / 'inputs'
        folder.mkdir()
        kept, outside = self.root / 'kept-inputs', self.root / 'outside'
        outside.mkdir(mode=0o755)
        mode = outside.stat().st_mode
        original = self.audio.read_bytes()
        real_open = m.os.open
        switched = []
        def swap(path, flags, *args, **kwargs):
            if str(path).endswith('.part') and not switched:
                folder.rename(kept)
                folder.symlink_to(outside, target_is_directory=True)
                switched.append(True)
            return real_open(path, flags, *args, **kwargs)
        with patch.object(m.os, 'open', side_effect=swap), self.assertRaises((ValueError, OSError)):
            m.preserve_memos([{'kind': 'voice_memo', 'path': str(self.audio)}], self.args.task_directory)
        self.assertTrue(switched)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(list(kept.iterdir()), [])
        self.assertEqual(outside.stat().st_mode, mode)
        self.assertEqual(self.audio.read_bytes(), original)

    def test_task_rebound_at_part_open_is_rejected_and_cleanup_stays_pinned(self):
        task = self.args.task_directory
        task.mkdir()
        kept, outside = self.root / 'kept-task', self.root / 'outside'
        outside.mkdir(mode=0o755)
        (outside / 'inputs').mkdir(mode=0o755)
        mode = (outside / 'inputs').stat().st_mode
        real_open = m.os.open
        switched = []
        original = self.audio.read_bytes()
        def swap(path, flags, *args, **kwargs):
            if str(path).endswith('.part') and not switched:
                task.rename(kept)
                task.symlink_to(outside, target_is_directory=True)
                switched.append(True)
            return real_open(path, flags, *args, **kwargs)
        with patch.object(m.os, 'open', side_effect=swap), self.assertRaises((ValueError, OSError)):
            m.preserve_memos([{'kind': 'voice_memo', 'path': str(self.audio)}], task)
        self.assertTrue(switched)
        self.assertEqual(list((kept / 'inputs').iterdir()), [])
        self.assertEqual(list((outside / 'inputs').iterdir()), [])
        self.assertEqual((outside / 'inputs').stat().st_mode, mode)
        self.assertEqual(self.audio.read_bytes(), original)

    def test_missing_dir_fd_support_fails_closed(self):
        self.args.task_directory.mkdir()
        with patch.object(m.os, 'supports_dir_fd', set()), self.assertRaisesRegex(ValueError, 'macOS'):
            m.preserve_memos([{'kind': 'voice_memo', 'path': str(self.audio)}], self.args.task_directory)
        self.assertEqual(list(self.args.task_directory.iterdir()), [])

    def test_changed_memo_during_copy_is_rejected_and_partial_removed(self):
        self.args.task_directory.mkdir()
        source = {'kind': 'voice_memo', 'path': str(self.audio), 'title': 'fixture'}
        real_fsync = m.os.fsync
        def mutate(fd):
            real_fsync(fd)
            self.audio.write_bytes(b'changed while copying')
        with patch.object(m.os, 'fsync', side_effect=mutate), self.assertRaisesRegex(ValueError, '發生變動'):
            m.preserve_memos([source], self.args.task_directory)
        self.assertEqual(list((self.args.task_directory / 'inputs').iterdir()), [])

    def test_input_folder_symlink_is_rejected_without_writing_elsewhere(self):
        self.args.task_directory.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.args.task_directory / 'inputs').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '保存位置'):
            m.preserve_memos([{'kind': 'voice_memo', 'path': str(self.audio)}], self.args.task_directory)
        self.assertEqual(list(outside.iterdir()), [])

    def test_saved_memo_can_be_reused_in_a_new_job_without_mutating_old_copy(self):
        self.args.task_directory.mkdir()
        source = {'kind': 'voice_memo', 'path': str(self.audio), 'title': 'fixture'}
        first = m.preserve_memos([source], self.args.task_directory)
        old = Path(first[0]['path'])
        self.audio.unlink()
        second_task = self.root / 'task-2'
        second_task.mkdir()
        second = m.preserve_memos(first, second_task)
        self.assertEqual(Path(second[0]['path']).read_bytes(), old.read_bytes())
        self.assertNotEqual(first[0]['path'], second[0]['path'])

    def test_memo_copy_disk_failure_preserves_original_and_leaves_no_partial(self):
        self.args.task_directory.mkdir()
        original = self.audio.read_bytes()
        with patch.object(m.os, 'fsync', side_effect=OSError('disk full')), self.assertRaises(OSError):
            m.preserve_memos([{'kind': 'voice_memo', 'path': str(self.audio)}], self.args.task_directory)
        self.assertEqual(self.audio.read_bytes(), original)
        self.assertEqual(list((self.args.task_directory / 'inputs').iterdir()), [])

    @unittest.skipUnless(hasattr(m.os, 'mkfifo'), 'POSIX-only Voice Memos source race')
    def test_memo_replaced_by_fifo_after_selection_is_rejected_without_blocking(self):
        sources = m.expand_sources([{'kind': 'voice_memo', 'path': str(self.audio), 'title': 'fixture'}])
        self.audio.unlink()
        m.os.mkfifo(self.audio)
        self.args.task_directory.mkdir()
        with self.assertRaisesRegex(ValueError, '不是可讀取'):
            m.preserve_memos(sources, self.args.task_directory)

    def test_colab_is_handoff_and_does_not_call_worker(self):
        self.request.write_text(json.dumps({'sources': [{'path': str(self.audio)}], 'engine': 'colab'}))
        with patch.object(m, 'execute') as execute:
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (2, 'waiting'))
        execute.assert_not_called()
        self.assertIn('colab', result['notebook'])

    def test_resume_rejects_multiple_independent_runs(self):
        self.request.write_text(json.dumps({'sources': [{'path': str(self.audio)}, {'path': str(self.audio)}]}))
        self.args.resume_from = self.root / 'old'
        with patch.object(m, 'execute') as execute:
            result, code = m.run(self.args)
        self.assertEqual(code, 1)
        self.assertIn('一次續跑', result['error'])
        execute.assert_not_called()

    def test_resume_argument_is_forwarded_to_selected_worker(self):
        cmd = m.worker_command(['python'], 'torch_worker.py', [{'path': str(self.audio)}],
                               self.root / 'new', 'qwen-1.7b', self.root / 'old')
        self.assertEqual(cmd[-2:], ['--resume-from', str(self.root / 'old')])
        self.assertIn('--out', cmd)

    def test_custom_summary_is_only_missing_field_when_sources_known(self):
        self.assertEqual(m.missing(m.choices({'sources': [{'path': str(self.audio)}], 'summary': 'custom'})),
                         ['summary_custom'])

    def test_missing_brief_preserves_local_default_and_normalizes_path_for_form(self):
        form = m.load('form')
        observed = {}
        def serve(memos, out, timeout, open_browser, prefill, mode='collect'):
            observed.update(prefill)
            # A recommendation based on credentials must not replace the resolved default.
            page = form.page([], None, 'gemini-3.5-transcribe', prefill)
            self.assertIn('value="qwen-0.6b" checked', page)
            return form.normalize_answers({**prefill, 'summary_custom': '重點'})
        with patch.object(form, 'serve', side_effect=serve), patch.object(m, 'load', return_value=form), \
                patch.object(m.subprocess, 'run') as external:
            answer = m.collect({'sources': [{'path': str(self.audio)}], 'summary': 'custom'},
                               self.root, True, 1)
        external.assert_not_called()
        self.assertEqual(answer['engine'], 'qwen-0.6b')
        self.assertEqual(observed['sources'][0]['kind'], 'path')
        self.assertEqual(observed['sources'][0]['title'], 'one.wav')

    def test_single_folder_merge_survives_form_and_expands_to_one_worker(self):
        folder = self.root / 'recordings'
        folder.mkdir()
        for name in ('b.wav', 'a.wav'):
            (folder / name).write_bytes(b'fixture')
        request = {'sources': [{'path': str(folder)}], 'merge': True, 'summary': 'custom'}
        self.request.write_text(json.dumps(request))
        form = m.load('form')
        original_load = m.load
        def serve(memos, out, timeout, open_browser, prefill, mode='collect'):
            return form.normalize_answers({**prefill, 'summary_custom': '重點'})
        with patch.object(form, 'serve', side_effect=serve), \
                patch.object(m, 'load', side_effect=lambda name: form if name == 'form' else original_load(name)), \
                patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', return_value=1) as execute:
            result, code = m.run(self.args)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0].count('--audio'), 2)
        self.assertEqual(code, 1)  # Stub worker produced nothing; the routing still preserves merge.
        saved = json.loads((self.args.task_directory / 'answers.json').read_text())
        self.assertTrue(saved['merge'])

    def test_nonzero_worker_exit_never_renders_as_complete(self):
        def stopped(command):
            self.worker(command)
            return 1
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', side_effect=stopped) as execute:
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (1, 'partial'))
        execute.assert_called_once()
        self.assertFalse((self.args.task_directory / 'output-1').exists())

    def test_resume_cannot_create_job_inside_original_run(self):
        old = self.root / 'old'
        old.mkdir()
        (old / 'keep').write_text('original')
        self.args.resume_from, self.args.task_directory = old, old / 'child'
        with self.assertRaisesRegex(ValueError, '舊 run 以外'):
            m.run(self.args)
        self.assertEqual([p.name for p in old.iterdir()], ['keep'])

    def test_cancel_preserves_deliverable_raw_and_does_not_render(self):
        def cancelled(command):
            self.worker(command, partial=True)
            raise KeyboardInterrupt
        with patch.object(m, 'runtime', return_value=([sys.executable], 'qwen_worker.py')), \
                patch.object(m, 'execute', side_effect=cancelled):
            result, code = m.run(self.args)
        self.assertEqual((code, result['status']), (130, 'cancelled'))
        self.assertIn(str(self.args.task_directory / 'run-1/raw-transcript.txt'), result['runs'][0]['outputs'])
        self.assertFalse((self.args.task_directory / 'output-1').exists())

    def test_cancel_requests_child_termination_and_waits(self):
        with patch.object(m.subprocess, 'Popen') as popen:
            child = popen.return_value.__enter__.return_value
            child.wait.side_effect = [KeyboardInterrupt, 130]
            with self.assertRaises(KeyboardInterrupt):
                m.execute(['synthetic-worker'])
        child.terminate.assert_called_once()
        child.kill.assert_not_called()
        self.assertEqual(child.wait.call_count, 2)


if __name__ == '__main__':
    unittest.main()

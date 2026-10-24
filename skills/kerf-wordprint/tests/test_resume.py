"""Stage continuation and corruption/cancellation boundaries; synthetic PCM, no model or cloud calls."""
import dataclasses
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location('test_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


q, t, g = load('qwen_worker'), load('torch_worker'), load('gemini_transcribe')
r = q.runtime


class Samples(list):
    def astype(self, _):
        return self

    def __truediv__(self, _):
        return self


NUMPY = SimpleNamespace(frombuffer=lambda data, **_: Samples([0.] * (len(data) // 2)), int16='int16', float32='float32')


class ResumeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.wav'
        self.source.write_bytes(b'source-one')
        self.pcm = b'\0\0' * 16000
        self.records = [{'path': str(self.source), 'sha256': r.digest(self.source), 'sample_count': 16000,
                         'sample_rate': 16000, 'duration': 1, 'offset': 0}]
        self.old = self.root / 'old'
        self.new = self.root / 'new'
        self.old.mkdir()
        self.new.mkdir()
        self.config = {'model': 'test'}

    def prepare(self, sources, directory, *_):
        r.write_pcm(directory / 'canonical.wav', self.pcm)
        r.save(directory / 'sources.json', self.records)
        return self.records, self.pcm

    def checkpoint(self):
        self.prepare([], self.old)
        r.state(self.old, {'stage': 'partial'})
        r.checkpoint(self.old, self.config, self.records, 'decode', ['canonical.wav', 'sources.json'])

    def snapshot(self, directory):
        return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}

    def assert_state(self, directory):
        state = json.loads((directory / 'state.json').read_text())
        self.assertTrue({'stage', 'status', 'warnings', 'available_outputs', 'retry_stage'} <= state.keys())
        self.assertTrue(all((directory / p).is_file() for p in state['available_outputs']))
        return state

    def test_integrity_model_source_order_and_prior_immutable(self):
        self.checkpoint()
        before = self.snapshot(self.old)
        r.resume(self.old, self.new, [self.source], self.config)
        self.assertEqual(before, self.snapshot(self.old))
        for config, sources in [({'model': 'different'}, [self.source]), (self.config, [self.source, self.source])]:
            with self.assertRaises(ValueError):
                r.resume(self.old, self.new, sources, config)
        (self.old / 'canonical.wav').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, '完整性'):
            r.resume(self.old, self.new, [self.source], self.config)
        with self.assertRaises(ValueError):
            r.check_location(self.old, self.old / 'child')

    def test_qwen_alignment_failure_can_resume_without_asr(self):
        # Full ASR checkpoint, then simulate a missing aligner. No numpy/MLX/model is needed to reuse it.
        config = {'backend': 'mlx-qwen3-asr', 'model': 'Qwen/Qwen3-ASR-0.6B',
                  'aligner': 'Qwen/Qwen3-ForcedAligner-0.6B', 'sample_rate': 16000,
                  'diarization_window_seconds': 1200, 'return_chunks': True}
        self.prepare([], self.old)
        raw = {'text': 'hello', 'chunks': [{'start': 0, 'end': 1, 'text': 'hello', 'truncated': False, 'finish_reason': 'eos'}]}
        r.save(self.old / 'raw.json', raw)
        r.state(self.old, {'stage': 'partial', 'modelRevision': 'cached-revision'})
        r.checkpoint(self.old, config, self.records, 'asr', ['canonical.wav', 'sources.json', 'raw.json'])
        args = SimpleNamespace(audio=[str(self.source)], run_directory=str(self.new), model='0.6B', resume_from=str(self.old))
        with mock.patch.object(q, 'snapshot', side_effect=RuntimeError('aligner unavailable')):
            q.transcribe(args)
        self.assertEqual((self.new / 'raw-transcript.txt').read_text(), 'hello\n')
        self.assertEqual(self.assert_state(self.new)['retry_stage'], 'alignment')
        # Inject a completed aligned checkpoint and prove diarization continuation does not import MLX or locate models.
        aligned = [{**raw['chunks'][0], 'complete': True, 'words': [{'text': 'hello', 'start': 0, 'end': 1}]}]
        r.save(self.new / 'alignment.json', aligned)
        r.save(self.new / 'alignment-model.json', {'id': config['aligner'], 'revision': 'align-rev'})
        r.checkpoint(self.new, config, self.records, 'alignment', ['alignment.json', 'alignment-model.json'])
        third = self.root / 'third'
        third.mkdir()
        before = self.snapshot(self.new)
        args.resume_from, args.run_directory = str(self.new), str(third)
        with mock.patch.object(q, 'snapshot', side_effect=AssertionError('must not load models')), \
             mock.patch.object(q, 'diarize', return_value=([{'start': 0, 'end': 1, 'speaker': 'S1'}], {'id': 'mock'})):
            q.transcribe(args)
        self.assertEqual(self.assert_state(third)['status'], 'complete')
        self.assertEqual(before, self.snapshot(self.new))

    def test_qwen_fresh_run_seals_only_valid_alignment_and_keeps_raw(self):
        raw = {'text': 'hello', 'chunks': [{'start': 0, 'end': 1, 'text': 'hello', 'truncated': False, 'finish_reason': 'eos'}]}
        fake_mlx = SimpleNamespace(transcribe=mock.Mock(return_value=object()),
                                   ForcedAligner=lambda **_: SimpleNamespace(align=lambda *_: [
                                       SimpleNamespace(text='wrong', start_time=0, end_time=1)]))
        args = SimpleNamespace(audio=[str(self.source)], run_directory=str(self.old), model='0.6B', resume_from=None)
        with mock.patch.dict(sys.modules, {'numpy': NUMPY, 'mlx_qwen3_asr': fake_mlx}), \
             mock.patch.object(q, 'prepare', side_effect=self.prepare), \
             mock.patch.object(q, 'snapshot', return_value=Path('/model/revision')), \
             mock.patch.object(q.importlib.metadata, 'version', return_value='test'), \
             mock.patch.object(q.dataclasses, 'asdict', return_value=raw), \
             mock.patch.object(q, 'diarize', side_effect=AssertionError('invalid alignment must not reach diarizer')):
            q.transcribe(args)
        checkpoint = json.loads((self.old / 'checkpoint.json').read_text())
        self.assertIn('asr', checkpoint['stages'])
        self.assertNotIn('alignment', checkpoint['stages'])
        self.assertEqual(self.assert_state(self.old)['retry_stage'], 'alignment')
        self.assertEqual((self.old / 'raw-transcript.txt').read_text(), 'hello\n')
        self.assertEqual(fake_mlx.transcribe.call_count, 1)

    def test_torch_source_mutation_cannot_produce_checkpoint(self):
        def decode(_):
            self.source.write_bytes(b'changed during decode')
            return self.pcm
        asr = SimpleNamespace(model=SimpleNamespace(generate=lambda: None))
        with mock.patch.dict(sys.modules, {'numpy': NUMPY}), mock.patch.object(t, 'decode', side_effect=decode), \
             self.assertRaisesRegex(ValueError, '解碼期間被更動'):
            t.transcribe(asr, [str(self.source)], 'Qwen/Qwen3-ASR-0.6B', 2048, 'test', 'float32', self.old)
        self.assertFalse((self.old / 'checkpoint.json').exists())

    def test_torch_checkpoints_before_cancel_and_resume_only_diarization(self):
        run = {'schema_version': 1, 'sources': self.records, 'model': {'id': 'Qwen/Qwen3-ASR-0.6B', 'size': '0.6B'},
               'chunks': [{'start': 0, 'end': 1, 'text': 'hello', 'complete': True, 'truncated': False,
                           'words': [{'text': 'hello', 'start': 0, 'end': 1}]}],
               'turns': [], 'speakers': {}, 'diarization_complete': False}
        def fake_asr(*args):
            self.prepare([], args[-1])
            return json.loads(json.dumps(run)), [0.] * 16000, self.pcm
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False), float32='float32', float16='float16')
        model_class = SimpleNamespace(from_pretrained=mock.Mock(return_value=object()))
        args = SimpleNamespace(audio=[str(self.source)], model='0.6B', max_new_tokens=2048, platform='test',
                               fallback=False, pcm=str(self.old / 'canonical.wav'), out=str(self.old / 'normalized-run.json'), resume_from=None)
        with mock.patch.dict(sys.modules, {'torch': torch, 'qwen_asr': SimpleNamespace(Qwen3ASRModel=model_class)}), \
             mock.patch.object(t, 'transcribe', side_effect=fake_asr), \
             mock.patch.object(t, 'diarize', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                t.execute(args, self.old)
        self.assertTrue((self.old / 'normalized-run.json').is_file())
        self.assertTrue((self.old / 'raw-transcript.txt').is_file())
        self.assertTrue((self.old / 'checkpoint.json').is_file())
        before = self.snapshot(self.old)
        args.resume_from, args.out, args.pcm = str(self.old), str(self.new / 'normalized-run.json'), str(self.new / 'canonical.wav')
        def diarize(run, *_):
            run.update(diarization_complete=True, speakers={'S1': {}}, turns=[{'start': 0, 'end': 1, 'speaker': 'S1'}])
        with mock.patch.dict(sys.modules, {'torch': torch, 'numpy': NUMPY}), \
             mock.patch.object(t, 'transcribe', side_effect=AssertionError('ASR must not run')), \
             mock.patch.object(t, 'diarize', side_effect=diarize):
            t.execute(args, self.new)
        self.assertEqual(self.assert_state(self.new)['status'], 'complete')
        self.assertEqual(before, self.snapshot(self.old))

    def test_cancelled_state_keeps_partial_artifacts(self):
        r.raw_text(self.old, ['partial words'])
        r.finish_error(self.old, {'stage': 'asr'}, KeyboardInterrupt())
        state = self.assert_state(self.old)
        self.assertEqual((state['status'], state['retry_stage']), ('cancelled', 'asr'))
        self.assertIn('raw-transcript.txt', state['available_outputs'])

    def test_gemini_resume_requests_only_unattempted_part(self):
        response = {'status': 'completed', 'steps': [{'type': 'model_output', 'content': [
            {'type': 'text', 'text': 'hello', 'annotations': [
                {'type': 'word_info', 'text': 'hello', 'start_offset': '0s', 'end_offset': '0.4s', 'speaker': 'speaker1'}]}]}]}
        args = SimpleNamespace(audio=[str(self.source)], run_directory=str(self.old), resume_from=None)
        save = g.worker.save
        def cancel_between_parts(path, value):
            save(path, value)
            if path.name == 'state.json' and value.get('part_requests') == {'1': 'completed'}:
                raise KeyboardInterrupt
        with mock.patch.object(g, 'PART_SAMPLES', 8000), \
             mock.patch.object(g.worker, 'prepare', side_effect=self.prepare), \
             mock.patch.object(g.worker, 'save', side_effect=cancel_between_parts), \
             mock.patch.object(g, 'transcribe_part', return_value=response) as first:
            with self.assertRaises(KeyboardInterrupt):
                g.transcribe(args, 'fake-key')
        self.assertEqual(first.call_count, 1)
        before = self.snapshot(self.old)
        args.run_directory, args.resume_from = str(self.new), str(self.old)
        with mock.patch.object(g, 'PART_SAMPLES', 8000), \
             mock.patch.object(g, 'transcribe_part', return_value=response) as second:
            g.transcribe(args, 'fake-key')
        self.assertEqual(second.call_count, 1)
        self.assertEqual(second.call_args.args[0].name, 'part-002.wav')
        self.assertEqual(self.assert_state(self.new)['status'], 'complete')
        self.assertEqual(before, self.snapshot(self.old))

    def test_gemini_reuses_only_verified_parts_and_blocks_ambiguous_requests(self):
        response = {'status': 'completed', 'steps': [{'type': 'model_output', 'content': [
            {'type': 'text', 'text': 'hello', 'annotations': [
                {'type': 'word_info', 'text': 'hello', 'start_offset': '0s', 'end_offset': '1s', 'speaker': 'speaker1'}]}]}]}
        args = SimpleNamespace(audio=[str(self.source)], run_directory=str(self.old), resume_from=None)
        with mock.patch.object(g.worker, 'prepare', side_effect=self.prepare), \
             mock.patch.object(g, 'transcribe_part', return_value=response) as remote:
            g.transcribe(args, 'fake-key')
        self.assertEqual(remote.call_count, 1)
        before = self.snapshot(self.old)
        args.run_directory, args.resume_from = str(self.new), str(self.old)
        with mock.patch.object(g, 'transcribe_part', side_effect=AssertionError('no repeated remote request')):
            g.transcribe(args, 'fake-key')
        self.assertEqual(self.assert_state(self.new)['status'], 'complete')
        self.assertEqual(before, self.snapshot(self.old))
        old_state = json.loads((self.old / 'state.json').read_text())
        old_state['part_requests']['2'] = 'started'
        old_state['google_resources'] = ['files/leftover']
        r.state(self.old, old_state)
        third = self.root / 'third'
        third.mkdir()
        args.run_directory = str(third)
        with mock.patch.object(g, 'transcribe_part', side_effect=AssertionError('must not retry')), \
             self.assertRaisesRegex(RuntimeError, '停止自動重送'):
            g.transcribe(args, 'fake-key')
        self.assertEqual(json.loads((third / 'state.json').read_text())['google_resources'], ['files/leftover'])
        self.assertTrue((third / 'raw-transcript.txt').is_file())

    def test_gemini_cancel_during_resume_keeps_request_journal_before_checkpoint(self):
        args = SimpleNamespace(audio=[str(self.source)], run_directory=str(self.old), resume_from=None)
        with mock.patch.object(g.worker, 'prepare', side_effect=self.prepare), \
                mock.patch.object(g, 'transcribe_part', side_effect=RuntimeError('response lost')):
            with self.assertRaisesRegex(RuntimeError, 'response lost'):
                g.transcribe(args, 'fake-key')
        original = self.snapshot(self.old)
        args.run_directory, args.resume_from = str(self.new), str(self.old)
        real_save = g.worker.runtime.save
        def interrupt_after_checkpoint(path, value):
            real_save(path, value)
            if Path(path).name == 'checkpoint.json':
                raise KeyboardInterrupt
        with mock.patch.object(g.worker.runtime, 'save', side_effect=interrupt_after_checkpoint), \
                mock.patch.object(g, 'transcribe_part') as remote:
            with self.assertRaises(KeyboardInterrupt):
                g.transcribe(args, 'fake-key')
        remote.assert_not_called()
        state = json.loads((self.new / 'state.json').read_text())
        self.assertEqual(state['part_requests'], {'1': 'started'})
        g.worker.runtime.finish_error(self.new, state, KeyboardInterrupt())
        third = self.root / 'third'
        third.mkdir()
        args.run_directory, args.resume_from = str(third), str(self.new)
        with mock.patch.object(g, 'transcribe_part') as remote, \
                self.assertRaisesRegex(RuntimeError, '停止自動重送'):
            g.transcribe(args, 'fake-key')
        remote.assert_not_called()
        self.assertEqual(original, self.snapshot(self.old))

    def test_gemini_missing_journal_cannot_publish_resumable_checkpoint(self):
        args = SimpleNamespace(audio=[str(self.source)], run_directory=str(self.old), resume_from=None)
        with mock.patch.object(g.worker, 'prepare', side_effect=self.prepare), \
                mock.patch.object(g, 'transcribe_part', side_effect=RuntimeError('response lost')):
            with self.assertRaises(RuntimeError):
                g.transcribe(args, 'fake-key')
        state = json.loads((self.old / 'state.json').read_text())
        state.pop('part_requests')
        r.save(self.old / 'state.json', state)
        args.run_directory, args.resume_from = str(self.new), str(self.old)
        with mock.patch.object(g, 'transcribe_part') as remote, \
                self.assertRaisesRegex(ValueError, '缺少請求'):
            g.transcribe(args, 'fake-key')
        remote.assert_not_called()
        self.assertFalse((self.new / 'checkpoint.json').exists())


if __name__ == '__main__':
    unittest.main()

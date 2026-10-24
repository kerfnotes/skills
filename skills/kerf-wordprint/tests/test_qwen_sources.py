"""Source-bound ASR regression tests; synthetic PCM and offline backend doubles."""
import dataclasses
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPT = Path(os.environ.get('WORDPRINT_QWEN_SCRIPT',
                            Path(__file__).parents[1] / 'scripts/qwen_worker.py'))
spec = importlib.util.spec_from_file_location('qwen_sources_worker', SCRIPT)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class Samples(list):
    def astype(self, _):
        return self

    def __truediv__(self, divisor):
        return Samples(value / divisor for value in self)


NUMPY = SimpleNamespace(frombuffer=lambda data, **_: Samples(struct.unpack('<' + 'h' * (len(data) // 2), data)),
                        int16='int16', float32='float32')


@dataclasses.dataclass
class Result:
    text: str
    chunks: list
    language: str = 'English'
    segments: object = None
    speaker_segments: object = None
    finish_reason: str = 'eos'
    truncated: bool = False


class SourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = [self.root / 'one.wav', self.root / 'two.wav']
        self.parts = [struct.pack('<h', 4096) * 16003, struct.pack('<h', -8192) * 32007]
        for index, source in enumerate(self.sources):
            source.write_bytes(f'source-{index}'.encode())
        self.calls, self.align_calls = [], []
        self.behavior = self.result
        self.diarizer = mock.Mock(side_effect=lambda pcm, directory, home, duration, state:
                                  ([{'start': 0, 'end': duration, 'speaker': 'S1'}], {'id': 'fake'}))
        backend = SimpleNamespace(transcribe=self.asr, ForcedAligner=lambda **_: SimpleNamespace(align=self.align))
        patches = [mock.patch.dict(sys.modules, {'numpy': NUMPY, 'mlx_qwen3_asr': backend}),
                   mock.patch.object(q, 'prepare', side_effect=self.prepare),
                   mock.patch.object(q, 'snapshot', return_value=Path('/model/cached')),
                   mock.patch.object(q.importlib.metadata, 'version', return_value='test'),
                   mock.patch.object(q.shutil, 'which', return_value='/test/ffmpeg'),
                   mock.patch.object(q, 'diarize', self.diarizer), mock.patch.object(q, 'progress')]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def prepare(self, sources, directory, *_):
        records, pcm = q.combine([{'path': str(source), 'sha256': q.sha256(source), 'pcm': part}
                                 for source, part in zip(sources, self.parts)])
        q.runtime.write_pcm(directory / 'canonical.wav', pcm)
        q.save(directory / 'sources.json', records)
        return records, pcm

    def result(self, samples, index, on_progress):
        length = len(samples) / 16000
        return Result('same words', [{'text': 'same words', 'start': 0, 'end': length,
                                     'chunk_index': 0, 'language': 'English',
                                     'truncated': False, 'finish_reason': 'eos'}])

    def asr(self, *, audio, on_progress, **kwargs):
        self.calls.append(list(audio[0]))
        self.assertEqual(audio[1], 16000)
        self.assertTrue(kwargs['return_chunks'])
        return self.behavior(audio[0], len(self.calls) - 1, on_progress)

    def align(self, samples, text, language):
        self.align_calls.append((list(samples), text, language))
        words = text.split()
        step = len(samples) / 16000 / len(words)
        return [SimpleNamespace(text=word, start_time=i * step, end_time=(i + 1) * step)
                for i, word in enumerate(words)]

    def run_worker(self, name='run', resume=None, main=False):
        directory = self.root / name
        args = SimpleNamespace(audio=[str(p) for p in self.sources], run_directory=str(directory),
                               model='0.6B', resume_from=str(resume) if resume else None)
        if main:
            argv = ['qwen_worker', '--run-directory', str(directory), '--model', '0.6B']
            for source in self.sources:
                argv.extend(['--audio', str(source)])
            with mock.patch.object(sys, 'argv', argv), mock.patch.object(q.signal, 'signal'), \
                 mock.patch.dict(os.environ), mock.patch.object(sys, 'stderr'):
                code = q.main()
            return directory, code
        directory.mkdir()
        q.transcribe(args)
        return directory

    def read(self, directory, name):
        return json.loads((directory / name).read_text())

    def test_unequal_sources_exact_slices_global_clock_and_repeated_text(self):
        directory = self.run_worker()
        self.assertEqual([len(call) for call in self.calls], [16003, 32007])
        self.assertEqual(self.calls, [[.125] * 16003, [-.25] * 32007])
        raw = self.read(directory, 'raw.json')
        self.assertEqual(raw['text'], 'same words\nsame words')
        self.assertEqual([c['chunk_index'] for c in raw['chunks']], [0, 1])
        boundary, end = 16003 / 16000, 48010 / 16000
        self.assertEqual([(c['start'], c['end']) for c in raw['chunks']], [(0, boundary), (boundary, end)])
        run = self.read(directory, 'normalized-run.json')
        self.assertEqual([w['text'] for c in run['chunks'] for w in c['words']], ['same', 'words'] * 2)
        self.assertEqual(run['chunks'][1]['words'][0]['start'], boundary)
        self.assertEqual(self.align_calls[1][0], self.calls[1])
        self.assertEqual(q.runtime.read_pcm(directory / 'canonical.wav'), b''.join(self.parts))
        self.assertEqual(self.diarizer.call_args.args[0], b''.join(self.parts))
        self.assertEqual(self.read(directory, 'state.json')['status'], 'complete')

    def test_multiple_chunks_get_contiguous_global_indices(self):
        def chunks(samples, index, callback):
            result = self.result(samples, index, callback)
            end = len(samples) / 16000
            result.chunks = [{**result.chunks[0], 'start': start, 'end': stop, 'chunk_index': i}
                             for i, (start, stop) in enumerate([(0, end / 2), (end / 2, end)])]
            result.text = 'same words same words'
            return result
        self.behavior = chunks
        directory = self.run_worker()
        raw = self.read(directory, 'raw.json')
        self.assertEqual([c['chunk_index'] for c in raw['chunks']], [0, 1, 2, 3])
        self.assertEqual(self.read(directory, 'raw-source-001.json')['chunks'][0]['start'], 0)

    def test_empty_text_source_is_valid(self):
        def empty(samples, index, callback):
            result = self.result(samples, index, callback)
            if index == 0:
                result.text = result.chunks[0]['text'] = ''
            return result
        self.behavior = empty
        directory = self.run_worker()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.read(directory, 'raw-source-000.json')['text'], '')
        self.assertEqual(self.read(directory, 'state.json')['status'], 'complete')
        self.assertEqual(len(self.align_calls), 1)
        self.assertEqual(self.read(directory, 'normalized-run.json')['chunks'][0]['words'], [])

    def test_later_failure_or_cancel_keeps_completed_and_progress_text(self):
        for error, expected_code, status in [(RuntimeError('later source failed'), 1, 'partial'),
                                             (KeyboardInterrupt(), 130, 'cancelled')]:
            with self.subTest(status=status):
                self.calls.clear()
                directory = self.root / status
                def fail(samples, index, callback):
                    if index == 1:
                        self.assertEqual(self.read(directory, 'raw-source-000.json')['text'], 'same words')
                        self.assertEqual((directory / 'raw-transcript.txt').read_text(), 'same words\n')
                        callback({'event': 'chunk_completed', 'text': 'unfinished words'})
                        raise error
                    return self.result(samples, index, callback)
                self.behavior = fail
                directory, code = self.run_worker(status, main=True)
                self.assertEqual(code, expected_code)
                self.assertEqual((directory / 'raw-transcript.txt').read_text(), 'same words\nunfinished words\n')
                self.assertEqual(self.read(directory, 'checkpoint.json')['stages'], ['decode'])
                state = self.read(directory, 'state.json')
                self.assertEqual((state['status'], state['retry_stage']), (status, 'asr'))
                self.assertIn('raw-source-000.json', state['available_outputs'])

    def test_invalid_local_chunks_rejected_before_offset_and_checkpoint(self):
        for index, invalid in enumerate([{'start': -.001}, {'start': .1}, {'end': 2.01 + 32007 / 16000},
                                         {'end': 0}, {'truncated': True}, {'finish_reason': 'length'}]):
            with self.subTest(invalid=invalid):
                self.calls.clear()
                def bad(samples, source_index, callback):
                    result = self.result(samples, source_index, callback)
                    if source_index == 1:
                        result.chunks[0].update(invalid)
                    return result
                self.behavior = bad
                directory, code = self.run_worker(f'invalid-{index}', main=True)
                self.assertEqual(code, 1)
                self.assertEqual(self.read(directory, 'checkpoint.json')['stages'], ['decode'])
                self.assertEqual(self.read(directory, 'raw-source-001.json')['text'], 'same words')
                self.assertEqual((directory / 'raw-transcript.txt').read_text(), 'same words\nsame words\n')
        self.assertEqual(self.diarizer.call_count, 0)

    def test_long_source_float_endpoint_uses_same_pcm_sample(self):
        # Real library arithmetic: offset + chunk duration exceeds total duration by one ULP.
        count, boundary = 480008, 100001
        self.parts[1] = bytes(count * 2)
        length = count / 16000
        endpoint = boundary / 16000 + (count - boundary) / 16000
        self.assertGreater(endpoint, length)
        def result(samples, index, callback):
            raw = self.result(samples, index, callback)
            if index == 1:
                raw.text = ''
                raw.chunks = [{**raw.chunks[0], 'text': '', 'start': start, 'end': end, 'chunk_index': i}
                              for i, (start, end) in enumerate([(0, boundary / 16000),
                                                               (boundary / 16000, endpoint)])]
            return raw
        self.behavior = result
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'complete')
        self.assertEqual(self.read(directory, 'raw-source-001.json')['chunks'][-1]['end'], endpoint)
        self.assertEqual(self.read(directory, 'raw.json')['chunks'][-1]['end'], 16003 / 16000 + length)
        self.assertEqual(self.read(directory, 'raw.json')['chunks'][1]['start'], 16003 / 16000)

    def test_endpoint_roundoff_limit_rejects_actual_overrun(self):
        length = len(self.parts[1]) / 32000
        for index, extra in enumerate([2 * math.ulp(length), 3 * math.ulp(length), .25 / 16000, 1 / 16000]):
            with self.subTest(extra=extra):
                self.calls.clear()
                def result(samples, source_index, callback):
                    raw = self.result(samples, source_index, callback)
                    if source_index == 1:
                        raw.chunks[-1]['end'] = length + extra
                    return raw
                self.behavior = result
                directory, code = self.run_worker(f'roundoff-{index}', main=True)
                self.assertEqual(code, 0 if index == 0 else 1)
                self.assertEqual(self.read(directory, 'state.json')['status'], 'complete' if index == 0 else 'partial')
                self.assertEqual(self.read(directory, 'raw-source-001.json')['chunks'][-1]['end'], length + extra)
                if index:
                    self.assertEqual(self.read(directory, 'checkpoint.json')['stages'], ['decode'])

    def test_fresh_and_resume_match_and_retain_source_raw(self):
        old = self.run_worker('old')
        self.assertEqual(self.read(old, 'checkpoint.json')['config'].get('asr_partition'), 'source-v1')
        before = {p.name: p.read_bytes() for p in old.iterdir()}
        self.behavior = mock.Mock(side_effect=AssertionError('ASR must not run on resume'))
        new = self.run_worker('new', resume=old)
        self.behavior.assert_not_called()
        for name in ['raw.json', 'raw-source-000.json', 'raw-source-001.json', 'alignment.json', 'canonical.wav']:
            self.assertEqual((old / name).read_bytes(), (new / name).read_bytes())
        self.assertEqual(self.read(new, 'state.json')['status'], 'complete')
        self.assertEqual(before, {p.name: p.read_bytes() for p in old.iterdir()})

    def test_legacy_multi_checkpoint_refused_before_raw_reuse(self):
        old = self.run_worker('old')
        checkpoint = self.read(old, 'checkpoint.json')
        checkpoint['config'].pop('asr_partition', None)
        q.save(old / 'checkpoint.json', checkpoint)
        with self.assertRaisesRegex(ValueError, '設定不符'):
            self.run_worker('new', resume=old)
        self.assertFalse((self.root / 'new/raw.json').exists())

    def test_single_source_raw_and_legacy_resume_unchanged(self):
        self.sources = self.sources[:1]
        old = self.run_worker('old')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.read(old, 'raw.json'), dataclasses.asdict(self.result(self.calls[0], 0, None)))
        self.assertNotIn('asr_partition', self.read(old, 'checkpoint.json')['config'])
        self.behavior = mock.Mock(side_effect=AssertionError('single ASR must be reused'))
        new = self.run_worker('new', resume=old)
        self.behavior.assert_not_called()
        self.assertEqual(self.read(new, 'state.json')['status'], 'complete')


if __name__ == '__main__':
    unittest.main()

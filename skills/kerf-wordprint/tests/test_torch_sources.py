"""Source boundaries, recovery and checkpoint compatibility without models or audio files."""
import array
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('torch_sources_worker', SCRIPTS / 'torch_worker.py')
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class Samples(list):
    def astype(self, _):
        return self

    def __truediv__(self, divisor):
        return Samples(value / divisor for value in self)


def result(text='hello!', end=.8):
    return NS(text=text, language='English', time_stamps=[NS(text='hello', start_time=.1, end_time=end)] if text else [])


class TorchSourcesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / 'run'
        self.directory.mkdir()
        self.names = [str(self.root / 'one.wav'), str(self.root / 'two.wav')]
        for index, name in enumerate(self.names):
            Path(name).write_bytes(f'synthetic source {index}'.encode())
        self.data = [array.array('h', [8192] * 16000).tobytes(),
                     array.array('h', [-16384] * 32000).tobytes()]
        self.results = [result(), result(end=1.8)]
        self.counts = [[3], [5, 7]]
        self.calls = []
        self.generated = mock.Mock(side_effect=lambda **kw: NS(sequences=NS(shape=(1, 2 + self.token_count))))
        self.asr = NS(model=NS(generate=self.generated), transcribe=self.infer)
        modules = {'numpy': NS(frombuffer=lambda data, **kw: Samples(array.array('h', data)),
                               int16='int16', float32='float32'),
                   'torch': NS(cuda=NS(is_available=lambda: False), float32='float32', float16='float16'),
                   'qwen_asr': NS(Qwen3ASRModel=NS(from_pretrained=lambda *a, **kw: self.asr))}
        for patch in [mock.patch.dict(sys.modules, modules),
                      mock.patch.object(t.importlib.metadata, 'version', return_value='stub'),
                      mock.patch.object(t, 'decode', side_effect=lambda name: self.data[self.names.index(name)])]:
            patch.start()
            self.addCleanup(patch.stop)
        self.args = NS(audio=self.names, model='0.6B', max_new_tokens=8, platform='test', fallback=False,
                       pcm=None, resume_from=None, out=str(self.directory / 'normalized-run.json'))

    def infer(self, audio, return_time_stamps):
        self.assertTrue(return_time_stamps)
        index = len(self.calls)
        self.calls.append(audio)
        for self.token_count in self.counts[index]:
            self.asr.model.generate(input_ids=NS(shape=(1, 2)))
        response = self.results[index]
        if isinstance(response, BaseException):
            raise response
        return [response]

    def transcribe(self):
        return t.transcribe(self.asr, self.args.audio, 'Qwen/Qwen3-ASR-0.6B', 8, 'test', 'float32', self.directory)

    def execute(self):
        def diarize(run, samples, _):
            self.assertEqual(len(samples), sum(source['sample_count'] for source in run['sources']))
            run.update(diarization_complete=True, speakers={'S1': {}},
                       turns=[{'start': 0, 'end': len(samples) / 16000, 'speaker': 'S1'}])
        with mock.patch.object(t, 'diarize', side_effect=diarize):
            t.execute(self.args, self.directory)

    def test_duplicate_sources_are_sliced_and_offsets_use_each_duration(self):
        run, samples, pcm = self.transcribe()
        self.assertEqual([len(audio[0]) for audio in self.calls], [16000, 32000])
        self.assertTrue(all(value == .25 for value in self.calls[0][0]))
        self.assertTrue(all(value == -.5 for value in self.calls[1][0]))
        self.assertEqual(pcm, b''.join(self.data))
        self.assertEqual(len(samples), 48000)
        self.assertEqual([(c['start'], c['end'], c['text']) for c in run['chunks']],
                         [(0, 1, 'hello!'), (1, 3, 'hello!')])
        self.assertEqual(run['chunks'][1]['words'], [{'text': 'hello!', 'start': 1.1, 'end': 2.8}])
        self.assertEqual([c['generated_tokens'] for c in run['chunks']], [[3], [5, 7]])
        self.assertEqual((self.directory / 'raw-transcript.txt').read_text(), 'hello!\nhello!\n')
        t.runtime.save(self.directory / 'checked.json', run)
        t.transcript.validate(self.directory / 'checked.json', require_speakers=False)
        self.assertIs(self.asr.model.generate, self.generated)

    def test_source_local_punctuation_and_duplicate_alignment(self):
        self.results = [result('「hello!」'), result(' hello? ', end=1.8)]
        run, _, _ = self.transcribe()
        self.assertEqual([c['words'][0]['text'] for c in run['chunks']], ['「hello!」', ' hello? '])

    def test_empty_source_is_legal_and_does_not_shift_later_words(self):
        self.results[0] = result('')
        self.execute()
        run = json.loads((self.directory / 'normalized-run.json').read_text())
        self.assertEqual(run['chunks'][0]['words'], [])
        self.assertEqual(run['chunks'][1]['words'][0]['start'], 1.1)
        self.assertEqual(json.loads((self.directory / 'state.json').read_text())['status'], 'complete')

    def test_truncation_is_per_source_and_blocks_complete_checkpoint(self):
        self.counts = [[8], [3]]
        self.execute()
        run = json.loads((self.directory / 'normalized-run.json').read_text())
        self.assertEqual([c['truncated'] for c in run['chunks']], [True, False])
        self.assertEqual([c['generated_tokens'] for c in run['chunks']], [[8], [3]])
        self.assertEqual(json.loads((self.directory / 'state.json').read_text())['status'], 'partial')
        self.assertEqual(json.loads((self.directory / 'checkpoint.json').read_text())['stages'], ['decode'])

    def test_later_failure_or_cancel_preserves_first_raw_and_partial_flags(self):
        for failure in [RuntimeError('second failed'), KeyboardInterrupt()]:
            with self.subTest(failure=type(failure).__name__):
                self.calls.clear()
                self.counts = [[8], [2]]
                self.results[1] = failure
                original_infer = self.infer
                def infer(*args, **kwargs):
                    if len(self.calls) == 1:
                        self.assertEqual((self.directory / 'raw-transcript.txt').read_text(), 'hello!\n')
                    return original_infer(*args, **kwargs)
                self.asr.transcribe = infer
                with self.assertRaises(type(failure)):
                    self.transcribe()
                self.assertIs(self.asr.model.generate, self.generated)
                partial = json.loads((self.directory / 'asr-run.json').read_text())
                self.assertTrue(partial['chunks'][0]['truncated'])
                self.assertEqual(partial['chunks'][0]['generated_tokens'], [8])
                self.assertFalse(partial['chunks'][1]['complete'])
                self.assertEqual(partial['chunks'][1]['generated_tokens'], [2])
                self.assertIsNotNone(t.validation_error(self.directory / 'asr-run.json'))
                self.assertFalse((self.directory / 'checkpoint.json').exists())

    def test_generate_failure_restores_wrapper(self):
        self.generated.side_effect = RuntimeError('generation failed')
        with self.assertRaisesRegex(RuntimeError, 'generation failed'):
            self.transcribe()
        self.assertIs(self.asr.model.generate, self.generated)

    def test_cli_later_failure_and_cancel_report_available_partial_outputs(self):
        for failure, code, status in [(RuntimeError('second failed'), 1, 'partial'),
                                      (KeyboardInterrupt(), 130, 'cancelled')]:
            with self.subTest(status=status):
                self.directory = self.root / status
                self.calls.clear()
                self.results[1] = failure
                output = self.directory / 'normalized-run.json'
                argv = ['torch_worker.py', '--out', str(output), '--max-new-tokens', '8']
                for name in self.names:
                    argv.extend(['--audio', name])
                with mock.patch.object(sys, 'argv', argv), mock.patch.object(t.signal, 'signal'), \
                     mock.patch.object(t, 'diarize') as diarize:
                    self.assertEqual(t.main(), code)
                diarize.assert_not_called()
                state = json.loads((self.directory / 'state.json').read_text())
                self.assertEqual(state['status'], status)
                self.assertEqual(state['retry_stage'], 'asr')
                self.assertIn('raw-transcript.txt', state['available_outputs'])
                self.assertIn('asr-run.json', state['available_outputs'])
                self.assertEqual((self.directory / 'raw-transcript.txt').read_text(), 'hello!\n')
                self.assertFalse(output.exists())
                self.assertIs(self.asr.model.generate, self.generated)

    def test_decode_failure_or_cancel_restores_wrapper(self):
        for failure in [RuntimeError('decode failed'), KeyboardInterrupt()]:
            with self.subTest(failure=type(failure).__name__), mock.patch.object(t, 'decode', side_effect=failure):
                with self.assertRaises(type(failure)):
                    self.transcribe()
                self.assertIs(self.asr.model.generate, self.generated)

    def test_alignment_warning_is_retained_and_invalid_text_is_not_repaired(self):
        self.results[1] = result('missing hello', end=1.8)
        with mock.patch('builtins.print') as printed:
            self.execute()
        self.assertTrue(any('對時漏掉' in str(call) for call in printed.call_args_list))
        state = json.loads((self.directory / 'state.json').read_text())
        self.assertEqual(state['status'], 'partial')
        self.assertTrue(state['warnings'])
        self.assertIn('missing hello', (self.directory / 'raw-transcript.txt').read_text())

    def resume(self):
        old = self.directory
        self.directory = self.root / 'resumed'
        self.directory.mkdir()
        self.args.out = str(self.directory / 'normalized-run.json')
        self.args.resume_from = str(old)
        self.calls.clear()
        return old

    def test_old_multi_source_checkpoint_rejected_before_copy(self):
        self.execute()
        path = self.directory / 'checkpoint.json'
        checkpoint = json.loads(path.read_text())
        checkpoint['config'].pop('asr_partition', None)
        t.runtime.save(path, checkpoint)
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        old = self.resume()
        with self.assertRaisesRegex(ValueError, '設定不符'):
            self.execute()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.directory / 'asr-run.json').exists())
        self.assertEqual(before, {p.name: p.read_bytes() for p in old.iterdir()})

    def test_new_multi_source_checkpoint_resumes_without_asr(self):
        self.execute()
        checkpoint = json.loads((self.directory / 'checkpoint.json').read_text())
        self.assertEqual(checkpoint['config']['asr_partition'], 'source-v1')
        self.resume()
        self.execute()
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads((self.directory / 'state.json').read_text())['status'], 'complete')

    def test_single_source_old_checkpoint_and_result_remain_compatible(self):
        self.args.audio = self.names[:1]
        self.execute()
        checkpoint = json.loads((self.directory / 'checkpoint.json').read_text())
        self.assertNotIn('asr_partition', checkpoint['config'])
        run = json.loads((self.directory / 'asr-run.json').read_text())
        self.assertEqual(run['chunks'], [{'start': 0, 'end': 1, 'text': 'hello!',
                                         'words': [{'text': 'hello!', 'start': .1, 'end': .8}],
                                         'complete': True, 'truncated': False, 'generated_tokens': [3]}])
        self.resume()
        self.execute()
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads((self.directory / 'state.json').read_text())['status'], 'complete')


if __name__ == '__main__':
    unittest.main()

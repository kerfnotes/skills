"""Exercise torch admission/completion with synthetic PCM and stub models only."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('torch_validation_worker', SCRIPTS / 'torch_worker.py')
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
r = t.runtime


class Samples(list):
    def astype(self, _):
        return self

    def __truediv__(self, _):
        return self


class TorchValidationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.wav'
        self.source.write_bytes(b'synthetic source')
        self.directory = self.root / 'job'
        self.directory.mkdir()
        self.pcm = b'\0\0' * 16000
        self.run = {'schema_version': 1,
                    'model': {'id': 'Qwen/Qwen3-ASR-0.6B', 'size': '0.6B'},
                    'sources': [{'path': str(self.source), 'sha256': r.digest(self.source),
                                 'sample_count': 16000, 'sample_rate': 16000, 'duration': 1, 'offset': 0}],
                    'chunks': [{'start': 0, 'end': 1, 'text': 'hello world', 'complete': True,
                                'truncated': False, 'words': [{'text': 'hello', 'start': .1, 'end': .4},
                                                            {'text': 'world', 'start': .7, 'end': .9}]}],
                    'turns': [], 'speakers': {}, 'diarization_complete': False}
        self.args = SimpleNamespace(audio=[str(self.source)], model='0.6B', max_new_tokens=2048,
                                    platform='test', fallback=False, pcm=None, resume_from=None,
                                    out=str(self.directory / 'normalized-run.json'))
        self.modules = {'torch': SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False),
                                                float32='float32', float16='float16'),
                        'qwen_asr': SimpleNamespace(Qwen3ASRModel=SimpleNamespace(from_pretrained=lambda *a, **kw: object())),
                        'numpy': SimpleNamespace(frombuffer=lambda *a, **kw: Samples([0.] * 16000),
                                                 int16='int16', float32='float32')}

    def transcribe(self, *args):
        directory = args[-1]
        r.write_pcm(directory / 'canonical.wav', self.pcm)
        r.save(directory / 'sources.json', self.run['sources'])
        return copy.deepcopy(self.run), [0.] * 16000, self.pcm

    @staticmethod
    def diarize(run, *_):
        run.update(diarization_complete=True, speakers={'S1': {}},
                   turns=[{'start': 0, 'end': 1, 'speaker': 'S1'}])

    def execute(self, diarize=None):
        with mock.patch.dict(sys.modules, self.modules), \
             mock.patch.object(t, 'transcribe', side_effect=self.transcribe), \
             mock.patch.object(t, 'diarize', side_effect=diarize or self.diarize) as spy:
            t.execute(self.args, self.directory)
        return json.loads((self.directory / 'state.json').read_text()), spy

    def test_out_of_order_words_preserve_partial_without_checkpoint_or_diarization(self):
        words = self.run['chunks'][0]['words']
        words[0].update(start=.7, end=.9)
        words[1].update(start=.1, end=.4)
        state, spy = self.execute()
        spy.assert_not_called()
        self.assertEqual((state['status'], state['retry_stage']), ('partial', 'asr'))
        self.assertIn('out of order', ' '.join(state['warnings']))
        self.assertEqual((self.directory / 'raw-transcript.txt').read_text(), 'hello world\n')
        self.assertTrue((self.directory / 'normalized-run.json').is_file())
        checkpoint = json.loads((self.directory / 'checkpoint.json').read_text())
        self.assertIn('decode', checkpoint['stages'])
        self.assertNotIn('asr', checkpoint['stages'])

    def test_valid_asr_and_diarization_complete(self):
        state, spy = self.execute()
        spy.assert_called_once()
        self.assertEqual(state['status'], 'complete')
        self.assertIn('asr', json.loads((self.directory / 'checkpoint.json').read_text())['stages'])
        t.transcript.validate(self.directory / 'normalized-run.json')

    def test_invalid_diarization_cannot_be_complete(self):
        def invalid(run, *_):
            self.diarize(run)
            run['turns'][0]['speaker'] = 'missing'
        state, spy = self.execute(invalid)
        spy.assert_called_once()
        self.assertEqual((state['status'], state['retry_stage']), ('partial', 'diarization'))
        self.assertIn('unknown speaker', ' '.join(state['warnings']))

    def test_previously_sealed_invalid_asr_is_rechecked_on_resume(self):
        self.execute()
        old = self.directory
        run = json.loads((old / 'asr-run.json').read_text())
        run['chunks'][0]['words'][1].update(start=0, end=.05)
        r.save(old / 'asr-run.json', run)
        checkpoint = json.loads((old / 'checkpoint.json').read_text())
        # Simulate the old worker sealing malformed ASR with a matching hash.
        r.checkpoint(old, checkpoint['config'], run['sources'], 'asr', ['asr-run.json'])
        before = {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()}
        self.directory = self.root / 'resumed'
        self.directory.mkdir()
        self.args.resume_from = str(old)
        self.args.out = str(self.directory / 'normalized-run.json')
        with mock.patch.dict(sys.modules, self.modules), \
             mock.patch.object(t, 'transcribe', side_effect=AssertionError('must reuse ASR')), \
             mock.patch.object(t, 'diarize') as spy:
            t.execute(self.args, self.directory)
        spy.assert_not_called()
        state = json.loads((self.directory / 'state.json').read_text())
        self.assertEqual((state['status'], state['retry_stage']), ('partial', 'asr'))
        self.assertEqual(before, {p.name: p.read_bytes() for p in old.iterdir() if p.is_file()})


if __name__ == '__main__':
    unittest.main()

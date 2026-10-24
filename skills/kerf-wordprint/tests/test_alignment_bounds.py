"""Offline public-worker regression for a model's terminal timestamp bin."""
import math
from types import SimpleNamespace
import sys
import unittest
from unittest import mock
import test_qwen_sources as source_tests

q = source_tests.q


class AlignmentBoundsTests(unittest.TestCase):
    setUp = source_tests.SourceTests.setUp
    prepare = source_tests.SourceTests.prepare
    result = source_tests.SourceTests.result
    asr = source_tests.SourceTests.asr
    align = source_tests.SourceTests.align
    run_worker = source_tests.SourceTests.run_worker
    read = source_tests.SourceTests.read

    def terminal_case(self, words=None, quantum_ms=80):
        self.sources = self.sources[:1]
        self.parts = [bytes(475798 * 2)]
        self.predictions = words or [(0, 29.6), (29.6, 29.76)]
        backend = sys.modules['mlx_qwen3_asr']
        backend.ForcedAligner = lambda **_: SimpleNamespace(
            _backend=SimpleNamespace(config=SimpleNamespace(timestamp_segment_time=quantum_ms)),
            align=lambda *_: [SimpleNamespace(text=text, start_time=a, end_time=b)
                             for text, (a, b) in zip(['same', 'words'], self.predictions)])

    def test_real_terminal_bin_public_worker(self):
        self.terminal_case()
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'complete')
        words = self.read(directory, 'normalized-run.json')['chunks'][0]['words']
        self.assertEqual(words[-1], {'text': 'words', 'start': 29.6, 'end': 29.737375})
        self.assertEqual(self.read(directory, 'raw.json')['chunks'][0]['end'], 29.737375)
        raw = self.read(directory, 'alignment-raw-0000.json')
        self.assertEqual(raw['words'], [{'text': 'same', 'start_time': 0, 'end_time': 29.6},
                                        {'text': 'words', 'start_time': 29.6, 'end_time': 29.76}])
        report = self.read(directory, 'alignment-boundary-report.json')
        self.assertEqual(report['chunks'][0]['sample_count'], 475798)
        self.assertEqual(report['chunks'][0]['quantum_seconds'], .08)
        self.assertEqual(report['chunks'][0]['adjustments'][0]['original_end'], 29.76)
        self.assertEqual(q.runtime.read_pcm(directory / 'canonical.wav'), self.parts[0])
        self.assertTrue(any('時間格' in w for w in self.read(directory, 'state.json')['warnings']))

    def test_legal_normal_unchanged(self):
        self.terminal_case([(0, 1), (1, 29.7)])
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'complete')
        self.assertEqual(self.read(directory, 'normalized-run.json')['chunks'][0]['words'],
                         [{'text': 'same', 'start': 0, 'end': 1}, {'text': 'words', 'start': 1, 'end': 29.7}])
        self.assertEqual(self.read(directory, 'alignment-boundary-report.json')['chunks'][0]['adjustments'], [])
        self.assertEqual(self.read(directory, 'state.json')['warnings'], [])

    def test_invalid_predictions_stay_partial(self):
        cases = [[(0, 29.6), (29.6, 29.84)], [(0, 29.6), (29.74, 29.76)],
                 [(0, 29.76), (29.6, 29.737375)], [(0, 29.6), (29.6, 29.759)],
                 [(-.1, 29.6), (29.6, 29.76)], [(0, 29.6), (29.6, float('nan'))],
                 [(0, 29.6), (float('inf'), 29.76)], [(0, 29.6), (29.6, 29.5)],
                 [(0, 29.6), (29.6, math.nextafter(29.76, math.inf))]]
        for index, words in enumerate(cases):
            with self.subTest(words=words):
                self.terminal_case(words)
                directory = self.run_worker(f'invalid-{index}')
                self.assertEqual(self.read(directory, 'state.json')['status'], 'partial')
                self.assertEqual(self.read(directory, 'checkpoint.json')['stages'], ['decode', 'asr'])
                raw = self.read(directory, 'alignment-raw-0000.json')
                self.assertEqual(len(raw['words']), 2)
                for record, (start, end) in zip(raw['words'], words):
                    for key, value in [('start_time', start), ('end_time', end)]:
                        if math.isnan(value):
                            self.assertTrue(math.isnan(record[key]))
                        else:
                            self.assertEqual(record[key], value)
        self.diarizer.assert_not_called()

    def test_exact_pcm_grid_endpoint_rejects_next_bin_public_worker(self):
        self.terminal_case([(0, .4), (.4, .64)])
        self.parts = [bytes(8960 * 2)]  # .56 / .08 is 7.000000000000001 in float.
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'partial')
        self.assertEqual(self.read(directory, 'normalized-run.json')['chunks'][0]['words'][-1]['end'], .64)
        self.diarizer.assert_not_called()

    def test_clipping_cannot_create_end_inversion(self):
        self.terminal_case([(0, 29.75), (29.6, 29.76)])
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'partial')
        self.assertEqual(self.read(directory, 'checkpoint.json')['stages'], ['decode', 'asr'])
        self.assertEqual([w['end'] for w in self.read(directory, 'alignment.json')[0]['words']],
                         [29.75, 29.76])
        self.assertEqual(self.read(directory, 'alignment-boundary-report.json')['chunks'][0]['adjustments'], [])
        self.diarizer.assert_not_called()

    def test_resume_rejects_previous_adjustment_with_end_inversion(self):
        self.terminal_case()
        old = self.run_worker('old')
        alignment = self.read(old, 'alignment.json')
        alignment[0]['words'][0]['end'] = 29.75
        q.save(old / 'alignment.json', alignment)
        checkpoint = self.read(old, 'checkpoint.json')
        checkpoint['artifacts']['alignment.json'] = q.runtime.digest(old / 'alignment.json')
        q.save(old / 'checkpoint.json', checkpoint)
        self.diarizer.reset_mock()
        self.behavior = mock.Mock(side_effect=AssertionError('ASR must remain reusable'))
        new = self.run_worker('new', resume=old)
        self.assertEqual(self.read(new, 'state.json')['status'], 'partial')
        self.assertEqual(self.read(new, 'state.json')['retry_stage'], 'alignment')
        self.diarizer.assert_not_called()

    def test_all_exact_grid_endpoints_and_decimal_model_representation(self):
        for index in range(1, 376):
            count = index * 1280
            end = (index + 1) * 80 / 1000  # Official parser's milliseconds -> decimal seconds.
            words = [{'text': 'x', 'start': 0., 'end': end}]
            bounded, changes = q.runtime.bound_alignment_terminal_bin(
                words, sample_count=count, sample_rate=16000, quantum_seconds=.08)
            self.assertEqual((bounded, changes), (words, []), index)
            # One sample below the next grid point: only that terminal bin is bounded.
            bounded, changes = q.runtime.bound_alignment_terminal_bin(
                words, sample_count=(index + 1) * 1280 - 1, sample_rate=16000, quantum_seconds=.08)
            self.assertEqual(bounded[0]['end'], ((index + 1) * 1280 - 1) / 16000, index)
            self.assertEqual(len(changes), 1)
            self.assertEqual(words[0]['end'], end)  # Pure helper retains the input.

    def test_selected_config_quantum_is_used(self):
        self.terminal_case([(0, 29.6), (29.6, 29.74)], quantum_ms=40)
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'complete')
        self.assertEqual(self.read(directory, 'alignment-boundary-report.json')['chunks'][0]['quantum_seconds'], .04)

    def test_unknown_quantum_is_not_guessed(self):
        self.terminal_case(quantum_ms=None)
        directory = self.run_worker()
        self.assertEqual(self.read(directory, 'state.json')['status'], 'partial')
        self.assertEqual(self.read(directory, 'normalized-run.json')['chunks'][0]['words'][-1]['end'], 29.76)

    def test_resume_preserves_raw_report_warning_and_old_run(self):
        self.terminal_case()
        old = self.run_worker('old')
        before = {p.name: p.read_bytes() for p in old.iterdir()}
        self.behavior = mock.Mock(side_effect=AssertionError('ASR must be reused'))
        sys.modules['mlx_qwen3_asr'].ForcedAligner = mock.Mock(side_effect=AssertionError('alignment must be reused'))
        new = self.run_worker('new', resume=old)
        checkpoint = self.read(new, 'checkpoint.json')
        for name in ['alignment-raw-0000.json', 'alignment-boundary-report.json', 'alignment-model.json']:
            self.assertIn(name, checkpoint['artifacts'])
            self.assertEqual((new / name).read_bytes(), before[name])
        self.assertEqual(self.read(new, 'state.json')['warnings'], self.read(old, 'state.json')['warnings'])
        self.assertEqual(self.read(new, 'state.json')['status'], 'complete')
        self.assertEqual(before, {p.name: p.read_bytes() for p in old.iterdir()})

    def test_legacy_legal_checkpoint_without_new_evidence(self):
        self.terminal_case([(0, 1), (1, 29.7)])
        old = self.run_worker('old')
        checkpoint = self.read(old, 'checkpoint.json')
        for name in list(checkpoint['artifacts']):
            if name.startswith('alignment-raw-') or name == 'alignment-boundary-report.json':
                checkpoint['artifacts'].pop(name)
                (old / name).unlink()
        q.save(old / 'checkpoint.json', checkpoint)
        new = self.run_worker('new', resume=old)
        self.assertEqual(self.read(new, 'state.json')['status'], 'complete')

    def test_resume_refuses_tampered_evidence(self):
        self.terminal_case()
        old = self.run_worker('old')
        (old / 'alignment-boundary-report.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, '完整性'):
            self.run_worker('new', resume=old)
        self.assertFalse((self.root / 'new/alignment.json').exists())


if __name__ == '__main__':
    unittest.main()

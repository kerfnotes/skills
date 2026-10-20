"""Small offline checks; model accuracy and platform inference require audio smoke tests."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'transcript.py'
spec = importlib.util.spec_from_file_location('wordprint_transcript', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '音 訊.wav').write_bytes(b'fixture audio identity')
        self.path = self.root / 'run.json'
        self.run = {
            'schema_version': 1, 'model': {'id': 'Qwen/Qwen3-ASR-0.6B', 'size': '0.6B'},
            'diarization_complete': True,
            'sources': [{'path': '音 訊.wav', 'sha256': hashlib.sha256(b'fixture audio identity').hexdigest(),
                         'duration': 3, 'offset': 0}],
            'chunks': [{'start': 0, 'end': 3, 'text': '你好，嗯？好。', 'complete': True, 'truncated': False,
                        'words': [{'text': '你好', 'start': 0, 'end': 1},
                                  {'text': '嗯', 'start': 1, 'end': 1.2},
                                  {'text': '好', 'start': 1.2, 'end': 2}]}],
            'turns': [{'start': 0, 'end': 1, 'speaker': 'S1'},
                      {'start': 1, 'end': 1.2, 'speaker': 'S2'},
                      {'start': 1.2, 'end': 2, 'speaker': 'S1'}],
            'speakers': {'S1': {}, 'S2': {'name': '陳先生', 'status': 'possible', 'evidence': '使用者：中間插話可能是陳先生'}},
            'participant_candidates': ['王小姐'],
        }

    def validate(self):
        self.path.write_text(json.dumps(self.run, ensure_ascii=False), encoding='utf-8')
        return m.validate(self.path)

    def test_render_preserves_original_and_short_interjection(self):
        run, report = self.validate()
        rows = list(m.rows(run))
        self.assertEqual(''.join(row['text'] for row in rows), self.run['chunks'][0]['text'])
        self.assertEqual([row['speakers'] for row in rows], [('S1',), ('S2',), ('S1',)])
        result = m.render(run, report, self.root / 'output', original_script=True)
        self.assertEqual(result['words'], 3)
        output = self.root / 'output'
        self.assertEqual((output / 'raw.txt').read_text(encoding='utf-8'), '你好，嗯？好。\n')
        self.assertIn('可能是 陳先生', (output / 'transcript.md').read_text(encoding='utf-8'))
        self.assertNotIn('王小姐', (output / 'transcript.md').read_text(encoding='utf-8'))
        self.assertEqual(m.validate(output / 'run.json')[1]['sources'], 1)
        with self.assertRaisesRegex(m.Invalid, 'already exists'):
            m.render(run, report, output, original_script=True)

    def test_no_alignment_truncation_or_changed_source_cannot_succeed(self):
        for mutation, message in [
            (lambda r: r['chunks'][0].pop('words'), 'alignment'),
            (lambda r: r['chunks'][0].update(truncated=True), 'truncated'),
            (lambda r: r['chunks'][0].update(end=2), 'recording end'),
            (lambda r: r['chunks'][0].update(start=0.2), 'continuously'),
            (lambda r: r['sources'][0].update(offset=1), 'continuous'),
            (lambda r: r.update(diarization_complete=False), 'diarization_complete'),
            (lambda r: r['turns'][0].update(speaker='S3'), 'unknown speaker'),
            (lambda r: r['speakers']['S2'].update(name={'bad': 'type'}), 'string required'),
            (lambda r: r['chunks'][0]['words'][0].update(text='錯誤'), 'differs'),
            (lambda r: r['chunks'][0]['words'][0].update(end=float('nan')), 'finite'),
            (lambda r: r['model'].update(size='1.7B'), 'disagree'),
            (lambda r: r['chunks'][0]['words'][0].update(end=3.03), 'invalid time'),
            (lambda r: r['chunks'][0]['words'][1].update(start=0.5, end=0.6), 'out of order'),
            (lambda r: r['chunks'][0]['words'][1].update(text='！'), 'standalone punctuation'),
            (lambda r: r['chunks'].append(dict(r['chunks'][0])), 'continuously'),
            (lambda r: r['sources'][0].update(sample_count=32000, sample_rate=16000), 'PCM sample count'),
            (lambda r: r['sources'][0].update(sample_count=48000), 'positive integers'),
            (lambda r: r['chunks'][0].update(text='ß', words=[{'text':'s','start':0,'end':1},
                                                            {'text':'s','start':1,'end':2}]), 'source character'),
        ]:
            with self.subTest(message=message):
                original = json.loads(json.dumps(self.run))
                mutation(self.run)
                with self.assertRaisesRegex(m.Invalid, message):
                    self.validate()
                self.run = original
        self.path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
        with self.assertRaisesRegex(m.Invalid, 'duplicate JSON key'):
            m.validate(self.path)
        (self.root / '音 訊.wav').write_bytes(b'replaced')
        with self.assertRaisesRegex(m.Invalid, 'SHA256 mismatch'):
            self.validate()

    def test_overlap_boundary_and_missing_diarization_are_distinct(self):
        word = {'start': 0, 'end': 1}
        overlap = [{'start': 0, 'end': 1, 'speaker': 'S1'}, {'start': 0.4, 'end': 0.6, 'speaker': 'S2'}]
        boundary = [{'start': 0, 'end': 0.5, 'speaker': 'S1'}, {'start': 0.5, 'end': 1, 'speaker': 'S2'}]
        self.assertEqual(m.classify(word, overlap), ('overlap', ('S1', 'S2')))
        self.assertEqual(m.classify(word, boundary), ('uncertain', ('S1', 'S2')))
        self.assertEqual(m.classify(word, []), ('unknown', ()))
        self.assertEqual(m.classify(word, [{'start': 0, 'end': 0.4, 'speaker': 'S1'}]), ('uncertain', ('S1',)))
        self.assertEqual(m.classify({'start': 0.5, 'end': 0.5}, overlap), ('uncertain', ('S1', 'S2')))
        self.assertEqual(m.classify({'start': 0.2, 'end': 0.2}, overlap), ('uncertain', ('S1',)))
        self.run['turns'] = []
        run, _ = self.validate()
        self.assertEqual(list(m.rows(run))[0]['kind'], 'unknown')

    def test_silence_multisource_casefold_and_punctuation(self):
        self.run['sources'][0].update(sample_count=48000, sample_rate=16000)
        self.run['sources'] *= 2
        self.run['sources'] = [dict(s) for s in self.run['sources']]
        self.run['sources'][1]['offset'] = 3
        self.run['chunks'].append({'start': 3, 'end': 6, 'text': '', 'words': [], 'complete': True, 'truncated': False})
        run, report = self.validate()
        self.assertEqual(report['duration'], 6)
        chunk = {'text': '「Straße」，好！', 'words': [{'text': 'STRASSE'}, {'text': '好'}]}
        self.assertEqual([text for _, text in m.pieces(chunk)], ['「Straße」，', '好！'])
        chunk = {'text': '你好，「嗯」好。', 'words': [{'text': '你好'}, {'text': '嗯'}, {'text': '好'}]}
        self.assertEqual([text for _, text in m.pieces(chunk)], ['你好，', '「嗯」', '好。'])
        self.assertEqual(m.normalized(' A，B！'), 'ab')
        self.assertNotEqual(m.normalized('a+b'), m.normalized('ab'))
        self.assertEqual(m.stamp(59.9999), '00:01:00.000')

    def test_cli_failure_never_creates_success_artifacts(self):
        self.run['chunks'][0].pop('words')
        self.path.write_text(json.dumps(self.run), encoding='utf-8')
        output = self.root / 'must-not-exist'
        result = subprocess.run([sys.executable, str(SCRIPT), 'render', str(self.path), '--output',
                                 str(output), '--original-script'], capture_output=True, text=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stderr)['ok'])
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.transcript-*')))

    def test_html_srt_and_playback(self):
        import wave
        with wave.open(str(self.root / 'canonical.wav'), 'wb') as audio:
            audio.setnchannels(1), audio.setsampwidth(2), audio.setframerate(16000)
            audio.writeframes(b'\0\0' * 48000)
        self.run['pcm'] = 'canonical.wav'
        self.run['speakers']['S2']['name'] = '陳<先生>'
        run, report = self.validate()
        result = m.render(run, report, self.root / 'out', original_script=True, title='週會 <草稿>')
        out = self.root / 'out'
        self.assertTrue(result['srt_written'] and result['playback_written'] and result['pcm_verified'])
        self.assertEqual((out / 'playback.wav').read_bytes(), (self.root / 'canonical.wav').read_bytes())
        page = (out / 'transcript.html').read_text(encoding='utf-8')
        self.assertIn('src="playback.wav"', page)
        self.assertIn('需與 playback.wav 同資料夾', page)
        self.assertIn('data-start="1.000"', page)
        self.assertIn('週會 &lt;草稿&gt;', page)
        self.assertIn('陳&lt;先生&gt;', page)
        self.assertNotIn('<先生>', page)  # The Markdown payload escapes '<' too.
        self.assertIn('mailto:?subject=', page)
        srt = (out / 'transcript.srt').read_text(encoding='utf-8')
        self.assertTrue(srt.startswith('1\n00:00:00,000 --> 00:00:01,000\n[S1] 你好，'))
        self.assertIn('[S2｜可能是 陳<先生>] ', srt)
        # Re-render from the output directory still finds playback audio.
        self.assertTrue(m.validate(out / 'run.json')[1]['pcm_verified'])

        self.run['chunks'][0]['words'][1].update(start=1.2, end=1.2)
        run, report = self.validate()
        result = m.render(run, report, self.root / 'zero', original_script=True)
        self.assertFalse(result['srt_written'])
        self.assertFalse((self.root / 'zero' / 'transcript.srt').exists())
        self.run['sources'][0]['duration'] = 2
        self.run['chunks'][0]['end'] = 2
        with self.assertRaisesRegex(m.Invalid, 'pcm: sample count'):
            self.validate()

    def test_pcm_header_frames_beyond_data_is_rejected(self):
        import wave
        pcm = self.root / 'canonical.wav'
        with wave.open(str(pcm), 'wb') as audio:
            audio.setnchannels(1), audio.setsampwidth(2), audio.setframerate(16000)
            audio.writeframes(b'\0\0' * 16000)
        os.truncate(pcm, os.path.getsize(pcm) - 16000)  # Header still says 16000 frames; 8000 remain.
        self.run['pcm'] = 'canonical.wav'
        self.run['sources'][0]['duration'] = 1
        self.run['chunks'][0]['end'] = 1
        self.run['chunks'][0]['words'] = [{'text': '你好嗯好', 'start': 0, 'end': 1}]
        with self.assertRaisesRegex(m.Invalid, 'declares 16000 frames but data holds 8000'):
            self.validate()

    def test_srt_skipped_when_millisecond_rounding_collapses_a_row(self):
        self.run['chunks'][0]['words'][0].update(start=0.0001, end=0.0002)
        run, report = self.validate()
        result = m.render(run, report, self.root / 'out', original_script=True)
        self.assertFalse(result['srt_written'])
        self.assertIn('millisecond rounding', result['srt_reason'])
        self.assertFalse((self.root / 'out' / 'transcript.srt').exists())
        self.assertEqual(json.loads((self.root / 'out' / 'validation.json').read_text(encoding='utf-8'))['srt_written'], False)

    def test_page_without_pcm_promises_no_playback(self):
        run, report = self.validate()
        result = m.render(run, report, self.root / 'out', original_script=True)
        page = (self.root / 'out' / 'transcript.html').read_text(encoding='utf-8')
        self.assertFalse(result['playback_written'])
        self.assertNotIn('<audio', page)
        self.assertNotIn('跳到該處播放', page)
        self.assertIn('此份沒有音訊，無法跳播', page)
        self.assertFalse((self.root / 'out' / 'playback.wav').exists())

    def test_opencc_absence_leaves_no_output_and_name_edit_reuses_text(self):
        run, report = self.validate()
        with self.assertRaisesRegex(m.Invalid, 'OpenCC not found'):
            m.render(run, report, self.root / 'missing', opencc='certainly-not-installed-opencc-command')
        self.assertFalse((self.root / 'missing').exists())
        run['speakers']['S2'] = {'name': '李先生', 'status': 'confirmed', 'evidence': '使用者確認'}
        m.render(run, report, self.root / 'renamed', original_script=True)
        rendered = (self.root / 'renamed' / 'transcript.txt').read_text(encoding='utf-8')
        self.assertIn('S2｜李先生', rendered)
        self.assertNotIn('可能是', rendered)
        self.assertEqual((self.root / 'renamed' / 'raw.txt').read_text(encoding='utf-8'), '你好，嗯？好。\n')


if __name__ == '__main__':
    unittest.main()

"""Gemini response → normalized run, no network.

The interactions below are HAND-BUILT from the documented response shape
(ai.google.dev/gemini-api/docs/transcribe, 2026-10-21); replace them with a saved real response once one exists.
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
import wave
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(f'wordprint_{name}', SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


g, t = load('gemini_transcribe'), load('transcript')


def interaction(text, words, status='completed'):
    return {'id': 'interactions/abc123xyz', 'status': status, 'steps': [{'id': 'step_001', 'type': 'model_output', 'content': [
        {'type': 'text', 'text': text, 'annotations': [
            {'type': 'word_info', 'text': w, 'speaker': s, 'start_offset': f'{a:.3f}s', 'end_offset': f'{b:.3f}s'}
            for w, s, a, b in words]}]}]}


PART_1 = interaction('大家好，今天測試。', [('大家', 'spk_2', .1, .4), ('好', 'spk_2', .4, .6), ('，', 'spk_2', .6, .6),
                                            ('今天', 'spk_1', .8, 1.2), ('測試', 'spk_1', 1.2, 1.6)])
PART_2 = interaction('Hello world.', [('Hello', 'spk_1', .1, .45), ('world', 'spk_1', .5, .85)])


class GeminiTests(unittest.TestCase):
    def validate(self, converted, seconds):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'source.wav'
            with wave.open(str(audio), 'wb') as file:
                file.setnchannels(1), file.setsampwidth(2), file.setframerate(16000)
                file.writeframes(b'\0\0' * 16000 * seconds)
            run = {'schema_version': 1, 'model': {'id': g.MODEL, 'size': None}, 'pcm': str(audio),
                   'sources': [{'path': str(audio), 'sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
                                'duration': seconds, 'offset': 0}], **converted}
            del run['warnings']
            (Path(folder) / 'run.json').write_text(json.dumps(run, ensure_ascii=False))
            return t.validate(Path(folder) / 'run.json')[1]

    def test_two_parts_offset_and_keep_ids_apart(self):
        converted = g.convert([PART_1, PART_2], [(0, 2), (2, 4)])
        self.assertEqual([w['text'] for w in converted['chunks'][0]['words']], ['大家', '好，', '今天', '測試'])
        self.assertEqual(converted['chunks'][1]['words'][0], {'text': 'Hello', 'start': 2.1, 'end': 2.45})
        self.assertEqual([(x['speaker'], x['start'], x['end']) for x in converted['turns']],
                         [('part-1-spk_2', .1, .6), ('part-1-spk_1', .8, 1.6), ('part-2-spk_1', 2.1, 2.85)])
        self.assertTrue(converted['diarization_complete'])
        self.assertEqual(converted['warnings'], [])
        self.assertEqual(self.validate(converted, 4)['words'], 6)

    def test_single_part_uses_first_speech_order(self):
        converted = g.convert([PART_1], [(0, 2)])
        self.assertEqual([x['speaker'] for x in converted['turns']], ['S1', 'S2'])
        self.assertEqual(self.validate(converted, 2)['chunks'], 1)

    def test_incomplete_missing_speaker_word_or_late_time_are_partial(self):
        converted = g.convert([interaction('Hello world.', [('Hello', 'spk_1', .1, .45)], 'incomplete')], [(0, 2)])
        self.assertEqual((converted['chunks'][0]['complete'], converted['chunks'][0]['truncated']), (True, True))
        self.assertFalse(converted['diarization_complete'])
        converted = g.convert([interaction('Hello world', [('Hello', 'spk_1', .1, .45), ('world', None, .5, .8)])], [(0, 2)])
        self.assertFalse(converted['diarization_complete'])
        for text, words in [('Hello world', [('Hello', 'spk_1', .1, .45)]), ('Hello world', []),
                            ('Hello', [('Hello', 'spk_1', 10, 11)])]:
            converted = g.convert([interaction(text, words)], [(0, 2)])
            self.assertEqual(converted['chunks'][0]['text'], text)
            self.assertFalse(converted['diarization_complete'])
            self.assertEqual(len(converted['warnings']), 1)
        self.assertEqual(converted['chunks'][0]['words'][0]['end'], 11)

    def test_failed_interaction_still_deletes_upload(self):
        calls = []

        def call(url, key, method='GET', body=None, raw=False, **_):
            calls.append((method, url))
            if raw:
                return type('R', (), {'headers': {'X-Goog-Upload-URL': 'upload'}})
            if url == 'upload':
                return {'file': {'name': 'files/f1', 'uri': 'u', 'state': 'ACTIVE'}}
            if url.endswith('/interactions'):
                raise RuntimeError('boom')
            return {}
        with mock.patch.object(g, 'call', call), tempfile.TemporaryDirectory() as folder:
            part, state = Path(folder) / 'part-001.wav', {'google_resources': [], 'warnings': []}
            part.write_bytes(b'RIFF')
            with self.assertRaises(RuntimeError):
                g.transcribe_part(part, 'k', state)
            self.assertEqual(json.loads((Path(folder) / 'state.json').read_text())['google_resources'], [])
        self.assertEqual(calls[-1], ('DELETE', f'{g.API}/v1beta/files/f1'))

if __name__ == '__main__':
    unittest.main()

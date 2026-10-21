"""Worker checks that need no model, ffmpeg, or audio backend."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(f'wordprint_{name}', SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


w = load('qwen_worker')


class WorkerTests(unittest.TestCase):
    def test_check_chunks(self):
        good = [{'start': 0, 'end': 1, 'truncated': False, 'finish_reason': 'eos'},
                {'start': 1, 'end': 2, 'truncated': False, 'finish_reason': 'repetition'}]
        w.check_chunks(good, 2)
        for chunks, duration, message in [
            ([], 2, '沒有完整'),
            ([dict(good[0], truncated=True)], 1, '截斷'),
            ([dict(good[0], finish_reason='length')], 1, '截斷'),
            ([good[0], dict(good[1], start=1.5)], 2, '不連續'),
            (good, 3, '結尾'),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                w.check_chunks(chunks, duration)

    def test_combine_offsets_follow_sample_counts(self):
        parts = [{'path': '/a.wav', 'sha256': 'a' * 64, 'pcm': b'\1\0' * 16000, 'probe_duration': '1.02'},
                 {'path': '/b.wav', 'sha256': 'b' * 64, 'pcm': b'\2\0' * 8000}]
        records, pcm = w.combine(parts)
        self.assertEqual([r['offset'] for r in records], [0, 1])
        self.assertEqual([r['sample_count'] for r in records], [16000, 8000])
        self.assertEqual(records[1]['duration'], 0.5)
        self.assertEqual(len(pcm) // 2, 24000)
        self.assertEqual(pcm[32000:32002], b'\2\0')
        with self.assertRaisesRegex(ValueError, '不完整'):
            w.combine([{'path': '/c.wav', 'sha256': 'c' * 64, 'pcm': b'\0'}])

    def test_speaker_ids(self):
        turns = [{'start': 2, 'end': 3, 'speaker': (0, 0)}, {'start': 0, 'end': 2, 'speaker': (0, 1)}]
        self.assertEqual([t['speaker'] for t in w.name_speakers([dict(t) for t in turns], 1)], ['S1', 'S2'])
        self.assertEqual([t['speaker'] for t in w.name_speakers([dict(t) for t in turns], 2)],
                         ['window-1-speaker-2', 'window-1-speaker-1'])


def write_wav(path, frames, keep_bytes=None):
    """16 kHz mono WAV whose header declares `frames`; keep_bytes truncates the data chunk afterwards."""
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1), audio.setsampwidth(2), audio.setframerate(16000)
        audio.writeframes(b'\1\0' * frames)
    if keep_bytes is not None:
        os.truncate(path, os.path.getsize(path) - frames * 2 + keep_bytes)


class WorkerIOTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.m4a'
        self.source.write_bytes(b'original audio')
        self.run = self.root / 'run'
        self.run.mkdir()

    def fake_command(self, frames=16000, keep_bytes=None, mutate=False):
        def command(arguments, directory, name, timeout=None):
            if name.startswith('probe'):
                return '{"format": {"duration": "1.0"}}'
            write_wav(Path(arguments[-1]), frames, keep_bytes)
            if mutate:
                self.source.write_bytes(b'replaced while decoding')
            return ''
        return command

    def test_rejected_run_directory_is_left_byte_identical(self):
        (self.run / 'raw.json').write_text('{"text": "keep"}')
        (self.run / 'state.json').write_text('{"stage":"complete"}')
        before = {p.name: p.read_bytes() for p in self.run.iterdir()}
        result = subprocess.run([sys.executable, str(SCRIPTS / 'qwen_worker.py'), '--audio', str(self.source),
                                 '--run-directory', str(self.run), '--model', '0.6B'],
                                capture_output=True, text=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 1)
        self.assertIn('既有目錄未改動', result.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in self.run.iterdir()}, before)

    def test_source_changed_during_decode_fails_with_both_hashes(self):
        with mock.patch.object(w, 'command', self.fake_command(mutate=True)), \
                self.assertRaisesRegex(RuntimeError, '解碼期間被更動'):
            w.decode_source(self.source, 0, self.run, 'ffmpeg', 'ffprobe')
        [record] = json.loads((self.run / 'sources.json').read_text(encoding='utf-8'))
        self.assertEqual(record['sha256_before_decode'], w.hashlib.sha256(b'original audio').hexdigest())
        self.assertEqual(record['sha256_after_decode'], w.hashlib.sha256(b'replaced while decoding').hexdigest())
        self.assertTrue((self.run / 'decode-000.wav').is_file())  # Decoded evidence kept.

    def test_decode_rejects_header_frames_beyond_data(self):
        with mock.patch.object(w, 'command', self.fake_command(frames=16000, keep_bytes=16000)), \
                self.assertRaisesRegex(ValueError, '宣告 16000 frames，實讀 8000'):
            w.decode_source(self.source, 0, self.run, 'ffmpeg', 'ffprobe')
        with mock.patch.object(w, 'command', self.fake_command()):
            part = w.decode_source(self.source, 0, self.run, 'ffmpeg', 'ffprobe')
        self.assertEqual((len(part['pcm']), part['sha256']), (32000, w.hashlib.sha256(b'original audio').hexdigest()))

    def test_success_records_both_decode_hashes(self):
        with mock.patch.object(w, 'command', self.fake_command()):
            part = w.decode_source(self.source, 0, self.run, 'ffmpeg', 'ffprobe')
        [record], _ = w.combine([part])
        digest = w.hashlib.sha256(b'original audio').hexdigest()
        self.assertEqual((record['sha256'], record['sha256_before_decode'], record['sha256_after_decode']), (digest,) * 3)


if __name__ == '__main__':
    unittest.main()

"""Synthetic public-render regression checks; no media or model access."""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'scripts' / 'transcript.py'
spec = importlib.util.spec_from_file_location('opencc_batch_transcript', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(texts):
    return {'model': {'id': 'synthetic'}, 'speakers': {'S1': {'name': '电脑', 'status': 'confirmed'}},
            'sources': [{'path': '/synthetic/电脑.wav', 'offset': 0, 'duration': max(1, len(texts))}],
            'turns': [], 'chunks': [{'text': text, 'start': i, 'end': i + 1, 'words': []}
                                    for i, text in enumerate(texts)]}


def reading_rows(texts):
    return [dict(text=text, start=i, end=i + 1, kind='speaker', speakers=('S1',))
            for i, text in enumerate(texts)]


class OpenCCBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(m, 'clayprint_css', return_value='').start()

    def test_public_render_starts_cli_once(self):
        # Real rows() call site: two chunks are enough to expose process-per-row cost.
        run = fixture(['电脑', '会议'])
        with patch.object(m.shutil, 'which', return_value='/synthetic/opencc') as which, patch.object(
                m.subprocess, 'run', side_effect=lambda *a, **kw: types.SimpleNamespace(
                    returncode=0, stdout=kw['input'], stderr=b'' if isinstance(kw['input'], bytes) else '')) as child:
            m.render(run, {'duration': 2}, self.root / 'out', opencc='explicit-opencc')
        which.assert_called_once_with('explicit-opencc')
        self.assertEqual(child.call_count, 1)
        self.assertEqual(child.call_args.args[0], ['/synthetic/opencc', '-c', 's2twp.json'])

    def test_bad_cli_output_never_publishes(self):
        for kind in ('error', 'empty', 'prefix', 'suffix', 'missing', 'duplicate', 'rowcount', 'blankrow'):
            with self.subTest(kind=kind):
                def broken(*a, **kw):
                    value = kw['input']
                    binary = isinstance(value, bytes)
                    if binary: value = value.decode('utf-8')
                    if kind == 'empty': value = ''
                    if kind == 'prefix': value = 'unexpected' + value
                    if kind == 'suffix': value += 'unexpected'
                    if kind == 'missing': value = value.replace('WORDPRINT', 'BROKEN', 1)
                    if kind == 'duplicate': value += value
                    if kind == 'rowcount': value = value.replace('\n__WORDPRINT_OPENCC_0__\n', '', 1)
                    if kind == 'blankrow': value = value.replace('电脑', '')
                    return types.SimpleNamespace(returncode=1 if kind == 'error' else 0,
                                                 stdout=value.encode('utf-8') if binary else value,
                                                 stderr=b'synthetic failure' if binary else 'synthetic failure')
                with patch.object(m.shutil, 'which', return_value='/synthetic/opencc'), patch.object(
                        m.subprocess, 'run', side_effect=broken):
                    with self.assertRaisesRegex(m.Invalid, 'OpenCC failed'):
                        m.render(fixture(['电脑', '会议']), {'duration': 2}, self.root / kind)
                self.assertFalse((self.root / kind).exists())
                self.assertFalse(list(self.root.glob('.transcript-*')))

    def test_binding_fallback_and_original_script(self):
        texts = ['电脑', '第一行\n第二行', '', '结尾\r\n']
        binding = types.SimpleNamespace(convert=lambda text: text.replace('电脑', '電腦'))
        module = types.SimpleNamespace(OpenCC=lambda config: binding)
        with patch.object(m, 'rows', return_value=reading_rows(texts)), patch.object(
                m.shutil, 'which', return_value=None), patch.dict(sys.modules, {'opencc': module}), patch.object(
                m.subprocess, 'run', side_effect=AssertionError('CLI must not run')):
            m.render(fixture(texts), {'duration': len(texts)}, self.root / 'binding')
            m.render(fixture(texts), {'duration': len(texts)}, self.root / 'original', original_script=True)
        self.assertIn('電腦', (self.root / 'binding/transcript.txt').read_text())
        self.assertIn('电脑', (self.root / 'original/transcript.txt').read_text())

    def test_no_rows_and_existing_output_do_not_start_cli(self):
        with patch.object(m.shutil, 'which', return_value='/synthetic/opencc'), patch.object(
                m.subprocess, 'run', side_effect=AssertionError('CLI must not run')):
            output = self.root / 'empty'
            m.render(fixture([]), {'duration': 1}, output)
            previous = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaisesRegex(m.Invalid, 'already exists'):
                m.render(fixture(['电脑']), {'duration': 1}, output)
            self.assertEqual(previous, {path.name: path.read_bytes() for path in output.iterdir()})

    @unittest.skipUnless(shutil.which('opencc'), 'real OpenCC CLI unavailable')
    def test_nul_corrupted_cli_framing_does_not_publish(self):
        # OpenCC's CLI truncates lines at NUL, including the adjacent framing LF.
        with self.assertRaisesRegex(m.Invalid, 'OpenCC failed'):
            m.render(fixture(['甲\x00乙']), {'duration': 1}, self.root / 'nul')
        self.assertFalse((self.root / 'nul').exists())

    @unittest.skipUnless(shutil.which('opencc'), 'real OpenCC CLI unavailable')
    def test_real_cli_matches_per_row_bytes(self):
        texts = ['电脑里的会议记录', '第一行\n第二行', '结尾\n', '', '\r\n',
                 '甲\r\n乙\r', '😀 café e\u0301，\t「计算机」！',
                 '__WORDPRINT_OPENCC_0__', '\n__WORDPRINT_OPENCC_0__\n',
                 '头\n\n', '发', '型', 'ＡＢＣ １２３', '\v\f\u2028\u2029电脑',
                 '\r', '\n\r\n', '__WORDPRINT_OPENCC_1__']
        binary = shutil.which('opencc')
        expected = [subprocess.run([binary, '-c', 's2twp.json'], input=text, text=True,
                    encoding='utf-8', capture_output=True, check=True).stdout for text in texts]
        for name, values, original in [('actual', texts, False), ('expected', expected, True)]:
            with patch.object(m, 'rows', return_value=reading_rows(values)):
                m.render(fixture(texts), {'duration': len(texts)}, self.root / name,
                         original_script=original, opencc=binary)
        for name in ('transcript.txt', 'transcript.md', 'transcript.html', 'transcript.srt',
                     'raw.txt', 'raw.md', 'run.json'):
            self.assertEqual((self.root / 'actual' / name).read_bytes(),
                             (self.root / 'expected' / name).read_bytes(), name)


if __name__ == '__main__':
    unittest.main()

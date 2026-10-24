"""The Colab notebook embeds scripts/torch_worker.py verbatim; `python3 tests/test_notebook.py --sync` rewrites that cell."""
import json
import os
import shlex
import tempfile
from unittest import mock
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
NOTEBOOK, WORKER = ROOT / 'colab' / 'wordprint.ipynb', ROOT / 'scripts' / 'torch_worker.py'
HEADER = '%%writefile torch_worker.py\n'
RUNTIME = ROOT / 'scripts' / 'worker_runtime.py'
RUNTIME_HEADER = '%%writefile worker_runtime.py\n'
TRANSCRIPT = ROOT / 'scripts' / 'transcript.py'
TRANSCRIPT_HEADER = '%%writefile transcript.py\n'


def worker_cell(notebook):
    return next(cell for cell in notebook['cells'] if ''.join(cell['source']).startswith(HEADER))


class NotebookTests(unittest.TestCase):
    def test_embedded_transcript_matches_script(self):
        notebook = json.loads(NOTEBOOK.read_text())
        cell = next(c for c in notebook['cells'] if ''.join(c['source']).startswith(TRANSCRIPT_HEADER))
        self.assertEqual(''.join(cell['source']), TRANSCRIPT_HEADER + TRANSCRIPT.read_text())

    def test_rerun_same_source_preserves_prior_exports_and_run_directories(self):
        code = ''.join(json.loads(NOTEBOOK.read_text())['cells'][-1]['source'])
        with tempfile.TemporaryDirectory() as temp:
            previous_cwd = Path.cwd()
            os.chdir(temp)
            try:
                source = Path('sample.wav')
                source.write_bytes(b'fake audio')
                legacy = Path('normalized-run-sample.json')
                legacy.write_bytes(b'previous export')
                legacy_run = legacy.with_suffix('.run')
                legacy_run.mkdir()
                (legacy_run / 'checkpoint.json').write_bytes(b'previous checkpoint')
                exports = []
                def execute(command):
                    argv = shlex.split(command)
                    out = Path(argv[argv.index('--out') + 1])
                    directory = out.parent if out.name == 'normalized-run.json' else out.with_suffix('.run')
                    if out.exists() or (directory.exists() and any(directory.iterdir())):
                        return 1
                    directory.mkdir(exist_ok=True)
                    (directory / 'checkpoint.json').write_text('new checkpoint')
                    out.write_text(f'export {len(exports)}')
                    exports.append(out)
                    return 0
                shell = mock.Mock()
                shell.system.side_effect = execute
                files = mock.Mock()
                context = dict(Path=Path, shlex=shlex, sys=sys, groups=[[str(source)]],
                               MODEL_SIZE='0.6B', MAX_NEW_TOKENS=2048, files=files,
                               get_ipython=lambda: shell)
                exec(code, context)
                first_snapshot = {p: p.read_bytes() for p in Path('.').rglob('*') if p.is_file()}
                exec(code, context)
                self.assertEqual(len(exports), 2)
                self.assertNotEqual(exports[0].parent, exports[1].parent)
                for path, content in first_snapshot.items():
                    self.assertEqual(path.read_bytes(), content)
                self.assertEqual(legacy.read_bytes(), b'previous export')
                self.assertEqual((legacy_run / 'checkpoint.json').read_bytes(), b'previous checkpoint')
                self.assertEqual(files.download.call_args_list,
                                 [mock.call(str(path)) for path in exports])
            finally:
                os.chdir(previous_cwd)

    def test_embedded_runtime_matches_script(self):
        notebook = json.loads(NOTEBOOK.read_text())
        cell = next(c for c in notebook['cells'] if ''.join(c['source']).startswith(RUNTIME_HEADER))
        self.assertEqual(''.join(cell['source']), RUNTIME_HEADER + RUNTIME.read_text())

    def test_embedded_worker_matches_script(self):
        cell = worker_cell(json.loads(NOTEBOOK.read_text()))
        self.assertEqual(''.join(cell['source']), HEADER + WORKER.read_text(),
                         'notebook drifted from torch_worker.py; run python3 tests/test_notebook.py --sync')


if __name__ == '__main__' and '--sync' in sys.argv:
    notebook = json.loads(NOTEBOOK.read_text())
    runtime_cell = next((c for c in notebook['cells'] if ''.join(c['source']).startswith(RUNTIME_HEADER)), None)
    if runtime_cell is None:
        runtime_cell = {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [], 'source': []}
        notebook['cells'].insert(notebook['cells'].index(worker_cell(notebook)), runtime_cell)
    transcript_cell = next((c for c in notebook['cells'] if ''.join(c['source']).startswith(TRANSCRIPT_HEADER)), None)
    if transcript_cell is None:
        transcript_cell = {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [], 'source': []}
        notebook['cells'].insert(notebook['cells'].index(worker_cell(notebook)), transcript_cell)
    transcript_cell['source'] = (TRANSCRIPT_HEADER + TRANSCRIPT.read_text()).splitlines(keepends=True)
    runtime_cell['source'] = (RUNTIME_HEADER + RUNTIME.read_text()).splitlines(keepends=True)
    worker_cell(notebook)['source'] = (HEADER + WORKER.read_text()).splitlines(keepends=True)
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n')
elif __name__ == '__main__':
    unittest.main()

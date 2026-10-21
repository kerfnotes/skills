"""The Colab notebook embeds scripts/torch_worker.py verbatim; `python3 tests/test_notebook.py --sync` rewrites that cell."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
NOTEBOOK, WORKER = ROOT / 'colab' / 'wordprint.ipynb', ROOT / 'scripts' / 'torch_worker.py'
HEADER = '%%writefile torch_worker.py\n'


def worker_cell(notebook):
    return next(cell for cell in notebook['cells'] if ''.join(cell['source']).startswith(HEADER))


class NotebookTests(unittest.TestCase):
    def test_embedded_worker_matches_script(self):
        cell = worker_cell(json.loads(NOTEBOOK.read_text()))
        self.assertEqual(''.join(cell['source']), HEADER + WORKER.read_text(),
                         'notebook drifted from torch_worker.py; run python3 tests/test_notebook.py --sync')


if __name__ == '__main__' and '--sync' in sys.argv:
    notebook = json.loads(NOTEBOOK.read_text())
    worker_cell(notebook)['source'] = (HEADER + WORKER.read_text()).splitlines(keepends=True)
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n')
elif __name__ == '__main__':
    unittest.main()

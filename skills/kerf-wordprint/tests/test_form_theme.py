"""Cross-surface design contract; the form remains usable without Node/Clayprint."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
CLAYPRINT = ROOT.parent / 'kerf-clayprint'
spec = importlib.util.spec_from_file_location('theme_form', ROOT / 'scripts/form.py')
form = importlib.util.module_from_spec(spec)
spec.loader.exec_module(form)


def variables(css):
    return dict(re.findall(r'--cp-([a-z-]+):\s*([^;]+);', css))


class ThemeTests(unittest.TestCase):
    def test_form_and_report_share_active_design_layer(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node needed only to compare the report generator')
        for name, mode in [('tokens.json', 'present'), ('tokens.blue.json', 'present'),
                           ('tokens.json', 'read')]:
            with self.subTest(name=name, mode=mode), patch.dict(os.environ, {
                    'CLAYPRINT_TOKENS': str(CLAYPRINT / 'design' / name),
                    'CLAYPRINT_MODE': mode}):
                report = subprocess.run([node, str(CLAYPRINT / 'scripts/theme-css.js')],
                                        capture_output=True, text=True, check=True)
                expected = variables(report.stdout)
                actual = variables(form.theme_css())
                self.assertTrue(actual)
                for key, value in actual.items():
                    self.assertEqual(value, expected[key], key)

    def test_isolated_form_needs_no_clayprint_or_node(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'skills/wordprint/scripts'
            root.mkdir(parents=True)
            for name in ('form.py', 'form.css', 'form.html', 'form.js', 'input_files.py'):
                shutil.copyfile(ROOT / 'scripts' / name, root / name)
            script = ('import importlib.util; '
                      f's=importlib.util.spec_from_file_location("f", {str(root / "form.py")!r}); '
                      'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                      'print(m.page([], None))')
            import sys
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script], cwd=folder,
                                    env={'PATH': '', 'PYTHONDONTWRITEBYTECODE': '1'},
                                    capture_output=True, text=True, check=True)
            self.assertIn('color-scheme: light', result.stdout)
            self.assertIn('#FAF9F5', result.stdout)
            self.assertIn('value="qwen-0.6b" checked', result.stdout)
            self.assertIn('id="source-list"', result.stdout)

            # Explicit design files also work in a standalone, no-Node install.
            design = Path(folder) / 'custom-design'
            design.mkdir()
            for name in ('tokens.json', 'read.json'):
                shutil.copyfile(CLAYPRINT / 'design' / name, design / name)
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script], cwd=folder,
                                    env={'PATH': '', 'CLAYPRINT_TOKENS': str(design / 'tokens.json'),
                                         'CLAYPRINT_MODE': 'read'},
                                    capture_output=True, text=True, check=True)
            self.assertEqual(variables(result.stdout)['body'], '11px')
            self.assertIn('value="qwen-0.6b" checked', result.stdout)

    def test_invalid_explicit_design_does_not_silently_switch_theme(self):
        with patch.dict(os.environ, {'CLAYPRINT_TOKENS': '/no-such-wordprint-design.json'}):
            with self.assertRaisesRegex(ValueError, 'Clayprint'):
                form.theme_css()

    def test_local_font_configuration_cannot_close_style_element(self):
        tokens = json.loads((CLAYPRINT / 'design/tokens.json').read_text())
        tokens['font']['latin'] = ['</style><script>bad()</script>']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tokens.json'
            path.write_text(json.dumps(tokens))
            with patch.dict(os.environ, {'CLAYPRINT_TOKENS': str(path), 'CLAYPRINT_MODE': 'present'}):
                page = form.page([], None)
                self.assertNotIn('</style><script>bad()', page)
                self.assertEqual(page.count('</style>'), 1)

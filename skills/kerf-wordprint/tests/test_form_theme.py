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
    # The generated screen :root precedes media overrides, including print.
    root = re.search(r':root\s*\{([^{}]*)\}', css.split('@media', 1)[0])
    return dict(re.findall(r'--cp-([a-z-]+):\s*([^;]+);', root[1])) if root else {}


class ThemeTests(unittest.TestCase):
    def test_variables_keep_screen_root_separate_from_print(self):
        screen = ':root { --cp-body: 16px; --cp-small: 12px; }'
        printed = '@media print { :root { --cp-body: 11pt; --cp-small: 9pt; } }'
        self.assertEqual(variables(screen + printed), {'body': '16px', 'small': '12px'})
        self.assertEqual(variables(printed), {})

    def test_screen_type_overrides_slide_sizes_in_both_modes(self):
        tokens = json.loads((CLAYPRINT / 'design/tokens.json').read_text())
        # Zero is an explicit override, just as with the canonical JS ?? operator.
        tokens['screen'] = {'type': {'body': 0, 'small': 13.5, 'sub': 21,
                                     'title': 31, 'display': 55}}
        expected = {'body': '0px', 'small': '13.5px', 'sub': '21px',
                    'title-size': '31px', 'display': '55px'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tokens.json'
            path.write_text(json.dumps(tokens))
            for mode in ('present', 'read'):
                with self.subTest(mode=mode), patch.dict(os.environ, {
                        'CLAYPRINT_TOKENS': str(path), 'CLAYPRINT_MODE': mode}):
                    actual = variables(form.theme_css())
                    self.assertEqual({key: actual[key] for key in expected}, expected)

    def test_legacy_layers_fall_back_for_missing_or_null_screen_sizes(self):
        expected = {
            'present': {'body': '20px', 'small': '12px', 'sub': '18px',
                        'title-size': '28px', 'display': '52px'},
            'read': {'body': '12px', 'small': '10px', 'sub': '14px',
                     'title-size': '22px', 'display': '36px'},
        }
        cases = [('missing', None), ('null', None), ('empty', {}),
                 ('null_type', {'type': None}), ('empty_type', {'type': {}}),
                 ('null_sizes', {'type': dict.fromkeys(('body', 'small', 'sub', 'title', 'display'))})]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tokens.json'
            for name, screen in cases:
                tokens = json.loads((CLAYPRINT / 'design/tokens.json').read_text())
                tokens.pop('screen')
                if name != 'missing':
                    tokens['screen'] = screen
                path.write_text(json.dumps(tokens))
                for mode in ('present', 'read'):
                    with self.subTest(screen=name, mode=mode), patch.dict(os.environ, {
                            'CLAYPRINT_TOKENS': str(path), 'CLAYPRINT_MODE': mode}):
                        actual = variables(form.theme_css())
                        self.assertEqual({key: actual[key] for key in expected[mode]}, expected[mode])

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
            self.assertEqual(variables(result.stdout)['body'], '16px')
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

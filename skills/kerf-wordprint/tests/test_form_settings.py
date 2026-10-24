"""Settings acceptance through the real localhost form, Chrome DOM, and saved answers.

Only generated audio is used. No model, remote engine, native picker, or Mail runs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

SCRIPT = Path(__file__).parents[1] / 'scripts/form.py'
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


@unittest.skipUnless(sync_playwright and CHROME.is_file(), 'Installed Playwright and Chrome required')
class FormSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(CHROME), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='wordprint-settings-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.audio = self.root / 'synthetic.wav'
        with wave.open(str(self.audio), 'wb') as audio:
            audio.setparams((1, 2, 16000, 160, 'NONE', 'not compressed'))
            audio.writeframes(b'\0\0' * 160)

    def open_form(self, settings=None, mode='collect', width=390):
        prefill = self.root / 'request.json'
        prefill.write_text(json.dumps({'sources': [{'kind': 'path', 'path': str(self.audio),
                                                  'title': '合成錄音'}], **(settings or {})}))
        self.out = self.root / 'answers.json'
        self.process = subprocess.Popen(
            [sys.executable, str(SCRIPT), '--prefill', str(prefill), '--out', str(self.out),
             '--mode', mode, '--no-open', '--timeout', '60'],
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process = self.process

        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)

        self.addCleanup(cleanup)
        url = process.stderr.readline().strip().removeprefix('form: ')
        self.assertTrue(url.startswith('http://127.0.0.1:'))
        page = self.browser.new_page(viewport={'width': width, 'height': 844})
        page.set_default_timeout(5000)
        self.addCleanup(page.close)
        page.goto(url)
        self.assertEqual(page.evaluate('innerWidth'), width)
        return page

    def submit(self, page):
        page.locator('#submit').focus()
        page.keyboard.press('Enter')
        page.locator('#success').wait_for(state='visible')
        stdout, stderr = self.process.communicate(timeout=10)
        self.assertEqual(self.process.returncode, 0, stderr)
        saved = json.loads(self.out.read_text())
        self.assertEqual(json.loads(stdout), saved)
        return saved

    def test_prefilled_explicit_choices_are_identifiable_while_settings_stay_collapsed(self):
        page = self.open_form({'engine': 'qwen-1.7b', 'summary': 'none', 'merge': False, 'mail': False})
        self.assertTrue(page.locator('#output-settings').is_visible())
        self.assertEqual(page.locator('#current-output').inner_text(), '逐字稿')
        self.assertIn('1.7B', page.locator('#processing-settings > summary').inner_text())
        self.assertFalse(page.locator('input[name=engine]:checked').is_visible())
        self.assertFalse(page.locator('input[name=summary]:checked').is_visible())
        self.assertFalse(page.locator('#roster').is_visible())
        page.locator('#change-summary').focus()
        reached = []
        for _ in range(4):
            page.keyboard.press('Tab')
            reached.append(page.evaluate('document.activeElement.id || document.activeElement.tagName'))
        self.assertEqual(reached[:3], ['SUMMARY', 'SUMMARY', 'submit'])
        saved = self.submit(page)
        self.assertEqual((saved['engine'], saved['summary'], saved['merge'], saved['mail']),
                         ('qwen-1.7b', 'none', False, False))
        self.assertNotIn('mode', saved)
        self.assertEqual(saved['sources'][0]['path'], str(self.audio))

    def test_custom_summary_changes_keep_text_and_reveal_the_first_error(self):
        page = self.open_form({'engine': 'qwen-1.7b', 'summary': 'custom'})
        self.assertTrue(page.locator('#summary_custom').is_visible())
        page.locator('#change-summary').click()
        self.assertFalse(page.locator('#summary_custom').is_visible())
        page.locator('#submit').click()
        self.assertTrue(page.locator('#summary_custom').is_visible())
        self.assertEqual(page.locator('#summary_custom').get_attribute('aria-invalid'), 'true')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'summary_custom')
        page.locator('#summary_custom').fill('保留決議與待辦')
        page.locator('input[name=summary][value=none]').check()
        self.assertFalse(page.locator('#summary_custom').is_visible())
        page.locator('input[name=summary][value=custom]').check()
        self.assertEqual(page.locator('#summary_custom').input_value(), '保留決議與待辦')
        page.locator('input[name=summary][value=interview]').check()
        self.assertEqual(page.locator('#current-output').inner_text(), '逐字稿＋訪談摘要')
        page.locator('input[name=summary][value=lecture]').check()
        self.assertEqual(page.locator('#current-output').inner_text(), '逐字稿＋演講／課程摘要')
        page.locator('input[name=summary][value=custom]').check()
        page.locator('#change-summary').click()
        self.assertEqual(page.locator('#change-summary').get_attribute('aria-expanded'), 'false')
        saved = self.submit(page)
        self.assertEqual((saved['engine'], saved['summary'], saved['summary_custom']),
                         ('qwen-1.7b', 'custom', '保留決議與待辦'))

    def test_mail_fields_only_validate_when_enabled_and_keep_unsent_recipients(self):
        page = self.open_form({'recipients': ['person@example.com'], 'mail': False})
        page.locator('#optional-settings > summary').click()
        self.assertFalse(page.locator('#recipients').is_visible())
        page.locator('#mail').check()
        self.assertTrue(page.locator('#recipients').is_visible())
        self.assertIn('只建立草稿', page.locator('#recipient-fields').inner_text())
        page.locator('#recipients').fill('bad-address')
        page.locator('#optional-settings > summary').click()
        page.locator('#submit').click()
        self.assertTrue(page.locator('#recipients').is_visible())
        self.assertEqual(page.evaluate('document.activeElement.id'), 'recipients')
        page.locator('#mail').uncheck()
        self.assertFalse(page.locator('#recipients').is_visible())
        page.locator('#mail').check()
        self.assertEqual(page.locator('#recipients').input_value(), 'bad-address')
        page.locator('#mail').uncheck()
        saved = self.submit(page)
        self.assertFalse(saved['mail'])
        self.assertEqual(saved['recipients'], ['bad-address'])

    def test_mail_can_be_requested_with_blank_recipients(self):
        page = self.open_form({'mail': True, 'recipients': []})
        self.assertIn('Mail 草稿', page.locator('#optional-settings > summary').inner_text())
        page.locator('#optional-settings > summary').click()
        self.assertTrue(page.locator('#recipients').is_visible())
        self.assertFalse(page.locator('#recipients').get_attribute('required'))
        saved = self.submit(page)
        self.assertTrue(saved['mail'])
        self.assertEqual(saved['recipients'], [])

    def test_remote_route_disclosure_remains_visible_after_collapsing_processing(self):
        page = self.open_form(mode='run')
        self.assertFalse(page.locator('#remote-notice').is_visible())
        for engine, label, disclosure, action in [
            ('gemini-3.5-transcribe', 'Gemini 3.5 Transcribe', 'API', '開始整理'),
            ('colab', 'Google Colab', '筆記本', '準備 Colab'),
        ]:
            page.locator('#processing-settings > summary').click()
            page.locator(f'input[name=engine][value="{engine}"]').check()
            page.locator('#processing-settings > summary').click()
            self.assertIn(label, page.locator('#processing-settings > summary').inner_text())
            self.assertTrue(page.locator('#remote-notice').is_visible())
            self.assertIn('上傳', page.locator('#remote-notice').inner_text())
            self.assertIn(disclosure, page.locator('#remote-notice').inner_text())
            self.assertEqual(page.locator('#submit').inner_text(), action)
        saved = self.submit(page)
        self.assertEqual(saved['engine'], 'colab')
        self.assertFalse((self.root / 'delivery.json').exists())

    def test_last_source_removal_and_reload_preserve_explicit_settings_and_draft_v1(self):
        page = self.open_form({'engine': 'qwen-1.7b', 'summary': 'custom', 'summary_custom': '保留原句',
                               'merge': True, 'mail': True, 'recipients': ['person@example.com'],
                               'roster': ['候選甲', '候選乙']})
        page.locator('#change-summary').click()
        page.locator('input[name=summary][value=none]').check()
        page.get_by_role('button', name='移除：合成錄音', exact=True).click()
        self.assertFalse(page.locator('#output-settings').is_visible())
        self.assertEqual(page.evaluate('document.activeElement.id'), 'choose-files')
        draft = page.evaluate('JSON.parse(sessionStorage.getItem(sessionStorage.key(0)))')
        self.assertEqual(draft['version'], 1)
        self.assertEqual(draft['settings']['summary_custom'], '保留原句')
        page.reload()
        self.assertFalse(page.locator('#output-settings').is_visible())
        page.locator('#more-sources > summary').click()
        page.locator('#paths').fill(str(self.audio))
        page.locator('#add-paths').click()
        self.assertIn('1.7B', page.locator('#processing-settings > summary').inner_text())
        self.assertIn('Mail 草稿', page.locator('#optional-settings > summary').inner_text())
        self.assertEqual(page.locator('#current-output').inner_text(), '逐字稿')
        self.assertTrue(page.locator('#merge').is_checked())
        page.locator('#change-summary').click()
        page.locator('input[name=summary][value=custom]').check()
        self.assertEqual(page.locator('#summary_custom').input_value(), '保留原句')
        saved = self.submit(page)
        self.assertEqual((saved['engine'], saved['merge'], saved['summary'], saved['mail']),
                         ('qwen-1.7b', True, 'custom', True))
        self.assertEqual(saved['recipients'], ['person@example.com'])
        self.assertEqual(saved['roster'], ['候選甲', '候選乙'])


if __name__ == '__main__':
    unittest.main()

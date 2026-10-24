"""Public CLI + real localhost/Chrome + fixed agent handoff. Synthetic data only.

Set WORDPRINT_FLOW_ARTIFACTS to a fresh outside-repo directory to retain evidence.
Only the external model process is substituted; collection, validation, rendering,
summary adapter, Clayprint checker and formal PDF commands run unchanged.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
CP = ROOT.parent / 'kerf-clayprint'
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
WIDTHS = (320, 375, 390, 728, 1280)


@unittest.skipUnless(importlib.util.find_spec('playwright') and CHROME.is_file(), 'Installed Playwright and Chrome required')
class DeliveryFlowTests(unittest.TestCase):
    def setUp(self):
        if saved := os.environ.get('WORDPRINT_FLOW_ARTIFACTS'):
            self.out = Path(saved).resolve() / self._testMethodName
            self.out.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='wordprint-flow-')
            self.addCleanup(temporary.cleanup)
            self.out = Path(temporary.name)
        self.audio = self.out / '合成會議 synthetic.wav'
        with wave.open(str(self.audio), 'wb') as wav:
            wav.setparams((1, 2, 16000, 190 * 16000, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 190 * 16000)
        runtime = self.out / 'runtime/bin'
        runtime.mkdir(parents=True)
        wrapper = runtime / 'python'
        wrapper.write_text('#!' + sys.executable + '\n' +
                           (ROOT / 'tests/fixtures/synthetic_runtime.py').read_text())
        wrapper.chmod(0o755)
        (runtime / 'mlx-qwen3-asr').write_text('#!' + sys.executable + ' ' + str(wrapper) + '\n')
        (runtime / 'mlx-qwen3-asr').chmod(0o755)
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                    'WORDPRINT_TORCH_VENV': str(runtime.parent),
                    'PATH': str(runtime) + os.pathsep + os.environ.get('PATH', '')}

    def command(self, *args, name):
        result = subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=90)
        (self.out / (name + '.log')).write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def measure(self, page, label):
        rows = []
        for width in WIDTHS:
            page.set_viewport_size({'width': width, 'height': 844 if width < 1000 else 800})
            row = page.evaluate('''() => ({width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
                 bodySize: getComputedStyle(document.body).fontSize})''')
            self.assertEqual(row['width'], width)
            self.assertFalse(row['overflow'], (label, row))
            page.screenshot(path=str(self.out / f'{label}-{width}.png'), full_page=label != 'long-reader')
            rows.append(row)
        return rows

    def test_browser_to_reader_to_fixed_summary_and_formal_pdf(self):
        from playwright.sync_api import sync_playwright
        job = self.out / 'job'
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run.py'), '--task-directory', str(job),
            '--no-open', '--timeout', '90', '--title', '合成會議：保留否定、提議與待確認'],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            url = process.stderr.readline().strip().removeprefix('form: ')
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
                page = browser.new_page(viewport={'width': 390, 'height': 844}, accept_downloads=True)
                page.set_default_timeout(7000)
                errors, external = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def restrict(route):
                    if route.request.url.startswith(('http://127.0.0.1:', 'file:', 'blob:', 'data:')):
                        route.continue_()
                    else:
                        external.append(route.request.url)
                        route.abort()
                page.route('**/*', restrict)
                # External memo metadata boundary, never the real Voice Memos DB.
                page.route('**/memos', lambda route: route.fulfill(json={'memos': [], 'total': 0}))
                page.goto(url)
                self.assertFalse(page.locator('#submit').is_visible())
                measurements = {'empty': self.measure(page, 'empty')}
                page.locator('#files').set_input_files(self.audio)
                page.wait_for_function('document.querySelector("#source-list li")?.dataset.status === "done"')
                self.assertEqual(page.locator('#current-output').inner_text(), '逐字稿＋會議摘要')
                self.assertEqual(page.locator('#submit').inner_text(), '開始整理')
                measurements['added'] = self.measure(page, 'added')
                # Correct a bad path without re-uploading the already preserved file.
                page.locator('#more-sources > summary').focus()
                page.keyboard.press('Enter')
                page.locator('#paths').fill(str(self.out / 'absent.wav'))
                page.locator('#add-paths').click()
                page.locator('#submit').focus()
                page.keyboard.press('Enter')
                page.locator('#sources-error').filter(has_text='第 2 個來源').wait_for()
                page.screenshot(path=str(self.out / 'error-recovery.png'), full_page=True)
                remove = page.get_by_role('button', name='移除：absent.wav', exact=True)
                self.assertTrue(remove.evaluate('(el) => el === document.activeElement'))
                page.keyboard.press('Enter')
                page.locator('#submit').focus()
                page.keyboard.press('Enter')
                page.locator('#success').wait_for(state='visible')
                self.assertIn('回到對話', page.locator('#success').inner_text())
                page.screenshot(path=str(self.out / 'submitted.png'), full_page=True)
                stdout, stderr = process.communicate(timeout=40)
                (self.out / 'runner.log').write_text(stdout + stderr)
                self.assertEqual(process.returncode, 0, stderr)
                delivery = json.loads((job / 'delivery.json').read_text())
                self.assertEqual(delivery['status'], 'complete')
                self.assertEqual(delivery['pending_agent_steps'][0]['status'], 'pending')
                self.assertFalse((job / 'output-1/notes.md').exists())
                answers = json.loads((job / 'answers.json').read_text())
                self.assertEqual((answers['engine'], answers['summary'], answers['mail']), ('qwen-0.6b', 'meeting', False))
                self.assertEqual(Path(answers['sources'][0]['path']).read_bytes(), self.audio.read_bytes())
                output = job / 'output-1'
                page.goto((output / 'transcript.html').as_uri())
                page.wait_for_function('document.querySelector("audio").readyState >= 1')
                self.assertTrue(page.locator('audio').evaluate('(el) => el.paused'))
                measurements['reader'] = self.measure(page, 'reader')
                target = page.get_by_role('button', name='提議下週發布，未通過。')
                target.focus()
                page.keyboard.press('Enter')
                page.wait_for_function('Math.abs(document.querySelector("audio").currentTime - 62) < 2')
                page.locator('audio').evaluate('(el) => el.pause()')
                page.keyboard.press('Space')
                page.wait_for_function('Math.abs(document.querySelector("audio").currentTime - 62) < 2')
                page.locator('audio').evaluate('(el) => el.pause()')
                self.assertTrue(target.evaluate('(el) => el === document.activeElement'))
                # Fixed, independently reviewed notes enter at the existing agent handoff.
                notes = output / 'notes.md'
                shutil.copyfile(ROOT / 'tests/fixtures/summary/meeting.md', notes)
                self.command(sys.executable, str(ROOT / 'scripts/summary_report.py'), str(notes),
                             str(output / 'notes.html'), '--template', 'meeting', '--clayprint', str(CP), name='summary-cli')
                self.command('node', str(CP / 'evals/check-report.mjs'), str(output / 'notes.html'), str(notes), name='summary-checker')
                page.goto((output / 'notes.html').as_uri())
                measurements['summary'] = self.measure(page, 'summary')
                source = page.locator('.wp-source > summary').first
                source.focus()
                page.keyboard.press('Enter')
                self.assertTrue(source.evaluate('(el) => el.parentElement.open'))
                page.screenshot(path=str(self.out / 'summary-sources.png'), full_page=True)
                page.keyboard.press('Space')
                self.assertFalse(source.evaluate('(el) => el.parentElement.open'))
                self.command('node', str(CP / 'scripts/pdf.js'), str(output / 'notes.html'), str(output / 'print'), name='formal-pdf')
                pdftext = self.command('pdftotext', str(output / 'print/notes.pdf'), '-', name='pdf-text').stdout
                for claim in ('目前不發布新版本，先完成驗證。', '提議下週發布，未通過。', '待確認', '重疊發言，不歸屬任何一人。'):
                    self.assertIn(''.join(claim.split()), ''.join(pdftext.split()))
                for timestamp in ('00:00:05', '00:00:17', '00:00:25', '00:01:02', '00:02:03', '00:02:15', '00:03:01'):
                    self.assertIn('[' + timestamp + ']', pdftext)
                self.assertNotIn('系統列印', pdftext)
                # Only this HTML is copied: exports stay available without media/siblings.
                standalone = self.out / 'standalone'
                standalone.mkdir()
                shutil.copyfile(output / 'transcript.html', standalone / 'transcript.html')
                page.goto((standalone / 'transcript.html').as_uri())
                page.locator('#playback-error').wait_for(state='visible')
                page.get_by_text('匯出', exact=True).focus()
                page.keyboard.press('Enter')
                page.locator('[data-download="md"]').focus()
                with page.expect_download() as download:
                    page.keyboard.press('Enter')
                downloaded = self.out / 'standalone-export.md'
                download.value.save_as(downloaded)
                self.assertEqual(downloaded.read_bytes(), (output / 'transcript.md').read_bytes())
                page.screenshot(path=str(self.out / 'standalone-missing-media.png'), full_page=True)
                self.assertFalse(errors, errors)
                self.assertFalse(external, external)
                (self.out / 'browser-receipt.json').write_text(json.dumps({'measurements': measurements,
                    'page_errors': errors, 'external_requests': external, 'native_zoom': 'unverified',
                    'VoiceOver': 'unverified', 'summary_origin': 'fixed agent-handoff fixture; runner does not summarize'}, ensure_ascii=False, indent=2))
                # Delivery links are derived only from actual, now-existing artifacts.
                paths = [output / name for name in ('notes.html', 'transcript.html', 'print/notes.pdf', 'notes.md', 'transcript.txt', 'transcript.srt')]
                self.assertTrue(all(path.is_file() for path in paths))
                (self.out / 'delivery-links.json').write_text(json.dumps([{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths], indent=2))
                browser.close()
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)

    def test_public_runner_statuses_keep_actual_outputs_and_pending_handoffs(self):
        results = {}
        for mode, expected in [('complete', (0, 'complete')), ('partial', (1, 'partial')),
                               ('empty', (0, 'complete')), ('cancelled', (130, 'cancelled')), ('colab', (2, 'waiting'))]:
            request = self.out / (mode + '.json')
            request.write_text(json.dumps({'sources': [{'path': str(self.audio)}], 'summary': 'meeting',
                'engine': 'colab' if mode == 'colab' else 'qwen-0.6b', 'mail': True, 'recipients': []}))
            job = self.out / mode
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/run.py'), '--request', str(request),
                '--task-directory', str(job), '--no-open'], env={**self.env, 'WORDPRINT_SYNTHETIC_MODE': mode},
                capture_output=True, text=True, timeout=40)
            (self.out / (mode + '.log')).write_text(result.stdout + result.stderr)
            delivery = json.loads((job / 'delivery.json').read_text())
            self.assertEqual((result.returncode, delivery['status']), expected, result.stderr)
            self.assertTrue(all(Path(path).is_file() for item in delivery['runs'] for path in item['outputs']))
            self.assertFalse(list(job.rglob('notes.*')))
            if mode in ('complete', 'empty'):
                steps = delivery['pending_agent_steps']
                self.assertEqual(steps[0]['status'], 'unavailable' if mode == 'empty' else 'pending')
                self.assertEqual((steps[1]['stage'], steps[1]['status']), ('mail_draft', 'pending'))
            elif mode == 'colab':
                self.assertFalse(list(job.glob('run-*')))
            else:
                self.assertFalse((job / 'output-1/transcript.html').exists())
                self.assertTrue((job / 'run-1/raw-transcript.txt').is_file())
            results[mode] = {'code': result.returncode, 'delivery': delivery}
        (self.out / 'status-matrix.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))

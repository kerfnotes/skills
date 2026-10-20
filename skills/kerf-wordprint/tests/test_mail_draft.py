"""AppleScript text only; never talks to Mail."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('wordprint_mail', Path(__file__).parents[1] / 'scripts' / 'mail_draft.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MailDraftTests(unittest.TestCase):
    def test_quotes_and_never_sends(self):
        text = m.script(['a@example.com'], '週會 "A" \\ B', '結論\n第二行', [Path('/tmp/逐字 稿.html')])
        self.assertIn('subject:"逐字稿：週會 \\"A\\" \\\\ B"', text)
        self.assertIn('content:"結論\\n第二行\\n\\n附件：\\n- 逐字 稿.html\\n"', text)
        self.assertIn('address:"a@example.com"', text)
        self.assertIn('POSIX file "/tmp/逐字 稿.html"', text)
        self.assertNotIn('send', text)
        self.assertNotIn('to recipient', m.script([], 'x', '', []))


if __name__ == '__main__':
    unittest.main()

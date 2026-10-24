"""Fixed notes -> public summary adapter, without models or mocked DOM."""
import base64
import importlib.util
from pathlib import Path
import re
from html.parser import HTMLParser
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'summary'
spec = importlib.util.spec_from_file_location('summary_report', ROOT / 'scripts' / 'summary_report.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class Document(HTMLParser):
    """Read generated markup, without simulating layout or browser behavior."""
    def __init__(self, html):
        super().__init__()
        self.root = {'tag': 'root', 'children': []}
        self.stack = [self.root]
        self.sources = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'children': [], 'parent': self.stack[-1], 'attrs': dict(attrs)}
        self.stack[-1]['children'].append(node)
        if tag == 'details' and dict(attrs).get('class') == 'wp-source':
            self.sources.append(node)
        if tag not in ('meta', 'br', 'hr', 'img', 'input', 'link'):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1]['children'].append(data)

    @staticmethod
    def text(node, excluded=()):
        if isinstance(node, str):
            return node
        if node['tag'] in excluded:
            return ''
        separator = ' | ' if node['tag'] == 'tr' else ''
        return separator.join(Document.text(c, excluded) for c in node['children'])

    def claim_sources(self):
        pairs = []
        for source in self.sources:
            owner = source['parent']
            if owner['tag'] == 'td':
                owner = owner['parent']
            claim = self.text(owner, ('details', 'sup', 'ul', 'ol')).strip()
            citations = re.findall(r'\[([0-9:]+)\]', self.text(source))
            pairs.append((claim, citations))
        return pairs


class SummaryReportTests(unittest.TestCase):
    def test_meeting_reads_decisions_and_actions_before_background(self):
        markdown = (FIXTURES / 'meeting.md').read_text()
        result = summary.build_summary(markdown, template='meeting')
        headings = re.findall(r'<h2[^>]*>(.*?)</h2>', result['html'])
        self.assertEqual(headings, ['一句話結論', '決議', '行動項目', '摘要', '討論要點', '風險與未決', '下次會議'])
        self.assertEqual((FIXTURES / 'meeting.md').read_text(), markdown)
        self.assertIn('逐字稿未提及', result['html'])

    def test_each_claim_keeps_rich_text_and_all_of_its_own_sources(self):
        result = summary.build_summary((FIXTURES / 'meeting.md').read_text(), template='meeting')
        self.assertIn('<strong>不發布</strong>', result['html'])
        self.assertIn('<blockquote>', result['html'])
        self.assertIn('<table>', result['html'])
        self.assertEqual([(c['text'], c['citations']) for c in result['claims'] if c['citations']], [
            ('目前**不發布**新版本，先完成驗證。', ['00:00:05', '00:00:17']),
            ('核對失敗案例 | 待確認 | 待確認 |', ['00:02:03', '00:02:15']),
            ('團隊檢視了測試結果，尚未確認正式日期。', ['00:00:25']),
            ('S1｜可能是 林先生：提議下週發布，**未通過**。', ['00:01:02']),
            ('「不確定是否完成；重疊發言，不歸屬任何一人。」', ['00:03:01']),
        ])
        self.assertNotRegex(result['html'], r'href="[^"#]*#t=')

    def test_other_templates_keep_order_and_download_exact_markdown(self):
        expected = {
            'interview': ['受訪者核心觀點', '主題分群', '關鍵引述', '矛盾或保留處', '追問清單'],
            'lecture': ['核心主張', '論證結構', '名詞解釋', '可引用句', '延伸問題'],
            'custom': ['尚待核對', '原話與連結', '逐字稿未提及'],
        }
        for template, headings in expected.items():
            with self.subTest(template=template):
                original = (FIXTURES / (template + '.md')).read_bytes()
                result = summary.build_summary(original.decode(), template=template)
                self.assertEqual(re.findall(r'<h2[^>]*>(.*?)</h2>', result['html']), headings)
                payload = re.search(r'href="data:text/markdown;charset=utf-8;base64,([^"]+)"', result['html'])
                self.assertIsNotNone(payload)
                self.assertEqual(base64.b64decode(payload[1]), original)
                toc = result['html'].index('aria-label="目錄"')
                self.assertLess(result['html'].index('wp-section-0'), toc)
                self.assertLess(toc, result['html'].index('<section aria-labelledby="wp-section-1"'))
                self.assertNotIn('<details class="wp-toc" open', result['html'])
                self.assertIn('window.print()', result['html'])
                self.assertNotIn('<script>alert', result['html'])

    def test_custom_repeated_headings_keep_sources_in_their_own_section(self):
        result = summary.build_summary('# 自訂摘要\n\n## 原話\n\n沒有核准。[00:01:00]\n\n## 原話\n\n提議未通過。[00:02:00]\n', template='custom')
        sections = re.findall(r'<section[^>]*>([\s\S]*?)</section>', result['html'])
        self.assertNotIn('[00:02:00]', sections[0])
        self.assertNotIn('[00:01:00]', sections[1])

    def test_fixed_claim_citation_oracle_rejects_semantic_and_source_mutations(self):
        html = summary.build_summary((FIXTURES / 'meeting.md').read_text(), template='meeting')['html']
        expected = [
            ('目前不發布新版本，先完成驗證。', ['00:00:05', '00:00:17']),
            ('核對失敗案例 | 待確認 | 待確認 |', ['00:02:03', '00:02:15']),
            ('團隊檢視了測試結果，尚未確認正式日期。', ['00:00:25']),
            ('S1｜可能是 林先生：提議下週發布，未通過。', ['00:01:02']),
            ('「不確定是否完成；重疊發言，不歸屬任何一人。」', ['00:03:01']),
        ]
        self.assertEqual(Document(html).claim_sources(), expected)
        # These fixtures are a literal oracle, not a general semantic AI checker.
        for before, after in [('不發布', '發布'), ('未通過', '已通過'), ('待確認', '林先生'), ('待確認', '明天'), ('可能是', '確定是'), ('[00:02:15]', '[00:01:02]')]:
            with self.subTest(mutation=(before, after)):
                self.assertNotEqual(Document(html.replace(before, after)).claim_sources(), expected)

    def test_print_note_is_at_paragraph_end_and_not_on_an_empty_line(self):
        html = summary.build_summary('# 自訂摘要\n\n## 結論\n\n尚未核准。[00:01:00]\n', template='custom')['html']
        self.assertRegex(html, r'<p>尚未核准。<sup[^>]+>a</sup></p>')

    def test_literal_marker_text_is_not_replaced_by_another_section(self):
        result = summary.build_summary('# 自訂摘要\n\n## 前段\n\nWORDPRINT_BODY_1\n\n## 後段\n\n保留這句。\n', template='custom')
        self.assertIn('<p>WORDPRINT_BODY_1</p>', result['html'])
        self.assertEqual(result['html'].count('<p>保留這句。</p>'), 1)

    def test_custom_code_quote_does_not_create_a_new_summary_section(self):
        result = summary.build_summary('# 自訂摘要\n\n## 原話\n\n```text\n## 不是新段落\n保留原話\n```\n', template='custom')
        self.assertEqual(result['section_order'], ['原話'])
        self.assertIn('<pre><code>## 不是新段落\n保留原話</code></pre>', result['html'])


if __name__ == '__main__':
    unittest.main()

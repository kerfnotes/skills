#!/usr/bin/env python3
"""Present verified notes.md through Clayprint's public report API.

build_summary(markdown, *, template, clayprint=None) returns html and section_order.
CLI: summary_report.py notes.md notes.html --template meeting [--clayprint DIR]
No inference, transcript mutation, or PDF application is embedded in the HTML.
"""
import argparse
import base64
from html import escape
import json
from pathlib import Path
import re
import subprocess

MEETING = ('一句話結論', '決議', '行動項目', '摘要', '討論要點', '風險與未決', '下次會議')


def find_clayprint(explicit=None):
    candidates = [Path(explicit)] if explicit else [
        Path(__file__).resolve().parents[2] / 'kerf-clayprint',
        Path.cwd() / '.claude/skills/kerf-clayprint',
        Path.cwd() / '.agents/skills/kerf-clayprint',
    ]
    for path in candidates:
        if (path / 'scripts/report.js').is_file():
            return path.resolve()
    raise ValueError('找不到 Clayprint；請提供 --clayprint，或只交付 notes.md。')


def _sections(markdown, template):
    if template not in ('meeting', 'interview', 'lecture', 'custom'):
        raise ValueError('摘要種類必須是 meeting、interview、lecture 或 custom。')
    lines = markdown.splitlines()
    if not lines or not lines[0].startswith('# '):
        raise ValueError('notes.md 第一行必須是 # 標題。')
    title, sections, current = lines[0][2:], [], None
    fence = None
    for line in lines[1:]:
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        in_code = fence is not None
        if marker:
            if fence is None:
                fence = marker[1]
            elif re.fullmatch(r'\s*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*', line):
                fence = None
        heading = None if in_code or marker else re.fullmatch(r'##\s+(.+?)\s*', line)
        if heading:
            current = {'title': heading[1], 'lines': []}
            sections.append(current)
        elif current is not None:
            current['lines'].append(line)
        elif line.strip():
            current = {'title': None, 'lines': [line]}
            sections.append(current)
    if not sections:
        raise ValueError('notes.md 沒有摘要內容。')
    if template == 'meeting':
        if sections[0]['title'] is None:
            sections[0]['title'] = '一句話結論'
        def key(s):
            name = s['title'] or ''
            return next((k for k in MEETING if re.fullmatch(re.escape(k) + r'(?:[（(].*?[）)])?', name)), name)
        names = [key(s) for s in sections]
        if any(names.count(k) != 1 for k in MEETING):
            raise ValueError('會議摘要須保留七節各一次；請核對原模板，勿自動補寫內容。')
        sections = sorted(sections, key=lambda s: MEETING.index(key(s)) if key(s) in MEETING else len(MEETING))
    return title, sections


CITATION = re.compile(r'\[(\d{2,}:\d{2}:\d{2})\]')
# Exact backtick runs delimit code; escaped punctuation is literal Markdown too.
LITERAL = re.compile(r'(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)|\\([\\`*{}\[\]()#+.!_>|-])')


def _extract_citations(text):
    """Remove source times only outside the literals supported by _inline."""
    citations, parts, end = [], [], 0
    def remove(match):
        citations.append(match[1])
        return ''
    for match in LITERAL.finditer(text):
        parts.append(CITATION.sub(remove, text[end:match.start()]))
        parts.append(match[0])
        end = match.end()
    parts.append(CITATION.sub(remove, text[end:]))
    return ''.join(parts).strip(), citations


def _inline(text):
    """Small, escaped Markdown subset; unsupported syntax stays visible as text."""
    pattern = re.compile(LITERAL.pattern + r'|\*\*(.+?)\*\*|__(.+?)__|\*([^*]+)\*|\[([^\]]+)\]\(([^\s)]+)\)')
    out, end = [], 0
    for m in pattern.finditer(text):
        out.append(escape(text[end:m.start()]))
        if m[1]:
            out.append('<code>' + escape(m[2]) + '</code>')
        elif m[3] is not None:
            out.append(escape(m[3]))
        elif m[4] is not None or m[5] is not None:
            out.append('<strong>' + _inline(m[4] if m[4] is not None else m[5]) + '</strong>')
        elif m[6] is not None:
            out.append('<em>' + _inline(m[6]) + '</em>')
        elif m[7] is not None:
            url = m[8]
            if re.match(r'^(?:https?://|mailto:|#|\.?\.?/)', url, re.I) or not re.match(r'^[\w+.-]+:', url):
                out.append('<a href="' + escape(url, quote=True) + '">' + _inline(m[7]) + '</a>')
            else:
                out.append(escape(m[0]))
        end = m.end()
    return ''.join(out) + escape(text[end:])


def _letter(index):
    text = ''
    while index:
        index, digit = divmod(index - 1, 26)
        text = chr(97 + digit) + text
    return text


def _cells(line):
    # A pipe escaped in text or inside a code span is content, not a cell boundary.
    parts, cell, code, i = [], '', 0, 0
    line = line.strip()
    if line.startswith('|'):
        line = line[1:]
    if line.endswith('|') and not line.endswith('\\|'):
        line = line[:-1]
    while i < len(line):
        char = line[i]
        if char == '\\' and i + 1 < len(line):
            cell += line[i:i + 2]
            i += 2
            continue
        if char == '`':
            ticks = len(line[i:]) - len(line[i:].lstrip('`'))
            code = 0 if code == ticks else ticks if not code else code
            cell += '`' * ticks
            i += ticks
            continue
        if char == '|' and not code:
            parts.append(cell.strip())
            cell = ''
        else:
            cell += char
        i += 1
    return parts + [cell.strip()]


class _Markdown:
    def __init__(self):
        self.claims = []

    def unit(self, text, section, render=None):
        clean, citations = _extract_citations(text)
        note = _letter(1 + sum(bool(c['citations']) for c in self.claims)) if citations else None
        self.claims.append({'text': clean, 'citations': citations, 'note': note, 'section': section})
        body = render(clean) if render else _inline(clean)
        if not citations:
            return body
        times = ' '.join('[' + t + ']' for t in citations)
        note_html = f'<sup class="wp-note" aria-label="附註 {note}">{note}</sup>'
        closing = re.search(r'</(?:p|h[3-6])>$', body)
        body = body[:closing.start()] + note_html + closing[0] if closing else body + note_html
        return (body
                + f'<details class="wp-source"><summary>來源 <span>{note}</span></summary><p>{escape(times)}</p></details>')

    def blocks(self, lines, section):
        out, i = [], 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            fence = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
            if fence:
                end = i + 1
                while end < len(lines) and not re.fullmatch(r'\s*' + re.escape(fence[1][0]) + '{' + str(len(fence[1])) + r',}\s*', lines[end]):
                    end += 1
                out.append('<pre><code>' + escape('\n'.join(lines[i + 1:end])) + '</code></pre>')
                i = min(end + 1, len(lines))
                continue
            if i + 1 < len(lines) and '|' in line and all(re.fullmatch(r':?-{3,}:?', c) for c in _cells(lines[i + 1])):
                headers = _cells(line)
                rows = []
                i += 2
                while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                    cells = _cells(lines[i])
                    if len(cells) != len(headers):
                        raise ValueError('Markdown 表格欄數不一致；請核對原稿，未產生不完整表格。')
                    # One table row is one claim. Render all cells, then attach its sources in its last cell.
                    def row(clean):
                        values = _cells(lines[i])
                        return ''.join('<td>' + _inline(_extract_citations(c)[0]) + '</td>' for c in values)
                    rendered = self.unit(' | '.join(cells), section, row)
                    if '</td><sup' in rendered:
                        rendered = rendered.replace('</td><sup', '<sup', 1) + '</td>'
                    rows.append('<tr>' + rendered + '</tr>')
                    i += 1
                out.append('<div class="table-scroll" role="region" tabindex="0" aria-label="' + escape(section or '摘要', quote=True) + '表格，可橫向捲動"><table><thead><tr>' + ''.join('<th scope="col">' + _inline(h) + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
                continue
            heading = re.match(r'^(#{3,6})\s+(.+)$', line)
            if heading:
                level = len(heading[1])
                out.append('<div>' + self.unit(heading[2], section, lambda t: f'<h{level}>' + _inline(t) + f'</h{level}>') + '</div>')
                i += 1
                continue
            if re.fullmatch(r'\s*(?:---+|\*\*\*+)\s*', line):
                out.append('<hr>')
                i += 1
                continue
            if re.match(r'^\s*>', line):
                quote = []
                while i < len(lines) and re.match(r'^\s*>', lines[i]):
                    quote.append(re.sub(r'^\s*> ?', '', lines[i]))
                    i += 1
                out.append('<blockquote>' + self.blocks(quote, section) + '</blockquote>')
                continue
            item = re.match(r'^(\s*)([-+*]|\d+[.)])\s+(.+)$', line)
            if item:
                indent, ordered = len(item[1]), item[2][0].isdigit()
                tag = 'ol' if ordered else 'ul'
                start = ' start="' + re.match(r'\d+', item[2])[0] + '"' if ordered else ''
                items = []
                while i < len(lines):
                    match = re.match(r'^(\s*)([-+*]|\d+[.)])\s+(.+)$', lines[i])
                    if not match or len(match[1]) != indent or match[2][0].isdigit() != ordered:
                        break
                    body, nested = [match[3]], []
                    i += 1
                    while i < len(lines) and lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) > indent:
                        nested.append(lines[i][min(indent + 2, len(lines[i]) - len(lines[i].lstrip())):])
                        i += 1
                    while nested and not re.match(r'^\s*(?:[-+*]|\d+[.)])\s+', nested[0]):
                        body.append(nested.pop(0))
                    items.append('<li>' + self.unit('\n'.join(body), section) + self.blocks(nested, section) + '</li>')
                out.append(f'<{tag}{start}>' + ''.join(items) + f'</{tag}>')
                continue
            para = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r'^\s*(?:#{2,6}\s|>|[-+*]\s|\d+[.)]\s|```|~~~)', lines[i]):
                if i + 1 < len(lines) and '|' in lines[i] and all(re.fullmatch(r':?-{3,}:?', c) for c in _cells(lines[i + 1])):
                    break
                para.append(lines[i])
                i += 1
            out.append('<div class="wp-claim">' + self.unit('\n'.join(para), section, lambda t: '<p>' + _inline(t) + '</p>') + '</div>')
        return '\n'.join(out)


def build_summary(markdown, *, template, clayprint=None):
    """Build a self-contained HTML; the exact UTF-8 Markdown remains downloadable."""
    title, sections = _sections(markdown, template)
    renderer = _Markdown()
    bodies, section_claims = [], []
    for section in sections:
        start = len(renderer.claims)
        bodies.append(renderer.blocks(section['lines'], section['title']))
        section_claims.append(renderer.claims[start:])
    report = {'title': title, 'message': 'WORDPRINT_MESSAGE', 'sections': [
        {'id': f'wp-section-{i}', 'claim': s['title'] or '摘要',
         'blocks': [{'type': 'text', 'text': f'WORDPRINT_BODY_{i}'}],
         **({'sources': [c['note'] + '　' + ' '.join('[' + t + ']' for t in c['citations']) for c in section_claims[i] if c['citations']]} if any(c['citations'] for c in section_claims[i]) else {})}
        for i, s in enumerate(sections)
    ]}
    root = find_clayprint(clayprint)
    script = 'import {buildReport} from ' + json.dumps((root / 'scripts/report.js').as_uri()) + ';let s="";for await(const c of process.stdin)s+=c;process.stdout.write(buildReport(JSON.parse(s)).html);'
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(report), text=True, capture_output=True, check=True)
    html = result.stdout
    html = re.sub(r'<nav class="toc"[\s\S]*?</nav>', '', html)
    html = html.replace('<p class="cover-message">WORDPRINT_MESSAGE</p>', '')
    html = html.replace('class="report-front"', 'class="wordprint-front"')
    html = re.sub(r'<p>WORDPRINT_BODY_(\d+)</p>', lambda m: bodies[int(m[1])], html)
    for i, s in enumerate(sections):
        html = html.replace(f'<h2 id="wp-section-{i}">', f'<h2 id="wp-section-{i}" tabindex="-1">')
        if s['title'] is None:
            html = html.replace(f'<header class="section-heading">\n<h2 id="wp-section-{i}" tabindex="-1">摘要</h2>\n</header>', f'<span id="wp-section-{i}" tabindex="-1"></span>')
    toc = '<details class="wp-toc"><summary>目錄</summary><nav aria-label="目錄"><ol>' + ''.join(
        f'<li><a href="#wp-section-{i}">' + escape(s['title'] or '核心內容') + '</a></li>' for i, s in enumerate(sections)) + '</ol></nav></details>'
    after_core = min(3 if template == 'meeting' else 1, len(sections))
    target = f'<section aria-labelledby="wp-section-{after_core}">'
    html = html.replace(target, toc + '\n' + target, 1) if after_core < len(sections) else html.replace('</main>', toc + '\n</main>')
    payload = base64.b64encode(markdown.encode('utf-8')).decode('ascii')
    toolbar = '<details class="wp-export"><summary>匯出</summary><div><a download="notes.md" href="data:text/markdown;charset=utf-8;base64,' + payload + '">下載摘要 Markdown</a><button type="button" onclick="window.print()">系統列印</button></div></details>'
    html = html.replace('class="report-cover"', 'class="wordprint-cover"').replace('</h1>', '</h1>' + toolbar, 1)
    margins = re.search(r'@page \{\s*size: A4; margin: ([^;]+);', html)[1]
    css = Path(__file__).with_name('summary_report.css').read_text(encoding='utf-8')
    html = html.replace('</head>', '<style id="wordprint-summary">' + css + '\n@page :first { margin: ' + margins + '; }\n</style>\n</head>')
    return {'html': html, 'section_order': [s['title'] for s in sections], 'claims': renderer.claims}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('notes', type=Path)
    parser.add_argument('html', type=Path)
    parser.add_argument('--template', required=True, choices=['meeting', 'interview', 'lecture', 'custom'])
    parser.add_argument('--clayprint', type=Path)
    args = parser.parse_args()
    try:
        result = build_summary(args.notes.read_bytes().decode('utf-8'), template=args.template, clayprint=args.clayprint)
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(result['html'], encoding='utf-8')
        print(json.dumps({'html': str(args.html.resolve()), 'section_order': result['section_order']}, ensure_ascii=False))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'摘要呈現失敗：{error}\n')


if __name__ == '__main__':
    main()

"""Synthetic reader fidelity and interaction contracts; no model or private audio."""
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'scripts/transcript.py'
spec = importlib.util.spec_from_file_location('reader_transcript', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    chunks, turns = [], []
    for n in range(3):
        tokens = ['我', '們', '一起', '閱讀', '中文', '與', 'English', ' words', '保留', '換行', '與', '標點 <&>']
        text = '  我們一起閱讀中文與English words\r\n保留換行與標點 <&>。  '
        words = []
        for i, token in enumerate(tokens):
            start = n * 12 + i + .000123
            words.append(dict(start=start, end=start if i % 3 == 0 else start + .8, text=token))
            turns.append(dict(start=start, end=start + 1, speaker='S1' if i % 2 else 'S2'))
        chunks.append(dict(start=n * 12, end=(n + 1) * 12, text=text, words=words))
    return dict(model={'id': 'synthetic-only'}, chunks=chunks, turns=turns,
                sources=[dict(path='synthetic.wav', offset=0, duration=36)], speakers={'S1': {}, 'S2': {}})


class ReaderParser(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.texts, self.chunks, self.spans, self.tags, self.groups = [], [], [], [], []
        self.in_text = False
        self.in_who = False
        self.whos = []
        self.feed(value)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if attrs.get('class') == 'chunk':
            self.chunks.append(attrs['data-chunk'])
            self.groups.append([])
        if attrs.get('class') == 'seg':
            self.spans.append(attrs)
            self.groups[-1].append(attrs)
        if attrs.get('class') == 'text':
            self.in_text = True
            self.texts.append('')
        if 'who' in attrs.get('class', '').split():
            self.in_who = True
            self.whos.append('')
    def handle_endtag(self, tag):
        if tag == 'span':
            self.in_text = False
            self.in_who = False
    def handle_data(self, data):
        if self.in_text:
            self.texts[-1] += data
        if self.in_who:
            self.whos[-1] += data


class ReaderTests(unittest.TestCase):
    def render(self, run):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, 'clayprint_css', return_value=''):
            out = Path(folder) / 'out'
            m.render(run, {'duration': 36}, out, original_script=True, title='合成 <script>')
            return {p.name: p.read_bytes() for p in out.iterdir()}

    def test_zero_duration_fragmentation_exact_text_and_chunk_membership(self):
        run = fixture()
        before = copy.deepcopy(run)
        rows = list(m.rows(run))
        self.assertGreater(len(rows), 24)
        result = self.render(run)
        parsed = ReaderParser(result['transcript.html'].decode())
        self.assertEqual(parsed.texts, [r['text'] for r in rows])
        self.assertEqual(parsed.whos, [f'[{m.stamp(r["start"])}–{m.stamp(r["end"])}] {m.label(r, run["speakers"])}'
                                      for r in rows])
        self.assertEqual(''.join(parsed.texts), ''.join(c['text'] for c in run['chunks']))
        self.assertEqual(parsed.chunks, ['0', '1', '2'])
        self.assertEqual([(float(a['data-start']), float(a['data-end'])) for a in parsed.spans],
                         [(r['start'], r['end']) for r in rows])
        self.assertEqual(before, run)
        self.assertEqual(len(parsed.spans), len(rows))
        self.assertNotIn('</span>\n<span class="seg"', result['transcript.html'].decode())

    def test_escaping_no_false_attribution_and_no_audio(self):
        value = self.render(fixture())['transcript.html'].decode()
        self.assertIn('&lt;script&gt;', value)
        self.assertIn('&lt;&amp;&gt;', value)
        parsed = ReaderParser(value)
        self.assertTrue(all('tabindex' not in a and 'role' not in a for a in parsed.spans))
        self.assertNotIn('<audio ', value)
        self.assertIn('無法跳播', value)
        self.assertIn('複製 Markdown', value)
        self.assertIn('mailto:', value)

    def test_empty_recovery_message(self):
        run = fixture()
        run['chunks'] = [dict(start=0, end=36, text='', words=[])]
        value = self.render(run)['transcript.html'].decode()
        self.assertIn(m.EMPTY_TRANSCRIPT_NOTICE, value)

    def test_source_seam_not_joined_and_overlap_metadata_preserved(self):
        run = fixture()
        run['sources'] = [dict(path='a.wav', offset=0, duration=6), dict(path='b.wav', offset=6, duration=30)]
        run['turns'].append(dict(start=1, end=2, speaker='S2'))
        value = self.render(run)['transcript.html'].decode()
        parsed = ReaderParser(value)
        self.assertGreater(parsed.chunks.count('0'), 1)
        for group in parsed.groups:
            if len(group) > 1:
                owners = [{i for i, source in enumerate(run['sources'])
                           if source['offset'] <= float(row['data-start']) <= float(row['data-end']) <= source['offset'] + source['duration']}
                          for row in group]
                self.assertEqual(len(set(map(frozenset, owners))), 1)
                self.assertEqual(len(owners[0]), 1)
        self.assertTrue(any('重疊發言' in who for who in parsed.whos))
        self.assertEqual(''.join(parsed.texts), ''.join(c['text'] for c in run['chunks']))

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for offline handler checks')
    def test_keyboard_seek_and_copy_handlers(self):
        script = re.findall(r'<script>(.*?)</script>', m.page('synthetic', '<div class="chunk"></div>', 'copy text', [], True), re.S)[0]
        harness = r"""
const assert = require('node:assert/strict');
class El {
  constructor(dataset={}) { this.dataset=dataset; this.events={}; this.attrs={}; this.classList={toggle:()=>{}}; }
  addEventListener(name, fn) { this.events[name]=fn; }
  setAttribute(key,value) { this.attrs[key]=value; }
}
const player = new El(); player.currentTime=0; let plays=0;
player.play=()=>{plays++;return Promise.resolve()};
const row=new El({start:'1.000123',end:'2.123456'});
const copy=new El(), markdown={textContent:'"copy text"'};
global.document={querySelector:s=>s==='audio'?player:null,querySelectorAll:()=>[row],
  getElementById:id=>({copy,markdown})[id]};
let copied='';Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async t=>{copied=t}}}});
"""
        assertions = r"""
(async()=>{
for (const key of ['Enter',' ']) {
  let prevented=false;row.events.keydown({key,preventDefault:()=>{prevented=true}});
  assert.equal(prevented,true);assert.equal(player.currentTime,1.000123);
}
row.events.click();assert.equal(player.currentTime,1.000123);
assert.equal(plays,3);
await copy.events.click({target:copy});assert.equal(copied,'copy text');assert.equal(copy.textContent,'已複製');
console.log('handler assertions passed; mocked media, not audio device');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run([shutil.which('node'), '-e', harness + script + assertions], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_baseline_exports_unchanged(self):
        baseline = os.environ.get('WORDPRINT_READER_BASELINE')
        if not baseline:
            self.skipTest('Set WORDPRINT_READER_BASELINE to frozen pre-change transcript.py')
        spec = importlib.util.spec_from_file_location('baseline_transcript', baseline)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        run = fixture()
        result = self.render(run)
        with tempfile.TemporaryDirectory() as folder, patch.object(old, 'clayprint_css', return_value=''):
            out = Path(folder) / 'old'
            old.render(run, {'duration': 36}, out, original_script=True, title='合成 <script>')
            for p in out.iterdir():
                if p.name == 'transcript.md':
                    prefix = ('# 含時間與說話者逐字稿\n\n'
                              '逐字稿由模型產生；姓名、數字與否定語句請回聽確認。\n\n'
                              '模型推定說話者；可能身分與不確定／重疊發言均保留標記。\n\n')
                    old_md = p.read_bytes().decode('utf-8')
                    self.assertTrue(old_md.startswith(prefix))
                    self.assertEqual('# 含時間與說話者逐字稿\n\n' + old_md[len(prefix):],
                                     result[p.name].decode('utf-8'))
                elif p.name != 'transcript.html':
                    self.assertEqual(p.read_bytes(), result[p.name], p.name)


if __name__ == '__main__':
    unittest.main()

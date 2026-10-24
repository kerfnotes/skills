import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { checkReport } from '../evals/check-report.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const json = (file) => JSON.parse(readFileSync(file, 'utf8'));
const save = (file, data) => writeFileSync(file, JSON.stringify(data));
const report = { title: '試排', message: '保留理由與限制', sections: [{ claim: '先核對內容', blocks: [
  { type: 'text', text: '正文與來源需要清楚可讀。' },
  { type: 'chart', title: '虛構件數', chart: { kind: 'rank', rows: [{ label: '甲', value: 2 }, { label: '乙', value: 3 }], source: '虛構測試原稿' } },
], sources: ['虛構測試原稿'] }] };
const story = { title: '試排', pages: [{ type: 'summary', claim: '先核對內容', visual: { lead: '保留理由與限制', body: '正文與來源需要清楚可讀。', items: [{ label: '狀態', value: '待確認' }] }, sources: { source: '虛構測試原稿' } }] };

function run(cwd, script, args, tokens) {
  const env = { ...process.env, CLAYPRINT_TOKENS: tokens };
  delete env.CLAYPRINT_MODE;
  const r = spawnSync(process.execPath, [join(cwd, 'scripts', script), ...args], { cwd, env, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
}
async function outputs(dir, tokens, mode = 'present') {
  const tokenFile = join(dir, 'custom.json');
  save(tokenFile, tokens);
  save(join(dir, 'report.json'), report);
  save(join(dir, 'story.json'), { ...story, mode });
  run(dir, 'report.js', [join(dir, 'report.json'), join(dir, 'report.html')], tokenFile);
  run(dir, 'pptx.js', [join(dir, 'story.json'), join(dir, 'deck.pptx')], tokenFile);
  const html = readFileSync(join(dir, 'report.html'), 'utf8');
  assert.equal(checkReport(html, '虛構測試原稿：甲 2 件、乙 3 件。正文與來源需要清楚可讀。').figures, 1);
  const zip = await JSZip.loadAsync(readFileSync(join(dir, 'deck.pptx')));
  const slide = await zip.file('ppt/slides/slide1.xml').async('string');
  const css = html.match(/<style id="clayprint-theme">([\s\S]*?)<\/style>/)[1];
  return { html, slide, screen: css.slice(0, css.indexOf('@page')), print: css.slice(css.indexOf('@page')) };
}
function fixture(t) {
  mkdirSync(join(root, 'out'), { recursive: true });
  const dir = mkdtempSync(join(root, 'out', 'font-isolation-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  for (const part of ['scripts', 'design', 'assets']) cpSync(join(root, part), join(dir, part), { recursive: true });
  return dir;
}

for (const name of ['tokens.json', 'tokens.blue.json']) {
  test(`${name}: present, read and print changes stay in their own output medium`, async (t) => {
    const dir = fixture(t), tokens = json(join(dir, 'design', name));
    const base = await outputs(dir, tokens);
    const readBase = await outputs(dir, tokens, 'read');
    assert.match(base.slide, /sz="2000"/);
    assert.match(readBase.slide, /sz="1200"/);
    assert.match(base.html, /--cp-body: 16px;/);
    assert.match(base.html, /--cp-small: 12px;/);
    assert.match(base.html, /--cp-print-small: 9pt;/);
    const present = structuredClone(tokens);
    present.type.body.px = 44;
    present.type.sub.px = 42;
    present.type.title.px = 62;
    present.type.display.px = 114;
    const changed = await outputs(dir, present);
    assert.match(changed.slide, /sz="2200"/);
    assert.equal(changed.html, base.html);
    assert.equal((await outputs(dir, present, 'read')).slide, readBase.slide);

    // read.json is the existing reading-mode configuration, exercised in a private runtime copy.
    const readFile = join(dir, 'design/read.json'), read = json(readFile);
    read.type.body = 26;
    save(readFile, read);
    const readChanged = await outputs(dir, tokens, 'read');
    assert.match(readChanged.slide, /sz="1300"/);
    assert.notEqual(readChanged.slide, readBase.slide);
    assert.equal(readChanged.html, base.html);
    assert.equal((await outputs(dir, tokens)).slide, base.slide);

    const print = structuredClone(tokens);
    print.print.type.small = 8.5;
    const printChanged = await outputs(dir, print);
    assert.match(printChanged.print, /--cp-print-small: 8\.5pt;/);
    assert.match(printChanged.print, /font: 8\.5pt var\(--cp-font\)/);
    assert.match(printChanged.print, /--cp-print-body: 11pt;/);
    assert.equal(printChanged.screen, base.screen);
    assert.equal(printChanged.slide, base.slide);
    assert.equal((await outputs(dir, print, 'read')).slide, readChanged.slide);
  });

  test(`${name}: legacy custom layers keep the slide-to-screen calculation`, async (t) => {
    const dir = fixture(t), tokens = json(join(dir, 'design', name));
    const original = await outputs(dir, tokens);
    delete tokens.screen;
    const legacy = await outputs(dir, tokens);
    assert.match(legacy.html, /--cp-body: 20px;/);
    assert.notEqual(legacy.screen, original.screen);
    tokens.type.body.px = 38;
    tokens.type.label.px = 26;
    tokens.type.sub.px = 42;
    tokens.type.title.px = 62;
    tokens.type.display.px = 114;
    const out = await outputs(dir, tokens);
    for (const [key, value] of Object.entries({ body: 19, small: 13, sub: 21, 'title-size': 31, display: 57 })) {
      assert.ok(out.html.includes(`--cp-${key}: ${value}px;`), key);
    }
    assert.match(out.slide, /sz="1900"/);
    assert.match(out.print, /--cp-print-small: 9pt;/);
  });

  test(`${name}: explicit screen sizes control complete HTML without changing PPTX or print`, async (t) => {
    const dir = fixture(t), tokens = json(join(dir, 'design', name));
    const base = await outputs(dir, tokens);
    const readBase = await outputs(dir, tokens, 'read');
    tokens.screen = { type: { body: 19, small: 13, sub: 21, title: 31, display: 57 } };
    const changed = await outputs(dir, tokens);
    for (const [key, value] of Object.entries({ body: 19, small: 13, sub: 21, 'title-size': 31, display: 57 })) {
      assert.ok(changed.html.includes(`--cp-${key}: ${value}px;`), key);
    }
    assert.equal(changed.slide, base.slide);
    assert.equal(changed.print, base.print);
    assert.equal((await outputs(dir, tokens, 'read')).slide, readBase.slide);
  });
}

for (const name of ['tokens.json', 'tokens.blue.json']) {
  test(`${name}: full artifacts isolate native and embedded SVG chart typography`, async (t) => {
    const dir = fixture(t), tokens = json(join(dir, 'design', name));
    const chart = { kind: 'rank', rows: [{ label: '甲', value: 2 }, { label: '乙', value: 3 }] };
    const pages = [
      ...[true, false].map((native) => ({ type: 'evidence', claim: '核對字級', visual: { ...chart, native }, sources: { source: '原稿' } })),
      { type: 'evidence', claim: '表格', sources: { source: '原稿' }, visual: { kind: 'table', columns: [{ name: '項目', type: 'text' }], rows: [['甲']] } },
    ];
    const sizes = async (mode, expected) => {
      save(join(dir, 'charts.json'), { title: '圖表字級', pages, mode });
      run(dir, 'pptx.js', [join(dir, 'charts.json'), join(dir, 'charts.pptx')], join(dir, 'custom.json'));
      const zip = await JSZip.loadAsync(readFileSync(join(dir, 'charts.pptx')));
      const xml = await zip.file('ppt/charts/chart1.xml').async('string');
      assert.deepEqual([...new Set([...xml.matchAll(/ sz="(\d+)"/g)].map((m) => Number(m[1])))], [expected * 100]);
      const svgs = Object.keys(zip.files).filter((n) => n.endsWith('.svg'));
      assert.equal(svgs.length, 1);
      const svg = await zip.file(svgs[0]).async('string');
      assert.deepEqual([...new Set([...svg.matchAll(/font-size="(\d+)"/g)].map((m) => Number(m[1])))], [expected * 2]);
      if (mode === 'read') {
        assert.match(await zip.file('ppt/slides/slide1.xml').async('string'), /sz="900"/);
        assert.match(await zip.file('ppt/slides/slide3.xml').async('string'), /sz="1000"/);
      }
    };
    const base = await outputs(dir, tokens);
    assert.match(base.html, /font-size="24"/);
    assert.match(base.print, /\[data-tick\] \{ font-size: 24px;/);
    assert.match(base.print, /th, td \{ font-size: var\(--cp-print-body\);/);
    await sizes('present', 16);
    await sizes('read', 10);
    tokens.type.chart.px = 36;
    const custom = await outputs(dir, tokens);
    assert.equal(custom.html, base.html);
    await sizes('present', 18);
    delete tokens.type.chart;
    await outputs(dir, tokens);
    await sizes('present', 12);
    delete tokens.print;
    const fallback = await outputs(dir, tokens);
    assert.match(fallback.print, /--cp-print-body: 11pt;/);
    assert.match(fallback.print, /--cp-print-small: 9pt;/);
  });
}

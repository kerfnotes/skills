import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { validateStory } from '../scripts/pptx.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const url = (file) => JSON.stringify(new URL(`../${file}`, import.meta.url).href);
const fixture = () => JSON.parse(readFileSync(path.join(root, 'tests/fixtures/story-panels.json'), 'utf8'));
const script = 'evals/fixtures/example-script.md';
const EMU = 914400 / 144;

function child(code) {
  const env = { ...process.env, CLAYPRINT_MODE: 'read' };
  delete env.CLAYPRINT_TOKENS;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', code], { cwd: root, env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}
const buildRead = (story, out) => child(`import { writeFileSync } from 'node:fs'; import { build } from ${url('scripts/pptx.js')};
  const r = await build(${JSON.stringify(story)}); ${out ? `writeFileSync(${JSON.stringify(out)}, r.buffer);` : ''} console.log(JSON.stringify(r.warnings));`);

// check.mjs from the CLI, so the story's mode picks its tokens the same way a user run does.
function checkCli(story) {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-panels-check-'));
  try {
    const file = path.join(dir, 'story.json');
    writeFileSync(file, JSON.stringify(story));
    const env = { ...process.env };
    delete env.CLAYPRINT_MODE;
    delete env.CLAYPRINT_TOKENS;
    return spawnSync(process.execPath, ['evals/check.mjs', file, script], { cwd: root, env, encoding: 'utf8' });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// Shapes on one slide in design px, with joined text and font sizes in hundredths of a point.
function shapes(xml) {
  return xml.split(/<p:(?:sp|graphicFrame|pic)>/).slice(1).map((sp) => {
    const [, x, y] = sp.match(/<a:off x="(\d+)" y="(\d+)"\/>/) ?? [];
    const [, cx, cy] = sp.match(/<a:ext cx="(\d+)" cy="(\d+)"\/>/) ?? [];
    return {
      x: x / EMU, y: y / EMU, w: cx / EMU, h: cy / EMU,
      chart: sp.includes('/chart"'), table: sp.includes('<a:tbl>'),
      text: sp.includes('<a:tbl>') ? '' : [...sp.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((m) => m[1]).join(''),
      sizes: [...sp.matchAll(/\ssz="(\d+)"/g)].map((m) => Number(m[1])),
    };
  });
}

const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1, `${msg}：${a} ≠ ${b}`);

test('panels：圖表加表格、清單加文字兩頁可建檔，每格有標題、內容與註，split 3:2 時左格寬為右格 1.5 倍', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-panels-'));
  try {
    const story = fixture(), out = path.join(dir, 'panels.pptx');
    assert.deepEqual(buildRead(story, out), []);
    const zip = await JSZip.loadAsync(readFileSync(out));
    const [chartPage, textPage] = story.pages;

    const one = shapes(await zip.file('ppt/slides/slide1.xml').async('string'));
    const titles = chartPage.visual.items.map((it) => one.find((s) => s.text === it.title));
    for (const t of titles) assert.deepEqual([...new Set(t.sizes)], [1000], `格標題 10 pt：${t.text}`);
    near(titles[0].w, titles[1].w * 1.5, '左格寬為右格 1.5 倍');
    assert.ok(titles[0].x + titles[0].w < titles[1].x, '兩格不重疊');
    const chart = one.find((s) => s.chart), table = one.find((s) => s.table);
    assert.ok(chart && table, '左格原生圖表、右格原生表格');
    near(chart.x, titles[0].x, '圖表對齊左格');
    near(chart.w, titles[0].w, '圖表寬等於左格');
    near(table.x, titles[1].x, '表格對齊右格');
    assert.ok(chart.y > titles[0].y && table.y > titles[1].y, '圖表與表格在格標題下方');
    for (const [i, it] of chartPage.visual.items.entries()) {
      const note = one.find((s) => s.text === it.note);
      assert.deepEqual([...new Set(note.sizes)], [1000], `第 ${i + 1} 格註 10 pt`);
      near(note.x, titles[i].x, `第 ${i + 1} 格註對齊`);
      assert.ok(note.y > (i ? table : chart).y, `第 ${i + 1} 格註在內容下方`);
    }
    for (const field of [chartPage.kicker, chartPage.claim, chartPage.lede, '1 / 2']) assert.ok(one.some((s) => s.text === field), `頁面保留 ${field}`);

    const two = shapes(await zip.file('ppt/slides/slide2.xml').async('string'));
    const [risk, choice] = textPage.visual.items.map((it) => two.find((s) => s.text === it.title));
    near(risk.w, choice.w, '省略 split 時等分');
    const body = two.find((s) => s.text === textPage.visual.items[1].visual);
    assert.deepEqual([...new Set(body.sizes)], [1100], '文字格正文 11 pt');
    near(body.x, choice.x, '文字在右格');
    for (const item of textPage.visual.items[0].visual.items) {
      const heading = two.find((s) => s.text === item.heading);
      assert.ok(heading, `清單項目 ${item.heading}`);
      near(heading.x, risk.x, '清單在左格');
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('panels：驗收器通過範例，每格註超過 3 行警告', () => {
  const ok = checkCli(fixture());
  assert.equal(ok.status, 0, ok.stderr);
  assert.match(ok.stdout, /0 項警告/);
  const story = fixture();
  story.pages[0].visual.items[1].note = '收支比由 0.90 降至 0.86，量增但成本增加更快。'.repeat(6);
  const warned = checkCli(story);
  assert.equal(warned.status, 0, warned.stderr);
  assert.match(warned.stderr, /第 1 頁 visual\.items\[1\]\.note：估算 \d+ 行，上限 3 行/);
});

test('panels：格內圖表、表格、註與文字的數字都要有原稿依據', () => {
  const cases = [
    [(s) => { s.pages[0].visual.items[1].note = '收支比降至 0.85。'; }, /第 1 頁 visual\.items\[1\]\.note：原稿找不到數字 0\.85/],
    [(s) => { s.pages[0].visual.items[0].visual.rows[1].value = 302; }, /第 1 頁 visual\.items\[0\]\.visual\.rows\[1\]\.value：原稿找不到數字 302/],
    [(s) => { s.pages[0].visual.items[1].visual.rows[1][2] = 466; }, /第 1 頁 visual\.items\[1\]\.visual\.rows\[1\]\[2\]：原稿找不到數字 466/],
    [(s) => { s.pages[1].visual.items[1].visual = '方案乙減少 29%。'; }, /第 2 頁 visual\.items\[1\]\.visual：原稿找不到數字 29%/],
    [(s) => { s.pages[1].visual.items[0].title = '7 大風險'; }, /第 2 頁 visual\.items\[0\]\.title：原稿找不到數字 7/],
  ];
  for (const [edit, pattern] of cases) {
    const story = fixture();
    edit(story);
    const result = checkCli(story);
    assert.equal(result.status, 1, `應失敗：${pattern}`);
    assert.match(result.stderr, pattern);
  }
});

test('panels：格數不是 2、格內缺 title、visual 種類不支援或 split 錯誤時指出頁碼與格序', () => {
  const page = () => structuredClone(fixture().pages[0]);
  const story = (p) => ({ mode: 'read', pages: [{ type: 'cover', claim: '封面' }, p] });
  const cases = [
    [(p) => { p.visual.items.pop(); }, /第 2 頁：pages\[1\]\.visual\.items .*恰好兩格/],
    [(p) => { p.visual.items.push(p.visual.items[0]); }, /第 2 頁：pages\[1\]\.visual\.items .*恰好兩格/],
    [(p) => { delete p.visual.items[1].title; }, /第 2 頁：pages\[1\]\.visual\.items\[1\]\.title .*第 2 格/],
    [(p) => { p.visual.items[0].visual = { kind: 'pie', rows: [] }; }, /第 2 頁：pages\[1\]\.visual\.items\[0\]\.visual\.kind .*第 1 格/],
    [(p) => { p.visual.items[1].visual = 42; }, /第 2 頁：pages\[1\]\.visual\.items\[1\]\.visual .*第 2 格.*chart、table、list 或 text/],
    [(p) => { p.visual.items[1].visual = { items: [{ body: '沒有標題' }] }; }, /第 2 頁：pages\[1\]\.visual\.items\[1\]\.visual\.items\[0\]\.heading/],
    [(p) => { p.visual.items[0].note = 7; }, /第 2 頁：pages\[1\]\.visual\.items\[0\]\.note/],
    [(p) => { p.visual.split = [3, 0]; }, /第 2 頁：pages\[1\]\.visual\.split/],
  ];
  for (const [edit, pattern] of cases) {
    const p = page();
    edit(p);
    assert.throws(() => validateStory(story(p)), pattern);
  }
  const ok = checkCli({ ...fixture(), pages: [fixture().pages[0], { ...fixture().pages[1], visual: { items: [fixture().pages[1].visual.items[0]] } }] });
  assert.equal(ok.status, 1);
  assert.match(ok.stderr, /驗收失敗：第 2 頁：pages\[1\]\.visual\.items .*恰好兩格/);
});

test('panels：格內圖表與 evidence 同一套檢查，x、columns、refs 錯誤指出格內欄位', () => {
  const story = (visual) => ({ mode: 'read', pages: [{ type: 'panels', claim: '兩格', sources: { source: '虛構' }, visual: { items: [
    { title: '左', visual }, { title: '右', visual: '文字' }] } }] });
  const cases = [
    [{ kind: 'line', x: [2024, 2025], series: [{ name: '甲', values: [1, 2] }] }, /pages\[0\]\.visual\.items\[0\]\.visual\.x 格式不正確；請改成文字字串陣列/],
    [{ kind: 'table', columns: [{ name: '項目' }, { name: ' ' }], rows: [['甲', 1]] }, /pages\[0\]\.visual\.items\[0\]\.visual\.columns\[1\]\.name 格式不正確/],
    [{ kind: 'rank', rows: [{ label: '甲', value: 1 }], refs: [{ label: '目標' }] }, /pages\[0\]\.visual\.items\[0\]\.visual\.refs\[0\] 格式不正確；請提供參考線的數字座標/],
  ];
  for (const [visual, pattern] of cases) {
    assert.throws(() => validateStory(story(visual)), pattern);
    assert.throws(() => validateStory({ pages: [{ type: 'evidence', claim: '證據', visual }] }), new RegExp(pattern.source.replace('pages\\[0\\]\\.visual\\.items\\[0\\]\\.visual', 'pages\\[0\\]\\.visual')));
  }
});

test('panels：簡報版 story 使用時，validateStory 與驗收器都說明只有閱讀版支援', () => {
  const { mode, ...present } = fixture();
  assert.equal(mode, 'read');
  assert.throws(() => validateStory(present), /第 1 頁：pages\[0\]\.type 格式不正確；請在根層填 "mode": "read"（只有閱讀版支援 panels）/);
  const result = checkCli(present);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /驗收失敗：第 1 頁：.*只有閱讀版/);
});

test('panels：兩格都是文字或清單時，頁面填滿低於 70% 會警告；含圖表或表格的格不估填滿', () => {
  const page = fixture().pages[1];
  page.visual.items[0].visual.items.splice(1);
  const sparse = buildRead({ mode: 'read', pages: [page] });
  assert.ok(sparse.some((w) => /^第 1 頁填滿 \d+%，低於 70%/.test(w)), sparse.join('\n'));
  assert.deepEqual(buildRead({ mode: 'read', pages: [fixture().pages[0]] }), []);
});

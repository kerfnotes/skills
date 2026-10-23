import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { build } from '../scripts/pptx.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const url = (file) => JSON.stringify(new URL(`../${file}`, import.meta.url).href);
const sources = { source: '虛構測試文字稿' };
const EMU = 914400 / 144;

function child(code, mode) {
  const env = { ...process.env };
  delete env.CLAYPRINT_MODE;
  delete env.CLAYPRINT_TOKENS;
  if (mode) env.CLAYPRINT_MODE = mode;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', code], { cwd: root, env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

// Build in a child process so design/read.json is loaded; returns warnings and, with out, writes the deck.
function buildIn(mode, story, out) {
  return child(`import { writeFileSync } from 'node:fs'; import { build } from ${url('scripts/pptx.js')};
    const r = await build(${JSON.stringify({ ...story, ...(mode === 'read' ? { mode } : {}) })});
    ${out ? `writeFileSync(${JSON.stringify(out)}, r.buffer);` : ''} console.log(JSON.stringify(r.warnings));`, mode);
}
const readWarnings = (pages) => buildIn('read', { title: '閱讀設計測試', pages });
const presentWarnings = async (pages) => (await build({ title: '閱讀設計測試', pages })).warnings;

// Text boxes on one slide: top y in design px, joined text and font sizes in hundredths of a point.
function shapes(xml) {
  return xml.split('<p:sp>').slice(1).map((sp) => ({
    y: Number(sp.match(/<a:off x="\d+" y="(\d+)"\/>/)?.[1]) / EMU,
    text: [...sp.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((m) => m[1]).join(''),
    sizes: [...sp.matchAll(/\ssz="(\d+)"/g)].map((m) => Number(m[1])),
  })).filter((s) => s.text);
}

test('閱讀設計層：字級、上下邊界與新字級鍵只在閱讀模式生效', () => {
  const code = `import { loadTokens } from ${url('scripts/tokens.js')}; const t = loadTokens();
    console.log(JSON.stringify({ title: t.type.title.px, body: t.type.body.px, label: t.type.label.px, chart: t.type.chart?.px, source: t.type.source?.px, minimum: t.type.minimum, margin: t.margin, capacity: t.capacity }));`;
  const present = JSON.parse(readFileSync(path.join(root, 'design/tokens.json'), 'utf8'));
  const read = child(code, 'read');
  assert.deepEqual({ ...read, margin: undefined, capacity: undefined }, { title: 44, body: 22, label: 20, chart: 18, source: 16, minimum: 16, margin: undefined, capacity: undefined });
  assert.deepEqual(read.margin, { ...present.margin, top: 45, bottom: 40 });
  assert.deepEqual(read.capacity, {
    summary: [2, 6], summaryBody: 10, list: [3, 8], listBody: 3, numbers: [2, 8], numbersNote: 3,
    compare: [2, 5], compareRows: 8, process: [3, 8], columns: [2, 5], columnsBody: 6, tableRows: 14, closeRows: 14,
    points: [2, 4], panelNote: 3, minFill: 0.7,
  });
  const base = child(code);
  assert.deepEqual(base.margin, present.margin);
  assert.equal(base.chart, undefined);
  assert.equal(base.source, undefined);
  assert.equal(base.title, present.type.title.px);
});

test('閱讀版範例：標題 22 pt、正文 11 pt、標籤 10 pt、圖表 9 pt、來源與頁碼 8 pt 同一行，上下邊界 8／7 mm', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-read-design-'));
  try {
    const story = JSON.parse(readFileSync(path.join(root, 'examples/story-read.json'), 'utf8'));
    const out = path.join(dir, 'read.pptx');
    buildIn('read', story, out);
    const zip = await JSZip.loadAsync(readFileSync(out));
    const total = story.pages.length;
    for (let n = 2; n <= total; n++) {
      const page = story.pages[n - 1], boxes = shapes(await zip.file(`ppt/slides/slide${n}.xml`).async('string'));
      const title = boxes.find((s) => s.text === page.claim);
      assert.deepEqual([...new Set(title.sizes)], [2200], `第 ${n} 頁標題`);
      assert.ok(Math.abs(title.y - (45 + 20 + 28)) < 1, `第 ${n} 頁標題 y ${title.y}`);
      const pageNo = boxes.find((s) => s.text === `${n} / ${total}`), source = boxes.find((s) => s.text === `資料來源：${page.sources.source}`);
      assert.deepEqual([...new Set([...pageNo.sizes, ...source.sizes])], [800], `第 ${n} 頁來源與頁碼`);
      assert.equal(pageNo.y, source.y, `第 ${n} 頁頁碼與來源同一行`);
      // One source row of 16 px × 1.45 above the 7 mm bottom margin.
      assert.ok(Math.abs(pageNo.y - (1080 - 40 - 16 * 1.45)) < 1, `第 ${n} 頁頁碼 y ${pageNo.y}`);
      if (page.kicker) assert.deepEqual([...new Set(boxes.find((s) => s.text === page.kicker).sizes)], [1000], `第 ${n} 頁頁首`);
    }
    const evidence = shapes(await zip.file('ppt/slides/slide3.xml').async('string'));
    assert.ok(evidence.find((s) => s.text === story.pages[2].note.replaceAll('\n', '')).sizes.every((sz) => sz === 1100), '證據頁 note 正文 11 pt');
    const charts = Object.keys(zip.files).filter((n) => /^ppt\/charts\/chart\d+\.xml$/.test(n));
    assert.ok(charts.length > 0);
    for (const name of charts) {
      const sizes = [...(await zip.file(name).async('string')).matchAll(/\ssz="(\d+)"/g)].map((m) => Number(m[1]));
      assert.deepEqual([...new Set(sizes)], [900], `${name} 圖表文字 9 pt`);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('閱讀版標題以 22 pt 估算：兩行不警告、三行警告；同一句在簡報版 28 pt 已是三行', async () => {
  const list = (claim) => ({ type: 'list', claim, sources, visual: { items: [{ heading: '甲' }, { heading: '乙' }, { heading: '丙' }] } });
  // Wraps at 95% of the 1720 px inner width; one CJK character is as wide as its px: 37 per line at 44 px, 29 at 56 px.
  const twoLines = '標'.repeat(37 * 2), threeLines = '標'.repeat(37 * 2 + 1);
  const claimWarn = (warnings) => warnings.filter((w) => /^第 1 頁 claim：估算/.test(w));
  assert.deepEqual(claimWarn(readWarnings([list(twoLines)])), []);
  assert.match(claimWarn(readWarnings([list(threeLines)])).join('\n'), /估算 3 行，上限 2 行/);
  assert.match(claimWarn(await presentWarnings([list(twoLines)])).join('\n'), /估算 3 行，上限 2 行/);
});

const items = (n, make) => Array.from({ length: n }, (_, i) => make(i));
const capacityPages = (extra) => [
  { type: 'list', claim: '清單', sources, visual: { items: items(8 + extra, (i) => ({ heading: `第${i}項` })) } },
  { type: 'numbers', claim: '數字', sources, visual: { items: items(8 + extra, (i) => ({ label: `指標${i}`, value: i })) } },
  { type: 'summary', claim: '摘要', sources, visual: { lead: '結論', items: items(6 + extra, (i) => ({ label: `項目${i}`, value: i })) } },
  { type: 'compare', claim: '比較', sources, visual: { rows: items(8 + extra, (i) => `列${i}`), options: items(5 + extra, (i) => ({ name: `案${i}`, values: items(8 + extra, () => '甲') })) } },
  { type: 'process', claim: '流程', sources, visual: { steps: items(8 + extra, (i) => ({ heading: `步${i}` })) } },
  { type: 'columns', claim: '並列', sources, visual: { items: items(5 + extra, (i) => ({ heading: `欄${i}` })) } },
  { type: 'evidence', claim: '表格', sources, note: '說明', visual: { kind: 'table', columns: [{ name: '項目', type: 'text' }, { name: '值', type: 'text' }], rows: items(14 + extra, (i) => [`項${i}`, '甲']) } },
  { type: 'close', claim: '下一步', sources, visual: { rows: items(14 + extra, (i) => ({ task: `待辦${i}` })) } },
];
const capacity = [
  [1, /第 1 頁診斷清單是 9 項，規格是 3～8 項/],
  [2, /第 2 頁數字格是 9 格，規格是 2～8 格/],
  [3, /第 3 頁主管摘要是 7 格，規格是 2～6 格/],
  [4, /第 4 頁比較方案是 6 個，規格是 2～5 個/],
  [4, /第 4 頁比較列是 9 列，規格是至多 8 列：刪掉次要的比較列，或拆成兩頁。/],
  [5, /第 5 頁無日期流程是 9 步，規格是 3～8 步/],
  [6, /第 6 頁並列重點是 6 欄，規格是 2～5 欄/],
  [7, /第 7 頁表格是 15 列，規格是至多 14 列：刪列或合併相近的列，或拆成兩頁。/],
  [8, /第 8 頁收尾待辦是 15 列，規格是至多 14 列：合併同一負責人的待辦，或拆成兩頁。/],
];

test('閱讀版容量上限：剛好上限不警告，超出一項才警告', () => {
  const atCap = readWarnings(capacityPages(0)), over = readWarnings(capacityPages(1));
  assert.deepEqual(atCap.filter((w) => /規格是/.test(w)), []);
  for (const [, pattern] of capacity) assert.ok(over.some((w) => pattern.test(w)), `${pattern}\n${over.join('\n')}`);
});

test('閱讀版軟上限放得下：標題一行時摘要 6 項、收尾 14 列沒有高度警告', () => {
  const warnings = readWarnings(capacityPages(0)).filter((w) => /^第 [38] 頁/.test(w));
  assert.deepEqual(warnings, []);
});

test('列數上限只屬於閱讀版：簡報版比較 9 列、表格與收尾 15 列不新增警告', async () => {
  const warnings = await presentWarnings(capacityPages(1).filter((p) => ['compare', 'evidence', 'close'].includes(p.type)));
  assert.deepEqual(warnings.filter((w) => /比較列|表格是|收尾待辦/.test(w)), []);
});

test('閱讀版行數上限：數字格 note 與清單 body 3 行不警告、4 行警告', () => {
  // 22 px body: a two-cell numbers note is 816 px wide (35 characters a line), a list body 1024 px (44 a line).
  const pages = (lines) => [
    { type: 'numbers', claim: '數字', sources, visual: { items: [{ label: '甲', value: 1, note: '註'.repeat(35 * (lines - 1) + 1) }, { label: '乙', value: 2 }] } },
    { type: 'list', claim: '清單', sources, visual: { items: [{ heading: '甲', body: '文'.repeat(44 * (lines - 1) + 1) }, { heading: '乙' }, { heading: '丙' }] } },
  ];
  const limit = (warnings) => warnings.filter((w) => /note：估算|body：估算/.test(w));
  assert.deepEqual(limit(readWarnings(pages(3))), []);
  const over = limit(readWarnings(pages(4)));
  assert.equal(over.length, 2, over.join('\n'));
  for (const w of over) assert.match(w, /估算 4 行，上限 3 行/);
});

test('閱讀版驗收：缺來源行的頁面失敗並指出頁碼', async () => {
  const story = { mode: 'read', title: '來源測試', pages: [
    { type: 'statement', claim: '第一頁', sources },
    { type: 'statement', claim: '第二頁', sources: { source: ' ' } },
  ] };
  const code = `import { check } from ${url('evals/check.mjs')};
    try { await check(${JSON.stringify(story)}, '無數字'); console.log('null'); } catch (e) { console.log(JSON.stringify(e.message)); }`;
  assert.match(child(code, 'read'), /^第 2 頁 sources\.source 缺少資料來源/);
});

test('閱讀版填滿率低於 70% 的內容頁以固定文案警告，簡報版不警告', async () => {
  const fill = /^第 1 頁填滿 (\d+)%，低於 70%：加 takeaway 或 points，或併入相鄰頁。$/;
  const statement = [{ type: 'statement', claim: '先記住這件事', sources }];
  assert.ok(readWarnings(statement).some((w) => fill.test(w)), readWarnings(statement).join('\n'));
  assert.ok(!(await presentWarnings(statement)).some((w) => /填滿|內容區/.test(w)));
  // A page between half and 70% full warned under neither old rule; it warns now.
  const columns = (lines) => [{ type: 'columns', claim: '並列', sources, visual: { items: [
    { heading: '甲', body: '欄內正文'.repeat(9 * lines) }, { heading: '乙' }] } }];
  const percents = [8, 9, 10, 11, 12].map((lines) => readWarnings(columns(lines)).map((w) => w.match(fill)?.[1]).find(Boolean));
  assert.ok(percents.some((p) => p >= 50 && p < 70), percents.join(','));
  assert.ok(!readWarnings(columns(16)).some((w) => fill.test(w) || /內容區/.test(w)));
});

test('閱讀版的填滿門檻、points 點數與 panels 註行數放在設計層 read.json', () => {
  const { capacity } = JSON.parse(readFileSync(path.join(root, 'design/read.json'), 'utf8'));
  assert.equal(capacity.minFill, 0.7);
  assert.deepEqual(capacity.points, [2, 4]);
  assert.equal(capacity.panelNote, 3);
  const pptx = readFileSync(path.join(root, 'scripts/pptx.js'), 'utf8');
  assert.doesNotMatch(pptx, /MIN_FILL|PANEL_NOTE|points: \[2, 4\]|低於 70%/);
});

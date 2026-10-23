import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { build, validateStory } from '../scripts/pptx.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const url = (file) => JSON.stringify(new URL(`../${file}`, import.meta.url).href);
const sources = { source: '虛構測試文字稿' };
const EMU = 914400 / 144;

function child(code) {
  const env = { ...process.env, CLAYPRINT_MODE: 'read' };
  delete env.CLAYPRINT_TOKENS;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', code], { cwd: root, env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

// Build a read deck in a child process (design/read.json loads at import); with out, also write the deck.
const readBuild = (pages, out) => child(`import { writeFileSync } from 'node:fs'; import { build } from ${url('scripts/pptx.js')};
  const r = await build(${JSON.stringify({ title: '閱讀版右欄測試', mode: 'read', pages })});
  ${out ? `writeFileSync(${JSON.stringify(out)}, r.buffer);` : ''} console.log(JSON.stringify(r.warnings));`);

// Run check.mjs in read mode; returns { warnings } or { error }.
const readCheck = (pages, script) => child(`import { check } from ${url('evals/check.mjs')};
  try { const r = await check(${JSON.stringify({ mode: 'read', pages })}, ${JSON.stringify(script)}); console.log(JSON.stringify({ warnings: r.warnings })); }
  catch (e) { console.log(JSON.stringify({ error: e.message })); }`);

function shapes(xml) {
  return xml.split('<p:sp>').slice(1).map((sp) => ({
    x: Number(sp.match(/<a:off x="(\d+)" y="\d+"\/>/)?.[1]) / EMU,
    y: Number(sp.match(/<a:off x="\d+" y="(\d+)"\/>/)?.[1]) / EMU,
    text: [...sp.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((m) => m[1]).join(''),
    sizes: [...sp.matchAll(/\ssz="(\d+)"/g)].map((m) => Number(m[1])),
    bold: /\sb="1"/.test(sp),
  })).filter((s) => s.text);
}

async function slides(pages) {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-read-evidence-'));
  try {
    const out = path.join(dir, 'deck.pptx');
    const warnings = readBuild(pages, out);
    const zip = await JSZip.loadAsync(readFileSync(out));
    const boxes = [];
    for (let n = 1; n <= pages.length; n++) boxes.push(shapes(await zip.file(`ppt/slides/slide${n}.xml`).async('string')));
    return { warnings, boxes };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const rank = { kind: 'rank', rows: [{ label: '甲', value: 12 }, { label: '乙', value: 8 }] };
const evidence = (extra) => ({ type: 'evidence', claim: '甲 12 件領先', sources, visual: rank, ...extra });

test('閱讀版 evidence 右欄依序顯示 takeaway、points、note：takeaway 10 pt 粗體、points 10 pt', async () => {
  const points = ['甲的件數最多，領先乙約一半。', '乙仍在成長，差距可能縮小。', '兩者合計占全部案件的大宗。'];
  const page = evidence({ takeaway: '甲是目前最主要的來源。', points, note: '資料只含已結案件，未結案件不列入。' });
  const { warnings, boxes: [boxes] } = await slides([page]);
  assert.deepEqual(warnings, []);
  const takeaway = boxes.find((s) => s.text === page.takeaway);
  assert.deepEqual([...new Set(takeaway.sizes)], [1000]);
  assert.ok(takeaway.bold, 'takeaway 粗體');
  const shown = points.map((p) => boxes.find((s) => s.text === p));
  for (const s of shown) assert.deepEqual([...new Set(s.sizes)], [1000]);
  const note = boxes.find((s) => s.text === page.note);
  const ys = [takeaway, ...shown, note].map((s) => s.y);
  assert.deepEqual(ys, [...ys].sort((a, b) => a - b), `右欄由上而下 ${ys.join(', ')}`);
  // The right column starts after the 1000 px read-deck chart.
  for (const s of [takeaway, ...shown, note]) assert.ok(s.x > 120 + 1000, `右欄 x ${s.x}`);
});

test('points 少於 2、多於 4 或單點超過兩行時警告並指出頁碼', () => {
  // 624 px column minus a 20 px bullet indent: 28 characters a line at 20 px.
  const warnings = readBuild([
    evidence({ points: ['只有一點'] }),
    evidence({ points: ['一', '二', '三', '四', '五'] }),
    evidence({ points: ['點'.repeat(56), '點'.repeat(57)] }),
  ]);
  assert.ok(warnings.includes('第 1 頁 points 是 1 點，規格是 2～4 點：增刪 points，細節移到 note。'), warnings.join('\n'));
  assert.ok(warnings.includes('第 2 頁 points 是 5 點，規格是 2～4 點：增刪 points，細節移到 note。'), warnings.join('\n'));
  assert.ok(!warnings.some((w) => /第 3 頁 points\[0\]/.test(w)), warnings.join('\n'));
  assert.ok(warnings.some((w) => /^第 3 頁 points\[1\]：估算 3 行，上限 2 行/.test(w)), warnings.join('\n'));
});

test('閱讀版 evidence 右欄空白時警告；簡報版不警告', async () => {
  const blank = '第 1 頁右欄空白：閱讀版的 evidence 要有 takeaway 或 points。';
  assert.ok(readBuild([evidence({})]).includes(blank));
  assert.ok(readBuild([evidence({ metric: { label: '甲', value: 12, unit: '件' } })]).includes(blank));
  assert.ok(!readBuild([evidence({ takeaway: '甲最多。' })]).includes(blank));
  assert.ok(!(await build({ pages: [evidence({})] })).warnings.some((w) => /右欄空白/.test(w)));
});

test('閱讀版 columns 每欄正文 6 行不警告、7 行警告；takeaway 顯示在欄下方 10 pt', async () => {
  // Two columns are 836 px wide: 36 characters a line at 22 px.
  const columns = (body, takeaway) => ({ type: 'columns', claim: '兩個方向', sources, takeaway,
    visual: { items: [{ heading: '甲', body }, { heading: '乙', body: '短' }] } });
  assert.ok(!readBuild([columns('文'.repeat(36 * 6))]).some((w) => /body：估算/.test(w)));
  assert.ok(readBuild([columns('文'.repeat(36 * 6 + 1))]).some((w) => /^第 1 頁 visual\.items\[0\]\.body：估算 7 行，上限 6 行/.test(w)));
  const page = columns('文'.repeat(36 * 3), '兩個方向都要做，先做甲。');
  const { boxes: [boxes] } = await slides([page]);
  const takeaway = boxes.find((s) => s.text === page.takeaway), body = boxes.find((s) => s.text === page.visual.items[0].body);
  assert.deepEqual([...new Set(takeaway.sizes)], [1000]);
  assert.ok(takeaway.y > body.y + 3 * 22 * 1.45 - 1, `takeaway y ${takeaway.y} 在正文 ${body.y} 下方`);
});

test('footnotes 自動編號、8 pt，置於來源行上方', async () => {
  const page = evidence({ takeaway: '甲最多(1)。', points: ['甲 12 件(2)。', '乙 8 件。'], footnotes: ['只計已結案件。', '含轉介案件。'] });
  const { boxes: [boxes] } = await slides([page]);
  const notes = ['(1) 只計已結案件。', '(2) 含轉介案件。'].map((t) => boxes.find((s) => s.text === t));
  for (const s of notes) assert.deepEqual([...new Set(s.sizes)], [800], JSON.stringify(s));
  const source = boxes.find((s) => s.text === `資料來源：${sources.source}`);
  assert.ok(notes[0].y < notes[1].y && notes[1].y < source.y, `${notes.map((s) => s.y)} < ${source.y}`);
  const lowest = Math.max(...boxes.filter((s) => s.text === page.points[1]).map((s) => s.y));
  assert.ok(lowest < notes[0].y, '右欄內容在註腳上方');
});

test('簡報版用到 takeaway、points 或 footnotes 時驗收失敗，說明只有閱讀版支援', () => {
  for (const extra of [{ takeaway: '甲最多。' }, { points: ['一', '二'] }, { footnotes: ['註'] }]) {
    assert.throws(() => validateStory({ pages: [evidence(extra)] }), /第 1 頁：.*只有閱讀版支援/);
  }
  assert.throws(() => validateStory({ pages: [{ type: 'columns', claim: '並列', sources, takeaway: '甲', visual: { items: [{ heading: '甲' }, { heading: '乙' }] } }] }), /只有閱讀版支援/);
  assert.doesNotThrow(() => validateStory({ mode: 'read', pages: [evidence({ takeaway: '甲', points: ['一', '二'], footnotes: ['註'] })] }));
});

test('驗收器：takeaway、points、footnotes 的數字要有原稿依據；「(N)」在 N 不超過註腳數時才剔除', () => {
  const script = '甲 12 件，乙 8 件。';
  const page = (extra) => evidence({ points: ['甲 12 件。', '乙 8 件。'], footnotes: ['只計已結案件。', '含轉介案件。'], ...extra });
  const ok = readCheck([page({ takeaway: '甲 12 件(2)，最多(1)。', note: '乙 8 件(2)。' })], script);
  assert.equal(ok.error, undefined);
  assert.ok(!ok.warnings.some((w) => /右欄空白|沒有講者/.test(w)), ok.warnings.join('\n'));
  assert.match(readCheck([page({ note: '見(5)。' })], script).error, /第 1 頁 note：原稿找不到數字 5/);
  assert.match(readCheck([page({ takeaway: '甲 30 件。' })], script).error, /第 1 頁 takeaway：原稿找不到數字 30/);
  assert.match(readCheck([page({ points: ['甲 12 件。', '丙 7 件。'] })], script).error, /第 1 頁 points\[1\]：原稿找不到數字 7/);
  assert.match(readCheck([page({ footnotes: ['只計已結案件。', '轉介 3 件。'] })], script).error, /第 1 頁 footnotes\[1\]：原稿找不到數字 3/);
  // A marker in the claim is not a number the page must show.
  const claim = readCheck([page({ claim: '甲 12 件領先(1)' })], script);
  assert.ok(!claim.warnings.some((w) => /claim：數字 1 /.test(w)), claim.warnings.join('\n'));
});

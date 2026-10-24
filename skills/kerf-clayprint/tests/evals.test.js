import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { check } from '../evals/check.mjs';
import { build } from '../scripts/pptx.js';

const sources = { source: '虛構測試文字稿' };
const story = (visual, extra = {}) => ({ title: '驗收測試', pages: [{
  type: 'evidence', claim: '甲的需求較高', sources, visual, ...extra,
}] });
const rank = (value) => ({ kind: 'rank', rows: [{ label: '甲', value }] });
const example = JSON.parse(readFileSync(new URL('../examples/story.json', import.meta.url), 'utf8'));
const script = readFileSync(new URL('../evals/fixtures/example-script.md', import.meta.url), 'utf8');

test('claim numbers absent from the page warn, while visible numbers and percent aliases pass', async () => {
  const manuscript = '甲 12 件，乙 8 件，比例 32%，另有 20 件。';
  for (const extra of [{}, { notes: '口頭補充 20 件。' }, { sources: { ...sources, more: ['合計 20 件'] } }]) {
    const { warnings } = await check(story(rank(12), { ...extra, claim: '共有 20 件' }), manuscript);
    assert.ok(warnings.some((w) => /第 1 頁 claim.*20.*畫面/.test(w)));
  }
  for (const extra of [{ metric: { value: 20 } }, { lede: '共有 20 件' }, { note: '共有 20 件' }]) {
    assert.ok(!(await check(story(rank(12), { ...extra, claim: '共有 20 件' }), manuscript)).warnings.some((w) => /claim/.test(w)));
  }
  for (const [claim, value] of [['比例 32%', 0.32], ['比例 0.32', '32%']]) {
    const { warnings } = await check(story({ items: [{ label: '比例', value }, { label: '件數', value: 12 }] }, { type: 'numbers', claim }), manuscript);
    assert.ok(!warnings.some((w) => /claim/.test(w)));
  }
});

test('claim drop counts match funnel loss labels only when enabled; conversions also count', async () => {
  const visual = { kind: 'funnel', steps: [{ label: '開始', value: 2400 }, { label: '送出', value: 1800 }, { label: '確認', value: 1260 }] };
  const extra = { claim: '600 人未送出、540 人未確認', notes: '計算：2400 - 1800 = 600\r\n算法：1800 - 1260 = 540' };
  const manuscript = '開始 2400 人，送出 1800 人，確認 1260 人，轉換率 70%。';
  assert.equal((await check(story(visual, extra), manuscript)).warnings.filter((w) => /claim/.test(w)).length, 2);
  assert.ok(!(await check(story({ ...visual, loss: true }, extra), manuscript)).warnings.some((w) => /claim/.test(w)));
  assert.ok(!(await check(story(visual, { claim: '確認轉換率 70%' }), manuscript)).warnings.some((w) => /claim/.test(w)));
});

test('claim matching includes rendered share percentages and excludes unused page fields', async () => {
  const manuscript = '甲 600 件，乙 400 件；甲占 60%，待完成 20 件。';
  const share = story({ kind: 'share', categories: ['甲', '乙'], rows: [{ label: '本期', values: [600, 400] }] }, { claim: '甲占 60%', notes: '說明本期組成比例。' });
  assert.ok(!(await check(share, manuscript)).warnings.some((w) => /claim/.test(w)));
  const visual = { steps: [{ heading: '收件' }, { heading: '交接' }, { heading: '完成' }] };
  for (const extra of [{ metric: { value: 20 } }, { note: '20 件' }, { body: '20 件' }, { visual: { ...visual, source: '20 件' } }]) {
    const input = story(visual, { type: 'process', claim: '待完成 20 件', notes: '說明流程。', ...extra });
    assert.ok((await check(input, manuscript)).warnings.some((w) => /claim.*20/.test(w)), JSON.stringify(extra));
  }
});

test('claim matching includes displayed number-tile deltas, but not unused column deltas', async () => {
  for (const type of ['numbers', 'summary']) {
    for (const [claim, value, prev] of [['增加 4 件', 12, 8], ['減少 4 件', 8, 12], ['增加 50%', 12, 8]]) {
      const visual = { items: [{ label: '甲', value, prev, better: 'higher', mode: claim.includes('%') ? 'pct' : 'abs' }, { label: '乙', value: 8 }] };
      if (type === 'summary') visual.lead = '先確認結果';
      assert.ok(!(await check(story(visual, { type, claim, notes: '說明前後變化。' }), '甲 12 件，前期 8 件，差額 4 件，成長 50%。')).warnings.some((w) => /claim/.test(w)), type + claim);
    }
  }
  const visual = { items: [{ heading: '甲', value: 12, prev: 8, better: 'higher' }, { heading: '乙', value: 8 }] };
  assert.ok((await check(story(visual, { type: 'columns', claim: '增加 4 件', notes: '說明前後變化。' }), '甲 12 件，前期 8 件，差額 4 件。')).warnings.some((w) => /claim.*4/.test(w)));
});

test('claim matching shares the renderer category order when later categories fold', async () => {
  const input = { pages: [
    { type: 'evidence', claim: '首批類別', sources, notes: '說明首批類別。', visual: { kind: 'share', categories: ['甲', '乙', '丙', '丁'], rows: [{ label: '首批', values: [1, 1, 1, 1] }] } },
    { type: 'evidence', claim: '其他占 100%', sources, notes: '說明合併後的類別。', visual: { kind: 'share', categories: ['戊', '己'], rows: [{ label: '次批', values: [600, 400] }] } },
  ] };
  const manuscript = '首批甲乙丙丁各 1。次批戊 600、己 400，分別占 60% 與 40%，合併為其他占 100%。';
  assert.ok(!(await check(input, manuscript)).warnings.some((w) => /claim/.test(w)));
  input.pages[1].claim = '戊占 60%';
  assert.ok((await check(input, manuscript)).warnings.some((w) => /第 2 頁 claim.*60%/.test(w)));
});

test('calculation and speaker lines accept LF, CRLF, and CR consistently', async () => {
  for (const eol of ['\n', '\r\n', '\r']) {
    const notes = ['計算：12 + 8 = 20', '算法：12 - 8 = 4', '先說明合計，再交代資料範圍。'].join(eol);
    const result = await check(story(rank(20), { claim: '共 20 件', notes }), '甲 12 件，乙 8 件。');
    assert.deepEqual(result.warnings, []);
  }
});

test('wrapping warnings retain original JSON indices after empty cells are omitted', async () => {
  const text = '甲\r\n乙\r\n丙\r\n丁';
  const cases = [
    ['summary', { lead: '先確認', items: [{}, { label: '甲', value: 12, note: text }, { label: '乙', value: 8 }] }, 'visual.items[1].note'],
    ['compare', { rows: ['條件'], options: [{}, { name: '甲', subtitle: text, values: ['符合'] }, { name: '乙', values: ['符合'] }] }, 'visual.options[1].subtitle'],
    ['close', { rows: [{}, { task: '確認', due: text }] }, 'visual.rows[1].due'],
    ['kpi', { main: { label: '耗時', value: 12, benchmarks: [{}, { label: text, value: 8 }] } }, 'visual.main.benchmarks[1].label'],
    ['steps', { start: '2026-01', end: '2026-12', phases: [{}, { name: '甲', note: text, from: '2026-01', to: '2026-12' }] }, 'visual.phases[1].note'],
  ];
  const { warnings } = await check({ pages: cases.map(([type, visual]) => ({ type, claim: '依原稿確認', visual, sources, notes: '說明已知內容。' })) }, '甲 12 件，乙 8 件。2026-01 至 2026-12。');
  for (const [i, [, , field]] of cases.entries()) assert.ok(warnings.some((w) => w.includes(`第 ${i + 1} 頁`) && w.includes(field)), field);
});

test('non-cover pages need speaker prose beyond calculation lines, including CRLF notes', async () => {
  for (const notes of [undefined, '', [], [' ', '\t'], '計算：12 + 8 = 20', ['算法：12 + 8 = 20'], '計算：12 + 8 = 20\r\n算法：12 - 8 = 4']) {
    const { warnings } = await check(story(rank(12), { notes }), '甲 12 件，乙 8 件。');
    assert.ok(warnings.some((w) => /第 1 頁 notes.*講稿/.test(w)), JSON.stringify(notes));
  }
  for (const notes of ['先說明甲的需求，再交代資料限制。', '計算：12 + 8 = 20\r\n先說明甲的需求。', ['計算：12 + 8 = 20', '目前只能判斷需求量。']]) {
    assert.ok(!(await check(story(rank(12), { notes }), '甲 12 件，乙 8 件。')).warnings.some((w) => /notes/.test(w)));
  }
  assert.ok(!(await check({ pages: [{ type: 'cover', claim: '封面', sources }] }, '原稿')).warnings.some((w) => /notes/.test(w)));
});

test('wrap warnings name the field, measured lines, and limit, and diagnose CJK orphans', async () => {
  const make = (type, visual) => ({ type, claim: '依原稿確認', visual, sources, notes: '說明已知內容；其餘留待確認。' });
  const summary = (body) => make('summary', { lead: '先確認需求', body, items: [{ label: '甲', value: 12 }, { label: '乙', value: 8 }] });
  const input = { pages: [
    summary('甲\r\n乙\r\n丙\r\n丁'),
    summary('甲'.repeat(21)),
    make('process', { steps: [{ heading: '甲'.repeat(15), body: '乙'.repeat(14) }, { heading: '交接' }, { heading: '完成' }] }),
    make('close', { rows: [{ task: '確認', owner: '甲'.repeat(13), due: '乙'.repeat(8) }] }),
    make('close', { rows: [{ task: '確認', due: '甲\r\n乙\r\n丙\r\n丁' }] }),
  ] };
  const { warnings } = await check(input, '甲 12 件，乙 8 件。依原稿確認需求。');
  assert.ok(warnings.some((w) => /第 1 頁.*visual\.body.*4 行.*上限 3 行/.test(w)));
  assert.ok(warnings.some((w) => /第 5 頁.*visual\.rows\[0\]\.due.*4 行.*上限 3 行/.test(w)));
  for (const [page, field] of [[2, 'visual.body'], [3, 'visual.steps[0].heading'], [3, 'visual.steps[0].body'], [4, 'visual.rows[0].owner'], [4, 'visual.rows[0].due']]) {
    assert.ok(warnings.some((w) => w.includes(`第 ${page} 頁`) && w.includes(field) && /2 行.*上限 \d+ 行.*末行.*1 個中文字/.test(w)), `${page} ${field}`);
  }
  const clean = await check({ pages: [summary('甲'.repeat(25)), make('close', { rows: [{ task: '確認', due: '乙'.repeat(9) }] })] }, '甲 12 件，乙 8 件。');
  assert.ok(!clean.warnings.some((w) => w.includes('末行')));
});

test('other wrapping layouts also locate overflowing fields and report line limits', async () => {
  const long = Array(30).fill('詳細內容').join('\r\n');
  const cases = [
    ['list', { items: [{ heading: '甲', body: '甲\r\n乙' }, { heading: '乙' }, { heading: '丙' }] }, 'visual.items[0].body'],
    ['columns', { items: [{ heading: '甲', body: long }, { heading: '乙' }] }, 'visual.items[0].body'],
    ['flow', { nodes: [{ heading: '甲', body: long }, { heading: '乙' }] }, 'visual.nodes[0].body'],
    ['compare', { rows: ['條件'], options: [{ name: '甲', subtitle: '甲\r\n乙', values: ['符合'] }, { name: '乙', values: ['符合'] }] }, 'visual.options[0].subtitle'],
    ['kpi', { main: { label: '耗時', value: 12, benchmarks: [{ label: '甲\r\n乙', value: 8 }] } }, 'visual.main.benchmarks[0].label'],
    ['steps', { start: '2026-01', end: '2026-12', phases: [{ name: '甲', note: '甲\r\n乙', from: '2026-01', to: '2026-12' }] }, 'visual.phases[0].note'],
    ['evidence', { kind: 'table', columns: [{ name: '項目', type: 'text' }], rows: [[long]] }, 'visual.rows[0][0]'],
  ];
  const { warnings } = await check({ pages: cases.map(([type, visual]) => ({ type, claim: '依原稿確認', visual, sources, notes: '說明已知內容。' })) }, '甲 12 件，乙 8 件。2026-01 至 2026-12。');
  for (const [i, [, , field]] of cases.entries()) assert.ok(warnings.some((w) => w.includes(`第 ${i + 1} 頁`) && w.includes(field) && /估算 \d+ 行，上限 \d+ 行/.test(w)), field);
});

test('範例通過驗收並建出九頁，封面後為主管摘要', async () => {
  const result = await check(example, script);
  assert.equal(result.pages, 9);
  assert.equal(example.pages[1].type, 'summary');
  assert.deepEqual(result.warnings, []);
  const zip = await JSZip.loadAsync(result.buffer);
  assert.equal(Object.keys(zip.files).filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f)).length, 9);
});

test('CLI 對範例回報通過', () => {
  const run = spawnSync(process.execPath, ['evals/check.mjs', 'examples/story.json', 'evals/fixtures/example-script.md'], { encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /通過：9 頁/);
});

test('主管摘要的建議、說明、數字與項目說明皆須有原稿依據', async () => {
  const visual = {
    lead: '優先改善交接', body: '甲有 12 件，乙有 8 件。',
    items: [{ label: '甲', value: 12, unit: '件', note: '已完成 12 件' }, { label: '乙', value: 8, unit: '件' }],
  };
  const manuscript = '甲有 12 件，乙有 8 件。';
  await check(story(visual, { type: 'summary' }), manuscript);
  for (const field of ['lead', 'body']) {
    await assert.rejects(check(story({ ...visual, [field]: '共有 999 件' }, { type: 'summary' }), manuscript), new RegExp(`visual\\.${field}.*999`));
  }
  for (const field of ['value', 'note']) {
    const items = [{ ...visual.items[0], [field]: field === 'value' ? 999 : '共有 999 件' }, visual.items[1]];
    await assert.rejects(check(story({ ...visual, items }, { type: 'summary' }), manuscript), new RegExp(`visual\\.items\\[0\\]\\.${field}.*999`));
  }
});

test('缺 claim、來源或不合法的 visual 都有頁碼與修法', async () => {
  for (const [input, message] of [
    [null, /story/],
    [{ pages: [] }, /pages/],
    [story(rank(12), { claim: ' ' }), /第 1 頁.*claim/],
    [story(rank(12), { sources: {} }), /第 1 頁.*sources.source/],
    [story(rank(12), { type: 'typo' }), /第 1 頁.*type/],
    [story({ kind: 'rank', rows: '錯誤' }), /第 1 頁.*visual/],
  ]) await assert.rejects(check(input, '甲有 12 件。'), message);
});

test('visual 的巢狀數字與數字字串須有原稿依據', async () => {
  await assert.rejects(check(story(rank(99)), '甲有 12 件。'), /visual.rows\[0\].value.*99/);
  await assert.rejects(check(story({ items: [{ label: '甲', value: 'NT$ 9,999' }] }, { type: 'numbers' }), '甲有 12 件。'), /visual.items\[0\].value.*9,999/);
  await assert.rejects(check(story({ kind: 'line', x: ['前期', '本期'], series: [{ name: '甲', values: [12, 99] }] }), '甲有 12 件。'), /visual.series\[0\].values\[1\]/);
  await assert.rejects(check(story(rank(0)), '甲有 10 件。'), /value.*0/);
  await assert.rejects(check(story(rank(1e-101)), '甲有 0 件。'), /value/);
  await assert.rejects(check(story(rank(-12)), '甲有 12 件。'), /value/);
});

test('十種新圖的數字欄位都須回到原稿', async () => {
  const edits = {
    grouped: (v) => { v.series[0].values[0] = 999; },
    sharetrend: (v) => { v.rows[0].values[0] = 999; },
    combo: (v) => { v.amounts[0] = 999; },
    bullet: (v) => { v.rows[0].target = 999; },
    waffle: (v) => { v.values[0] = 999; },
    mekko: (v) => { v.rows[0].values[0] = 999; },
    pareto: (v) => { v.rows[0].value = 999; },
    tornado: (v) => { v.baseline = 999; },
    box: (v) => { v.groups[0].values[0] = 999; },
    ordered: (v) => { v.rows[0].value = 999; },
  };
  for (const [kind, edit] of Object.entries(edits)) {
    const original = JSON.parse(readFileSync(new URL(`../examples/${kind}.json`, import.meta.url), 'utf8'));
    const changed = structuredClone(original);
    edit(changed);
    await assert.rejects(check(story(changed), JSON.stringify(original)), /visual\..*999/, kind);
  }
  const pareto = JSON.parse(readFileSync(new URL('../examples/pareto.json', import.meta.url), 'utf8'));
  pareto.threshold = 0.7;
  await assert.rejects(check(story(pareto), JSON.stringify({ ...pareto, threshold: 0.8 })), /visual\.threshold.*0\.7/);
});

test('每個畫面文字欄位的數字都須有原稿依據', async () => {
  for (const field of ['claim', 'kicker', 'note']) {
    await assert.rejects(check(story(rank(12), { [field]: '共有 999 件' }), '甲有 12 件。'), new RegExp(`第 1 頁 ${field}.*999`));
  }
  for (const field of ['value', 'label', 'unit']) {
    const metric = { value: 12, label: '數量', unit: '件', [field]: field === 'value' ? 999 : '共 999 件' };
    await assert.rejects(check(story(rank(12), { metric }), '甲有 12 件。'), new RegExp(`第 1 頁 metric\\.${field}.*999`));
  }
  for (const field of ['title', 'date']) {
    await assert.rejects(check({ ...story(rank(12)), [field]: '2029 年' }, '甲有 12 件。'), new RegExp(`根層 ${field}.*2029`));
  }
});

test('畫面文字可用原稿數字與同頁合法加減結果，講稿本身不當成數字來源', async () => {
  const input = story(rank(12), {
    claim: '合計 20 件', kicker: '合計 20 件', note: '合計 20 件',
    metric: { value: 20, label: '共 20 件', unit: '20 件' },
    notes: '計算：12 + 8 = 20',
  });
  await check({ ...input, title: '2026 年需求', date: '2026 年' }, '2026 年甲有 12 件、乙有 8 件。');
  await check(story(rank(12), { metric: { value: 20 }, sources: { ...sources, more: ['算法：12 + 8 = 20'] } }), '甲有 12 件、乙有 8 件。');
  await assert.rejects(check(story(rank(12), { metric: { value: 999 }, notes: '共有 999 件' }), '甲有 12 件。'), /metric\.value.*999/);
  await assert.rejects(check(story(rank(12), { claim: '共有 999 件', sources: { ...sources, more: ['共有 999 件'] } }), '甲有 12 件。'), /claim.*999/);
  const otherPage = story(rank(12), { metric: { value: 20 } });
  otherPage.pages.push({ type: 'statement', claim: '另一頁說明', sources, notes: '計算：12 + 8 = 20' });
  await assert.rejects(check(otherPage, '甲有 12 件、乙有 8 件。'), /第 1 頁 metric\.value.*20/);
  await assert.rejects(check({ ...input, title: '合計 20 件' }, '甲有 12 件、乙有 8 件。'), /根層 title.*20/);
});

test('圖表自動計算比例可通過，畫面填入比例仍須可核對', async () => {
  const input = story({ kind: 'funnel', steps: [{ label: '送出', value: 1800 }, { label: '確認', value: 1260 }] });
  await check(input, '送出 1,800 人、確認 1,260 人。');
  input.pages[0].metric = { value: '70%', label: '轉換率' };
  input.pages[0].notes = '轉換率以完成確認人數除以送出人數，即 1,260 除以 1,800。';
  await assert.rejects(check(input, '送出 1,800 人、確認 1,260 人。'), /metric\.value.*70%/);
  await check(input, '送出 1,800 人、確認 1,260 人，轉換率 70%。');
  input.pages[0].notes = '計算：1260 / 1800 = 70%';
  await assert.rejects(check(input, '送出 1,800 人、確認 1,260 人。'), /算式.*加減/);
});

test('千分位、全形、百分比與小數比例可對照，digits 不當成資料', async () => {
  for (const [value, source] of [[1200, '１，２００'], [0.32, '32 %'], [32, '３２％'], [-12, '−12']]) {
    await check(story({ ...rank(value), digits: 2 }), `甲：${source}。`);
  }
  await check(story({ items: [{ label: '甲', value: '32%' }] }, { type: 'numbers' }), '甲的比例為 0.32。');
  await check(story({ kind: 'rank', rows: [{ label: '甲', value: 0 }, { label: '乙', value: null }] }), '甲有 0 件；乙未提供。');
});

test('省略整數部的小數仍要查證，百分比不接受百倍差異', async () => {
  for (const value of ['.999', '-.5', '1e999', '1e-999']) {
    await assert.rejects(check(story({ items: [{ label: '甲', value }] }, { type: 'numbers' }), '原稿只有文字，沒有數據。'), /visual.items\[0\].value/);
  }
  await check(story(rank(0.5)), '甲為 .5。');
  await assert.rejects(check(story({ items: [{ label: '甲', value: '100%' }] }, { type: 'numbers' }), '甲的比例為 1%。'), /value.*100%/);
  await assert.rejects(check(story({ items: [{ label: '甲', value: '1%' }] }, { type: 'numbers' }), '甲的比例為 100%。'), /value.*1%/);
  await assert.rejects(check(story(rank(0)), '甲為 1e-999。'), /原稿.*數字|表示/);
});

test('合計與差額須有當頁算式且運算元可回到原稿', async () => {
  await check(story(rank(2000), { notes: '合計，計算：1,200 + 800 = 2,000' }), '甲 1,200，乙 800。');
  await check(story(rank(-400), { sources: { ...sources, more: ['差額，計算：800 − 1,200 = −400'] } }), '甲 1,200，乙 800。');
  await check(story(rank(0.3), { notes: ['計算：0.1 + 0.2 = 0.3'] }), '甲 0.1，乙 0.2。');
  await assert.rejects(check(story(rank(2000), { notes: '這是計算所得的 2,000。' }), '甲 1,200，乙 800。'), /找不到.*2,000|2000/);
  await assert.rejects(check(story(rank(2000), { notes: '計算：1,200 + 800 = 2,100' }), '甲 1,200，乙 800。'), /算式.*不符/);
  await assert.rejects(check(story(rank(2000), { notes: '計算：1,999 + 1 = 2,000' }), '甲 1,200，乙 800。'), /算式.*原稿/);
  const input = story(rank(2000));
  input.pages.push({ type: 'statement', claim: '備註在其他頁', sources, notes: '計算：1,200 + 800 = 2,000' });
  await assert.rejects(check(input, '甲 1,200，乙 800。'), /第 1 頁/);
});

test('算式驗完整左式，不從不支援的運算截取尾段', async () => {
  await assert.rejects(check(story(rank(1), { notes: '計算：10 + -2 + 3 = 1' }), '甲10；乙-2；丙3。'), /算式.*不符/);
  await assert.rejects(check(story(rank(5), { notes: '計算：10 × 2 + 3 = 5' }), '甲10；乙2；丙3。'), /算式.*加減/);
  await check(story(rank(17), { notes: '計算：5 - -12 = 17' }), '甲5；乙-12。');
  await check(story(rank(0.0003), { notes: '計算：1e-4 + 2e-4 = 3e-4' }), '甲1e-4；乙2e-4。');
  await check(story(rank(25), { notes: '計算：30% - 5% = 25%' }), '甲30%；乙5%。');
});

test('無數字稿允許文字版型與文字表格，拒絕量化圖表', async () => {
  const script = '先確認需求，再交接處理；服務窗口接收，承辦單位追蹤。';
  const input = { title: '交接流程', pages: [
    { type: 'statement', claim: '先確認需求，再交接處理', sources },
    { type: 'close', claim: '服務窗口接收後交承辦追蹤', sources, visual: { rows: [{ task: '確認需求', owner: '服務窗口', due: '交接前' }] } },
  ] };
  await check(input, script);
  await check(story({ kind: 'table', columns: [{ name: '工作' }], rows: [['確認需求']] }), script);
  await assert.rejects(check(story(rank(12), { notes: '計算：6 + 6 = 12' }), script), /沒有.*數字.*圖表/);
  await assert.rejects(check(story({ kind: 'matrix', points: [{ label: '甲', x: 1, y: 2 }] }), script), /沒有.*數字.*圖表/);
});

test('警告照常通過、保留訊息供看圖判斷', async () => {
  const { warnings } = await check(story({ ...rank(12), focus: '不存在' }), '甲 12 件。');
  assert.ok(warnings.some((w) => w.includes('focus')));
});

const singlePage = (extra = {}) => ({ pages: [{ type: 'statement', claim: '稿', sources: { source: '稿' }, ...extra }] });

test('算式拒絕非有限運算元、累加和與結果', async () => {
  for (const notes of [
    '計算:1e308+1e308=999',
    '計算:1e308+1e308-1e308=999',
    '計算:1e999=999',
    '計算:1e308=1e999',
  ]) {
    await assert.rejects(check(singlePage({ claim: '999', notes }), '1e308'), /第 1 頁.*算式.*有限數字/);
  }
  await check(singlePage({ claim: '1e308', notes: '計算:1e308=1e308' }), '1e308');
});

test('百分比運算保留原稿單位，拒絕裸數洗值與漏寫百分號', async () => {
  await assert.rejects(check(singlePage({ claim: '3200%', notes: '計算:32=3200%' }), '32%'), /算式.*不符/);
  await check(singlePage({ claim: '40%', notes: '計算：32% + 8% = 40%' }), '32%；8%');
  await check(singlePage({ claim: '40%', notes: '計算：32 + 8 = 40%' }), '32%；8%');
  await check(singlePage({ claim: '40%', notes: '計算：0.32 + 0.08 = 40%' }), '32%；8%');
  await check(singlePage({ claim: '40%', notes: '計算：32% + 8% = 40%' }), '0.32；0.08');
  await assert.rejects(check(singlePage({ notes: '計算：32% + 8% = 40' }), '32%；8%'), /算式.*不符/);
  await assert.rejects(check(singlePage({ notes: '計算：32 + 8 = 40' }), '32%；8%'), /算式.*不符/);
});

test('來源列的 source、unit、more 都核對，合法算式仍可顯示', async () => {
  for (const field of ['more', 'source', 'unit']) {
    const sources = { source: '稿', [field]: field === 'more' ? ['999'] : '999' };
    await assert.rejects(check(singlePage({ sources }), '待查'), new RegExp(`sources\\.${field}.*999`));
  }
  await check(singlePage({ sources: { source: '稿', more: ['計算：12 + 8 = 20'] } }), '12；8');
  await assert.rejects(check(singlePage({ sources: { source: '稿', more: ['計算：12 + 8 = 21'] } }), '12；8'), /算式.*不符/);
});

test('來源列合法算式的減號不是原稿負數，式外文字仍須核對', async () => {
  await check(singlePage({ sources: { source: '稿', more: ['計算：800-1200=-400'] } }), '800；1200');
  await check(singlePage({ sources: { source: '稿', more: ['計算：5--12=17'] } }), '5；-12');
  await check(singlePage({ sources: { source: '稿', more: ['計算：12 -8 = 4'] } }), '12；8');
  await check(singlePage({ sources: { source: '稿', more: ['計算：12 - - 8 = 20'] } }), '12；-8');
  await check(singlePage({ sources: { source: '稿', more: ['計算：8 - 12 = - 4'] } }), '12；8');
  await check(singlePage({ sources: { source: '稿', more: ['計算：32% -8% = 24%'] } }), '32%；8%');
  await assert.rejects(check(singlePage({ sources: { source: '稿', more: ['計算：800-1200=-400；999'] } }), '800；1200'), /sources\.more\[0\].*999/);
  await assert.rejects(check(singlePage({ claim: '-8', sources: { source: '稿', more: ['計算：12 -8 = 4'] } }), '12；8'), /claim.*-8/);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, globSync } from 'node:fs';
import { T, C, contrast } from '../scripts/core.js';
import { render, framed } from '../scripts/svg.js';

const examples = globSync('examples/*.json').map((f) => [f, JSON.parse(readFileSync(f, 'utf8'))]).filter(([, spec]) => spec.kind);
const count = (svg, re) => (svg.match(re) ?? []).length;

// ---- lessons, one chart at a time

test('rank: 0 is drawn and labeled, null is listed as missing', () => {
  const spec = { kind: 'rank', rows: [{ label: 'A', value: 5 }, { label: 'B', value: null }, { label: 'C', value: 0 }] };
  const { svg, model } = render(spec);
  assert.equal(model.rows[1].text, '0');
  assert.equal(count(svg, />0<\/text>/g), 2, 'the zero bar label plus the axis tick 0');
  assert.deepEqual(model.rows.map((r) => r.label), ['A', 'C']);
  assert.deepEqual(model.missing, ['B']);
  assert.ok(!svg.includes('>B</text>'), 'missing row is not drawn');
  assert.ok(framed(spec).svg.includes('未提供：B'), 'missing value reaches the source row');
});

test('axis ticks keep decimals instead of printing <1', () => {
  const { svg } = render({ kind: 'line', digits: 1, x: ['a', 'b', 'c'], series: [{ name: 'S', values: [0.1, 0.2, 0.3] }] });
  for (const t of ['0.1', '0.2', '0.3']) assert.ok(svg.includes(`>${t}</text>`), t);
  assert.ok(!svg.includes('&lt;1'));
});

test('no values at all is an error, an all-zero share row is kept with a warning', () => {
  assert.throws(() => render({ kind: 'rank', rows: [{ label: 'A', value: null }] }));
  assert.throws(() => render({ kind: 'line', x: ['a', 'b'], series: [{ name: 'S', values: [null, null] }] }));
  const { model } = render({ kind: 'share', categories: ['甲', '乙'], rows: [{ label: 'X', values: [1, 1] }, { label: 'Y', values: [0, 0] }] });
  assert.equal(model.rows.length, 2);
  assert.ok(model.warnings.some((w) => w.includes('「Y」')));
});

test('a flat line gets no peak label', () => {
  const { model } = render({ kind: 'line', x: ['a', 'b', 'c'], series: [{ name: 'S', values: [5, 5, 5] }] });
  assert.equal(model.series[0].peak, -1);
});

test('labels outside the chart area become warnings', () => {
  const { model } = render({ kind: 'rank', rows: [{ label: '一個長到放不進三百像素寬圖表區的站名', value: 5 }] }, { width: 300, height: 200 });
  assert.ok(model.warnings.some((w) => w.includes('超出圖表區')));
});

test('rank: bars start at 0 even when data sits far from it', () => {
  const { model } = render({ kind: 'rank', rows: [{ label: 'A', value: 900 }, { label: 'B', value: 600 }] });
  assert.equal(model.axis.ticks[0], 0);
});

test('rank: exactly one focus bar, the rest gray', () => {
  const { svg } = render(JSON.parse(readFileSync('examples/rank.json', 'utf8')));
  assert.equal(count(svg, new RegExp(`<rect[^>]*fill="${C.focus}"`, 'g')), 1);
  assert.equal(count(svg, new RegExp(`<rect[^>]*fill="${C.gray}"`, 'g')), 7);
});

test('rank and funnel accept multiple named focuses and warn for each missing name', () => {
  for (const kind of ['rank', 'funnel']) {
    const data = [{ label: '甲', value: 2400 }, { label: '乙', value: 1800 }, { label: '丙', value: 1260 }];
    const { model } = render({ kind, [kind === 'rank' ? 'rows' : 'steps']: data, focus: ['乙', '丙', '缺項'] });
    const rows = model.rows ?? model.steps;
    assert.deepEqual(rows.filter((r) => r.focus).map((r) => r.label).sort(), ['丙', '乙']);
    assert.equal(rows.find((r) => r.label === '甲').color, C.gray);
    assert.ok(model.warnings.some((w) => w.includes('focus「缺項」')));
    assert.throws(() => render({ kind, [kind === 'rank' ? 'rows' : 'steps']: data, focus: [1] }), /focus/);
  }
});

test('funnel loss labels show drops, preserve zero, and omit unknown transitions', () => {
  const steps = [{ label: '開始', value: 2400 }, { label: '送出', value: 1800 }, { label: '確認', value: 1260 }, { label: '持平', value: 1260 }, { label: '未知', value: null }, { label: '結束', value: 1000 }];
  const { model, svg } = render({ kind: 'funnel', steps, loss: true });
  assert.deepEqual(model.steps.map((s) => s.lossText), [null, '−600', '−540', '0', null, null]);
  assert.ok(svg.includes('流失數') && svg.includes('−600') && svg.includes('−540'));
  assert.ok(!render({ kind: 'funnel', steps }).svg.includes('−600'));
  const rising = render({ kind: 'funnel', steps: [{ label: '甲', value: 10 }, { label: '乙', value: 12 }], loss: true });
  assert.equal(rising.model.steps[1].lossText, `${T.delta.signs.increase}2`);
  assert.throws(() => render({ kind: 'funnel', steps, loss: 'true' }), /loss/);
});

test('funnel loss heading stays valid for people and other count units', () => {
  const { svg } = render({ kind: 'funnel', unit: '件', loss: true, steps: [{ label: '送件', value: 100 }, { label: '完成', value: 70 }] });
  assert.ok(svg.includes('流失數'));
  assert.ok(!svg.includes('流失人數'));
});

test('line: a missing point breaks the line and is listed', () => {
  const values = [3, 4, null, 6, 7];
  const { svg, model } = render({ kind: 'line', focus: 'A', x: ['1月', '2月', '3月', '4月', '5月'], series: [{ name: 'A', values }, { name: 'B', values: [1, 2, 3, 4, 5] }] });
  assert.equal(count(svg, new RegExp(`<path[^>]*stroke="${C.focus}"`, 'g')), 2);
  assert.deepEqual(model.missing, ['A／3月']);
});

test('slope: periods use two Ordered steps, deltas follow better', () => {
  const { svg, model } = render({ kind: 'slope', better: 'lower', periods: ['前', '後'], rows: [{ label: 'A', values: [10, 8] }, { label: 'B', values: [5, 6] }] });
  assert.deepEqual(model.colors, [C.ordered[0], C.ordered.at(-1)]);
  assert.ok(svg.includes(`fill="${C.ordered[0]}"`) && svg.includes(`fill="${C.ordered.at(-1)}"`));
  assert.deepEqual(model.rows.map((r) => r.delta), [{ text: '−2', color: C.better }, { text: `${T.delta.signs.increase}1`, color: C.worse }]);
});

test('share: categories past the 4th fold into 其他, kept by shared order', () => {
  const spec = { kind: 'share', categories: ['通勤', '購物', '休閒', '接駁', '觀光', '運動'], rows: [{ label: 'X', values: [10, 20, 30, 5, 25, 10] }] };
  const { model } = render(spec, { categoryOrder: ['通勤', '購物', '休閒', '接駁', '觀光', '運動'] });
  assert.deepEqual(model.categories.map((c) => c.name), ['通勤', '購物', '休閒', '接駁', '其他']);
  assert.equal(model.rows[0].segments.at(-1).value, 35);
  assert.ok(model.warnings.some((w) => w.includes('併入')));
});

test('share: an existing 其他 and folded categories merge into one segment', () => {
  const spec = { kind: 'share', categories: ['通勤', '購物', '休閒', '接駁', '觀光', '其他'], rows: [{ label: 'X', values: [10, 10, 10, 10, 5, 7] }] };
  const { model } = render(spec);
  assert.equal(model.categories.filter((c) => c.name === '其他').length, 1);
  assert.equal(model.rows[0].segments.find((s) => s.name === '其他').value, 12);
});

test('share: categories past the shared palette borrow free colors instead of folding', () => {
  const { model } = render({ kind: 'share', categories: ['觀光', '運動'], rows: [{ label: 'X', values: [1, 2] }] }, { categoryOrder: ['通勤', '購物', '休閒', '接駁', '觀光', '運動'] });
  assert.deepEqual(model.warnings, []);
  assert.deepEqual(model.categories.map((c) => c.other), [false, false]);
  assert.notEqual(model.categories[0].color, model.categories[1].color);
});

test('share: 其他 is hatched in SVG, other segments are solid', () => {
  const { svg } = render(JSON.parse(readFileSync('examples/share.json', 'utf8')));
  assert.ok(count(svg, new RegExp(`<line[^>]*stroke="${T.fill.other.svg.stroke}"`, 'g')) > 10);
  assert.ok(!svg.includes('<pattern'));
});

test('bridge: totals are checked, colors follow better, axis covers a dip below 0', () => {
  const steps = [{ label: '年初', value: 100, total: true }, { label: '減少', value: -300 }, { label: '年末', value: -150, total: true }];
  const { model } = render({ kind: 'bridge', steps });
  assert.ok(model.warnings.some((w) => w.includes('累計')), 'a total that disagrees with the running sum warns');
  assert.ok(model.axis.lo <= -200);
  assert.equal(model.steps[1].color, C.worse);
  const lower = render({ kind: 'bridge', better: 'lower', steps: [{ label: 'A', value: 10, total: true }, { label: '降', value: -4 }, { label: 'B', value: 6, total: true }] });
  assert.equal(lower.model.steps[1].color, C.better);
  assert.deepEqual(lower.model.warnings, []);
});

test('bridge：預估值的斜線使用生效設計層的顏色', () => {
  const { svg } = render(JSON.parse(readFileSync('examples/bridge.json', 'utf8')));
  assert.ok(count(svg, new RegExp(`<line[^>]*stroke="${T.fill.estimate.svg.stroke}"[^>]*stroke-width="${T.fill.estimate.svg.width}"`, 'g')) > 10);
});

test('histogram: the tallest bin is the focus; gaps between bins warn', () => {
  const { model } = render({ kind: 'histogram', bins: [{ from: 0, to: 1, value: 3 }, { from: 1, to: 2, value: 7 }, { from: 2, to: 3, value: 7 }] });
  assert.deepEqual(model.bins.map((b) => b.focus), [false, true, false]);
  const gap = render({ kind: 'histogram', bins: [{ from: 0, to: 1, value: 3 }, { from: 2, to: 3, value: 4 }] });
  assert.ok(gap.model.warnings.some((w) => w.includes('沒有接上')));
});

test('histogram: bin edges keep their decimals; focus can be set by a bin start', () => {
  const { svg, model } = render({ kind: 'histogram', focus: 0, bins: [{ from: 0, to: 0.5, value: 3 }, { from: 0.5, to: 1, value: 7 }] });
  assert.ok(svg.includes('>0.5</text>'));
  assert.deepEqual(model.bins.map((b) => b.focus), [true, false]);
});

test('matrix: a point sitting on a split line warns', () => {
  const { model } = render({ kind: 'matrix', domain: [0, 10], points: [{ label: 'edge', x: 5, y: 2 }, { label: 'ok', x: 2, y: 8 }] });
  assert.ok(model.warnings.some((w) => w.includes('「edge」')));
});

test('strip: median lives in the model, odd and even counts', () => {
  const { model } = render({ kind: 'strip', groups: [{ label: 'A', values: [5, 1, 3] }, { label: 'B', values: [4, 1, 2, 3] }, { label: 'C', values: [null, 2] }] });
  assert.deepEqual(model.groups.map((g) => [g.median, g.medianText]), [[3, '3'], [2.5, '3'], [2, '2']]);
  assert.deepEqual(model.missing, ['C 1 筆']);
});

test('scatter: crowded labels warn instead of silently overlapping', () => {
  const pts = Array.from({ length: 12 }, (_, i) => ({ label: `站點${i}`, x: 10 + (i % 2) * 0.01, y: 10 + (i % 3) * 0.01 }));
  pts.push({ label: 'far', x: 0, y: 0 });
  const { model } = render({ kind: 'scatter', points: pts });
  assert.ok(model.warnings.some((w) => w.includes('放不下')));
});

test('matrix: points in the priority quadrant take the focus color', () => {
  const { model } = render(JSON.parse(readFileSync('examples/matrix.json', 'utf8')));
  assert.deepEqual(model.points.filter((p) => p.focus).map((p) => p.label), ['煞車調整', '車鎖故障排除', '鏈條更換']);
  assert.ok(model.points.filter((p) => !p.focus).every((p) => p.color === C.gray));
  assert.throws(() => render({ kind: 'matrix', priority: 'middle', points: [{ label: 'a', x: 1, y: 1 }] }));
});

test('dumbbell: axis from 0, delta colored by better, values sit outside their dots', () => {
  const { svg, model } = render(JSON.parse(readFileSync('examples/dumbbell.json', 'utf8')));
  assert.equal(model.axis.lo, 0);
  assert.deepEqual(model.rows[0].delta, { text: '−4.6', color: C.better });
  const after = svg.match(/<text x="([\d.]+)"[^>]*>7\.8<\/text>/), before = svg.match(/<text x="([\d.]+)"[^>]*>12\.4<\/text>/);
  assert.ok(Number(after[1]) < Number(before[1]), 'the smaller value is labeled on the left');
  assert.ok(after[0].includes('text-anchor="end"') && !before[0].includes('text-anchor'));
});

test('funnel: focus is the lowest conversion, first step and zero previous have none', () => {
  const { model } = render(JSON.parse(readFileSync('examples/funnel.json', 'utf8')));
  assert.equal(model.steps.find((s) => s.focus).label, '首次騎乘');
  assert.equal(model.steps[0].convText, null);
  const odd = render({ kind: 'funnel', steps: [{ label: 'a', value: 0 }, { label: 'b', value: 5 }, { label: 'c', value: 2 }] });
  assert.equal(odd.model.steps[1].conversion, null);
  assert.ok(odd.model.warnings.some((w) => w.includes('「b」')));
});

test('heat: must be rectangular; empty cells are listed; legend shows ranges', () => {
  assert.throws(() => render({ kind: 'heat', rowLabels: ['a', 'b'], colLabels: ['x', 'y'], values: [[1, 2], [3]] }));
  const { model } = render({ kind: 'heat', rowLabels: ['六'], colLabels: ['6–8', '8–10'], values: [[4, null]] });
  assert.deepEqual(model.missing, ['六 8–10']);
  const ex = render(JSON.parse(readFileSync('examples/heat.json', 'utf8')));
  assert.deepEqual(ex.model.legend.map((l) => l.text), ['0–2', '2–4', '4–6', '6–8', '8–10']);
});

test('table: emphasis row tinted and bold, deltas colored, total ruled, missing listed', () => {
  const { svg, model } = render(JSON.parse(readFileSync('examples/table.json', 'utf8')));
  assert.equal(model.rows[0].fill, C.tint);
  assert.ok(model.rows[0].bold);
  assert.deepEqual(model.rows[4].cells[4], { text: '−5', align: 'end', value: -5, color: C.worse });
  assert.ok(model.rows.at(-1).total);
  assert.ok(svg.includes(`font-size="${T.type.tableBody.px}"`) && svg.includes(`font-size="${T.type.tableHeader.px}"`));
  const gap = render({ kind: 'table', columns: [{ name: '區', type: 'text' }, { name: '量' }], rows: [['甲', null]] });
  assert.deepEqual(gap.model.missing, ['甲／量']);
});

for (const [label, rows, rowH, overflow] of [
  ['sparse rows stop at 1.8 times the old maximum', 2, 129.6, false],
  ['medium rows fill the available height', 6, (669 - 50.8) / 6, false],
  ['dense rows keep their old height', 10, (669 - 50.8) / 10, false],
  ['overflowing rows keep their minimum and warn', 14, 48, true],
]) {
  test(`table: ${label}`, () => {
    const { svg, model } = render({
      kind: 'table', columns: [{ name: '區', type: 'text' }, { name: '量' }],
      rows: Array.from({ length: rows }, (_, i) => [`R${i}`, i + 1]), emphasis: 'R0',
    }, { height: 669 });
    const headH = T.type.tableHeader.px * 1.45 + 16;
    const labels = [...svg.matchAll(/<text[^>]* y="([\d.]+)"[^>]*font-size="(\d+)"[^>]*>R\d+<\/text>/g)];
    assert.equal(labels.length, rows);
    labels.forEach(([, y, size], i) => {
      assert.equal(Number(size), T.type.tableBody.px, 'row growth never changes font size');
      assert.ok(Math.abs(Number(y) - (headH + rowH * (i + 0.5) + T.type.tableBody.px * 0.35)) <= 0.01);
    });
    const fill = svg.match(new RegExp(`<rect[^>]* y="([\\d.]+)"[^>]* height="([\\d.]+)" fill="${C.tint}"`));
    assert.ok(fill);
    assert.equal(Number(fill[1]), headH);
    assert.ok(Math.abs(Number(fill[2]) - rowH) <= 0.01, 'emphasis fill grows with its row');
    assert.equal(model.warnings.some((w) => w.includes('表格列數太多')), overflow);
  });
}

test('crowded heat column labels, untyped text columns, and unlabeled share segments', () => {
  const cols = Array.from({ length: 24 }, (_, i) => `${i}:00–${i + 1}:00`);
  const heat = render({ kind: 'heat', rowLabels: ['一'], colLabels: cols, values: [cols.map((_, i) => i)] });
  assert.ok(heat.model.warnings.some((w) => w.includes('欄標籤太擠')));
  const table = render({ kind: 'table', columns: [{ name: '區' }, { name: '量' }], rows: [['甲', 3], ['乙', 4]] });
  assert.equal(table.model.header[0].align, 'start', 'a column of strings is text without saying so');
  const share = render({ kind: 'share', categories: ['甲', '乙'], rows: [{ label: 'X', values: [99, 1] }] });
  assert.ok(share.model.warnings.some((w) => w.includes('X 乙')));
});

// ---- Codex adversarial review (2026-10-09): each finding reproduced before the fix

test('a value of 1e-101 draws and labels instead of crashing', () => {
  const { svg, model } = render({ kind: 'rank', rows: [{ label: 'a', value: 1e-101 }] });
  assert.equal(model.rows[0].text, '<1');
  assert.ok(svg.includes('&lt;1'));
});

test('share rejects negative values; a row with a missing category is not drawn as 100%', () => {
  assert.throws(() => render({ kind: 'share', categories: ['a', 'b'], rows: [{ label: 'x', values: [-1, 1] }] }));
  const { model } = render({ kind: 'share', categories: ['a', 'b'], rows: [{ label: 'x', values: [null, 1] }, { label: 'y', values: [1, 1] }] });
  assert.deepEqual(model.rows.map((r) => r.label), ['y']);
  assert.deepEqual(model.missing, ['x a']);
});

test('too many slope labels for the height warn instead of overlapping silently', () => {
  const rows = Array.from({ length: 21 }, (_, i) => ({ label: `R${i}`, values: [i, i + 1] }));
  for (const height of [669, 599]) {
    const { model } = render({ kind: 'slope', periods: ['a', 'b'], rows }, { height });
    assert.ok(model.warnings.some((w) => w.includes('排不下')), `height ${height}`);
  }
});

test('an all-zero funnel has finite geometry and warns', () => {
  const { svg, model } = render({ kind: 'funnel', steps: [{ label: 'a', value: 0 }, { label: 'b', value: 0 }] });
  assert.ok(!svg.includes('NaN'));
  assert.ok(model.warnings.length > 0);
});

test('render never mutates the spec', () => {
  for (const [, spec] of examples) {
    const before = structuredClone(spec);
    render(spec);
    assert.deepEqual(spec, before);
  }
});

// ---- scans over every example

const tokenColors = new Set();
(function collect(v) {
  if (typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v)) tokenColors.add(v.toUpperCase());
  else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) { collect(k); collect(x); }
})({ color: T.color, textOnFill: T.textOnFill, fill: T.fill });

for (const [file, spec] of examples) {
  test(`${file}: clean at every chart-area size`, () => {
    for (const [name, size] of Object.entries(T.chartArea)) {
      const { model } = framed(spec, size);
      assert.deepEqual(model.warnings, [], `${name} ${size.width}×${size.height}`);
    }
  });

  test(`${file}: text ≥ ${T.type.minimum}px, colors from tokens, labels on fills ≥ 4.5:1`, () => {
    const { svg } = framed(spec);
    for (const [, size] of svg.matchAll(/font-size="([\d.]+)"/g)) assert.ok(Number(size) >= T.type.minimum, `font-size ${size}`);
    for (const [hex] of svg.matchAll(/#[0-9a-f]{6}/gi)) assert.ok(tokenColors.has(hex.toUpperCase()), `${hex} is not a token color`);
    for (const [tag] of svg.matchAll(/<text[^>]*data-on="[^"]+"[^>]*>/g)) {
      const fill = tag.match(/fill="([^"]+)"/)[1], on = tag.match(/data-on="([^"]+)"/)[1];
      assert.ok(contrast(fill, on) >= 4.5, `${fill} on ${on}`);
    }
  });
}

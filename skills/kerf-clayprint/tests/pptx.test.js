import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import JSZip from 'jszip';
import { build, validateStory } from '../scripts/pptx.js';
import { T, C, SLIDE_FONT, prepare, textOn, decimalsOf, contrast } from '../scripts/core.js';

const example = (kind) => JSON.parse(readFileSync(`examples/${kind}.json`, 'utf8'));

test('story validation names the page, JSON path, and repair for malformed input', () => {
  const cases = [
    [null, 'story'], [{ pages: [] }, 'pages'], [{ pages: [null] }, 'pages[0]'],
    [{ pages: [{ type: 'constructor', claim: '判斷' }] }, 'pages[0].type'],
    [{ pages: [{ type: 'statement', claim: ' ' }] }, 'pages[0].claim'],
    [{ pages: [{ type: 'evidence', claim: '判斷' }] }, 'pages[0].visual'],
    [{ pages: [{ type: 'evidence', claim: '判斷', visual: { kind: 'line', series: [null] } }] }, 'pages[0].visual'],
    [{ pages: [{ type: 'evidence', claim: '判斷', visual: { kind: 'constructor' } }] }, 'pages[0].visual.kind'],
    [{ pages: [{ type: 'statement', claim: '判斷', visual: { kind: 'line', series: '錯誤' } }] }, 'pages[0].visual'],
    [{ pages: [{ type: 'numbers', claim: '判斷', visual: { items: [{ label: '甲', value: {} }] } }] }, 'pages[0].visual.items[0].value'],
    [{ pages: [{ type: 'numbers', claim: '判斷', visual: { items: [] } }] }, 'pages[0].visual.items'],
    [{ pages: [{ type: 'compare', claim: '判斷', visual: { rows: ['成本'], options: [{ name: '甲', values: [] }] } }] }, 'pages[0].visual.options[0].values'],
    [{ pages: [{ type: 'steps', claim: '判斷', visual: { start: '2026-13', end: '2026-12', phases: [] } }] }, 'pages[0].visual.start'],
    [{ pages: [{ type: 'close', claim: '判斷', visual: { rows: [null] } }] }, 'pages[0].visual.rows[0]'],
    [{ pages: [{ type: 'statement', claim: '判斷', sources: { more: '補充' } }] }, 'pages[0].sources.more'],
  ];
  for (const [story, path] of cases) assert.throws(() => validateStory(story), (err) => {
    assert.ok(err.message.includes(path), err.message);
    assert.match(err.message, /請/);
    if (path.startsWith('pages[')) assert.match(err.message, /第 1 頁/);
    return true;
  });
});

test('build validates before collecting chart categories', async () => {
  await assert.rejects(build({ pages: [{ type: 'evidence', claim: '判斷', visual: { kind: 'line', series: [null] } }] }), /第 1 頁.*pages\[0\]\.visual.*請/);
});

test('story validation accepts examples and rejects unsafe dates and visual settings', () => {
  const valid = example('story'), before = structuredClone(valid);
  assert.doesNotThrow(() => validateStory(valid));
  assert.deepEqual(valid, before, 'validation leaves authored content untouched');
  const changes = [
    ['numbers', (p) => { p.visual.items[0].digits = -1; }, /items\[0\]\.digits/],
    ['steps', (p) => { p.visual.end = '2025-12'; }, /visual\.end/],
    ['steps', (p) => { p.visual.phases[0].to = '2027-01'; }, /phases\[0\]\.to/],
    ['evidence', (p) => { p.visual.native = 'false'; }, /visual\.native/],
    ['evidence', (p) => { p.visual = { kind: 'matrix', domain: [0, 0], points: [{ label: '甲', x: 1, y: 2 }] }; }, /visual\.domain/],
  ];
  for (const [type, change, error] of changes) {
    const story = example('story'), page = story.pages.find((p) => p.type === type);
    change(page);
    assert.throws(() => validateStory(story), error);
  }
});

test('empty visual cells and metric omit their blocks while missing numbers remain in sources', async () => {
  const pages = [
    { type: 'numbers', claim: '觀察與缺值', visual: { items: [{}, { label: '甲', value: 0 }, { label: '乙', value: null }] } },
    { type: 'compare', claim: '比較', visual: { rows: ['條件'], options: [{}, { name: '甲', values: ['可行'] }, { name: '乙', values: ['待確認'] }] } },
    { type: 'close', claim: '下一步', visual: { rows: [{}, { task: '提出草案' }] } },
    { type: 'evidence', claim: '觀察', visual: visuals[0], metric: {} },
  ];
  const omitted = structuredClone(pages);
  omitted[0].visual.items.shift();
  omitted[1].visual.options.shift();
  omitted[2].visual.rows.shift();
  delete omitted[3].metric;
  const a = await deck(pages), b = await deck(omitted);
  for (let n = 1; n <= pages.length; n++) assert.equal(await a.zip.file(`ppt/slides/slide${n}.xml`).async('string'), await b.zip.file(`ppt/slides/slide${n}.xml`).async('string'));
  const numbers = textOf(await xml(a.zip, 'ppt/slides/slide1.xml'));
  assert.ok(numbers.includes('未提供：乙'));
  assert.ok(numbers.includes('0'));
  assert.doesNotMatch(textOf(await xml(a.zip, 'ppt/slides/slide3.xml')), /負責人|期限/);
  assert.deepEqual(a.warnings, []);
});

test('renderable numbers and comparison counts are warnings rather than blockers', async () => {
  const { buffer, warnings } = await deck([
    { type: 'numbers', claim: '觀察', visual: { items: [{ label: '甲', value: 1 }] }, notes: ['講稿甲', '講稿乙'] },
    { type: 'compare', claim: '比較', visual: { rows: ['條件'], options: [{ name: '甲', values: ['可行'] }] } },
  ]);
  assert.ok(buffer.length);
  assert.ok(warnings.some((w) => /第 1 頁.*2～4/.test(w)));
  assert.ok(warnings.some((w) => /第 2 頁.*2～4/.test(w)));
});

test('a numeric zero in an evidence metric remains visible', async () => {
  const { zip } = await deck([{ type: 'evidence', claim: '觀察', visual: visuals[0], metric: { label: '新增件數', value: 0 } }]);
  assert.ok(nodes(await xml(zip, 'ppt/slides/slide1.xml'), 'a:t').some((node) => textOf(node) === '0'));
});
const hex = (color) => color.replace('#', '').toUpperCase();
const decode = (s) => s.replace(/&(?:#x([\da-f]+)|#(\d+)|(amp|lt|gt|quot|apos));/gi, (_, h, d, n) => h || d ? String.fromCodePoint(parseInt(h ?? d, h ? 16 : 10)) : ({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" })[n]);

// A small structural parser: reject mismatched tags and invalid attributes without another dependency.
function parseXml(xml) {
  const root = { name: '#document', attrs: {}, children: [], text: '' }, stack = [root];
  const tokens = /<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<!\[CDATA\[[\s\S]*?\]\]>|<\/?[\w:.-]+(?:[^<>"']|"[^"]*"|'[^']*')*>/g;
  let at = 0;
  const append = (text) => {
    assert.ok(!text.includes('<'), 'unparsed XML markup');
    assert.ok(!/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[\da-f]+;)/i.test(text), 'unescaped XML entity');
    stack.at(-1).text += decode(text);
  };
  for (const match of xml.matchAll(tokens)) {
    append(xml.slice(at, match.index));
    const tag = match[0];
    at = match.index + tag.length;
    if (tag.startsWith('<?') || tag.startsWith('<!--')) continue;
    if (tag.startsWith('<![CDATA[')) { stack.at(-1).text += tag.slice(9, -3); continue; }
    if (tag.startsWith('</')) {
      assert.ok(stack.length > 1, `unexpected closing tag ${tag}`);
      assert.equal(stack.pop().name, tag.slice(2, -1).trim(), `unpaired tag ${tag}`);
      continue;
    }
    const name = tag.match(/^<([\w:.-]+)/)[1], attrs = {};
    let rest = tag.slice(name.length + 1).replace(/\/?\s*>$/, '');
    while (rest.trim()) {
      const attr = rest.match(/^\s+([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/);
      assert.ok(attr, `invalid attributes in ${tag}`);
      assert.ok(!(attr[1] in attrs), `duplicate attribute ${attr[1]}`);
      attrs[attr[1]] = decode(attr[2] ?? attr[3]);
      rest = rest.slice(attr[0].length);
    }
    const node = { name, attrs, children: [], text: '' };
    stack.at(-1).children.push(node);
    if (!tag.endsWith('/>')) stack.push(node);
  }
  append(xml.slice(at));
  assert.equal(stack.length, 1, 'unclosed XML tag');
  assert.equal(root.children.length, 1, 'XML must have one root');
  assert.equal(root.text.trim(), '', 'text outside XML root');
  return root.children[0];
}

const children = (node, name) => node.children.filter((n) => n.name === name);
const nodes = (node, name) => node.children.flatMap((n) => [...(n.name === name ? [n] : []), ...nodes(n, name)]);
const one = (node, name) => { const found = nodes(node, name); assert.ok(found.length, `missing ${name}`); return found[0]; };
const textOf = (node) => node.text + node.children.map(textOf).join('');
const value = (node, name) => one(node, name).attrs.val;
const xml = async (zip, name) => { assert.ok(zip.file(name), `missing ${name}`); return parseXml(await zip.file(name).async('string')); };
const files = (zip, re) => Object.keys(zip.files).filter((name) => re.test(name));
const partTarget = (part, target) => target.startsWith('/') ? target.slice(1) : path.posix.normalize(path.posix.join(path.posix.dirname(part), target));
const relsPath = (part) => path.posix.join(path.posix.dirname(part), '_rels', `${path.posix.basename(part)}.rels`);
async function related(zip, part, id) {
  const all = nodes(await xml(zip, relsPath(part)), 'Relationship');
  const found = all.find((r) => r.attrs.Id === id);
  assert.ok(found, `${part}: missing ${id}`);
  return partTarget(part, found.attrs.Target);
}
async function chartAt(zip, n) {
  const slide = `ppt/slides/slide${n}.xml`, ref = one(await xml(zip, slide), 'c:chart');
  const name = await related(zip, slide, ref.attrs['r:id']);
  return { name, root: await xml(zip, name) };
}
async function workbook(zip, chart) {
  const ref = one(chart.root, 'c:externalData');
  const name = await related(zip, chart.name, ref.attrs['r:id']);
  assert.match(name, /^ppt\/embeddings\/.*\.xlsx$/);
  return JSZip.loadAsync(await zip.file(name).async('nodebuffer'));
}
const evidence = (visual) => ({ type: 'evidence', claim: '資料比較', visual });
const deck = async (pages, extra = {}) => { const result = await build({ title: '測試簡報', pages, ...extra }); return { ...result, zip: await JSZip.loadAsync(result.buffer) }; };
const shapeText = (root, text) => { const found = nodes(root, 'p:sp').find((s) => textOf(s) === text); assert.ok(found, `missing text shape ${text}`); return found; };
const geometry = (shape) => {
  const off = one(shape, 'a:off').attrs, ext = one(shape, 'a:ext').attrs, unit = 914400 / T.slide.pxPerIn;
  return { x: Number(off.x) / unit, y: Number(off.y) / unit, w: Number(ext.cx) / unit, h: Number(ext.cy) / unit };
};
const shapeFill = (shape) => children(one(shape, 'p:spPr'), 'a:solidFill').flatMap((f) => nodes(f, 'a:srgbClr')).map((c) => c.attrs.val);

test('single-series line does not consume deck-wide categorical colours', async () => {
  for (const extra of [{}, { categories: ['總量'] }]) {
    const { zip } = await deck([
      evidence({ kind: 'line', x: ['前期', '本期'], series: [{ name: '總量', values: [1, 2] }], ...extra }),
      evidence({ kind: 'grouped', seriesRole: 'categorical', x: ['本期'], series: [{ name: '甲', values: [3] }, { name: '乙', values: [4] }] }),
    ]);
    const chart = await chartAt(zip, 2);
    assert.deepEqual(nodes(chart.root, 'c:ser').map((s) => value(one(s, 'c:spPr'), 'a:srgbClr')), C.categorical.slice(0, 2).map(hex));
  }
});

test('native rank highlights both named channels and funnel SVG includes loss labels', async () => {
  const rows = [{ label: '甲', value: 2400 }, { label: '乙', value: 1800 }, { label: '丙', value: 1260 }];
  const { zip } = await deck([evidence({ kind: 'rank', rows, focus: ['乙', '丙'] }), evidence({ kind: 'funnel', steps: rows, loss: true, focus: ['乙', '丙'] })]);
  const chart = await chartAt(zip, 1);
  assert.equal(nodes(chart.root, 'c:dPt').filter((p) => nodes(p, 'a:srgbClr').some((c) => c.attrs.val === hex(C.focus))).length, 2);
  const media = await Promise.all(files(zip, /\.svg$/).map((name) => zip.file(name).async('string')));
  assert.ok(media.some((s) => s.includes('−600') && s.includes('−540')));
});
const sourceY = (root) => Math.max(...nodes(root, 'p:sp').filter((s) => nodes(s, 'a:prstGeom').some((g) => g.attrs.prst === 'line') && Math.abs(geometry(s).w - (T.slide.widthPx - 2 * T.margin.x)) < 0.01).map((s) => geometry(s).y));
const near = (actual, expected, why) => assert.ok(Math.abs(actual - expected) < 0.01, `${why}: ${actual} != ${expected}`);

test('summary validation requires a lead and validates inherited number and optional text fields', () => {
  const page = { type: 'summary', claim: '判斷', visual: { lead: '優先試行', items: [{ label: '甲', value: 1 }, { label: '乙', value: 2 }] } };
  for (const [change, field] of [
    [(p) => { delete p.visual.lead; }, 'visual.lead'],
    [(p) => { p.visual.lead = ' '; }, 'visual.lead'],
    [(p) => { p.visual.lead = 1; }, 'visual.lead'],
    [(p) => { p.visual.body = []; }, 'visual.body'],
    [(p) => { p.visual.items = []; }, 'visual.items'],
    [(p) => { p.visual.items[0].note = 1; }, 'visual.items[0].note'],
    [(p) => { p.visual.items[0].value = {}; }, 'visual.items[0].value'],
    [(p) => { p.visual.items[0].prev = '2'; }, 'visual.items[0].prev'],
    [(p) => { p.visual.items[0].digits = -1; }, 'visual.items[0].digits'],
    [(p) => { p.visual.items[0].better = 'unknown'; }, 'visual.items[0].better'],
    [(p) => { p.visual.items[0].mode = 'unknown'; }, 'visual.items[0].mode'],
    [(p) => { p.notes = [1]; }, 'notes'],
  ]) {
    const changed = structuredClone(page); change(changed);
    assert.throws(() => validateStory({ pages: [changed] }), (error) => error.message.includes(`第 1 頁：pages[0].${field}`) && error.message.includes('請'));
  }
});

test('summary keeps zero, missing sources, units, delta, notes, and left/right vertical geometry', async () => {
  const page = { type: 'summary', kicker: '主管摘要', claim: '優先改善服務', visual: {
    lead: '先做小規模試行', body: '先確認可行性。\n再擴大範圍。',
    items: [{ label: '新增缺失', value: 0, unit: '件', prev: 2, better: 'lower', note: '本期未新增' }, { label: '待確認值', value: null }],
  }, sources: { source: '會議紀錄' }, notes: ['講稿甲', '講稿乙'] };
  const { zip, warnings } = await deck([page]);
  assert.deepEqual(warnings, []);
  const root = await xml(zip, 'ppt/slides/slide1.xml'), lead = shapeText(root, page.visual.lead), body = shapeText(root, '先確認可行性。再擴大範圍。');
  const number = shapeText(root, '0 件'), first = shapeText(root, '新增缺失'), second = shapeText(root, '待確認值');
  const leadBox = geometry(lead), numberBox = geometry(number), firstBox = geometry(first), secondBox = geometry(second);
  const claim = geometry(shapeText(root, page.claim));
  near(leadBox.y, claim.y + claim.h + T.margin.contentGap, 'summary starts below claim');
  assert.ok(geometry(body).y > leadBox.y + leadBox.h);
  assert.ok(numberBox.x > leadBox.x + leadBox.w, 'numbers occupy the right column');
  near(numberBox.x, firstBox.x, 'number and label share a left edge');
  near(firstBox.x, secondBox.x, 'items form a vertical column');
  assert.ok(firstBox.y >= numberBox.y + numberBox.h && secondBox.y > firstBox.y);
  assert.ok(nodes(lead, 'a:rPr').every((r) => r.attrs.b === '1'));
  assert.ok(nodes(first, 'a:rPr').every((r) => r.attrs.b === '1'));
  assert.ok(nodes(number, 'a:rPr').some((r) => Number(r.attrs.sz) === T.type.conclusionNumber.px / T.slide.pxPerPt * 100));
  assert.equal(value(one(shapeText(root, '−2'), 'a:rPr'), 'a:srgbClr'), hex(C.better));
  assert.ok(textOf(root).includes('未提供：待確認值'));
  assert.doesNotMatch(textOf(root), /null|undefined|NaN/);
  const between = nodes(root, 'p:sp').filter((s) => nodes(s, 'a:prstGeom').some((g) => g.attrs.prst === 'line') && geometry(s).x === numberBox.x);
  assert.equal(between.length, 1, 'one divider separates two items');
  assert.ok(geometry(between[0]).y > firstBox.y && geometry(between[0]).y < secondBox.y);
  const notes = textOf(await xml(zip, 'ppt/notesSlides/notesSlide1.xml'));
  assert.ok(notes.includes('講稿甲') && notes.includes('講稿乙'));
  const optional = structuredClone(page); delete optional.visual.body; delete optional.visual.items[0].note; optional.notes = '單段講稿';
  const without = await deck([optional]), withoutRoot = await xml(without.zip, 'ppt/slides/slide1.xml');
  assert.deepEqual(without.warnings, []);
  assert.ok(!textOf(withoutRoot).includes('先確認可行性') && !textOf(withoutRoot).includes('本期未新增'));
  assert.ok(textOf(await xml(without.zip, 'ppt/notesSlides/notesSlide1.xml')).includes('單段講稿'));
});

test('summary warns for capacity and long lead, body, number, label, and note without blocking output', async () => {
  const make = (count) => ({ type: 'summary', claim: '建議', visual: { lead: '先行試辦', items: Array.from({ length: count }, (_, i) => ({ label: `項目${i}`, value: i })) } });
  const long = make(2);
  Object.assign(long.visual, { lead: '建議\n第二行', body: '甲\n乙\n丙\n丁' });
  Object.assign(long.visual.items[0], { label: '標籤\n第二行', note: '說明\n第二行', value: '12345678901234567890' });
  const { buffer, warnings } = await deck([make(1), make(2), make(3), make(4), long]);
  assert.ok(buffer.length);
  for (const n of [1, 4]) assert.ok(warnings.some((w) => w.includes(`第 ${n} 頁主管摘要`) && /2～3/.test(w)));
  for (const n of [2, 3]) assert.ok(!warnings.some((w) => w.includes(`第 ${n} 頁`)));
  for (const pattern of [/visual\.lead.*2 行.*上限 1 行/, /visual\.body.*4 行.*上限 3 行/, /數字超出欄寬/, /visual\.items\[0\]\.note.*2 行.*上限 1 行/, /超出單列容量/]) assert.ok(warnings.some((w) => /第 5 頁/.test(w) && pattern.test(w)), String(pattern));
});

test('process visual.note sits below steps, reserves room, and validates its text', async () => {
  const visual = { steps: [{ heading: '收件', body: '核對資料' }, { heading: '交接' }, { heading: '完成' }], note: '遇到缺件，回到收件補齊。' };
  const { zip, warnings } = await deck([{ type: 'process', claim: '先核對再交接', visual }]);
  const root = await xml(zip, 'ppt/slides/slide1.xml');
  const note = geometry(shapeText(root, visual.note)), body = geometry(shapeText(root, '核對資料'));
  assert.ok(note.y >= body.y + T.type.body.px * 1.45 + 24);
  assert.ok(note.y + note.h <= sourceY(root) - T.margin.sourceGap);
  assert.deepEqual(warnings, []);
  assert.throws(() => validateStory({ pages: [{ type: 'process', claim: '流程', visual: { ...visual, note: 1 } }] }), /visual\.note/);
  const overflow = await deck([{ type: 'process', claim: '流程', visual: { ...visual, note: '甲\r\n乙' } }]);
  assert.ok(overflow.warnings.some((w) => /visual\.note.*2 行.*上限 1 行/.test(w)));
});

test('positive delta uses the design-layer sign in PowerPoint and SVG', async () => {
  const { zip } = await deck([{ type: 'numbers', claim: '變化', visual: { items: [{ label: '甲', prev: 100, value: 310, better: 'higher' }, { label: '乙', value: 1 }] } }]);
  assert.ok(textOf(await xml(zip, 'ppt/slides/slide1.xml')).includes(`${T.delta.signs.increase}210`));
  const { svg } = await import('../scripts/svg.js').then(({ render }) => render({ kind: 'dumbbell', periods: ['前期', '本期'], rows: [{ label: '甲', values: [100, 310] }] }));
  assert.ok(svg.includes(`${T.delta.signs.increase}210`));
});

test('close uses the cover background, white bold tasks, right-aligned muted owners/dates and readable footer', async () => {
  const rows = [{ task: '提出草案', owner: '營運科', due: '月底' }, { task: '確認範圍', owner: '規劃科' }];
  const pages = [{ type: 'cover', claim: '封面' }, { type: 'close', claim: '決議', visual: { rows }, sources: { source: '會議決議' } },
    ...['owner', 'due'].map((omit) => ({ type: 'close', claim: '決議', visual: { rows: rows.map((r) => Object.fromEntries(Object.entries(r).filter(([key]) => key !== omit))) } }))];
  const { zip, warnings } = await deck(pages);
  assert.deepEqual(warnings, []);
  const cover = await xml(zip, 'ppt/slides/slide1.xml'), root = await xml(zip, 'ppt/slides/slide2.xml');
  assert.equal(value(one(root, 'p:bg'), 'a:srgbClr'), value(one(cover, 'p:bg'), 'a:srgbClr'));
  assert.equal(value(one(root, 'p:bg'), 'a:srgbClr'), hex(C.dark));
  for (const text of ['提出草案', '確認範圍']) {
    const s = shapeText(root, text);
    assert.ok(nodes(s, 'a:rPr').every((r) => r.attrs.b === '1' && value(r, 'a:srgbClr') === hex(C.onDark[0])));
  }
  for (const text of ['營運科', '規劃科', '月底', '資料來源：會議決議', '2 / 4']) {
    const s = shapeText(root, text);
    assert.ok(nodes(s, 'a:rPr').every((r) => value(r, 'a:srgbClr') === hex(C.onDark[1])));
    if (!text.startsWith('資料來源')) assert.ok(nodes(s, 'a:pPr').every((r) => r.attrs.algn === 'r'));
  }
  for (const s of nodes(root, 'p:sp').filter((s) => nodes(s, 'a:prstGeom').some((g) => g.attrs.prst === 'line'))) {
    assert.equal(value(one(s, 'a:ln'), 'a:srgbClr'), hex(C.onDark[1]));
    assert.equal(Number(one(s, 'a:ln').attrs.w), T.stroke.axis / T.slide.pxPerPt * 12700);
  }
  assert.ok(!textOf(await xml(zip, 'ppt/slides/slide3.xml')).includes('負責人'));
  assert.ok(!textOf(await xml(zip, 'ppt/slides/slide4.xml')).includes('期限'));
});

test('compare highlights the complete recommended column and leaves unselected headers and cells unfilled', async () => {
  const page = { type: 'compare', claim: '比較方案', visual: { rows: ['成本', '時間'], options: [
    { name: '方案甲', subtitle: '保守作法', values: ['甲成本', '甲時間'] },
    { name: '方案乙', subtitle: '優先試行', recommended: true, values: ['乙成本', '乙時間'] },
  ] } };
  const plain = structuredClone(page); delete plain.visual.options[1].recommended;
  const { zip, warnings } = await deck([page, plain]);
  assert.deepEqual(warnings, []);
  const root = await xml(zip, 'ppt/slides/slide1.xml'), shapes = nodes(root, 'p:sp');
  const header = shapes.filter((s) => shapeFill(s).includes(hex(C.focus))), cells = shapes.filter((s) => shapeFill(s).includes(hex(C.tint)));
  assert.equal(header.length, 1); assert.equal(cells.length, 2);
  const h = geometry(header[0]);
  for (const label of ['方案乙　建議', '優先試行']) {
    const s = shapeText(root, label), g = geometry(s);
    assert.ok(nodes(s, 'a:rPr').every((r) => value(r, 'a:srgbClr') === hex(C.onDark[0])));
    assert.ok(g.x >= h.x && g.x + g.w <= h.x + h.w + 0.01 && g.y >= h.y && g.y + g.h <= h.y + h.h + 0.01, `${label}: text inside solid header`);
  }
  for (const [i, s] of cells.entries()) {
    const g = geometry(s), text = geometry(shapeText(root, ['乙成本', '乙時間'][i]));
    near(g.x, h.x, 'recommended cells align with header'); near(g.w, h.w, 'recommended column has uniform width');
    assert.ok(text.x >= g.x && text.x + text.w <= g.x + g.w + 0.01 && text.y >= g.y && text.y + text.h <= g.y + g.h + 0.01);
  }
  const unselected = await xml(zip, 'ppt/slides/slide2.xml');
  assert.equal(nodes(unselected, 'p:sp').filter((s) => shapeFill(s).includes(hex(C.focus)) || shapeFill(s).includes(hex(C.tint))).length, 0);
  assert.ok(!textOf(unselected).includes('建議'));
});

test('numbers sit centered below one-line and two-line titles', async () => {
  const { zip, warnings } = await deck(['主張', '主張\n第二行'].map((claim) => ({ type: 'numbers', claim, visual: { items: [{ label: '甲', value: 1 }, { label: '乙', value: 2 }] } })));
  assert.deepEqual(warnings, []);
  for (const n of [1, 2]) {
    const root = await xml(zip, `ppt/slides/slide${n}.xml`), title = geometry(shapeText(root, n === 1 ? '主張' : '主張第二行'));
    const lines = nodes(root, 'p:sp').filter((s) => nodes(s, 'a:prstGeom').some((g) => g.attrs.prst === 'line') && geometry(s).w > 0 && geometry(s).w < T.slide.widthPx - 2 * T.margin.x);
    const top = Math.min(...lines.map((s) => geometry(s).y)), end = sourceY(root) - T.margin.sourceGap;
    const bottom = Math.max(...nodes(root, 'p:sp').filter((s) => /^\d$/.test(textOf(s))).map((s) => geometry(s).y + geometry(s).h));
    assert.ok(top > title.y + title.h + T.margin.contentGap, 'tiles leave the content gap');
    assert.ok(Math.abs((top - (title.y + title.h + T.margin.contentGap)) - (end - bottom)) < 120, 'tiles are roughly centered');
    assert.ok(geometry(shapeText(root, '甲')).y < geometry(shapeText(root, '1')).y, 'label precedes its number');
  }
});

test('dark closing lede uses a readable onDark color', async () => {
  const { zip } = await deck([{ type: 'close', claim: '收尾', lede: '執行說明', visual: { rows: [{ task: '完成交接' }] } }]);
  const lede = shapeText(await xml(zip, 'ppt/slides/slide1.xml'), '執行說明');
  assert.equal(one(lede, 'a:srgbClr').attrs.val, hex(C.onDark[1]));
  assert.ok(contrast(C.onDark[1], C.dark) >= 4.5);
});

test('columns and process anchor below the lede while flow retains its centered band', async () => {
  const pages = [
    { type: 'columns', claim: '結論', lede: '說明行', visual: { items: [{ kicker: '類別', heading: '資料', body: '資料說明' }, { heading: '作業', body: '作業說明' }] } },
    { type: 'flow', claim: '結論', lede: '說明行', visual: { nodes: [{ heading: '起點' }, { heading: '終點' }], note: '補充說明' } },
    { type: 'process', claim: '結論', lede: '說明行', visual: { steps: [{ heading: '收件', body: '完成收件' }, { heading: '登錄', body: '完成登錄' }, { heading: '交接', body: '完成交接' }] } },
  ];
  const { zip, warnings } = await deck(pages);
  assert.deepEqual(warnings, []);
  for (let i = 0; i < pages.length; i++) {
    const root = await xml(zip, `ppt/slides/slide${i + 1}.xml`);
    const lede = geometry(shapeText(root, '說明行'));
    const start = lede.y + lede.h + T.margin.contentGap, end = sourceY(root) - T.margin.sourceGap;
    let first, last;
    if (i === 0) {
      first = geometry(shapeText(root, '類別')).y;
      const body = geometry(shapeText(root, '資料說明'));
      last = body.y + body.h;
    } else if (i === 1) {
      const boxes = nodes(root, 'p:sp').filter((s) => shapeFill(s).some((c) => [hex(C.tint), hex(C.focus)].includes(c))).map(geometry);
      assert.equal(boxes.length, 2);
      first = Math.min(...boxes.map((b) => b.y));
      const note = geometry(shapeText(root, '補充說明'));
      last = note.y + note.h;
    } else {
      first = geometry(shapeText(root, '步驟 1')).y;
      const body = geometry(shapeText(root, '完成交接'));
      last = body.y + T.type.body.px * 1.45;
    }
    if (i === 1) {
      assert.ok(first > start, 'flow: content follows lede');
      assert.ok(Math.abs((first - start) - (end - last)) < 120, 'flow: content is roughly centered');
    } else near(first, start + 28, `${pages[i].type}: band starts below lede`);
  }
});

test('short statements centre, tall statements stop at the title position, both preserve focus', async () => {
  const claims = ['先確認需求', '甲\n乙\n丙\n丁\n戊\n己\n庚'];
  const { zip, warnings } = await deck(claims.map((claim) => ({ type: 'statement', claim, focus: claim.slice(0, 1), lede: '原稿範圍', note: '資料尚待確認。' })));
  for (let i = 0; i < claims.length; i++) {
    const root = await xml(zip, `ppt/slides/slide${i + 1}.xml`), s = shapeText(root, claims[i].replaceAll('\n', ''));
    const anchor = T.margin.top + T.type.label.px + T.margin.titleGap;
    if (i === 0) assert.ok(geometry(s).y > anchor + 100, 'short statement is centred, not pinned to the top');
    else near(geometry(s).y, anchor, 'tall statement stops at title anchor');
    assert.ok(nodes(s, 'a:srgbClr').some((c) => c.attrs.val === hex(C.focus)));
  }
  assert.ok(warnings.some((w) => /第 2 頁.*高度/.test(w)));
});

test('statement rich text uses identical paragraphs for LF, CRLF, and CR', async () => {
  const { zip } = await deck(['\n', '\r\n', '\r'].map((eol) => ({ type: 'statement', claim: `甲${eol}乙`, focus: '乙' })));
  for (let n = 1; n <= 3; n++) {
    const root = await xml(zip, `ppt/slides/slide${n}.xml`), shape = shapeText(root, '甲乙');
    assert.deepEqual(nodes(one(shape, 'p:txBody'), 'a:p').map(textOf), ['甲', '乙']);
  }
});

test('oversized columns, flow, and process content starts at the top and warns', async () => {
  const long = Array(18).fill('詳細內容').join('\n');
  const pages = [
    { type: 'columns', claim: '結論', visual: { items: [{ heading: '甲', body: long }, { heading: '乙' }] } },
    { type: 'flow', claim: '結論', visual: { nodes: [{ heading: '甲', body: long }, { heading: '乙' }] } },
    { type: 'process', claim: '結論', visual: { steps: [{ heading: '甲', body: long }, { heading: '乙' }, { heading: '丙' }] } },
  ];
  const { zip, warnings } = await deck(pages);
  for (let i = 0; i < pages.length; i++) {
    const root = await xml(zip, `ppt/slides/slide${i + 1}.xml`);
    const title = geometry(shapeText(root, '結論'));
    const start = title.y + title.h + T.margin.contentGap;
    const first = i === 0 ? geometry(shapeText(root, '甲')).y - 28
      : i === 1 ? Math.min(...nodes(root, 'p:sp').filter((s) => shapeFill(s).includes(hex(C.tint)) || shapeFill(s).includes(hex(C.focus))).map((s) => geometry(s).y))
      : geometry(shapeText(root, '步驟 1')).y - 28;
    assert.ok(Math.abs(first - start) < 1, `${pages[i].type}: content starts at top`);
    assert.ok(warnings.some((w) => w.includes(`第 ${i + 1} 頁`) && w.includes('高度不足')), `${pages[i].type}: overflow warns`);
  }
});

for (const [type, base, medium] of [['table', 72, 6], ['compare', 110, 4], ['close', 100, 4]]) {
  test(`${type}: sparse rows cap at 1.8x, medium rows reach the source gap, crowded rows shrink and warn`, async () => {
    const counts = [2, medium, 12];
    const pages = counts.map((count) => {
      const labels = Array.from({ length: count }, (_, i) => `R${i}`);
      const visual = type === 'table' ? { kind: 'table', columns: [{ name: '項目', type: 'text' }, { name: '量' }], rows: labels.map((s, i) => [s, i + 1]) }
        : type === 'compare' ? { rows: labels, options: [{ name: '方案甲', values: labels }, { name: '方案乙', values: labels }] }
          : { rows: labels.map((task) => ({ task })) };
      return { type: type === 'table' ? 'evidence' : type, claim: '容量測試', visual };
    });
    const { zip, warnings } = await deck(pages);
    for (const [i, count] of counts.entries()) {
      const root = await xml(zip, `ppt/slides/slide${i + 1}.xml`), end = sourceY(root) - T.margin.sourceGap;
      let heights, top;
      if (type === 'table') {
        const rows = nodes(root, 'a:tr');
        heights = rows.slice(1).map((r) => Number(r.attrs.h) / (914400 / T.slide.pxPerIn));
        top = geometry(one(root, 'p:graphicFrame')).y + Number(rows[0].attrs.h) / (914400 / T.slide.pxPerIn);
      } else {
        const pad = 0; // row text fills its row and is vertically centered
        const rows = Array.from({ length: count }, (_, j) => geometry(shapeText(root, `R${j}`)));
        heights = rows.map((r) => r.h + pad); top = rows[0].y - pad;
      }
      assert.equal(heights.length, count);
      for (const h of heights) near(h, heights[0], 'rows have equal height');
      if (i === 0) near(heights[0], base * 1.8, 'sparse row cap');
      else near(top + heights.reduce((a, b) => a + b, 0), end, 'content ends at source gap');
      if (i === 2) assert.ok(heights[0] < base, 'crowded rows keep shrinking');
      assert.equal(warnings.some((w) => w.includes(`第 ${i + 1} 頁`) && /visual\..*估算 \d+ 行，上限 \d+ 行.*超出容量/.test(w)), i === 2);
    }
  });
}

const visuals = [
  { kind: 'rank', focus: '甲', rows: [{ label: '甲', value: 30 }, { label: '乙', value: 20 }, { label: '丙', value: 10 }] },
  { kind: 'line', focus: '主線', digits: 1, x: ['一月', '二月', '三月', '四月'], series: [{ name: '主線', values: [1.2, 6.4, null, 4.1] }, { name: '副線', values: [2.3, 3.5, 4.6, null] }] },
  { kind: 'slope', periods: ['前期', '本期'], rows: [{ label: '甲', values: [10, 12] }, { label: '乙', values: [8, 9] }] },
  { kind: 'share', categories: ['甲', '乙', '其他'], rows: [{ label: '北區', values: [12, 8, 5] }, { label: '南區', values: [3, 6, 21] }] },
  { kind: 'scatter', focus: '甲', points: [{ label: '甲', x: 1, y: 8 }, { label: '乙', x: 5, y: 2 }, { label: '丙', x: 9, y: 6 }] },
  example('table'),
];
let nativePromise, storyPromise, svgPromise;
const nativeDeck = () => nativePromise ??= deck(visuals.map(evidence), { author: '測試作者' });
const storyDeck = () => storyPromise ??= (async () => { const story = example('story'); const result = await build(story); return { ...result, zip: await JSZip.loadAsync(result.buffer), story }; })();
const svgKinds = ['multiples', 'bridge', 'histogram', 'strip', 'matrix', 'dumbbell', 'funnel', 'heat'];
const svgDeck = () => svgPromise ??= deck(svgKinds.map((kind) => evidence(example(kind))));
const tokenColors = new Set();
(function collect(v) {
  if (typeof v === 'string' && /^#[\da-f]{6}$/i.test(v)) tokenColors.add(hex(v));
  else if (v && typeof v === 'object') for (const [key, entry] of Object.entries(v)) { collect(key); collect(entry); }
})(T);

function checkColors(root, name) {
  for (const color of nodes(root, 'a:srgbClr')) assert.ok(tokenColors.has(color.attrs.val.toUpperCase()), `${name}: non-token color ${color.attrs.val}`);
}
function checkText(root, name) {
  for (const tag of ['a:rPr', 'a:defRPr', 'a:endParaRPr']) for (const r of nodes(root, tag)) {
    if (r.attrs.sz) assert.ok(Number(r.attrs.sz) >= T.type.minimum / T.slide.pxPerPt * 100, `${name}: font size ${r.attrs.sz}`);
  }
  for (const tag of ['a:latin', 'a:ea']) for (const font of nodes(root, tag)) assert.equal(font.attrs.typeface, SLIDE_FONT, `${name}: ${tag}`);
}
const enabled = (node, name) => nodes(node, name).some((n) => n.attrs.val === '1');
const labelIndex = (label) => Number(value(label, 'c:idx'));
const cacheValues = (node) => nodes(node, 'c:pt').map((p) => ({ index: Number(p.attrs.idx), value: textOf(one(p, 'c:v')) }));
const formatDigits = (format) => (format.split(';')[0].match(/\.(0+)/)?.[1] ?? '').length;
const cellValue = (cells, ref) => { const cell = cells.find((c) => c.attrs.r === ref); assert.ok(cell, `missing numeric cell ${ref}`); return textOf(one(cell, 'v')); };

// These checks validate the parser too, so malformed generated XML cannot pass an empty regex scan.
test('PPTX XML parser rejects broken tags and preserves escaped text', () => {
  assert.equal(textOf(parseXml('<?xml version="1.0"?><r a="x&amp;y"><p/>甲&amp;乙</r>')), '甲&乙');
  for (const bad of ['<a><b></a>', '<a>', '<a/><b/>', '<a b=x/>', '<a>&oops;</a>']) assert.throws(() => parseXml(bad));
});

test('story: nine pages, page numbers, no warnings, and empty author metadata', async () => {
  const { zip, story, warnings } = await storyDeck();
  assert.deepEqual(warnings, []);
  assert.equal(story.pages.length, 9);
  assert.equal(files(zip, /^ppt\/slides\/slide\d+\.xml$/).length, story.pages.length);
  for (let n = 1; n <= story.pages.length; n++) assert.ok(textOf(await xml(zip, `ppt/slides/slide${n}.xml`)).includes(`${n} / ${story.pages.length}`));
  const core = await xml(zip, 'docProps/core.xml');
  assert.equal(textOf(one(core, 'dc:creator')), '');
  assert.equal(textOf(one(core, 'cp:lastModifiedBy')), '');
  assert.equal(textOf(one(await xml(zip, 'docProps/app.xml'), 'Company')), '');
});

test('所有版型、表格、原生圖與段落末尾都使用繁體中文換行語言', async () => {
  const seen = new Set();
  for (const { zip } of await Promise.all([storyDeck(), nativeDeck(), svgDeck()])) {
    for (const name of files(zip, /^ppt\/.*\.xml$/)) {
      const source = await zip.file(name).async('string');
      assert.doesNotMatch(source, /\blang="en-US"/, name);
      const root = parseXml(source);
      for (const tag of ['a:rPr', 'a:defRPr', 'a:endParaRPr']) for (const props of nodes(root, tag)) {
        seen.add(tag);
        assert.equal(props.attrs.lang, 'zh-TW', `${name}: ${tag}`);
      }
      for (const lang of nodes(root, 'c:lang')) assert.equal(lang.attrs.val, 'zh-TW', name);
    }
  }
  assert.deepEqual([...seen].sort(), ['a:defRPr', 'a:endParaRPr', 'a:rPr']);
});

test('所有版型的 claim 保留指定斷點並依行數配置標題高度', async () => {
  const pages = example('story').pages.map((page) => ({ ...page, claim: '交接重新\n確認後開始', ...(page.type === 'statement' ? { focus: '重新\n確認' } : {}) }));
  const single = pages.map((page) => ({ ...page, claim: '交接重新確認後開始', ...(page.type === 'statement' ? { focus: '重新確認' } : {}) }));
  const a = await deck(pages), b = await deck(single);
  for (const [i, page] of pages.entries()) {
    const shape = async (zip) => nodes(await xml(zip, `ppt/slides/slide${i + 1}.xml`), 'p:sp')
      .find((node) => textOf(node) === '交接重新確認後開始');
    const multiline = await shape(a.zip), oneline = await shape(b.zip);
    assert.ok(multiline && oneline, page.type);
    assert.deepEqual(nodes(one(multiline, 'p:txBody'), 'a:p').map(textOf), ['交接重新', '確認後開始'], page.type);
    const height = (node) => Number(one(one(node, 'a:xfrm'), 'a:ext').attrs.cy);
    assert.equal(height(multiline), height(oneline) * 2, `${page.type}: 兩行高度`);
    if (['cover', 'section', 'statement'].includes(page.type) && page.note) {
      const note = nodes(await xml(a.zip, `ppt/slides/slide${i + 1}.xml`), 'p:sp').find((node) => textOf(node) === page.note);
      const y = (node) => Number(one(one(node, 'a:xfrm'), 'a:off').attrs.y);
      assert.ok(y(note) > y(multiline) + height(multiline), `${page.type}: 副標在標題下方`);
    }
  }
});

test('一句話頁的強調片段在斷點前後或跨行都不增加換行', async () => {
  const claim = '交接重新\n確認後開始';
  const focuses = [undefined, '重新', '確認', '重新\n確認', '交接重新\n', '\n確認'];
  const { zip } = await deck(focuses.map((focus) => ({ type: 'statement', claim, focus })));
  for (const [i, focus] of focuses.entries()) {
    const shape = nodes(await xml(zip, `ppt/slides/slide${i + 1}.xml`), 'p:sp').find((node) => textOf(node) === claim.replaceAll('\n', ''));
    assert.ok(shape);
    assert.deepEqual(nodes(one(shape, 'p:txBody'), 'a:p').map(textOf), claim.split('\n'), focus);
    const highlighted = nodes(shape, 'a:r').filter((r) => nodes(r, 'a:srgbClr').some((c) => c.attrs.val === hex(C.focus))).map(textOf).join('');
    assert.equal(highlighted, (focus ?? '').replaceAll('\n', ''));
  }
});

test('empty optional fields omit their text boxes, including source units', async () => {
  const page = { type: 'cover', kicker: '單位名稱', claim: '主張', note: '備註內容', sources: { source: '來源內容', unit: '數值單位', period: '資料期間' } };
  const full = await deck([page]);
  const empty = await deck([{ ...page, kicker: '', note: '', sources: { ...page.sources, unit: '' } }]);
  const before = await xml(full.zip, 'ppt/slides/slide1.xml'), after = await xml(empty.zip, 'ppt/slides/slide1.xml');
  assert.equal(nodes(before, 'p:sp').length - nodes(after, 'p:sp').length, 3);
  for (const text of ['單位名稱', '備註內容', '數值單位', '單位：']) assert.ok(!textOf(after).includes(text));
  for (const text of ['主張', '來源內容', '資料期間', '1 / 1']) assert.ok(textOf(after).includes(text));
});

test('all native charts have embedded editable workbooks; table uses a native table', async () => {
  const { zip } = await nativeDeck();
  assert.equal(files(zip, /^ppt\/charts\/chart\d+\.xml$/).length, 5);
  assert.equal(files(zip, /^ppt\/embeddings\/.*\.xlsx$/).length, 5);
  const kinds = ['c:barChart', 'c:lineChart', 'c:lineChart', 'c:barChart', 'c:scatterChart'];
  for (let n = 1; n <= 5; n++) {
    const chart = await chartAt(zip, n);
    one(chart.root, kinds[n - 1]);
    const book = await workbook(zip, chart);
    assert.ok(files(book, /^xl\/worksheets\/sheet\d+\.xml$/).length);
  }
  const table = await xml(zip, 'ppt/slides/slide6.xml');
  one(table, 'a:tbl');
  assert.equal(nodes(table, 'c:chart').length, 0);
  assert.equal(files(zip, /^ppt\/media\/.*\.svg$/).length, 0);
});

test('all deck/chart/workbook XML is paired and metadata contains no PptxGenJS', async () => {
  for (const { zip } of [await nativeDeck(), await storyDeck()]) {
    for (const name of files(zip, /\.xml$/)) {
      const raw = await zip.file(name).async('string');
      assert.doesNotMatch(raw, /PptxGenJS/i, name);
      parseXml(raw);
    }
    for (const name of files(zip, /^ppt\/embeddings\/.*\.xlsx$/)) {
      const book = await JSZip.loadAsync(await zip.file(name).async('nodebuffer'));
      for (const part of files(book, /\.xml$/)) {
        const raw = await book.file(part).async('string');
        assert.doesNotMatch(raw, /PptxGenJS/i, `${name}: ${part}`);
        parseXml(raw);
      }
    }
  }
});

test('slide and chart text uses JhengHei, minimum 12 pt, and only token colors', async () => {
  for (const { zip } of [await nativeDeck(), await storyDeck()]) {
    for (const name of files(zip, /^ppt\/(?:slides\/slide|charts\/chart)\d+\.xml$/)) {
      const root = await xml(zip, name);
      checkText(root, name);
      checkColors(root, name);
    }
    const themeRaw = await zip.file('ppt/theme/theme1.xml').async('string');
    assert.doesNotMatch(themeRaw, /新細明體|PMingLiU/i);
    const theme = parseXml(themeRaw);
    for (const tag of ['a:majorFont', 'a:minorFont']) {
      const group = one(theme, tag);
      assert.equal(one(group, 'a:ea').attrs.typeface, SLIDE_FONT);
      assert.equal(nodes(group, 'a:font').find((f) => f.attrs.script === 'Hant')?.attrs.typeface, SLIDE_FONT);
    }
  }
});

test('rank：單一系列、反向類別、外部標籤與粗體重點標籤', async () => {
  const { zip } = await nativeDeck(), { root } = await chartAt(zip, 1);
  const series = nodes(root, 'c:ser');
  assert.equal(series.length, 1);
  const points = children(series[0], 'c:dPt');
  assert.equal(points.length, visuals[0].rows.length);
  assert.equal(points.filter((p) => nodes(p, 'a:srgbClr').some((c) => c.attrs.val === hex(C.focus))).length, 1);
  assert.equal(value(one(root, 'c:catAx'), 'c:orientation'), 'maxMin');
  assert.ok(nodes(root, 'c:dLblPos').some((p) => p.attrs.val === 'outEnd'));
  const label = nodes(series[0], 'c:dLbl').find((l) => labelIndex(l) === 0);
  assert.ok(label);
  assert.ok(nodes(label, 'a:srgbClr').some((c) => c.attrs.val === hex(C.focus)));
  assert.ok([...nodes(label, 'a:defRPr'), ...nodes(label, 'a:rPr')].some((p) => p.attrs.b === '1'));
  assert.equal(nodes(label, 'c:tx').length, 0);
  assert.deepEqual(nodes(series[0], 'c:dLbl').filter((item) => enabled(item, 'c:showCatName')).map(labelIndex), [0]);
  assert.ok(enabled(label, 'c:showVal'));
  assert.ok(nodes(root, 'c:manualLayout').some((layout) => nodes(layout, 'c:layoutTarget').length));
});

test('rank keeps long focus names on the category axis when a narrow plot cannot fit both ends', async () => {
  const label = '很長的排行類別名稱'.repeat(3);
  const spec = { kind: 'rank', focus: label, rows: [{ label, value: -20 }, { label: '乙', value: 10 }] };
  const { zip, warnings } = await deck([{ ...evidence(spec), note: '雙向比較' }]);
  const { root } = await chartAt(zip, 1);
  assert.ok(warnings.some((w) => w.includes('焦點名稱保留在類別軸')));
  assert.equal(value(one(root, 'c:catAx'), 'c:tickLblPos'), 'low');
  assert.ok(nodes(root, 'c:dLbl').every((item) => !enabled(item, 'c:showCatName')));
  assert.ok(textOf(one(root, 'c:cat')).includes(label));
});

test('line: missing cache/workbook cells are absent and labels follow only tail/peak indices', async () => {
  const { zip } = await nativeDeck(), chart = await chartAt(zip, 2), series = nodes(chart.root, 'c:ser');
  const source = textOf(await xml(zip, 'ppt/slides/slide2.xml'));
  assert.ok(source.includes('未提供：主線／三月、副線／四月'));
  assert.equal(value(chart.root, 'c:dispBlanksAs'), 'gap');
  assert.equal(nodes(chart.root, 'c:legend').length, 0);
  const strokes = prepare(visuals[1]).series.map((row) => Math.round(row.width / T.slide.pxPerPt * 12700));
  assert.deepEqual(series.map((s) => Number(one(one(s, 'c:spPr'), 'a:ln').attrs.w)), strokes);
  assert.ok(strokes[0] > strokes[1]);
  for (let i = 0; i < series.length; i++) {
    const expected = visuals[1].series[i].values.flatMap((v, index) => v === null ? [] : [{ index, value: String(v) }]);
    assert.deepEqual(cacheValues(one(one(series[i], 'c:val'), 'c:numCache')), expected);
    const labels = nodes(series[i], 'c:dLbl');
    const visible = labels.filter((l) => enabled(l, 'c:showVal') || enabled(l, 'c:showSerName'));
    assert.deepEqual(visible.map(labelIndex).sort(), i === 0 ? [1, 3] : [2]);
    const tail = visible.find((l) => labelIndex(l) === (i === 0 ? 3 : 2));
    assert.ok(enabled(tail, 'c:showVal') && enabled(tail, 'c:showSerName'));
    assert.equal(nodes(series[i], 'c:dLbl').flatMap((l) => nodes(l, 'c:tx')).length, 0);
  }
  const book = await workbook(zip, chart), sheet = await xml(book, 'xl/worksheets/sheet1.xml');
  assert.ok(!nodes(sheet, 'c').some((c) => ['B4', 'C5'].includes(c.attrs.r)));
  for (const cell of nodes(sheet, 'c')) assert.ok(nodes(cell, 'v').every((v) => textOf(v).length), `empty cell ${cell.attrs.r}`);
  const model = prepare(visuals[1]), axis = one(chart.root, 'c:valAx');
  assert.equal(Number(value(axis, 'c:min')), model.axis.lo);
  assert.equal(nodes(axis, 'c:max').length, 0, 'maximum stays automatic after editing data');
  assert.equal(Number(value(axis, 'c:majorUnit')), model.axis.step);
  assert.equal(formatDigits(one(axis, 'c:numFmt').attrs.formatCode), decimalsOf(model.axis.ticks));
  for (const s of series) assert.ok(nodes(s, 'c:numFmt').some((f) => formatDigits(f.attrs.formatCode) === model.digits));
});

test('slope: gray series, ordered point markers, dynamic endpoint labels in OOXML order', async () => {
  const { zip } = await nativeDeck(), { root } = await chartAt(zip, 3);
  for (const series of nodes(root, 'c:ser')) {
    const line = one(one(series, 'c:spPr'), 'a:ln');
    assert.equal(one(line, 'a:srgbClr').attrs.val, hex(C.gray));
    const points = children(series, 'c:dPt');
    assert.equal(points.length, 2);
    for (const point of points) {
      const i = Number(value(point, 'c:idx'));
      assert.equal(one(one(point, 'c:marker'), 'a:srgbClr').attrs.val, hex(i ? C.ordered.at(-1) : C.ordered[0]));
    }
    const names = series.children.map((n) => n.name);
    assert.ok(names.indexOf('c:dPt') > names.indexOf('c:marker'));
    assert.ok(names.lastIndexOf('c:dPt') < names.indexOf('c:cat'));
    const labels = nodes(series, 'c:dLbl');
    for (const label of labels) {
      assert.equal(nodes(label, 'c:tx').length, 0);
      assert.ok(enabled(label, 'c:showVal'));
      assert.equal(enabled(label, 'c:showSerName'), labelIndex(label) === 0);
      const order = ['c:idx', 'c:numFmt', 'c:spPr', 'c:txPr', 'c:dLblPos', 'c:showLegendKey', 'c:showVal', 'c:showCatName', 'c:showSerName', 'c:showPercent', 'c:showBubbleSize', 'c:separator'];
      const actual = label.children.map((c) => order.indexOf(c.name));
      assert.ok(actual.every((n) => n >= 0));
      assert.deepEqual(actual, [...actual].sort((a, b) => a - b));
    }
  }
});

test('share: percent stacking keeps raw data and dynamic percentage formulas with contrast labels', async () => {
  const { zip } = await nativeDeck(), chart = await chartAt(zip, 4), model = prepare(visuals[3]);
  assert.equal(value(chart.root, 'c:grouping'), 'percentStacked');
  assert.equal(value(chart.root, 'c:barDir'), 'bar');
  assert.equal(value(one(chart.root, 'c:catAx'), 'c:orientation'), 'maxMin');
  const series = nodes(chart.root, 'c:ser');
  const book = await workbook(zip, chart), sheet = await xml(book, 'xl/worksheets/sheet1.xml');
  const cells = nodes(sheet, 'c'), raw = cells.filter((c) => !nodes(c, 'f').length).flatMap((c) => nodes(c, 'v').map(textOf));
  for (const v of visuals[3].rows.flatMap((r) => r.values)) assert.ok(raw.includes(String(v)), `raw value ${v}`);
  assert.ok(cells.some((c) => nodes(c, 'f').some((f) => /SUM\(/i.test(textOf(f)))), 'percent values must recalculate from raw data');
  const cellAt = (ref) => { const c = cells.find((cell) => cell.attrs.r === ref.replaceAll('$', '')); assert.ok(c, `missing ${ref}`); return c; };
  const calc = one(await xml(book, 'xl/workbook.xml'), 'calcPr');
  assert.equal(calc.attrs.fullCalcOnLoad, '1');
  for (let i = 0; i < series.length; i++) {
    const expected = model.categories[i].other ? T.fill.other.native.color : model.categories[i].color;
    assert.equal(one(one(series[i], 'c:spPr'), 'a:srgbClr').attrs.val, hex(expected));
    assert.ok(nodes(series[i], 'c:numFmt').some((f) => f.attrs.formatCode.includes('%')));
    assert.equal(nodes(series[i], 'c:dLbl').flatMap((l) => nodes(l, 'c:tx')).length, 0);
    const cached = cacheValues(one(one(series[i], 'c:val'), 'c:numCache'));
    for (let row = 0; row < cached.length; row++) assert.ok(Math.abs(Number(cached[row].value) - model.rows[row].segments[i].share) < 1e-12);
    const range = textOf(one(one(series[i], 'c:val'), 'c:f')).match(/!\$?([A-Z]+)\$?(\d+):\$?\1\$?(\d+)$/);
    assert.ok(range, 'chart references a worksheet column');
    for (let row = Number(range[2]); row <= Number(range[3]); row++) {
      const cell = cellAt(`${range[1]}${row}`), formula = textOf(one(cell, 'f'));
      const numerator = formula.match(/IFERROR\((\$?[A-Z]+\$?\d+)\s*\/\s*SUM\(/i)?.[1];
      assert.ok(numerator, 'chart value must use a percentage formula');
      assert.equal(Number(textOf(one(cellAt(numerator), 'v'))), model.rows[row - Number(range[2])].segments[i].value);
      assert.equal(Number(textOf(one(cell, 'v'))), Number(cached[row - Number(range[2])].value));
    }
    const labels = one(series[i], 'c:dLbls');
    assert.ok(nodes(labels, 'a:srgbClr').some((c) => c.attrs.val === hex(textOn(expected))), 'label contrast follows textOn');
    assert.ok(enabled(labels, 'c:showVal'));
  }
});

test('scatter: point labels contain names as the explicit static-text exception', async () => {
  const { zip } = await nativeDeck(), { root } = await chartAt(zip, 5);
  const labels = nodes(root, 'c:dLbl');
  assert.equal(labels.length, visuals[4].points.length);
  assert.deepEqual(labels.map((l) => textOf(one(l, 'c:tx'))), visuals[4].points.map((p) => p.label));
});

test('native table maps model cells, emphasis, alignment, text sizes, and total rule', async () => {
  const { zip } = await nativeDeck(), root = await xml(zip, 'ppt/slides/slide6.xml');
  const rows = nodes(one(root, 'a:tbl'), 'a:tr'), model = prepare(visuals[5]);
  assert.equal(rows.length, model.rows.length + 1);
  for (let r = 0; r < rows.length; r++) {
    const cells = children(rows[r], 'a:tc'), source = r ? model.rows[r - 1].cells : model.header;
    assert.deepEqual(cells.map((c) => nodes(c, 'a:t').map(textOf).join('')), source.map((c) => c.text));
    for (let c = 0; c < cells.length; c++) {
      const expectedSize = (r ? T.type.tableBody.px : T.type.tableHeader.px) / T.slide.pxPerPt * 100;
      assert.ok(nodes(cells[c], 'a:rPr').some((p) => Number(p.attrs.sz) === expectedSize));
      assert.ok(nodes(cells[c], 'a:pPr').some((p) => p.attrs.algn === (source[c].align === 'end' ? 'r' : 'l')));
      assert.ok(nodes(one(cells[c], 'a:rPr'), 'a:srgbClr').some((p) => p.attrs.val === hex(r ? source[c].color : C.textSecondary)));
      if (r && model.rows[r - 1].bold) assert.ok(nodes(cells[c], 'a:rPr').some((p) => p.attrs.b === '1'));
      if (r && model.rows[r - 1].fill) assert.ok(nodes(one(cells[c], 'a:tcPr'), 'a:srgbClr').some((p) => p.attrs.val === hex(model.rows[r - 1].fill)));
    }
  }
  const totalRule = nodes(rows.at(-2), 'a:lnB');
  assert.ok(totalRule.some((line) => nodes(line, 'a:srgbClr').some((color) => color.attrs.val === hex(C.text))));
});

test('all eight SVG-only charts have real PNG fallbacks linked by their slide', async () => {
  const { zip } = await svgDeck();
  assert.equal(files(zip, /^ppt\/charts\/chart\d+\.xml$/).length, 0);
  assert.equal(files(zip, /^ppt\/media\/.*\.svg$/).length, svgKinds.length);
  for (let n = 1; n <= svgKinds.length; n++) {
    const slideName = `ppt/slides/slide${n}.xml`, slide = await xml(zip, slideName);
    const image = one(slide, 'p:pic');
    const svg = one(image, 'asvg:svgBlip'), fallback = one(image, 'a:blip');
    const svgName = await related(zip, slideName, svg.attrs['r:embed']), pngName = await related(zip, slideName, fallback.attrs['r:embed']);
    assert.match(svgName, /\.svg$/);
    assert.match(pngName, /\.png$/);
    const png = await zip.file(pngName).async('nodebuffer');
    assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
    assert.ok((await zip.file(svgName).async('string')).includes(SLIDE_FONT));
  }
});

test('tiny nonzero values fall back to SVG with a warning, including negative values', async () => {
  const specs = [
    { kind: 'rank', rows: [{ label: '甲', value: 0.001 }] },
    { kind: 'line', x: ['一', '二'], series: [{ name: '甲', values: [-0.001, 1] }] },
    { kind: 'slope', periods: ['前', '後'], rows: [{ label: '甲', values: [1, 0.001] }] },
    { kind: 'share', categories: ['甲', '乙'], rows: [{ label: '北', values: [0.001, 100] }] },
    { kind: 'scatter', points: [{ label: '甲', x: 0.001, y: 1 }, { label: '乙', x: 2, y: 2 }] },
  ];
  const { zip, warnings } = await deck(specs.map(evidence));
  assert.equal(files(zip, /^ppt\/charts\/chart\d+\.xml$/).length, 0);
  assert.equal(files(zip, /^ppt\/media\/.*\.svg$/).length, specs.length);
  for (let n = 1; n <= specs.length; n++) assert.ok(warnings.some((w) => w.includes(`第 ${n} 頁`) && /SVG/.test(w)), `page ${n}: fallback warning`);
});

test('native:false forces SVG for all five chart kinds and table', async () => {
  const { zip } = await deck(visuals.map((v) => evidence({ ...v, native: false })));
  assert.equal(files(zip, /^ppt\/charts\/chart\d+\.xml$/).length, 0);
  assert.equal(files(zip, /^ppt\/media\/.*\.svg$/).length, visuals.length);
  assert.equal(nodes(await xml(zip, 'ppt/slides/slide6.xml'), 'a:tbl').length, 0);
});

test('steps, comparison, and close warn when their rows cannot fit text', async () => {
  const many = Array.from({ length: 12 }, (_, i) => `工作項目 ${i + 1}`);
  const pages = [
    { type: 'steps', claim: '時程', visual: { start: '2026-01', end: '2026-12', phases: many.map((name) => ({ name, note: '需完成審核', from: '2026-01', to: '2026-03' })) } },
    { type: 'compare', claim: '方案', visual: { rows: many, options: [{ name: '甲', values: many }, { name: '乙', values: many }] } },
    { type: 'close', claim: '決議', visual: { rows: many.map((task) => ({ task, owner: '負責人', due: '月底' })) } },
  ];
  const { warnings } = await deck(pages);
  for (let n = 1; n <= pages.length; n++) assert.ok(warnings.some((w) => w.includes(`第 ${n} 頁`) && /visual\..*估算 \d+ 行，上限 \d+ 行.*超出容量/.test(w)), `page ${n}: row height warning`);
});

test('string number tiles display verbatim and do not calculate a delta or warn about better', async () => {
  const { zip, warnings } = await deck([{ type: 'numbers', claim: '經費', visual: { items: [{ label: '方案甲', value: 'NT$ 600 萬', prev: 500 }, { label: '方案乙', value: '尚待估算', prev: 1 }] } }]);
  const root = await xml(zip, 'ppt/slides/slide1.xml'), content = textOf(root);
  assert.ok(content.includes('NT$ 600 萬'));
  assert.ok(content.includes('尚待估算'));
  assert.doesNotMatch(content, /NaN|[+＋]100|−|±0/);
  assert.ok(!warnings.some((w) => /better|前期/.test(w)));
});

test('scatter uses each axis precision for small values instead of the default label digits', async () => {
  const spec = { kind: 'scatter', points: [{ label: '甲', x: 0.1, y: 0.3 }, { label: '乙', x: 0.2, y: 0.6 }] };
  const { zip, warnings } = await deck([evidence(spec)]), model = prepare(spec);
  assert.equal(files(zip, /^ppt\/media\/.*\.svg$/).length, 0);
  assert.ok(!warnings.some((w) => /SVG/.test(w)));
  const { root } = await chartAt(zip, 1), axes = nodes(root, 'c:valAx');
  assert.equal(axes.length, 2);
  for (const [i, axis] of [model.xAxis, model.yAxis].entries()) {
    assert.equal(formatDigits(one(axes[i], 'c:numFmt').attrs.formatCode), decimalsOf(axis.ticks));
    assert.ok(Math.abs(Number(value(axes[i], 'c:min')) - (axis.lo - axis.step)) < 1e-12);
    assert.ok(Math.abs(Number(value(axes[i], 'c:max')) - (axis.hi + axis.step)) < 1e-12);
    assert.equal(Number(value(axes[i], 'c:majorUnit')), axis.step);
  }
});

test('zero, negative, empty-series, trailing-gap and one-sided slope values preserve editable data', async () => {
  const specs = [
    { kind: 'line', focus: '主線', x: ['一', '二', '三', '四'], series: [{ name: '主線', values: [0, -4, 2, null] }, { name: '缺值', values: [null, null, null, null] }] },
    { kind: 'slope', periods: ['前', '後'], rows: [{ label: '僅前', values: [-2, null] }, { label: '僅後', values: [null, 0] }, { label: '完整', values: [0, 4] }] },
  ];
  const { zip } = await deck(specs.map(evidence)), line = await chartAt(zip, 1), series = nodes(line.root, 'c:ser');
  assert.deepEqual(cacheValues(one(one(series[0], 'c:val'), 'c:numCache')), [{ index: 0, value: '0' }, { index: 1, value: '-4' }, { index: 2, value: '2' }]);
  assert.deepEqual(cacheValues(one(one(series[1], 'c:val'), 'c:numCache')), []);
  assert.deepEqual(nodes(series[0], 'c:dLbl').filter((l) => enabled(l, 'c:showVal') || enabled(l, 'c:showSerName')).map(labelIndex), [2]);
  assert.equal(nodes(series[1], 'c:dLbl').filter((l) => enabled(l, 'c:showVal') || enabled(l, 'c:showSerName')).length, 0);
  assert.equal(children(one(series[1], 'c:dLbls'), 'c:showVal')[0]?.attrs.val, '0');
  const book = await workbook(zip, line), sheet = await xml(book, 'xl/worksheets/sheet1.xml'), cells = nodes(sheet, 'c');
  for (const [ref, val] of [['B2', '0'], ['B3', '-4'], ['B4', '2']]) assert.equal(cellValue(cells, ref), val);
  for (const ref of ['B5', 'C2', 'C3', 'C4', 'C5']) assert.ok(!cells.some((c) => c.attrs.r === ref), `missing cell ${ref}`);
  const slope = await chartAt(zip, 2), slopes = nodes(slope.root, 'c:ser');
  for (const [i, row] of specs[1].rows.entries()) {
    const expected = row.values.flatMap((v, index) => v === null ? [] : [{ index, value: String(v) }]);
    assert.deepEqual(cacheValues(one(one(slopes[i], 'c:val'), 'c:numCache')), expected);
    assert.deepEqual(children(slopes[i], 'c:dPt').map((p) => Number(value(p, 'c:idx'))), expected.map((p) => p.index));
    assert.deepEqual(nodes(slopes[i], 'c:dLbl').map(labelIndex), expected.map((p) => p.index));
  }
  const slopeSheet = await xml(await workbook(zip, slope), 'xl/worksheets/sheet1.xml'), slopeCells = nodes(slopeSheet, 'c');
  for (const ref of ['B3', 'C2']) assert.ok(!slopeCells.some((c) => c.attrs.r === ref));
  for (const [ref, val] of [['B2', '-2'], ['C3', '0'], ['D2', '0'], ['D3', '4']]) assert.equal(cellValue(slopeCells, ref), val);
});

test('author and static scatter names preserve XML characters and replacement-dollar text', async () => {
  const special = '甲 $& <乙> & "quote"';
  const spec = { kind: 'scatter', focus: special, points: [{ label: special, x: 1, y: 2 }, { label: '丙', x: 2, y: 3 }] };
  const { zip } = await deck([evidence(spec)], { author: special });
  for (const name of files(zip, /\.xml$/)) parseXml(await zip.file(name).async('string'));
  const core = await xml(zip, 'docProps/core.xml');
  assert.equal(textOf(one(core, 'dc:creator')), special);
  assert.equal(textOf(one(core, 'cp:lastModifiedBy')), special);
  const chart = await chartAt(zip, 1);
  assert.equal(textOf(one(nodes(chart.root, 'c:dLbl')[0], 'c:tx')), special);
  const book = await workbook(zip, chart);
  for (const name of files(book, /\.xml$/)) parseXml(await book.file(name).async('string'));
  const author = await xml(book, 'docProps/core.xml');
  assert.equal(textOf(one(author, 'dc:creator')), special);
  assert.equal(textOf(one(author, 'cp:lastModifiedBy')), special);
});

test('rank, share and scatter workbooks keep observed zeros, and scatter suffixes do not scale data', async () => {
  const specs = [
    { kind: 'rank', sort: false, rows: [{ label: '零', value: 0 }, { label: '負', value: -3 }] },
    { kind: 'share', categories: ['甲', '乙'], rows: [{ label: '北', values: [0, 2] }, { label: '南', values: [0, 0] }] },
    { kind: 'scatter', suffix: '%', points: [{ label: '零', x: 0, y: 0 }, { label: '一', x: 1, y: 2 }] },
  ];
  const { zip } = await deck(specs.map(evidence));
  for (const [i, refs] of [['B2'], ['B2', 'B3', 'C3'], ['A2', 'B2']].entries()) {
    const chart = await chartAt(zip, i + 1), book = await workbook(zip, chart);
    const cells = nodes(await xml(book, 'xl/worksheets/sheet1.xml'), 'c');
    for (const ref of refs) assert.equal(cellValue(cells, ref), '0');
  }
  const scatter = await chartAt(zip, 3), axes = nodes(scatter.root, 'c:valAx');
  assert.ok(!one(axes[0], 'c:numFmt').attrs.formatCode.includes('%'));
  assert.ok(one(axes[1], 'c:numFmt').attrs.formatCode.includes('"%"'));
  for (const axis of axes) assert.equal(value(axis, 'c:majorTickMark'), 'out');
});

// PowerPoint asks to repair a deck whose table cells use anchor="mid" (pptxgenjs only maps 'middle' to ctr).
test('table cells use a valid vertical anchor', async () => {
  const { buffer } = await build({ title: 't', pages: [{ type: 'evidence', claim: 'x', visual: example('table') }] });
  const zip = await JSZip.loadAsync(buffer);
  const slide = await zip.file('ppt/slides/slide1.xml').async('string');
  const anchors = [...slide.matchAll(/<a:tcPr[^>]*\banchor="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(anchors.length > 0);
  assert.ok(anchors.every((a) => ['t', 'ctr', 'b'].includes(a)), anchors.join(','));
});

test('every numeric point label has its own number format in OOXML order', async () => {
  const specs = [0, 2].flatMap((digits) => visuals.slice(0, 4).map((v) => ({ ...v, digits })));
  const { zip } = await deck(specs.map(evidence));
  for (const [i, spec] of specs.entries()) {
    const { root } = await chartAt(zip, i + 1), labels = nodes(root, 'c:dLbl');
    assert.ok(labels.length, `${spec.kind}: missing point labels`);
    const unit = spec.kind === 'share' ? '%' : '';
    const n = `${unit ? '0' : '#,##0'}${spec.digits ? '.00' : ''}${unit}`;
    for (const label of labels) {
      const formats = children(label, 'c:numFmt');
      assert.equal(formats.length, 1, `${spec.kind}: point ${labelIndex(label)} needs its own format`);
      assert.equal(formats[0].attrs.formatCode, `${n};−${n};0${unit}`);
      assert.equal(formats[0].attrs.sourceLinked, '0');
      // Bar-end labels add a background box (c:spPr), which the schema places between numFmt and txPr.
      const names = label.children.map((c) => c.name), box = names.includes('c:spPr') ? ['c:spPr'] : [];
      assert.deepEqual(names.slice(0, 3 + box.length), ['c:idx', 'c:numFmt', ...box, 'c:txPr']);
      assert.equal(children(label, 'c:tx').length, 0, 'numeric labels remain linked to data');
    }
  }
  const scatter = await chartAt((await nativeDeck()).zip, 5);
  for (const label of nodes(scatter.root, 'c:dLbl')) {
    assert.equal(children(label, 'c:tx').length, 1);
    assert.equal(children(label, 'c:numFmt').length, 0);
  }
});

// The value axis crosses the reversed category axis at its last category, which sits at the bottom.
// (Putting crosses="max" on the category axis instead moves the categories to the right and flips the bars.)
test('rank and share keep the value axis below reversed categories', async () => {
  const { zip } = await nativeDeck();
  for (const n of [1, 4]) {
    const { root } = await chartAt(zip, n), catAxis = one(root, 'c:catAx');
    assert.equal(value(catAxis, 'c:orientation'), 'maxMin');
    assert.equal(value(catAxis, 'c:crosses'), 'autoZero');
    assert.equal(value(one(root, 'c:valAx'), 'c:crosses'), 'max');
    assert.equal(value(one(root, 'c:valAx'), 'c:tickLblPos'), 'nextTo', 'labels follow the axis instead of the low end');
  }
  for (const n of [2, 3]) {
    const { root } = await chartAt(zip, n);
    assert.equal(value(one(root, 'c:catAx'), 'c:crosses'), 'autoZero');
  }
});

test('rank, line and slope keep automatic maxima; share retains its percentage domain', async () => {
  const { zip } = await nativeDeck();
  for (const n of [1, 2, 3]) {
    const { root } = await chartAt(zip, n), axis = one(root, 'c:valAx'), model = prepare(visuals[n - 1]);
    assert.equal(nodes(axis, 'c:max').length, 0, `${model.kind}: maximum must follow edited data`);
    assert.equal(Number(value(axis, 'c:min')), model.axis.lo);
    assert.equal(Number(value(axis, 'c:majorUnit')), model.axis.step);
  }
  const axis = one((await chartAt(zip, 4)).root, 'c:valAx');
  assert.equal(Number(value(axis, 'c:min')), 0);
  assert.equal(Number(value(axis, 'c:max')), 1);
});

test('scatter pads only occupied axis boundaries by one step without changing data', async () => {
  const specs = [[0, 10], [0, 9], [1, 10], [1.2, 9.2]].map(([a, b]) => ({
    kind: 'scatter', points: [{ label: '甲', x: a, y: a }, { label: '乙', x: b, y: b }],
  }));
  const before = structuredClone(specs), { zip } = await deck(specs.map(evidence));
  for (const [n, spec] of specs.entries()) {
    const { root } = await chartAt(zip, n + 1), axes = nodes(root, 'c:valAx'), model = prepare(spec);
    for (const [i, a] of [model.xAxis, model.yAxis].entries()) {
      const key = i === 0 ? 'x' : 'y';
      const atLo = spec.points.some((p) => p[key] === a.lo), atHi = spec.points.some((p) => p[key] === a.hi);
      assert.equal(Number(value(axes[i], 'c:min')), atLo ? a.lo - a.step : a.lo);
      if (atHi) assert.equal(Number(value(axes[i], 'c:max')), a.hi + a.step);
      else assert.equal(nodes(axes[i], 'c:max').length, 0, 'unpadded upper boundary stays automatic');
      assert.equal(Number(value(axes[i], 'c:majorUnit')), a.step);
    }
    assert.deepEqual(cacheValues(one(root, 'c:xVal')).map((p) => Number(p.value)), spec.points.map((p) => p.x));
    assert.deepEqual(cacheValues(one(root, 'c:yVal')).map((p) => Number(p.value)), spec.points.map((p) => p.y));
  }
  assert.deepEqual(specs, before);
});

test('scatter preserves references in SVG, while an empty refs array keeps editable data', async () => {
  const base = example('scatter');
  const spec = { ...base, refs: [...base.refs, { x: 32, label: '車柱門檻' }] };
  const tiny = { ...base, refs: [], points: [{ label: '甲', x: 0.001, y: 1 }, { label: '乙', x: 2, y: 2 }] };
  const { warnings, zip } = await deck([spec, { ...spec, native: false }, { ...spec, refs: [] }, tiny, { ...spec, native: true }].map(evidence));
  const refs = warnings.filter((w) => w.includes('以 SVG 保留參考線'));
  assert.deepEqual(refs.map((warning) => Number(warning.match(/第 (\d+) 頁/)[1])), [1, 5]);
  assert.ok(warnings.some((warning) => warning.includes('第 4 頁') && warning.includes('非零極小值')));
  for (const n of [1, 2, 4, 5]) assert.match(await zip.file(`ppt/slides/slide${n}.xml`).async('string'), /svgBlip/);
  const svgs = await Promise.all(files(zip, /^ppt\/media\/.*\.svg$/).map((name) => zip.file(name).async('string')));
  assert.ok(svgs.some((svg) => svg.includes('車柱門檻') && svg.includes('全市平均') && svg.includes('stroke-dasharray')));
  const native = await chartAt(zip, 3);
  one(native.root, 'c:scatterChart');
  assert.ok(await workbook(zip, native));
});

test('native slope hides its value axis and gridlines', async () => {
  const { zip } = await nativeDeck(), axis = one((await chartAt(zip, 3)).root, 'c:valAx');
  assert.equal(value(axis, 'c:delete'), '1');
  assert.equal(nodes(axis, 'c:majorGridlines').length, 0);
  const lineAxis = one((await chartAt(zip, 2)).root, 'c:valAx');
  assert.equal(value(lineAxis, 'c:delete'), '0');
  assert.equal(nodes(lineAxis, 'c:majorGridlines').length, 1);
});

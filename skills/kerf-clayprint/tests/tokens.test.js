import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { textOn } from '../scripts/core.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const moduleUrl = (name) => new URL(`../scripts/${name}.js`, import.meta.url).href;
const readDesign = (name = 'tokens.json') => JSON.parse(readFileSync(path.join(root, 'design', name), 'utf8'));

function run(code, { cwd = root, tokens } = {}) {
  const env = { ...process.env };
  delete env.CLAYPRINT_TOKENS;
  delete env.CLAYPRINT_MODE;
  if (tokens !== undefined) env.CLAYPRINT_TOKENS = tokens;
  return spawnSync(process.execPath, ['--input-type=module', '-e', code], { cwd, env, encoding: 'utf8' });
}

function result(child) {
  assert.equal(child.status, 0, child.stderr || child.error?.message);
  return JSON.parse(child.stdout);
}

function withDesign(design, code) {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-tokens-'));
  try {
    const file = path.join(dir, 'tokens.json');
    writeFileSync(file, JSON.stringify(design));
    return run(code, { tokens: file });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test('設計層預設路徑不受工作目錄影響，環境變數支援相對與絕對路徑', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-loader-'));
  const code = `import { loadTokens } from ${JSON.stringify(moduleUrl('tokens'))}; console.log(JSON.stringify(loadTokens()));`;
  try {
    assert.deepEqual(result(run(code, { cwd: dir })), readDesign());
    const custom = { ...readDesign(), name: '自訂設計層' };
    const file = path.join(dir, 'custom.json');
    writeFileSync(file, JSON.stringify(custom));
    for (const tokens of ['custom.json', file]) {
      assert.deepEqual(result(run(code, { cwd: dir, tokens })), custom);
    }
    const explicit = code.replace('loadTokens()', "loadTokens('custom.json')");
    assert.deepEqual(result(run(explicit, { cwd: dir, tokens: '不存在.json' })), custom);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('設計層讀取與 JSON 錯誤提供中文原因及檔案位置', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-loader-'));
  try {
    writeFileSync(path.join(dir, 'broken.json'), '{');
    for (const [name, reason] of [['missing.json', /讀取|開啟/], ['broken.json', /JSON/]]) {
      const child = run(`import { loadTokens } from ${JSON.stringify(moduleUrl('tokens'))}; loadTokens(${JSON.stringify(name)});`, { cwd: dir });
      assert.notEqual(child.status, 0);
      assert.match(child.stderr, /設計層/);
      assert.match(child.stderr, reason);
      assert.ok(child.stderr.includes(name), child.stderr);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('色塊字色優先依對照表，未列出的顏色選對比最高的正文或淺色', () => {
  const design = {
    color: { text: '#000000', onDark: ['#FFFFFF'] },
    textOnFill: { '#222222': ['#ABCDEF'] },
  };
  assert.equal(textOn('#abcdef', design), '#222222');
  assert.equal(textOn('#FEFEFE', design), '#000000');
  assert.equal(textOn('#010101', design), '#FFFFFF');
});

const inspectPalette = `
  import { categoryLimit, categoryColors, heatBins, prepare } from ${JSON.stringify(moduleUrl('core'))};
  import { render } from ${JSON.stringify(moduleUrl('svg'))};
  const names = ['甲', '乙', '丙', '丁'];
  const colors = categoryColors(names);
  const share = prepare({ kind: 'share', categories: names, rows: [{ label: '總計', values: [1, 2, 3, 4] }] });
  const spec = { kind: 'heat', rowLabels: ['列'], colLabels: ['甲', '乙', '丙'], values: [[0, 3, 6]] };
  const heat = prepare(spec);
  console.log(JSON.stringify({
    limit: categoryLimit(), colors: [...colors.colors], folded: colors.folded,
    share, heat, edges: heatBins([0, 6]).edges,
    explicitEdges: heatBins([0, 6], 2).edges, svg: render(spec),
  }));
`;

test('較短的分類與順序色盤限制折疊和圖例，所有圖形都有有效色碼', () => {
  const design = readDesign();
  design.color.categorical = design.color.categorical.slice(0, 2);
  design.color.ordered = design.color.ordered.slice(0, 3);
  const actual = result(withDesign(design, inspectPalette));
  assert.equal(actual.limit, 2);
  assert.deepEqual(actual.folded, ['丙', '丁']);
  assert.deepEqual(actual.colors.map(([, color]) => color), [...design.color.categorical, design.color.other]);
  assert.deepEqual(actual.share.rows[0].segments.map((s) => s.value), [1, 2, 7]);
  assert.deepEqual(actual.heat.legend.map((item) => item.color), design.color.ordered);
  assert.deepEqual(actual.heat.cells[0].map((cell) => cell.color), design.color.ordered);
  assert.deepEqual(actual.edges, [0, 2, 4, 6]);
  assert.deepEqual(actual.explicitEdges, [0, 3, 6]);
  assert.doesNotMatch(JSON.stringify(actual), /undefined|NaN/);
});

test('分類上限與熱度階數較小時，以設定值限制色盤使用量', () => {
  const design = readDesign();
  design.categoryRules.maxCategorical = 1;
  design.heatmap.steps = 2;
  const actual = result(withDesign(design, inspectPalette));
  assert.equal(actual.limit, 1);
  assert.deepEqual(actual.folded, ['乙', '丙', '丁']);
  assert.deepEqual(actual.share.rows[0].segments.map((s) => s.value), [1, 9]);
  assert.deepEqual(actual.heat.legend.map((item) => item.color), design.color.ordered.slice(0, 2));
  assert.deepEqual(actual.edges, [0, 3, 6]);
});

test('空的分類色盤、無效分類上限與不足兩階的順序色盤明確報錯', () => {
  for (const [change, call, token] of [
    [(d) => { d.color.categorical = []; }, "categoryColors(['甲'])", /categorical/],
    [(d) => { d.categoryRules.maxCategorical = 0; }, "categoryColors(['甲'])", /maxCategorical/],
    [(d) => { d.color.ordered = d.color.ordered.slice(0, 1); }, 'heatBins([0, 6])', /ordered/],
  ]) {
    const design = readDesign();
    change(design);
    const child = withDesign(design, `import { categoryColors, heatBins } from ${JSON.stringify(moduleUrl('core'))}; ${call};`);
    assert.notEqual(child.status, 0);
    assert.match(child.stderr, token);
    assert.match(child.stderr, /[\u4E00-\u9FFF]/);
  }
});

test('環境變數切換藍色設計層後，實際 build 的投影片底色與原生圖表皆套用藍色', () => {
  const clay = readDesign(), blue = readDesign('tokens.blue.json');
  const code = `
    import { build } from ${JSON.stringify(moduleUrl('pptx'))};
    import JSZip from 'jszip';
    const { buffer } = await build({ pages: [
      { type: 'statement', claim: '測試設計層' },
      { type: 'evidence', claim: '資料比較', visual: { kind: 'rank', rows: [{ label: '甲', value: 2 }, { label: '乙', value: 1 }] } },
    ] });
    const zip = await JSZip.loadAsync(buffer);
    const slide = await zip.file('ppt/slides/slide1.xml').async('string');
    const charts = await Promise.all(Object.keys(zip.files).filter((name) => /^ppt\\/charts\\/chart\\d+\\.xml$/.test(name)).map((name) => zip.file(name).async('string')));
    console.log(JSON.stringify({ slide, charts }));
  `;
  const actual = result(run(code, { tokens: 'design/tokens.blue.json' }));
  const hex = (color) => color.slice(1).toUpperCase();
  const background = actual.slide.match(/<p:bg>[\s\S]*?<a:srgbClr val="([^"]+)"/);
  assert.ok(background, '產物必須包含明確的投影片底色');
  assert.equal(background[1], hex(blue.color.onDark[0]));
  if (clay.color.onDark[0] !== blue.color.onDark[0]) assert.notEqual(background[1], hex(clay.color.onDark[0]));
  assert.equal(actual.charts.length, 1);
  assert.ok(actual.charts[0].includes(`val="${hex(blue.color.focus)}"`));
  if (clay.color.focus !== blue.color.focus) assert.ok(!actual.charts[0].includes(`val="${hex(clay.color.focus)}"`));
});

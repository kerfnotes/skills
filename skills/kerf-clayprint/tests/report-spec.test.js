import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildReport } from '../scripts/report.js';
import { checkReport } from '../evals/check-report.mjs';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { check } from '../evals/check.mjs';

const source = '甲 2 件，乙 3 件。來源：虛構稿。';
const share = { kind: 'share', categories: ['甲', '乙'], rows: [{ label: '本期', values: [2, 3] }], source: '虛構稿' };
const chart = (spec = share) => ({ type: 'chart', title: '組成', chart: spec });
const report = (...blocks) => ({ title: '報告', message: '比較組成', sections: [{ claim: '組成比較', blocks }] });

test('原稿件數生成的比例僅在對應報告圖表通過；legacy 保持嚴格', () => {
  const spec = report(chart());
  const { html } = buildReport(spec);
  assert.match(html, />40%<|>40 %</);
  assert.throws(() => checkReport(html, source), /40/);
  assert.equal(checkReport(html, source, { report: spec }).figures, 1);
});

test('同節可見加減算式核對後可作為圖表原值', () => {
  for (const [equation, value] of [['2 + 3 = 5', 5], ['3 - 2 = 1', 1]]) {
    const spec = report({ type: 'text', text: `計算：${equation}` }, chart({ kind: 'rank', rows: [{ label: '合計', value }], source: '虛構稿' }));
    const { html } = buildReport(spec);
    assert.equal(checkReport(html, source).figures, 1);
    assert.equal(checkReport(html, source, { report: spec }).figures, 1);
  }
});

test('算式只授權交付 HTML 中對應的可見節，含摘要及自訂節 ID', () => {
  const total = chart({ kind: 'rank', rows: [{ label: '合計', value: 5 }], source: '虛構稿' });
  const equation = { type: 'text', text: '計算：2 + 3 = 5' };
  const spec = {
    ...report(equation, total), summary: { claim: '摘要', items: [{ label: '甲', value: '2' }] },
    sections: [{ id: 'context', claim: '背景', blocks: [{ type: 'text', text: '原稿內容' }] },
      { id: 'total', claim: '合計', blocks: [equation, total] }],
  };
  const { html } = buildReport(spec);
  assert.equal(checkReport(html, source, { report: spec }).figures, 1);
  for (const replacement of ['', '<span hidden>計算：2 + 3 = 5</span>', '<span style="display:none">計算：2 + 3 = 5</span>', '<span style="visibility:hidden">計算：2 + 3 = 5</span>']) {
    assert.throws(() => checkReport(html.replace('計算：2 + 3 = 5', replacement), source, { report: spec }), /sections\[1\].*原稿找不到數字 5/);
  }
  const elsewhere = { ...spec, sections: [
    { claim: '計算依據', blocks: [equation] }, { claim: '合計', blocks: [total] },
  ] };
  assert.throws(() => checkReport(buildReport(elsewhere).html, source, { report: elsewhere }), /sections\[1\].*原稿找不到數字 5/);
});

test('錯誤、未支援或原稿外運算元不能授權圖表，SVG 也不能提供算式', () => {
  for (const [equation, value, error] of [
    ['2 + 3 = 6', 6, /結果不符/], ['2 * 3 = 6', 6, /格式不支援/], ['2 + 4 = 6', 6, /4 不在原稿/],
  ]) {
    const spec = report({ type: 'text', text: `計算：${equation}` }, chart({ kind: 'rank', rows: [{ label: '合計', value }], source: '虛構稿' }));
    assert.throws(() => checkReport(buildReport(spec).html, source, { report: spec }), error);
  }
  const svgEquation = report(chart({ kind: 'rank', rows: [{ label: '計算：2 + 3 = 5', value: 5 }], source: '虛構稿' }));
  assert.throws(() => checkReport(buildReport(svgEquation).html, source, { report: svgEquation }), /原稿找不到數字 5/);
  const bogus = { ...report(chart()), sections: [
    { claim: '組成', blocks: [chart(), { type: 'text', text: '計算：2 + 3 = 5' }] },
    { claim: '其他', blocks: [chart({ kind: 'rank', rows: [{ label: '偽值', value: 40 }], source: '虛構稿' })] },
  ] };
  assert.throws(() => checkReport(buildReport(bogus).html, source, { report: bogus }), /sections\[1\].*原稿找不到數字 40/);
});

test('跨圖換序與子集合維持文件類別色，報告與簡報一致', async () => {
  const reordered = { ...share, categories: ['乙', '甲'], rows: [{ label: '本期', values: [3, 2] }] };
  const subset = { ...share, categories: ['乙'], rows: [{ label: '本期', values: [3] }] };
  const { html } = buildReport(report(chart(), chart(reordered), chart(subset)));
  const svgs = html.match(/<svg\b[\s\S]*?<\/svg>/g);
  const legend = (svg, name) => svg.match(new RegExp(`<rect[^>]*fill="([^"]+)"[^>]*>\\s*<text[^>]*>${name}<`))?.[1];
  assert.ok(legend(svgs[0], '甲'));
  assert.equal(legend(svgs[0], '甲'), legend(svgs[1], '甲'));
  assert.equal(legend(svgs[0], '乙'), legend(svgs[2], '乙'));
  const story = { pages: [share, reordered, subset].map((visual) => ({ type: 'evidence', claim: '組成比較', visual, sources: { source: '虛構稿' } })) };
  const zip = await JSZip.loadAsync((await check(story, source)).buffer);
  for (let i = 0; i < 3; i++) {
    const xml = await zip.file(`ppt/charts/chart${i + 1}.xml`).async('string');
    for (const name of i === 2 ? ['乙'] : ['甲', '乙']) {
      const series = [...xml.matchAll(/<c:ser>[\s\S]*?<\/c:ser>/g)].map((m) => m[0]).find((s) => s.includes(`<c:v>${name}</c:v>`));
      assert.ok(series, name);
      assert.ok(series.includes(`val="${legend(svgs[i], name).slice(1)}"`));
    }
  }
});

test('衍生比例與其裸數別名不流到正文、摘要、標題或其他圖表', () => {
  const spec = report(chart(), { type: 'text', text: '原稿內容' }, chart({ kind: 'rank', rows: [{ label: '甲', value: 2 }], source: '虛構稿' }));
  const { html } = buildReport(spec);
  for (const token of ['40%', '40', '0.4', '60%', '0.6']) {
    assert.throws(() => checkReport(html.replace('原稿內容', `新增 ${token}`), source, { report: spec }), /原稿找不到數字/);
    assert.throws(() => checkReport(html.replace('<h1>報告', `<h1>${token} 報告`), source, { report: spec }), /原稿找不到數字/);
    assert.throws(() => checkReport(html.replace('<p class="cover-message">', `<p class="cover-message">${token} `), source, { report: spec }), /原稿找不到數字/);
    const svgs = [...html.matchAll(/<svg\b[\s\S]*?<\/svg>/g)];
    const tampered = html.slice(0, svgs[1].index) + svgs[1][0].replace('</svg>', `<text data-derived="true">${token}</text></svg>`) + html.slice(svgs[1].index + svgs[1][0].length);
    assert.throws(() => checkReport(tampered, source, { report: spec }), /第 2 張圖.*不匹配/);
  }
  const summary = { ...report(chart()), summary: { claim: '摘要', items: [{ label: '甲', value: '40%' }] } };
  assert.throws(() => checkReport(buildReport(summary).html, source, { report: summary }), /原稿找不到數字 40%/);
});

test('逐圖比對標籤、刻度與形狀，不信任自填豁免標記，也不容許移位', () => {
  const spec = report(chart(), { type: 'text', text: '原稿內容' });
  const { html } = buildReport(spec);
  for (const changed of [
    html.replace('>40%<', '>41%<'),
    html.replace('>40%<', '>60%<'),
    html.replace('>40%<', '>0.4<'),
    html.replace('>40%<', '>4000%<'),
    html.replace('>40%<', '>41%<').replace('<text ', '<text data-tick="1" data-derived="true" '),
    html.replace(/(<rect[^>]*width=")[^"]+/, (_, prefix) => `${prefix}999`),
    html.replace(/(<svg\b[\s\S]*?<\/svg>)/, '$1$1'),
    html.replace(/<svg\b[\s\S]*?<\/svg>/, ''),
  ]) assert.throws(() => checkReport(changed, source, { report: spec }), /圖.*不匹配/);
  const figure = html.match(/<figure[\s\S]*?<\/figure>/)[0];
  const moved = html.replace(figure, '').replace('<p>原稿內容</p>', `<p>原稿內容</p>${figure}`);
  assert.throws(() => checkReport(moved, source, { report: spec }), /位置.*不匹配/);
  assert.equal(checkReport(html.replaceAll('\n', '\r\n'), source, { report: spec }).figures, 1);
});

test('原值需先核對原稿；即使 HTML 與修改後輸入一致也不放行', () => {
  const spec = report(chart({ ...share, rows: [{ label: '本期', values: [4, 3] }] }));
  assert.throws(() => checkReport(buildReport(spec).html, source, { report: spec }), /sections\[0\].blocks\[0\].chart.rows\[0\].values\[0\].*4/);
  const changed = report(chart({ ...share, rows: [{ label: '本期', values: [3, 2] }] }));
  assert.throws(() => checkReport(buildReport(report(chart())).html, source, { report: changed }), /SVG.*不匹配/);
});


test('外部圖表相對 report.json 解析；缺檔、錯 JSON 與錯圖表都指出欄位', () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-spec-'));
  try {
    const spec = report(chart('nested/share.json'));
    mkdirSync(join(dir, 'nested'));
    for (const content of [undefined, '{bad', '{"kind":"share"}']) {
      if (content !== undefined) writeFileSync(join(dir, 'nested/share.json'), content);
      assert.throws(() => checkReport('<html></html>', source, { report: spec, baseDir: dir }), /sections\[0\].blocks\[0\].chart/);
    }
    writeFileSync(join(dir, 'nested/share.json'), JSON.stringify(share));
    writeFileSync(join(dir, 'nested/reordered.json'), JSON.stringify({ ...share, categories: ['乙', '甲'], rows: [{ label: '本期', values: [3, 2] }] }));
    const externalPair = report(chart('nested/share.json'), chart('nested/reordered.json'));
    const pairHtml = buildReport(externalPair, { baseDir: dir }).html;
    const pairSvgs = pairHtml.match(/<svg\b[\s\S]*?<\/svg>/g);
    assert.deepEqual(pairSvgs[0].match(/<rect[^>]*fill="#[^"]+"\/><text[^>]*>[^<]+/g).slice(0, 2), pairSvgs[1].match(/<rect[^>]*fill="#[^"]+"\/><text[^>]*>[^<]+/g).slice(0, 2));
    assert.equal(checkReport(pairHtml, source, { report: externalPair, baseDir: dir }).figures, 2);
    const { html } = buildReport(spec, { baseDir: dir });
    assert.equal(checkReport(html, source, { report: spec, baseDir: dir }).figures, 1);
    writeFileSync(join(dir, 'report.json'), JSON.stringify(spec));
    writeFileSync(join(dir, 'report.html'), html);
    writeFileSync(join(dir, 'script.md'), source);
    const run = (file) => spawnSync(process.execPath, ['evals/check-report.mjs', join(dir, 'report.html'), join(dir, 'script.md'), file], { encoding: 'utf8', cwd: new URL('..', import.meta.url) });
    const success = run(join(dir, 'report.json'));
    assert.equal(success.status, 0, success.stderr);
    const missing = run(join(dir, 'missing.json'));
    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /missing.json.*report.json/);
    writeFileSync(join(dir, 'report.json'), '{bad');
    assert.equal(run(join(dir, 'report.json')).status, 1);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});


test('超上限類別、既有其他與局部子集合沿用文件折疊與合併值', () => {
  const full = { ...share, categories: ['甲', '乙', '丙', '丁', '戊', '己', '其他'], rows: [{ label: '全部', values: [1, 2, 3, 4, 5, 6, 7] }] };
  const subset = { ...share, categories: ['戊', '其他', '乙'], rows: [{ label: '部分', values: [5, 7, 2] }] };
  const spec = report(chart(full), chart(subset));
  const { html, warnings } = buildReport(spec);
  const svgs = html.match(/<svg\b[\s\S]*?<\/svg>/g);
  assert.match(svgs[0], /width="585.64" height="60"/); // (5+6+7)/28, existing 其他 merged once
  assert.match(svgs[1], /width="780.86" height="60"/); // (5+7)/14; 戊 remains folded in subset
  assert.doesNotMatch(svgs[1], /<text[^>]*>戊</);
  assert.match(svgs[1], /<text[^>]*>其他</);
  assert.ok(warnings.some((w) => /整份報告.*戊、己/.test(w)));
  assert.equal(checkReport(html, '虛構稿 1 2 3 4 5 6 7', { report: spec }).figures, 2);
});

test('零、缺值、極小值與指定精度維持顯示；全零與負值限制不變', () => {
  const input = { ...share, digits: 2, rows: [
    { label: '缺值', values: [null, 1] },
    { label: '全零', values: [0, 0] },
    { label: '極小', values: [1e-101, 1] },
    { label: '精度', values: [0.125, 0.875] },
  ] };
  const spec = report(chart(input), chart({ kind: 'rank', digits: 2, rows: [{ label: '極小', value: 1e-101 }, { label: '精度', value: 0.125 }, { label: '零', value: 0 }], source: '虛構稿' }));
  const { html, warnings } = buildReport(spec);
  assert.match(html, /未提供：缺值 甲/);
  assert.match(html, /&lt;0.01/);
  assert.match(html, />12.50%</);
  assert.ok(warnings.some((w) => /各類都是 0/.test(w)));
  assert.equal(checkReport(html, '虛構稿 0 1 1e-101 0.125 0.875', { report: spec }).figures, 2);
  assert.throws(() => buildReport(report(chart({ ...share, rows: [{ label: '負值', values: [-1, 3] }] }))), /chart.*不能有負值/);
  const zero = report(chart({ ...share, kind: 'waffle', rows: undefined, values: [0, 0] }));
  assert.throws(() => buildReport(zero), /總和不能是 0/);
  // Tiny source observations cannot silently be replaced by zero or another tiny value.
  assert.throws(() => checkReport(html, '虛構稿 0 1 2e-101 0.125 0.875', { report: spec }), /1e-101/);
});

test('模型產生漏斗轉換、流失差額與箱型中位數，無須在原稿回填推導值', () => {
  const inputs = [
    { kind: 'funnel', loss: true, steps: [{ label: '起點', value: 5 }, { label: '終點', value: 2 }], source: '虛構稿' },
    { kind: 'box', digits: 1, groups: [{ label: '樣本', values: [1, 2, 5, 8] }], source: '虛構稿' },
  ];
  const spec = report(...inputs.map(chart));
  const { html } = buildReport(spec);
  assert.match(html, /40%/);
  assert.match(html, />3.5</);
  assert.equal(checkReport(html, '虛構稿 1 2 5 8', { report: spec }).figures, 2);
  assert.throws(() => checkReport(html.replace('>3.5<', '>3.6<'), '虛構稿 1 2 5 8', { report: spec }), /不匹配/);
});

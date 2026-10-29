import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildReport } from '../scripts/report.js';
import { checkReport } from '../evals/check-report.mjs';

const report = (...charts) => ({ title: '報告', message: '比較', sections: [{ claim: '比較', blocks: charts.map((chart, i) => ({ type: 'chart', title: `圖表${'甲乙丙'[i]}`, chart })) }] });
const tables = (html) => [...html.matchAll(/<figure[\s\S]*?<\/figure>/g)].map(([fig]) => fig.match(/<details class="chart-data">[\s\S]*?<\/details>/)?.[0] ?? null);
const cells = (table) => [...table.matchAll(/<t[hd](?:\s[^>]*)?>([\s\S]*?)<\/t[hd]>/g)].map(([, c]) => c);

test('每張圖在圖說下方附上輸入數字，缺值標未提供，開放組界寫「以上」；表格圖不重複', () => {
  const rank = { kind: 'rank', rows: [{ label: '甲', value: 1200 }, { label: '乙', value: null }], source: '虛構稿' };
  const histogram = { kind: 'histogram', bins: [{ from: 0, to: 5, value: 3 }, { from: 5, to: null, value: 2 }], source: '虛構稿' };
  const table = { kind: 'table', columns: [{ name: '項目', type: 'text' }, { name: '件數', type: 'number' }], rows: [['甲', 2]], source: '虛構稿' };
  const [r, h, t] = tables(buildReport(report(rank, histogram, table)).html);
  assert.deepEqual(cells(r), ['', '數值', '甲', '1,200', '乙', '<span class="missing">未提供</span>']);
  assert.deepEqual(cells(h).slice(2), ['0–5', '3', '5 以上', '2']);
  assert.equal(t, null);
});

test('驗收器比對資料表與 report.json：手改數字被擋下，表內標籤不能提供算式', () => {
  const source = '甲 2 件，乙 3 件。來源：虛構稿。';
  const spec = report({ kind: 'rank', rows: [{ label: '甲', value: 2 }, { label: '乙', value: 3 }], source: '虛構稿' });
  const { html } = buildReport(spec);
  assert.equal(checkReport(html, source, { report: spec }).figures, 1);
  const edited = html.replace('<td class="num">3</td>', '<td class="num">2</td>');
  assert.throws(() => checkReport(edited, source, { report: spec }), /第 1 張圖 資料表或位置與 report\.json/);
  const labelled = report({ kind: 'rank', rows: [{ label: '計算：2 + 3 = 5', value: 5 }], source: '虛構稿' });
  assert.throws(() => checkReport(buildReport(labelled).html, source, { report: labelled }), /原稿找不到數字 5/);
});

test('資料表照圖表 JSON 原樣列數字：組界與數值不依 digits 進位，舊模式驗收也找得到原稿數字', () => {
  const histogram = { kind: 'histogram', digits: 0, bins: [{ from: 0, to: 2.5, value: 4 }, { from: 2.5, to: 5, value: 12.5 }], source: '虛構稿' };
  const { html } = buildReport(report(histogram));
  assert.deepEqual(cells(tables(html)[0]).slice(2), ['0–2.5', '4', '2.5–5', '12.5']);
  const source = '0 到 2.5 有 4 筆，2.5 到 5 有 12.5 筆，圖上取整為 13。來源：虛構稿。';
  assert.equal(checkReport(html, source).figures, 1);
});

test('選填欄位不標成缺值：五數摘要逐項標名、沒有背景區間不出欄位；參考線附位置，比率預設單位 %', () => {
  const box = { kind: 'box', groups: [{ label: '甲', summary: [1, 2, 3, 4, 5], outliers: [9] }], source: '虛構稿' };
  const bullet = { kind: 'bullet', rows: [{ label: '甲', value: 8, target: 10 }], source: '虛構稿' };
  const scatter = { kind: 'scatter', xLabel: '成本', points: [{ label: '甲', x: 1, y: 2 }, { label: '乙', x: 3, y: 4 }], refs: [{ x: 2, label: '平均' }], native: false, source: '虛構稿' };
  const [b, u, s] = tables(buildReport(report(box, bullet, scatter)).html);
  assert.deepEqual(cells(b).slice(2), ['甲', '最小值 1、第一四分位 2、中位數 3、第三四分位 4、最大值 5；離群值 9']);
  assert.deepEqual(cells(u), ['', '實際', '目標', '甲', '8', '10']);
  assert.match(s, /<p>參考線「平均」：成本 2<\/p>/);
  const combo = { kind: 'combo', unit: '億元', x: ['甲', '乙'], amounts: [1, 2], rates: [3, 4], source: '虛構稿' };
  assert.deepEqual(cells(tables(buildReport(report(combo)).html)[0]).slice(0, 3), ['', '金額（億元）', '比率（%）']);
});

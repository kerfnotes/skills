import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { T, C, prepare, categoryColors, borrowedNotice } from '../scripts/core.js';
import { render } from '../scripts/svg.js';
import { buildReport } from '../scripts/report.js';

const [up, down] = [T.delta.signs.increase, T.delta.signs.decrease];
const example = JSON.parse(readFileSync(new URL('../examples/contrib.json', import.meta.url), 'utf8'));

test('contrib：正負各自從零堆疊，合計是各段加總', () => {
  const m = prepare(example);
  const harbor = m.rows.find((r) => r.label === '港南區');
  assert.equal(harbor.net, 7);
  assert.equal(harbor.netText, `${up}7`);
  assert.deepEqual(harbor.texts, [`${down}24`, `${up}31`]);
  assert.ok(m.axis.lo <= -24 && m.axis.hi >= 50, `axis ${m.axis.lo}–${m.axis.hi}`);
  assert.equal(m.rows.find((r) => r.label === '北岸區').netText, `${down}13`);
});

test('contrib：缺值保留該列與其餘段，不算合計', () => {
  const m = prepare({ ...example, rows: [{ label: '甲', values: [3, null] }, { label: '乙', values: [1, 2] }] });
  assert.deepEqual(m.missing, ['甲／休閒']);
  assert.equal(m.rows[0].netText, null);
  assert.equal(m.rows[1].netText, `${up}3`);
});

test('contrib：net: false 不畫合計欄', () => {
  const { svg } = render({ ...example, net: false });
  assert.doesNotMatch(svg, />合計</);
  assert.match(render(example).svg, />合計</);
});

test('contrib：範例沒有警告；窄的最外段把數字標在長條外側', () => {
  const { svg, model } = render(example);
  assert.deepEqual(model.warnings, []);
  for (const s of ['通勤', '休閒', `${up}42`, `${down}24`, `${up}31`, `${down}6`, `${up}5`]) assert.match(svg, new RegExp(`>${s.replace(/[+]/g, '\\+')}<`));
});

test('contrib：格式錯誤明確報錯', () => {
  assert.throws(() => prepare({ ...example, parts: ['只有一段'] }), /2～4 個 parts/);
  assert.throws(() => prepare({ ...example, rows: [{ label: '甲', values: [1] }] }), /values 長度/);
});

test('contrib：報告的查看資料逐列列出各段原值', () => {
  const { html } = buildReport({ title: 'T', message: 'M', sections: [{ claim: 'C', blocks: [{ type: 'chart', title: '拆解', chart: example }] }] });
  assert.match(html, /<th[^>]*>通勤<\/th>/);
  assert.match(html, /<td class="num">−24<\/td>/);
});

test('categoryColors：放得下的圖一律上色，超出共用色盤的類別借用本圖空著的顏色', () => {
  const order = ['甲', '乙', '丙', '丁', '戊', '己'];
  const r = categoryColors(['甲', '戊'], { order });
  assert.deepEqual(r.folded, []);
  assert.deepEqual(r.borrowed, ['戊']);
  assert.equal(r.colors.get('甲'), C.categorical[0]);
  assert.ok(C.categorical.includes(r.colors.get('戊')));
  assert.notEqual(r.colors.get('戊'), r.colors.get('甲'));
  assert.equal(r.colors.has('其他'), false);
});

test('categoryColors：共用色盤內的類別在每張圖同色', () => {
  const order = ['甲', '乙', '丙', '丁', '戊'];
  const a = categoryColors(['乙', '戊'], { order }), b = categoryColors(['丙', '乙'], { order });
  assert.equal(a.colors.get('乙'), b.colors.get('乙'));
});

test('borrowedNotice：只在類別超過色盤時提醒', () => {
  assert.equal(borrowedNotice(['甲', '乙'], '整份報告'), null);
  assert.match(borrowedNotice(['甲', '乙', '丙', '丁', '戊'], '整份報告'), /「戊」在各圖借用/);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import JSZip from 'jszip';
import { check } from '../evals/check.mjs';
import { build } from '../scripts/pptx.js';
import { buildReport } from '../scripts/report.js';
import { checkReport } from '../evals/check-report.mjs';

const sources = { source: '虛構測試文字稿' };
const slideText = async (pages) => {
  const zip = await JSZip.loadAsync((await build({ title: '位數測試', pages })).buffer);
  const xml = await zip.file('ppt/slides/slide1.xml').async('string');
  return [...xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((m) => m[1]);
};

test('封面 claim 估算三行時驗收器警告頁碼、欄位、估算行數與上限；兩行以內不警告', async () => {
  const cover = (claim) => ({ title: '封面測試', pages: [{ type: 'cover', claim, sources }] });
  const long = await check(cover('封面主張很長'.repeat(7)), '無數字');
  assert.ok(long.warnings.some((w) => /^第 1 頁 claim：估算 3 行，上限 2 行/.test(w)), long.warnings.join('\n'));
  for (const claim of ['封面主張'.repeat(7), '封面主張\n第二行']) {
    const short = await check(cover(claim), '無數字');
    assert.ok(!short.warnings.some((w) => /claim：估算/.test(w)), short.warnings.join('\n'));
  }
});

test('章節與內容頁的標題超過兩行同樣警告', async () => {
  const long = '標題很長'.repeat(30);
  const { warnings } = await build({ title: '標題測試', pages: [
    { type: 'section', claim: long, sources },
    { type: 'statement', claim: '短句', sources },
    { type: 'list', claim: long, sources, visual: { items: [{ heading: '甲' }, { heading: '乙' }, { heading: '丙' }] } },
  ] });
  for (const n of [1, 3]) assert.ok(warnings.some((w) => new RegExp(`^第 ${n} 頁 claim：估算 \\d+ 行，上限 2 行`).test(w)), warnings.join('\n'));
});

test('數字格與 metric 未指定 digits 時照數值小數位顯示，指定時照指定', async () => {
  const numbers = (items) => [{ type: 'numbers', claim: '數字', sources, visual: { items } }];
  const text = await slideText(numbers([
    { label: '甲', value: 24.7, prev: 25, better: 'higher' },
    { label: '乙', value: 476.56 },
    { label: '丙', value: 24.7, digits: 0 },
  ]));
  for (const shown of ['24.7', '476.56', '25', '−0.3']) assert.ok(text.some((t) => t.includes(shown)), `${shown} 不在 ${text.join('|')}`);
  assert.ok(!text.some((t) => t.includes('&lt;1')));
  const metric = (m) => slideText([{ type: 'evidence', claim: '證據', sources, metric: m, visual: { kind: 'rank', rows: [{ label: '甲', value: 1 }] } }]);
  assert.ok((await metric({ label: '比例', value: 24.7 })).includes('24.7'));
  assert.ok((await metric({ label: '比例', value: 476.56 })).includes('476.56'));
  const rounded = await metric({ label: '比例', value: 24.7, digits: 0 });
  assert.ok(rounded.includes('25') && !rounded.includes('24.7'));
});

test('驗收器的增減值核對與畫面同一位數', async () => {
  const story = { title: '增減測試', pages: [{ type: 'numbers', claim: '比例下降 0.3', sources, notes: '講稿。',
    visual: { items: [{ label: '甲', value: 24.7, prev: 25, better: 'higher' }, { label: '乙', value: 3 }] } }] };
  const { warnings } = await check(story, '甲由 25 降到 24.7，乙 3，下降 0.3。');
  assert.ok(!warnings.some((w) => /claim/.test(w)), warnings.join('\n'));
});

test('範例報告的「完成 N 節」與驗收器的「通過 N 節」數字一致，安裝文件也一樣', () => {
  const report = JSON.parse(readFileSync(new URL('../examples/report.json', import.meta.url), 'utf8'));
  const built = buildReport(report, { baseDir: new URL('../examples/', import.meta.url).pathname });
  const script = readFileSync(new URL('../evals/fixtures/explain-script.md', import.meta.url), 'utf8');
  const checked = checkReport(built.html, script);
  assert.equal(built.sections, checked.sections);
  const install = readFileSync(new URL('../docs/install.md', import.meta.url), 'utf8');
  assert.match(install, new RegExp(`${checked.sections} 節報告`));
});

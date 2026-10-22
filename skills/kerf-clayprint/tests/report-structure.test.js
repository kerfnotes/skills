import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildReport } from '../scripts/report.js';
import { themeCss } from '../scripts/theme-css.js';

const sections = (n) => Array.from({ length: n }, (_, i) => ({ claim: `判斷${'甲乙丙丁'[i]}`, blocks: [{ type: 'text', text: '內文' }] }));
const base = (n, extra = {}) => ({ title: '測試', message: '帶走這句', summary: { claim: '建議', items: [{ label: '甲', value: 1 }, { label: '乙', value: 2 }] }, sections: sections(n), ...extra });
const front = (html) => html.match(/<div class="report-front"[^>]*>([\s\S]*?)<\/div>\s*(?=<nav|<section|<\/main>)/)?.[1] ?? '';
const printCss = () => { const css = themeCss(); return css.slice(css.indexOf('@media print')); };

test('第一頁容器：預設橫幅封面、目錄與摘要同在第一頁，容器不是 section', () => {
  const { html, sections: n } = buildReport(base(3));
  assert.match(html, /<div class="report-front">\n<header class="report-cover">/);
  const page1 = front(html);
  assert.match(page1, /<nav class="toc"/);
  assert.match(page1, /<section class="summary"/);
  assert.doesNotMatch(page1, /section-heading/);
  assert.equal(n, 4);
});

test('cover: "page" 時第一頁只有封面，目錄與摘要移到容器之後；其他值指出修法', () => {
  const { html } = buildReport(base(3, { cover: 'page' }));
  assert.match(html, /<div class="report-front" data-cover="page">\n<header class="report-cover">/);
  const page1 = front(html);
  assert.match(page1, /report-cover/);
  assert.doesNotMatch(page1, /toc|summary/);
  assert.match(html, /<\/header>\n<\/div>\n\n<nav class="toc"/);
  assert.throws(() => buildReport(base(3, { cover: 'full' })), /cover 格式不正確；請.*page/);
});

test('目錄三節以上才出現，只列節標題、不印頁碼', () => {
  assert.doesNotMatch(buildReport(base(2)).html, /<nav class="toc"/);
  const toc = buildReport(base(3)).html.match(/<nav class="toc"[\s\S]*?<\/nav>/)[0];
  assert.deepEqual([...toc.matchAll(/<li><a href="#section-\d">([^<]*)<\/a><\/li>/g)].map((m) => m[1]), ['判斷甲', '判斷乙', '判斷丙']);
  assert.doesNotMatch(toc, /counter|頁/);
});

test('列印：第一頁容器出血並以分頁結束，節不換頁，節標題與目錄、引言對齊 22 mm 線', () => {
  const css = printCss();
  // 第 1 頁 @page 邊界為 0：容器抵銷 body 內距，再補回左 50、右 25 mm；橫幅再抵銷容器內距印到紙邊。
  assert.match(css, /\.report-front \{[^}]*margin: 0 -11mm 0 -28mm;[^}]*padding: 0 25mm 15mm 50mm;[^}]*break-after: page;/);
  assert.match(css, /\.report-cover \{[^}]*margin: 0 -25mm[^;]*-50mm;[^}]*padding: [^;]*25mm [^;]*50mm;[^}]*background: /);
  assert.doesNotMatch(css, /(?:^|\s)section \{[^}]*break-(?:inside|before)/m);
  assert.doesNotMatch(css, /\.report-cover \{[^}]*break-after/);
  assert.match(css, /\.toc, \.section-heading, \.callout \{ margin-left: -28mm;/);
  assert.match(css, /\.section-heading \{[^}]*border-top: [^;]*var\(--cp-accent\)/);
  assert.match(css, /\.section-heading h2 \{[^}]*color: var\(--cp-accent\)/);
  assert.match(css, /\.section-heading \{[^}]*break-inside: avoid; break-after: avoid/);
});

test('列印：callout 是 24 pt 強調色、無框無底色的引言；螢幕仍是色框', () => {
  const css = themeCss();
  const screen = css.slice(0, css.indexOf('@page'));
  assert.match(screen, /\.callout \{[^}]*padding: 20px 24px; background: var\(--cp-tint\);/);
  const print = printCss();
  assert.match(print, /\.callout \{[^}]*padding: 0;[^}]*background: none;[^}]*border: 0;/);
  assert.match(print, /\.callout p \{[^}]*font-size: 24pt;[^}]*line-height: [\d.]+;[^}]*color: var\(--cp-accent\)/);
});

test('列印：圖、表、摘要不切；超過八列的表格才可分頁並重複表頭', () => {
  const css = printCss();
  assert.match(css, /figure, \.callout, \.summary, \.table-scroll[^{]*\{ break-inside: avoid; \}/);
  assert.match(css, /\.table-scroll:has\(tbody tr:nth-child\(9\)\)[^{]*\{ break-inside: auto; \}/);
  assert.match(css, /thead \{ display: table-header-group; \}/);
  assert.match(css, /caption, thead \{ break-after: avoid; \}/);
});

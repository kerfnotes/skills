import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { checkReport } from '../evals/check-report.mjs';
import { themeCss, replaceTheme } from '../scripts/theme-css.js';
import { loadTokens } from '../scripts/tokens.js';

// Compare content, not line endings: a Windows checkout may turn LF into CRLF.
const file = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const cssOf = (html) => html.match(/<style id="clayprint-theme">\n([\s\S]*?)\n<\/style>/)?.[1];

test('範本與完整範例使用目前 clay 設計層，blue 可重寫同一區塊', () => {
  for (const path of ['assets/report.html', 'examples/report.html']) {
    const html = file(path);
    assert.equal(cssOf(html), themeCss());
    const blue = replaceTheme(html, themeCss(loadTokens('design/tokens.blue.json')));
    assert.match(cssOf(blue), /--cp-accent: #125A98/);
    assert.equal(blue.replace(/<style id="clayprint-theme">[\s\S]*?<\/style>/, ''), html.replace(/<style id="clayprint-theme">[\s\S]*?<\/style>/, ''));
  }
  assert.throws(() => replaceTheme('<p>缺少樣式區塊</p>'), /找不到/);
});

test('報告範本不強制表格最小寬度，也不使用粗側邊框', () => {
  const css = cssOf(file('assets/report.html'));
  assert.doesNotMatch(css, /(?:^|\s)table\s*\{[^}]*min-width\s*:\s*\d/);
  assert.doesNotMatch(css, /border-(?:left|right)\s*:\s*(?:[3-9]|\d{2,})px/);
});

test('範例報告可核對原稿及兩張圖的來源', () => {
  const result = checkReport(file('examples/report.html'), file('evals/fixtures/explain-script.md'));
  assert.equal(result.figures, 2);
  const run = spawnSync(process.execPath, ['evals/check-report.mjs', 'examples/report.html', 'evals/fixtures/explain-script.md'], { encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
});

test('只查可見文字，含 SVG；殘留示意文字與缺來源圖說會失敗', () => {
  const html = '<style>p{width:999px}</style><!-- 999 --><p hidden>999</p><p style="display:none">999</p><section><p>甲 12 件</p><figure><svg><text>12</text></svg><figcaption>來源：原稿</figcaption></figure></section>';
  assert.equal(checkReport(html, '甲 12 件。').figures, 1);
  assert.throws(() => checkReport(html.replace('<text>12', '<text>99'), '甲 12 件。'), /99/);
  assert.throws(() => checkReport(html.replace('來源：原稿', '原稿'), '甲 12 件。'), /figcaption/);
  assert.throws(() => checkReport(`${html}{{尚未填}}`, '甲 12 件。'), /示意文字/);
});

test('相鄰表格格與 SVG 文字分開核對，不會黏成一個數字', () => {
  const source = '2024 年 12 件，2025 年 8 件。';
  assert.doesNotThrow(() => checkReport('<section><table><tr><th>2024</th><th>2025</th></tr><tr><td>12</td><td>8</td></tr></table></section>', source));
  assert.doesNotThrow(() => checkReport('<section><figure><svg><text>2024</text><text>2025</text></svg><figcaption>來源：原稿</figcaption></figure></section>', source));
});

test('推導值沿用簡報的完整加減算式，且只在同節有效', () => {
  const source = '甲 12 件，乙 8 件。';
  assert.doesNotThrow(() => checkReport('<section><p>計算：12 + 8 = 20</p><p>合計 20 件</p></section>', source));
  assert.throws(() => checkReport('<section><p>計算：12 + 8 = 20</p></section><section><p>合計 20 件</p></section>', source), /第 2 節.*20/);
  assert.throws(() => checkReport('<section><p>計算：12 + 8 = 21</p></section>', source), /算式.*不符/);
});

test('theme-css keeps CRLF files in CRLF', () => {
  const crlf = '<html>\r\n<style id="clayprint-theme">\r\nold\r\n</style>\r\n</html>\r\n';
  const out = replaceTheme(crlf, ':root {\n  --x: 1;\n}');
  assert.ok(!/[^\r]\n/.test(out), 'no bare LF after rewriting a CRLF file');
  assert.match(out, /--x: 1;/);
});

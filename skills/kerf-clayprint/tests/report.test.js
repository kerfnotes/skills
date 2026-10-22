import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { checkReport } from '../evals/check-report.mjs';
import { buildReport } from '../scripts/report.js';
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

test('report.json 產生的範例報告通過原稿核對，樣式來自生效設計層', () => {
  const { html, figures, warnings } = buildReport(JSON.parse(file('examples/report.json')), { baseDir: 'examples' });
  assert.equal(figures, 2);
  assert.deepEqual(warnings, []);
  assert.equal(cssOf(html), themeCss());
  assert.match(html, /<nav class="toc"/);
  assert.match(html, /data-tick="1"/);
  assert.equal(checkReport(html, file('evals/fixtures/explain-script.md')).figures, 2);
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-report-'));
  try {
    const run = spawnSync(process.execPath, ['scripts/report.js', 'examples/report.json', path.join(dir, 'r.html')], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    assert.equal(readFileSync(path.join(dir, 'r.html'), 'utf8'), html);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('座標軸刻度不核對，資料標籤仍要來自原稿', () => {
  const html = (label) => `<section><figure><svg><text data-tick="1">40</text><text>${label}</text></svg><figcaption>來源：原稿</figcaption></figure></section>`;
  assert.doesNotThrow(() => checkReport(html('12'), '甲 12 件。'));
  assert.throws(() => checkReport(html('99'), '甲 12 件。'), /99/);
  assert.throws(() => checkReport('<section><p data-tick="1">甲 99 件</p></section>', '甲 12 件。'), /99/);
});

test('report.json：跳脫 HTML、缺值標未提供、缺來源的圖與錯誤元件指出位置', () => {
  const base = { title: '測試', message: '帶走 <b>這句</b>', sections: [{ claim: '判斷', blocks: [{ type: 'text', text: '<script>x</script>' }] }] };
  const { html } = buildReport({ ...base, summary: { claim: '建議', items: [{ label: '甲', value: null }, { label: '乙', value: 0, unit: '件' }] } });
  assert.match(html, /帶走 &lt;b&gt;這句&lt;\/b&gt;/);
  assert.match(html, /&lt;script&gt;x&lt;\/script&gt;/);
  assert.match(html, /<dd><span class="missing">未提供<\/span><\/dd>/);
  assert.match(html, /<dd>0 件<\/dd>/);
  const chart = { kind: 'rank', rows: [{ label: '甲', value: 1 }] };
  assert.throws(() => buildReport({ ...base, sections: [{ claim: '判斷', blocks: [{ type: 'chart', title: '圖', chart }] }] }), /source/);
  assert.throws(() => buildReport({ ...base, sections: [{ claim: '判斷', blocks: [{ type: 'slide' }] }] }), /sections\[0\]\.blocks\[0\]\.type/);
  assert.throws(() => buildReport({ ...base, summary: { claim: '建議', items: [{ label: '甲' }] } }), /summary\.items\[0\]\.value/);
  assert.throws(() => buildReport({ ...base, sections: [{ claim: '判斷', blocks: [{ type: 'compare', rows: ['成本'], options: [{ values: ['低'] }] }] }] }), /options\[0\]\.name/);
  assert.throws(() => buildReport({ ...base, sections: [{ claim: '判斷', blocks: [{ type: 'process', focus: '1', steps: [{ heading: '甲' }, { heading: '乙' }] }] }] }), /focus/);
  assert.throws(() => buildReport({ ...base, sections: [{ id: 'section-2', claim: '判斷', blocks: base.sections[0].blocks }] }), /\.id/);
});

test('列印版心：白紙 A4、學者邊、頁尾頁碼、列印字級，螢幕規則不變', () => {
  const css = themeCss();
  const at = css.indexOf('@page');
  const screen = css.slice(0, at), print = css.slice(at);
  // 螢幕：940 px、米色、圖表橫向捲動與窄螢幕最小寬度都還在，且不受列印屬性影響。
  assert.match(screen, /body \{[^}]*max-width: 940px/);
  assert.match(screen, /html \{[^}]*background: var\(--cp-paper\)/);
  assert.match(screen, /\.chart-scroll \{ max-width: 100%; overflow-x: auto; \}/);
  assert.match(screen, /\.chart-scroll svg \{ min-width: 640px; max-width: none; \}/);
  assert.doesNotMatch(screen, /data-paper|data-size|\dmm|\dpt/);
  // 紙張與邊界：預設 A4 白紙；@page 設在最外的 22／14 mm 線，正文欄由 body 內距推到左 50、右 25 mm；
  // 第一頁零邊界且無頁尾；Letter 只換紙張大小。
  assert.match(print, /@page \{[^}]*size: A4; margin: 12mm 14mm 15mm 22mm;/);
  assert.match(print, /@bottom-right \{[^}]*content: var\(--report-title, ""\) " \| " counter\(page\) " \/ " counter\(pages\);[^}]*font: 7pt var\(--cp-font\);[^}]*padding-right: 11mm;/);
  assert.match(print, /@page :first \{ margin: 0;[^}]*@bottom-right \{ content: none; \}/);
  assert.match(print, /@page letter \{ size: letter; \}/);
  assert.match(print, /html\[data-size="letter"\] body \{ page: letter; \}/);
  assert.match(print, /html\[data-paper="clay"\] body \{ page: clay; \}/);
  assert.match(print, /@page clay \{ background: var\(--cp-paper\); \}/);
  assert.doesNotMatch(print, /size: letter;[^}]*margin/);
  // 列印字級與欄寬。
  const media = print.slice(print.indexOf('@media print'));
  assert.match(media, /html \{[^}]*background: #fff;[^}]*font-size: 10\.5pt; line-height: 16pt;/);
  assert.match(media, /body \{[^}]*padding: 0 11mm 0 28mm;/);
  assert.match(media, /h2 \{ font-size: 24pt;/);
  assert.match(media, /h3 \{ font-size: 12pt;/);
  assert.match(media, /figcaption, \.sources \{ font-size: 7pt;/);
  assert.match(media, /figure, \.table-scroll \{ margin-right: -11mm; max-width: none; \}/);
  assert.match(media, /\.chart-scroll svg \{ min-width: 0; max-width: 100%; \}/);
  // 列印區塊在窄螢幕規則之後，才能蓋掉它（A4 版心約 510 CSS px，會命中 max-width: 640px）。
  assert.ok(css.indexOf('@media print') > css.indexOf('@media (max-width: 640px)'));
});

test('報告名寫在根元素的 CSS 變數，給列印頁尾用，並跳脫引號與反斜線', () => {
  const { html } = buildReport({ title: `甲's "乙" \\ <丙>\n丁`, message: '帶走這句', sections: [{ claim: '判斷', blocks: [{ type: 'text', text: '內文' }] }] });
  assert.match(html, /<html lang="zh-Hant" style="--report-title: '甲\\'s &quot;乙&quot; \\\\ &lt;丙&gt; 丁'">/);
  assert.match(file('examples/report.html'), /<html lang="zh-Hant" style="--report-title: '讓標本登錄從交接開始變快'">/);
  assert.match(file('assets/report.html'), /<html lang="zh-Hant" style="--report-title: '\{\{報告標題\}\}'">/);
});

test('圖表區塊：圖、表各自編號，標籤與標題在上，註與來源在下', () => {
  const html = file('examples/report.html');
  const figures = html.match(/<figure[\s\S]*?<\/figure>/g);
  assert.equal(figures.length, 2);
  figures.forEach((f, i) => {
    const head = f.indexOf(`<span class="exhibit-label" data-label>圖 ${i + 1}</span>`);
    assert.ok(head > 0 && head < f.indexOf('<svg'), `圖 ${i + 1} 標籤在圖上方`);
    assert.ok(f.indexOf('<figcaption>') > f.indexOf('</svg>'), '圖說在圖下方');
    assert.match(f, /<figcaption>[^<]*來源：/);
  });
  assert.match(figures[0], /class="exhibit-title"><span class="exhibit-label" data-label>圖 1<\/span>登錄時間比較<\/p>/);
  assert.match(figures[0], /<figcaption>[^<]*附註：24 小時是試行目標/);
  assert.doesNotMatch(figures[0], /<figcaption>登錄時間比較/);
  assert.match(html, /<caption><span class="exhibit-label" data-label>表 1<\/span>同一流程的時間對照<\/caption>/);
  assert.match(html, /<\/table>\n<\/div>\n<p class="exhibit-note">來源：/);

  // 圖與表分開從 1 起算；沒有標題的表格也編號；compare 不編號；註與來源只在有填時出現。
  const chart = { kind: 'rank', source: '原稿', rows: [{ label: '甲', value: 1 }] };
  const table = { type: 'table', columns: [{ name: '項目' }], rows: [['甲']] };
  const { html: out, figures: n } = buildReport({ title: '測試', message: '帶走這句', sections: [
    { claim: '一', blocks: [table, { type: 'chart', title: '甲圖', chart }, { type: 'compare', rows: ['成本'], options: [{ name: 'A', values: ['低'] }] }] },
    { claim: '二', blocks: [{ type: 'chart', title: '乙圖', chart, note: '區塊附註', wide: true }, { ...table, caption: '乙表', source: '原稿', note: '表附註' }] },
  ] });
  assert.equal(n, 2);
  assert.deepEqual(out.match(/data-label>[^<]+/g).map((s) => s.slice(11)), ['表 1', '圖 1', '圖 2', '表 2']);
  assert.match(out, /<figure class="wide">/);
  assert.equal((out.match(/<figure>/g) ?? []).length, 1);
  assert.match(out, /<figcaption>附註：區塊附註｜來源：原稿<\/figcaption>/);
  assert.match(out, /<p class="exhibit-note">附註：表附註｜來源：原稿<\/p>/);
  assert.equal((out.match(/<p class="exhibit-note">/g) ?? []).length, 1);
  assert.throws(() => buildReport({ title: '測試', message: '帶走這句', sections: [{ claim: '一', blocks: [{ type: 'chart', title: '圖', chart, wide: 'yes' }] }] }), /wide/);
  assert.throws(() => buildReport({ title: '測試', message: '帶走這句', sections: [{ claim: '一', blocks: [{ ...table, source: '' }] }] }), /source/);
});

test('全寬圖只在列印時從左 22 mm 起，不伸出 @page', () => {
  const css = themeCss();
  const media = css.slice(css.indexOf('@media print'));
  assert.match(media, /figure\.wide, \.table-scroll\.wide \{ margin-left: -28mm; \}/);
  assert.match(media, /\.exhibit-title, caption \{[^}]*font-size: 12pt;/);
  assert.match(media, /\.exhibit-note, figcaption, \.sources \{ font-size: 7pt;/);
  assert.doesNotMatch(css.slice(0, css.indexOf('@page')), /\.wide/);
});

test('驗收器略過產生器加的圖表標籤，正文裡原稿沒有的編號仍核對', () => {
  const source = '甲 12 件。';
  const fig = '<figure><p class="exhibit-title"><span class="exhibit-label" data-label>圖 7</span>甲</p><svg><text>12</text></svg><figcaption>來源：原稿</figcaption></figure>';
  assert.doesNotThrow(() => checkReport(`<section>${fig}<table><caption><span class="exhibit-label" data-label>表 3</span>乙</caption><tr><td>12</td></tr></table></section>`, source));
  assert.throws(() => checkReport(`<section><p>見圖 7</p>${fig}</section>`, source), /原稿找不到數字 7/);
  assert.throws(() => checkReport(`<section>${fig.replace('甲</p>', '甲 99 件</p>')}</section>`, source), /99/);
  assert.throws(() => checkReport(`<section>${fig.replace('>圖 7<', '>圖 7 共 99 件<')}</section>`, source), /原稿找不到數字/);
  assert.throws(() => checkReport(fig.replace('來源：原稿', '原稿'), source), /figcaption/);
});

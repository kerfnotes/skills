import { readFileSync, writeFileSync } from 'node:fs';
import { loadTokens } from './tokens.js';
import { isMain } from './main.js';

export function themeCss(tokens = loadTokens()) {
  const c = tokens.color;
  const font = [...tokens.font.latin, ...tokens.font.cjk].map((name) => `"${name}"`).join(', ');
  const body = tokens.type.body.px / 2;
  return `:root {
  --cp-paper: ${c.onDark[0]};
  --cp-ink: ${c.text};
  --cp-muted: ${c.textSecondary};
  --cp-title: ${c.title};
  --cp-line: ${c.grid};
  --cp-accent: ${c.focus};
  --cp-tint: ${c.tint};
  --cp-soft: ${c.onDark[1]};
  --cp-font: ${font}, sans-serif;
  --cp-body: ${body}px;
  --cp-small: ${tokens.type.label.px / 2}px;
  --cp-sub: ${tokens.type.sub.px / 2}px;
  --cp-title-size: ${tokens.type.title.px / 2}px;
  --cp-display: ${tokens.type.display.px / 2}px;
}
* { box-sizing: border-box; }
html { color: var(--cp-ink); background: var(--cp-paper); font-family: var(--cp-font); font-size: var(--cp-body); line-height: 1.65; }
body { margin: 0 auto; padding: 0 24px 72px; max-width: 940px; overflow-wrap: anywhere; }
main, article, section { min-width: 0; }
h1, h2, h3, p { margin-top: 0; }
h1, h2, h3 { color: var(--cp-title); line-height: 1.25; }
h1 { font-size: clamp(32px, 7vw, var(--cp-display)); letter-spacing: -.035em; }
h2 { font-size: var(--cp-title-size); letter-spacing: -.02em; }
h3 { font-size: var(--cp-sub); }
p, li { max-width: 72ch; }
a { color: var(--cp-accent); text-underline-offset: .16em; }
.report-cover { padding: 72px 0 64px; border-bottom: 3px solid var(--cp-accent); }
.eyebrow { color: var(--cp-accent); font-size: var(--cp-small); font-weight: 700; letter-spacing: .08em; }
.report-cover > p:not(:first-child) { font-size: var(--cp-sub); }
.cover-meta { display: flex; flex-wrap: wrap; gap: 10px 28px; margin-top: 40px; color: var(--cp-muted); font-size: var(--cp-small); }
.cover-meta dt { font-weight: 700; }
.cover-meta dd, .summary-metrics dd { margin: 0; }
.toc, section { margin-top: 52px; }
.toc ol { padding-left: 1.4em; }
.toc li { border-bottom: 1px solid var(--cp-line); padding: 7px 0; }
.summary { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 28px; padding: 30px; background: var(--cp-tint); }
.summary h2 { margin-bottom: 12px; }
.summary-metrics { display: grid; gap: 12px; align-content: center; }
.summary-metrics dt { color: var(--cp-muted); font-size: var(--cp-small); }
.summary-metrics dd { color: var(--cp-accent); font-size: var(--cp-title-size); font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.section-heading { margin-bottom: 22px; border-top: 1px solid var(--cp-line); padding-top: 24px; }
.section-heading > p:last-child { color: var(--cp-muted); }
.callout { margin: 28px 0; padding: 20px 24px; background: var(--cp-tint); }
figure { margin: 32px 0; }
figure svg { display: block; width: 100%; height: auto; max-width: 100%; }
.chart-scroll { max-width: 100%; overflow-x: auto; }
figcaption, .sources { margin-top: 10px; color: var(--cp-muted); font-size: var(--cp-small); line-height: 1.5; }
.chart-focus { fill: var(--cp-accent); stroke: var(--cp-accent); }
.chart-muted { fill: var(--cp-soft); stroke: var(--cp-soft); }
.chart-grid { stroke: var(--cp-line); }
.chart-text { fill: var(--cp-ink); }
.chart-subtle { fill: var(--cp-muted); }
.table-scroll { max-width: 100%; overflow-x: auto; box-shadow: inset -12px 0 10px -12px var(--cp-accent); }
table { width: 100%; border-collapse: collapse; text-align: left; font-variant-numeric: tabular-nums; }
caption { text-align: left; }
th, td { padding: 11px 14px; border-bottom: 1px solid var(--cp-line); vertical-align: top; }
thead th { border-bottom: 2px solid var(--cp-ink); font-size: var(--cp-small); }
.num, td[data-type="number"], th[data-type="number"] { text-align: right; white-space: nowrap; }
tr.emphasis, tr.total { font-weight: 700; background: var(--cp-tint); }
.comparison .recommended { background: var(--cp-tint); }
.diagnosis, .flow { padding-left: 1.4em; }
.diagnosis li, .flow li { padding: 9px 0; border-bottom: 1px solid var(--cp-line); }
.flow li::marker { color: var(--cp-accent); font-weight: 700; }
.missing { display: inline-block; padding: 0 .4em; border: 1px solid var(--cp-muted); color: var(--cp-muted); font-size: var(--cp-small); }
@media (max-width: 640px) {
  body { padding: 0 18px 44px; }
  .report-cover { padding: 48px 0 42px; }
  .summary { grid-template-columns: 1fr; padding: 20px; }
  .summary-metrics { grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); }
  .chart-scroll svg { min-width: 640px; max-width: none; }
}
/* Chrome clips print content outside the page area and shrinks the whole page when anything overflows on the right,
   so @page sits on the outermost lines (22 mm left, 14 mm right) and body padding sets the 50 / 25 mm text column. */
@page {
  size: A4; margin: 12mm 14mm 15mm 22mm;
  @bottom-right { content: var(--report-title, "") " | " counter(page) " / " counter(pages); font: 7pt var(--cp-font); color: var(--cp-muted); padding-right: 11mm; }
}
/* The first page has no margin so the cover band can bleed, and no footer. */
@page :first { margin: 0; @bottom-right { content: none; } }
/* The PDF printer sets data-paper / data-size on the root; @page cannot match attributes, so they pick named pages. */
@page clay { background: var(--cp-paper); }
@page letter { size: letter; }
@page clay-letter { size: letter; background: var(--cp-paper); }
@media print {
  html { background: #fff; font-size: 10.5pt; line-height: 16pt; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  html[data-paper="clay"] { background: var(--cp-paper); }
  html[data-paper="clay"] body { page: clay; }
  html[data-size="letter"] body { page: letter; }
  html[data-paper="clay"][data-size="letter"] body { page: clay-letter; }
  body { max-width: none; padding: 0 11mm 0 28mm; }
  h2 { font-size: 24pt; }
  h3 { font-size: 12pt; }
  figcaption, .sources { font-size: 7pt; }
  /* Page 1 has no @page margin: the front container cancels the body padding and brings back the 50 / 25 mm column,
     the cover band cancels that again to reach the paper edge. Sections always start on the next page.
     ponytail: front matter longer than one page keeps the 50 mm padding on top of page 2's margin; shorten the summary if it spills. */
  .report-front { margin: 0 -11mm 0 -28mm; padding: 0 25mm 15mm 50mm; break-after: page; }
  .report-cover { margin: 0 -25mm 10mm -50mm; padding: 24mm 25mm 12mm 50mm; background: var(--cp-tint); }
  .report-cover h1 { font-size: 30pt; line-height: 1.2; }
  /* A full-page cover fills the paper; 1 mm short so it never spills onto a second page. */
  .report-front[data-cover="page"] { padding-bottom: 0; }
  .report-front[data-cover="page"] .report-cover { min-height: 296mm; margin-bottom: 0; padding-top: 80mm; }
  html[data-size="letter"] .report-front[data-cover="page"] .report-cover { min-height: 278mm; }
  .toc { margin-top: 0; }
  .toc h2 { font-size: 12pt; }
  /* Section headings, contents and pull quotes sit on the 22 mm line, the inner edge of @page. */
  .toc, .section-heading, .callout { margin-left: -28mm; }
  .section-heading { break-inside: avoid; break-after: avoid; border-top: 1.5pt solid var(--cp-accent); padding-top: 4mm; }
  .section-heading h2 { color: var(--cp-accent); margin-bottom: 3mm; }
  .callout { margin-top: 6mm; margin-bottom: 6mm; padding: 0; background: none; border: 0; }
  .callout p { font-size: 24pt; line-height: 1.3; color: var(--cp-accent); font-weight: 700; max-width: none; }
  figure, .callout, .summary, .table-scroll, .comparison, .diagnosis, .flow, .decisions { break-inside: avoid; }
  /* Tables over eight rows may break; the header repeats on the next page. */
  .table-scroll:has(tbody tr:nth-child(9)), .table-scroll:has(tbody tr:nth-child(9)) table { break-inside: auto; }
  thead { display: table-header-group; }
  caption, thead { break-after: avoid; }
  tr { break-inside: avoid; }
  /* Charts and tables may run into the body padding, to 14 mm from the right edge (146 mm on A4). */
  figure, .table-scroll { margin-right: -11mm; max-width: none; }
  .chart-scroll, .table-scroll { overflow: visible; box-shadow: none; }
  /* Overrides the narrow-screen min-width above: the A4 column is about 510 CSS px. */
  .chart-scroll svg { min-width: 0; max-width: 100%; }
  /* SVG text is in viewBox units (979 wide); 19 units at 146 mm is about 8 pt. */
  .chart-scroll svg [data-tick] { font-size: 19px; }
  .sources { break-before: avoid; }
  a { color: inherit; }
}`;
}

export function replaceTheme(html, css = themeCss()) {
  const pattern = /(<style\s+id=["']clayprint-theme["']\s*>)[\s\S]*?(<\/style>)/i;
  if (!pattern.test(html)) throw new Error('找不到 <style id="clayprint-theme"> 區塊');
  // Keep the file's own line endings (Windows checkouts and editors may use CRLF).
  const eol = /\r\n/.test(html) ? '\r\n' : '\n';
  return html.replace(pattern, (_, open, close) => `${open}${eol}${css.replace(/\r?\n/g, eol)}${eol}${close}`);
}

if (isMain(import.meta.url)) {
  const file = process.argv[2];
  try {
    if (file) writeFileSync(file, replaceTheme(readFileSync(file, 'utf8')));
    else console.log(themeCss());
  } catch (error) {
    console.error(`設計層 CSS 失敗：${error.message}`);
    process.exitCode = 1;
  }
}

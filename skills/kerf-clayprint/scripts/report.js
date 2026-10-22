// Build a continuous-reading HTML report from report.json: cover, contents, summary, then sections of blocks.
// node scripts/report.js report.json report.html
// Markup and classes follow assets/report.html; charts come from scripts/svg.js, tables from the same model as the deck.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { T, formatValue, prepare } from './core.js';
import { render, reportHeight } from './svg.js';
import { themeCss } from './theme-css.js';
import { isMain } from './main.js';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const MISSING = '<span class="missing">未提供</span>';
const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const BLOCKS = ['text', 'callout', 'chart', 'table', 'compare', 'list', 'process', 'close', 'missing'];
// A summary or meta value: number formatted like the deck, text as written, null marked in place.
const shown = (value, { digits = 0, unit } = {}) => value === null ? MISSING
  : `${esc(typeof value === 'number' ? formatValue(value, { digits }) : value)}${unit ? ` ${esc(unit)}` : ''}`;
const scroll = (label, inner) => `<div class="table-scroll" tabindex="0" role="region" aria-label="${esc(label)}，可橫向捲動">\n${inner}\n</div>`;

function validate(report) {
  const need = (ok, path, repair) => { if (!ok) throw new Error(`${path} 格式不正確；請${repair}。`); };
  const str = (v, path) => need(typeof v === 'string' && v.trim().length > 0, path, '填入非空白文字');
  const list = (v, path) => need(Array.isArray(v) && v.length > 0, path, '提供至少一筆資料的陣列');
  need(isObject(report), 'report', '提供包含 title、message 與 sections 的 JSON 物件');
  str(report.title, 'title');
  str(report.message, 'message');
  if (report.meta != null) { list(report.meta, 'meta'); report.meta.forEach((m, i) => { str(m?.label, `meta[${i}].label`); str(m?.value, `meta[${i}].value`); }); }
  if (report.summary != null) {
    str(report.summary.claim, 'summary.claim');
    list(report.summary.items, 'summary.items');
    report.summary.items.forEach((it, i) => {
      str(it?.label, `summary.items[${i}].label`);
      need(it.value === null || (typeof it.value === 'number' && Number.isFinite(it.value)) || (typeof it.value === 'string' && it.value.trim()), `summary.items[${i}].value`, '填數字或文字；原稿沒給就填 null');
    });
  }
  list(report.sections, 'sections');
  const ids = new Set();
  report.sections.forEach((s, i) => {
    const p = `sections[${i}]`;
    str(s?.claim, `${p}.claim`);
    // section-N and summary-title are generated anchors, so a custom id may not take them.
    if (s.id != null) { need(/^[A-Za-z][\w-]*$/.test(s.id) && !/^(?:section-\d+|summary-title)$/.test(s.id) && !ids.has(s.id), `${p}.id`, '改成不重複的英文錨點，例如 time'); ids.add(s.id); }
    list(s.blocks, `${p}.blocks`);
    if (s.sources != null) list(s.sources, `${p}.sources`);
    s.blocks.forEach((b, j) => {
      const q = `${p}.blocks[${j}]`;
      need(isObject(b) && BLOCKS.includes(b.type), `${q}.type`, `選用 ${BLOCKS.join('、')} 其中一種`);
      if (['text', 'callout', 'missing'].includes(b.type)) str(b.text, `${q}.text`);
      if (b.type === 'chart') { str(b.title, `${q}.title`); need(typeof b.chart === 'string' || isObject(b.chart), `${q}.chart`, '填圖表 JSON 路徑或圖表物件'); }
      if (b.type === 'table') { list(b.columns, `${q}.columns`); list(b.rows, `${q}.rows`); b.columns.forEach((c, k) => str(c?.name, `${q}.columns[${k}].name`)); }
      if (b.type === 'compare') { list(b.rows, `${q}.rows`); list(b.options, `${q}.options`); b.options.forEach((o, k) => str(o?.name, `${q}.options[${k}].name`)); }
      if (b.type === 'list') { list(b.items, `${q}.items`); b.items.forEach((it, k) => str(it?.heading, `${q}.items[${k}].heading`)); }
      if (b.type === 'process') {
        list(b.steps, `${q}.steps`);
        b.steps.forEach((it, k) => str(it?.heading, `${q}.steps[${k}].heading`));
        if (b.focus != null) need(Number.isInteger(b.focus) && b.focus >= 0 && b.focus < b.steps.length, `${q}.focus`, '填零起算的步驟索引，例如 1');
      }
      if (b.type === 'close') { list(b.rows, `${q}.rows`); b.rows.forEach((r, k) => str(r?.task, `${q}.rows[${k}].task`)); }
    });
  });
}

function figure(block, where, baseDir, warnings) {
  let spec = block.chart;
  if (typeof spec === 'string') {
    try { spec = JSON.parse(readFileSync(resolve(baseDir, spec), 'utf8')); }
    catch { throw new Error(`${where}.chart：無法讀取 ${block.chart} 為圖表 JSON；路徑相對於 report.json。`); }
  }
  const out = render(spec, { width: Math.round(6.8 * T.slide.pxPerIn), height: reportHeight(prepare(spec)) });
  const m = out.model;
  if (!m.source) throw new Error(`${where}.chart 缺少 source；請在圖表 JSON 填資料來源。`);
  for (const w of m.warnings) warnings.push(`${where}「${block.title}」：${w}`);
  const notes = [typeof spec.note === 'string' ? spec.note : null,
    m.missing.length && T.dataDisplay.missing.sourceField.replace('{item}', m.missing.join('、'))].filter(Boolean);
  const caption = [block.title, m.unit && `單位：${m.unit}`, m.period && `期間：${m.period}`, `來源：${m.source}`, notes.length && `附註：${notes.join('；')}`]
    .filter(Boolean).map(esc).join('｜');
  const svg = out.svg.replace('<svg ', `<svg role="img" aria-label="${esc(block.title)}" `);
  return `<figure>\n<div class="chart-scroll" tabindex="0" role="region" aria-label="${esc(block.title)}，可橫向捲動">\n${svg}\n</div>\n<figcaption>${caption}</figcaption>\n</figure>`;
}

function table(block, where, warnings) {
  const m = prepare({ kind: 'table', columns: block.columns, rows: block.rows, total: block.total, emphasis: block.emphasis });
  for (const w of m.warnings) warnings.push(`${where}：${w}`);
  const cls = (align) => (align === 'end' ? ' class="num"' : '');
  const cell = (c) => (c.value === null ? MISSING : esc(c.text));
  const row = (r) => `<tr${r.total ? ' class="total"' : r.emphasis ? ' class="emphasis"' : ''}>${r.cells.map((c, i) => (i
    ? `<td${cls(c.align)}>${cell(c)}</td>` : `<th scope="row"${cls(c.align)}>${cell(c)}</th>`)).join('')}</tr>`;
  const body = m.rows.filter((r) => !r.total), total = m.rows.filter((r) => r.total);
  return scroll(block.caption ?? '表格', `<table>${block.caption ? `<caption>${esc(block.caption)}</caption>` : ''}
<thead><tr>${m.header.map((h) => `<th scope="col"${cls(h.align)}>${esc(h.text)}</th>`).join('')}</tr></thead>
<tbody>
${body.map(row).join('\n')}
</tbody>${total.length ? `\n<tfoot>${total.map(row).join('')}</tfoot>` : ''}
</table>`);
}

function compare(block) {
  const rec = (o) => (o.recommended ? ' class="recommended"' : '');
  const value = (v) => (v === null || v === undefined ? MISSING : esc(typeof v === 'number' ? formatValue(v) : v));
  return scroll(block.caption ?? '方案比較', `<table class="comparison">${block.caption ? `<caption>${esc(block.caption)}</caption>` : ''}
<thead><tr><th scope="col">比較項目</th>${block.options.map((o) => `<th scope="col"${rec(o)}>${esc(o.name)}${o.recommended ? '（建議）' : ''}</th>`).join('')}</tr></thead>
<tbody>
${block.rows.map((label, r) => `<tr><th scope="row">${esc(label)}</th>${block.options.map((o) => `<td${rec(o)}>${value(o.values?.[r])}</td>`).join('')}</tr>`).join('\n')}
</tbody>
</table>`);
}

function close(block) {
  // Same columns as the deck's close page; a column nobody filled is left out.
  const cols = [['task', '事項'], ['owner', '負責人'], ['due', '期限']].filter(([key]) => block.rows.some((r) => r[key]));
  return scroll(block.caption ?? '決議事項', `<table class="decisions">${block.caption ? `<caption>${esc(block.caption)}</caption>` : ''}
<thead><tr>${cols.map(([, name]) => `<th scope="col">${name}</th>`).join('')}</tr></thead>
<tbody>
${block.rows.map((r) => `<tr>${cols.map(([key], i) => (i ? `<td>${esc(r[key] ?? '')}</td>` : `<th scope="row">${esc(r[key])}</th>`)).join('')}</tr>`).join('\n')}
</tbody>
</table>`);
}

const item = (it) => `<li${it.current ? ' aria-current="step"' : ''}><strong>${esc(it.heading)}</strong>${it.body ? `<span>${esc(it.body)}</span>` : ''}</li>`;

function block(b, where, baseDir, warnings) {
  switch (b.type) {
    case 'text': return `<p>${esc(b.text)}</p>`;
    case 'callout': return `<aside class="callout"><p>${esc(b.text)}</p></aside>`;
    case 'missing': return `<p class="missing">未提供：${esc(b.text)}</p>`;
    case 'chart': return figure(b, where, baseDir, warnings);
    case 'table': return table(b, where, warnings);
    case 'compare': return compare(b);
    case 'close': return close(b);
    case 'list': return `<ul class="diagnosis">\n${b.items.map(item).join('\n')}\n</ul>`;
    case 'process': return `<ol class="flow">\n${b.steps.map((s, i) => item({ ...s, current: i === b.focus })).join('\n')}\n</ol>`;
  }
}

export function buildReport(report, { baseDir = '.' } = {}) {
  validate(report);
  const warnings = [];
  const ids = report.sections.map((s, i) => s.id ?? `section-${i + 1}`);
  if (report.meta?.length > 3) warnings.push(`封面資訊是 ${report.meta.length} 項，建議最多 3 項`);
  const items = report.summary?.items ?? [];
  if (report.summary && (items.length < 2 || items.length > 3)) warnings.push(`摘要數字是 ${items.length} 格，建議 2～3 格`);
  let figures = 0;
  const parts = [`<header class="report-cover">
${report.kicker ? `<p class="eyebrow">${esc(report.kicker)}</p>\n` : ''}<h1>${esc(report.title)}</h1>
<p class="cover-message">${esc(report.message)}</p>${report.meta ? `
<dl class="cover-meta">
${report.meta.map((m) => `<div><dt>${esc(m.label)}</dt><dd>${esc(m.value)}</dd></div>`).join('\n')}
</dl>` : ''}
</header>`];
  // Contents only when there is enough to skip around in.
  if (report.sections.length >= 3) parts.push(`<nav class="toc" aria-label="目錄">
<h2>目錄</h2>
<ol>
${report.sections.map((s, i) => `<li><a href="#${ids[i]}">${esc(s.kicker ? `${s.kicker}：${s.claim}` : s.claim)}</a></li>`).join('\n')}
</ol>
</nav>`);
  if (report.summary) {
    const s = report.summary;
    parts.push(`<section class="summary" aria-labelledby="summary-title">
<div>
<p class="eyebrow">${esc(s.kicker ?? '摘要')}</p>
<h2 id="summary-title">${esc(s.claim)}</h2>${s.body ? `\n<p>${esc(s.body)}</p>` : ''}
</div>
<dl class="summary-metrics">
${items.map((it) => `<div><dt>${esc(it.label)}</dt><dd>${shown(it.value, it)}</dd></div>`).join('\n')}
</dl>
</section>`);
  }
  report.sections.forEach((s, i) => {
    const body = s.blocks.map((b, j) => {
      if (b.type === 'chart') figures += 1;
      return block(b, `第 ${i + 1} 節第 ${j + 1} 個元件`, baseDir, warnings);
    });
    const sources = s.sources ? `\n<footer class="sources">\n<h3>來源與附註</h3>\n${s.sources.map((t) => `<p>${esc(t)}</p>`).join('\n')}\n</footer>` : '';
    parts.push(`<section aria-labelledby="${ids[i]}">
<header class="section-heading">
${s.kicker ? `<p class="eyebrow">${esc(s.kicker)}</p>\n` : ''}<h2 id="${ids[i]}">${esc(s.claim)}</h2>${s.lede ? `\n<p>${esc(s.lede)}</p>` : ''}
</header>
${body.join('\n')}${sources}
</section>`);
  });
  // The print footer reads the title from this CSS string; escape it for CSS first, then for the attribute.
  const footerTitle = report.title.replace(/[\\']/g, '\\$&').replace(/\s+/g, ' ');
  const html = `<!doctype html>
<html lang="zh-Hant" style="--report-title: '${esc(footerTitle)}'">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(report.title)}</title>
<style id="clayprint-theme">
${themeCss()}
</style>
</head>
<body>
<main class="report">
${parts.join('\n\n')}
</main>
</body>
</html>
`;
  // The summary is a <section> too, so this matches evals/check-report.mjs.
  return { html, warnings, sections: report.sections.length + (report.summary ? 1 : 0), figures };
}

if (isMain(import.meta.url)) {
  const [input, output] = process.argv.slice(2);
  if (!input || !output) {
    console.error('用法：node scripts/report.js report.json report.html');
    process.exitCode = 2;
  } else {
    try {
      let report;
      try { report = JSON.parse(readFileSync(input, 'utf8')); }
      catch { throw new Error(`無法讀取 ${input} 為 JSON；請確認路徑、雙引號與逗號。`); }
      const result = buildReport(report, { baseDir: dirname(input) });
      writeFileSync(output, result.html);
      for (const w of result.warnings) console.error(`警告：${w}`);
      console.log(`完成：${result.sections} 節、${result.figures} 張圖，${result.warnings.length} 項警告 → ${output}`);
    } catch (error) {
      console.error(`錯誤：${error.message}`);
      process.exitCode = 1;
    }
  }
}

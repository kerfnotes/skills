// Build a continuous-reading HTML report from report.json: cover, contents, summary, then sections of blocks.
// node scripts/report.js report.json report.html
// Markup and classes follow assets/report.html; charts come from scripts/svg.js, tables from the same model as the deck.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { T, formatValue, decimalsOf, prepare, shownDigits, documentCategories, categoryColors, categoryLimit } from './core.js';
import { render, reportHeight } from './svg.js';
import { themeCss } from './theme-css.js';
import { isMain } from './main.js';
import { SLUG } from './brand.js';

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const MISSING = '<span class="missing">未提供</span>';
const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const BLOCKS = ['text', 'callout', 'chart', 'table', 'compare', 'list', 'process', 'close', 'missing'];
// A summary or meta value: number formatted like the deck, text as written, null marked in place.
const shown = (value, { digits, unit } = {}) => value === null ? MISSING
  : `${esc(typeof value === 'number' ? formatValue(value, { digits: shownDigits(digits, value) }) : value)}${unit ? ` ${esc(unit)}` : ''}`;
const scroll = (label, inner, wide) => `<div class="table-scroll${wide ? ' wide' : ''}" tabindex="0" role="region" aria-label="${esc(label)}，可橫向捲動">\n${inner}\n</div>`;

function validate(report) {
  const need = (ok, path, repair) => { if (!ok) throw new Error(`${path} 格式不正確；請${repair}。`); };
  const str = (v, path) => need(typeof v === 'string' && v.trim().length > 0, path, '填入非空白文字');
  const list = (v, path) => need(Array.isArray(v) && v.length > 0, path, '提供至少一筆資料的陣列');
  need(isObject(report), 'report', '提供包含 title、message 與 sections 的 JSON 物件');
  str(report.title, 'title');
  str(report.message, 'message');
  need(report.cover == null || report.cover === 'page', 'cover', '填 "page" 改成整頁封面，或省略使用橫幅封面');
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
      if (b.type === 'chart' || b.type === 'table') {
        if (b.wide != null) need(typeof b.wide === 'boolean', `${q}.wide`, '填 true 或 false');
        for (const key of b.type === 'table' ? ['note', 'source'] : ['note']) if (b[key] != null) str(b[key], `${q}.${key}`);
      }
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

// Resolve once relative to the owning report, before document category collection.
export function resolveReport(report, { baseDir = '.' } = {}) {
  validate(report);
  return { ...report, sections: report.sections.map((section, i) => ({ ...section,
    blocks: section.blocks.map((block, j) => {
      if (block.type !== 'chart') return block;
      const path = `sections[${i}].blocks[${j}].chart`;
      let spec = block.chart;
      if (typeof spec === 'string') {
        try { spec = JSON.parse(readFileSync(resolve(baseDir, spec), 'utf8')); }
        catch { throw new Error(`${path}：無法讀取 ${block.chart} 為圖表 JSON；路徑相對於 report.json。`); }
      }
      if (!isObject(spec)) throw new Error(`${path}：圖表 JSON 必須是物件。`);
      return { ...block, chart: spec };
    }),
  })) };
}

// The generated 「圖 N」「表 N」 label; data-label tells evals/check-report.mjs not to check its number.
const label = (text) => `<span class="exhibit-label" data-label>${text}</span>`;

// Every chart offers its input numbers as a table inside the caption, so a reader can trace each mark back to the chart JSON
// and its source. Values print as written in the chart JSON, not rounded to the chart's digits; reference lines, split lines
// and baselines follow the table. Screen only: print hides it. evals/check-report.mjs matches it against report.json, or
// without report.json checks its numbers against the manuscript like any other text.
function chartData(spec, m) {
  const num = (v) => (v === null || v === undefined ? MISSING : esc(formatValue(v, { digits: decimalsOf([v]) })));
  // A string is a cell already built here: the not-applicable mark or a labelled box summary.
  const cell = (v) => (typeof v === 'string' ? v : Array.isArray(v) ? v.map(num).join('、') : num(v));
  const byLabel = (items, head, values) => ({ head, rows: items.map((it) => [esc(it.label), ...values(it).map(cell)]) });
  const byX = (head, columns) => ({ head, rows: spec.x.map((x, i) => [esc(x), ...columns.map((values) => num(values[i]))]) });
  const unit = (name, u) => (typeof u === 'string' && u.trim() ? `${name}（${u.trim()}）` : name);
  const axis = { x: spec.xLabel ?? (spec.kind === 'histogram' ? '區間' : 'X'), y: spec.yLabel ?? 'Y' };
  const FIVE = ['最小值', '第一四分位', '中位數', '第三四分位', '最大值'];
  const data = {
    line: () => byX(['', ...spec.series.map((s) => s.name)], spec.series.map((s) => s.values)),
    combo: () => byX(['', unit('金額', spec.amountUnit ?? m.unit), unit('比率', spec.rateUnit ?? '%')], [spec.amounts, spec.rates]),
    dumbbell: () => byLabel(spec.rows, ['', ...spec.periods], (r) => r.values),
    share: () => byLabel(spec.rows, ['', ...spec.categories], (r) => r.values),
    rank: () => byLabel(spec.rows, ['', '數值'], (r) => [r.value]),
    funnel: () => byLabel(spec.steps, ['', '數值'], (s) => [s.value]),
    bridge: () => ({ head: ['', '數值', '類型'], rows: spec.steps.map((s) => [esc(s.label), num(s.value), s.total ? '累計' : '增減']) }),
    // ranges are optional: the column appears only when some row has them, and a row without them is not missing data.
    bullet: () => {
      const ranges = spec.rows.some((r) => r.ranges);
      return byLabel(spec.rows, ['', '實際', '目標', ...(ranges ? ['背景區間'] : [])], (r) => [r.value, r.target, ...(ranges ? [r.ranges ?? '—'] : [])]);
    },
    tornado: () => byLabel(spec.rows, ['', '低', '高'], (r) => [r.low, r.high]),
    waffle: () => ({ head: ['', '數值'], rows: spec.categories.map((c, i) => [esc(c), num(spec.values[i])]) }),
    // An open last bin (to: null) has no upper edge.
    histogram: () => ({ head: [axis.x, unit('數值', spec.suffix)], rows: spec.bins.map((b) => [b.to === null ? `${num(b.from)} 以上` : `${num(b.from)}–${num(b.to)}`, num(b.value)]) }),
    strip: () => byLabel(spec.groups, ['', '數值'], (g) => [g.values]),
    // A group given as a five-number summary prints those five numbers by name, then its outliers.
    box: () => byLabel(spec.groups, ['', '數值'], (g) => [g.summary
      ? FIVE.map((name, i) => `${name} ${num(g.summary[i])}`).join('、') + (g.outliers?.length ? `；離群值 ${g.outliers.map(num).join('、')}` : '')
      : g.values]),
    heat: () => ({ head: ['', ...spec.colLabels], rows: spec.rowLabels.map((r, i) => [esc(r), ...spec.values[i].map(num)]) }),
    scatter: () => byLabel(spec.points, ['', axis.x, unit(axis.y, spec.suffix)], (p) => [p.x, p.y]),
  };
  Object.assign(data, { multiples: data.line, grouped: data.line, slope: data.dumbbell, sharetrend: data.share, mekko: data.share,
    ordered: data.rank, pareto: data.rank, matrix: data.scatter });
  // A table chart already shows every number as text.
  if (!data[spec.kind]) return '';
  const { head, rows } = data[spec.kind]();
  const at = (point) => ['x', 'y'].filter((k) => typeof point?.[k] === 'number').map((k) => `${esc(axis[k])} ${num(point[k])}`).join('，');
  const extras = [
    ...(spec.refs ?? []).map((r) => `參考線${r.label ? `「${esc(r.label)}」` : ''}：${at(r)}`),
    at(spec.split) && `分割線：${at(spec.split)}`,
    typeof spec.baseline === 'number' && `基準：${num(spec.baseline)}`,
  ].filter(Boolean);
  return `\n<details class="chart-data"><summary>查看資料</summary>
<div class="table-scroll" tabindex="0" role="region" aria-label="圖表資料，可橫向捲動"><table>
<thead><tr>${head.map((h, i) => `<th scope="col"${i ? ' class="num"' : ''}>${esc(h)}</th>`).join('')}</tr></thead>
<tbody>
${rows.map((r) => `<tr>${r.map((c, i) => (i ? `<td class="num">${c}</td>` : `<th scope="row">${c}</th>`)).join('')}</tr>`).join('\n')}
</tbody>
</table></div>${extras.length ? `\n<p>${extras.join('；')}</p>` : ''}
</details>`;
}

function figure(block, n, where, warnings, categoryOrder) {
  const spec = block.chart;
  let out;
  try { out = render(spec, { chartPx: T.screen?.type?.chart ?? 24, width: Math.round(6.8 * T.slide.pxPerIn), height: reportHeight(prepare(spec, { categoryOrder })), categoryOrder }); }
  catch (error) { throw new Error(`${where}.chart：${error.message}`); }
  const m = out.model;
  if (!m.source) throw new Error(`${where}.chart 缺少 source；請在圖表 JSON 填資料來源。`);
  for (const w of m.warnings) warnings.push(`${where}「${block.title}」：${w}`);
  const notes = [block.note, typeof spec.note === 'string' ? spec.note : null,
    m.missing.length && T.dataDisplay.missing.sourceField.replace('{item}', m.missing.join('、'))].filter(Boolean);
  // The title sits above the chart; unit, period, notes and source go below it, source last.
  const caption = [m.unit && `單位：${m.unit}`, m.period && `期間：${m.period}`, notes.length && `附註：${notes.join('；')}`, `來源：${m.source}`]
    .filter(Boolean).map(esc).join('｜');
  const svg = out.svg.replace('<svg ', `<svg role="img" aria-label="${esc(block.title)}" `);
  return `<figure${block.wide ? ' class="wide"' : ''}>
<p class="exhibit-title">${label(`圖 ${n}`)}${esc(block.title)}</p>
<div class="chart-scroll" tabindex="0" role="region" aria-label="${esc(block.title)}，可橫向捲動">\n${svg}\n</div>
<figcaption>${caption}${chartData(spec, m)}</figcaption>
</figure>`;
}

function table(block, n, where, warnings) {
  const m = prepare({ kind: 'table', columns: block.columns, rows: block.rows, total: block.total, emphasis: block.emphasis });
  for (const w of m.warnings) warnings.push(`${where}：${w}`);
  const cls = (align) => (align === 'end' ? ' class="num"' : '');
  const cell = (c) => (c.value === null ? MISSING : esc(c.text));
  const row = (r) => `<tr${r.total ? ' class="total"' : r.emphasis ? ' class="emphasis"' : ''}>${r.cells.map((c, i) => (i
    ? `<td${cls(c.align)}>${cell(c)}</td>` : `<th scope="row"${cls(c.align)}>${cell(c)}</th>`)).join('')}</tr>`;
  const body = m.rows.filter((r) => !r.total), total = m.rows.filter((r) => r.total);
  const note = [block.note && `附註：${block.note}`, block.source && `來源：${block.source}`].filter(Boolean).map(esc).join('｜');
  return scroll(block.caption ?? '表格', `<table><caption>${label(`表 ${n}`)}${esc(block.caption ?? '')}</caption>
<thead><tr>${m.header.map((h) => `<th scope="col"${cls(h.align)}>${esc(h.text)}</th>`).join('')}</tr></thead>
<tbody>
${body.map(row).join('\n')}
</tbody>${total.length ? `\n<tfoot>${total.map(row).join('')}</tfoot>` : ''}
</table>`, block.wide) + (note ? `\n<p class="exhibit-note">${note}</p>` : '');
}

function compare(block) {
  const rec = (o) => (o.recommended ? ' class="recommended"' : '');
  const value = (v) => (v === undefined ? MISSING : shown(v));
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

function block(b, n, where, warnings, categoryOrder) {
  switch (b.type) {
    case 'text': return `<p>${esc(b.text)}</p>`;
    case 'callout': return `<aside class="callout"><p>${esc(b.text)}</p></aside>`;
    case 'missing': return `<p class="missing">未提供：${esc(b.text)}</p>`;
    case 'chart': return figure(b, n, where, warnings, categoryOrder);
    case 'table': return table(b, n, where, warnings);
    case 'compare': return compare(b);
    case 'close': return close(b);
    case 'list': return `<ul class="diagnosis">\n${b.items.map(item).join('\n')}\n</ul>`;
    case 'process': return `<ol class="flow">\n${b.steps.map((s, i) => item({ ...s, current: i === b.focus })).join('\n')}\n</ol>`;
  }
}

export function buildReport(report, { baseDir = '.' } = {}) {
  report = resolveReport(report, { baseDir });
  const warnings = [];
  // Validate chart shapes before collecting names; errors retain editable paths.
  report.sections.forEach((s, i) => s.blocks.forEach((b, j) => {
    if (b.type !== 'chart') return;
    try { prepare(b.chart); }
    catch (error) { throw new Error(`sections[${i}].blocks[${j}].chart：${error.message}`); }
  }));
  const categoryOrder = documentCategories(report.sections.flatMap((s) => s.blocks.filter((b) => b.type === 'chart').map((b) => b.chart)));
  const folded = categoryColors(categoryOrder, { order: categoryOrder }).folded;
  if (folded.length) warnings.push(`整份報告超過 ${categoryLimit()} 個類別，「${folded.join('、')}」在每張圖都併入「其他」`);
  const ids = report.sections.map((s, i) => s.id ?? `section-${i + 1}`);
  if (report.meta?.length > 3) warnings.push(`封面資訊是 ${report.meta.length} 項，建議最多 3 項`);
  const items = report.summary?.items ?? [];
  if (report.summary && (items.length < 2 || items.length > 3)) warnings.push(`摘要數字是 ${items.length} 格，建議 2～3 格`);
  let figures = 0, tables = 0;
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
  // Page 1 holds the cover band, contents and summary, then breaks; with cover: "page" it holds the cover only.
  const front = parts.splice(0, report.cover === 'page' ? 1 : parts.length);
  parts.unshift(`<div class="report-front"${report.cover === 'page' ? ' data-cover="page"' : ''}>\n${front.join('\n')}\n</div>`);
  report.sections.forEach((s, i) => {
    const body = s.blocks.map((b, j) => {
      const n = b.type === 'chart' ? ++figures : b.type === 'table' ? ++tables : 0;
      return block(b, n, `第 ${i + 1} 節第 ${j + 1} 個元件`, warnings, categoryOrder);
    });
    const sources = s.sources ? `\n<footer class="sources">\n<h3>來源與附註</h3>\n${s.sources.map((t) => `<p>${esc(t)}</p>`).join('\n')}\n</footer>` : '';
    parts.push(`<section aria-labelledby="${ids[i]}">
<header class="section-heading">
${s.kicker ? `<p class="eyebrow">${esc(s.kicker)}</p>\n` : ''}<h2 id="${ids[i]}">${esc(s.claim)}</h2>${s.lede ? `\n<p>${esc(s.lede)}</p>` : ''}
</header>
${body.join('\n')}${sources}
</section>`);
  });
  // The print footer reads the title and its separator from this CSS string; escape it for CSS first, then for the attribute.
  const footerTitle = `${report.title.replace(/[\\']/g, '\\$&').replace(/\s+/g, ' ')} | `;
  const html = `<!doctype html>
<html lang="zh-Hant" style="--report-title: '${esc(footerTitle)}'">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(report.title)}</title>
<style id="${SLUG}-theme">
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
      mkdirSync(dirname(output), { recursive: true });
      writeFileSync(output, result.html);
      for (const w of result.warnings) console.error(`警告：${w}`);
      console.log(`完成：${result.sections} 節、${result.figures} 張圖，${result.warnings.length} 項警告 → ${output}`);
    } catch (error) {
      console.error(`錯誤：${error.message}`);
      process.exitCode = 1;
    }
  }
}

// Check visible report copy, including SVG labels, against the source manuscript.
import { readFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { buildReport, resolveReport } from '../scripts/report.js';
import { numbers, found, calculations } from './numbers.mjs';
import { isMain } from '../scripts/main.js';

const hiddenTags = new Set(['head', 'style', 'script', 'template', 'noscript', 'defs', 'title', 'desc']);
const voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'path', 'rect', 'line', 'circle', 'polygon', 'polyline', 'ellipse', 'use']);
const blockTags = new Set(['p', 'div', 'li', 'tr', 'table', 'header', 'footer', 'section', 'article', 'figure', 'figcaption', 'h1', 'h2', 'h3', 'br', 'th', 'td', 'dt', 'dd', 'text']);

function decode(text) {
  const named = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
  return text.replace(/&(#x[\da-f]+|#\d+|[a-z]+);/gi, (all, entity) => {
    if (entity[0] !== '#') return named[entity.toLowerCase()] ?? all;
    const value = entity[1].toLowerCase() === 'x' ? parseInt(entity.slice(2), 16) : Number(entity.slice(1));
    return Number.isInteger(value) && value >= 0 && value <= 0x10ffff ? String.fromCodePoint(value) : all;
  });
}

function reportParts(html) {
  const blocks = [{ label: '文件', text: '' }], sections = [blocks[0]], figures = [], activeFigures = [], tags = [];
  const append = (value) => {
    sections.at(-1).text += value;
    if (tags.some((tag) => tag.name === 'figcaption')) for (const figure of activeFigures) figure.caption += value;
  };
  for (const part of html.replace(/<!--[\s\S]*?-->/g, '').match(/<[^>]*>|[^<]+/g) ?? []) {
    if (!part.startsWith('<')) {
      const text = decode(part);
      if (!tags.some((tag) => tag.hidden) && !(tags.at(-1)?.label && /^\s*[圖表] \d+\s*$/.test(text))) append(text);
      continue;
    }
    const match = part.match(/^<\s*(\/?)\s*([a-z][\w:-]*)\b/i);
    if (!match) continue;
    const name = match[2].toLowerCase(), closing = Boolean(match[1]);
    if (closing) {
      if (blockTags.has(name) && !tags.some((tag) => tag.hidden)) append('\n');
      if (name === 'section' && sections.length > 1) sections.pop();
      if (name === 'figure') activeFigures.pop();
      const index = tags.findLastIndex((tag) => tag.name === name);
      if (index >= 0) tags.splice(index);
    } else {
      if (blockTags.has(name) && !tags.some((tag) => tag.hidden)) append('\n');
      if (name === 'section') {
        const section = { label: `第 ${blocks.length} 節`, text: '' };
        blocks.push(section);
        sections.push(section);
      }
      if (name === 'figure') {
        const figure = { caption: '', hasCaption: false };
        figures.push(figure);
        activeFigures.push(figure);
      }
      if (name === 'figcaption' && activeFigures.length) activeFigures.at(-1).hasCaption = true;
      // data-tick on an SVG <text> marks an axis scale label from scripts/svg.js; like evals/check.mjs, scale ticks are not checked.
      // data-label marks the 「圖 N」「表 N」 label scripts/report.js numbers itself; the same words in body text are still checked.
      if (!voidTags.has(name) && !/\/\s*>$/.test(part)) tags.push({ name, hidden: hiddenTags.has(name) || /\shidden(?:\s|=|>)/i.test(part) || (name === 'text' && /\sdata-tick(?:\s|=|>)/i.test(part)) || /\b(?:display\s*:\s*none|visibility\s*:\s*hidden)\b/i.test(part), label: name === 'span' && /\sdata-label(?:\s|=|>)/i.test(part) });
    }
  }
  return { blocks, figures };
}

// Locate SVG by its element path, not an HTML-authored exemption token. Matching a
// regenerated chart includes every label, axis, shape and attribute at that position.
function chartSpans(html) {
  const root = { path: '', children: 0, section: 0 }, stack = [root], spans = [];
  let section = 0;
  for (const match of html.matchAll(/<!--[\s\S]*?-->|<[^>]*>/g)) {
    const tag = match[0].match(/^<\s*(\/?)\s*([a-z][\w:-]*)\b/i);
    if (!tag) continue;
    const name = tag[2].toLowerCase();
    if (tag[1]) {
      const index = stack.findLastIndex((node) => node.name === name);
      if (index < 1) throw new Error(`HTML 結構不匹配：${name} 結尾沒有對應起點。`);
      const node = stack[index];
      if (name === 'svg') spans.push({ start: node.start, end: match.index + match[0].length, path: node.path, section: node.section });
      stack.splice(index);
    } else {
      const parent = stack.at(-1);
      const node = { name, path: `${parent.path}/${name}[${parent.children++}]`, children: 0, start: match.index, section: name === 'section' ? ++section : parent.section };
      if (!voidTags.has(name) && !/\/\s*>$/.test(match[0])) stack.push(node);
    }
  }
  if (stack.some((node) => node.name === 'svg')) throw new Error('HTML 圖表缺少 </svg>。');
  return spans;
}

function chartInputs(value, path, original) {
  if (typeof value === 'string' || typeof value === 'number') {
    for (const n of numbers(value)) if (!found(n, original)) throw new Error(`${path}：原稿找不到數字 ${n.text}。`);
  } else if (Array.isArray(value)) value.forEach((v, i) => chartInputs(v, `${path}[${i}]`, original));
  else if (value && typeof value === 'object') for (const [key, v] of Object.entries(value)) {
    if (key === 'digits' || key === 'focus' && typeof v === 'number') continue;
    chartInputs(v, `${path}.${key}`, original);
  }
}

function verifiedCharts(html, report, baseDir, original) {
  const resolved = resolveReport(report, { baseDir });
  const expected = buildReport(resolved).html;
  const actualSpans = chartSpans(html), expectedSpans = chartSpans(expected);
  if (actualSpans.length !== expectedSpans.length) throw new Error(`圖表數量不匹配：HTML ${actualSpans.length}，report.json ${expectedSpans.length}。`);
  for (let i = 0; i < actualSpans.length; i++) {
    const a = actualSpans[i], e = expectedSpans[i];
    if (a.path !== e.path || html.slice(a.start, a.end) !== expected.slice(e.start, e.end)) {
      throw new Error(`第 ${i + 1} 張圖 SVG 或位置與 report.json 圖表輸入不匹配；請使用相同設計層重新產生並核對。`);
    }
  }
  // Only spans whose complete content AND position matched are replaced. The rest
  // still uses the legacy numeric scanner; no derived numeric token enters it.
  for (const span of actualSpans.toReversed()) html = html.slice(0, span.start) + '<svg></svg>' + html.slice(span.end);
  // Use only visible copy from the delivered section after removing all SVGs.
  // Model-generated labels cannot supply equations or authorize another chart's inputs.
  const { blocks } = reportParts(html);
  const charts = resolved.sections.flatMap((section, i) => section.blocks.flatMap((block, j) =>
    block.type === 'chart' ? [{ chart: block.chart, path: `sections[${i}].blocks[${j}].chart` }] : []));
  charts.forEach(({ chart, path }, i) => {
    const section = actualSpans[i].section;
    const allowed = [...original, ...calculations({ notes: blocks[section].text }, original, section + 1)];
    chartInputs(chart, path, allowed);
  });
  return html;
}

export function checkReport(html, script, { report, baseDir = '.' } = {}) {
  if (typeof html !== 'string' || !html.trim()) throw new Error('report.html 必須是非空 HTML。');
  if (typeof script !== 'string' || !script.trim()) throw new Error('script.md 必須是非空文字稿。');
  if (html.includes('{{')) throw new Error('報告仍有 {{…}} 示意文字，請刪除或換成原稿內容。');
  const original = numbers(script);
  if (original.some((n) => !n.valid)) throw new Error('原稿含無法以有限數字精確表示的數值；請核對科學記號或調整單位。');
  if (report !== undefined) html = verifiedCharts(html.replace(/\r\n/g, '\n'), report, baseDir, original);
  const { blocks, figures } = reportParts(html);
  for (const [i, block] of blocks.entries()) {
    const allowed = [...original, ...calculations({ notes: block.text }, original, i + 1)];
    for (const value of numbers(block.text)) {
      if (!found(value, allowed)) throw new Error(`${block.label}：原稿找不到數字 ${value.text}；請改回原稿數字，或在同節寫出可核對的加減算式。`);
    }
  }
  for (const [i, figure] of figures.entries()) {
    if (!figure.hasCaption || !figure.caption.includes('來源')) throw new Error(`第 ${i + 1} 張圖缺少含「來源」的 figcaption。`);
  }
  return { sections: blocks.length - 1, figures: figures.length };
}

if (isMain(import.meta.url)) {
  const [htmlFile, scriptFile, reportFile] = process.argv.slice(2);
  if (!htmlFile || !scriptFile) {
    console.error('用法：node evals/check-report.mjs report.html script.md [report.json]');
    process.exitCode = 2;
  } else {
    try {
      let options = {};
      if (reportFile) {
        try { options = { report: JSON.parse(readFileSync(reportFile, 'utf8')), baseDir: dirname(reportFile) }; }
        catch { throw new Error(`無法讀取 ${reportFile} 為 report.json；請確認路徑與 JSON 格式。`); }
      }
      const result = checkReport(readFileSync(htmlFile, 'utf8'), readFileSync(scriptFile, 'utf8'), options);
      console.log(`通過：${result.sections} 節、${result.figures} 張圖；請再檢查列印分頁與手機寬度。`);
    } catch (error) {
      console.error(`驗收失敗：${error.message}`);
      process.exitCode = 1;
    }
  }
}

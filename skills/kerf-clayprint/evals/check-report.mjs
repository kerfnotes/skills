// Check visible report copy, including SVG labels, against the source manuscript.
import { readFileSync } from 'node:fs';
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
      if (!tags.some((tag) => tag.hidden)) append(decode(part));
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
      if (!voidTags.has(name) && !/\/\s*>$/.test(part)) tags.push({ name, hidden: hiddenTags.has(name) || /\shidden(?:\s|=|>)/i.test(part) || /\b(?:display\s*:\s*none|visibility\s*:\s*hidden)\b/i.test(part) });
    }
  }
  return { blocks, figures };
}

export function checkReport(html, script) {
  if (typeof html !== 'string' || !html.trim()) throw new Error('report.html 必須是非空 HTML。');
  if (typeof script !== 'string' || !script.trim()) throw new Error('script.md 必須是非空文字稿。');
  if (html.includes('{{')) throw new Error('報告仍有 {{…}} 示意文字，請刪除或換成原稿內容。');
  const original = numbers(script);
  if (original.some((n) => !n.valid)) throw new Error('原稿含無法以有限數字精確表示的數值；請核對科學記號或調整單位。');
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
  const [htmlFile, scriptFile] = process.argv.slice(2);
  if (!htmlFile || !scriptFile) {
    console.error('用法：node evals/check-report.mjs report.html script.md');
    process.exitCode = 2;
  } else {
    try {
      const result = checkReport(readFileSync(htmlFile, 'utf8'), readFileSync(scriptFile, 'utf8'));
      console.log(`通過：${result.sections} 節、${result.figures} 張圖；請再檢查列印分頁與手機寬度。`);
    } catch (error) {
      console.error(`驗收失敗：${error.message}`);
      process.exitCode = 1;
    }
  }
}

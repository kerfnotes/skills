// A figure is an SVG the author drew because the chart menu has no chart for the claim. It is placed as drawn, never redrawn:
//   story.json, evidence page:  "visual": { "figure": "flow.svg" }
//   report.json, block:         { "type": "figure", "title": "…", "figure": "flow.svg", "source": "…" }
// The path is relative to the JSON file. Resolving reads the file once into { file, svg, width, height }; every later step
// (validation, build, numeric checks) works on that content and never reads the disk again.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// A visual that holds a figure instead of a chart kind.
export const isFigure = (v) => isObject(v) && v.figure !== undefined;
// What a JSON file may write: a path, or the resolved form with the SVG text itself.
export const figureInput = (v) => (typeof v === 'string' && v.trim().length > 0) || (isObject(v) && typeof v.svg === 'string');

export function decode(text) {
  const named = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
  return text.replace(/&(#x[\da-f]+|#\d+|[a-z]+);/gi, (all, entity) => {
    if (entity[0] !== '#') return named[entity.toLowerCase()] ?? all;
    const value = entity[1].toLowerCase() === 'x' ? parseInt(entity.slice(2), 16) : Number(entity.slice(1));
    return Number.isInteger(value) && value >= 0 && value <= 0x10ffff ? String.fromCodePoint(value) : all;
  });
}

// Anything that could put a number on screen where the checkers cannot read it, or that PowerPoint and the PNG fallback do not draw.
const REFUSED = [
  [/<script\b/i, '<script>'],
  [/<style\b/i, '<style>：樣式改寫在元素屬性上（如 fill、font-size），PowerPoint 與同頁其他圖才不受影響'],
  [/<foreignObject\b/i, '<foreignObject>：文字改用 <text>'],
  [/<image\b/i, '<image>：點陣圖上的字無法核對，改用向量圖形與 <text>'],
  [/<!/, '<!DOCTYPE […]>、<!ENTITY> 或 <![CDATA[…]]>：文字直接寫在 <text> 裡'],
  [/\sdata-(?:tick|label)\b/i, 'data-tick 或 data-label 屬性：這兩個標記保留給產生器'],
];

// One normal form for the deck, the report and the checkers: LF line ends, no prolog or comments, a single <svg> root with a viewBox.
export function cleanFigure(source, path = 'figure') {
  const fail = (why) => { throw new Error(`${path}：${why}`); };
  if (typeof source !== 'string' || !source.trim()) fail('自畫圖是空的；請提供 SVG 內容。');
  let svg = source.replace(/^﻿/, '').replace(/\r\n?/g, '\n').replace(/<\?xml[\s\S]*?\?>/gi, '')
    .replace(/<!DOCTYPE[^>[]*>/gi, '').replace(/<!--[\s\S]*?-->/g, '').trim();
  for (const [pattern, what] of REFUSED) if (pattern.test(svg)) fail(`自畫圖不能含 ${what}。`);
  if (!/^<svg\b[^>]*>/i.test(svg) || !/<\/svg\s*>$/i.test(svg)) fail('自畫圖必須是一個完整的 <svg>…</svg>。');
  if (svg.match(/<svg\b/gi).length > 1) fail('自畫圖只能有一個 <svg>；請把巢狀的 <svg> 改成 <g>。');
  const root = svg.match(/^<svg\b[^>]*>/i)[0];
  const attr = (name) => root.match(new RegExp(`\\s${name}\\s*=\\s*["']([^"']*)["']`, 'i'))?.[1];
  const box = attr('viewBox')?.trim().split(/[\s,]+/).map(Number);
  let [width, height] = box?.length === 4 ? box.slice(2) : ['width', 'height'].map((name) => Number(attr(name)?.trim().replace(/px$/i, '')));
  if (!(width > 0 && height > 0)) fail('自畫圖的 <svg> 需要 viewBox="0 0 寬 高"（或數字的 width 與 height），才能等比放進版面。');
  if (box?.length !== 4) svg = svg.replace(/^<svg\b/i, `$& viewBox="0 0 ${width} ${height}"`);
  return { svg, width, height };
}

// Every piece of text in the figure, one <text> per line; <tspan> pieces stay joined so a split number still reads as one.
// <title> and <desc> are included: stricter than the screen, never looser.
export const figureText = (svg) => decode(svg.replace(/<\/?text\b[^>]*>/gi, '\n').replace(/<[^>]*>/g, ''));

export function resolveFigure(figure, { baseDir = '.', path = 'figure' } = {}) {
  if (isObject(figure) && typeof figure.svg === 'string') return { ...figure, ...cleanFigure(figure.svg, path) };
  if (typeof figure !== 'string' || !figure.trim()) throw new Error(`${path}：請填 SVG 檔路徑，相對於這份 JSON 所在的資料夾。`);
  let source;
  // Backslashes become slashes so a path written on Windows also resolves elsewhere.
  try { source = readFileSync(resolve(baseDir, figure.replace(/\\/g, '/')), 'utf8'); }
  catch { throw new Error(`${path}：無法讀取 ${figure}；路徑相對於這份 JSON 所在的資料夾。`); }
  return { file: figure, ...cleanFigure(source, path) };
}

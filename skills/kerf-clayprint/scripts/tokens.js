import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Read decks (story.json "mode": "read") lay design/read.json over the active design layer: smaller type, tighter top and bottom margins, a narrower evidence chart
// so the reading note gets a wider column, and wider capacity.
// Modules read sizes at import, so the mode is fixed per process; scripts/main.js reruns a CLI under the story's mode.
const mode = process.env.CLAYPRINT_MODE || 'present';
if (!['present', 'read'].includes(mode)) throw new Error(`CLAYPRINT_MODE 只能是 present 或 read，收到 ${mode}`);
export const MODE = mode;

// Report print page: margins in mm (indent and gutter are the body padding inside the 22 / 14 mm @page lines), type in pt.
const PRINT = { margin: { top: 12, right: 14, bottom: 15, left: 22, indent: 28, gutter: 11 },
  type: { body: 10.5, leading: 16, heading: 24, sub: 12, small: 7, cover: 30, summary: 16 } };

// Explicit and environment paths follow cwd; the default follows this module.
export function loadTokens(path = process.env.CLAYPRINT_TOKENS || fileURLToPath(new URL('../design/tokens.json', import.meta.url))) {
  let tokens;
  try {
    tokens = JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    throw new Error(`無法載入 Clayprint 設計層 ${path}：${error instanceof SyntaxError ? 'JSON 格式錯誤' : '檔案無法讀取'}`, { cause: error });
  }
  tokens.print = { margin: { ...PRINT.margin, ...tokens.print?.margin }, type: { ...PRINT.type, ...tokens.print?.type } };
  if (MODE !== 'read') return tokens;
  const read = JSON.parse(readFileSync(new URL('../design/read.json', import.meta.url), 'utf8'));
  // Type changes px only; each size keeps the layer's weight and color. Read-only sizes (chart, source) take label's.
  const type = { ...tokens.type };
  for (const [key, px] of Object.entries(read.type)) type[key] = typeof tokens.type[key] === 'number' ? px : { ...(tokens.type[key] ?? tokens.type.label), px };
  return { ...tokens, type, margin: { ...tokens.margin, ...read.margin }, chartArea: { ...tokens.chartArea, ...read.chartArea }, capacity: read.capacity };
}

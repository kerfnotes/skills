import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Read decks (story.json "mode": "read") lay design/read.json over the active design layer: smaller type, a narrower evidence chart
// so the reading note gets a wider column, and wider capacity.
// Modules read sizes at import, so the mode is fixed per process; scripts/main.js reruns a CLI under the story's mode.
const mode = process.env.CLAYPRINT_MODE || 'present';
if (!['present', 'read'].includes(mode)) throw new Error(`CLAYPRINT_MODE 只能是 present 或 read，收到 ${mode}`);
export const MODE = mode;

// Explicit and environment paths follow cwd; the default follows this module.
export function loadTokens(path = process.env.CLAYPRINT_TOKENS || fileURLToPath(new URL('../design/tokens.json', import.meta.url))) {
  let tokens;
  try {
    tokens = JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    throw new Error(`無法載入 Clayprint 設計層 ${path}：${error instanceof SyntaxError ? 'JSON 格式錯誤' : '檔案無法讀取'}`, { cause: error });
  }
  if (MODE !== 'read') return tokens;
  const read = JSON.parse(readFileSync(new URL('../design/read.json', import.meta.url), 'utf8'));
  // Type changes px only; each size keeps the layer's weight and color.
  const type = Object.fromEntries(Object.entries(tokens.type).map(([key, value]) => [key,
    !(key in read.type) ? value : typeof value === 'number' ? read.type[key] : { ...value, px: read.type[key] }]));
  return { ...tokens, type, chartArea: { ...tokens.chartArea, ...read.chartArea }, capacity: read.capacity };
}

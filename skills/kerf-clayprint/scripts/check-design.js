import { pathToFileURL } from 'node:url';
import { contrast, textOn } from './core.js';
import { loadTokens } from './tokens.js';
import { BRAND } from './brand.js';

// 公開數學資料；檢查流程自行實作，沒有引入外部驗證器。
// WCAG：https://www.w3.org/TR/WCAG22/#dfn-relative-luminance
// OKLab：https://bottosson.github.io/posts/oklab/
// Machado 2009，嚴重度 1.0：https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html
const MACHADO = {
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
  tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
};
const VISION = { protan: '紅色盲（protan）', deutan: '綠色盲（deutan）', tritan: '藍色盲（tritan）' };
const HEX = /^#[0-9a-f]{6}$/i;
const multiply = (matrix, vector) => matrix.map((row) => row.reduce((sum, value, i) => sum + value * vector[i], 0));

export function simulateRgb(hex, vision) {
  if (!HEX.test(hex)) throw new Error(`色碼 ${hex} 格式不符：請使用 #RRGGBB`);
  const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  if (!vision) return rgb;
  if (!Object.hasOwn(MACHADO, vision)) throw new Error(`不認得的色盲類型：${vision}`);
  // 矩陣作用在線性 RGB；裁切顯示色域後直接轉 OKLab，避免再次套用 gamma。
  return multiply(MACHADO[vision], rgb).map((v) => Math.max(0, Math.min(1, v)));
}

export function oklab(hex, vision) {
  const cones = multiply([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
  ], simulateRgb(hex, vision)).map(Math.cbrt);
  return multiply([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
  ], cones);
}

export function deltaE(first, second, vision) {
  const a = oklab(first, vision), b = oklab(second, vision);
  return Math.hypot(...a.map((v, i) => v - b[i])) * 100;
}

// 取包住所有色相的最短圓弧；359° 與 1° 相差 2°，無彩色不具有色相。
export function hueSpread(labs) {
  const hues = labs.filter(([, a, b]) => Math.hypot(a, b) > 1e-4)
    .map(([, a, b]) => (Math.atan2(b, a) * 180 / Math.PI + 360) % 360).sort((a, b) => a - b);
  if (hues.length < 2) return 0;
  const gaps = hues.map((hue, i) => (i === hues.length - 1 ? hues[0] + 360 : hues[i + 1]) - hue);
  return 360 - Math.max(...gaps);
}

export function checkDesign(design) {
  const failures = [], warnings = [];
  let checks = 0;
  const failFormat = (token, actual, expected, advice) => {
    checks++;
    failures.push(`${token} 格式不符，收到 ${JSON.stringify(actual) ?? '未提供'}（要求 ${expected}）：${advice}`);
  };
  const validHex = (token, value) => {
    if (typeof value !== 'string' || !HEX.test(value)) failFormat(token, value, '#RRGGBB', '填入完整六位十六進位色碼');
  };
  const c = design?.color;
  for (const key of ['text', 'textSecondary', 'better', 'worse', 'unchanged', 'dark', 'tint', 'focus', 'gray', 'other']) {
    validHex(`color.${key}`, c?.[key]);
  }
  // Optional: the table header rule; without it the engine uses color.text.
  if (c?.tableRule !== undefined) validHex('color.tableRule', c.tableRule);
  for (const [key, min] of [['onDark', 2], ['categorical', 1], ['ordered', 2]]) {
    const values = c?.[key];
    if (!Array.isArray(values) || values.length < min) failFormat(`color.${key}`, values, `至少 ${min} 個色碼`, '補足色階，不能用空色階產生圖表');
    if (Array.isArray(values)) values.forEach((value, i) => validHex(`color.${key}[${i}]`, value));
  }
  if (!design?.textOnFill || typeof design.textOnFill !== 'object' || Array.isArray(design.textOnFill)) {
    failFormat('textOnFill', design?.textOnFill, '字色對應填色陣列的物件', '用 {} 啟用自動判斷，或填入字色與色塊對照');
  } else {
    for (const [ink, fills] of Object.entries(design.textOnFill)) {
      validHex('textOnFill 字色', ink);
      if (!Array.isArray(fills)) failFormat(`textOnFill[${ink}]`, fills, '色碼陣列', '將填色放入陣列');
      else fills.forEach((fill, i) => validHex(`textOnFill[${ink}][${i}]`, fill));
    }
  }
  if (failures.length) return { failures, warnings, checks };

  const minimum = (label, measured, threshold, advice, warning = false, digits = 2) => {
    checks++;
    if (!Number.isFinite(measured) || measured < threshold) {
      (warning ? warnings : failures).push(`${label} ${measured.toFixed(digits)}（門檻 ≥ ${threshold}）：${advice}`);
    }
  };
  const background = c.onDark[0];
  for (const key of ['text', 'textSecondary', 'better', 'worse', 'unchanged']) {
    minimum(`color.${key} ${c[key]} 在底色 onDark[0] ${background} 上對比`, contrast(c[key], background), 4.5, '拉開文字與底色的亮度差');
  }
  c.onDark.slice(0, 2).forEach((ink, i) => minimum(`color.onDark[${i}] ${ink} 在 dark ${c.dark} 上對比`, contrast(ink, c.dark), 4.5, '提高字色亮度，或壓低 dark 的亮度'));
  minimum(`color.text ${c.text} 在 tint ${c.tint} 上對比`, contrast(c.text, c.tint), 4.5, '拉開正文與 tint 的亮度差');

  const fills = [['focus', c.focus], ...c.categorical.map((v, i) => [`categorical[${i}]`, v]), ...c.ordered.map((v, i) => [`ordered[${i}]`, v]), ['other', c.other], ['tint', c.tint]];
  for (const [key, fill] of fills) {
    const ink = textOn(fill, design);
    minimum(`color.${key} ${fill} 的標籤字色 ${ink} 對比`, contrast(fill, ink), 4.5, '調整 textOnFill 的字色；必要時拉開填色與文字的亮度差');
  }
  for (const [key, fill] of [['focus', c.focus], ...c.categorical.map((v, i) => [`categorical[${i}]`, v])]) {
    minimum(`color.${key} ${fill} 與底色 ${background} 對比`, contrast(fill, background), 3, '需要直接標值或表格；也可加深標記顏色', true);
  }
  minimum(`color.ordered[0] ${c.ordered[0]} 與底色 ${background} 對比`, contrast(c.ordered[0], background), 2, '加深 ordered 最淺一階，並維持由淺到深');

  for (let i = 0; i < c.categorical.length - 1; i++) {
    const first = c.categorical[i], second = c.categorical[i + 1];
    const pair = `color.categorical[${i}] ${first} 與 categorical[${i + 1}] ${second}`;
    minimum(`${pair} 在正常色覺下色差 ΔE`, deltaE(first, second), 15, '把其中一色的亮度拉開，或換色相');
    for (const [vision, label] of Object.entries(VISION)) {
      const distance = deltaE(first, second, vision);
      minimum(`${pair} 在${label}下色差 ΔE`, distance, 6, '把其中一色的亮度拉開，或換色相');
      if (distance >= 6 && distance < 8) warnings.push(`${pair} 在${label}下色差 ΔE ${distance.toFixed(2)}（警告區間 6～8，建議 ≥ 8）：需要直接標值；也可拉開亮度或換色相`);
    }
  }
  const focusPair = `color.focus ${c.focus} 與 gray ${c.gray}`;
  minimum(`${focusPair} 在正常色覺下色差 ΔE`, deltaE(c.focus, c.gray), 15, '拉開 focus 與 gray 的亮度或色相，讓重點可辨識');
  for (const [vision, label] of Object.entries(VISION)) {
    minimum(`${focusPair} 在${label}下色差 ΔE`, deltaE(c.focus, c.gray, vision), 8, '拉開 focus 與 gray 的亮度，讓重點可辨識');
  }
  const ordered = c.ordered.map((color) => oklab(color));
  for (let i = 0; i < ordered.length - 1; i++) {
    minimum(`color.ordered[${i}] ${c.ordered[i]} → ordered[${i + 1}] ${c.ordered[i + 1]} 的 OKLab 亮度下降量`, ordered[i][0] - ordered[i + 1][0], 0.06, '由淺到深排列，並拉開相鄰亮度至少 0.06', false, 4);
  }
  const spread = hueSpread(ordered);
  checks++;
  if (spread > 20) failures.push(`color.ordered ${c.ordered.join('、')} 的色相分散 ${spread.toFixed(2)}°（門檻 ≤ 20°）：將各階色相靠攏，以亮度表達順序`);
  return { failures, warnings, checks };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const design = loadTokens(process.argv[2]);
    const { failures, warnings, checks } = checkDesign(design);
    warnings.forEach((message) => console.log(`警告：${message}`));
    failures.forEach((message) => console.error(`失敗：${message}`));
    console.log(`${BRAND} 設計層 ${design.name ?? '未命名'}：${failures.length ? '未通過' : '通過'} ${checks} 項檢查，${failures.length} 項失敗、${warnings.length} 項警告。`);
    process.exitCode = failures.length ? 1 : 0;
  } catch (error) {
    console.error(`${BRAND} 設計層檢查失敗：${error.message}`);
    process.exitCode = 1;
  }
}

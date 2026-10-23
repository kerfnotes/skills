// Print a report to PDF with headless Chrome, Edge, Chromium or Brave, then check every page.
// node scripts/pdf.js out/report.html out/print [--letter] [--paper clay]
// Fill and right overflow come from ink rows in a 50 dpi grayscale render; split exhibits from pdftotext page by page.
import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { tmpdir } from 'node:os';
import { basename, dirname, extname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isMain } from './main.js';
import { contactSheet, findProgram, numbered, programFiles } from './preview.js';

const NO_BROWSER = '找不到 Chrome、Edge、Chromium 或 Brave；設 CLAYPRINT_CHROME 指向瀏覽器執行檔後重跑。';

export function findBrowser({ platform = process.platform, env = process.env, exists = existsSync } = {}) {
  if (env.CLAYPRINT_CHROME) return exists(env.CLAYPRINT_CHROME) ? env.CLAYPRINT_CHROME : null;
  const installed = platform === 'darwin'
    ? ['Google Chrome', 'Chromium', 'Microsoft Edge', 'Brave Browser'].map((app) => `/Applications/${app}.app/Contents/MacOS/${app}`)
    : platform === 'win32'
      ? programFiles(env, ['Google', 'Chrome', 'Application', 'chrome.exe'], ['Chromium', 'Application', 'chrome.exe'],
        ['Microsoft', 'Edge', 'Application', 'msedge.exe'], ['BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'])
      : [];
  return findProgram(['google-chrome', 'chromium', 'chrome', 'msedge'], installed, { platform, env, exists });
}

// Gray below 240 is ink: tints and rules count, white and clay paper (about 249) do not.
const INK = 240;

// One P5 page: fill is the last ink row within the type area (12 mm top, 15 mm bottom; page 1 starts at the paper edge
// because its banner bleeds), overflow is how far ink reaches past 14 mm from the right edge, with 1 mm to spare.
// The footer sits in the bottom margin, so neither scan sees it. Chrome clips anything pushed past the 22 mm left margin,
// so a row with ink left of it is a deliberate bleed (page 1's cover band and rule) and does not count as overflow.
// Content wider than the page does not reach past 14 mm: Chrome shrinks the whole page to fit, about the 22 mm line,
// so the body column (normally 22 + 28 mm) moves left. Its left edge is the leftmost start shared by two or more runs
// of ink rows right of 30 mm: headings, quotes, wide figures and wide-table cells (22–26 mm) stay put and are skipped,
// and a chart is one tall run, so its axis does not count twice.
function measure(pgm, dpi, firstPage) {
  const head = /^P5\s+(\d+)\s+(\d+)\s+\d+\s/.exec(pgm.subarray(0, 64).toString('latin1'));
  const [w, h] = [Number(head[1]), Number(head[2])], data = pgm.subarray(head[0].length), mm = dpi / 25.4;
  const top = firstPage ? 0 : Math.round(12 * mm), bottom = h - Math.round(15 * mm), right = w - 14 * mm;
  const left = Math.round(21 * mm);
  let last = -1, far = -1, run = Infinity;
  const starts = new Map();
  const close = () => { if (run < Infinity) starts.set(run, (starts.get(run) ?? 0) + 1); run = Infinity; };
  for (let y = top; y < bottom; y++) {
    const row = data.subarray(y * w, (y + 1) * w);
    const start = row.findIndex((v) => v < INK);
    if (start < 0) { close(); continue; }
    last = y;
    if (start < left) { close(); continue; }
    far = Math.max(far, row.findLastIndex((v) => v < INK));
    run = Math.min(run, start);
  }
  close();
  const column = Math.min(...[...starts].filter(([x, n]) => x >= 30 * mm && n >= 2).map(([x]) => x));
  return {
    fill: last < 0 ? 0 : Math.min(100, Math.round((last - top) / (bottom - top) * 100)),
    overflow: far + 1 > right + mm ? Math.round((far + 1 - right) / mm) : 0,
    scale: firstPage || column === Infinity ? 1 : (column / mm - 22) / 28,
  };
}

// 圖 N or 表 N label and the next 來源 line on different pages. Labels are their own line in pdftotext ("圖1").
// Tables count only when they carry a source and have eight body rows or fewer; longer ones may break
// (scripts/theme-css.js lets a table break from its ninth row, :has(tbody tr:nth-child(9)); change both together).
function splitExhibits(pages, html) {
  const tables = new Map();
  for (const [, n, body, note = ''] of html.matchAll(/data-label>表\s*(\d+)<\/span>([\s\S]*?)<\/table>\s*<\/div>(?:\s*<p class="exhibit-note">([\s\S]*?)<\/p>)?/g)) {
    tables.set(n, { rows: (body.match(/<tbody>[\s\S]*?<\/tbody>/)?.[0].match(/<tr\b/g) ?? []).length, source: note.includes('來源') });
  }
  const lines = pages.flatMap((text, i) => text.split('\n').map((line) => ({ page: i + 1, line })));
  const seen = new Set(), warnings = [];
  lines.forEach(({ page, line }, i) => {
    const label = /^\s*([圖表])\s*(\d+)\s*$/.exec(line);
    if (!label || seen.has(label[1] + label[2])) return;
    seen.add(label[1] + label[2]);
    const [, kind, n] = label, table = tables.get(n);
    if (kind === '表' && !(table?.source && table.rows <= 8)) return;
    const source = lines.slice(i + 1).find((l) => l.line.includes('來源'));
    if (!source || source.page === page) return;
    warnings.push(kind === '圖'
      ? `圖 ${n} 的標題在第 ${page} 頁、來源在第 ${source.page} 頁：縮短圖上方的段落，或改小圖。`
      : `表 ${n} 跨第 ${page}–${source.page} 頁：8 列以內不該分頁，縮短表上方的段落。`);
  });
  return warnings;
}

export function printPdf(html, outDir, { letter = false, paper = 'white' } = {}) {
  const browser = findBrowser();
  if (!browser) throw new Error(NO_BROWSER);
  const name = basename(html, extname(html)), pdf = resolve(outDir, `${name}.pdf`), source = readFileSync(html, 'utf8');
  mkdirSync(outDir, { recursive: true });
  // Paper and size switch through root attributes the print CSS reads; a sibling copy keeps the source untouched.
  const attrs = [paper === 'clay' && 'data-paper="clay"', letter && 'data-size="letter"'].filter(Boolean);
  const target = attrs.length ? join(dirname(resolve(html)), `${name}.${randomBytes(4).toString('hex')}.html`) : resolve(html);
  rmSync(pdf, { force: true });
  try {
    if (attrs.length) writeFileSync(target, source.replace(/<html\b/i, `<html ${attrs.join(' ')}`));
    execFileSync(browser, ['--headless', '--disable-gpu', '--no-pdf-header-footer', `--print-to-pdf=${pdf}`, pathToFileURL(target).href],
      { stdio: ['ignore', 'pipe', 'pipe'], timeout: 180000 });
  } finally {
    if (attrs.length) rmSync(target, { force: true });
  }
  if (!existsSync(pdf)) throw new Error('瀏覽器沒有產生 PDF；確認 HTML 能在瀏覽器開啟後重跑。');

  for (const f of numbered(outDir, 'page', 'png')) rmSync(join(outDir, f));
  execFileSync('pdftoppm', ['-r', '100', '-png', pdf, join(outDir, 'page')]);
  const pngs = numbered(outDir, 'page', 'png').map((f, i) => {
    const png = join(outDir, `page-${String(i + 1).padStart(2, '0')}.png`);
    renameSync(join(outDir, f), png);
    return png;
  });
  // Portrait pages, four to a row.
  const sheet = contactSheet(pngs, join(outDir, 'sheet.png'), { perRow: 4, width: 420, height: 580 });

  const tmp = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  let pages;
  try {
    execFileSync('pdftoppm', ['-gray', '-r', '50', pdf, join(tmp, 'm')]);
    pages = numbered(tmp, 'm', 'pgm').map((f, i) => measure(readFileSync(join(tmp, f)), 50, i === 0));
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
  const warnings = [];
  // Page 1 always ends with a page break after the front matter; on later pages a short fill means a block that may not
  // split moved whole to the next page.
  pages.forEach(({ fill }, i) => {
    if (i < pages.length - 1 && fill < 70) warnings.push(i === 0
      ? `第 1 頁只填 ${fill}%：縮短摘要或目錄，或把下一節的開頭段落放進第 1 頁前的摘要。`
      : `第 ${i + 1} 頁只填 ${fill}%：把被推到下一頁的整塊元件前移，或在它前面加一段文字。`);
  });
  // Chrome shrinks the whole document, not one page: warn once, at the first page that shows it.
  const shrunk = pages.findIndex((p) => p.scale < 0.97);
  if (shrunk >= 0) warnings.push(`內容超出右邊界，整份被縮成 ${Math.round(pages[shrunk].scale * 100)}%（第 ${shrunk + 1} 頁起）：減少表格欄數或設 wide: true。`);
  else pages.forEach(({ overflow }, i) => {
    if (overflow) warnings.push(`第 ${i + 1} 頁內容超出右邊界約 ${overflow} mm：減少表格欄數或設 wide: true。`);
  });
  warnings.push(...splitExhibits(execFileSync('pdftotext', [pdf, '-'], { encoding: 'utf8' }).split('\f'), source));
  return { pdf, pngs, sheet, fills: pages.map((p) => p.fill), size: letter ? 'Letter' : 'A4', warnings };
}

if (isMain(import.meta.url)) {
  // Anything unknown (a typo such as --leter, or "--paper clay" passed as one argument) stops with the usage.
  const args = process.argv.slice(2), paths = [];
  let letter = false, paper = 'white', ok = true;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--letter') letter = true;
    else if (args[i] === '--paper') { paper = args[++i]; ok &&= paper === 'clay'; }
    else if (args[i].startsWith('--')) ok = false;
    else paths.push(args[i]);
  }
  const [html, outDir] = paths;
  if (!ok || paths.length !== 2) {
    console.error('用法：node scripts/pdf.js out/report.html out/print [--letter] [--paper clay]');
    process.exit(2);
  }
  try {
    const result = printPdf(html, outDir, { letter, paper });
    for (const w of result.warnings) console.error(`警告：${w}`);
    console.log(`PDF：${result.pdf}；每頁 PNG${result.sheet ? ' 與 sheet.png' : ''} 在 ${resolve(outDir)}`);
    console.log(`印出 ${result.fills.length} 頁（${result.size}）；填滿率 ${result.fills.join('／')}%。`);
  } catch (error) {
    console.error(`錯誤：${error.message}`);
    process.exit(1);
  }
}

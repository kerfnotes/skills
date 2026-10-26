// Render a deck page by page: PowerPoint for Mac or LibreOffice saves a PDF, then pdftoppm rasterizes it.
// node scripts/preview.js deck.pptx out/preview
// PowerPoint is sandboxed, so the deck is copied into its container first; "save as PNG" writes nothing, PDF works.
import { accessSync, constants, copyFileSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import { basename, delimiter, join, resolve } from 'node:path';
import { isMain } from './main.js';

// Find a program on PATH. Windows programs carry an extension from PATHEXT (soffice.exe, tool.cmd).
export function executable(name, { platform = process.platform, env = process.env } = {}) {
  const exts = platform === 'win32' ? ['', ...(env.PATHEXT ?? '.COM;.EXE;.BAT;.CMD').split(';').filter(Boolean)] : [''];
  for (const dir of (env.PATH ?? env.Path ?? '').split(platform === 'win32' ? ';' : delimiter)) {
    for (const ext of exts) {
      const path = join(dir || '.', name + ext);
      try { accessSync(path, platform === 'win32' ? constants.F_OK : constants.X_OK); return path; } catch { /* keep looking */ }
    }
  }
  return null;
}

// The first of names on PATH, else the first install location that exists.
export function findProgram(names, installed, { platform, env, exists = existsSync } = {}) {
  return names.map((name) => executable(name, { platform, env })).find(Boolean) ?? installed.find((path) => exists(path)) ?? null;
}

// Windows install locations: each path under Program Files and Program Files (x86).
export const programFiles = (env, ...paths) => [env.ProgramFiles, env['ProgramFiles(x86)']].filter(Boolean)
  .flatMap((dir) => paths.map((parts) => join(dir, ...parts)));

// Files pdftoppm wrote for prefix, in page order. It pads numbers to the page count (page-1 or page-01).
export const numbered = (dir, prefix, ext) => readdirSync(dir).filter((f) => new RegExp(`^${prefix}-\\d+\\.${ext}$`).test(f))
  .sort((a, b) => parseInt(a.slice(prefix.length + 1)) - parseInt(b.slice(prefix.length + 1)));

// Pages perRow to a row, each fitted into a width × height cell with a 10 px white margin. ffmpeg's xstack needs at
// least two inputs, so a one-page document has no sheet: returns null.
export function contactSheet(pngs, sheet, { perRow, width, height }) {
  rmSync(sheet, { force: true });
  if (pngs.length < 2) return null;
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', ...pngs.flatMap((p) => ['-i', p]),
    '-filter_complex', `${pngs.map((_, i) => `[${i}]scale=${width - 20}:${height - 20}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:10:white[p${i}]`).join(';')};${pngs.map((_, i) => `[p${i}]`).join('')}xstack=inputs=${pngs.length}:layout=${pngs.map((_, i) => `${(i % perRow) * width}_${Math.floor(i / perRow) * height}`).join('|')}:fill=white`,
    sheet]);
  return sheet;
}

// PowerPoint for Mac saves the PDF. The copy gets a unique name and is addressed by it: "active presentation" can be
// another deck the user has open, which fails with error -9074 or saves the wrong file.
function powerPointPdf(deck, outPdf) {
  const box = join(homedir(), 'Library/Containers/com.microsoft.Powerpoint/Data/Documents/clayprint-preview');
  mkdirSync(box, { recursive: true });
  // Only safe characters reach the AppleScript string literals.
  const stem = `${basename(deck, '.pptx').replace(/[^\p{L}\p{N}._-]/gu, '_')}-${process.pid}-${Date.now()}`;
  const inBox = join(box, `${stem}.pptx`), pdf = join(box, `${stem}.pdf`);
  copyFileSync(deck, inBox);
  try {
    execFileSync('osascript', ['-e', `
      tell application "Microsoft PowerPoint"
        open POSIX file "${inBox}"
        delay 2
        set p to presentation "${stem}.pptx"
        save p in POSIX file "${pdf}" as save as PDF
        close p saving no
      end tell`], { timeout: 180000, stdio: ['ignore', 'ignore', 'pipe'] });
    if (!existsSync(pdf)) throw new Error('PowerPoint 未產生 PDF');
    copyFileSync(pdf, outPdf);
  } catch (err) {
    // A failure after open leaves the copy open in PowerPoint; close it before its file goes away.
    try {
      execFileSync('osascript', ['-e', `tell application "Microsoft PowerPoint" to close (presentations whose name is "${stem}.pptx") saving no`],
        { timeout: 30000, stdio: 'ignore' });
    } catch { /* PowerPoint may already be gone */ }
    throw err;
  } finally {
    rmSync(inBox, { force: true });
    rmSync(pdf, { force: true });
  }
}

// One line from a failed command: its stderr, else its message.
const reason = (err) => (err.stderr?.toString().trim() || err.message).split('\n').filter(Boolean).pop();

export function preview(deck, outDir) {
  mkdirSync(outDir, { recursive: true });
  const name = basename(deck, '.pptx');
  const outPdf = join(outDir, `${name}.pdf`);
  rmSync(outPdf, { force: true });
  let failed = null;
  if (process.platform === 'darwin' && existsSync('/Applications/Microsoft PowerPoint.app') && executable('osascript')) {
    try { powerPointPdf(deck, outPdf); } catch (err) { failed = `PowerPoint 轉檔失敗（${reason(err)}）`; }
  }
  if (!existsSync(outPdf)) {
    const installed = [
      ...(process.platform === 'darwin' ? ['/Applications/LibreOffice.app/Contents/MacOS/soffice'] : []),
      ...(process.platform === 'win32' ? programFiles(process.env, ['LibreOffice', 'program', 'soffice.exe']) : []),
    ];
    const soffice = findProgram(['soffice'], installed);
    if (!soffice) {
      throw new Error(failed
        ? `${failed}，也找不到 LibreOffice。簡報檔已保留；預覽標「受阻」。關閉 PowerPoint 的對話框後重跑，或安裝 LibreOffice（soffice）。`
        : '找不到 PowerPoint 或 LibreOffice。請安裝 LibreOffice（soffice），或改看 SVG／PNG 圖表。');
    }
    if (failed) console.warn(`${failed}，改用 LibreOffice。`);
    try {
      execFileSync(soffice, ['--headless', '--convert-to', 'pdf', '--outdir', resolve(outDir), resolve(deck)], { timeout: 180000, stdio: ['ignore', 'ignore', 'pipe'] });
    } catch (err) {
      throw new Error(`LibreOffice 轉檔失敗（${reason(err)}）。簡報檔已保留；預覽標「受阻」。`);
    }
    if (!existsSync(outPdf)) throw new Error('LibreOffice 未產生 PDF，請檢查簡報檔與轉檔訊息。');
    console.warn('LibreOffice 會使用替代字型；此預覽只能檢查版面，請用 PowerPoint 確認正式外觀。');
  }
  // 144 dpi gives 1920×1080 per page, the design size.
  try {
    execFileSync('pdftoppm', ['-r', '144', '-png', outPdf, join(outDir, 'page')], { stdio: ['ignore', 'ignore', 'pipe'] });
  } catch (err) {
    throw new Error(`pdftoppm 轉圖失敗（${reason(err)}）；PDF 已存在 ${outPdf}，逐頁圖片標「受阻」。安裝 Poppler 後重跑。`);
  }
  const pages = numbered(outDir, 'page', 'png').map((p) => resolve(outDir, p));
  contactSheet(pages, join(outDir, 'sheet.png'), { perRow: 2, width: 980, height: 560 });
  return pages;
}

if (isMain(import.meta.url)) {
  const [deck, outDir] = process.argv.slice(2);
  if (!deck || !outDir) {
    console.error('用法：node scripts/preview.js deck.pptx out/preview');
    process.exit(2);
  }
  try {
    for (const p of preview(resolve(deck), outDir)) console.log(p);
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }
}

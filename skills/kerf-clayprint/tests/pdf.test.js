import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../scripts/pdf.js', import.meta.url));
const example = fileURLToPath(new URL('../examples/report.html', import.meta.url));
const { findBrowser } = await import('../scripts/pdf.js');

// A4 at 50 dpi, the size pdftoppm -gray -r 50 writes. Ink is 0 on white 255.
const W = 414, H = 585, k = 50 / 25.4;
function pgm(inkRows, inkPixels = [], from = 100) {
  const data = Buffer.alloc(W * H, 255);
  for (const y of inkRows) data.fill(0, y * W + from, y * W + from + 200);
  for (const [x, y] of inkPixels) data[y * W + x] = 0;
  return Buffer.concat([Buffer.from(`P5\n${W} ${H}\n255\n`), data]);
}
const top = Math.round(12 * k), bottom = H - Math.round(15 * k);

// POSIX shell shims stand in for the browser and Poppler; Windows cannot run them.
function shims(dir) {
  const bin = join(dir, 'bin'), fixtures = join(dir, 'fixtures');
  mkdirSync(bin);
  mkdirSync(fixtures);
  const log = `printf '%s\\n' "$(basename "$0")" "$@" >> "$FAKE_LOG"`;
  writeFileSync(join(bin, 'google-chrome'), `#!/bin/sh
${log}
for arg do
  case "$arg" in
    --print-to-pdf=*) pdf="\${arg#--print-to-pdf=}" ;;
    file://*) cp "\${arg#file://}" "$FAKE_LOG.html" ;;
  esac
done
printf '%%PDF fake' > "$pdf"
`, { mode: 0o755 });
  writeFileSync(join(bin, 'pdftoppm'), `#!/bin/sh
${log}
for arg do prefix="$arg"; done
case " $* " in
  *" -gray "*) for f in "$FAKE_FIXTURES"/*.pgm; do cp "$f" "$prefix-$(basename "$f")"; done ;;
  *) for n in $(seq "\${FAKE_PAGES:-3}"); do printf 'fake PNG' > "$prefix-$n.png"; done ;;
esac
`, { mode: 0o755 });
  writeFileSync(join(bin, 'pdftotext'), `#!/bin/sh
${log}
cat "$FAKE_FIXTURES/text"
`, { mode: 0o755 });
  writeFileSync(join(bin, 'ffmpeg'), `#!/bin/sh
${log}
for arg do sheet="$arg"; done
printf 'fake sheet' > "$sheet"
`, { mode: 0o755 });
  // Page 1 fills to the bottom; page 2 stops halfway and has ink past the right margin plus a footer that must not count;
  // page 3 is the last page, so its low fill is fine.
  // Page 1's rule under the cover band bleeds from edge to edge; a bleed is not an overflow.
  writeFileSync(join(fixtures, '1.pgm'), pgm([5, bottom - 10], [[0, 100], [W - 1, 100]]));
  writeFileSync(join(fixtures, '2.pgm'), pgm([top + 10, 300, bottom + 15], [[W - 4, 200], [W - 20, bottom + 15]]));
  writeFileSync(join(fixtures, '3.pgm'), pgm([top + 10, 150]));
  // 圖 1 starts on page 1 and its source sits on page 2; 表 1 runs from page 2 to 3; 圖 2 stays on page 3.
  writeFileSync(join(fixtures, 'text'), '時間結果\n圖1\n登錄時間比較\f單位：小時｜來源：試行稿\n表1\n同一流程的時間對照\f來源：試行稿\n圖2\n單位：件｜來源：試行稿\f');
  return { bin, fixtures };
}

function run(dir, args, env = {}, pages, text) {
  const { bin, fixtures } = shims(dir);
  if (pages) pages.forEach((page, i) => writeFileSync(join(fixtures, `${i + 1}.pgm`), page));
  if (text) writeFileSync(join(fixtures, 'text'), text);
  const { CLAYPRINT_CHROME, ...rest } = process.env;
  return spawnSync(process.execPath, [script, ...args], {
    encoding: 'utf8', env: { ...rest, PATH: `${bin}:/usr/bin:/bin`, FAKE_LOG: join(dir, 'calls'), FAKE_FIXTURES: fixtures, ...env },
  });
}

test('pdf.js prints with the browser, rasterizes pages, and warns about fill, overflow and split exhibits', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'report.html'), out = join(dir, 'print');
    writeFileSync(html, readFileSync(example));
    const result = run(dir, [html, out]);
    assert.equal(result.status, 0, result.stderr);

    const calls = readFileSync(join(dir, 'calls'), 'utf8').trim().split('\n');
    assert.deepEqual(calls.slice(0, 6), ['google-chrome', '--headless', '--disable-gpu', '--no-pdf-header-footer',
      `--print-to-pdf=${join(out, 'report.pdf')}`, `file://${html}`]);
    const at = (name) => calls.indexOf(name);
    assert.deepEqual(calls.slice(at('pdftoppm'), at('pdftoppm') + 6), ['pdftoppm', '-r', '100', '-png', join(out, 'report.pdf'), join(out, 'page')]);
    assert.ok(calls.includes('-gray'));
    assert.ok(calls.includes('pdftotext') && calls.includes('ffmpeg'));

    assert.deepEqual(readdirSync(out).sort(), ['page-01.png', 'page-02.png', 'page-03.png', 'report.pdf', 'sheet.png']);
    assert.equal(readFileSync(html, 'utf8'), readFileSync(example, 'utf8'));

    const fill = (last, from) => Math.round((last - from) / (bottom - from) * 100);
    assert.match(result.stdout, new RegExp(`印出 3 頁（A4）；填滿率 ${fill(bottom - 10, 0)}／${fill(300, top)}／${fill(150, top)}%。`));
    assert.match(result.stderr, new RegExp(`第 2 頁只填 ${fill(300, top)}%：先查原稿是否漏了理由、定義或限制，再評估元件前移、拆分或重排；內容完整時可記錄留白理由，勿為填滿補字。`));
    assert.doesNotMatch(result.stderr, /第 [13] 頁只填/);
    assert.match(result.stderr, /第 2 頁內容超出右邊界約 \d+ mm：減少表格欄數或設 wide: true。/);
    assert.doesNotMatch(result.stderr, /第 [13] 頁內容超出右邊界/);
    assert.match(result.stderr, /圖 1 的標題在第 1 頁、來源在第 2 頁：縮短圖上方的段落，或改小圖。/);
    assert.doesNotMatch(result.stderr, /圖 2 的標題/);
    assert.match(result.stderr, /表 1 跨第 2–3 頁：8 列以內不該分頁，縮短表上方的段落。/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('Chrome shrinks a page whose content runs past the right edge: the body column moves left of 50 mm', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'report.html'), out = join(dir, 'print');
    writeFileSync(html, readFileSync(example));
    const rows = (from, n) => Array.from({ length: n }, (_, i) => from + i * 20);
    // Page 2: body lines start at x 85 (43.2 mm, so 28 mm became 21.2 mm: 76%); section headings on the 22 mm line (x 43)
    // and a lone block at x 70 do not move the estimate. Page 3: body at 50.8 mm and a wide table whose cells start
    // at 25.7 mm (x 51): not shrunk.
    const shrunk = pgm(rows(top + 10, 12), [[43, top + 2], [43, top + 3], [70, top + 300], [90, top + 300]], 85);
    const wide = pgm(rows(top + 10, 6), rows(top + 200, 8).map((y) => [51, y]));
    const result = run(dir, [html, out], {}, [pgm([5, bottom - 10]), shrunk, wide]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stderr, /內容超出右邊界，整份被縮成 76%（第 2 頁起）：減少表格欄數或設 wide: true。/);
    assert.doesNotMatch(result.stderr, /第 [13] 頁內容超出右邊界/);
    // Chrome shrinks the whole document, so later shrunk pages do not repeat the warning.
    const second = join(dir, 'again');
    mkdirSync(second);
    const again = run(second, [html, join(second, 'print')], {}, [pgm([5, bottom - 10]), shrunk, shrunk, wide]);
    assert.equal(again.stderr.match(/整份被縮成/g)?.length, 1, again.stderr);
    assert.match(again.stderr, /整份被縮成 76%（第 2 頁起）/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('page 1 ends at a fixed page break, so its low fill asks to shorten the summary or contents', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'report.html'), out = join(dir, 'print');
    writeFileSync(html, readFileSync(example));
    const result = run(dir, [html, out], {}, [pgm([5, 200]), pgm([top + 10, bottom - 10]), pgm([top + 10])]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stderr, new RegExp(`第 1 頁只填 ${Math.round(200 / bottom * 100)}%：縮短摘要或目錄，或把下一節的開頭段落放進第 1 頁前的摘要。`));
    assert.doesNotMatch(result.stderr, /第 1 頁只填[^\n]*整塊元件/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('unknown flags and a --paper other than clay print the usage and exit 2', () => {
  for (const args of [['--leter'], ['--paper clay'], ['--paper', 'white'], ['--paper']]) {
    const result = spawnSync(process.execPath, [script, example, join(tmpdir(), 'clayprint-unused'), ...args], { encoding: 'utf8' });
    assert.equal(result.status, 2, `${args.join(' ')}\n${result.stderr}`);
    assert.match(result.stderr, /用法：node scripts\/pdf\.js out\/report\.html out\/print \[--letter\] \[--paper clay\]/);
  }
  const extra = spawnSync(process.execPath, [script, example, join(tmpdir(), 'clayprint-unused'), 'third'], { encoding: 'utf8' });
  assert.equal(extra.status, 2, extra.stderr);
});

test('--letter --paper clay prints a marked temporary copy, deletes it, and skips long tables', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'brief.html'), out = join(dir, 'print');
    // Nine body rows: a table that long may break across pages.
    const source = readFileSync(example, 'utf8').replace(/(<tbody>\n)(<tr>[^\n]*\n)/, (_, open, row) => open + row.repeat(8));
    writeFileSync(html, source);
    const result = run(dir, [html, out, '--letter', '--paper', 'clay']);
    assert.equal(result.status, 0, result.stderr);

    const printed = readFileSync(join(dir, 'calls.html'), 'utf8');
    assert.match(printed, /<html data-paper="clay" data-size="letter" lang="zh-Hant" style="--report-title: '讓標本登錄從交接開始變快 \| '">/);
    const target = readFileSync(join(dir, 'calls'), 'utf8').split('\n').find((l) => l.startsWith('file://'));
    assert.notEqual(target, `file://${html}`);
    assert.ok(target.startsWith(`file://${dir}/`));
    assert.equal(readFileSync(html, 'utf8'), source);
    assert.deepEqual(readdirSync(dir).filter((f) => f.endsWith('.html')).sort(), ['brief.html', 'calls.html']);
    assert.ok(existsSync(join(out, 'brief.pdf')));
    assert.match(result.stdout, /印出 3 頁（Letter）/);
    assert.doesNotMatch(result.stderr, /表 1 跨/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a one-page print skips sheet.png instead of failing', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'one.html'), out = join(dir, 'print');
    writeFileSync(html, '<html><body><p>一頁</p></body></html>');
    const result = run(dir, [html, out], { FAKE_PAGES: '1' });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(readdirSync(out).sort(), ['one.pdf', 'page-01.png']);
    assert.ok(!readFileSync(join(dir, 'calls'), 'utf8').includes('ffmpeg'));
    assert.match(result.stdout, /每頁 PNG 在 /);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a missing browser ends with the CLAYPRINT_CHROME hint', () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'report.html');
    writeFileSync(html, '<html></html>');
    const result = spawnSync(process.execPath, [script, html, join(dir, 'print')], {
      encoding: 'utf8', env: { ...process.env, PATH: dir, CLAYPRINT_CHROME: join(dir, 'no-such-browser') },
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /找不到 Chrome、Edge、Chromium 或 Brave；設 CLAYPRINT_CHROME 指向瀏覽器執行檔後重跑。/);
    assert.equal(existsSync(join(dir, 'print', 'report.pdf')), false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('findBrowser() tries CLAYPRINT_CHROME, then PATH, then install locations', { skip: process.platform === 'win32' && 'POSIX modes' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-browser-'));
  try {
    for (const name of ['msedge', 'chromium', 'custom']) writeFileSync(join(dir, name), '', { mode: 0o755 });
    assert.equal(findBrowser({ platform: 'linux', env: { PATH: dir }}), join(dir, 'chromium'));
    assert.equal(findBrowser({ platform: 'linux', env: { PATH: dir, CLAYPRINT_CHROME: join(dir, 'custom') }}), join(dir, 'custom'));
    assert.equal(findBrowser({ platform: 'linux', env: { PATH: dir, CLAYPRINT_CHROME: join(dir, 'missing') }}), null);
    const edge = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge';
    assert.equal(findBrowser({ platform: 'darwin', env: { PATH: '' }, exists: (p) => p === edge }), edge);
    const win = join('C:\\Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe');
    assert.equal(findBrowser({ platform: 'win32', env: { PATH: '', 'ProgramFiles(x86)': 'C:\\Program Files (x86)' }, exists: (p) => p === win }), win);
    for (const exe of [join('C:\\Program Files', 'Chromium', 'Application', 'chrome.exe'), join('C:\\Program Files', 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe')]) {
      assert.equal(findBrowser({ platform: 'win32', env: { PATH: '', ProgramFiles: 'C:\\Program Files' }, exists: (p) => p === exe }), exe);
    }
    assert.equal(findBrowser({ platform: 'linux', env: { PATH: '' }}), null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a section whose closing callout or paragraph opens a page is flagged, inline markup included; one that stays with its section is not', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pdf-'));
  try {
    const html = join(dir, 'report.html');
    writeFileSync(html, `<main>
<section aria-labelledby="a">
<header class="section-heading"><h2 id="a">甲節</h2></header>
<p>甲節正文。</p>
<aside class="callout">
  <p>先統一<strong>收件欄位</strong>，再固定交接順序。</p>
</aside>
</section>
<section aria-labelledby="b">
<header class="section-heading"><h2 id="b">乙節</h2></header>
<p>乙節最後一段 &amp; 收尾。</p>
<footer class="sources">
<h3>來源與附註</h3>
<p>來源：試行稿</p>
</footer>
</section>
<section aria-labelledby="c">
<header class="section-heading"><h2 id="c">丙節</h2></header>
<p>丙節只有一段。</p>
</section>
</main>`);
    const page = pgm([top + 10, bottom - 10]);
    const flagged = run(dir, [html, join(dir, 'print')], {}, [page, page, page],
      '封面\f甲節\n甲節正文。\f先統一收件欄位，再固定\n交接順序。\n乙節\n乙節最後一段 & 收尾。\n丙節\n丙節只有一段。\f');
    assert.equal(flagged.status, 0, flagged.stderr);
    assert.match(flagged.stderr, /第 1 節最後一段落在第 3 頁開頭，和本節其他內容分開/);
    assert.doesNotMatch(flagged.stderr, /第 [23] 節最後一段/);

    const together = run(mkdtempSync(join(dir, 'b-')), [html, join(dir, 'print2')], {}, [page, page, page],
      '封面\f甲節\n甲節正文。\n先統一收件欄位，再固定交接順序。\f乙節\n乙節最後一段 & 收尾。\f丙節最後\f');
    assert.doesNotMatch(together.stderr, /最後一段落在/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

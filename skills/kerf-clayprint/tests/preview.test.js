import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../scripts/preview.js', import.meta.url));
const { executable } = await import('../scripts/preview.js');

// The fake programs below are POSIX shell scripts; Windows cannot run them, so this flow test runs on macOS and Linux.
test('LibreOffice fallback converts PDF and continues through PNG and contact sheet', { skip: process.platform === 'win32' && 'POSIX shell shims' }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-preview-'));
  try {
    const bin = join(dir, 'bin'), out = join(dir, 'out'), deck = join(dir, 'deck.pptx'), log = join(dir, 'calls');
    mkdirSync(bin);
    writeFileSync(deck, 'fake deck');
    writeFileSync(join(bin, 'soffice'), `#!/bin/sh
printf 'soffice\\n' >> "$FAKE_LOG"
printf '%s\\n' "$@" >> "$FAKE_LOG"
while [ "$#" -gt 0 ]; do
  if [ "$1" = '--outdir' ]; then outdir="$2"; fi
  shift
done
printf 'fake PDF' > "$outdir/deck.pdf"
`, { mode: 0o755 });
    writeFileSync(join(bin, 'pdftoppm'), `#!/bin/sh
printf 'pdftoppm\\n' >> "$FAKE_LOG"
printf '%s\\n' "$@" >> "$FAKE_LOG"
for arg do prefix="$arg"; done
n=1
while [ "$n" -le "\${FAKE_PAGES:-2}" ]; do printf 'fake PNG' > "\${prefix}-$n.png"; n=$((n + 1)); done
`, { mode: 0o755 });
    writeFileSync(join(bin, 'ffmpeg'), `#!/bin/sh
printf 'ffmpeg\\n' >> "$FAKE_LOG"
printf '%s\\n' "$@" >> "$FAKE_LOG"
for arg do sheet="$arg"; done
printf 'fake sheet' > "$sheet"
`, { mode: 0o755 });

    const result = spawnSync(process.execPath, [script, deck, out], {
      encoding: 'utf8', env: { ...process.env, PATH: bin, FAKE_LOG: log },
    });
    assert.equal(result.status, 0, result.stderr);
    const calls = readFileSync(log, 'utf8').trim().split('\n');
    assert.deepEqual(calls.slice(0, 7), ['soffice', '--headless', '--convert-to', 'pdf', '--outdir', out, deck]);
    assert.deepEqual(calls.slice(7, 13), ['pdftoppm', '-r', '144', '-png', join(out, 'deck.pdf'), join(out, 'page')]);
    assert.equal(calls[13], 'ffmpeg');
    assert.ok(existsSync(join(out, 'deck.pdf')));
    assert.ok(existsSync(join(out, 'page-1.png')));
    assert.ok(existsSync(join(out, 'sheet.png')));
    assert.match(result.stderr, /替代字型.*只能檢查版面/);
    assert.match(result.stdout, /page-1\.png/);

    // One page: ffmpeg's xstack needs two inputs, so the preview skips the sheet instead of failing.
    rmSync(log);
    const single = join(dir, 'single');
    const one = spawnSync(process.execPath, [script, deck, single], {
      encoding: 'utf8', env: { ...process.env, PATH: bin, FAKE_LOG: log, FAKE_PAGES: '1' },
    });
    assert.equal(one.status, 0, one.stderr);
    assert.ok(!readFileSync(log, 'utf8').includes('ffmpeg'));
    assert.ok(existsSync(join(single, 'page-1.png')) && !existsSync(join(single, 'sheet.png')));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('missing presentation renderer explains the fallback options', { skip: existsSync('/Applications/LibreOffice.app/Contents/MacOS/soffice') }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-preview-'));
  try {
    const deck = join(dir, 'deck.pptx');
    writeFileSync(deck, 'fake deck');
    const result = spawnSync(process.execPath, [script, deck, join(dir, 'out')], {
      encoding: 'utf8', env: { ...process.env, PATH: dir },
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /請安裝 LibreOffice.*SVG／PNG/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('executable() finds Windows programs through PATHEXT', () => {
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-pathext-'));
  try {
    writeFileSync(join(dir, 'soffice.EXE'), '');
    const env = { PATH: dir, PATHEXT: '.COM;.EXE;.CMD' };
    assert.equal(executable('soffice', { platform: 'win32', env }), join(dir, 'soffice.EXE'));
    assert.equal(executable('missing', { platform: 'win32', env }), null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

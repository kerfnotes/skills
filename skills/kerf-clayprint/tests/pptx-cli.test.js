import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';

test('pptx CLI reports the saved path and page count after successful output', async () => {
  mkdirSync('out', { recursive: true });
  const dir = mkdtempSync(join('out', 'cli-test-'));
  try {
    const input = join(dir, 'story.json'), output = join(dir, 'deck with spaces.pptx');
    writeFileSync(input, JSON.stringify({ pages: [{ type: 'cover', claim: '封面' }, { type: 'statement', claim: '判斷' }] }));
    const run = spawnSync(process.execPath, ['scripts/pptx.js', input, output], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    assert.ok(run.stdout.includes(output), run.stdout);
    assert.match(run.stdout, /2 頁/);
    const zip = await JSZip.loadAsync(readFileSync(output));
    assert.equal(Object.keys(zip.files).filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name)).length, 2);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('pptx CLI creates a missing output folder', () => {
  mkdirSync('out', { recursive: true });
  const dir = mkdtempSync(join('out', 'cli-test-'));
  try {
    const input = join(dir, 'story.json'), output = join(dir, 'new', 'deeper', 'deck.pptx');
    writeFileSync(input, JSON.stringify({ pages: [{ type: 'cover', claim: '封面' }] }));
    const run = spawnSync(process.execPath, ['scripts/pptx.js', input, output], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    assert.ok(readFileSync(output).length > 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

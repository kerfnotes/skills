import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { differingFiles, engineFiles } from '../scripts/sync-engine.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));

test('引擎檔案不寫死品牌或套件名稱，換品牌只改 package.json 與設計層', () => {
  const names = [pkg.brand, pkg.name].map((s) => s.toLowerCase());
  for (const file of engineFiles(root)) {
    const text = readFileSync(path.join(root, file), 'utf8').toLowerCase();
    for (const name of names) assert.ok(!text.includes(name), `${file} 含有「${name}」`);
  }
});

test('引擎比對列出內容不同與只有一邊有的檔案', (t) => {
  const other = mkdtempSync(path.join(tmpdir(), 'engine-sync-'));
  t.after(() => rmSync(other, { recursive: true, force: true }));
  for (const part of ['scripts', 'evals', 'package.json']) cpSync(path.join(root, part), path.join(other, part), { recursive: true });
  assert.deepEqual(differingFiles(other, root), []);
  writeFileSync(path.join(other, 'scripts', 'core.js'), '// changed\n', { flag: 'a' });
  writeFileSync(path.join(other, 'scripts', 'extra.js'), '');
  assert.deepEqual(differingFiles(other, root), ['scripts/core.js', 'scripts/extra.js']);
});

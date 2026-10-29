// Keep the engine identical across brand skills. Brand differences live in package.json "brand" and design/*.json, never here.
// node scripts/sync-engine.js check <other-skill-dir>   list engine files that differ; exit 1 when any do
// node scripts/sync-engine.js copy <other-skill-dir>    copy this skill's engine files over the other skill's
import { copyFileSync, existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isMain } from './main.js';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const EVALS = ['evals/check.mjs', 'evals/check-report.mjs', 'evals/numbers.mjs'];

export function engineFiles(root = ROOT) {
  const scripts = existsSync(join(root, 'scripts')) ? readdirSync(join(root, 'scripts')).filter((f) => f.endsWith('.js')) : [];
  return [...scripts.map((f) => `scripts/${f}`), ...EVALS].sort();
}

export function differingFiles(other, root = ROOT) {
  const names = [...new Set([...engineFiles(root), ...engineFiles(other)])].sort();
  const same = (f) => existsSync(join(root, f)) && existsSync(join(other, f)) && readFileSync(join(root, f)).equals(readFileSync(join(other, f)));
  return names.filter((f) => !same(f));
}

if (isMain(import.meta.url)) {
  const [command, dir] = process.argv.slice(2);
  if (!['check', 'copy'].includes(command) || !dir || !existsSync(join(dir, 'package.json'))) {
    console.error('用法：node scripts/sync-engine.js check|copy <另一個 skill 資料夾>');
    process.exit(2);
  }
  const other = resolve(dir);
  if (command === 'copy') for (const f of engineFiles()) copyFileSync(join(ROOT, f), join(other, f));
  const diff = differingFiles(other);
  if (!diff.length) console.log(`引擎相同：${engineFiles().length} 個檔案`);
  // After a copy only files this skill lacks can remain; removing them is left to the person syncing.
  for (const f of diff) console.log(`${command === 'copy' ? '對方多出、未刪除' : '不同'}：${f}`);
  process.exitCode = diff.length ? 1 : 0;
}

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const docs = ['README.md', 'SKILL.md', 'references/report.md', 'docs/install.md', 'docs/make-it-yours.md', 'design/brief.md'];
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));

test('起點文件中的 node／npm 指令指向現有檔案與 npm 任務', () => {
  let commands = 0;
  // Derived copies may omit README.md; every document that exists must hold true.
  for (const doc of docs.filter((d) => existsSync(join(root, d)))) {
    for (const line of readFileSync(join(root, doc), 'utf8').split('\n')) {
      if (!/\b(?:node|npm)\s+/.test(line)) continue;
      for (const [, script] of line.matchAll(/\bnode\s+([\w./-]+\.(?:mjs|js))\b/g)) {
        commands++;
        assert.ok(existsSync(join(root, script)), `${doc}: ${script}`);
      }
      for (const [, target] of line.matchAll(/\b((?:scripts|evals|examples|design|tests)\/[\w./-]+\.(?:json|mjs|js|md|html))\b/g)) {
        assert.ok(existsSync(join(root, target)), `${doc}: ${target}`);
      }
      for (const [, command] of line.matchAll(/\bnpm\s+([\w-]+(?:\s+[\w:-]+)?)/g)) {
        commands++;
        if (command.split(/\s+/)[0] === 'ci') assert.ok(existsSync(join(root, 'package-lock.json')), `${doc}: npm ci`);
        else assert.ok(pkg.scripts?.[command === 'test' ? 'test' : command.replace(/^run /, '')], `${doc}: npm ${command}`);
      }
    }
  }
  assert.ok(commands > 0, '文件沒有可檢查的指令');
});

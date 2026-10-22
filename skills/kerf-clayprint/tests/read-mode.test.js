import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { build, validateStory } from '../scripts/pptx.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const moduleUrl = (name) => new URL(`../scripts/${name}.js`, import.meta.url).href;

function run(args, { mode, tokens, code } = {}) {
  const env = { ...process.env };
  delete env.CLAYPRINT_MODE;
  delete env.CLAYPRINT_TOKENS;
  if (mode !== undefined) env.CLAYPRINT_MODE = mode;
  if (tokens !== undefined) env.CLAYPRINT_TOKENS = tokens;
  return spawnSync(process.execPath, code ? ['--input-type=module', '-e', code] : args, { cwd: root, env, encoding: 'utf8' });
}

const list = (n) => ({ type: 'list', claim: '清單', sources: { source: '原稿' }, visual: { items: Array.from({ length: n }, (_, i) => ({ heading: `第${i + 1}項` })) } });

test('閱讀模式只改字級、證據圖寬與容量，保留各設計層的字重與顏色；未知模式報錯', () => {
  const code = `import { loadTokens } from ${JSON.stringify(moduleUrl('tokens'))}; const t = loadTokens(); console.log(JSON.stringify({ title: t.type.title, label: t.type.label.px, minimum: t.type.minimum, list: t.capacity?.list, evidence: t.chartArea.evidence.width, focus: t.color.focus }));`;
  const base = JSON.parse(readFileSync(path.join(root, 'design/tokens.blue.json'), 'utf8'));
  const child = run([], { code, mode: 'read', tokens: 'design/tokens.blue.json' });
  assert.equal(child.status, 0, child.stderr);
  assert.deepEqual(JSON.parse(child.stdout), { title: { ...base.type.title, px: 44 }, label: 20, minimum: 16, list: [3, 8], evidence: 1000, focus: base.color.focus });
  const present = JSON.parse(run([], { code }).stdout);
  assert.equal(present.title.px, JSON.parse(readFileSync(path.join(root, 'design/tokens.json'), 'utf8')).type.title.px);
  assert.equal(present.list, undefined);
  assert.match(run([], { code, mode: 'dense' }).stderr, /CLAYPRINT_MODE/);
});

test('mode: read 的 story 由 CLI 自動改用閱讀字級，最小 8 pt，驗收無警告', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-read-'));
  try {
    const out = path.join(dir, 'read.pptx');
    const made = run(['scripts/pptx.js', 'examples/story-read.json', out]);
    assert.equal(made.status, 0, made.stderr);
    const zip = await JSZip.loadAsync(readFileSync(out));
    const sizes = [];
    for (const name of Object.keys(zip.files).filter((n) => /^ppt\/(?:slides\/slide|charts\/chart)\d+\.xml$/.test(n))) {
      sizes.push(...[...(await zip.file(name).async('string')).matchAll(/\ssz="(\d+)"/g)].map((m) => Number(m[1])));
    }
    assert.ok(sizes.includes(2200), '頁標題 22 pt');
    assert.ok(Math.min(...sizes) >= 800, `最小字級 ${Math.min(...sizes) / 100} pt`);
    const checked = run(['evals/check.mjs', 'examples/story-read.json', 'evals/fixtures/example-script.md']);
    assert.equal(checked.status, 0, checked.stderr);
    assert.match(checked.stdout, /0 項警告/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('程式內呼叫時，story 模式與載入字級不符就停下；mode 只接受 present 或 read', async () => {
  await assert.rejects(build({ mode: 'read', pages: [list(3)] }), /CLAYPRINT_MODE=read/);
  assert.throws(() => validateStory({ mode: 'dense', pages: [list(3)] }), /mode/);
});

test('清單容量：現場簡報 6 項警告，閱讀型簡報 6 項可放', async () => {
  const { warnings } = await build({ pages: [list(6)] });
  assert.ok(warnings.some((w) => /3～5 項/.test(w)), warnings.join('\n'));
  const code = `import { build } from ${JSON.stringify(moduleUrl('pptx'))}; const r = await build(${JSON.stringify({ mode: 'read', pages: [list(6)] })}); console.log(JSON.stringify(r.warnings));`;
  const child = run([], { code, mode: 'read' });
  assert.equal(child.status, 0, child.stderr);
  assert.deepEqual(JSON.parse(child.stdout).filter((w) => /診斷清單/.test(w)), []);
});

test('數字格 note：閱讀型 4 格排兩列、可寫 2 行；現場版同一句超出 1 行會警告', async () => {
  const note = '這一格的說明寫成兩行左右，交代口徑、比較基準與資料限制，讓讀者不必問人。';
  const items = [{ label: '甲', value: 1, note }, { label: '乙', value: 2 }, { label: '丙', value: 3 }, { label: '丁', value: 4 }];
  const story = { pages: [{ type: 'numbers', claim: '四個指標', sources: { source: '原稿' }, visual: { items } }] };
  const { warnings } = await build(story);
  assert.ok(warnings.some((w) => /items\[0\]\.note：估算 \d+ 行，上限 1 行/.test(w)), warnings.join('\n'));
  const code = `import { build } from ${JSON.stringify(moduleUrl('pptx'))}; const r = await build(${JSON.stringify({ ...story, mode: 'read' })}); console.log(JSON.stringify(r.warnings));`;
  const child = run([], { code, mode: 'read' });
  assert.equal(child.status, 0, child.stderr);
  assert.deepEqual(JSON.parse(child.stdout), []);
});

test('閱讀型簡報的證據頁要有 note，不再要求講稿', () => {
  const story = { mode: 'read', pages: [{ type: 'evidence', claim: '甲 12 件', sources: { source: '原稿' }, visual: { kind: 'rank', rows: [{ label: '甲', value: 12 }, { label: '乙', value: 8 }] } }] };
  const code = `import { check } from ${JSON.stringify(new URL('../evals/check.mjs', import.meta.url).href)}; const r = await check(${JSON.stringify(story)}, '甲 12 件，乙 8 件。'); console.log(JSON.stringify(r.warnings));`;
  const warnings = JSON.parse(run([], { code, mode: 'read' }).stdout);
  assert.ok(warnings.some((w) => /note：閱讀型簡報沒有講者/.test(w)), warnings.join('\n'));
  assert.ok(!warnings.some((w) => /講稿/.test(w)), warnings.join('\n'));
});

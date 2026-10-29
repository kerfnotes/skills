import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import JSZip from 'jszip';
import { build, validateStory } from '../scripts/pptx.js';
import { check } from '../evals/check.mjs';

const source = { source: '虛構示意稿' };
const page = (type, visual, extra = {}) => ({ type, claim: '結論', visual, sources: source, ...extra });
const slide = async (buffer, n = 1) => (await JSZip.loadAsync(buffer)).file(`ppt/slides/slide${n}.xml`).async('string');
const cases = {
  list: { items: [{ tag: '先', heading: '欄位' }, { heading: '交接' }, { heading: '檢核' }], focus: 0 },
  process: { steps: [{ heading: '收件' }, { heading: '交接' }, { heading: '登錄' }], focus: 1 },
  kpi: { main: { label: '耗時', value: 1234.5, digits: 1, unit: '小時', benchmarks: [{ label: '前期', value: 36 }] }, secondary: [{ label: '件數', value: 0 }] },
  flow: { nodes: [{ heading: '欄位' }, { heading: '重工' }], connectors: ['→'] },
  columns: { items: [{ heading: '資料' }, { heading: '作業' }] },
};

test('五種新版型可建檔，標題下說明行與新欄位進入畫面', async () => {
  const pages = Object.entries(cases).map(([type, visual]) => page(type, visual, { lede: '指標：登錄時間・期間：試行週' }));
  const { buffer, warnings } = await build({ pages });
  assert.deepEqual(warnings, []);
  for (let i = 0; i < pages.length; i++) {
    const xml = await slide(buffer, i + 1);
    assert.ok(xml.includes('指標：登錄時間・期間：試行週'));
    assert.ok(xml.includes('資料來源：虛構示意稿'));
  }
  assert.ok((await slide(buffer, 2)).includes('步驟 1'));
  assert.ok((await slide(buffer, 3)).includes('1,234.5'));
  assert.ok((await slide(buffer, 3)).includes('>0<'));
  assert.ok((await slide(buffer, 4)).includes('→'));
});

test('lede 只在填入時增加內容起點高度', async () => {
  const visual = { items: [{ heading: '資料' }, { heading: '作業' }] };
  const render = async (lede) => slide((await build({ pages: [page('columns', visual, lede === undefined ? {} : { lede })] })).buffer);
  const plain = await render(), blank = await render(''), withLede = await render('範圍：試行週');
  assert.equal(plain, blank);
  const y = (xml) => {
    const shape = [...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)].map((m) => m[0]).find((part) => part.includes('<a:t>資料</a:t>'));
    return Number(shape.match(/<a:off x="[^"]+" y="(\d+)"/)[1]);
  };
  assert.ok(y(withLede) > y(plain));
});

test('清單沒有 tag 時不保留左欄，標題與頁標題左緣對齊', async () => {
  const left = async (items) => {
    const xml = await slide((await build({ pages: [page('list', { items })] })).buffer);
    const shapes = [...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)].map((m) => m[0]);
    return (text) => Number(shapes.find((part) => part.includes(`<a:t>${text}</a:t>`)).match(/<a:off x="(\d+)"/)[1]);
  };
  const plain = await left([{ heading: '欄位' }, { heading: '交接' }, { heading: '檢核' }]);
  const tagged = await left([{ tag: '先', heading: '欄位' }, { heading: '交接' }, { heading: '檢核' }]);
  assert.equal(plain('欄位'), plain('結論'));
  assert.ok(tagged('欄位') > tagged('結論'));
  assert.equal(tagged('先'), tagged('結論'));
});

test('新版型指出錯誤欄位，容量超出時警告；四方案可容納', async () => {
  for (const [type, visual, path] of [
    ['list', { items: [{ heading: 3 }] }, 'items[0].heading'],
    ['process', { steps: [{ heading: '收件' }], focus: 2 }, 'visual.focus'],
    ['kpi', { main: { label: '耗時', value: {}, benchmarks: [{ label: '前期', value: 3 }] } }, 'main.value'],
    ['flow', { nodes: [{ heading: '甲' }, { heading: '乙' }], connectors: ['×'] }, 'visual.connectors'],
    ['columns', { items: [{ heading: '甲', digits: -1 }] }, 'items[0].digits'],
  ]) assert.throws(() => validateStory({ pages: [page(type, visual)] }), (error) => error.message.includes(path));
  assert.throws(() => validateStory({ pages: [{ type: 'cover', claim: '封面', lede: '不適用' }] }), /lede/);
  const n = (count, make) => Array.from({ length: count }, (_, i) => make(i));
  const pages = [
    page('list', { items: n(2, (i) => ({ heading: `項目${i}` })) }),
    page('process', { steps: n(2, (i) => ({ heading: `步驟${i}` })) }),
    page('kpi', { main: { label: '核心', value: 1, benchmarks: n(4, (i) => ({ label: `對照${i}`, value: i })) }, secondary: n(5, (i) => ({ label: `次要${i}`, value: i })) }),
    page('flow', { nodes: n(6, (i) => ({ heading: `節點${i}` })) }),
    page('columns', { items: n(5, (i) => ({ heading: `欄位${i}` })) }),
    page('compare', { rows: ['條件'], options: n(4, (i) => ({ name: `方案${i}`, values: ['符合'] })) }),
  ];
  const { warnings } = await build({ pages });
  for (const type of ['診斷清單', '無日期流程', '核心數字', '因果圖', '並列重點']) assert.ok(warnings.some((w) => w.includes(type)), type);
  assert.ok(!warnings.some((w) => w.includes('比較方案')));
  pages[5].visual.options.push({ name: '方案五', values: ['符合'] });
  assert.ok((await build({ pages: [pages[5]] })).warnings.some((w) => /比較方案.*2～4/.test(w)));
});

test('明示的 null 在數字、比較與表格原位寫未提供，空物件略去', async () => {
  const pages = [
    page('numbers', { items: [{}, { label: '件數', value: null }, { label: '已知', value: 0 }] }),
    page('summary', { lead: '先核對資料', items: [{ label: '件數', value: null }, { label: '已知', value: 0 }] }),
    page('compare', { rows: ['件數'], options: [{ name: '甲', values: [null] }, { name: '乙', values: [0] }] }),
    page('kpi', { main: { label: '件數', value: null, benchmarks: [{}, { label: '前期', value: 0 }] }, secondary: [{ label: '次要', value: null }] }),
    page('columns', { items: [{ heading: '甲', value: null }, { heading: '乙', value: 0 }] }),
    page('evidence', { kind: 'table', columns: [{ name: '項目', type: 'text' }, { name: '件數', type: 'number' }], rows: [['甲', null], ['乙', 0]] }),
  ];
  const { buffer } = await build({ pages });
  for (let i = 0; i < pages.length; i++) {
    const xml = await slide(buffer, i + 1);
    assert.ok((xml.match(/未提供/g) ?? []).length >= 2, `第 ${i + 1} 頁原位與來源列`);
    assert.ok(xml.includes('>0<'), `第 ${i + 1} 頁保留觀察值 0`);
  }
  assert.ok(!(await slide(buffer, 1)).includes('undefined'));
  const firstCell = await slide((await build({ pages: [page('evidence', { kind: 'table', columns: [{ name: '項目', type: 'text' }, { name: '件數', type: 'number' }], rows: [[null, 0]] })] })).buffer);
  assert.ok(firstCell.includes('未提供：第 1 列／項目'));
});

test('驗收器檢查 lede 與新版型畫面數字，略過控制用的 focus 索引', async () => {
  const base = { pages: [page('columns', { items: [{ heading: '甲', value: 12 }, { heading: '乙' }], focus: 1 }, { lede: '期間：試行週' })] };
  await check(base, '甲的觀察值為 12。');
  await assert.rejects(check({ pages: [{ ...base.pages[0], lede: '期間：2026 年' }] }, '甲的觀察值為 12。'), /lede.*2026/);
  await assert.rejects(check({ pages: [page('kpi', { main: { label: '甲', value: 99, benchmarks: [{ label: '乙', value: 12 }] } })] }, '乙為 12。'), /visual.main.value.*99/);
});

test('說明型範例與原稿可核對，所有頁面均無容量警告', async () => {
  const story = JSON.parse(readFileSync('examples/story-explain.json', 'utf8'));
  const script = readFileSync('evals/fixtures/explain-script.md', 'utf8');
  const result = await check(story, script);
  assert.equal(result.pages, 8);
  assert.deepEqual(result.warnings, []);
  assert.deepEqual(story.pages.map((p) => p.type), ['cover', 'summary', 'kpi', 'list', 'columns', 'flow', 'process', 'close']);
});

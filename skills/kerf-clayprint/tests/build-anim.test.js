import { test } from 'node:test';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import { build, validateStory } from '../scripts/pptx.js';

const list = { type: 'list', claim: '先處理三件事', visual: { items: [{ heading: '甲' }, { heading: '乙' }, { heading: '丙' }] } };
const flow = { type: 'flow', claim: '甲加乙造成丙', visual: { nodes: [{ heading: '甲' }, { heading: '乙' }, { heading: '丙' }] } };

async function slides(pages) {
  const { buffer } = await build({ title: '測試', pages });
  const zip = await JSZip.loadAsync(buffer);
  return Promise.all(pages.map((_, i) => zip.file(`ppt/slides/slide${i + 1}.xml`).async('string')));
}
// Steps in the order the timing tree fades them in, one entry per effect, and the number of clicks.
function played(xml) {
  const step = new Map([...xml.matchAll(/<p:cNvPr id="(\d+)" name="build-(\d+)"/g)].map(([, id, s]) => [id, Number(s)]));
  const timing = xml.match(/<p:timing>[\s\S]*<\/p:timing>/)?.[0] ?? '';
  const order = [...timing.matchAll(/nodeType="(clickEffect|withEffect)"[\s\S]*?<p:spTgt spid="(\d+)"/g)].map(([, , spid]) => step.get(spid));
  return { order, clicks: (timing.match(/nodeType="clickEffect"/g) ?? []).length, shapes: step.size };
}

test('build 頁每個項目一次點擊，依項目順序淡入，項目的所有圖形一起出現', async () => {
  const [built, plain] = await slides([{ ...list, build: true }, list]);
  const { order, clicks, shapes } = played(built);
  assert.equal(clicks, 3);
  assert.equal(order.length, shapes);
  assert.deepEqual([...new Set(order)], [0, 1, 2]);
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  assert.match(built, /presetID="10" presetClass="entr"/);
  assert.doesNotMatch(plain, /<p:timing>|name="build-/);
});

test('因果圖的箭頭跟它指向的方框一起出現', async () => {
  const [xml] = await slides([{ ...flow, build: true }]);
  const arrows = [...xml.matchAll(/<p:cNvPr id="\d+" name="(build-\d+)"[\s\S]*?<\/p:sp>/g)].filter(([shape]) => shape.includes('<a:t>→</a:t>')).map(([, name]) => name);
  assert.deepEqual(arrows, ['build-1', 'build-2']);
  assert.equal(played(xml).clicks, 3);
});

test('build 只接受布林值、現場簡報與逐項版型，錯誤指出頁面與修法', () => {
  validateStory({ pages: [{ ...list, build: false }] });
  const cases = [
    [{ pages: [{ ...list, build: 'yes' }] }, /第 1 頁：pages\[0\]\.build.*請/],
    [{ mode: 'read', pages: [{ ...list, build: true }] }, /第 1 頁：pages\[0\]\.build 只有現場簡報支援/],
    [{ pages: [{ type: 'statement', claim: '判斷', build: true }] }, /第 1 頁：pages\[0\]\.build.*list、process、columns、flow、numbers/],
  ];
  for (const [story, error] of cases) assert.throws(() => validateStory(story), error);
});

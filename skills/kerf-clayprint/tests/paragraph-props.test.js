import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import JSZip from 'jszip';
import { build } from '../scripts/pptx.js';

test('每段文字最多一組段落屬性，而且排在第一個（混合格式的標題也一樣）', async () => {
  const story = JSON.parse(readFileSync(new URL('../examples/story.json', import.meta.url), 'utf8'));
  const zip = await JSZip.loadAsync((await build(story)).buffer);
  const names = Object.keys(zip.files).filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n));
  let mixed = 0;
  for (const name of names) {
    const xml = await zip.file(name).async('string');
    for (const [, inner] of xml.matchAll(/<a:p>([\s\S]*?)<\/a:p>/g)) {
      const props = inner.match(/<a:pPr\b/g) ?? [];
      assert.ok(props.length <= 1 && (!props.length || inner.startsWith('<a:pPr')), `${name}：${inner.slice(0, 160)}`);
      if ((inner.match(/<a:r>/g) ?? []).length > 1) mixed++;
    }
  }
  assert.ok(mixed > 0, '範例要有混合格式的段落，這個測試才有意義');
});

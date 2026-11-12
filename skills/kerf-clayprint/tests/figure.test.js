// The figure slot: an SVG the author drew is placed by the engine on an evidence page and in a report, and its text is checked.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import JSZip from 'jszip';
import { check } from '../evals/check.mjs';
import { checkReport } from '../evals/check-report.mjs';
import { build, validateStory } from '../scripts/pptx.js';
import { buildReport } from '../scripts/report.js';
import { cleanFigure, figureText, resolveFigure } from '../scripts/figure.js';

const root = fileURLToPath(new URL('../', import.meta.url));
const fixtures = join(root, 'tests', 'fixtures');
const svg = readFileSync(join(fixtures, 'figure.svg'), 'utf8').replace(/\r\n/g, '\n');
const manuscript = '收件 12 件，審核後剩 8 件，最後結案。';
const plain = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 100"><text x="10" y="50">收件後審核</text></svg>';
const story = (visual, extra = {}) => ({ title: '自畫圖測試', pages: [{
  type: 'evidence', claim: '收件後先審核再結案', sources: { source: '虛構測試文字稿' }, notes: '說明流程。', visual, ...extra,
}] });
const report = (blocks) => ({ title: '自畫圖報告', message: '收件後先審核再結案', sections: [{ claim: '流程分三步', blocks }] });
const drawn = { type: 'figure', title: '收件到結案', figure: 'figure.svg', source: '虛構測試文字稿' };
const chart = { type: 'chart', title: '各步件數', chart: { kind: 'rank', source: '虛構測試文字稿', rows: [{ label: '收件', value: 12 }, { label: '審核', value: 8 }] } };
const temp = (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'figure-slot-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
};

test('證據頁的自畫圖以 SVG 加 PNG 後備放進投影片，依原比例縮放', async () => {
  const { buffer } = await build(story({ figure: 'figure.svg' }), { baseDir: fixtures });
  const zip = await JSZip.loadAsync(buffer);
  const media = Object.keys(zip.files).filter((name) => /^ppt\/media\//.test(name));
  assert.equal(media.filter((name) => /\.svg$/.test(name)).length, 1);
  assert.equal(media.filter((name) => /\.png$/.test(name)).length, 1);
  assert.match(await zip.file(media.find((name) => /\.svg$/.test(name))).async('string'), /收件/);
  assert.equal(Object.keys(zip.files).filter((name) => /^ppt\/charts\/chart\d+\.xml$/.test(name)).length, 0);
  const slide = await zip.file('ppt/slides/slide1.xml').async('string');
  const [, cx, cy] = slide.match(/<p:pic>[\s\S]*?<a:ext cx="(\d+)" cy="(\d+)"/);
  assert.ok(Math.abs(cx / cy - 1200 / 400) < 0.01, `${cx}×${cy}`);
});

test('簡報驗收讀自畫圖裡的文字：圖上數字要在原稿，檔名與座標不算', async (t) => {
  const dir = temp(t);
  copyFileSync(join(fixtures, 'figure.svg'), join(dir, 'figure-2026.svg'));
  const ok = await check(story({ figure: 'figure-2026.svg' }, { claim: '12 件收件後先審核' }), manuscript, { baseDir: dir });
  assert.ok(!ok.warnings.some((w) => /claim/.test(w)), ok.warnings.join('\n'));
  await assert.rejects(check(story({ figure: 'figure.svg' }), '收件後審核，最後結案，共 12 件。', { baseDir: fixtures }), /第 1 頁 visual\.figure：原稿找不到數字 8/);
  writeFileSync(join(dir, 'plain.svg'), plain);
  assert.equal((await check(story({ figure: 'plain.svg' }), '收件後審核，沒有任何數字。', { baseDir: dir })).pages, 1);
  writeFileSync(join(dir, 'story.json'), JSON.stringify(story({ figure: 'figure-2026.svg' })));
  writeFileSync(join(dir, 'script.md'), manuscript);
  const run = spawnSync(process.execPath, ['evals/check.mjs', join(dir, 'story.json'), join(dir, 'script.md')], { encoding: 'utf8', cwd: root });
  assert.equal(run.status, 0, run.stderr);
  const made = spawnSync(process.execPath, ['scripts/pptx.js', join(dir, 'story.json'), join(dir, 'deck.pptx')], { encoding: 'utf8', cwd: root });
  assert.equal(made.status, 0, made.stderr);
});

test('自畫圖讀檔一次並正規化：CRLF、BOM、XML 宣告與反斜線路徑都可用', async (t) => {
  const dir = temp(t);
  writeFileSync(join(dir, 'crlf.svg'), `﻿<?xml version="1.0" encoding="UTF-8"?>\r\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\r\n<!-- 註解 12345 -->\r\n${svg.replace(/\n/g, '\r\n')}`);
  assert.equal(resolveFigure('crlf.svg', { baseDir: dir }).svg, svg.trim());
  assert.equal(resolveFigure('.\\crlf.svg', { baseDir: dir }).svg, svg.trim());
  assert.deepEqual(cleanFigure('<svg width="300px" height="100"><text>甲</text></svg>'), { svg: '<svg viewBox="0 0 300 100" width="300px" height="100"><text>甲</text></svg>', width: 300, height: 100 });
  assert.match(figureText(svg), /\n12 件\n/);
  assert.equal(figureText('<svg><title>&#49;&#x32;</title></svg>'), '12');
  const html = buildReport(report([drawn]), { baseDir: fixtures }).html;
  assert.deepEqual(checkReport(html.replace(/\n/g, '\r\n'), manuscript, { report: report([{ ...drawn, figure: 'crlf.svg' }]), baseDir: dir }), { sections: 1, figures: 1 });
});

test('自畫圖拒絕驗收器讀不到或畫不出來的內容，並指出原因', () => {
  const wrap = (inner, root = 'viewBox="0 0 10 10"') => `<svg ${root}>${inner}</svg>`;
  for (const [bad, why] of [
    [wrap('<script>1</script>'), /script/], [wrap('<style>text{fill:red}</style>'), /style/], [wrap('<image href="a.png"/>'), /image/],
    [wrap('<foreignObject><p>12</p></foreignObject>'), /foreignObject/], [wrap('<svg viewBox="0 0 1 1"></svg>'), /只能有一個/],
    [wrap('<text data-tick>99</text>'), /data-tick/], [wrap('<text data-label>99</text>'), /data-label/], [wrap('<text><![CDATA[99]]></text>'), /CDATA/],
    [`<!DOCTYPE svg [<!ENTITY n "99">]>${wrap('<text>&n;</text>')}`, /ENTITY/], [wrap('<text>甲</text>', ''), /viewBox/],
    [wrap('<text>甲</text>', 'width="100%" height="100%"'), /viewBox/], ['<p>不是 SVG</p>', /完整的 <svg>/], ['', /空的/],
  ]) assert.throws(() => cleanFigure(bad, '第 1 頁 visual.figure'), (error) => /^第 1 頁 visual\.figure：/.test(error.message) && why.test(error.message), bad);
  assert.throws(() => resolveFigure('missing.svg', { baseDir: fixtures, path: 'x' }), /x：無法讀取 missing\.svg/);
});

test('自畫圖只放在 evidence 頁；kind 與 figure 擇一，路徑不可空白', async () => {
  assert.throws(() => validateStory(story({ figure: '' })), /visual\.figure 格式不正確/);
  assert.throws(() => validateStory(story({ figure: 'figure.svg', kind: 'rank' })), /兩者擇一/);
  assert.throws(() => validateStory(story({})), /畫成 SVG 後改填 \{"figure": "檔名\.svg"\}/);
  await assert.rejects(build(story({ figure: 'missing.svg' }), { baseDir: fixtures }), /第 1 頁 visual\.figure：無法讀取/);
  assert.throws(() => validateStory({ mode: 'read', pages: [{ type: 'panels', claim: '兩格', sources: { source: '稿' },
    visual: { items: [{ title: '甲', visual: { figure: 'figure.svg' } }, { title: '乙', visual: '文字' }] } }] }), /第 1 格/);
});

test('報告的自畫圖由產生器放進 HTML、與圖表共用圖號，重產結果相同並通過嚴格驗收', (t) => {
  for (const blocks of [[drawn, chart], [chart, { ...drawn, note: '示意', wide: true }], [drawn, { type: 'text', text: '共 12 件。' }, { ...drawn, title: '再看一次' }]]) {
    const spec = report(blocks);
    const out = buildReport(spec, { baseDir: fixtures });
    assert.equal(out.figures, blocks.filter((b) => b.type !== 'text').length);
    assert.equal(out.html, buildReport(spec, { baseDir: fixtures }).html);
    const at = blocks.indexOf(blocks.find((b) => b.type === 'figure')) ? 2 : 1;
    assert.match(out.html, new RegExp(`data-label>圖 ${at}</span>收件到結案</p>\\n<div class="chart-scroll"[^>]*>\\n<svg role="img" aria-label="收件到結案" xmlns`));
    assert.match(out.html, /<figcaption>(?:附註：示意｜)?來源：虛構測試文字稿<\/figcaption>/);
    assert.deepEqual(checkReport(out.html, manuscript, { report: spec, baseDir: fixtures }), { sections: 1, figures: out.figures });
    assert.equal(checkReport(out.html, manuscript).figures, out.figures);
    // A number changed by hand inside the figure no longer matches the file.
    assert.throws(() => checkReport(out.html.replace('>8 件<', '>12 件<'), manuscript, { report: spec, baseDir: fixtures }), /與 report\.json 圖表輸入不匹配/);
    // A figure pasted in after generation is not in report.json.
    assert.throws(() => checkReport(out.html.replace('</section>', `<figure>${plain}<figcaption>來源：稿</figcaption></figure></section>`), manuscript, { report: spec, baseDir: fixtures }), /圖表數量不匹配/);
    // Numbers on the figure must be in the manuscript, with or without report.json.
    assert.throws(() => checkReport(out.html, '收件 12 件後審核。', { report: spec, baseDir: fixtures }), blocks[0].type === 'figure' ? /blocks\[0\]\.figure：原稿找不到數字 8/ : /blocks\[0\]\.chart\.rows\[1\]\.value：原稿找不到數字 8/);
    assert.throws(() => checkReport(out.html, '收件 12 件後審核。'), /原稿找不到數字 8/);
  }
  assert.throws(() => buildReport(report([{ ...drawn, source: undefined }]), { baseDir: fixtures }), /blocks\[0\]\.source 格式不正確/);
  assert.throws(() => buildReport(report([{ ...drawn, figure: 3 }]), { baseDir: fixtures }), /blocks\[0\]\.figure 格式不正確/);

  const dir = temp(t);
  copyFileSync(join(fixtures, 'figure.svg'), join(dir, 'figure.svg'));
  writeFileSync(join(dir, 'report.json'), JSON.stringify({ ...report([drawn]), layout: 'web' }));
  writeFileSync(join(dir, 'script.md'), manuscript);
  const run = (script, ...args) => spawnSync(process.execPath, [script, ...args.map((name) => join(dir, name))], { encoding: 'utf8', cwd: root });
  const made = run('scripts/report.js', 'report.json', 'report.html');
  assert.match(made.stdout, /完成：1 節、1 張圖/, made.stderr);
  const first = readFileSync(join(dir, 'report.html'), 'utf8');
  run('scripts/report.js', 'report.json', 'report.html');
  assert.equal(readFileSync(join(dir, 'report.html'), 'utf8'), first);
  const checked = run('evals/check-report.mjs', 'report.html', 'script.md', 'report.json');
  assert.match(checked.stdout, /通過：1 節、1 張圖/, checked.stderr);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import JSZip from 'jszip';
import { build, lineGeometry, lineLabelClashes } from '../scripts/pptx.js';
import { C, T, prepare, textWidth } from '../scripts/core.js';
import { render } from '../scripts/svg.js';

const CHART = (T.type.chart ?? T.type.label).px;
const page = (visual, extra = {}) => ({ type: 'evidence', claim: '判斷', visual, sources: { source: '測試' }, ...extra });
const growth = { kind: 'line', x: ['1 月', '2 月', '3 月', '4 月'], series: [{ name: '完成報名', values: [300, 380, 450, 510] }], focus: '完成報名' };
const tied = { kind: 'line', x: ['1 月', '2 月', '3 月', '4 月'],
  series: [{ name: '甲據點', values: [100, 200, 300, 410] }, { name: '乙據點', values: [150, 220, 330, 400] }] };
const crossed = { kind: 'line', x: ['1 月', '2 月', '3 月', '4 月', '5 月'], focus: '甲',
  series: [{ name: '甲', values: [100, 300, 520, 300, 200] }, { name: '乙', values: [500, 560, 548, 560, 100] }] };

async function deck(pages) {
  const { buffer, warnings } = await build({ title: '測試', pages });
  return { zip: await JSZip.loadAsync(buffer), warnings };
}

// The baseline deck's "完成報名 510" sat on its line: PowerPoint fitted the plot to the whole chart box, then pulled the
// right-hand end label back inside it. The plot must leave the label's width right of the last category.
test('native line chart reserves room right of the last point for its end label', async () => {
  const { zip, warnings } = await deck([page(growth)]);
  assert.deepEqual(warnings, []);
  const chart = await zip.file('ppt/charts/chart1.xml').async('string');
  const layout = chart.match(/<c:plotArea>\s*<c:layout>([\s\S]*?)<\/c:layout>/)?.[1];
  assert.ok(layout && /<c:layoutTarget val="inner"/.test(layout), 'plot area needs an inner manual layout');
  const frac = (k) => Number(layout.match(new RegExp(`<c:${k} val="([^"]+)"`))[1]);
  const slide = await zip.file('ppt/slides/slide1.xml').async('string');
  const frame = slide.match(/<p:graphicFrame>[\s\S]*?<a:ext cx="(\d+)"/);
  const areaW = Number(frame[1]) / 914400 * T.slide.pxPerIn;
  const lastX = frac('x') + frac('w') * (1 - 1 / (2 * growth.x.length));
  assert.ok((1 - lastX) * areaW >= textWidth('完成報名 510', CHART), `right of the last point: ${((1 - lastX) * areaW).toFixed(0)} px`);
});

test('native line chart warns when labels collide with each other or with a line, and not on a clean chart', async () => {
  const { warnings } = await deck([page(tied), page(crossed), page(growth)]);
  assert.equal(warnings.length, 2, warnings.join('\n'));
  assert.match(warnings[0], /^第 1 頁折線圖標籤「甲據點 410」和「乙據點 400」重疊/);
  assert.match(warnings[1], /^第 2 頁折線圖標籤「520」壓到「乙」的線/);
  const area = { w: T.chartArea.evidence.width, h: T.chartArea.evidence.height };
  assert.deepEqual(lineLabelClashes(prepare(growth), area), []);
  assert.ok(lineGeometry(prepare(growth), area).fits);
});

test('native line chart warns instead of laying out when the end label leaves too little plot', async () => {
  const long = { ...growth, series: [{ name: '完成報名的課程與活動件數合計（含線上與現場）'.repeat(2), values: growth.series[0].values }], focus: undefined };
  const { warnings } = await deck([page(long)]);
  assert.ok(warnings.some((w) => /線尾標籤太長，繪圖區放不下/.test(w)), warnings.join('\n'));
});

test('SVG charts warn when two texts overlap, and the examples stay clean', () => {
  const grouped = { kind: 'grouped', x: ['實作課', '導覽課', '講座'], seriesRole: 'categorical',
    series: [{ name: '山側據點', values: [600, 240, 160] }, { name: '海側據點', values: [420, 330, 250] }] };
  assert.ok(render(grouped).model.warnings.some((w) => /「山側據點」和「600」重疊/.test(w)));
  for (const f of readdirSync('examples').filter((n) => n.endsWith('.json'))) {
    const spec = JSON.parse(readFileSync(`examples/${f}`, 'utf8'));
    if (typeof spec.kind !== 'string') continue;
    assert.deepEqual(render(spec).model.warnings.filter((w) => /重疊|壓到/.test(w)), [], f);
  }
});

test('notes given as an array become one paragraph each, not a comma-joined run', async () => {
  const { zip } = await deck([page(growth, { notes: ['先說結論。', '計算：510 − 300 = 210'] }), page(growth, { notes: '單段講稿。' })]);
  const paragraphs = async (n) => {
    const xml = await zip.file(`ppt/notesSlides/notesSlide${n}.xml`).async('string');
    const body = xml.match(/name="Notes Placeholder 2"[\s\S]*?<p:txBody>([\s\S]*?)<\/p:txBody>/)[1];
    return [...body.matchAll(/<a:p>([\s\S]*?)<\/a:p>/g)].map((m) => [...m[1].matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((t) => t[1]).join(''));
  };
  assert.deepEqual(await paragraphs(1), ['先說結論。', '計算：510 − 300 = 210']);
  assert.deepEqual(await paragraphs(2), ['單段講稿。']);
});

// Round 2: PowerPoint wrapped the focus label "中心電子報 900" after the name, and the 1,000 gridline ran through both
// lines. A one-line label still crosses that gridline (the bar ends at 900), so bar-end labels also need a box in the
// chart background. The fill sits between numFmt and txPr, the order the schema requires.
test('native bar-end data labels stay on one line and cover the gridline under them', async () => {
  const rank = { kind: 'rank', unit: '份', focus: ['中心電子報', '社區公告'], rows: [
    { label: '中心電子報', value: 900 }, { label: '社區公告', value: 650 }, { label: '親友介紹', value: 450 }, { label: '電話語音服務', value: 0 }] };
  const grouped = { kind: 'grouped', x: ['實作課', '導覽課', '講座'],
    series: [{ name: '山側據點', values: [600, 240, 160] }, { name: '海側據點', values: [420, 330, 250] }] };
  const { zip } = await deck([page(rank), page(grouped), page(growth)]);
  // pptxgenjs numbers charts across builds in one process, so take this deck's charts in page order.
  const names = Object.keys(zip.files).filter((f) => /^ppt\/charts\/chart\d+\.xml$/.test(f))
    .sort((a, b) => parseInt(a.match(/\d+/)) - parseInt(b.match(/\d+/)));
  assert.equal(names.length, 3);
  const bg = C.onDark[0].replace('#', '').toUpperCase();
  for (const n of [0, 1]) {
    const chart = await zip.file(names[n]).async('string');
    const dLbls = chart.match(/<c:dLbl>[\s\S]*?<\/c:dLbl>/g) ?? [];
    assert.ok(dLbls.length >= 4, `chart${n} labels`);
    for (const d of dLbls) {
      assert.match(d, /<c:txPr><a:bodyPr wrap="none"\/>/, `chart${n} label wraps`);
      assert.match(d, new RegExp(`sourceLinked="0"/><c:spPr><a:solidFill><a:srgbClr val="${bg}"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr><c:txPr>`), `chart${n} label fill`);
    }
  }
  const line = await zip.file(names[2]).async('string');
  for (const d of line.match(/<c:dLbl>[\s\S]*?<\/c:dLbl>/g)) assert.doesNotMatch(d, /<c:spPr>/, 'line labels must not hide the line');
});

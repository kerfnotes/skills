import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import JSZip from 'jszip';
import { extract } from '../scripts/extract.js';
import { build } from '../scripts/pptx.js';

const chart = `<?xml version="1.0"?><c:chartSpace xmlns:c="chart"><c:chart><c:plotArea><c:barChart><c:ser><c:tx><c:strRef><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>件數</c:v></c:pt></c:strCache></c:strRef></c:tx><c:cat><c:strRef><c:strCache><c:ptCount val="2"/><c:pt idx="0"><c:v>甲</c:v></c:pt><c:pt idx="1"><c:v>乙</c:v></c:pt></c:strCache></c:strRef></c:cat><c:val><c:numRef><c:numCache><c:ptCount val="2"/><c:pt idx="0"><c:v>0</c:v></c:pt></c:numCache></c:numRef></c:val></c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>`;
const rels = (entries) => `<Relationships>${entries.map(([id, type, target]) => `<Relationship Id="${id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${type}" Target="${target}"/>`).join('')}</Relationships>`;
async function fixture(ext, parts, run) {
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-extract-'));
  try {
    const zip = new JSZip();
    for (const [name, value] of Object.entries(parts)) zip.file(name, value);
    const filename = path.join(dir, `input.${ext}`);
    writeFileSync(filename, await zip.generateAsync({ type: 'nodebuffer' }));
    await run(filename);
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

test('既有 PPTX 逐頁擷取文字、備忘稿與圖表快取，保留零與缺值', async () => {
  // Build the decks here so the test runs in a fresh checkout (out/ is not versioned).
  const dir = mkdtempSync(path.join(tmpdir(), 'clayprint-extract-'));
  try {
    const read = (name) => JSON.parse(readFileSync(new URL(`../examples/${name}.json`, import.meta.url), 'utf8'));
    const story = read('story');
    const storyFile = path.join(dir, 'story.pptx');
    writeFileSync(storyFile, (await build(story)).buffer);
    const deck = await extract(storyFile);
    assert.equal(deck.slides.length, story.pages.length);
    assert.ok(deck.slides[0].text.some((s) => s.includes(story.pages[0].claim.split('\n')[0])));
    assert.ok(deck.slides.some((s) => s.notes.length));

    const kinds = ['rank', 'line', 'slope', 'share', 'scatter', 'table'];
    const nativeFile = path.join(dir, 'native.pptx');
    const pages = kinds.map((kind) => {
      const visual = read(kind);
      if (kind === 'scatter') delete visual.refs; // This fixture exercises native chart caches.
      return { type: 'evidence', claim: kind, sources: { source: '測試' }, visual };
    });
    writeFileSync(nativeFile, (await build({ pages })).buffer);
    const native = await extract(nativeFile);
    assert.equal(native.slides.length, kinds.length);
    assert.deepEqual(native.slides.map((s) => s.charts[0]?.type).filter(Boolean), ['barChart', 'lineChart', 'lineChart', 'barChart', 'scatterChart']);
    const rank = read('rank').rows.map((r) => r.value).filter((v) => v !== null).sort((a, b) => b - a);
    assert.deepEqual(native.slides[0].charts[0].series[0].values.filter((v) => v !== null), rank);
    assert.match(native.slides[0].charts[0].embeddedWorkbook, /^ppt\/embeddings\/.*\.xlsx$/);
    const line = read('line'), first = line.series.find((s) => s.name === line.focus) ?? line.series[0];
    const missing = first.values.findIndex((v) => v === null);
    if (missing >= 0) assert.equal(native.slides[1].charts[0].series.find((s) => s.name === first.name)?.values[missing] ?? null, null);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('DOCX 擷取段落、表格、頁首、圖表快取與圖片清單', async () => {
  await fixture('docx', {
    'word/document.xml': `<w:document xmlns:w="word" xmlns:r="rels" xmlns:c="chart"><w:body><w:p><w:r><w:t>第一段 &amp; 補充</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>項目</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:drawing><c:chart r:id="rId1"/></w:drawing></w:p></w:body></w:document>`,
    'word/_rels/document.xml.rels': rels([['rId1', 'chart', 'charts/chart1.xml']]),
    'word/charts/chart1.xml': chart,
    'word/header1.xml': '<w:hdr xmlns:w="word"><w:p><w:r><w:t>頁首</w:t></w:r></w:p></w:hdr>',
    'word/media/image1.png': Buffer.from([137, 80, 78, 71]),
  }, async (filename) => {
    const result = await extract(filename);
    assert.deepEqual(result.blocks[0], { type: 'paragraph', text: '第一段 & 補充' });
    assert.deepEqual(result.blocks[1].rows, [['項目', '12']]);
    assert.deepEqual(result.headers[0].text, ['頁首']);
    assert.equal(result.images.length, 1);
    assert.deepEqual(result.charts[0].series[0].values, [0, null]);
  });
});

test('XLSX 擷取工作表共享文字、公式快取、圖表與圖片', async () => {
  await fixture('xlsx', {
    'xl/workbook.xml': '<workbook xmlns:r="rels"><sheets><sheet name="資料" sheetId="1" r:id="rId1"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels': rels([['rId1', 'worksheet', 'worksheets/sheet1.xml']]),
    'xl/sharedStrings.xml': '<sst><si><t>甲</t></si></sst>',
    'xl/worksheets/sheet1.xml': '<worksheet xmlns:r="rels"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><f>2+3</f><v>5</v></c></row></sheetData><drawing r:id="rId2"/><tableParts><tablePart r:id="rId3"/></tableParts></worksheet>',
    'xl/worksheets/_rels/sheet1.xml.rels': rels([['rId2', 'drawing', '../drawings/drawing1.xml'], ['rId3', 'table', '../tables/table1.xml']]),
    'xl/tables/table1.xml': '<table name="Test" displayName="測試表" ref="A1:B2"><tableColumns><tableColumn id="1" name="項目"/><tableColumn id="2" name="件數"/></tableColumns></table>',
    'xl/drawings/drawing1.xml': '<xdr:wsDr xmlns:xdr="drawing" xmlns:c="chart" xmlns:a="main" xmlns:r="rels"><xdr:twoCellAnchor><c:chart r:id="rId1"/><a:blip r:embed="rId2"/></xdr:twoCellAnchor></xdr:wsDr>',
    'xl/drawings/_rels/drawing1.xml.rels': rels([['rId1', 'chart', '../charts/chart1.xml'], ['rId2', 'image', '../media/image1.png']]),
    'xl/charts/chart1.xml': chart,
    'xl/media/image1.png': Buffer.from([137, 80, 78, 71]),
  }, async (filename) => {
    const result = await extract(filename);
    assert.equal(result.sheets[0].name, '資料');
    assert.deepEqual(result.sheets[0].rows[0].cells, [{ ref: 'A1', value: '甲' }, { ref: 'B1', value: 5, formula: '2+3' }]);
    assert.equal(result.sheets[0].charts[0].series[0].name, '件數');
    assert.deepEqual(result.sheets[0].charts[0].series[0].categories, ['甲', '乙']);
    assert.deepEqual(result.sheets[0].tables[0].columns, ['項目', '件數']);
    assert.equal(result.images.length, 1);
    assert.deepEqual(result.sheets[0].images, ['xl/media/image1.png']);
  });
});

test('不支援的副檔名直接拒絕', async () => {
  await assert.rejects(extract('file.html'), /只支援/);
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildReport } from '../scripts/report.js';
import { replaceTheme, themeCss, webThemeCss } from '../scripts/theme-css.js';
import { checkReport } from '../evals/check-report.mjs';

const report = JSON.parse(readFileSync('examples/report.json', 'utf8'));
const web = { ...report, layout: 'web' };
const build = (r) => buildReport(r, { baseDir: 'examples' });

test('default layout output is unchanged; "report" equals omitted; other values are rejected', () => {
  const baseline = build(report).html;
  assert.equal(baseline, readFileSync('examples/report.html', 'utf8'));
  assert.equal(build({ ...report, layout: 'report' }).html, baseline);
  assert.throws(() => build({ ...report, layout: 'slides' }), /layout/);
});

test('web layout: hero headline is the message, no cover or contents, same sections', () => {
  const { html, sections } = build(web);
  assert.match(html, /<html lang="zh-Hant" data-layout="web"/);
  assert.ok(html.includes(`<h1>${report.message}</h1>`));
  assert.ok(html.includes(`<title>${report.title}</title>`));
  assert.doesNotMatch(html, /class="(?:report-cover|report-front|toc|cover-message)"/);
  assert.match(html, /<header class="web-hero">/);
  assert.match(html, /<section class="summary"[\s\S]*class="summary-metrics"/);
  assert.equal((html.match(/<section\b/g) ?? []).length, sections);
  assert.equal(sections, build(report).sections);
});

test('web CSS keeps the screen rules and drops print', () => {
  const css = webThemeCss(), base = themeCss();
  assert.ok(base.startsWith(css.slice(0, css.indexOf('[data-layout="web"]'))));
  assert.doesNotMatch(css, /@page|@media print/);
  assert.match(css, /\.web-hero/);
  const html = build(web).html;
  assert.equal(replaceTheme(html), html);
  assert.equal(replaceTheme(build(report).html), build(report).html);
});

test('web report passes the number check, fails when tampered, and refuses PDF', () => {
  const { html } = build(web);
  const script = readFileSync('evals/fixtures/explain-script.md', 'utf8');
  const options = { report: web, baseDir: 'examples' };
  assert.equal(checkReport(html, script, options).sections, build(report).sections);
  assert.throws(() => checkReport(html.replace('</h1>', ' 987654321</h1>'), script, options));
  const dir = mkdtempSync(join(tmpdir(), 'clayprint-web-'));
  try {
    const file = join(dir, 'report.html');
    writeFileSync(file, html);
    const pdf = spawnSync(process.execPath, ['scripts/pdf.js', file, join(dir, 'pdf')], { encoding: 'utf8' });
    assert.equal(pdf.status, 2);
    assert.match(pdf.stderr, /網頁型不供列印/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

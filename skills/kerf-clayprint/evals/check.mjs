// Validate a story against its source manuscript, then build it with the production renderer.
import { readFileSync } from 'node:fs';
import { build, validateStory, deckCategories } from '../scripts/pptx.js';
import { normalize, numbers, found, calculations, calculationPattern } from './numbers.mjs';
import { isMain, rerunForMode } from '../scripts/main.js';
import { prepare, delta, shownDigits } from '../scripts/core.js';

function visibleText(value, path) {
  if (typeof value === 'number' || typeof value === 'string') return [{ text: String(value), path }];
  if (Array.isArray(value)) return value.flatMap((v, i) => visibleText(v, `${path}[${i}]`));
  if (!value || typeof value !== 'object') return [];
  // digits and numeric focus indices control rendering; neither is a visible measurement.
  return Object.entries(value).flatMap(([key, v]) => key === 'digits' || key === 'focus' && typeof v === 'number' ? [] : visibleText(v, `${path}.${key}`));
}

export async function check(story, script) {
  validateStory(story);
  if (typeof script !== 'string' || !script.trim()) throw new Error('script.md 必須是非空文字稿；請提供原始內容。');
  const original = numbers(script);
  const warnings = [];
  const categoryOrder = deckCategories(story);
  if (original.some((n) => !n.valid)) throw new Error('原稿含無法以有限數字精確表示的數值；請核對科學記號或調整單位，保留原始資料。');
  for (const field of ['title', 'date']) {
    for (const { text, path } of visibleText(story[field], field)) {
      for (const value of numbers(text)) {
        if (!found(value, original)) throw new Error(`根層 ${path}：原稿找不到數字 ${value.text}；請改回原稿數字，未提供日期時省略 date。`);
      }
    }
  }
  for (const [i, page] of story.pages.entries()) {
    const n = i + 1;
    if (typeof page.sources?.source !== 'string' || !page.sources.source.trim()) {
      throw new Error(`第 ${n} 頁 sources.source 缺少資料來源；請填文字稿名稱，虛構稿也要註明。`);
    }
    if (!original.length && page.type === 'evidence' && page.visual.kind !== 'table') {
      throw new Error(`第 ${n} 頁：文字稿沒有可核對的數字，不能放量化圖表；請改用 statement、compare、close 或純文字 table。`);
    }
    const allowed = [...original, ...calculations(page, original, n)];
    // panels' split is a width ratio, not a measurement.
    const shown = (field) => field === 'visual' && page.type === 'panels' ? { ...page.visual, split: undefined } : page[field];
    // Footnote markers (1)…(N) are references, not measurements; a marker past the page's footnote count is still checked.
    const marks = page.footnotes?.length ?? 0;
    const unmark = (text) => normalize(text).replace(/\((\d+)\)/g, (m, d) => Number(d) >= 1 && Number(d) <= marks ? ' ' : m);
    const visible = [
      ...['claim', 'kicker', 'lede', 'note', 'takeaway', 'points', 'footnotes'].map((field) => [field, page[field]]),
      ...['value', 'label', 'unit'].map((field) => [`metric.${field}`, page.metric?.[field]]),
      // period holds date ranges such as 2025.01–2025.12; dates are reviewed by hand, not as measured values.
      ...['source', 'unit', 'more'].map((field) => [`sources.${field}`, page.sources[field]]),
      ['visual', shown('visual')],
    ].flatMap(([path, value]) => visibleText(value, path));
    for (const { text, path } of visible) {
      // 已驗算的片段由算式語法處理正負號，避免將減號誤認為原稿負數。
      const unverified = path.startsWith('sources.more[') ? unmark(text).replace(calculationPattern, '') : unmark(text);
      for (const value of numbers(unverified)) {
        if (!found(value, allowed)) {
          throw new Error(`第 ${n} 頁 ${path}：原稿找不到數字 ${value.text}；請改回原稿數字，或在當頁 notes／sources.more 寫出可核對的加減算式（如「計算：1200 + 800 = 2000」）。`);
        }
      }
    }
    const fields = ['visual', 'lede', 'takeaway', 'points', 'footnotes'];
    if (page.type === 'evidence') fields.push('metric');
    if (['cover', 'section', 'statement', 'evidence'].includes(page.type)) fields.push('note');
    const picture = fields.filter((field) => field !== 'visual' || page.type !== 'evidence')
      .flatMap((field) => visibleText(shown(field), field))
      .filter(({ path }) => !/\.(?:focus|digits|source|period|prev)(?:[.\[]|$)/.test(path))
      .flatMap(({ text }) => numbers(text));
    if (page.type === 'evidence') {
      const model = prepare(page.visual, { categoryOrder });
      const labels = visibleText(model, 'visual').filter(({ path }) => /\.(?:text|texts|\w*Text|label|name|x|periods|rowLabels|colLabels|xLabel|yLabel)(?:\[\d+\])?$/.test(path)
        && !(page.visual.kind === 'slope' && page.visual.native !== false && path.endsWith('.delta.text')));
      picture.push(...labels.flatMap(({ text }) => numbers(text)));
      if (model.kind === 'funnel') for (const step of model.steps) {
        if (step.lossText !== null) picture.push(...numbers(step.loss));
      }
    }
    if (page.type === 'numbers' || page.type === 'summary') for (const item of page.visual.items) {
      if (typeof item.value !== 'number' || item.prev === undefined) continue;
      const change = delta(item.prev, item.value, { better: item.better ?? 'higher', mode: item.mode ?? 'abs', digits: shownDigits(item.digits, item.prev, item.value), suffix: item.deltaSuffix ?? '' });
      const labels = numbers(change?.text ?? '');
      picture.push(...labels, ...labels.map((n) => ({ ...n, value: Math.abs(n.value) })));
    }
    for (const value of numbers(unmark(page.claim))) {
      if (!found(value, picture)) warnings.push(`第 ${n} 頁 claim：數字 ${value.text} 未出現在當頁畫面；請補入 visual／metric／lede／body，讓主張與畫面可核對。`);
    }
    const noteLines = (Array.isArray(page.notes) ? page.notes : [page.notes ?? '']).flatMap((text) => normalize(text).split(/\r\n|\r|\n/));
    // A read deck has no presenter: the build warns when an evidence page's right column is blank instead of asking for speaker notes.
    if (story.mode !== 'read' && page.type !== 'cover' && !noteLines.some((line) => line.trim() && !/^(?:計算|算法)\s*:/.test(line.trim()))) {
      warnings.push(`第 ${n} 頁 notes：缺少講稿或只有計算行；請另寫 1～3 句要說的話與資料限制。`);
    }
  }
  const result = await build(story);
  return { ...result, warnings: [...result.warnings, ...warnings], pages: story.pages.length };
}

if (isMain(import.meta.url)) {
  const [storyFile, scriptFile] = process.argv.slice(2);
  if (!storyFile || !scriptFile) {
    console.error('用法：node evals/check.mjs story.json script.md');
    process.exitCode = 2;
  } else {
    try {
      let story;
      try { story = JSON.parse(readFileSync(storyFile, 'utf8')); }
      catch { throw new Error(`無法讀取 ${storyFile} 為 JSON；請確認路徑、雙引號與逗號。`); }
      if (rerunForMode(story)) process.exit();
      let script;
      try { script = readFileSync(scriptFile, 'utf8'); }
      catch { throw new Error(`無法讀取文字稿 ${scriptFile}；請確認檔案路徑。`); }
      const result = await check(story, script);
      for (const warning of result.warnings) console.error(`警告：${warning}`);
      console.log(`通過：${result.pages} 頁，PowerPoint 建檔成功；${result.warnings.length} 項警告。請再逐頁核對語意與預覽。`);
    } catch (error) {
      console.error(`驗收失敗：${error.message}`);
      process.exitCode = 1;
    }
  }
}

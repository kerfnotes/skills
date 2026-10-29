// Data side of the charts: number formatting, deltas, ticks, color roles.
// Everything visual comes from the active design layer; nothing here draws.
import { loadTokens } from './tokens.js';

const tokens = loadTokens();

export const T = tokens;
export const C = tokens.color;
export const FONT_FAMILY = [...tokens.font.latin, ...tokens.font.cjk, 'sans-serif']
  .map((f) => (f.includes(' ') ? `'${f}'` : f)).join(', ');
// Inside PowerPoint every run uses one font, font.slide in the design layer. The default, Microsoft JhengHei,
// ships with Windows and Office for Mac, so slides and their embedded charts look the same on both.
// Text widths are calibrated for it; with another font, check line breaks in the preview.
export const SLIDE_FONT = tokens.font.slide ?? 'Microsoft JhengHei';
const MINUS = '−';
const OTHER = tokens.categoryRules.otherByName;

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const round = (v, digits) => Number(v.toFixed(digits));

function group(intPart) {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// A label for one value. 0 is a value; null is missing. A non-zero value never prints as 0.
export function formatValue(v, { digits = 0, suffix = '' } = {}) {
  if (!isNum(v)) return null;
  if (v === 0) return `0${suffix}`;
  const r = round(v, digits);
  if (r === 0) {
    const step = (10 ** -digits).toFixed(digits);
    return `${v > 0 ? '<' : `>${MINUS}`}${step}${suffix}`;
  }
  const [i, f] = Math.abs(r).toFixed(digits).split('.');
  return `${r < 0 ? MINUS : ''}${group(i)}${f ? `.${f}` : ''}${suffix}`;
}

// Change label: the sign is literal, the color says better or worse.
// mode: 'abs' difference, 'pct' percent change, 'pp' difference between two percentages.
export function delta(prev, curr, { better = 'higher', mode = 'abs', digits = 0, suffix = '' } = {}) {
  if (!isNum(prev) || !isNum(curr)) return null;
  if (mode === 'pct' && prev === 0) mode = 'abs';
  const d = mode === 'pct' ? ((curr - prev) / Math.abs(prev)) * 100 : curr - prev;
  if (d === 0) return { text: tokens.delta.signs.unchanged, color: C.unchanged };
  const unit = mode === 'pp' ? ` ${tokens.delta.percentOfPercent}` : mode === 'pct' ? '%' : suffix;
  const sign = d > 0 ? tokens.delta.signs.increase : tokens.delta.signs.decrease;
  const good = (d > 0) === (better !== 'lower');
  return { text: `${sign}${formatValue(Math.abs(d), { digits })}${unit}`, color: good ? C.better : C.worse };
}

// Ticks on 1/2/5 × 10^n steps covering [min, max]. Takes the finest step that keeps at most count + 2 ticks,
// so the top tick hugs the data (0–5,000 for 4,100, not 0–6,000).
export function niceTicks(min, max, count = 5) {
  // A range too small to step through (e.g. 0 to 1e-101) gets a unit range; labels still say "<1".
  if (max - min < 1e-9 * Math.max(1, Math.abs(min), Math.abs(max))) max = min + 1;
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const steps = [1, 2, 5, 10, 20, 50].map((k) => k * mag).filter((s) => s >= raw * 0.8);
  for (const step of steps) {
    const decimals = Math.max(0, -Math.floor(Math.log10(step)));
    const lo = Math.floor(min / step + 1e-9) * step;
    const hi = Math.ceil(max / step - 1e-9) * step;
    if (Math.round((hi - lo) / step) + 1 > count + 2 && step !== steps.at(-1)) continue;
    const ticks = [];
    for (let t = lo; t <= hi + step / 2; t += step) ticks.push(round(t, decimals));
    return { ticks, lo: ticks[0], hi: ticks.at(-1), step, decimals };
  }
}

// Most decimal places among the numbers (capped at 6), for bin edges and legend ranges.
export function decimalsOf(nums) {
  return Math.max(0, ...nums.filter(isNum).map((v) => {
    const [, frac = ''] = String(Number(v.toFixed(6))).split('.');
    return frac.length;
  }));
}

// Digits for a shown value: the ones given, else the values' own decimals, so 24.7 stays 24.7 and never prints as 25.
export const shownDigits = (digits, ...values) => digits ?? decimalsOf(values);

// Axis labels keep the tick step's precision, so 0.1 never prints as "<1".
export function tickText(axis, t, suffix = '') {
  return formatValue(t, { digits: axis.decimals, suffix });
}

// Color per category name. With a shared order (from the deck), a name keeps its color in every chart;
// "其他" is gray by name; categories beyond the available palette fold into "其他".
// Shared document order for unordered categories; ordered/focus semantics stay local.
export function documentCategories(visuals) {
  const seen = [];
  for (const v of visuals) {
    if (!v?.kind) continue;
    const names = ['share', 'sharetrend', 'waffle', 'mekko'].includes(v.kind) ? v.categories
      : v.kind === 'grouped' && v.seriesRole === 'categorical' || v.kind === 'line' && !v.focus && v.series.length > 1 ? v.series.map((s) => s.name) : [];
    for (const name of names) if (!seen.includes(name)) seen.push(name);
  }
  return seen;
}

export function categoryLimit() {
  if (!Array.isArray(C.categorical) || C.categorical.length < 1) throw new Error('color.categorical 長度不足：至少需要 1 色');
  if (!Number.isInteger(tokens.categoryRules.maxCategorical) || tokens.categoryRules.maxCategorical < 1) throw new Error('categoryRules.maxCategorical 必須是至少 1 的整數');
  return Math.min(tokens.categoryRules.maxCategorical, C.categorical.length);
}

export function categoryColors(names, { order } = {}) {
  const limit = categoryLimit();
  const ranked = [...(order ?? []), ...names].filter((n, i, all) => n !== OTHER && all.indexOf(n) === i);
  const colors = new Map();
  const folded = [];
  for (const name of names) {
    if (name === OTHER) continue;
    const i = ranked.indexOf(name);
    if (i < limit) colors.set(name, C.categorical[i]);
    else folded.push(name);
  }
  folded.sort((a, b) => ranked.indexOf(a) - ranked.indexOf(b));
  if (folded.length || names.includes(OTHER)) colors.set(OTHER, C.other);
  return { colors, folded };
}

export function shares(values) {
  if (values.some((v) => !isNum(v) || v < 0)) throw new Error('比例需要非負的數字');
  const sum = values.reduce((a, b) => a + b, 0);
  if (sum === 0) throw new Error('比例的總和不能是 0');
  return values.map((v) => v / sum);
}

// Keep explicit design choices; new fills use the more legible of the two body inks.
export function textOn(fill, design = T) {
  for (const [ink, fills] of Object.entries(design.textOnFill ?? {})) {
    if (fills.some((color) => color.toUpperCase() === fill.toUpperCase())) return ink;
  }
  const { text, onDark } = design.color;
  return contrast(fill, text) >= contrast(fill, onDark[0]) ? text : onDark[0];
}

function luminance(hex) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error(`色碼 ${hex} 必須是 #RRGGBB 格式`);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// Equal-width bins from 0 to the maximum; each bin holds its lower edge, the top bin also its upper edge.
export function heatBins(values, steps = tokens.heatmap.steps) {
  if (!Array.isArray(C.ordered) || C.ordered.length < 2) throw new Error('color.ordered 長度不足：至少需要 2 色');
  if (!Number.isInteger(steps) || steps < 2) throw new Error('heatmap.steps 必須是至少 2 的整數');
  steps = Math.min(steps, C.ordered.length);
  const nums = values.filter(isNum);
  if (nums.some((v) => v < 0)) throw new Error('熱度格從 0 起算；有負值要改用雙向色階');
  const max = Math.max(...nums);
  const width = max > 0 ? max / steps : 1;
  const edges = Array.from({ length: steps + 1 }, (_, i) => round(i * width, 10));
  const binOf = (v) => Math.min(steps - 1, Math.floor(v / width + 1e-9));
  return { edges, binOf };
}

// Advance widths in em, calibrated against resvg with Helvetica Neue and PingFang (tests/core.test.js).
function charEm(ch) {
  const c = ch.codePointAt(0);
  if ((c >= 0x2e80 && c <= 0x9fff) || (c >= 0xf900 && c <= 0xfaff) || (c >= 0xff00 && c <= 0xffef) || (c >= 0x3000 && c <= 0x303f)) return 1;
  if (ch >= '0' && ch <= '9') return 0.6;
  if ('ijlI'.includes(ch)) return 0.26;
  if ('frt'.includes(ch)) return 0.37;
  if (ch === 'm') return 0.86;
  if (ch === 'w') return 0.76;
  if (ch === 'M' || ch === 'W') return 0.92;
  if (ch >= 'A' && ch <= 'Z') return 0.7;
  if (ch >= 'a' && ch <= 'z') return 0.56;
  if (',.:;\'|'.includes(ch)) return 0.28;
  if (ch === ' ') return 0.34;
  if (ch === '%') return 0.97;
  if (ch === MINUS || ch === '–') return 0.83;
  return 0.6;
}

export function textWidth(str, px) {
  let em = 0;
  for (const ch of String(str)) em += charEm(ch);
  return em * px;
}

// ---- prepare: spec → model. The model is what both renderers draw (SVG now, PowerPoint native in Phase 3):
// every mark carries its raw value, its label text and its color; missing values are listed for the source row.

const KINDS = {};
const numOrNull = (v) => v === null || isNum(v);
const need = (ok, msg) => { if (!ok) throw new Error(msg); };
const fmt = (m) => (v) => formatValue(v, { digits: m.digits });

export function prepare(spec, opts = {}) {
  need(spec && typeof spec === 'object', '圖表 spec 必須是物件');
  const fn = KINDS[spec.kind];
  need(fn, `不認得的圖表種類：${spec.kind}`);
  const model = {
    kind: spec.kind, unit: spec.unit ?? null, period: spec.period ?? null, source: spec.source ?? null,
    digits: spec.digits ?? 0, better: spec.better ?? tokens.delta.better.default, missing: [], warnings: [],
  };
  return fn(spec, model, opts);
}

KINDS.rank = (spec, m) => {
  need(Array.isArray(spec.rows) && spec.rows.length, 'rank 需要 rows');
  for (const r of spec.rows) need(typeof r.label === 'string' && numOrNull(r.value), `rank 的資料格式不對：${JSON.stringify(r)}`);
  let rows = spec.rows.filter((r) => (r.value === null ? (m.missing.push(r.label), false) : true));
  need(rows.length, 'rank 沒有任何數值');
  if (spec.sort !== false) rows = [...rows].sort((a, b) => b.value - a.value);
  const focuses = spec.focus === undefined ? [] : Array.isArray(spec.focus) ? spec.focus : [spec.focus];
  need(focuses.every((name) => typeof name === 'string'), 'rank 的 focus 需要名稱或名稱陣列');
  for (const name of focuses) if (!rows.some((r) => r.label === name)) m.warnings.push(`focus「${name}」不在資料裡`);
  const vals = rows.map((r) => r.value);
  m.axis = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals), 4);
  m.rows = rows.map((r) => ({
    label: r.label, value: r.value, text: fmt(m)(r.value), focus: focuses.includes(r.label),
    color: !focuses.length || focuses.includes(r.label) ? C.focus : C.gray,
  }));
  return m;
};

function series(spec, m, opts, tickCount) {
  need(Array.isArray(spec.x) && spec.x.length >= 2, `${spec.kind} 需要 x（至少兩個點）`);
  need(Array.isArray(spec.series) && spec.series.length, `${spec.kind} 需要 series`);
  for (const s of spec.series) {
    need(typeof s.name === 'string' && Array.isArray(s.values) && s.values.length === spec.x.length && s.values.every(numOrNull),
      `${spec.kind} 的系列「${s.name}」長度或數值不對`);
  }
  const all = spec.series.flatMap((s) => s.values).filter(isNum);
  need(all.length, `${spec.kind} 沒有任何數值`);
  m.x = spec.x;
  m.axis = niceTicks(Math.min(0, ...all), Math.max(...all), tickCount);
  const single = spec.series.length === 1;
  const cats = spec.focus || single || spec.kind === 'multiples' ? null : categoryColors(spec.series.map((s) => s.name), { order: opts.categoryOrder });
  if (cats?.folded.length) m.warnings.push(`沒有 focus 的系列超過 ${categoryLimit()} 條，「${cats.folded.join('、')}」改用「其他」的灰`);
  if (spec.focus && !spec.series.some((s) => s.name === spec.focus)) m.warnings.push(`focus「${spec.focus}」不在資料裡`);
  m.series = spec.series.map((s) => {
    s.values.forEach((v, i) => v === null && m.missing.push(`${s.name}／${spec.x[i]}`));
    const focus = spec.focus ? s.name === spec.focus : single;
    const color = cats ? cats.colors.get(s.name) ?? C.other : focus ? C.focus : C.gray;
    const last = s.values.findLastIndex(isNum);
    let peak = -1;
    if (focus) {
      peak = s.values.reduce((best, v, i) => (isNum(v) && (best < 0 || v > s.values[best]) ? i : best), -1);
      if (peak === last || s.values[peak] === s.values[last]) peak = -1;
    }
    return {
      name: s.name, values: s.values, texts: s.values.map(fmt(m)), focus, color,
      width: focus || !spec.focus ? tokens.stroke.focusLine : tokens.stroke.otherLine, last, peak,
    };
  });
  return m;
}

KINDS.line = (spec, m, opts) => series(spec, m, opts, 4);

KINDS.multiples = (spec, m, opts) => {
  series({ ...spec, focus: undefined }, m, opts, 2);
  for (const s of m.series) Object.assign(s, { color: C.focus, width: tokens.stroke.focusLine, peak: -1 });
  if (m.series.length > 6) m.warnings.push(`小倍數有 ${m.series.length} 格，超過 6 格會很擠`);
  return m;
};

// Two periods per row: slope and dumbbell. Older period is the light Ordered step, newer the darkest.
function pairs(spec, m, { fromZero = false } = {}) {
  need(Array.isArray(C.ordered) && C.ordered.length >= 2, 'color.ordered 長度不足：至少需要 2 色');
  need(Array.isArray(spec.periods) && spec.periods.length === 2, `${spec.kind} 需要兩個 periods`);
  need(Array.isArray(spec.rows) && spec.rows.length, `${spec.kind} 需要 rows`);
  m.periods = spec.periods;
  m.colors = [C.ordered[0], C.ordered.at(-1)];
  m.rows = [];
  for (const r of spec.rows) {
    need(typeof r.label === 'string' && Array.isArray(r.values) && r.values.length === 2 && r.values.every(numOrNull),
      `${spec.kind} 的資料格式不對：${JSON.stringify(r)}`);
    const gaps = r.values.flatMap((v, i) => (v === null ? [`${r.label} ${spec.periods[i]}`] : []));
    m.missing.push(...gaps);
    if (gaps.length === 2) continue;
    m.rows.push({
      label: r.label, values: r.values, texts: r.values.map(fmt(m)),
      delta: delta(r.values[0], r.values[1], { better: m.better, digits: m.digits }),
    });
  }
  const all = m.rows.flatMap((r) => r.values).filter(isNum);
  need(all.length, `${spec.kind} 沒有任何數值`);
  m.axis = niceTicks(Math.min(fromZero ? 0 : Infinity, ...all), Math.max(...all), 4);
  return m;
}

KINDS.slope = (spec, m) => pairs(spec, m);

KINDS.share = (spec, m, opts) => {
  need(Array.isArray(spec.categories) && spec.categories.length, `${spec.kind} 需要 categories`);
  need(Array.isArray(spec.rows) && spec.rows.length, `${spec.kind} 需要 rows`);
  const { colors, folded } = categoryColors(spec.categories, { order: opts.categoryOrder });
  if (folded.length) m.warnings.push(`超過 ${categoryLimit()} 類，「${folded.join('、')}」併入「其他」`);
  const ranked = [...(opts.categoryOrder ?? []), ...spec.categories];
  const kept = spec.categories.filter((c) => c !== OTHER && colors.has(c)).sort((a, b) => ranked.indexOf(a) - ranked.indexOf(b));
  if (!kept.length) m.warnings.push('所有類別都被併入「其他」，這張圖沒有資訊');
  m.categories = [...kept, ...(colors.has(OTHER) ? [OTHER] : [])].map((name) => ({ name, color: colors.get(name), other: name === OTHER }));
  m.rows = spec.rows.flatMap((r) => {
    need(typeof r.label === 'string' && Array.isArray(r.values) && r.values.length === spec.categories.length && r.values.every(numOrNull),
      `${spec.kind} 的資料格式不對：${JSON.stringify(r)}`);
    need(r.values.every((v) => v === null || v >= 0), `${spec.kind} 不能有負值：${r.label}`);
    const gaps = spec.categories.filter((c, i) => r.values[i] === null);
    if (gaps.length) {
      // A missing share makes the rest look like 100%; leave the row out and say why.
      m.missing.push(...gaps.map((c) => `${r.label} ${c}`));
      return [];
    }
    const sum = new Map();
    spec.categories.forEach((c, i) => {
      const v = r.values[i];
      const key = c !== OTHER && colors.has(c) ? c : OTHER;
      sum.set(key, (sum.get(key) ?? 0) + v);
    });
    const vals = m.categories.map((c) => sum.get(c.name) ?? 0);
    const total = vals.reduce((a, b) => a + b, 0);
    if (total === 0) m.warnings.push(`「${r.label}」各類都是 0，這一列沒有長條`);
    const sh = total === 0 ? vals.map(() => 0) : shares(vals);
    return [{
      label: r.label,
      segments: m.categories.map((c, i) => ({
        name: c.name, value: vals[i], share: sh[i], text: formatValue(sh[i] * 100, { digits: m.digits, suffix: '%' }),
        color: c.color, other: c.other, ink: c.other ? null : textOn(c.color),
      })),
    }];
  });
  need(m.rows.length, `${spec.kind} 沒有完整的一列可以畫`);
  return m;
};

KINDS.bridge = (spec, m) => {
  need(Array.isArray(spec.steps) && spec.steps.length >= 2, 'bridge 需要 steps（至少兩步）');
  let cum = 0, started = false;
  m.steps = [];
  for (const st of spec.steps) {
    need(typeof st.label === 'string' && numOrNull(st.value), `bridge 的資料格式不對：${JSON.stringify(st)}`);
    if (st.value === null) {
      m.missing.push(st.label);
      m.warnings.push(`「${st.label}」缺值，後面的累計可能不對`);
      continue;
    }
    let start, end;
    if (st.total) {
      if (started && !st.estimate && Math.abs(st.value - cum) > 1e-9 * Math.max(1, Math.abs(cum))) {
        m.warnings.push(`「${st.label}」是 ${fmt(m)(st.value)}，但前面累計是 ${fmt(m)(cum)}`);
      }
      [start, end, cum] = [0, st.value, st.value];
    } else {
      [start, end] = [cum, cum + st.value];
      cum = end;
    }
    started = true;
    const d = st.total ? null : delta(0, st.value, { better: m.better, digits: m.digits });
    m.steps.push({
      label: st.label, value: st.value, start, end, total: !!st.total, estimate: !!st.estimate,
      text: d ? d.text : fmt(m)(st.value),
      color: !d || d.color === C.unchanged ? C.gray : d.color,
      textColor: d ? d.color : C.text,
    });
  }
  const levels = m.steps.flatMap((s) => [s.start, s.end]);
  m.axis = niceTicks(Math.min(0, ...levels), Math.max(0, ...levels), 4);
  return m;
};

KINDS.histogram = (spec, m) => {
  need(Array.isArray(spec.bins) && spec.bins.length, 'histogram 需要 bins');
  spec.bins.forEach((b, i) => {
    need(isNum(b.from) && (b.to === null || isNum(b.to)) && numOrNull(b.value), `histogram 的資料格式不對：${JSON.stringify(b)}`);
    const next = spec.bins[i + 1];
    if (next && b.to !== next.from) m.warnings.push(`分組 ${b.from}–${b.to ?? ''} 和下一組沒有接上`);
  });
  const vals = spec.bins.map((b) => b.value).filter(isNum);
  need(vals.length, 'histogram 沒有任何數值');
  m.suffix = spec.suffix ?? '';
  const top = Math.max(...vals);
  const focus = spec.focus !== undefined ? spec.bins.findIndex((b) => b.from === spec.focus) : spec.bins.findIndex((b) => b.value === top);
  if (spec.focus !== undefined && focus < 0) m.warnings.push(`focus ${spec.focus} 不是任何一組的起點`);
  m.edgeDigits = decimalsOf(spec.bins.flatMap((b) => [b.from, b.to]));
  m.bins = spec.bins.map((b, i) => {
    if (b.value === null) m.missing.push(`${b.from}–${b.to ?? ''}`);
    return {
      from: b.from, to: b.to, value: b.value, text: formatValue(b.value, { digits: m.digits, suffix: m.suffix }),
      focus: i === focus, color: i === focus ? C.focus : C.gray,
    };
  });
  m.axis = niceTicks(0, top, 3);
  m.xLabel = spec.xLabel ?? null;
  m.refs = (spec.refs ?? []).map((r) => ({ x: r.x, label: r.label }));
  return m;
};

KINDS.strip = (spec, m) => {
  need(Array.isArray(spec.groups) && spec.groups.length, 'strip 需要 groups');
  m.groups = [];
  for (const g of spec.groups) {
    need(typeof g.label === 'string' && Array.isArray(g.values) && g.values.every(numOrNull), `strip 的資料格式不對：${g.label}`);
    const vals = g.values.filter(isNum);
    if (vals.length < g.values.length) m.missing.push(`${g.label} ${g.values.length - vals.length} 筆`);
    if (!vals.length) continue;
    const s = [...vals].sort((a, b) => a - b);
    const median = s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
    m.groups.push({ label: g.label, values: vals, median, medianText: fmt(m)(median), focus: g.label === spec.focus });
  }
  need(m.groups.length, 'strip 沒有任何數值');
  if (spec.focus && !m.groups.some((g) => g.focus)) m.warnings.push(`focus「${spec.focus}」不在資料裡`);
  const all = m.groups.flatMap((g) => g.values);
  m.axis = niceTicks(Math.min(0, ...all), Math.max(...all), 3);
  return m;
};

function points(spec, m) {
  need(Array.isArray(spec.points) && spec.points.length, `${spec.kind} 需要 points`);
  const out = [];
  for (const p of spec.points) {
    need(typeof p.label === 'string' && numOrNull(p.x) && numOrNull(p.y), `${spec.kind} 的資料格式不對：${JSON.stringify(p)}`);
    if (p.x === null || p.y === null) m.missing.push(p.label);
    else out.push({ label: p.label, x: p.x, y: p.y });
  }
  need(out.length, `${spec.kind} 沒有任何數值`);
  m.suffix = spec.suffix ?? '';
  m.xLabel = spec.xLabel ?? null;
  m.yLabel = spec.yLabel ?? null;
  return out;
}

KINDS.scatter = (spec, m) => {
  const pts = points(spec, m);
  m.refs = (spec.refs ?? []).map((r) => ({ x: r.x ?? null, y: r.y ?? null, label: r.label }));
  const xs = [...pts.map((p) => p.x), ...m.refs.map((r) => r.x).filter(isNum)];
  const ys = [...pts.map((p) => p.y), ...m.refs.map((r) => r.y).filter(isNum)];
  m.xAxis = niceTicks(Math.min(...xs), Math.max(...xs), 4);
  m.yAxis = niceTicks(Math.min(...ys), Math.max(...ys), 3);
  if (spec.focus && !pts.some((p) => p.label === spec.focus)) m.warnings.push(`focus「${spec.focus}」不在資料裡`);
  m.points = pts.map((p) => ({ ...p, focus: p.label === spec.focus, color: !spec.focus || p.label === spec.focus ? C.focus : C.gray }));
  return m;
};

const QUADRANTS = ['topLeft', 'topRight', 'bottomLeft', 'bottomRight'];

KINDS.matrix = (spec, m) => {
  const pts = points(spec, m);
  need(!spec.priority || QUADRANTS.includes(spec.priority), `matrix 的 priority 要是 ${QUADRANTS.join('／')}`);
  const axis = (vals, dom) => (dom ? { lo: dom[0], hi: dom[1], ticks: [dom[0], dom[1]], decimals: 0 } : niceTicks(Math.min(...vals), Math.max(...vals), 2));
  m.xAxis = axis(pts.map((p) => p.x), spec.domain);
  m.yAxis = axis(pts.map((p) => p.y), spec.domain);
  m.split = { x: spec.split?.x ?? (m.xAxis.lo + m.xAxis.hi) / 2, y: spec.split?.y ?? (m.yAxis.lo + m.yAxis.hi) / 2 };
  m.quadrants = spec.quadrants ?? null;
  m.priority = spec.priority ?? null;
  const quadrantOf = (p) => `${p.y >= m.split.y ? 'top' : 'bottom'}${p.x < m.split.x ? 'Left' : 'Right'}`;
  for (const p of pts) if (p.x === m.split.x || p.y === m.split.y) m.warnings.push(`「${p.label}」剛好在分割線上，請調整 split 或資料`);
  m.points = pts.map((p) => {
    const focus = m.priority ? quadrantOf(p) === m.priority : false;
    return { ...p, quadrant: quadrantOf(p), focus, color: !m.priority || focus ? C.focus : C.gray };
  });
  return m;
};

KINDS.dumbbell = (spec, m) => {
  pairs(spec, m, { fromZero: true });
  m.xLabel = spec.xLabel ?? m.unit;
  return m;
};

KINDS.funnel = (spec, m) => {
  need(Array.isArray(spec.steps) && spec.steps.length >= 2, 'funnel 需要 steps（至少兩步）');
  need(spec.loss === undefined || typeof spec.loss === 'boolean', 'funnel 的 loss 需要 true 或 false');
  m.steps = spec.steps.map((st, i) => {
    need(typeof st.label === 'string' && numOrNull(st.value) && !(st.value < 0), `funnel 的資料格式不對：${JSON.stringify(st)}`);
    if (st.value === null) m.missing.push(st.label);
    const prev = i > 0 ? spec.steps[i - 1].value : null;
    if (isNum(prev) && isNum(st.value) && st.value > prev) m.warnings.push(`「${st.label}」比上一步多，漏斗應該逐步變少`);
    const conversion = isNum(prev) && prev > 0 && isNum(st.value) ? st.value / prev : null;
    const loss = spec.loss && isNum(prev) && isNum(st.value) ? prev - st.value : null;
    return {
      label: st.label, value: st.value, text: fmt(m)(st.value), conversion,
      convText: conversion === null ? null : formatValue(conversion * 100, { suffix: '%' }),
      loss, lossText: loss === null ? null : `${loss < 0 ? tokens.delta.signs.increase : ''}${fmt(m)(-loss)}`,
    };
  });
  const vals = m.steps.map((s) => s.value).filter(isNum);
  need(vals.length, 'funnel 沒有任何數值');
  let focus = -1;
  const focuses = spec.focus === undefined ? null : Array.isArray(spec.focus) ? spec.focus : [spec.focus];
  need(focuses === null || focuses.every((name) => typeof name === 'string'), 'funnel 的 focus 需要名稱或名稱陣列');
  if (focuses) {
    for (const name of focuses) if (!m.steps.some((s) => s.label === name)) m.warnings.push(`focus「${name}」不在資料裡`);
  } else {
    m.steps.forEach((s, i) => { if (s.conversion !== null && (focus < 0 || s.conversion < m.steps[focus].conversion)) focus = i; });
  }
  m.steps.forEach((s, i) => {
    const highlighted = focuses ? focuses.includes(s.label) : i === focus;
    Object.assign(s, { focus: highlighted, color: highlighted ? C.focus : C.gray });
  });
  m.max = Math.max(...vals);
  if (m.max === 0) m.warnings.push('漏斗每一步都是 0');
  return m;
};

KINDS.heat = (spec, m) => {
  need(Array.isArray(spec.rowLabels) && Array.isArray(spec.colLabels) && Array.isArray(spec.values), 'heat 需要 rowLabels、colLabels、values');
  need(spec.values.length === spec.rowLabels.length
    && spec.values.every((r) => Array.isArray(r) && r.length === spec.colLabels.length && r.every(numOrNull)), 'heat 的 values 必須是列數 × 欄數的長方形');
  const flat = spec.values.flat().filter(isNum);
  need(flat.length, 'heat 沒有任何數值');
  const bins = heatBins(flat);
  const dg = decimalsOf(bins.edges);
  m.rowLabels = spec.rowLabels;
  m.colLabels = spec.colLabels;
  m.legendUnit = spec.legendUnit ?? null;
  m.legend = bins.edges.slice(0, -1).map((lo, i) => ({
    color: C.ordered[i], text: `${formatValue(lo, { digits: dg })}–${formatValue(bins.edges[i + 1], { digits: dg })}`,
  }));
  m.cells = spec.values.map((row, r) => row.map((v, c) => {
    if (v === null) return (m.missing.push(`${spec.rowLabels[r]} ${spec.colLabels[c]}`), null);
    const color = C.ordered[bins.binOf(v)];
    return { value: v, text: fmt(m)(v), color, ink: textOn(color) };
  }));
  return m;
};

// Cells carry text, alignment, color and fill so Phase 3 can map them one-to-one onto a native table.
KINDS.table = (spec, m) => {
  need(Array.isArray(spec.columns) && spec.columns.length, 'table 需要 columns');
  need(Array.isArray(spec.rows) && spec.rows.length, 'table 需要 rows');
  const isText = (j) => spec.rows.every((r) => !Array.isArray(r) || r[j] === null || typeof r[j] === 'string');
  const cols = spec.columns.map((c, j) => ({
    name: c.name, type: c.type ?? (isText(j) ? 'text' : 'number'), digits: c.digits ?? spec.digits, suffix: c.suffix ?? '', better: c.better ?? m.better,
  }));
  need(cols.every((c) => ['text', 'number', 'delta'].includes(c.type)), 'table 的欄位 type 只能是 text、number、delta');
  m.header = cols.map((c) => ({ text: c.name, align: c.type === 'text' ? 'start' : 'end' }));
  const cells = (row, name) => cols.map((c, j) => {
    const v = row[j];
    const align = c.type === 'text' ? 'start' : 'end';
    if (v === null || v === undefined) return (m.missing.push(`${name}／${c.name}`), { text: '未提供', align, value: null, color: C.text });
    if (c.type === 'text') return { text: String(v), align, value: v, color: C.text };
    need(isNum(v), `table 的「${name} ${c.name}」不是數字`);
    if (c.type === 'delta') {
      const d = delta(0, v, { better: c.better, digits: shownDigits(c.digits, v), suffix: c.suffix });
      return { text: d.text, align, value: v, color: d.color };
    }
    return { text: formatValue(v, { digits: shownDigits(c.digits, v), suffix: c.suffix }), align, value: v, color: C.text };
  });
  m.rows = spec.rows.map((r, i) => {
    need(Array.isArray(r) && r.length === cols.length, `table 每一列要有 ${cols.length} 格`);
    const emphasis = r[0] === spec.emphasis;
    return { cells: cells(r, r[0] == null ? `第 ${i + 1} 列` : String(r[0])), emphasis, total: false, fill: emphasis ? C.tint : null, bold: emphasis };
  });
  if (spec.total) {
    need(Array.isArray(spec.total) && spec.total.length === cols.length, `table 的 total 要有 ${cols.length} 格`);
    m.rows.push({ cells: cells(spec.total, spec.total[0] == null ? '總計' : String(spec.total[0])), emphasis: false, total: true, fill: null, bold: false });
  }
  if (spec.emphasis && !m.rows.some((r) => r.emphasis)) m.warnings.push(`emphasis「${spec.emphasis}」不在資料裡`);
  return m;
};

// One category position is retained for every input value, including null.
KINDS.grouped = (spec, m, opts) => {
  need(Array.isArray(spec.x) && spec.x.length && spec.x.every((x) => typeof x === 'string'), 'grouped 需要 x 類別名稱');
  need(Array.isArray(spec.series) && spec.series.length >= 2 && spec.series.length <= 4, 'grouped 需要 2～4 個 series');
  need(spec.seriesRole === undefined || ['ordered', 'categorical'].includes(spec.seriesRole), 'grouped 的 seriesRole 只能是 ordered 或 categorical');
  need(spec.series.every((s) => s && typeof s.name === 'string'), 'grouped 的每個系列都需要名稱');
  need(new Set(spec.series.map((s) => s.name)).size === spec.series.length, 'grouped 的系列名稱不可重複');
  m.seriesRole = spec.seriesRole ?? 'ordered';
  m.x = spec.x;
  const cats = m.seriesRole === 'categorical' ? categoryColors(spec.series.map((s) => s.name), { order: opts.categoryOrder }) : null;
  if (cats?.folded.length) m.warnings.push(`系列超過 ${categoryLimit()} 色，「${cats.folded.join('、')}」改用灰色`);
  m.series = spec.series.map((s, j) => {
    need(typeof s.name === 'string' && Array.isArray(s.values) && s.values.length === m.x.length && s.values.every(numOrNull), `grouped 的系列「${s.name}」長度或數值不對`);
    s.values.forEach((v, i) => { if (v === null) m.missing.push(`${s.name}／${m.x[i]}`); });
    const color = m.seriesRole === 'ordered'
      ? C.ordered[Math.round(j * (C.ordered.length - 1) / (spec.series.length - 1))]
      : cats.colors.get(s.name) ?? C.other;
    return { name: s.name, values: s.values, texts: s.values.map(fmt(m)), color };
  });
  const nums = m.series.flatMap((s) => s.values).filter(isNum);
  need(nums.length, 'grouped 沒有任何數值');
  m.rows = m.x.map((label, i) => ({ label, values: m.series.map((s) => s.values[i]), texts: m.series.map((s) => s.texts[i]) }));
  m.axis = niceTicks(Math.min(0, ...nums), Math.max(0, ...nums), 4);
  return m;
};

KINDS.sharetrend = (spec, m, opts) => {
  need(Array.isArray(spec.rows) && spec.rows.length >= 2, 'sharetrend 需要至少兩期 rows');
  need(Array.isArray(spec.categories) && spec.categories.length && spec.categories.every((c) => typeof c === 'string'), 'sharetrend 需要 categories 類別名稱');
  need(new Set(spec.categories).size === spec.categories.length, 'sharetrend 的類別名稱不可重複');
  need(spec.rows.every((r) => r && typeof r.label === 'string'), 'sharetrend 的每一期都需要名稱');
  KINDS.share(spec, m, opts);
  m.x = m.rows.map((r) => r.label);
  return m;
};

KINDS.combo = (spec, m) => {
  need(Array.isArray(spec.x) && spec.x.length >= 2 && spec.x.every((x) => typeof x === 'string'), 'combo 需要至少兩個 x 期間');
  need(Array.isArray(spec.amounts) && Array.isArray(spec.rates)
    && spec.amounts.length === spec.x.length && spec.rates.length === spec.x.length
    && spec.amounts.every(numOrNull) && spec.rates.every(numOrNull), 'combo 的 amounts、rates 長度或數值不對');
  m.x = spec.x;
  for (const [name, values, unit] of [['amount', spec.amounts, spec.amountUnit ?? m.unit], ['rate', spec.rates, spec.rateUnit ?? '%']]) {
    values.forEach((v, i) => { if (v === null) m.missing.push(`${m.x[i]}／${name === 'amount' ? '金額' : '比率'}`); });
    const nums = values.filter(isNum);
    need(nums.length, `combo 的${name === 'amount' ? '金額' : '比率'}沒有任何數值`);
    m[name] = { values, texts: values.map(fmt(m)), axis: niceTicks(Math.min(0, ...nums), Math.max(0, ...nums), 3), unit };
  }
  return m;
};

KINDS.bullet = (spec, m) => {
  need(Array.isArray(spec.rows) && spec.rows.length, 'bullet 需要 rows');
  m.rows = [];
  for (const r of spec.rows) {
    need(r && typeof r.label === 'string' && numOrNull(r.value) && numOrNull(r.target), `bullet 的資料格式不對：${JSON.stringify(r)}`);
    need(r.ranges === undefined || (Array.isArray(r.ranges) && r.ranges.length === 3
      && r.ranges.every(isNum) && r.ranges.every((v, i) => i === 0 || v >= r.ranges[i - 1])), `bullet「${r.label}」的 ranges 需要三個遞增界線`);
    if (r.value === null || r.target === null) {
      if (r.value === null) m.missing.push(`${r.label}／實際`);
      if (r.target === null) m.missing.push(`${r.label}／目標`);
      continue;
    }
    m.rows.push({ label: r.label, actual: r.value, target: r.target, actualText: fmt(m)(r.value), targetText: fmt(m)(r.target),
      delta: delta(r.target, r.value, { better: m.better, digits: m.digits }), ranges: r.ranges ?? null });
  }
  need(m.rows.length, 'bullet 沒有完整的一列可以畫');
  const nums = m.rows.flatMap((r) => [r.actual, r.target, ...(r.ranges ?? [])]);
  m.axis = niceTicks(Math.min(0, ...nums), Math.max(0, ...nums), 4);
  return m;
};

KINDS.waffle = (spec, m, opts) => {
  need(Array.isArray(spec.categories) && spec.categories.length && spec.categories.every((c) => typeof c === 'string'), 'waffle 需要 categories');
  need(new Set(spec.categories).size === spec.categories.length, 'waffle 的類別名稱不可重複');
  need(Array.isArray(spec.values) && spec.values.length === spec.categories.length && spec.values.every(numOrNull), 'waffle 的 values 長度或數值不對');
  need(spec.values.every((v) => v === null || v >= 0), 'waffle 不能有負值');
  spec.values.forEach((v, i) => { if (v === null) m.missing.push(spec.categories[i]); });
  m.categories = [];
  if (m.missing.length) {
    m.warnings.push('類別缺值，無法計算完整的 100 格');
    return m;
  }
  const { colors, folded } = categoryColors(spec.categories, { order: opts.categoryOrder });
  if (folded.length) m.warnings.push(`超過 ${categoryLimit()} 類，「${folded.join('、')}」併入「其他」`);
  const ranked = [...(opts.categoryOrder ?? []), ...spec.categories];
  const names = [...spec.categories.filter((c) => c !== OTHER && colors.has(c)).sort((a, b) => ranked.indexOf(a) - ranked.indexOf(b)), ...(colors.has(OTHER) ? [OTHER] : [])];
  const sums = new Map(names.map((name) => [name, 0]));
  spec.categories.forEach((name, i) => {
    const key = name !== OTHER && colors.has(name) ? name : OTHER;
    sums.set(key, sums.get(key) + spec.values[i]);
  });
  const values = names.map((name) => sums.get(name));
  const fractions = shares(values);
  const cells = fractions.map((v) => Math.floor(v * 100));
  const remainder = 100 - cells.reduce((a, b) => a + b, 0);
  [...fractions.keys()].sort((a, b) => (fractions[b] * 100 - cells[b]) - (fractions[a] * 100 - cells[a]) || a - b)
    .slice(0, remainder).forEach((i) => { cells[i] += 1; });
  m.categories = names.map((name, i) => ({ name, value: values[i], share: fractions[i], cells: cells[i],
    text: formatValue(fractions[i] * 100, { digits: m.digits, suffix: '%' }), color: colors.get(name), ink: textOn(colors.get(name)) }));
  return m;
};

KINDS.mekko = (spec, m, opts) => {
  need(Array.isArray(spec.categories) && spec.categories.length && spec.categories.every((c) => typeof c === 'string'), 'mekko 需要 categories');
  need(new Set(spec.categories).size === spec.categories.length, 'mekko 的類別名稱不可重複');
  need(Array.isArray(spec.rows) && spec.rows.length, 'mekko 需要 rows');
  const { colors, folded } = categoryColors(spec.categories, { order: opts.categoryOrder });
  if (folded.length) m.warnings.push(`超過 ${categoryLimit()} 類，「${folded.join('、')}」併入「其他」`);
  const ranked = [...(opts.categoryOrder ?? []), ...spec.categories];
  const names = [...spec.categories.filter((c) => c !== OTHER && colors.has(c)).sort((a, b) => ranked.indexOf(a) - ranked.indexOf(b)), ...(colors.has(OTHER) ? [OTHER] : [])];
  m.categories = names.map((name) => ({ name, color: colors.get(name) }));
  m.columns = [];
  for (const r of spec.rows) {
    need(r && typeof r.label === 'string' && Array.isArray(r.values) && r.values.length === spec.categories.length && r.values.every(numOrNull), `mekko「${r?.label ?? '未命名'}」的 values 長度或數值不對`);
    need(r.values.every((v) => v === null || v >= 0), `mekko「${r.label}」不能有負值`);
    const gaps = spec.categories.filter((_, i) => r.values[i] === null);
    if (gaps.length) { m.missing.push(...gaps.map((name) => `${r.label} ${name}`)); continue; }
    const sum = new Map(names.map((name) => [name, 0]));
    spec.categories.forEach((name, i) => {
      const key = name !== OTHER && colors.has(name) ? name : OTHER;
      sum.set(key, sum.get(key) + r.values[i]);
    });
    const total = r.values.reduce((a, b) => a + b, 0);
    if (total === 0) { m.warnings.push(`「${r.label}」總量為 0，無法畫欄寬`); continue; }
    m.columns.push({ label: r.label, total, totalText: fmt(m)(total), segments: names.map((name) => {
      const value = sum.get(name), share = value / total, color = colors.get(name);
      return { name, value, share, text: formatValue(share * 100, { digits: m.digits, suffix: '%' }), color, ink: textOn(color) };
    }) });
  }
  need(m.columns.length, 'mekko 沒有完整且總量大於 0 的欄位');
  const all = m.columns.reduce((a, c) => a + c.total, 0);
  m.columns.forEach((c) => { c.width = c.total / all; });
  return m;
};

KINDS.pareto = (spec, m) => {
  need(Array.isArray(spec.rows) && spec.rows.length, 'pareto 需要 rows');
  need(spec.threshold === undefined || (isNum(spec.threshold) && spec.threshold > 0 && spec.threshold <= 1), 'pareto 的 threshold 必須大於 0 且不超過 1');
  m.threshold = spec.threshold ?? 0.8;
  m.rows = spec.rows.flatMap((r) => {
    need(r && typeof r.label === 'string' && numOrNull(r.value) && !(r.value < 0), `pareto「${r?.label ?? '未命名'}」需要非負數值`);
    if (r.value === null) { m.missing.push(r.label); return []; }
    return [{ label: r.label, value: r.value, text: fmt(m)(r.value) }];
  }).sort((a, b) => b.value - a.value);
  const total = m.rows.reduce((a, r) => a + r.value, 0);
  need(total > 0, 'pareto 的數值總和必須大於 0');
  if (m.missing.length) m.warnings.push('部分原因缺值，累積占比只依已知數值計算');
  let sum = 0;
  m.crossing = -1;
  m.rows.forEach((r, i) => {
    sum += r.value;
    r.cumulative = sum / total;
    r.cumulativeText = `累積 ${formatValue(r.cumulative * 100, { digits: m.digits, suffix: '%' })}`;
    if (m.crossing < 0 && r.cumulative >= m.threshold) m.crossing = i;
  });
  m.rows.forEach((r, i) => { r.color = i <= m.crossing ? C.focus : C.gray; });
  m.thresholdText = formatValue(m.threshold * 100, { digits: m.digits, suffix: '%' });
  m.axis = niceTicks(0, m.rows[0].value, 4);
  return m;
};

KINDS.tornado = (spec, m) => {
  need(isNum(spec.baseline), 'tornado 需要數字 baseline');
  need(Array.isArray(spec.rows) && spec.rows.length, 'tornado 需要 rows');
  m.base = spec.baseline;
  m.rows = spec.rows.flatMap((r) => {
    need(r && typeof r.label === 'string' && numOrNull(r.low) && numOrNull(r.high), `tornado「${r?.label ?? '未命名'}」的 low、high 數值不對`);
    if (r.low === null || r.high === null) {
      if (r.low === null) m.missing.push(`${r.label}／低情境`);
      if (r.high === null) m.missing.push(`${r.label}／高情境`);
      return [];
    }
    const colorOf = (v, role) => spec.better === undefined ? (role === 'high' ? C.focus : C.gray)
      : v === m.base ? C.gray : (v > m.base) === (m.better !== 'lower') ? C.better : C.worse;
    return [{ label: r.label, low: r.low, high: r.high, lowText: fmt(m)(r.low), highText: fmt(m)(r.high),
      lowColor: colorOf(r.low, 'low'), highColor: colorOf(r.high, 'high'), impact: Math.abs(r.high - r.low) }];
  }).sort((a, b) => b.impact - a.impact);
  need(m.rows.length, 'tornado 沒有完整的一列可以畫');
  m.axis = niceTicks(Math.min(m.base, ...m.rows.flatMap((r) => [r.low, r.high])), Math.max(m.base, ...m.rows.flatMap((r) => [r.low, r.high])), 4);
  return m;
};

const median = (sorted) => !sorted.length ? null : sorted.length % 2 ? sorted[(sorted.length - 1) / 2]
  : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2;

KINDS.box = (spec, m) => {
  need(Array.isArray(spec.groups) && spec.groups.length, 'box 需要 groups');
  m.groups = [];
  for (const g of spec.groups) {
    need(g && typeof g.label === 'string' && ((Array.isArray(g.values) && g.values.every(numOrNull))
      || (Array.isArray(g.summary) && g.summary.length === 5 && g.summary.every(isNum))), `box「${g?.label ?? '未命名'}」需要 values 或五數 summary`);
    need(!(g.values && g.summary), `box「${g.label}」不能同時提供 values 與 summary`);
    let min, q1, mid, q3, max, outliers;
    if (g.values) {
      const vals = g.values.filter(isNum).sort((a, b) => a - b);
      if (vals.length !== g.values.length) m.missing.push(`${g.label} ${g.values.length - vals.length} 筆`);
      if (!vals.length) continue;
      if (vals.length < 5) m.warnings.push(`「${g.label}」觀察值少於 5 筆，四分位數不穩定`);
      mid = median(vals);
      const half = Math.floor(vals.length / 2);
      q1 = median(vals.slice(0, half)) ?? mid;
      q3 = median(vals.slice(vals.length - half)) ?? mid;
      const fenceLo = q1 - 1.5 * (q3 - q1), fenceHi = q3 + 1.5 * (q3 - q1);
      min = vals.find((v) => v >= fenceLo) ?? vals[0];
      max = vals.findLast((v) => v <= fenceHi) ?? vals.at(-1);
      outliers = vals.filter((v) => v < min || v > max);
    } else {
      [min, q1, mid, q3, max] = g.summary;
      need(min <= q1 && q1 <= mid && mid <= q3 && q3 <= max, `box「${g.label}」的 summary 必須由小到大`);
      need(g.outliers === undefined || (Array.isArray(g.outliers) && g.outliers.every(isNum)), `box「${g.label}」的 outliers 必須是數字陣列`);
      outliers = g.outliers ?? [];
    }
    m.groups.push({ label: g.label, min, q1, median: mid, q3, max, outliers,
      texts: [min, q1, mid, q3, max].map(fmt(m)), focus: g.label === spec.focus });
  }
  need(m.groups.length, 'box 沒有任何數值');
  if (spec.focus && !m.groups.some((g) => g.focus)) m.warnings.push(`focus「${spec.focus}」不在資料裡`);
  const nums = m.groups.flatMap((g) => [g.min, g.max, ...g.outliers]);
  m.axis = niceTicks(Math.min(...nums), Math.max(...nums), 4);
  return m;
};

KINDS.ordered = (spec, m) => {
  need(Array.isArray(spec.rows) && spec.rows.length, 'ordered 需要 rows');
  need(C.ordered.length >= 2, 'color.ordered 長度不足：至少需要 2 色');
  m.rows = spec.rows.flatMap((r, i) => {
    need(r && typeof r.label === 'string' && numOrNull(r.value), `ordered 的資料格式不對：${JSON.stringify(r)}`);
    need(r.value === null || r.value >= 0, `ordered「${r.label}」的數量不能是負值`);
    if (r.value === null) { m.missing.push(r.label); return []; }
    return [{ label: r.label, value: r.value, text: fmt(m)(r.value), focus: r.label === spec.focus,
      color: C.ordered[Math.round(i * (C.ordered.length - 1) / Math.max(1, spec.rows.length - 1))] }];
  });
  need(m.rows.length, 'ordered 沒有任何數值');
  if (spec.focus && !m.rows.some((r) => r.focus)) m.warnings.push(`focus「${spec.focus}」不在資料裡`);
  const nums = m.rows.map((r) => r.value);
  m.axis = niceTicks(Math.min(0, ...nums), Math.max(0, ...nums), 4);
  return m;
};

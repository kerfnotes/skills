// Skill identity. The brand comes from this skill's package.json, so every engine file stays identical across brands:
// environment variables are <ENV>_TOKENS, <ENV>_MODE and <ENV>_CHROME; the report style block is <style id="<slug>-theme">.
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
if (typeof pkg.brand !== 'string' || !/^[A-Za-z][A-Za-z0-9]*$/.test(pkg.brand)) {
  throw new Error('package.json 的 brand 必須是英文字母開頭、只含英數字的名稱');
}

export const BRAND = pkg.brand;
export const PACKAGE = pkg.name;
export const ENV = BRAND.toUpperCase();
export const SLUG = BRAND.toLowerCase();

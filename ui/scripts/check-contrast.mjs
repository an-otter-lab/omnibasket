// Feature 8: WCAG 2.x contrast ratios for the colour tokens in src/styles.css,
// light and dark. Body text needs 4.5:1, large text and UI parts 3:1.
// Run: node scripts/check-contrast.mjs  (exits 1 if a required pair fails).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'styles.css'), 'utf8');

function block(selector) {
  const i = css.indexOf(selector + '{');
  if (i < 0) throw new Error('no token block ' + selector);
  const body = css.slice(i + selector.length + 1, css.indexOf('}', i));
  const out = {};
  for (const m of body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2].toLowerCase();
  return out;
}

const themes = { light: block(':root'), dark: block(':root[data-theme=dark]') };

function lum(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function ratio(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

// [foreground, background, minimum, where it is used]
const PAIRS = [
  ['ink', 'surface', 4.5, 'body text'],
  ['ink', 'surface-2', 4.5, 'text in boxes, settings bar'],
  ['ink', 'surface-3', 4.5, 'text in panels and notes'],
  ['ink', 'kraft', 4.5, 'text in order boxes'],
  ['ink', 'good-bg', 4.5, 'text in the editions preview'],
  ['ink-2', 'surface', 4.5, 'soft paragraphs'],
  ['ink-soft', 'surface', 4.5, 'small secondary text (.s, .k)'],
  ['ink-soft', 'surface-2', 4.5, 'secondary text in boxes'],
  ['ink-soft', 'surface-3', 4.5, 'secondary text in panels'],
  ['ink-soft', 'surface-4', 4.5, 'tab sub-labels'],
  ['ink-soft', 'kraft', 4.5, 'secondary text in order boxes'],
  ['muted', 'surface', 4.5, 'muted text'],
  ['brand-ink', 'surface', 4.5, 'links, green totals'],
  ['brand-ink', 'surface-2', 4.5, 'links in boxes'],
  ['brand-ink', 'kraft', 4.5, 'green text in order boxes'],
  ['brand-ink', 'good-bg', 4.5, 'green label in editions preview, store hover'],
  ['brand-ink-hover', 'surface', 4.5, 'link hover'],
  ['on-brand', 'brand', 4.5, 'button and selected-tab text'],
  ['on-brand', 'brand-hover', 4.5, 'button hover text'],
  ['on-brand-soft', 'brand', 4.5, 'selected-tab sub-label'],
  ['warn', 'warn-bg', 4.5, '"not printed" badges'],
  ['warn', 'surface', 4.5, 'warning text, mismatch tag'],
  ['control', 'surface', 3, 'input, chip, toggle borders (UI)'],
  ['control', 'surface-2', 3, 'settings toggle border (UI)'],
  ['brand-ink', 'surface', 3, 'focus ring, selected order box border (UI)'],
  ['brand', 'surface', 3, 'switched-on toggle, meter fill (UI)'],
  ['ink', 'surface', 3, 'meter threshold mark (UI)'],
  ['kraft-ink', 'kraft', 3, 'cover icon (graphic)'],
];
// Shown for the record; WCAG exempts disabled controls.
const INFO = [
  ['muted', 'surface-4', 'disabled tab label'],
  ['ink-soft', 'disabled-bg', 'disabled button label'],
];

let failed = 0;
for (const [name, t] of Object.entries(themes)) {
  console.log(`\n${name}`);
  for (const [fg, bg, min, use] of PAIRS) {
    const r = ratio(t[fg], t[bg]);
    const ok = r >= min;
    if (!ok) failed++;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${r.toFixed(2).padStart(6)}:1 >= ${min}  --${fg} ${t[fg]} on --${bg} ${t[bg]}  (${use})`);
  }
  for (const [fg, bg, use] of INFO) {
    console.log(`info ${ratio(t[fg], t[bg]).toFixed(2).padStart(6)}:1        --${fg} ${t[fg]} on --${bg} ${t[bg]}  (${use}, exempt)`);
  }
}
if (failed) {
  console.error(`\n${failed} pair(s) below WCAG AA`);
  process.exit(1);
}
console.log('\nall required pairs meet WCAG AA');

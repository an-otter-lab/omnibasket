#!/usr/bin/env node
// Feature 9: check the web app manifest. No dependencies, no network.
// Usage: node scripts/check-manifest.mjs [dir]   (default: public; pass dist/ui/browser after a build)
// Checks: valid JSON, required fields, the index.html link and theme-color,
// and every icon exists with the declared type and pixel size.
import { readFileSync, existsSync } from 'node:fs';
import { join, resolve, dirname, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ui = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dir = resolve(ui, process.argv[2] || 'public');
const errors = [];
const fail = (msg) => errors.push(msg);

const REQUIRED = {
  name: 'Omnibasket',
  short_name: 'Omnibasket',
  start_url: '/',
  scope: '/',
  display: 'standalone',
};
const HEX = /^#[0-9a-f]{6}$/i;
const TYPES = { '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };

function pngSize(buf) {
  const sig = '89504e470d0a1a0a';
  if (buf.subarray(0, 8).toString('hex') !== sig || buf.subarray(12, 16).toString('latin1') !== 'IHDR') return null;
  return `${buf.readUInt32BE(16)}x${buf.readUInt32BE(20)}`;
}

const manifestPath = join(dir, 'manifest.webmanifest');
let manifest = null;
if (!existsSync(manifestPath)) fail(`missing ${manifestPath}`);
else {
  try {
    manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  } catch (err) {
    fail(`manifest is not valid JSON: ${err.message}`);
  }
}

if (manifest) {
  for (const [key, value] of Object.entries(REQUIRED)) {
    if (manifest[key] !== value) fail(`${key} must be ${JSON.stringify(value)}, got ${JSON.stringify(manifest[key])}`);
  }
  for (const key of ['theme_color', 'background_color']) {
    if (!HEX.test(manifest[key] || '')) fail(`${key} must be a #rrggbb colour`);
  }
  if (!Array.isArray(manifest.icons) || manifest.icons.length === 0) fail('icons must be a non-empty list');
  for (const icon of manifest.icons || []) {
    const label = `icon ${icon.src}`;
    if (!icon.src || /^[a-z]+:|^\/\//i.test(icon.src)) {
      fail(`${label}: src must be a local path`);
      continue;
    }
    const file = join(dir, icon.src.replace(/^\//, ''));
    if (!existsSync(file)) {
      fail(`${label}: file not found at ${file}`);
      continue;
    }
    const want = TYPES[extname(file).toLowerCase()];
    if (icon.type !== want) fail(`${label}: type ${icon.type} but the file is ${want}`);
    for (const p of String(icon.purpose || 'any').split(/\s+/)) {
      if (!['any', 'maskable', 'monochrome'].includes(p)) fail(`${label}: unknown purpose ${p}`);
    }
    const buf = readFileSync(file);
    if (want === 'image/png') {
      const size = pngSize(buf);
      if (!size) fail(`${label}: not a PNG`);
      else if (icon.sizes !== size) fail(`${label}: declares ${icon.sizes}, file is ${size}`);
    } else if (want === 'image/svg+xml') {
      if (!/<svg[\s>]/.test(buf.toString('utf8'))) fail(`${label}: not an SVG`);
      if (icon.sizes !== 'any') fail(`${label}: an SVG icon declares sizes "any"`);
    }
  }
}

const indexPath = existsSync(join(dir, 'index.html')) ? join(dir, 'index.html') : join(ui, 'src', 'index.html');
const html = readFileSync(indexPath, 'utf8');
if (!/<link rel="manifest" href="manifest\.webmanifest">/.test(html)) fail(`${indexPath}: no <link rel="manifest" href="manifest.webmanifest">`);
const theme = /<meta name="theme-color" content="(#[0-9a-f]{6})">/i.exec(html);
if (!theme) fail(`${indexPath}: no theme-color meta`);
else if (manifest && theme[1].toLowerCase() !== String(manifest.theme_color).toLowerCase()) {
  fail(`${indexPath}: theme-color ${theme[1]} differs from manifest ${manifest.theme_color}`);
}

if (errors.length) {
  console.error(`manifest check FAILED (${dir}):\n- ` + errors.join('\n- '));
  process.exit(1);
}
console.log(`manifest check OK (${dir}): ${manifest.icons.length} icons, index ${indexPath}`);

import fs from 'node:fs';
import path from 'node:path';

const source = process.argv[2];
const output = process.argv[3];

if (!source || !output) {
  throw new Error('Usage: node extract-wanted-reference.mjs <saved-landing.html> <output.js>');
}

const html = fs.readFileSync(source, 'utf8');
const figuresMatch = html.match(/const FIGS = (\[[^;]+\]);/);
const packedMatch = html.match(/const raw = atob\('([^']+)'\);/);

if (!figuresMatch || !packedMatch) {
  throw new Error('The saved Wanted landing page does not contain the expected particle payload.');
}

const figures = JSON.parse(figuresMatch[1]).map(({ pts, ...figure }) => figure);
const payload = `/* Generated from the user-provided saved Wanted landing page. */\nwindow.WANTED_HERO_REFERENCE=${JSON.stringify({ figures, packed: packedMatch[1] })};\n`;

fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, payload);
console.log(`Wrote ${output} (${payload.length.toLocaleString()} bytes, ${figures.reduce((sum, figure) => sum + figure.n, 0).toLocaleString()} source points)`);

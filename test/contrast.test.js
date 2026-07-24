/* WCAG contrast gate for the design tokens (#96).
 *
 * Parses the :root colour tokens out of public/css/styles.css and checks the
 * meaningful foreground/surface pairs the UI actually renders. Text tokens are
 * held to WCAG AA for normal text (>=4.5:1); accent colours that only ever
 * appear as large/bold chips, grade letters, direction arrows and other UI
 * glyphs are held to the AA large-text / non-text-UI bar (>=3:1). A regression
 * that dims a token below its bar fails CI — the same tripwire idea as the
 * Lighthouse budget, so a contrast slip can't ship silently.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const css = fs.readFileSync(path.join(__dirname, "..", "public", "css", "styles.css"), "utf8");

// ---- pull `--name: #hex;` tokens from the :root block ------------------------
const root = (css.match(/:root\s*\{([\s\S]*?)\n\}/) || [, ""])[1];
const tokens = {};
for (const m of root.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,8})\b/g)) tokens[m[1]] = m[2];

function rgb(hex) {
  let h = hex.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}
// WCAG relative luminance + contrast ratio.
function lum([r, g, b]) {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function ratio(fg, bg) {
  const a = lum(rgb(fg)), b = lum(rgb(bg));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const T = (name) => {
  const v = tokens[name];
  assert.ok(v, `token --${name} not found in :root`);
  return v;
};

// Surfaces text sits on (darkest first — the worst case for these tokens).
const SURFACES = ["bg", "panel", "panel-2"];

// (token, minimum, note). Text tokens -> 4.5; accent/UI glyph colours -> 3.0.
const TEXT = [
  ["text", 4.5], ["text-2", 4.5], ["muted", 4.5], ["muted-2", 4.5],
];
const UI = [
  ["green", 3.0], ["blue", 3.0], ["red", 3.0], ["orange", 3.0],
  ["teal", 3.0], ["purple", 3.0], ["grade-c", 3.0],
];

let passed = 0, worst = { r: Infinity };
const check = (name, min) => {
  for (const surf of SURFACES) {
    const r = ratio(T(name), T(surf));
    if (r < worst.r) worst = { r, pair: `${name} on ${surf}` };
    try {
      assert.ok(r >= min, `--${name} on --${surf} = ${r.toFixed(2)}:1 (needs >=${min}:1)`);
      passed++;
      console.log(`PASS  --${name} on --${surf}  ${r.toFixed(2)}:1  (>=${min})`);
    } catch (e) { console.error("FAIL  " + e.message); process.exitCode = 1; }
  }
};

console.log("Text tokens (AA normal text, >=4.5:1):");
for (const [n, min] of TEXT) check(n, min);
console.log("\nAccent / UI-glyph tokens (AA large-text / UI, >=3:1):");
for (const [n, min] of UI) check(n, min);

console.log(`\nTightest pair: ${worst.pair} at ${worst.r.toFixed(2)}:1`);
console.log(process.exitCode ? "SOME CONTRAST CHECKS FAILED" : `ALL ${passed} contrast checks passed`);

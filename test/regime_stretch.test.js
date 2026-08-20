#!/usr/bin/env node
/* Breadth-stretch readout (public/js/regime.js, batch-100 WS-E).
 *
 * The stretch line turns "67% above the 200-day" from a fact into a position
 * (vs its own mean, with a percentile). These tests slice the REAL
 * stretchHTML out of the shipped file and drive it with hand-computed
 * series — the percentile and mean must be exactly right, because the whole
 * point of the line is that the number can be trusted at a glance.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/regime.js"), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
}

function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `regime.js no longer contains "${startMarker}"`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

const ctx = vm.createContext({ console });
vm.runInContext(
  "const esc = (s) => String(s);\n"
  + "const pct = (v) => v == null ? \"—\" : Math.round(100 * v) + \"%\";\n"
  + slice("function stretchHTML(blk) {", "\n  }") + "\n"
  + "this.stretchHTML = stretchHTML;\n", ctx);
const { stretchHTML } = ctx;

// A 100-session series: 90 sessions at 0.50, 10 at 0.70; latest 0.70.
// mean = 0.52. MIDRANK percentile (ties count half): 0.70 -> (90+5)/100 = p95;
// 0.50 -> (0+45)/100 = p45 (a flat series must NOT read as stretched).
const series = Array(90).fill(0.5).concat(Array(10).fill(0.7));
const blk = (cur, s = series) => ({ above200: s, latest: { above200: cur } });

test("mean and percentile are computed exactly from the shipped series", () => {
  const h = stretchHTML(blk(0.7));
  assert.ok(h.includes("70%") && h.includes("52%"), h);
  assert.ok(h.includes("95th"), `midrank: (90 below + 10/2 equal)/100 -> 95th: ${h}`);
  assert.ok(h.includes("STRETCHED"), "90th+ percentile must say so");
  assert.ok(h.includes("is-hot"));
});

test("an ordinary reading says ordinary and carries no heat class", () => {
  const h = stretchHTML(blk(0.5));
  assert.ok(h.includes("45th"), `midrank keeps a flat tape ordinary: ${h}`);
  assert.ok(h.includes("ordinary"), h);
  assert.ok(!h.includes("is-hot"));
});

test("a washed-out reading is named too — the line is symmetric, not a bull alarm", () => {
  const h = stretchHTML(blk(0.3, Array(50).fill(0.5).concat(Array(50).fill(0.6), [0.3])));
  assert.ok(h.includes("washed out"), h);
});

test("silent below 40 sessions and without a current value — a fortnight is not a distribution", () => {
  assert.equal(stretchHTML(blk(0.5, Array(30).fill(0.5))), "");
  assert.equal(stretchHTML({ above200: series, latest: {} }), "");
  assert.equal(stretchHTML({}), "");
});

test("NaN/garbage sessions are filtered before any arithmetic", () => {
  const dirty = series.concat([NaN, null, "x"]);
  const h = stretchHTML(blk(0.7, dirty));
  assert.ok(h.includes("95th"), "the three junk values must not enter the percentile");
});

test("the panel and the strip both consume it", () => {
  assert.ok(SRC.includes("${stretchHTML(blk)}"), "panel column renders the stretch line");
  assert.ok(SRC.includes("rg-strip-pctl"), "the strip carries the percentile chip");
});

console.log(`\nregime_stretch.test.js: ${passed} passed, ${failed} failed`);
if (failed) process.exit(1);

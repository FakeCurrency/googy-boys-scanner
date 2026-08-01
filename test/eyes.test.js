#!/usr/bin/env node
/* Tests for the WHAT NEEDS MY EYES strip (owner-ruled 2026-08-01) —
 * eyesRank/eyesHTML in public/js/app.js.
 *
 * The owner's ask: dual/triple lens agreement, and any name that is both A+
 * and multi-lens, as the loudest thing on the deck. These tests pin the two
 * properties that make the strip trustworthy: the RANKING (triple beats dual,
 * A+ leads inside a tier — the order IS the message) and the honesty of what
 * it renders (counts, escaping, and silence when there is nothing to say).
 *
 * Slices the REAL functions out of the shipped file (house pattern — a
 * re-typed fixture drifts in step with the bug it is supposed to catch).
 * Run with: node test/eyes.test.js
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("eyes.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/app.js"), "utf8");

// Parser-walk extraction (the extractConst pattern): let new Function decide
// which terminator closes the definition rather than brace-matching by hand.
function sliceConst(name) {
  const at = SRC.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `app.js no longer defines "${name}" — was it renamed?`);
  const start = SRC.indexOf("=", at) + 1;
  for (let i = SRC.indexOf(";", start); i > 0 && i - start < 8000; i = SRC.indexOf(";", i + 1)) {
    const candidate = SRC.slice(start, i).trim();
    try { new Function(`return (${candidate});`); return `const ${name} = ${candidate};`; }
    catch (_) { /* unbalanced — keep walking */ }
  }
  assert.fail(`could not slice "${name}" out of app.js`);
}

const NAMES = ["esc", "eyesRank", "eyesHTML"];
const { eyesRank, eyesHTML } =
  new Function(NAMES.map(sliceConst).join("\n") + `\nreturn { ${NAMES.join(", ")} };`)();

const mk = (t, count, grade, side) => ({
  ticker: t, count, side: side || "long",
  lenses: count >= 3 ? ["VIVEK", "PHASEMAP", "SPECS"] : ["VIVEK", "PHASEMAP"],
  detail: grade ? { vivek: { grade, side: side || "long" } } : {},
});

// ── ranking — the order IS the message ───────────────────────────────────────
suite("ranking");

test("triple beats dual, and A+ leads inside each tier", () => {
  const rows = [
    mk("DUAL", 2, "A"), mk("DUALAP", 2, "A+"),
    mk("TRIP", 3, "B+"), mk("TRIPAP", 3, "A+"),
  ];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker),
    ["TRIPAP", "TRIP", "DUALAP", "DUAL"]);
});

test("a PhaseMap+Specs dual with no VIVEK grade ranks by count without throwing", () => {
  const noVivek = { ticker: "PMSP", count: 2, side: "long",
    lenses: ["PHASEMAP", "SPECS"], detail: { phasemap: {}, specs: {} } };
  const out = eyesRank([noVivek, mk("AP", 2, "A+")]);
  assert.deepEqual(out.map((x) => x.ticker), ["AP", "PMSP"]);
});

test("the caller's array is not reordered in place", () => {
  const rows = [mk("B", 2), mk("A", 3)];
  eyesRank(rows);
  assert.deepEqual(rows.map((x) => x.ticker), ["B", "A"]);
});

// ── what renders ─────────────────────────────────────────────────────────────
suite("rendering");

test("empty input renders nothing — the strip stays silent, never a husk", () => {
  assert.equal(eyesHTML([], "asx"), "");
  assert.equal(eyesHTML(null, "asx"), "");
});

test("the summary counts aligned, triples and A+ correctly", () => {
  const html = eyesHTML([mk("T", 3, "A+"), mk("D", 2, "A+"), mk("E", 2)], "asx");
  assert.ok(html.includes("3 aligned"), html);
  assert.ok(html.includes("1 triple"), html);
  assert.ok(html.includes("2 A+"), html);
});

test("a triple gets the beacon class and an A+ gets the tag", () => {
  const html = eyesHTML([mk("T", 3, "A+")], "asx");
  assert.ok(html.includes("ey-3"), html);
  assert.ok(html.includes("ey-ap"), html);
  assert.ok(html.includes("🎯"), html);
  assert.ok(html.includes(">A+<"), html);
});

test("chips link to the combined chart with the right market and direction", () => {
  const html = eyesHTML([mk("XRO", 2, "A+", "short")], "asx");
  assert.ok(html.includes("chart.html?m=asx&s=XRO&pm=1&dir=bearish"), html);
  assert.ok(html.includes("▼"), html);
});

test("the cap holds and the overflow is a filter control, not a dead label", () => {
  const rows = Array.from({ length: 11 }, (_, i) => mk("T" + i, 2));
  const html = eyesHTML(rows, "asx", 8);
  assert.equal((html.match(/ey-chip/g) || []).length, 8);
  assert.ok(html.includes("data-eyes-more"), html);
  assert.ok(html.includes("+3 more"), html);
});

test("a hostile ticker cannot break out of the markup", () => {
  const evil = mk(`"><img src=x onerror=alert(1)>`, 3, "A+");
  const html = eyesHTML([evil], "asx");
  assert.ok(!html.includes("<img"), html);
});

// ── wiring — a surface nobody sees is not a surface ──────────────────────────
suite("wiring");

const INDEX = fs.readFileSync(path.resolve(__dirname, "../public/index.html"), "utf8");

test("index.html hosts #eyes-strip inside the deck, above the pills", () => {
  const eyes = INDEX.indexOf('id="eyes-strip"');
  const pills = INDEX.indexOf('id="deck-pills"');
  assert.ok(eyes >= 0, "host missing");
  assert.ok(pills > eyes, "the strip must sit ABOVE the filter pills — do not bury it");
  assert.match(INDEX, /css\/eyes\.css\?v=\d+/, "eyes.css not linked/versioned");
});

test("renderEyes is hooked into BOTH the confluence load and the market-switch reset", () => {
  // One call paints it when lenses land; the other hides the stale strip the
  // moment the market changes — miss either and the strip lies about which
  // market it is describing (#79's lesson, one surface over).
  const hooks = (SRC.match(/renderEyes\(\)/g) || []).length;
  assert.ok(hooks >= 2, `expected >=2 renderEyes() call sites, found ${hooks}`);
  assert.ok(/state\.confl = null;\s*\n\s*renderEyes\(\)/.test(SRC),
    "the reset path no longer hides the strip");
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

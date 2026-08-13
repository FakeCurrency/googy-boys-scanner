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

// Function-declaration slicer (the fnSrc pattern): walk candidate closers
// and let the parser say which one ends the declaration.
function sliceFn(src, name, where) {
  const at = src.search(new RegExp(`\\bfunction\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `${where} no longer defines function "${name}"`);
  for (let i = src.indexOf("}", at); i > 0 && i - at < 8000; i = src.indexOf("}", i + 1)) {
    const candidate = src.slice(at, i + 1);
    try { new Function(`return (${candidate});`); return candidate; }
    catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice function "${name}" out of ${where}`);
}
function sliceConstFrom(src, name, where) {
  const at = src.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `${where} no longer defines "${name}"`);
  const start = src.indexOf("=", at) + 1;
  for (let i = src.indexOf(";", start); i > 0 && i - start < 8000; i = src.indexOf(";", i + 1)) {
    const candidate = src.slice(start, i).trim();
    try { new Function(`return (${candidate});`); return `const ${name} = ${candidate};`; }
    catch (_) { /* keep walking */ }
  }
  assert.fail(`could not slice "${name}" out of ${where}`);
}

// The strip's quality + fund reads come from PM (phasemap-shared.js). Build
// the sandbox's PM from the SHIPPED implementations, not a re-typed stub —
// this is what makes the NFLX word-boundary regression test test the fix.
const SHARED = fs.readFileSync(path.resolve(__dirname, "../public/js/phasemap-shared.js"), "utf8");
const PM_REAL = new Function(
  ["PM_STATE_RANK", "PM_TIER_RANK"].map((n) => sliceConstFrom(SHARED, n, "phasemap-shared.js")).join("\n") +
  "\n" + sliceFn(SHARED, "pmLegQuality", "phasemap-shared.js") +
  "\n" + ["FUND_SECTOR_HINTS", "NON_OP_SECTORS", "FUND_NAME_KW", "FUND_KW_RE"]
    .map((n) => sliceConstFrom(SHARED, n, "phasemap-shared.js")).join("\n") +
  "\n" + sliceFn(SHARED, "isFundReit", "phasemap-shared.js") +
  "\nreturn { pmLegQuality, isFundReit };")();

const NAMES = ["esc", "eyesRank", "eyesHTML"];
const { eyesRank, eyesHTML } =
  new Function("PM", NAMES.map(sliceConst).join("\n") + `\nreturn { ${NAMES.join(", ")} };`)(PM_REAL);
// A second sandbox with NO PM at all — the strip must degrade, never throw.
const bare = new Function("PM", NAMES.map(sliceConst).join("\n") + `\nreturn { eyesRank, eyesHTML };`)(undefined);

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

// ── PM-leg quality ranking + fund markers (owner fixes, 2026-08-01) ─────────
suite("quality ranking");

const mkq = (t, grade, state, tier, extra) => Object.assign(mk(t, 2, grade), {
  detail: {
    vivek: Object.assign({ grade, side: "long" }, extra || {}),
    phasemap: state ? { state, tier, side: "long" } : undefined,
  },
});

test("inside the A+ tier, a RUNNING/A+ leg outranks an alphabetically earlier SWEPT/Watch leg", () => {
  // The EVT-vs-COG case from the review: the alphabet used to decide this.
  const rows = [mkq("COG", "A+", "SWEPT", "Watch"), mkq("EVT", "A+", "RUNNING", "A+")];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["EVT", "COG"]);
});

test("state dominates tier, and tier breaks ties within a state", () => {
  const rows = [mkq("SWA", "A+", "SWEPT", "A+"), mkq("RUNW", "A+", "RUNNING", "Watch"),
    mkq("SWW", "A+", "SWEPT", "Watch"), mkq("DIS", "A+", "DISPLACED", "A")];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["RUNW", "DIS", "SWA", "SWW"]);
});

test("the key order is pinned: count, then A+, THEN leg quality, then alphabet", () => {
  // An A+ on the weakest leg still beats a non-A+ on the strongest leg, and
  // a triple on the weakest leg beats every dual — quality refines, it never
  // reorders the owner's established hierarchy.
  const rows = [mkq("STRONG", "A", "RUNNING", "A+"), mkq("WEAKAP", "A+", "SWEPT", "Watch")];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["WEAKAP", "STRONG"]);
  const trip = Object.assign(mk("TRIPW", 3, "B+"), { detail: { vivek: { grade: "B+" },
    phasemap: { state: "SWEPT", tier: "Watch" } } });
  assert.deepEqual(eyesRank([mkq("DUALSTR", "A+", "RUNNING", "A+"), trip]).map((x) => x.ticker),
    ["TRIPW", "DUALSTR"]);
});

test("equal quality still falls back to the alphabet, deterministically", () => {
  const rows = [mkq("ZZZ", "A+", "SWEPT", "Watch"), mkq("AAA", "A+", "SWEPT", "Watch")];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["AAA", "ZZZ"]);
});

test("without PM the strip degrades to the old order instead of throwing", () => {
  const rows = [mkq("COG", "A+", "SWEPT", "Watch"), mkq("EVT", "A+", "RUNNING", "A+")];
  assert.deepEqual(bare.eyesRank(rows).map((x) => x.ticker), ["COG", "EVT"]);
  assert.ok(bare.eyesHTML(rows, "asx").includes("ey-chip"));
});

test("the chip title states the PhaseMap leg it ranked on", () => {
  const html = eyesHTML([mkq("EVT", "A+", "RUNNING", "A+")], "asx");
  assert.ok(html.includes("PhaseMap RUNNING/A+"), html);
});

suite("fund markers");

test("a fund-named chip carries the marker and the dimming class", () => {
  const html = eyesHTML([mkq("CQE", "A+", "SWEPT", "Watch",
    { name: "Charter Hall Social Infrastructure REIT", sector: "Real Estate" })], "asx");
  assert.ok(html.includes("ey-fund"), html);
  assert.ok(html.includes(">FUND<"), html);
  assert.ok(html.includes("FUND / REIT-type name"), html);
});

test("NETFLIX is clean — the ETF keyword no longer matches inside words", () => {
  // The false positive the owner ordered fixed: includes() saw N-ETF-LIX.
  const html = eyesHTML([mkq("NFLX", "A+", "SWEPT", "Watch",
    { name: "Netflix, Inc. - Common Stock", sector: "Communication Services" })], "nasdaq");
  assert.ok(!html.includes("ey-fund"), html);
  assert.ok(!html.includes(">FUND<"), html);
  // ...while the real vehicles keep their flags through the same regex:
  assert.ok(PM_REAL.isFundReit({ name: "BETASHARES AUSTRALIA 200 ETF", ticker: "A200" }));
  assert.ok(PM_REAL.isFundReit({ name: "VanEck Global X Thing", ticker: "GX" }));
  assert.ok(!PM_REAL.isFundReit({ name: "Netflix, Inc. - Common Stock", ticker: "NFLX" }));
});

test("an operating company with no fund traits renders unmarked", () => {
  const html = eyesHTML([mkq("FMG", "A+", "SWEPT", "Watch",
    { name: "Fortescue Ltd", sector: "Materials" })], "asx");
  assert.ok(!html.includes("ey-fund"), html);
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
// ── product ranking penalty (owner-ordered 2026-08-13) ──────────────────────
// The chip already SAID fund. A marker the eye skips is not a ranking, so a
// bond ETF could still lead the strip that exists to answer "what needs my
// eyes". Products now sort below operating companies at equal lens count.
suite("products rank below real companies");

// Distinct from the file's `mk` above: this one carries name+sector, which is
// what PM.isFundReit reads. Product-ness lives in the NAME, never the ticker.
const mkp = (t, count, grade, name, sector) => ({
  ticker: t, count, side: "long",
  lenses: count >= 3 ? ["VIVEK", "PHASEMAP", "SPECS"] : ["VIVEK", "PHASEMAP"],
  detail: { vivek: { grade, name: name || (t + " Holdings Ltd"), sector: sector || "Materials" } },
});

test("at equal lens count, a real company outranks a product", () => {
  const out = eyesRank([
    mkp("AAA", 2, "A+", "Betashares Australian High Interest Cash ETF", "Unclassified"),
    mkp("FMG", 2, "A+", "Fortescue Ltd"),
  ]).map((x) => x.ticker);
  assert.deepStrictEqual(out, ["FMG", "AAA"],
    "a cash ETF is leading the strip over an operating company");
});

test("the penalty sits BELOW lens count — a triple product still beats a dual", () => {
  // The strip's premise is agreement between detectors. A triple IS a triple,
  // even when the name is a product; demoting it under count would make the
  // headline number ("1 triple") disagree with the order beneath it.
  const out = eyesRank([
    mkp("FMG", 2, "A+", "Fortescue Ltd"),
    mkp("VAS", 3, "A+", "Vanguard Australian Shares Index ETF", "Unclassified"),
  ]).map((x) => x.ticker);
  assert.deepStrictEqual(out, ["VAS", "FMG"]);
});

test("the penalty sits ABOVE grade — a real A outranks a product A+", () => {
  const out = eyesRank([
    mkp("GOVT", 2, "A+", "iShares Government Bond ETF", "Unclassified"),
    mkp("BHP", 2, "A", "BHP Group Limited"),
  ]).map((x) => x.ticker);
  assert.deepStrictEqual(out, ["BHP", "GOVT"]);
});

test("the A+ summary counts TRADEABLE A+ only", () => {
  const html = eyesHTML([
    mkp("AAA", 2, "A+", "Betashares Australian High Interest Cash ETF", "Unclassified"),
    mkp("FMG", 2, "A+", "Fortescue Ltd"),
  ], "asx");
  assert.ok(/1 A\+/.test(html), "the headline still counts the bond ETF as A+ opportunity");
  // …but BOTH chips still render — nothing is hidden, the product is marked.
  assert.strictEqual((html.match(/ey-chip/g) || []).length, 2);
  assert.ok(/ey-fund/.test(html), "the product lost its marker");
});

test("with no PM the penalty degrades to nothing, exactly like pmLegQuality", () => {
  // Same contract as the 2026-08-01 quality key: a missing PM must not throw
  // and must not silently reorder — it just stops penalising.
  const out = bare.eyesRank([
    mkp("AAA", 2, "A+", "Betashares Australian High Interest Cash ETF", "Unclassified"),
    mkp("FMG", 2, "A+", "Fortescue Ltd"),
  ]).map((x) => x.ticker);
  assert.deepStrictEqual(out, ["AAA", "FMG"], "alphabetical fallback, no throw");
});


console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

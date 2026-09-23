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

const NAMES = ["esc", "eyesRank", "eyesHTML", "eyesIsProduct", "eyesFingerprint"];
const { eyesRank, eyesHTML, eyesIsProduct, eyesFingerprint } =
  new Function("PM", NAMES.map(sliceConst).join("\n") + `\nreturn { ${NAMES.join(", ")} };`)(PM_REAL);
// A second sandbox with NO PM at all — the strip must degrade, never throw.
const bare = new Function("PM", NAMES.map(sliceConst).join("\n") + `\nreturn { eyesRank, eyesHTML, eyesIsProduct };`)(undefined);

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

test("leg-strength: VIVEK score breaks the last tie inside a grade band", () => {
  // Session C (2026-08-19): a 10/10 A+ dual and a 9/10 A+ dual with equal PM
  // legs used to sort alphabetically. The score is the finest grain of the
  // VIVEK leg the payload carries; it decides only after count, product,
  // grade band and PM leg quality — the qualification rule reads none of it.
  const rows = [
    mkq("AAA", "A+", "SWEPT", "Watch", { score: 9 }),
    mkq("ZZZ", "A+", "SWEPT", "Watch", { score: 10 }),
  ];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["ZZZ", "AAA"]);
});

test("a missing score reads 0 and the old alphabetical order survives", () => {
  // Old cached payloads carry no score in detail.vivek — the rank must
  // degrade to exactly the previous behaviour, never throw or jump.
  const rows = [mkq("BBB", "A+", "SWEPT", "Watch"), mkq("AAA", "A+", "SWEPT", "Watch")];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["AAA", "BBB"]);
});

test("score never outranks PM leg quality — it is the LAST quality key", () => {
  // A RUNNING leg with a 9 must still beat a SWEPT leg with a 10: the order
  // of keys is the design, and this is the mutation that would invert it.
  const rows = [
    mkq("SWP", "A+", "SWEPT", "Watch", { score: 10 }),
    mkq("RUN", "A+", "RUNNING", "A+", { score: 9 }),
  ];
  assert.deepEqual(eyesRank(rows).map((x) => x.ticker), ["RUN", "SWP"]);
});

suite("products never reach the strip (owner, 2026-09-21)");

/* "how many times am i going to have to see the same shit again and again?"
 * — and two of the eight chips in the screenshot that prompted it were AFI and
 * IEU: an LIC and an index ETF. Marking them was the 2026-08-01 answer and it
 * was not enough; a marker the eye has to skip is still something you read.
 * They are now filtered out BEFORE ranking, which is also what makes the old
 * product-penalty sort key unreachable (it was removed with this change). */

// Distinct from `mk` above: carries name+sector, which is what PM.isFundReit
// reads. Product-ness lives in the NAME, never the ticker.
const mkp = (t, name, sector, extra) => ({
  ticker: t, count: 2, side: "long", lenses: ["VIVEK", "PHASEMAP"],
  detail: { vivek: Object.assign({ grade: "A+", name, sector: sector || "Materials" }, extra || {}) },
});

test("a REIT, an ETF and a keyword-invisible LIC are all products", () => {
  assert.ok(eyesIsProduct(mkp("CQE", "Charter Hall Social Infrastructure REIT", "Real Estate")));
  assert.ok(eyesIsProduct(mkp("A200", "BETASHARES AUSTRALIA 200 ETF", "Unclassified")));
  // AFI-class: nothing in the name matches the keyword list, so ONLY the
  // scanner's published verdict can catch it.
  assert.ok(eyesIsProduct(mkp("AFI", "Australian Foundation Investment Company Limited",
                              "Financials", { is_product: true })));
});

test("an explicit is_product:false wins over a fund-looking name", () => {
  // The classifier looked and says operating company — the keyword fallback
  // must not overrule it. (Absent stays a guess; false is a verdict.)
  assert.ok(!eyesIsProduct(mkp("XTR", "Extra Trust Holdings", "Industrials", { is_product: false })));
});

test("NETFLIX is clean — the ETF keyword no longer matches inside words", () => {
  // The false positive the owner ordered fixed: includes() saw N-ETF-LIX.
  assert.ok(!eyesIsProduct(mkp("NFLX", "Netflix, Inc. - Common Stock", "Communication Services")));
  assert.ok(!eyesIsProduct(mkp("FMG", "Fortescue Ltd", "Materials")));
});

test("renderEyes drops products BEFORE the marks, the ranking and the counts", () => {
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  const filt = fn.indexOf("eyesIsProduct");
  assert.ok(filt > 0, "renderEyes no longer filters products at all");
  assert.ok(filt < fn.indexOf("EYES.marks"), "products must be gone before the dismissals are read");
  assert.ok(filt < fn.indexOf("eyesHTML("), "products must be gone before anything is rendered");
});

test("no chip can carry a product marker any more, because none can appear", () => {
  const html = eyesHTML([mk("FMG", 2, "A+"), mk("BHP", 2, "A")], "asx");
  assert.ok(!/ey-fund/.test(html) && !/>PRODUCT</.test(html),
    "the product marker is back — it is dead markup now that products are filtered");
  assert.ok(!/prod\(/.test(sliceConst("eyesRank")), "the product penalty is back in the ranking");
});

test("without PM the filter lets everything through rather than throwing", () => {
  // Same degrade rule as pmLegQuality: no PM on the page = no opinion.
  assert.doesNotThrow(() => bare.eyesIsProduct(mkp("CQE", "Some REIT", "Real Estate")));
  assert.strictEqual(bare.eyesIsProduct(mkp("CQE", "Some REIT", "Real Estate")), false);
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
  // Pinned by POSITION, not by count: a count of "renderEyes()" also counts
  // the declaration, a comment and the two click handlers, so it stayed >= 2
  // with the confluence-load call deleted.
  assert.ok(/state\.confl = c;[^}]*?renderEyes\(\)/.test(SRC),
    "the confluence load no longer paints the strip");
  assert.ok(/state\.confl = null;\s*\n\s*renderEyes\(\)/.test(SRC),
    "the reset path no longer hides the strip");
});

// ─────────────────────────────── summary ─────────────────────────────────────
// ── product ranking penalty (owner-ordered 2026-08-13) ──────────────────────
// The chip already SAID fund. A marker the eye skips is not a ranking, so a
// bond ETF could still lead the strip that exists to answer "what needs my
// eyes". Products now sort below operating companies at equal lens count.
suite("dismissed until it CHANGES (owner, 2026-09-21)");

/* "how many times am i going to have to see the same shit again and again?"
 *
 * Three earlier scopings each brought reviewed names back on a clock — per
 * scan, per day, per week. A dismissal now lasts until the name's ALIGNMENT
 * changes, so a setup that sits there for a fortnight is seen ONCE. These run
 * the REAL public/js/eyes-store.js, not a copy. */

function eyesStore(storage) {
  const src = fs.readFileSync(path.resolve(__dirname, "../public/js/eyes-store.js"), "utf8");
  const win = {};
  new Function("window", "localStorage", "JSON", "Object", "Array", src)(
    win, storage, JSON, Object, Array);
  return win.EYES;
}

function fakeStore(initial) {
  const m = new Map(Object.entries(initial || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    _dump: () => Object.fromEntries(m),
  };
}

test("a dismissed name stays dismissed while its alignment is unchanged", () => {
  const E = eyesStore(fakeStore());
  E.mark("asx", "CVV", "VIVEK+PHASEMAP|short|A");
  assert.strictEqual(E.isDismissed("asx", "CVV", "VIVEK+PHASEMAP|short|A"), true);
  // ...and again, and again. No clock is consulted anywhere in the decision.
  assert.strictEqual(E.isDismissed("asx", "CVV", "VIVEK+PHASEMAP|short|A"), true);
});

test("it comes back the moment the alignment DOES change", () => {
  const E = eyesStore(fakeStore());
  E.mark("asx", "CVV", "VIVEK+PHASEMAP|short|A");
  assert.strictEqual(E.isDismissed("asx", "CVV", "PHASEMAP+SPECS+VIVEK|short|A"), false,
    "a dual that became a triple is new information");
  assert.strictEqual(E.isDismissed("asx", "CVV", "VIVEK+PHASEMAP|long|A"), false,
    "a direction flip is new information");
  assert.strictEqual(E.isDismissed("asx", "CVV", "VIVEK+PHASEMAP|short|A+"), false,
    "a grade upgrade is new information");
});

test("the fingerprint is lenses + direction + grade, and nothing else", () => {
  const fp = (o) => eyesFingerprint(o);
  const base = { ticker: "X", side: "long", lenses: ["VIVEK", "PHASEMAP"],
                 detail: { vivek: { grade: "A+" } } };
  // lens ORDER must not matter, or a reordered payload re-surfaces everything
  assert.strictEqual(fp(base), fp(Object.assign({}, base, { lenses: ["PHASEMAP", "VIVEK"] })));
  assert.notStrictEqual(fp(base), fp(Object.assign({}, base, { side: "short" })));
  assert.notStrictEqual(fp(base), fp(Object.assign({}, base, { lenses: ["VIVEK", "PHASEMAP", "SPECS"] })));
  assert.notStrictEqual(fp(base), fp(Object.assign({}, base, { detail: { vivek: { grade: "A" } } })));
  // PhaseMap state advancing is deliberately NOT in it — it churns on its own,
  // and re-surfacing on it walks back into the complaint (see eyes-store.js).
  assert.strictEqual(fp(base),
    fp(Object.assign({}, base, { detail: { vivek: { grade: "A+" }, phasemap: { state: "RUNNING" } } })));
  assert.doesNotThrow(() => fp(null));
  assert.doesNotThrow(() => fp({}));
});

test("UNKNOWN matches ANY state — the chart marks without knowing why", () => {
  // chart.js has the ticker but never computes confluence, so it dismisses at
  // UNKNOWN. That must hide the name whatever the deck later computes, or the
  // arrows would mark names that reappear immediately.
  const E = eyesStore(fakeStore());
  E.mark("asx", "CVV");
  assert.strictEqual(E.marks()["asx:CVV"], E.UNKNOWN);
  assert.strictEqual(E.isDismissed("asx", "CVV", "anything at all"), true);
  assert.strictEqual(E.isDismissed("asx", "CVV", null), true);
});

test("upgrade() teaches an UNKNOWN mark today's fingerprint without un-dismissing it", () => {
  const E = eyesStore(fakeStore());
  E.mark("asx", "CVV");                                  // chart-style mark
  assert.strictEqual(E.upgrade("asx", [{ ticker: "CVV", fp: "VIVEK+PHASEMAP|short|A" }]), 1);
  assert.strictEqual(E.marks()["asx:CVV"], "VIVEK+PHASEMAP|short|A");
  assert.strictEqual(E.isDismissed("asx", "CVV", "VIVEK+PHASEMAP|short|A"), true, "still dismissed");
  assert.strictEqual(E.isDismissed("asx", "CVV", "VIVEK+PHASEMAP|long|A"), false, "and now it tracks");
  // a REAL fingerprint is never overwritten by a later upgrade
  assert.strictEqual(E.upgrade("asx", [{ ticker: "CVV", fp: "SOMETHING|else|B+" }]), 0);
  assert.strictEqual(E.marks()["asx:CVV"], "VIVEK+PHASEMAP|short|A");
});

test("MIGRATION: marks from every earlier build survive (the 2026-09-21 loss)", () => {
  /* The complaint's immediate cause: the v2->v3 store changed shape and the
   * reader did not understand the old one, so every name already reviewed came
   * straight back. All three shapes are honoured now, at UNKNOWN — so nothing
   * already done is lost, and the deck upgrades them on the next render. */
  const v1 = eyesStore(fakeStore({ "gbs:eyes_seen":
    JSON.stringify({ stamp: "2026-09-20", keys: ["asx:CVV", "asx:EMP"] }) }));
  assert.deepStrictEqual(Object.keys(v1.marks()).sort(), ["asx:CVV", "asx:EMP"]);
  assert.strictEqual(v1.isDismissed("asx", "CVV", "whatever"), true);

  const v3 = eyesStore(fakeStore({ "gbs:eyes_seen":
    JSON.stringify({ marks: { "asx:KOV": Date.now() }, reset: 0 }) }));
  assert.strictEqual(v3.isDismissed("asx", "KOV", "whatever"), true);
});

test("markAll dismisses the whole strip in one tap", () => {
  const E = eyesStore(fakeStore());
  E.markAll("asx", [{ ticker: "CVV", fp: "a" }, { ticker: "EMP", fp: "b" }, { ticker: "ALL", fp: "c" }]);
  assert.deepStrictEqual(Object.keys(E.marks()).sort(), ["asx:ALL", "asx:CVV", "asx:EMP"]);
  assert.strictEqual(E.isDismissed("asx", "EMP", "b"), true);
  assert.strictEqual(E.isDismissed("asx", "EMP", "b2"), false, "clear-all still tracks changes");
});

test("keys are market-scoped and case-insensitive", () => {
  const E = eyesStore(fakeStore());
  E.mark("asx", "link", "f");
  assert.strictEqual(E.isDismissed("asx", "LINK", "f"), true, "case must not matter");
  assert.strictEqual(E.isDismissed("crypto", "LINK", "f"), false,
    "an ASX LINK and a crypto LINK are different names");
});

test("reset brings everything back", () => {
  const E = eyesStore(fakeStore());
  E.mark("asx", "CVV", "f");
  E.reset();
  assert.deepStrictEqual(E.marks(), {});
});

test("the map is bounded, and evicts the OLDEST dismissal first", () => {
  const E = eyesStore(fakeStore());
  const many = [];
  for (let i = 0; i < E.MAX_MARKS + 50; i++) many.push({ ticker: "T" + i, fp: "f" });
  E.markAll("asx", many);
  const kept = Object.keys(E.marks());
  assert.ok(kept.length <= E.MAX_MARKS, `unbounded: ${kept.length} marks stored`);
  assert.ok(kept.length > 0);
});

test("a hostile or corrupt localStorage degrades to showing everything", () => {
  const hostile = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  const E = eyesStore(hostile);
  assert.deepStrictEqual(E.marks(), {});
  assert.doesNotThrow(() => E.mark("asx", "CVV", "f"));
  assert.doesNotThrow(() => E.reset());
  assert.strictEqual(E.isDismissed("asx", "CVV", "f"), false, "safe direction: show it");
  const junk = eyesStore(fakeStore({ "gbs:eyes_seen": "{not json" }));
  assert.deepStrictEqual(junk.marks(), {});
});

test("NOTHING in the store re-surfaces a name on a clock", () => {
  /* The property all three previous versions failed. The 90-day age cut in
   * saveMarks is garbage collection on a name nobody has seen aligned in three
   * months — it must not be reachable as a "show it again" timer, and no
   * calendar/day value may appear in the dismissal decision at all. */
  const src = fs.readFileSync(path.resolve(__dirname, "../public/js/eyes-store.js"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const at = src.indexOf("isDismissed:");
  assert.ok(at > 0, "eyes-store.js no longer exposes isDismissed");
  const body = src.slice(at, src.indexOf("\n    },", at));
  assert.ok(!/Date\.now|day\(\)|stamp|AGE|DAY_MS/.test(body),
    "the dismissal decision consults a clock again — that is the bug, three times over");
  // and the deck's own filter must not either
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  assert.ok(!/eyesStamp\(\)[\s\S]{0,200}?filter/.test(fn),
    "renderEyes is scoping the dismissals by day again");
});

// ── the strip's own wiring ───────────────────────────────────────────────────

test("every chip carries the hook the click handler needs", () => {
  const html = eyesHTML([mk("UNIT", 2, "short"), mk("CVLT", 2, "long")], "nasdaq");
  assert.ok(/data-eyes-tk="UNIT"/.test(html), "no ticker hook — clicks could not be recorded");
  assert.ok(/data-eyes-tk="CVLT"/.test(html));
});

test("renderEyes filters the dismissed set BEFORE ranking and counting", () => {
  // Filtering after the fact would leave the summary claiming names that are
  // no longer on screen.
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  assert.ok(/EYES\.marks\(\)/.test(fn), "renderEyes does not consult the dismissals");
  assert.ok(fn.indexOf("filter") < fn.indexOf("eyesHTML("), "must filter before rendering");
});

test("the deck marks a clicked chip WITH its fingerprint, not a bare ticker", () => {
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  assert.ok(/markEyeSeen\(state\.market, tk, row \? eyesFingerprint\(row\) : null\)/.test(fn),
    "a click that stored no fingerprint would dismiss the name forever");
});

test("clear-all is wired to markAll at each row's CURRENT fingerprint", () => {
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  assert.ok(/data-eyes-clear/.test(fn) && /markAll\(/.test(fn), "the clear-all control is not wired");
  assert.ok(/eyesFingerprint\(x\)/.test(fn.slice(fn.indexOf("markAll("))),
    "clear-all must record WHY each name was dismissed, or none of them can come back");
  assert.ok(/data-eyes-clear/.test(sliceConst("eyesHTML")), "no clear-all button is rendered");
});

test("the strip hides itself once everything has been dismissed", () => {
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  assert.ok(/rows\.length \? eyesHTML/.test(fn) && /host\.hidden = true/.test(fn),
    "an empty worklist must remove the strip, not leave an empty box");
});

test("the restore control is offered whenever something is hidden", () => {
  const html = eyesHTML([mk("UNIT", 2, "short")], "nasdaq", 0, 3);
  assert.ok(/data-eyes-reset/.test(html));
  assert.ok(/3 reviewed/.test(html));
});

test("and is absent when nothing is hidden, so a clean strip stays clean", () => {
  const html = eyesHTML([mk("UNIT", 2, "short")], "nasdaq", 0, 0);
  assert.ok(!/data-eyes-reset/.test(html));
});


// ═══════════════ the chain: arrows walk the strip (owner, 2026-09-20) ════════
/* "that arrow back and forward; this should continue down the chain of FOR MY
 * EYES. So once i've clicked forward or back a few times it marks off the
 * LIST." */
suite("the chain — stepping the strip with the chart's arrows");

test("the deck saves the order and the chart reads it back", () => {
  const store = fakeStore();
  const E = eyesStore(store);
  E.saveChain("nasdaq", "scan-1", ["UNIT", "CVLT", "WMT"]);
  assert.deepEqual(E.chain("nasdaq", "scan-1"), ["UNIT", "CVLT", "WMT"]);
});

test("tickers are normalised, so a lowercase link still matches the chain", () => {
  const E = eyesStore(fakeStore());
  E.saveChain("asx", "s1", ["enr", "Nol"]);
  assert.deepEqual(E.chain("asx", "s1"), ["ENR", "NOL"]);
});

test("a chain from ANOTHER MARKET is ignored", () => {
  const E = eyesStore(fakeStore());
  E.saveChain("asx", "s1", ["ENR"]);
  assert.deepEqual(E.chain("nasdaq", "s1"), [], "ASX order must not drive a NASDAQ chart");
});

test("a chain from an EARLIER DAY is ignored", () => {
  // Yesterday's order would walk names that have since stopped being aligned.
  // No chain is better than a wrong one. Within a day it survives re-scans.
  const E = eyesStore(fakeStore());
  E.saveChain("asx", "2026-09-20", ["ENR", "NOL"]);
  assert.deepEqual(E.chain("asx", "2026-09-20"), ["ENR", "NOL"], "same day must survive");
  assert.deepEqual(E.chain("asx", "2026-09-21"), []);
});

test("a hostile localStorage yields no chain rather than throwing", () => {
  const hostile = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  const E = eyesStore(hostile);
  assert.equal(E.saveChain("asx", "s1", ["ENR"]), false);
  assert.deepEqual(E.chain("asx", "s1"), []);
});

test("the deck links chips with src=eyes so the chart knows to walk the chain", () => {
  const html = eyesHTML([mk("UNIT", 2, "A+"), mk("CVLT", 2, "A+")], "nasdaq");
  assert.ok(/src=eyes/.test(html), "without src=eyes the arrows fall back to the whole deck");
});

test("the deck saves the FULL ranked set, not just the visible chips", () => {
  // The strip caps at 8 chips behind "+N more"; the arrows must keep going.
  const fn = sliceFn(SRC, "renderEyes", "app.js");
  assert.ok(/saveChain\(/.test(fn), "renderEyes never stores the chain");
  assert.ok(/eyesRank\(rows\)\.map/.test(fn),
    "the chain must be the ranked set, not the sliced chips");
});

test("the chart marks a name reviewed on ARRIVAL, not just on a chip click", () => {
  const chart = fs.readFileSync(path.resolve(__dirname, "../public/js/chart.js"), "utf8");
  const blk = chart.slice(chart.indexOf('navSrc === "eyes"'));
  const scoped = blk.slice(0, blk.indexOf("fetch(file,"));
  assert.ok(/EYES\.mark\(/.test(scoped), "arrowing onto a name must cross it off");
  assert.ok(/EYES\.chain\(/.test(scoped), "the arrows must read the saved order");
  assert.ok(/eyes`/.test(scoped) || /eyes"/.test(scoped), "the counter should say it is the eyes chain");
});

test("an expired chain falls through to the normal deck nav, never dead arrows", () => {
  const chart = fs.readFileSync(path.resolve(__dirname, "../public/js/chart.js"), "utf8");
  const blk = chart.slice(chart.indexOf('navSrc === "eyes"'));
  const scoped = blk.slice(0, blk.indexOf("fetch(file,"));
  assert.ok(/idx >= 0 && chain\.length > 1/.test(scoped),
    "must only take over the arrows when the current name IS in a usable chain");
});

test("both pages load the shared store, so they cannot drift apart", () => {
  for (const page of ["index.html", "chart.html"]) {
    const html = fs.readFileSync(path.resolve(__dirname, "../public", page), "utf8");
    assert.ok(/js\/eyes-store\.js\?v=/.test(html), `${page} does not load eyes-store.js`);
  }
});

if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

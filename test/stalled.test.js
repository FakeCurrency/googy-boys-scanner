#!/usr/bin/env node
/* Tests for public/js/stalled.js — the stalled-position decision surface.
 *
 * The surface exists to show, read-only, exactly the cohort the stale probe
 * (scanner/broker/vivek_run._stale_probe) has already stamped `stale_pinged`.
 * These tests pin the three things that matter:
 *
 *   1. The cohort is the ENGINE's, not this file's — a row is listed iff it is
 *      open and carries the stamp. No threshold lives here.
 *   2. The numbers are honest: day arithmetic in the book's own calendar,
 *      summary R/dollars/slots from the rows and rules as published.
 *   3. It is read-only BY SOURCE: no POST, no dispatch, no store writes.
 *
 * Runs the REAL functions, sliced out of the shipped file at load time rather
 * than re-typed here (house pattern — a mirrored copy drifts in step with the
 * bug it is supposed to catch). Run with: node test/stalled.test.js
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("stalled.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ── pull the real functions out of the shipped file ──────────────────────────
const SRC_PATH = path.resolve(__dirname, "../public/js/stalled.js");
const SRC = fs.readFileSync(SRC_PATH, "utf8");

// Ask the PARSER where each definition ends rather than matching an end
// marker: an arrow body full of `return {...};` has many plausible `;`
// terminators, and only the parser knows which one closes the expression
// (the house pattern from test/escaping.test.js's extractConst).
function sliceConst(name) {
  const at = SRC.search(new RegExp(`\\bconst\\s+${name}\\s*=`));
  assert.ok(at >= 0, `stalled.js no longer defines "${name}" — was it renamed?`);
  const start = SRC.indexOf("=", at) + 1;
  for (let i = SRC.indexOf(";", start); i > 0 && i - start < 8000; i = SRC.indexOf(";", i + 1)) {
    const candidate = SRC.slice(start, i).trim();
    try {
      new Function(`return (${candidate});`); // parse-only
      return `const ${name} = ${candidate};`;
    } catch (_) { /* unbalanced — keep walking */ }
  }
  assert.fail(`could not slice "${name}" out of stalled.js`);
}

// Same-realm sandbox (new Function, not vm) per the Tier 5 note: a vm context
// is a separate realm and cross-realm deepStrictEqual fails on Array.prototype.
const NAMES = ["esc", "stalledRows", "daysBetween", "bookDay", "framing",
               "summarize", "fmtR", "slotsClause"];
const body = NAMES.map(sliceConst).join("\n") +
  `\nreturn { ${NAMES.join(", ")} };`;
const { esc, stalledRows, daysBetween, bookDay, framing, summarize, fmtR, slotsClause } =
  new Function(body)();

const row = (over) => Object.assign({
  symbol: "GLBE", market: "nasdaq", direction: "long", status: "open",
  entry_date: "2026-07-09", stale_pinged: "2026-07-28",
  unreal_r: 0.172, risk_usd: 1830.93, grade: "A+", tp1_hit: false,
}, over || {});

// ── 1. the cohort is the engine's ────────────────────────────────────────────
suite("cohort — the stamp is the whole definition");

test("only open rows carrying stale_pinged are listed", () => {
  const book = { open: [
    row(),
    row({ symbol: "MOVING", stale_pinged: undefined }),
    row({ symbol: "CLOSED", status: "closed" }),
    null,
  ] };
  assert.deepEqual(stalledRows(book).map((p) => p.symbol), ["GLBE"]);
});

test("no threshold lives in this file — a stamp is listed regardless of R or age", () => {
  // A row the probe stamped yesterday at +0.49R and one it stamped months ago
  // at -0.49R are both the engine's cohort. The surface must not re-filter.
  const book = { open: [
    row({ symbol: "FRESH", stale_pinged: "2026-08-01", unreal_r: 0.49 }),
    row({ symbol: "OLD", stale_pinged: "2026-05-01", unreal_r: -0.49 }),
  ] };
  assert.equal(stalledRows(book).length, 2);
});

test("an empty or absent book yields an empty cohort, never a throw", () => {
  assert.deepEqual(stalledRows({}), []);
  assert.deepEqual(stalledRows(null), []);
  assert.deepEqual(stalledRows({ open: null }), []);
});

// ── 2. the numbers ───────────────────────────────────────────────────────────
suite("day arithmetic — the book's calendar, not the browser's");

test("held and mark-age are whole days between ISO dates", () => {
  assert.equal(daysBetween("2026-07-09", "2026-08-01"), 23);
  assert.equal(daysBetween("2026-07-28", "2026-08-01"), 4);
  assert.equal(daysBetween("2026-08-01", "2026-08-01"), 0);
});

test("an unparseable date is null, not NaN", () => {
  // NaN propagates through comparisons as false and would sort rows
  // unpredictably; null renders as an em-dash.
  assert.equal(daysBetween(null, "2026-08-01"), null);
  assert.equal(daysBetween("garbage", "2026-08-01"), null);
});

test("the day is the book's own updated_day when it carries one", () => {
  assert.equal(bookDay({ summary: { updated_day: "2026-08-01" } }), "2026-08-01");
  // Fallback only when the book cannot say: shape must be an ISO date.
  assert.match(bookDay({}), /^\d{4}-\d{2}-\d{2}$/);
});

suite("summary — R, dollars, slots");

const BOOK = { open: [
  row(), row({ symbol: "AXON", unreal_r: -0.259, risk_usd: 1836.94 }),
  row({ symbol: "HELD", stale_pinged: undefined }),
] };
const RULES = { max_open_total: 30, max_hold_days: 28, account_equity: 150000 };

test("combined R and dollars-at-risk sum over the stalled rows only", () => {
  const s = summarize(stalledRows(BOOK), BOOK, RULES);
  assert.equal(s.n, 2);
  assert.ok(Math.abs(s.totalR - (0.172 - 0.259)) < 1e-9, String(s.totalR));
  assert.ok(Math.abs(s.riskUsd - (1830.93 + 1836.94)) < 1e-9, String(s.riskUsd));
  assert.ok(Math.abs(s.riskPct - 100 * s.riskUsd / 150000) < 1e-9, String(s.riskPct));
});

test("slots blocked are counted against the GLOBAL cap from bot_rules", () => {
  const s = summarize(stalledRows(BOOK), BOOK, RULES);
  assert.equal(s.maxOpen, 30);
  assert.equal(s.open, 3);
  assert.equal(s.free, 27);
  assert.equal(s.atCap, false);
});

test("a full book reads FULL and names the stalled rows as the only source of slots", () => {
  const open = Array.from({ length: 30 }, (_, i) => row({ symbol: "S" + i, stale_pinged: i < 8 ? "2026-07-28" : undefined }));
  const s = summarize(stalledRows({ open }), { open }, RULES);
  assert.equal(s.atCap, true);
  assert.equal(s.free, 0);
  const clause = slotsClause(s);
  assert.ok(clause.includes("8 of 30"), clause);
  assert.ok(clause.includes("FULL"), clause);
  assert.ok(clause.includes("only slots a new A+ can come from"), clause);
});

test("missing rules degrade the summary, never break it", () => {
  const s = summarize(stalledRows(BOOK), BOOK, null);
  assert.equal(s.maxOpen, null);
  assert.equal(s.riskPct, null);
  assert.ok(!slotsClause(s).includes("null"), slotsClause(s));
});

test("a NaN or missing unreal_r contributes zero, not NaN, to the totals", () => {
  // A NaN in a sum makes every later comparison false — the Tier 4 lesson.
  const b = { open: [row({ unreal_r: NaN, risk_usd: undefined })] };
  const s = summarize(stalledRows(b), b, RULES);
  assert.ok(isFinite(s.totalR) && s.totalR === 0, String(s.totalR));
  assert.ok(isFinite(s.riskUsd) && s.riskUsd === 0, String(s.riskUsd));
});

// ── 3. the framing ───────────────────────────────────────────────────────────
suite("your call — keep / time-stop / free capacity");

test("a pre-TP1 stall names the time-stop and the days remaining", () => {
  const f = framing(row(), 23, 28);
  assert.equal(f.kind, "timed");
  assert.ok(f.label.includes("time-stop in 5d"), f.label);
  assert.ok(f.detail.includes("Keep it"), f.detail);
  assert.ok(f.detail.includes("free the slot"), f.detail);
});

test("a pre-TP1 stall past the hold limit reads due", () => {
  const f = framing(row(), 30, 28);
  assert.equal(f.kind, "due");
  assert.ok(f.label.includes("due"), f.label);
});

test("a runner past TP1 says the time-stop never applies and only a manual close frees the slot", () => {
  const f = framing(row({ tp1_hit: true }), 33, 28);
  assert.equal(f.kind, "runner");
  assert.ok(f.detail.includes("never applies"), f.detail);
  assert.ok(f.detail.includes("manual close"), f.detail);
});

test("the framing never claims an action was or will be taken by this surface", () => {
  for (const f of [framing(row(), 23, 28), framing(row({ tp1_hit: true }), 33, 28)]) {
    assert.ok(!/\b(closed|closing now|will close|I will)\b/i.test(f.label + " " + f.detail),
      f.label + " / " + f.detail);
  }
});

// ── 4. read-only by source ───────────────────────────────────────────────────
suite("read-only — no write path exists in the shipped file");

test("it fetches only the two published artifacts", () => {
  const urls = [...SRC.matchAll(/get\("([^"]+)"\)/g)].map((m) => m[1]);
  assert.deepEqual(urls.sort(),
    ["data/bot_rules.json", "data/vivek_bot_book.json"]);
});

test("esc escapes all five breakout characters and is null-safe", () => {
  assert.equal(esc(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  assert.equal(esc(null), "");
});

// ── 5. the page actually loads it ────────────────────────────────────────────
suite("wiring — a surface nobody sees is not a surface");

test("journal.html hosts #stalled-strip and requests stalled.js and stalled.css", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.ok(html.includes('id="stalled-strip"'), "host section missing from journal.html");
  assert.match(html, /js\/stalled\.js\?v=\d+/, "script tag missing or unversioned");
  assert.match(html, /css\/stalled\.css\?v=\d+/, "stylesheet missing or unversioned");
});

test("the host section starts hidden, so a missing file costs nothing", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  assert.match(html, /id="stalled-strip"[^>]*hidden|hidden[^>]*id="stalled-strip"/,
    "the strip must ship hidden and only appear when the book carries a mark");
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

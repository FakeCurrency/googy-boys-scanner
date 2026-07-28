#!/usr/bin/env node
/* Review-chip tests for public/js/journal.js.

   Owner instruction, 2026-07-28: "Flag this in the future so i can verify
   whether claude or I should take the position or not." The server computes the
   flag (scanner/broker/vivek_bot.review_flags, tests/test_review_flags.py) and
   writes it onto the book row; this file covers the last hop, the one where the
   owner actually reads it.

   It runs the REAL function, sliced out of the shipped file at load time rather
   than re-typed here. journal.js is one big IIFE with no export surface, and the
   house pattern in test/unit.test.js is to mirror the maths in the test — which
   is fine for arithmetic that would fail loudly, and wrong for this: a mirrored
   copy of a chip renderer drifts silently, and a chip that silently stops
   rendering is indistinguishable from a position that was never flagged. So the
   extraction is deliberately brittle. If someone renames or removes reviewChip,
   this file fails to load and says so, which is the alarm we want.

   Run with: node test/journal_review.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("journal_review.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ── pull the real reviewChip out of the shipped file ─────────────────────────
const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");

function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — was it renamed?`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

// esc comes along for the ride — the chip's escaping is part of what is tested,
// so mocking it would test the mock.
const escSrc = slice("const esc = (s) =>", ";\n");
const chipSrc = slice("const reviewChip = (t) => {", "\n  };");

const ctx = vm.createContext({});
vm.runInContext(`${escSrc}\n${chipSrc}\nthis.reviewChip = reviewChip; this.esc = esc;`, ctx);
const { reviewChip } = ctx;

const flagged = (over) => Object.assign({
  symbol: "MDB", direction: "long", status: "open",
  review: [{ code: "heavy_risk", share_pct: 26.7, stop_pct: 24.0, risk_usd: 1200,
             limit_usd: 4500,
             note: "a 1R loss here is $1,200 - 27% of the $4,500 daily loss guard, on a 24% stop" }],
}, over || {});

// ── what renders and what does not ───────────────────────────────────────────
suite("review chip — presence");

test("a flagged position renders a chip", () => {
  const html = reviewChip(flagged());
  assert.ok(html.includes("jr-review"), html);
  assert.ok(html.includes("27% of the day"), html);   // 26.7 rounds to 27
});

test("a clean position renders nothing", () => {
  assert.equal(reviewChip({ symbol: "BHP", review: [] }), "");
});

test("a row written before flags existed renders nothing", () => {
  // Absent key, not an empty array. Both are silent, but the book keeps them
  // apart on purpose and neither may throw here.
  assert.equal(reviewChip({ symbol: "BHP" }), "");
  assert.equal(reviewChip({ symbol: "BHP", review: null }), "");
});

test("a closed position still shows its flag", () => {
  // Deliberate. The flag records what was known at ENTRY, and the flagged
  // trades' outcomes are the only evidence that ever tells us whether the
  // threshold is set sensibly. Hiding it on close deletes that evidence.
  const html = reviewChip(flagged({ status: "closed", exit: 88.2 }));
  assert.ok(html.includes("jr-review"), html);
});

// ── the numbers it shows ─────────────────────────────────────────────────────
suite("review chip — content");

test("the note becomes the tooltip verbatim", () => {
  // The server writes one sentence carrying both dollar figures and the stop
  // width; the chip shows a three-word summary, so the tooltip is the only
  // place the actual numbers reach the reader. It must arrive whole.
  const t = flagged();
  const html = reviewChip(t);
  assert.ok(html.includes(`title="${t.review[0].note}"`), html);
  assert.ok(html.includes("$1,200") && html.includes("$4,500"), html);
});

test("a flag with no note falls back to an explanatory title, never blank", () => {
  const html = reviewChip(flagged({ review: [{ code: "heavy_risk", share_pct: 30 }] }));
  assert.ok(/title="[^"]{20,}"/.test(html), `expected a real title: ${html}`);
});

test("a flag with no share_pct still renders, reading 'heavy'", () => {
  // Defensive: a future flag code need not carry share_pct, and the chip must
  // degrade to "there is something here" rather than to "0% of the day", which
  // would read as reassurance.
  const html = reviewChip(flagged({ review: [{ code: "some_future_code", note: "x" }] }));
  assert.ok(html.includes("heavy"), html);
  assert.ok(!html.includes("0%"), html);
});

test("only the first flag is rendered", () => {
  const html = reviewChip(flagged({
    review: [{ code: "heavy_risk", share_pct: 26.7, note: "first" },
             { code: "other", share_pct: 99, note: "second" }],
  }));
  assert.ok(html.includes("27%"), html);
  assert.ok(!html.includes("99%"), html);
});

// ── it is markup, and the note reaches it from the server ────────────────────
suite("review chip — escaping");

test("a note containing markup cannot break out of the title attribute", () => {
  // The note is built server-side from a symbol the scan supplied. Treat it as
  // untrusted on principle: an unescaped quote here would end the attribute.
  const html = reviewChip(flagged({
    review: [{ code: "heavy_risk", share_pct: 20, note: `"><img src=x onerror=alert(1)>` }],
  }));
  assert.ok(!html.includes("<img"), html);
  assert.ok(html.includes("&quot;") || html.includes("&#39;"), html);
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

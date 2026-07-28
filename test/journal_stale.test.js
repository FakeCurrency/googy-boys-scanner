#!/usr/bin/env node
/* Stale-mark tests for public/js/journal.js  (TOP100 #24).

   A scan back-fills any ticker Yahoo dropped this run from the last-good frame
   cache, and that cached close is published into `prices` looking exactly like
   a live one. Every open position on the journal page is marked off that map —
   so a name Yahoo had not returned in a week was drawing a week-old close as
   its current price, computing an unrealised R off it, and showing nothing at
   all to say so. The number was not so much wrong as not what it claimed to be.

   scanner/data.py refuses a frame past FRAME_CACHE_MAX_AGE_DAYS outright
   (tests/test_data_download.py); everything INSIDE that ceiling is still a past
   close being presented as a live mark, and this file covers the last hop —
   whether the owner can see that when he reads the number.

   Like test/journal_review.test.js, it runs the REAL functions sliced out of
   the shipped file rather than re-typed here. A mirrored copy of a badge
   renderer drifts silently, and a badge that has silently stopped rendering is
   indistinguishable from a mark that was fresh.

   Run with: node test/journal_stale.test.js
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
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("journal_stale.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ── pull the real helpers out of the shipped file ────────────────────────────
const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");
function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — was it renamed?`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

const ctx = vm.createContext({});
vm.runInContext(
  "const scanAge = new Map();\n"
  + slice("const ageOf = (key)", ";\n") + "\n"
  + slice("const staleWord = (d)", ";\n") + "\n"
  + slice("function markStale(cell, days) {", "\n  }") + "\n"
  + "this.scanAge = scanAge; this.ageOf = ageOf; this.staleWord = staleWord;"
  + "this.markStale = markStale;",
  ctx);
const { scanAge, ageOf, staleWord, markStale } = ctx;

// The smallest thing markStale can act on: it toggles one class and sets title.
function cell() {
  const set = new Set();
  return {
    title: "",
    classList: {
      toggle(c, on) { if (on) set.add(c); else set.delete(c); },
      contains: (c) => set.has(c),
    },
  };
}
const isStale = (c) => c.classList.contains("jr-stale");

// ── the sparse convention ────────────────────────────────────────────────────
suite("absent means fresh");

test("an unknown symbol reads as fresh, not as unknown", () => {
  // `price_age` is published SPARSE — a healthy ASX run has ~2,200 marks and
  // every one of them is 0, so writing the zeros would roughly double the slim
  // prices file to say nothing. Absent therefore has to mean fresh, which is
  // also what every reader assumed before this existed: an old cached page
  // that has never heard of price_age keeps working unchanged.
  assert.equal(ageOf("asx:NEVER-SEEN"), 0);
});

test("a recorded age comes back as itself", () => {
  scanAge.set("asx:BGA", 4);
  assert.equal(ageOf("asx:BGA"), 4);
  scanAge.delete("asx:BGA");
});

// ── the badge ────────────────────────────────────────────────────────────────
suite("what the owner sees");

test("a stale mark is badged and says where the price came from", () => {
  const c = cell();
  markStale(c, 6);
  assert.ok(isStale(c));
  // The title has to name the CAUSE, not just the age. "6 sessions old" invites
  // "so what"; "missing from the latest scan, filled from cache" is the fact
  // that tells him the R beside it is computed off a price nobody quoted today.
  assert.match(c.title, /6 sessions/);
  assert.match(c.title, /cache/i);
});

test("a fresh mark is left completely alone", () => {
  const c = cell();
  markStale(c, 0);
  assert.ok(!isStale(c));
  assert.equal(c.title, "");
});

test("THE ONE THAT MATTERS: a name that comes back loses its badge", () => {
  // refreshLive repaints every 20s and loadScanMeta re-pulls every 3 minutes,
  // against cells that persist. If markStale only ever ADDED the badge, the
  // first stale run would mark a cell permanently — and a badge that never
  // clears is worse than no badge at all, because it trains you to read past
  // the ones that are real. Both branches of the toggle always run.
  const c = cell();
  markStale(c, 9);
  assert.ok(isStale(c));
  markStale(c, 0);
  assert.ok(!isStale(c), "the badge survived the name coming back into the scan");
  assert.equal(c.title, "");
});

test("markStale is a no-op on a cell that is not there", () => {
  // paint() walks rows that may have been re-rendered out from under it.
  assert.doesNotThrow(() => markStale(null, 3));
  assert.doesNotThrow(() => markStale(undefined, 0));
});

test("one session is a session, not sessions", () => {
  assert.equal(staleWord(1), "1 session");
  assert.equal(staleWord(2), "2 sessions");
});

// ── the wiring, pinned against the source ────────────────────────────────────
// These are source assertions rather than behavioural ones because the code
// they cover lives inside fetch/DOM paths that would cost more to fake than
// they would prove. Each pins a decision that is easy to undo by accident.
suite("wiring");

test("the loader DELETES an age that has gone fresh", () => {
  // The half that makes the clearing test above reachable in real life. Without
  // it, scanAge keeps yesterday's entry for a symbol that is fresh today —
  // because a sparse map cannot express "no longer stale" by omission alone
  // when the map persists across loads.
  assert.ok(SRC.includes("if (a > 0) scanAge.set(k, a); else scanAge.delete(k);"),
            "loadScanMeta no longer clears a stale age when the mark goes fresh");
});

test("a live quote is never treated as stale", () => {
  // refreshLive falls back to a live quote when the scan has no price. That
  // quote was fetched seconds ago, so it carries no age BY CONSTRUCTION —
  // reading scanAge for it would badge a genuinely live price.
  assert.ok(SRC.includes("paint(g, price, cached ? ageOf(g.key) : 0);"),
            "refreshLive no longer distinguishes a scan snapshot from a live quote");
});

test("the bot side gets the badge too", () => {
  // The bot's marks are computed SERVER-SIDE, but off the same merged frames
  // the price map comes from, so they inherit exactly the same fossil risk.
  // Marking only the manual side would leave the larger book unlabelled.
  assert.ok(SRC.includes('const cls = "num jr-now" + (d > 0 ? " jr-stale" : "");'),
            "the bot Now cell no longer carries the stale class");
});

test("the P&L headline counts them", () => {
  // The row badge is only seen by someone already looking at that row. The
  // headline is the one number on the page that gets read every time, and a
  // total summed partly from week-old closes should not present itself as
  // today's P&L in silence.
  assert.ok(SRC.includes("priced off a stale close"),
            "the P&L headline no longer reports stale marks");
});

test("the badge has a style to render", () => {
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  assert.ok(css.includes(".jr-stale"), "journal.css has no .jr-stale rule");
});

test("both assets were version-bumped on the page that loads them", () => {
  // House rule: any edit to a public/js or public/css asset bumps its ?v= in
  // every referencing page, or the service worker serves the old one from
  // cache-first storage and the change never reaches a returning visitor.
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  const js = /js\/journal\.js\?v=(\d+)/.exec(html);
  const css = /css\/journal\.css\?v=(\d+)/.exec(html);
  assert.ok(js && css, "journal.html no longer versions its journal assets");
  assert.ok(+js[1] >= 62, `journal.js is still at ?v=${js[1]}`);
  assert.ok(+css[1] >= 32, `journal.css is still at ?v=${css[1]}`);
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

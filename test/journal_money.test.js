#!/usr/bin/env node
/* The journal's money arithmetic — TOP100 Tier 2 (#25, #26, #30, #33).

   Four fixes, one theme: every one of them was a number the page reported with
   full confidence that was quietly measuring something other than what its
   label said. None of them threw, none of them rendered a dash, and none of
   them disagreed with any other number on the page — which is exactly why they
   survived. A wrong total that contradicts the chart beside it gets noticed in
   an afternoon; a wrong total that the chart agrees with gets trusted for
   months.

     #25  Closed-trade R dropped the un-booked remainder of the position. The
          FULL ladder sums to 0.90, so even a perfect winner left a 10% runner
          unpriced — every completed VIVEK winner on the page was under-reported.
          And `computeCloseOutcome` clones the trade through the SAME resolver,
          so the close preview was wrong by precisely the same amount as the
          outcome it predicted. The two never disagreed.
     #26  `_init` was an enumerable boolean, so it round-tripped through
          localStorage and KV and froze `risk_usd` at whatever constants the
          first device to open the row happened to be holding. Forever, on every
          device, because the early return fired before any sizing ran.
     #30  Max drawdown walked `closed` in store order. For the bot book that is
          market-by-market, so every NASDAQ trade of the year lands before the
          first ASX one and the "worst drawdown" described a sequence of trades
          that never happened in that order.
     #33  The TP ladder was a hand-typed JS copy of VIVEK_TP_SCALE_LONG/SHORT
          with nothing comparing them — the one sizing constant on the page that
          structurally could not raise the drift warning the others could.

   Like test/journal_review.test.js and test/journal_stale.test.js, this runs the
   REAL functions sliced out of the shipped file. Re-typing `ensureClosedR` here
   would produce a suite that passes forever against a copy of the bug.

   Run with: node test/journal_money.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.resolve(__dirname, "../public/js/journal.js"), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("journal_money.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

function slice(startMarker, endMarker) {
  const a = SRC.indexOf(startMarker);
  assert.ok(a >= 0, `journal.js no longer contains "${startMarker}" — was it renamed?`);
  const b = SRC.indexOf(endMarker, a);
  assert.ok(b > a, `could not find the end of "${startMarker}"`);
  return SRC.slice(a, b + endMarker.length);
}

// ── the real money path, lifted whole ────────────────────────────────────────
// Everything below the constants is SHIPPED CODE. The constants are declared
// here because in the file they are `let`s mutated by an async fetch, and this
// suite is about the arithmetic, not about the fetch. They are set to the
// file's own fallbacks so a test that reasons about dollars reasons about the
// same numbers the offline page would show.
const ctx = vm.createContext({ console });
vm.runInContext(
  "let EQUITY = 150000, POSITION_NOTIONAL = 5000, RISK_PCT = 0.35;\n"
  + "const RISK_MIN = 0.25, RISK_MAX = 0.5;\n"
  + "const LEVERAGE = { asx: 5, nasdaq: 5, crypto: 3 };\n"
  + "let SCALE = { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] };\n"
  + "const COMMISSION_BPS = { asx: 2, nasdaq: 1, crypto: 6, default: 2 };\n"
  + "const SLIPPAGE_BPS   = { asx: 5, nasdaq: 4, crypto: 8, default: 5 };\n"
  + "const isCryptoTrade = (t) => (t.market || t.asset_type) === 'crypto';\n"
  + "const today = () => '2026-07-28';\n"
  + "let FX_AUDUSD = 0.66;\n"
  + slice("const round = (v, n)", ";\n") + "\n"
  + slice("function marketOf(t) {", "\n  }") + "\n"
  + slice("function sizeOf(market, entry, stop) {", "\n  }") + "\n"
  + slice("const costsFor = (market) =>", "];\n") + "\n"
  + slice("function costR(t, slip, comm) {", "\n  }") + "\n"
  + slice("const rOf = (price, entry, risk, isLong)", ";\n") + "\n"
  + slice("const isVivek = (t) =>", ";\n") + "\n"
  + "let RULES_GEN = 1;\n"
  + slice("function ensureInit(t) {", "\n  }") + "\n"
  + slice("function finalizeR(t) {", "\n  }") + "\n"
  + slice("function ensureClosedR(t) {", "\n  }") + "\n"
  + slice("const fxOf = (t) =>", ";\n") + "\n"
  + slice("const dollarsOf = (t) =>", ";\n") + "\n"
  + slice("function exitMs(t) {", "\n  }") + "\n"
  + slice("const byExit = (closed) =>", ";\n") + "\n"
  + slice("function stats(closed, openN) {", "\n  }") + "\n"
  + "this.ensureInit = ensureInit; this.ensureClosedR = ensureClosedR;"
  + "this.stats = stats; this.byExit = byExit; this.sizeOf = sizeOf;"
  + "this.bumpGen = () => { RULES_GEN++; }; this.gen = () => RULES_GEN;"
  + "this.setScale = (s) => { SCALE = s; };",
  ctx);
const { ensureInit, ensureClosedR, stats, byExit, sizeOf, bumpGen, gen, setScale } = ctx;

// A closed VIVEK long with round numbers: entry 100, stop 90, so 1R = 10 points.
// Exit at 130 is +3R gross on whatever fraction of the position is still on.
function closedLong(over) {
  return Object.assign({
    id: "t1", market: "nasdaq", direction: "long", status: "closed",
    entry: 100, stop: 90, risk: 10, risk_stop: 90,
    tp1: 110, tp2: 120, tp3: 125,
    exit: 130, exit_date: "2026-07-20",
    gross_r: 0, booked_pct: 0, exits: [],
  }, over);
}

// ── #25 — the un-booked remainder ────────────────────────────────────────────
suite("#25 — a closed trade books the whole position, not just the ladder");

test("a trade that never scaled out books 1.0 of the position", () => {
  const t = closedLong();
  ensureClosedR(t);
  assert.equal(t.booked_pct, 1);
  assert.equal(t.exits.length, 1);
  assert.equal(t.exits[0].pct, 1);
  assert.equal(t.gross_r, 3);           // (130 - 100) / 10
});

test("a PARTIAL ladder books the manual tail — the 0.75 that used to vanish", () => {
  // tp1 filled at 110 for 0.25 of the position (+0.25R), then closed by hand at
  // 130. The old guard was `if (!t.exits.length)`, so this trade — which HAS an
  // exit — took the early return and reported 0.25R for a +3R move.
  const t = closedLong({ gross_r: 0.25, booked_pct: 0.25,
    exits: [{ reason: "tp1", price: 110, pct: 0.25, date: "2026-07-15" }] });
  ensureClosedR(t);
  assert.equal(t.booked_pct, 1);
  assert.equal(t.exits.length, 2);
  // 0.25 booked at +1R, plus 0.75 of the +3R move = 0.25 + 2.25.
  assert.equal(t.gross_r, 2.5);
  assert.ok(t.realized_r > 2.4 && t.realized_r < 2.5, "costs come off, but not 2R of them");
});

test("a FULL ladder still has a 10% runner, and it is now priced", () => {
  // The subtle half, and the one that hit every completed winner: SCALE sums to
  // 0.90 by design. Hitting all three targets does NOT close the position.
  const t = closedLong({
    gross_r: 0.25 * 1 + 0.50 * 2 + 0.15 * 2.5, booked_pct: 0.90,
    exits: [
      { reason: "tp1", price: 110, pct: 0.25, date: "2026-07-15" },
      { reason: "tp2", price: 120, pct: 0.50, date: "2026-07-17" },
      { reason: "tp3", price: 125, pct: 0.15, date: "2026-07-18" },
    ],
  });
  const before = t.gross_r;
  ensureClosedR(t);
  assert.equal(t.booked_pct, 1);
  assert.equal(t.exits.length, 4);
  assert.equal(round4(t.gross_r - before), 0.3);   // 0.10 × 3R
});
function round4(v) { return +v.toFixed(4); }

test("it is IDEMPOTENT — it runs on every load, not once at close", () => {
  // Load-bearing: ensureClosedR is called from the `closed` branch of the render
  // loop, which re-runs on every paint and every three-minute refresh. If a
  // second pass booked the remainder again, the page's total R would climb on
  // its own for as long as it was left open.
  const t = closedLong();
  ensureClosedR(t);
  const first = { r: t.realized_r, n: t.exits.length, g: t.gross_r };
  for (let i = 0; i < 5; i++) ensureClosedR(t);
  assert.equal(t.realized_r, first.r);
  assert.equal(t.exits.length, first.n);
  assert.equal(t.gross_r, first.g);
});

test("a legacy row with booked_pct but an EMPTY exits array is not booked twice", () => {
  // `booked` takes the LARGER of the summed exits and the stored booked_pct.
  // Under-booking is the bug being fixed; double-booking would invent R that
  // was never made, which is the worse direction to be wrong in.
  const t = closedLong({ gross_r: 2.7, booked_pct: 0.9, exits: [] });
  ensureClosedR(t);
  assert.equal(round4(t.gross_r - 2.7), 0.3, "only the 0.10 remainder, not the whole position");
});

test("a zero-width stop is refused rather than divided by", () => {
  // One degenerate row would otherwise put NaN into gross_r, and NaN poisons
  // every $ aggregate on the page — not just its own row.
  const t = closedLong({ risk: 0, risk_stop: 100 });
  ensureClosedR(t);
  assert.ok(Number.isFinite(t.gross_r), `gross_r went non-finite: ${t.gross_r}`);
  assert.ok(Number.isFinite(t.realized_r), `realized_r went non-finite: ${t.realized_r}`);
});

test("a non-VIVEK row (no plan) reports no R at all rather than a made-up one", () => {
  const t = closedLong({ stop: null, tp1: null });
  ensureClosedR(t);
  assert.equal(t.realized_r, null);
});

// ── #26 — `_init` is a cache, not data ───────────────────────────────────────
suite("#26 — the sizing cache never leaves the page");

test("_init does not survive JSON.stringify — the localStorage/KV/backup path", () => {
  const t = closedLong();
  ensureInit(t);
  assert.ok(t._init, "the cache stamp must still be SET, just not enumerable");
  assert.ok(!("_init" in JSON.parse(JSON.stringify(t))),
    "_init round-tripped through JSON — a persisted stamp freezes risk_usd at the " +
    "constants of whichever device opened the row first, on every device, forever");
  assert.ok(!Object.keys(t).includes("_init"));
});

test("bumping the generation re-derives risk_usd instead of returning early", () => {
  // The whole point of #26's second half. `_init` used to be a boolean, so the
  // `loadMe()` that loadBotRules fires after adopting live constants re-entered
  // ensureInit and returned on its first line — re-deriving nothing, which made
  // that function's own comment false.
  const t = closedLong();
  ensureInit(t);
  const firstGen = t._init;
  ensureInit(t);
  assert.equal(t._init, firstGen, "same generation is a genuine no-op");
  bumpGen();
  ensureInit(t);
  assert.equal(t._init, gen(), "a bumped generation must re-run the sizing");
  assert.ok(t._init > firstGen);
});

test("1R is pinned to the PLAN stop, so trailing the stop cannot rescale booked R", () => {
  // manage() trails t.stop to break-even on a tp1 fill. Deriving risk from the
  // live stop then gave risk === 0 and realized_r === Infinity, on exactly the
  // path (a manual close) that deletes the cache stamp and re-derives.
  const t = closedLong({ stop: 100 });   // trailed to break-even
  ensureInit(t);
  assert.equal(t.risk, 10, "risk must come from risk_stop (90), not the trailed stop (100)");
  assert.ok(Number.isFinite(t.risk_usd) && t.risk_usd > 0);
});

test("a legacy row with no risk_stop recovers the plan stop exactly from `risk`", () => {
  // No guessing and no migration: `risk` was written from the plan stop back
  // when the stop still WAS the plan stop, so entry ± risk reproduces it.
  const t = closedLong({ stop: 100, risk_stop: undefined, risk: 10 });
  delete t.risk_stop;
  ensureInit(t);
  assert.equal(t.risk_stop, 90);
  assert.equal(t.risk, 10);
});

test("a SHORT legacy row recovers its plan stop on the other side of entry", () => {
  const t = closedLong({ direction: "short", stop: 100, risk: 10, exit: 70 });
  delete t.risk_stop;
  ensureInit(t);
  assert.equal(t.risk_stop, 110);
});

// ── #30 — drawdown is a property of the ORDER ────────────────────────────────
suite("#30 — max drawdown walks exit order, like the chart beside it");

// Same three trades, two store orders. risk_usd is forced so the $ figures are
// exact and the test is about sequencing rather than about the sizer.
function tr(id, r, exitDate) {
  return { id, market: "nasdaq", realized_r: r, risk_usd: 100,
           status: "closed", exit_date: exitDate, exit_time: "16:00" };
}
const WIN_FIRST = [tr("a", +5, "2026-07-01"), tr("b", -3, "2026-07-02"), tr("c", -1, "2026-07-03")];

test("the same set in a different store order gives the same drawdown", () => {
  const shuffled = [WIN_FIRST[2], WIN_FIRST[0], WIN_FIRST[1]];
  assert.equal(stats(WIN_FIRST, 0).maxDD, stats(shuffled, 0).maxDD);
});

test("and that drawdown is the real one: peak +$500, trough +$100, so -$400", () => {
  // Walked in store order, the shuffled array reads -1, +5, -3 → peak 400,
  // trough -100 at the start, and reports a drawdown of -$300. Neither number
  // is absurd, which is why nobody caught it.
  assert.equal(stats(WIN_FIRST, 0).maxDD, -400);
});

test("byExit does not mutate the caller's array", () => {
  // stats() and series() both call it on the same live `closed` list. If it
  // sorted in place, the first render would silently reorder the store.
  const orig = [WIN_FIRST[2], WIN_FIRST[0], WIN_FIRST[1]];
  const snapshot = orig.slice();
  byExit(orig);
  assert.deepEqual(orig.map((t) => t.id), snapshot.map((t) => t.id));
});

test("rows with an unparseable exit date sort as 0 rather than throwing", () => {
  const messy = [tr("x", -2, "not-a-date"), tr("y", +1, "2026-07-02")];
  const s = stats(messy, 0);
  assert.ok(Number.isFinite(s.maxDD));
  assert.ok(Number.isFinite(s.totalD));
});

test("totals and win rate are order-independent too (the sanity check)", () => {
  const a = stats(WIN_FIRST, 0), b = stats([...WIN_FIRST].reverse(), 0);
  assert.equal(a.totalR, b.totalR);
  assert.equal(a.totalD, b.totalD);
  assert.equal(a.win, b.win);
});

test("ASX dollars are converted before they enter the curve", () => {
  // Not a #30 fix, but it shares the code path and the drawdown is a DOLLAR
  // curve: mixing A$ and US$ at face value would overstate an ASX leg ~50%.
  const asx = [{ id: "a", market: "asx", realized_r: 1, risk_usd: 100,
                 status: "closed", exit_date: "2026-07-01", exit_time: "16:00" }];
  assert.equal(stats(asx, 0).totalD, 66);
});

// ── #33 — the ladder is adopted, not re-typed ────────────────────────────────
suite("#33 — the TP ladder comes from the engine");

test("SCALE is mutable, because loadBotRules replaces it from bot_rules.json", () => {
  // A `const` array of three literals is what the bug looked like. This asserts
  // the shape that lets the published ladder win — if someone re-freezes it,
  // adoption silently becomes a no-op and the drift warning never fires again.
  setScale({ long: [0.3, 0.4, 0.2], short: [0.5, 0.25, 0.15] });
  const t = { id: "n", market: "nasdaq", direction: "long", status: "open",
              entry: 100, stop: 90, risk: 10, risk_stop: 90, tp1: 110, tp2: 120, tp3: 125 };
  ensureInit(t);
  assert.deepEqual(t.scale, [0.3, 0.4, 0.2],
    "a NEW position must take the live ladder, not the hand-typed fallback");
  setScale({ long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] });
});

test("a trade that already carries a `scale` keeps it when the ladder changes", () => {
  // The correct scope for adoption: a position was taken under one ladder and
  // its booked R was computed with it. Retro-fitting a new ladder would restate
  // history. Only positions opened from here on see the change.
  setScale({ long: [0.3, 0.4, 0.2], short: [0.5, 0.25, 0.15] });
  const t = { id: "o", market: "nasdaq", direction: "long", status: "open",
              entry: 100, stop: 90, risk: 10, risk_stop: 90, tp1: 110, tp2: 120, tp3: 125,
              scale: [0.25, 0.50, 0.15] };
  ensureInit(t);
  assert.deepEqual(t.scale, [0.25, 0.50, 0.15]);
  setScale({ long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] });
});

test("journal.js adopts bot_rules.tp_scale and shouts when it differs", () => {
  // Source-pin: the adoption lives inside an async fetch handler that this
  // harness does not run. Deleting the block would leave every test above
  // passing against a ladder nothing publishes to.
  assert.ok(/j\.tp_scale/.test(SRC),
    "journal.js no longer reads bot_rules.tp_scale — the ladder is a hand-typed copy again");
  assert.ok(/drift\["tp_scale\." \+ side\]/.test(SRC),
    "the ladder no longer reports drift, so a divergence from scanner/config.py is silent");
  assert.ok(/RULES_GEN\+\+/.test(SRC),
    "adopting live constants no longer invalidates the ensureInit cache, so the " +
    "loadMe() that follows re-derives nothing (TOP100 #26)");
});

// ── the version gate ─────────────────────────────────────────────────────────
suite("cache-busting");

test("journal.html requests a journal.js at or past the version these fixes shipped in", () => {
  // Project rule 2. Every one of the fixes above is invisible to a browser
  // holding the old file, and journal.js is cache-first on `?v=` — so a missed
  // bump means the money arithmetic silently stays wrong for existing users
  // while every test here passes.
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  const m = html.match(/js\/journal\.js\?v=(\d+)/);
  assert.ok(m, "journal.html no longer version-stamps journal.js");
  assert.ok(Number(m[1]) >= 63, `journal.js?v=${m[1]} predates the Tier 2 money fixes (need >= 63)`);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);

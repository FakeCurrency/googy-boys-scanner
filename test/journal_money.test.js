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
  // ── the open-positions sort (2026-08-07) ──
  // paintOpen / refreshLive are the DOM half and are stubbed; everything that
  // DECIDES an order is real code lifted out of the shipped file.
  + slice("const scanPrice = new Map()", ";\n") + "\n"
  + slice("function openedMs(t) {", "\n  }") + "\n"
  + slice("const OPEN_SORT_KEYS =", ";\n") + "\n"
  + slice("let openSort = {", ";") + "\n"
  + slice("function openMetric(t, side) {", "\n  }") + "\n"
  + slice("const openSortValue = (t, side, key) =>", ";\n") + "\n"
  + slice("function sortedOpen(list, side) {", "\n  }") + "\n"
  + "let painted = [];\n"
  + "function paintOpen(side) { painted.push(side); }\n"
  + "function refreshLive() { painted.push('refresh'); }\n"
  + slice("function setOpenSort(key) {", "\n  }") + "\n"
  + "this.ensureInit = ensureInit; this.ensureClosedR = ensureClosedR;"
  + "this.stats = stats; this.byExit = byExit; this.sizeOf = sizeOf;"
  + "this.bumpGen = () => { RULES_GEN++; }; this.gen = () => RULES_GEN;"
  + "this.setScale = (s) => { SCALE = s; };"
  + "this.costR = costR;"
  + "this.openMetric = openMetric; this.sortedOpen = sortedOpen;"
  + "this.setOpenSort = setOpenSort; this.scanPrice = scanPrice;"
  + "this.sortState = () => ({ ...openSort });"
  + "this.resetSort = () => { openSort = { key: 'opened', dir: -1 }; painted = []; };"
  + "this.painted = () => painted.slice();",
  ctx);
const { ensureInit, ensureClosedR, stats, byExit, sizeOf, bumpGen, gen, setScale } = ctx;
const { openMetric, sortedOpen, setOpenSort, scanPrice, sortState, resetSort, painted } = ctx;
const { costR } = ctx;

// CODE-only view of the source. A substring ban that reads its own explanatory
// comment as the offence passes forever against the bug it describes — this
// file's comments name `localStorage` and `.sort(` deliberately.
const CODE = SRC.split("\n")
  .filter((l) => !/^\s*(\/\/|\/\*|\*)/.test(l))
  .join("\n");

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

// ── #74 — the cost model's exit test ───────────────────────────────────────
// Inverted 2026-08-07. `vivek_journal._cost_r` was flipped to a deny-list by
// TOP100 #74 and this JS copy was left on the old ALLOW-list, under a comment
// asserting the two agreed. Four exit reasons exist in the tree; the allow-list
// knew two.
suite("#74 — every exit that is not a resting limit pays slippage");

// entry 100, stop 90 → 1R = 10 points. slip/comm as round numbers so the
// arithmetic is checkable by hand rather than by copying the implementation.
const SLIP = 0.001, COMM = 0.0005;
const withExit = (reason) => ({
  entry: 100, risk: 10, exits: [{ reason, price: 100, pct: 1 }],
});

test("a resting TP limit pays commission only", () => {
  // entry leg 100*(slip+comm) + exit leg 100*comm, over 1R = 10
  const want = (100 * (SLIP + COMM) + 100 * COMM) / 10;
  for (const r of ["tp1", "tp2", "tp3"]) {
    assert.equal(costR(withExit(r), SLIP, COMM), want, `${r} should not pay slippage`);
  }
});

test("stop and manual pay slippage — unchanged by the inversion", () => {
  const want = (100 * (SLIP + COMM) + 100 * (COMM + SLIP)) / 10;
  assert.equal(costR(withExit("stop"), SLIP, COMM), want);
  assert.equal(costR(withExit("manual"), SLIP, COMM), want);
});

test("time and eod pay slippage too — the two the allow-list missed", () => {
  // vivek_run.py writes `time`; vivek_backtest.py writes `eod`. The Python has
  // charged both since #74. Before the inversion this JS charged neither, which
  // UNDER-reports cost and therefore OVER-reports realized R, win rate and
  // expectancy — on the Me side of a Me-vs-Claude comparison.
  const want = (100 * (SLIP + COMM) + 100 * (COMM + SLIP)) / 10;
  assert.equal(costR(withExit("time"), SLIP, COMM), want, "a time-stop is a market exit");
  assert.equal(costR(withExit("eod"), SLIP, COMM), want, "an eod close is a market exit");
});

test("an unknown reason fails EXPENSIVE, not cheap", () => {
  // The whole point of the deny-list shape. A reason nobody has thought of yet
  // must not silently arrive free — that error flatters the record and is
  // invisible downstream (vivek_journal.py:83-88 makes the same argument).
  const want = (100 * (SLIP + COMM) + 100 * (COMM + SLIP)) / 10;
  assert.equal(costR(withExit("some_future_reason"), SLIP, COMM), want);
  assert.equal(costR(withExit(""), SLIP, COMM), want);
  assert.equal(costR({ entry: 100, risk: 10, exits: [{ price: 100, pct: 1 }] }, SLIP, COMM), want);
});

test("the JS deny-list is spelled the same way as the Python's", () => {
  // Python: _LIMIT_EXIT_REASONS = ("tp1","tp2","tp3"); is_market = not startswith(...)
  // If either side is edited alone, this and the numbers above disagree.
  const py = fs.readFileSync(path.resolve(__dirname, "../scanner/vivek_journal.py"), "utf8");
  assert.ok(/_LIMIT_EXIT_REASONS\s*=\s*\(\s*"tp1",\s*"tp2",\s*"tp3"\s*\)/.test(py),
    "the Python limit-reason tuple moved — the JS mirror below is now guessing");
  assert.ok(/const market = !\/\^tp\[123\]\//.test(CODE),
    "journal.js costR is back on an allow-list, or the test moved");
});

// ── the open-positions sort ──────────────────────────────────────────────────
// Owner-requested 2026-08-07: "toggle by which one is currently in the BEST $
// or R". The ordering itself is cosmetic; what is NOT cosmetic is what a row
// claims while being ordered, which is why these pins are here in the money
// suite rather than a view suite of their own.
suite("open sort — the two books do not carry the same numbers");

// A manual (Me) position: no unreal_r, no unreal_usd. Those cells are painted
// by refreshLive AFTER render, so the sort has to re-derive them itself.
const mePos = (over) => Object.assign({
  id: "x", market: "asx", direction: "long", status: "open",
  entry: 10, stop: 9, risk: 1, risk_stop: 9, risk_usd: 500,
  opened_at: "2026-07-20T01:00:00Z",
}, over);
// A bot position: marked server-side, arrives with both numbers on it.
const botPos = (over) => Object.assign({
  id: "b", market: "nasdaq", direction: "long", status: "open",
  entry: 100, stop: 90, risk: 10, unreal_r: 0.5, unreal_usd: 250,
  opened_at: "2026-07-20T01:00:00Z",
}, over);

test("the bot side reads the numbers the scan already computed", () => {
  const m = openMetric(botPos({ unreal_r: 1.25, unreal_usd: 600 }), "bot");
  assert.equal(m.r, 1.25);
  assert.equal(m.usd, 600);          // nasdaq → fx 1
});

test("the me side derives from the scan price, because nothing on the row has it", () => {
  resetSort(); scanPrice.clear();
  const t = mePos({ symbol: "AAA" });
  // Sorting off the RENDERED cell would sort the literal "—": at this point in
  // the page's life refreshLive has not run and the row carries no R at all.
  assert.equal(t.unreal_r, undefined);
  scanPrice.set("asx:AAA", 12);      // +2R on a 1-point risk
  const m = openMetric(t, "me");
  assert.equal(m.r, 2);
  assert.equal(m.usd, 2 * 500 * 0.66, "ASX dollars must be FX-converted, not taken at face value");
});

test("a short is measured in its own direction", () => {
  resetSort(); scanPrice.clear();
  scanPrice.set("asx:BBB", 8);
  const m = openMetric(mePos({ symbol: "BBB", direction: "short" }), "me");
  assert.equal(m.r, 2, "price 8 against a short entered at 10 is +2R, not -2R");
});

test("an unpriced row is UNKNOWN, never a flat zero", () => {
  resetSort(); scanPrice.clear();
  // Zero would be a lie that sorts into the middle of the table, where it reads
  // as a real number someone might act on.
  assert.equal(openMetric(mePos({ symbol: "GONE" }), "me").r, null);
  assert.equal(openMetric(botPos({ unreal_r: undefined }), "bot").r, null);
  assert.equal(openMetric(botPos({ unreal_usd: undefined }), "bot").usd, null);
});

test("a zero-risk row cannot divide its way to Infinity", () => {
  resetSort(); scanPrice.clear();
  scanPrice.set("asx:FLAT", 11);
  const m = openMetric(mePos({ symbol: "FLAT", risk: 0, stop: 10 }), "me");
  assert.equal(m.r, null);
});

test("a row with no risk_usd still sorts by R, it just has no dollars", () => {
  resetSort(); scanPrice.clear();
  scanPrice.set("asx:CCC", 11);
  const m = openMetric(mePos({ symbol: "CCC", risk_usd: null }), "me");
  assert.equal(m.r, 1);
  assert.equal(m.usd, null);
});

suite("open sort — ordering");

const book = () => {
  scanPrice.clear();
  scanPrice.set("asx:WIN", 12);      // +2.0R · risk_usd 100 → $132
  scanPrice.set("asx:BIG", 10.5);    // +0.5R · risk_usd 900 → $297
  scanPrice.set("asx:LOSE", 9.5);    // -0.5R · risk_usd 200 → -$66
  return [
    mePos({ id: "win", symbol: "WIN", risk_usd: 100, opened_at: "2026-07-01T00:00:00Z" }),
    mePos({ id: "big", symbol: "BIG", risk_usd: 900, opened_at: "2026-07-02T00:00:00Z" }),
    mePos({ id: "lose", symbol: "LOSE", risk_usd: 200, opened_at: "2026-07-03T00:00:00Z" }),
    mePos({ id: "dark", symbol: "DARK", risk_usd: 300, opened_at: "2026-07-04T00:00:00Z" }),
  ];
};
const ids = (list) => list.map((t) => t.id).join(",");

test("default is newest opened first — unchanged from before the sort existed", () => {
  resetSort();
  assert.equal(ids(sortedOpen(book(), "me")), "dark,lose,big,win");
});

test("R descending puts the best R at the top", () => {
  resetSort(); const b = book(); setOpenSort("r");
  assert.equal(ids(sortedOpen(b, "me")), "win,big,lose,dark");
});

test("$ descending is a DIFFERENT order to R — that is the point of two keys", () => {
  resetSort(); const b = book(); setOpenSort("usd");
  // BIG is only +0.5R but carries 9x the size, so it is the bigger dollar win.
  // If this ever equals the R order, one of the two keys has stopped working.
  assert.equal(ids(sortedOpen(b, "me")), "big,win,lose,dark");
});

test("UNKNOWN sinks to the bottom in BOTH directions", () => {
  // The one that actually matters. Reversing the sort must not promote "we
  // don't know what this is worth" to the top of the table, where it sits in
  // the position reserved for the worst loser and reads as one.
  resetSort(); const b = book();
  setOpenSort("r");
  assert.equal(ids(sortedOpen(b, "me")).split(",").pop(), "dark", "descending");
  setOpenSort("r");                                     // reverse
  assert.equal(sortState().dir, 1);
  assert.equal(ids(sortedOpen(b, "me")), "lose,big,win,dark", "ascending — dark STILL last");
});

test("ties break by newest, so the order cannot jitter between renders", () => {
  resetSort(); scanPrice.clear();
  const same = [
    mePos({ id: "old", symbol: "T1", opened_at: "2026-07-01T00:00:00Z" }),
    mePos({ id: "new", symbol: "T2", opened_at: "2026-07-05T00:00:00Z" }),
  ];
  scanPrice.set("asx:T1", 11); scanPrice.set("asx:T2", 11);   // identical +1R
  setOpenSort("r");
  assert.equal(ids(sortedOpen(same, "me")), "new,old");
});

test("sortedOpen does not mutate the caller's array", () => {
  // Same house rule byExit is held to above: state.bot.open / state.me.open are
  // the LIVE books, and reordering them reorders every other surface that reads
  // them — silently, and only for whoever clicked.
  resetSort(); const b = book(); const before = ids(b);
  setOpenSort("usd");
  sortedOpen(b, "me");
  assert.equal(ids(b), before);
});

suite("open sort — the toggle");

// sortState()/painted() cross the vm boundary and carry the CONTEXT's
// prototype, so strict deepEqual fails on structurally identical values.
// Compare what the values ARE, not which realm made them.
const sortStr = () => { const s = sortState(); return s.key + ":" + s.dir; };

test("a new column always opens best-first, and re-clicking reverses it", () => {
  resetSort();
  assert.equal(sortStr(), "opened:-1");
  setOpenSort("r");
  assert.equal(sortStr(), "r:-1", "a new column opens BEST-first");
  setOpenSort("r");
  assert.equal(sortStr(), "r:1", "re-clicking the live column reverses");
  setOpenSort("usd");
  assert.equal(sortStr(), "usd:-1", "switching columns resets to best-first");
});

test("an unknown key is ignored rather than sorting by undefined", () => {
  resetSort(); setOpenSort("r");
  setOpenSort("../../etc/passwd");
  assert.equal(sortStr(), "r:-1");
});

test("one click repaints BOTH books and re-runs the live fill", () => {
  // The Me side's R/$ cells are painted by refreshLive, not by openRows, so a
  // re-render without it leaves them on placeholders.
  resetSort(); setOpenSort("usd");
  assert.equal(painted().join(","), "bot,me,refresh");
});

suite("open sort — pins on the shipped file");

test("openRows sorts through sortedOpen, not an inline comparator", () => {
  assert.ok(/const rows = sortedOpen\(list, side\)/.test(CODE),
    "openRows has gone back to sorting inline, so the toggle no longer reaches it");
});

test("both affordances are the same attribute, so they cannot drift apart", () => {
  // The section-title buttons and the clickable column headers are one control
  // wearing two hats. Two attributes would be two code paths and one of them
  // would rot.
  assert.ok(/data-osort="\$\{k\}"/.test(CODE), "the section-title control lost data-osort");
  assert.ok(/data-osort="\$\{key\}"/.test(CODE), "the column headers lost data-osort");
  assert.ok(/closest\("\[data-osort\]"\)/.test(CODE), "nothing listens for data-osort any more");
});

test("the header cell is reachable by a screen reader as a sort control", () => {
  assert.ok(/aria-sort=/.test(CODE), "the sortable headers no longer announce their state");
});

test("the sort is NOT persisted", () => {
  // Deliberate. A sort is a question you are asking right now, not a setting;
  // sticky "$ descending" would bury the newest position — the one most likely
  // to still need a decision — under a choice made weeks ago and forgotten.
  assert.ok(!/openSort[\s\S]{0,200}localStorage/.test(CODE),
    "the open sort is being persisted — see the note on openSort for why it is not");
  assert.ok(!/(jr_open_sort|open_sort|osort)["']\s*[,)]/.test(CODE.replace(/data-osort/g, "")),
    "a storage key for the open sort has appeared");
});

test("the sort control survives a re-render", () => {
  // openSort is module-scoped for exactly this reason: renderAll() re-enters
  // openRows from scratch every 3 minutes and a local would be thrown away.
  // Module scope inside the page's IIFE is exactly two spaces of indent;
  // anything nested inside a function is four or more.
  assert.ok(/\n  let openSort = /.test(CODE),
    "openSort is no longer at module scope — a re-render will throw the choice away");
  assert.ok(!/\n {4,}let openSort = /.test(CODE),
    "openSort has been moved inside a function and will not survive a re-render");
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
  assert.ok(Number(m[1]) >= 66,
    `journal.js?v=${m[1]} predates the Tier 2 money fixes and the open sort (need >= 66)`);
});

test("journal.html requests a journal.css new enough to style the sort control", () => {
  // Without it the control renders as three unstyled words in the section
  // title — still clickable, but it does not read as a control.
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  const m = html.match(/css\/journal\.css\?v=(\d+)/);
  assert.ok(m, "journal.html no longer version-stamps journal.css");
  assert.ok(Number(m[1]) >= 33, `journal.css?v=${m[1]} predates the sort control (need >= 33)`);
});

test("the sort hosts exist in the markup the control paints into", () => {
  const html = fs.readFileSync(path.resolve(__dirname, "../public/journal.html"), "utf8");
  for (const side of ["bot", "me"]) {
    assert.ok(html.includes(`id="${side}-open-sort"`),
      `#${side}-open-sort is gone — paintOpen silently no-ops and the control never appears`);
  }
});

test("the control is reachable on a phone, where the column headers are not", () => {
  // .jr-cardable thead is clipped to 1px below 680px, so the headers are
  // physically untappable there and this control is the ONLY way to sort.
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(/\.jr-osort-b/.test(code), "the sort control has no styling at all");
  const mobile = code.slice(code.indexOf("@media (max-width: 680px)"));
  assert.ok(/\.jr-osort-b\s*\{[^}]*min-height/.test(mobile),
    "the mobile tap target is back to its unpadded 23x21px, which is a miss waiting to happen");
});


// ── WHO DECIDED THE EXIT (2026-08-13) ────────────────────────────────────────
// The bot book is meant to be evidence about the FROZEN RULES. On the live book
// 21 of 40 closes are `manual` — the owner clicking Close — and every aggregate
// on the page pools them with the 19 the rules made. The two halves do not
// resemble each other: rules -6.97R over 19, owner +0.16R over 21. Read as one
// number they cancel into a shrug, and the strategy-review checkpoint has
// already been declared satisfied on the blend.
//
// These pins are about a CAVEAT, not a calculation: nothing here changes what
// stats() returns. What must not silently regress is the classification.
suite("who decided the exit");

const dctx = vm.createContext({ console });
vm.runInContext(
  "const esc = (s) => String(s);\n"
  + slice("const MECHANICAL_EXITS =", "];\n") + "\n"
  + slice("function deciderSplit(list) {", "\n  }") + "\n"
  + slice("function deciderHTML(list) {", "\n  }") + "\n"
  + "this.deciderSplit = deciderSplit; this.deciderHTML = deciderHTML;\n"
  + "this.MECHANICAL_EXITS = MECHANICAL_EXITS;\n", dctx);
const { deciderSplit, deciderHTML, MECHANICAL_EXITS } = dctx;

const cl = (reason, r) => ({ status: "closed", exit_reason: reason, realized_r: r });

test("the four mechanical reasons are exactly the four the engine writes", () => {
  // stop / time / trail / target are the frozen rules acting. Adding "manual"
  // to this list would erase the entire distinction in one edit, which is why
  // it is asserted by value rather than by length.
  assert.deepEqual([...MECHANICAL_EXITS].sort(), ["stop", "target", "time", "trail"]);
});

test("a stop-out is the rules, a manual close is not", () => {
  const s = deciderSplit([cl("stop", -1), cl("manual", 0.1)]);
  assert.equal(s.bot, 1); assert.equal(s.own, 1);
  assert.equal(s.botR, -1); assert.ok(Math.abs(s.ownR - 0.1) < 1e-9);
});

test("the 28-day time-stop counts as the BOT — it is the rule firing, not a human", () => {
  const s = deciderSplit([cl("time", 0.2)]);
  assert.equal(s.bot, 1, "a time-stop is a mechanical exit");
  assert.equal(s.own, 0);
});

test("an ABSENT exit_reason counts as manual, matching how the row renders", () => {
  // closedRows falls back to "manual" for a missing value; the split must agree
  // or the caveat would describe a different set than the table beneath it.
  const s = deciderSplit([{ status: "closed", realized_r: 0.5 }]);
  assert.equal(s.own, 1); assert.equal(s.bot, 0);
});

test("case and whitespace do not smuggle a manual close into the bot's evidence", () => {
  assert.equal(deciderSplit([cl("STOP", -1)]).bot, 1);
  assert.equal(deciderSplit([cl(" Time ", 1)]).bot, 0, "a padded value is not silently trusted");
});

test("open rows are never counted — this is a caveat on the CLOSED table", () => {
  const s = deciderSplit([{ status: "open", exit_reason: "stop", realized_r: 9 }, cl("stop", -1)]);
  assert.equal(s.n, 1); assert.equal(s.botR, -1);
});

test("a missing realized_r contributes 0 rather than NaN-ing the whole sum", () => {
  // A NaN here would make every later comparison false and the caveat would
  // read "+NaNR" — the same disarm-by-NaN failure the guards fixed in Tier 1.
  const s = deciderSplit([cl("stop", undefined), cl("stop", -2)]);
  assert.equal(s.botR, -2);
});

test("the line is SILENT when the book is one-sided", () => {
  // A caveat that always shows stops being read. Nothing to disambiguate when
  // every close came from the same decider.
  assert.equal(deciderHTML([cl("stop", -1), cl("time", 1)]), "", "all-mechanical needs no caveat");
  assert.equal(deciderHTML([cl("manual", 1)]), "", "all-manual needs no caveat");
  assert.equal(deciderHTML([]), "");
});

test("and it SPEAKS, with both counts and both R totals, when they are mixed", () => {
  const h = deciderHTML([cl("stop", -3), cl("stop", -1), cl("manual", 0.5)]);
  assert.ok(h.includes("<b>2</b>") && h.includes("-4.00R"), `bot side missing: ${h}`);
  assert.ok(h.includes("<b>1</b>") && h.includes("+0.50R"), `owner side missing: ${h}`);
  assert.ok(/pool both/.test(h), "must say the stats below pool both");
});

test("renderSide actually prints it above the closed table", () => {
  // A caveat computed and never rendered is not a caveat.
  assert.ok(/deciderHTML\(d\.closed\) \+ closedRows\(d\.closed, side\)/.test(SRC),
    "renderSide no longer prefixes the closed table with the decider split");
});

test("journal.css gives BOTH previously-unstyled reasons a rule", () => {
  // Before this, .jr-reason-manual and .jr-reason-time did not exist, so the
  // bot's time-stop and the owner's click rendered as the same grey chip.
  const css = fs.readFileSync(path.resolve(__dirname, "../public/css/journal.css"), "utf8");
  assert.ok(/\.jr-reason-time\s*\{/.test(css), ".jr-reason-time has no rule");
  assert.ok(/\.jr-reason-manual\s*\{/.test(css), ".jr-reason-manual has no rule");
  for (const c of ["target", "trail", "stop"]) {
    assert.ok(new RegExp(`\\.jr-reason-${c}\\s*\\{`).test(css), `.jr-reason-${c} was dropped`);
  }
});


// ── w3-1 progress line (2026-08-15) ─────────────────────────────────────────
// The one number that decides everything — the pre-registered cycle's progress
// to its 30-close readout — lived only in raw book JSON. One quiet line now
// renders above the bot stats. These pins hold its honesty properties.
suite("w3-1 progress line");

const w3ctx = vm.createContext({ console });
vm.runInContext(slice("function w3Line(d) {", "\n  }") + "\nthis.w3Line = w3Line;", w3ctx);
const { w3Line } = w3ctx;
const w3row = (cycle) => (cycle ? { cycle } : {});

test("counts stamped open and stamped closes, and states the /30 target", () => {
  const h = w3Line({ open: [w3row("w3-1"), w3row("w3-1"), w3row()], closed: [w3row("w3-1"), w3row()] });
  assert.ok(h.includes("<b>2</b>"), "stamped-open count wrong");
  assert.ok(h.includes("<b>1/30</b>"), "gated-close count must be stated against the 30-close readout");
});

test("SILENT when nothing carries the stamp — fixtures, pre-cycle books, the manual side", () => {
  assert.equal(w3Line({ open: [w3row()], closed: [w3row()] }), "");
  assert.equal(w3Line({ open: [], closed: [] }), "");
});

test("a different cycle tag is not counted as w3-1", () => {
  // The audit-tag design (config: VIVEK_BOT_CYCLE_TAG) allows future cycles;
  // a w4 row leaking into the w3 line would blur exactly the cohorts the
  // stamp exists to keep apart.
  assert.equal(w3Line({ open: [w3row("w4-1")], closed: [] }), "");
});

test("renderSide injects it above the bot stats, and re-render does not duplicate", () => {
  assert.ok(/document\.querySelectorAll\("#bot-w3"\)\.forEach\(\(el\) => el\.remove\(\)\);/.test(SRC),
    "the remove-before-insert guard is gone - every refresh would stack another line");
  assert.ok(/host\.insertAdjacentHTML\("beforebegin", w3Line\(d\)\)/.test(SRC),
    "renderSide no longer renders the w3 line");
});

// ---------------------------------------------------------------------------
test("the fired review checkpoint states the BLEND, and reads as the owner's call", () => {
  // Lane A (2026-08-16). It used to read "✅ Review checkpoint reached — time
  // to review", which celebrates a threshold and invites reading ONE combined
  // record. A 30+ close book is two records: measured at head, 19 closes by
  // the rules at -6.97R against 23 owner closes at -0.15R. Judging the blend
  // as if one system produced it is how a rules problem gets blamed on the
  // market. Pre-30 wording is deliberately untouched — nothing is decided yet.
  const src = fs.readFileSync(path.join(__dirname, "..", "public", "js", "journal.js"), "utf8");
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.ok(/const sp = deciderSplit\(state\.bot\.closed\)/.test(code),
    "the checkpoint must derive the split from the SHIPPED deciderSplit, not recount");
  assert.ok(/\$\{sp\.bot\} by the rules, \$\{sp\.own\} closed by you/.test(code),
    "the fired line must name both records");
  assert.ok(/your call, nothing is locked now/.test(code),
    "it must hand the decision back rather than instruct");
  assert.ok(!/✅ Review checkpoint reached/.test(code),
    "the celebratory tick is back on the one line that needs careful reading");
  assert.ok(/stay locked until then/.test(code),
    "the PRE-30 wording must be untouched — the gate itself has not moved");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);


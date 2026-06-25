#!/usr/bin/env node
/* Unit tests for risk_manager.js — the enforceable risk engine.
   Run with: node test/risk_manager.test.js
   No external dependencies — Node.js built-ins only.

   Covers the four rules the dashboard must actually enforce:
     1. TP1 → scale 25% → move stop to break-even (risk-free runner)
     2. 3 consecutive losses → hard stop (reset only on win / manual)
     3. Weekly+3D bias filter blocks counter-trend entries
     4. 0.25% per-trade sizing + portfolio-level open-risk cap
*/
"use strict";
const assert = require("assert").strict;
const path = require("path");
const RiskManager = require(path.resolve(__dirname, "../public/js/risk_manager.js"));

// ── in-memory localStorage stub so persistence paths are exercised ───────────
function makeStorage() {
  let data = {};
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    clear() { data = {}; },
    _dump() { return data; },
  };
}
// Fresh engine helper (silent, isolated storage).
function mk(cfg) {
  return new RiskManager(Object.assign({ equity: 10000, verbose: false, storage: makeStorage() }, cfg));
}

// ── tiny runner ──────────────────────────────────────────────────────────────
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find(l => l.includes("risk_manager.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(n) { console.log(`\n── ${n} ──`); }

// ═════════════════════════ 1. POSITION SIZING (0.25%) ════════════════════════
suite("position sizing — 0.25% of equity");

test("default max risk per trade is 0.25%", () => {
  assert.equal(mk().config.maxRiskPerTradePct, 0.25);
});

test("/NQ at $20/pt, 50pt stop → risk = 0.25% of 10k = $25 budget", () => {
  const r = mk().calculatePositionSize("/NQ", 50);
  assert.equal(r.maxRiskUsd, 25);            // 10000 * 0.0025 * 1.0
  // riskPerUnit = 50 * 20 = 1000 → rawUnits 0.025 → floored to 0.02
  assert.equal(r.riskPerUnit, 1000);
  assert.equal(r.recommendedUnits, 0.02);
  assert.ok(r.actualRiskUsd <= r.maxRiskUsd + 1e-9, "actual risk must not exceed budget");
});

test("sizing scales with equity", () => {
  const e = mk({ equity: 40000 });
  const r = e.calculatePositionSize("/NQ", 50);
  assert.equal(r.maxRiskUsd, 100);           // 40000 * 0.0025
});

test("volatility factor shrinks NatGas budget", () => {
  const r = mk().calculatePositionSize("NG", 0.05);
  assert.equal(r.maxRiskUsd, 10);            // 10000 * 0.0025 * 0.4
});

test("alias 'Gold' resolves to GC", () => {
  const r = mk().calculatePositionSize("Gold", 20);
  assert.equal(r.spec, "GC");
});

test("never sizes above the budget (floor, not round)", () => {
  const r = mk().calculatePositionSize("GC", 7);   // 7*100=700/u, 25/700=0.0357
  assert.equal(r.recommendedUnits, 0.03);          // floored, not 0.04
  assert.ok(r.actualRiskUsd <= r.maxRiskUsd);
});

test("unknown instrument returns an error, never throws", () => {
  const r = mk().calculatePositionSize("ZZZ", 10);
  assert.ok(r.error);
  assert.equal(r.recommendedUnits, 0);
});

// ═════════════════════════ 2. CONSECUTIVE-LOSS HARD STOP ═════════════════════
suite("consecutive-loss hard stop");

test("3 losses block new entries", () => {
  const e = mk();
  assert.equal(e.canEnterNewTrade().allowed, true);
  e.registerTradeClosed(-100);
  e.registerTradeClosed(-100);
  assert.equal(e.canEnterNewTrade().allowed, true, "2 losses still OK");
  e.registerTradeClosed(-100);
  const g = e.canEnterNewTrade();
  assert.equal(g.allowed, false);
  assert.equal(g.code, RiskManager.REASON.CONSECUTIVE_LOSS_LIMIT);
});

test("a win resets the counter and re-enables entries", () => {
  const e = mk();
  e.registerTradeClosed(-100); e.registerTradeClosed(-100); e.registerTradeClosed(-100);
  assert.equal(e.canEnterNewTrade().allowed, false);
  e.registerTradeClosed(+250);
  assert.equal(e.getCurrentRiskState().consecutiveLossCount, 0);
  assert.equal(e.canEnterNewTrade().allowed, true);
});

test("break-even trade leaves the counter unchanged", () => {
  const e = mk();
  e.registerTradeClosed(-100);
  e.registerTradeClosed(0);
  assert.equal(e.getCurrentRiskState().consecutiveLossCount, 1);
});

test("state flags: isWarning at 2, isPausedByLosses at 3", () => {
  const e = mk();
  e.registerTradeClosed(-1); e.registerTradeClosed(-1);
  assert.equal(e.getCurrentRiskState().isWarning, true);
  e.registerTradeClosed(-1);
  assert.equal(e.getCurrentRiskState().isPausedByLosses, true);
});

test("counter + kill state persist across a reload", () => {
  const store = makeStorage();
  const a = new RiskManager({ equity: 10000, verbose: false, storage: store });
  a.registerTradeClosed(-1); a.registerTradeClosed(-1); a.registerTradeClosed(-1);
  const b = new RiskManager({ equity: 10000, verbose: false, storage: store });
  assert.equal(b.getCurrentRiskState().consecutiveLossCount, 3);
  assert.equal(b.canEnterNewTrade().allowed, false);
});

test("kill switch blocks independently of the loss counter", () => {
  const e = mk();
  e.activateKillSwitch("news", "Closed all");
  const g = e.canEnterNewTrade();
  assert.equal(g.allowed, false);
  assert.equal(g.code, RiskManager.REASON.KILL_SWITCH);
  e.deactivateKillSwitch();
  assert.equal(e.canEnterNewTrade().allowed, true);
});

// ═════════════════════════ 3. WEEKLY+3D BIAS FILTER ══════════════════════════
suite("Weekly+3D bias filter");

test("no bias set → not filtered (allowed, strength unknown)", () => {
  const a = mk().checkBiasAlignment("/NQ", "long");
  assert.equal(a.aligned, true);
  assert.equal(a.strength, "unknown");
});

test("bias bull+bull → long aligned, short blocked", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  assert.equal(e.checkBiasAlignment("/NQ", "long").strength, "aligned");
  const s = e.checkBiasAlignment("/NQ", "short");
  assert.equal(s.aligned, false);
  assert.equal(s.strength, "counter");
});

test("one TF neutral → partial alignment (allowed, flagged)", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "neutral" });
  const a = e.checkBiasAlignment("/NQ", "long");
  assert.equal(a.aligned, true);
  assert.equal(a.strength, "partial");
});

test("evaluateEntry blocks a counter-trend entry with BIAS_CONFLICT", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  const d = e.evaluateEntry({ symbol: "/NQ", direction: "short", entry: 20000, stop: 20100, units: 0.02 });
  assert.equal(d.allowed, false);
  assert.equal(d.code, RiskManager.REASON.BIAS_CONFLICT);
});

test("evaluateEntry allows a with-trend entry", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  const d = e.evaluateEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, units: 0.02 });
  assert.equal(d.allowed, true);
});

// ═════════════════════════ 4. TP1 → BREAK-EVEN ══════════════════════════════
suite("TP1 → scale 25% → break-even");

const longPos = { symbol: "/NQ", direction: "long", entry: 20000, stop: 19800, tp1: 20200, target: 20600, size_units: 0.5, point_value: 20 };

test("price below TP1 → stop unchanged, full risk on", () => {
  const e = mk();
  e.loadPositions([longPos]);
  e.onPrice("/NQ", 20100);
  const p = e.getOpenPositions()[0];
  assert.equal(p.tp1Hit, false);
  assert.equal(p.stop, 19800);
});

test("price reaches TP1 → stop jumps to break-even (entry)", () => {
  const e = mk();
  e.loadPositions([longPos]);
  const res = e.onPrice("/NQ", 20200);
  assert.equal(res.event, "tp1_breakeven");
  const p = e.getOpenPositions()[0];
  assert.equal(p.tp1Hit, true);
  assert.equal(p.stopAtBreakeven, true);
  assert.equal(p.stop, p.entry, "stop must equal entry after TP1");
  assert.equal(p.remainingFraction, 0.75, "25% scaled out");
});

test("open risk drops to ~0 once the runner is at break-even", () => {
  const e = mk();
  e.loadPositions([longPos]);
  assert.ok(e.getOpenRiskUsd() > 0, "risk on before TP1");
  e.onPrice("/NQ", 20250);
  assert.equal(e.getOpenRiskUsd(), 0, "risk-free runner → zero open risk");
});

test("short position: TP1 below entry triggers break-even", () => {
  const e = mk();
  e.loadPositions([{ symbol: "CL", direction: "short", entry: 71.4, stop: 73.1, tp1: 69.8, target: 67.2, size_units: 15, point_value: 1 }]);
  e.onPrice("CL", 69.7);
  const p = e.getOpenPositions()[0];
  assert.equal(p.stopAtBreakeven, true);
  assert.equal(p.stop, 71.4);
});

test("TP1 fires only once (idempotent on further ticks)", () => {
  const e = mk();
  e.loadPositions([longPos]);
  assert.equal(e.onPrice("/NQ", 20200).event, "tp1_breakeven");
  assert.equal(e.onPrice("/NQ", 20300).event, null);
});

test("loadPositions re-applies BE if price already past TP1", () => {
  const e = mk();
  e.loadPositions([Object.assign({}, longPos, { current: 20400 })]);
  const p = e.getOpenPositions()[0];
  assert.equal(p.stopAtBreakeven, true);
});

// ═════════════════════════ 5. PORTFOLIO RISK + ADD-ONS ══════════════════════
suite("portfolio risk cap + multiple entries");

test("open risk aggregates across positions", () => {
  const e = mk();
  e.loadPositions([
    { symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, target: 20600, size_units: 0.1, point_value: 20 }, // 100*20*0.1=200
    { symbol: "GC", direction: "long", entry: 2640, stop: 2620, target: 2728, size_units: 0.1, point_value: 100 },     // 20*100*0.1=200
  ]);
  assert.equal(e.getOpenRiskUsd(), 400);
  assert.equal(e.getOpenRiskPct(), 4);  // of 10k
});

test("entry blocked when it would breach the portfolio cap", () => {
  const e = mk({ maxPortfolioRiskPct: 2.0 }); // cap = $200 on 10k
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.loadPositions([{ symbol: "GC", direction: "long", entry: 2640, stop: 2620, target: 2728, size_units: 0.09, point_value: 100 }]); // risk 180
  const d = e.evaluateEntry({ symbol: "/NQ", direction: "long", riskUsd: 50 }); // 180+50=230 > 200
  assert.equal(d.allowed, false);
  assert.equal(d.code, RiskManager.REASON.PORTFOLIO_RISK_LIMIT);
});

test("a position at break-even frees portfolio budget for a new entry", () => {
  const e = mk({ maxPortfolioRiskPct: 2.0 }); // cap $200
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.loadPositions([{ symbol: "GC", direction: "long", entry: 2640, stop: 2620, tp1: 2680, target: 2728, size_units: 0.09, point_value: 100 }]); // risk 180
  let d = e.evaluateEntry({ symbol: "/NQ", direction: "long", riskUsd: 50 });
  assert.equal(d.allowed, false, "blocked while GC carries 180 risk");
  e.onPrice("GC", 2680);  // GC hits TP1 → BE → its open risk → 0
  d = e.evaluateEntry({ symbol: "/NQ", direction: "long", riskUsd: 50 });
  assert.equal(d.allowed, true, "now allowed — GC is risk-free");
});

test("max-positions cap blocks a brand-new symbol", () => {
  const e = mk({ maxPositions: 2, maxPortfolioRiskPct: 99 });
  e.loadPositions([
    { symbol: "/NQ", direction: "long", entry: 20000, stop: 19990, target: 20600, size_units: 0.01, point_value: 20 },
    { symbol: "GC", direction: "long", entry: 2640, stop: 2639, target: 2728, size_units: 0.01, point_value: 100 },
  ]);
  const d = e.evaluateEntry({ symbol: "CL", direction: "long", riskUsd: 5 });
  assert.equal(d.allowed, false);
  assert.equal(d.code, RiskManager.REASON.MAX_POSITIONS);
});

test("add-on to an existing symbol: weighted-avg entry, summed units, entry_count++", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, target: 20600, units: 0.1 });
  const r = e.addEntry({ symbol: "/NQ", direction: "long", entry: 20100, stop: 19950, target: 20600, units: 0.1 });
  assert.equal(r.committed, true);
  const p = e.getOpenPositions()[0];
  assert.equal(p.entryCount, 2);
  assert.equal(p.units, 0.2);
  assert.equal(p.entry, 20050); // weighted avg of equal-size legs
});

test("add-on does NOT count against the max-positions cap", () => {
  const e = mk({ maxPositions: 1, maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, target: 20600, units: 0.1 });
  const r = e.addEntry({ symbol: "/NQ", direction: "long", entry: 20100, stop: 19950, target: 20600, units: 0.1 });
  assert.equal(r.committed, true, "add-on allowed even at max positions");
});

test("closePosition books P/L (net of fees) and feeds the loss counter", () => {
  const e = mk({ maxPortfolioRiskPct: 99 }); // default roundTurnFeeUsd = $2
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, target: 20600, units: 0.1 });
  const r = e.closePosition("/NQ", 19900); // -100 pts * 20 * 0.1 = -$200 gross
  assert.equal(r.gross, -200, "gross before fees");
  assert.equal(r.costs, 2, "round-turn fee booked");
  assert.equal(r.netPnl, -202, "net = gross − fees");
  assert.equal(e.getCurrentRiskState().consecutiveLossCount, 1);
  assert.equal(e.positionCount(), 0);
});

test("closePosition produces a journal entry with time, duration, fees, P/L, R", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("GC", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "GC", direction: "long", entry: 2600, stop: 2590, target: 2630, units: 0.1, dollarsPerPoint: 100 });
  const r = e.closePosition("GC", 2620, { reason: "Target hit" });
  const je = r.journalEntry;
  assert.ok(je, "journal entry returned");
  assert.equal(je.symbol, "GC");
  assert.equal(je.exit, 2620);
  assert.equal(je.gross, 200, "20 pts * $100 * 0.1 = $200");
  assert.equal(je.costs, 2);
  assert.equal(je.net, 198);
  assert.equal(je.r, 2, "20 pt gain / 10 pt initial risk = 2R");
  assert.equal(je.win, true);
  assert.equal(je.reason, "Target hit");
  assert.ok(je.opened && je.closed, "start + close timestamps present");
  assert.ok(typeof je.durationMs === "number", "duration computed");
});

test("closePosition R-multiple uses the INITIAL stop, not the break-even stop", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  // entry 20000, initial stop 19900 (100 pt risk), tp1 at 20100
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, tp1: 20100, target: 20400, units: 0.1 });
  e.onPrice("/NQ", 20100); // TP1 → stop moves to break-even (20000)
  const r = e.closePosition("/NQ", 20200); // +200 pts gross
  // R must be measured off the 100 pt initial risk, not the 0-risk BE stop.
  assert.equal(r.r, 2, "200 pt gain / 100 pt initial risk = 2R (not div-by-zero)");
});

suite("live price feed (onPrices batch) + persist hook");

test("onPrices applies a batch and fires TP1→BE per symbol", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.setBias("GC", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, tp1: 20100, target: 20400, units: 0.1 });
  e.addEntry({ symbol: "GC", direction: "long", entry: 2600, stop: 2590, tp1: 2620, target: 2660, units: 0.1, dollarsPerPoint: 100 });
  const fired = e.onPrices({ "/NQ": 20100, "GC": 2605 }); // only /NQ reaches TP1
  assert.deepEqual(fired, ["/NQ"]);
  assert.equal(e.getOpenPositions().find(p => p.symbol === "/NQ").stopAtBreakeven, true);
  assert.equal(e.getOpenPositions().find(p => p.symbol === "GC").stopAtBreakeven, false);
});

test("setPersistHook receives the journalEntry on close (backend-ready)", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  let captured = null;
  e.setPersistHook(entry => { captured = entry; });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, target: 20400, units: 0.1 });
  e.closePosition("/NQ", 20100, { reason: "Target hit" });
  assert.ok(captured, "persist hook fired");
  assert.equal(captured.symbol, "/NQ");
  assert.equal(captured.reason, "Target hit");
  assert.ok(captured.opened !== undefined && captured.net !== undefined, "entry carries timing + P/L");
});

suite("portfolio intelligence layer");

test("flat book is neutral (~50 health, no open risk)", () => {
  const e = mk();
  const h = e.getBookHealth();
  assert.equal(h.positionCount, 0);
  assert.equal(h.openRiskUsd, 0);
  assert.equal(h.healthScore, 50);
  assert.equal(e.getPortfolioStance(h).stance, "neutral");
});

test("getBookHealth separates risk-free runners from risk-on positions", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.setBias("GC", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, tp1: 20100, target: 20400, units: 0.1 });
  e.addEntry({ symbol: "GC", direction: "long", entry: 2600, stop: 2590, tp1: 2620, target: 2660, units: 0.1, dollarsPerPoint: 100 });
  e.onPrice("/NQ", 20100); // → break-even (risk-free)
  const h = e.getBookHealth();
  assert.equal(h.positionCount, 2);
  assert.equal(h.riskFreeCount, 1, "/NQ is now risk-free");
  assert.equal(h.riskOnCount, 1, "GC still carries risk");
});

test("a strong de-risked book reads AGGRESSIVE", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.setBias("GC", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, tp1: 20100, target: 20400, units: 0.1 });
  e.addEntry({ symbol: "GC", direction: "long", entry: 2600, stop: 2590, tp1: 2620, target: 2660, units: 0.1, dollarsPerPoint: 100 });
  e.onPrice("/NQ", 20200); // both to BE + in profit
  e.onPrice("GC", 2630);
  const s = e.getPortfolioStance();
  assert.equal(s.stance, "aggressive");
  assert.ok(s.healthScore >= 68, "health should clear the aggressive threshold");
});

test("a break-even runner that turns counter-trend is flagged weak → defensive", () => {
  const e = mk({ maxPortfolioRiskPct: 99 });
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  e.addEntry({ symbol: "/NQ", direction: "long", entry: 20000, stop: 19900, tp1: 20100, target: 20400, units: 0.1 });
  e.onPrice("/NQ", 20100);              // runner at break-even
  e.setBias("/NQ", { weekly: "bear", threeDay: "bear" }); // HTF flips against it
  const h = e.getBookHealth();
  assert.deepEqual(h.weakRunners, ["/NQ"]);
  const runners = e.reviewRunners();
  assert.equal(runners[0].status, "weak");
  assert.equal(runners[0].action, "scale_out");
  assert.equal(e.getPortfolioStance(h).stance, "defensive");
});

test("warning state (one loss from the hard stop) forces DEFENSIVE", () => {
  const e = mk(); // maxConsecutiveLosses = 3
  e.registerTradeClosed(-100);
  e.registerTradeClosed(-100); // 2 losses → warning
  assert.equal(e.getPortfolioStance().stance, "defensive");
});

test("hard stop → posture LOCKED", () => {
  const e = mk();
  for (let i = 0; i < 3; i++) e.registerTradeClosed(-100);
  assert.equal(e.getPortfolioStance().stance, "locked");
});

test("adviseEntry NEVER overrides a hard block (3-loss stop)", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  for (let i = 0; i < 3; i++) e.registerTradeClosed(-100);
  const d = e.adviseEntry({ symbol: "/NQ", direction: "long", riskUsd: 10 });
  assert.equal(d.allowed, false);
  assert.equal(d.hard, true, "block is a HARD rule, not a soft stance defer");
  assert.equal(d.code, "CONSECUTIVE_LOSS_LIMIT");
});

test("adviseEntry passes a bias conflict straight through as a hard block", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  const d = e.adviseEntry({ symbol: "/NQ", direction: "short", riskUsd: 10 });
  assert.equal(d.allowed, false);
  assert.equal(d.hard, true);
  assert.equal(d.code, "BIAS_CONFLICT");
});

test("defensive book DEFERS a partial-bias entry (soft, not hard)", () => {
  const e = mk();
  e.registerTradeClosed(-100); e.registerTradeClosed(-100); // → defensive (warning)
  e.setBias("GC", { weekly: "bull", threeDay: "neutral" }); // partial alignment
  const d = e.adviseEntry({ symbol: "GC", direction: "long", riskUsd: 5 });
  assert.equal(d.allowed, false);
  assert.equal(d.hard, false, "soft stance defer, not a hard rule break");
  assert.equal(d.code, "STANCE_DEFERRED");
  assert.equal(d.stance, "defensive");
});

test("neutral book endorses a clean, in-budget entry with a size multiplier", () => {
  const e = mk();
  e.setBias("/NQ", { weekly: "bull", threeDay: "bull" });
  const d = e.adviseEntry({ symbol: "/NQ", direction: "long", riskUsd: 10 });
  assert.equal(d.allowed, true);
  assert.equal(d.hard, false);
  assert.equal(d.stance, "neutral");
  assert.equal(d.sizeMult, 1, "neutral does not size down");
  assert.ok(d.bookSummary, "carries an observable book summary");
});

test("stance soft-cap is always ≤ the hard portfolio cap", () => {
  const e = mk(); // equity 10000, maxPortfolioRiskPct 2 → hard cap $200
  const s = e.getPortfolioStance();
  assert.ok(s.effectiveCapUsd <= 200 + 1e-6, "soft cap never exceeds the hard cap");
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) { console.error(`FAILED  ${failed} failed, ${passed} passed`); process.exit(1); }
else { console.log(`ALL ${passed} risk-engine tests passed`); }

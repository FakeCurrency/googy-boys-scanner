#!/usr/bin/env node
/* Parity tests for the cloud watcher's VIVEK scale-out management
   (functions/api/_vivek_manage.js) — the exact module tick.js runs.
   These pin the behaviours that were hand-verified when the watcher gained
   client parity: TP fills at the LEVEL (resting limit, no overshoot credit),
   honest gap fills on stops, the chased-entry valid() guard, SL trailing
   (break-even at TP1, TP1 at TP2), leverage-capped risk sizing, the cost
   model, and full long/short symmetry. Drift here = wrong P&L in every
   synced journal. Run with: node test/vivek_manage.test.js
*/
"use strict";
const assert = require("assert").strict;

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("vivek_manage.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

const NP = { date: "2026-07-16", time: "10:00" };

function longTrade(over) {
  return Object.assign({
    symbol: "XYZ", market: "asx", direction: "long", status: "open",
    entry: 100, stop: 96, tp1: 106, tp2: 112, tp3: 120,
  }, over || {});
}
function shortTrade(over) {
  return Object.assign({
    symbol: "XYZ", market: "asx", direction: "short", status: "open",
    entry: 100, stop: 104, tp1: 94, tp2: 88, tp3: 80,
  }, over || {});
}

import("../functions/api/_vivek_manage.js").then((M) => {
  const { VK, isVivek, vkMarket, vkSizeRiskUsd, manageVivek, vkFinalize } = M;

  suite("recognition + market mapping");
  test("isVivek needs stop and tp1", () => {
    assert.ok(isVivek(longTrade()));
    assert.ok(!isVivek({ stop: 1 }));
    assert.ok(!isVivek(null));
  });
  test("vkMarket maps asset types to cost tiers", () => {
    assert.equal(vkMarket({ market: "asx" }), "asx");
    assert.equal(vkMarket({ asset_type: "crypto" }), "crypto");
    assert.equal(vkMarket({ market: "commodity" }), "nasdaq");
  });

  suite("risk sizing");
  test("plain risk = equity x 0.35%", () => {
    assert.ok(Math.abs(vkSizeRiskUsd("asx", 100, 96) - 35) < 1e-9);
  });
  test("tight stop caps risk at max leverage notional", () => {
    // stop 0.05% away: uncapped units would be 70,000 notional > 50k cap
    const r = vkSizeRiskUsd("asx", 100, 99.95);
    assert.ok(Math.abs(r - 25) < 1e-9, `expected 25, got ${r}`);  // (50000/100)*0.05
  });
  test("crypto caps at 3x", () => {
    const r = vkSizeRiskUsd("crypto", 100, 99.95);
    assert.ok(Math.abs(r - 15) < 1e-9, `expected 15, got ${r}`);  // (30000/100)*0.05
  });

  suite("TP ladder — fills at the LEVEL, no overshoot credit");
  test("TP1 books 25% at the level and SL moves to break-even", () => {
    const t = longTrade();
    const r = manageVivek(t, 107.5, NP);        // price overshot TP1
    assert.equal(r, "book");
    assert.equal(t.tp1_hit, true);
    assert.equal(t.exits[0].price, 106);        // level, not 107.5
    assert.equal(t.exits[0].pct, 0.25);
    assert.equal(t.stop, 100);                  // break-even
    assert.equal(t.gross_r, +(0.25 * (106 - 100) / 4).toFixed(4));
  });
  test("TP2 books 50% and SL moves to TP1", () => {
    const t = longTrade();
    manageVivek(t, 113, NP);                    // sweeps TP1+TP2 in one tick
    assert.equal(t.tp2_hit, true);
    assert.equal(t.booked_pct, 0.75);
    assert.equal(t.stop, 106);
  });
  test("TP3 books 15%, 10% runner remains", () => {
    const t = longTrade();
    manageVivek(t, 121, NP);
    assert.equal(t.tp3_hit, true);
    assert.equal(+t.booked_pct.toFixed(2), 0.9);
    assert.equal(t.status, "open");             // runner still on
  });

  suite("stops — honest fills");
  test("stop hit closes remainder at the stop", () => {
    const t = longTrade();
    const r = manageVivek(t, 96, NP);
    assert.equal(r, "close");
    assert.equal(t.exit, 96);
    assert.equal(t.exit_reason, "stop");
    assert.ok(Math.abs(t.gross_r - -1) < 1e-9);
  });
  test("gap through the stop fills at the WORSE gapped price", () => {
    const t = longTrade();
    manageVivek(t, 92, NP);                     // gapped 4% through
    assert.equal(t.exit, 92);                   // never better than stop... never AT stop when gapped
    assert.equal(t.gross_r, -2);                // (92-100)/4
  });
  test("stop after TP1 = trail exit, break-even remainder", () => {
    const t = longTrade();
    manageVivek(t, 106.5, NP);                  // TP1 books, SL -> 100
    const r = manageVivek(t, 100, NP);          // trail tagged
    assert.equal(r, "close");
    assert.equal(t.exit_reason, "trail");
    assert.equal(+t.booked_pct.toFixed(2), 1);
    // gross = 0.25*1.5R (tp1) + 0.75*0R (breakeven) = 0.375
    assert.ok(Math.abs(t.gross_r - 0.375) < 1e-6, `gross_r ${t.gross_r}`);
  });
  test("stop after TP3 = target exit", () => {
    const t = longTrade();
    manageVivek(t, 121, NP);
    manageVivek(t, 106, NP);                    // trail down to SL at TP1
    assert.equal(t.exit_reason, "target");
  });

  suite("chased-entry guard (valid())");
  test("TP below a chased long entry never books", () => {
    const t = longTrade({ entry: 108 });        // chased above TP1
    const r = manageVivek(t, 107, NP);          // "reaches" tp1=106 but invalid
    assert.equal(r, false);
    assert.equal(t.tp1_hit, false);
  });

  suite("cost model parity");
  test("full stop-out cost matches the client formula", () => {
    const t = longTrade();
    manageVivek(t, 96, NP);
    // entry leg: 100*(5+2)bps=0.07; stop exit leg: 1*96*(2+5)bps=0.0672
    // cost_r = (0.07+0.0672)/4 = 0.0343
    assert.equal(t.cost_r, 0.0343);
    assert.equal(t.realized_r, +(-1 - 0.0343).toFixed(4));
  });
  test("TP legs pay commission only (resting limit, no slippage)", () => {
    const t = longTrade();
    manageVivek(t, 106.5, NP);
    // entry leg 0.07 + tp1 leg 0.25*106*2bps=0.0053 → /4 = 0.0188
    assert.equal(t.cost_r, 0.0188);
  });

  suite("short symmetry");
  test("short TP ladder books down-moves with short scale", () => {
    const t = shortTrade();
    manageVivek(t, 93, NP);                     // through tp1=94
    assert.equal(t.tp1_hit, true);
    assert.equal(t.exits[0].pct, VK.SCALE.short[0]);   // 0.50 first leg
    assert.equal(t.stop, 100);                  // break-even downwards
  });
  test("short stop gap fills worse (higher)", () => {
    const t = shortTrade();
    manageVivek(t, 106, NP);
    assert.equal(t.exit, 106);
    assert.equal(t.gross_r, -1.5);              // (100-106)/4
  });
  test("short chased below tp1 never books", () => {
    const t = shortTrade({ entry: 93 });        // chased below tp1=94
    assert.equal(manageVivek(t, 93.5, NP), false);
  });

  suite("idempotence + non-VIVEK safety");
  test("second tick at the same TP books nothing new", () => {
    const t = longTrade();
    manageVivek(t, 106.5, NP);
    const n = t.exits.length;
    assert.equal(manageVivek(t, 106.5, NP), false);
    assert.equal(t.exits.length, n);
  });
  test("closed trades are untouched", () => {
    const t = longTrade({ status: "closed" });
    assert.equal(manageVivek(t, 50, NP), false);
  });
  test("finalize is stable when re-run", () => {
    const t = longTrade();
    manageVivek(t, 96, NP);
    const r1 = t.realized_r;
    vkFinalize(t);
    assert.equal(t.realized_r, r1);
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}).catch((e) => { console.error("could not load _vivek_manage.js:", e); process.exit(1); });

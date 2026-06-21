#!/usr/bin/env node
/* Pure-function unit tests for gbs-sync.js, chart.js, and journal.js.
   Run with: node test/unit.test.js
   No external dependencies — only Node.js built-ins required.
*/
"use strict";
const assert = require("assert").strict;
const fs     = require("fs");
const path   = require("path");
const vm     = require("vm");

// ─────────────────────────────── test runner ─────────────────────────────────
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) {
    const loc = (e.stack || "").split("\n").slice(1).find((l) => l.includes("unit.test.js"));
    console.error(`  ✗  ${name}\n     ${e.message}${loc ? "\n     " + loc.trim() : ""}`);
    failed++;
  }
}
function suite(name) { console.log(`\n── ${name} ──`); }

// ─────────────────── load gbs-sync.js into a vm context ─────────────────────
const mockLocalStorage = (() => {
  let data = {};
  return {
    getItem(k)    { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    clear()       { data = {}; },
  };
})();
const mockWindow = { dispatchEvent() {} };
const gbsCtx = vm.createContext({ window: mockWindow, localStorage: mockLocalStorage });
vm.runInContext(
  fs.readFileSync(path.resolve(__dirname, "../public/js/gbs-sync.js"), "utf8"),
  gbsCtx,
);
const { normalize, merge, saveLocal, load } = gbsCtx.window.GBSSync;

// ── pure math extracted from chart.js / journal.js (no DOM needed) ───────────

// Mirrors journal.js mjCalc exactly.
function mjCalc(t, brokerage) {
  if (t.status !== "closed" || t.exit == null) return { pnl: null, r: null };
  const m   = t.direction === "long" ? 1 : -1;
  const pnl = parseFloat((t.shares * m * (t.exit - t.entry) - 2 * brokerage).toFixed(2));
  let r = null;
  if (t.stop != null) {
    const risk = t.direction === "long" ? t.entry - t.stop : t.stop - t.entry;
    if (risk > 0) r = parseFloat(((m * (t.exit - t.entry)) / risk).toFixed(2));
  }
  return { pnl, r };
}

// BINANCE_MAP from chart.js — must stay in sync.
const BINANCE_MAP = {
  BTC: "BTCUSDT", ETH: "ETHUSDT", BNB: "BNBUSDT", SOL: "SOLUSDT",
  XRP: "XRPUSDT", ADA: "ADAUSDT", DOGE: "DOGEUSDT", AVAX: "AVAXUSDT",
  DOT: "DOTUSDT", LINK: "LINKUSDT", LTC: "LTCUSDT", BCH: "BCHUSDT",
};

// isCrypto flag — mirrors wireSim / wireLiveBox in chart.js.
function isCrypto(sym, market) {
  return !!BINANCE_MAP[sym.toUpperCase()] || market === "scalp" || market === "crypto";
}

// Brokerage routing — mirrors simBrok / posBrok in chart.js.
function routeBrok(data, cryptoFlag) {
  return cryptoFlag ? data.crypto_brokerage : data.stock_brokerage;
}

// asset_type assigned to sim trades — mirrors the fix in wireSim buyBtn handler.
function simAssetType(cryptoFlag, market) {
  return cryptoFlag ? "crypto" : (market === "asx" ? "asx" : "nasdaq");
}

// Honest fill price — mirrors checkAutoClose / maybeAutoClose in chart.js.
function autoCloseFill(dir, stop, target, livePx, wasStop) {
  if (wasStop) {
    return dir === "long" ? Math.min(stop, livePx) : Math.max(stop, livePx);
  }
  return target;
}

// Stub candle builder — mirrors renderPosition catch block in chart.js.
function buildStub(ep) {
  const absEp = Math.abs(ep || 1);
  const prec0 = absEp >= 100 ? 2 : absEp >= 1 ? 3 : absEp >= 0.1 ? 4
              : absEp >= 0.01 ? 5 : absEp >= 0.001 ? 6 : 8;
  const mv = Math.pow(10, -prec0);
  return { high: ep + mv, low: Math.max(ep - mv, 0), mv };
}

// fmt() decimal-precision tier — mirrors chart.js fmt.
function fmtPrec(v) {
  const a = Math.abs(v);
  return a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : a >= 0.001 ? 6 : 8;
}

// mjClosedPnls brokerage routing — mirrors journal.js mjClosedPnls.
function mjClosedPnlsBrok(t, data) {
  const isCryptoAsset = !t.asset_type || t.asset_type === "crypto";
  return isCryptoAsset ? (data.crypto_brokerage ?? 5) : (data.stock_brokerage ?? 10);
}

// ═══════════════════════════════════ TESTS ══════════════════════════════════

// ── normalize() ─────────────────────────────────────────────────────────────
suite("normalize()");

test("sets all defaults on empty object", () => {
  const d = normalize({});
  assert.equal(d.capital,          10000);
  assert.equal(d.brokerage,        10);
  assert.equal(d.stock_capital,    10000);
  assert.equal(d.stock_brokerage,  10);
  assert.equal(d.crypto_capital,   10000);
  assert.equal(d.crypto_brokerage, 5);
  assert.equal(d.updated_at,       0);
  assert.equal(d.trades.length,    0);
  assert.equal(d.deleted.length,   0);
});

test("does not overwrite existing values", () => {
  const d = normalize({ capital: 5000, crypto_brokerage: 3, stock_brokerage: 7,
                         trades: [{ id: "t1" }] });
  assert.equal(d.capital,          5000);
  assert.equal(d.crypto_brokerage, 3);
  assert.equal(d.stock_brokerage,  7);
  assert.equal(d.trades.length,    1);
});

test("null input → all defaults", () => {
  const d = normalize(null);
  assert.equal(d.crypto_brokerage, 5);
  assert.equal(d.stock_brokerage,  10);
});

test("non-object (string) input → all defaults", () => {
  const d = normalize("bad");
  assert.equal(d.capital, 10000);
});

test("crypto_brokerage default is 5 (not 10 like brokerage)", () => {
  const d = normalize({});
  assert.equal(d.crypto_brokerage, 5);
  assert.notEqual(d.crypto_brokerage, d.brokerage);
});

test("falsy-zero preserved: typeof 0 === 'number' so 0 is not replaced", () => {
  const d = normalize({ stock_brokerage: 0, crypto_brokerage: 0 });
  assert.equal(d.stock_brokerage,  0);
  assert.equal(d.crypto_brokerage, 0);
});

// ── merge() ──────────────────────────────────────────────────────────────────
suite("merge()");

test("union: trades from both sides appear", () => {
  const a = { trades: [{ id: "a1", mtime: 1 }], updated_at: 100 };
  const b = { trades: [{ id: "b1", mtime: 2 }], updated_at: 50  };
  const m = merge(a, b);
  const ids = m.trades.map((t) => t.id);
  assert.ok(ids.includes("a1"), "a1 missing");
  assert.ok(ids.includes("b1"), "b1 missing");
});

test("id clash: newer mtime wins", () => {
  const old  = { id: "x", mtime: 100, status: "open"   };
  const newT = { id: "x", mtime: 200, status: "closed" };
  const m = merge({ trades: [old],  updated_at: 0 },
                  { trades: [newT], updated_at: 0 });
  assert.equal(m.trades[0].status, "closed");
});

test("id clash: equal mtime → b (last-processed) wins", () => {
  const ta = { id: "x", mtime: 100, v: "a" };
  const tb = { id: "x", mtime: 100, v: "b" };
  const m = merge({ trades: [ta], updated_at: 0 },
                  { trades: [tb], updated_at: 0 });
  assert.equal(m.trades[0].v, "b");
});

test("tombstone on a removes trade from result", () => {
  const trade = { id: "dead", mtime: 1 };
  const a = { trades: [trade], deleted: ["dead"], updated_at: 0 };
  const b = { trades: [trade], deleted: [],       updated_at: 0 };
  const m = merge(a, b);
  assert.equal(m.trades.filter((t) => t.id === "dead").length, 0);
});

test("tombstone on b removes trade from result", () => {
  const trade = { id: "ghost", mtime: 1 };
  const a = { trades: [trade], deleted: [],        updated_at: 0 };
  const b = { trades: [],      deleted: ["ghost"], updated_at: 0 };
  const m = merge(a, b);
  assert.equal(m.trades.filter((t) => t.id === "ghost").length, 0);
});

test("deleted set is union of both sides", () => {
  const a = { trades: [], deleted: ["x"], updated_at: 0 };
  const b = { trades: [], deleted: ["y"], updated_at: 0 };
  const m = merge(a, b);
  assert.ok(m.deleted.includes("x"), "x missing from deleted");
  assert.ok(m.deleted.includes("y"), "y missing from deleted");
});

test("per-asset settings: newer updated_at side wins", () => {
  const a = { stock_brokerage: 9,  crypto_brokerage: 4, updated_at: 200, trades: [] };
  const b = { stock_brokerage: 12, crypto_brokerage: 6, updated_at: 100, trades: [] };
  const m = merge(a, b);  // a is newer
  assert.equal(m.stock_brokerage,  9);
  assert.equal(m.crypto_brokerage, 4);
});

test("updated_at = max of both", () => {
  const a = { updated_at: 500, trades: [] };
  const b = { updated_at: 300, trades: [] };
  const m = merge(a, b);
  assert.equal(m.updated_at, 500);
});

test("merge of two empty journals produces valid normalized result", () => {
  const m = merge({}, {});
  assert.equal(m.crypto_brokerage, 5);
  assert.equal(m.trades.length, 0);
});

test("per-asset settings: when newer side never set the field, older's explicit value is preserved", () => {
  // b is newer (updated_at=200) but never set crypto_brokerage (raw field absent).
  // a (older) explicitly set it to 3.
  // Before this fix, normalize(b) filled 5 as default and newer(b).?? never fell through.
  const a = { crypto_brokerage: 3, updated_at: 100, trades: [] };
  const b = {                       updated_at: 200, trades: [] };
  const m = merge(a, b);
  assert.equal(m.crypto_brokerage, 3);   // a's explicit value survives
});

test("per-asset settings: when both sides explicitly set the field, newer wins", () => {
  const a = { crypto_brokerage: 3, updated_at: 100, trades: [] };
  const b = { crypto_brokerage: 6, updated_at: 200, trades: [] };
  const m = merge(a, b);
  assert.equal(m.crypto_brokerage, 6);   // b is newer and explicitly set 6
});

test("per-asset settings: when neither side set the field, normalize default is used", () => {
  const m = merge({ updated_at: 200, trades: [] }, { updated_at: 100, trades: [] });
  assert.equal(m.crypto_brokerage, 5);   // normalize() default
  assert.equal(m.stock_brokerage,  10);
});

// ── mjCalc() — P&L and R ─────────────────────────────────────────────────────
suite("mjCalc() — P&L and R");

const baseLong  = { status: "closed", direction: "long",  shares: 100, entry: 10, stop: 9,  target: 12 };
const baseShort = { status: "closed", direction: "short", shares: 100, entry: 10, stop: 11, target: 8  };

test("long profit: +$1 move × 100sh − 2×$10 brok = +$80", () => {
  assert.equal(mjCalc({ ...baseLong, exit: 11 }, 10).pnl, 80);
});

test("long loss: −$1 move × 100sh − 2×$10 brok = −$120", () => {
  assert.equal(mjCalc({ ...baseLong, exit: 9 }, 10).pnl, -120);
});

test("short profit: −$2 move × 100sh − 2×$5 brok = +$190 (crypto brok)", () => {
  assert.equal(mjCalc({ ...baseShort, exit: 8 }, 5).pnl, 190);
});

test("short loss: +$1 gap × 100sh − 2×$10 brok = −$120", () => {
  assert.equal(mjCalc({ ...baseShort, exit: 11 }, 10).pnl, -120);
});

test("long 2R trade (exit at target, risk=1, reward=2) = +2.00R", () => {
  assert.equal(mjCalc({ ...baseLong, exit: 12 }, 10).r, 2);
});

test("long break-even (exit at entry) = 0.00R", () => {
  assert.equal(mjCalc({ ...baseLong, exit: 10 }, 10).r, 0);
});

test("short stop hit: exit=11, entry=10, stop=11, risk=1 → −1.00R", () => {
  assert.equal(mjCalc({ ...baseShort, exit: 11 }, 10).r, -1);
});

test("R is null when no stop set", () => {
  assert.equal(mjCalc({ ...baseLong, stop: null, exit: 15 }, 10).r, null);
});

test("R is null when stop = entry (zero risk denominator)", () => {
  assert.equal(mjCalc({ ...baseLong, stop: 10, exit: 12 }, 10).r, null);
});

test("open trade → {pnl: null, r: null}", () => {
  const res = mjCalc({ ...baseLong, status: "open", exit: null }, 10);
  assert.equal(res.pnl, null);
  assert.equal(res.r,   null);
});

test("closed trade with null exit → {pnl: null, r: null}", () => {
  assert.equal(mjCalc({ ...baseLong, exit: null }, 10).pnl, null);
});

test("brokerage=0 → pure move P&L", () => {
  assert.equal(mjCalc({ ...baseLong, exit: 11 }, 0).pnl, 100);
});

// ── brokerage routing ────────────────────────────────────────────────────────
suite("brokerage routing (isCrypto + routeBrok)");

const defData = normalize({});   // crypto_brokerage=5, stock_brokerage=10

test("BINANCE_MAP coin (ETH) → crypto_brokerage", () => {
  assert.equal(routeBrok(defData, isCrypto("ETH", "asx")), 5);
});

test("non-map coin + market=scalp → crypto_brokerage", () => {
  assert.equal(routeBrok(defData, isCrypto("PEPE", "scalp")), 5);
});

test("non-map coin + market=asx → stock_brokerage", () => {
  assert.equal(routeBrok(defData, isCrypto("PEPE", "asx")), 10);
});

test("ASX stock → stock_brokerage", () => {
  assert.equal(routeBrok(defData, isCrypto("BHP", "asx")), 10);
});

test("NASDAQ stock → stock_brokerage", () => {
  assert.equal(routeBrok(defData, isCrypto("AAPL", "nasdaq")), 10);
});

test("BTC in market=asx still → crypto_brokerage (BINANCE_MAP takes precedence)", () => {
  assert.equal(routeBrok(defData, isCrypto("BTC", "asx")), 5);
});

test("non-map coin + market=crypto → crypto_brokerage (regular crypto scan)", () => {
  // INJ is not in BINANCE_MAP but is opened from the top-level CRYPTO market.
  assert.equal(routeBrok(defData, isCrypto("INJ", "crypto")), 5);
});

// ── sim trade asset_type assignment ──────────────────────────────────────────
suite("sim trade asset_type (wireSim buy handler)");

test("sim buy on asx → asset_type 'asx'", () => {
  assert.equal(simAssetType(false, "asx"),    "asx");
});

test("sim buy on nasdaq → asset_type 'nasdaq'", () => {
  assert.equal(simAssetType(false, "nasdaq"), "nasdaq");
});

test("sim buy on scalp crypto → asset_type 'crypto'", () => {
  assert.equal(simAssetType(true,  "scalp"),  "crypto");
});

test("sim buy on BINANCE_MAP coin → asset_type 'crypto' regardless of market", () => {
  assert.equal(simAssetType(true,  "asx"),    "crypto");
});

test("sim buy on non-map coin from crypto market → asset_type 'crypto'", () => {
  // Regression: INJ from the CRYPTO market used to fall through to 'nasdaq'
  // and vanish from the My Crypto tab. It must now classify as crypto.
  assert.equal(simAssetType(isCrypto("INJ", "crypto"), "crypto"), "crypto");
});

// Prove the scoreboard uses the right brokerage per asset_type
test("mjClosedPnls brokerage: undefined asset_type → crypto_brokerage (backward compat)", () => {
  const data = normalize({});
  const trade = { status: "closed", exit: 11, direction: "long" };  // no asset_type
  assert.equal(mjClosedPnlsBrok(trade, data), 5);  // crypto default
});

test("mjClosedPnls brokerage: asset_type='asx' → stock_brokerage", () => {
  const data = normalize({});
  const trade = { status: "closed", exit: 11, direction: "long", asset_type: "asx" };
  assert.equal(mjClosedPnlsBrok(trade, data), 10);
});

test("mjClosedPnls brokerage: asset_type='nasdaq' → stock_brokerage", () => {
  const data = normalize({});
  const trade = { status: "closed", exit: 11, direction: "long", asset_type: "nasdaq" };
  assert.equal(mjClosedPnlsBrok(trade, data), 10);
});

// ── auto-close fill price ────────────────────────────────────────────────────
suite("auto-close fill price (honest fills)");

test("long stop hit at exactly stop → fill at stop", () => {
  assert.equal(autoCloseFill("long", 10, 15, 10, true), 10);
});

test("long gaps below stop → fill at livePx (worse, not stop)", () => {
  assert.equal(autoCloseFill("long", 10, 15, 8, true), 8);
});

test("long target → fill at target (no overshoot credit)", () => {
  assert.equal(autoCloseFill("long", 10, 15, 16, false), 15);
});

test("short stop hit at exactly stop → fill at stop", () => {
  assert.equal(autoCloseFill("short", 11, 8, 11, true), 11);
});

test("short gaps above stop → fill at livePx (worse, not stop)", () => {
  assert.equal(autoCloseFill("short", 11, 8, 13, true), 13);
});

test("short target → fill at target", () => {
  assert.equal(autoCloseFill("short", 11, 8, 7, false), 8);
});

// ── stub candle safety: high > low, low ≥ 0 ─────────────────────────────────
suite("stub candle (renderPosition fallback)");

test("normal price $1.50 → high > low", () => {
  const { high, low } = buildStub(1.5);
  assert.ok(high > low, `high(${high}) > low(${low})`);
  assert.ok(low >= 0);
});

test("micro-cap $0.001 → high > low", () => {
  const { high, low } = buildStub(0.001);
  assert.ok(high > low);
  assert.ok(low >= 0);
});

test("sub-micro $0.0000001 → high > low (the old ep×1.001 bug)", () => {
  const { high, low } = buildStub(0.0000001);
  assert.ok(high > low, `high(${high}) must be > low(${low})`);
  assert.ok(low >= 0);
});

test("zero entry → fallback to ep||1=1, high > low", () => {
  const { high, low } = buildStub(0);
  assert.ok(high > low);
  assert.ok(low >= 0);
});

test("large price $500 → high > low", () => {
  const { high, low } = buildStub(500);
  assert.ok(high > low);
});

test("spread is exactly 2×mv (or low clamped to 0)", () => {
  const ep = 0.5;
  const { high, low, mv } = buildStub(ep);
  // ep=0.5 → prec0=4 → mv=0.0001; low = max(0.5-0.0001, 0) = 0.4999
  const spread = high - low;
  const expected = low === 0 ? high : 2 * mv;
  assert.ok(Math.abs(spread - expected) < 1e-12,
    `spread ${spread} !== 2×mv ${expected}`);
});

// ── fmt() decimal precision tiers ────────────────────────────────────────────
suite("fmt() precision tiers");

test("$150    → 2 dp", () => { assert.equal(fmtPrec(150),    2); });
test("$1.50   → 3 dp", () => { assert.equal(fmtPrec(1.5),    3); });
test("$0.15   → 4 dp", () => { assert.equal(fmtPrec(0.15),   4); });
test("$0.015  → 5 dp", () => { assert.equal(fmtPrec(0.015),  5); });
test("$0.0015 → 6 dp", () => { assert.equal(fmtPrec(0.0015), 6); });
test("sub-satoshi → 8 dp", () => { assert.equal(fmtPrec(0.000001), 8); });

// ── localStorage round-trip via gbs-sync saveLocal/load ──────────────────────
suite("localStorage round-trip");

test("saveLocal then load returns same trades and per-asset fields", () => {
  mockLocalStorage.clear();
  const d = normalize({ trades: [{ id: "t1", mtime: 1, status: "open" }],
                        crypto_brokerage: 3, stock_brokerage: 7 });
  saveLocal(d);
  const loaded = load();
  assert.equal(loaded.trades.length,    1);
  assert.equal(loaded.trades[0].id,     "t1");
  assert.equal(loaded.crypto_brokerage, 3);
  assert.equal(loaded.stock_brokerage,  7);
});

test("load on empty storage returns normalized defaults", () => {
  mockLocalStorage.clear();
  const d = load();
  assert.equal(d.capital,          10000);
  assert.equal(d.crypto_brokerage, 5);
  assert.equal(d.stock_brokerage,  10);
  assert.equal(d.trades.length,    0);
});

// ─────────────────────────────── summary ─────────────────────────────────────
console.log(`\n${"─".repeat(48)}`);
if (failed) {
  console.error(`FAILED  ${failed} test(s) failed, ${passed} passed`);
  process.exit(1);
} else {
  console.log(`ALL ${passed} tests passed`);
}

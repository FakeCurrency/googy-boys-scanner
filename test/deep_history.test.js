#!/usr/bin/env node
/* Deep chart history (functions/api/_prices.js + price.js + chart.js).

   Owner, 2026-09-19: every chart on the site started in Sept 2021, and the
   weekly 200-SMA had ~52 of 251 bars to stand on. The fix serves deep daily
   history by STITCHING explicit date windows, because asking Yahoo for
   range=max silently returns coarser candles.

   Most of this file is about the two ways stitching could quietly corrupt a
   chart: double-counting bars at the seams, and losing the ordering. It runs
   the REAL shipped functions, sliced out at load time.

   Run with: node test/deep_history.test.js
*/
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

let passed = 0, failed = 0;
const QUEUE = [];
function test(name, fn) { QUEUE.push({ name, fn }); }
const suite = (name) => QUEUE.push({ suite: name });
async function runQueue() {
  for (const item of QUEUE) {
    if (item.suite) { console.log(`\n── ${item.suite} ──`); continue; }
    try { await item.fn(); console.log(`  ✓  ${item.name}`); passed++; }
    catch (e) { console.error(`  ✗  ${item.name}\n     ${e.message}`); failed++; }
  }
}

const API = (f) => fs.readFileSync(path.join(__dirname, "..", "functions", "api", f), "utf8");
const PRICES = API("_prices.js");
const PRICE = API("price.js");
const CHART = fs.readFileSync(path.join(__dirname, "..", "public", "js", "chart.js"), "utf8");

// Load the real module with its exports stripped, against injected fakes.
function load({ fetchImpl, now = 1_780_000_000_000 } = {}) {
  const src = PRICES
    .replace(/export\s+async\s+function/g, "async function")
    .replace(/export\s+function/g, "function")
    .replace(/export\s+const/g, "const");
  const sandbox = {
    JSON, Math, Number, String, Array, Object, Promise, Map, Set, isFinite, parseFloat,
    console, AbortSignal: { timeout: () => null },
    Date: class extends Date { static now() { return now; } },
    encodeURIComponent,
    fetch: fetchImpl || (() => Promise.reject(new Error("no fetch stub"))),
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src + "\n;globalThis.__api = { deepYears, fetchYahooDeep, fetchYahooWindow, targetBars, trimCandles, yahooCandles };", sandbox);
  return sandbox.__api;
}

/* A Yahoo chart result covering `n` sessions ending at `endSec`, priced so each
 * bar's close encodes its own day index — that makes a mis-stitched series
 * detectable by value, not just by count. */
function result(endSec, n, step = 86400) {
  const ts = [], close = [], open = [], high = [], low = [], volume = [];
  for (let i = n - 1; i >= 0; i--) {
    const t = endSec - i * step;
    ts.push(t); close.push(t / 86400); open.push(t / 86400);
    high.push(t / 86400); low.push(t / 86400); volume.push(100);
  }
  return { timestamp: ts, indicators: { quote: [{ open, high, low, close, volume }] } };
}
const okRes = (r) => Promise.resolve({ ok: true, json: () => Promise.resolve({ chart: { result: [r] } }) });

// ═══════════════════════════ range → depth ═══════════════════════════════════
suite("which ranges go deep, and which are left exactly as they were");

test("the deep ranges map to their year counts", () => {
  const a = load();
  assert.equal(a.deepYears("10y"), 10);
  assert.equal(a.deepYears("25y"), 25);
  assert.equal(a.deepYears("max"), 25);
});

test("every pre-existing range stays SHALLOW, so no current caller changes path", () => {
  // This is the blast-radius guarantee: nothing that worked before now takes a
  // different code path, because nothing before ever asked for 10y+.
  const a = load();
  for (const r of ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"]) {
    assert.equal(a.deepYears(r), 0, `${r} must not be routed to the stitcher`);
  }
});

test("the bar cap allows a whole deep span instead of the old flat 2600", () => {
  const a = load();
  assert.ok(a.targetBars("25y", "1d") >= 6300, "25y would be trimmed back to ~10y");
  assert.equal(a.targetBars("5y", "1d"), 1900, "the 5y cap must not move");
  assert.equal(a.targetBars("1y", "1d"), 260);
});

// ═══════════════════════════ the stitcher ════════════════════════════════════
suite("stitching — the two ways it could corrupt a chart");

test("windows are fetched in PARALLEL, one per chunk", async () => {
  let inFlight = 0, maxInFlight = 0, calls = 0;
  const a = load({
    fetchImpl: () => {
      calls++; inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
      return new Promise((res) => setTimeout(() => { inFlight--; res(); }, 5))
        .then(() => okRes(result(1_780_000_000, 10)));
    },
  });
  await a.fetchYahooDeep("ON", { years: 25, chunkYears: 5 });
  assert.equal(calls, 5, "25 years in 5-year chunks is five windows");
  assert.ok(maxInFlight > 1, "windows must not be fetched one after another");
});

test("overlapping seam bars are DEDUPED, not double-counted", async () => {
  // Every window is given the SAME 100 sessions. A naive concat yields 500 bars
  // for 100 real ones, which would draw a chart five times too dense.
  const a = load({ fetchImpl: () => okRes(result(1_780_000_000, 100)) });
  const out = await a.fetchYahooDeep("ON", { years: 25, chunkYears: 5 });
  assert.equal(out.candles.length, 100, "duplicate sessions must collapse");
});

test("the stitched series comes back in ascending time order", async () => {
  let k = 0;
  const a = load({
    fetchImpl: () => okRes(result(1_780_000_000 - (k++) * 100 * 86400, 100)),
  });
  const out = await a.fetchYahooDeep("ON", { years: 25, chunkYears: 5 });
  for (let i = 1; i < out.candles.length; i++) {
    assert.ok(out.candles[i].time > out.candles[i - 1].time,
      `bar ${i} is out of order — a chart would draw a zigzag`);
  }
  assert.ok(out.candles.length > 400, "five distinct windows should merge to ~500 bars");
});

test("bar VALUES survive the merge unchanged", async () => {
  const a = load({ fetchImpl: () => okRes(result(1_780_000_000, 30)) });
  const out = await a.fetchYahooDeep("ON", { years: 10, chunkYears: 5 });
  for (const c of out.candles) {
    assert.equal(c.close, c.time / 86400, "a merged bar must keep its own price");
  }
});

test("a window that fails is SKIPPED, not fatal — young tickers 400 on old windows", async () => {
  let n = 0;
  const a = load({
    fetchImpl: () => (++n <= 4
      ? Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({}) })
      : okRes(result(1_780_000_000, 50))),
  });
  const out = await a.fetchYahooDeep("GLBE", { years: 25, chunkYears: 5 });
  assert.ok(out.candles.length > 0, "half a chart beats none");
});

test("when every window fails it returns empty rather than throwing", async () => {
  const a = load({ fetchImpl: () => Promise.reject(new Error("network")) });
  const out = await a.fetchYahooDeep("NOPE", { years: 25, chunkYears: 5 });
  // length, not deepEqual: the array is built inside the vm realm, so a
  // cross-realm deepStrictEqual fails for reasons unrelated to the code.
  assert.equal(out.candles.length, 0);
});

test("the window request asks by DATE, not by range — that is the whole point", async () => {
  let url = "";
  const a = load({ fetchImpl: (u) => { url = u; return okRes(result(1_780_000_000, 5)); } });
  await a.fetchYahooWindow("BHP.AX", { p1: 1000, p2: 2000 });
  assert.match(url, /period1=1000/);
  assert.match(url, /period2=2000/);
  assert.ok(!/[?&]range=/.test(url), "a range= param would re-introduce the coarsening");
  assert.match(url, /interval=1d/);
});

// ═══════════════════════════ the reverse switch ══════════════════════════════
suite("the reverse switch — owner asked to be able to undo this in a day or two");

test("CHART_MAX_YEARS clamps the request, and 5 restores the old behaviour", () => {
  assert.match(PRICE, /CHART_MAX_YEARS/,
    "the env-var reverse switch is gone — reversing would need a deploy");
  assert.match(PRICE, /RANGE_YEARS/);
  assert.match(PRICE, /range:\s*effRange/,
    "history() must receive the CLAMPED range, or the switch does nothing");
});

test("it clamps rather than rejects, so a cached page still gets bars", () => {
  assert.ok(!/CHART_MAX_YEARS[\s\S]{0,400}return json\(4\d\d/.test(PRICE),
    "an old cached page asking for 25y must degrade to 5y, not error");
});

test("the deep ranges are whitelisted on the endpoint", () => {
  for (const r of ["10y", "15y", "20y", "25y"]) {
    assert.ok(PRICE.includes(`"${r}"`), `${r} missing from the range whitelist`);
  }
});

// ═══════════════════════════ the chart ═══════════════════════════════════════
suite("the chart asks for the deep range through one constant");

test("one constant drives every stock daily call site", () => {
  assert.match(CHART, /const DAILY_RANGE = "25y";/);
  assert.equal((CHART.match(/yahooBars\(yfTickerFor\(SYM, assetType\), DAILY_RANGE, "1d", true\)/g) || []).length, 3);
  assert.ok(!/yahooBars\(yfTickerFor\(SYM, assetType\), "5y", "1d", true\)/.test(CHART),
    "a hardcoded 5y stock daily call survived the change");
});

test("crypto is deliberately left shallow", () => {
  assert.match(CHART, /vivekCryptoBars\(SYM, "5y", "1d", true\)/,
    "crypto was changed — that needs its own measurements (Binance caps at 1000 bars)");
});

test("the constant documents how to reverse it", () => {
  const block = CHART.slice(0, CHART.indexOf('const DAILY_RANGE'));
  assert.match(block, /CHART_MAX_YEARS/, "the revert path must be written where the knob is");
});

runQueue().then(() => {
  console.log(`\ndeep_history.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});

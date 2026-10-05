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
  vm.runInContext(src + "\n;globalThis.__api = { deepYears, fetchYahooDeep, fetchYahooWindow, targetBars, trimCandles, yahooCandles, fetchBinanceCandles, fetchBinancePrice };", sandbox);
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

test("hourly is range-aware — a 2y/1h request is not trimmed to five months", () => {
  // The flat 750 was why every 4H pane, on BOTH charts, drew about a fifth of
  // the history it asked for: 750 hourly bars is ~125 ASX sessions, and
  // bucketed to 4H that is ~187 candles. Reported by the owner on LRV 4H.
  const a = load();
  assert.ok(a.targetBars("2y", "1h") >= 3000,
    "2y of hourly must allow ~504 sessions x 6 hours");
  assert.equal(a.targetBars("1mo", "1h"), 160, "a short hourly range stays short");
  // The finer intraday intervals are the scalp path and are unchanged.
  for (const iv of ["1m", "5m", "15m", "30m"]) {
    assert.equal(a.targetBars("2y", iv), 750, `${iv} must keep the old cap`);
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
  // 4 since 2026-09-22: momentumFallback is the fourth stock-daily call site
  // and it goes through the SAME constant. The count is the tripwire -- a new
  // call site must come here and prove it did not hardcode its own range.
  assert.equal((CHART.match(/yahooBars\(yfTickerFor\(SYM, assetType\), DAILY_RANGE, "1d", true\)/g) || []).length, 4);
  assert.ok(!/yahooBars\(yfTickerFor\(SYM, assetType\), "5y", "1d", true\)/.test(CHART),
    "a hardcoded 5y stock daily call survived the change");
});

test("crypto is deliberately left shallow", () => {
  assert.match(CHART, /vivekCryptoBars\(SYM, "5y", "1d", true\)/,
    "crypto was changed — that needs its own measurements (the Binance proxy pages to 4000 bars)");
});

// ═══════════════ Binance at full depth (2026-09-28, the crypto switch) ═════════
suite("the Binance proxy pages past its 1000-bar cap, mirror first");

// A fake Binance: `n` daily klines ending at `endMs`; honours limit + endTime.
function binance(n, endMs, { failHosts = [] } = {}) {
  const DAY = 86_400_000;
  const all = [];
  for (let i = n - 1; i >= 0; i--) {
    const t = endMs - i * DAY;
    all.push([t, "1", "2", "0.5", String(t / DAY), "10"]);
  }
  const calls = [];
  const impl = (url) => {
    calls.push(url);
    if (failHosts.some((h) => url.startsWith(h))) return Promise.resolve({ ok: false, status: 451 });
    const q = new URL(url).searchParams;
    const limit = +q.get("limit");
    const end = q.get("endTime") == null ? Infinity : +q.get("endTime");
    const page = all.filter((k) => k[0] <= end).slice(-limit);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(page) });
  };
  return { impl, calls };
}

test("5 years of daily bars arrive in order, unique, newest last", async () => {
  const END = 1_790_000_000_000;
  const b = binance(2500, END);
  const a = load({ fetchImpl: b.impl });
  const c = await a.fetchBinanceCandles("QNT-USD", { interval: "1d", limit: 1900 });
  assert.equal(c.length, 1900);
  assert.equal(c[c.length - 1].time, END / 1000);
  for (let i = 1; i < c.length; i++) assert.equal(c[i].time - c[i - 1].time, 86400);
  assert.equal(b.calls.length, 2, "1000 + 900");
  assert.ok(b.calls.every((u) => u.startsWith("https://data-api.binance.vision/")), "the mirror is asked first");
  assert.ok(/[?&]symbol=QNTUSDT/.test(b.calls[0]) && !/endTime/.test(b.calls[0]));
  assert.ok(/endTime=/.test(b.calls[1]), "the second page walks back with endTime");
});

test("a young coin stops at its listing date after one request", async () => {
  const b = binance(300, 1_790_000_000_000);
  const c = await load({ fetchImpl: b.impl }).fetchBinanceCandles("NEW-USD", { limit: 1900 });
  assert.equal(c.length, 300);
  assert.equal(b.calls.length, 1);
});

test("a refused mirror falls back to the main API", async () => {
  const b = binance(50, 1_790_000_000_000, { failHosts: ["https://data-api.binance.vision"] });
  const c = await load({ fetchImpl: b.impl }).fetchBinanceCandles("BTC-USD", { limit: 50 });
  assert.equal(c.length, 50);
  assert.ok(b.calls.some((u) => u.startsWith("https://api.binance.com/")));
});

test("the page count is bounded (Cloudflare subrequests)", async () => {
  const b = binance(9000, 1_790_000_000_000);
  const c = await load({ fetchImpl: b.impl }).fetchBinanceCandles("BTC-USD", { limit: 6600 });
  assert.equal(c.length, 4000);
  assert.equal(b.calls.length, 4);
});

suite("the VIVEK crypto chart draws the venue the scan read");

test("the row's data_source picks the series; anything but Binance stays Yahoo", () => {
  const i = CHART.indexOf("const cryptoSrcFor");
  const expr = CHART.slice(CHART.indexOf("=", i) + 1, CHART.indexOf(";", i));
  const f = eval(expr);
  assert.equal(f({ data_source: "binance_vision" }), "binance");
  assert.equal(f({ data_source: "binance" }), "binance");
  assert.equal(f({ data_source: "coinbase" }), "yahoo");
  assert.equal(f({ data_source: "yahoo" }), "yahoo");
  assert.equal(f({}), "yahoo");
  assert.equal(f(null), "yahoo");
});

test("the fallback sets it from the row, and both fetches use it", () => {
  const vf = CHART.slice(CHART.indexOf("function vivekFallback"), CHART.indexOf("function vivekCryptoBars"));
  assert.match(vf, /VIVEK_CRYPTO_SRC = cryptoSrcFor\(m\)/);
  const vb = CHART.slice(CHART.indexOf("function vivekCryptoBars"), CHART.indexOf("function vivekCryptoBars") + 700);
  assert.match(vb, /&src=\$\{VIVEK_CRYPTO_SRC\}/);
  assert.ok(!/&src=yahoo`/.test(vb), "the chart must not hard-force Yahoo any more");
  const live = CHART.slice(CHART.indexOf("function startStockLive"), CHART.indexOf("function startStockLive") + 1500);
  assert.match(live, /VIVEK_CRYPTO_SRC !== "binance"/, "the header price follows the chart's venue");
});

// 2026-09-28: TAO (Bittensor, Binance-sourced in the IGNITION lens, no VIVEK
// row) opened from the Ignition panel and dead-ended: with no scan row the
// venue stayed "yahoo" and Yahoo's "TAO-USD" is not Bittensor. The no-plan
// path now sets the venue from whatever row it was handed, and boot() hands
// it the Ignition row when VIVEK has none.
test("an Ignition-only coin draws the lens row's venue, not the Yahoo default", () => {
  const pm = CHART.slice(CHART.indexOf("function pmOnlyFallback"), CHART.indexOf("function pmOnlyFallback") + 900);
  assert.match(pm, /const m = meta \|\| \{\};[\s\S]{0,600}VIVEK_CRYPTO_SRC = cryptoSrcFor\(m\)/,
    "pmOnlyFallback must set the venue from its row, as vivekFallback does");
  const ig = CHART.slice(CHART.indexOf("function ignitionMeta"), CHART.indexOf("function fallbackFromLive"));
  assert.match(ig, /data\/ignition\/\$\{market\}\.json/, "reads the lens's own file");
  assert.match(ig, /data_source: row\.source/, "the lens's `source` is handed on as the scan row's `data_source`");
  assert.match(ig, /if \(market !== "crypto"\) return Promise\.resolve\(null\)/, "crypto only");
  const boot = CHART.slice(CHART.indexOf("if (isVivek) {"), CHART.indexOf("if (isVivek) {") + 700);
  assert.match(boot, /\(meta \? Promise\.resolve\(meta\) : ignitionMeta\(\)\)[\s\S]{0,120}pmOnlyFallback\(baseSymbol, m, rec\)/,
    "the Ignition row stands in ONLY when VIVEK has no row");
  // The whole chain, end to end, on a row shaped like the shipped file's TAO.
  const src = new Function(CHART.slice(CHART.indexOf("const cryptoSrcFor"), CHART.indexOf("const GRADE_VAR")) + "return cryptoSrcFor;")();
  const row = { symbol: "TAO", name: "Bittensor", data_source: "binance_vision", price: 304.2, asset_type: "crypto" };
  assert.equal(src(row), "binance");
  assert.equal(src({ symbol: "LTC", data_source: "coinbase" }), "yahoo", "a Coinbase-sourced coin still draws Yahoo (the proxy serves two venues)");
  const back = CHART.slice(CHART.indexOf("const SRC_BACK_MAP"), CHART.indexOf("const SRC_BACK_MAP") + 500);
  assert.match(back, /ignition:\s*\["index\.html",\s*"← Ignition"\]/, "the back-link names the lens");
});

// 2026-09-28, MEASURED on the live proxy: from Cloudflare's servers Binance
// never answers (BNB/QNT asked src=binance came back source "yahoo"; TAO came
// back 502). A Binance-sourced chart therefore reads Binance from the BROWSER,
// and the proxy is the fallback. These run the SHIPPED functions against a
// fake network, not a copy of them.
function directHarness(src, handler) {
  const body = CHART.slice(CHART.indexOf("const BINANCE_DIRECT_HOSTS"),
                           CHART.indexOf("// ── PhaseMap-only chart"));
  const calls = [];
  const fetch = (url) => { calls.push(url); return Promise.resolve(handler(url)); };
  const res = (status, json) => ({ ok: status === 200, status, json: () => Promise.resolve(json) });
  const api = new Function("fetch", "src", `let VIVEK_CRYPTO_SRC = src; let DATA_META = null;
    ${body}
    return { vivekCryptoBars, binanceDirectPrice, meta: () => DATA_META };`)(fetch, src);
  return { api, calls, res };
}
const kl = (n, endMs, step) => Array.from({ length: n }, (_, i) =>
  [endMs - (n - 1 - i) * step, "1", "2", "0.5", String(100 + i), "10"]);

test("a Binance coin draws Binance from the browser even when the proxy is dead", async () => {
  const { api, calls, res } = directHarness("binance", (u) =>
    /binance\.vision/.test(u) ? res(200, kl(900, 1790000000000, 864e5)) : res(502, { ok: false }));
  const bars = await api.vivekCryptoBars("TAO", "5y", "1d", true);
  assert.equal(bars.length, 900);
  assert.equal(calls.length, 1, "900 < a full page: one request, stops at the listing date");
  assert.match(calls[0], /^https:\/\/data-api\.binance\.vision\/api\/v3\/klines\?symbol=TAOUSDT&interval=1d&limit=1000$/);
  assert.ok(!calls.some((u) => u.startsWith("/api/price")), "the proxy is not asked when Binance answered");
  assert.equal(api.meta().bars, 900);
  assert.ok(bars.every((b, i) => i === 0 || b.time > bars[i - 1].time), "ascending, de-duplicated");
});

test("deep history pages BACKWARD with endTime, bounded at 4 pages", async () => {
  const { api, calls, res } = directHarness("binance", (u) => {
    const q = new URL(u).searchParams;
    const end = q.get("endTime") ? +q.get("endTime") : 1790000000000;
    return res(200, kl(+q.get("limit"), end, 36e5));
  });
  const bars = await api.vivekCryptoBars("BTC-USD", "2y", "1h");
  assert.equal(bars.length, 3300, "matches the proxy's 2y hourly depth");
  assert.equal(calls.length, 4);
  assert.ok(!/endTime/.test(calls[0]) && calls.slice(1).every((u) => /endTime=\d+/.test(u)));
});

test("mirror down -> main API; both down -> the proxy, exactly as before", async () => {
  let h = directHarness("binance", (u) => /binance\.vision/.test(u) ? res451()
    : /api\.binance\.com/.test(u) ? { ok: true, status: 200, json: () => Promise.resolve(kl(50, 1790000000000, 864e5)) }
    : null);
  function res451() { return { ok: false, status: 451, json: () => Promise.resolve({}) }; }
  assert.equal((await h.api.vivekCryptoBars("TAO", "5y", "1d")).length, 50);
  assert.match(h.calls[1], /^https:\/\/api\.binance\.com\//);
  h = directHarness("binance", (u) => u.startsWith("/api/price")
    ? { ok: true, status: 200, json: () => Promise.resolve({ ok: true, candles: [{ time: 1, close: 7 }] }) }
    : res451());
  const viaProxy = await h.api.vivekCryptoBars("TAO", "5y", "1d");
  assert.deepEqual(viaProxy, [{ time: 1, close: 7 }]);
  assert.match(h.calls[2], /^\/api\/price\?symbol=TAO-USD&type=crypto&range=5y&interval=1d&src=binance$/);
});

test("a host that answers EMPTY (pair not there) hands on to the next host", async () => {
  const ok = (j) => ({ ok: true, status: 200, json: () => Promise.resolve(j) });
  let h = directHarness("binance", (u) => /binance\.vision/.test(u) ? ok([])
    : /api\.binance\.com/.test(u) ? ok(kl(40, 1790000000000, 864e5)) : null);
  assert.equal((await h.api.vivekCryptoBars("TAO", "5y", "1d")).length, 40);
  h = directHarness("binance", (u) => /binance\.vision/.test(u) ? ok({}) : ok({ price: "9.5" }));
  assert.equal(await h.api.binanceDirectPrice("TAO"), 9.5, "no price from the mirror -> the main API");
});

test("a Yahoo-sourced coin never touches Binance", async () => {
  const { api, calls } = directHarness("yahoo", () =>
    ({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, candles: [] }) }));
  await api.vivekCryptoBars("LTC", "5y", "1d");
  assert.deepEqual(calls, ["/api/price?symbol=LTC-USD&type=crypto&range=5y&interval=1d&src=yahoo"]);
});

test("the header price reads Binance direct for a Binance coin, then the proxy", async () => {
  const { api, calls } = directHarness("binance", (u) => /binance\.vision/.test(u)
    ? { ok: true, status: 200, json: () => Promise.resolve({ price: "304.20" }) } : null);
  assert.equal(await api.binanceDirectPrice("TAO"), 304.2);
  assert.match(calls[0], /ticker\/price\?symbol=TAOUSDT$/);
  const live = CHART.slice(CHART.indexOf("function startStockLive"), CHART.indexOf("function startStockLive") + 2500);
  assert.match(live, /VIVEK_CRYPTO_SRC === "binance" \? await binanceDirectPrice\(SYM\) : null/);
  assert.match(live, /if \(px == null\) \{[\s\S]{0,80}\/api\/quote/, "the quote proxy is still the fallback");
});

test("the constant documents how to reverse it", () => {
  const block = CHART.slice(0, CHART.indexOf('const DAILY_RANGE'));
  assert.match(block, /CHART_MAX_YEARS/, "the revert path must be written where the knob is");
});

// ═══════════════ daily stock bars on the exchange's calendar ══════════════════
// 2026-10-05, the first ASX Monday under AEDT. Yahoo stamps a daily bar at the
// session OPEN in UTC: 10:00 Sydney was 00:00Z until 4 Oct and is 23:00Z the
// PREVIOUS day until April; 09:30 New York is 13:30Z / 14:30Z. Every daily
// reader on the chart reads the UTC date, so an ASX Monday read as Sunday
// (markers a session late, Mondays tinted as weekend, 3D candles off the
// engine's), and in a Melbourne browser a NASDAQ session's labels read the next
// day. yahooBars now re-stamps daily bars at 00:00Z on the exchange date. These
// run the SHIPPED functions, sliced out of chart.js, against a fake network.
suite("daily stock bars carry their EXCHANGE date (AEDT, 2026-10-05)");

function chartFn(name) {                      // parser-bounded, like momentum.test.js
  const at = CHART.indexOf(`function ${name}(`);
  assert.ok(at > 0, `chart.js no longer defines ${name}`);
  for (let i = CHART.indexOf("{", at); i < CHART.length; i++) {
    if (CHART[i] !== "}") continue;
    const cand = CHART.slice(at, i + 1);
    try { new Function("return (" + cand + ");"); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error("slice " + name);
}
function chartConst(name) {
  const at = CHART.indexOf(`const ${name} = `);
  assert.ok(at > 0, `chart.js no longer declares ${name}`);
  for (let i = CHART.indexOf(";", at); i > 0; i = CHART.indexOf(";", i + 1)) {
    const cand = CHART.slice(at, i + 1);
    try { new Function(cand); return cand; } catch (_) { /* keep walking */ }
  }
  throw new Error("slice const " + name);
}
const DATE_FNS = ["sessionClock", "exchangeDay", "tickerSession", "toExchangeDates", "yahooBars",
  "barAtDate", "barDateStr", "shadeRows", "bucketBars", "resampleWeekly", "sessionWeeks",
  "yfTickerFor", "checkRecentDividend"];
function dateHarness({ candles = [], market = "asx", recentDiv = null, el = null } = {}) {
  const calls = [];
  const fetch = (url) => {
    calls.push(url);
    return Promise.resolve({ ok: true, status: 200,
      json: () => Promise.resolve({ ok: true, candles, recent_div: recentDiv }) });
  };
  const $ = (sel) => (sel === "#ct-divadj" ? el : null);
  const body = ["MOM_SESSION", "_sessFmt", "DAILY_UP_INTERVAL", "INTRADAY_TF", "YF_TICKER"].map(chartConst)
    .concat(DATE_FNS.map(chartFn)).join("\n");
  const api = new Function("fetch", "market", "$",
    `let DATA_META = null;\n${body}\nreturn { ${DATE_FNS.join(", ")}, MOM_SESSION };`)(fetch, market, $);
  return { api, calls };
}
const isoOf = (t) => new Date(t * 1000).toISOString().replace(".000Z", "Z");
const dayOf = (t) => new Date(t * 1000).toISOString().slice(0, 10);
const bar = (iso, close) => ({ time: Date.parse(iso) / 1000, open: close, high: close + 0.5,
  low: close - 0.5, close, volume: 100 });
// Three ASX weeks as Yahoo serves them: 10:00 Sydney in UTC (stamps checked
// with python zoneinfo), close = the session's day of the month. AEST for the
// first week, AEDT from Monday 5 October.
const ASX_SESSIONS = [
  ["2026-09-28", "2026-09-28T00:00:00Z"], ["2026-09-29", "2026-09-29T00:00:00Z"],
  ["2026-09-30", "2026-09-30T00:00:00Z"], ["2026-10-01", "2026-10-01T00:00:00Z"],
  ["2026-10-02", "2026-10-02T00:00:00Z"],
  ["2026-10-05", "2026-10-04T23:00:00Z"], ["2026-10-06", "2026-10-05T23:00:00Z"],
  ["2026-10-07", "2026-10-06T23:00:00Z"], ["2026-10-08", "2026-10-07T23:00:00Z"],
  ["2026-10-09", "2026-10-08T23:00:00Z"],
  ["2026-10-12", "2026-10-11T23:00:00Z"], ["2026-10-13", "2026-10-12T23:00:00Z"],
  ["2026-10-14", "2026-10-13T23:00:00Z"], ["2026-10-15", "2026-10-14T23:00:00Z"],
  ["2026-10-16", "2026-10-15T23:00:00Z"],
];
const asxRaw = () => ASX_SESSIONS.map(([d, iso]) => bar(iso, +d.slice(8)));
const asxDaily = async () => {
  const h = dateHarness({ candles: asxRaw() });
  return { h, bars: await h.api.yahooBars("BHP.AX", "25y", "1d", true) };
};
// Reader timezone for the label tests (the owner's, unless a test says
// otherwise). Restored afterwards so no other test runs on a borrowed clock.
async function inTZ(tz, fn) {
  const was = process.env.TZ;
  process.env.TZ = tz;
  try { return await fn(); }
  finally { if (was === undefined) delete process.env.TZ; else process.env.TZ = was; }
}
const inMelbourne = (fn) => inTZ("Australia/Melbourne", fn);

test("an AEDT ASX Monday (2026-10-04T23:00Z) is stamped 2026-10-05 00:00Z", async () => {
  const { bars } = await asxDaily();
  const mon = bars.find((b) => b.close === 5);
  assert.equal(isoOf(mon.time), "2026-10-05T00:00:00Z");
  assert.deepEqual(bars.map((b) => dayOf(b.time)), ASX_SESSIONS.map(([d]) => d),
    "every session, AEST and AEDT alike, carries its Sydney date");
  assert.ok(bars.every((b) => b.time % 86400 === 0), "all at 00:00Z");
  assert.ok(bars.every((b, i) => i === 0 || b.time > bars[i - 1].time), "strictly ascending");
});

test("barAtDate puts each engine marker on its own session -- 2026-10-05 hits Monday", async () => {
  const { h, bars } = await asxDaily();
  assert.equal(h.api.barAtDate(bars, "2026-10-05").close, 5,
    "the old raw stamp put a 2026-10-05 marker on Tuesday's candle");
  for (const [d] of ASX_SESSIONS) {
    assert.equal(h.api.barAtDate(bars, d).close, +d.slice(8), `marker ${d} landed on another session`);
  }
});

test("no ASX session is tinted as a weekend -- AEDT Mondays included", async () => {
  const { h, bars } = await asxDaily();
  const tc = bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
  assert.deepEqual(h.api.shadeRows(tc, "1D"), [], "stocks have no weekend bars to tint");
});

test("3D candles hold the ENGINE's sessions (scanner/vivek.py _resample_3day_ohlc)", async () => {
  const { h, bars } = await asxDaily();
  // The engine's 72h epoch buckets for these sessions, read off the shipped
  // _resample_3day_ohlc on naive Sydney dates (2026-10-05): open / close /
  // session count per bucket. The raw stamps put Wed 7 Oct in the 10-04
  // candle, Tue 13 in 10-10 and Fri 16 in 10-13.
  const ENGINE = [["2026-09-28", 28, 30, 3], ["2026-10-01", 1, 2, 2], ["2026-10-04", 5, 6, 2],
    ["2026-10-07", 7, 9, 3], ["2026-10-10", 12, 12, 1], ["2026-10-13", 13, 15, 3], ["2026-10-16", 16, 16, 1]];
  const d3 = h.api.bucketBars(bars, 3 * 86400);
  assert.deepEqual(d3.map((b) => [dayOf(b.time), b.open, b.close, b.volume / 100]), ENGINE);
});

test("weeks end on their Sydney Friday, AEDT weeks included", async () => {
  const { h, bars } = await asxDaily();
  const wk = h.api.resampleWeekly(bars);
  assert.deepEqual(wk.map((b) => [dayOf(b.time), b.open, b.close]),
    [["2026-10-02", 28, 2], ["2026-10-09", 5, 9], ["2026-10-16", 12, 16]], "the engine's W-FRI weeks");
});

test("a NASDAQ session at 2026-10-05T13:30Z labels as 5 Oct in a Melbourne browser", () => inMelbourne(async () => {
  const h = dateHarness({ market: "nasdaq", candles: [bar("2026-10-02T13:30:00Z", 2), bar("2026-10-05T13:30:00Z", 5)] });
  const bars = await h.api.yahooBars("AAPL", "25y", "1d", true);
  assert.equal(isoOf(bars[1].time), "2026-10-05T00:00:00Z");
  const opt = { day: "numeric", month: "short" };
  const want = new Date(Date.UTC(2026, 9, 5)).toLocaleDateString(undefined, Object.assign({ timeZone: "UTC" }, opt));
  const nextDay = new Date(Date.UTC(2026, 9, 6)).toLocaleDateString(undefined, Object.assign({ timeZone: "UTC" }, opt));
  for (const tf of ["1D", "3D", "1W"]) assert.equal(h.api.barDateStr(bars[1].time, tf, opt), want, tf);
  // The pre-fix label: the raw 13:30Z stamp on the reader's clock is 00:30 on 6 Oct.
  assert.equal(new Date(Date.parse("2026-10-05T13:30:00Z")).toLocaleDateString(undefined, opt), nextDay,
    "the harness really is reading on Melbourne's clock");
  // Intraday labels are untouched: still the reader's local clock.
  const raw = Date.parse("2026-10-05T13:30:00Z") / 1000;
  assert.equal(h.api.barDateStr(raw, "4H", opt), nextDay, "4H keeps the local date, as before");
}));

test("a daily label names the exchange date in a reader's timezone WEST of UTC too", () => inTZ("America/Los_Angeles", async () => {
  // 00:00Z is the previous evening in Los Angeles: formatting a daily bar on
  // the reader's clock would print 4 Oct under a 5 Oct candle.
  const h = dateHarness({ candles: asxRaw() });
  const bars = await h.api.yahooBars("BHP.AX", "25y", "1d");
  const mon = bars.find((b) => b.close === 5);
  const opt = { day: "numeric", month: "short", year: "2-digit" };
  const want = new Date(Date.UTC(2026, 9, 5)).toLocaleDateString(undefined, Object.assign({ timeZone: "UTC" }, opt));
  assert.equal(h.api.barDateStr(mon.time, "1D", opt), want);
  assert.notEqual(new Date(mon.time * 1000).toLocaleDateString(undefined, opt), want,
    "the harness really is reading on Los Angeles' clock");
  const t4 = Date.parse("2026-10-05T03:00:00Z") / 1000;   // an ASX 4H bar, 14:00 Sydney
  assert.equal(h.api.barDateStr(t4, "4H", opt), new Date(t4 * 1000).toLocaleDateString(undefined, opt),
    "intraday stays on the reader's clock");
}));

test("the replay, ruler and forecast labels all go through barDateStr", () => {
  assert.match(CHART, /const dstr = barDateStr\(sec, curTF, \{ weekday:/, "forecast projFmt");
  assert.match(CHART, /const d = barDateStr\(sec, curTF, \{ day:/, "ruler fmtDT");
  assert.match(CHART, /posLbl\.textContent = `\$\{idx\}\/\$\{c\.length\} · ` \+\s*barDateStr\(tCut, curTF,/, "replay position");
  assert.equal((CHART.match(/toLocaleDateString\(undefined/g) || []).length, 1,
    "a bar date formatted on the browser's clock outside barDateStr would split the chart's dates again");
});

test("the DIV-ADJ chip names the ex-date on the exchange's calendar", () => inMelbourne(async () => {
  const run = async (market, symbol, iso) => {
    const el = { textContent: "", title: "", hidden: true };
    const h = dateHarness({ market, el, recentDiv: { date: Date.parse(iso) / 1000, amount: 0.26 } });
    h.api.checkRecentDividend({ symbol, asset_type: null });
    await new Promise((r) => setTimeout(r, 0));
    return { el, calls: h.calls };
  };
  const nq = await run("nasdaq", "AAPL", "2026-10-05T13:30:00Z");   // Tue 00:30 in Melbourne
  assert.equal(nq.el.textContent, "Ⓓ DIV-ADJ 5 Oct");
  assert.match(nq.el.title, /^Went ex-dividend 5 Oct /);
  assert.equal(nq.el.hidden, false);
  assert.deepEqual(nq.calls, ["/api/price?symbol=AAPL&range=1mo&interval=1d"]);
  const winter = await run("nasdaq", "AAPL", "2026-12-16T14:30:00Z");   // AEDT + EST
  assert.equal(winter.el.textContent, "Ⓓ DIV-ADJ 16 Dec");
  const asx = await run("asx", "BHP", "2026-10-04T23:00:00Z");
  assert.equal(asx.el.textContent, "Ⓓ DIV-ADJ 5 Oct");
  assert.deepEqual(asx.calls, ["/api/price?symbol=BHP.AX&range=1mo&interval=1d"]);
}));

test("Momentum's exchange weeks still cut on Monday once NASDAQ bars sit at 00:00Z", async () => {
  // 00:00Z is 20:00 the evening BEFORE in New York, so reading a re-stamped
  // bar on New York's clock would file every Monday under the previous week.
  const days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-09", "2026-10-12"];
  const h = dateHarness({ market: "nasdaq", candles: days.map((d) => bar(d + "T13:30:00Z", +d.slice(8))) });
  const bars = await h.api.yahooBars("AAPL", "25y", "1d");
  const w = h.api.sessionWeeks(bars, h.api.MOM_SESSION.nasdaq);
  assert.deepEqual(w.map((b) => [dayOf(b.time), b.open, b.close]),
    [["2026-10-01", 1, 2], ["2026-10-05", 5, 9], ["2026-10-12", 12, 12]]);
});

test("the re-stamp is idempotent: a 00:00Z bar is already a calendar date", () => {
  const { api } = dateHarness();
  const NQ = api.MOM_SESSION.nasdaq;
  const eod = [bar("2026-10-02T00:00:00Z", 2), bar("2026-10-05T00:00:00Z", 5)];   // the EODHD / saved-file shape
  assert.deepEqual(api.toExchangeDates(eod, NQ).map((b) => dayOf(b.time)), ["2026-10-02", "2026-10-05"],
    "New York's clock must not move a calendar date back a day");
  const once = api.toExchangeDates(asxRaw(), api.MOM_SESSION.asx);
  assert.deepEqual(api.toExchangeDates(once, api.MOM_SESSION.asx), once);
  assert.equal(api.exchangeDay(Date.parse("2026-10-04T23:00:00Z") / 1000, "Australia/Sydney"), "2026-10-05");
});

test("a repeated live session collapses to one bar, the later one", () => {
  const { api } = dateHarness();
  const live = [bar("2026-10-04T23:00:00Z", 5), bar("2026-10-05T23:00:00Z", 6), bar("2026-10-06T03:12:00Z", 7)];
  const out = api.toExchangeDates(live, api.MOM_SESSION.asx);
  assert.deepEqual(out.map((b) => [dayOf(b.time), b.close]), [["2026-10-05", 5], ["2026-10-06", 7]]);
  assert.deepEqual(live.map((b) => b.close), [5, 6, 7], "the caller's bars are not mutated");
});

test("intraday, crypto and futures bars are left exactly as served", async () => {
  const raw = [bar("2026-10-04T23:00:00Z", 5), bar("2026-10-05T00:00:00Z", 6)];
  let h = dateHarness({ candles: raw });
  assert.deepEqual(await h.api.yahooBars("BHP.AX", "2y", "1h"), raw, "hourly keeps its real clock");
  for (const yf of ["BTC-USD", "GC=F", "^N225"]) {
    h = dateHarness({ candles: raw });
    assert.deepEqual(await h.api.yahooBars(yf, "1y", "1d"), raw, yf);
  }
  const s = dateHarness().api.tickerSession;
  assert.equal(s("BHP.AX").tz, "Australia/Sydney");
  assert.equal(s("^AXJO").tz, "Australia/Sydney", "the ASX compare index is dated like the ASX chart");
  assert.equal(s("SPY").tz, "America/New_York");
  assert.equal(s("BRK-B").tz, "America/New_York");
});

runQueue().then(() => {
  console.log(`\ndeep_history.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
});

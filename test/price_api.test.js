#!/usr/bin/env node
/* Behavioural tests for the free price relay: functions/api/price.js,
 * functions/api/quote.js and their shared guard, functions/api/_relay_guard.js
 * (REFINE200 #166, 2026-10-14).
 *
 * WHY THIS FILE EXISTS: these two endpoints serve every chart and every header
 * quote on the site, and no test ever ran them -- price.js was only regex-read,
 * quote.js and _relay_guard.js not at all. The defects found alongside this
 * suite (a zero-candle answer cached as a 200, a live-price call nobody reads
 * spent before every history fetch, the server asking Binance it cannot reach,
 * LINK quoted as Chainlink) were invisible for exactly that reason.
 *
 * Pattern follows test/api_guards.test.js: the REAL sources are read, the ESM
 * surface stripped, the real helpers prepended, and the handlers run in a vm
 * sandbox against a fake network and a fake caches.default.
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

const SRC = (f) => fs.readFileSync(path.join(__dirname, "..", "functions", "api", f), "utf8");
const STRIP_EXPORTS = (src) => src
  .replace(/export\s+async\s+function/g, "async function")
  .replace(/export\s+function/g, "function")
  .replace(/export\s+const/g, "const");
const HELPERS = ["_secrets.js", "_prices.js", "_relay_guard.js"].map((f) => STRIP_EXPORTS(SRC(f))).join("\n");
const LOCAL_IMPORTS = /^import\s*\{[^}]*\}\s*from\s*"\.\/_[a-z_]+\.js";\s*$/gm;

const NOW_MS = 1_780_000_000_000;
const NOW_S = NOW_MS / 1000;

/* Load one endpoint with a fresh module scope (so _relay_guard's per-IP Map
 * starts empty) against `fetchImpl` and an in-memory caches.default. */
function load(file, { fetchImpl, cache = new Map(), cacheThrows = false } = {}) {
  const source = HELPERS + "\n" + SRC(file)
    .replace(LOCAL_IMPORTS, "")
    .replace(/export const onRequestGet\s*=/, "globalThis.onRequestGet =")
    .replace(/export async function onRequestGet/, "globalThis.onRequestGet = async function");
  const calls = [];
  const sandbox = {
    Response, Request, URL, JSON, Math, String, Number, Array, Object, Promise, Set, Map,
    parseInt, parseFloat, isFinite, encodeURIComponent, console,
    Date: class extends Date { static now() { return NOW_MS; } },
    AbortSignal: { timeout: () => null },
    fetch: (url, init) => { calls.push(String(url)); return fetchImpl(String(url), init); },
    caches: { default: {
      match: async (u) => { if (cacheThrows) throw new Error("cache down"); const r = cache.get(u); return r ? r.clone() : undefined; },
      put: async (u, r) => { if (cacheThrows) throw new Error("cache down"); cache.set(u, r); },
    } },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source + "\n;globalThis.__h = { isCryptoSymbol, overPxLimit, cacheMatch, cachePut, PX_REQS_PER_MIN };", sandbox);
  return { handler: sandbox.onRequestGet, h: sandbox.__h, calls, cache };
}

/* Run a handler like the runtime does: waitUntil promises are settled before
 * the test looks at the cache (a rejected one is the runtime's to log, never
 * the response's to fail). */
async function hit(ep, url, { env = {}, ip = "1.1.1.1" } = {}) {
  const waits = [];
  const request = new Request("https://x" + url, { headers: { "CF-Connecting-IP": ip } });
  const res = await ep.handler({ request, env, waitUntil: (p) => waits.push(p) });
  await Promise.allSettled(waits);
  let body = null;
  try { body = await res.clone().json(); } catch (_) { /* not JSON */ }
  return { res, body, status: res.status };
}

// A Yahoo chart result: `n` daily sessions ending at `endSec`, meta price `px`.
function yres(endSec, n, px = 50) {
  const ts = [], c = [];
  for (let i = n - 1; i >= 0; i--) { ts.push(endSec - i * 86400); c.push(10 + (n - i) / 100); }
  return { meta: { regularMarketPrice: px, currency: "AUD", regularMarketTime: endSec },
           timestamp: ts, indicators: { quote: [{ open: c, high: c, low: c, close: c, volume: c.map(() => 5) }] } };
}
const ok = (json) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(json) });
const fail = (status = 429) => Promise.resolve({ ok: false, status, json: () => Promise.resolve({}) });
const isYahoo = (u) => /finance\.yahoo\.com/.test(u);
const isBinance = (u) => /binance/.test(u);

/* A Yahoo that answers every chart call: an explicit window with the bars in
 * that window, a range= call with `n` recent bars. */
function yahooOK({ n = 300, px = 50 } = {}) {
  return (u) => {
    if (!isYahoo(u)) return fail(451);
    const m = /period1=(\d+)&period2=(\d+)/.exec(u);
    if (m) return ok({ chart: { result: [yres(Math.min(+m[2], NOW_S) - 86400, Math.floor((+m[2] - +m[1]) / 86400) - 1, px)] } });
    return ok({ chart: { result: [yres(NOW_S - 86400, n, px)] } });
  };
}

// ═══════════════════════════ input validation ════════════════════════════════
suite("both endpoints refuse a malformed symbol before any upstream call");

test("price.js: 400 for a bad symbol, never cached, nothing fetched", async () => {
  for (const sym of ["", "a b", "x".repeat(31), "BHP;rm", "<script>"]) {
    const ep = load("price.js", { fetchImpl: yahooOK() });
    const { status } = await hit(ep, `/api/price?symbol=${encodeURIComponent(sym)}&range=1y&interval=1d`);
    assert.equal(status, 400, JSON.stringify(sym));
    assert.equal(ep.calls.length, 0);
    assert.equal(ep.cache.size, 0);
  }
});

test("quote.js: 400 for a bad symbol, nothing fetched", async () => {
  for (const sym of ["", "a b", "x".repeat(21), "BHP;rm"]) {
    const ep = load("quote.js", { fetchImpl: yahooOK() });
    const { status } = await hit(ep, `/api/quote?sym=${encodeURIComponent(sym)}`);
    assert.equal(status, 400, JSON.stringify(sym));
    assert.equal(ep.calls.length, 0);
  }
});

// ═══════════════════════════ _relay_guard ════════════════════════════════════
suite("_relay_guard.js — the per-IP limiter and the edge cache");

test("more than 120 a minute from one IP is a 429; another IP is unaffected", async () => {
  for (const file of ["price.js", "quote.js"]) {
    const ep = load(file, { fetchImpl: yahooOK() });
    const q = (i) => (file === "price.js" ? `/api/price?symbol=S${i}` : `/api/quote?sym=S${i}`);
    for (let i = 0; i < ep.h.PX_REQS_PER_MIN; i++) {
      assert.equal((await hit(ep, q(i))).status, 200, `${file} request ${i + 1}`);
    }
    const over = await hit(ep, q(999));
    assert.equal(over.status, 429, file);
    assert.equal(over.res.headers.get("Cache-Control"), "no-store");
    assert.equal((await hit(ep, q(1000), { ip: "2.2.2.2" })).status, 200, "the limit is per IP");
  }
});

test("a repeated request is served from the edge cache without an upstream call", async () => {
  const ep = load("price.js", { fetchImpl: yahooOK() });
  const url = "/api/price?symbol=BHP.AX&range=1y&interval=1d";
  const first = await hit(ep, url);
  assert.equal(first.status, 200);
  assert.equal(first.res.headers.get("Cache-Control"), "public, max-age=15, s-maxage=20");
  const n = ep.calls.length;
  const second = await hit(ep, url);
  assert.equal(second.status, 200);
  assert.equal(ep.calls.length, n, "a cache hit must not touch Yahoo");
  assert.deepEqual(second.body.candles.length, first.body.candles.length);
});

test("errors are never cached: a dead upstream is a 502 with no-store, and the next call retries", async () => {
  for (const file of ["price.js", "quote.js"]) {
    let up = false;
    const ep = load(file, { fetchImpl: (u) => (up ? yahooOK()(u) : fail(500)) });
    const url = file === "price.js" ? "/api/price?symbol=BHP.AX" : "/api/quote?sym=BHP.AX";
    const r = await hit(ep, url);
    assert.equal(r.status, 502, file);
    assert.equal(r.res.headers.get("Cache-Control"), "no-store");
    assert.equal(ep.cache.size, 0, file + ": an error must never be cached");
    up = true;
    assert.equal((await hit(ep, url)).status, 200, file + ": the retry must reach upstream");
  }
});

test("a broken cache never fails the request", async () => {
  const ep = load("quote.js", { fetchImpl: yahooOK(), cacheThrows: true });
  const r = await hit(ep, "/api/quote?sym=BHP.AX");
  assert.equal(r.status, 200);
  assert.equal(r.body.price, 50);
  assert.equal(await ep.h.cacheMatch(new Request("https://x/y")), null);
  const resp = new Response("body");
  assert.equal(ep.h.cachePut({ request: new Request("https://x/y") }, resp), resp,
    "no waitUntil: the response still comes back, readable");
  assert.equal(await resp.text(), "body");
});

// ═══════════════════════════ price.js candle path ════════════════════════════
suite("price.js — the candle path (REFINE200 #162 / #163)");

test("a candle request with no candles is a 502, never a cached 200 ok:true bars:0 (#163)", async () => {
  // The live 1d call answers, every history call is throttled: that used to
  // be a 200 {ok:true, bars:0} that every viewer got for 20 seconds.
  const ep = load("price.js", { fetchImpl: (u) => (/range=1d&/.test(u)
    ? ok({ chart: { result: [yres(NOW_S, 1, 42)] } }) : fail(429)) });
  const r = await hit(ep, "/api/price?symbol=BHP.AX&range=25y&interval=1d");
  assert.equal(r.status, 502);
  assert.equal(r.body.ok, false);
  assert.match(r.body.error, /no history/, "refused on purpose, not by a crash on an empty array");
  assert.equal(r.res.headers.get("Cache-Control"), "no-store");
  assert.equal(ep.cache.size, 0);
});

test("a 25y chart costs the five window calls and nothing else; price rides the newest window (#162)", async () => {
  const ep = load("price.js", { fetchImpl: yahooOK({ px: 77.7 }) });
  const r = await hit(ep, "/api/price?symbol=BHP.AX&range=25y&interval=1d");
  assert.equal(r.status, 200);
  assert.equal(r.body.source, "yahoo-deep");
  assert.equal(ep.calls.length, 5, "one call per 5-year window: " + ep.calls.join("\n"));
  assert.ok(ep.calls.every((u) => /period1=/.test(u)), "no separate range=1d live-price call");
  assert.equal(r.body.price, 77.7, "the live price Yahoo already sent with the newest window");
});

test("with no meta price the candle answer falls back to the last close", async () => {
  const ep = load("price.js", { fetchImpl: (u) => {
    const r = yres(NOW_S - 86400, 30, null);
    delete r.meta.regularMarketPrice;
    return isYahoo(u) ? ok({ chart: { result: [r] } }) : fail();
  } });
  const r = await hit(ep, "/api/price?symbol=BHP.AX&range=1mo&interval=1d");
  assert.equal(r.status, 200);
  assert.equal(r.body.price, r.body.candles[r.body.candles.length - 1].close);
});

test("the price-only path still answers a bare quote", async () => {
  const ep = load("price.js", { fetchImpl: yahooOK({ px: 12.34 }) });
  const r = await hit(ep, "/api/price?symbol=BHP.AX");
  assert.equal(r.status, 200);
  assert.equal(r.body.price, 12.34);
  assert.equal(ep.calls.length, 1);
});

test("CHART_MAX_YEARS=5 really steps a 25y request down to ONE 5y call (the reverse switch)", async () => {
  const ep = load("price.js", { fetchImpl: yahooOK() });
  const r = await hit(ep, "/api/price?symbol=BHP.AX&range=25y&interval=1d", { env: { CHART_MAX_YEARS: "5" } });
  assert.equal(r.status, 200);
  assert.equal(ep.calls.length, 1, ep.calls.join("\n"));
  assert.match(ep.calls[0], /[?&]range=5y&/);
  assert.equal(r.body.source, "yahoo");
});

test("an EODHD key pasted with a BOM / newline reaches EODHD clean (#164)", async () => {
  let eod = "";
  const ep = load("price.js", { fetchImpl: (u) => {
    if (/eodhd\.com/.test(u)) {
      eod = u;
      return ok([{ date: "2026-05-27", open: 1, high: 2, low: 0.5, close: 1.5, adjusted_close: 1.5, volume: 10 },
                 { date: "2026-05-28", open: 1, high: 2, low: 0.5, close: 1.6, adjusted_close: 1.6, volume: 10 }]);
    }
    return yahooOK()(u);
  } });
  const r = await hit(ep, "/api/price?symbol=BHP.AX&range=25y&interval=1d",
    { env: { EODHD_API_TOKEN: "\ufeffk3y\r\n" } });
  assert.equal(r.status, 200);
  assert.equal(r.body.source, "eodhd");
  assert.match(eod, /[?&]api_token=k3y&/, "the key must be sent trimmed: " + eod);
});

// ═══════════════════ Binance from the server: off by default ═════════════════
suite("the server-side Binance leg runs only with PRICES_TRY_BINANCE=1 (REFINE200 #76)");

test("price.js: a crypto chart and a crypto price go straight to Yahoo <base>-USD by default", async () => {
  for (const url of ["/api/price?symbol=BTC-USD&type=crypto&range=5y&interval=1d&src=binance",
                     "/api/price?symbol=BTC-USD"]) {
    const ep = load("price.js", { fetchImpl: yahooOK() });
    const r = await hit(ep, url);
    assert.equal(r.status, 200, url);
    assert.ok(!ep.calls.some(isBinance), "Cloudflare cannot reach Binance -- do not spend calls on it: " + ep.calls.join(" "));
    assert.ok(ep.calls.every((u) => /\/chart\/BTC-USD\?/.test(u)), url);
  }
});

test("price.js: with the flag set, crypto asks Binance first", async () => {
  const klines = Array.from({ length: 30 }, (_, i) =>
    [NOW_MS - (29 - i) * 864e5, "1", "2", "0.5", "1.5", "3", 0, "4.5"]);
  const ep = load("price.js", { fetchImpl: (u) => (isBinance(u) ? ok(klines) : yahooOK()(u)) });
  const r = await hit(ep, "/api/price?symbol=BTC-USD&type=crypto&range=1mo&interval=1d",
    { env: { PRICES_TRY_BINANCE: "1" } });
  assert.equal(r.body.source, "binance");
  assert.match(ep.calls[0], /^https:\/\/data-api\.binance\.vision\//);
  assert.equal(r.body.price, 1.5, "a Binance chart's price is its last close");
});

test("quote.js: Yahoo by default, Binance first only with the flag", async () => {
  let ep = load("quote.js", { fetchImpl: yahooOK({ px: 60000 }) });
  let r = await hit(ep, "/api/quote?sym=BTC-USD");
  assert.equal(r.body.source, "yahoo");
  assert.ok(!ep.calls.some(isBinance));
  ep = load("quote.js", { fetchImpl: (u) => (isBinance(u) ? ok({ price: "61000.5" }) : yahooOK()(u)) });
  r = await hit(ep, "/api/quote?sym=BTC-USD", { env: { PRICES_TRY_BINANCE: "1" } });
  assert.equal(r.body.source, "binance");
  assert.equal(r.body.price, 61000.5);
});

// ═══════════════════ which symbols are crypto (REFINE200 #167) ════════════════
suite("a bare ticker is a stock: ATOM is Atomera, LINK is Interlink Electronics");

test("isCryptoSymbol is the suffix rule only", () => {
  const { h } = load("quote.js", { fetchImpl: yahooOK() });
  for (const s of ["BTC-USD", "eth-usd", "BTCUSDT", "SOL-USDT"]) assert.equal(h.isCryptoSymbol(s), true, s);
  for (const s of ["ATOM", "LINK", "OP", "LTC", "SOL", "TRX", "APT", "SEI", "NEAR", "SUI", "BTC", "BHP.AX", "AAPL", "^AXJO"]) {
    assert.equal(h.isCryptoSymbol(s), false, s + " must not be read as a coin");
  }
});

test("/api/quote?sym=LINK quotes the stock, not Chainlink", async () => {
  const ep = load("quote.js", { fetchImpl: yahooOK({ px: 7.1 }) });
  const r = await hit(ep, "/api/quote?sym=LINK", { env: { PRICES_TRY_BINANCE: "1" } });
  assert.equal(r.status, 200);
  assert.ok(ep.calls.every((u) => /\/chart\/LINK\?/.test(u)), ep.calls.join(" "));
  assert.ok(!ep.calls.some(isBinance));
});

test("/api/price?symbol=ATOM charts the stock; type=crypto still makes it the coin", async () => {
  let ep = load("price.js", { fetchImpl: yahooOK() });
  await hit(ep, "/api/price?symbol=ATOM&range=1y&interval=1d", { env: { PRICES_TRY_BINANCE: "1" } });
  assert.ok(ep.calls.every((u) => /\/chart\/ATOM\?/.test(u)), ep.calls.join(" "));
  ep = load("price.js", { fetchImpl: yahooOK() });
  await hit(ep, "/api/price?symbol=ATOM&type=crypto&range=1y&interval=1d");
  assert.ok(ep.calls.every((u) => /\/chart\/ATOM-USD\?/.test(u)), "the type hint still wins: " + ep.calls.join(" "));
});

(async () => {
  for (const item of QUEUE) {
    if (item.suite) { console.log(`\n── ${item.suite} ──`); continue; }
    try { await item.fn(); console.log(`  ✓  ${item.name}`); passed++; }
    catch (e) { console.error(`  ✗  ${item.name}\n     ${e.message}`); failed++; }
  }
  console.log(`\nprice_api.test.js: ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

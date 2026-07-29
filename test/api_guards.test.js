#!/usr/bin/env node
/* Guard-rail tests for the four state-touching Pages Functions —
 * functions/api/journal.js, scan.js, close.js, tick.js.
 *
 * WHY THIS FILE EXISTS (2026-07-29): three of these guards were verified wrong
 * the same day, and none of them had a single test.
 *
 *   1. journal.js counted GET+PUT against 30/hr — UNDER the journal page's own
 *      poll cadence (silentPull every 60s = 60 GET/hr), so a tab left open
 *      rate-limited ITSELF out of cloud sync within ~30 minutes of every UTC
 *      hour. And the limiter wrote KV on every ALLOWED request, against the
 *      miss-counter's own stated goal ("the write quota stays protected").
 *      Now: GETs uncapped (the miss counter is the enumeration guard), PUTs
 *      capped, counter writes stop at the cap.
 *   2. scan.js/close.js wrote their cooldown + daily counter BEFORE the GitHub
 *      dispatch, and kept them when it failed — five minutes of "it's still
 *      running" about a run that never existed, plus a burned daily slot per
 *      failed attempt. Now: refunded on definite failure, kept on timeout
 *      (the dispatch MAY have landed; a duplicate run costs more than a wait).
 *   3. tick.js's crypto price fell back to Yahoo with the BARE base symbol.
 *      _prices.js's own header names the hazard: a bare base resolves to a
 *      same-named EQUITY (BDX → Becton Dickinson, ~$230) — and this is the one
 *      call site that AUTO-CLOSES positions off the price it fetches.
 *
 * Pattern follows test/health.test.js: read the REAL source, strip the ESM
 * surface, run it in a vm sandbox — no re-typed mirror to drift.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

let passed = 0, failed = 0;
function test(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { console.log(`  ✓  ${name}`); passed++; })
    .catch((e) => { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; });
}
const suite = (name) => console.log(`\n── ${name} ──`);

const SRC = (f) => fs.readFileSync(path.join(__dirname, "..", "functions", "api", f), "utf8");

function loadModule(file, { strip = [], sandboxExtra = {} } = {}) {
  let source = SRC(file);
  for (const [re, sub] of strip) source = source.replace(re, sub);
  const sandbox = {
    Response, Request, URL, TextEncoder, JSON, Math, Date, String, Number,
    Array, Object, Promise, Set, Map, parseInt, parseFloat, isFinite,
    setTimeout, clearTimeout, AbortController, console,
    crypto: globalThis.crypto,
    ...sandboxExtra,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return sandbox;
}

/* A Map-backed KV fake that records every operation — the tests assert on the
 * op log as much as the state, because "how many writes" IS the defect. */
function fakeKV(initial = {}) {
  const store = new Map(Object.entries(initial));
  const ops = [];
  return {
    store, ops,
    async get(k) { ops.push(["get", k]); return store.has(k) ? store.get(k) : null; },
    async put(k, v, opts) { ops.push(["put", k, v]); store.set(k, String(v)); void opts; },
    async delete(k) { ops.push(["delete", k]); store.delete(k); },
    async list({ prefix = "", cursor } = {}) {
      void cursor;
      const keys = [...store.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name }));
      return { keys, list_complete: true, cursor: null };
    },
    writes(pfx = "") { return ops.filter(([op, k]) => op === "put" && k.startsWith(pfx)).length; },
  };
}

// ═══════════════════ 1. journal.js — the sync rate limiter ═══════════════════

// NOTE the replacement is `globalThis.x =`, not `const x =`: vm scripts put
// `function` declarations on the contextified sandbox but keep `const` in a
// separate lexical environment the test could never reach.
const J = loadModule("journal.js", {
  strip: [
    [/export const onRequestGet/, "globalThis.onRequestGet"],
    [/export const onRequestPut/, "globalThis.onRequestPut"],
  ],
});
const jGet = (env, headers) => J.onRequestGet({
  env, request: new Request("https://x/api/journal", { headers }),
});
const jPut = (env, headers, body) => J.onRequestPut({
  env, request: new Request("https://x/api/journal", {
    method: "PUT", headers, body: JSON.stringify(body || { trades: [] }),
  }),
});
const H = { "X-Sync-Code": "viv-code", "CF-Connecting-IP": "1.2.3.4" };

const jTests = async () => {
  suite("journal.js — polling can never lock itself out");

  await test("61 GETs in one hour all succeed — the poll cadence is 60/hr and the old cap was 30", async () => {
    const kv = fakeKV();
    const env = { JOURNAL_KV: kv };
    await jPut(env, H, { trades: [{ id: "t1" }] });      // seed so GETs are hits
    for (let i = 0; i < 61; i++) {
      const r = await jGet(env, H);
      assert.equal(r.status, 200, `GET #${i + 1} returned ${r.status}`);
    }
  });

  await test("a hit-GET writes NOTHING to KV — counting was burning the write quota", async () => {
    const kv = fakeKV();
    const env = { JOURNAL_KV: kv };
    await jPut(env, H, { trades: [] });
    const before = kv.writes();
    for (let i = 0; i < 10; i++) await jGet(env, H);
    assert.equal(kv.writes(), before, "10 successful GETs must cost zero KV writes");
  });

  await test("PUTs are still capped per hour", async () => {
    const kv = fakeKV();
    const env = { JOURNAL_KV: kv };
    let limited = 0;
    for (let i = 0; i < 40; i++) {
      const r = await jPut(env, H, { trades: [] });
      if (r.status === 429) limited++;
    }
    assert.ok(limited >= 5, `expected the tail of 40 PUTs limited, got ${limited}`);
  });

  await test("over the PUT cap the counter itself stops being written", async () => {
    const kv = fakeKV();
    const env = { JOURNAL_KV: kv };
    for (let i = 0; i < 40; i++) await jPut(env, H, { trades: [] });
    const counterWrites = kv.ops.filter(([op, k]) => op === "put" && k.startsWith("ratelimit:journal:")).length;
    assert.ok(counterWrites <= 31, `counter kept writing past the cap (${counterWrites})`);
  });

  await test("an unknown code still counts a miss (the enumeration guard is the GET guard now)", async () => {
    const kv = fakeKV();
    const env = { JOURNAL_KV: kv };
    await jGet(env, { ...H, "X-Sync-Code": "wrong-code" });
    assert.equal(kv.writes("ratelimit:journal-miss:"), 1);
  });

  await test("30 misses lock the IP out for the day", async () => {
    const kv = fakeKV();
    const env = { JOURNAL_KV: kv };
    for (let i = 0; i < 30; i++) await jGet(env, { ...H, "X-Sync-Code": `guess-${i}` });
    const r = await jGet(env, H);                        // even the RIGHT code now
    assert.equal(r.status, 429);
  });
};

// ═══════════════ 2. scan.js / close.js — the cooldown refund ════════════════

function ghFetchStub(status) {
  return async (url, opts) => {
    if (opts && opts.signal && opts.signal.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });
    if (status === "abort") throw Object.assign(new Error("The operation was aborted"), { name: "AbortError" });
    if (status === "network") throw new TypeError("fetch failed");
    return { status, ok: status < 300, json: async () => ({}) };
  };
}

const scanTests = async () => {
  suite("scan.js — a failed dispatch must not poison the cooldown");

  const load = (fetchImpl) => loadModule("scan.js", {
    strip: [[/export const onRequestPost/, "globalThis.onRequestPost"]],
    sandboxExtra: { fetch: fetchImpl },
  });
  const call = (S, env) => S.onRequestPost({
    env, request: new Request("https://x/api/scan", {
      method: "POST", body: JSON.stringify({ market: "asx" }),
    }),
  });

  await test("204 keeps the cooldown (the run IS running)", async () => {
    const kv = fakeKV();
    const S = load(ghFetchStub(204));
    const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 202);
    assert.ok(kv.store.has("ratelimit:scan:asx"), "cooldown must persist on success");
  });

  await test("a 401 (dead token) refunds the cooldown AND the daily slot", async () => {
    const kv = fakeKV();
    const S = load(ghFetchStub(401));
    const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 502);
    assert.ok(!kv.store.has("ratelimit:scan:asx"),
      "cooldown stuck after a failed dispatch — five minutes of 'it's still running' about nothing");
    const day = [...kv.store].find(([k]) => k.startsWith("ratelimit:scan:day:"));
    assert.equal(day && day[1], "0", "daily slot must be restored");
  });

  await test("after a failed dispatch the user can retry immediately", async () => {
    const kv = fakeKV();
    let status = 401;
    const S = load(async (u, o) => ghFetchStub(status)(u, o));
    await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    status = 204;                                        // token fixed / GitHub back
    const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 202, "retry after refund must dispatch, not 429");
  });

  await test("a network error refunds; nothing was dispatched", async () => {
    const kv = fakeKV();
    const S = load(ghFetchStub("network"));
    const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 502);
    assert.ok(!kv.store.has("ratelimit:scan:asx"));
  });

  await test("a TIMEOUT keeps the cooldown — the dispatch may have landed", async () => {
    const kv = fakeKV();
    const S = load(ghFetchStub("abort"));
    const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 504);
    assert.ok(kv.store.has("ratelimit:scan:asx"),
      "refunding a timeout invites a duplicate Actions run");
  });

  suite("close.js — same refund contract");

  const loadC = (fetchImpl) => loadModule("close.js", {
    strip: [[/export const onRequestPost/, "globalThis.onRequestPost"]],
    sandboxExtra: { fetch: fetchImpl },
  });
  const callC = (S, env) => S.onRequestPost({
    env, request: new Request("https://x/api/close", {
      method: "POST",
      body: JSON.stringify({ symbol: "WES", market: "asx", price: 71.5 }),
    }),
  });

  await test("close: failed dispatch refunds the per-symbol cooldown", async () => {
    const kv = fakeKV();
    const S = loadC(ghFetchStub(403));
    const r = await callC(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 502);
    assert.ok(!kv.store.has("ratelimit:close:WES"));
  });

  await test("close: success keeps it; timeout keeps it", async () => {
    for (const [status, want] of [[204, 202], ["abort", 504]]) {
      const kv = fakeKV();
      const S = loadC(ghFetchStub(status));
      const r = await callC(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
      assert.equal(r.status, want);
      assert.ok(kv.store.has("ratelimit:close:WES"), `cooldown must persist on ${status}`);
    }
  });
};

// ══════════ 3. tick.js — the watcher prices the RIGHT instrument ═════════════

const tickTests = async () => {
  suite("tick.js — crypto fallback queries <base>-USD, never the bare base");

  const yahooCalls = [];
  const T = loadModule("tick.js", {
    strip: [
      [/import\s*\{[^}]*\}\s*from\s*"\.\/_prices\.js";/, ""],
      [/import\s*\{[^}]*\}\s*from\s*"\.\/_vivek_manage\.js";/, ""],
      [/export const onRequest\b/, "const onRequest"],
    ],
    sandboxExtra: {
      fetchBinancePrice: async () => null,               // thin coin: not on Binance
      fetchYahooChart: async (sym) => { yahooCalls.push(sym); return { meta: { regularMarketPrice: 0.07 } }; },
      // real normaliser, inlined from _prices.js semantics — asserted below
      yahooCryptoSymbol: (sym) => String(sym || "").toUpperCase()
        .replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "") + "-USD",
      isVivek: () => false,
      manageVivek: () => false,
    },
  });

  await test("a bare journal base like BDX goes to Yahoo as BDX-USD", async () => {
    yahooCalls.length = 0;
    const px = await T.cryptoPrice("BDX", {});
    assert.equal(px, 0.07);
    assert.deepEqual(yahooCalls, ["BDX-USD"],
      "bare BDX resolves to Becton Dickinson (~$230) — the wrong instrument under an auto-closer");
  });

  await test("an already-suffixed symbol is not double-suffixed", async () => {
    yahooCalls.length = 0;
    await T.cryptoPrice("ETH-USD", {});
    assert.deepEqual(yahooCalls, ["ETH-USD"]);
  });

  await test("the shipped tick.js actually imports the normaliser (the stub above must mirror _prices.js)", () => {
    const src = SRC("tick.js");
    assert.match(src, /import\s*\{[^}]*yahooCryptoSymbol[^}]*\}\s*from\s*"\.\/_prices\.js"/,
      "tick.js must take yahooCryptoSymbol from _prices.js, not roll its own");
    // and the real exporter still exports it, so the import cannot go dead:
    assert.match(SRC("_prices.js"), /export function yahooCryptoSymbol/);
  });

  await test("a null price stays null — no fill on a missing quote", async () => {
    const T2 = loadModule("tick.js", {
      strip: [
        [/import\s*\{[^}]*\}\s*from\s*"\.\/_prices\.js";/, ""],
        [/import\s*\{[^}]*\}\s*from\s*"\.\/_vivek_manage\.js";/, ""],
        [/export const onRequest\b/, "const onRequest"],
      ],
      sandboxExtra: {
        fetchBinancePrice: async () => null,
        fetchYahooChart: async () => { throw new Error("both hosts down"); },
        yahooCryptoSymbol: (s) => s + "-USD",
        isVivek: () => false, manageVivek: () => false,
      },
    });
    assert.equal(await T2.cryptoPrice("BDX", {}), null);
  });
};

// ── summary (sequential so the suite headers stay attached to their tests) ───
(async () => {
  await jTests();
  await scanTests();
  await tickTests();
  console.log(`\napi_guards.test.js: ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

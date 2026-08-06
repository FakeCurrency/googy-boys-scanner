#!/usr/bin/env node
/* Guard-rail tests for the five state-touching Pages Functions —
 * functions/api/journal.js, scan.js, close.js, tick.js, heartbeat.js.
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

// ═════════ 4. heartbeat.js — the self-heal leg, and what it must NOT do ══════
//
// Added 2026-08-04, the day GitHub's cron scheduler dropped fires across three
// workflows at once and the ASX session went 3h39m unscanned during a live
// pre-registered cycle. Every backstop in this repo is itself a cron, so all of
// them were dropped by the same outage — adding a fourth cron could not have
// helped. /api/heartbeat is the uncorrelated leg: an EXTERNAL monitor pings it
// and it dispatches a scan when one is overdue.
//
// It lives in this file rather than its own because it is the fifth
// state-touching Pages Function and it inherits scan.js's refund contract
// verbatim — the two belong where they can be read against each other.

const hbTests = async () => {
  suite("heartbeat.js — heal when overdue, and never page on success");

  // Both exports must be stripped. `onRequestGet` is a function DECLARATION, so
  // the vm puts it on the sandbox by itself; `onRequestHead` is a `const`, which
  // lives in a lexical environment the test can never reach — hence the
  // globalThis form (same reason journal.js's loader uses it).
  const load = (fetchImpl) => loadModule("heartbeat.js", {
    strip: [[/export async function onRequestGet/, "async function onRequestGet"],
            [/export const onRequestHead/, "globalThis.onRequestHead"]],
    sandboxExtra: { fetch: fetchImpl },
  });
  const minsAgo = (m) => new Date(Date.now() - m * 6e4).toISOString();
  // book: an object to serve as vivek_bot_book.json, or a number = HTTP status.
  const envFor = (book, extra) => ({
    ASSETS: {
      fetch: async () => (typeof book === "number"
        ? new Response("err", { status: book })
        : new Response(JSON.stringify(book), { status: 200 })),
    },
    ...extra,
  });
  const call = (H, env, qs) => H.onRequestGet({
    env, request: new Request("https://x/api/heartbeat" + (qs || "")),
  });
  const FRESH = { updated_at: minsAgo(10) };
  const STALE = { updated_at: minsAgo(200) };

  await test("a SUCCESSFUL HEAL returns 200 — an alarm that fires on success gets muted", async () => {
    const H = load(ghFetchStub(204));
    const r = await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }));
    const b = await r.json();
    assert.equal(r.status, 200, "stale is the condition this exists to FIX, not a fault to report");
    assert.equal(b.action, "dispatched");
    assert.equal(b.healthy, false, "it still records that the book WAS stale");
  });

  await test("a fresh book dispatches NOTHING", async () => {
    let hits = 0;
    const H = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const r = await call(H, envFor(FRESH, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }));
    assert.equal(r.status, 200);
    assert.equal((await r.json()).action, "none");
    assert.equal(hits, 0, "a healthy pipeline must never be dispatched at");
  });

  await test("an unreadable stamp FAILS LOUD — 503, and no dispatch", async () => {
    // Reading it as stale would dispatch a scan on every probe, for ever, off
    // one corrupt file; reading it as fresh hides the outage. Neither.
    let hits = 0;
    const H = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const r = await call(H, envFor({ updated_at: "not-a-date" },
      { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }));
    assert.equal(r.status, 503);
    assert.ok(/updated_at/.test((await r.json()).error));
    assert.equal(hits, 0);
  });

  await test("an unreadable asset is 503, not a heal", async () => {
    const H = load(ghFetchStub(204));
    const r = await call(H, envFor(404, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }));
    assert.equal(r.status, 503);
  });

  await test("stale with no token is 503 — a disarmed healer nothing else can see", async () => {
    const H = load(ghFetchStub(204));
    const r = await call(H, envFor(STALE, { JOURNAL_KV: fakeKV() }));
    assert.equal(r.status, 503);
    assert.equal((await r.json()).action, "cannot_heal");
  });

  await test("a FRESH book with no token stays green — an unarmed healer only matters once needed", async () => {
    const H = load(ghFetchStub(204));
    const r = await call(H, envFor(FRESH, { JOURNAL_KV: fakeKV() }));
    assert.equal(r.status, 200);
  });

  await test("the 5-minute cooldown key is SHARED with /api/scan", async () => {
    // Load-bearing: a manual SCAN and a heal must never dispatch the same run
    // twice. The key below is exactly what scan.js writes.
    let hits = 0;
    const H = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const kv = fakeKV({ "ratelimit:scan:all": "1" });
    const r = await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv }));
    assert.equal(r.status, 200, "a heal already in flight is the system working");
    assert.equal((await r.json()).action, "cooling_down");
    assert.equal(hits, 0);
  });

  await test("the DAILY cap key is NOT shared — the healer cannot eat the SCAN button", async () => {
    const H = load(ghFetchStub(204));
    const kv = fakeKV();
    await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv }));
    const keys = [...kv.store.keys()];
    assert.ok(keys.some((k) => k.startsWith("ratelimit:heal:day:")), JSON.stringify(keys));
    assert.ok(!keys.some((k) => k.startsWith("ratelimit:scan:day:")),
      "a shared daily budget lets an automated healer starve the owner's manual SCAN on exactly the day he reaches for it");
  });

  await test("hitting the heal cap while STILL stale is 503 — a runaway healer is worse than a stopped one", async () => {
    let hits = 0;
    const H = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const day = new Date().toISOString().slice(0, 10);
    const kv = fakeKV({ ["ratelimit:heal:day:" + day]: "24" });
    const r = await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv }));
    assert.equal(r.status, 503);
    assert.equal((await r.json()).action, "heal_cap_reached");
    assert.equal(hits, 0);
  });

  await test("a 401 refunds the cooldown and never echoes GitHub's body", async () => {
    const H = load(ghFetchStub(401));
    const kv = fakeKV();
    const r = await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t0ken", JOURNAL_KV: kv }));
    const b = await r.json();
    assert.equal(r.status, 503);
    assert.equal(b.action, "dispatch_failed");
    assert.ok(/GH_DISPATCH_TOKEN/.test(b.error), b.error);
    assert.ok(!/t0ken/.test(JSON.stringify(b)), "the token must never reach the caller");
    assert.ok(!kv.store.has("ratelimit:scan:all"),
      "nothing was dispatched — the retry must not be blocked for five minutes");
  });

  await test("a network error refunds; a TIMEOUT deliberately does not", async () => {
    const kvNet = fakeKV();
    let r = await call(load(ghFetchStub("network")),
      envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kvNet }));
    assert.equal((await r.json()).action, "dispatch_error");
    assert.ok(!kvNet.store.has("ratelimit:scan:all"), "a clean failure dispatched nothing");

    const kvAbort = fakeKV();
    r = await call(load(ghFetchStub("abort")),
      envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kvAbort }));
    assert.equal((await r.json()).action, "dispatch_timeout");
    assert.ok(kvAbort.store.has("ratelimit:scan:all"),
      "on timeout the dispatch MAY have landed — a duplicate scan costs more than a five-minute wait");
  });

  await test("the cooldown is written BEFORE the dispatch, closing the double-fire race", async () => {
    const kv = fakeKV();
    let seen = null;
    const H = load(async () => {
      seen = kv.store.get("ratelimit:scan:all");
      return { status: 204, ok: true, json: async () => ({}) };
    });
    await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv }));
    assert.equal(seen, "1", "a concurrent probe mid-dispatch must already see the cooldown");
  });

  await test("stale_min is clamped to 15..720 with a 90-minute default", async () => {
    const H = load(ghFetchStub(204));
    const env = () => envFor(FRESH, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() });
    const at = async (qs) => (await (await call(H, env(), qs)).json()).stale_min;
    assert.equal(await at(""), 90);
    assert.equal(await at("?stale_min=1"), 90);
    assert.equal(await at("?stale_min=9999"), 90);
    assert.equal(await at("?stale_min=45"), 45);
  });

  await test("answers are never cached and always carry the age they decided on", async () => {
    const H = load(ghFetchStub(204));
    const r = await call(H, envFor(STALE, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }));
    assert.equal(r.headers.get("Cache-Control"), "no-store");
    assert.ok((await r.json()).age_min > 90);
  });

  await test("HEAD is answered, not 404'd — the trap that silently disarmed the whole loop", async () => {
    // Cloudflare Pages sends a method with NO handler onward to the static
    // assets; nothing is served at /api/heartbeat, so an unhandled HEAD is a
    // 404 and the handler never runs. UptimeRobot's current dashboard defaults
    // NEW monitors to HEAD, so the first armed heartbeat monitor reported DOWN
    // for its entire life against a healthy endpoint while the healer executed
    // zero times (2026-08-07). Both dashboards looked armed; nothing was
    // connected. Verified live: HEAD -> 404, GET -> 200, same URL, same minute.
    const H = load(ghFetchStub(204));
    assert.equal(typeof H.onRequestHead, "function",
      "no onRequestHead export — every HEAD probe 404s before reaching the healer");
    assert.equal(H.onRequestHead, H.onRequestGet,
      "HEAD must do the same work and return the same status; the runtime drops the body");
    const r = await H.onRequestHead({
      env: envFor(FRESH, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }),
      request: new Request("https://x/api/heartbeat"),
    });
    assert.equal(r.status, 200);
  });

  await test("the ALARM answers HEAD too — same trap, worse blast radius", async () => {
    // /api/health was not broken (its monitor predates the HEAD default and
    // sends GET) and is fixed anyway: it is the last thing still speaking when
    // GitHub's scheduler dies. Recreate that monitor, or let UptimeRobot
    // migrate its default, and the alarm goes permanently red against a healthy
    // pipeline until somebody reads a 404 carefully.
    const HL = loadModule("health.js", {
      strip: [[/export async function onRequestGet/, "async function onRequestGet"],
              [/export const onRequestHead/, "globalThis.onRequestHead"]],
    });
    assert.equal(typeof HL.onRequestHead, "function", "health.js must answer HEAD");
    assert.equal(HL.onRequestHead, HL.onRequestGet);
  });

  await test("the two decisions most likely to be 'tidied away' keep their reasoning in the source", async () => {
    // The tempting future edits are "surely stale should be RED" and "surely
    // this should need a secret". Both are wrong here for reasons that only
    // exist in the comments, so the comments are load-bearing.
    const src = SRC("heartbeat.js");
    assert.ok(/RETURNS 200 WHEN IT HEALS/.test(src), "the 200-on-heal rationale was deleted");
    assert.ok(/alarm that fires on success/.test(src));
    assert.ok(/UNAUTHENTICATED BY CONSTRUCTION/.test(src),
      "if this ever grows a secret it must be a decision, not a drift");
  });
};

// ── summary (sequential so the suite headers stay attached to their tests) ───
(async () => {
  await jTests();
  await scanTests();
  await tickTests();
  await hbTests();
  console.log(`\napi_guards.test.js: ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

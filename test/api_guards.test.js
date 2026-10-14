#!/usr/bin/env node
/* Guard-rail tests for the three state-touching Pages Functions —
 * functions/api/scan.js, close.js, heartbeat.js (plus health.js's HEAD answer).
 * journal.js and tick.js were the other two until they went, 2026-09-21.
 * REFINE200 (2026-10-14) added the request guards: same-origin JSON only (#52),
 * an exit-price band and a daily cap on CLOSES (#53), no default-to-all scan
 * (#54), limiters that fail closed (#158), heal floors (#159), clean secrets
 * (#164), a 400 for an unknown heal market (#170), one close shape (#172).
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

// The two dispatch endpoints (close.js, scan.js) import the REAL access-log helper
// (2026-08-20). Its source is prepended, exports stripped, so the wrapped
// handlers run with the shipped logging code rather than a stub — the
// logging path is part of what these guards now exercise.
const STRIP_EXPORTS = (src) => src
  .replace(/export\s+async\s+function/g, "async function")
  .replace(/export\s+function/g, "function")
  .replace(/export\s+const/g, "const");
const ACCESS_LOG_HELPER = STRIP_EXPORTS(SRC("_access_log.js"));

// Same treatment for the shared GitHub workflow_dispatch transport (2026-09-17):
// the REAL _dispatch.js source is prepended, so the headers, the 10s abort and
// the cooldown refund rule these guards assert on are the shipped ones rather
// than a stub that could drift away from them. And for the two request guards
// added 2026-10-14 (_secrets.js, _same_origin.js).
const DISPATCH_HELPER = STRIP_EXPORTS(SRC("_dispatch.js"));
const GUARD_HELPERS = STRIP_EXPORTS(SRC("_secrets.js")) + "\n" + STRIP_EXPORTS(SRC("_same_origin.js"));
// Every `import {...} from "./_x.js"` line: the helpers are prepended instead.
const LOCAL_IMPORTS = /^import\s*\{[^}]*\}\s*from\s*"\.\/_[a-z_]+\.js";\s*$/gm;

function loadModule(file, { strip = [], sandboxExtra = {} } = {}) {
  let source = SRC(file);
  source = source.replace(LOCAL_IMPORTS, "");
  source = GUARD_HELPERS + "\n" + ACCESS_LOG_HELPER + "\n" + DISPATCH_HELPER + "\n" + source;
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

// (1. journal.js — the sync rate limiter — went with the KV journal store on
//  2026-09-21 when the manual journal was removed.)

// ═══════════════ 2. scan.js / close.js — the cooldown refund ════════════════

function ghFetchStub(status) {
  return async (url, opts) => {
    if (opts && opts.signal && opts.signal.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });
    if (status === "abort") throw Object.assign(new Error("The operation was aborted"), { name: "AbortError" });
    if (status === "network") throw new TypeError("fetch failed");
    return { status, ok: status < 300, json: async () => ({}) };
  };
}

// What the site's own pages send (app.js SCAN button, journal.js close-all,
// stalled.js): a same-origin JSON POST. Every call below starts from this.
const SITE = "https://x";
const browserPost = (path, body, headers = {}) => new Request(SITE + path, {
  method: "POST",
  headers: { "Content-Type": "application/json", Origin: SITE, "Sec-Fetch-Site": "same-origin", ...headers },
  body: typeof body === "string" ? body : JSON.stringify(body),
});

/* A KV whose writes all throw: what Cloudflare does once the free daily write
 * quota (1,000) is spent. Reads still work. */
function quotaSpentKV(initial = {}) {
  const kv = fakeKV(initial);
  kv.put = async (k) => { kv.ops.push(["put-refused", k]); throw new Error("KV put() limit exceeded for the day."); };
  return kv;
}

const scanTests = async () => {
  suite("scan.js — a failed dispatch must not poison the cooldown");

  const load = (fetchImpl) => loadModule("scan.js", {
    strip: [[/export const onRequestPost/, "globalThis.onRequestPost"]],
    sandboxExtra: { fetch: fetchImpl },
  });
  const call = (S, env, body = { market: "asx" }, headers) =>
    S.onRequestPost({ env, request: browserPost("/api/scan", body, headers) });

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

  suite("scan.js — what it will not dispatch (REFINE200 #52 / #54 / #158)");

  await test("a missing, unparseable or unknown market is a 400, never a FULL scan", async () => {
    // It used to default to market=all: the cheapest junk POST bought the most
    // expensive run.
    for (const body of [{}, "not json", { market: "" }, { market: "bogus" }, { market: ["asx"] }]) {
      let hits = 0;
      const S = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
      const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() }, body);
      assert.equal(r.status, 400, "accepted body " + JSON.stringify(body));
      assert.equal(hits, 0, "nothing may be dispatched for " + JSON.stringify(body));
    }
    const S = load(ghFetchStub(204));
    for (const m of ["asx", "nasdaq", "crypto", "all", " ASX "]) {
      const r = await call(S, { GH_DISPATCH_TOKEN: "t" }, { market: m });
      assert.equal(r.status, 202, m);
    }
  });

  await test("the deck's real request shape is accepted (app.js SCAN button)", async () => {
    // app.js posts {market: state.market} with Content-Type application/json,
    // same-origin; the browser adds Origin and Sec-Fetch-Site itself.
    const app = fs.readFileSync(path.join(__dirname, "..", "public", "js", "app.js"), "utf8");
    const i = app.indexOf('fetchT("/api/scan"');
    assert.ok(i > 0, "app.js no longer posts to /api/scan the way this test assumes");
    const call_ = app.slice(i, i + 300);
    assert.match(call_, /"Content-Type": "application\/json"/, "the SCAN button must send JSON");
    assert.match(call_, /JSON\.stringify\(\{ market: mkt \}\)/);
    const r = await call(load(ghFetchStub(204)), { GH_DISPATCH_TOKEN: "t" }, { market: "nasdaq" });
    assert.equal(r.status, 202);
  });

  await test("a cross-site browser POST is refused before anything else happens", async () => {
    for (const headers of [
      { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" },
      { Origin: "https://evil.example", "Sec-Fetch-Site": "" },
      { "Sec-Fetch-Site": "cross-site", Origin: SITE },
      { "Sec-Fetch-Site": "same-site", Origin: "https://preview.x" },
      { Origin: "null", "Sec-Fetch-Site": "" },
    ]) {
      const kv = fakeKV();
      let hits = 0;
      const S = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
      const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv }, { market: "asx" }, headers);
      assert.equal(r.status, 403, JSON.stringify(headers));
      assert.equal(hits, 0);
      assert.equal(kv.writes("ratelimit:"), 0, "a refused request must not touch the limiter");
    }
  });

  await test("only JSON is accepted: a form post cannot reach the dispatcher", async () => {
    // An HTML form on another site can send only urlencoded, multipart or
    // text/plain, and no CORS preflight is needed for those -- so refusing
    // them is what stops a form-based forgery even if Origin were missing.
    const S = load(ghFetchStub(204));
    for (const ct of ["text/plain;charset=UTF-8", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", ""]) {
      const r = await call(S, { GH_DISPATCH_TOKEN: "t" }, { market: "asx" }, { "Content-Type": ct });
      assert.equal(r.status, 415, "content-type " + ct);
    }
    const ok = await call(S, { GH_DISPATCH_TOKEN: "t" }, { market: "asx" },
      { "Content-Type": "application/json; charset=utf-8" });
    assert.equal(ok.status, 202, "a charset parameter is still JSON");
  });

  await test("a request with no provenance headers is not a browser forgery and goes on to the limits", async () => {
    // Every current browser sends Origin on a POST; a request with neither
    // header comes from curl or a script, which can forge both anyway. That is
    // Cloudflare Access's job (REFINE200 #55), not this guard's.
    const r = await load(ghFetchStub(204)).onRequestPost({
      env: { GH_DISPATCH_TOKEN: "t" },
      request: new Request(SITE + "/api/scan", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ market: "asx" }) }),
    });
    assert.equal(r.status, 202);
  });

  await test("a spent KV write quota FAILS CLOSED — 503, no dispatch (it used to switch both limits off)", async () => {
    // Measured before the fix: ten back-to-back POSTs, ten dispatched runs.
    let hits = 0;
    const S = load(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const kv = quotaSpentKV();
    for (let i = 0; i < 5; i++) {
      const r = await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
      assert.equal(r.status, 503);
      assert.match((await r.json()).message, /rate limiter is unavailable/);
    }
    assert.equal(hits, 0, "no scan may be dispatched while the limiter cannot record it");
  });

  await test("a KV READ failure also fails closed; an ABSENT binding still means no limiting", async () => {
    const S = load(ghFetchStub(204));
    const broken = { get: async () => { throw new Error("kv down"); }, put: async () => {}, delete: async () => {} };
    assert.equal((await call(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: broken })).status, 503);
    assert.equal((await call(S, { GH_DISPATCH_TOKEN: "t" })).status, 202,
      "no binding is a configuration choice, not something a caller can cause");
  });

  await test("a half-written limiter does not leave a stray cooldown behind", async () => {
    // The cooldown put lands, the daily-counter put is refused: the request is
    // refused, and the cooldown it wrote is taken back (best-effort) so it
    // does not block the owner's retry for five minutes about nothing.
    const kv = fakeKV();
    const put = kv.put.bind(kv);
    kv.put = async (k, v, o) => { if (k.startsWith("ratelimit:scan:day:")) throw new Error("quota"); return put(k, v, o); };
    const r = await call(load(ghFetchStub(204)), { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 503);
    assert.ok(!kv.store.has("ratelimit:scan:asx"));
  });

  await test("a token pasted with a BOM / newline dispatches, instead of 'Network error reaching GitHub'", async () => {
    // Headers refuses a BOM in `Bearer ${token}`; _dispatch.js read the throw
    // as a network failure, so the endpoint named the wrong cause (#164).
    let auth = null;
    const S = load(async (url, opts) => { auth = opts.headers.Authorization; return { status: 204, ok: true }; });
    const r = await call(S, { GH_DISPATCH_TOKEN: "\ufeffghp_abc\r\n" });
    assert.equal(r.status, 202);
    assert.equal(auth, "Bearer ghp_abc");
    const blank = await call(S, { GH_DISPATCH_TOKEN: " \ufeff\n" });
    assert.equal(blank.status, 503, "a whitespace-only secret is an unset one");
    assert.equal((await blank.json()).configured, false);
  });

  suite("close.js — same refund contract");

  // close.js logs every close the price band could not check; collected here
  // rather than printed, and asserted on below.
  const closeLogs = [];
  const loadC = (fetchImpl) => loadModule("close.js", {
    strip: [[/export const onRequestPost/, "globalThis.onRequestPost"]],
    sandboxExtra: { fetch: fetchImpl, console: { ...console, log: (m) => closeLogs.push(String(m)) } },
  });
  const good = (sym, price = 4.2) => ({ symbol: sym, market: "asx", direction: "long", price });
  const callBatch = (S, env, closes, jt = "bot", headers) =>
    S.onRequestPost({ env, request: browserPost("/api/close", { journal_type: jt, closes }, headers) });
  const callC = (S, env) => callBatch(S, env, [good("WES", 71.5)]);

  await test("close: failed dispatch refunds the cooldown and the closes it counted", async () => {
    const kv = fakeKV();
    const S = loadC(ghFetchStub(403));
    const r = await callC(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
    assert.equal(r.status, 502);
    assert.ok(!kv.store.has("ratelimit:close:batch"));
    const day = [...kv.store].find(([k]) => k.startsWith("ratelimit:close:day:"));
    assert.equal(day && day[1], "0");
  });

  await test("close: success keeps it; timeout keeps it", async () => {
    for (const [status, want] of [[204, 202], ["abort", 504]]) {
      const kv = fakeKV();
      const S = loadC(ghFetchStub(status));
      const r = await callC(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv });
      assert.equal(r.status, want);
      assert.ok(kv.store.has("ratelimit:close:batch"), `cooldown must persist on ${status}`);
    }
  });

  // ── the batch shape (2026-08-13): N closes, ONE dispatch, one Actions run ──
  suite("close.js — batch: N closes ride ONE dispatch");

  await test("batch: one GitHub dispatch regardless of N, entries re-serialised clean", async () => {
    const calls = [];
    const S = loadC((url, opts) => { calls.push({ url, opts }); return Promise.resolve(new Response(null, { status: 204 })); });
    // The first entry carries a hostile extra field ON PURPOSE: the mutation
    // this pin exists to catch is `entries.push({ ...c, ... })` — forwarding
    // the raw client object — and entries with only clean keys cannot see it.
    const poisoned = { ...good("AAA"), exit_date: "2026-01-01; rm -rf /", extra: { nested: true } };
    const r = await callBatch(S, { GH_DISPATCH_TOKEN: "t" }, [poisoned, good("BBB"), good("CCC")]);
    assert.equal(r.status, 202);
    assert.equal(calls.length, 1, "a batch must cost exactly one Actions dispatch");
    const sent = JSON.parse(calls[0].opts.body);
    const batch = JSON.parse(sent.inputs.batch);
    assert.equal(batch.length, 3);
    // Only the four validated fields may ride — the raw client JSON never
    // reaches the workflow input.
    for (const e of batch) {
      assert.deepEqual(Object.keys(e).sort(), ["direction", "market", "price", "symbol"]);
    }
    assert.equal(sent.inputs.journal_type, "bot");
    assert.match(sent.inputs.symbol, /^AAA\+2$/, "the display symbol should read AAA+2");
  });

  await test("batch: bot-book only, and one bad entry rejects the WHOLE batch", async () => {
    const S = loadC(ghFetchStub(204));
    assert.equal((await callBatch(S, { GH_DISPATCH_TOKEN: "t" }, [good("AAA")], "swing")).status, 400,
      "a non-bot batch must be refused");
    for (const bad of [
      [good("AAA"), { ...good("BBB"), price: 0 }],
      [good("AAA"), { ...good("BBB"), market: "scalp" }],
      [good("AAA"), { ...good("BBB"), symbol: "b;rm -rf" }],
      [good("AAA"), good("AAA")],                       // duplicate
    ]) {
      const r = await callBatch(S, { GH_DISPATCH_TOKEN: "t" }, bad);
      assert.equal(r.status, 400, "accepted: " + JSON.stringify(bad[1]));
    }
  });

  await test("batch: capped at 60 (a full book, owner 2026-09-27) and never empty", async () => {
    const S = loadC(ghFetchStub(204));
    const full = Array.from({ length: 60 }, (_, i) => good("S" + i));
    assert.equal((await callBatch(S, { GH_DISPATCH_TOKEN: "t" }, full)).status, 202,
      "a full 60-slot book must close in ONE run");
    const many = Array.from({ length: 61 }, (_, i) => good("S" + i));
    assert.equal((await callBatch(S, { GH_DISPATCH_TOKEN: "t" }, many)).status, 400);
    assert.equal((await callBatch(S, { GH_DISPATCH_TOKEN: "t" }, [])).status, 400);
  });

  await test("batch: the daily cap counts CLOSES, not requests (#53); refunded on failure", async () => {
    const kv = fakeKV();
    const S = loadC(ghFetchStub(204));
    const r = await callBatch(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv }, [good("AAA"), good("BBB"), good("CCC")]);
    assert.equal(r.status, 202);
    const dayKey = [...kv.store.keys()].find((k) => k.startsWith("ratelimit:close:day:"));
    assert.equal(kv.store.get(dayKey), "3", "a 3-close batch is three closes against the day's 60");
    assert.ok(kv.store.has("ratelimit:close:batch"), "the batch cooldown key is missing");
    // 58 already today: a 3-close batch would make 61 -- refused whole, nothing dispatched.
    let hits = 0;
    const S58 = loadC(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const kv58 = fakeKV({ [dayKey]: "58" });
    const over = await callBatch(S58, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv58 }, [good("AAA"), good("BBB"), good("CCC")]);
    assert.equal(over.status, 429);
    assert.match((await over.json()).message, /58 of 60 closes/);
    assert.equal(hits, 0);
    const two = await callBatch(S58, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv58 }, [good("AAA"), good("BBB")]);
    assert.equal(two.status, 202, "exactly reaching 60 is allowed");
    assert.equal(kv58.store.get(dayKey), "60");
    // Failed dispatch refunds both, same contract as before.
    const kv2 = fakeKV();
    const S2 = loadC(ghFetchStub(500));
    await callBatch(S2, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv2 }, [good("AAA")]);
    assert.ok(!kv2.store.has("ratelimit:close:batch"), "failed dispatch must refund the batch cooldown");
  });

  suite("close.js — one shape, same-origin JSON, a sane exit price (REFINE200 #52 / #53 / #172)");

  await test("the retired single-close shape is refused — no route to the legacy journals is left", async () => {
    // Its callers (the manual journal's close modal, swing/scalp pages) went
    // 2026-09-21; it still routed to the swing/scalp journals.
    let hits = 0;
    const S = loadC(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    for (const body of [
      { symbol: "WES", market: "asx", price: 71.5, journal_type: "bot" },
      { symbol: "WES", market: "", price: 71.5, journal_type: "swing" },
      { symbol: "BTC", market: "scalp", price: 1, journal_type: "scalp" },
    ]) {
      const r = await S.onRequestPost({ env: { GH_DISPATCH_TOKEN: "t" }, request: browserPost("/api/close", body) });
      assert.equal(r.status, 400, JSON.stringify(body));
    }
    assert.equal(hits, 0);
    const src = SRC("close.js");
    assert.ok(!/journal_type === "scalp"|"swing"/.test(src), "close.js still knows the legacy journal types");
  });

  await test("both browser callers post exactly the shape close.js accepts", async () => {
    for (const f of ["journal.js", "stalled.js"]) {
      const js = fs.readFileSync(path.join(__dirname, "..", "public", "js", f), "utf8");
      const i = js.indexOf('fetch("/api/close"');
      assert.ok(i > 0, f + " no longer posts to /api/close");
      const c = js.slice(i, i + 400);
      assert.match(c, /"Content-Type": "application\/json"/, f + " must send JSON");
      assert.match(c, /journal_type: "bot"/, f);
      assert.match(c, /closes:/, f + " must post the batch shape");
    }
  });

  await test("a cross-site or non-JSON close is refused and closes nothing", async () => {
    let hits = 0;
    const S = loadC(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const env = { GH_DISPATCH_TOKEN: "t" };
    assert.equal((await callBatch(S, env, [good("AAA")], "bot",
      { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" })).status, 403);
    assert.equal((await callBatch(S, env, [good("AAA")], "bot",
      { "Content-Type": "text/plain" })).status, 415);
    assert.equal(hits, 0);
  });

  // The published book the band reads: one open row per (market, symbol).
  const BOOK = { open: [
    { symbol: "AAA", market: "asx", direction: "long", last_mark: 4.0 },
    { symbol: "BBB", market: "asx", direction: "long", last_mark: 10 },
    { symbol: "NOMARK", market: "asx", direction: "long", last_mark: null },
  ] };
  const assets = (book) => ({
    fetch: async (req) => {
      assert.equal(new URL(req.url).pathname, "/data/vivek_bot_book.json");
      return typeof book === "number" ? new Response("x", { status: book }) : new Response(JSON.stringify(book));
    },
  });

  await test("an exit price far from the published last mark is refused (#53)", async () => {
    let hits = 0;
    const S = loadC(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const env = { GH_DISPATCH_TOKEN: "t", ASSETS: assets(BOOK) };
    for (const px of [42, 1.9, 6.01]) {          // a stray digit, -52%, +50.25%
      const r = await callBatch(S, env, [good("AAA", px)]);
      assert.equal(r.status, 400, "accepted " + px + " against a mark of 4.0");
      assert.match((await r.json()).message, /AAA: exit price/);
    }
    assert.equal(hits, 0, "an off-band batch closes nothing at all");
    for (const px of [4.0, 2.0, 6.0, 4.37]) {     // the mark itself, and the band's edges
      assert.equal((await callBatch(S, env, [good("AAA", px), good("BBB", 10)])).status, 202, String(px));
    }
  });

  await test("one off-band entry refuses the whole batch", async () => {
    const S = loadC(ghFetchStub(204));
    const r = await callBatch(S, { GH_DISPATCH_TOKEN: "t", ASSETS: assets(BOOK) },
      [good("AAA", 4.0), good("BBB", 100)]);
    assert.equal(r.status, 400);
    assert.match((await r.json()).message, /^BBB:/);
  });

  await test("what the book cannot vouch for passes: no row, no mark, or no readable book", async () => {
    // The workflow's own --close refuses a position that is not open; blocking
    // a real close because a static asset hiccuped would be the worse failure.
    const S = loadC(ghFetchStub(204));
    for (const a of [assets(BOOK), assets(404), assets({ nope: 1 }), undefined]) {
      closeLogs.length = 0;
      const r = await callBatch(S, { GH_DISPATCH_TOKEN: "t", ASSETS: a },
        [good("NEWSYM", 999), good("NOMARK", 5)]);
      assert.equal(r.status, 202);
      assert.ok(closeLogs.some((m) => /band NOT checked/.test(m)), "an unchecked close must leave a log line");
    }
  });

  await test("close: a spent KV write quota FAILS CLOSED", async () => {
    let hits = 0;
    const S = loadC(async (...a) => { hits++; return ghFetchStub(204)(...a); });
    const r = await callBatch(S, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: quotaSpentKV() }, [good("AAA")]);
    assert.equal(r.status, 503);
    assert.match((await r.json()).message, /close_position\.yml/, "the refusal names the way round it");
    assert.equal(hits, 0);
  });
};

// ═════════════ secrets: every Cloudflare secret is read clean (#164) ═════════
const secretTests = async () => {
  suite("_secrets.js — the trim is config.clean_secret's, and nothing reads a secret raw");

  const S = (() => {
    const sandbox = { String };
    vm.createContext(sandbox);
    vm.runInContext(STRIP_EXPORTS(SRC("_secrets.js")) + "\n;this.cleanSecret = cleanSecret;", sandbox);
    return sandbox;
  })();
  await test("ends are trimmed of whitespace, BOM and zero-width marks; the interior never", () => {
    assert.equal(S.cleanSecret("\ufeff ghp_a b\u200b\r\n"), "ghp_a b");
    assert.equal(S.cleanSecret("\u200e\u200f\u200c\u200dx\t"), "x");
    assert.equal(S.cleanSecret(undefined), "");
    assert.equal(S.cleanSecret(null), "");
    assert.equal(S.cleanSecret("a\ufeffb"), "a\ufeffb", "interior characters are never touched");
  });

  await test("the trim set is scanner/config.py clean_secret's, character for character", () => {
    const py = fs.readFileSync(path.join(__dirname, "..", "scanner", "config.py"), "utf8");
    const m = /def clean_secret[\s\S]*?\.strip\(\s*"([^"]*)"\)/.exec(py);
    assert.ok(m, "config.clean_secret no longer ends in .strip(\"...\")");
    const js = /export const SECRET_TRIM = "([^"]*)";/.exec(SRC("_secrets.js"));
    assert.ok(js, "_secrets.js no longer declares SECRET_TRIM as one string literal");
    assert.equal(js[1], m[1], "the Python and JS trim sets differ");
  });

  await test("no endpoint reads a Cloudflare secret raw", () => {
    const SECRET = /env\.(GH_DISPATCH_TOKEN|MORNING_PLAYS_TRIGGER_SECRET|EODHD_API_TOKEN)\b/;
    let reads = 0;
    for (const f of fs.readdirSync(path.join(__dirname, "..", "functions", "api"))) {
      if (!f.endsWith(".js")) continue;
      for (const line of SRC(f).split("\n")) {
        if (/^\s*(\*|\/\*|\/\/)/.test(line)) continue;              // comment lines
        let code = line.replace(/\/\/.*$/, "");
        if (!SECRET.test(code)) continue;
        reads++;
        // Allowed: the argument of cleanSecret(...), and a presence test on
        // the way to one (price.js: `ctx.env && ctx.env.X ? cleanSecret(...)`).
        code = code.replace(/(?:ctx\.)?env && (?:ctx\.)?env\.[A-Z_]+ \? (?=cleanSecret)/g, "")
                   .replace(/cleanSecret\((?:ctx\.)?env\.[A-Z_]+\)/g, "");
        assert.ok(!SECRET.test(code), `${f}: a secret is read without cleanSecret: ${line.trim()}`);
      }
    }
    assert.ok(reads >= 6, "the scan found too few secret reads to mean anything: " + reads);
  });
};

// (3. tick.js — the cloud stop/target watcher — went the same day, with the
//  manual positions it was the only reader of.)

// ═════════ 4. heartbeat.js — the self-heal leg, and what it must NOT do ══════
//
// Added 2026-08-04, the day GitHub's cron scheduler dropped fires across three
// workflows at once and the ASX session went 3h39m unscanned during a live
// pre-registered cycle. Every backstop in this repo is itself a cron, so all of
// them were dropped by the same outage — adding a fourth cron could not have
// helped. /api/heartbeat is the uncorrelated leg: an EXTERNAL monitor pings it
// and it dispatches a scan when one is overdue.
//
// It lives in this file rather than its own because it is a
// state-touching Pages Function and it inherits scan.js's refund contract
// verbatim — the two belong where they can be read against each other.

const hbTests = async () => {
  suite("heartbeat.js — heal when overdue, and never page on success");

  // Both exports must be stripped. `onRequestGet` is a function DECLARATION, so
  // the vm puts it on the sandbox by itself; `onRequestHead` is a `const`, which
  // lives in a lexical environment the test can never reach — hence the
  // globalThis form (same reason the scan.js / close.js loaders above use it).
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
    const kv = fakeKV({ ["ratelimit:heal:day:all:" + day]: "30" });
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

  await test("stale_min: the 90-minute default, and never below the market's floor (#159)", async () => {
    // A caller could declare an hourly-refreshed market overdue every few
    // minutes and force ~30 scans a day on a healthy pipeline. The floors are
    // the smallest values the real cron-job.org jobs use.
    const H = load(ghFetchStub(204));
    // One fresh asset that answers for the combined book and every sidecar.
    const BOTH = { updated_at: minsAgo(10), generated_at: minsAgo(10) };
    const env = () => envFor(BOTH, { GH_DISPATCH_TOKEN: "t", JOURNAL_KV: fakeKV() });
    const at = async (qs) => (await (await call(H, env(), qs)).json()).stale_min;
    assert.equal(await at(""), 90);
    assert.equal(await at("?stale_min=junk"), 90);
    assert.equal(await at("?stale_min=9999"), 90);
    assert.equal(await at("?stale_min=1"), 90, "market=all reads the combined book; its floor is the default");
    assert.equal(await at("?stale_min=45"), 90);
    assert.equal(await at("?stale_min=120"), 120);
    // The values the live jobs send pass through untouched.
    assert.equal(await at("?market=asx&stale_min=15"), 15, "the 16:40 ASX close job");
    assert.equal(await at("?market=asx&stale_min=40"), 40, "the 17:20 close probe");
    assert.equal(await at("?market=nasdaq&stale_min=15"), 15);
    assert.equal(await at("?market=crypto&stale_min=45"), 45, "the hourly crypto job");
    // Anything lower is raised to the floor, never obeyed.
    assert.equal(await at("?market=asx&stale_min=1"), 15);
    assert.equal(await at("?market=crypto&stale_min=15"), 45);
  });

  await test("a 24h prober on a healthy hourly market forces at most one heal an hour", async () => {
    // The finding, replayed: crypto's sidecar is re-stamped at :22 every hour,
    // on time, and a caller probes ?market=crypto&stale_min=15 every 5 minutes
    // for a day. Before the floor that was 34 dispatches (about two an hour,
    // spaced only by the 25-minute heal window). With the floor a heal needs
    // the data 45+ minutes old -- the hourly job's own threshold -- so the
    // prober can only get in ahead of a heal the job would make anyway.
    const H = load(ghFetchStub(204));
    const t0 = Date.UTC(2026, 9, 14, 0, 0, 0);
    let now = t0;
    const store = new Map();                      // key -> [value, expiresAt]
    const kv = {
      async get(k) { const e = store.get(k); return e && e[1] > now ? e[0] : null; },
      async put(k, v, o) { store.set(k, [String(v), now + ((o && o.expirationTtl) || 1e9) * 1000]); },
      async delete(k) { store.delete(k); },
    };
    const realNow = Date.now;
    Date.now = () => now;
    const healsByHour = new Map();
    try {
      for (let m = 0; m < 24 * 60; m += 5) {
        now = t0 + m * 6e4;
        const lastCommit = t0 + (Math.floor((m - 22) / 60) * 60 + 22) * 6e4;
        const r = await H.onRequestGet({
          env: { ASSETS: { fetch: async () => new Response(JSON.stringify({ generated_at: new Date(lastCommit).toISOString() })) },
                 GH_DISPATCH_TOKEN: "t", JOURNAL_KV: kv },
          request: new Request("https://x/api/heartbeat?market=crypto&stale_min=15"),
        });
        const b = await r.json();
        if (b.action === "dispatched") {
          assert.ok(b.age_min > 45, `healed a ${b.age_min}-minute-old market`);
          healsByHour.set(Math.floor(m / 60), (healsByHour.get(Math.floor(m / 60)) || 0) + 1);
        }
      }
    } finally { Date.now = realNow; }
    const total = [...healsByHour.values()].reduce((a, b) => a + b, 0);
    assert.ok(total <= 24, `${total} forced heals in a day`);
    assert.ok(Math.max(...healsByHour.values()) <= 1, "more than one forced heal in an hour");
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
  await scanTests();
  await secretTests();
  await hbTests();
  console.log(`\napi_guards.test.js: ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

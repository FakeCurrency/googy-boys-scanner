#!/usr/bin/env node
/* Tests for the endpoint access log (functions/api/_access_log.js) and its
 * wiring into the unauthenticated dispatch endpoints (close.js, scan.js) —
 * 2026-08-20. (journal.js was the third until it went, 2026-09-21.)
 *
 * WHY THIS FILE EXISTS: after the 2026-08-20 bad-commit incident there was
 * nothing to read to answer "what else hit these endpoints in the last 24
 * hours". The log is the diagnosis trail; these tests pin the properties
 * it must never lose:
 *   1. A call gets logged — method/path/outcome/IP/country/UA reach KV.
 *   2. Logging is BEST-EFFORT — a KV failure must never block or change the
 *      underlying close/scan response.
 *   3. (REFINE200 #158) A REFUSED call costs at most one write per caller IP
 *      per hour — the caps limit dispatches, not calls, so a per-call write let
 *      junk POSTs spend the whole KV write quota.
 *
 * Pattern follows test/api_guards.test.js: the REAL sources are read, the ESM
 * surface stripped, and the real helper prepended — no re-typed mirror.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// The suite MUST be able to fail CI (REFINE200 #165): it used to count its
// failures and exit 0, so a broken contract printed a cross on a green run.
let passed = 0, failed = 0;
function test(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => { console.log(`  ✓  ${name}`); passed++; })
    .catch((e) => { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; });
}
const suite = (name) => console.log(`\n── ${name} ──`);

const SRC = (f) => fs.readFileSync(path.join(__dirname, "..", "functions", "api", f), "utf8");

const STRIP_EXPORTS = (src) => src
  .replace(/export\s+async\s+function/g, "async function")
  .replace(/export\s+function/g, "function")
  .replace(/export\s+const/g, "const");
const HELPER = STRIP_EXPORTS(SRC("_access_log.js"));
// The shared dispatch transport and the request guards, prepended real (see
// api_guards.test.js).
const DISPATCH_HELPER = STRIP_EXPORTS(SRC("_dispatch.js"));
const GUARD_HELPERS = STRIP_EXPORTS(SRC("_secrets.js")) + "\n" + STRIP_EXPORTS(SRC("_same_origin.js"));
const LOCAL_IMPORTS = /^import\s*\{[^}]*\}\s*from\s*"\.\/_[a-z_]+\.js";\s*$/gm;

function loadModule(file, { strip = [], sandboxExtra = {} } = {}) {
  let source = SRC(file);
  source = source.replace(LOCAL_IMPORTS, "");
  source = GUARD_HELPERS + "\n" + HELPER + "\n" + DISPATCH_HELPER + "\n" + source;
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

function fakeKV(initial = {}) {
  const store = new Map(Object.entries(initial));
  const ops = [];
  return {
    store, ops,
    async get(k) { ops.push(["get", k]); return store.has(k) ? store.get(k) : null; },
    async put(k, v, opts) { ops.push(["put", k, v]); store.set(k, String(v)); void opts; },
    async delete(k) { ops.push(["delete", k]); store.delete(k); },
  };
}

const alogEntries = (kv) =>
  [...kv.store.entries()].filter(([k]) => k.startsWith("alog:"))
    .map(([k, v]) => [k, JSON.parse(v)]);
const alogWrites = (kv) => kv.ops.filter(([op, k]) => op === "put" && k.startsWith("alog:")).length;

// Standalone helper sandbox (for outcomeOf / logAccess unit cases).
const A = (() => {
  const sandbox = {
    Response, Request, URL, JSON, Math, Date, String, Number, Array, Object,
    Promise, parseInt, console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(HELPER + "\n;globalThis.__o = outcomeOf; globalThis.__l = logAccess; globalThis.__w = withAccessLog;", sandbox);
  return { outcomeOf: sandbox.__o, logAccess: sandbox.__l, withAccessLog: sandbox.__w };
})();

// The envelope Cloudflare adds, plus what the site's own pages send (a
// same-origin JSON POST; close.js and scan.js refuse anything else).
const req = (url, init, headers = {}) => new Request(url, {
  ...init,
  headers: {
    "CF-Connecting-IP": "9.8.7.6",
    "CF-IPCountry": "AU",
    "User-Agent": "test-agent/1.0",
    "Content-Type": "application/json",
    Origin: new URL(url).origin,
    ...headers,
  },
});

(async () => {
  suite("outcomeOf — the outcome taxonomy");

  await test("2xx is ok, 429 is rate-limited, everything else is error", () => {
    assert.equal(A.outcomeOf(200), "ok");
    assert.equal(A.outcomeOf(202), "ok");
    assert.equal(A.outcomeOf(429), "rate-limited");
    assert.equal(A.outcomeOf(400), "error");
    assert.equal(A.outcomeOf(503), "error");
    assert.equal(A.outcomeOf(502), "error");
  });

  suite("logAccess — what reaches KV");

  await test("an event entry carries method, path, status, outcome, IP, country, UA", async () => {
    const kv = fakeKV();
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/close", { method: "POST" }), "/api/close", 503);
    const entries = alogEntries(kv);
    assert.equal(entries.length, 1);
    const [, e] = entries[0];
    assert.equal(e.m, "POST");
    assert.equal(e.p, "/api/close");
    assert.equal(e.s, 503);
    assert.equal(e.o, "error");
    assert.equal(e.ip, "9.8.7.6");
    assert.equal(e.cc, "AU");
    assert.equal(e.ua, "test-agent/1.0");
    assert.ok(e.t, "timestamp present");
  });

  await test("no KV binding is a silent no-op, never a throw", async () => {
    await A.logAccess({}, req("https://x/api/scan", { method: "POST" }), "/api/scan", 202);
    await A.logAccess(null, req("https://x/api/scan", { method: "POST" }), "/api/scan", 202);
  });

  await test("a User-Agent longer than 120 chars is truncated, not stored whole", async () => {
    const kv = fakeKV();
    const r = req("https://x/api/close", { method: "POST" }, { "User-Agent": "x".repeat(500) });
    await A.logAccess({ JOURNAL_KV: kv }, r, "/api/close", 400);
    const [, e] = alogEntries(kv)[0];
    assert.equal(e.ua.length, 120);
  });

  await test("every DISPATCHED call gets its own entry (bounded by the endpoints' daily caps)", async () => {
    const src = SRC("_access_log.js");
    assert.ok(!/coalesceOk/.test(src), "the /api/journal-era coalescing flag is back");
    const kv = fakeKV();
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", 202);
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", 202);
    const entries = alogEntries(kv);
    assert.equal(entries.length, 2, "each dispatch call gets its own entry");
    assert.ok(entries.every(([k]) => !k.startsWith("alog:refused:")));
  });

  await test("REFUSED calls cost one write per IP per path per hour, not one per call (#158)", async () => {
    // Measured before: 100 POSTs, 1 dispatch, 99 refusals, 100 log writes --
    // ~1,000 junk calls spent the day's whole KV write quota.
    const kv = fakeKV();
    for (const status of [429, 429, 400, 403, 503, 429]) {
      await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", status);
    }
    assert.equal(alogWrites(kv), 1, "six refusals from one IP in one hour must cost ONE write");
    const [[key, e]] = alogEntries(kv);
    assert.match(key, /^alog:refused:\/api\/scan:\d{4}-\d{2}-\d{2}T\d{2}:9\.8\.7\.6$/);
    assert.equal(e.s, 429, "the marker records the hour's FIRST refusal");
    assert.equal(e.ip, "9.8.7.6");
    // A second IP, or a second path, is its own record.
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }, { "CF-Connecting-IP": "1.2.3.4" }), "/api/scan", 429);
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/close", { method: "POST" }), "/api/close", 400);
    assert.equal(alogWrites(kv), 3);
  });

  await test("a refusal stream does not block the log of a real dispatch", async () => {
    const kv = fakeKV();
    for (let i = 0; i < 20; i++) {
      await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", 429);
    }
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", 202);
    assert.equal(alogWrites(kv), 2);
    assert.equal(alogEntries(kv).filter(([, e]) => e.o === "ok").length, 1);
  });

  suite("withAccessLog — the wrapper contract");

  await test("a KV put that THROWS never changes the handler's response", async () => {
    const kv = { get: async () => { throw new Error("kv down"); },
                 put: async () => { throw new Error("kv down"); } };
    const wrapped = A.withAccessLog("/api/x", async () => new Response("ok", { status: 202 }));
    const res = await wrapped({ env: { JOURNAL_KV: kv }, request: req("https://x/api/x", { method: "POST" }) });
    assert.equal(res.status, 202);
    assert.equal(await res.text(), "ok");
  });

  await test("with ctx.waitUntil present the log rides it instead of delaying the response", async () => {
    const kv = fakeKV();
    let captured = null;
    const wrapped = A.withAccessLog("/api/x", async () => new Response("ok", { status: 200 }));
    const res = await wrapped({
      env: { JOURNAL_KV: kv },
      request: req("https://x/api/x", { method: "POST" }),
      waitUntil: (p) => { captured = p; },
    });
    assert.equal(res.status, 200);
    assert.ok(captured && typeof captured.then === "function", "waitUntil received the log promise");
    await captured;
    assert.equal(alogEntries(kv).length, 1, "the deferred write still lands");
  });

  suite("close.js — every call is logged, logging never blocks the close");

  const loadClose = (fetchImpl) => loadModule("close.js", {
    strip: [[/export const onRequestPost = withAccessLog\(/, "globalThis.onRequestPost = withAccessLog("]],
    // close.js logs a close its price band could not check (no ASSETS here);
    // api_guards.test.js asserts on that line, this suite only silences it.
    sandboxExtra: { fetch: fetchImpl, console: { ...console, log: () => {} } },
  }).onRequestPost;

  const closeCall = (env, body) => loadClose(async () => new Response(null, { status: 204 }))({
    env,
    request: req("https://x/api/close", { method: "POST", body: JSON.stringify(body) }),
  });
  const batchOf = (symbol) => ({ journal_type: "bot", closes: [{ symbol, price: 42, market: "asx" }] });

  await test("an unconfigured close (503) is logged with its status", async () => {
    const kv = fakeKV();
    const res = await closeCall({ JOURNAL_KV: kv }, batchOf("BHP"));
    assert.equal(res.status, 503);
    const [, e] = alogEntries(kv)[0];
    assert.equal(e.p, "/api/close");
    assert.equal(e.s, 503);
  });

  await test("a dispatched close (202) is logged ok — and the body is NOT in the log", async () => {
    const kv = fakeKV();
    const res = await closeCall({ JOURNAL_KV: kv, GH_DISPATCH_TOKEN: "tok" }, batchOf("SECRETSYM"));
    assert.equal(res.status, 202);
    const entries = alogEntries(kv);
    assert.equal(entries.length, 1);
    assert.equal(entries[0][1].o, "ok");
    for (const [k, v] of entries) {
      assert.ok(!k.includes("SECRETSYM") && !JSON.stringify(v).includes("SECRETSYM"),
        "request-body content must never reach the access log");
    }
  });

  await test("a close still succeeds when the KV log write throws", async () => {
    // get() works (rate-limit reads) but put() dies — the worst case for a
    // logger sharing the namespace with the cooldown bookkeeping.
    const store = new Map();
    const kv = {
      get: async (k) => (store.has(k) ? store.get(k) : null),
      put: async (k) => { if (k.startsWith("alog:")) throw new Error("kv write down"); store.set(k, "1"); },
      delete: async () => {},
    };
    const res = await closeCall({ JOURNAL_KV: kv, GH_DISPATCH_TOKEN: "tok" }, batchOf("BHP"));
    assert.equal(res.status, 202, "the close dispatch must not be blocked by a log failure");
  });

  suite("scan.js — same wiring");

  const loadScan = (fetchImpl) => loadModule("scan.js", {
    strip: [[/export const onRequestPost = withAccessLog\(/, "globalThis.onRequestPost = withAccessLog("]],
    sandboxExtra: { fetch: fetchImpl },
  }).onRequestPost;

  await test("a rate-limited scan (429) is logged as rate-limited", async () => {
    const kv = fakeKV({ "ratelimit:scan:asx": "1" });
    const res = await loadScan(async () => new Response(null, { status: 204 }))({
      env: { JOURNAL_KV: kv, GH_DISPATCH_TOKEN: "tok" },
      request: req("https://x/api/scan", { method: "POST", body: JSON.stringify({ market: "asx" }) }),
    });
    assert.equal(res.status, 429);
    const events = alogEntries(kv);
    assert.equal(events.length, 1);
    assert.equal(events[0][1].o, "rate-limited");
  });

  await test("a refused cross-site scan is logged once, and dispatches nothing", async () => {
    const kv = fakeKV();
    let hits = 0;
    const scan = loadScan(async () => { hits++; return new Response(null, { status: 204 }); });
    for (let i = 0; i < 5; i++) {
      const res = await scan({
        env: { JOURNAL_KV: kv, GH_DISPATCH_TOKEN: "tok" },
        request: req("https://x/api/scan", { method: "POST", body: JSON.stringify({ market: "asx" }) },
          { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }),
      });
      assert.equal(res.status, 403);
    }
    assert.equal(hits, 0);
    assert.equal(alogWrites(kv), 1, "five refused calls, one log write");
    assert.equal(alogEntries(kv)[0][1].s, 403);
  });

  // (The journal.js access-log suite went with the KV journal store on
  //  2026-09-21 — the manual journal it served was removed.)

  console.log(`\naccess_log.test.js: ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

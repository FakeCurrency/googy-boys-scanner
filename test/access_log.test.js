#!/usr/bin/env node
/* Tests for the endpoint access log (functions/api/_access_log.js) and its
 * wiring into the unauthenticated dispatch endpoints (close.js, scan.js) —
 * 2026-08-20. (journal.js was the third until it went, 2026-09-21.)
 *
 * WHY THIS FILE EXISTS: after the 2026-08-20 bad-commit incident there was
 * nothing to read to answer "what else hit these endpoints in the last 24
 * hours". The log is the diagnosis trail; these tests pin the two properties
 * it must never lose:
 *   1. A call gets logged — method/path/outcome/IP/country/UA reach KV.
 *   2. Logging is BEST-EFFORT — a KV failure must never block or change the
 *      underlying close/scan response.
 *
 * Pattern follows test/api_guards.test.js: the REAL sources are read, the ESM
 * surface stripped, and the real helper prepended — no re-typed mirror.
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

const STRIP_EXPORTS = (src) => src
  .replace(/export\s+async\s+function/g, "async function")
  .replace(/export\s+function/g, "function")
  .replace(/export\s+const/g, "const");
const HELPER = STRIP_EXPORTS(SRC("_access_log.js"));
// The shared dispatch transport, prepended real (see api_guards.test.js).
const DISPATCH_HELPER = STRIP_EXPORTS(SRC("_dispatch.js"));

function loadModule(file, { strip = [], sandboxExtra = {} } = {}) {
  let source = SRC(file);
  source = source.replace(/^import\s*\{[^}]*\}\s*from\s*"\.\/_access_log\.js";\s*$/m, "");
  source = source.replace(/^import\s*\{[^}]*\}\s*from\s*"\.\/_dispatch\.js";\s*$/m, "");
  source = HELPER + "\n" + DISPATCH_HELPER + "\n" + source;
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

const req = (url, init, headers = {}) => new Request(url, {
  ...init,
  headers: {
    "CF-Connecting-IP": "9.8.7.6",
    "CF-IPCountry": "AU",
    "User-Agent": "test-agent/1.0",
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

  await test("there is no coalescing branch left to opt into", async () => {
    // It existed for /api/journal's 60-second GET poll, whose write volume would
    // have eaten the KV quota the sync itself needed. That endpoint went with the
    // manual journal on 2026-09-21, and both remaining callers are daily-capped
    // dispatch endpoints — so every call is logged individually. If a polled
    // endpoint is ever added, coalescing comes back with it rather than sitting
    // here uncalled (the header carries the argument).
    const src = SRC("_access_log.js");
    assert.ok(!/coalesceOk/.test(src), "coalesceOk is back with no polled caller");
    const kv = fakeKV();
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", 200);
    await A.logAccess({ JOURNAL_KV: kv }, req("https://x/api/scan", { method: "POST" }), "/api/scan", 200);
    const entries = alogEntries(kv);
    assert.equal(entries.length, 2, "each dispatch call gets its own entry");
    assert.ok(!entries.some(([k]) => k.startsWith("alog:seen:")), "no seen markers");
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
    sandboxExtra: { fetch: fetchImpl },
  }).onRequestPost;

  const closeCall = (env, body) => loadClose(async () => new Response(null, { status: 204 }))({
    env,
    request: req("https://x/api/close", { method: "POST", body: JSON.stringify(body) }),
  });

  await test("an unconfigured close (503) is logged with its status", async () => {
    const kv = fakeKV();
    const res = await closeCall({ JOURNAL_KV: kv }, { symbol: "BHP", price: 42, market: "asx" });
    assert.equal(res.status, 503);
    const [, e] = alogEntries(kv)[0];
    assert.equal(e.p, "/api/close");
    assert.equal(e.s, 503);
  });

  await test("a dispatched close (202) is logged ok — and the body is NOT in the log", async () => {
    const kv = fakeKV();
    const res = await closeCall({ JOURNAL_KV: kv, GH_DISPATCH_TOKEN: "tok" },
      { symbol: "SECRETSYM", price: 42, market: "asx", journal_type: "bot" });
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
    const res = await closeCall({ JOURNAL_KV: kv, GH_DISPATCH_TOKEN: "tok" },
      { symbol: "BHP", price: 42, market: "asx", journal_type: "bot" });
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

  // (The journal.js access-log suite went with the KV journal store on
  //  2026-09-21 — the manual journal it served was removed.)

})();

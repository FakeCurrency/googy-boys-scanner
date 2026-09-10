#!/usr/bin/env node
/* Guard-rail tests for functions/api/morning_plays.js — the EXTERNAL trigger
 * for the Discord plays digest (2026-09-10).
 *
 * WHY THIS FILE EXISTS: GitHub's cron ran the ASX slot hours late / not at all,
 * so an external pinger now kicks the workflow at the exact Melbourne minute.
 * That makes this the one endpoint whose failure mode is "the owner's daily
 * list silently never arrives", so its gates are pinned: it must FAIL CLOSED
 * without a secret (never an open trigger), refuse a bad key, validate the
 * slot, dispatch the right workflow with the right input, never echo the
 * GitHub token, and refund its cooldown on a definite failure.
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
  return Promise.resolve().then(fn)
    .then(() => { passed++; console.log("  ok  " + name); })
    .catch((e) => { failed++; console.log("  FAIL " + name + "\n       " + (e && e.message)); });
}

// ---- load the real handler --------------------------------------------------
const SRC = path.join(__dirname, "..", "functions", "api", "morning_plays.js");
const source = fs.readFileSync(SRC, "utf8")
  .replace(/export\s+const\s+onRequest/, "globalThis.onRequest");

function load(fetchImpl) {
  const sandbox = {
    Response, Request, URL, JSON, String, Date, AbortController,
    setTimeout, clearTimeout, console,
    fetch: fetchImpl,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return sandbox.onRequest;
}

// ---- helpers ------------------------------------------------------------------
const BASE = "https://x.pages.dev/api/morning_plays";
const SECRET = "s3cret-value";
const TOKEN = "ghp_TOKEN_NEVER_ECHOED";

function req(qs = "", { method = "GET", headers = {}, body } = {}) {
  return new Request(BASE + qs, { method, headers, body });
}
function kv() {
  const store = {};
  const calls = { get: 0, put: 0, del: 0 };
  return {
    store, calls,
    async get(k) { calls.get++; return store[k] ?? null; },
    async put(k, v) { calls.put++; store[k] = v; },
    async delete(k) { calls.del++; delete store[k]; },
  };
}
function envOf(over = {}) {
  return { MORNING_PLAYS_TRIGGER_SECRET: SECRET, GH_DISPATCH_TOKEN: TOKEN, ...over };
}
// a fetch that records the call and answers with the given status
function ghFetch(status = 204) {
  const seen = [];
  const f = async (url, init) => { seen.push({ url, init }); return new Response(status === 204 ? null : "upstream-body-" + TOKEN, { status }); };
  f.seen = seen;
  return f;
}

(async () => {
  console.log("morning_plays_api.test.js");

  await test("405 on a method that is not GET/POST", async () => {
    const f = ghFetch(); const h = load(f);
    const r = await h({ request: req("?slot=asx&key=" + SECRET, { method: "PUT" }), env: envOf() });
    assert.equal(r.status, 405);
    assert.equal(f.seen.length, 0);
  });

  await test("FAILS CLOSED: no MORNING_PLAYS_TRIGGER_SECRET -> 503, nothing dispatched", async () => {
    const f = ghFetch(); const h = load(f);
    const r = await h({ request: req("?slot=asx&key=anything"), env: envOf({ MORNING_PLAYS_TRIGGER_SECRET: undefined }) });
    assert.equal(r.status, 503);
    const b = await r.json();
    assert.equal(b.configured, false);
    assert.equal(f.seen.length, 0, "an unset secret must never open the trigger");
  });

  await test("wrong or missing key -> 401, nothing dispatched", async () => {
    const f = ghFetch(); const h = load(f);
    for (const qs of ["?slot=asx&key=wrong", "?slot=asx"]) {
      const r = await h({ request: req(qs), env: envOf() });
      assert.equal(r.status, 401, qs);
    }
    assert.equal(f.seen.length, 0);
  });

  await test("the key is accepted as ?key= AND as Authorization: Bearer", async () => {
    const f = ghFetch(); const h = load(f);
    const r1 = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf() });
    const r2 = await h({ request: req("?slot=asx", { headers: { Authorization: "Bearer " + SECRET } }), env: envOf() });
    assert.equal(r1.status, 202);
    assert.equal(r2.status, 202);
    assert.equal(f.seen.length, 2);
  });

  await test("a missing or unknown slot -> 400 (good key), nothing dispatched", async () => {
    const f = ghFetch(); const h = load(f);
    for (const qs of ["?key=" + SECRET, "?slot=nasdaq&key=" + SECRET, "?slot=ASXX&key=" + SECRET]) {
      const r = await h({ request: req(qs), env: envOf() });
      assert.equal(r.status, 400, qs);
    }
    assert.equal(f.seen.length, 0);
  });

  await test("slot is case-insensitive and also readable from a POST JSON body", async () => {
    const f = ghFetch(); const h = load(f);
    const r1 = await h({ request: req("?slot=US&key=" + SECRET), env: envOf() });
    assert.equal(r1.status, 202);
    const r2 = await h({ request: req("?key=" + SECRET, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot: "asx" }) }), env: envOf() });
    assert.equal(r2.status, 202);
    assert.equal(JSON.parse(f.seen[0].init.body).inputs.slot, "us");
    assert.equal(JSON.parse(f.seen[1].init.body).inputs.slot, "asx");
  });

  await test("no GH_DISPATCH_TOKEN -> 503 (good key + slot), nothing dispatched", async () => {
    const f = ghFetch(); const h = load(f);
    const r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf({ GH_DISPATCH_TOKEN: undefined }) });
    assert.equal(r.status, 503);
    assert.equal(f.seen.length, 0);
  });

  await test("happy path dispatches morning_plays.yml on main with inputs.slot and the Bearer token", async () => {
    const f = ghFetch(204); const h = load(f);
    const r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf() });
    assert.equal(r.status, 202);
    const b = await r.json();
    assert.equal(b.ok, true); assert.equal(b.slot, "asx");
    assert.equal(f.seen.length, 1);
    const { url, init } = f.seen[0];
    assert.equal(url, "https://api.github.com/repos/FakeCurrency/googy-boys-scanner/actions/workflows/morning_plays.yml/dispatches");
    assert.equal(init.method, "POST");
    assert.equal(init.headers.Authorization, "Bearer " + TOKEN);
    assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { slot: "asx" } });
  });

  await test("a GitHub rejection -> 502 that NEVER echoes the token or upstream body", async () => {
    const f = ghFetch(401); const h = load(f);
    const r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf() });
    assert.equal(r.status, 502);
    const text = await r.text();
    assert.ok(!text.includes(TOKEN), "token must never reach the caller");
    assert.ok(!text.includes("upstream-body"), "upstream body must never be echoed");
    assert.ok(JSON.parse(text).message.includes("GH_DISPATCH_TOKEN"), "names the fix");
  });

  await test("KV cooldown: written before dispatch, second call within window -> 429, refunded on a definite failure", async () => {
    // success writes the cooldown and keeps it
    let store = kv();
    let h = load(ghFetch(204));
    let r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf({ JOURNAL_KV: store }) });
    assert.equal(r.status, 202);
    assert.equal(store.store["ratelimit:morning_plays:asx"], "1");
    // repeat inside the window is refused without dispatching
    const f2 = ghFetch(204); h = load(f2);
    r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf({ JOURNAL_KV: store }) });
    assert.equal(r.status, 429);
    assert.equal(f2.seen.length, 0);
    // a different slot is independent
    r = await h({ request: req("?slot=us&key=" + SECRET), env: envOf({ JOURNAL_KV: store }) });
    assert.equal(r.status, 202);
    // a definite GitHub failure refunds the cooldown so the retry is free
    store = kv(); h = load(ghFetch(401));
    r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf({ JOURNAL_KV: store }) });
    assert.equal(r.status, 502);
    assert.equal(store.store["ratelimit:morning_plays:asx"], undefined, "refunded");
    assert.equal(store.calls.del, 1);
  });

  await test("a missing KV binding degrades to no cooldown, never to a broken trigger", async () => {
    const f = ghFetch(204); const h = load(f);
    const r = await h({ request: req("?slot=asx&key=" + SECRET), env: envOf({ JOURNAL_KV: undefined }) });
    assert.equal(r.status, 202);
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();

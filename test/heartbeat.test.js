/* Unit tests for the self-heal endpoint (functions/api/heartbeat.js).
 *
 * WHY THIS FILE EXISTS (2026-08-20): heartbeat.js accepted a `market` param
 * and even threaded it into the GitHub dispatch payload, but the STALENESS
 * CHECK that decides whether to heal always read the COMBINED bot book
 * (BOOK's updated_at) regardless of `market`. crypto_bot.yml re-stamps that
 * combined book hourly, 24/7, so a market=asx probe could never see an
 * ASX-only gap — the exact bug class health.js was fixed for on 2026-07-28
 * (see health.test.js), just not yet ported to this sibling endpoint. The
 * fix makes a scoped probe read /data/<market>_prices.json's generated_at
 * instead; market=all (or omitted, or invalid) keeps reading the combined
 * book exactly as before. These tests pin both halves.
 *
 * Runs under plain node with no dependencies. heartbeat.js is an ES module
 * and this suite is CommonJS (the repo has no package.json "type"), so the
 * source is read and its two `export`s stripped before evaluation — the REAL
 * handler body is exercised, not a reimplementation of it.
 *
 * Unlike health.js, this handler also reaches for AbortController/setTimeout
 * and a bare global `fetch` (to dispatch a workflow) and reads a KV binding
 * (for the cooldown/daily-cap), so the sandbox and fake `env` are larger than
 * health.test.js's, and — because the fetch mock is swapped per test via a
 * single shared variable — the cases below run SEQUENTIALLY, not as a
 * Promise.all fan-out: two tests racing each other's fetch mock would be a
 * self-inflicted flake, not a real bug.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// ---- load the real handler --------------------------------------------------
const SRC = path.join(__dirname, "..", "functions", "api", "heartbeat.js");
const source = fs.readFileSync(SRC, "utf8")
  .replace(/export\s+async\s+function\s+onRequestGet/, "async function onRequestGet")
  .replace(/export\s+const\s+onRequestHead/, "globalThis.onRequestHead");

let currentFetch = async () => new Response("fetch mock not set for this test", { status: 500 });
const sandbox = {
  Response, Request, URL, Date, Number, Math, Array, JSON, String, Set,
  AbortController, setTimeout, clearTimeout, parseFloat, parseInt,
  fetch: (...args) => currentFetch(...args),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source + "\n;globalThis.__handler = onRequestGet;", sandbox);
const onRequestGet = sandbox.__handler;

// ---- fakes --------------------------------------------------------------
function fakeKV(store = {}) {
  return {
    get: async (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    put: async (k, v) => { store[k] = v; },
    delete: async (k) => { delete store[k]; },
  };
}

// assets: { "/data/x.json": <object | number(status)> }
function ctx(url, { assets = {}, token = "tok", kv } = {}) {
  return {
    request: new Request(url),
    env: {
      ASSETS: {
        fetch: async (req) => {
          const p = new URL(req.url).pathname;
          const hit = assets[p];
          if (hit === undefined) return new Response("not found", { status: 404 });
          if (typeof hit === "number") return new Response("err", { status: hit });
          return new Response(JSON.stringify(hit), { status: 200 });
        },
      },
      GH_DISPATCH_TOKEN: token,
      JOURNAL_KV: kv,
    },
  };
}

const BASE = "https://example.test/api/heartbeat";
const minsAgo = (m) => new Date(Date.now() - m * 6e4).toISOString();
const call = async (qs, opts) => {
  const res = await onRequestGet(ctx(BASE + qs, opts));
  return { status: res.status, body: await res.json() };
};

// The scenario that actually bit: crypto keeps the combined book fresh while
// ASX has not scanned in hours (stale_min=90 in every case below). market=all
// cannot see it; market=asx must.
const MIXED = {
  "/data/vivek_bot_book.json": { updated_at: minsAgo(2) },
  "/data/asx_prices.json": { generated_at: minsAgo(200) },
  "/data/crypto_prices.json": { generated_at: minsAgo(2) },
};

const cases = [
  ["market=all reads the combined book, unchanged", async () => {
    const { status, body } = await call("?market=all&stale_min=90", { assets: MIXED });
    assert.equal(status, 200);
    assert.equal(body.action, "none");
    assert.equal(body.updated_at, MIXED["/data/vivek_bot_book.json"].updated_at);
  }],

  ["no market param defaults to all, unchanged", async () => {
    const { status, body } = await call("?stale_min=90", { assets: MIXED });
    assert.equal(status, 200);
    assert.equal(body.action, "none");
  }],

  ["the combined book hides a stale ASX behind crypto's hourly commit", async () => {
    // Same data, same probe time, two different answers — that is the bug.
    const all = await call("?market=all&stale_min=90", { assets: MIXED });
    const asx = await call("?market=asx&stale_min=90", { assets: MIXED, token: "" });
    assert.equal(all.body.action, "none", "market=all looks healthy...");
    assert.equal(asx.status, 503);
    assert.equal(asx.body.action, "cannot_heal", "...while ASX is 200min stale (would heal if armed)");
  }],

  ["a fresh market reports healthy off its OWN sidecar, not the combined book", async () => {
    const { status, body } = await call("?market=crypto&stale_min=90", { assets: MIXED });
    assert.equal(status, 200);
    assert.equal(body.action, "none");
    assert.equal(body.updated_at, MIXED["/data/crypto_prices.json"].generated_at);
  }],

  ["a stale market with no dispatch token reports cannot_heal, not silently healthy", async () => {
    const { status, body } = await call("?market=asx&stale_min=90", { assets: MIXED, token: "" });
    assert.equal(status, 503);
    assert.equal(body.action, "cannot_heal");
    assert.ok(body.age_min > 90, `age_min was ${body.age_min}`);
  }],

  ["a stale market dispatches a scan scoped to THAT market", async () => {
    let seenBody = null;
    currentFetch = async (_url, opts) => {
      seenBody = JSON.parse(opts.body);
      return new Response(null, { status: 204 });
    };
    const { status, body } = await call("?market=asx&stale_min=90", { assets: MIXED });
    assert.equal(status, 200);
    assert.equal(body.action, "dispatched");
    assert.equal(body.market, "asx");
    assert.equal(seenBody.inputs.market, "asx", "the dispatch is scoped to the stale market");
  }],

  ["an invalid market silently falls back to all (unlike health.js's 400)", async () => {
    const { status, body } = await call("?market=bogus&stale_min=90", { assets: MIXED });
    assert.equal(status, 200);
    assert.equal(body.action, "none");
    assert.equal(body.updated_at, MIXED["/data/vivek_bot_book.json"].updated_at, "read the combined book, not a bogus path");
  }],

  ["a missing per-market sidecar is not silently healthy", async () => {
    const { status, body } = await call("?market=nasdaq&stale_min=90", { assets: MIXED });
    assert.equal(status, 503);
    assert.ok(/HTTP 404/.test(body.error), body.error);
  }],

  ["an unparseable generated_at is not silently healthy", async () => {
    const { status, body } = await call("?market=asx&stale_min=90", {
      assets: { "/data/asx_prices.json": { generated_at: "not a date" } },
    });
    assert.equal(status, 503);
    assert.ok(/generated_at/.test(body.error), body.error);
  }],

  ["a cooling-down market stays green without re-dispatching", async () => {
    const kv = fakeKV({ "ratelimit:scan:asx": "1" });
    const { status, body } = await call("?market=asx&stale_min=90", { assets: MIXED, kv });
    assert.equal(status, 200);
    assert.equal(body.action, "cooling_down");
  }],
];

async function main() {
  let passed = 0;
  for (const [name, fn] of cases) {
    try {
      await fn();
      passed++;
    } catch (e) {
      console.error(`FAIL: ${name}\n  ${e && e.stack}`);
      process.exitCode = 1;
    }
  }
  console.log(`heartbeat.test.js: ${passed}/${cases.length} passed`);
}
main();

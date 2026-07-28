/* Unit tests for the freshness heartbeat (functions/api/health.js).
 *
 * WHY THIS FILE EXISTS (2026-07-28): the endpoint's default answer reads the
 * COMBINED bot book, which crypto_bot.yml re-stamps hourly 24/7. scan.yml's
 * :47 ASX backstop asked that default question ("did a scan land this hour?"),
 * always got "yes" from crypto's commit, and skipped itself every single time —
 * so the ghosted :07 ASX runs it exists to rescue were never rescued. The
 * per-market mode is the fix, and these tests pin it.
 *
 * Runs under plain node with no dependencies. health.js is an ES module and
 * this suite is CommonJS (the repo has no package.json "type"), so the source
 * is read and its single `export` stripped before evaluation — the REAL handler
 * body is exercised, not a reimplementation of it.
 */
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// ---- load the real handler --------------------------------------------------
const SRC = path.join(__dirname, "..", "functions", "api", "health.js");
const source = fs.readFileSync(SRC, "utf8").replace(
  /export\s+async\s+function\s+onRequestGet/,
  "async function onRequestGet",
);
const sandbox = { Response, Request, URL, Date, Number, Math, Array, JSON, String, Set };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source + "\n;globalThis.__handler = onRequestGet;", sandbox);
const onRequestGet = sandbox.__handler;

// ---- a fake Cloudflare ASSETS binding ---------------------------------------
// assets: { "/data/x.json": <object | number(status) > }
function ctx(url, assets) {
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
    },
  };
}

const BASE = "https://example.test/api/health";
const hoursAgo = (h) => new Date(Date.now() - h * 3.6e6).toISOString();
const call = async (qs, assets) => {
  const res = await onRequestGet(ctx(BASE + qs, assets));
  return { status: res.status, body: await res.json() };
};

let passed = 0;
function test(name, fn) {
  return fn().then(
    () => { passed++; },
    (e) => { console.error(`FAIL: ${name}\n  ${e && e.message}`); process.exitCode = 1; },
  );
}

// The scenario that actually bit: crypto keeps the combined book fresh while
// ASX has not scanned for hours. The default probe cannot see the problem;
// the per-market probe must.
const MIXED = {
  "/data/vivek_bot_book.json": { updated_at: hoursAgo(0.2), open: [1, 2, 3] },
  "/data/asx_prices.json": { generated_at: hoursAgo(9), market: "asx" },
  "/data/crypto_prices.json": { generated_at: hoursAgo(0.2), market: "crypto" },
};

const tests = [
  test("default probe answers for the whole pipeline, unchanged", async () => {
    const { status, body } = await call("?max_h=1", MIXED);
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.open, 3, "book position count still reported");
    assert.ok(!("market" in body), "no market key on the pipeline answer");
  }),

  test("the combined book hides a stale ASX behind crypto's hourly commit", async () => {
    // This is the bug, pinned: same data, same hour, two different answers.
    const pipeline = await call("?max_h=1", MIXED);
    const asx = await call("?market=asx&max_h=1", MIXED);
    assert.equal(pipeline.body.ok, true, "pipeline looks healthy...");
    assert.equal(asx.body.ok, false, "...while ASX has not scanned in 9h");
  }),

  test("a stale market answers 503 so the caller runs the missed scan", async () => {
    const { status, body } = await call("?market=asx&max_h=1", MIXED);
    assert.equal(status, 503);
    assert.equal(body.market, "asx");
    assert.ok(body.age_h >= 8.9 && body.age_h <= 9.1, `age_h was ${body.age_h}`);
  }),

  test("a market that did scan this hour answers ok, so the backstop skips", async () => {
    const { status, body } = await call("?market=crypto&max_h=1", MIXED);
    assert.equal(status, 200);
    assert.equal(body.ok, true);
    assert.equal(body.market, "crypto");
  }),

  test("an unknown market is rejected, never path-interpolated", async () => {
    const { status, body } = await call("?market=../../etc/passwd", MIXED);
    assert.equal(status, 400);
    assert.equal(body.ok, false);
    assert.ok(/unknown market/.test(body.error), body.error);
  }),

  test("market names are case- and space-insensitive", async () => {
    const { body } = await call("?market=%20ASX%20&max_h=24", MIXED);
    assert.equal(body.ok, true);
    assert.equal(body.market, "asx");
  }),

  test("a missing sidecar is not silently healthy", async () => {
    const { status, body } = await call("?market=nasdaq&max_h=1", MIXED);
    assert.equal(status, 503);
    assert.ok(/HTTP 404/.test(body.error), body.error);
  }),

  test("an unparseable timestamp is not silently healthy", async () => {
    const { status, body } = await call("?market=asx&max_h=1", {
      "/data/asx_prices.json": { generated_at: "not a date" },
    });
    assert.equal(status, 503);
    assert.ok(/generated_at/.test(body.error), body.error);
  }),

  test("max_h stays clamped to 1..48 with a 4h default", async () => {
    const fresh = { "/data/asx_prices.json": { generated_at: hoursAgo(3) } };
    assert.equal((await call("?market=asx", fresh)).body.max_h, 4);
    assert.equal((await call("?market=asx&max_h=0.1", fresh)).body.max_h, 4);
    assert.equal((await call("?market=asx&max_h=999", fresh)).body.max_h, 4);
    assert.equal((await call("?market=asx&max_h=2", fresh)).body.max_h, 2);
  }),

  test("responses are never cached", async () => {
    const res = await onRequestGet(ctx(BASE + "?market=asx", MIXED));
    assert.equal(res.headers.get("Cache-Control"), "no-store");
  }),
];

Promise.all(tests).then(() => {
  console.log(`health.test.js: ${passed}/${tests.length} passed`);
});

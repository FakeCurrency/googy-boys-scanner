/* Unit tests for the freshness heartbeat (functions/api/health.js).
 *
 * WHY THIS FILE EXISTS (2026-07-28): the endpoint's default answer reads the
 * COMBINED bot book, which crypto_bot.yml re-stamps hourly 24/7. scan.yml's
 * :47 ASX backstop asked that default question ("did a scan land this hour?"),
 * always got "yes" from crypto's commit, and skipped itself every single time —
 * so the ghosted :07 ASX runs it exists to rescue were never rescued. The
 * per-market mode is the fix, and these tests pin it. (That backstop was
 * replaced by scripts/scan_gate.py on 2026-10-05; the per-market mode is now a
 * manual / diagnostic probe, and its answers are still pinned here.)
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
// BOTH exports have to come off. onRequestHead was added 2026-08-07 (a HEAD
// probe was falling through to the static assets and 404ing — see the note in
// heartbeat.js); it is a `const`, so the vm keeps it in a lexical environment
// this suite cannot reach, hence the globalThis form. api_guards.test.js owns
// the behavioural pin for it; this replace only keeps the file evaluable here.
// Since NEXT100 #12 health.js imports _token_expiry.js (the KV read of the
// dispatch token's expiry): the REAL helper is prepended, exports stripped,
// and the import line comes off, as the other Function suites do.
const TOKEN_HELPER = fs.readFileSync(path.join(__dirname, "..", "functions", "api", "_token_expiry.js"), "utf8")
  .replace(/export\s+async\s+function/g, "async function")
  .replace(/export\s+function/g, "function")
  .replace(/export\s+const/g, "const");
const HEALTH_SRC = fs.readFileSync(SRC, "utf8");
const source = TOKEN_HELPER + "\n" + HEALTH_SRC
  .replace(/^import\s*\{[^}]*\}\s*from\s*"\.\/_[a-z_]+\.js";\s*$/gm, "")
  .replace(/export\s+async\s+function\s+onRequestGet/, "async function onRequestGet")
  .replace(/export\s+const\s+onRequestHead/, "globalThis.onRequestHead");

// A FROZEN CLOCK (NEXT100 #13). The pipeline answer now judges each stock
// market in its own session hours, so "9 hours ago" means a different thing
// at 3am and at 3pm Sydney -- every case below runs at one fixed instant:
// Mon 2 Nov 2026 23:00 UTC = Tue 10:00 AEDT (before the ASX window) = Mon
// 18:00 EST (after the NASDAQ one). The sandbox shares this Date.
const FROZEN_MS = Date.parse("2026-11-02T23:00:00Z");
Date.now = () => FROZEN_MS;

const sandbox = { Response, Request, URL, Date, Number, Math, Array, JSON, String, Set };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source + "\n;globalThis.__handler = onRequestGet;" +
  "globalThis.__sessionHours = sessionHours; globalThis.__WIN = SCAN_WINDOWS;", sandbox);
const onRequestGet = sandbox.__handler;
const sessionHours = sandbox.__sessionHours;
const SCAN_WINDOWS = sandbox.__WIN;

// ---- a fake Cloudflare ASSETS binding ---------------------------------------
// assets: { "/data/x.json": <object | number(status) > }; kv: a JOURNAL_KV fake.
function ctx(url, assets, kv) {
  return {
    request: new Request(url),
    env: {
      JOURNAL_KV: kv,
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
const call = async (qs, assets, kv) => {
  const res = await onRequestGet(ctx(BASE + qs, assets, kv));
  return { status: res.status, body: await res.json() };
};
// A read-only KV fake that records every operation (health must only read).
function fakeKV(store = {}, { throws = false } = {}) {
  const ops = [];
  return {
    ops,
    get: async (k) => { ops.push(["get", k]); if (throws) throw new Error("KV down");
                        return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    put: async (k) => { ops.push(["put", k]); },
    delete: async (k) => { ops.push(["delete", k]); },
  };
}
const daysFromNow = (d) => new Date(FROZEN_MS + d * 864e5).toISOString().replace(/\.000Z$/, "Z");

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

  test("the pipeline answer names the breached loss guards (REFINE200 #68)", async () => {
    // status.js lights the lamp off this field, so a page that has no other use
    // for the ~370 KB book does not download it just to learn about a breach.
    const book = {
      updated_at: hoursAgo(0.2), open: [],
      guard: { asx: { breached: false }, nasdaq: { breached: true, breach_kind: "weekly" },
               crypto: { breached: true } },
    };
    const { body } = await call("", { "/data/vivek_bot_book.json": book });
    assert.deepEqual(body.breached, [
      { market: "nasdaq", kind: "weekly" }, { market: "crypto", kind: "loss limit" }]);
    const clean = await call("", MIXED);
    assert.deepEqual(clean.body.breached, [], "no guard block = nothing breached, not undefined");
    const asx = await call("?market=asx&max_h=24", MIXED);
    assert.ok(!("breached" in asx.body), "the per-market answer reads a sidecar with no book");
  }),

  test("the combined book hides a stale ASX behind crypto's hourly commit", async () => {
    // This is the bug, pinned: same data, same hour, two different answers.
    const pipeline = await call("?max_h=1", MIXED);
    const asx = await call("?market=asx&max_h=1", MIXED);
    assert.equal(pipeline.body.ok, true, "pipeline looks healthy...");
    assert.equal(asx.body.ok, false, "...while ASX has not scanned in 9h");
  }),

  test("a stale market answers 503 (a manual probe sees the gap; scan_gate.py owns the catch-up now)", async () => {
    const { status, body } = await call("?market=asx&max_h=1", MIXED);
    assert.equal(status, 503);
    assert.equal(body.market, "asx");
    assert.ok(body.age_h >= 8.9 && body.age_h <= 9.1, `age_h was ${body.age_h}`);
  }),

  test("a market that did scan this hour answers ok", async () => {
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

  test("max_h outside 1..48 falls back to the 4h default", async () => {
    const fresh = { "/data/asx_prices.json": { generated_at: hoursAgo(3) } };
    assert.equal((await call("?market=asx", fresh)).body.max_h, 4);
    assert.equal((await call("?market=asx&max_h=0.1", fresh)).body.max_h, 4);
    assert.equal((await call("?market=asx&max_h=999", fresh)).body.max_h, 4);
    assert.equal((await call("?market=asx&max_h=2", fresh)).body.max_h, 2);
  }),

  // ---- NEXT100 #13: each stock market on its own session clock ------------
  test("a stock market past 3 session hours is listed as stale; the status stays the book's", async () => {
    // Frozen at Tue 10:00 AEDT / Mon 18:00 EST. ASX last scanned Mon 12:00
    // AEDT -> 4.75 session hours; NASDAQ Mon 15:00 EST -> 1.75. The combined
    // book is fresh (crypto), which is exactly what used to hide the ASX.
    const assets = {
      "/data/vivek_bot_book.json": { updated_at: hoursAgo(0.2), open: [],
        guard: { nasdaq: { breached: true, breach_kind: "daily" } } },
      "/data/asx_prices.json": { generated_at: "2026-11-02T12:00:00+11:00" },
      "/data/nasdaq_prices.json": { generated_at: "2026-11-02T15:00:00-05:00" },
    };
    const { status, body } = await call("", assets);
    assert.equal(status, 200, "a stale stock market is amber on the lamp, never a 503 from the alarm");
    assert.equal(body.ok, true);
    assert.deepEqual(body.breached, [
      { market: "nasdaq", kind: "daily" },
      { market: "asx", kind: "stale", session_h: 4.75, updated_at: "2026-11-02T12:00:00+11:00" }]);
  }),

  test("the night and the weekend never count; fresh markets list nothing", async () => {
    const assets = {
      "/data/vivek_bot_book.json": { updated_at: hoursAgo(0.2), open: [] },
      // ASX: Mon 16:45 AEDT, 17h15m of wall clock ago but no session since.
      "/data/asx_prices.json": { generated_at: "2026-11-02T16:45:00+11:00" },
      // NASDAQ: Mon 13:45 EST = exactly 3.0 session hours -> not past the line.
      "/data/nasdaq_prices.json": { generated_at: "2026-11-02T13:45:00-05:00" },
    };
    assert.deepEqual((await call("", assets)).body.breached, []);
  }),

  test("an unreadable sidecar is not invented into a stale market", async () => {
    for (const side of [404, { generated_at: "garbage" }, { nope: 1 }]) {
      const { status, body } = await call("", {
        "/data/vivek_bot_book.json": { updated_at: hoursAgo(0.2), open: [] },
        "/data/asx_prices.json": side,
        "/data/nasdaq_prices.json": { generated_at: "2026-11-02T15:00:00-05:00" },
      });
      assert.equal(status, 200);
      assert.deepEqual(body.breached, [], JSON.stringify(side));
    }
  }),

  test("a stale BOOK is still the 503, whatever the sidecars say", async () => {
    const { status, body } = await call("?max_h=4", {
      "/data/vivek_bot_book.json": { updated_at: hoursAgo(5), open: [] },
      "/data/asx_prices.json": { generated_at: "2026-11-02T12:00:00+11:00" },
    });
    assert.equal(status, 503);
    assert.equal(body.breached[0].market, "asx");
  }),

  test("sessionHours matches the watchdog on every shared case (tests/fixtures/session_hours_cases.json)", async () => {
    const cases = JSON.parse(fs.readFileSync(
      path.join(__dirname, "..", "tests", "fixtures", "session_hours_cases.json"), "utf8")).cases;
    assert.ok(cases.length >= 10, "the shared fixture lost its cases");
    for (const c of cases) {
      const got = sessionHours(Date.parse(c.start), Date.parse(c.end), SCAN_WINDOWS[c.market]);
      assert.ok(Math.abs(got - c.hours) < 1e-9, `${c.name}: got ${got}, want ${c.hours} (${c.why})`);
    }
  }),

  // ---- NEXT100 #12: the dispatch token's expiry, from KV only --------------
  test("the token's expiry comes back from KV with whole days left and the warning flag", async () => {
    const kv = fakeKV({ gh_token_expiry: daysFromNow(10.5) });
    const { status, body } = await call("", MIXED, kv);
    assert.equal(status, 200);
    assert.equal(body.token_expires, daysFromNow(10.5));
    assert.equal(body.token_days_left, 10, "floored: 10.5 days left reads 10");
    assert.equal(body.token_expiring, true, "inside the 14-day line");
    assert.equal(body.token_warn_days, 14);
    assert.deepEqual(kv.ops, [["get", "gh_token_expiry"]], "health READS the key once and writes nothing");
  }),

  test("outside the line, expired, absent or broken: never a status change", async () => {
    const far = await call("", MIXED, fakeKV({ gh_token_expiry: daysFromNow(14) }));
    assert.equal(far.body.token_days_left, 14);
    assert.equal(far.body.token_expiring, false, "14 whole days left is not inside 14 days");
    const gone = await call("", MIXED, fakeKV({ gh_token_expiry: daysFromNow(-1.5) }));
    assert.equal(gone.body.token_days_left, -2);
    assert.equal(gone.body.token_expiring, true, "an expired key is the loudest case, not a quiet one");
    for (const kv of [undefined, fakeKV({}), fakeKV({}, { throws: true }), fakeKV({ gh_token_expiry: "soon" })]) {
      const { status, body } = await call("", MIXED, kv);
      assert.equal(status, 200, "the token can never move health's 200/503");
      assert.equal(body.ok, true);
      assert.equal(body.token_expires, null);
      assert.equal(body.token_days_left, null);
      assert.equal(body.token_expiring, false);
    }
    const stale = await call("?max_h=1", { "/data/vivek_bot_book.json": { updated_at: hoursAgo(3) } },
      fakeKV({ gh_token_expiry: daysFromNow(300) }));
    assert.equal(stale.status, 503, "a healthy token cannot rescue a stale book either");
  }),

  test("the per-market answer is unchanged: no token, no stale list", async () => {
    const { body } = await call("?market=asx&max_h=24", MIXED, fakeKV({ gh_token_expiry: daysFromNow(3) }));
    assert.ok(!("token_expires" in body) && !("breached" in body), JSON.stringify(body));
  }),

  test("health stays GitHub-independent: it never fetches, never writes KV", async () => {
    const code = HEALTH_SRC.split("\n").filter((l) => !/^\s*(\*|\/\*|\/\/)/.test(l)).join("\n");
    assert.ok(!/github\.com/i.test(code), "health.js names a GitHub host in code");
    assert.ok(!/(^|[^.\w])fetch\(/.test(code), "health.js calls a bare fetch (only ASSETS.fetch is allowed)");
    assert.ok(!/\.(put|delete)\(/.test(code), "health.js writes KV");
    assert.ok(!/dispatchWorkflow|_dispatch\.js/.test(code), "health.js reaches the dispatch transport");
  }),

  test("responses are never cached", async () => {
    const res = await onRequestGet(ctx(BASE + "?market=asx", MIXED));
    assert.equal(res.headers.get("Cache-Control"), "no-store");
  }),
];

Promise.all(tests).then(() => {
  console.log(`health.test.js: ${passed}/${tests.length} passed`);
});

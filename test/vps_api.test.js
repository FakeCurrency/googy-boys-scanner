#!/usr/bin/env node
/* The VPS API adapter -- deploy/api/{server,shims,dispatch}.mjs plus the D4
 * transport in functions/api/_dispatch.js (deploy/DESIGN.md section 5 / 8).
 *
 * WHY THIS FILE EXISTS (2026-09-27): on the VPS the adapter is the only thing
 * between the internet and the bot book. The security review reproduced what a
 * relay-shaped /api/dispatch would allow (a close at 0.01 on every open long),
 * so the endpoint is a TYPED API and every refusal is pinned here: the
 * 503/401/400/422/429/202 matrix, "extra over the wire -> 400", "unknown
 * workflow -> 400 and NO spool file", a close of a non-open symbol -> 422, a
 * price off the mark band -> 422 naming the mark, the batch re-serialised, the
 * spool file's exact shape and its atomic temp. Around it: Pages' routing
 * semantics reproduced for every Function, the Phase 1 route restriction, the
 * XFF trust rule (spoof from a non-loopback peer ignored, two hops -> last),
 * KV TTL expiry, ASSETS traversal refused, and the four endpoints accepting
 * DISPATCH_URL with no GitHub token at all -- end to end, through the REAL
 * server on an ephemeral port with temp state/public dirs and a fixture book.
 *
 * Pattern: the shipped modules are imported and run, not mirrored; the
 * _dispatch.js checks reuse the prepend-and-strip vm loader the other API
 * suites use so the sandbox constraints (no console/process) are exercised.
 * No network: outbound fetches from the Functions are stubbed in-process.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const vm = require("vm");
const { pathToFileURL } = require("url");

let passed = 0, failed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log("  ok  " + name); }
  catch (e) { failed++; console.log("  FAIL " + name + "\n       " + ((e && e.stack) || e)); }
}
const suite = (n) => console.log(`\n-- ${n} --`);

const REPO = path.join(__dirname, "..");
const FN = (f) => path.join(REPO, "functions", "api", f);
const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), "vps-api-"));
const TOKEN = "t0k3n-" + "x".repeat(40);
const MP_SECRET = "mp-secret-" + "y".repeat(20);
const realFetch = globalThis.fetch;

// ── fixtures ───────────────────────────────────────────────────────────────
const NOW_REAL = Date.now();
const BOOK = {
  version: 2, mode: "paper",
  open: [
    { symbol: "NIC", market: "asx", direction: "long", last_mark: 0.815, status: "open" },
    { symbol: "MSFT", market: "nasdaq", direction: "long", last_mark: 400, status: "open" },
    { symbol: "BTC", market: "crypto", direction: "long", last_mark: 60000, status: "open" },
    { symbol: "NOMARK", market: "asx", direction: "long", status: "open" },
    { symbol: "GONE", market: "asx", direction: "long", last_mark: 10, status: "closed" },
  ],
  closed: [],
  updated_at: new Date(NOW_REAL - 3 * 3600 * 1000).toISOString(),   // 3h stale -> the healer heals
};
function makeTree(name) {
  const root = path.join(SCRATCH, name);
  const pub = path.join(root, "public");
  const state = path.join(root, "state");
  fs.mkdirSync(path.join(pub, "data"), { recursive: true });
  fs.mkdirSync(state, { recursive: true });
  fs.writeFileSync(path.join(pub, "data", "vivek_bot_book.json"), JSON.stringify(BOOK));
  fs.writeFileSync(path.join(pub, "data", "asx_prices.json"), JSON.stringify({ generated_at: new Date(NOW_REAL).toISOString() }));
  fs.writeFileSync(path.join(pub, "index.html"), "<!doctype html><title>x</title>");
  fs.writeFileSync(path.join(root, "book.json"), JSON.stringify(BOOK));
  fs.writeFileSync(path.join(root, "secret.txt"), "not served");
  return { root, pub, state, book: path.join(root, "book.json") };
}
function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}
const spoolFiles = (state) => { try { return fs.readdirSync(path.join(state, "spool")).filter((n) => n.endsWith(".json")).sort(); } catch (_) { return []; } };
// vm-realm results carry the sandbox's Object prototype; compare their JSON shape (the Tier 5 cross-realm rule).
const plain = (o) => JSON.parse(JSON.stringify(o));
const readSpool = (state, name) => JSON.parse(fs.readFileSync(path.join(state, "spool", name), "utf8"));
// Same-second spool names differ only in their random hex, so "the newest" is found by set difference, never by sort order.
const newSpool = (state, before) => { const fresh = spoolFiles(state).filter((n) => !before.includes(n)); assert.equal(fresh.length, 1, `expected exactly one new spool file, got ${fresh}`); return readSpool(state, fresh[0]); };
const NOW = { t: NOW_REAL };            // the fake clock every server shares (kv TTLs, cooldowns)
const clock = () => NOW.t;
const advance = (ms) => { NOW.t += ms; };

async function post(url, body, { token = TOKEN, headers = {} } = {}) {
  const h = { "Content-Type": "application/json", ...headers };
  if (token !== null) h.Authorization = `Bearer ${token}`;
  const r = await realFetch(url, { method: "POST", headers: h, body: typeof body === "string" ? body : JSON.stringify(body) });
  let j = null;
  try { j = await r.json(); } catch (_) { /* empty */ }
  return { status: r.status, j, headers: r.headers };
}

(async () => {
  const S = await import(pathToFileURL(path.join(REPO, "deploy", "api", "server.mjs")).href);
  const D = await import(pathToFileURL(path.join(REPO, "deploy", "api", "dispatch.mjs")).href);
  const X = await import(pathToFileURL(path.join(REPO, "deploy", "api", "shims.mjs")).href);

  // Phase 2 server whose Functions dispatch to ITSELF over loopback (the box's shape).
  const T2 = makeTree("p2");
  const port2 = await freePort();
  const logs2 = [];
  const P2 = await S.createServer({
    phase: 2, trustProxy: "1", stateDir: T2.state, publicDir: T2.pub, bookPath: T2.book, clock,
    env: { DISPATCH_TOKEN: TOKEN, DISPATCH_URL: `http://127.0.0.1:${port2}/api/dispatch`, MORNING_PLAYS_TRIGGER_SECRET: MP_SECRET },
    log: (l) => logs2.push(l),
  });
  const U2 = await P2.listen(port2);
  // Phase 1 server: dispatch + vps only.
  const T1 = makeTree("p1");
  const P1 = await S.createServer({ phase: 1, stateDir: T1.state, publicDir: T1.pub, bookPath: T1.book, clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
  const U1 = await P1.listen(0);
  // No token at all.
  const T0 = makeTree("p0");
  const P0 = await S.createServer({ phase: 2, stateDir: T0.state, publicDir: T0.pub, bookPath: T0.book, clock, env: {}, log: () => {} });
  const U0 = await P0.listen(0);
  // TRUST_PROXY off.
  const TU = makeTree("pu");
  const PU = await S.createServer({ phase: 2, trustProxy: "0", stateDir: TU.state, publicDir: TU.pub, bookPath: TU.book, clock, env: { DISPATCH_TOKEN: TOKEN, DISPATCH_URL: `http://127.0.0.1:${port2}/api/dispatch` }, log: () => {} });
  const UU = await PU.listen(0);

  // ═══════════ 1. routing (Pages semantics) ═══════════
  suite("server.mjs -- routes each Function with Pages' method semantics");
  await test("phase 2 routes exactly the seven Functions, helpers excluded", () => {
    assert.deepEqual([...P2.routes.keys()].sort(),
      ["/api/close", "/api/health", "/api/heartbeat", "/api/morning_plays", "/api/price", "/api/quote", "/api/scan"]);
    assert.deepEqual(Object.keys(P2.routes.get("/api/scan")), ["POST"]);
    assert.deepEqual(Object.keys(P2.routes.get("/api/health")).sort(), ["GET", "HEAD"]);
    assert.deepEqual(Object.keys(P2.routes.get("/api/morning_plays")), ["*"]);
  });
  await test("GET /api/health reads the fixture book through the ASSETS shim and keeps its headers", async () => {
    const r = await realFetch(U2 + "/api/health");
    assert.equal(r.status, 200);
    assert.equal(r.headers.get("cache-control"), "no-store");
    const j = await r.json();
    assert.equal(j.ok, true); assert.equal(j.open, 5);
    const m = await (await realFetch(U2 + "/api/health?market=asx")).json();
    assert.equal(m.market, "asx"); assert.equal(m.ok, true);
  });
  await test("HEAD /api/health answers with the status and no body", async () => {
    const r = await realFetch(U2 + "/api/health", { method: "HEAD" });
    assert.equal(r.status, 200);
    assert.equal(await r.text(), "");
  });
  await test("a method with no handler 404s (not 405), unknown paths 404, helpers are not routable", async () => {
    assert.equal((await realFetch(U2 + "/api/scan")).status, 404);
    assert.equal((await realFetch(U2 + "/api/close")).status, 404);
    assert.equal((await realFetch(U2 + "/api/nope", { method: "POST" })).status, 404);
    assert.equal((await realFetch(U2 + "/api/_dispatch")).status, 404);
    assert.equal((await realFetch(U2 + "/api/_prices")).status, 404);
    assert.equal((await realFetch(U2 + "/")).status, 404);
  });
  await test("onRequest catches every method (morning_plays answers its own 405 from inside)", async () => {
    const r = await realFetch(U2 + "/api/morning_plays", { method: "PUT" });
    assert.equal(r.status, 405);
    assert.equal((await r.json()).message, "Use GET or POST.");
  });
  await test("a Function runs before any network: /api/quote refuses a bad symbol with 400", async () => {
    const r = await realFetch(U2 + "/api/quote?sym=%25%25");
    assert.equal(r.status, 400);
  });
  await test("the request log carries method + path + status and never the query string", async () => {
    logs2.length = 0;
    await realFetch(U2 + "/api/morning_plays?slot=asx&key=SHOULD-NOT-BE-LOGGED");
    assert.equal(logs2.length, 1);
    assert.equal(logs2[0], "GET /api/morning_plays 401");
    assert.ok(!logs2.some((l) => l.includes("SHOULD-NOT")));
  });

  suite("server.mjs -- VIVEK_PHASE=1 exposes only /api/dispatch and /api/vps");
  await test("phase 1: every Function is 404, dispatch and vps answer", async () => {
    assert.equal(P1.routes.size, 0);
    for (const p of ["/api/health", "/api/heartbeat", "/api/price?symbol=BHP.AX", "/api/quote?sym=BHP.AX"]) {
      assert.equal((await realFetch(U1 + p)).status, 404, p);
    }
    assert.equal((await realFetch(U1 + "/api/scan", { method: "POST", body: "{}" })).status, 404);
    assert.equal((await realFetch(U1 + "/api/vps")).status, 200);
    const d = await post(U1 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } });
    assert.equal(d.status, 202); assert.equal(d.j.ok, true);
    assert.equal(spoolFiles(T1.state).length, 1);
  });

  // ═══════════ 2. XFF rules ═══════════
  suite("server.mjs -- X-Forwarded-For is honoured only from a trusted loopback peer, last hop only");
  await test("clientIp(): the pure rule", () => {
    const ip = S.clientIp;
    assert.equal(ip({ peer: "203.0.113.9", xff: "1.2.3.4", trustProxy: true }), "203.0.113.9", "spoof from a non-loopback peer is ignored");
    assert.equal(ip({ peer: "127.0.0.1", xff: "1.2.3.4, 5.6.7.8", trustProxy: true }), "5.6.7.8", "two hops -> the LAST (proxy-appended) hop");
    assert.equal(ip({ peer: "::ffff:127.0.0.1", xff: "1.2.3.4", trustProxy: true }), "1.2.3.4", "v4-mapped loopback counts as loopback");
    assert.equal(ip({ peer: "::1", xff: "2001:db8::7", trustProxy: true }), "2001:db8::7");
    assert.equal(ip({ peer: "127.0.0.1", xff: "1.2.3.4", trustProxy: false }), "127.0.0.1", "TRUST_PROXY=0 -> socket address");
    assert.equal(ip({ peer: "127.0.0.1", xff: "not-an-ip", trustProxy: true }), "127.0.0.1", "garbage XFF -> socket address");
    assert.equal(ip({ peer: "127.0.0.1", xff: "", trustProxy: true }), "127.0.0.1");
    assert.equal(ip({ peer: "::ffff:10.0.0.4", xff: "1.2.3.4", trustProxy: true }), "10.0.0.4");
  });
  await test("over the socket: the Functions see the last XFF hop, and a client CF-Connecting-IP is dropped", async () => {
    const r = await post(U2 + "/api/scan", { market: "crypto" },
      { token: null, headers: { "X-Forwarded-For": "1.1.1.1, 2.2.2.2", "CF-Connecting-IP": "9.9.9.9", "User-Agent": "vps-test/1" } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    await P2.waits.drain();
    const logged = (await P2.kv.list({ prefix: "alog:/api/scan:" })).keys;
    assert.ok(logged.length >= 1);
    const last = JSON.parse(await P2.kv.get(logged[logged.length - 1].name));
    assert.equal(last.ip, "2.2.2.2");
    assert.equal(last.ua, "vps-test/1");
  });
  await test("over the socket with TRUST_PROXY=0: the socket address wins over any XFF", async () => {
    const r = await post(UU + "/api/scan", { market: "asx" }, { token: null, headers: { "X-Forwarded-For": "1.1.1.1" } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    await PU.waits.drain();
    const logged = (await PU.kv.list({ prefix: "alog:/api/scan:" })).keys;
    const last = JSON.parse(await PU.kv.get(logged[logged.length - 1].name));
    assert.equal(last.ip, "127.0.0.1");
  });

  // ═══════════ 3. KV shim ═══════════
  suite("shims.mjs -- file-backed KV with TTLs");
  await test("expirationTtl expires on the shim's clock, survives a reload, and delete works", async () => {
    const file = path.join(SCRATCH, "kv-unit", "kv.json");
    let t = 1_000_000;
    const kv = X.makeKV({ file, clock: () => t });
    await kv.put("ratelimit:scan:asx", "1", { expirationTtl: 300 });
    await kv.put("forever", "v");
    assert.equal(await kv.get("ratelimit:scan:asx"), "1");
    t += 299_000;
    assert.equal(await kv.get("ratelimit:scan:asx"), "1");
    t += 2_000;
    assert.equal(await kv.get("ratelimit:scan:asx"), null, "expired at the TTL");
    assert.equal(await kv.get("forever"), "v");
    const again = X.makeKV({ file, clock: () => t });
    assert.equal(await again.get("forever"), "v", "persisted to disk");
    assert.equal(await again.get("ratelimit:scan:asx"), null);
    await again.put("day", "3", { expirationTtl: 172800 });
    const third = X.makeKV({ file, clock: () => t + 172_801_000 });
    assert.equal(await third.get("day"), null, "the expiry stamp itself persists");
    await again.delete("forever");
    assert.equal(await X.makeKV({ file, clock: () => t }).get("forever"), null);
    assert.equal(await kv.get("missing", "json"), null);
    await kv.put("j", JSON.stringify({ a: 1 }));
    assert.deepEqual(await kv.get("j", "json"), { a: 1 });
    assert.ok(!fs.readdirSync(path.dirname(file)).some((n) => n.endsWith(".tmp")), "no temp file left behind");
  });

  // ═══════════ 4. ASSETS shim ═══════════
  suite("shims.mjs -- ASSETS serves the public dir and refuses traversal");
  await test("traversal refused (403), symlink out of the root refused, missing 404, real files served with a type", async () => {
    const A = X.makeAssets({ publicDir: T2.pub });
    assert.equal((await A.fetch("http://x/data/vivek_bot_book.json")).status, 200);
    assert.equal((await A.fetch(new Request("http://x/data/vivek_bot_book.json"))).headers.get("content-type"), "application/json; charset=utf-8");
    assert.equal((await A.fetch("http://x/data/../../secret.txt")).status, 404, "URL parsing already collapses .. -> a miss, never the secret");
    // The WHATWG parser treats a %2e%2e segment as "..", so that form is collapsed to /secret.txt (a miss) before the shim sees it;
    // %2f is NOT decoded by the parser, so /%2e%2e%2fsecret.txt reaches the shim as a real ".." segment and is refused outright.
    const enc = await A.fetch("http://x/data/%2e%2e/%2e%2e/secret.txt");
    assert.equal(enc.status, 404); assert.notEqual(await enc.text(), "not served");
    assert.equal((await A.fetch("http://x/%2e%2e%2fsecret.txt")).status, 403, "an encoded .. segment is refused before any fs call");
    assert.equal((await A.fetch("http://x/data/..%2fsecret.txt")).status, 403);
    fs.symlinkSync(path.join(T2.root, "secret.txt"), path.join(T2.pub, "leak.txt"));
    assert.equal((await A.fetch("http://x/leak.txt")).status, 403, "a symlink escaping the public dir is refused");
    assert.equal((await A.fetch("http://x/data/nope.json")).status, 404);
    assert.equal((await A.fetch("http://x/")).status, 200, "a directory serves its index.html");
    assert.equal((await A.fetch("http://x/data/vivek_bot_book.json?x=1")).status, 200, "the query is ignored");
  });

  // ═══════════ 5. caches.default shim ═══════════
  suite("shims.mjs -- caches.default is an s-maxage LRU that hands out fresh bodies");
  await test("unit: stores 200s with s-maxage, expires on the clock, never stores no-store, evicts LRU by bytes", async () => {
    const saved = globalThis.caches;
    let t = 5_000_000;
    const c = X.installCaches({ clock: () => t, maxBytes: 64 });
    const mk = (body, cc = "public, max-age=15, s-maxage=20") => new Response(body, { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": cc } });
    await c.put("http://x/a", mk('{"a":1}'));
    const h1 = await c.match("http://x/a"); const h2 = await c.match("http://x/a");
    assert.equal(await h1.text(), '{"a":1}'); assert.equal(await h2.text(), '{"a":1}', "each match is a fresh readable Response");
    assert.equal(h2.headers.get("content-type"), "application/json");
    t += 20_001;
    assert.equal(await c.match("http://x/a"), undefined, "expired at s-maxage");
    await c.put("http://x/ns", mk("x", "no-store"));
    assert.equal(await c.match("http://x/ns"), undefined);
    await c.put("http://x/err", new Response("boom", { status: 502, headers: { "Cache-Control": "public, s-maxage=20" } }));
    assert.equal(await c.match("http://x/err"), undefined, "non-200 never cached");
    await c.put("http://x/b", mk("b".repeat(30)));
    await c.put("http://x/c", mk("c".repeat(30)));
    await c.match("http://x/b");                       // touch b -> c is now least recent
    await c.put("http://x/d", mk("d".repeat(30)));      // 90 > 64 -> evict c
    assert.equal(await c.match("http://x/c"), undefined);
    assert.ok(await c.match("http://x/b"));
    globalThis.caches = saved;
  });
  await test("end to end: two /api/quote calls inside the TTL reach the stubbed upstream once", async () => {
    const upstream = [];
    globalThis.fetch = (input, init) => {
      const u = String((input && input.url) || input);
      if (u.startsWith("http://127.0.0.1")) return realFetch(input, init);
      upstream.push(u);
      return Promise.resolve(new Response(JSON.stringify({ chart: { result: [{ meta: { regularMarketPrice: 42.5, currency: "AUD", regularMarketTime: 1700000000 } }] } }),
        { status: 200, headers: { "Content-Type": "application/json" } }));
    };
    try {
      const a = await realFetch(U2 + "/api/quote?sym=BHP.AX");
      assert.equal(a.status, 200);
      assert.equal(a.headers.get("cache-control"), "public, max-age=15, s-maxage=20");
      assert.equal((await a.json()).price, 42.5);
      await P2.waits.drain();
      const b = await realFetch(U2 + "/api/quote?sym=BHP.AX");
      assert.equal(b.status, 200);
      assert.equal((await b.json()).price, 42.5);
      assert.equal(upstream.length, 1, "second call served from caches.default");
      assert.ok(upstream[0].includes("finance.yahoo.com"));
    } finally { globalThis.fetch = realFetch; }
  });

  // ═══════════ 6. /api/dispatch matrix ═══════════
  suite("dispatch.mjs -- auth");
  await test("no DISPATCH_TOKEN -> 503 and nothing spooled (never open)", async () => {
    const r = await post(U0 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } });
    assert.equal(r.status, 503); assert.equal(r.j.configured, false);
    assert.equal(spoolFiles(T0.state).length, 0);
  });
  await test("missing / wrong / query-string / wrong-length bearer -> 401, GET -> 404", async () => {
    const body = { workflow: "scan.yml", inputs: { market: "asx" } };
    const n0 = spoolFiles(T2.state).length;
    assert.equal((await post(U2 + "/api/dispatch", body, { token: null })).status, 401);
    assert.equal((await post(U2 + "/api/dispatch", body, { token: TOKEN.slice(0, -1) + "Y" })).status, 401);
    assert.equal((await post(U2 + "/api/dispatch", body, { token: "short" })).status, 401);
    assert.equal((await post(U2 + `/api/dispatch?key=${TOKEN}`, body, { token: null })).status, 401, "Authorization header only");
    assert.equal((await post(U2 + "/api/dispatch", body, { token: null, headers: { Authorization: "Basic abc" } })).status, 401);
    assert.equal((await realFetch(U2 + "/api/dispatch")).status, 404);
    assert.equal(spoolFiles(T2.state).length, n0, "no 401 ever spools");
  });
  await test("a placeholder or short DISPATCH_TOKEN keeps the endpoint CLOSED (503), even with a matching bearer", async () => {
    for (const weak of ["CHANGE_ME", "short-token", "x".repeat(D.DISPATCH_TOKEN_MIN_CHARS - 1)]) {
      const TW = makeTree("weak-" + weak.length);
      const PW = await S.createServer({ phase: 1, stateDir: TW.state, publicDir: TW.pub, bookPath: TW.book, clock, env: { DISPATCH_TOKEN: weak }, log: () => {} });
      const UW = await PW.listen(0);
      const r = await post(UW + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } }, { token: weak });
      assert.equal(r.status, 503, weak); assert.equal(r.j.configured, false);
      assert.equal(spoolFiles(TW.state).length, 0, weak);
      await PW.close();
    }
    assert.equal(D.tokenProblem("x".repeat(D.DISPATCH_TOKEN_MIN_CHARS)), null);
    assert.equal(D.DISPATCH_TOKEN_MIN_CHARS, 32);
  });
  await test("an unauthenticated body is never read: 401 from the headers alone, even for 1 MiB", async () => {
    const huge = JSON.stringify({ workflow: "scan.yml", inputs: { market: "asx" }, pad: "z".repeat(1024 * 1024) });
    const r = await post(U2 + "/api/dispatch", huge, { token: "wrong" });
    assert.equal(r.status, 401);
    const noTok = await post(U0 + "/api/dispatch", huge);
    assert.equal(noTok.status, 503);
    assert.equal(S.MAX_BODY_BYTES, 64 * 1024, "the general body cap is 64 KiB, not 1 MiB");
    const srv = fs.readFileSync(path.join(REPO, "deploy", "api", "server.mjs"), "utf8");
    assert.ok(srv.indexOf("preAuthDispatch(req.headers.authorization") < srv.indexOf("await readBody(req, cap)"),
      "auth is checked before the body is read");
  });
  await test("the token is trimmed like every pasted credential (BOM + newline tolerated)", () => {
    assert.equal(D.bearerMatches(`Bearer ${TOKEN}`, X.cleanSecret(`﻿${TOKEN}\n`)), true);
    assert.equal(D.bearerMatches(`Bearer ${TOKEN}x`, TOKEN), false);
    assert.equal(D.bearerMatches("", ""), false);
  });

  suite("dispatch.mjs -- typed validation (400, nothing written)");
  const before = () => spoolFiles(T2.state).length;
  const refused = async (body, status, needle) => {
    const n = before();
    const r = await post(U2 + "/api/dispatch", body);
    assert.equal(r.status, status, `${JSON.stringify(body)} -> ${r.status} ${JSON.stringify(r.j)}`);
    assert.equal(r.j.ok, false);
    if (needle) assert.ok(String(r.j.message).includes(needle), `message ${JSON.stringify(r.j.message)} lacks ${needle}`);
    assert.equal(before(), n, "nothing spooled on a refusal");
    return r;
  };
  await test("invalid JSON, non-object, and a body over 16 KiB", async () => {
    await refused("{not json", 400, "Invalid JSON");
    await refused([1, 2], 400);
    const big = { workflow: "scan.yml", inputs: { market: "asx" }, pad: "z".repeat(17000) };
    const r = await post(U2 + "/api/dispatch", big);
    assert.equal(r.status, 413);
  });
  await test("unknown workflow -> 400 and NO spool file (momentum.yml is internal-only, phasemap.yml operator-only)", async () => {
    await refused({ workflow: "phasemap.yml", inputs: {} }, 400, "unknown workflow");
    await refused({ workflow: "momentum.yml", inputs: {} }, 400, "unknown workflow");
    await refused({ workflow: "../scan.yml", inputs: { market: "asx" } }, 400, "unknown workflow");
    await refused({ workflow: 7, inputs: {} }, 400);
    await refused({ inputs: { market: "asx" } }, 400);
  });
  await test("extra over the wire -> 400: unknown input keys and unknown top-level keys", async () => {
    await refused({ workflow: "scan.yml", inputs: { market: "asx", extra: "--out /tmp" } }, 400, "unknown input");
    await refused({ workflow: "scan.yml", inputs: { market: "asx", args: "-x" } }, 400, "unknown input");
    await refused({ workflow: "morning_plays.yml", inputs: { slot: "asx", force: "true" } }, 400, "unknown input");
    await refused({ workflow: "close_position.yml", inputs: { symbol: "NIC", market: "asx", price: "0.8", journal_type: "bot", attempt: "2" } }, 400, "unknown input");
    await refused({ workflow: "scan.yml", inputs: { market: "asx" }, ref: "main" }, 400, "unknown input");
  });
  await test("scan.yml: market and reason sets are the Functions' own", async () => {
    await refused({ workflow: "scan.yml", inputs: { market: "nyse" } }, 400, "market");
    await refused({ workflow: "scan.yml", inputs: {} }, 400, "market");
    await refused({ workflow: "scan.yml", inputs: { market: "asx", reason: "cron" } }, 400, "reason");
    await refused({ workflow: "scan.yml", inputs: { market: ["asx"] } }, 400);
    await refused({ workflow: "scan.yml", inputs: "asx" }, 400);
  });
  await test("morning_plays.yml: slot in asx|us", async () => {
    await refused({ workflow: "morning_plays.yml", inputs: { slot: "eu" } }, 400, "slot");
    await refused({ workflow: "morning_plays.yml", inputs: {} }, 400, "slot");
  });
  await test("close_position.yml: symbol regex, market set, direction, price, exit_date, journal_type", async () => {
    const base = { symbol: "NIC", market: "asx", price: "0.8", journal_type: "bot" };
    await refused({ workflow: "close_position.yml", inputs: { ...base, symbol: "bad sym" } }, 400, "symbol");
    await refused({ workflow: "close_position.yml", inputs: { ...base, symbol: "A".repeat(16) } }, 400, "symbol");
    await refused({ workflow: "close_position.yml", inputs: { ...base, market: "scalp" } }, 400, "market");
    await refused({ workflow: "close_position.yml", inputs: { ...base, market: "" } }, 400, "market");
    await refused({ workflow: "close_position.yml", inputs: { ...base, direction: "sideways" } }, 400, "direction");
    await refused({ workflow: "close_position.yml", inputs: { ...base, price: "0" } }, 400, "price");
    await refused({ workflow: "close_position.yml", inputs: { ...base, price: "abc" } }, 400, "price");
    await refused({ workflow: "close_position.yml", inputs: { ...base, price: "-1" } }, 400, "price");
    await refused({ workflow: "close_position.yml", inputs: { ...base, exit_date: "26/09/2026" } }, 400, "exit_date");
    await refused({ workflow: "close_position.yml", inputs: { symbol: "NIC", market: "asx", price: "0.8" } }, 400, "journal_type");
    await refused({ workflow: "close_position.yml", inputs: { ...base, journal_type: "paper" } }, 400, "journal_type");
    await refused({ workflow: "close_position.yml", inputs: { ...base, journal_type: "swing", batch: "[]" } }, 400, "bot-book only");
    await refused({ workflow: "close_position.yml", inputs: { ...base, batch: "not json" } }, 400, "batch");
    await refused({ workflow: "close_position.yml", inputs: { ...base, batch: "[]" } }, 400, "1-30");
    const many = JSON.stringify(Array.from({ length: 31 }, (_, i) => ({ symbol: `S${i}`, market: "asx", price: "1" })));
    await refused({ workflow: "close_position.yml", inputs: { ...base, batch: many } }, 400, "1-30");
    const dup = JSON.stringify([{ symbol: "NIC", market: "asx", price: "0.8" }, { symbol: "nic", market: "asx", price: "0.81" }]);
    await refused({ workflow: "close_position.yml", inputs: { ...base, batch: dup } }, 400, "twice");
    const badEntry = JSON.stringify([{ symbol: "NIC", market: "asx", price: "0.8" }, { symbol: "MSFT", market: "nyse", price: "400" }]);
    await refused({ workflow: "close_position.yml", inputs: { ...base, batch: badEntry } }, 400, "asx|nasdaq|crypto");
  });

  suite("dispatch.mjs -- close sanity against the book (422 names the mark)");
  await test("a close of a symbol that is not OPEN -> 422", async () => {
    const r = await refused({ workflow: "close_position.yml", inputs: { symbol: "XYZ", market: "asx", price: "1", journal_type: "bot" } }, 422, "XYZ (asx) is not an open position");
    assert.ok(!("id" in r.j));
    await refused({ workflow: "close_position.yml", inputs: { symbol: "GONE", market: "asx", price: "10", journal_type: "bot" } }, 422, "not an open position");
    await refused({ workflow: "close_position.yml", inputs: { symbol: "NIC", market: "nasdaq", price: "0.8", journal_type: "bot" } }, 422, "NIC (nasdaq)", "same symbol, wrong market");
  });
  await test("a price off the mark band -> 422 naming the row's last_mark and the band", async () => {
    const r = await refused({ workflow: "close_position.yml", inputs: { symbol: "NIC", market: "asx", price: "5", journal_type: "bot" } }, 422, "last mark 0.815");
    assert.ok(r.j.message.includes("+-35%"), r.j.message);
    await refused({ workflow: "close_position.yml", inputs: { symbol: "NIC", market: "asx", price: "0.5", journal_type: "bot" } }, 422, "0.815");   // -38.7%
    await refused({ workflow: "close_position.yml", inputs: { symbol: "MSFT", market: "nasdaq", price: "541", journal_type: "bot" } }, 422, "last mark 400");
    await refused({ workflow: "close_position.yml", inputs: { symbol: "BTC", market: "crypto", price: "18000", journal_type: "bot" } }, 422, "+-60%");   // -70%
    await refused({ workflow: "close_position.yml", inputs: { symbol: "NOMARK", market: "asx", price: "1", journal_type: "bot" } }, 422, "no last_mark");
    const b = JSON.stringify([{ symbol: "NIC", market: "asx", price: "0.8" }, { symbol: "MSFT", market: "nasdaq", price: "100" }]);
    await refused({ workflow: "close_position.yml", inputs: { symbol: "NIC+1", market: "asx", price: "0.8", journal_type: "bot", batch: b } }, 422, "MSFT price 100");
  });
  await test("inside the band -> 202 (asx edge 35%, crypto edge 60%), and a legacy swing close skips the book by design", async () => {
    let r = await post(U2 + "/api/dispatch", { workflow: "close_position.yml", inputs: { symbol: "nic", market: "ASX", price: 1.1, journal_type: "bot", exit_date: "2026-09-26" } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    const f = readSpool(T2.state, `${r.j.id}.json`);
    assert.deepEqual(f.inputs, { symbol: "NIC", direction: "long", market: "asx", price: "1.1", exit_date: "2026-09-26", journal_type: "bot" });
    assert.equal(f.source, "api/close");
    r = await post(U2 + "/api/dispatch", { workflow: "close_position.yml", inputs: { symbol: "BTC", market: "crypto", price: "30000", journal_type: "bot" } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    r = await post(U2 + "/api/dispatch", { workflow: "close_position.yml", inputs: { symbol: "NOTINBOOK", market: "asx", price: "3", journal_type: "swing" } });
    assert.equal(r.status, 202, "swing/scalp closes touch the legacy journals, not the book -- no mark to check");
  });
  await test("an unreadable book refuses every bot close with 503 (fail closed)", async () => {
    const TB = makeTree("nobook");
    const PB = await S.createServer({ phase: 1, stateDir: TB.state, publicDir: TB.pub, bookPath: path.join(TB.root, "missing.json"), clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
    const UB = await PB.listen(0);
    const r = await post(UB + "/api/dispatch", { workflow: "close_position.yml", inputs: { symbol: "NIC", market: "asx", price: "0.8", journal_type: "bot" } });
    assert.equal(r.status, 503); assert.ok(r.j.message.includes("unreadable"));
    assert.equal(spoolFiles(TB.state).length, 0);
    await PB.close();
  });

  suite("dispatch.mjs -- the batch is re-serialised from validated fields only");
  await test("batch entries come out with exactly {direction, market, price, symbol}, upper/lower-cased, price as a string", async () => {
    advance(6 * 60 * 1000);   // clear the batch cooldown from the 422 tests (none succeeded, but be explicit)
    const closes = [
      { symbol: " nic ", market: "ASX", direction: "long", price: 0.9, note: "ride-along", stop: 0.1 },
      { symbol: "msft", market: "nasdaq", price: "410", direction: "bogus" },
      { symbol: "btc", market: "Crypto", direction: "short", price: 59000 },
    ];
    const r = await post(U2 + "/api/dispatch", { workflow: "close_position.yml",
      inputs: { symbol: "junk-ignored", market: "asx", price: "1", journal_type: "bot", exit_date: "", direction: "long", batch: JSON.stringify(closes) } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    const f = readSpool(T2.state, `${r.j.id}.json`);
    assert.equal(f.workflow, "close_position.yml");
    assert.deepEqual(Object.keys(f.inputs).sort(), ["batch", "direction", "exit_date", "journal_type", "market", "price", "symbol"]);
    assert.equal(f.inputs.symbol, "NIC+2"); assert.equal(f.inputs.market, "asx"); assert.equal(f.inputs.price, "0.9");
    assert.equal(f.inputs.direction, "long"); assert.equal(f.inputs.exit_date, ""); assert.equal(f.inputs.journal_type, "bot");
    const entries = JSON.parse(f.inputs.batch);
    assert.equal(entries.length, 3);
    for (const e of entries) assert.deepEqual(Object.keys(e).sort(), ["direction", "market", "price", "symbol"]);
    assert.deepEqual(entries, [
      { symbol: "NIC", market: "asx", direction: "long", price: "0.9" },
      { symbol: "MSFT", market: "nasdaq", direction: "long", price: "410" },
      { symbol: "BTC", market: "crypto", direction: "short", price: "59000" },
    ]);
    assert.ok(!f.inputs.batch.includes("ride-along"));
  });
  await test("the same body as `closes` (the design's wording) is accepted and lands identically", async () => {
    advance(6 * 60 * 1000);
    const r = await post(U2 + "/api/dispatch", { workflow: "close_position.yml", inputs: { journal_type: "bot", closes: [{ symbol: "NIC", market: "asx", price: 0.85 }] } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    const f = readSpool(T2.state, `${r.j.id}.json`);
    assert.equal(f.inputs.symbol, "NIC"); assert.deepEqual(JSON.parse(f.inputs.batch), [{ symbol: "NIC", market: "asx", direction: "long", price: "0.85" }]);
  });

  suite("dispatch.mjs -- the spool file");
  await test("shape: exactly {id, received_at, workflow, inputs, source}; name = id; no .tmp leftover", async () => {
    advance(6 * 60 * 1000);
    process.umask(0o022);                                    // systemd's default for a service
    const n0 = spoolFiles(T2.state).length;
    const r = await post(U2 + "/api/dispatch", { workflow: "morning_plays.yml", inputs: { slot: "US" } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    assert.match(r.j.id, /^\d{8}T\d{6}Z-[0-9a-f]{8}$/);
    const files = spoolFiles(T2.state);
    assert.equal(files.length, n0 + 1);
    const name = files.find((f) => f === `${r.j.id}.json`);
    assert.ok(name, "file named after the id");
    assert.match(name, D.SPOOL_NAME_RE);
    const raw = fs.readFileSync(path.join(T2.state, "spool", name), "utf8");
    assert.ok(raw.endsWith("\n"));
    const f = JSON.parse(raw);
    assert.deepEqual(Object.keys(f), ["id", "received_at", "workflow", "inputs", "source"]);
    assert.equal(f.id, r.j.id);
    assert.match(f.received_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    assert.equal(f.received_at.replace(/[-:]/g, ""), f.id.slice(0, 16));
    assert.deepEqual(f, { id: f.id, received_at: f.received_at, workflow: "morning_plays.yml", inputs: { slot: "us" }, source: "api/morning_plays" });
    assert.deepEqual(fs.readdirSync(path.join(T2.state, "spool", ".tmp")), [], "temp+rename leaves nothing behind");
    assert.equal(fs.statSync(path.join(T2.state, "spool", name)).mode & 0o777, 0o660,
      "0660 whatever the umask: the RUNNER reads it through group vivek5-spool (security review BLOCKER)");
    for (const d of ["done", "failed"]) assert.ok(!fs.existsSync(path.join(T2.state, "spool", d)) || fs.readdirSync(path.join(T2.state, "spool", d)).length === 0);
  });
  await test("scan.yml defaults reason=manual and stamps source api/scan; reason=heartbeat stamps api/heartbeat; values are trimmed/lower-cased", async () => {
    advance(6 * 60 * 1000);
    let r = await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: " NASDAQ " } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    let f = readSpool(T2.state, `${r.j.id}.json`);
    assert.deepEqual(f.inputs, { market: "nasdaq", reason: "manual" }); assert.equal(f.source, "api/scan");
    r = await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "all", reason: "heartbeat" } });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    f = readSpool(T2.state, `${r.j.id}.json`);
    assert.deepEqual(f.inputs, { market: "all", reason: "heartbeat" }); assert.equal(f.source, "api/heartbeat");
  });

  suite("dispatch.mjs -- cooldown, daily caps, spool depth (429)");
  await test("the cooldown is per workflow and mirrors each Function's own TTL (scan.js 300 s, close.js 60 s, morning_plays.js 300 s)", () => {
    assert.deepEqual(D.DISPATCH_COOLDOWN_S, { "scan.yml": 300, "close_position.yml": 60, "morning_plays.yml": 300 });
    for (const [fn, wf] of [["scan.js", "scan.yml"], ["close.js", "close_position.yml"], ["morning_plays.js", "morning_plays.yml"]]) {
      const m = fs.readFileSync(FN(fn), "utf8").match(/put\(cdKey, "1", \{ expirationTtl: (\d+) \}\)/);
      assert.ok(m, fn); assert.equal(Number(m[1]), D.DISPATCH_COOLDOWN_S[wf], fn);
    }
    assert.equal(D.cooldownWords(300), "5 minutes"); assert.equal(D.cooldownWords(60), "60 seconds");
  });
  await test("a second scan of the same market inside 5 minutes -> 429; another scope -> 202; after the window -> 202", async () => {
    advance(6 * 60 * 1000);
    assert.equal((await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } })).status, 202);
    const r = await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } });
    assert.equal(r.status, 429); assert.ok(r.j.message.includes("scan.yml for asx") && r.j.message.includes("5 minutes"), r.j.message);
    assert.equal((await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "crypto" } })).status, 202);
    advance(D.DISPATCH_COOLDOWN_S["scan.yml"] * 1000 - 1000);
    assert.equal((await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } })).status, 429);
    advance(2000);
    assert.equal((await post(U2 + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } })).status, 202);
  });
  await test("close cooldown is per symbol (and one bucket for batches): a second close-all inside 60 s is refused, one inside 5 min is not", async () => {
    advance(6 * 60 * 1000);
    const one = { workflow: "close_position.yml", inputs: { symbol: "NIC", market: "asx", price: "0.8", journal_type: "bot" } };
    assert.equal((await post(U2 + "/api/dispatch", one)).status, 202);
    assert.equal((await post(U2 + "/api/dispatch", one)).status, 429);
    assert.equal((await post(U2 + "/api/dispatch", { workflow: "close_position.yml", inputs: { symbol: "MSFT", market: "nasdaq", price: "401", journal_type: "bot" } })).status, 202);
    const all = { workflow: "close_position.yml", inputs: { journal_type: "bot", closes: [{ symbol: "NIC", market: "asx", price: 0.8 }, { symbol: "BTC", market: "crypto", price: 60500 }] } };
    advance(61 * 1000);
    assert.equal((await post(U2 + "/api/dispatch", all)).status, 202, "close-all");
    const again = await post(U2 + "/api/dispatch", all);
    assert.equal(again.status, 429, "a second close-all inside 60 s");
    assert.ok(again.j.message.includes("60 seconds"), again.j.message);
    advance(59 * 1000);
    assert.equal((await post(U2 + "/api/dispatch", all)).status, 429, "still inside 60 s");
    advance(2 * 1000);
    assert.equal((await post(U2 + "/api/dispatch", all)).status, 202, "61 s later -- well inside 5 min -- a close-all is accepted again");
  });
  await test("daily cap per workflow (seeded kv.json) -> 429 while other workflows still dispatch", async () => {
    const TC = makeTree("cap");
    const day = new Date(NOW.t).toISOString().slice(0, 10);
    fs.writeFileSync(path.join(TC.state, "kv.json"), JSON.stringify({
      [`vps:dispatch:day:morning_plays.yml:${day}`]: { v: String(D.DISPATCH_DAILY_CAPS["morning_plays.yml"]), exp: null },
      [`vps:dispatch:day:scan.yml:${day}`]: { v: String(D.DISPATCH_DAILY_CAPS["scan.yml"] - 1), exp: null },
    }));
    const PC = await S.createServer({ phase: 1, stateDir: TC.state, publicDir: TC.pub, bookPath: TC.book, clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
    const UC = await PC.listen(0);
    const r = await post(UC + "/api/dispatch", { workflow: "morning_plays.yml", inputs: { slot: "asx" } });
    assert.equal(r.status, 429); assert.ok(r.j.message.includes("Daily"), r.j.message);
    assert.equal((await post(UC + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } })).status, 202, "39 used of 40");
    assert.equal((await post(UC + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "nasdaq" } })).status, 429, "40 used of 40");
    assert.equal(spoolFiles(TC.state).length, 1);
    await PC.close();
  });
  await test("more pending spool files than the cap -> 429; at the cap -> 202", async () => {
    const TD = makeTree("depth");
    const spool = path.join(TD.state, "spool");
    fs.mkdirSync(spool, { recursive: true });
    for (let i = 0; i < D.SPOOL_MAX_PENDING; i++) {
      fs.writeFileSync(path.join(spool, `20260101T0000${String(i).padStart(2, "0")}Z-${String(i).padStart(8, "0")}.json`), "{}");
    }
    fs.writeFileSync(path.join(spool, "not-a-dispatch.json"), "{}");           // not counted
    fs.mkdirSync(path.join(spool, "done")); fs.writeFileSync(path.join(spool, "done", "20260101T000000Z-aaaaaaaa.json"), "{}");  // not counted
    const PD = await S.createServer({ phase: 1, stateDir: TD.state, publicDir: TD.pub, bookPath: TD.book, clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
    const UD = await PD.listen(0);
    assert.equal(D.pendingCount(TD.state), D.SPOOL_MAX_PENDING);
    assert.equal((await post(UD + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "asx" } })).status, 202, "20 pending -> the 21st is accepted");
    assert.equal(D.pendingCount(TD.state), D.SPOOL_MAX_PENDING + 1);
    const r = await post(UD + "/api/dispatch", { workflow: "scan.yml", inputs: { market: "nasdaq" } });
    assert.equal(r.status, 429); assert.ok(r.j.message.includes("waiting"), r.j.message);
    await PD.close();
  });

  // ═══════════ 7. /api/vps ═══════════
  suite("dispatch.mjs -- GET /api/vps");
  await test("no ledger -> ok; a failed CRITICAL job -> 503 naming it; HALT -> 503; rows are projected", async () => {
    const TV = makeTree("vps");
    const PV = await S.createServer({ phase: 1, stateDir: TV.state, publicDir: TV.pub, bookPath: TV.book, clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
    const UV = await PV.listen(0);
    let r = await realFetch(UV + "/api/vps"); let j = await r.json();
    assert.equal(r.status, 200); assert.deepEqual([j.ok, j.halted, j.failed, j.jobs], [true, false, [], {}]);
    const ledger = {
      "scan.yml": { last_status: "failed", last_end: "2026-09-27T00:00:00Z", last_failure_at: "2026-09-27T00:00:00Z", consecutive_failures: 2, last_line: "git: fatal https://***@github.com", last_args: { market: "asx" }, host: "vps" },
      "reco_note.yml": { last_status: "failed", last_end: "2026-09-27T00:00:00Z" },
      "crypto_bot.yml": { last_status: "ok", last_success_at: "2026-09-27T00:22:00Z", pushed: "abc123" },
    };
    fs.writeFileSync(path.join(TV.state, "runs.json"), JSON.stringify(ledger));
    r = await realFetch(UV + "/api/vps"); j = await r.json();
    assert.equal(r.status, 503);
    assert.deepEqual(j.failed, ["scan.yml"], "reco_note is not CRITICAL");
    assert.equal(j.halted, false);
    assert.equal(j.jobs["scan.yml"].consecutive_failures, 2);
    assert.ok(!("last_line" in j.jobs["scan.yml"]) && !("last_args" in j.jobs["scan.yml"]), "no free text on an open route");
    assert.equal(j.jobs["crypto_bot.yml"].pushed, "abc123");
    ledger["scan.yml"].last_status = "ok";
    fs.writeFileSync(path.join(TV.state, "runs.json"), JSON.stringify(ledger));
    assert.equal((await realFetch(UV + "/api/vps")).status, 200);
    fs.writeFileSync(path.join(TV.state, "HALT"), "{}");
    r = await realFetch(UV + "/api/vps"); j = await r.json();
    assert.equal(r.status, 503); assert.equal(j.halted, true); assert.deepEqual(j.failed, []);
    assert.equal((await realFetch(UV + "/api/vps", { method: "HEAD" })).status, 503);
    assert.equal((await realFetch(UV + "/api/vps", { method: "POST" })).status, 404);
    assert.deepEqual(D.CRITICAL_JOBS, ["kill_switch.yml", "backup_book.yml", "scan.yml", "crypto_bot.yml"]);
    await PV.close();
  });
  await test("a CRITICAL job whose last run HALTED counts like a failure -> 503 (M1); a halted non-critical job does not", async () => {
    const TV = makeTree("vps-halted");
    const PV = await S.createServer({ phase: 1, stateDir: TV.state, publicDir: TV.pub, bookPath: TV.book, clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
    const UV = await PV.listen(0);
    const ledger = { "crypto_bot.yml": { last_status: "halted", last_halt_at: "2026-09-27T00:22:00Z" }, "reco_note.yml": { last_status: "halted" } };
    fs.writeFileSync(path.join(TV.state, "runs.json"), JSON.stringify(ledger));
    let r = await realFetch(UV + "/api/vps"); let j = await r.json();
    assert.equal(r.status, 503); assert.deepEqual(j.failed, ["crypto_bot.yml"]); assert.equal(j.ok, false);
    ledger["crypto_bot.yml"].last_status = "ok";
    fs.writeFileSync(path.join(TV.state, "runs.json"), JSON.stringify(ledger));
    r = await realFetch(UV + "/api/vps");
    assert.equal(r.status, 200, "reco_note halted is not CRITICAL");
    await PV.close();
  });
  await test("a ledger that EXISTS but cannot be read or parsed is 503 'ledger unreadable', never 'no jobs' (S1)", async () => {
    const TV = makeTree("vps-unreadable");
    const PV = await S.createServer({ phase: 1, stateDir: TV.state, publicDir: TV.pub, bookPath: TV.book, clock, env: { DISPATCH_TOKEN: TOKEN }, log: () => {} });
    const UV = await PV.listen(0);
    fs.writeFileSync(path.join(TV.state, "runs.json"), "{truncated");
    let r = await realFetch(UV + "/api/vps"); let j = await r.json();
    assert.equal(r.status, 503); assert.equal(j.error, "ledger unreadable"); assert.equal(j.ok, false);
    fs.rmSync(path.join(TV.state, "runs.json"));
    fs.mkdirSync(path.join(TV.state, "runs.json"));          // EISDIR stands in for EACCES (tests run as root)
    r = await realFetch(UV + "/api/vps"); j = await r.json();
    assert.equal(r.status, 503); assert.equal(j.reason, "EISDIR");
    fs.rmdirSync(path.join(TV.state, "runs.json"));
    assert.equal((await realFetch(UV + "/api/vps")).status, 200, "ENOENT alone means nothing has run yet");
    await PV.close();
  });

  // ═══════════ 8. _dispatch.js (vm-loaded, house pattern) ═══════════
  suite("_dispatch.js -- the D4 transport, loaded the way heartbeat.test.js loads it");
  const HELPER = fs.readFileSync(FN("_dispatch.js"), "utf8")
    .replace(/export\s+async\s+function/g, "async function")
    .replace(/export\s+const/g, "const");
  function loadDispatch(fetchImpl) {
    // heartbeat.test.js's sandbox exactly: no console, no process, no crypto.
    const sandbox = { Response, Request, URL, Date, Number, Math, Array, JSON, String, Set,
      AbortController, setTimeout, clearTimeout, parseFloat, parseInt, fetch: fetchImpl };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(HELPER + "\nglobalThis.dispatchWorkflow = dispatchWorkflow;", sandbox);
    return sandbox.dispatchWorkflow;
  }
  const recorder = (status) => { const seen = []; const f = async (url, init) => { seen.push({ url, init }); return { status, ok: status < 300, json: async () => ({}) }; }; f.seen = seen; return f; };
  await test("the stripped helper leaves no export/import token (the three loaders' constraint)", () => {
    assert.ok(!/^\s*export\b/m.test(HELPER), "an export keyword the loaders do not strip");
    assert.ok(!/^\s*import\b/m.test(HELPER), "the loaders strip no import from this file");
    assert.ok(!/\bconsole\.|\bprocess\./.test(HELPER));
  });
  await test("GitHub path unchanged when dispatchUrl is absent: URL, headers, body, 204 -> ok", async () => {
    const f = recorder(204);
    const r = await loadDispatch(f)({ token: "T", repo: "FakeCurrency/googy-boys-scanner", workflow: "morning_plays.yml", ref: "main", inputs: { slot: "asx" } });
    assert.deepEqual(plain(r), { ok: true });
    assert.equal(f.seen[0].url, "https://api.github.com/repos/FakeCurrency/googy-boys-scanner/actions/workflows/morning_plays.yml/dispatches");
    assert.equal(f.seen[0].init.method, "POST");
    assert.deepEqual(plain(f.seen[0].init.headers), { Authorization: "Bearer T", Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "googy-boys-scanner", "Content-Type": "application/json" });
    assert.deepEqual(plain(JSON.parse(f.seen[0].init.body)), { ref: "main", inputs: { slot: "asx" } });
    assert.ok(f.seen[0].init.signal, "still aborts on the timer");
  });
  await test("with dispatchUrl set: POST {workflow, inputs} there with Bearer dispatchToken; 202 -> ok; the GitHub token never travels", async () => {
    const f = recorder(202);
    let refunds = 0;
    const r = await loadDispatch(f)({ token: "GH", repo: "r", workflow: "scan.yml", ref: "main", inputs: { market: "asx" },
      dispatchUrl: "https://vps.example/api/dispatch", dispatchToken: "VPS", refund: async () => { refunds++; } });
    assert.deepEqual(plain(r), { ok: true }); assert.equal(refunds, 0);
    assert.equal(f.seen.length, 1);
    assert.equal(f.seen[0].url, "https://vps.example/api/dispatch");
    assert.equal(f.seen[0].init.headers.Authorization, "Bearer VPS");
    assert.deepEqual(plain(JSON.parse(f.seen[0].init.body)), { workflow: "scan.yml", inputs: { market: "asx" } });
    assert.ok(!JSON.stringify(f.seen[0]).includes("GH"), "no GitHub token on the VPS wire");
    assert.ok(!("ref" in JSON.parse(f.seen[0].init.body)));
    assert.equal(f.seen[0].init.redirect, "manual", "the bearer never rides a redirect");
    let refunds2 = 0;
    const bounced = await loadDispatch(recorder(302))({ workflow: "scan.yml", inputs: {}, dispatchUrl: "https://vps.example/api/dispatch",
      dispatchToken: "VPS", refund: async () => { refunds2++; } });
    assert.deepEqual(plain(bounced), { ok: false, status: 302 }); assert.equal(refunds2, 1, "a 3xx is a definite failure");
  });
  await test("204 from the adapter is NOT success (it answers 202); other statuses refund; the refund rule is unchanged", async () => {
    let refunds = 0; const refund = async () => { refunds++; };
    const args = { token: "GH", repo: "r", workflow: "scan.yml", ref: "main", inputs: { market: "asx" }, dispatchUrl: "http://127.0.0.1:1/api/dispatch", dispatchToken: "VPS", refund };
    assert.deepEqual(plain(await loadDispatch(recorder(204))(args)), { ok: false, status: 204 }); assert.equal(refunds, 1);
    assert.deepEqual(plain(await loadDispatch(recorder(429))(args)), { ok: false, status: 429 }); assert.equal(refunds, 2);
    assert.deepEqual(plain(await loadDispatch(recorder(422))(args)), { ok: false, status: 422 }); assert.equal(refunds, 3);
    const abort = async () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); };
    assert.deepEqual(plain(await loadDispatch(abort)(args)), { ok: false, aborted: true }); assert.equal(refunds, 3, "timeout keeps the cooldown");
    const net_ = async () => { throw new TypeError("fetch failed"); };
    assert.deepEqual(plain(await loadDispatch(net_)(args)), { ok: false, aborted: false }); assert.equal(refunds, 4);
  });
  await test("http to a non-loopback host is refused up front: {ok:false,status:0}, refund, NO fetch", async () => {
    for (const bad of ["http://vps.example/api/dispatch", "http://10.0.0.5:8787/api/dispatch", "ftp://127.0.0.1/x", "not a url", "http://127.0.0.1.evil.com/"]) {
      const f = recorder(202); let refunds = 0;
      const r = await loadDispatch(f)({ token: "GH", repo: "r", workflow: "scan.yml", ref: "main", inputs: {}, dispatchUrl: bad, dispatchToken: "V", refund: async () => { refunds++; } });
      assert.deepEqual(plain(r), { ok: false, status: 0 }, bad); assert.equal(refunds, 1, bad); assert.equal(f.seen.length, 0, bad);
    }
    for (const good of ["http://127.0.0.1:8787/api/dispatch", "http://localhost:8787/api/dispatch", "http://[::1]:8787/api/dispatch", "http://127.0.0.2/api/dispatch", "https://vps.example/api/dispatch"]) {
      const f = recorder(202);
      assert.deepEqual(plain(await loadDispatch(f)({ workflow: "scan.yml", inputs: {}, dispatchUrl: good, dispatchToken: "V" })), { ok: true }, good);
      assert.equal(f.seen.length, 1, good);
    }
  });

  // ═══════════ 9. end to end through the four Functions ═══════════
  suite("the four endpoints accept DISPATCH_URL with no GH_DISPATCH_TOKEN and spool end to end");
  await test("POST /api/scan -> 202 configured:true, spool scan.yml {market, reason:manual} source api/scan", async () => {
    advance(6 * 60 * 1000);
    const b0 = spoolFiles(T2.state);
    const r = await post(U2 + "/api/scan", { market: "nasdaq" }, { token: null });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    assert.equal(r.j.configured, true); assert.equal(r.j.market, "nasdaq");
    const f = newSpool(T2.state, b0);
    assert.deepEqual(f.inputs, { market: "nasdaq", reason: "manual" }); assert.equal(f.source, "api/scan");
    const again = await post(U2 + "/api/scan", { market: "nasdaq" }, { token: null });
    assert.equal(again.status, 429, "scan.js's own 5-minute cooldown still guards the button");
  });
  await test("POST /api/close batch (the journal/stalled shape) -> 202 and a close_position.yml spool with the batch", async () => {
    advance(6 * 60 * 1000);
    const b0 = spoolFiles(T2.state);
    const r = await post(U2 + "/api/close", { journal_type: "bot", closes: [{ symbol: "NIC", market: "asx", direction: "long", price: 0.8 }, { symbol: "BTC", market: "crypto", direction: undefined, price: 61000 }] }, { token: null });
    assert.equal(r.status, 202, JSON.stringify(r.j));
    assert.ok(r.j.message.includes("2 closes queued"));
    const f = newSpool(T2.state, b0);
    assert.equal(f.workflow, "close_position.yml"); assert.equal(f.inputs.symbol, "NIC+1"); assert.equal(f.inputs.journal_type, "bot");
    assert.deepEqual(JSON.parse(f.inputs.batch), [{ symbol: "NIC", market: "asx", direction: "long", price: "0.8" }, { symbol: "BTC", market: "crypto", direction: "long", price: "61000" }]);
  });
  await test("POST /api/close of a non-open symbol surfaces the adapter's refusal as a non-ok answer and refunds close.js's cooldown", async () => {
    advance(6 * 60 * 1000);
    const n0 = spoolFiles(T2.state).length;
    const r = await post(U2 + "/api/close", { symbol: "XYZ", market: "asx", price: 1, journal_type: "bot" }, { token: null });
    assert.equal(r.status, 502); assert.equal(r.j.ok, false);
    assert.equal(spoolFiles(T2.state).length, n0);
    assert.equal(await P2.kv.get("ratelimit:close:XYZ"), null, "the cooldown was refunded (definite failure)");
  });
  await test("GET /api/heartbeat on a 3h-stale book -> 200 action:dispatched and a scan.yml spool with reason heartbeat", async () => {
    advance(6 * 60 * 1000);
    const b0 = spoolFiles(T2.state);
    const r = await realFetch(U2 + "/api/heartbeat");
    const j = await r.json();
    assert.equal(r.status, 200, JSON.stringify(j));
    assert.equal(j.action, "dispatched"); assert.equal(j.market, "all");
    const f = newSpool(T2.state, b0);
    assert.deepEqual(f.inputs, { market: "all", reason: "heartbeat" }); assert.equal(f.source, "api/heartbeat");
    const again = await (await realFetch(U2 + "/api/heartbeat")).json();
    assert.equal(again.action, "heal_in_flight", "heartbeat.js's own heal window still applies");
  });
  await test("GET /api/morning_plays?slot=asx with the trigger secret -> 202 and a morning_plays.yml spool", async () => {
    advance(6 * 60 * 1000);
    const b0 = spoolFiles(T2.state);
    const r = await realFetch(U2 + "/api/morning_plays?slot=asx", { headers: { Authorization: `Bearer ${MP_SECRET}` } });
    const j = await r.json();
    assert.equal(r.status, 202, JSON.stringify(j)); assert.equal(j.slot, "asx");
    const f = newSpool(T2.state, b0);
    assert.deepEqual(f, { id: f.id, received_at: f.received_at, workflow: "morning_plays.yml", inputs: { slot: "asx" }, source: "api/morning_plays" });
  });
  await test("with DISPATCH_URL pointing at plain http off-box the Functions answer non-ok, refund, and spool nothing", async () => {
    const TX = makeTree("badurl");
    const PX = await S.createServer({ phase: 2, stateDir: TX.state, publicDir: TX.pub, bookPath: TX.book, clock, env: { DISPATCH_TOKEN: TOKEN, DISPATCH_URL: "http://vps.example/api/dispatch" }, log: () => {} });
    const UX = await PX.listen(0);
    const r = await post(UX + "/api/scan", { market: "asx" }, { token: null });
    assert.equal(r.status, 502); assert.equal(r.j.configured, true);
    assert.equal(await PX.kv.get("ratelimit:scan:asx"), null, "cooldown refunded");
    assert.equal(spoolFiles(TX.state).length, 0);
    await PX.close();
  });
  await test("with neither DISPATCH_URL nor GH_DISPATCH_TOKEN the four endpoints still say 'not configured' (503) exactly as before", async () => {
    const r = await post(U0 + "/api/scan", { market: "asx" }, { token: null });
    assert.equal(r.status, 503); assert.equal(r.j.configured, false); assert.ok(r.j.message.includes("GH_DISPATCH_TOKEN"));
    const c = await post(U0 + "/api/close", { symbol: "NIC", market: "asx", price: 1, journal_type: "bot" }, { token: null });
    assert.equal(c.status, 503); assert.ok(c.j.message.includes("GH_DISPATCH_TOKEN not configured"));
    const h = await (await realFetch(U0 + "/api/heartbeat")).json();
    assert.equal(h.action, "cannot_heal"); assert.equal(h.configured, false);
  });

  // ═══════════ 10. source pins ═══════════
  suite("source pins -- the shapes the loaders and the box rely on");
  await test("functions/package.json is exactly {\"type\":\"module\"} and .gitignore un-ignores it right after the package.json rule", () => {
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(REPO, "functions", "package.json"), "utf8")), { type: "module" });
    assert.ok(!fs.existsSync(path.join(REPO, "package.json")), "a ROOT package.json would flip every test/*.test.js to ESM");
    const gi = fs.readFileSync(path.join(REPO, ".gitignore"), "utf8").split("\n");
    const i = gi.indexOf("package.json");
    assert.ok(i >= 0);
    assert.equal(gi[i + 1], "!functions/package.json", "the negation sits on the very next line");
  });
  await test("the four endpoints key 'configured' on DISPATCH_URL || GH_DISPATCH_TOKEN and thread both D4 args", () => {
    for (const f of ["scan.js", "close.js", "heartbeat.js", "morning_plays.js"]) {
      const src = fs.readFileSync(FN(f), "utf8");
      assert.ok(src.includes("!dispatchUrl && !token"), f);
      assert.ok(src.includes("env.DISPATCH_URL"), f);
      assert.ok(/dispatchUrl,\s*dispatchToken/.test(src), f);
    }
  });
  await test("server binds loopback only, logs pathname not req.url, and dispatch reads the bearer from the header only", () => {
    const srv = fs.readFileSync(path.join(REPO, "deploy", "api", "server.mjs"), "utf8");
    assert.ok(srv.includes('server.listen(port, "127.0.0.1"'));
    assert.ok(srv.includes("log(`${method} ${pathname} ${status}`)"));
    assert.ok(!/log\([^)]*rawUrl/.test(srv) && !/log\([^)]*req\.url/.test(srv));
    const dsp = fs.readFileSync(path.join(REPO, "deploy", "api", "dispatch.mjs"), "utf8");
    assert.ok(!dsp.includes('searchParams.get("key")'));
    assert.ok(dsp.includes("timingSafeEqual"));
  });

  for (const p of [P2, P1, P0, PU]) await p.close();
  try { fs.rmSync(SCRATCH, { recursive: true, force: true }); } catch (_) { /* best-effort cleanup */ }
  console.log(`\nvps_api.test.js: ${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

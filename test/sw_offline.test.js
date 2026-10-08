#!/usr/bin/env node
/* Service-worker offline fallback behind Cloudflare Pages' redirects (audit #73,
 * 2026-10-08).
 *
 * Pages 308s /x.html -> /x and /index.html -> /. The install step's
 * fetch("offline.html") follows that redirect, so the response it cached had
 * redirected=true -- and the Fetch spec makes a redirected response a NETWORK
 * ERROR when it answers a navigation. The branded offline page (UX-20 #19)
 * therefore never rendered on the live site; serve.py does not redirect, so
 * nothing local could see it.
 *
 * This suite runs the SHIPPED public/sw.js against a fake worker scope whose
 * fetch() behaves like Pages (redirected responses for the .html spellings) and
 * whose Cache keeps the redirected flag the way Chromium's does. The browser's
 * own rule is modelled by servable(): a navigation answered with a redirected
 * response fails.
 *
 * Run with: node test/sw_offline.test.js
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const SW_SRC = fs.readFileSync(path.join(__dirname, "..", "public", "sw.js"), "utf8");
const ORIGIN = "https://vivek5.pages.dev";

let passed = 0, failed = 0;
const QUEUE = [];
const test = (name, fn) => QUEUE.push({ name, fn });

// A Response that followed a redirect, as fetch() hands it back on Pages. Its
// clone() is redirected too, as a real one is (the URL list is cloned with it).
function redirected(body, finalPath) {
  const make = () => {
    const r = new Response(body, { status: 200, headers: { "Content-Type": "text/html" } });
    Object.defineProperty(r, "redirected", { value: true });
    Object.defineProperty(r, "url", { value: ORIGIN + finalPath });
    Object.defineProperty(r, "clone", { value: make });
    return r;
  };
  return make();
}
const page = (body) => new Response(body, { status: 200, headers: { "Content-Type": "text/html" } });

// Cache Storage that, like Chromium's, keeps a stored response's redirect flag.
function fakeCaches() {
  const stores = new Map();
  const key = (k) => (typeof k === "string" ? new URL(k, ORIGIN + "/").href : k.url);
  const out = (rec) => rec.res.clone();     // a redirected entry stays redirected
  const api = {
    stores,
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const m = stores.get(name);
      return {
        async put(k, res) { m.set(key(k), { res: res.clone() }); },
        async match(k) { const rec = m.get(key(k)); return rec ? out(rec) : undefined; },
      };
    },
    async match(k) {
      for (const m of stores.values()) { const rec = m.get(key(k)); if (rec) return out(rec); }
      return undefined;
    },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
  };
  return api;
}

// Boot the shipped worker. `network(url)` answers (or throws, offline).
function boot(network, caches = fakeCaches()) {
  const handlers = {};
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (t, fn) => { handlers[t] = fn; },
    skipWaiting: () => {},
    clients: { claim: async () => {} },
  };
  const fetch = async (req) => network(typeof req === "string" ? new URL(req, ORIGIN + "/").href : req.url);
  const CACHE = new Function("self", "caches", "fetch", SW_SRC + "\nreturn CACHE;")(self, caches, fetch);
  const lifecycle = async (type) => {
    const waits = [];
    handlers[type]({ waitUntil: (p) => waits.push(p) });
    await Promise.all(waits);
  };
  const navigate = async (pathAndQuery) => {
    let answer = null;
    handlers.fetch({
      request: { method: "GET", mode: "navigate", url: ORIGIN + pathAndQuery },
      respondWith: (p) => { answer = p; },
    });
    assert.ok(answer, "the worker did not answer the navigation");
    return answer;
  };
  return { CACHE, caches, lifecycle, navigate };
}

// The browser's rule: a redirected response cannot answer a navigation.
async function servable(res) {
  assert.equal(res.redirected, false, "a redirected response answering a navigation is a network error");
  assert.equal(res.status, 200);
  return res.text();
}

const OFFLINE = "<title>Offline</title>branded offline page";
const INDEX = '<title>Vivek 5.0</title><link href="css/styles.css?v=7"><script src="js/app.js?v=9"></script>';
// What Pages does: the .html spellings 308 to the extensionless URL.
const pages = (url) => {
  const u = new URL(url);
  if (u.pathname === "/offline.html") return redirected(OFFLINE, "/offline");
  if (u.pathname === "/index.html") return redirected(INDEX, "/");
  if (u.search.includes("v=")) return new Response("/* asset */", { status: 200 });
  return page("<title>other</title>");
};
const offline = () => { throw new TypeError("Failed to fetch"); };

async function installedOffline() {
  let net = pages;
  const w = boot((u) => net(u));
  await w.lifecycle("install");
  await w.lifecycle("activate");
  net = offline;
  return w;
}

test("an offline tap on a never-visited page renders the branded offline page", async () => {
  const w = await installedOffline();
  const html = await servable(await w.navigate("/chart.html?sym=NEW"));
  assert.ok(html.includes("branded offline page"), "offline.html was not the fallback");
});

test("a cold offline launch at start_url ./index.html renders the app shell", async () => {
  const w = await installedOffline();
  const html = await servable(await w.navigate("/index.html"));
  assert.ok(html.includes("<title>Vivek 5.0</title>"));
});

test("the install still precaches the shell's versioned assets", async () => {
  const w = await installedOffline();
  assert.ok(await w.caches.match("css/styles.css?v=7"), "styles.css was not precached");
  assert.ok(await w.caches.match("js/app.js?v=9"), "app.js was not precached");
});

test("a page cached under /x is found offline from a /x.html link, and the reverse", async () => {
  // Online, Pages serves /journal (the browser followed the 308), so that is
  // the key the runtime cache holds. The nav links say journal.html.
  let net = pages;
  const w = boot((u) => net(u));
  await w.lifecycle("install");
  net = (u) => (new URL(u).pathname === "/journal" ? page("<title>Journal</title>") : pages(u));
  await servable(await w.navigate("/journal"));
  net = offline;
  const html = await servable(await w.navigate("/journal.html"));
  assert.ok(html.includes("<title>Journal</title>"), "the cached /journal copy was not used for /journal.html");

  // serve.py (local) does the opposite: the .html spelling is what got cached.
  net = (u) => (new URL(u).pathname === "/momentum.html" ? page("<title>Momentum</title>") : pages(u));
  await servable(await w.navigate("/momentum.html"));
  net = offline;
  assert.ok((await servable(await w.navigate("/momentum"))).includes("<title>Momentum</title>"));
  // "/" and "/index.html" are one page.
  assert.ok((await servable(await w.navigate("/"))).includes("<title>Vivek 5.0</title>"));
});

test("a redirected entry already in the cache is re-wrapped before it answers", async () => {
  // e.g. one written by a non-navigation fetch of the same URL.
  const caches = fakeCaches();
  const w = boot(offline, caches);
  const c = await caches.open(w.CACHE);
  await c.put(ORIGIN + "/sectors", redirected("<title>News</title>", "/sectors"));
  const html = await servable(await w.navigate("/sectors"));
  assert.ok(html.includes("<title>News</title>"));
});

test("online navigations are untouched: the network's own response is returned", async () => {
  const w = await installedOffline();
  const opaque = { ok: false, redirected: false, status: 0, type: "opaqueredirect" };
  const w2 = boot(() => opaque, w.caches);
  assert.equal(await w2.navigate("/journal.html"), opaque,
    "an opaque redirect must reach the browser as-is so it follows the 308 itself");
});

test("the CACHE name moved, so activate drops v8's redirected precache", async () => {
  const caches = fakeCaches();
  const old = await caches.open("vivek5-v8");
  await old.put("offline.html", redirected(OFFLINE, "/offline"));
  const w = boot(pages, caches);
  assert.notEqual(w.CACHE, "vivek5-v8");
  await w.lifecycle("install");
  await w.lifecycle("activate");
  assert.deepEqual(await caches.keys(), [w.CACHE]);
});

(async () => {
  for (const { name, fn } of QUEUE) {
    try { await fn(); console.log(`  ✓  ${name}`); passed++; }
    catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
  }
  console.log(`\nsw_offline.test.js: ${passed}/${passed + failed} passed`);
  if (failed) process.exit(1);
})();

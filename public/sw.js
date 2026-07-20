/* Vivek 5.0 service worker (2026-07-10) — makes the installed PWA feel
   instant and survive offline, without ever serving stale market data
   when the network is up.

   Strategy:
     data/*.json + /api/*  → network-first (fresh data always wins; the last
                             good copy is the offline fallback)
     versioned assets ?v=  → cache-first (immutable: every edit bumps ?v=)
     fonts / icons / vendor→ cache-first
     HTML navigations      → network-first (deploys land immediately),
                             cache fallback offline
   Bump CACHE below to force-refresh every cached asset on a breaking change. */

const CACHE = "vivek5-v2";   // v2 2026-07-20: schema v4 + Phase 1/2 JS — purge stale cached assets

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

const put = async (req, res) => {
  try {
    const c = await caches.open(CACHE);
    await c.put(req, res.clone());
  } catch (_) { /* quota/opaque — skip */ }
  return res;
};

const networkFirst = async (req) => {
  try {
    const res = await fetch(req);
    return res.ok ? put(req, res) : res;
  } catch (_) {
    const hit = await caches.match(req);
    if (hit) return hit;
    throw _;
  }
};

const cacheFirst = async (req) => {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  return res.ok ? put(req, res) : res;
};

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;   // fonts CDN etc: browser default

  if (url.pathname.startsWith("/api/")) return;      // never cache API calls

  if (url.pathname.startsWith("/data/")) {
    e.respondWith(networkFirst(req));
    return;
  }
  if (req.mode === "navigate") {
    e.respondWith(networkFirst(req));
    return;
  }
  if (url.search.includes("v=") ||
      /\/(icons|vendor)\//.test(url.pathname) ||
      /\.(png|svg|woff2?)$/.test(url.pathname)) {
    e.respondWith(cacheFirst(req));
    return;
  }
  // everything else: network-first keeps behaviour predictable
  e.respondWith(networkFirst(req));
});

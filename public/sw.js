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

const CACHE = "vivek5-v5";   // v5 2026-07-24: #63 app-shell precache on install

// #63: precache the app shell on install — read index.html and pull its
// CURRENT versioned CSS/JS (so the list is always in sync with the deploy,
// never a hardcoded stale ?v=), plus the page itself. Repeat loads then paint
// the shell instantly from cache; a cold offline launch has something to show.
self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    try {
      const c = await caches.open(CACHE);
      const html = await fetch("index.html", { cache: "no-cache" });
      if (html && html.ok) {
        await c.put("index.html", html.clone());
        const text = await html.text();
        const urls = [...text.matchAll(/(?:href|src)="([^"]+\.(?:css|js)\?v=\d+)"/g)].map((m) => m[1]);
        await Promise.all([...new Set(urls)].map((u) =>
          fetch(u).then((r) => (r && r.ok ? c.put(u, r) : null)).catch(() => {})));
      }
    } catch (_) { /* offline at install / quota — fine, runtime caching still fills in */ }
    self.skipWaiting();
  })());
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

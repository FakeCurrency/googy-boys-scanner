/* Vivek 5.0 service worker (2026-07-10) — makes the installed PWA feel
   instant and survive offline, without ever serving stale market data
   when the network is up.

   Strategy:
     data/*.json           → network-first (fresh data always wins; the last
                             good copy is the offline fallback)
     /api/*                → not intercepted, never cached
     versioned assets ?v=  → cache-first (immutable: every edit bumps ?v=)
     fonts / icons / vendor→ cache-first
     HTML navigations      → network-first (deploys land immediately),
                             cache fallback offline
   Bump CACHE below to force-refresh every cached asset on a breaking change. */

const CACHE = "vivek5-v9";   // v9 2026-10-08 (audit #73): v8's precached offline.html / index.html were stored REDIRECTED (Pages 308s) and can never answer a navigation — drop them. v8 2026-09-21: the MY JOURNAL side + MY NAMES page were removed

// REDIRECTED RESPONSES CANNOT ANSWER A NAVIGATION (audit #73, 2026-10-08).
// Cloudflare Pages 308s /x.html -> /x and /index.html -> /, so the install
// step's fetch("offline.html") follows a redirect and the stored response has
// redirected=true. The Fetch spec makes such a response a NETWORK ERROR when it
// is used for a navigation (redirect mode "manual"), so the branded offline
// page could never render on the live site: an offline tap on a page not yet
// cached got the browser's error page instead. serve.py does not redirect,
// which is why nothing local ever saw it. Re-wrapping the body drops the flag
// (Workbox's copyResponse); a response that was not redirected passes through.
const unredirect = async (res) => (res && res.redirected
  ? new Response(await res.blob(), { status: res.status, statusText: res.statusText, headers: res.headers })
  : res);

// The other spelling of a page, so an offline navigation finds the copy the
// browser cached under it: the site links /x.html, Pages serves (and the
// runtime cache stores) /x, and / and /index.html are one page.
const pageAlias = (url) => {
  const p = url.pathname;
  let alt = null;
  if (/\/index\.html$/.test(p)) alt = p.slice(0, -"index.html".length);
  else if (/\.html$/.test(p)) alt = p.slice(0, -".html".length);
  else if (p.endsWith("/")) alt = p + "index.html";
  else if (!/\.[^/]*$/.test(p)) alt = p + ".html";
  return alt == null ? null : alt + url.search;
};

// #63: precache the app shell on install — read index.html and pull its
// CURRENT versioned CSS/JS (so the list is always in sync with the deploy,
// never a hardcoded stale ?v=), plus the page itself. Repeat loads then paint
// the shell instantly from cache; a cold offline launch has something to show.
self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    try {
      const c = await caches.open(CACHE);
      // UX-20 #19: the offline fallback page rides in the shell precache —
      // fully self-contained, so it renders even with nothing else cached.
      // Both are stored un-redirected (see unredirect above), or the one
      // page that exists to be shown offline can never be shown.
      try {
        const off = await fetch("offline.html", { cache: "no-cache" });
        if (off && off.ok) await c.put("offline.html", await unredirect(off));
      } catch (_) { /* fills in on a later install */ }
      const html = await fetch("index.html", { cache: "no-cache" });
      if (html && html.ok) {
        await c.put("index.html", await unredirect(html.clone()));
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
    // network → cached copy of the SAME page (either spelling, audit #73) →
    // offline.html (UX-20 #19), so an offline navigation to a never-visited
    // page lands on a branded explanation instead of the browser dinosaur.
    // Whatever is served from cache goes through unredirect: a redirected
    // entry would be a network error here.
    e.respondWith(networkFirst(req).then(unredirect, async () => {
      const alt = pageAlias(url);
      const same = alt && await caches.match(alt);
      if (same) return unredirect(same);
      const off = await caches.match("offline.html");
      if (off) return unredirect(off);
      throw new Error("offline");
    }));
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

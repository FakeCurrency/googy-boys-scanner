/* Shared guard + edge cache for the free price/quote relay (/api/quote, /api/price).
 *
 * WHY THIS EXISTS (2026-07-20): the previous per-IP rate limiter counted
 * requests in KV — one read + one write per request. At normal journal/chart
 * polling volume the guard alone burned the KV free-tier daily write quota
 * (1,000 writes/day), which is what triggered Cloudflare's daily-limit email.
 * The guard now costs zero KV operations.
 *
 * Also: a Cache-Control header on a Pages Function response does NOT edge-cache
 * it by itself — the function still runs on every request. Real edge caching
 * needs the Cache API (caches.default), provided here as cacheMatch/cachePut.
 */

// ── in-memory per-IP limiter ────────────────────────────────────────────────
// Isolate-local Map instead of KV. Counts reset when an isolate recycles and
// aren't shared across PoPs, so a determined abuser sees a higher effective
// cap — fine for an abuse guard on a free relay; legit clients never notice.
export const PX_REQS_PER_MIN = 120;

const buckets = new Map();

export function overPxLimit(request, cap = PX_REQS_PER_MIN) {
  let ip = "unknown";
  try { ip = request.headers.get("CF-Connecting-IP") || "unknown"; } catch (_) {}
  const minute = Math.floor(Date.now() / 60000);
  const key = `${ip}:${minute}`;
  // Bound memory: when the map grows, drop every bucket from past minutes.
  if (buckets.size > 2000) {
    const live = `:${minute}`;
    for (const k of buckets.keys()) if (!k.endsWith(live)) buckets.delete(k);
  }
  const n = (buckets.get(key) || 0) + 1;
  buckets.set(key, n);
  return n > cap;
}

// ── edge cache helpers ──────────────────────────────────────────────────────
// Keyed on the full request URL; expiry follows the response's own
// Cache-Control (s-maxage), so the JSON helpers in quote.js/price.js stay the
// single source of truth for TTLs. Only 200s should be cachePut — errors and
// 429s must never be served from cache.
export async function cacheMatch(request) {
  try { return await caches.default.match(request.url); } catch (_) { return null; }
}

export function cachePut(ctx, response) {
  try {
    // clone() so the original body stays readable for the client.
    ctx.waitUntil(caches.default.put(ctx.request.url, response.clone()));
  } catch (_) { /* cache is best-effort — never fail the request over it */ }
  return response;
}

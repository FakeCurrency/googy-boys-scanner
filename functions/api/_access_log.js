/* Best-effort access logging for the unauthenticated dispatch/sync endpoints
 * (/api/close, /api/scan, /api/journal) — 2026-08-20.
 *
 * WHY: after the 2026-08-20 bad-commit incident there was nothing to read to
 * answer "what else hit these endpoints in the last 24 hours". This is the
 * diagnosis trail, not analytics: method + path + outcome + coarse caller
 * identity (IP / country / User-Agent), kept in KV for a few days and gone.
 *
 * THE RULES (same spirit as the cooldown-refund try/catch patterns beside it):
 *   - BEST-EFFORT ONLY. Every KV touch is inside try/catch; a logging failure
 *     must never block or fail the close/scan/journal action it describes.
 *     Callers route through ctx.waitUntil() so it does not even add latency.
 *   - NO REQUEST BODIES. Journal PUTs carry the user's whole journal; close
 *     bodies carry trade details. Only the envelope is recorded.
 *   - WRITES STAY PROPORTIONAL TO RARE EVENTS. journal.js's own limiter
 *     comments document the constraint: KV writes are the scarce resource
 *     (~1k/day free vs 100k reads), and the journal page polls GET every 60s
 *     per open tab (~1,440/day). Logging every successful GET per-request
 *     would burn the write quota the sync itself needs — so hot-path success
 *     is COALESCED to one "seen" marker per IP per UTC day (callers opt in
 *     via coalesceOk). Dispatch endpoints are already daily-capped (40 scans,
 *     60 closes) so their every call is cheap to record individually.
 */

const LOG_TTL_S = 4 * 86400;   // a few days is plenty — incident diagnosis, not analytics

export function outcomeOf(status) {
  if (status === 429) return "rate-limited";
  if (status >= 200 && status < 300) return "ok";
  return "error";
}

/* Record one request's envelope. `opts.coalesceOk` switches successful calls
 * to the once-per-IP-per-day marker (for polled endpoints — see header). */
export async function logAccess(env, request, path, status, opts = {}) {
  try {
    if (!env || !env.JOURNAL_KV) return;               // same degradation as the rate limiters
    const now = new Date();
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const country = (request.cf && request.cf.country)
      || request.headers.get("CF-IPCountry") || "";
    const ua = (request.headers.get("User-Agent") || "").slice(0, 120);
    const outcome = outcomeOf(status);

    if (opts.coalesceOk && outcome === "ok") {
      const day = now.toISOString().slice(0, 10);
      const seenKey = `alog:seen:${path}:${day}:${ip}`;
      if (await env.JOURNAL_KV.get(seenKey)) return;   // already recorded today
      await env.JOURNAL_KV.put(seenKey,
        JSON.stringify({ t: now.toISOString(), cc: country, ua }),
        { expirationTtl: LOG_TTL_S });
      return;
    }

    // One entry per event. The random suffix stops two same-millisecond
    // requests clobbering each other's key.
    const key = `alog:${path}:${now.toISOString()}:${Math.random().toString(36).slice(2, 8)}`;
    await env.JOURNAL_KV.put(key, JSON.stringify({
      m: request.method,
      p: path,
      s: status,
      o: outcome,
      ip,
      cc: country,
      ua,
      t: now.toISOString(),
    }), { expirationTtl: LOG_TTL_S });
  } catch (_) { /* best-effort: a log failure must never block the action */ }
}

/* Wrap a Pages Function handler so every response it returns is logged.
 * The log write rides ctx.waitUntil when the runtime provides it (so the
 * response is not delayed); otherwise it is awaited — which is what makes
 * the behaviour deterministic under test. */
export const withAccessLog = (path, handler, opts = {}) => async (ctx) => {
  const res = await handler(ctx);
  const p = logAccess(ctx.env, ctx.request, path, res.status, opts);
  if (typeof ctx.waitUntil === "function") ctx.waitUntil(p);
  else await p;
  return res;
};

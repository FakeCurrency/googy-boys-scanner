/* Best-effort access logging for the unauthenticated dispatch endpoints
 * (/api/close, /api/scan) — 2026-08-20.
 *
 * WHY: after the 2026-08-20 bad-commit incident there was nothing to read to
 * answer "what else hit these endpoints in the last 24 hours". This is the
 * diagnosis trail, not analytics: method + path + outcome + coarse caller
 * identity (IP / country / User-Agent), kept in KV for a few days and gone.
 *
 * THE RULES (same spirit as the cooldown-refund try/catch patterns beside it):
 *   - BEST-EFFORT ONLY. Every KV touch is inside try/catch; a logging failure
 *     must never block or fail the close/scan action it describes.
 *     Callers route through ctx.waitUntil() so it does not even add latency.
 *   - NO REQUEST BODIES. Close bodies carry trade details; only the envelope
 *     is recorded.
 *   - WRITES STAY PROPORTIONAL TO RARE EVENTS. KV writes are the scarce
 *     resource (~1k/day free vs 100k reads), so nothing polled may be logged
 *     per request. Both remaining callers are daily-capped dispatch endpoints
 *     (40 scans, 60 closes), so every one of their calls is cheap to record
 *     individually. THE COALESCING BRANCH IS GONE (2026-09-21): it existed for
 *     /api/journal's 60-second GET poll — one "seen" marker per IP per UTC day
 *     — and that endpoint went with the manual journal it synced. If a polled
 *     endpoint is ever added back, coalescing comes back WITH it rather than
 *     sitting here uncalled; the write-quota argument above is the reason it
 *     existed and is what to re-read first.
 */

const LOG_TTL_S = 4 * 86400;   // a few days is plenty — incident diagnosis, not analytics

export function outcomeOf(status) {
  if (status === 429) return "rate-limited";
  if (status >= 200 && status < 300) return "ok";
  return "error";
}

/* Record one request's envelope. One entry per call: every caller is a
 * daily-capped dispatch endpoint (see the header on coalescing). */
export async function logAccess(env, request, path, status) {
  try {
    if (!env || !env.JOURNAL_KV) return;               // same degradation as the rate limiters
    const now = new Date();
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const country = (request.cf && request.cf.country)
      || request.headers.get("CF-IPCountry") || "";
    const ua = (request.headers.get("User-Agent") || "").slice(0, 120);
    const outcome = outcomeOf(status);

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
export const withAccessLog = (path, handler) => async (ctx) => {
  const res = await handler(ctx);
  const p = logAccess(ctx.env, ctx.request, path, res.status);
  if (typeof ctx.waitUntil === "function") ctx.waitUntil(p);
  else await p;
  return res;
};

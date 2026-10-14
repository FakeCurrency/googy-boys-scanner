/* Best-effort access logging for the unauthenticated dispatch endpoints
 * (/api/close, /api/scan, and the heals /api/heartbeat dispatches) — 2026-08-20.
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
 *     resource (~1k/day free vs 100k reads), so nothing a caller can repeat at
 *     will may cost a write per request.
 *
 * SPLIT BY OUTCOME (REFINE200 #158, 2026-10-14). The caps on these endpoints
 * limit DISPATCHES, not calls: measured, 100 POSTs to /api/scan dispatched one
 * run, were refused 99 times, and still cost 100 log writes. ~1,000 junk calls
 * would spend the whole free write quota, and with it the rate limiters'
 * own writes. So:
 *   - a SUCCESSFUL call (2xx = a dispatch went out) gets its own entry, as
 *     before. Those are bounded by the endpoints' daily caps;
 *   - a REFUSED or FAILED call (anything else) writes ONE marker per caller IP
 *     per path per UTC hour, recording the first refusal of that hour. Later
 *     ones cost a KV read, not a write. The trail still names who was knocking
 *     and when; it no longer pays per knock.
 * (The 2026-09-21 note that coalescing should come back WITH any caller that
 * can repeat at will is what this is: refused calls are exactly that caller.)
 */

const LOG_TTL_S = 4 * 86400;   // a few days is plenty — incident diagnosis, not analytics

export function outcomeOf(status) {
  if (status === 429) return "rate-limited";
  if (status >= 200 && status < 300) return "ok";
  return "error";
}

/* Record one request's envelope: every dispatched call individually, refused
 * calls once per IP per path per hour (see the header). */
export async function logAccess(env, request, path, status) {
  try {
    if (!env || !env.JOURNAL_KV) return;               // same degradation as the rate limiters
    const now = new Date();
    const iso = now.toISOString();
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const country = (request.cf && request.cf.country)
      || request.headers.get("CF-IPCountry") || "";
    const ua = (request.headers.get("User-Agent") || "").slice(0, 120);
    const outcome = outcomeOf(status);
    const entry = JSON.stringify({
      m: request.method,
      p: path,
      s: status,
      o: outcome,
      ip,
      cc: country,
      ua,
      t: iso,
    });

    if (outcome === "ok") {
      // One entry per dispatch. The random suffix stops two same-millisecond
      // requests clobbering each other's key.
      const key = `alog:${path}:${iso}:${Math.random().toString(36).slice(2, 8)}`;
      await env.JOURNAL_KV.put(key, entry, { expirationTtl: LOG_TTL_S });
      return;
    }
    // Refused / failed: the first one this hour from this IP is the record.
    const key = `alog:refused:${path}:${iso.slice(0, 13)}:${ip}`;
    if (await env.JOURNAL_KV.get(key)) return;
    await env.JOURNAL_KV.put(key, entry, { expirationTtl: LOG_TTL_S });
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

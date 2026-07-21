/* Cloudflare Pages Function — GET /api/health
 *
 * GitHub-INDEPENDENT freshness heartbeat (2026-07-21, Phase 6 P2).
 *
 * The Phase 5 watchdog rides GitHub Actions — the same scheduler it monitors.
 * This endpoint gives an external uptime monitor (UptimeRobot etc.) a second,
 * uncorrelated leg: it reads the PUBLISHED bot book (a static asset served by
 * Cloudflare, deployed by the last successful data commit) and answers
 *
 *   200 {ok:true,  age_h, updated_at}   book fresher than the threshold
 *   503 {ok:false, age_h|error, ...}    stale / missing / unparseable
 *
 * so "the pipeline stopped committing" turns into a monitor alert with NO
 * GitHub involvement anywhere in the path. Default threshold 4h — the same
 * WATCHDOG_BOOK_MAX_AGE_H the in-repo watchdog uses (a data commit lands at
 * least hourly via crypto_bot). Override per-probe with ?max_h=N (1..48).
 *
 * No secrets, read-only, never cached (a cached "ok" would defeat the point).
 */

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

export async function onRequestGet(context) {
  let maxH = parseFloat(new URL(context.request.url).searchParams.get("max_h"));
  if (!Number.isFinite(maxH) || maxH < 1 || maxH > 48) maxH = 4;

  try {
    const assetURL = new URL("/data/vivek_bot_book.json", context.request.url);
    const res = await context.env.ASSETS.fetch(new Request(assetURL));
    if (!res.ok) return json(503, { ok: false, error: `book asset HTTP ${res.status}` });
    const book = await res.json();
    const updated = Date.parse(book.updated_at || "");
    if (!Number.isFinite(updated))
      return json(503, { ok: false, error: "book has no parseable updated_at" });
    const ageH = (Date.now() - updated) / 3.6e6;
    const body = {
      ok: ageH <= maxH,
      age_h: Math.round(ageH * 100) / 100,
      max_h: maxH,
      updated_at: book.updated_at,
      open: Array.isArray(book.open) ? book.open.length : null,
    };
    return json(body.ok ? 200 : 503, body);
  } catch (e) {
    return json(503, { ok: false, error: String(e && e.message || e) });
  }
}

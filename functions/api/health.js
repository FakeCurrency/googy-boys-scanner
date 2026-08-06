/* Cloudflare Pages Function — GET /api/health[?market=asx][&max_h=N]
 *
 * GitHub-INDEPENDENT freshness heartbeat (2026-07-21, Phase 6 P2).
 *
 * The Phase 5 watchdog rides GitHub Actions — the same scheduler it monitors.
 * This endpoint gives an external uptime monitor (UptimeRobot etc.) a second,
 * uncorrelated leg: it reads a PUBLISHED data asset (served by Cloudflare,
 * deployed by the last successful data commit) and answers
 *
 *   200 {ok:true,  age_h, updated_at}   fresher than the threshold
 *   503 {ok:false, age_h|error, ...}    stale / missing / unparseable
 *
 * so "the pipeline stopped committing" turns into a monitor alert with NO
 * GitHub involvement anywhere in the path. Default threshold 4h — the same
 * WATCHDOG_BOOK_MAX_AGE_H the in-repo watchdog uses (a data commit lands at
 * least hourly via crypto_bot). Override per-probe with ?max_h=N (1..48).
 *
 * PER-MARKET MODE (?market=asx|nasdaq|crypto, added 2026-07-28)
 * ------------------------------------------------------------
 * The default (whole-pipeline) answer reads the COMBINED bot book, whose
 * updated_at moves whenever ANY market commits. crypto_bot.yml commits hourly,
 * 24/7 — so the combined answer is essentially always "fresh", which is right
 * for "is the pipeline alive?" and badly wrong for "did THIS market scan?".
 *
 * That distinction was not academic: scan.yml's :47 ASX backstop asked the
 * default endpoint whether a scan had landed in the last hour, crypto's hourly
 * commit always said yes, and the backstop skipped itself every single time —
 * so the ghosted :07 ASX runs it exists to rescue were never rescued. On
 * Mon 2026-07-27 only ONE of the six 00:07–05:07 ASX crons produced a scan and
 * the backstop stayed silent through all five misses.
 *
 * With ?market=<m> the probe reads public/data/<m>_prices.json instead — small
 * (2–55 KB vs the 2 MB *_vivek.json), carries the same wall-clock generated_at,
 * and scan.yml commits it per-market, so it moves if and ONLY if that market
 * actually scanned. The market name is checked against a fixed allowlist; the
 * asset path is never built from raw user input.
 *
 * No secrets, read-only, never cached (a cached "ok" would defeat the point).
 */

// Fixed allowlist — the asset path is NEVER interpolated from raw input.
const MARKETS = new Set(["asx", "nasdaq", "crypto"]);

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

export async function onRequestGet(context) {
  const params = new URL(context.request.url).searchParams;

  let maxH = parseFloat(params.get("max_h"));
  if (!Number.isFinite(maxH) || maxH < 1 || maxH > 48) maxH = 4;

  const market = (params.get("market") || "").trim().toLowerCase();
  if (market && !MARKETS.has(market)) {
    // Callers fail OPEN on a non-ok answer (scan.yml runs the scan rather than
    // trusting a broken probe), so a typo'd market must not read as healthy.
    return json(400, { ok: false, error: `unknown market '${market}'` });
  }

  // Per-market: that market's prices sidecar. Default: the combined book.
  const path = market ? `/data/${market}_prices.json` : "/data/vivek_bot_book.json";
  const stampKey = market ? "generated_at" : "updated_at";

  try {
    const assetURL = new URL(path, context.request.url);
    const res = await context.env.ASSETS.fetch(new Request(assetURL));
    if (!res.ok) return json(503, { ok: false, error: `asset ${path} HTTP ${res.status}` });
    const doc = await res.json();
    const stamp = doc[stampKey] || "";
    const updated = Date.parse(stamp);
    if (!Number.isFinite(updated))
      return json(503, { ok: false, error: `${path} has no parseable ${stampKey}` });
    const ageH = (Date.now() - updated) / 3.6e6;
    const body = {
      ok: ageH <= maxH,
      age_h: Math.round(ageH * 100) / 100,
      max_h: maxH,
      updated_at: stamp,
      // Kept for the whole-pipeline probe's existing consumers; the per-market
      // sidecar carries no book, so it reports the market instead.
      ...(market ? { market } : { open: Array.isArray(doc.open) ? doc.open.length : null }),
    };
    return json(body.ok ? 200 : 503, body);
  } catch (e) {
    return json(503, { ok: false, error: String(e && e.message || e) });
  }
}

/* HEAD must answer, not 404 — see the same note in heartbeat.js (2026-08-07).
 *
 * This one was NOT broken: its UptimeRobot monitor predates the HEAD default
 * and sends GET. It is fixed anyway because the trap is identical and the
 * blast radius here is worse — this endpoint is the ALARM, the last thing that
 * still speaks when GitHub's scheduler dies. Recreate this monitor one day, or
 * let UptimeRobot migrate its default, and the alarm goes permanently red
 * against a healthy pipeline until someone reads a 404 carefully.
 */
export const onRequestHead = onRequestGet;

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
 * WHO CALLS WHICH MODE (updated 2026-10-14). The default mode is the external
 * uptime monitor's alarm and the deck/status lamp's read (app.js, status.js).
 * The per-market mode has NO automated caller any more: scan.yml's backstop
 * was replaced by scripts/scan_gate.py on 2026-10-05, which reads the market
 * calendar itself, and /api/heartbeat (the healer) reads the same sidecars
 * directly. It stays as a manual / diagnostic probe -- e.g. ops.yml site-probe
 * with paths=/api/health?market=asx -- and its answers are unchanged.
 *
 * TWO MORE THINGS THE PIPELINE ANSWER CARRIES (NEXT100 #12/#13, 2026-11-03),
 * neither of which can move its 200/503 -- that stays the combined book's age:
 *
 *   - Per-stock-market staleness, as `breached` entries {market, kind:"stale",
 *     session_h, updated_at}. 57 of 60 open rows are stocks whose stops and
 *     time stops fire only in an in-session scan, and crypto's hourly commit
 *     keeps the combined book fresh whatever the stock clock is doing, so a
 *     dead ASX or NASDAQ scan was invisible here. Each stock market is judged
 *     on its OWN published prices sidecar (the stamp scripts/scan_gate.py and
 *     /api/heartbeat read: it moves if and only if that market scanned) in
 *     SESSION hours -- time inside its config.MARKET_SCAN_WINDOWS window, on
 *     its own weekdays and clock -- so a night or a weekend never counts. Past
 *     STOCK_STALE_SESSION_H the market is listed. A sidecar that cannot be read
 *     is not judged here (?market= answers 503 for it); the watchdog judges
 *     the same market off its canonical book in scanner/watchdog.py.
 *   - GH_DISPATCH_TOKEN's expiry, from KV ONLY (token_expires, token_days_left,
 *     token_expiring, token_warn_days): _dispatch.js notes the date GitHub
 *     states on each dispatch's answer (see _token_expiry.js). This endpoint
 *     never calls GitHub; nothing stored = nulls and token_expiring false.
 *
 * No secrets, read-only, never cached (a cached "ok" would defeat the point).
 */

import { tokenExpiryOf } from "./_token_expiry.js";

// Fixed allowlist — the asset path is NEVER interpolated from raw input.
const MARKETS = new Set(["asx", "nasdaq", "crypto"]);

// GH_DISPATCH_TOKEN's warning line (NEXT100 #12): with fewer than this many
// whole days left before the token expires, the answer says
// token_expiring:true and the status lamp turns amber. ONE home -- status.js
// reads the flag and the number from the answer, never a copy of its own.
const TOKEN_WARN_DAYS = 14;

// Per-stock-market staleness (NEXT100 #13). Mirrors of
// config.WATCHDOG_STOCK_SCAN_MAX_SESSION_H and config.MARKET_SCAN_WINDOWS
// ([tz, first-scan minute, last-scan minute], market-local, weekdays), pinned
// to config by tests/test_js_config_mirrors.py -- never edit one side alone.
// SESSION_WALK_DAYS = watchdog.SESSION_WALK_DAYS (a stamp older than that is
// stale under any reading, so the walk stops there).
const STOCK_STALE_SESSION_H = 3;
const SCAN_WINDOWS = { asx: ["Australia/Sydney", 660, 1005], nasdaq: ["America/New_York", 630, 1005] };
const SESSION_WALK_DAYS = 31;

// Minutes `tz` is ahead of UTC at the instant `ms` (DST-correct, via Intl,
// which the Workers runtime ships with full time-zone data).
const ZONE_FMT = {};
function tzOffsetMin(ms, tz) {
  const f = ZONE_FMT[tz] || (ZONE_FMT[tz] = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
    hour: "numeric", minute: "numeric", second: "numeric",
  }));
  const p = {};
  for (const part of f.formatToParts(new Date(ms))) p[part.type] = Number(part.value);
  const wall = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second);
  return Math.round((wall - Math.floor(ms / 1000) * 1000) / 6e4);
}

// The instant of wall time `min` minutes past midnight, in `tz`, on the local
// calendar date whose 00:00 UTC is `dayUtcMs`. Two passes, so a date on which
// the clocks change still lands on the right side of the change.
function localToMs(dayUtcMs, min, tz) {
  const wall = dayUtcMs + min * 6e4;
  const first = wall - tzOffsetMin(wall, tz) * 6e4;
  return wall - tzOffsetMin(first, tz) * 6e4;
}

// Hours of a stock market's scan window between two instants: the overlap of
// [startMs, endMs] with each weekday's [first, last] scan minute in the
// market's own clock. Exact, and the same sum as scanner/watchdog.py
// market_session_hours (both run tests/fixtures/session_hours_cases.json).
function sessionHours(startMs, endMs, win) {
  if (!win || !(endMs > startMs)) return 0;
  const [tz, lo, hi] = win;
  const local = new Date(startMs + tzOffsetMin(startMs, tz) * 6e4);
  const day0 = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate());
  let total = 0;
  for (let i = 0; i < SESSION_WALK_DAYS; i++) {
    const day = day0 + i * 864e5;
    const open = localToMs(day, lo, tz);
    if (open >= endMs) break;
    const wd = new Date(day).getUTCDay();
    if (wd >= 1 && wd <= 5) {
      total += Math.max(0, Math.min(endMs, localToMs(day, hi, tz)) - Math.max(startMs, open));
    }
  }
  return total / 36e5;
}

// The stock markets past STOCK_STALE_SESSION_H session hours since their own
// last scan, as `breached` entries. Never throws: an unreadable sidecar is
// left unjudged rather than invented into a finding.
async function staleMarkets(context, nowMs) {
  const rows = await Promise.all(Object.keys(SCAN_WINDOWS).map(async (m) => {
    try {
      const res = await context.env.ASSETS.fetch(
        new Request(new URL(`/data/${m}_prices.json`, context.request.url)));
      if (!res.ok) return null;
      const stamp = String((await res.json()).generated_at || "");
      const t = Date.parse(stamp);
      if (!Number.isFinite(t)) return null;
      const h = sessionHours(t, nowMs, SCAN_WINDOWS[m]);
      return h > STOCK_STALE_SESSION_H
        ? { market: m, kind: "stale", session_h: Math.round(h * 100) / 100, updated_at: stamp }
        : null;
    } catch (_) {
      return null;
    }
  }));
  return rows.filter(Boolean);
}

// The markets whose loss guard has halted new entries, as the book's `guard`
// block records them (vivek_run writes breached + breach_kind per market).
const breachedOf = (guard) => {
  const g = guard && typeof guard === "object" ? guard : {};
  return Object.keys(g)
    .filter((m) => g[m] && g[m].breached)
    .map((m) => ({ market: m, kind: String(g[m].breach_kind || "loss limit") }));
};

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
    const nowMs = Date.now();
    // The pipeline answer also reads the stock sidecars and the token's
    // expiry; neither helper throws, so only the book read can fail this.
    const [res, stale, token] = await Promise.all([
      context.env.ASSETS.fetch(new Request(assetURL)),
      market ? null : staleMarkets(context, nowMs),
      market ? null : tokenExpiryOf(context.env.JOURNAL_KV, nowMs),
    ]);
    if (!res.ok) return json(503, { ok: false, error: `asset ${path} HTTP ${res.status}` });
    const doc = await res.json();
    const stamp = doc[stampKey] || "";
    const updated = Date.parse(stamp);
    if (!Number.isFinite(updated))
      return json(503, { ok: false, error: `${path} has no parseable ${stampKey}` });
    const ageH = (nowMs - updated) / 3.6e6;
    const body = {
      ok: ageH <= maxH,
      age_h: Math.round(ageH * 100) / 100,
      max_h: maxH,
      updated_at: stamp,
      // Kept for the whole-pipeline probe's existing consumers; the per-market
      // sidecar carries no book, so it reports the market instead. `breached`
      // (REFINE200 #68) is the loss guards' state off the same book, so the
      // status lamp can show a breach without every page downloading the book.
      ...(market ? { market } : {
        open: Array.isArray(doc.open) ? doc.open.length : null,
        breached: breachedOf(doc.guard).concat(stale),
        ...token,
        token_expiring: token.token_days_left !== null && token.token_days_left < TOKEN_WARN_DAYS,
        token_warn_days: TOKEN_WARN_DAYS,
      }),
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

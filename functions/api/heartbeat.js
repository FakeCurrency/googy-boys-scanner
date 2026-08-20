/* Cloudflare Pages Function — GET /api/heartbeat[?stale_min=N][&market=all]
 *
 * THE SELF-HEAL LEG (2026-08-04, owner-approved). Pinged on a timer by an
 * EXTERNAL monitor (UptimeRobot). Reads how stale the committed book is; if a
 * scan is overdue it dispatches one itself. Fresh -> does nothing.
 *
 * WHY THIS EXISTS — the incident, not a hypothetical
 * --------------------------------------------------
 * 2026-08-04: GitHub's cron scheduler dropped fires across THREE workflows at
 * once. crypto_bot.yml (48/day) went 09:53 -> 13:53 with eight consecutive
 * fires missed; scan.yml's three real ASX crons never ran; stop_watcher.yml
 * (five-minute cron) was running at ~5% of its declared cadence. The session opened at
 * 10:00 and the first scan of the day landed at 13:39 — 3h39m of a live
 * session, during a pre-registered cycle, with nothing evaluated.
 *
 * The reason no backstop caught it is the whole argument for this file:
 * scan.yml's :47 ASX backstop, crypto_bot's :52 freshness fire and the
 * watchdog in kill_switch.yml are ALL crons. The mechanism that exists to
 * rescue a dropped cron is dropped by the same outage. The correlation is
 * total, and no amount of adding crons fixes a correlated failure — it only
 * adds more things to drop. The only thing that saw the outage was
 * /api/health, built (2026-07-21) precisely to be GitHub-independent.
 *
 * So this endpoint is the second half of that idea: /api/health is the ALARM,
 * this is the HEALER, and neither runs on GitHub's clock.
 *
 * IT RETURNS 200 WHEN IT HEALS, AND THAT IS THE DESIGN
 * ----------------------------------------------------
 * Stale is the condition this exists to FIX, not a fault to report. Return
 * red on "stale -> dispatched" and the monitor pages the owner every time the
 * system successfully repairs itself — an alarm that fires on success, which
 * is the fastest way to teach someone to ignore it (the stop_watcher 503
 * lesson, learned here at the cost of a five-minutely failure email).
 *
 * It returns 503 for exactly one class of thing: THE HEALER ITSELF CANNOT
 * HEAL — no dispatch token, GitHub rejected the dispatch, the asset is
 * unreadable. That state is invisible to every other channel (a silent
 * scheduler plus a silent healer looks identical to a healthy system until
 * /api/health trips four hours later), so it is the one thing worth waking
 * someone for. Same split as tick.js: "never switched on / now broken" are
 * two different questions and must not share an icon.
 *
 * UNAUTHENTICATED BY CONSTRUCTION, and that is safe here
 * -----------------------------------------------------
 * A secret in a monitor URL is a secret in a query string, in a third party's
 * database, in every one of its logs. Not worth it, because the endpoint is
 * self-limiting by shape: it only ever acts when a scan is ALREADY overdue,
 * it shares /api/scan's KV cooldown, and it carries its own daily cap. The
 * most an abuser achieves is a scan the pipeline already needed. The token
 * never leaves the server and the upstream GitHub body is never echoed.
 *
 * Setup: needs GH_DISPATCH_TOKEN in Cloudflare (the same one /api/scan uses)
 * and the JOURNAL_KV binding. Point an UptimeRobot HTTP(s) monitor here on a
 * 5-minute interval and leave the /api/health monitor alone — it stays the
 * alarm.
 */

// Default staleness before a heal fires. Deliberately BETWEEN the two numbers
// either side of it and not settable without checking both: a healthy full
// cycle is ~40-80 min (so anything under ~90 would fight a working schedule
// and dispatch duplicates), and /api/health alarms at 4h (so anything over
// ~180 would let the owner get paged before the healer ever tried). 90 min
// means the pipeline has missed at least one whole cycle before this acts.
const DEFAULT_STALE_MIN = 90;

// Separate from /api/scan's cap ON PURPOSE. They share the 5-minute cooldown
// below — that is correctness, it stops a manual SCAN and a heal dispatching
// the same run twice — but a shared DAILY budget would let an automated healer
// silently eat the owner's manual SCAN button on a bad scheduler day, which is
// the one control he reaches for when he notices something is wrong.
const HEAL_DAILY_CAP = 24;

const BOOK = "/data/vivek_bot_book.json";

// Per-market freshness sidecars — same fix as health.js shipped 2026-07-28 for
// the identical bug class: crypto's hourly commits keep the COMBINED book's
// updated_at perpetually fresh, so a healer that only ever reads BOOK can
// never see an ASX- or NASDAQ-only staleness gap. market="all" still reads
// the combined book, unchanged; a specific market reads its own sidecar.
const marketPath = (mkt) => `/data/${mkt}_prices.json`;

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

export async function onRequestGet(context) {
  const { env, request } = context;
  const params = new URL(request.url).searchParams;

  let staleMin = parseFloat(params.get("stale_min"));
  if (!Number.isFinite(staleMin) || staleMin < 15 || staleMin > 720) {
    staleMin = DEFAULT_STALE_MIN;
  }

  const m = String(params.get("market") || "all").toLowerCase();
  const market = ["asx", "nasdaq", "crypto", "all"].includes(m) ? m : "all";

  // ---- how stale is the relevant freshness source? --------------------------
  // "all" -> combined book (updated_at), unchanged. A specific market -> its
  // own /data/<market>_prices.json sidecar (generated_at), so the healer can
  // actually detect a market-scoped gap instead of always answering for
  // whichever market last committed to the combined book. `market` is already
  // constrained to the asx/nasdaq/crypto/all allowlist above, so marketPath()
  // is never called with untrusted input.
  const assetPath = market === "all" ? BOOK : marketPath(market);
  const stampKey = market === "all" ? "updated_at" : "generated_at";

  let ageMin, stamp;
  try {
    const assetURL = new URL(assetPath, request.url);
    const res = await env.ASSETS.fetch(new Request(assetURL));
    if (!res.ok) return json(503, { ok: false, error: `asset ${assetPath} HTTP ${res.status}` });
    const doc = await res.json();
    stamp = doc[stampKey] || "";
    const updated = Date.parse(stamp);
    // FAIL LOUD, NOT OPEN. An unreadable stamp must not be treated as "stale,
    // heal it" — that would dispatch a scan every probe, for ever, off a
    // corrupt file. It also must not read as fresh. It is the healer being
    // unable to answer its own question, which is the 503 class.
    if (!Number.isFinite(updated)) {
      return json(503, { ok: false, error: `${assetPath} has no parseable ${stampKey}` });
    }
    ageMin = (Date.now() - updated) / 6e4;
  } catch (e) {
    return json(503, { ok: false, error: String((e && e.message) || e) });
  }

  const base = {
    age_min: Math.round(ageMin * 10) / 10,
    stale_min: staleMin,
    updated_at: stamp,
  };

  if (ageMin <= staleMin) {
    return json(200, { ok: true, healthy: true, action: "none", ...base });
  }

  // ---- overdue: heal ------------------------------------------------------
  const token = env.GH_DISPATCH_TOKEN;
  if (!token) {
    // The healer is installed and disarmed. Nothing else in the system can see
    // that, so it is worth the alert rather than a quiet 200.
    return json(503, {
      ok: false, configured: false, action: "cannot_heal", ...base,
      error: "GH_DISPATCH_TOKEN is not set in Cloudflare — the heartbeat cannot dispatch a scan.",
    });
  }

  // Cooldown SHARED with /api/scan (same key), daily cap NOT shared. See the
  // constants above for why the two differ. Written BEFORE the GitHub call to
  // close the double-fire race, refunded if the dispatch fails — the pattern
  // scan.js arrived at on 2026-07-29, where a sticky cooldown after a failed
  // dispatch meant five minutes of "already running" about a run that never
  // existed.
  let refund = null;
  if (env.JOURNAL_KV) {
    try {
      const cdKey = `ratelimit:scan:${market}`;
      if (await env.JOURNAL_KV.get(cdKey)) {
        // A heal (or a manual SCAN) is already in flight. Not an error — the
        // system is doing the right thing, so the monitor stays green.
        return json(200, { ok: true, healthy: false, action: "cooling_down", ...base });
      }
      const dayKey = `ratelimit:heal:day:${new Date().toISOString().slice(0, 10)}`;
      const used = parseInt((await env.JOURNAL_KV.get(dayKey)) || "0", 10);
      if (used >= HEAL_DAILY_CAP) {
        // Healing this often means something is wrong that healing cannot fix
        // (a scan failing on arrival, say). Stop pouring runs into it and say
        // so — a runaway healer is worse than a stopped one.
        return json(503, {
          ok: false, action: "heal_cap_reached", heals_today: used, ...base,
          error: `Heal cap (${HEAL_DAILY_CAP}/day) reached while still stale — scans are being dispatched and not landing.`,
        });
      }
      await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 300 });
      await env.JOURNAL_KV.put(dayKey, String(used + 1), { expirationTtl: 172800 });
      refund = async () => {
        try {
          await env.JOURNAL_KV.delete(cdKey);
          await env.JOURNAL_KV.put(dayKey, String(used), { expirationTtl: 172800 });
        } catch (_) { /* best effort */ }
      };
    } catch (_) { /* KV hiccup -> let the heal through; being stale is worse */ }
  }

  const repo = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const workflow = env.GH_WORKFLOW || "scan.yml";
  const ref = env.GH_REF || "main";
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 10000);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "googy-boys-scanner",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref, inputs: { market } }),
      signal: ctrl.signal,
    });

    if (res.status === 204) {
      return json(200, { ok: true, healthy: false, action: "dispatched", market, ...base });
    }

    // Never echo the upstream body — it can carry token/repo details.
    const friendly = {
      401: "Dispatch token invalid or expired — regenerate GH_DISPATCH_TOKEN in Cloudflare.",
      403: "Dispatch token lacks permission (needs Actions: Read and write), or GitHub is rate-limiting.",
      404: `Workflow "${workflow}" or repo not found — check GH_WORKFLOW / GH_REPO.`,
      422: `GitHub could not dispatch on ref "${ref}" — check the branch and that the workflow has workflow_dispatch.`,
      429: "GitHub is rate-limiting dispatches.",
    }[res.status] || `GitHub rejected the dispatch (${res.status}).`;

    if (refund) await refund();   // nothing was dispatched — free the retry
    return json(503, { ok: false, action: "dispatch_failed", status: res.status, error: friendly, ...base });
  } catch (err) {
    const aborted = err && err.name === "AbortError";
    // On timeout the dispatch MAY still have landed, so the cooldown is
    // deliberately NOT refunded: a duplicate scan costs more than a 5-minute
    // wait. A clean network failure dispatched nothing — refund.
    if (!aborted && refund) await refund();
    return json(503, {
      ok: false,
      action: aborted ? "dispatch_timeout" : "dispatch_error",
      error: aborted
        ? "GitHub took too long to respond — the scan may still have started."
        : "Network error reaching GitHub.",
      ...base,
    });
  } finally {
    clearTimeout(timer);
  }
}

/* HEAD must answer, not 404 — found live 2026-08-07.
 *
 * Cloudflare Pages routes a method with no matching handler onward to the
 * STATIC assets, and there is no file at /api/heartbeat, so an unhandled HEAD
 * returns 404 — the handler above never executes at all. UptimeRobot's current
 * dashboard defaults NEW http monitors to HEAD (the older /api/health monitor
 * predates that default and sends GET, which is why one worked and one did
 * not). So the first armed heartbeat monitor spent its entire life reporting
 * DOWN against a perfectly healthy endpoint while the healer ran zero times:
 * a self-heal loop that looked armed on both dashboards and was not connected
 * at either end. A monitor is worth exactly what its probe reaches.
 *
 * Same handler, same status code, same side effects — the runtime drops the
 * body for HEAD, which is all a prober reads anyway. Deliberately NOT
 * `onRequest`: this endpoint dispatches a workflow, and POST/PUT/DELETE have
 * no business doing that.
 */
export const onRequestHead = onRequestGet;

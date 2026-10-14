/* Cloudflare Pages Function — POST /api/scan
 *
 * Triggers a fresh cloud scan by dispatching the GitHub Actions "Scheduled scan"
 * workflow (which scans every market, commits the data, and redeploys the site).
 *
 * The GitHub token NEVER reaches the browser — it lives only here as a Pages
 * environment variable. One-time setup (see below) is required before the button
 * works; until then this returns a friendly "not configured" message and the UI
 * falls back to just reloading the latest data.
 *
 * One-time setup (guided):
 *   1. GitHub → Settings → Developer settings → Fine-grained personal access
 *      tokens → Generate new token. Scope it to the repo
 *      FakeCurrency/googy-boys-scanner with Repository permission
 *      "Actions: Read and write". Copy the token.
 *   2. Cloudflare Pages → your project → Settings → Environment variables → add
 *        GH_DISPATCH_TOKEN = <the token>
 *      (optionally GH_REPO and GH_WORKFLOW to override the defaults below).
 *   3. Redeploy. The SCAN button now kicks off a fresh scan.
 *
 * Access-logged (2026-08-20): every dispatch's envelope goes to KV via
 * _access_log.js — best-effort, never blocks the dispatch. See that file.
 *
 * Request (2026-10-14, REFINE200 #52/#54): POST, Content-Type application/json,
 * same-origin (see _same_origin.js), body {"market": "asx|nasdaq|crypto|all"}.
 * A missing, unparseable or unknown market is a 400. It used to fall back to a
 * FULL scan, so the cheapest junk POST bought the most expensive run.
 */
import { withAccessLog } from "./_access_log.js";
import { dispatchWorkflow } from "./_dispatch.js";
import { crossSiteRefusal } from "./_same_origin.js";
import { cleanSecret } from "./_secrets.js";

const MARKETS = ["asx", "nasdaq", "crypto", "all"];
const DAILY_CAP = 40;          // manual scans per UTC day, all markets together

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

export const onRequestPost = withAccessLog("/api/scan", async ({ env, request }) => {
  const token = cleanSecret(env.GH_DISPATCH_TOKEN);
  const repo = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const workflow = env.GH_WORKFLOW || "scan.yml";
  const ref = env.GH_REF || "main";

  const refused = crossSiteRefusal(request);
  if (refused) return json(refused.status, { ok: false, message: refused.message });

  // Per-market scan: the dashboard sends the market it's currently showing so a
  // single tab (e.g. ASX) refreshes fast, without re-scanning everything.
  let body;
  try { body = await request.json(); } catch (_) { body = null; }
  const market = typeof body?.market === "string" ? body.market.trim().toLowerCase() : "";
  if (!MARKETS.includes(market)) {
    return json(400, { ok: false, message: `Name the market to scan: {"market": "${MARKETS.join("|")}"}.` });
  }

  if (!token) {
    return json(503, {
      ok: false,
      configured: false,
      message:
        "Scan button not set up yet — add a GH_DISPATCH_TOKEN env var in Cloudflare (see functions/api/scan.js).",
    });
  }

  // Abuse guard (2026-07-09): the site is public and every call here burns a
  // GitHub Actions run. KV-backed cooldown — one dispatch per market per
  // 5 minutes, and a hard daily cap across all markets. Degrades to
  // no-limiting if the KV binding is absent, so a misconfig can't brick the
  // button. (Reuses the JOURNAL_KV namespace, which now backs only these rate limits
  // and the access log — the journal sync store it was named for is gone.)
  //
  // The cooldown/counter are written BEFORE the GitHub call (closing the
  // double-click race) and REFUNDED if the dispatch fails (2026-07-29). They
  // used to stick on failure, so an expired token meant: 502 to the user, no
  // run dispatched — and then five minutes of 429 "it's still running" about a
  // scan that never existed, plus a burned daily slot per attempt. The refund
  // has the same non-atomicity the increment does (a concurrent success could
  // land between write and refund); rare-path, accepted for an abuse guard.
  //
  // FAILS CLOSED on a KV error (REFINE200 #158, 2026-10-14). It used to let the
  // request through, and Cloudflare refuses every KV write once the free daily
  // quota (1,000) is spent -- which junk POSTs can spend -- so the cooldown and
  // the daily cap both switched off for the rest of the UTC day (measured: ten
  // back-to-back POSTs, ten dispatched runs). A limiter that cannot record
  // cannot limit. An ABSENT binding still means no limiting (a config choice,
  // not something a caller can cause), and /api/heartbeat keeps failing open
  // because its own staleness test bounds it.
  let refundGuard = null;
  if (env.JOURNAL_KV) {
    const cdKey = `ratelimit:scan:${market}`;
    const dayKey = `ratelimit:scan:day:${new Date().toISOString().slice(0, 10)}`;
    let used = 0;
    let wroteCooldown = false;
    try {
      if (await env.JOURNAL_KV.get(cdKey)) {
        return json(429, {
          ok: false, configured: true,
          message: "A scan for this market was requested in the last 5 minutes — it's still running. The data refreshes automatically when it lands.",
        });
      }
      used = parseInt((await env.JOURNAL_KV.get(dayKey)) || "0", 10);
      if (used >= DAILY_CAP) {
        return json(429, {
          ok: false, configured: true,
          message: "Daily manual-scan limit reached — the scheduled scans keep running as normal.",
        });
      }
      await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 300 });
      wroteCooldown = true;
      await env.JOURNAL_KV.put(dayKey, String(used + 1), { expirationTtl: 172800 });
    } catch (_) {
      if (wroteCooldown) {
        try { await env.JOURNAL_KV.delete(cdKey); } catch (_) { /* best-effort */ }
      }
      return json(503, {
        ok: false, configured: true,
        message: "The scan rate limiter is unavailable (Cloudflare KV refused a read or write), so no scan was started. The scheduled scans keep running.",
      });
    }
    refundGuard = async () => {
      try {
        await env.JOURNAL_KV.delete(cdKey);
        await env.JOURNAL_KV.put(dayKey, String(used), { expirationTtl: 172800 });
      } catch (_) { /* refund is best-effort */ }
    };
  }

  // Transport + the cooldown refund rule live in _dispatch.js; the wording below
  // is this endpoint's own (it answers the deck's SCAN button).
  const r = await dispatchWorkflow({ token, repo, workflow, ref, inputs: { market }, refund: refundGuard });

  if (r.ok) {
    const scope = market === "all" ? "Full scan" : `${market.toUpperCase()} scan`;
    const eta = market === "all" ? "~6–10 minutes" : "~2–4 minutes";
    return json(202, {
      ok: true,
      configured: true,
      market,
      message: `${scope} started — fresh data in ${eta}.`,
    });
  }

  if (r.status) {
    // Map the common GitHub failure modes to a clear, actionable message.
    // Never echo the upstream body — it can carry token/repo details.
    const friendly = {
      401: "Scan token is invalid or expired — regenerate GH_DISPATCH_TOKEN in Cloudflare.",
      403: "Scan token lacks permission (needs Actions: Read and write) or GitHub is rate-limiting.",
      404: `Workflow "${workflow}" or repo not found — check GH_WORKFLOW / GH_REPO.`,
      422: `GitHub couldn't dispatch on ref "${ref}" — check the branch exists and the workflow has workflow_dispatch.`,
      429: "GitHub is rate-limiting scan requests — wait a minute and try again.",
    }[r.status] || `GitHub rejected the request (${r.status}).`;

    return json(502, { ok: false, configured: true, status: r.status, message: friendly });
  }

  return json(r.aborted ? 504 : 502, {
    ok: false,
    configured: true,
    message: r.aborted
      ? "GitHub took too long to respond — the scan may still start; check back shortly."
      : "Network error reaching GitHub.",
  });
});

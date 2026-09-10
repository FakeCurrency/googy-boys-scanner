/* Cloudflare Pages Function — GET|POST /api/morning_plays?slot=asx|us
 *
 * THE EXTERNAL TRIGGER for the Discord plays digest (2026-09-10). GitHub's
 * free-tier cron is unreliable for hitting a minute: it ran the ASX slot 2-5
 * HOURS late on 2026-09-09 and had not fired at all by 19:19 Melbourne on
 * 2026-09-10 (the owner's "where the fuck did my ASX post-market scan go").
 * The in-repo fix (morning_plays.yml + slot_due) makes a late cron still
 * deliver, but nothing in-repo can make GitHub fire on time. This endpoint
 * lets an EXTERNAL scheduler that keeps real time (cron-job.org, UptimeRobot,
 * a Cloudflare cron Worker) kick the workflow at the exact Melbourne minute.
 *
 * It dispatches morning_plays.yml with the `slot` input, which runs the real
 * --slot path: at/past-target check + the per-day marker + 7-day ticker
 * dedup, and it WRITES state. So calling this early is a harmless no-op,
 * calling it twice is a harmless no-op, and GitHub's own late cron becomes a
 * no-op once this has delivered — no duplicate for the reader. Schedule the
 * pinger a few minutes AFTER the target (16:35 / 06:35 Melbourne), never
 * before, because before-target is a no-op and the day would then wait on
 * GitHub's cron.
 *
 * The GitHub token is the EXISTING GH_DISPATCH_TOKEN (it already dispatches
 * scan.yml from /api/scan) — it never leaves Cloudflare and never has to be
 * pasted into a third-party pinger. What the pinger carries instead is
 * MORNING_PLAYS_TRIGGER_SECRET, a value the owner invents and sets in BOTH
 * halves (Cloudflare Pages env var + the pinger's request), the tick.js
 * "set both halves in one sitting" pattern.
 *
 * FAIL CLOSED, tick.js-style: no MORNING_PLAYS_TRIGGER_SECRET → 503 (a setup
 * gap, never an open trigger); wrong/missing key → 401. Accepts the key as
 * `?key=` or `Authorization: Bearer` so any pinger can send it. A KV cooldown
 * (one dispatch per slot per 5 min, refunded on a definite failure, kept on a
 * timeout — scan.js's rule) bounds Actions-run spam if the secret ever leaks.
 *
 * Owner setup:
 *   1. Cloudflare Pages → googy-boys-scanner → Settings → Environment variables
 *        MORNING_PLAYS_TRIGGER_SECRET = <any long random string you make up>
 *      (GH_DISPATCH_TOKEN is already there.)
 *   2. In a free pinger (cron-job.org), two jobs, timezone Australia/Melbourne:
 *        16:35 daily → https://googy-boys-scanner.pages.dev/api/morning_plays?slot=asx&key=<that string>
 *        06:35 daily → https://googy-boys-scanner.pages.dev/api/morning_plays?slot=us&key=<that string>
 */

const VALID_SLOTS = ["asx", "us"];

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

function authorised(request, env) {
  const url = new URL(request.url);
  const fromQuery = url.searchParams.get("key");
  const header = request.headers.get("Authorization") || "";
  const fromHeader = header.startsWith("Bearer ") ? header.slice(7) : "";
  return fromQuery === env.MORNING_PLAYS_TRIGGER_SECRET
    || fromHeader === env.MORNING_PLAYS_TRIGGER_SECRET;
}

async function slotOf(request) {
  const url = new URL(request.url);
  let slot = String(url.searchParams.get("slot") || "").toLowerCase();
  if (!slot && request.method === "POST") {
    try {
      const body = await request.json();
      slot = String((body && body.slot) || "").toLowerCase();
    } catch (_) { /* no/invalid body → fall through to the 400 */ }
  }
  return slot;
}

export const onRequest = async ({ request, env }) => {
  if (request.method !== "GET" && request.method !== "POST") {
    return json(405, { ok: false, message: "Use GET or POST." });
  }
  // Fail closed: an unset secret disables the trigger instead of opening it.
  if (!env.MORNING_PLAYS_TRIGGER_SECRET) {
    return json(503, {
      ok: false, configured: false,
      message: "MORNING_PLAYS_TRIGGER_SECRET not configured — trigger disabled. "
        + "Set it in Cloudflare Pages env vars (see functions/api/morning_plays.js).",
    });
  }
  if (!authorised(request, env)) return json(401, { ok: false, message: "Unauthorized." });

  const slot = await slotOf(request);
  if (!VALID_SLOTS.includes(slot)) {
    return json(400, { ok: false, message: `slot must be one of ${VALID_SLOTS.join("|")}.` });
  }

  const token = env.GH_DISPATCH_TOKEN;
  if (!token) {
    return json(503, {
      ok: false, configured: false,
      message: "GH_DISPATCH_TOKEN not configured in Cloudflare — cannot dispatch (see functions/api/scan.js).",
    });
  }
  const repo = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const workflow = env.MORNING_PLAYS_WORKFLOW || "morning_plays.yml";
  const ref = env.GH_REF || "main";

  // Abuse guard (scan.js pattern): one dispatch per slot per 5 minutes. The
  // workflow's own per-day marker already makes a repeat a no-op; this just
  // bounds burned Actions runs. Written BEFORE the dispatch (closes the
  // double-fire race), refunded on a definite failure, kept on a timeout.
  let refundGuard = null;
  if (env.JOURNAL_KV) {
    try {
      const cdKey = `ratelimit:morning_plays:${slot}`;
      if (await env.JOURNAL_KV.get(cdKey)) {
        return json(429, { ok: false, configured: true, slot,
          message: "This slot was triggered in the last 5 minutes — it's already running." });
      }
      await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 300 });
      refundGuard = async () => {
        try { await env.JOURNAL_KV.delete(cdKey); } catch (_) { /* best-effort */ }
      };
    } catch (_) { /* KV hiccup → let the request through */ }
  }

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
      body: JSON.stringify({ ref, inputs: { slot } }),
      signal: ctrl.signal,
    });

    if (res.status === 204) {
      return json(202, { ok: true, configured: true, slot,
        message: `${slot.toUpperCase()} slot dispatched — it posts if the slot is due and has not gone out today.` });
    }
    // Never echo the upstream body — it can carry token/repo details.
    const friendly = {
      401: "GH_DISPATCH_TOKEN is invalid or expired — regenerate it in Cloudflare.",
      403: "GH_DISPATCH_TOKEN lacks permission (needs Actions: Read and write) or GitHub is rate-limiting.",
      404: `Workflow "${workflow}" or repo not found.`,
      422: `GitHub couldn't dispatch on ref "${ref}" — check the workflow has workflow_dispatch with a slot input.`,
      429: "GitHub is rate-limiting — try again in a minute.",
    }[res.status] || `GitHub rejected the request (${res.status}).`;
    if (refundGuard) await refundGuard();   // nothing was dispatched — free the retry
    return json(502, { ok: false, configured: true, slot, status: res.status, message: friendly });
  } catch (err) {
    const aborted = err && err.name === "AbortError";
    // A timeout MAY have landed server-side: keep the cooldown (a duplicate run
    // costs more than a 5-minute wait). A clean network failure sent nothing.
    if (!aborted && refundGuard) await refundGuard();
    return json(aborted ? 504 : 502, { ok: false, configured: true, slot,
      message: aborted ? "GitHub took too long — the dispatch may still start." : "Network error reaching GitHub." });
  } finally {
    clearTimeout(timer);
  }
};

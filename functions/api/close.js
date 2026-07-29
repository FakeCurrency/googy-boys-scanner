/* Cloudflare Pages Function — POST /api/close
 *
 * Receives a manual position-close request from the journal UI and dispatches
 * the GitHub Actions "close_position" workflow to record it in the journal JSON,
 * commit, and let Cloudflare Pages redeploy.
 *
 * Requires the same GH_DISPATCH_TOKEN used by /api/scan (Actions: read+write).
 *
 * Request body (JSON):
 *   { symbol, direction, market, price, exit_date, journal_type }
 */
export const onRequestPost = async ({ request, env }) => {
  const token = env.GH_DISPATCH_TOKEN;
  const repo  = env.GH_REPO     || "FakeCurrency/googy-boys-scanner";
  const ref   = env.GH_REF      || "main";

  const json = (status, body) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  if (!token) {
    return json(503, {
      ok: false,
      message: "GH_DISPATCH_TOKEN not configured — add it to Cloudflare Pages env vars.",
    });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json(400, { ok: false, message: "Invalid JSON body." });
  }

  // Strict validation: these inputs reach a GitHub Actions workflow, so only
  // known-shape values may pass (defence in depth with the env-var quoting in
  // close_position.yml).
  const symbol = String(body?.symbol || "").trim().toUpperCase();
  const market = String(body?.market || "").trim().toLowerCase();
  const price  = parseFloat(body?.price);
  if (!/^[A-Z0-9.\-]{1,15}$/.test(symbol) || !isFinite(price) || price <= 0) {
    return json(400, { ok: false, message: "symbol and a positive price are required." });
  }
  if (!["asx", "nasdaq", "crypto", "scalp", ""].includes(market)) {
    return json(400, { ok: false, message: "Invalid market." });
  }

  // journal_type "bot" (2026-07-20, review C4) routes to the REAL bot-book
  // close in the workflow; a bot close requires a concrete market.
  const journalType = body.journal_type === "scalp" ? "scalp"
    : body.journal_type === "bot" ? "bot" : "swing";
  if (journalType === "bot" && !["asx", "nasdaq", "crypto"].includes(market)) {
    return json(400, { ok: false, message: "A bot close needs market asx|nasdaq|crypto." });
  }

  const inputs = {
    symbol,
    direction:    body.direction === "short" ? "short" : "long",
    market,
    price:        String(price),
    exit_date:    /^\d{4}-\d{2}-\d{2}$/.test(body.exit_date) ? body.exit_date : "",
    journal_type: journalType,
  };

  // Abuse guard (2026-07-09): public endpoint, each call burns an Actions run.
  // One close per symbol per minute + daily cap. No KV binding → no limiting.
  // Written before the dispatch (closes the double-click race), REFUNDED if the
  // dispatch fails (2026-07-29) — a failed dispatch used to leave a minute of
  // "give it a minute to process" about a close that never existed, and burned
  // a daily slot. Same non-atomicity as the increment; rare-path, accepted.
  let refundGuard = null;
  if (env.JOURNAL_KV) {
    try {
      const cdKey = `ratelimit:close:${inputs.symbol}`;
      if (await env.JOURNAL_KV.get(cdKey)) {
        return json(429, { ok: false, message: "A close for this symbol was just requested — give it a minute to process." });
      }
      const dayKey = `ratelimit:close:day:${new Date().toISOString().slice(0, 10)}`;
      const used = parseInt((await env.JOURNAL_KV.get(dayKey)) || "0", 10);
      if (used >= 60) {
        return json(429, { ok: false, message: "Daily close-request limit reached." });
      }
      await env.JOURNAL_KV.put(cdKey, "1", { expirationTtl: 60 });
      await env.JOURNAL_KV.put(dayKey, String(used + 1), { expirationTtl: 172800 });
      refundGuard = async () => {
        try {
          await env.JOURNAL_KV.delete(cdKey);
          await env.JOURNAL_KV.put(dayKey, String(used), { expirationTtl: 172800 });
        } catch (_) { /* refund is best-effort */ }
      };
    } catch (_) { /* KV hiccup → let it through */ }
  }

  const url  = `https://api.github.com/repos/${repo}/actions/workflows/close_position.yml/dispatches`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 10_000);

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization:          `Bearer ${token}`,
        Accept:                 "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent":           "vivek-beta-scanner",
        "Content-Type":         "application/json",
      },
      body: JSON.stringify({ ref, inputs }),
      signal: ctrl.signal,
    });

    if (res.status === 204) {
      return json(202, {
        ok: true,
        message: `${inputs.symbol} ${inputs.direction} close queued — journal updates in ~1 minute.`,
      });
    }

    // Never echo the upstream body — it can carry token/repo details.
    if (refundGuard) await refundGuard();   // nothing was dispatched — free the retry
    return json(502, { ok: false, message: `GitHub rejected the request (${res.status}).` });
  } catch (err) {
    const aborted = err?.name === "AbortError";
    // Timeout: the dispatch MAY have landed — keep the cooldown (a duplicate
    // close-run costs more than a one-minute wait). Clean failure: refund.
    if (!aborted && refundGuard) await refundGuard();
    return json(aborted ? 504 : 502, {
      ok: false,
      message: aborted ? "GitHub took too long — try again." : "Network error reaching GitHub.",
    });
  } finally {
    clearTimeout(timer);
  }
};

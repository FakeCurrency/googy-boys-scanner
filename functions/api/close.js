/* Cloudflare Pages Function — POST /api/close
 *
 * Receives a manual position-close request from the journal UI and dispatches
 * the GitHub Actions "close_position" workflow to record it in the journal JSON,
 * commit, and let Cloudflare Pages redeploy.
 *
 * Requires the same GH_DISPATCH_TOKEN used by /api/scan (Actions: read+write).
 *
 * Request body (JSON) — two shapes:
 *   { symbol, direction, market, price, exit_date, journal_type }     — one close
 *   { journal_type: "bot", closes: [{symbol, market, direction, price}, ...] }
 *
 * The `closes` array (2026-08-13) is the BATCH shape: N bot-book closes in ONE
 * workflow run. Born from the stalled strip's real use — nine closes as nine
 * serial runs is ~half an hour behind the scan mutex; as one batch it is one
 * dispatch, one commit, one deploy, ~2 minutes for the lot. Batch is bot-book
 * only (the legacy swing/scalp journals have no batch path and never will).
 *
 * Access-logged (2026-08-20): every call's envelope goes to KV via
 * _access_log.js — best-effort, never blocks the close. See that file.
 */
import { withAccessLog } from "./_access_log.js";
export const onRequestPost = withAccessLog("/api/close", async ({ request, env }) => {
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

  // ---- BATCH shape -----------------------------------------------------------
  // Validated entry-by-entry with the SAME rules as a single close, and then
  // RE-SERIALISED from the validated fields only — the raw client JSON never
  // reaches the workflow input, so nothing unvalidated can ride along in it.
  if (Array.isArray(body?.closes)) {
    if (body.journal_type !== "bot") {
      return json(400, { ok: false, message: "Batch close is bot-book only." });
    }
    if (body.closes.length < 1 || body.closes.length > 30) {
      return json(400, { ok: false, message: "Batch must contain 1-30 closes." });
    }
    const entries = [];
    const seen = new Set();
    for (const c of body.closes) {
      const sym = String(c?.symbol || "").trim().toUpperCase();
      const mkt = String(c?.market || "").trim().toLowerCase();
      const px  = parseFloat(c?.price);
      if (!/^[A-Z0-9.\-]{1,15}$/.test(sym) || !isFinite(px) || px <= 0) {
        return json(400, { ok: false, message: `Batch entry ${sym || "?"}: symbol and a positive price are required.` });
      }
      if (!["asx", "nasdaq", "crypto"].includes(mkt)) {
        return json(400, { ok: false, message: `Batch entry ${sym}: market must be asx|nasdaq|crypto.` });
      }
      const key = mkt + ":" + sym;
      if (seen.has(key)) {
        return json(400, { ok: false, message: `Batch lists ${sym} twice.` });
      }
      seen.add(key);
      entries.push({
        symbol: sym,
        market: mkt,
        direction: c?.direction === "short" ? "short" : "long",
        price: String(px),
      });
    }
    return dispatchClose(env, json, {
      // The single-close inputs are required by the workflow and display-only
      // here: the roster makes the Actions list legible at a glance.
      symbol: entries[0].symbol + (entries.length > 1 ? `+${entries.length - 1}` : ""),
      direction: "long",
      market: entries[0].market,
      price: entries[0].price,
      exit_date: "",
      journal_type: "bot",
      batch: JSON.stringify(entries),
    }, `ratelimit:close:batch`, entries.length);
  }

  // ---- single-close shape (unchanged) ---------------------------------------
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

  return dispatchClose(env, json, inputs, `ratelimit:close:${inputs.symbol}`, 1);
});

// One dispatch path for both shapes (the single/batch split above is pure
// validation). Guard rules unchanged from the 2026-07-09/07-29 design:
// cooldown written BEFORE the dispatch (closes the double-click race),
// refunded if the dispatch fails, kept on a timeout (the dispatch MAY have
// landed, and a duplicate close-run costs more than a one-minute wait).
// A batch counts ONCE against the daily cap — the cap protects Actions runs,
// and a batch is one run regardless of how many closes ride in it.
async function dispatchClose(env, json, inputs, cdKey, nCloses) {
  const token = env.GH_DISPATCH_TOKEN;
  const repo  = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const ref   = env.GH_REF  || "main";

  let refundGuard = null;
  if (env.JOURNAL_KV) {
    try {
      if (await env.JOURNAL_KV.get(cdKey)) {
        return json(429, { ok: false, message: nCloses > 1
          ? "A batch close was just requested — give it a minute to process."
          : "A close for this symbol was just requested — give it a minute to process." });
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
        "User-Agent":           "googy-boys-scanner",
        "Content-Type":         "application/json",
      },
      body: JSON.stringify({ ref, inputs }),
      signal: ctrl.signal,
    });

    if (res.status === 204) {
      return json(202, {
        ok: true,
        message: nCloses > 1
          ? `${nCloses} closes queued as ONE run — the strip confirms each against the book.`
          : `${inputs.symbol} ${inputs.direction} close queued — journal updates in ~1 minute.`,
      });
    }

    // Never echo the upstream body — it can carry token/repo details. But DO
    // say something actionable: this endpoint's input is a deliberate human
    // act on the track record, and it used to give the least useful error of
    // the three dispatch endpoints (flagged in the 2026-08-07 audit).
    const friendly = {
      401: "Dispatch token invalid or expired — regenerate GH_DISPATCH_TOKEN in Cloudflare.",
      403: "Dispatch token lacks permission (needs Actions: Read and write), or GitHub is rate-limiting.",
      404: "close_position.yml or the repo was not found — check GH_REPO.",
      422: "GitHub could not dispatch on this ref — check the branch and workflow inputs.",
      429: "GitHub is rate-limiting dispatches — wait a minute and retry.",
    }[res.status] || `GitHub rejected the request (${res.status}).`;

    if (refundGuard) await refundGuard();   // nothing was dispatched — free the retry
    return json(502, { ok: false, message: friendly });
  } catch (err) {
    const aborted = err?.name === "AbortError";
    if (!aborted && refundGuard) await refundGuard();
    return json(aborted ? 504 : 502, {
      ok: false,
      message: aborted ? "GitHub took too long — try again." : "Network error reaching GitHub.",
    });
  } finally {
    clearTimeout(timer);
  }
}

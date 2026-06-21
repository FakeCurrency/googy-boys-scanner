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

  const price = parseFloat(body?.price);
  if (!body?.symbol || !isFinite(price) || price <= 0) {
    return json(400, { ok: false, message: "symbol and a positive price are required." });
  }

  const inputs = {
    symbol:       String(body.symbol).slice(0, 20),
    direction:    body.direction === "short" ? "short" : "long",
    market:       String(body.market || "").slice(0, 20),
    price:        String(price),
    exit_date:    /^\d{4}-\d{2}-\d{2}$/.test(body.exit_date) ? body.exit_date : "",
    journal_type: body.journal_type === "scalp" ? "scalp" : "swing",
  };

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

    const detail = (await res.text().catch(() => "")).slice(0, 200);
    return json(502, { ok: false, message: `GitHub error ${res.status}: ${detail}` });
  } catch (err) {
    const aborted = err?.name === "AbortError";
    return json(aborted ? 504 : 502, {
      ok: false,
      message: aborted ? "GitHub took too long — try again." : `Network error: ${err}`,
    });
  } finally {
    clearTimeout(timer);
  }
};

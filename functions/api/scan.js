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
 */
export const onRequestPost = async ({ env, request }) => {
  const token = env.GH_DISPATCH_TOKEN;
  const repo = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const workflow = env.GH_WORKFLOW || "scan.yml";
  const ref = env.GH_REF || "main";

  // Per-market scan: the dashboard sends the market it's currently showing so a
  // single tab (e.g. ASX) refreshes fast, without re-scanning everything.
  let market = "all";
  try {
    const body = await request.json();
    const m = String((body && body.market) || "").toLowerCase();
    if (["asx", "nasdaq", "crypto", "all"].includes(m)) market = m;
  } catch (_) { /* no/invalid body → full scan */ }

  const json = (status, body) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  if (!token) {
    return json(503, {
      ok: false,
      configured: false,
      message:
        "Scan button not set up yet — add a GH_DISPATCH_TOKEN env var in Cloudflare (see functions/api/scan.js).",
    });
  }

  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

  // Abort if GitHub is slow so the browser never hangs on this request.
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
      const scope = market === "all" ? "Full scan" : `${market.toUpperCase()} scan`;
      const eta = market === "all" ? "~6–10 minutes" : "~2–4 minutes";
      return json(202, {
        ok: true,
        configured: true,
        market,
        message: `${scope} started — fresh data in ${eta}.`,
      });
    }

    // Map the common GitHub failure modes to a clear, actionable message.
    const detail = (await res.text().catch(() => "")).slice(0, 200);
    const friendly = {
      401: "Scan token is invalid or expired — regenerate GH_DISPATCH_TOKEN in Cloudflare.",
      403: "Scan token lacks permission (needs Actions: Read and write) or GitHub is rate-limiting.",
      404: `Workflow "${workflow}" or repo not found — check GH_WORKFLOW / GH_REPO.`,
      422: `GitHub couldn't dispatch on ref "${ref}" — check the branch exists and the workflow has workflow_dispatch.`,
      429: "GitHub is rate-limiting scan requests — wait a minute and try again.",
    }[res.status] || `GitHub rejected the request (${res.status}). ${detail}`;

    return json(502, { ok: false, configured: true, status: res.status, message: friendly });
  } catch (err) {
    const aborted = err && err.name === "AbortError";
    return json(aborted ? 504 : 502, {
      ok: false,
      configured: true,
      message: aborted
        ? "GitHub took too long to respond — the scan may still start; check back shortly."
        : `Network error reaching GitHub: ${err}`,
    });
  } finally {
    clearTimeout(timer);
  }
};

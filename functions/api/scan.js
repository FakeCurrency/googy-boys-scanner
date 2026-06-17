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
export const onRequestPost = async ({ env }) => {
  const token = env.GH_DISPATCH_TOKEN;
  const repo = env.GH_REPO || "FakeCurrency/googy-boys-scanner";
  const workflow = env.GH_WORKFLOW || "scan.yml";
  const ref = env.GH_REF || "main";

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
      body: JSON.stringify({ ref }),
    });

    if (res.status === 204) {
      return json(202, {
        ok: true,
        configured: true,
        message: "Scan started — fresh data in ~6–10 minutes.",
      });
    }
    const detail = await res.text();
    return json(502, {
      ok: false,
      configured: true,
      message: `GitHub rejected the request (${res.status}). ${detail.slice(0, 200)}`,
    });
  } catch (err) {
    return json(502, { ok: false, configured: true, message: `Network error: ${err}` });
  }
};

/* Cloudflare Pages — site-wide password (HTTP Basic Auth).
 *
 * Runs at Cloudflare's edge in front of every request (pages AND data files),
 * so nothing is served until the password is entered. The password lives only
 * here on the server, never in anything sent to the browser.
 *
 * Default username: "googy"   password: "120291"
 * To change without editing code, set Pages env vars SITE_USER / SITE_PASSWORD.
 */
export const onRequest = async ({ request, next, env }) => {
  const USER = env.SITE_USER || "googy";
  const PASS = env.SITE_PASSWORD || "120291";

  const header = request.headers.get("Authorization") || "";
  if (header.startsWith("Basic ")) {
    try {
      const [user, pass] = atob(header.slice(6)).split(":");
      if (user === USER && pass === PASS) return next();
    } catch (_) { /* fall through to prompt */ }
  }
  return new Response("Authentication required.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Googy Boys Scanner"' },
  });
};

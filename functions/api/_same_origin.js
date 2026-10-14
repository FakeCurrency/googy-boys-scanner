/* Cross-site refusal for the two browser-driven dispatch endpoints, POST
 * /api/close and POST /api/scan (REFINE200 #52, 2026-10-14).
 *
 * Both are called from the site's own pages (the deck's SCAN button, the
 * journal's close-all and the stalled strip), and both used to accept any POST
 * from anywhere: a page on another site could submit a form at them and spend
 * a GitHub Actions run, or close bot-book positions, using the visitor's
 * browser. Cloudflare Access is the real fix and is the owner's to switch on
 * (REFINE200 #55); this is the part code can do.
 *
 * Two independent checks, either of which stops a cross-site browser request:
 *
 *   1. Content-Type must be application/json. An HTML form can only send
 *      urlencoded, multipart or text/plain, and a cross-origin fetch() that
 *      sends JSON triggers a CORS preflight these endpoints never approve.
 *      Every caller on the site already sends this header.
 *   2. The browser's own provenance headers must not say cross-site:
 *      Sec-Fetch-Site, when present, must be "same-origin" (or "none", a
 *      user-typed navigation), and Origin, when present, must name this host.
 *      A same-site sibling (a preview deployment on another pages.dev
 *      subdomain) is refused too.
 *
 * A request carrying NEITHER provenance header is not from a browser (every
 * current browser sends Origin on a POST), so it cannot be a cross-site forgery
 * and is let through to the endpoint's own rate limits. Forging these headers
 * is trivial for a non-browser client, which is why they protect only against
 * CSRF and why Cloudflare Access is still the item that matters.
 *
 * Returns null when the request may proceed, else { status, message } for the
 * caller to wrap in its own JSON shape (each endpoint answers a different UI).
 */

export function crossSiteRefusal(request) {
  const type = (request.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
  if (type !== "application/json") {
    return { status: 415, message: "Send the request as JSON (Content-Type: application/json)." };
  }
  const site = (request.headers.get("Sec-Fetch-Site") || "").trim().toLowerCase();
  if (site && site !== "same-origin" && site !== "none") {
    return { status: 403, message: "Cross-site request refused." };
  }
  const origin = request.headers.get("Origin");
  if (origin != null) {
    let host = null;
    try { host = new URL(origin).host; } catch (_) { /* "null" (sandboxed frame) or junk */ }
    if (!host || host !== new URL(request.url).host) {
      return { status: 403, message: "Cross-site request refused." };
    }
  }
  return null;
}

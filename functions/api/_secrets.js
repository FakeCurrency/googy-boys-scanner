/* Secret hygiene for the Pages Functions (REFINE200 #164, 2026-10-14).
 *
 * The Python side learned this on 2026-08-01 (scanner/config.py clean_secret):
 * a value pasted into a settings box can carry an invisible byte-order mark, a
 * zero-width character or a trailing newline. No Function trimmed anything, and
 * in the Workers runtime the symptoms are worse than a plain failure because
 * they name the wrong cause:
 *
 *   - GH_DISPATCH_TOKEN with a leading U+FEFF: `Bearer ${token}` is not a valid
 *     header value, Headers throws, and _dispatch.js reads the throw as a
 *     network failure -- so /api/scan answered "Network error reaching GitHub"
 *     and /api/heartbeat "dispatch_error" about a token that was simply pasted
 *     with a BOM.
 *   - MORNING_PLAYS_TRIGGER_SECRET with a trailing newline: the === compare
 *     fails and every rung of the cron-job.org digest ladder answers 401.
 *
 * Every Cloudflare secret is therefore read through cleanSecret() AT THE READ
 * SITE (a test pins that no endpoint reads one raw). The trim set is
 * config.clean_secret's character for character, and a test pins that parity
 * too. Ends only: an interior character is never touched, and a value that is
 * nothing but whitespace comes back "" -- i.e. unset, which is how every caller
 * already treats a missing secret.
 *
 * Helpers only: no request handler, so this file is never a routable endpoint.
 */

export const SECRET_TRIM = " \t\r\n\ufeff\u200b\u200c\u200d\u200e\u200f";

export function cleanSecret(value) {
  const s = String(value || "");
  let a = 0;
  let b = s.length;
  while (a < b && SECRET_TRIM.includes(s[a])) a++;
  while (b > a && SECRET_TRIM.includes(s[b - 1])) b--;
  return s.slice(a, b);
}

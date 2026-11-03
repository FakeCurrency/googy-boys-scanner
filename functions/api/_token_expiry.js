/* GH_DISPATCH_TOKEN's expiry date, remembered (NEXT100 #12, 2026-11-03).
 *
 * One token starts almost every scan (875 of 926 scans since 6 Oct came from
 * the cron-job.org heals through /api/heartbeat), both morning-plays ladders
 * (/api/morning_plays), the SCAN button (/api/scan) and the emergency close
 * (/api/close) -- and its expiry date was written nowhere. The first sign of a
 * lapsed token would have been every one of them answering 401 at once.
 *
 * GitHub states the date on every response to a request made with an expiring
 * token, in the `github-authentication-token-expiration` header (for example
 * "2027-01-31 00:00:00 UTC"). _dispatch.js hands each dispatch's response
 * headers to noteTokenExpiry(), which keeps the date under ONE KV key;
 * /api/health reads it back with tokenExpiryOf() (KV only, never GitHub) and
 * the status lamp turns amber inside health.js's TOKEN_WARN_DAYS.
 *
 * KV WRITE BUDGET: read first, write only when the date CHANGES (a new token),
 * so a steady token costs one KV read per dispatch and no writes. An ACCEPTED
 * dispatch (204) that carries no header means the token in use does not expire
 * at all, so a stored date is dropped rather than left behind to warn about a
 * token that has been replaced. A header that is present but unreadable, or
 * absent on a refused dispatch, proves nothing and changes nothing.
 *
 * NEVER IN THE WAY: every KV error is swallowed and nothing here throws, so the
 * bookkeeping can never block a dispatch, turn one that landed into the
 * network-error path (which refunds the cooldown), or change an answer. The
 * token itself never reaches this file -- only the response headers do -- and
 * nothing here logs.
 *
 * Helpers only: no request handler, so this file is never a routable endpoint.
 * No imports, so the test harnesses can prepend it as plain script.
 */

export const TOKEN_EXPIRY_HEADER = "github-authentication-token-expiration";
export const TOKEN_EXPIRY_KEY = "gh_token_expiry";

// "2027-01-31 00:00:00 UTC", "2027-01-31T00:00:00Z", "2027-01-31 00:00:00 +0000",
// "2027-01-31 10:00:00 +10:00", "2027-01-31". No zone = UTC (GitHub's own).
const EXPIRY_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(UTC|GMT|Z|[+-]\d{2}:?\d{2})?$/i;

/* The expiry as an ISO 8601 UTC instant ("2027-01-31T00:00:00Z"), or null for
 * anything that is not a real calendar date and time. */
export function parseTokenExpiry(raw) {
  const m = EXPIRY_RE.exec(String(raw == null ? "" : raw).trim());
  if (!m) return null;
  const n = (i) => Number(m[i] || 0);
  const [y, mo, d, h, mi, s] = [n(1), n(2), n(3), n(4), n(5), n(6)];
  if (mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || s > 59) return null;
  let ms = Date.UTC(y, mo - 1, d, h, mi, s);
  if (new Date(ms).getUTCDate() !== d) return null;            // 2027-02-31
  const z = (m[7] || "").toUpperCase();
  if (z && z !== "UTC" && z !== "GMT" && z !== "Z") {
    const digits = z.slice(1).replace(":", "");
    const oh = Number(digits.slice(0, 2));
    const om = Number(digits.slice(2, 4));
    if (oh > 14 || om > 59) return null;
    ms -= (z[0] === "-" ? -1 : 1) * (oh * 60 + om) * 6e4;
  }
  return Number.isFinite(ms) ? new Date(ms).toISOString().replace(/\.000Z$/, "Z") : null;
}

/* Remember what GitHub's answer to a dispatch says about the token's expiry.
 * `headers` is the response's Headers, `status` its HTTP status. Never throws;
 * resolves to nothing. */
export async function noteTokenExpiry(kv, headers, status) {
  try {
    if (!kv || !headers || typeof headers.get !== "function") return;
    const raw = headers.get(TOKEN_EXPIRY_HEADER);
    const iso = parseTokenExpiry(raw);
    if (raw != null && !iso) return;        // present but unreadable: keep what we know
    if (!iso && status !== 204) return;     // absent on a refusal proves nothing
    const stored = await kv.get(TOKEN_EXPIRY_KEY);
    if (iso && stored !== iso) await kv.put(TOKEN_EXPIRY_KEY, iso);
    else if (!iso && stored) await kv.delete(TOKEN_EXPIRY_KEY);
  } catch (_) { /* bookkeeping only: it never blocks or changes a dispatch */ }
}

/* What /api/health reports, from KV alone:
 *   { token_expires: ISO string | null, token_days_left: whole days | null }
 * token_days_left is floored (13.9 days left reads 13) and goes negative once
 * the date has passed. Null for both when nothing is stored, KV is missing or
 * KV errors. */
export async function tokenExpiryOf(kv, nowMs) {
  const none = { token_expires: null, token_days_left: null };
  try {
    if (!kv) return none;
    const iso = parseTokenExpiry(await kv.get(TOKEN_EXPIRY_KEY));
    const days = iso ? Math.floor((Date.parse(iso) - nowMs) / 864e5) : NaN;
    return Number.isFinite(days) ? { token_expires: iso, token_days_left: days } : none;
  } catch (_) {
    return none;
  }
}

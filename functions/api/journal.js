/* Cloudflare Pages Function — GET/PUT /api/journal?code=<syncCode>
 *
 * Stores the user's "My Trades" journal JSON so it syncs across devices. The
 * data is keyed by a SHA-256 hash of the user's private sync code (the raw code
 * is never stored), so two devices using the same code share one journal.
 *
 * This is paper-trade bookkeeping only — no money, no secrets. Anyone who knows
 * the code can read/write that journal, so use a non-obvious code.
 *
 * One-time setup (so the sync code works):
 *   1. Cloudflare dashboard → Workers & Pages → KV → Create a namespace
 *        (e.g. name it "gbs-journal").
 *   2. Your Pages project → Settings → Functions → KV namespace bindings →
 *        Add binding:  Variable name = JOURNAL_KV  →  select the namespace.
 *   3. Redeploy. Until this binding exists, the app reports "sync not set up"
 *      and the Backup/Restore buttons still work as a manual fallback.
 *
 * Access-logged (2026-08-20) via _access_log.js — best-effort, never blocks
 * sync. Successful GETs are COALESCED to one marker per IP per day because
 * the page polls every 60s and per-request logging would burn the KV write
 * quota this endpoint's own limiter comments document as scarce; PUTs,
 * errors, misses and rate-limits are logged individually.
 */
import { withAccessLog } from "./_access_log.js";

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

async function keyFor(code) {
  const bytes = new TextEncoder().encode("gbs-journal:" + code);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return "journal:" + hex;
}

// Sync code arrives via the X-Sync-Code HEADER (2026-07-20 security pass —
// query strings leak through Referer, proxy/CDN logs and browser history;
// the code is the journal's only credential). The ?code= query form is kept
// as a fallback for older cached clients.
const cleanCode = (request) =>
  ((request.headers.get("X-Sync-Code") || "").trim()
   || (new URL(request.url).searchParams.get("code") || "").trim());

// Legacy floor — the owner's own sync code may be this short. New codes should
// be ≥8 chars; the enumeration guard below is what keeps short codes viable.
const MIN_CODE_LEN = 4;

// Per-IP hourly throttle — PUTS ONLY (2026-07-29). It used to count GET+PUT at
// 30/hr, which sat UNDER the journal page's own poll cadence: journal.js runs
// silentPull() every 60s while the tab is visible (= 60 GET/hr), plus a pull on
// every visibilitychange, plus a pull+put per edit. A tab left open therefore
// rate-limited ITSELF out of cloud sync within ~30 minutes of every UTC hour —
// and the client swallowed the 429 and kept printing "Synced at", so the
// lockout was invisible. Any GET cap below the poll cadence re-creates that.
//
// GETs are now uncapped here on purpose, for three reasons that stack:
//   1. Enumeration (the thing the old cap named) is guarded by the MISS counter
//      below — a wrong code is a miss, 30 misses/day locks the IP out. A GET
//      with the RIGHT code is the owner; there is nothing to throttle.
//   2. Reads are the cheap KV resource (100k/day free vs 1k writes/day), and a
//      KV-backed limiter cannot protect reads anyway — every check IS a read.
//   3. The old limiter wrote KV on EVERY allowed request (up to 720 writes/day
//      per IP just for counting) — directly against the miss-counter's own
//      stated goal ("the write quota stays protected"). Counting only PUTs
//      keeps counter writes proportional to journal writes.
//
// KV read+increment is not atomic, so racing PUTs can slip a few past the cap;
// acceptable for an abuse guard (the client's own PUT_BUDGET backs it up).
// Fail-open on KV errors: a limiter outage must never break sync.
const PUTS_PER_HOUR = 30;

async function overPutLimit(env, request) {
  try {
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const bucket = new Date().toISOString().slice(0, 13);   // UTC hour bucket
    const key = `ratelimit:journal:${ip}:${bucket}`;
    const n = parseInt((await env.JOURNAL_KV.get(key)) || "0", 10) + 1;
    if (n > PUTS_PER_HOUR) return true;   // over the cap → refuse WITHOUT writing
    await env.JOURNAL_KV.put(key, String(n), { expirationTtl: 7200 });
    return false;
  } catch (_) { return false; }
}

// Brute-force guard: someone guessing sync codes produces GET *misses* — a
// legit user misses at most once or twice at setup. Count only misses per IP
// per day (so the counter costs a KV write only on misses, not on normal
// traffic — the write quota stays protected) and lock the IP out past the cap.
// Fail-open if KV hiccups: a limiter outage must never break sync.
const MISS_DAY_LIMIT = 30;

const missKey = (request) =>
  `ratelimit:journal-miss:${new Date().toISOString().slice(0, 10)}:` +
  (request.headers.get("CF-Connecting-IP") || "unknown");

async function tooManyMisses(env, request) {
  try {
    return parseInt((await env.JOURNAL_KV.get(missKey(request))) || "0", 10) >= MISS_DAY_LIMIT;
  } catch (_) { return false; }
}

async function countMiss(env, request) {
  try {
    const key = missKey(request);
    const n = parseInt((await env.JOURNAL_KV.get(key)) || "0", 10) + 1;
    await env.JOURNAL_KV.put(key, String(n), { expirationTtl: 172800 });
  } catch (_) { /* fail-open */ }
}

export const onRequestGet = withAccessLog("/api/journal", async ({ env, request }) => {
  if (!env.JOURNAL_KV) {
    return json(503, { ok: false, configured: false,
      message: "Cloud sync not set up — add a JOURNAL_KV namespace in Cloudflare (see functions/api/journal.js)." });
  }
  const code = cleanCode(request);
  if (code.length < MIN_CODE_LEN) return json(400, { ok: false, configured: true, message: "Sync code must be at least 4 characters." });
  // No hourly cap on GET — see PUTS_PER_HOUR above. The miss counter is the
  // enumeration guard; a capped GET was locking out the page's own polling.
  if (await tooManyMisses(env, request)) {
    return json(429, { ok: false, configured: true,
      message: "Too many unknown sync codes from this connection today — try again tomorrow." });
  }

  const raw = await env.JOURNAL_KV.get(await keyFor(code));
  let data = null;
  if (raw) { try { data = JSON.parse(raw); } catch (_) { data = null; } }
  else await countMiss(env, request);   // unknown code — brute-force signal
  return json(200, { ok: true, configured: true, data });
}, { coalesceOk: true });

export const onRequestPut = withAccessLog("/api/journal", async ({ env, request }) => {
  if (!env.JOURNAL_KV) {
    return json(503, { ok: false, configured: false,
      message: "Cloud sync not set up — add a JOURNAL_KV namespace in Cloudflare." });
  }
  const code = cleanCode(request);
  if (code.length < MIN_CODE_LEN) return json(400, { ok: false, configured: true, message: "Sync code must be at least 4 characters." });
  if (await overPutLimit(env, request)) {
    return json(429, { ok: false, configured: true,
      message: "Too many sync writes from this connection — try again in an hour. (Your journal is saved locally.)" });
  }
  if (await tooManyMisses(env, request)) {
    return json(429, { ok: false, configured: true,
      message: "Too many unknown sync codes from this connection today — try again tomorrow." });
  }

  let body;
  try { body = await request.json(); } catch (_) { return json(400, { ok: false, configured: true, message: "Invalid JSON body." }); }
  if (!body || typeof body !== "object" || !Array.isArray(body.trades)) {
    return json(400, { ok: false, configured: true, message: "Body must be a journal object with a trades array." });
  }
  // Guard against accidental giant payloads (KV value limit is 25 MB; journals are tiny).
  const serialized = JSON.stringify(body);
  if (serialized.length > 2_000_000) return json(413, { ok: false, configured: true, message: "Journal too large to sync." });

  await env.JOURNAL_KV.put(await keyFor(code), serialized);
  return json(200, { ok: true, configured: true });
});

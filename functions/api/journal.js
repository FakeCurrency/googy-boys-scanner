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
 */

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

const cleanCode = (url) => (new URL(url).searchParams.get("code") || "").trim();

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

export const onRequestGet = async ({ env, request }) => {
  if (!env.JOURNAL_KV) {
    return json(503, { ok: false, configured: false,
      message: "Cloud sync not set up — add a JOURNAL_KV namespace in Cloudflare (see functions/api/journal.js)." });
  }
  const code = cleanCode(request.url);
  if (code.length < 4) return json(400, { ok: false, configured: true, message: "Sync code must be at least 4 characters." });
  if (await tooManyMisses(env, request)) {
    return json(429, { ok: false, configured: true,
      message: "Too many unknown sync codes from this connection today — try again tomorrow." });
  }

  const raw = await env.JOURNAL_KV.get(await keyFor(code));
  let data = null;
  if (raw) { try { data = JSON.parse(raw); } catch (_) { data = null; } }
  else await countMiss(env, request);   // unknown code — brute-force signal
  return json(200, { ok: true, configured: true, data });
};

export const onRequestPut = async ({ env, request }) => {
  if (!env.JOURNAL_KV) {
    return json(503, { ok: false, configured: false,
      message: "Cloud sync not set up — add a JOURNAL_KV namespace in Cloudflare." });
  }
  const code = cleanCode(request.url);
  if (code.length < 4) return json(400, { ok: false, configured: true, message: "Sync code must be at least 4 characters." });
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
};

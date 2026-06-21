/* Cloudflare Pages Function — cloud-side stop/target watcher.  GET|POST /api/tick
 *
 * Walks every synced journal in KV and auto-closes any OPEN paper position whose
 * live price has hit its stop or target — so stops fire 24/7 without keeping a
 * chart page open on any device. This is 100% paper bookkeeping: it never places
 * a real order. The matching client-side logic (chart.js maybeAutoClose) still
 * runs when a chart is open; both guard on status so a trade is closed once.
 *
 * Trigger it on a schedule with the GitHub Action .github/workflows/stop_watcher.yml
 * (every 5 min), an external uptime cron, or a Cloudflare cron Worker. Honest
 * fills: a stop that gaps through fills at the worse live price (never better
 * than the stop); a target never credits overshoot — identical to the chart.
 *
 * Setup: needs the same JOURNAL_KV binding as /api/journal. Optionally set a
 * TICK_SECRET env var (and the matching GitHub secret) to require a bearer token.
 */

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

const BINANCE = "https://api.binance.com/api/v3/ticker/price?symbol=";
const yahooURL = (sym) =>
  `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1m&range=1d`;

function nowParts() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return {
    date: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`,
    time: `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`,
  };
}

// Memoised live-price lookups (one cache per invocation dedups shared symbols).
async function cryptoPrice(sym, cache) {
  const k = "C:" + sym;
  if (k in cache) return cache[k];
  let px = null;
  try {
    const r = await fetch(BINANCE + encodeURIComponent(String(sym).toUpperCase() + "USDT"), {
      cf: { cacheTtl: 0 },
    });
    if (r.ok) { const j = await r.json(); px = j && j.price != null ? +j.price : null; }
  } catch (_) {}
  return (cache[k] = px);
}
async function stockPrice(sym, aType, cache) {
  const ticket = aType === "asx" && !String(sym).includes(".") ? sym + ".AX" : sym;
  const k = "S:" + ticket;
  if (k in cache) return cache[k];
  let px = null;
  try {
    const r = await fetch(yahooURL(ticket), {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; GoogyBoysScanner/1.0)", "Accept": "application/json" },
      cf: { cacheTtl: 0 },
    });
    if (r.ok) { const j = await r.json(); px = j?.chart?.result?.[0]?.meta?.regularMarketPrice ?? null; }
  } catch (_) {}
  return (cache[k] = px);
}

// Decide whether an open trade has hit its stop/target and, if so, the fill.
function resolveClose(t, px) {
  if (px == null) return null;
  const long = t.direction !== "short";
  const stopped  = t.stop   != null && (long ? px <= t.stop   : px >= t.stop);
  const targeted = t.target != null && (long ? px >= t.target : px <= t.target);
  if (!stopped && !targeted) return null;
  // Stop takes precedence if somehow both are satisfied in one gap.
  if (stopped) {
    const fill = long ? Math.min(t.stop, px) : Math.max(t.stop, px);
    return { fill, kind: "stop" };
  }
  return { fill: t.target, kind: "target" };
}

async function runTick(env) {
  if (!env.JOURNAL_KV) {
    return json(503, { ok: false, configured: false, message: "JOURNAL_KV not bound." });
  }
  const cache = {};
  const np = nowParts();
  let journals = 0, closed = 0;
  const details = [];

  let cursor;
  do {
    const list = await env.JOURNAL_KV.list({ prefix: "journal:", cursor });
    cursor = list.list_complete ? null : list.cursor;
    for (const { name } of list.keys) {
      journals++;
      let data;
      try { data = JSON.parse((await env.JOURNAL_KV.get(name)) || "null"); } catch (_) { data = null; }
      if (!data || !Array.isArray(data.trades)) continue;

      let changed = false;
      for (const t of data.trades) {
        if (!t || t.status !== "open") continue;
        if (t.stop == null && t.target == null) continue;
        const aType = t.asset_type || "crypto";
        const isStock = aType === "asx" || aType === "nasdaq";
        const px = await (isStock ? stockPrice(t.symbol, aType, cache) : cryptoPrice(t.symbol, cache));
        const hit = resolveClose(t, px);
        if (!hit) continue;
        t.status = "closed";
        t.exit = hit.fill;
        t.exit_date = np.date;
        t.exit_time = np.time;
        t.auto_closed = hit.kind;
        t.closed_by = "cloud-watcher";
        t.mtime = Date.now();
        changed = true;
        closed++;
        details.push({ symbol: t.symbol, dir: t.direction, kind: hit.kind, fill: hit.fill });
      }

      if (changed) {
        data.updated_at = Date.now();
        await env.JOURNAL_KV.put(name, JSON.stringify(data));
      }
    }
  } while (cursor);

  return json(200, { ok: true, journals, closed, details, at: new Date().toISOString() });
}

function authorised(request, env) {
  if (!env.TICK_SECRET) return true;          // open unless a secret is configured
  const url = new URL(request.url);
  const fromQuery = url.searchParams.get("key");
  const header = request.headers.get("Authorization") || "";
  const fromHeader = header.startsWith("Bearer ") ? header.slice(7) : "";
  return fromQuery === env.TICK_SECRET || fromHeader === env.TICK_SECRET;
}

export const onRequest = async ({ request, env }) => {
  if (request.method !== "GET" && request.method !== "POST") {
    return json(405, { ok: false, message: "Use GET or POST." });
  }
  if (!authorised(request, env)) return json(401, { ok: false, message: "Unauthorized." });
  return runTick(env);
};

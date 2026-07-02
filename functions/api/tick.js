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

import { fetchBinancePrice, fetchYahooChart } from "./_prices.js";

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

function nowParts() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return {
    date: `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`,
    time: `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`,
  };
}

// Commodity/index symbols → their Yahoo tickers (mirrors journal.js YF_TICKER),
// so a GOLD or NAS100 position resolves a real quote instead of a dead lookup.
const YF_TICKER = {
  NAS100: "^NDX", US30: "^DJI", SPX500: "^GSPC", GER40: "^GDAXI", UK100: "^FTSE", JP225: "^N225",
  GOLD: "GC=F", SILVER: "SI=F", COPPER: "HG=F", PLATINUM: "PL=F", PALLADIUM: "PA=F",
  OIL: "CL=F", WTI: "CL=F", BRENT: "BZ=F", NATGAS: "NG=F", WHEAT: "ZW=F", COFFEE: "KC=F",
};

// Memoised live-price lookups (one cache per invocation dedups shared symbols).
// Both paths fall back gracefully: crypto tries Binance then Yahoo; stocks try
// both Yahoo hosts. A null result simply means "no fill this pass" — the trade
// stays open and is re-checked next tick (never closed on a missing price).
async function cryptoPrice(sym, cache) {
  const k = "C:" + sym;
  if (k in cache) return cache[k];
  let px = await fetchBinancePrice(sym);
  if (px == null) {
    try {
      const result = await fetchYahooChart(sym, { interval: "1m", range: "1d" });
      px = result?.meta?.regularMarketPrice ?? null;
    } catch (_) { px = null; }
  }
  return (cache[k] = px);
}
async function stockPrice(sym, aType, cache) {
  const up = String(sym || "").toUpperCase();
  const ticket = YF_TICKER[up]
    || (aType === "asx" && !String(sym).includes(".") ? sym + ".AX" : sym);
  const k = "S:" + ticket;
  if (k in cache) return cache[k];
  let px = null;
  try {
    const result = await fetchYahooChart(ticket, { interval: "1m", range: "1d" });
    px = result?.meta?.regularMarketPrice ?? result?.meta?.previousClose ?? null;
  } catch (_) { px = null; }
  return (cache[k] = px);
}

/* ── VIVEK scale-out management (parity with public/js/journal.js manage()) ───
 * A VIVEK trade (has stop + tp1) must NOT be full-closed at a single "target":
 * the rules book partials at TP1/TP2/TP3, trail the SL (break-even at TP1, TP1
 * at TP2) and close the remainder on the stop. Before this, a trade whose page
 * was closed got legacy handling — full exit at tp2, untrailed stop — so the
 * journal diverged from the rules whenever nobody had a chart open. The
 * constants mirror the client exactly; drift between the two = wrong P&L.   */
const VK = {
  EQUITY: 10000, RISK_PCT: 0.35, RISK_MIN: 0.25, RISK_MAX: 0.5,
  LEVERAGE: { asx: 5, nasdaq: 5, crypto: 3 },
  SCALE: { long: [0.25, 0.50, 0.15], short: [0.50, 0.25, 0.15] },
  COMMISSION_BPS: { asx: 2, nasdaq: 1, crypto: 6, default: 2 },
  SLIPPAGE_BPS: { asx: 5, nasdaq: 4, crypto: 8, default: 5 },
};
const isVivek = (t) => t && t.stop != null && t.tp1 != null;
const vkMarket = (t) => {
  const a = t.market || t.asset_type;
  if (a === "crypto") return "crypto";
  if (a === "asx") return "asx";
  return "nasdaq";               // nasdaq + commodity/index use nasdaq-tier costs
};
function vkSizeRiskUsd(market, entry, stop) {
  const riskPct = Math.min(Math.max(VK.RISK_PCT, VK.RISK_MIN), VK.RISK_MAX) / 100;
  const dist = Math.abs(entry - stop);
  if (!(dist > 0) || !(entry > 0)) return 0;
  let riskUsd = VK.EQUITY * riskPct;
  const maxN = VK.EQUITY * (VK.LEVERAGE[market] || VK.LEVERAGE.asx);
  if ((riskUsd / dist) * entry > maxN) riskUsd = (maxN / entry) * dist;
  return riskUsd;
}
function vkInit(t) {
  const isLong = t.direction !== "short";
  if (!(t.risk > 0)) t.risk = Math.abs(t.entry - t.stop);
  if (t.risk_usd == null) t.risk_usd = vkSizeRiskUsd(vkMarket(t), t.entry, t.stop);
  if (!Array.isArray(t.scale)) t.scale = VK.SCALE[isLong ? "long" : "short"];
  if (!Array.isArray(t.exits)) t.exits = [];
  if (t.gross_r == null) t.gross_r = 0;
  if (t.booked_pct == null) t.booked_pct = 0;
  if (t.tp1_hit == null) { t.tp1_hit = false; t.tp2_hit = false; t.tp3_hit = false; }
}
const vkR = (price, entry, risk, isLong) => (isLong ? price - entry : entry - price) / risk;
function vkFinalize(t) {
  const m = vkMarket(t);
  const slip = (VK.SLIPPAGE_BPS[m] ?? VK.SLIPPAGE_BPS.default) / 1e4;
  const comm = (VK.COMMISSION_BPS[m] ?? VK.COMMISSION_BPS.default) / 1e4;
  let cp = t.entry * (slip + comm);
  for (const ex of t.exits) {
    const market = /^(stop|manual)/.test(ex.reason || "");
    cp += (ex.pct || 0) * (ex.price || t.entry) * (comm + (market ? slip : 0));
  }
  t.cost_r = +(cp / t.risk).toFixed(4);
  t.realized_r = +((t.gross_r || 0) - t.cost_r).toFixed(4);
}
// Returns "close" | "book" | false. np = {date, time} for close stamps.
function manageVivek(t, px, np) {
  if (t.status !== "open" || px == null) return false;
  vkInit(t);
  const isLong = t.direction !== "short", risk = t.risk;
  if (!(risk > 0)) return false;
  let booked = false;

  const stopHit = isLong ? px <= t.stop : px >= t.stop;
  if (stopHit) {
    // Honest gap fill: never better than the stop.
    const fill = isLong ? Math.min(t.stop, px) : Math.max(t.stop, px);
    const remaining = +(1 - (t.booked_pct || 0)).toFixed(6);
    if (remaining > 1e-9) {
      t.exits.push({ reason: "stop", price: +fill.toFixed(8), pct: remaining, date: np.date });
      t.gross_r = +((t.gross_r || 0) + remaining * vkR(fill, t.entry, risk, isLong)).toFixed(4);
      t.booked_pct = 1;
    }
    t.status = "closed"; t.exit = +fill.toFixed(8);
    t.exit_date = np.date; t.exit_time = np.time;
    t.exit_reason = t.tp3_hit ? "target" : (t.tp1_hit ? "trail" : "stop");
    t.auto_closed = "stop"; t.closed_by = "cloud-watcher"; t.mtime = Date.now();
    vkFinalize(t);
    return "close";
  }

  const scale = t.scale;
  const reached = (lvl) => (isLong ? px >= lvl : px <= lvl);
  const valid = (lvl) => (isLong ? lvl > t.entry : lvl < t.entry);   // chased-entry guard
  const fav = (nsl, csl) => (isLong ? nsl > csl : nsl < csl);        // SL only in our favour
  const book = (name, lvl, pct) => {
    t.exits.push({ reason: name, price: +lvl.toFixed(8), pct, date: np.date });
    t.gross_r = +((t.gross_r || 0) + pct * vkR(lvl, t.entry, risk, isLong)).toFixed(4);
    t.booked_pct = +((t.booked_pct || 0) + pct).toFixed(6);
    booked = true;
  };
  if (!t.tp1_hit && t.tp1 != null && valid(t.tp1) && reached(t.tp1)) {
    t.tp1_hit = true; book("tp1", t.tp1, scale[0]);
    if (fav(t.entry, t.stop)) t.stop = t.entry;                      // SL → break-even
  }
  if (!t.tp2_hit && t.tp2 != null && valid(t.tp2) && reached(t.tp2)) {
    t.tp2_hit = true; book("tp2", t.tp2, scale[1]);
    if (t.tp1 != null && fav(t.tp1, t.stop)) t.stop = t.tp1;         // SL → locked structure
  }
  if (!t.tp3_hit && t.tp3 != null && valid(t.tp3) && reached(t.tp3)) {
    t.tp3_hit = true; book("tp3", t.tp3, scale[2]);
  }
  if (booked) { t.mtime = Date.now(); vkFinalize(t); return "book"; }
  return false;
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
        const isStock = aType === "asx" || aType === "nasdaq"
          || aType === "commodity" || aType === "index";
        const px = await (isStock ? stockPrice(t.symbol, aType, cache) : cryptoPrice(t.symbol, cache));

        // VIVEK trades (stop + tp1) get the full scale-out rules — TP partials,
        // SL trailing, stop closes the remainder — identical to the client.
        if (isVivek(t)) {
          const r = manageVivek(t, px, np);
          if (!r) continue;
          changed = true;
          if (r === "close") {
            closed++;
            details.push({ symbol: t.symbol, dir: t.direction, kind: t.exit_reason, fill: t.exit });
          } else {
            details.push({ symbol: t.symbol, dir: t.direction, kind: "scale-out", fill: px });
          }
          continue;
        }

        // Legacy (non-VIVEK) trades: simple full close on stop or target.
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

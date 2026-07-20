/* Cloudflare Pages Function — GET /api/price?symbol=BTC-USD
 *
 * Resilient price + history proxy. Crypto prefers Binance (real-time, 24/7) and
 * falls back to Yahoo; stocks/commodities use Yahoo across both hosts. History
 * is trimmed to a consistent bar-count per range so every asset type returns a
 * comparable-length series for the chart.
 *
 *   GET /api/price?symbol=AAPL
 *     → { ok, price, symbol, source }
 *   GET /api/price?symbol=BTC-USD&range=1y&interval=1d&type=crypto
 *     → { ok, price, symbol, source, delayed, bars, candles:[{time,open,high,low,close,volume}] }
 */
import { livePrice, history } from "./_prices.js";

// Successful responses edge-cache for ~20s — chart opens and journal refreshes
// re-request the same symbols in bursts; a short shared cache absorbs those
// instead of hammering Yahoo into throttling. Errors are never cached.
const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": status === 200 ? "public, max-age=15, s-maxage=20" : "no-store",
    },
  });

// Free-relay guard: per-IP cap shared with /api/quote (same "px" key space).
// KV read+increment is not atomic — racing bursts can slip a few past the cap,
// fine for an abuse guard. Degrades open (no limiting) when the KV binding is
// absent, same as scan.js, so a misconfig can't kill charts.
const PX_REQS_PER_MIN = 120;

async function overPxLimit(env, request) {
  if (!env || !env.JOURNAL_KV) return false;
  try {
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const bucket = new Date().toISOString().slice(0, 16);   // UTC minute bucket
    const key = `ratelimit:px:${ip}:${bucket}`;
    const n = parseInt((await env.JOURNAL_KV.get(key)) || "0", 10) + 1;
    if (n > PX_REQS_PER_MIN) return true;
    await env.JOURNAL_KV.put(key, String(n), { expirationTtl: 120 });
    return false;
  } catch (_) { return false; }
}

export const onRequestGet = async ({ request, env }) => {
  const url = new URL(request.url);
  const symbol = url.searchParams.get("symbol") || "";

  // Whitelist the ranges / intervals we actually use so the param can't craft
  // arbitrary upstream requests.
  const RANGES = new Set(["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]);
  const INTERVALS = new Set(["1m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"]);
  const range = RANGES.has(url.searchParams.get("range")) ? url.searchParams.get("range") : null;
  const interval = INTERVALS.has(url.searchParams.get("interval")) ? url.searchParams.get("interval") : null;
  const assetType = (url.searchParams.get("type") || "").toLowerCase() || null;  // optional hint
  // Optional source override: "yahoo" forces the Yahoo path (skips the Binance
  // pair guess) so VIVEK crypto charts match the scan's <base>-USD series.
  const prefer = ["yahoo", "binance"].includes((url.searchParams.get("src") || "").toLowerCase())
    ? url.searchParams.get("src").toLowerCase() : null;
  const wantCandles = Boolean(range && interval);

  if (!symbol || symbol.length > 30 || !/^[\w.\-^=]+$/i.test(symbol)) {
    return json(400, { ok: false, error: "Invalid symbol" });
  }

  if (await overPxLimit(env, request)) {
    return json(429, { ok: false, error: "Too many price requests — slow down." });
  }

  try {
    const live = await livePrice(symbol, assetType, prefer);

    if (!wantCandles) {
      if (live.price == null) return json(502, { ok: false, error: "no price from any source", symbol });
      return json(200, { ok: true, price: +live.price.toFixed(8), symbol, source: live.source });
    }

    const hist = await history(symbol, assetType, { range, interval, prefer });
    // Prefer the live tick for `price`; fall back to the last candle close.
    const lastClose = hist.candles.length ? hist.candles[hist.candles.length - 1].close : null;
    const price = live.price != null ? +live.price : lastClose;

    if (price == null && !hist.candles.length) {
      return json(502, { ok: false, error: "no price or history from any source", symbol });
    }

    return json(200, {
      ok: true,
      symbol,
      price: price == null ? null : +price.toFixed(8),
      source: hist.source || live.source,
      delayed: hist.delayed,
      bars: hist.candles.length,
      candles: hist.candles,
      // dividend within ~45d → the adjusted series (and levels) differs from
      // the raw prices a broker shows; the chart surfaces this as a chip
      recent_div: hist.recent_div || null,
    });
  } catch (err) {
    return json(502, { ok: false, error: String(err && err.message ? err.message : err), symbol });
  }
};

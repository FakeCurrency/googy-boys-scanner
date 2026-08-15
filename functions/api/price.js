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
import { livePrice, history, intervalDegraded } from "./_prices.js";
import { overPxLimit, cacheMatch, cachePut } from "./_relay_guard.js";

// Successful responses edge-cache for ~20s via the Cache API (cachePut below —
// a Cache-Control header alone does NOT edge-cache a Function response) — chart
// opens and journal refreshes re-request the same symbols in bursts; a short
// shared cache absorbs those instead of hammering Yahoo into throttling.
// Errors are never cached. The per-IP guard is in-memory — zero KV operations
// on this hot path (the old KV counter burned the daily write quota by itself).
const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": status === 200 ? "public, max-age=15, s-maxage=20" : "no-store",
    },
  });

export const onRequestGet = async (ctx) => {
  const { request } = ctx;
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

  const hit = await cacheMatch(request);
  if (hit) return hit;

  if (overPxLimit(request)) {
    return json(429, { ok: false, error: "Too many price requests — slow down." });
  }

  try {
    const live = await livePrice(symbol, assetType, prefer);

    if (!wantCandles) {
      if (live.price == null) return json(502, { ok: false, error: "no price from any source", symbol });
      return cachePut(ctx, json(200, { ok: true, price: +live.price.toFixed(8), symbol, source: live.source }));
    }

    // EODHD (owner-installed Cloudflare env var EODHD_API_TOKEN) feeds the
    // CHART/HISTORY path only. The key exists solely in Cloudflare Pages, so
    // the GitHub-Actions scan engine cannot read it even by accident — that
    // is the live-grade-path fence, structural rather than promised.
    const hist = await history(symbol, assetType,
      { range, interval, prefer, eodKey: ctx.env && ctx.env.EODHD_API_TOKEN ? ctx.env.EODHD_API_TOKEN : null });
    // Prefer the live tick for `price`; fall back to the last candle close.
    const lastClose = hist.candles.length ? hist.candles[hist.candles.length - 1].close : null;
    const price = live.price != null ? +live.price : lastClose;

    if (price == null && !hist.candles.length) {
      return json(502, { ok: false, error: "no price or history from any source", symbol });
    }

    // DATA HONESTY (2026-08-15) — three facts the chart needs to stop
    // presenting a series as something it is not:
    //   basis    "adj" = bars share the scan's dividend/split-adjusted
    //            arithmetic (levels line up); "raw" = unadjusted (intraday, or
    //            Yahoo returned no adjclose).
    //   flat     bars in the served window with open==high==low==close — on
    //            thin ASX names Yahoo pads no-trade sessions with carried
    //            closes (measured: RML 49% of its "5y"), and structure-TA on a
    //            padded tape is fiction the chart must label.
    //   degraded true when the bars came back COARSER than the requested
    //            interval (Yahoo degrades deep ranges silently — max/1d has
    //            been observed returning monthly bars).
    const flat = hist.candles.reduce(
      (n, b) => n + (b.open === b.high && b.high === b.low && b.low === b.close ? 1 : 0), 0);
    return cachePut(ctx, json(200, {
      ok: true,
      symbol,
      price: price == null ? null : +price.toFixed(8),
      source: hist.source || live.source,
      delayed: hist.delayed,
      bars: hist.candles.length,
      candles: hist.candles,
      basis: hist.basis || "raw",
      flat,
      degraded: intervalDegraded(hist.candles, interval),
      // dividend within ~45d → the adjustment is RECENT, so the gap between
      // these (adjusted) bars and the raw prices a broker quotes is fresh and
      // visible; the chart surfaces this as a chip
      recent_div: hist.recent_div || null,
    }));
  } catch (err) {
    return json(502, { ok: false, error: String(err && err.message ? err.message : err), symbol });
  }
};

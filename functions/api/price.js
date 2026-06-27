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

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

export const onRequestGet = async ({ request }) => {
  const url = new URL(request.url);
  const symbol = url.searchParams.get("symbol") || "";

  // Whitelist the ranges / intervals we actually use so the param can't craft
  // arbitrary upstream requests.
  const RANGES = new Set(["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"]);
  const INTERVALS = new Set(["1m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"]);
  const range = RANGES.has(url.searchParams.get("range")) ? url.searchParams.get("range") : null;
  const interval = INTERVALS.has(url.searchParams.get("interval")) ? url.searchParams.get("interval") : null;
  const assetType = (url.searchParams.get("type") || "").toLowerCase() || null;  // optional hint
  const wantCandles = Boolean(range && interval);

  if (!symbol || symbol.length > 30 || !/^[\w.\-^=]+$/i.test(symbol)) {
    return json(400, { ok: false, error: "Invalid symbol" });
  }

  try {
    const live = await livePrice(symbol, assetType);

    if (!wantCandles) {
      if (live.price == null) return json(502, { ok: false, error: "no price from any source", symbol });
      return json(200, { ok: true, price: +live.price.toFixed(8), symbol, source: live.source });
    }

    const hist = await history(symbol, assetType, { range, interval });
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
    });
  } catch (err) {
    return json(502, { ok: false, error: String(err && err.message ? err.message : err), symbol });
  }
};

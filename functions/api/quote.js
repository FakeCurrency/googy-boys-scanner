// Cloudflare Pages Function — resilient single-quote proxy.
// GET /api/quote?sym=BHP.AX  → { price, currency, time, source }
// GET /api/quote?sym=BTC-USD → { price, currency, time, source }
//
// Crypto prefers Binance (real-time, 24/7); stocks/commodities use Yahoo across
// both hosts. Currency is preserved from Yahoo meta (so ASX returns AUD).
import { isCryptoSymbol, fetchBinancePrice, fetchYahooChart, yahooCryptoSymbol } from "./_prices.js";

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

export async function onRequestGet(ctx) {
  const sym = new URL(ctx.request.url).searchParams.get("sym") || "";

  if (!/^[A-Za-z0-9.\^=\-_]{1,20}$/.test(sym)) {
    return json(400, { error: "Invalid symbol" });
  }

  const now = Math.floor(Date.now() / 1000);

  // Crypto: Binance first (keyless, real-time), Yahoo as a backstop.
  const crypto = isCryptoSymbol(sym);
  if (crypto) {
    const px = await fetchBinancePrice(sym);
    if (px != null) return json(200, { price: px, currency: "USD", time: now, source: "binance" });
  }

  // Stocks / commodities (and crypto fallback): Yahoo across both hosts. Crypto
  // must use "<base>-USD" so a bare base can't resolve to a same-named equity.
  try {
    const result = await fetchYahooChart(crypto ? yahooCryptoSymbol(sym) : sym, { interval: "1m", range: "1d" });
    const meta = result?.meta;
    if (!meta) return json(502, { error: "No data returned for " + sym });
    const price = meta.regularMarketPrice ?? meta.previousClose ?? null;
    if (price == null) return json(502, { error: "No price for " + sym });
    return json(200, {
      price,
      currency: meta.currency ?? "USD",
      time: meta.regularMarketTime ?? now,
      source: "yahoo",
    });
  } catch (err) {
    return json(502, { error: "Upstream failed: " + String(err && err.message ? err.message : err) });
  }
}

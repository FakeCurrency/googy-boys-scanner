// Cloudflare Pages Function — resilient single-quote proxy.
// GET /api/quote?sym=BHP.AX  → { price, currency, time, source }
// GET /api/quote?sym=BTC-USD → { price, currency, time, source }
//
// Crypto prefers Binance (real-time, 24/7); stocks/commodities use Yahoo across
// both hosts. Currency is preserved from Yahoo meta (so ASX returns AUD).
import { isCryptoSymbol, fetchBinancePrice, fetchYahooChart, yahooCryptoSymbol } from "./_prices.js";

// Successful quotes are edge-cached for ~20s: the journal opens with a batch
// of per-symbol fetches, so a short shared cache absorbs repeat opens (and
// multiple devices) instead of hammering Yahoo into throttling us. Errors are
// never cached.
const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": status === 200 ? "public, max-age=15, s-maxage=20" : "no-store",
    },
  });

// Free-relay guard: per-IP cap shared with /api/price (same "px" key space).
// KV read+increment is not atomic — racing bursts can slip a few past the cap,
// fine for an abuse guard. Degrades open (no limiting) when the KV binding is
// absent, same as scan.js, so a misconfig can't kill quotes.
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

export async function onRequestGet(ctx) {
  const url = new URL(ctx.request.url);
  const sym = url.searchParams.get("sym") || "";
  // src=yahoo forces the Yahoo path (skips the Binance pair guess) so a VIVEK
  // crypto header price matches its chart's scan-consistent <base>-USD series.
  const prefer = url.searchParams.get("src") === "yahoo" ? "yahoo" : null;

  if (!/^[A-Za-z0-9.\^=\-_]{1,20}$/.test(sym)) {
    return json(400, { error: "Invalid symbol" });
  }

  if (await overPxLimit(ctx.env, ctx.request)) {
    return json(429, { error: "Too many quote requests — slow down." });
  }

  const now = Math.floor(Date.now() / 1000);

  // Crypto: Binance first (keyless, real-time), Yahoo as a backstop.
  const crypto = isCryptoSymbol(sym);
  if (crypto && prefer !== "yahoo") {
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

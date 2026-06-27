/* Shared price/candle helpers for the API Functions (Cloudflare Workers runtime).
 *
 * This file exports helpers only — it has no request handler, so it is bundled
 * into the Functions that import it and is never itself a routable endpoint.
 *
 * Design goals (resilience + consistency):
 *   • Live prices never depend on a single upstream. Crypto prefers Binance
 *     (real-time, keyless, 24/7) and falls back to Yahoo; everything else uses
 *     Yahoo across BOTH hosts (query1 → query2) before giving up.
 *   • Historical candles are trimmed to a target bar-count per range so every
 *     asset type returns a consistent-length series for the chart.
 *   • Every fetch has a timeout and is wrapped so one dead source can't hang or
 *     crash the caller — failures degrade to the next source, then to null.
 */

const UA = "Mozilla/5.0 (compatible; VivekBetaScanner/1.0)";
const YH_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"];
const BINANCE_PRICE = "https://api.binance.com/api/v3/ticker/price?symbol=";
const BINANCE_KLINES = "https://api.binance.com/api/v3/klines";

// Common base tickers that are crypto even without a -USD/USDT suffix.
const KNOWN_CRYPTO = new Set([
  "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
  "MATIC", "LTC", "TRX", "ATOM", "UNI", "ARB", "OP", "SUI", "APT", "NEAR",
  "INJ", "TIA", "SEI", "RNDR", "FIL", "AAVE", "MKR", "PEPE", "WIF", "BONK",
]);

/** True if the symbol looks like a crypto pair (suffix or known base). */
export function isCryptoSymbol(sym) {
  const s = String(sym || "").toUpperCase();
  if (/-USD$/.test(s) || /USDT$/.test(s) || /-USDT$/.test(s)) return true;
  const base = s.replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "");
  return KNOWN_CRYPTO.has(base);
}

/** Normalise any crypto symbol to its Binance USDT pair (BTC-USD → BTCUSDT). */
export function binanceSymbol(sym) {
  const base = String(sym || "").toUpperCase()
    .replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "");
  return base + "USDT";
}

/** Map our chart intervals to Binance kline intervals. */
function binanceInterval(interval) {
  return ({
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1h", "1h": "1h", "1d": "1d", "1wk": "1w", "1mo": "1M",
  })[interval] || "1d";
}

/** Target bar-count per range so all asset types return a consistent-length series. */
export function targetBars(range, interval) {
  if (["1m", "5m", "15m", "30m", "60m", "1h"].includes(interval)) return 500;
  return ({
    "1d": 2, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 130,
    "1y": 260, "2y": 520, "5y": 1000, "10y": 1000, "max": 1000,
  })[range] || 260;
}

async function timedFetch(url, opts = {}, timeout = 9000) {
  return fetch(url, { ...opts, signal: AbortSignal.timeout(timeout), cf: { cacheTtl: 0 } });
}

/** Fetch a Yahoo v8 chart result, trying both hosts before failing. */
export async function fetchYahooChart(sym, { interval = "1d", range = "1d", timeout = 9000 } = {}) {
  let lastErr;
  for (const host of YH_HOSTS) {
    try {
      const url = `https://${host}/v8/finance/chart/${encodeURIComponent(sym)}` +
        `?interval=${interval}&range=${range}`;
      const res = await timedFetch(url, { headers: { "User-Agent": UA, "Accept": "application/json" } }, timeout);
      if (!res.ok) { lastErr = new Error(`yahoo ${res.status}`); continue; }
      const data = await res.json();
      const result = data?.chart?.result?.[0];
      if (!result) { lastErr = new Error("yahoo: empty result"); continue; }
      return result;
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error("yahoo: all hosts failed");
}

/** Live Binance spot price (or null on any failure). */
export async function fetchBinancePrice(sym, timeout = 6000) {
  try {
    const r = await timedFetch(BINANCE_PRICE + encodeURIComponent(binanceSymbol(sym)), {}, timeout);
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.price != null ? +j.price : null;
  } catch (_) { return null; }
}

/** Binance klines → candle objects ({time:sec, o,h,l,c,volume}); [] on failure. */
export async function fetchBinanceCandles(sym, { interval = "1d", limit = 260, timeout = 9000 } = {}) {
  try {
    const url = `${BINANCE_KLINES}?symbol=${encodeURIComponent(binanceSymbol(sym))}` +
      `&interval=${binanceInterval(interval)}&limit=${Math.min(limit, 1000)}`;
    const r = await timedFetch(url, {}, timeout);
    if (!r.ok) return [];
    const rows = await r.json();
    if (!Array.isArray(rows)) return [];
    return rows.map((k) => ({
      time: Math.floor(k[0] / 1000),
      open: +k[1], high: +k[2], low: +k[3], close: +k[4],
      volume: k[5] == null ? 0 : Math.round(+k[5]),
    }));
  } catch (_) { return []; }
}

/** Yahoo chart result → clean candle objects (nulls dropped). */
export function yahooCandles(result) {
  const ts = result?.timestamp || [];
  const q = result?.indicators?.quote?.[0] || {};
  const { open = [], high = [], low = [], close = [], volume = [] } = q;
  const out = [];
  for (let i = 0; i < ts.length; i++) {
    const o = open[i], h = high[i], l = low[i], c = close[i];
    if (o == null || h == null || l == null || c == null) continue;  // skip padded gaps
    out.push({ time: ts[i], open: +o, high: +h, low: +l, close: +c, volume: volume[i] == null ? 0 : Math.round(volume[i]) });
  }
  return out;
}

/** Trim a candle series to the last `n` bars (keeps lengths consistent). */
export function trimCandles(candles, n) {
  return n > 0 && candles.length > n ? candles.slice(candles.length - n) : candles;
}

/**
 * Resilient live price with a source-aware fallback chain.
 * @returns {{price:number|null, source:string|null, delayed:boolean}}
 */
export async function livePrice(sym, assetType) {
  const crypto = assetType ? assetType === "crypto" : isCryptoSymbol(sym);
  if (crypto) {
    const b = await fetchBinancePrice(sym);
    if (b != null) return { price: +b, source: "binance", delayed: false };
  }
  try {
    const result = await fetchYahooChart(sym, { interval: "1d", range: "1d" });
    const m = result?.meta;
    const px = m?.regularMarketPrice ?? m?.previousClose ?? null;
    if (px != null) return { price: +px, source: "yahoo", delayed: !crypto };
  } catch (_) { /* fall through */ }
  // Last resort: a crypto whose Binance pair failed but has a Yahoo listing
  if (crypto) {
    try {
      const result = await fetchYahooChart(sym, { interval: "1d", range: "1d" });
      const px = result?.meta?.regularMarketPrice ?? null;
      if (px != null) return { price: +px, source: "yahoo", delayed: false };
    } catch (_) { /* give up */ }
  }
  return { price: null, source: null, delayed: false };
}

/**
 * Resilient candle history, consistent-length across asset types.
 * Crypto → Binance klines (fallback Yahoo); others → Yahoo (dual host).
 * @returns {{candles:Array, source:string|null, delayed:boolean}}
 */
export async function history(sym, assetType, { range = "1y", interval = "1d" } = {}) {
  const crypto = assetType ? assetType === "crypto" : isCryptoSymbol(sym);
  const want = targetBars(range, interval);

  if (crypto) {
    const c = await fetchBinanceCandles(sym, { interval, limit: want });
    if (c.length) return { candles: trimCandles(c, want), source: "binance", delayed: false };
  }
  try {
    const result = await fetchYahooChart(sym, { interval, range });
    const c = yahooCandles(result);
    if (c.length) return { candles: trimCandles(c, want), source: "yahoo", delayed: !crypto };
  } catch (_) { /* fall through */ }
  return { candles: [], source: null, delayed: false };
}

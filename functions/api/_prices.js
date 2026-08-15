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

/** Normalise any crypto symbol to its Yahoo pair (BDX → BDX-USD, BDXUSDT → BDX-USD).
 * Crypto MUST be queried on Yahoo as "<base>-USD"; a bare base like "BDX" resolves
 * to a same-named EQUITY (BDX = Becton Dickinson), which is the wrong instrument. */
export function yahooCryptoSymbol(sym) {
  const base = String(sym || "").toUpperCase()
    .replace(/-USD$/, "").replace(/-USDT$/, "").replace(/USDT$/, "");
  return base + "-USD";
}

/** Map our chart intervals to Binance kline intervals. */
function binanceInterval(interval) {
  return ({
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1h", "1h": "1h", "1d": "1d", "1wk": "1w", "1mo": "1M",
  })[interval] || "1d";
}

/** Target bar-count per range so all asset types return a consistent-length series.
 *
 * DEPTH (2026-08-15): 5y/10y/max used to cap at 1000 bars, which silently cut
 * every "5y" DAILY request to ~4 years (equities) and ~2.7 years (7-day crypto)
 * — the weekly view is resampled from this pull, so the flagship Weekly SMA-200
 * had ~11 valid points on ASX and could not be computed at all on crypto.
 * 1900 covers 5y of 7-day crypto (1827) and 5y of equity sessions (~1265) with
 * slack; 2600 gives 10y of equity sessions. Chart-page only (lazy), never on
 * the deck first-paint. Binance klines are hard-capped at 1000 by the exchange
 * (fetchBinanceCandles clamps) — VIVEK crypto charts use the Yahoo path. */
export function targetBars(range, interval) {
  if (["1m", "5m", "15m", "30m", "60m", "1h"].includes(interval)) return 750;
  return ({
    "1d": 2, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 130,
    "1y": 260, "2y": 520, "5y": 1900, "10y": 2600, "max": 2600,
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
        `?interval=${interval}&range=${range}&events=div`;
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

/** Yahoo chart result → clean candle objects (nulls dropped).
 *
 * BASIS PARITY (2026-08-15): the scanner computes every level on
 * dividend/split-ADJUSTED prices (yfinance auto_adjust=True, scanner/data.py),
 * while Yahoo's raw quote arrays are unadjusted — so raw bars put the engine's
 * levels on the wrong side of the chart's own SMAs. Measured the day this
 * shipped: RHC/AIA/SDF (all A+ weekly-lens) each drew price BELOW a raw-basis
 * weekly 200-SMA while the engine had it reacting from ABOVE (drift +2.9–4.9%).
 * Each bar is therefore scaled by adjclose/close so chart bars share the
 * engine's arithmetic. adjclose is absent on intraday intervals — those stay
 * raw, which is fine: the intraday window is too recent for adjustments to
 * matter, and the LAST bar's factor is 1 by construction either way (adjclose
 * back-adjusts history relative to the latest close). */
export function yahooCandles(result) {
  const ts = result?.timestamp || [];
  const q = result?.indicators?.quote?.[0] || {};
  const adj = result?.indicators?.adjclose?.[0]?.adjclose || null;
  const { open = [], high = [], low = [], close = [], volume = [] } = q;
  const out = [];
  for (let i = 0; i < ts.length; i++) {
    const o = open[i], h = high[i], l = low[i], c = close[i];
    if (o == null || h == null || l == null || c == null) continue;  // skip padded gaps
    let f = 1;
    if (adj) {
      const a = adj[i];
      // Guard: a missing/zero/absurd factor falls back to raw for THAT bar
      // rather than fabricating a price (f must be finite and positive).
      if (a != null && c > 0) { const r = a / c; if (Number.isFinite(r) && r > 0) f = r; }
    }
    out.push(f === 1
      ? { time: ts[i], open: +o, high: +h, low: +l, close: +c, volume: volume[i] == null ? 0 : Math.round(volume[i]) }
      : { time: ts[i], open: +(o * f).toFixed(8), high: +(h * f).toFixed(8),
          low: +(l * f).toFixed(8), close: +(c * f).toFixed(8),
          volume: volume[i] == null ? 0 : Math.round(volume[i]) });
  }
  return out;
}

/** True when a Yahoo chart result carries an adjusted-close series (i.e. the
 *  candles yahooCandles() built from it are on the scan's adjusted basis). */
export function isAdjusted(result) {
  return Boolean(result?.indicators?.adjclose?.[0]?.adjclose);
}

/** Median spacing (seconds) between consecutive bars, over the last ≤20 gaps.
 *  null with fewer than 3 bars (not enough evidence to judge). */
export function barSpacing(candles) {
  if (!candles || candles.length < 3) return null;
  const tail = candles.slice(-21);
  const gaps = [];
  for (let i = 1; i < tail.length; i++) gaps.push(tail[i].time - tail[i - 1].time);
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)];
}

const INTERVAL_SEC = {
  "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600,
  "1d": 86400, "1wk": 604800, "1mo": 2629800,
};

/** INTERVAL HONESTY (2026-08-15): Yahoo silently DEGRADES the interval when a
 *  range is too deep for it — measured live: CBA.AX range=max&interval=1d came
 *  back as 420 MONTHLY bars from 1991, labelled as if daily. The proxy could
 *  not tell, so neither could the chart. Median bar spacing > 1.8× the
 *  requested interval ⇒ the series is coarser than asked for. Weekend/holiday
 *  gaps do not trip this: the MEDIAN daily gap in a Mon–Fri run is still 86400. */
export function intervalDegraded(candles, interval) {
  const want = INTERVAL_SEC[interval];
  const got = barSpacing(candles);
  if (!want || !got) return false;
  return got > want * 1.8;
}

/** Trim a candle series to the last `n` bars (keeps lengths consistent). */
export function trimCandles(candles, n) {
  return n > 0 && candles.length > n ? candles.slice(candles.length - n) : candles;
}

/**
 * Resilient live price with a source-aware fallback chain.
 * @returns {{price:number|null, source:string|null, delayed:boolean}}
 */
export async function livePrice(sym, assetType, prefer = null) {
  const crypto = assetType ? assetType === "crypto" : isCryptoSymbol(sym);
  if (crypto && prefer !== "yahoo") {
    const b = await fetchBinancePrice(sym);
    if (b != null) return { price: +b, source: "binance", delayed: false };
  }
  // Crypto must be queried on Yahoo as "<base>-USD" (a bare base resolves to a
  // same-named equity); stocks/commodities use the symbol as-is.
  const ySym = crypto ? yahooCryptoSymbol(sym) : sym;
  try {
    const result = await fetchYahooChart(ySym, { interval: "1d", range: "1d" });
    const m = result?.meta;
    const px = m?.regularMarketPrice ?? m?.previousClose ?? null;
    if (px != null) return { price: +px, source: "yahoo", delayed: !crypto };
  } catch (_) { /* give up */ }
  return { price: null, source: null, delayed: false };
}

/** EODHD symbol dialect: ASX is ".AU" (not Yahoo's ".AX"), bare US tickers get
 *  ".US". Indices (^…), forex (=X) and anything already odd return null →
 *  caller falls through to Yahoo. */
export function eodhdSymbol(sym) {
  const s = String(sym || "").toUpperCase();
  if (!s || /[\^=]/.test(s)) return null;
  if (/\.AX$/.test(s)) return s.replace(/\.AX$/, ".AU");
  if (/\./.test(s)) return null;          // other exchange suffixes: not mapped yet
  return s + ".US";
}

/** EODHD EOD candles on the SCAN's adjusted basis (o/h/l/c scaled by
 *  adjusted_close/close, the same maths as the Yahoo adjclose path). EOD data
 *  only — intraday intervals are not on this plan and return []. Any failure
 *  returns [] so the caller falls through to Yahoo (soft fail, incl. no key). */
export async function fetchEodhdCandles(sym, { range = "1y", interval = "1d", key = null, timeout = 9000 } = {}) {
  if (!key || interval !== "1d") return [];
  const es = eodhdSymbol(sym);
  if (!es) return [];
  const YEARS = { "1mo": 1, "3mo": 1, "6mo": 1, "1y": 1, "2y": 2, "5y": 5, "10y": 10, "max": 30 };
  const yrs = YEARS[range] || 1;
  const from = new Date(Date.now() - yrs * 365.25 * 86400 * 1000).toISOString().slice(0, 10);
  try {
    const url = `https://eodhd.com/api/eod/${encodeURIComponent(es)}?api_token=${encodeURIComponent(key)}` +
      `&fmt=json&period=d&from=${from}`;
    const r = await timedFetch(url, { headers: { "Accept": "application/json" } }, timeout);
    if (!r.ok) return [];
    const rows = await r.json();
    if (!Array.isArray(rows)) return [];
    const out = [];
    for (const k of rows) {
      const { open: o, high: h, low: l, close: c, adjusted_close: a, volume: v, date } = k || {};
      if (o == null || h == null || l == null || c == null || !date) continue;
      let f = 1;
      if (a != null && c > 0) { const r2 = a / c; if (Number.isFinite(r2) && r2 > 0) f = r2; }
      out.push({ time: Math.floor(Date.parse(date + "T00:00:00Z") / 1000),
                 open: +(o * f).toFixed(8), high: +(h * f).toFixed(8),
                 low: +(l * f).toFixed(8), close: +(c * f).toFixed(8),
                 volume: v == null ? 0 : Math.round(+v) });
    }
    return out;
  } catch (_) { return []; }
}

/**
 * Resilient candle history, consistent-length across asset types.
 * Crypto → Binance klines (fallback Yahoo); stocks → EODHD when a key is
 * configured (CHART/HISTORY PATH ONLY — the live scan engine has no access to
 * this key by construction), falling back to Yahoo (dual host) on any failure.
 * @returns {{candles:Array, source:string|null, delayed:boolean}}
 */
export async function history(sym, assetType, { range = "1y", interval = "1d", prefer = null, eodKey = null } = {}) {
  const crypto = assetType ? assetType === "crypto" : isCryptoSymbol(sym);
  const want = targetBars(range, interval);

  // `prefer:"yahoo"` skips the Binance pair guess — used by the VIVEK daily chart
  // so a thin coin (no/!=Binance pair) matches the scan's Yahoo <base>-USD series
  // exactly, instead of a wrong pair that throws the price scale off.
  if (crypto && prefer !== "yahoo") {
    const c = await fetchBinanceCandles(sym, { interval, limit: want });
    // Binance is raw exchange data, but crypto has no dividends/splits — its
    // raw and adjusted bases are the same thing, so "adj" is honest here.
    if (c.length) return { candles: trimCandles(c, want), source: "binance", delayed: false, basis: "adj" };
  }
  // Stocks: EODHD first when the owner has installed a key (adjusted basis,
  // 30y depth, official actions). [] on any failure/miss → Yahoo, unchanged.
  if (!crypto && eodKey) {
    const c = await fetchEodhdCandles(sym, { range, interval, key: eodKey });
    if (c.length) {
      return { candles: trimCandles(c, want), source: "eodhd", delayed: !crypto, basis: "adj" };
    }
  }
  // Crypto on Yahoo MUST be "<base>-USD" (a bare base = a same-named equity).
  const ySym = crypto ? yahooCryptoSymbol(sym) : sym;
  try {
    const result = await fetchYahooChart(ySym, { interval, range });
    const c = yahooCandles(result);
    if (c.length) {
      return { candles: trimCandles(c, want), source: "yahoo", delayed: !crypto,
               basis: crypto ? "adj" : (isAdjusted(result) ? "adj" : "raw"),
               recent_div: recentDividend(result) };
    }
  } catch (_) { /* fall through */ }
  return { candles: [], source: null, delayed: false, basis: "raw" };
}

/** Most recent dividend within ~45 days from a Yahoo chart result (events=div),
 *  or null. Recent dividends mean the ADJUSTED series (and every level derived
 *  from it) differs from the raw prices a broker shows. */
export function recentDividend(result, windowDays = 45) {
  const divs = result?.events?.dividends;
  if (!divs) return null;
  const cutoff = Date.now() / 1000 - windowDays * 86400;
  let latest = null;
  for (const k of Object.keys(divs)) {
    const d = divs[k];
    if (d && d.date >= cutoff && (!latest || d.date > latest.date)) latest = d;
  }
  return latest ? { date: latest.date, amount: +latest.amount || 0 } : null;
}

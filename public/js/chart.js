/* =========================================================================
   Chart page — candlestick chart (lightweight-charts) showing the user's own
   system (EMA/SMA + SuperTrend + entry/stop/target levels) on every timeframe.
   Timeframe buttons (D / 3D / W / M / 3M) switch the data client-side.
   ========================================================================= */
(() => {
  "use strict";

  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B+": "var(--grade-b)", "B": "var(--grade-b)", "WATCH": "var(--grade-c)", "C": "var(--grade-c)" };
  const TF_LABEL = { "1H": "1H", "4H": "4H", "1D": "D", "3D": "3D", "1W": "W", "1M": "M", "3M": "3M" };
  // Per-timeframe tooltips — used to flag the 4H view's honest limitations.
  const TF_TITLE = {
    "4H": "≈2y max history (yfinance hourly) · trade levels are the Daily plan",
    "3D": "3-day candles (3 sessions per bar) · trade levels are the Daily plan",
  };
  const TF_ORDER = ["1H", "4H", "1D", "3D", "1W", "1M", "3M"];

  const params = new URLSearchParams(location.search);
  const VALID_MARKETS = new Set(["asx", "nasdaq", "crypto", "scalp"]);
  const marketRaw = (params.get("m") || "asx").toLowerCase();
  const market = VALID_MARKETS.has(marketRaw) ? marketRaw : "asx";
  const symbol = params.get("s") || "";
  // Non-scalp charts are VIVEK charts by default — stale modes in old URLs are
  // ignored. Exception (2026-07-02, Specs re-enabled): an explicit mode=spec is
  // honoured so SPECS cards get the generic EMA chart with the spec row's
  // entry/stop/target lines (fetchResultMeta reads <market>_spec.json off it).
  const urlMode = (params.get("mode") || "").toLowerCase();
  const mode = market === "scalp" ? (urlMode || "scalp")
    : urlMode === "spec" ? "spec" : "vivek";
  // Back-link context: return to wherever the user actually came from
  // (journal / phasemap / specs / mynames / alerts pass src=...) instead of
  // always dumping them on the dashboard. src already drives prev/next lists.
  {
    const SRC_BACK = {
      journal:  ["journal.html",  "← Journal"],
      phasemap: ["phasemap.html", "← Phase Map"],
      specs:    ["specs.html",    "← Specs"],
      mynames:  ["mynames.html",  "← My Names"],
      alerts:   ["alerts.html",   "← Alerts"],
      sectors:  ["sectors.html",  "← News"],
    };
    const back = SRC_BACK[(params.get("src") || "").toLowerCase()];
    const el = document.querySelector(".back-link");
    if (back && el) { el.href = back[0]; el.textContent = back[1]; }
  }
  const isVivek = mode === "vivek";
  const modeDir = mode === "reversal" ? "_rev" : mode === "spec" ? "_spec" : mode === "short" ? "_short" : "";
  const chartFile = `data/charts/${market}${modeDir}/${encodeURIComponent(symbol)}.json`;

  // #71: which lens's watchlist this chart's star belongs to — matches the
  // page the user arrived from (src=…) so a star set here shows up on that
  // lens's list and on ★ My Names. Same unified PM.watch store the dashboard,
  // PhaseMap and Specs pages write to (mirrors to Cloudflare KV with a sync
  // code). scalp/crypto charts fold into the market's vivek watchlist.
  const _src = (params.get("src") || "").toLowerCase();
  const starLens = _src === "phasemap" ? "phasemap"
    : (mode === "spec" || _src === "specs") ? "specs" : "vivek";
  const starMarket = market === "scalp" ? "crypto" : market;
  const MARKET_LABEL = { asx: "ASX", nasdaq: "NASDAQ", crypto: "CRYPTO", scalp: "CRYPTO" };

  // ── PhaseMap overlay — draws the scanned zone bands + sweep/displacement
  // markers ON TOP of the normal chart. The record is ALWAYS fetched
  // (2026-07-02; ?pm=1 kept in old links but no longer required) so zones
  // ride along wherever a setup exists and the chart never dead-ends on a
  // ticker with no live VIVEK plan (e.g. journal names whose setup ended).
  const pmDirWanted = (params.get("dir") || "").toLowerCase();
  let pmRec = null;
  function fetchPhaseMapRec() {
    if (market === "scalp") return Promise.resolve(null);
    const want = decodeURIComponent(symbol || "").toUpperCase();
    // narrations live in a sidecar file since 2026-07-05 (slimmer latest.json)
    return Promise.all([
      fetch(`data/phasemap/${market}/latest.json`, { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : null)),
      fetch(`data/phasemap/${market}/narrations.json`, { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ])
      .then(async ([j, nj]) => {
        const rows = ((j && j.results) || []).filter((r) => String(r.ticker).toUpperCase() === want);
        const rec = rows.find((r) => r.direction === pmDirWanted) || rows[0] || null;
        if (rec && rec.narration == null) {
          // pair-mismatch guard (review H5): a deploy between the two parallel
          // fetches can leave the sidecar on the previous scan — refetch once,
          // cache-busted by the run_date we actually want.
          if (nj && j && nj.run_date && j.run_date && nj.run_date !== j.run_date) {
            try {
              const r2 = await fetch(
                `data/phasemap/${market}/narrations.json?rd=${encodeURIComponent(j.run_date)}`,
                { cache: "reload" });
              if (r2.ok) nj = await r2.json();
            } catch (_) { /* keep what we have */ }
          }
          rec.narration = (((nj && nj.narrations) || {})[`${rec.ticker}|${rec.direction}`]) || "";
        }
        return rec;
      })
      .catch(() => null);
  }

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── live crypto data (Binance public API — keyless, CORS-ok, 24/7) ──────────
  // Every crypto-scalp coin trades as <SYMBOL>USDT on Binance, so we derive the
  // pair generically (same as the journal) instead of hardcoding a list that
  // silently drifts out of date. BINANCE_MAP is only for the rare symbol whose
  // Binance pair differs from <SYMBOL>USDT.
  const BINANCE_MAP = {};
  const cryptoPair = (sym) =>
    BINANCE_MAP[String(sym || "").toUpperCase()] ||
    (String(sym || "").toUpperCase() + "USDT");
  // Intraday live timeframes for crypto (Binance kline intervals).
  const BINANCE_IV    = { "15M": "15m", "30M": "30m", "1H": "1h" };
  const LIVE_TF_ORDER = ["15M", "30M", "1H"];
  // Default sim sizing. Crypto intraday/scalps are sized at $500 margin × 10×
  // leverage (= $5,000 exposure); stocks stay at a flat $1,000 cash position.
  const SIM_CRYPTO_MARGIN   = 500;
  const SIM_CRYPTO_LEVERAGE = 10;
  const SIM_STOCK_SIZE      = 1000;
  // Shared with the simulate buttons / live box so a buy/sell fills at the true
  // live price and every dependent widget reacts on each tick.
  const liveState = { price: null, entryLineFns: null, listeners: [] };
  const onLiveTick = (fn) => { liveState.listeners.push(fn); };

  const posId = params.get("pos");   // open-position id passed from the journal

  // Yahoo Finance tickers for scalp index/commodity instruments — the scanner's
  // internal symbol (NAS100, GOLD…) isn't what Yahoo uses. Shared shape with the
  // journal's map so live (~15-min delayed) quotes resolve consistently.
  const YF_TICKER = {
    NAS100: "^NDX", US30: "^DJI", SPX500: "^GSPC", GER40: "^GDAXI", UK100: "^FTSE", JP225: "^N225",
    GOLD: "GC=F", SILVER: "SI=F", COPPER: "HG=F", PLATINUM: "PL=F", PALLADIUM: "PA=F",
    OIL: "CL=F", WTI: "CL=F", BRENT: "BZ=F", NATGAS: "NG=F", WHEAT: "ZW=F", COFFEE: "KC=F",
  };
  // Resolve the Yahoo ticker for a non-crypto instrument given its asset_type.
  function yfTickerFor(sym, assetType) {
    const up = String(sym || "").toUpperCase();
    if (YF_TICKER[up]) return YF_TICKER[up];
    // Crypto MUST be "<base>-USD" — a bare base (e.g. BDX) is a same-named stock
    // on Yahoo (Becton Dickinson), giving a wildly wrong price + off-scale levels.
    if (assetType === "crypto" || market === "crypto") return up.replace(/-USD$/, "") + "-USD";
    if (assetType === "asx" || market === "asx") return up.includes(".") ? up : up + ".AX";
    return up;   // nasdaq / index symbols Yahoo already knows
  }
  const isCryptoMarket = (assetType) => assetType === "crypto" || market === "crypto";

  // Exchange-prefixed symbol so "Open in TradingView" lands on the RIGHT
  // instrument (a bare "BHP" is ambiguous — TradingView would not pick ASX).
  function tvSymbolFor(sym, assetType) {
    const up = String(sym || "").toUpperCase();
    if (isCryptoMarket(assetType)) return `CRYPTO:${up}USD`;
    if (assetType === "asx" || market === "asx") return `ASX:${up}`;
    return up;   // US — TradingView resolves the bare symbol fine
  }

  // Indicator math mirroring scanner/scalp.py exactly (BB20/2, KC20/1.5×ATR,
  // EMA9/21, TTM momentum = linreg(12) of close−midline, Wilder ATR).
  const SQ_P = 20, SQ_MOM = 12, BB_MULT = 2.0, KC_MULT = 1.5;
  const emaArr = (s, span) => { const k = 2 / (span + 1), o = []; let p;
    for (let i = 0; i < s.length; i++) { p = i === 0 ? s[i] : s[i] * k + p * (1 - k); o[i] = p; } return o; };
  const smaArr = (s, p) => { const o = new Array(s.length).fill(NaN); let sum = 0;
    for (let i = 0; i < s.length; i++) { sum += s[i]; if (i >= p) sum -= s[i - p]; if (i >= p - 1) o[i] = sum / p; } return o; };
  const stdArr = (s, p) => { const o = new Array(s.length).fill(NaN);
    for (let i = p - 1; i < s.length; i++) { let m = 0; for (let k = i - p + 1; k <= i; k++) m += s[k]; m /= p;
      let v = 0; for (let k = i - p + 1; k <= i; k++) { const d = s[k] - m; v += d * d; } o[i] = Math.sqrt(v / p); } return o; };
  const atrArr = (hi, lo, cl, p) => { const tr = [];
    for (let i = 0; i < cl.length; i++) tr[i] = i === 0 ? hi[i] - lo[i]
      : Math.max(hi[i] - lo[i], Math.abs(hi[i] - cl[i - 1]), Math.abs(lo[i] - cl[i - 1]));
    const a = 1 / p, o = []; let pv;
    for (let i = 0; i < tr.length; i++) { pv = i === 0 ? tr[i] : tr[i] * a + pv * (1 - a); o[i] = pv; } return o; };
  const rollMax = (s, p) => { const o = new Array(s.length).fill(NaN);
    for (let i = p - 1; i < s.length; i++) { let m = -Infinity; for (let k = i - p + 1; k <= i; k++) if (s[k] > m) m = s[k]; o[i] = m; } return o; };
  const rollMin = (s, p) => { const o = new Array(s.length).fill(NaN);
    for (let i = p - 1; i < s.length; i++) { let m = Infinity; for (let k = i - p + 1; k <= i; k++) if (s[k] < m) m = s[k]; o[i] = m; } return o; };
  const linregArr = (s, n) => { const o = new Array(s.length).fill(NaN);
    let st = 0, stt = 0; for (let i = 0; i < n; i++) { st += i; stt += i * i; }
    const denom = n * stt - st * st;
    for (let i = n - 1; i < s.length; i++) { let sy = 0, sty = 0;
      for (let j = 0; j < n; j++) { const y = s[i - n + 1 + j]; sy += y; sty += j * y; }
      const slope = (n * sty - st * sy) / denom, intercept = (sy - slope * st) / n;
      o[i] = slope * (n - 1) + intercept; } return o; };

  // Compute the 7 overlay lines + momentum histogram + squeeze markers from bars.
  function computeScalp(bars, nDisp) {
    const hi = bars.map((b) => b.high), lo = bars.map((b) => b.low), cl = bars.map((b) => b.close);
    const mid = smaArr(cl, SQ_P), std = stdArr(cl, SQ_P), kcR = atrArr(hi, lo, cl, SQ_P);
    const bbU = mid.map((m, i) => m + BB_MULT * std[i]), bbL = mid.map((m, i) => m - BB_MULT * std[i]);
    const kcU = mid.map((m, i) => m + KC_MULT * kcR[i]), kcL = mid.map((m, i) => m - KC_MULT * kcR[i]);
    const ema9 = emaArr(cl, 9), ema21 = emaArr(cl, 21);
    const hh = rollMax(hi, SQ_P), ll = rollMin(lo, SQ_P);
    const val = cl.map((c, i) => c - (((hh[i] + ll[i]) / 2 + mid[i]) / 2));
    const mom = linregArr(val, SQ_MOM);

    const start = Math.max(0, bars.length - nDisp);
    const t = (i) => bars[i].time;
    const pack = (arr) => { const out = []; for (let i = start; i < bars.length; i++)
      if (isFinite(arr[i])) out.push({ time: t(i), value: arr[i] }); return out; };
    // order must match the static JSON: BB U/M/L, KC U/L, EMA9, EMA21
    const lineData = [pack(bbU), pack(mid), pack(bbL), pack(kcU), pack(kcL), pack(ema9), pack(ema21)];

    const hist = [];
    for (let i = start; i < bars.length; i++) { const v = mom[i]; if (!isFinite(v)) continue;
      const prev = isFinite(mom[i - 1]) ? mom[i - 1] : v;
      const color = v >= 0 ? (v >= prev ? "#00e6cc" : "#127d70") : (v <= prev ? "#ff3b3b" : "#7d1f1f");
      hist.push({ time: t(i), value: v, color }); }

    const markers = []; let prevOn = null;
    for (let i = start; i < bars.length; i++) {
      const on = isFinite(bbU[i]) && bbU[i] < kcU[i] && bbL[i] > kcL[i];
      if (prevOn !== null && on !== prevOn)
        markers.push(on
          ? { time: t(i), position: "belowBar", color: "#ff5b5b", shape: "circle", size: 1 }
          : { time: t(i), position: "belowBar", color: "#2fd07f", shape: "arrowUp", size: 1, text: "fire" });
      prevOn = on;
    }
    return { lineData, hist, markers };
  }

  // Pull raw klines from Binance and shape them into bar objects.
  function binanceKlines(pair, interval, limit) {
    const url = `https://api.binance.com/api/v3/klines?symbol=${pair}&interval=${interval}&limit=${limit}`;
    return fetch(url, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((rows) => rows.map((k) => ({ time: Math.floor(k[0] / 1000), open: +k[1],
        high: +k[2], low: +k[3], close: +k[4], volume: +k[5] })));
  }

  // Crypto history WITH a fallback: try Binance directly (fast, real-time), and
  // if that's blocked (region/CORS/outage) drop through to the resilient
  // /api/price proxy — which itself tries Binance server-side, then Yahoo. Keeps
  // a crypto chart working even when the browser can't reach Binance.
  function cryptoBars(sym, interval, limit) {
    return binanceKlines(cryptoPair(sym), interval, limit)
      .then((bars) => { if (!bars.length) throw new Error("empty"); return bars; })
      .catch(() =>
        fetch(`/api/price?symbol=${encodeURIComponent(sym)}&type=crypto&range=6mo&interval=${interval}`,
          { cache: "no-store" })
          .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then((j) => (j && j.ok && Array.isArray(j.candles)) ? j.candles : []));
  }

  // Build a chart-page "timeframe" object (candles + volume + 7 overlays + mom)
  // straight from live bars — lets a position chart render with no static JSON.
  function barsToTF(bars) {
    const n = Math.min(120, bars.length), slice = bars.slice(-n);
    const candles = slice.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    const volume  = slice.map((b) => ({ time: b.time, value: Math.round(b.volume),
      color: b.close >= b.open ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.5)" }));
    const c = computeScalp(bars, 120);
    const meta = [["BB Upper", "#4477cc"], ["BB Mid", "#888888"], ["BB Lower", "#4477cc"],
                  ["KC Upper", "#cc7700"], ["KC Lower", "#cc7700"], ["EMA 9", "#ffd23f"], ["EMA 21", "#2fd07f"]];
    const lines = c.lineData.map((data, i) => ({ name: meta[i][0], color: meta[i][1], data }));
    return { candles, volume, histogram: c.hist, squeeze_dots: [], lines };
  }

  // ── graceful live fallback (no saved scan chart) ───────────────────────────
  // Pull OHLCV history from the Yahoo proxy for a non-crypto instrument. Used to
  // draw a real chart when the per-ticker scan JSON is missing or empty, instead
  // of dead-ending on "Chart unavailable".
  function yahooBars(yfTicker, range, interval) {
    return fetch(`/api/price?symbol=${encodeURIComponent(yfTicker)}&range=${range}&interval=${interval}`,
      { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => (j && j.ok && Array.isArray(j.candles)) ? j.candles : []);
  }

  // Build a daily timeframe block (candles + volume + EMA 34/55/89) from plain
  // OHLCV bars — the user's same EMA system, on whatever history we can fetch.
  function barsToStockTF(bars) {
    const candles = bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    const volume  = bars.map((b) => ({ time: b.time, value: Math.round(b.volume || 0),
      color: b.close >= b.open ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.5)" }));
    const cl = bars.map((b) => b.close);
    const mkLine = (span, name, color) => {
      const e = emaArr(cl, span);
      // Drop the warm-up region so the EMA doesn't render as a misleading flat
      // line before it has enough data behind it.
      const data = [];
      for (let i = span - 1; i < bars.length; i++) data.push({ time: bars[i].time, value: e[i] });
      return { name, color, data };
    };
    const lines = bars.length >= 35
      ? [mkLine(34, "EMA 34", "#2fd07f"), mkLine(55, "EMA 55", "#4d9fff"), mkLine(89, "EMA 89", "#a78bfa")]
      : [];
    return { candles, volume, lines };
  }

  // Aggregate bars into fixed-width buckets (e.g. 4h from 1h) for DISPLAY only —
  // candles + volume, not trade-plan logic. OHLC = first open / max high / min
  // low / last close; volume summed.
  function bucketBars(bars, widthSec) {
    const out = []; let cur = null, curKey = null;
    for (const b of bars) {
      const key = Math.floor(b.time / widthSec);
      if (key !== curKey) {
        if (cur) out.push(cur);
        cur = { time: key * widthSec, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume || 0 };
        curKey = key;
      } else {
        cur.high = Math.max(cur.high, b.high);
        cur.low = Math.min(cur.low, b.low);
        cur.close = b.close;
        cur.volume += b.volume || 0;
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  // Daily → weekly OHLCV, bucketed by the Monday of each bar's week (UTC).
  function resampleWeekly(bars) {
    const out = []; let cur = null, curKey = null;
    for (const b of bars) {
      const dow = new Date(b.time * 1000).getUTCDay() || 7;   // 1=Mon … 7=Sun
      const monday = b.time - (dow - 1) * 86400;
      if (monday !== curKey) {
        if (cur) out.push(cur);
        cur = { time: monday, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume || 0 };
        curKey = monday;
      } else {
        cur.high = Math.max(cur.high, b.high);
        cur.low = Math.min(cur.low, b.low);
        cur.close = b.close;
        cur.volume += b.volume || 0;
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  // ── VIVEK plans come from Python (the single source of truth) ───────────────
  // The scanner emits a per-timeframe plan (entry/SL/TP1-3 + the 200 SMA level +
  // trigger state) and a small marker set in each row. The chart no longer
  // recomputes any of that — it normalises the Python plan into the shape the
  // renderer expects and snaps the Python markers onto the drawn bars by date.
  function normalizePlan(p) {
    if (!p) return null;
    return {
      level: p.level, entry: p.entry, stop: p.stop,
      tp1: p.tp1, tp2: p.tp2, tp3: p.tp3, rr: p.rr ?? 0,
      risk: p.risk, scale: p.scale,
      swingHigh: p.swing_high ?? null, swingLow: p.swing_low ?? null,
      structural_tps: p.structural_tps ?? 0,
      armed: !!p.armed, entry_trigger: p.entry_trigger || null,
    };
  }

  // Find the drawn bar matching a Python marker's ISO date. Exact match for daily;
  // for weekly we snap to the bar on/just before the date.
  function barAtDate(bars, dateStr) {
    let best = null;
    for (const b of bars) {
      const d = new Date(b.time * 1000).toISOString().slice(0, 10);
      if (d === dateStr) return b;
      if (d < dateStr) best = b;
    }
    return best;
  }

  // Turn the Python marker list into chart markers (≤2: the 200 SMA reaction and
  // the entry trigger). Deliberately minimal — no swing-pivot thicket.
  function adaptMarkers(pyMarkers, bars, direction) {
    const isLong = direction !== "short";
    const out = [];
    for (const mk of (pyMarkers || [])) {
      const b = barAtDate(bars, mk.date);
      if (!b) continue;
      if (mk.kind === "reaction") {
        out.push({ time: b.time, position: isLong ? "belowBar" : "aboveBar",
                   color: "#ffb020", shape: "circle", text: "200 SMA" });
      } else if (mk.kind === "trigger") {
        out.push({ time: b.time, position: isLong ? "belowBar" : "aboveBar",
                   color: isLong ? "#2fd07f" : "#ff5b5b",
                   shape: isLong ? "arrowUp" : "arrowDown", text: mk.label || "entry" });
      }
    }
    out.sort((a, b) => a.time - b.time);
    return out;
  }

  // Build a VIVEK timeframe DISPLAY block: candles + volume + the moving averages
  // the chart draws (10/20/43/200). Display only — the trade plan/levels/markers
  // come from Python, not from here.
  function barsToVivekTF(bars) {
    const candles = bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    const cl = bars.map((b) => b.close);
    const vols = bars.map((b) => b.volume || 0);
    const volSma = smaArr(vols, 20);                          // recent average volume
    // Volume colouring carries two reads at a glance: a 1.5× spike is a bright
    // cyan bar; otherwise a green tint when volume is rising vs the prior bar,
    // red tint when it's falling. Clean, no extra markers/lines.
    const volume = bars.map((b, i) => {
      const v = vols[i];
      const avg = isFinite(volSma[i]) ? volSma[i] : v;
      const rising = i > 0 ? v >= vols[i - 1] : true;
      const color = (avg > 0 && v >= 1.5 * avg) ? "rgba(0,210,255,0.9)"
                  : rising ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.42)";
      return { time: b.time, value: Math.round(v), color };
    });
    const mkSma = (span, name, color) => {
      const s = smaArr(cl, span);
      const data = [];
      for (let i = span - 1; i < bars.length; i++) if (isFinite(s[i])) data.push({ time: bars[i].time, value: s[i] });
      return { name, color, data };
    };
    const lines = [];
    if (bars.length >= 10)  lines.push(mkSma(10,  "SMA 10",  "#e5e9f0"));  // white
    if (bars.length >= 20)  lines.push(mkSma(20,  "SMA 20",  "#ffd23f"));  // yellow
    if (bars.length >= 43)  lines.push(mkSma(43,  "SMA 43",  "#a78bfa"));  // purple (trend structure)
    if (bars.length >= 200) lines.push(mkSma(200, "SMA 200", "#ffb020"));  // amber — the level
    return { candles, volume, lines };
  }

  // ── Session / weekend shading (UX-20 #9) ───────────────────────────────────
  // Per-bar background tints, drawn with the same full-height hidden-scale
  // histogram trick as the FLASH bands: intraday timeframes get alternating
  // UTC-day banding (day boundaries read at a glance) with weekend bars a
  // shade heavier (crypto's weekend chop stands out); daily/3D charts tint
  // weekend bars only (stocks have none — crypto does). Weekly+ stays clean.
  const SHADE_INTRADAY = { "15M": 1, "30M": 1, "1H": 1, "4H": 1 };
  function shadeRows(candles, key) {
    const out = [];
    const intraday = !!SHADE_INTRADAY[key];
    const daily = key === "1D" || key === "3D";
    if (!intraday && !daily) return out;
    for (const c of candles || []) {
      const dow = new Date(c.time * 1000).getUTCDay();
      const wk = dow === 0 || dow === 6;
      if (intraday) {
        if (wk) out.push({ time: c.time, value: 1, color: "rgba(120,140,190,0.10)" });
        else if (Math.floor(c.time / 86400) % 2) out.push({ time: c.time, value: 1, color: "rgba(110,125,150,0.05)" });
      } else if (wk) {
        out.push({ time: c.time, value: 1, color: "rgba(120,140,190,0.10)" });
      }
    }
    return out;
  }

  // Render a chart purely from live history when no static JSON exists. `meta`
  // (optional) is the scan-results row, which still carries grade / entry / stop
  // / target even when the per-ticker chart file is missing.
  function liveFallback(SYM, meta) {
    const assetType = (meta && meta.asset_type) || (market === "crypto" ? "crypto" : null);
    const dir = (meta && meta.dir) || "LONG";
    const cur = (meta && meta.currency_symbol) || (market === "asx" || assetType === "asx" ? "A$" : "$");
    const d = {
      symbol: SYM, name: (meta && meta.name) || SYM,
      asset_type: assetType,
      price: (meta && meta.price) ?? null,
      grade: (meta && meta.grade) || "", score: (meta && meta.score) || 0,
      score_max: (meta && meta.score_max) || 0, chips: (meta && meta.chips) || [],
      sector: (meta && meta.sector) || "", currency_symbol: cur,
      tv_symbol: (meta && meta.tv_symbol) || SYM, dir,
      rr: (meta && meta.rr) || 0, low_rr: (meta && meta.low_rr) || false,
      rr_text: (meta && meta.rr_text) || "", risk_pct: (meta && meta.risk_pct) ?? null,
      entry: meta && meta.entry, stop: meta && meta.stop, target: meta && meta.target,
      analysis: (meta && meta.analysis)
        || "Live fallback chart — no saved scan data for this ticker, showing recent history.",
      default_tf: "1D", level_lines: [], timeframes: {}, _fallback: true,
    };
    if (d.stop   != null) d.level_lines.push({ price: d.stop,   color: "#ff5b5b", title: "STOP" });
    if (d.entry  != null) d.level_lines.push({ price: d.entry,  color: "#e5e9f0", title: "ENTRY" });
    if (d.target != null) d.level_lines.push({ price: d.target, color: "#2fd07f", title: "TARGET" });

    if (isCryptoMarket(assetType)) {
      cryptoBars(SYM, "1h", 1000)
        .then((bars) => { if (!bars.length) throw new Error("no bars"); d.timeframes["1H"] = barsToTF(bars); d.default_tf = "1H"; render(d); })
        .catch(() => fail(`Couldn't load live data for ${SYM} right now.`));
    } else {
      // Specs ship their own saved daily candles (deterministic, works even
      // when the live proxy is unavailable) — live history is the fallback.
      const specStatic = mode === "spec"
        ? fetch(`data/spec_charts/${market}/${encodeURIComponent(SYM)}.json`,
                { cache: "no-cache" })
            .then((r) => (r.ok ? r.json() : null)).catch(() => null)
        : Promise.resolve(null);
      specStatic.then((js) => {
        const staticBars = ((js && js.candles) || []).map((c) => ({
          time: Math.floor(Date.parse(c.t + "T00:00:00Z") / 1000),
          open: c.o, high: c.h, low: c.l, close: c.c, volume: c.v || 0,
        }));
        const barsP = staticBars.length >= 6
          ? Promise.resolve(staticBars)
          : yahooBars(yfTickerFor(SYM, assetType), "2y", "1d");
        barsP
          .then((bars) => {
            if (bars.length < 6) throw new Error("thin");
            d.timeframes["1D"] = barsToStockTF(bars);
            if (d.price == null) d.price = bars[bars.length - 1].close;
            render(d);
          })
          .catch(() => fail(`No chart data for ${SYM.toUpperCase()} yet, and live history is unavailable right now.`));
      });
    }
  }

  // ── VIVEK (5.0-style) chart — the 200 SMA reaction, not the scalp overlays ──
  // VIVEK has no per-ticker static chart files; it always renders live from daily
  // history, drawing the 200 SMA (the level) + 50 SMA structure and the full
  // Entry / SL / TP1 / TP2 / TP3 ladder as price lines.
  function vivekFallback(SYM, meta) {
    const m = meta || {};
    // The VIVEK levels (grade/200-SMA/entry/SL/TP1-3) MUST come from the saved
    // scan row. If the _vivek.json row is missing or has no levels, say so
    // plainly rather than drawing a level-less "live fallback" that looks broken.
    if (!meta || m.entry == null || m.stop == null || m.tp1 == null) {
      console.warn(`[vivek] no scan row for ${SYM} — not rendering a generic fallback`);
      fail(`No VIVEK setup saved for ${String(SYM).toUpperCase()}. ` +
           `The VIVEK scan may not have run yet, or this ticker isn't a current 200-SMA setup. ` +
           `Open the VIVEK tab and run a scan, then try again.`);
      return;
    }
    const assetType = m.asset_type || (market === "crypto" ? "crypto" : null);
    const dir = m.dir || "LONG";
    const cur = m.currency_symbol || (market === "asx" || assetType === "asx" ? "A$" : "$");
    const tfLabel = m.level_tf === "weekly" ? "200 SMA · Weekly" : m.level_tf === "3d" ? "200 SMA · 3D" : "200 SMA · H4";
    const d = {
      symbol: SYM, name: m.name || SYM, asset_type: assetType,
      price: m.price ?? null,
      grade: m.grade || "", score: m.score || 0, score_max: m.score_max || 0,
      chips: m.chips || [], sector: m.sector || "", currency_symbol: cur,
      plans: m.plans || null,                                // raw per-TF plans (for high-conviction)
      tv_symbol: m.tv_symbol || SYM, dir,
      rr: m.rr || 0, low_rr: m.low_rr || false, rr_text: m.rr_text || "",
      entry: m.entry, stop: m.stop, target: m.tp2,            // headline target = TP2
      tp1: m.tp1, tp2: m.tp2, tp3: m.tp3, scale: m.scale, risk: m.risk,
      level: m.level, level_tf: m.level_tf, confluence: m.confluence,
      analysis: m.analysis || "200 SMA reaction setup (5.0 style).",
      default_tf: "1D", level_lines: [], timeframes: {}, _fallback: true, _vivek: true,
    };
    // Level lines, drawn from the 200 SMA outward: the level itself (amber), the
    // stop (red), entry (white), then the three take-profits (green).
    if (d.level != null) d.level_lines.push({ price: d.level, color: "#ffb020", title: tfLabel });
    if (d.stop  != null) d.level_lines.push({ price: d.stop,  color: "#ff5b5b", title: "SL" });
    if (d.entry != null) d.level_lines.push({ price: d.entry, color: "#e5e9f0", title: "ENTRY" });
    if (d.tp1   != null) d.level_lines.push({ price: d.tp1,   color: "#2fd07f", title: "TP1" });
    if (d.tp2   != null) d.level_lines.push({ price: d.tp2,   color: "#2fd07f", title: "TP2" });
    if (d.tp3   != null) d.level_lines.push({ price: d.tp3,   color: "#2fd07f", title: "TP3" });

    // Build the Daily + Weekly + best-effort 4H views, then render once. The DEEP
    // daily pull drives the Daily candles and a resampled Weekly view; a ~2y
    // hourly pull bucketed to 4H drives the 4H view. Each TF draws its own
    // 10/20/43/200 SMA for DISPLAY, but the trade PLAN (Entry/SL/TP1-3, the level,
    // the trigger) and the markers come straight from the scan row (Python) — the
    // chart never recomputes them. Daily and Weekly EACH carry their OWN Python
    // plan, so the levels genuinely change when you switch between them.
    //
    // 4H has NO server-side plan, so it shows the Daily plan's levels as a clearly
    // labelled reference (approx=true → no mismatched markers; the chart shows a
    // prominent "4H uses Daily levels" notice in both the 2D and 3D views).
    // NOTE: /api/price only whitelists ranges 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/max
    // and intervals incl. 1h/1d — keep fetches on whitelisted values.
    const direction = String(dir).toUpperCase() === "SHORT" ? "short" : "long";
    const plans = m.plans || {};
    const pyMarkers = m.markers || {};
    // Back-compat: data from before per-TF plans (schema < 3) still has a flat
    // headline plan on the row — use it as the 1D plan so old rows still render.
    const headlinePlan = plans["1D"] ? null : {
      level: m.level, entry: m.entry, stop: m.stop, tp1: m.tp1, tp2: m.tp2, tp3: m.tp3,
      rr: m.rr || 0, risk: m.risk, scale: m.scale,
      swing_high: null, swing_low: null,
      structural_tps: (m.detail || {}).structural_tps || 0,
      armed: m.armed, entry_trigger: m.entry_trigger,
    };
    const dailyPlan = plans["1D"] || headlinePlan;
    // approx=true → this TF has no Python plan of its own; it borrows the Daily
    // plan as reference (flagged on the TF block) and shows no mismatched markers.
    const makeTF = (bars, tfKey, planRaw, approx) => {
      const tf = barsToVivekTF(bars);                 // candles + volume + SMAs (display)
      tf.levels = normalizePlan(planRaw);             // the plan (from Python)
      tf.markers = approx ? [] : adaptMarkers(pyMarkers[tfKey], bars, direction);
      tf.approx = !!approx;                           // 4H reuses the Daily plan
      return tf;
    };
    const isCrypto = isCryptoMarket(assetType);
    // Crypto: force the proxy's Yahoo "<base>-USD" series (src=yahoo) so the chart
    // matches the SCAN's instrument/price exactly. A guessed Binance pair can be
    // the wrong token (or missing → a same-named stock), which throws the price
    // scale off and pushes the real levels off-screen.
    const dailyP = isCrypto ? vivekCryptoBars(SYM, "5y", "1d")
                            : yahooBars(yfTickerFor(SYM, assetType), "5y", "1d");
    const intradayP = (isCrypto ? vivekCryptoBars(SYM, "2y", "1h")
                                : yahooBars(yfTickerFor(SYM, assetType), "2y", "1h")).catch(() => []);

    dailyP.then((daily) => {
      if (!daily || daily.length < 6) throw new Error("thin");
      d.timeframes["1D"] = makeTF(daily, "1D", dailyPlan);
      // 3-Day (3D) view: epoch-anchored 3-calendar-day candles (bucketBars), which
      // line up with the engine's "72h" 3-Day resample. If the scan emitted a real
      // 3-Day plan it gets its OWN levels (a first-class timeframe like Daily /
      // Weekly); on older data with no 3-Day plan it falls back to the Daily plan
      // as a labelled reference (approx=true), like the 4H view.
      const d3 = bucketBars(daily, 3 * 86400);
      if (d3.length >= 6) {
        const p3 = plans["3D"];
        d.timeframes["3D"] = makeTF(d3, "3D", p3 || dailyPlan, !p3);
      }
      if (plans["1W"]) {
        const wk = resampleWeekly(daily);
        if (wk.length >= 6) d.timeframes["1W"] = makeTF(wk, "1W", plans["1W"]);
      }
      if (d.price == null) d.price = daily[daily.length - 1].close;
      d.default_tf = "1D";
      return intradayP.then((intraday) => {
        if (intraday && intraday.length >= 24) {
          const h4 = bucketBars(intraday, 4 * 3600);
          // 4H candles/SMAs are real 4H; the trade levels are the Daily plan
          // (reference), labelled on the chart so there's no confusion.
          if (h4.length >= 6) d.timeframes["4H"] = makeTF(h4, "4H", dailyPlan, true);
        }
        console.info(`[vivek] ${SYM} chart TFs: [${Object.keys(d.timeframes).join(", ")}] ` +
                     `(daily=${daily.length}, intraday=${(intraday || []).length}); ` +
                     `plans=[${Object.keys(plans).join(", ")}]`);
        render(d);
      });
    }).catch(() => fail(`No chart data for ${SYM.toUpperCase()} yet, and live history is unavailable right now.`));
  }

  // VIVEK crypto history, forced to the scan-consistent Yahoo <base>-USD series
  // via the proxy (src=yahoo) — never a guessed Binance pair.
  function vivekCryptoBars(sym, range, interval) {
    const usd = String(sym || "").toUpperCase().replace(/-USD$/, "") + "-USD";
    return fetch(`/api/price?symbol=${encodeURIComponent(usd)}&type=crypto&range=${range}&interval=${interval}&src=yahoo`,
      { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => (j && j.ok && Array.isArray(j.candles)) ? j.candles : []);
  }

  // ── PhaseMap-only chart: the ticker has no live VIVEK plan but IS in the
  // PhaseMap scan. Same candle/SMA display + D/3D/W timeframes as a VIVEK
  // chart; the level ladder comes from the PhaseMap zones (drawn in render).
  // Candles prefer the scan's saved daily file (deterministic, works offline),
  // falling back to live history.
  function pmChartBars(SYM) {
    return fetch(`data/phasemap/charts/${market}/${encodeURIComponent(SYM)}.json`,
      { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => ((j && j.candles) || []).map((c) => ({
        time: Math.floor(Date.parse(c.t + "T00:00:00Z") / 1000),
        open: c.o, high: c.h, low: c.l, close: c.c, volume: c.v || 0,
      })))
      .catch(() => []);
  }

  function pmOnlyFallback(SYM, meta, rec) {
    // rec may be NULL — tier-3 fallback: no VIVEK plan, no PhaseMap setup.
    // The chart still renders (candles + SMAs, D/3D/W) so a ticker link
    // never dead-ends — journal names whose setup ended stay clickable.
    const m = meta || {};
    const assetType = m.asset_type || (market === "crypto" ? "crypto" : null);
    const bull = rec ? rec.direction === "bullish" : true;
    const d = {
      symbol: String(SYM).toUpperCase(), name: m.name || (rec && rec.name) || SYM,
      asset_type: assetType,
      price: (rec && rec.metrics && rec.metrics.close) != null ? rec.metrics.close
           : (m.price != null ? m.price : null),
      grade: rec ? (String(rec.tier || "").toUpperCase() === "WATCH" ? "WATCH" : (rec.tier || "")) : "",
      score: 0, score_max: 0,
      chips: rec ? [rec.state.replace("_", " "), rec.regime].concat(rec.tags || []) : [],
      sector: m.sector || (rec && rec.sector) || "",
      currency_symbol: m.currency_symbol || (market === "asx" ? "A$" : "$"),
      tv_symbol: m.tv_symbol || SYM, dir: rec ? (bull ? "LONG" : "SHORT") : "",
      analysis: (rec && rec.narration) ||
        "No live VIVEK or PhaseMap setup on this name right now — showing the raw chart (candles + SMAs) so every ticker always opens.",
      default_tf: "1D", level_lines: [], timeframes: {},
      _fallback: true, _vivek: false, _pm: true,
    };
    // Zone-native sim plan (2026-07-03): a PhaseMap setup is paper-tradeable —
    // entry at the current price, stop at the hard invalidation's outer edge,
    // target at the first live target zone's mid. The Simulate buttons and
    // their auto-close-at-stop/target machinery work exactly like VIVEK's.
    if (rec && rec.zones && rec.zones.length && d.price != null) {
      const c = d.price;
      const hard = rec.zones.find((z) => z.id === "inv_hard");
      // first live target whose MID is beyond price in the trade direction —
      // a wide merged band can straddle price (AGR), which would hand a short
      // a target above its entry and auto-close it instantly
      const tgt = rec.zones.find((z) => z.type === "TARGET" && z.status !== "CONSUMED" &&
        (bull ? (z.low + z.high) / 2 > c : (z.low + z.high) / 2 < c));
      if (hard && tgt) {
        const stop = bull ? hard.low : hard.high;
        const target = (tgt.low + tgt.high) / 2;
        const risk = bull ? c - stop : stop - c;
        const rew = bull ? target - c : c - target;
        if (risk > 0 && rew > 0) {   // only publish a plan that makes sense
          d.entry = c;
          d.stop = stop;
          d.target = target;
          d.tp1 = target;
          d.rr = Math.round((rew / risk) * 100) / 100;
          d._zonePlan = true;
        }
      }
    }
    const liveDaily = () => (isCryptoMarket(assetType)
      ? vivekCryptoBars(SYM, "5y", "1d")
      : yahooBars(yfTickerFor(SYM, assetType), "5y", "1d"));
    const intradayP = (isCryptoMarket(assetType)
      ? vivekCryptoBars(SYM, "2y", "1h")
      : yahooBars(yfTickerFor(SYM, assetType), "2y", "1h")).catch(() => []);
    pmChartBars(d.symbol)
      .then((bars) => (bars.length >= 6 ? bars : liveDaily()))
      .then((daily) => {
        if (!daily || daily.length < 6) throw new Error("thin");
        d.timeframes["1D"] = barsToVivekTF(daily);
        const d3 = bucketBars(daily, 3 * 86400);
        if (d3.length >= 6) d.timeframes["3D"] = barsToVivekTF(d3);
        const wk = resampleWeekly(daily);
        if (wk.length >= 6) d.timeframes["1W"] = barsToVivekTF(wk);
        if (d.price == null) d.price = daily[daily.length - 1].close;
        // 4H parity with VIVEK charts (2026-07-03) — real 4H candles/SMAs
        // bucketed from live hourly history; silently absent when the live
        // feed can't serve hourly data.
        return intradayP.then((intraday) => {
          if (intraday && intraday.length >= 24) {
            const h4 = bucketBars(intraday, 4 * 3600);
            if (h4.length >= 6) d.timeframes["4H"] = barsToVivekTF(h4);
          }
          render(d);
        });
      })
      .catch(() => fail(`No chart data for ${String(SYM).toUpperCase()} yet, and live history is unavailable right now.`));
  }

  // A purple "ENTRY" marker, snapped to the bar the fill falls inside so it lines
  // up on whatever interval is showing (15m/30m/1h).
  function buildEntryMarker(epoch, intervalSec, dir) {
    if (!epoch || !intervalSec) return null;
    const t = Math.floor(epoch / intervalSec) * intervalSec;
    return { time: t, position: dir === "long" ? "belowBar" : "aboveBar",
      color: "#a78bfa", shape: dir === "long" ? "arrowUp" : "arrowDown", text: "ENTRY" };
  }

  function fmt(v, cur) {
    if (v == null || isNaN(v)) return "—";
    const a = Math.abs(v);
    const dp = a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : a >= 0.001 ? 6 : 8;
    return (cur || "") + v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }

  // #77: drop the loading skeleton once anything real (a header, a paint, or an
  // error) is on screen. Idempotent — every render path calls header(), which
  // calls this; fail() calls it too.
  function hideSkeleton() {
    const sk = document.getElementById("chart-skeleton");
    if (sk) sk.remove();
  }

  function fail(msg) {
    hideSkeleton();
    const offline = typeof navigator !== "undefined" && navigator.onLine === false;
    const h = document.createElement("header");
    h.className = "chart-top";
    h.innerHTML = `<a class="back-link" href="index.html">← Dashboard</a>`;
    const d = document.createElement("div");
    d.className = "chart-error" + (offline ? " is-offline" : "");
    const tvSym = symbol
      ? encodeURIComponent(market === "crypto" ? `CRYPTO:${symbol}USD` : market === "asx" ? `ASX:${symbol}` : symbol)
      : "";
    // #78: an offline failure is a distinct, non-alarming state — say so plainly
    // rather than implying the chart is broken.
    const head = offline ? "You're offline" : "Chart unavailable";
    const body = offline
      ? "This chart isn't in the offline cache yet. Reconnect and it'll load."
      : esc(msg);
    d.innerHTML = `<h2>${head}</h2><p>${body}</p>` +
      `<p><button class="tv-btn" id="chart-retry" type="button">↻ Retry</button></p>` +
      (symbol && !offline ? `<p><a class="tv-link" href="https://www.tradingview.com/chart/?symbol=${tvSym}" target="_blank" rel="noopener">View ${esc(symbol.toUpperCase())} on TradingView →</a></p>` : "");
    document.body.replaceChildren(h, d);
    // A hiccuping live proxy shouldn't require a manual URL re-entry.
    const btn = document.getElementById("chart-retry");
    if (btn) btn.addEventListener("click", () => location.reload());
  }

  // #78: offline banner — reflects connectivity live. The chart still shows the
  // last loaded data (SW-cached); this just tells the user why live prices and
  // the "next setup" arrows may be quiet.
  function initOffline() {
    const banner = document.getElementById("offline-banner");
    if (!banner) return;
    const sync = () => { banner.hidden = navigator.onLine !== false; };
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    sync();
  }

  // #76: a CANONICAL shareable link — just the identity params (market, symbol,
  // lens context), dropping the transient filter/sort state (flt=…) that only
  // makes sense to the tab you came from. Copies to the clipboard.
  function canonicalURL() {
    const q = new URLSearchParams();
    q.set("m", market);
    if (symbol) q.set("s", decodeURIComponent(symbol));
    if (mode === "spec") q.set("mode", "spec");
    const dir = params.get("dir"); if (dir) q.set("dir", dir);
    const src = params.get("src"); if (src) q.set("src", src);
    return `${location.origin}${location.pathname}?${q.toString()}`;
  }
  function wireShare() {
    const btn = document.getElementById("cf-share");
    if (!btn || btn._wired) return;
    btn._wired = true;
    btn.addEventListener("click", async () => {
      const url = canonicalURL();
      const done = (ok) => {
        const old = btn.textContent;
        btn.textContent = ok ? "✓ Link copied" : "⤴ " + url;
        setTimeout(() => { btn.textContent = old; }, ok ? 1600 : 3500);
      };
      try {
        if (navigator.share && /Mobi|Android|iPhone|iPad/.test(navigator.userAgent)) {
          await navigator.share({ title: `${decodeURIComponent(symbol)} — Vivek 5.0`, url });
          return;
        }
        await navigator.clipboard.writeText(url); done(true);
      } catch (_) { done(false); }
    });
  }

  // #76: PNG export — lightweight-charts' takeScreenshot() gives the rendered
  // canvas; we download it as <SYM>_<tf>.png. Wired from render() so it has the
  // live chart handle.
  function wirePng(chart, d, getTF) {
    const btn = document.getElementById("cf-png");
    if (!btn || !chart || typeof chart.takeScreenshot !== "function") { if (btn) btn.hidden = true; return; }
    if (btn._wired) return;
    btn._wired = true;
    btn.addEventListener("click", () => {
      try {
        const cnv = chart.takeScreenshot();
        const name = `${(d.symbol || symbol).toUpperCase()}_${(getTF && getTF()) || ""}.png`.replace(/_\.png$/, ".png");
        const dl = (href) => { const a = document.createElement("a"); a.href = href; a.download = name; a.click(); };
        if (cnv.toBlob) cnv.toBlob((b) => { const u = URL.createObjectURL(b); dl(u); setTimeout(() => URL.revokeObjectURL(u), 4000); });
        else dl(cnv.toDataURL("image/png"));
      } catch (_) {}
    });
  }

  // High conviction (matches the dashboard): a WEEKLY reclaim that's A/A+ or has
  // strong structure — the cleanest, lowest-drawdown cell in the backtest.
  function isHighConviction(d) {
    // Prefer the raw scan plan (always present in the JSON); fall back to the
    // built Weekly timeframe. A genuine weekly reclaim that's A/A+ or structured.
    const tf = d && d.timeframes && d.timeframes["1W"];
    const p = (d && d.plans && d.plans["1W"]) || (tf && !tf.approx && tf.levels) || null;
    if (!p || !p.armed || p.entry_trigger !== "reclaim") return false;
    return d.grade === "A+" || d.grade === "A" || (p.structural_tps || 0) >= 2;
  }

  // REIT / ETF / LIC / managed fund — mirrors scanner/broker/vivek_bot.py. The
  // bot won't trade these and most CFD brokers (e.g. CMC) don't list them.
  const FUND_NAME_KW = ["REIT", "TRUST", "FUND", "ETF", "SPDR", "ISHARES",
    "VANGUARD", "BETASHARES", "VANECK", "GLOBAL X"];
  const FUND_SECTOR_HINTS = ["reit", "real estate investment trust"];
  const NON_OP_SECTORS = new Set(["not applicable", "not applic", "n/a"]);
  function isFundReit(d) {
    const sector = String((d && d.sector) || "").trim().toLowerCase();
    if (FUND_SECTOR_HINTS.some((h) => sector.includes(h))) return true;
    if (NON_OP_SECTORS.has(sector)) return true;
    const name = String((d && (d.name || d.symbol)) || "").toUpperCase();
    return FUND_NAME_KW.some((kw) => name.includes(kw));
  }

  // Dividend honesty: scan levels come from a dividend-ADJUSTED series, so a
  // recent ex-div means every level differs from the raw prices your broker
  // shows. Best-effort, stocks only (the proxy edge-caches this request).
  function checkRecentDividend(d) {
    const el = $("#ct-divadj");
    if (!el || d.asset_type === "crypto" || !d.symbol) return;
    fetch(`/api/price?symbol=${encodeURIComponent(yfTickerFor(String(d.symbol).toUpperCase(), d.asset_type))}&range=1mo&interval=1d`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        const div = j && j.recent_div;
        if (!div || !div.date) return;
        const when = new Date(div.date * 1000).toLocaleDateString("en-AU",
          { day: "numeric", month: "short", timeZone: "Australia/Melbourne" });
        el.textContent = `Ⓓ DIV-ADJ ${when}`;
        el.title = `Went ex-dividend ${when} (${div.amount ? "$" + div.amount : "amount n/a"}). ` +
          `Chart prices and levels are dividend-adjusted — your broker's raw prices ` +
          `(e.g. CMC) will sit slightly higher than these levels.`;
        el.hidden = false;
      })
      .catch(() => {});
  }

  // #71: the header watchlist star — same unified PM.watch store as every
  // other page, namespaced to the lens the user came from. Persists locally
  // even without a sync code; mirrors to the cloud when one is set.
  function wireStar(d) {
    const btn = $("#ct-star");
    const w = window.PM && PM.watch;
    if (!btn || !w) return;
    const SYM = (d.symbol || symbol).toUpperCase();
    const paint = () => {
      const on = w.has(starLens, starMarket, SYM);
      btn.textContent = on ? "★" : "☆";
      btn.classList.toggle("is-on", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.title = (on ? "Remove from" : "Add to") +
        " watchlist — starred names stay monitored even after the setup ends";
    };
    btn.hidden = false;
    paint();
    if (!btn._wired) {
      btn._wired = true;
      btn.addEventListener("click", () => {
        w.toggle(starLens, starMarket, SYM, {
          symbol: SYM, name: d.name || d.symbol, grade: d.grade || null,
          dir: d.dir || null, price: d.price != null ? d.price : null,
        });
        paint();
      });
    }
  }

  function header(d) {
    const cur = d.currency_symbol || "";
    hideSkeleton();
    $("#ct-sym").textContent = d.symbol;
    document.title = `${d.symbol} — Vivek 5.0`;
    wireStar(d);
    const mk = $("#ct-market");
    if (mk) {
      const lbl = MARKET_LABEL[market] || market.toUpperCase();
      mk.textContent = lbl; mk.dataset.mk = starMarket; mk.hidden = false;
    }
    if (d.sector) { const s = $("#ct-sector"); s.textContent = d.sector; s.hidden = false; }
    const fw = $("#ct-fundwarn");
    if (fw) fw.hidden = !isFundReit(d);
    checkRecentDividend(d);
    $("#ct-price").textContent = fmt(d.price, cur);
    const g = $("#ct-grade"); g.textContent = d.grade; g.style.color = GRADE_VAR[d.grade] || "var(--grade-c)";
    const dirEl = $("#ct-dir");
    if (d.dir) {
      const isShort = d.dir.toUpperCase() === "SHORT";
      dirEl.textContent = d.dir;
      dirEl.classList.toggle("short", isShort);
      dirEl.classList.toggle("long", !isShort);   // explicit colour both ways (LONG green / SHORT red)
    }
    // plain-fallback charts (no setup anywhere) have no direction — hide the chip
    dirEl.hidden = !d.dir;
    const hc = $("#ct-hiconv");
    if (hc) hc.hidden = !isHighConviction(d);
    $("#ct-chips").innerHTML = (d.chips || [])
      .map((c) => `<span class="chip${String(c).startsWith("WEEKLY") ? " weekly" : ""}">${esc(c)}</span>`).join("");
  }

  // VIVEK footer — the 5.0 metric set for a GIVEN set of levels (so it can be
  // re-rendered when the user switches timeframe). `tfKey` labels the 200 SMA.
  function renderVivekFooter(d, lv, tfKey) {
    const cur = d.currency_symbol || "";
    const metric = (label, val, cls) =>
      `<div class="cf-metric"><span class="cfm-label">${label}</span><span class="cfm-val ${cls || ""}">${val}</span></div>`;
    const sc = (d.scale || [0.25, 0.50, 0.15]).map((x) => Math.round(x * 100));
    // A "reference" TF borrows the Daily plan (no plan of its own) — that's 4H
    // always, and 3D only on older data without a real 3-Day plan. Flagged via
    // the TF block's `approx`, set when the chart built it.
    const isRef = !!((d.timeframes && d.timeframes[tfKey]) || {}).approx;
    const tfName = tfKey === "1W" ? "Weekly" : tfKey === "4H" ? "4H" : tfKey === "3D" ? "3-Day" : "Daily";
    const tfCode = tfKey === "1W" ? "W" : tfKey === "4H" ? "4H" : tfKey === "3D" ? "3D" : "D";
    const tfTxt = `200 SMA (${isRef ? "D·ref" : tfCode})`;
    const rr = lv.rr || 0;
    // Trigger state — ARMED (a trigger fired) vs WATCHING (near the level only).
    const trig = lv.entry_trigger ? lv.entry_trigger.toUpperCase() : null;
    const setupVal = lv.armed ? `ARMED · ${trig || "trigger"}` : "WATCHING";
    $("#cf-metrics").innerHTML = [
      metric("Setup", setupVal, lv.armed ? "green" : "amber"),
      metric(tfTxt, fmt(lv.level, cur), "amber"),
      metric("Entry", fmt(lv.entry, cur)),
      metric("SL", fmt(lv.stop, cur), "red"),
      metric(`TP1 · ${sc[0]}%`, fmt(lv.tp1, cur), "green"),
      metric(`TP2 · ${sc[1]}%`, fmt(lv.tp2, cur), "green"),
      metric(`TP3 · ${sc[2]}%`, fmt(lv.tp3, cur), "green"),
      metric("R:R → TP2", rr.toFixed(2), rr && rr < 1.5 ? "red" : "green"),
      metric("Grade", `${d.grade} · ${d.score}/${d.score_max}`),
    ].join("");
    const trigTxt = lv.armed
      ? `Entry is the ${trig} trigger price on the ${isRef ? "Daily" : tfName} timeframe — a fired setup. `
      : `WATCHING: price is near the 200 SMA but no trigger has fired yet; entry shown is indicative. `;
    const refTxt = isRef
      ? `${tfName} view: its candles/SMAs are real ${tfName}, but the trade levels shown are the Daily plan (no separate ${tfKey} plan). `
      : "";
    $("#cf-analysis").textContent =
      (d.analysis ? d.analysis + "  " : "") + refTxt + trigTxt +
      "SL management: at TP1 → break-even · at TP2 → below new support · SL never moves against the trade.";
    if (d.low_rr) $("#cf-lowrr").innerHTML = `<span class="chip warn">LOW R:R (${d.rr_text})</span>`;
    $("#cf-tv").href = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbolFor(d.symbol, d.asset_type))}`;
    // Cross-check note: our prices/SMAs are dividend-adjusted; tell the user how
    // to make TradingView match (else dividend-payers read a few % off).
    const note = $("#cf-tvnote");
    if (note) {
      note.hidden = false;
      note.textContent = "Levels use dividend-adjusted prices. On TradingView, enable “Adjust data for dividends” + set SMA to 43 for best alignment.";
    }
  }

  function footer(d) {
    const cur = d.currency_symbol || "";
    const metric = (label, val, cls) =>
      `<div class="cf-metric"><span class="cfm-label">${label}</span><span class="cfm-val ${cls || ""}">${val}</span></div>`;

    // VIVEK: render the default-TF levels now; applyTF re-renders per timeframe.
    if (d._vivek) {
      renderVivekFooter(d, d, d.default_tf || "1D");
      return;
    }

    $("#cf-metrics").innerHTML = [
      metric("Entry", fmt(d.entry, cur)),
      metric("Stop", fmt(d.stop, cur), "red"),
      metric("Target", fmt(d.target, cur), "green"),
      metric("Trail", "after entry", "amber"),
      metric("Score", `${d.score}/${d.score_max}`),
      metric("Risk", d.risk_pct != null ? `${d.risk_pct}%` : "—", "red"),
      metric("R:R", (d.rr || 0).toFixed(2), d.low_rr ? "red" : "green"),
    ].join("");
    $("#cf-analysis").textContent = d.analysis || "";
    if (d.low_rr) $("#cf-lowrr").innerHTML = `<span class="chip warn">LOW R:R (${d.rr_text})</span>`;
    $("#cf-tv").href = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(d.tv_symbol || d.symbol)}`;
  }

  // ----------------------------------------------------------- simulate buy/sell
  // Writes straight into the same localStorage the "My Trades" journal reads
  // (gbs:manual_journal), so a simulated entry/exit shows up there with full P&L.
  const MJ_KEY = "gbs:manual_journal";
  // Prefer the shared GBSSync store (handles schema + optional cloud sync); fall
  // back to plain localStorage if the module didn't load for some reason.
  function mjLoad() {
    if (window.GBSSync) return window.GBSSync.load();
    try { const r = localStorage.getItem(MJ_KEY); if (r) return JSON.parse(r); } catch (_) {}
    return { capital: 10000, brokerage: 10, stock_capital: 10000, stock_brokerage: 10, crypto_capital: 10000, crypto_brokerage: 5, trades: [] };
  }
  function mjSave(x) {   // local + cloud — user actions only (Simulate Buy/Sell)
    if (window.GBSSync) { window.GBSSync.saveLocal(x); window.GBSSync.syncOutDebounced(); return; }
    localStorage.setItem(MJ_KEY, JSON.stringify(x));
  }
  // Local-only — for rule-computed auto-closes (stop/target hit while the chart
  // is open). Each device re-derives these, so they must not spam the cloud.
  function mjSaveLocal(x) {
    if (window.GBSSync) { window.GBSSync.saveLocal(x); return; }
    localStorage.setItem(MJ_KEY, JSON.stringify(x));
  }
  function mjUid()   { return Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }
  const nowDate = () => new Date().toLocaleDateString("en-CA");          // YYYY-MM-DD (local)
  const nowTime = () => new Date().toTimeString().slice(0, 5);            // HH:MM (local)
  // Tidy a (possibly fractional, possibly large) unit count for display.
  const fmtUnits = (n) => {
    if (n == null || isNaN(n)) return "—";
    const a = Math.abs(n);
    if (a >= 1000) return Math.round(n).toLocaleString();
    if (a >= 1)    return (+n.toFixed(2)).toString();
    return (+n.toFixed(4)).toString();
  };
  const levTag = (t) => (t && t.leverage > 1 ? ` <small>×${t.leverage}</small>` : "");

  // Recompute TP1/2/3 as fresh R-multiples from the ACTUAL entry, so a late or
  // chased fill still gets three real targets sized to its own risk (|entry −
  // stop|). We preserve the plan's R-multiples when they're sane and strictly
  // increasing; otherwise fall back to 1R / 2R / 3R. Returns the plan targets
  // unchanged if there's no usable stop to measure risk against.
  function entryRelTargets(isLong, entry, stop, planEntry, planTps) {
    const plan = (planTps || []).slice(0, 3);
    const risk = stop != null ? Math.abs(entry - stop) : 0;
    if (!(risk > 0)) return plan;
    const planRisk = planEntry != null && stop != null ? Math.abs(planEntry - stop) : 0;
    const fallback = [1, 2, 3];
    const out = [];
    let prev = 0;
    for (let i = 0; i < 3; i++) {
      let mult = fallback[i];
      const tp = plan[i];
      if (planRisk > 0 && tp != null) {
        const m = (isLong ? tp - planEntry : planEntry - tp) / planRisk;
        if (m > prev + 0.05) mult = m;          // use the plan's ratio when it's valid + rising
      }
      prev = mult;
      out.push(+(isLong ? entry + mult * risk : entry - mult * risk).toFixed(8));
    }
    return out;
  }

  // ── Yahoo Finance proxy for ASX / NASDAQ live prices ──────────────────────
  async function fetchStockQuote(sym, assetType) {
    const ticket = assetType === "asx" ? sym + ".AX" : sym;
    try {
      const r = await fetch(`/api/quote?sym=${encodeURIComponent(ticket)}`);
      if (!r.ok) return null;
      const j = await r.json();
      return j.price != null ? j.price : null;
    } catch (_) { return null; }
  }

  // Real-money position sizer: your account + risk% against THIS setup's
  // entry/stop → exact share count for the broker order. Persisted locally.
  function wireSizeCalc(d) {
    const host = $("#cf-mysize");
    if (!host) return;
    if (d.entry == null || d.stop == null) { host.hidden = true; return; }
    const cur = d.currency_symbol || "$";
    const LS_ACCT = "gbs:mysize-acct", LS_RISK = "gbs:mysize-risk";
    let acct = +(localStorage.getItem(LS_ACCT) || 0);
    let risk = +(localStorage.getItem(LS_RISK) || 1);
    host.hidden = false;
    host.innerHTML =
      `<span class="ms-label">💰 My size:</span>` +
      `<label>acct $<input id="ms-acct" type="number" min="0" step="100" value="${acct || ""}" placeholder="10000"></label>` +
      `<label>risk <input id="ms-risk" type="number" min="0.1" max="5" step="0.1" value="${risk}">%</label>` +
      `<span class="ms-out" id="ms-out"></span>`;
    const out = $("#ms-out");
    const calc = () => {
      acct = +($("#ms-acct").value || 0);
      risk = +($("#ms-risk").value || 0);
      try { localStorage.setItem(LS_ACCT, String(acct)); localStorage.setItem(LS_RISK, String(risk)); } catch (_) {}
      const dist = Math.abs(d.entry - d.stop);
      if (!(acct > 0) || !(risk > 0) || !(dist > 0)) { out.textContent = ""; return; }
      const riskD = acct * risk / 100;
      const shares = riskD / dist;
      const units = shares >= 100 ? Math.floor(shares) : +shares.toFixed(4);
      const notional = shares * d.entry;
      out.innerHTML = `→ <strong>${units.toLocaleString()}</strong> units ` +
        `≈ ${cur}${Math.round(notional).toLocaleString()} notional · ` +
        `1R = ${cur}${riskD.toFixed(0)}${notional > acct ? ` · ×${(notional / acct).toFixed(1)} leverage` : ""}`;
    };
    $("#ms-acct").addEventListener("input", calc);
    $("#ms-risk").addEventListener("input", calc);
    calc();
  }

  function wireSim(d) {
    const buyBtn  = $("#cf-sim-buy");
    const sellBtn = $("#cf-sim-sell");
    const statusEl = $("#cf-sim-status");
    if (!buyBtn || !sellBtn) return;
    // No plan anywhere (tier-3 plain chart) → simulating would journal a trade
    // with no stop/target. Hide the buttons instead of logging nonsense.
    if (d.entry == null || d.stop == null) {
      buyBtn.hidden = true;
      sellBtn.hidden = true;
      return;
    }
    buyBtn.hidden = false;
    sellBtn.hidden = false;

    const cur     = d.currency_symbol || "";
    const dir     = (d.dir || "LONG").toLowerCase() === "short" ? "short" : "long";
    const SYM     = (d.symbol || symbol).toUpperCase();
    // Crypto is identified by the row's asset_type — NOT by market==="scalp",
    // because the scalp universe also contains commodities (GOLD, OIL) and ASX
    // stocks (BHP, CBA) which must NOT be sized/priced as 10× crypto.
    const isCrypto = d.asset_type === "crypto" || market === "crypto";
    const simBrok  = (data) => isCrypto ? data.crypto_brokerage : data.stock_brokerage;

    // Re-label AND re-colour the buttons to match the setup direction: the entry
    // action is coloured by its side (long entry = green ▲, short entry = red ▼),
    // and the close is the opposite (cover a short = green ▲, sell a long = red ▼).
    const isShort = dir === "short";
    buyBtn.textContent  = isShort ? "▼ Simulate Short" : "▲ Simulate Buy";
    sellBtn.textContent = isShort ? "▲ Cover / Close"  : "▼ Simulate Sell";
    buyBtn.classList.toggle("sim-sell", isShort);   // short entry → red
    buyBtn.classList.toggle("sim-buy", !isShort);
    sellBtn.classList.toggle("sim-buy", isShort);   // cover → green
    sellBtn.classList.toggle("sim-sell", !isShort);

    const openSimTrade = () =>
      mjLoad().trades.find((t) => t.sim && t.status === "open" &&
        (t.symbol || "").toUpperCase() === SYM && t.direction === dir);

    function refresh(livePx) {
      const t = openSimTrade();
      if (!t) {
        buyBtn.disabled = false; sellBtn.disabled = true;
        statusEl.className = "sim-status";
        statusEl.textContent = "";
        return;
      }
      buyBtn.disabled = true; sellBtn.disabled = false;
      const px = livePx || liveState.price;
      if (px) {
        const m      = dir === "long" ? 1 : -1;
        const data   = mjLoad();
        const brok   = simBrok(data);
        const unreal = t.shares * m * (px - t.entry);  // unrealised, before close brok
        const net    = unreal - 2 * brok;               // what you'd bank if closed now
        const pnlCls = net >= 0 ? " live" : " neg";
        const sign   = net >= 0 ? "+" : "";
        statusEl.className = `sim-status${pnlCls}`;
        statusEl.innerHTML =
          `● ${dir.toUpperCase()} @ ${fmt(t.entry, cur)} &nbsp;·&nbsp; ` +
          `Live P&L <strong>${sign}${cur}${net.toFixed(2)}</strong> &nbsp;·&nbsp; ` +
          `${fmt(px, cur)} now`;
      } else {
        statusEl.className = "sim-status live";
        statusEl.textContent = `● In ${dir} @ ${fmt(t.entry, cur)} · ${fmtUnits(t.shares)} units${t.leverage > 1 ? ` ×${t.leverage}` : ""}`;
      }
    }

    function checkAutoClose(t, livePx) {
      const m        = dir === "long" ? 1 : -1;
      const stopped  = t.stop   != null && (dir === "long" ? livePx <= t.stop   : livePx >= t.stop);
      const targeted = t.target != null && (dir === "long" ? livePx >= t.target : livePx <= t.target);
      if (!stopped && !targeted) return false;
      const data = mjLoad();
      const rec  = data.trades.find((x) => x.id === t.id);
      if (!rec || rec.status === "closed") return true;
      // Honest fills: a stop that gaps through fills at the worse live price
      // (never better than the stop); a target never credits overshoot. This
      // keeps the simulated P&L from being optimistic vs. real execution.
      const fillPx = stopped
        ? (dir === "long" ? Math.min(t.stop, livePx) : Math.max(t.stop, livePx))
        : t.target;
      rec.status = "closed"; rec.exit = fillPx; rec.exit_date = nowDate(); rec.exit_time = nowTime();
      rec.mtime = Date.now();
      mjSaveLocal(data);   // rule-computed auto-close → local only
      if (liveState.entryLineFns) liveState.entryLineFns.remove();
      const pnl = t.shares * m * (fillPx - t.entry) - 2 * simBrok(data);
      statusEl.className = `sim-status${pnl >= 0 ? " live" : " neg"}`;
      statusEl.textContent = `${stopped ? "🛑 Stopped out" : "🎯 Target hit"} @ ${fmt(fillPx, cur)} · P&L ${pnl >= 0 ? "+" : ""}${cur}${pnl.toFixed(2)}`;
      buyBtn.disabled = false; sellBtn.disabled = true;
      return true;
    }
    // Hook into the live price stream — auto-close on stop/target, then refresh P&L.
    onLiveTick((px) => {
      const t = openSimTrade();
      if (!t) return;
      if (checkAutoClose(t, px)) return;
      refresh(px);
    });

    // Always fill at the TRUE live price. Never fall back to the scan price
    // (d.entry/d.price), which can be hours stale — that was booking trades at a
    // phantom entry so the journal showed an instant loss the moment it marked
    // the position against the real live price.
    async function livePriceNow() {
      if (+liveState.price) return +liveState.price;     // streaming feed already has it
      if (isCrypto) {
        try {
          const r = await fetch(
            `https://api.binance.com/api/v3/ticker/price?symbol=${encodeURIComponent(cryptoPair(SYM))}`,
            { cache: "no-store" });
          if (r.ok) { const j = await r.json(); if (j && j.price != null) return +j.price; }
        } catch (_) {}
        return null;
      }
      return await fetchStockQuote(SYM, market === "asx" ? "asx" : "nasdaq");
    }

    buyBtn.addEventListener("click", async () => {
      if (openSimTrade()) return;
      buyBtn.disabled = true;
      statusEl.className = "sim-status"; statusEl.textContent = "Fetching live price…";
      const px = await livePriceNow();
      if (!px) {
        statusEl.textContent = "Couldn't fetch a live price — try again in a moment.";
        buyBtn.disabled = false;
        return;
      }
      const margin   = isCrypto ? SIM_CRYPTO_MARGIN   : SIM_STOCK_SIZE;
      const leverage = isCrypto ? SIM_CRYPTO_LEVERAGE : 1;
      const exposure = margin * leverage;
      const data  = mjLoad();
      const isLong = dir === "long";
      // VIVEK: book the SL/TP of the timeframe the user is viewing (the per-TF
      // plan), not the scan's canonical daily plan. Falls back to the scan plan.
      const av     = d._vivek ? (d._activeLevels || null) : null;
      const stopV  = av ? (av.stop ?? null) : (d.stop ?? null);
      const planEntry = av ? (av.entry ?? null) : (d.entry ?? null);
      const planTp1 = av ? (av.tp1 ?? null) : (d.tp1 ?? null);
      const planTp2 = av ? (av.tp2 ?? null) : (d.tp2 ?? null);
      const planTp3 = av ? (av.tp3 ?? null) : (d.tp3 ?? null);

      // (a) Chasing guard — if the live price is already at/through the plan's
      // first target, the setup has run and the reward left is degraded. Warn
      // before booking a chased entry (targets get recut from the real entry).
      if (planTp1 != null && (isLong ? px >= planTp1 : px <= planTp1)) {
        const side = isLong ? "above" : "below";
        const ok = confirm(
          `⚠️ Chasing ${SYM}\n\n` +
          `${fmt(px, cur)} is already ${side} the plan's first target (${fmt(planTp1, cur)}). ` +
          `The move looks extended and your risk:reward is reduced.\n\n` +
          `Targets will be recalculated as fresh 1R/2R/3R from this entry. Take the trade anyway?`);
        if (!ok) {
          buyBtn.disabled = false;
          statusEl.className = "sim-status"; statusEl.textContent = "";
          return;
        }
      }

      // (b) Entry-relative targets — recompute TP1/2/3 from the ACTUAL entry so a
      // late/chased fill still gets three real targets. Risk = |entry − stop|;
      // we mirror the plan's R-multiples when they're sane + increasing, else
      // fall back to 1R / 2R / 3R. The structural stop is kept as-is.
      const tps = entryRelTargets(isLong, px, stopV, planEntry, [planTp1, planTp2, planTp3]);
      const tp1V = tps[0], tp2V = tps[1], tp3V = tps[2];
      const tgtV = tp2V != null ? tp2V : (av ? (av.tp2 ?? null) : (d.target ?? null));
      const tfTag  = d._vivek && d._activeTf ? `${d._activeTf} · ` : "";
      data.trades.push({
        id: mjUid(), symbol: SYM, direction: dir,
        // Preserve the instrument's true type so it buckets correctly in the
        // journal: a scalp index/commodity (NAS100, GOLD) must keep "index" /
        // "commodity" and never be coerced to a stock or crypto.
        asset_type: isCrypto ? "crypto"
          : (d.asset_type || (market === "asx" ? "asx" : "nasdaq")),
        entry: px, entry_date: nowDate(), entry_time: nowTime(),
        size_usd: margin, leverage, shares: +(exposure / px).toFixed(8),
        stop: stopV, target: tgtV, tp1: tp1V, tp2: tp2V, tp3: tp3V,
        timeframe: d._vivek ? (d._activeTf || "1D") : null,
        // Log the grade + setup type so the journal matches Claude's rows: the
        // canonical scan grade, and the entry trigger on the timeframe you took
        // (reclaim / retest / break → "Weekly reclaim" etc. in the journal).
        grade: d.grade || null,
        entry_type: (av && av.entry_trigger) || d.entry_trigger || null,
        // Which lens produced this trade — lets the journal answer
        // "which system actually makes money" (2026-07-03)
        lens: d._zonePlan ? "phasemap" : d._vivek ? "vivek"
            : mode === "spec" ? "specs" : market === "scalp" ? "scalp" : "chart",
        notes: `Simulated from chart · ${tfTag}${d.grade || ""} ${(d.chips && d.chips[0]) || ""}`.trim(),
        status: "open", exit: null, exit_date: null, exit_time: null, sim: true, mtime: Date.now(),
      });
      mjSave(data);
      refresh(px);
    });

    sellBtn.addEventListener("click", async () => {
      const t = openSimTrade();
      if (!t) return;
      sellBtn.disabled = true;
      statusEl.textContent = "Fetching live price…";
      const px = await livePriceNow();
      if (!px) {
        statusEl.textContent = "Couldn't fetch a live price to close — try again in a moment.";
        sellBtn.disabled = false;
        return;
      }
      const data = mjLoad();
      const rec  = data.trades.find((x) => x.id === t.id);
      if (rec) {
        rec.status = "closed";
        rec.exit = px; rec.exit_date = nowDate(); rec.exit_time = nowTime();
        rec.mtime = Date.now();
        mjSave(data);
      }
      if (liveState.entryLineFns) liveState.entryLineFns.remove();
      const m   = dir === "long" ? 1 : -1;
      const pnl = (t.shares * m * (px - t.entry) - 2 * simBrok(data));
      statusEl.className = "sim-status" + (pnl >= 0 ? " live" : "");
      statusEl.textContent = `Closed @ ${fmt(px, cur)} · P&L ${pnl >= 0 ? "+" : ""}${cur}${pnl.toFixed(2)} — logged to My Trades`;
      buyBtn.disabled = false; sellBtn.disabled = true;
    });

    refresh();
  }

  // Draw a purple entry-price line on the chart while a sim position is open.
  // Must be called after the candle series is created (inside render).
  function wireChartPosition(candle, d) {
    const dir = (d.dir || "LONG").toLowerCase() === "short" ? "short" : "long";
    const SYM = (d.symbol || symbol).toUpperCase();
    let entryLine = null;

    const getOpenTrade = () => mjLoad().trades.find(
      (t) => t.sim && t.status === "open" && (t.symbol || "").toUpperCase() === SYM && t.direction === dir);

    function addLine(price) {
      if (entryLine) return;
      entryLine = candle.createPriceLine({
        price, color: "#a78bfa", lineWidth: 2, lineStyle: 0,
        axisLabelVisible: true, title: `▶ IN ${dir.toUpperCase()}`,
      });
    }
    function removeLine() {
      if (!entryLine) return;
      try { candle.removePriceLine(entryLine); } catch (_) {}
      entryLine = null;
    }
    liveState.entryLineFns = { add: addLine, remove: removeLine };

    const t = getOpenTrade();
    if (t) addLine(t.entry);

    const buy  = $("#cf-sim-buy");
    const sell = $("#cf-sim-sell");
    if (buy)  buy.addEventListener("click",  () => setTimeout(() => { const t2 = getOpenTrade(); if (t2) addLine(t2.entry); }, 60));
    if (sell) sell.addEventListener("click", () => setTimeout(removeLine, 60));
  }

  // Poll a delayed live quote for a non-crypto instrument and push it into the
  // header price + liveState (so the sim box, auto-close and entry P&L all react
  // to a moving price instead of the static scan close). Shows a "~15m delayed"
  // badge since Yahoo isn't real-time for stocks / futures.
  function startStockLive(d, SYM) {
    const cur      = d.currency_symbol || "";
    const yf       = yfTickerFor(SYM, d.asset_type);
    // VIVEK crypto: force Yahoo <base>-USD so the header price matches the chart
    // (a guessed Binance pair could be a different/colliding token).
    const srcParam = (d.asset_type === "crypto" || market === "crypto") ? "&src=yahoo" : "";
    const priceEl  = $("#ct-price");
    const delayEl  = $("#ct-delayed");
    let lastPx = null;
    const tick = async () => {
      if (document.hidden) return;   // backgrounded tab: don't burn the quote relay
      try {
        const r = await fetch(`/api/quote?sym=${encodeURIComponent(yf)}${srcParam}`, { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (j == null || j.price == null) return;
        const px = +j.price;
        liveState.price = px;
        if (delayEl) delayEl.hidden = false;
        if (priceEl) {
          if (lastPx != null && px !== lastPx) {
            priceEl.classList.remove("tick-up", "tick-down");
            void priceEl.offsetWidth;
            priceEl.classList.add(px > lastPx ? "tick-up" : "tick-down");
          }
          priceEl.textContent = fmt(px, cur);
          lastPx = px;
        }
        liveState.listeners.forEach((fn) => { try { fn(px); } catch (_) {} });
      } catch (_) { /* keep the last good price */ }
    };
    tick();
    const iv = setInterval(tick, 20000);
    window.addEventListener("beforeunload", () => clearInterval(iv), { once: true });
  }

  // ── VIVEK "setups across timeframes" strip ──────────────────────────────────
  // A read-only decision aid: for THIS ticker it surfaces which timeframes have a
  // live setup (armed / entry type / R:R) and flags multi-timeframe confluence —
  // so the chart actively suggests where the edge is, not just draws it. Reads the
  // same per-TF plans the chart already holds; clicking a chip jumps to that TF.
  const TFS_MIN_RR = 1.5;
  const TFS_NEAR_PCT = 1.5;   // price within 1.5% of the 200-SMA line = "approaching"
  function renderTFSetups(d, tfs, pickTF, getCurTF) {
    const order = ["4H", "1D", "3D", "1W"];
    const items = order.filter((k) => tfs[k] && tfs[k].levels).map((k) => {
      const lv = tfs[k].levels;
      // How far this timeframe's latest close sits from its own 200-SMA reaction
      // line (the core event). Lets the strip ANTICIPATE setups, not just report
      // ones that have already armed.
      const candles = tfs[k].candles || [];
      const px = candles.length ? +candles[candles.length - 1].close : null;
      const lvl = +lv.level || null;
      const nearPct = (px && lvl) ? Math.abs(px - lvl) / lvl * 100 : null;
      return { k, approx: !!tfs[k].approx, armed: !!lv.armed, rr: +lv.rr || 0,
               trig: lv.entry_trigger, nearPct };
    });
    if (!items.length) return null;
    const fmtPct = (p) => (p < 0.1 ? "<0.1%" : p.toFixed(1) + "%");
    // Real-plan timeframes only (a 4H / old-3D reference borrows the Daily plan —
    // don't let it double-count toward confluence).
    const realArmed = items.filter((i) => i.armed && !i.approx);
    // "Approaching": a real-plan TF that hasn't triggered but whose price is
    // hugging the 200-SMA line — a setup that may be about to fire.
    const realNear = items
      .filter((i) => !i.armed && !i.approx && i.nearPct != null && i.nearPct <= TFS_NEAR_PCT)
      .sort((a, b) => a.nearPct - b.nearPct);
    const isNear = (i) => realNear.includes(i);
    let cls, read;
    if (realArmed.length >= 2) {
      cls = "strong";
      read = `⚡ Multi-timeframe setup — armed on ${realArmed.map((i) => TF_LABEL[i.k]).join(" + ")}`;
    } else if (realArmed.length === 1) {
      const a = realArmed[0];
      cls = a.rr >= TFS_MIN_RR ? "armed" : "weak";
      read = `Armed on ${TF_LABEL[a.k]} · ${a.trig || "trigger"} · R:R ${a.rr.toFixed(1)}`;
      // An armed TF with another TF also hugging the line = stacking confluence.
      if (realNear.length) read += ` · ${TF_LABEL[realNear[0].k]} approaching (${fmtPct(realNear[0].nearPct)})`;
    } else if (realNear.length >= 2) {
      cls = "near";
      read = `⚡ 200-SMA cluster forming — ${realNear.map((i) => TF_LABEL[i.k]).join(" + ")} ` +
             `within ${fmtPct(realNear[realNear.length - 1].nearPct)} of the line`;
    } else if (realNear.length === 1) {
      const a = realNear[0];
      cls = "near";
      read = `⏳ Approaching a ${TF_LABEL[a.k]} setup — ${fmtPct(a.nearPct)} from the 200-SMA`;
    } else {
      cls = "watch";
      // Name the nearest real-plan TF so the strip still points somewhere useful.
      const nearest = items
        .filter((i) => !i.approx && i.nearPct != null)
        .sort((x, y) => x.nearPct - y.nearPct)[0];
      read = nearest
        ? `Watching — nearest is ${TF_LABEL[nearest.k]}, ${fmtPct(nearest.nearPct)} from the line`
        : "Watching — no timeframe has triggered yet";
    }
    const chip = (i) => {
      const near = isNear(i);
      const state = i.armed ? (i.rr >= TFS_MIN_RR ? "armed" : "weak") : (near ? "near" : "watch");
      const sub = i.armed ? `${(i.trig || "arm").slice(0, 3)} · ${i.rr.toFixed(1)}R`
                : (i.nearPct != null && !i.approx ? fmtPct(i.nearPct) : "watch");
      const title = i.approx
        ? `${TF_LABEL[i.k]} — reference view (uses the Daily plan)`
        : `${TF_LABEL[i.k]} 200-SMA plan${i.armed ? " · ARMED" : (near ? " · approaching" : " · watching")}` +
          (i.nearPct != null ? ` · ${fmtPct(i.nearPct)} from the line` : "");
      return `<button class="tfs-chip s-${state}${i.approx ? " ref" : ""}" data-tf="${esc(i.k)}" title="${esc(title)}">` +
             `<b>${TF_LABEL[i.k]}</b><span>${esc(sub)}</span></button>`;
    };
    const host = document.createElement("div");
    host.className = "tfs-strip s-" + cls;
    host.innerHTML = `<span class="tfs-read">${esc(read)}</span><div class="tfs-chips">${items.map(chip).join("")}</div>`;
    const toggle = $("#tf-toggle");
    if (toggle && toggle.parentNode) toggle.parentNode.insertBefore(host, toggle.nextSibling);
    host.querySelectorAll(".tfs-chip").forEach((b) => b.addEventListener("click", () => pickTF(b.dataset.tf)));
    const markActive = (key) =>
      host.querySelectorAll(".tfs-chip").forEach((b) => b.classList.toggle("is-active", b.dataset.tf === key));
    markActive(getCurTF());
    return { markActive };
  }

  function render(d) {
    header(d); footer(d); wireSim(d); wireSizeCalc(d);
    const tfs = d.timeframes || {};
    const available = TF_ORDER.filter((k) => tfs[k]);
    if (!available.length) {
      // Static JSON had no usable timeframes — try live history before failing
      // (but don't loop if we're already rendering a live fallback).
      if (d._fallback) { fail("No chart data for this ticker yet."); }
      else { fallbackFromLive(); }
      return;
    }
    // Surface that this is a live-built chart rather than the saved scan view.
    // (VIVEK is always rendered live by design, so it doesn't get the badge.)
    if (d._fallback && !d._vivek && !d._pm) {
      const note = document.createElement("span");
      note.className = "ct-fallback-note";
      note.textContent = "live fallback";
      note.title = "No saved scan chart for this ticker — showing recent history pulled live.";
      const priceEl = $("#ct-price");
      if (priceEl && priceEl.parentNode) priceEl.parentNode.insertBefore(note, priceEl.nextSibling);
    }
    let curTF = tfs[d.default_tf] ? d.default_tf : available[0];
    let drawClear = () => {};         // set by initDrawing; clears temp drawings on TF switch
    let drawRedraw = () => {};        // set by initDrawing; re-anchors drawings on pan/zoom/resize
    let drawRestore = () => {};       // set by initDrawing; reloads saved drawings for the current TF
    let tfSetups = null;              // VIVEK multi-timeframe setup strip (set below)
    let rsApply = () => {};           // set by initCompare; re-maps the RS overlay per TF
    let rsTrim = () => {};            // set by initCompare; clips the overlay during replay
    const replayCtl = { active: false, abort() {} };   // set by initReplay

    const el = $("#chart");
    const LC = window.LightweightCharts;
    // site is dark-only (terminal theme)
    const chart = LC.createChart(el, {
      width: el.clientWidth, height: el.clientHeight,
      layout: { background: { color: "transparent" }, textColor: "#aab4c5",
        fontFamily: '"JetBrains Mono", ui-monospace, Menlo, Consolas, monospace' },
      grid: { vertLines: { color: "rgba(110,125,150,0.10)" },
              horzLines: { color: "rgba(110,125,150,0.10)" } },
      rightPriceScale: { borderColor: "rgba(110,125,150,0.22)" },
      timeScale: { borderColor: "rgba(110,125,150,0.22)", rightOffset: 6 },
      crosshair: { mode: LC.CrosshairMode.Normal },
    });

    const a = Math.abs(d.price || 1);
    const prec = a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : a >= 0.001 ? 6 : 8;
    const candle = chart.addCandlestickSeries({
      upColor: "#2fd07f", downColor: "#ff5b5b", wickUpColor: "#2fd07f", wickDownColor: "#ff5b5b",
      borderVisible: false, priceFormat: { type: "price", precision: prec, minMove: Math.pow(10, -prec) },
    });
    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" } });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });

    // TTM Squeeze momentum histogram (scalp 1H charts only) — its own pane band
    // below the price, with LazyBear-style colouring baked into the data.
    const hasMom = TF_ORDER.some((k) => tfs[k] && tfs[k].histogram);
    let momSeries = null;
    if (hasMom) {
      // squeeze the price into the top, leave room for the momentum pane
      chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.30 } });
      momSeries = chart.addHistogramSeries({
        priceScaleId: "mom", priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
        lastValueVisible: false, priceLineVisible: false,
      });
      chart.priceScale("mom").applyOptions({ scaleMargins: { top: 0.72, bottom: 0.06 } });
    }

    // ── Session / weekend shading (UX-20 #9) — created BEFORE the flash series
    // so event flashes always paint over the calendar banding.
    const shadeSeries = chart.addHistogramSeries({
      priceScaleId: "shade", lastValueVisible: false, priceLineVisible: false,
    });
    chart.priceScale("shade").applyOptions({
      scaleMargins: { top: 0, bottom: 0 }, visible: false,
    });
    const applyShade = (key) => shadeSeries.setData(shadeRows((tfs[key] || {}).candles, key));

    // ── FLASH bands (2026-07-02, owner request) — a translucent full-height
    // column on every bar where a system spoke (VIVEK reaction/trigger,
    // PhaseMap sweep/displacement). The TradingView-style "review this bar"
    // visual cue: impossible to scroll past. Hidden price scale, value-1
    // columns stretched to the full pane.
    const flashSeries = chart.addHistogramSeries({
      priceScaleId: "flash", lastValueVisible: false, priceLineVisible: false,
    });
    chart.priceScale("flash").applyOptions({
      scaleMargins: { top: 0, bottom: 0 }, visible: false,
    });
    function setFlashes(items) {
      // items: [{time, color}] — dedupe on time (lightweight-charts requires
      // ascending unique times)
      const seen = new Map();
      (items || []).forEach((f) => { if (f && f.time != null) seen.set(f.time, f.color); });
      flashSeries.setData([...seen.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([time, color]) => ({ time, value: 1, color })));
    }
    let vkFlashes = [], pmFlashes = [];

    // One line series per indicator (the set is the same across timeframes).
    const lineSeries = tfs[curTF].lines.map((l) => chart.addLineSeries({
      color: l.color, lineWidth: l.name === "SuperTrend" ? 1.5 : 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    }));
    // #73: tap a legend name to hide/show that SMA line. Tracked by NAME (line
    // counts differ per timeframe) so the choice survives TF switches. The
    // per-button click is wired inside legend() (idempotent onclick) so it
    // always references THIS render's series, never a stale earlier render.
    const hiddenSmas = new Set();
    function toggleSma(name) {
      if (hiddenSmas.has(name)) hiddenSmas.delete(name); else hiddenSmas.add(name);
      const cur = tfs[curTF];
      (cur ? cur.lines : []).forEach((l, i) => {
        if (l.name === name && lineSeries[i]) lineSeries[i].applyOptions({ visible: !hiddenSmas.has(name) });
      });
      if (cur) legend(cur);
    }

    // ── PhaseMap zone bands (?pm=1) — every scanned zone as a shaded band with
    // a labelled dotted midline. Bands are price-static, so only their time
    // span is refreshed per timeframe (applyPmZones, called from applyTF).
    const pmBands = [];
    if (pmRec) {
      const PM_COLS = {
        TARGET: ["rgba(47,208,127,0.14)", "#2fd07f"],
        ENTRY_CONTINUATION: ["rgba(55,208,196,0.12)", "#37d0c4"],
        INVALIDATION_HARD: ["rgba(255,91,91,0.14)", "#ff5b5b"],
        INVALIDATION_MOMENTUM: ["rgba(255,91,91,0.14)", "#ff5b5b"],
        DEMAND: ["rgba(255,178,36,0.16)", "#ffb224"],
        SUPPLY: ["rgba(255,178,36,0.16)", "#ffb224"],
      };
      const PM_LABEL = { ENTRY_CONTINUATION: "ENTRY", INVALIDATION_HARD: "HARD INV",
        INVALIDATION_MOMENTUM: "50% INV", DEMAND: "DEMAND", SUPPLY: "SUPPLY" };
      // legend/tooltip groups — the four togglable families of zone
      const PM_GROUP = { TARGET: "target", ENTRY_CONTINUATION: "entry",
        INVALIDATION_HARD: "invalid", INVALIDATION_MOMENTUM: "invalid",
        DEMAND: "trap", SUPPLY: "trap" };
      const GROUP_LABEL = { target: "TARGETS", entry: "ENTRY", invalid: "INVALIDATION", trap: "TRAP" };
      const GROUP_COL = { target: "#2fd07f", entry: "#37d0c4", invalid: "#ff5b5b", trap: "#ffb224" };
      // user prefs (persisted): overall band opacity + per-group visibility
      const OPACITY = { subtle: 0.55, normal: 1, bold: 1.7 };
      let zOp = "normal";
      try { zOp = localStorage.getItem("pm-zone-opacity") || "normal"; } catch (_) {}
      if (!(zOp in OPACITY)) zOp = "normal";
      let zHide = {};
      try { zHide = JSON.parse(localStorage.getItem("pm-zone-hidden") || "{}") || {}; } catch (_) {}
      const alphaScale = (rgba, mult) =>
        rgba.replace(/([\d.]+)\)$/, (_m, a) => Math.min(0.8, +a * mult).toFixed(3) + ")");
      const pf = (x) => x == null ? "—" : x >= 1000 ? x.toLocaleString("en-AU", { maximumFractionDigits: 0 })
        : x < 0.001 ? x.toFixed(8).replace(/0+$/, "") : x < 0.1 ? x.toFixed(4) : x < 2 ? x.toFixed(3) : x.toFixed(2);
      const SRC_LABEL = { box_high: "box high", box_low: "box low", equal_highs: "equal highs",
        equal_lows: "equal lows", prior_high: "prior high", prior_low: "prior low",
        yearly_open: "yearly open", quarterly_open: "quarterly open", monthly_open: "monthly open",
        prior_yearly_close: "prior yearly close", fib_ext_10: "fib ext 1.0–1.272",
        fib_ext_1618: "fib ext 1.618–2.0", sweep_wick: "sweep wick" };

      function paintBand(b) {
        // Zone strength reads visually: ×N-confluence bands sit heavier on the
        // chart, dead (consumed/violated) bands fade right back, and the fill
        // runs as a soft top→bottom gradient — a band, not a hard-edged box.
        const cols = PM_COLS[b.z.type] || ["rgba(109,120,137,0.10)", "#6d7889"];
        const dead = b.z.status === "CONSUMED" || b.z.status === "VIOLATED";
        const strength = 1 + 0.35 * (Math.min(b.z.confluence || 1, 3) - 1);
        const mult = OPACITY[zOp] * strength * (dead ? 0.3 : 1);
        b.series.applyOptions({
          visible: !zHide[b.group],
          topFillColor1: alphaScale(cols[0], mult * 1.45),   // upper edge, denser
          topFillColor2: alphaScale(cols[0], mult * 0.55),   // fades toward the base
        });
        if (b.pl) { candle.removePriceLine(b.pl); b.pl = null; }
        if (!zHide[b.group]) b.pl = candle.createPriceLine(b.plOpts);
      }

      (pmRec.zones || []).forEach((z) => {
        const cols = PM_COLS[z.type] || ["rgba(109,120,137,0.10)", "#6d7889"];
        const dead = z.status === "CONSUMED" || z.status === "VIOLATED";
        const s = chart.addBaselineSeries({
          baseValue: { type: "price", price: z.low },
          topFillColor1: cols[0], topFillColor2: cols[0],
          topLineColor: "transparent", bottomLineColor: "transparent",
          bottomFillColor1: "transparent", bottomFillColor2: "transparent",
          lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
        });
        const label = z.type === "TARGET" ? z.id.toUpperCase() : (PM_LABEL[z.type] || z.type);
        const b = { series: s, z, group: PM_GROUP[z.type] || "trap", pl: null,
          plOpts: { price: (z.low + z.high) / 2, color: cols[1], lineWidth: 1,
            lineStyle: LC.LineStyle.Dotted, axisLabelVisible: true,
            title: `PM ${label}${z.confluence > 1 ? ` ×${z.confluence}` : ""}${dead ? ` · ${z.status.toLowerCase()}` : ""}` } };
        pmBands.push(b);
        paintBand(b);
      });

      const strip = document.createElement("div");
      strip.className = "pm-chart-strip";
      strip.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;" +
        "font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px;color:#aab4c5;" +
        "padding:8px 10px;margin:8px 0;border:1px solid #1c2230;border-radius:8px;background:#10131a;";
      const groups = [...new Set(pmBands.map((b) => b.group))];
      strip.innerHTML =
        `<span style="color:#37d0c4;font-weight:700">PHASEMAP</span>` +
        `<span style="font-weight:700">${esc(pmRec.state.replace("_", " "))}</span>` +
        (pmRec.tier ? `<span style="color:#2fd07f;font-weight:700">${esc(pmRec.tier)}</span>` : "") +
        `<span style="color:#8b96a9">${esc(pmRec.regime)}</span>` +
        (pmRec.next ? `<span style="flex:1 1 100%;color:#37d0c4;line-height:1.5">` +
          `<b>WANTED NEXT</b> · ${esc(pmRec.next)}</span>` : "") +
        `<span style="flex:1 1 100%;color:#98a2b5;line-height:1.5">${esc(pmRec.narration || "")}</span>` +
        `<span style="flex:1 1 100%;display:flex;flex-wrap:wrap;gap:6px;align-items:center">` +
          `<span style="color:#6d7889">ZONES</span>` +
          groups.map((g) => `<button class="pm-zone-toggle" data-zg="${g}" style="cursor:pointer;` +
            `font:inherit;padding:2px 9px;border-radius:999px;border:1px solid #2a3242;` +
            `background:${zHide[g] ? "transparent" : "#1a2130"};color:${zHide[g] ? "#5b6577" : GROUP_COL[g]};` +
            `${zHide[g] ? "text-decoration:line-through;" : ""}" ` +
            `title="Show/hide ${GROUP_LABEL[g].toLowerCase()} zones on the chart">${GROUP_LABEL[g]}</button>`).join("") +
          `<button class="pm-zone-op" style="cursor:pointer;font:inherit;padding:2px 9px;margin-left:6px;` +
            `border-radius:999px;border:1px dashed #2a3242;background:transparent;color:#8b96a9" ` +
            `title="Cycle band opacity — subtle / normal / bold (saved)">◐ ${esc(zOp.toUpperCase())}</button>` +
        `</span>` +
        `<a href="phasemap.html" style="color:#37d0c4">PhaseMap tab →</a>`;
      el.insertAdjacentElement("afterend", strip);
      strip.querySelectorAll(".pm-zone-toggle").forEach((btn) => btn.addEventListener("click", () => {
        const g = btn.dataset.zg;
        zHide[g] = !zHide[g];
        try { localStorage.setItem("pm-zone-hidden", JSON.stringify(zHide)); } catch (_) {}
        btn.style.background = zHide[g] ? "transparent" : "#1a2130";
        btn.style.color = zHide[g] ? "#5b6577" : GROUP_COL[g];
        btn.style.textDecoration = zHide[g] ? "line-through" : "none";
        pmBands.filter((b) => b.group === g).forEach(paintBand);
      }));
      strip.querySelector(".pm-zone-op").addEventListener("click", (e) => {
        const order = ["subtle", "normal", "bold"];
        zOp = order[(order.indexOf(zOp) + 1) % order.length];
        try { localStorage.setItem("pm-zone-opacity", zOp); } catch (_) {}
        e.currentTarget.textContent = `◐ ${zOp.toUpperCase()}`;
        pmBands.forEach(paintBand);
      });

      // Hover/tap tooltip: every zone the cursor price sits inside, with
      // bounds, midpoint, status and the sources that flagged the band.
      const zoneTip = document.createElement("div");
      zoneTip.className = "pm-zone-tip";
      zoneTip.style.display = "none";
      el.style.position = "relative";
      el.appendChild(zoneTip);
      chart.subscribeCrosshairMove((param) => {
        if (!param || !param.point) { zoneTip.style.display = "none"; return; }
        const price = candle.coordinateToPrice(param.point.y);
        if (price == null) { zoneTip.style.display = "none"; return; }
        const hits = (pmRec.zones || []).filter((z) =>
          price >= z.low && price <= z.high && !zHide[PM_GROUP[z.type] || "trap"]);
        if (!hits.length) { zoneTip.style.display = "none"; return; }
        zoneTip.innerHTML = hits.map((z) => {
          const label = z.type === "TARGET" ? z.id.toUpperCase() : (PM_LABEL[z.type] || z.type);
          const col = (PM_COLS[z.type] || [0, "#6d7889"])[1];
          const src = (z.sources || []).map((s2) => SRC_LABEL[s2] || s2).join(" + ");
          return `<div class="pm-zone-tip-row"><b style="color:${col}">${esc(label)}` +
            `${z.confluence > 1 ? ` ×${z.confluence}` : ""}</b> ` +
            `${pf(z.low)}–${pf(z.high)} · mid ${pf((z.low + z.high) / 2)} · ${esc(z.status)}` +
            (src ? `<span class="pm-zone-tip-src">${esc(src)}</span>` : "") + `</div>`;
        }).join("");
        zoneTip.style.display = "block";
        const w = zoneTip.offsetWidth, cw = el.clientWidth;
        zoneTip.style.left = Math.min(param.point.x + 14, Math.max(4, cw - w - 8)) + "px";
        zoneTip.style.top = (param.point.y + 14) + "px";
      });
    }
    function applyPmZones(key) {
      if (!pmBands.length) return;
      const cs = (tfs[key] || {}).candles || [];
      if (!cs.length) return;
      const t0 = cs[0].time, tN = cs[cs.length - 1].time;
      pmBands.forEach((b) => b.series.setData([
        { time: t0, value: b.z.high }, { time: tN, value: b.z.high }]));
      const bull = pmRec.direction === "bullish";
      const snap = (iso) => {
        const t = Math.floor(Date.parse(iso + "T00:00:00Z") / 1000);
        let best = null;
        for (let i = 0; i < cs.length; i++) { if (cs[i].time <= t + 86399) best = cs[i].time; else break; }
        return best;
      };
      const mm = pmRec.metrics || {};
      const sweepT = mm.sweep_date ? snap(mm.sweep_date) : null;
      const dispT = mm.displacement_date ? snap(mm.displacement_date) : null;
      // FLASH the event bars on every timeframe (amber = sweep, green = displacement)
      pmFlashes = [];
      if (sweepT) pmFlashes.push({ time: sweepT, color: "rgba(255,178,36,0.12)" });
      if (dispT) pmFlashes.push({ time: dispT, color: "rgba(47,208,127,0.12)" });
      setFlashes([...vkFlashes, ...pmFlashes]);
      // Sweep / displacement arrows — only where nothing else sets markers.
      if (!(tfs[key] || {}).levels && !(tfs[key] || {}).squeeze_dots &&
          typeof candle.setMarkers === "function") {
        const mk = [];
        if (sweepT) mk.push({ time: sweepT, position: bull ? "belowBar" : "aboveBar",
          color: "#ffb224", shape: bull ? "arrowUp" : "arrowDown", text: "SWEEP" });
        if (dispT) mk.push({ time: dispT, position: bull ? "belowBar" : "aboveBar",
          color: "#2fd07f", shape: bull ? "arrowUp" : "arrowDown", text: "DISPLACE" });
        mk.sort((a, b) => a.time - b.time);
        candle.setMarkers(mk);
      }
    }

    // Non-VIVEK: static level lines drawn once. VIVEK draws its levels PER
    // timeframe (applyVivekLevels) so they update when you switch 4H / D / W.
    if (!d._vivek) (d.level_lines || []).forEach((L) => {
      if (L.price == null) return;
      let title = L.title || "";
      const ep = d.entry;
      if (ep && ep > 0 && L.price !== ep) {
        const pct = ((L.price - ep) / ep * 100);
        title += ` ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
        const riskDist = d.stop && d.stop > 0 ? Math.abs(ep - d.stop) : 0;
        if (riskDist > 0) {
          const rMult = Math.abs(L.price - ep) / riskDist;
          title += ` · ${rMult.toFixed(1)}R`;
        }
      } else if (ep && L.price === ep && d.price > 0 && L.price !== d.price) {
        // #74: ENTRY line shows its gap from the current price (trigger distance).
        const g = (L.price - d.price) / d.price * 100;
        title += ` ${g >= 0 ? "+" : ""}${g.toFixed(2)}% vs live`;
      }
      candle.createPriceLine({ price: L.price, color: L.color, lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title });
    });

    // VIVEK: per-timeframe trade levels (200 SMA · swing high/low · SL · Entry ·
    // TP1/2/3), redrawn whenever the timeframe changes, plus the matching footer.
    let vkHandles = [];
    function applyVivekLevels(key) {
      const lv = (tfs[key] || {}).levels;
      if (!lv) return;
      vkHandles.forEach((h) => { try { candle.removePriceLine(h); } catch (_) {} });
      vkHandles = [];
      const ep = lv.entry;
      // weight: 2 = the actionable trade (SL/Entry/TP1), 1 = context/secondary.
      const line = (price, color, label, weight, dotted) => {
        if (price == null || !isFinite(price)) return;
        let t = label;
        if (ep && ep > 0 && price !== ep) {
          const pct = (price - ep) / ep * 100;
          t += ` ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
          const rd = lv.stop ? Math.abs(ep - lv.stop) : 0;
          if (rd > 0) t += ` · ${(Math.abs(price - ep) / rd).toFixed(1)}R`;
        } else if (price === ep && d.price > 0 && price !== d.price) {
          // #74: the ENTRY line carries its distance from the current price —
          // how far price must travel to arm the trade. (SL/TP above are
          // labelled entry-relative — that's the R ladder of the plan itself.)
          const g = (price - d.price) / d.price * 100;
          t += ` ${g >= 0 ? "+" : ""}${g.toFixed(2)}% vs live`;
        }
        vkHandles.push(candle.createPriceLine({ price, color, lineWidth: weight || 1,
          lineStyle: dotted ? LC.LineStyle.Dotted : LC.LineStyle.Dashed, axisLabelVisible: true, title: t }));
      };
      // Visual hierarchy: the trade ladder (SL/Entry/TP1) is loudest; the 200 SMA
      // and the further targets are secondary. Swing lines were dropped — the
      // structure markers already show them, so the chart stays clean.
      const lvlLabel = key === "1W" ? "200 SMA·W" : key === "4H" ? "200 SMA·D (ref)" : "200 SMA·D";
      line(lv.level, "#ffb020", lvlLabel, 1, true);
      line(lv.stop,  "#ff5b5b", "SL",    2);
      line(lv.entry, "#e5e9f0", "ENTRY", 2);
      line(lv.tp1,   "#2fd07f", "TP1",   2);
      line(lv.tp2,   "#2fd07f", "TP2",   1);
      line(lv.tp3,   "#2fd07f", "TP3",   1);
      // Markers (200 SMA reaction + entry trigger) for this TF, from Python,
      // plus the open-position entry marker if there is one.
      if (typeof candle.setMarkers === "function") {
        const ivSec = key === "4H" ? 14400 : key === "1W" ? 604800 : 86400;
        const ms = ((tfs[key] || {}).markers || []).slice();
        const em = buildEntryMarker(entryEpoch, ivSec, posDir);
        if (em) { ms.push(em); ms.sort((a, b) => a.time - b.time); }
        candle.setMarkers(ms);
        // FLASH the bars where the system spoke (blue tint = VIVEK events)
        vkFlashes = ms.map((m) => ({ time: m.time, color: "rgba(77,163,255,0.10)" }));
        setFlashes([...vkFlashes, ...pmFlashes]);
      }
      // Expose the active timeframe's plan so Simulate-Buy logs THIS TF's levels.
      d._activeLevels = lv;
      d._activeTf = key;
      renderVivekFooter(d, lv, key);
    }

    // ── open-position context (entry marker + floating LIVE box) ──────────────
    const SYM    = (d.symbol || symbol).toUpperCase();
    const posDir = (d.dir || "LONG").toLowerCase() === "short" ? "short" : "long";
    // Any open trade (sim OR manually logged) for this symbol+direction.
    const findOpen = () => mjLoad().trades.find(
      (t) => t.status === "open" && (t.symbol || "").toUpperCase() === SYM && t.direction === posDir);
    const entryEpochOf = (t) => {
      if (!t || !t.entry_date) return null;
      const ms = new Date(`${t.entry_date}T${(t.entry_time || "00:00")}:00`).getTime();
      return isFinite(ms) ? Math.floor(ms / 1000) : null;
    };
    const entryEpoch = entryEpochOf(findOpen());

    function legend(tf) {
      const smas = tf.lines.map((l) => {
        const last = l.data.length ? l.data[l.data.length - 1].value : null;
        const off = hiddenSmas.has(l.name);
        // #73: each SMA name is a toggle button — tap to hide/show its line.
        return `<span class="cl-item${off ? " is-off" : ""}"><button type="button" class="cl-name" ` +
          `data-sma="${esc(l.name)}" style="color:${l.color}" aria-pressed="${off ? "false" : "true"}" ` +
          `title="Tap to ${off ? "show" : "hide"} the ${esc(l.name)} line">${esc(l.name)}</button>` +
          ` ${last != null ? fmt(last, d.currency_symbol) : ""}</span>`;
      }).join("");
      // VIVEK: a small key so the reaction dot, the entry-trigger arrow and the
      // volume colours are self-explanatory.
      const key = d._vivek
        ? `<span class="cl-key"><span style="color:#ffb020">● 200 SMA reaction</span>` +
          `<span style="color:#2fd07f">▲ entry trigger</span>` +
          `<span style="color:#00d2ff">▮ vol ≥1.5×</span>` +
          `<span style="color:#2fd07f">▮ rising</span><span style="color:#ff5b5b">▮ falling</span></span>`
        : "";
      const host = $("#chart-legend");
      host.innerHTML = `<span id="cl-ohlc" class="cl-ohlc"></span>` + smas + key;
      // #73: (re)wire each name button to this render's toggle. onclick is
      // idempotent, so rebuilding the legend on every TF switch never stacks.
      host.querySelectorAll(".cl-name[data-sma]").forEach((btn) => {
        btn.onclick = () => toggleSma(btn.dataset.sma);
      });
    }
    // Candle readout on hover: O/H/L/C + the period's % move (vs the prior
    // close), coloured. Updates the legend slot as the crosshair moves.
    function updateOHLC(param) {
      const host = document.getElementById("cl-ohlc");
      if (!host) return;
      const bar = param && param.seriesData && param.seriesData.get(candle);
      if (!bar || bar.close == null || !param.time) { host.innerHTML = ""; return; }
      const cs = (tfs[curTF] && tfs[curTF].candles) || [];
      let prevClose = null;
      for (let i = 0; i < cs.length; i++) {
        if (cs[i].time === param.time) { prevClose = i > 0 ? cs[i - 1].close : null; break; }
      }
      const base = prevClose != null && prevClose > 0 ? prevClose : bar.open;
      const chg = base > 0 ? (bar.close - base) / base * 100 : 0;
      const cur = d.currency_symbol || "";
      const cls = chg >= 0 ? "up" : "down";
      host.innerHTML =
        `<span class="ohlc-v">O ${fmt(bar.open, cur)}</span>` +
        `<span class="ohlc-v">H ${fmt(bar.high, cur)}</span>` +
        `<span class="ohlc-v">L ${fmt(bar.low, cur)}</span>` +
        `<span class="ohlc-v">C ${fmt(bar.close, cur)}</span>` +
        `<b class="ohlc-chg ${cls}">${chg >= 0 ? "▲ +" : "▼ "}${chg.toFixed(2)}%</b>`;
    }
    chart.subscribeCrosshairMove(updateOHLC);

    // ── forward date projection ────────────────────────────────────────────
    // Hover to the RIGHT of the last candle to see the rough calendar date that
    // spot maps to — extrapolated from the average bar spacing (so weekends /
    // holidays are baked in). Point at where you think price is headed and this
    // tells you roughly WHEN.
    const fc = document.createElement("div");
    fc.className = "ct-forecast"; fc.hidden = true;
    el.appendChild(fc);
    const projFmt = (sec) => {
      const dt = new Date(sec * 1000);
      const dstr = dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
      return curTF === "4H"
        ? dstr + " · " + dt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
        : dstr;
    };
    function updateForecast(param) {
      const cs = (tfs[curTF] && tfs[curTF].candles) || [];
      if (!param || !param.point || param.time || cs.length < 3) { fc.hidden = true; return; }
      const ts = chart.timeScale();
      const lastI = cs.length - 1;
      const lastX = ts.logicalToCoordinate(lastI);
      if (lastX == null) { fc.hidden = true; return; }
      const bs = (ts.options && ts.options().barSpacing) || 6;
      const ahead = (param.point.x - lastX) / bs;          // bars past the last candle
      if (ahead < 0.5) { fc.hidden = true; return; }        // only in the future zone
      const n = Math.min(30, lastI);
      const avgSec = n > 0 ? (cs[lastI].time - cs[lastI - n].time) / n : 86400;
      const projSec = cs[lastI].time + ahead * (avgSec > 0 ? avgSec : 86400);
      const days = Math.max(1, Math.round((projSec - cs[lastI].time) / 86400));
      fc.innerHTML =
        `<span class="fc-date">🔮 ${projFmt(projSec)}</span>` +
        `<span class="fc-in">≈ ${days} day${days === 1 ? "" : "s"} out · +${Math.round(ahead)} bars</span>`;
      fc.hidden = false;
      const w = el.clientWidth;
      fc.style.left = Math.min(Math.max(param.point.x, 78), w - 78) + "px";
      fc.style.top  = Math.max(6, (param.point.y || 44) - 48) + "px";
    }
    chart.subscribeCrosshairMove(updateForecast);

    function applyTF(key) {
      const tf = tfs[key]; if (!tf) return;
      if (replayCtl.active) replayCtl.abort();   // TF switch ends a replay silently
      curTF = key;
      drawClear();                    // wipe the canvas state for the old TF…
      drawRestore();                  // …then load this TF's SAVED drawings (persistent)
      candle.setData(tf.candles);
      vol.setData(tf.volume);
      // Timeframes can carry DIFFERENT line counts (a thin 4H/3D/W history has
      // no SMA-200). Grow the series pool on demand and CLEAR every series the
      // new TF doesn't use — a stale line from the previous TF would otherwise
      // ghost across the chart and stretch the time axis (the "fucked 4H" bug).
      while (lineSeries.length < tf.lines.length) {
        const l = tf.lines[lineSeries.length];
        lineSeries.push(chart.addLineSeries({
          color: l.color, lineWidth: l.name === "SuperTrend" ? 1.5 : 2,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        }));
      }
      lineSeries.forEach((s, i) => {
        const l = tf.lines[i];
        if (l) { s.applyOptions({ color: l.color, visible: !hiddenSmas.has(l.name) }); s.setData(l.data); }
        else { s.setData([]); }
      });

      // Momentum histogram + squeeze on/off markers under the price bars
      if (momSeries) momSeries.setData(tf.histogram || []);
      if (tf.squeeze_dots && typeof candle.setMarkers === "function") {
        // Mark only the transitions: squeeze turning ON (coiling) and FIRING.
        const marks = [];
        let prevOn = null;
        tf.squeeze_dots.forEach((p) => {
          const on = p.color === "#ff5b5b";
          if (prevOn !== null && on !== prevOn) {
            marks.push(on
              ? { time: p.time, position: "belowBar", color: "#ff5b5b", shape: "circle", size: 1 }
              : { time: p.time, position: "belowBar", color: "#2fd07f", shape: "arrowUp", size: 1, text: "fire" });
          }
          prevOn = on;
        });
        const em = buildEntryMarker(entryEpoch, 3600, posDir);
        candle.setMarkers(em ? [...marks, em] : marks);
      }
      chart.timeScale().fitContent();
      legend(tf);
      if (d._vivek) {
        applyVivekLevels(key);               // re-read trade levels for this timeframe
        // Prominent notice on the reference timeframes (4H, 3D): their candles
        // are real, but the trade levels are the Daily plan (no separate plan at
        // those timeframes yet), so users aren't misled.
        if (tfNotice) {
          const isRef = (tfs[key] || {}).approx;
          if (isRef) {
            const nm = key === "3D" ? "3-Day (3D)" : key;
            tfNotice.textContent =
              `${nm} view — trade levels shown are from the Daily plan (no separate ${key} plan yet). ` +
              `${nm} candles & SMAs are real.`;
          }
          tfNotice.hidden = !isRef;
        }
        if (tfSetups) tfSetups.markActive(key);   // sync the multi-timeframe strip
      }
      applyPmZones(key);                     // PhaseMap bands ride every timeframe
      applyShade(key);                       // #9: session / weekend banding
      rsApply(key);                          // #8: re-map the RS overlay to this TF
    }

    // On-chart notice for reference timeframes (4H / 3D) — pinned over the candles.
    const tfNotice = d._vivek ? Object.assign(document.createElement("div"), {
      className: "tf-notice", hidden: true,
    }) : null;
    if (tfNotice) { el.style.position = "relative"; el.appendChild(tfNotice); }

    const toggle = $("#tf-toggle");
    // Live Binance feed only for genuine crypto (by asset_type) — commodities and
    // stocks in the scalp universe stay on static scan data. VIVEK is a daily-200
    // SMA swing view, so it never switches into the intraday scalp stream (which
    // would recompute the BB/KC/EMA9/21 overlays we deliberately don't want here).
    const pair = (!d._vivek && (d.asset_type === "crypto" || market === "crypto")) ? cryptoPair(SYM) : null;
    const liveCtx = { chart, candle, vol, lineSeries, momSeries, posDir, entryEpoch, shadeSeries };
    wirePng(chart, d, () => curTF);   // #76: PNG export needs the live chart handle

    if (pair) {
      // Crypto → live intraday timeframes streamed from Binance (15M / 30M / 1H).
      curTF = "1H";
      if (tfs["1H"]) applyTF("1H");                 // instant paint while REST loads
      const live = makeLive(d, pair, liveCtx);
      live.start();
      toggle.innerHTML = LIVE_TF_ORDER.map((k) =>
        `<button class="tf-btn${k === "1H" ? " is-active" : ""}" data-tf="${k}">${k}</button>`).join("");
      toggle.querySelectorAll(".tf-btn").forEach((b) => b.addEventListener("click", () => {
        toggle.querySelectorAll(".tf-btn").forEach((x) => x.classList.toggle("is-active", x === b));
        live.switchTo(b.dataset.tf);
      }));
    } else {
      // Everything else → static multi-timeframe data from the scan JSON.
      toggle.innerHTML = available.map((k) =>
        `<button class="tf-btn${k === curTF ? " is-active" : ""}" data-tf="${k}"${TF_TITLE[k] ? ` title="${TF_TITLE[k]}"` : ""}>${TF_LABEL[k]}</button>`).join("");
      // Switch timeframe from a button OR a setup-strip chip, keeping both in sync.
      const selectTF = (key) => {
        if (!tfs[key]) return;
        toggle.querySelectorAll(".tf-btn").forEach((x) => x.classList.toggle("is-active", x.dataset.tf === key));
        applyTF(key);
      };
      // VIVEK: a read-only "setups across timeframes" decision strip that surfaces
      // which TF(s) have a live setup for this ticker (armed / entry / R:R / MTF
      // confluence) and lets you jump straight to one.
      if (d._vivek) tfSetups = renderTFSetups(d, tfs, selectTF, () => curTF);
      toggle.querySelectorAll(".tf-btn").forEach((b) =>
        b.addEventListener("click", () => selectTF(b.dataset.tf)));
      applyTF(curTF);
      // Poll a live (~15-min delayed) quote so the header price isn't frozen at
      // the last scan close. Covers ASX / NASDAQ stocks and scalp index /
      // commodity instruments (NAS100, US30, GOLD, SILVER, OIL).
      startStockLive(d, SYM);
    }

    wireChartPosition(candle, d);
    wireLiveBox(d, el, SYM, posDir, findOpen);

    // Fix-10 #4: ⧉ Plan — copy the ACTIVE timeframe's plan as pasteable text.
    const planBtn = $("#cf-plan");
    if (planBtn) planBtn.onclick = async () => {
      const lv = d._activeLevels || { entry: d.entry, stop: d.stop, tp1: d.tp1, tp2: d.tp2, tp3: d.tp3, rr: d.rr };
      if (lv.entry == null) { planBtn.textContent = "— no plan"; setTimeout(() => { planBtn.textContent = "⧉ Plan"; }, 1400); return; }
      const c = d.currency_symbol || "";
      const f = (v) => (v == null || !isFinite(v)) ? "—" : fmt(v, c);
      const txt = `${SYM} ${(d.dir || "LONG").toUpperCase()} — entry ${f(lv.entry)} · SL ${f(lv.stop)} · ` +
        `TP1 ${f(lv.tp1)} / TP2 ${f(lv.tp2)} / TP3 ${f(lv.tp3)} · R:R ${(+lv.rr || 0).toFixed(1)} ` +
        `(${d._activeTf || curTF} plan · ${d.grade || ""} · Vivek 5.0 — not advice)`;
      try { await navigator.clipboard.writeText(txt); planBtn.textContent = "✓ Copied"; }
      catch (_) { planBtn.textContent = "✗ Blocked"; }
      setTimeout(() => { planBtn.textContent = "⧉ Plan"; }, 1600);
    };

    // ── Temporary drawing tools + measure + eraser ───────────────────────────
    // Not persisted — purely for eyeballing structure while viewing. Points are
    // anchored to chart coordinates (logical index + price) so they track pan/
    // zoom; switching timeframe clears them (the data underneath changed).
    initDrawing();
    const alertsApi = initAlerts();   // UX-20 #4: tap-to-set price alert lines
    initReplay();                     // UX-20 #7: bar-by-bar setup replay
    initCompare();                    // UX-20 #8: relative-strength overlay

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      drawRedraw();
    });
    ro.observe(el);

    function initDrawing() {
      const cur = d.currency_symbol || "";
      const tools = $("#draw-tools");
      const canvas = document.createElement("canvas");
      canvas.className = "draw-layer";
      el.style.position = "relative";
      el.appendChild(canvas);
      // Relocate the drawing tools into the timeframe pill row for one clean
      // control strip, instead of a floating overlay. On phones the UX #7
      // bottom sheet owns the tools instead — don't steal them back from it.
      if (tools) {
        tools.hidden = false;
        const tgl = $("#tf-toggle");
        const inSheet = !!document.getElementById("ct-sheet");
        if (tgl && tools.parentNode !== tgl && !inSheet) { tools.classList.add("in-toggle"); tgl.appendChild(tools); }
      }
      // Floating stats label for the measure tool (price Δ, %, bars, time).
      const measureLabel = Object.assign(document.createElement("div"), { className: "measure-label" });
      el.appendChild(measureLabel);

      const ts = chart.timeScale();
      let tool = "cursor";            // cursor | trend | hline | measure | erase
      let drawings = [];              // {type:'trend', a, b} | {type:'hline', price}
      let pending = null;             // first point of a trendline in progress
      let hover = null;               // live cursor point {x,y,logical,price}
      let measure = null;             // locked measurement {a, b}
      let measureDrag = null;         // {a} while dragging out a measurement
      let eraseIdx = -1;              // drawing under the cursor in erase mode

      const setPE = () => { canvas.style.pointerEvents = tool === "cursor" ? "none" : "auto"; };

      function sizeCanvas() {
        const r = el.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.max(1, Math.round(r.width * dpr));
        canvas.height = Math.max(1, Math.round(r.height * dpr));
        canvas.style.width = r.width + "px";
        canvas.style.height = r.height + "px";
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }

      const xOf = (logical) => { const x = ts.logicalToCoordinate(logical); return x == null ? null : x; };
      const yOf = (price) => { const y = candle.priceToCoordinate(price); return y == null ? null : y; };

      // ── time helpers (for the measure tool's bar/day span) ──────────────────
      const PER_BAR_DAYS = { "1H": 1 / 24, "4H": 4 / 24, "1D": 1, "3D": 3, "1W": 7, "1M": 30, "3M": 91 };
      const timeAtLogical = (logical) => {
        const c = (tfs[curTF] && tfs[curTF].candles) || [];
        const i = Math.round(logical);
        return (i >= 0 && i < c.length) ? c[i].time : null;
      };
      function spanText(aLog, bLog) {
        const bars = Math.abs(Math.round(bLog - aLog));
        const t1 = timeAtLogical(aLog), t2 = timeAtLogical(bLog);
        const days = (t1 != null && t2 != null) ? Math.abs(t2 - t1) / 86400
                                                : bars * (PER_BAR_DAYS[curTF] || 1);
        let span;
        if (days < 1) span = `${Math.max(1, Math.round(days * 24))}h`;
        else if (days < 60) span = `${Math.round(days)}d`;
        else if (days < 365) span = `${Math.round(days / 7)}w`;
        else span = `${(days / 365).toFixed(1)}y`;
        return `${bars} bar${bars === 1 ? "" : "s"} · ${span}`;
      }
      // Time at a logical index, EXTRAPOLATED past the last bar (avg bar spacing)
      // so a measurement dragged into the future still gets a projected date.
      function timeAtLogicalExt(logical) {
        const c = (tfs[curTF] && tfs[curTF].candles) || [];
        if (!c.length) return null;
        const i = Math.round(logical), lastI = c.length - 1;
        if (i >= 0 && i <= lastI) return c[i].time;
        const n = Math.min(30, lastI);
        const avg = n > 0 ? (c[lastI].time - c[lastI - n].time) / n : 86400;
        return (i > lastI ? c[lastI].time + (logical - lastI) * avg
                          : c[0].time + logical * avg);
      }
      const fmtDT = (sec) => {
        if (sec == null) return "—";
        const dt = new Date(sec * 1000);
        const d = dt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
        return (curTF === "4H" || curTF === "1H")
          ? d + " " + dt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
          : d;
      };
      // "Jun 12 '26 → 15 Aug '26" for the two endpoints, earliest first.
      function datesText(aLog, bLog) {
        const [lo, hi] = aLog <= bLog ? [aLog, bLog] : [bLog, aLog];
        return `${fmtDT(timeAtLogicalExt(lo))} → ${fmtDT(timeAtLogicalExt(hi))}`;
      }

      // ── hit-testing (for the eraser) ────────────────────────────────────────
      function segDist(px, py, x1, y1, x2, y2) {
        const dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
        let t = L2 ? ((px - x1) * dx + (py - y1) * dy) / L2 : 0;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
      }
      function distToDrawing(d2, px, py) {
        if (d2.type === "hline") { const y = yOf(d2.price); return y == null ? Infinity : Math.abs(py - y); }
        const x1 = xOf(d2.a.logical), y1 = yOf(d2.a.price), x2 = xOf(d2.b.logical), y2 = yOf(d2.b.price);
        if (x1 == null || y1 == null || x2 == null || y2 == null) return Infinity;
        return segDist(px, py, x1, y1, x2, y2);
      }
      function nearestDrawing(px, py) {
        let best = -1, bd = 9;        // 9px hit radius
        drawings.forEach((d2, i) => { const dd = distToDrawing(d2, px, py); if (dd < bd) { bd = dd; best = i; } });
        return best;
      }

      // ── the TradingView-style measurement box + stats label ─────────────────
      function drawMeasure(ctx, a, b) {
        const x1 = xOf(a.logical), y1 = yOf(a.price), x2 = xOf(b.logical), y2 = yOf(b.price);
        if (x1 == null || y1 == null || x2 == null || y2 == null) { measureLabel.style.display = "none"; return; }
        const up = b.price >= a.price, col = up ? "#2fd07f" : "#ff5b5b";
        const left = Math.min(x1, x2), right = Math.max(x1, x2), top = Math.min(y1, y2), bot = Math.max(y1, y2);
        ctx.save();
        ctx.fillStyle = up ? "rgba(47,208,127,0.13)" : "rgba(255,91,91,0.13)";
        ctx.fillRect(left, top, right - left, bot - top);
        ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
        ctx.strokeRect(left, top, Math.max(1, right - left), Math.max(1, bot - top));
        // a vertical arrow down the middle showing the price travel direction
        const mx = (x1 + x2) / 2;
        ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(mx, y1); ctx.lineTo(mx, y2); ctx.stroke();
        ctx.restore();
        // stats label, centred on the box, on the far side of the move
        const delta = b.price - a.price, pct = a.price ? delta / a.price * 100 : 0;
        const sign = delta >= 0 ? "+" : "";
        const ad = Math.abs(a.price) >= 100 ? 2 : Math.abs(a.price) >= 1 ? 3 : Math.abs(a.price) >= 0.01 ? 5 : 8;
        measureLabel.style.display = "block";
        measureLabel.style.borderColor = col; measureLabel.style.color = col;
        measureLabel.style.left = ((left + right) / 2) + "px";
        measureLabel.style.top = (up ? top - 8 : bot + 8) + "px";
        measureLabel.style.transform = `translate(-50%, ${up ? "-100%" : "0"})`;
        measureLabel.innerHTML =
          `<div class="ml-price">${sign}${pct.toFixed(2)}% <span>${sign}${cur}${Math.abs(delta).toFixed(ad)}</span></div>` +
          `<div class="ml-time">${spanText(a.logical, b.logical)}</div>` +
          `<div class="ml-dates">${datesText(a.logical, b.logical)}</div>`;
      }

      function redraw() {
        const ctx = canvas.getContext("2d");
        const w = canvas.width / (window.devicePixelRatio || 1);
        const h = canvas.height / (window.devicePixelRatio || 1);
        ctx.clearRect(0, 0, w, h);
        const seg = (x1, y1, x2, y2) => { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); };
        drawings.forEach((d2, i) => {
          const hot = (i === eraseIdx && (tool === "erase" || tool === "cursor"));   // erase target
          ctx.strokeStyle = hot ? "#ff5b5b" : "#4d9fff";
          ctx.lineWidth = hot ? 2.5 : 1.5;
          if (d2.type === "hline") {
            const y = yOf(d2.price); if (y == null) return;
            ctx.setLineDash([5, 4]); seg(0, y, w, y); ctx.setLineDash([]);
          } else {
            const x1 = xOf(d2.a.logical), y1 = yOf(d2.a.price), x2 = xOf(d2.b.logical), y2 = yOf(d2.b.price);
            if (x1 == null || y1 == null || x2 == null || y2 == null) return;
            seg(x1, y1, x2, y2);
          }
        });
        ctx.lineWidth = 1.5; ctx.strokeStyle = "#4d9fff";
        // live preview of the trendline being drawn
        if (tool === "trend" && pending && hover) {
          const x1 = xOf(pending.logical), y1 = yOf(pending.price);
          if (x1 != null && y1 != null) {
            ctx.setLineDash([3, 3]); ctx.strokeStyle = "#9aa4b2";
            seg(x1, y1, hover.x, hover.y); ctx.setLineDash([]); ctx.strokeStyle = "#4d9fff";
          }
        }
        // measurement: the dragging preview, else the locked one
        if (measureDrag && hover && hover.logical != null && hover.price != null) {
          drawMeasure(ctx, measureDrag.a, { logical: hover.logical, price: hover.price });
        } else if (measure) {
          drawMeasure(ctx, measure.a, measure.b);
        } else {
          measureLabel.style.display = "none";
        }
      }
      drawRedraw = redraw;
      drawClear = () => {
        drawings = []; pending = null; hover = null; measure = null; measureDrag = null; eraseIdx = -1;
        if (delBtn) { delBtn.style.display = "none"; delTarget = -1; }   // also clear the hover trash
        redraw();
      };

      // ── persistence (2026-07-03): drawings survive reloads and TF switches.
      // Stored per ticker + timeframe, anchored by BAR TIME + price (logical
      // indices shift as new bars arrive, times don't).
      const drawKey = () => `gbs:draw:${market}:${(d.symbol || symbol).toUpperCase()}:${curTF}`;
      const l2t = (l) => {
        const cs = (tfs[curTF] || {}).candles || [];
        if (!cs.length || l == null) return null;
        const i = Math.min(cs.length - 1, Math.max(0, Math.round(l)));
        return { t: cs[i].time, off: l - i };
      };
      const t2l = (a) => {
        const cs = (tfs[curTF] || {}).candles || [];
        if (!cs.length || !a || a.t == null) return null;
        let i = cs.findIndex((c) => c.time >= a.t);
        if (i < 0) i = cs.length - 1;
        return i + (a.off || 0);
      };
      function saveDrawings() {
        try {
          const ser = drawings.map((dr) => dr.type === "hline"
            ? { type: "hline", price: dr.price }
            : { type: "trend", a: { ...(l2t(dr.a.logical) || {}), price: dr.a.price },
                b: { ...(l2t(dr.b.logical) || {}), price: dr.b.price } });
          if (ser.length) localStorage.setItem(drawKey(), JSON.stringify(ser));
          else localStorage.removeItem(drawKey());
        } catch (_) {}
      }
      function restoreDrawings() {
        try {
          const raw = JSON.parse(localStorage.getItem(drawKey()) || "[]");
          drawings = raw.map((dr) => dr.type === "hline"
            ? { type: "hline", price: dr.price }
            : { type: "trend",
                a: { logical: t2l(dr.a), price: dr.a.price },
                b: { logical: t2l(dr.b), price: dr.b.price } })
            .filter((dr) => dr.type === "hline" ||
                    (dr.a.logical != null && dr.b.logical != null));
        } catch (_) { drawings = []; }
        redraw();
      }
      drawRestore = restoreDrawings;
      restoreDrawings();   // pick up saved drawings for the initial timeframe

      function ptFromEvent(ev) {
        const r = canvas.getBoundingClientRect();
        const x = ev.clientX - r.left, y = ev.clientY - r.top;
        return { x, y, logical: ts.coordinateToLogical(x), price: candle.coordinateToPrice(y) };
      }

      canvas.addEventListener("pointerdown", (ev) => {
        if (tool === "cursor") return;
        const p = ptFromEvent(ev);
        if (tool === "erase") {
          const i = nearestDrawing(p.x, p.y);
          if (i >= 0) { drawings.splice(i, 1); eraseIdx = -1; redraw(); saveDrawings(); }
          return;
        }
        if (tool === "alert") { alertsApi.toggleAt(p); return; }   // UX-20 #4
        if (p.logical == null || p.price == null) return;
        if (tool === "hline") {
          drawings.push({ type: "hline", price: p.price });
          saveDrawings();
        } else if (tool === "trend") {
          if (!pending) { pending = { logical: p.logical, price: p.price }; }
          else { drawings.push({ type: "trend", a: pending, b: { logical: p.logical, price: p.price } }); pending = null; saveDrawings(); }
        } else if (tool === "measure") {
          measure = null;                          // start a fresh measurement
          measureDrag = { a: { logical: p.logical, price: p.price } };
          hover = p;
          try { canvas.setPointerCapture(ev.pointerId); } catch (_) {}
        }
        redraw();
      });

      canvas.addEventListener("pointermove", (ev) => {
        const r = canvas.getBoundingClientRect();
        const x = ev.clientX - r.left, y = ev.clientY - r.top;
        if (tool === "trend" && pending) { hover = { x, y }; redraw(); }
        else if (tool === "measure" && measureDrag) {
          hover = { x, y, logical: ts.coordinateToLogical(x), price: candle.coordinateToPrice(y) };
          redraw();
        } else if (tool === "erase") {
          const i = nearestDrawing(x, y);
          if (i !== eraseIdx) { eraseIdx = i; el.style.cursor = i >= 0 ? "pointer" : "crosshair"; redraw(); }
        }
      });

      canvas.addEventListener("pointerup", (ev) => {
        if (tool !== "measure" || !measureDrag) return;
        try { canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
        const r = canvas.getBoundingClientRect();
        const x = ev.clientX - r.left, y = ev.clientY - r.top;
        const ax = xOf(measureDrag.a.logical), ay = yOf(measureDrag.a.price);
        const moved = ax == null || ay == null || Math.abs(x - ax) > 3 || Math.abs(y - ay) > 3;
        const logical = ts.coordinateToLogical(x), price = candle.coordinateToPrice(y);
        measure = (moved && logical != null && price != null) ? { a: measureDrag.a, b: { logical, price } } : null;
        measureDrag = null; hover = null;
        redraw();
      });

      // ── simplest erase: hover any drawing (in the default cursor mode) and a
      // trash button appears right on it — one click deletes just that drawing.
      // No mode to enter; works alongside the eraser tool and "clear all".
      const delBtn = Object.assign(document.createElement("button"), {
        className: "draw-del-btn", type: "button", title: "Delete this drawing",
      });
      delBtn.textContent = "🗑";
      delBtn.style.display = "none";
      el.appendChild(delBtn);
      let delTarget = -1, overDel = false, hideTimer = 0;
      const scheduleHide = () => { clearTimeout(hideTimer); hideTimer = setTimeout(() => {
        if (!overDel) { delBtn.style.display = "none"; if (eraseIdx !== -1) { eraseIdx = -1; redraw(); } delTarget = -1; }
      }, 260); };
      delBtn.addEventListener("mouseenter", () => { overDel = true; clearTimeout(hideTimer); });
      delBtn.addEventListener("mouseleave", () => { overDel = false; scheduleHide(); });
      delBtn.addEventListener("click", () => {
        if (delTarget >= 0) { drawings.splice(delTarget, 1); delTarget = -1; eraseIdx = -1; delBtn.style.display = "none"; redraw(); saveDrawings(); }
      });
      chart.subscribeCrosshairMove((param) => {
        if (tool !== "cursor" || !param.point || !drawings.length) { scheduleHide(); return; }
        const i = nearestDrawing(param.point.x, param.point.y);
        if (i >= 0) {
          delTarget = i;
          delBtn.style.left = (param.point.x + 6) + "px";
          delBtn.style.top = (param.point.y - 6) + "px";
          delBtn.style.display = "flex";
          if (eraseIdx !== i) { eraseIdx = i; redraw(); }      // highlight the target red
        } else {
          scheduleHide();
        }
      });

      ts.subscribeVisibleLogicalRangeChange(redraw);

      function selectTool(name, btn) {
        tool = name; pending = null; hover = null; measureDrag = null; eraseIdx = -1;
        if (name !== "measure") { measure = null; }     // leaving measure clears the box
        if (tools && btn) tools.querySelectorAll(".draw-btn[data-tool]").forEach((x) => x.classList.toggle("is-active", x === btn));
        setPE();
        el.style.cursor = name === "cursor" ? "" : "crosshair";
        redraw();
      }

      if (tools) {
        tools.querySelectorAll(".draw-btn[data-tool]").forEach((b) =>
          b.addEventListener("click", () => selectTool(b.dataset.tool, b)));
        const clearBtn = $("#draw-clear");
        if (clearBtn) clearBtn.addEventListener("click", () => { drawClear(); saveDrawings(); });
      }
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && tool !== "cursor") {
          const cursorBtn = tools && tools.querySelector('.draw-btn[data-tool="cursor"]');
          selectTool("cursor", cursorBtn);
        }
      });

      sizeCanvas(); setPE(); redraw();
      // keep the backing store in sync with chart resizes
      const cro = new ResizeObserver(() => { sizeCanvas(); redraw(); });
      cro.observe(el);
    }

    // Small in-chart toast (alerts / replay / compare feedback).
    function chartToast(msg) {
      el.querySelectorAll(".pa-toast").forEach((x) => x.remove());   // never stack
      const t = document.createElement("div");
      t.className = "pa-toast";
      t.textContent = msg;
      el.appendChild(t);
      setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 400); }, 5200);
    }

    // ── UX-20 #4: tap-to-set price alert lines ─────────────────────────────
    // The 🔔 drawing tool: tap a price → a dotted cyan alert line + a saved
    // one-shot alert (gbs:palerts:<market>:<SYM>). It fires as a browser
    // notification (+ in-page toast) when the live tick crosses the level
    // while this chart is open, AND the dashboard checks the same store
    // against every fresh scan — so the alert still lands when this tab is
    // long closed. Tap on/near an existing alert line removes it.
    function initAlerts() {
      const SYMU = (d.symbol || symbol).toUpperCase();
      const KEY = `gbs:palerts:${market}:${SYMU}`;
      const cur = d.currency_symbol || "";
      let list = [];
      try { list = JSON.parse(localStorage.getItem(KEY) || "[]") || []; } catch (_) {}
      const handles = new Map();
      const save = () => { try {
        if (list.length) localStorage.setItem(KEY, JSON.stringify(list));
        else localStorage.removeItem(KEY);
      } catch (_) {} };
      const draw = (a) => {
        handles.set(a, candle.createPriceLine({
          price: a.p, color: "#00d2ff", lineWidth: 1, lineStyle: LC.LineStyle.Dotted,
          axisLabelVisible: true, title: "⏰ ALERT",
        }));
      };
      const remove = (a) => {
        const pl = handles.get(a);
        if (pl) { try { candle.removePriceLine(pl); } catch (_) {} }
        handles.delete(a);
        list = list.filter((x) => x !== a);
        save();
      };
      const fire = (a, px) => {
        const msg = `${SYMU} crossed ${fmt(a.p, cur)} — now ${fmt(px, cur)}`;
        try {
          if ("Notification" in window && Notification.permission === "granted")
            new Notification(`⏰ ${SYMU} price alert`, {
              body: `${msg} · ${MARKET_LABEL[market] || market.toUpperCase()}`,
              icon: "icons/icon-192.png", tag: `pa:${market}:${SYMU}:${a.p}`,
            });
        } catch (_) {}
        chartToast(`⏰ ${msg}`);
        remove(a);
      };
      list.forEach(draw);
      let lastTick = null;
      onLiveTick((px) => {
        if (px == null) return;
        const prev = lastTick; lastTick = px;
        if (!list.length) return;
        list.slice().forEach((a) => {
          const ref = prev != null ? prev : a.ref;
          if (ref == null || ref === px) return;
          if ((ref < a.p && px >= a.p) || (ref > a.p && px <= a.p)) fire(a, px);
        });
      });
      return {
        toggleAt(p) {
          if (p.price == null || !isFinite(p.price)) return;
          for (const [a] of handles) {
            const ay = candle.priceToCoordinate(a.p);
            if (ay != null && p.y != null && Math.abs(ay - p.y) <= 8) {
              remove(a);
              chartToast(`Alert at ${fmt(a.p, cur)} removed`);
              return;
            }
          }
          const a = { p: p.price, ref: liveState.price ?? d.price ?? null, t: Date.now() };
          list.push(a); save(); draw(a);
          try {
            if ("Notification" in window && Notification.permission === "default")
              Notification.requestPermission();
          } catch (_) {}
          chartToast(`⏰ Alert set at ${fmt(a.p, cur)} — fires when price crosses it (here or on the dashboard)`);
        },
      };
    }

    // ── UX-20 #7: setup replay ─────────────────────────────────────────────
    // ▶ REPLAY rewinds the current timeframe to the signal bar (the first
    // Python marker — the 200-SMA reaction) and steps forward bar by bar:
    // slider scrub, ‹ › steps, space to auto-play, arrows on the keyboard.
    // Everything time-anchored (candles, volume, SMAs, momentum, markers,
    // flashes, shading, RS overlay, PhaseMap band spans) is clipped to the
    // scrub point; price-static lines (SL/Entry/TP, alerts) stay. Exiting
    // (or switching TF) restores the full view via applyTF. Live-streamed
    // scalp charts skip replay — the stream would fight the scrubber.
    function initReplay() {
      if (pair) return;
      const tgl = $("#tf-toggle");
      if (!tgl) return;
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "tf-btn replay-btn";
      btn.textContent = "▶ REPLAY";
      btn.title = "Setup replay — rewind to the signal bar, then step forward bar by bar";
      // Fix-10 #9: phones keep the timeframe row clean — the button lives in
      // the ✏ sheet's ANALYZE section there instead.
      const sheetRow = window.__ctSheet && window.__ctSheet.analyzeRow;
      (sheetRow || tgl).appendChild(btn);

      const bar = document.createElement("div");
      bar.className = "replay-bar"; bar.hidden = true;
      bar.innerHTML =
        `<button class="rp-btn" data-rp="sig" title="Jump back to the signal bar">⚑</button>` +
        `<button class="rp-btn" data-rp="back" title="Step back one bar (←)">‹</button>` +
        `<button class="rp-btn rp-play" data-rp="play" title="Play / pause (space)">▶</button>` +
        `<button class="rp-btn" data-rp="fwd" title="Step forward one bar (→)">›</button>` +
        `<input class="rp-slider" type="range" min="12" max="100" value="100" aria-label="Replay position" />` +
        `<span class="rp-pos"></span>` +
        `<button class="rp-btn rp-exit" data-rp="exit" title="Exit replay (Esc)">✕</button>`;
      el.appendChild(bar);
      const slider = bar.querySelector(".rp-slider");
      const posLbl = bar.querySelector(".rp-pos");
      const playBtn = bar.querySelector(".rp-play");

      let idx = 0, timer = 0;
      const cs = () => (tfs[curTF] || {}).candles || [];
      const stopPlay = () => { if (timer) { clearInterval(timer); timer = 0; playBtn.textContent = "▶"; } };

      function rApply(i) {
        const tf = tfs[curTF] || {}; const c = tf.candles || [];
        if (!c.length) return;
        idx = Math.max(Math.min(12, c.length), Math.min(i, c.length));
        const tCut = c[idx - 1].time;
        candle.setData(c.slice(0, idx));
        vol.setData((tf.volume || []).filter((p) => p.time <= tCut));
        lineSeries.forEach((s, k) => {
          const l = tf.lines && tf.lines[k];
          s.setData(l ? l.data.filter((pt) => pt.time <= tCut) : []);
        });
        if (momSeries) momSeries.setData((tf.histogram || []).filter((p) => p.time <= tCut));
        if (typeof candle.setMarkers === "function")
          candle.setMarkers((tf.markers || []).filter((m) => m.time <= tCut));
        setFlashes([...vkFlashes, ...pmFlashes].filter((f) => f.time <= tCut));
        shadeSeries.setData(shadeRows(c.slice(0, idx), curTF));
        rsTrim(tCut);
        pmBands.forEach((b) => b.series.setData(
          [{ time: c[0].time, value: b.z.high }, { time: tCut, value: b.z.high }]));
        chart.timeScale().fitContent();
        drawRedraw();
        slider.value = String(idx);
        const dt = new Date(tCut * 1000);
        posLbl.textContent = `${idx}/${c.length} · ` +
          dt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
        if (idx >= c.length) stopPlay();
      }

      // Start point: the first marker (200-SMA reaction) on this TF, else ~30
      // bars back — "rewind to where the setup began".
      const sigIdx = () => {
        const c = cs();
        const mk = ((tfs[curTF] || {}).markers || [])[0];
        if (mk) { const i = c.findIndex((b) => b.time === mk.time); if (i >= 0) return Math.max(i + 1, 12); }
        return Math.max(12, c.length - 30);
      };

      function enter() {
        const c = cs();
        if (c.length < 15) { chartToast("Not enough bars on this timeframe to replay."); return; }
        if (window.__ctSheet) window.__ctSheet.close();   // show the chart, not the sheet
        replayCtl.active = true;
        btn.classList.add("is-active");
        bar.hidden = false;
        slider.min = "12"; slider.max = String(c.length);
        rApply(sigIdx());
      }
      function exit() {
        if (!replayCtl.active) return;
        stopPlay();
        replayCtl.active = false;
        btn.classList.remove("is-active");
        bar.hidden = true;
        applyTF(curTF);                 // full restore of the real view
      }
      replayCtl.abort = () => {         // applyTF repaints anyway — just reset UI state
        stopPlay();
        replayCtl.active = false;
        btn.classList.remove("is-active");
        bar.hidden = true;
      };
      const togglePlay = () => {
        if (timer) { stopPlay(); return; }
        if (idx >= cs().length) rApply(sigIdx());
        playBtn.textContent = "❚❚";
        timer = setInterval(() => {
          if (idx >= cs().length) { stopPlay(); return; }
          rApply(idx + 1);
        }, 400);
      };

      btn.addEventListener("click", () => (replayCtl.active ? exit() : enter()));
      bar.addEventListener("click", (e) => {
        const b = e.target.closest("[data-rp]"); if (!b) return;
        const k = b.dataset.rp;
        if (k === "exit") exit();
        else if (k === "sig") { stopPlay(); rApply(sigIdx()); }
        else if (k === "back") { stopPlay(); rApply(idx - 1); }
        else if (k === "fwd") { stopPlay(); rApply(idx + 1); }
        else if (k === "play") togglePlay();
      });
      slider.addEventListener("input", () => { stopPlay(); rApply(+slider.value); });
      // Capture-phase keys so ←/→ scrub bars instead of jumping to the
      // prev/next SETUP (wireScanNav listens on the same document).
      document.addEventListener("keydown", (e) => {
        if (!replayCtl.active) return;
        if (e.key === "ArrowLeft") { e.preventDefault(); e.stopImmediatePropagation(); stopPlay(); rApply(idx - 1); }
        else if (e.key === "ArrowRight") { e.preventDefault(); e.stopImmediatePropagation(); stopPlay(); rApply(idx + 1); }
        else if (e.key === "Escape") { e.stopImmediatePropagation(); exit(); }
        else if (e.key === " ") { e.preventDefault(); e.stopImmediatePropagation(); togglePlay(); }
      }, true);
    }

    // ── UX-20 #8: relative-strength overlay ────────────────────────────────
    // ⚖ VS overlays a second instrument (market index / SPY / ETH / any
    // ticker) as a dashed pink line REBASED to this chart's first visible
    // close — divergence between the two lines IS the relative strength.
    // The chip states who's leading over the window; choice persists per
    // market and re-applies on every chart until removed.
    function initCompare() {
      if (pair) return;
      const tgl = $("#tf-toggle");
      if (!tgl) return;
      const SYMU = (d.symbol || symbol).toUpperCase();
      const RS_KEY = `gbs:rs:${market}`;
      const IDX = market === "nasdaq" ? ["^NDX", "NDX"]
                : market === "crypto" ? ["BTC-USD", "BTC"] : ["^AXJO", "XJO"];
      const fmtPct = (x) => (x >= 0 ? "+" : "") + x.toFixed(1) + "%";

      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "tf-btn rs-btn"; btn.textContent = "⚖ VS";
      btn.title = "Relative strength — overlay a rebased index or ticker to see who's leading";
      // Fix-10 #9: button folds into the phone sheet; the CHIP stays on the
      // timeframe row everywhere — it's the live overlay indicator/remover.
      const sheetRow = window.__ctSheet && window.__ctSheet.analyzeRow;
      (sheetRow || tgl).appendChild(btn);
      const chip = document.createElement("button");
      chip.type = "button"; chip.className = "tf-btn rs-chip"; chip.hidden = true;
      tgl.appendChild(chip);
      const menu = document.createElement("div");
      menu.className = "rs-menu"; menu.hidden = true;
      document.body.appendChild(menu);

      let rsSeries = null, rsBars = null, rsLabel = "";
      const ensureSeries = () => rsSeries || (rsSeries = chart.addLineSeries({
        color: "#ff6ad5", lineWidth: 2, lineStyle: LC.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      }));
      // Map compare bars onto this TF's candle times (last daily close at or
      // before each bar; +86399s absorbs day-start timezone stamps).
      const mapRs = (c) => {
        let j = 0; const out = [];
        for (const b of c) {
          while (j + 1 < rsBars.length && rsBars[j + 1].time <= b.time + 86399) j++;
          if (rsBars[j].time <= b.time + 86399) out.push({ time: b.time, value: rsBars[j].close, mc: b.close });
        }
        return out;
      };

      rsApply = (key) => {
        if (!rsSeries) return;
        const c = (tfs[key] || {}).candles || [];
        if (!rsBars || !rsBars.length || !c.length) { rsSeries.setData([]); return; }
        const out = mapRs(c);
        if (out.length < 2) { rsSeries.setData([]); return; }
        const scale = out[0].mc / out[0].value;
        rsSeries.setData(out.map((p) => ({ time: p.time, value: p.value * scale })));
        const mPct = (out[out.length - 1].mc / out[0].mc - 1) * 100;
        const cPct = (out[out.length - 1].value / out[0].value - 1) * 100;
        const lead = mPct >= cPct;
        chip.textContent = `vs ${rsLabel} ${lead ? "▲" : "▼"} ✕`;
        chip.classList.toggle("lead", lead);
        chip.classList.toggle("lag", !lead);
        chip.title = `${SYMU} ${fmtPct(mPct)} vs ${rsLabel} ${fmtPct(cPct)} over this window — ` +
          `${SYMU} is ${lead ? "LEADING" : "LAGGING"}. The dashed pink line is ${rsLabel} ` +
          `rebased to the first bar. Tap to remove.`;
      };
      rsTrim = (tCut) => {              // replay support: clip to the scrub point
        if (!rsSeries || !rsBars || !rsBars.length) return;
        const c = ((tfs[curTF] || {}).candles || []).filter((b) => b.time <= tCut);
        const out = c.length >= 2 ? mapRs(c) : [];
        if (out.length < 2) { rsSeries.setData([]); return; }
        const scale = out[0].mc / out[0].value;
        rsSeries.setData(out.map((p) => ({ time: p.time, value: p.value * scale })));
      };

      function clearOverlay() {
        rsBars = null; rsLabel = "";
        if (rsSeries) rsSeries.setData([]);
        chip.hidden = true; btn.classList.remove("is-active");
        try { localStorage.removeItem(RS_KEY); } catch (_) {}
      }
      function load(cands, label, persist) {
        const tryOne = (i) => {
          if (i >= cands.length) {
            if (persist) chartToast(`Couldn't load "${label}" — try the full Yahoo form (BHP.AX, ^NDX, BTC-USD).`);
            else { try { localStorage.removeItem(RS_KEY); } catch (_) {} }   // stale saved compare
            return;
          }
          yahooBars(cands[i], "1y", "1d")
            .then((bars) => {
              if (!bars || bars.length < 5) throw new Error("empty");
              rsBars = bars; rsLabel = label;
              ensureSeries(); rsApply(curTF);
              chip.hidden = false; btn.classList.add("is-active");
              if (persist && window.__ctSheet) window.__ctSheet.close();   // #9: reveal the overlay
              if (persist) { try { localStorage.setItem(RS_KEY, JSON.stringify({ yf: cands[i], label })); } catch (_) {} }
            })
            .catch(() => tryOne(i + 1));
        };
        tryOne(0);
      }
      const normalize = (raw) => {
        const up = String(raw || "").trim().toUpperCase();
        if (!up || up.length > 15 || !/^[\w.\-^=]+$/.test(up)) return null;
        if (/[\^=.]/.test(up) || /-USD$/.test(up)) return { c: [up], label: up.replace(/\.AX$/, "") };
        if (market === "crypto") return { c: [up + "-USD"], label: up };
        if (market === "asx") return { c: [up + ".AX", up], label: up };   // try ASX first, then the bare US symbol
        return { c: [up], label: up };
      };

      const onDoc = (e) => { if (!menu.contains(e.target) && e.target !== btn) close(); };
      function close() { menu.hidden = true; document.removeEventListener("click", onDoc); }
      function openMenu() {
        menu.innerHTML =
          `<button class="rsm-opt" data-rs="idx">${IDX[1]} · market index</button>` +
          (market === "crypto"
            ? `<button class="rsm-opt" data-rs="eth">ETH · Ethereum</button>`
            : `<button class="rsm-opt" data-rs="spy">SPY · S&amp;P 500</button>`) +
          `<div class="rsm-custom"><input class="rsm-in" type="text" placeholder="Ticker (BHP, NVDA, ^NDX…)" ` +
            `spellcheck="false" autocomplete="off" /><button class="rsm-go" type="button" title="Apply">→</button></div>` +
          (rsBars ? `<button class="rsm-opt rsm-off" data-rs="off">✕ remove overlay</button>` : "");
        const r = btn.getBoundingClientRect();
        menu.style.left = Math.max(8, Math.min(r.left, innerWidth - 236)) + "px";
        menu.style.top = (r.bottom + 6) + "px";
        menu.hidden = false;
        const applyCustom = () => {
          const n = normalize(menu.querySelector(".rsm-in").value);
          if (n) { load(n.c, n.label, true); close(); }
        };
        menu.querySelector(".rsm-go").addEventListener("click", applyCustom);
        menu.querySelector(".rsm-in").addEventListener("keydown", (e) => { if (e.key === "Enter") applyCustom(); });
        menu.querySelectorAll(".rsm-opt").forEach((b) => b.addEventListener("click", () => {
          const k = b.dataset.rs;
          if (k === "idx") load([IDX[0]], IDX[1], true);
          else if (k === "spy") load(["SPY"], "SPY", true);
          else if (k === "eth") load(["ETH-USD"], "ETH", true);
          else if (k === "off") clearOverlay();
          close();
        }));
        setTimeout(() => document.addEventListener("click", onDoc), 0);
      }
      btn.addEventListener("click", () => (menu.hidden ? openMenu() : close()));
      chip.addEventListener("click", clearOverlay);

      // Sticky: re-apply the saved compare for this market on every chart.
      try {
        const saved = JSON.parse(localStorage.getItem(RS_KEY) || "null");
        if (saved && saved.yf) load([saved.yf], saved.label || saved.yf, false);
      } catch (_) {}
    }
  }

  // Live Binance feed controller. The forming candle ticks in real time, the
  // indicators recompute on each update, and the timeframe (15m/30m/1h) can be
  // switched on the fly. Falls back silently to whatever was painted if the
  // network/stream is unavailable.
  function makeLive(d, pair, S) {
    const cur = d.currency_symbol || "";
    const N_DISP = 120, KEEP = 1000;   // KEEP = Binance max per request → deepest intraday history
    const liveEl = $("#ct-live"), priceEl = $("#ct-price");
    let bars = [], ws = null, stopped = false, lastCalc = 0, lastPx = null;
    let iv = "1h", ivSec = 3600;

    const restURL   = () => `https://api.binance.com/api/v3/klines?symbol=${pair}&interval=${iv}&limit=${KEEP}`;
    const streamURL = () => `wss://stream.binance.com:9443/ws/${pair.toLowerCase()}@kline_${iv}`;

    const setMarks = (marks) => {
      if (typeof S.candle.setMarkers !== "function") return;
      const em = buildEntryMarker(S.entryEpoch, ivSec, S.posDir);
      S.candle.setMarkers(em ? [...marks, em] : marks);
    };

    const applyAll = (fit) => {
      S.candle.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
      S.vol.setData(bars.map((b) => ({ time: b.time, value: Math.round(b.volume),
        color: b.close >= b.open ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.5)" })));
      // #9: alternating-day + weekend banding on the live intraday stream too
      if (S.shadeSeries) S.shadeSeries.setData(
        shadeRows(bars, iv === "1h" ? "1H" : iv === "30m" ? "30M" : "15M"));
      const c = computeScalp(bars, N_DISP);
      c.lineData.forEach((ld, i) => S.lineSeries[i] && S.lineSeries[i].setData(ld));
      if (S.momSeries) S.momSeries.setData(c.hist);
      setMarks(c.markers);
      if (fit) S.chart.timeScale().fitContent();
    };

    const setPrice = (px) => {
      liveState.price = px;
      if (priceEl) {
        priceEl.textContent = fmt(px, cur);
        if (lastPx != null && px !== lastPx) {
          priceEl.classList.remove("tick-up", "tick-down");
          void priceEl.offsetWidth;
          priceEl.classList.add(px > lastPx ? "tick-up" : "tick-down");
        }
        lastPx = px;
      }
      liveState.listeners.forEach((fn) => { try { fn(px); } catch (_) {} });
    };

    function load() {
      return binanceKlines(pair, iv, KEEP).then((rows) => {
        bars = rows;
        if (!bars.length) return;
        applyAll(true);
        setPrice(bars[bars.length - 1].close);
        if (liveEl) liveEl.hidden = false;
      });
    }

    function connect() {
      if (stopped) return;
      try { ws = new WebSocket(streamURL()); } catch (_) { return; }
      ws.onmessage = (ev) => {
        let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
        const k = m.k; if (!k) return;
        const t = Math.floor(k.t / 1000);
        const bar = { time: t, open: +k.o, high: +k.h, low: +k.l, close: +k.c, volume: +k.v };
        const last = bars[bars.length - 1];
        if (last && last.time === t) bars[bars.length - 1] = bar;
        else if (!last || t > last.time) { bars.push(bar); if (bars.length > KEEP) bars.shift(); }
        else return;

        S.candle.update({ time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
        S.vol.update({ time: bar.time, value: Math.round(bar.volume),
          color: bar.close >= bar.open ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.5)" });
        setPrice(bar.close);

        const now = Date.now();               // throttle the heavier indicator recompute
        if (now - lastCalc > 700) {
          lastCalc = now;
          const c = computeScalp(bars, N_DISP);
          c.lineData.forEach((ld, i) => S.lineSeries[i] && S.lineSeries[i].setData(ld));
          if (S.momSeries) S.momSeries.setData(c.hist);
          setMarks(c.markers);
        }
      };
      ws.onclose = () => { if (!stopped) setTimeout(connect, 3000); };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    }

    function closeWs() { if (ws) { try { ws.onclose = null; ws.close(); } catch (_) {} } ws = null; }

    function start() { load().then(connect).catch(() => {}); }
    function switchTo(ivKey) {
      const niv = BINANCE_IV[ivKey];
      if (!niv || niv === iv) return;
      iv = niv; ivSec = niv === "15m" ? 900 : niv === "30m" ? 1800 : 3600;
      closeWs(); lastPx = null;
      load().then(connect).catch(() => {});
    }

    window.addEventListener("beforeunload", () => { stopped = true; closeWs(); });
    return { start, switchTo };
  }

  // Let the user drag the floating LIVE box anywhere on the chart; its spot is
  // remembered across reloads (and across symbols). Works with mouse and touch.
  function makeLiveBoxDraggable(box, container) {
    const KEY = "gbs:livebox_pos";
    const clamp = (v, max) => Math.max(0, Math.min(v, Math.max(0, max)));

    function place(left, top) {
      const cr = container.getBoundingClientRect();
      box.style.left  = clamp(left, cr.width  - box.offsetWidth)  + "px";
      box.style.top   = clamp(top,  cr.height - box.offsetHeight) + "px";
      box.style.right = "auto";
    }
    // Restore a saved position once the box has real dimensions (it starts hidden).
    function restore() {
      let p = null;
      try { p = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) {}
      if (p && box.offsetWidth) place(p.left, p.top);
    }

    let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
    const pointOf = (e) => (e.touches && e.touches[0]) ? e.touches[0] : e;

    function onDown(e) {
      const pt = pointOf(e);
      const r = box.getBoundingClientRect();
      const cr = container.getBoundingClientRect();
      ox = r.left - cr.left; oy = r.top - cr.top;
      sx = pt.clientX; sy = pt.clientY;
      dragging = true;
      box.classList.add("dragging");
      place(ox, oy);
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      document.addEventListener("touchmove", onMove, { passive: false });
      document.addEventListener("touchend", onUp);
      e.preventDefault();
    }
    function onMove(e) {
      if (!dragging) return;
      const pt = pointOf(e);
      place(ox + (pt.clientX - sx), oy + (pt.clientY - sy));
      if (e.cancelable) e.preventDefault();
    }
    function onUp() {
      if (!dragging) return;
      dragging = false;
      box.classList.remove("dragging");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
      try {
        localStorage.setItem(KEY, JSON.stringify({
          left: parseFloat(box.style.left) || 0,
          top:  parseFloat(box.style.top)  || 0,
        }));
      } catch (_) {}
    }
    box.addEventListener("mousedown", onDown);
    box.addEventListener("touchstart", onDown, { passive: false });
    // Re-apply the saved spot the first time the box is shown and on resize.
    box.__restorePos = restore;
    window.addEventListener("resize", restore);
  }

  // 🤖 Claude's open positions get a DOG-BALLS banner pinned over the chart
  // (owner 2026-07-10): the scanner's read can flip AFTER entry — a long
  // reclaim at the 200-SMA can grade as a short reject hours later — so the
  // chart must state loudly what direction the position was TAKEN as, and
  // shout when the current read disagrees.
  // Mounted from boot() into the STATIC .chart-main container, so it shows
  // on every render path (saved chart, VIVEK live fallback, PhaseMap-only).
  async function wireBotPosBanner() {
    if (market === "scalp") return;
    const host = document.querySelector(".chart-main");
    if (!host) return;
    try {
      const [bookR, scanR] = await Promise.all([
        fetch("data/vivek_bot_book.json", { cache: "no-cache" }),
        fetch(`data/${market}_vivek.json`, { cache: "no-cache" }),
      ]);
      if (!bookR.ok) return;
      const book = await bookR.json();
      const want = decodeURIComponent(symbol || "").toUpperCase();
      const pos = (book.open || []).find((p) =>
        String(p.symbol).toUpperCase() === want &&
        (p.market || market) === market && p.status !== "closed");
      if (!pos) return;
      const dirUp = String(pos.direction || "long").toUpperCase();
      let flip = "";
      if (scanR.ok) {
        const j = await scanR.json();
        const row = (j.results || []).find((r) => String(r.symbol).toUpperCase() === want);
        const nowDir = row ? String(row.dir || "").toUpperCase() : null;
        if (nowDir && nowDir !== dirUp) {
          flip = `<div class="bpb-flip">⚠ THE CHART NOW READS ${esc(nowDir)} — this setup flipped AFTER entry. ` +
            `It was a ${esc(pos.grade || "")} ${esc(dirUp)} ${esc(pos.entry_type || "")} when taken.</div>`;
        }
      }
      const isLong = dirUp !== "SHORT";
      const fp = (x) => x == null || !isFinite(x) ? "—"
        : x < 0.1 ? (+x).toFixed(4) : x < 2 ? (+x).toFixed(3) : (+x).toFixed(2);
      const div = document.createElement("div");
      div.className = "bot-pos-banner " + (isLong ? "long" : "short");
      div.innerHTML =
        `<div class="bpb-head">🤖 CLAUDE IS <b class="bpb-dir">${isLong ? "▲ LONG" : "▼ SHORT"}</b> ${esc(want)}` +
        `<span class="bpb-sub">taken ${esc(pos.entry_date || "")} @ ${fp(pos.entry)} · SL ${fp(pos.stop)} · TP1 ${fp(pos.tp1)}</span></div>` +
        flip;
      host.insertBefore(div, host.firstChild);
    } catch (_) { /* banner is best-effort */ }
  }

  // Floating LIVE box — shows the full state of the open position (entry, time,
  // current, P&L, R, move %, stop/target distance, time-in-trade) and updates on
  // every tick. Visible only while a matching position is open.
  function wireLiveBox(d, el, SYM, posDir, findOpen) {
    const cur        = d.currency_symbol || "";
    // Crypto when the row says so, or the market is crypto. Scalp charts now
    // always carry a real asset_type, so an index/commodity (NAS100, GOLD) is
    // correctly treated as a stock-style position rather than crypto.
    const isCryptoPos = d.asset_type === "crypto" || market === "crypto";
    const posBrok    = (data) => isCryptoPos ? data.crypto_brokerage : data.stock_brokerage;
    const box = document.createElement("div");
    box.className = "live-pos-box";
    box.style.display = "none";
    el.style.position = "relative";
    el.appendChild(box);
    makeLiveBoxDraggable(box, el);

    // Banner shown when a manual position auto-closes on stop/target.
    const banner = document.createElement("div");
    banner.style.display = "none";
    el.appendChild(banner);

    const dur = (t) => {
      if (!t || !t.entry_date) return "—";
      const start = new Date(`${t.entry_date}T${(t.entry_time || "00:00")}:00`).getTime();
      let s = Math.max(0, Math.floor((Date.now() - start) / 1000));
      const dd = Math.floor(s / 86400); s -= dd * 86400;
      const hh = Math.floor(s / 3600);  s -= hh * 3600;
      const mm = Math.floor(s / 60);
      return (dd ? dd + "d " : "") + (hh ? hh + "h " : "") + mm + "m";
    };

    // Auto-close a MANUALLY-logged position when the live price hits its stop or
    // target. Sim trades are handled separately by wireSim(); we skip them here
    // to avoid double-closing. Fires only while this chart page is open — it is a
    // simulator, not a resting exchange order. A banner shows when it triggers.
    function maybeAutoClose(px) {
      const t = findOpen();
      if (!t || t.sim || px == null) return false;
      const stopped  = t.stop   != null && (posDir === "long" ? px <= t.stop   : px >= t.stop);
      const targeted = t.target != null && (posDir === "long" ? px >= t.target : px <= t.target);
      if (!stopped && !targeted) return false;
      const data = mjLoad();
      const rec  = data.trades.find((x) => x.id === t.id);
      if (!rec || rec.status === "closed") return true;
      // Honest fills: a stop that gaps through fills at the worse live price
      // (never better than the stop); a target never credits overshoot.
      const fillPx = stopped
        ? (posDir === "long" ? Math.min(t.stop, px) : Math.max(t.stop, px))
        : t.target;
      rec.status = "closed"; rec.exit = fillPx;
      rec.exit_date = nowDate(); rec.exit_time = nowTime();
      rec.auto_closed = stopped ? "stop" : "target";
      rec.mtime = Date.now();
      mjSaveLocal(data);   // rule-computed auto-close → local only
      const m   = posDir === "long" ? 1 : -1;
      const pnl = t.shares * m * (fillPx - t.entry) - 2 * posBrok(data);
      banner.className = "lpb-banner " + (stopped ? "neg" : "pos");
      banner.innerHTML = `${stopped ? "🛑 STOP HIT" : "🎯 TARGET HIT"} — auto-closed @ ${fmt(fillPx, cur)} · ` +
        `P&L ${pnl >= 0 ? "+" : ""}${cur}${pnl.toFixed(2)} <small>(logged to your journal)</small>`;
      banner.style.display = "block";
      if (liveState.entryLineFns) liveState.entryLineFns.remove();
      return true;
    }

    function update(px) {
      if (maybeAutoClose(px)) { box.style.display = "none"; return; }
      const t = findOpen();
      if (!t) { box.style.display = "none"; return; }
      const wasHidden = box.style.display === "none";
      box.style.display = "block";
      // Apply the saved drag position once the box has real dimensions.
      if (wasHidden && box.__restorePos) box.__restorePos();
      const m     = posDir === "long" ? 1 : -1;
      const data  = mjLoad(), brok = posBrok(data);
      const price = px || liveState.price || t.entry;
      const net   = t.shares * m * (price - t.entry) - 2 * brok;
      const move  = (price - t.entry) / t.entry * 100 * m;       // signed in trade's favour
      let rStr = "—", rCls = "";
      if (t.stop != null) {
        const risk = posDir === "long" ? t.entry - t.stop : t.stop - t.entry;
        if (risk > 0) { const r = (m * (price - t.entry)) / risk; rStr = (r >= 0 ? "+" : "") + r.toFixed(2) + "R"; rCls = r >= 0 ? "pos" : "neg"; }
      }
      const pnlCls   = net >= 0 ? "pos" : "neg";
      const distStop = t.stop   != null ? Math.abs((price - t.stop) / price * 100)   : null;
      const distTgt  = t.target != null ? Math.abs((t.target - price) / price * 100) : null;
      box.innerHTML =
        `<div class="lpb-head ${posDir}"><span class="lpb-dot"></span> IN ${posDir.toUpperCase()} · ${SYM}` +
          `<span class="lpb-units">${fmtUnits(t.shares)} u${levTag(t)}</span></div>` +
        `<div class="lpb-pnl ${pnlCls}">${net >= 0 ? "+" : ""}${cur}${net.toFixed(2)}</div>` +
        `<div class="lpb-grid">` +
          `<span class="lpb-k">Entry</span><span class="lpb-v">${fmt(t.entry, cur)}</span>` +
          `<span class="lpb-k">Now</span><span class="lpb-v">${fmt(price, cur)}</span>` +
          `<span class="lpb-k">Move</span><span class="lpb-v ${move >= 0 ? "pos" : "neg"}">${move >= 0 ? "+" : ""}${move.toFixed(2)}%</span>` +
          `<span class="lpb-k">R mult</span><span class="lpb-v ${rCls}">${rStr}</span>` +
          `<span class="lpb-k">Stop</span><span class="lpb-v neg">${t.stop != null ? fmt(t.stop, cur) : "—"}${distStop != null ? ` <small>(${distStop.toFixed(2)}%)</small>` : ""}</span>` +
          `<span class="lpb-k">Target</span><span class="lpb-v pos">${t.target != null ? fmt(t.target, cur) : "—"}${distTgt != null ? ` <small>(${distTgt.toFixed(2)}%)</small>` : ""}</span>` +
          `<span class="lpb-k">Opened</span><span class="lpb-v">${t.entry_date || "—"} ${t.entry_time || ""}</span>` +
          `<span class="lpb-k">In trade</span><span class="lpb-v">${dur(t)}</span>` +
        `</div>`;
    }

    onLiveTick(update);
    update();
    const durIv = setInterval(() => { if (findOpen()) update(); }, 30000);
    window.addEventListener("beforeunload", () => clearInterval(durIv), { once: true });
  }

  // ── entry point ────────────────────────────────────────────────────────────
  // A `pos` param means "open the chart for this journal position" — render it
  // live (crypto) with the entry, entry time and a floating LIVE box.
  function renderPosition(id) {
    const trade = mjLoad().trades.find((t) => t.id === id);
    if (!trade) { fail("That position is no longer in your journal."); return; }
    const SYM = (trade.symbol || "").toUpperCase();
    const d = {
      symbol: SYM, name: SYM, price: trade.entry, entry: trade.entry,
      stop: trade.stop ?? null, target: trade.target ?? null,
      grade: "", score: 0, score_max: 0, chips: [], sector: "",
      asset_type: trade.asset_type,
      currency_symbol: "$", dir: trade.direction === "short" ? "SHORT" : "LONG",
      rr: 0, low_rr: false, rr_text: "", risk_pct: null,
      analysis: trade.notes || "Your open position — live view.",
      default_tf: "1H", tv_symbol: SYM, level_lines: [], timeframes: {},
    };
    if (trade.stop   != null) d.level_lines.push({ price: trade.stop,   color: "#ff5b5b", title: "STOP" });
    d.level_lines.push({ price: trade.entry, color: "#f0a500", title: "ENTRY" });
    if (trade.target != null) d.level_lines.push({ price: trade.target, color: "#2fd07f", title: "TARGET" });

    // Crypto = anything that isn't a known stock-style asset type (matches the
    // journal's bucketing; legacy crypto trades have null/"" asset_type).
    const STOCK_TYPES = ["asx", "nasdaq", "commodity", "index"];
    const pair = STOCK_TYPES.includes(trade.asset_type) ? null : cryptoPair(SYM);
    if (pair) {
      binanceKlines(pair, "1h", 1000)
        .then((bars) => { d.timeframes["1H"] = barsToTF(bars); render(d); })
        .catch(() => fail(`Couldn't load live data for ${SYM} right now.`));
    } else {
      const isStock = trade.asset_type === "asx" || trade.asset_type === "nasdaq";
      let stockTick = null;
      if (isStock) {
        const liveBadge = $("#ct-live");
        if (liveBadge) { liveBadge.hidden = false; }
        let lastStockPx = null;
        const priceHd = $("#ct-price");
        stockTick = async () => {
          if (document.hidden) return;   // backgrounded tab: don't burn the quote relay
          const price = await fetchStockQuote(SYM, trade.asset_type);
          if (price == null) return;
          liveState.price = price;
          if (priceHd) {
            if (lastStockPx != null && price !== lastStockPx) {
              priceHd.classList.remove("tick-up", "tick-down");
              void priceHd.offsetWidth;
              priceHd.classList.add(price > lastStockPx ? "tick-up" : "tick-down");
            }
            priceHd.textContent = fmt(price, "$");
            lastStockPx = price;
          }
          liveState.listeners.forEach((fn) => { try { fn(price); } catch (_) {} });
        };
        const pollIv = setInterval(stockTick, 15000);
        window.addEventListener("beforeunload", () => clearInterval(pollIv), { once: true });
      }

      // Try to fetch the scan JSON for chart context; fall back to a minimal stub so
      // the live position box and level lines still render when no scan JSON exists.
      fetch(chartFile, { cache: "no-cache" })
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then((j) => { render(j); if (stockTick) stockTick(); })
        .catch(() => {
          const ts  = Math.floor(Date.now() / 1000);
          const ep  = trade.entry;
          // Use exactly 1 minMove unit as the high/low spread so the stub is valid
          // even for sub-micro-cap prices where a % spread collapses to zero after
          // lightweight-charts' internal quantisation.
          const absEp  = Math.abs(ep || 1);
          const prec0  = absEp >= 100 ? 2 : absEp >= 1 ? 3 : absEp >= 0.1 ? 4 : absEp >= 0.01 ? 5 : absEp >= 0.001 ? 6 : 8;
          const mv     = Math.pow(10, -prec0);
          d.timeframes["1D"] = {
            candles: [
              { time: ts - 86400, open: ep, high: ep + mv, low: Math.max(ep - mv, 0), close: ep },
              { time: ts,         open: ep, high: ep + mv, low: Math.max(ep - mv, 0), close: ep },
            ],
            volume: [
              { time: ts - 86400, value: 0, color: "rgba(47,208,127,0.5)" },
              { time: ts,         value: 0, color: "rgba(47,208,127,0.5)" },
            ],
            lines: [],
          };
          d.default_tf = "1D";
          render(d);
          if (stockTick) stockTick();
        });
    }
  }

  // ── prev / next through the scanner result list ──────────────────────────────
  // Lets you step down the same scan (e.g. all ASX reversals) without bouncing
  // back to the dashboard. Reads the scan-results JSON that backs this chart,
  // finds the current symbol's position, and wires the header arrows + ←/→ keys.
  function wireScanNav() {
    const nav = $("#ct-nav"), prevB = $("#ct-prev"), nextB = $("#ct-next"), posEl = $("#ct-nav-pos");
    if (!nav || !symbol) return;

    // src=phasemap|specs (2026-07-03): step through the lens the user came
    // from — previously the arrows only knew the VIVEK list, so browsing
    // PhaseMap/Specs results meant a round-trip to the tab per ticker.
    const navSrc = (params.get("src") || "").toLowerCase();
    const isScalp = market === "scalp";
    const suffix  = mode === "reversal" ? "_reversal" : mode === "spec" ? "_spec"
                  : mode === "short"    ? "_short"    : mode === "vivek" ? "_vivek" : "";
    let file = isScalp ? "data/scalp.json" : `data/${market}${suffix}.json`;
    let sOf = isScalp
      ? (r) => `${r.symbol}_${String(r.dir || "").toLowerCase()}`
      : (r) => r.symbol;
    let hrefFor = (s) => isScalp
      ? `chart.html?m=scalp&s=${encodeURIComponent(s)}`
      : `chart.html?m=${market}&s=${encodeURIComponent(s)}${mode !== "pullback" ? `&mode=${mode}` : ""}`;

    // flt=… carries the source page's filters + sort, so the arrows step
    // through exactly the list the user was looking at (2026-07-03).
    const fltRaw = (params.get("flt") || "").split("~");
    let listFilter = (rows) => rows;
    if (navSrc === "phasemap") {
      file = `data/phasemap/${market}/latest.json`;
      // one entry per (ticker, direction) so both sides of a name are stepped
      sOf = (r) => `${r.ticker}|${r.direction}`;
      hrefFor = (key) => {
        const [t, dir] = String(key).split("|");
        return `chart.html?m=${market}&s=${encodeURIComponent(t)}&dir=${dir}&src=phasemap` +
          (params.get("flt") ? `&flt=${encodeURIComponent(params.get("flt"))}` : "");
      };
      const [view, tier, dirF, hideIll, sort] = fltRaw;
      const PM_VIEWS = {
        setups: ["RUNNING", "DISPLACED"], watch: ["TRAP_SET", "SWEPT"],
        rotation: ["STALLED"], ended: ["COMPLETE", "DEAD"],
      };
      const states = PM_VIEWS[view] || null;   // all/watchlist -> no state filter
      const evDate = (r) => {
        const mm = r.metrics || {};
        return (mm.displacement_date || "") > (mm.sweep_date || "")
          ? mm.displacement_date : (mm.sweep_date || "");
      };
      const zRR = (r) => {
        const c = r.metrics && r.metrics.close;
        const hardZ = (r.zones || []).find((z) => z.id === "inv_hard");
        const tgtZ = (r.zones || []).find((z) => z.type === "TARGET" && z.status !== "CONSUMED");
        if (c == null || !hardZ || !tgtZ) return null;
        const bull2 = r.direction !== "bearish";
        const rew = bull2 ? (tgtZ.low + tgtZ.high) / 2 - c : c - (tgtZ.low + tgtZ.high) / 2;
        const rsk = bull2 ? c - hardZ.low : hardZ.high - c;
        return rsk > 0 && rew > 0 ? rew / rsk : null;
      };
      listFilter = (rows) => {
        let out = rows.filter((r) =>
          (!states || states.includes(r.state)) &&
          (!tier || tier === "all" || r.tier === tier) &&
          (!dirF || dirF === "all" || r.direction === dirF) &&
          (hideIll !== "1" || !(r.tags || []).includes("ILLIQUID")));
        const bynum = (fn) => (a, b) => (fn(b) ?? -Infinity) - (fn(a) ?? -Infinity)
          || a.ticker.localeCompare(b.ticker);
        if (sort === "fresh") out = [...out].sort((a, b) =>
          String(evDate(b)).localeCompare(String(evDate(a))) || a.ticker.localeCompare(b.ticker));
        else if (sort === "turnover") out = [...out].sort(bynum((r) => r.metrics && r.metrics.avg_turnover_20d));
        else if (sort === "zrr") out = [...out].sort(bynum(zRR));
        return out;
      };
    } else if (navSrc === "specs") {
      file = `data/${market}_spec.json`;
      sOf = (r) => r.symbol;
      hrefFor = (s2) => `chart.html?m=${market}&s=${encodeURIComponent(s2)}&mode=spec&src=specs` +
        (params.get("flt") ? `&flt=${encodeURIComponent(params.get("flt"))}` : "");
      const [grade, sort] = fltRaw;
      listFilter = (rows) => {
        let out = rows.filter((r) => !grade || grade === "all" || r.grade === grade);
        const bynum = (fn, asc) => (a, b) => (asc ? 1 : -1) *
          ((fn(a) ?? (asc ? Infinity : -Infinity)) - (fn(b) ?? (asc ? Infinity : -Infinity)))
          || a.symbol.localeCompare(b.symbol);
        if (sort === "spike") out = [...out].sort(bynum((r) => r.spike_ratio));
        else if (sort === "rr") out = [...out].sort(bynum((r) => r.rr));
        else if (sort === "price") out = [...out].sort(bynum((r) => r.price, true));
        return out;
      };
    }

    fetch(file, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        const list = listFilter((j && j.results) || []).map(sOf);
        const cur = navSrc === "phasemap"
          ? `${decodeURIComponent(symbol).toUpperCase()}|${pmDirWanted || "bullish"}`
          : decodeURIComponent(symbol).toUpperCase();
        const idx  = list.findIndex((s) => String(s).toUpperCase() === cur.toUpperCase());
        if (idx < 0 || list.length < 2) return;   // not in this list → leave nav hidden

        nav.hidden = false;
        posEl.textContent = `${idx + 1} / ${list.length}`;
        const go = (i) => { if (i >= 0 && i < list.length) location.href = hrefFor(list[i]); };
        prevB.disabled = idx === 0;
        nextB.disabled = idx === list.length - 1;
        prevB.onclick = () => go(idx - 1);
        nextB.onclick = () => go(idx + 1);
        document.addEventListener("keydown", (e) => {
          if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
          if (e.key === "ArrowLeft"  && idx > 0)               go(idx - 1);
          if (e.key === "ArrowRight" && idx < list.length - 1) go(idx + 1);
        });
        // #75: swipe left/right to step the list — but NOT on the chart canvas
        // (it owns horizontal drag for panning) or the drawing layer. Swiping
        // the header / toolbar / footer frame changes setup; a clear, mostly-
        // horizontal flick only.
        let tsX = 0, tsY = 0, onCanvas = false;
        document.addEventListener("touchstart", (e) => {
          const t = e.changedTouches[0]; tsX = t.clientX; tsY = t.clientY;
          onCanvas = !!(e.target.closest && e.target.closest("#chart, .draw-layer, .draw-tools"));
        }, { passive: true });
        document.addEventListener("touchend", (e) => {
          if (onCanvas) return;
          const t = e.changedTouches[0];
          const dx = t.clientX - tsX, dy = t.clientY - tsY;
          if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 2) return;
          if (dx > 0 && idx > 0) go(idx - 1);              // swipe right → previous
          else if (dx < 0 && idx < list.length - 1) go(idx + 1);  // swipe left → next
        }, { passive: true });
      })
      .catch(() => {});
  }

  // The base instrument symbol (scalp charts are keyed "<SYM>_<dir>", but the
  // live feeds want just "<SYM>").
  const baseSymbol = market === "scalp"
    ? decodeURIComponent(symbol).replace(/_(long|short)$/i, "")
    : decodeURIComponent(symbol);

  // Pull the scan-results row for this symbol so the live fallback can still
  // show grade / entry / stop / target even when the per-ticker chart JSON is
  // missing. Resolves to null if the results file or row isn't found.
  function fetchResultMeta() {
    const isScalp = market === "scalp";
    const suffix  = mode === "reversal" ? "_reversal" : mode === "spec" ? "_spec"
                  : mode === "short"    ? "_short"    : mode === "vivek" ? "_vivek" : "";
    const file    = isScalp ? "data/scalp.json" : `data/${market}${suffix}.json`;
    const sOf     = isScalp
      ? (r) => `${r.symbol}_${String(r.dir || "").toLowerCase()}`
      : (r) => r.symbol;
    const want = decodeURIComponent(symbol).toUpperCase();
    return fetch(file, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        const rows = (j && j.results) || [];
        const row  = rows.find((r) => String(sOf(r)).toUpperCase() === want);
        if (row && j) {
          // Carry the per-scan currency onto the row so the fallback labels match.
          row.currency_symbol = row.currency_symbol || j.currency_symbol || "$";
        }
        return row || null;
      })
      .catch(() => null);
  }

  // No static chart anywhere → render from live history instead of dead-ending.
  function fallbackFromLive() {
    fetchResultMeta().then((meta) => liveFallback(baseSymbol, meta));
  }

  // ── Mobile control sheet (UX top-10 #7, 2026-07-26) ───────────────────────
  // On phones the drawing tools floated cramped over the canvas corner and the
  // Share/PNG actions sat below the fold. A ✏ FAB now opens a bottom sheet
  // holding those SECONDARY controls in thumb reach — the existing DOM nodes
  // are MOVED in (listeners intact), so nothing is re-wired. The timeframe bar
  // deliberately stays visible under the canvas: it's the most-used control
  // and never belongs behind an extra tap. Desktop unchanged.
  function initMobileSheet() {
    if (!window.matchMedia || !matchMedia("(max-width: 560px)").matches) return;
    const tools = document.getElementById("draw-tools");
    const share = document.getElementById("cf-share");
    const png = document.getElementById("cf-png");
    const tv = document.getElementById("cf-tv");
    const plan = document.getElementById("cf-plan");   // Fix-10 #4 rides along
    if (!tools) return;
    const fab = document.createElement("button");
    fab.id = "ct-fab"; fab.type = "button";
    fab.setAttribute("aria-haspopup", "dialog");
    fab.setAttribute("aria-expanded", "false");
    fab.title = "Chart tools — draw, share, export";
    fab.textContent = "✏";
    const scrim = document.createElement("div");
    scrim.id = "ct-sheet-scrim"; scrim.hidden = true;
    const sheet = document.createElement("div");
    sheet.id = "ct-sheet"; sheet.hidden = true;
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-label", "Chart tools");
    const secTools = document.createElement("div");
    secTools.className = "cts-sec";
    secTools.innerHTML = `<div class="cts-hd">Draw</div>`;
    secTools.appendChild(tools);            // move — listeners ride along
    // Fix-10 #9: an ANALYZE section — initReplay/initCompare drop their
    // buttons here on phones (instead of crowding the timeframe row).
    const secAn = document.createElement("div");
    secAn.className = "cts-sec";
    secAn.innerHTML = `<div class="cts-hd">Analyze</div>`;
    const anRow = document.createElement("div");
    anRow.className = "cts-actions";
    secAn.appendChild(anRow);
    const secActs = document.createElement("div");
    secActs.className = "cts-sec";
    secActs.innerHTML = `<div class="cts-hd">Share</div>`;
    const actRow = document.createElement("div");
    actRow.className = "cts-actions";
    [plan, share, png, tv].forEach((el) => { if (el) actRow.appendChild(el); });
    secActs.appendChild(actRow);
    sheet.appendChild(secTools); sheet.appendChild(secAn); sheet.appendChild(secActs);
    const setOpen = (open) => {
      sheet.hidden = !open; scrim.hidden = !open;
      fab.setAttribute("aria-expanded", open ? "true" : "false");
    };
    window.__ctSheet = { close: () => setOpen(false), analyzeRow: anRow };
    fab.addEventListener("click", () => setOpen(sheet.hidden));
    scrim.addEventListener("click", () => setOpen(false));
    document.body.append(scrim, sheet, fab);
  }

  function boot() {
    initOffline();
    initMobileSheet();
    wireShare();
    if (posId) { renderPosition(posId); return; }
    if (!symbol) { fail("No ticker specified."); return; }
    wireScanNav();
    wireBotPosBanner();
    // VIVEK has no per-ticker static chart files — render the 200 SMA reaction
    // live (with the full 5.0 level ladder). Three-tier fallback so a ticker
    // link NEVER dead-ends (owner rule 2026-07-02 after a journal name whose
    // setup had ended showed "Chart unavailable"):
    //   1. live VIVEK plan  -> full ladder chart (+ zones overlay if any)
    //   2. PhaseMap setup   -> zones-as-ladder chart
    //   3. neither          -> plain candles + SMAs, always renders
    if (isVivek) {
      Promise.all([fetchResultMeta(), fetchPhaseMapRec()]).then(([meta, rec]) => {
        pmRec = rec;
        const hasPlan = meta && meta.entry != null && meta.stop != null && meta.tp1 != null;
        if (hasPlan) { vivekFallback(baseSymbol, meta); return; }
        pmOnlyFallback(baseSymbol, meta, rec);   // rec may be null -> plain chart
      });
      return;
    }
    fetch(chartFile, { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(render)
      .catch(() => {
        // For mode-specific subdirs, try the base pullback chart first.
        if (modeDir) {
          const baseFile = `data/charts/${market}/${encodeURIComponent(symbol)}.json`;
          fetch(baseFile, { cache: "no-cache" })
            .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(render)
            .catch(fallbackFromLive);
        } else {
          fallbackFromLive();
        }
      });
  }

  // If cloud sync is on, pull the latest journal first so positions taken on
  // another device show here too. Never block rendering on it for long.
  if (window.GBSSync && window.GBSSync.enabled()) {
    Promise.race([window.GBSSync.syncIn(), new Promise((res) => setTimeout(res, 2500))]).finally(boot);
  } else {
    boot();
  }
})();

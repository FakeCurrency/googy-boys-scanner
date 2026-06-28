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
  // The app is VIVEK-only. Every non-scalp chart is a VIVEK chart, FULL STOP —
  // we ignore any stale/explicit mode in the URL (old bookmarks, shared links,
  // or a retired "pullback"/"reversal"/… value) that would otherwise drop us
  // into the generic EMA "live fallback" chart. This also makes fetchResultMeta
  // read the *_vivek.json file (it keys off `mode`). Scalp keeps its own mode.
  const mode = market === "scalp" ? (params.get("mode") || "scalp").toLowerCase() : "vivek";
  const isVivek = mode === "vivek";
  const modeDir = mode === "reversal" ? "_rev" : mode === "spec" ? "_spec" : mode === "short" ? "_short" : "";
  const chartFile = `data/charts/${market}${modeDir}/${encodeURIComponent(symbol)}.json`;

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
      const yf = yfTickerFor(SYM, assetType);
      yahooBars(yf, "2y", "1d")
        .then((bars) => {
          if (bars.length < 6) throw new Error("thin");
          d.timeframes["1D"] = barsToStockTF(bars);
          if (d.price == null) d.price = bars[bars.length - 1].close;
          render(d);
        })
        .catch(() => fail(`No chart data for ${SYM.toUpperCase()} yet, and live history is unavailable right now.`));
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
    const tfLabel = m.level_tf === "weekly" ? "200 SMA · Weekly" : "200 SMA · H4";
    const d = {
      symbol: SYM, name: m.name || SYM, asset_type: assetType,
      price: m.price ?? null,
      grade: m.grade || "", score: m.score || 0, score_max: m.score_max || 0,
      chips: m.chips || [], sector: m.sector || "", currency_symbol: cur,
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

  function fail(msg) {
    const h = document.createElement("header");
    h.className = "chart-top";
    h.innerHTML = `<a class="back-link" href="index.html">← Dashboard</a>`;
    const d = document.createElement("div");
    d.className = "chart-error";
    const tvSym = symbol
      ? encodeURIComponent(market === "crypto" ? `CRYPTO:${symbol}USD` : market === "asx" ? `ASX:${symbol}` : symbol)
      : "";
    d.innerHTML = `<h2>Chart unavailable</h2><p>${esc(msg)}</p>` +
      (symbol ? `<p><a class="tv-link" href="https://www.tradingview.com/chart/?symbol=${tvSym}" target="_blank" rel="noopener">View ${esc(symbol.toUpperCase())} on TradingView →</a></p>` : "");
    document.body.replaceChildren(h, d);
  }

  function header(d) {
    const cur = d.currency_symbol || "";
    $("#ct-sym").textContent = d.symbol;
    document.title = `${d.symbol} — Vivek's Beta Scanner`;
    if (d.sector) { const s = $("#ct-sector"); s.textContent = d.sector; s.hidden = false; }
    $("#ct-price").textContent = fmt(d.price, cur);
    const g = $("#ct-grade"); g.textContent = d.grade; g.style.color = GRADE_VAR[d.grade] || "var(--grade-c)";
    const dirEl = $("#ct-dir");
    if (d.dir) {
      const isShort = d.dir.toUpperCase() === "SHORT";
      dirEl.textContent = d.dir;
      dirEl.classList.toggle("short", isShort);
      dirEl.classList.toggle("long", !isShort);   // explicit colour both ways (LONG green / SHORT red)
    }
    dirEl.hidden = false;
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
  function mjSave(x) {
    if (window.GBSSync) { window.GBSSync.saveLocal(x); window.GBSSync.syncOutDebounced(); return; }
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

  function wireSim(d) {
    const buyBtn  = $("#cf-sim-buy");
    const sellBtn = $("#cf-sim-sell");
    const statusEl = $("#cf-sim-status");
    if (!buyBtn || !sellBtn) return;

    const cur     = d.currency_symbol || "";
    const dir     = (d.dir || "LONG").toLowerCase() === "short" ? "short" : "long";
    const SYM     = (d.symbol || symbol).toUpperCase();
    // Crypto is identified by the row's asset_type — NOT by market==="scalp",
    // because the scalp universe also contains commodities (GOLD, OIL) and ASX
    // stocks (BHP, CBA) which must NOT be sized/priced as 10× crypto.
    const isCrypto = d.asset_type === "crypto" || market === "crypto";
    const simBrok  = (data) => isCrypto ? data.crypto_brokerage : data.stock_brokerage;

    // Re-label the entry button to match the setup direction.
    buyBtn.textContent  = dir === "short" ? "▲ Simulate Short" : "▲ Simulate Buy";
    sellBtn.textContent = dir === "short" ? "▼ Cover / Close"  : "▼ Simulate Sell";

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
      mjSave(data);
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
      // VIVEK: book the SL/TP of the timeframe the user is viewing (the per-TF
      // plan), not the scan's canonical daily plan. Falls back to the scan plan.
      const av     = d._vivek ? (d._activeLevels || null) : null;
      const stopV  = av ? (av.stop ?? null) : (d.stop ?? null);
      const tp1V   = av ? (av.tp1 ?? null) : (d.tp1 ?? null);
      const tp2V   = av ? (av.tp2 ?? null) : (d.tp2 ?? null);
      const tp3V   = av ? (av.tp3 ?? null) : (d.tp3 ?? null);
      const tgtV   = av ? (av.tp2 ?? null) : (d.target ?? null);
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
  function renderTFSetups(d, tfs, pickTF, getCurTF) {
    const order = ["4H", "1D", "3D", "1W"];
    const items = order.filter((k) => tfs[k] && tfs[k].levels).map((k) => {
      const lv = tfs[k].levels;
      return { k, approx: !!tfs[k].approx, armed: !!lv.armed, rr: +lv.rr || 0, trig: lv.entry_trigger };
    });
    if (!items.length) return null;
    // Real-plan timeframes only (a 4H / old-3D reference borrows the Daily plan —
    // don't let it double-count toward confluence).
    const realArmed = items.filter((i) => i.armed && !i.approx);
    let cls, read;
    if (realArmed.length >= 2) {
      cls = "strong";
      read = `⚡ Multi-timeframe setup — armed on ${realArmed.map((i) => TF_LABEL[i.k]).join(" + ")}`;
    } else if (realArmed.length === 1) {
      const a = realArmed[0];
      cls = a.rr >= TFS_MIN_RR ? "armed" : "weak";
      read = `Armed on ${TF_LABEL[a.k]} · ${a.trig || "trigger"} · R:R ${a.rr.toFixed(1)}`;
    } else {
      cls = "watch";
      read = "Watching — no timeframe has triggered yet";
    }
    const chip = (i) => {
      const state = i.armed ? (i.rr >= TFS_MIN_RR ? "armed" : "weak") : "watch";
      const sub = i.armed ? `${(i.trig || "arm").slice(0, 3)} · ${i.rr.toFixed(1)}R` : "watch";
      const title = i.approx ? `${TF_LABEL[i.k]} — reference view (uses the Daily plan)`
                             : `${TF_LABEL[i.k]} 200-SMA plan${i.armed ? " · ARMED" : " · watching"}`;
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
    header(d); footer(d); wireSim(d);
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
    if (d._fallback && !d._vivek) {
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
    let tfSetups = null;              // VIVEK multi-timeframe setup strip (set below)

    const el = $("#chart");
    const LC = window.LightweightCharts;
    const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const chart = LC.createChart(el, {
      width: el.clientWidth, height: el.clientHeight,
      layout: { background: { color: "transparent" }, textColor: dark ? "#aeb9c9" : "#4b4b52",
        fontFamily: '-apple-system, "SF Pro Text", Inter, system-ui, sans-serif' },
      grid: { vertLines: { color: dark ? "rgba(84,84,88,0.28)" : "rgba(60,60,67,0.08)" },
              horzLines: { color: dark ? "rgba(84,84,88,0.28)" : "rgba(60,60,67,0.08)" } },
      rightPriceScale: { borderColor: dark ? "rgba(84,84,88,0.4)" : "rgba(60,60,67,0.14)" },
      timeScale: { borderColor: dark ? "rgba(84,84,88,0.4)" : "rgba(60,60,67,0.14)" },
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

    // One line series per indicator (the set is the same across timeframes).
    const lineSeries = tfs[curTF].lines.map((l) => chart.addLineSeries({
      color: l.color, lineWidth: l.name === "SuperTrend" ? 1.5 : 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    }));

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
        return `<span><span class="cl-name" style="color:${l.color}">${l.name}</span> ${last != null ? fmt(last, d.currency_symbol) : ""}</span>`;
      }).join("");
      // VIVEK: a small key so the reaction dot, the entry-trigger arrow and the
      // volume colours are self-explanatory.
      const key = d._vivek
        ? `<span class="cl-key"><span style="color:#ffb020">● 200 SMA reaction</span>` +
          `<span style="color:#2fd07f">▲ entry trigger</span>` +
          `<span style="color:#00d2ff">▮ vol ≥1.5×</span>` +
          `<span style="color:#2fd07f">▮ rising</span><span style="color:#ff5b5b">▮ falling</span></span>`
        : "";
      $("#chart-legend").innerHTML = smas + key;
    }
    function applyTF(key) {
      const tf = tfs[key]; if (!tf) return;
      curTF = key;
      drawClear();                    // temp drawings are TF-specific — reset on switch
      candle.setData(tf.candles);
      vol.setData(tf.volume);
      tf.lines.forEach((l, i) => lineSeries[i] && lineSeries[i].setData(l.data));

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
    const liveCtx = { chart, candle, vol, lineSeries, momSeries, posDir, entryEpoch };

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

    // ── Temporary drawing tools + measure + eraser ───────────────────────────
    // Not persisted — purely for eyeballing structure while viewing. Points are
    // anchored to chart coordinates (logical index + price) so they track pan/
    // zoom; switching timeframe clears them (the data underneath changed).
    initDrawing();

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
      // control strip, instead of a floating overlay.
      if (tools) {
        tools.hidden = false;
        const tgl = $("#tf-toggle");
        if (tgl && tools.parentNode !== tgl) { tools.classList.add("in-toggle"); tgl.appendChild(tools); }
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
          `<div class="ml-time">${spanText(a.logical, b.logical)}</div>`;
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
          if (i >= 0) { drawings.splice(i, 1); eraseIdx = -1; redraw(); }
          return;
        }
        if (p.logical == null || p.price == null) return;
        if (tool === "hline") {
          drawings.push({ type: "hline", price: p.price });
        } else if (tool === "trend") {
          if (!pending) { pending = { logical: p.logical, price: p.price }; }
          else { drawings.push({ type: "trend", a: pending, b: { logical: p.logical, price: p.price } }); pending = null; }
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
        if (delTarget >= 0) { drawings.splice(delTarget, 1); delTarget = -1; eraseIdx = -1; delBtn.style.display = "none"; redraw(); }
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
        if (clearBtn) clearBtn.addEventListener("click", () => drawClear());
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
      mjSave(data);
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

    const isScalp = market === "scalp";
    const suffix  = mode === "reversal" ? "_reversal" : mode === "spec" ? "_spec"
                  : mode === "short"    ? "_short"    : mode === "vivek" ? "_vivek" : "";
    const file    = isScalp ? "data/scalp.json" : `data/${market}${suffix}.json`;
    const sOf     = isScalp
      ? (r) => `${r.symbol}_${String(r.dir || "").toLowerCase()}`
      : (r) => r.symbol;
    const hrefFor = (s) => isScalp
      ? `chart.html?m=scalp&s=${encodeURIComponent(s)}`
      : `chart.html?m=${market}&s=${encodeURIComponent(s)}${mode !== "pullback" ? `&mode=${mode}` : ""}`;

    fetch(file, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        const list = ((j && j.results) || []).map(sOf);
        const cur  = decodeURIComponent(symbol).toUpperCase();
        const idx  = list.findIndex((s) => String(s).toUpperCase() === cur);
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

  function boot() {
    if (posId) { renderPosition(posId); return; }
    if (!symbol) { fail("No ticker specified."); return; }
    wireScanNav();
    // VIVEK has no per-ticker static chart files — render the 200 SMA reaction
    // live (with the full 5.0 level ladder) instead of the generic scalp chart.
    if (isVivek) { fetchResultMeta().then((meta) => vivekFallback(baseSymbol, meta)); return; }
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

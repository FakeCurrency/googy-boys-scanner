/* =========================================================================
   Chart page — candlestick chart (lightweight-charts) showing the user's own
   system (EMA/SMA + SuperTrend + entry/stop/target levels) on every timeframe.
   Timeframe buttons (D / 3D / W / M / 3M) switch the data client-side.
   ========================================================================= */
(() => {
  "use strict";

  /* DAILY CHART DEPTH (owner, 2026-09-19). Was "5y" on every symbol, which is
   * why every chart on the site started in Sept 2021 regardless of ticker or
   * market, and why the WEEKLY 200-SMA -- the level this whole lens exists to
   * read -- had only ~52 of 251 weekly bars to stand on. A 200-period average
   * needs 200 finished bars before it produces its first value, so at 5 years
   * roughly four fifths of the weekly chart carried no 200 line at all and no
   * prior reaction at that level was visible.
   *
   * "25y" is served by /api/price's stitched date-window path (see
   * functions/api/_prices.js): asking Yahoo for range=max does NOT work, it
   * silently returns coarser candles (measured: 14 of 14 symbols, BHP came back
   * with 156 bars to cover 38.7 years). Five 5-year windows joined by date come
   * back at true 1d granularity -- measured 6345 bars over 25 years, 0 chunks
   * degraded, median spacing exactly 1.0 day.
   *
   * TO REVERSE WITHOUT A DEPLOY: set CHART_MAX_YEARS=5 in the Cloudflare Pages
   * env vars. price.js clamps every request to that cap, so the old behaviour
   * comes back on the next request for everyone. Changing this constant back to
   * "5y" is the permanent version of the same thing.
   *
   * CRYPTO IS DELIBERATELY LEFT AT 5y: its history is shallower anyway and its
   * bars come from a different path (Binance klines cap at 1000), so deepening
   * it would be a separate change with its own measurements. */
  const DAILY_RANGE = "25y";

  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B+": "var(--grade-b)", "B": "var(--grade-b)", "WATCH": "var(--grade-c)", "C": "var(--grade-c)" };
  const TF_LABEL = { "1H": "1H", "4H": "4H", "1D": "D", "3D": "3D", "1W": "W", "1M": "M", "3M": "3M" };
  // Per-timeframe tooltips — used to flag the 4H view's honest limitations.
  const TF_TITLE = {
    "4H": "≈2y max history (yfinance hourly) · trade levels are the Daily plan",
    "3D": "3-day candles (3 sessions per bar) · trade levels are the Daily plan",
  };
  const TF_ORDER = ["1H", "4H", "1D", "3D", "1W", "1M", "3M"];

  // ── per-render teardown (TOP100 #80/#81) ──────────────────────────────────
  // render() is RE-ENTRANT — eight call sites, and every timeframe button is
  // one of them. Everything it wired was wired unconditionally and never
  // removed: a 30s live-box refresh, a 20s stock quote poll, a window resize
  // handler, and two or three onLiveTick subscribers. Each render built a BRAND
  // NEW box element (document.createElement) and appended it, so after a
  // session of clicking D/3D/W/M/3M the page held one orphaned interval, one
  // orphaned resize listener and three orphaned tick subscribers PER CLICK,
  // every one of them still doing full work — a lookup, a large HTML build, an
  // innerHTML write — against a node render() had already detached. Not a
  // slow leak of bytes; a growing pile of live work with no visible output.
  //
  // The `beforeunload → clearInterval` teardowns that were there did nothing
  // about this, and could not: they fire when the page is being DESTROYED, at
  // which point every interval dies anyway. They were cargo cult, and worse
  // than inert — a beforeunload listener is a bfcache hazard, so the "fix" was
  // costing back-navigation performance to solve nothing. They are replaced
  // here, not supplemented.
  //
  // This is `sectors.js`'s clearInterval-before-re-set pattern generalised:
  // whatever the previous render wired, the next render unwires first.
  const _renderTeardown = [];
  const onRenderTeardown = (fn) => { _renderTeardown.push(fn); };
  function tearDownPreviousRender() {
    // LIFO and pop-as-you-go: a teardown that throws must not strand the ones
    // behind it, and must not be run twice by a later render.
    while (_renderTeardown.length) { try { _renderTeardown.pop()(); } catch (_) {} }
  }

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
  const srcParam = (params.get("src") || "").toLowerCase();
  // MOMENTUM (2026-09-22): the fourth lens screens a DIFFERENT stack (20/50/200
  // Pine-seeded EMAs + an RSI divergence) from 5.0's 200-SMA reaction, so a row
  // opened from that page must not be dressed in 5.0's 10/20/43 and its trade
  // ladder. Entered by `src=momentum` (what momentum.js links) OR an explicit
  // `mode=momentum`; a bare `?s=&m=` link is untouched and still reads VIVEK.
  const wantsMomentum = urlMode === "momentum" || srcParam === "momentum";
  const mode = market === "scalp" ? (urlMode || "scalp")
    : urlMode === "spec" ? "spec"
    : wantsMomentum ? "momentum" : "vivek";
  // Back-link context: return to wherever the user actually came from
  // (journal / phasemap / specs / alerts pass src=...) instead of
  // always dumping them on the dashboard. src already drives prev/next
  // lists. (The TURTLE back-link went with the lens, 2026-09-17.)
  {
    const SRC_BACK = {
      journal:  ["journal.html",  "← Journal"],
      phasemap: ["phasemap.html", "← Phase Map"],
      specs:    ["specs.html",    "← Specs"],
      alerts:   ["alerts.html",   "← Alerts"],
      sectors:  ["sectors.html",  "← News"],
      momentum: ["momentum.html", "← Momentum"],
    };
    const back = SRC_BACK[srcParam];
    const el = document.querySelector(".back-link");
    if (back && el) { el.href = back[0]; el.textContent = back[1]; }
  }
  const isVivek = mode === "vivek";
  const isMomentum = mode === "momentum";
  // Stated in one place because it is a CLAIM ABOUT THE EVIDENCE, not a label:
  // the spec calls the divergence screen an attention filter, not an entry
  // system, so the chart must never read as a plan. See momentumFallback.
  // The plan drawn on a Momentum chart comes from the Pine template, NOT from
  // vivek.py. Saying so is the whole job of this line: five lines labelled
  // ENTRY/SL/TP look exactly like a 5.0 ladder and are a different system.
  const MOM_CAPTION = "Auto plan from the Pine template \u2014 not a 5.0 plan.";
  // ~3 years of sessions. The Daily pull is 25y and the stitcher really
  // serves it, so fitContent() on a long-listed name squeezes 6,000+ bars
  // into the canvas and the recent structure the lens actually screens is
  // unreadable. First paint therefore WINDOWS to the last ~750 bars; the
  // full series is still loaded and panning reaches all of it. Momentum
  // only -- 5.0 first paint stays fitContent.
  const MOM_FIRST_PAINT_BARS = 750;
  // `data/charts/<market>[<mode>]/<SYM>.json` — the per-ticker pre-rendered
  // chart files — were REMOVED 2026-08-15. The directory has never existed in
  // this repo (git ls-files: zero entries), so every fetch of it was a
  // guaranteed 404 paid BEFORE the live fallback: a serial round-trip added to
  // every scalp/spec chart open, plus one per hovered deck row (the prefetch,
  // also removed). The fallbacks the 404 eventually reached are now called
  // directly. If per-ticker chart JSON ever gets a producer, reintroduce the
  // path THERE first.

  // scalp/crypto charts label themselves CRYPTO. (This used to pick the lens
  // whose ★ watchlist the header star wrote to; the stars went with the manual
  // journal on 2026-09-21 and only the market label survives.)
  const chartMarket = market === "scalp" ? "crypto" : market;
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
    // MOMENTUM: the zones are a DIFFERENT lens's read on the same tape, and on
    // a chart that now carries its own box, ladder and two panes they are
    // clutter rather than context. Opt in with ?pm=1, which is the flag the
    // zones used to require anyway.
    if (isMomentum && params.get("pm") !== "1") return Promise.resolve(null);
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

  // ── Trading costs — ONE model, the published one (TOP100 #28) ──────────────
  //
  // This page used to charge a FLAT round-trip brokerage: `2 * (isCrypto ? 5 :
  // 10)` dollars, out of `stock_brokerage`/`crypto_brokerage` on the manual
  // journal blob. Those two fields had no editor anywhere in the app — they were
  // schema defaults written by the (since-removed) sync layer, never touched — so they were
  // not a setting, they were a second hardcoded cost model sitting next to the
  // real one. journal.js prices the SAME rows in basis points per market,
  // adopted from `bot_rules.json`, which is itself published from
  // `scanner/config.py` every scan and mirrors `vivek_journal._cost_r`.
  //
  // A flat fee is not merely a different number, it is a different SHAPE: it
  // does not scale with position size, so it was roughly 3x too heavy on a
  // $1,000 sim stock position and far too light on anything real. Every dollar
  // figure this page showed therefore disagreed with the journal's figure for
  // the identical trade, and there was no way to tell which one to believe.
  //
  // What remains different, deliberately, is the SIZE each page prices: this
  // page costs the `shares` it actually booked, while the journal re-prices
  // every manual row at the bot's fixed notional so the Me-vs-Claude comparison
  // is like-for-like (see journal.js `sizeOf` and CLAUDE.md "Position sizing is
  // FIXED NOTIONAL"). That is a sizing convention, not a second cost model.
  const COMMISSION_BPS = { asx: 2, nasdaq: 1, crypto: 6, default: 2 };  // fallback
  const SLIPPAGE_BPS   = { asx: 5, nasdaq: 4, crypto: 8, default: 5 };  // fallback
  const costsFor = (mkt) => [
    (SLIPPAGE_BPS[mkt]   ?? SLIPPAGE_BPS.default)   / 1e4,
    (COMMISSION_BPS[mkt] ?? COMMISSION_BPS.default) / 1e4,
  ];
  // Cost of ONE leg, in dollars, on `units` at `price`. `slipped` is false only
  // for a resting take-profit limit, which is filled by the exchange at the
  // price you named — the same carve-out journal.js `costR` makes.
  const legCost = (mkt, units, price, slipped) => {
    const [slip, comm] = costsFor(mkt);
    return Math.abs(units || 0) * (price || 0) * (comm + (slipped ? slip : 0));
  };
  // The published constants win over the fallbacks above, exactly as in
  // journal.js `loadBotRules`. Silent on failure: an offline page keeps the
  // fallbacks rather than showing nothing.
  (async () => {
    try {
      const r = await fetch("data/bot_rules.json", { cache: "no-cache" });
      if (!r.ok) return;
      const j = await r.json();
      for (const [key, tgt] of [["commission_bps", COMMISSION_BPS], ["slippage_bps", SLIPPAGE_BPS]]) {
        const src = j[key];
        if (!src || typeof src !== "object") continue;
        for (const m of Object.keys(tgt)) {
          if (typeof src[m] === "number" && src[m] >= 0) tgt[m] = src[m];
        }
      }
    } catch (_) { /* offline — fallbacks stand */ }
  })();
  // Shared with the simulate buttons / live box so a buy/sell fills at the true
  // live price and every dependent widget reacts on each tick.
  const liveState = { price: null, listeners: [] };
  // Every subscriber is registered from inside render() (initAlerts, the stock
  // quote poll), so each one is scoped to the render that added it — otherwise
  // a price tick fans out to N copies of the same handler writing into N-1
  // detached boxes. Unsubscribing here rather than at the three call sites is
  // deliberate: a fourth caller added later inherits the teardown for free.
  const onLiveTick = (fn) => {
    liveState.listeners.push(fn);
    onRenderTeardown(() => {
      const i = liveState.listeners.indexOf(fn);
      if (i >= 0) liveState.listeners.splice(i, 1);
    });
  };


  // Held-plan passthrough (2026-08-20): he/hs/hd(+ht1/ht2/ht3) carry a real
  // journal position's own entry/stop/direction/targets, set by journal.js's
  // symCell/jr-new-row links. When present they override whatever the live
  // scan or PhaseMap would otherwise guess for this ticker — see
  // heldPlanFallback() below. Entry+stop are the minimum bar for "usable".
  const heldPlan = (() => {
    const n = (v) => { const x = parseFloat(v); return isFinite(x) ? x : null; };
    const he = n(params.get("he")), hs = n(params.get("hs"));
    if (he == null || hs == null) return null;
    return {
      entry: he, stop: hs,
      tp1: n(params.get("ht1")), tp2: n(params.get("ht2")), tp3: n(params.get("ht3")),
      dir: (params.get("hd") || "long").toLowerCase() === "short" ? "SHORT" : "LONG",
    };
  })();

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
  // DATA HONESTY metadata from the DAILY pull (basis / flat padding / interval
  // degradation) — captured only when the caller asks (capture=true on the
  // series that drives the chart), rendered by renderDataHonesty() below.
  let DATA_META = null;
  function yahooBars(yfTicker, range, interval, capture) {
    return fetch(`/api/price?symbol=${encodeURIComponent(yfTicker)}&range=${range}&interval=${interval}`,
      { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => {
        if (capture && j && j.ok) {
          DATA_META = { bars: j.bars || 0, flat: j.flat || 0,
                        basis: j.basis || null, degraded: !!j.degraded };
        }
        return (j && j.ok && Array.isArray(j.candles)) ? j.candles : [];
      });
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

  // Daily → weekly OHLCV, bucketed Saturday→Friday and stamped with the LAST
  // bar's own time — the same weeks the ENGINE grades (vivek.py resamples
  // W-FRI, i.e. weeks that END Friday). For Mon–Fri equities the membership is
  // identical to the old Monday bucketing; for 7-day crypto the old Mon–Sun
  // weeks genuinely disagreed with the engine's Sat–Fri ones, so the weekly
  // candles (and the SMAs on them) were built from different weeks than the
  // scan graded. Stamping the last bar also puts a completed week's candle on
  // its Friday, matching the engine's W-FRI labels (2026-08-15).
  function resampleWeekly(bars) {
    const out = []; let cur = null, curKey = null;
    for (const b of bars) {
      const dow = new Date(b.time * 1000).getUTCDay();      // 0=Sun … 6=Sat
      const sat = b.time - ((dow + 1) % 7) * 86400;         // the Saturday opening this Sat→Fri week
      if (sat !== curKey) {
        if (cur) out.push(cur);
        cur = { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume || 0 };
        curKey = sat;
      } else {
        cur.time = b.time;                                  // stamp = last bar in the week (Friday when complete)
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

  // ── MOMENTUM display stack (2026-09-22) ────────────────────────────────────
  // The Momentum lens does NOT use 5.0's 10/20/43/200 SMAs. It screens a
  // 20/50 cross (Rule B) under a 200 trend filter, and the 200 is the one the
  // score reads — so drawing 5.0's stack on a Momentum row would show a reader
  // averages no rule in that lens has ever consulted.
  //
  // THE SEEDING IS THE WHOLE POINT, and it is why this is not `emaArr` above.
  // `emaArr` is pandas' ewm(adjust=false): it seeds on the FIRST value and
  // emits from bar 0. Pine — and therefore scanner/momentum/ema.py — seeds with
  // the SMA of the first `length` values and is `na` before that. The seed
  // error decays as (1-alpha)^n, so it matters in inverse proportion to alpha:
  // negligible on the 20, measurable on the 200, which is exactly the line the
  // trend filter tests `close > slow` against. A chart drawn with the wrong
  // seed can therefore show price on the opposite side of the 200 from the
  // side the scanner scored. This is a direct port of `_recursive_ma(..., seed
  // = "sma")`; keep the two in step.
  function emaPine(vals, period) {
    const n = vals.length;
    const out = new Array(n).fill(NaN);
    const len = Math.floor(period);
    if (!(len >= 1) || !n) return out;
    let f = -1;
    for (let i = 0; i < n; i++) if (isFinite(vals[i])) { f = i; break; }
    if (f < 0 || n - f < len) return out;            // Pine returns na, not a guess
    const alpha = 2 / (len + 1);
    // A NaN inside the seed window: walk forward to the first clean one, exactly
    // as the Python does, rather than seeding off a mean that carries a hole.
    let start = -1, seed = NaN;
    for (let st = f; st <= n - len; st++) {
      let sum = 0, bad = false;
      for (let k = st; k < st + len; k++) { if (!isFinite(vals[k])) { bad = true; break; } sum += vals[k]; }
      if (!bad) { start = st + len - 1; seed = sum / len; break; }
    }
    if (start < 0) return out;
    let prev = seed;
    out[start] = prev;
    for (let i = start + 1; i < n; i++) {
      const x = vals[i];
      if (!isFinite(x)) { prev = NaN; out[i] = NaN; continue; }
      if (!isFinite(prev)) { prev = x; out[i] = x; continue; }
      prev = alpha * x + (1 - alpha) * prev;
      out[i] = prev;
    }
    return out;
  }

  // The lengths and the average TYPE are read from the payload's own `params`,
  // never hardcoded here: the scanner publishes the config it actually ran
  // (ma_type/fast_len/mid_len/slow_len), so retuning the screen moves the chart
  // with it instead of leaving a second copy to drift. Falls back to the
  // shipped defaults when an old payload has no params block.
  const MOM_MA_DEFAULTS = { ma_type: "EMA", fast_len: 20, mid_len: 50, slow_len: 200 };
  function momentumMAs(cl, mp) {
    const P = Object.assign({}, MOM_MA_DEFAULTS, mp || {});
    const sma = (span) => {
      const o = new Array(cl.length).fill(NaN);
      let sum = 0;
      for (let i = 0; i < cl.length; i++) {
        sum += cl[i];
        if (i >= span) sum -= cl[i - span];
        if (i >= span - 1) o[i] = sum / span;
      }
      return o;
    };
    const ma = (span) => (String(P.ma_type).toUpperCase() === "SMA" ? sma(span) : emaPine(cl, span));
    const t = String(P.ma_type).toUpperCase() === "SMA" ? "SMA" : "EMA";
    return [
      { span: +P.fast_len, name: `${t} ${P.fast_len}`, color: "#ffd23f", vals: ma(+P.fast_len) },
      { span: +P.mid_len,  name: `${t} ${P.mid_len}`,  color: "#4d9fff", vals: ma(+P.mid_len) },
      // amber, the same weight 5.0 gives its 200 — this IS the trend filter.
      { span: +P.slow_len, name: `${t} ${P.slow_len}`, color: "#ffb020", vals: ma(+P.slow_len) },
    ];
  }

  // Wilder's RMA (ta.rma): alpha = 1/length, seeded with the SMA of the first
  // `length` values -- the same seeding discipline as emaPine, and what
  // scanner/momentum/ema.py::wilder_rma does. RSI and ATR both ride on it.
  function rmaPine(vals, period) {
    const n = vals.length, out = new Array(n).fill(NaN), len = Math.floor(period);
    if (!(len >= 1) || !n) return out;
    let f = -1;
    for (let i = 0; i < n; i++) if (isFinite(vals[i])) { f = i; break; }
    if (f < 0 || n - f < len) return out;
    const alpha = 1 / len;
    let start = -1, seed = NaN;
    for (let st = f; st <= n - len; st++) {
      let sum = 0, bad = false;
      for (let k = st; k < st + len; k++) { if (!isFinite(vals[k])) { bad = true; break; } sum += vals[k]; }
      if (!bad) { start = st + len - 1; seed = sum / len; break; }
    }
    if (start < 0) return out;
    let prev = seed; out[start] = prev;
    for (let i = start + 1; i < n; i++) {
      const x = vals[i];
      if (!isFinite(x)) { prev = NaN; out[i] = NaN; continue; }
      if (!isFinite(prev)) { prev = x; out[i] = x; continue; }
      prev = alpha * x + (1 - alpha) * prev;
      out[i] = prev;
    }
    return out;
  }

  function rsiPine(cl, period) {
    const n = cl.length, up = new Array(n).fill(NaN), dn = new Array(n).fill(NaN);
    for (let i = 1; i < n; i++) {
      const ch = cl[i] - cl[i - 1];
      up[i] = Math.max(ch, 0); dn[i] = Math.max(-ch, 0);
    }
    const ru = rmaPine(up, period), rd = rmaPine(dn, period), out = new Array(n).fill(NaN);
    for (let i = 0; i < n; i++) {
      if (!isFinite(ru[i]) || !isFinite(rd[i])) continue;
      out[i] = rd[i] === 0 ? (ru[i] > 0 ? 100 : 50) : 100 - 100 / (1 + ru[i] / rd[i]);
    }
    return out;
  }

  function macdPine(cl, f, sl, sg) {
    const ef = emaPine(cl, f), es = emaPine(cl, sl);
    const line = cl.map((_, i) => (isFinite(ef[i]) && isFinite(es[i]) ? ef[i] - es[i] : NaN));
    const sig = emaPine(line, sg);
    return { line, signal: sig, hist: line.map((v, i) => (isFinite(v) && isFinite(sig[i]) ? v - sig[i] : NaN)) };
  }

  function atrPine(bars, period) {
    const tr = bars.map((b, i) => (i === 0 ? b.high - b.low : Math.max(
      b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close))));
    return rmaPine(tr, period);
  }

  // ── THE AUTO TRADE BOX, from tradingview/Final_Top_Script.pine ─────────────
  // Recovered 2026-09-22 and ported line-for-line. It is NOT vivek.py's plan and
  // shares no code with it: it anchors to the last SCORED CROSS (the 20/50 cross
  // that is Rule B) within `autoMaxAge` bars, stops at the 5-bar swing plus an
  // ATR pad, caps that distance at `maxStopPct` of entry, and lays TP1/2/3 at
  // 1R/2R/3R -- `math.max(..., entRaw * 0.05)` and all.
  //
  // Verified against the owner's TradingView ELS 1D screenshot on the committed
  // daily series: Entry 5.88 / SL 6.76 / TP1 5.00 / TP2 4.12 / TP3 3.23, worst
  // absolute error $0.0040, which is TradingView printing 6.76 for 6.7620.
  const TV_PLAN = {
    swingLen: 5, atrPad: 0.25, atrMult: 1.5, slMode: "Swing",
    maxStopPct: 15, r: [1, 2, 3], autoMaxAge: 60, minScore: 1,
    macd: [12, 26, 9], rsiLen: 14, atrLen: 14,
    useMacd: true, useSlow: true, useRsi: false,
  };
  function momentumPlan(bars, mp) {
    const P = Object.assign({}, MOM_MA_DEFAULTS, mp || {});
    const n = bars.length;
    if (n < 2) return null;
    const cl = bars.map((b) => b.close);
    const fast = emaPine(cl, +P.fast_len), mid = emaPine(cl, +P.mid_len), slow = emaPine(cl, +P.slow_len);
    const { hist } = macdPine(cl, TV_PLAN.macd[0], TV_PLAN.macd[1], TV_PLAN.macd[2]);
    const rsi = rsiPine(cl, TV_PLAN.rsiLen);
    const atr = atrPine(bars, TV_PLAN.atrLen);
    const L = TV_PLAN.swingLen;
    let sigBar = -1, sigDir = 0, sigScore = 0, sigEntry = NaN, sigStop = NaN;
    for (let i = 1; i < n; i++) {
      if (!(isFinite(fast[i]) && isFinite(mid[i]) && isFinite(fast[i - 1]) && isFinite(mid[i - 1]))) continue;
      const bullX = fast[i - 1] <= mid[i - 1] && fast[i] > mid[i];
      const bearX = fast[i - 1] >= mid[i - 1] && fast[i] < mid[i];
      if (!bullX && !bearX) continue;
      const above = isFinite(slow[i]) && cl[i] > slow[i], below = isFinite(slow[i]) && cl[i] < slow[i];
      const bullScore = 1 + (TV_PLAN.useMacd && hist[i] > 0 ? 1 : 0) + (TV_PLAN.useSlow && above ? 1 : 0)
                          + (TV_PLAN.useRsi && rsi[i] > 50 ? 1 : 0);
      const bearScore = 1 + (TV_PLAN.useMacd && hist[i] < 0 ? 1 : 0) + (TV_PLAN.useSlow && below ? 1 : 0)
                          + (TV_PLAN.useRsi && rsi[i] < 50 ? 1 : 0);
      let dir = 0, score = 0;
      if (bullX && bullScore >= TV_PLAN.minScore) { dir = 1; score = bullScore; }
      else if (bearX && bearScore >= TV_PLAN.minScore) { dir = -1; score = bearScore; }
      else continue;
      // 5-bar swing at the signal bar, ATR-padded — ta.lowest/highest(len).
      let lo = Infinity, hi = -Infinity;
      for (let k = Math.max(0, i - L + 1); k <= i; k++) { lo = Math.min(lo, bars[k].low); hi = Math.max(hi, bars[k].high); }
      const a = isFinite(atr[i]) ? atr[i] : 0;
      sigBar = i; sigDir = dir; sigScore = score; sigEntry = cl[i];
      sigStop = TV_PLAN.slMode === "ATR"
        ? (dir === 1 ? cl[i] - a * TV_PLAN.atrMult : cl[i] + a * TV_PLAN.atrMult)
        : (dir === 1 ? lo - a * TV_PLAN.atrPad : hi + a * TV_PLAN.atrPad);
    }
    if (sigBar < 0 || !isFinite(sigEntry)) return null;
    const age = (n - 1) - sigBar;
    if (age > TV_PLAN.autoMaxAge) return null;          // stale signal draws nothing
    const capD = sigEntry * TV_PLAN.maxStopPct / 100;
    const stop = TV_PLAN.maxStopPct <= 0 ? sigStop
      : sigDir === 1 ? Math.max(sigStop, sigEntry - capD) : Math.min(sigStop, sigEntry + capD);
    const risk = Math.abs(sigEntry - stop);
    const tp = TV_PLAN.r.map((r) => Math.max(sigEntry + sigDir * risk * r, sigEntry * 0.05));
    return {
      dir: sigDir, score: sigScore, age, capped: Math.abs(stop - sigStop) > 1e-12,
      bar: bars[sigBar], entry: sigEntry, stop, risk,
      tp1: tp[0], tp2: tp[1], tp3: tp[2], rawStop: sigStop,
    };
  }

  // Strict both-sides pivots ON THE RSI SERIES, returning CONFIRMATION indices
  // (a pivot at i-right is only knowable at i). Strict on both sides means a
  // tie is not a pivot -- scanner/momentum/config.py's pivot_strict_* default.
  function pivotIdx(vals, left, right, low) {
    const out = [], n = vals.length;
    for (let i = left; i + right < n; i++) {
      const v = vals[i];
      if (!isFinite(v)) continue;
      let ok = true;
      for (let k = i - left; k <= i + right && ok; k++) {
        if (k === i || !isFinite(vals[k])) { if (!isFinite(vals[k])) ok = false; continue; }
        ok = low ? v < vals[k] : v > vals[k];
      }
      if (ok) out.push({ pivot: i, confirm: i + right });
    }
    return out;
  }

  // Regular bull/bear divergence, Final_RSI_Plus.pine's rule exactly.
  //
  // THE GAP IS 6..61, NOT 5..60, and it is inherited from TradingView's own
  // Divergence Indicator: f_inRange is called with plFound[1], so
  // ta.barssince() reads (i - previous_confirm - 1). scanner/momentum/screen.py
  // carries the same note; the two must not drift.
  function momentumDivs(bars, rsi, mp) {
    const P = mp || {};
    const L = +(P.piv_left ?? 5), R = +(P.piv_right ?? 5);
    const LO = +(P.range_lower ?? 5), UP = +(P.range_upper ?? 60);
    const lows = pivotIdx(rsi, L, R, true), highs = pivotIdx(rsi, L, R, false);
    const out = [];
    const scan = (piv, bull) => {
      for (let k = 1; k < piv.length; k++) {
        const cur = piv[k], prev = piv[k - 1];
        const gap = cur.confirm - prev.confirm - 1;          // ta.barssince(cond[1])
        if (!(gap >= LO && gap <= UP)) continue;
        const rNow = rsi[cur.pivot], rPrev = rsi[prev.pivot];
        if (!isFinite(rNow) || !isFinite(rPrev)) continue;
        const pNow = bull ? bars[cur.pivot].low : bars[cur.pivot].high;
        const pPrev = bull ? bars[prev.pivot].low : bars[prev.pivot].high;
        const hit = bull ? (pNow < pPrev && rNow > rPrev) : (pNow > pPrev && rNow < rPrev);
        if (hit) out.push({ bull, pivot: cur.pivot, confirm: cur.confirm, rsi: rNow });
      }
    };
    scan(lows, true); scan(highs, false);
    out.sort((a, b) => a.pivot - b.pivot);
    return out;
  }

  // Every scored cross in the series, for the on-price labels the template
  // draws ("+3 Bullish" / "-2 Bearish"). Same scoring as momentumPlan -- both
  // read TV_PLAN, so a retune moves the labels and the box together.
  function momentumCrosses(bars, mp) {
    const P = Object.assign({}, MOM_MA_DEFAULTS, mp || {});
    const cl = bars.map((b) => b.close);
    const fast = emaPine(cl, +P.fast_len), mid = emaPine(cl, +P.mid_len), slow = emaPine(cl, +P.slow_len);
    const { hist } = macdPine(cl, TV_PLAN.macd[0], TV_PLAN.macd[1], TV_PLAN.macd[2]);
    const rsi = rsiPine(cl, TV_PLAN.rsiLen);
    const out = [];
    for (let i = 1; i < bars.length; i++) {
      if (!(isFinite(fast[i]) && isFinite(mid[i]) && isFinite(fast[i - 1]) && isFinite(mid[i - 1]))) continue;
      const bullX = fast[i - 1] <= mid[i - 1] && fast[i] > mid[i];
      const bearX = fast[i - 1] >= mid[i - 1] && fast[i] < mid[i];
      if (!bullX && !bearX) continue;
      const above = isFinite(slow[i]) && cl[i] > slow[i], below = isFinite(slow[i]) && cl[i] < slow[i];
      const bs = 1 + (TV_PLAN.useMacd && hist[i] > 0 ? 1 : 0) + (TV_PLAN.useSlow && above ? 1 : 0)
                   + (TV_PLAN.useRsi && rsi[i] > 50 ? 1 : 0);
      const rs = 1 + (TV_PLAN.useMacd && hist[i] < 0 ? 1 : 0) + (TV_PLAN.useSlow && below ? 1 : 0)
                   + (TV_PLAN.useRsi && rsi[i] < 50 ? 1 : 0);
      if (bullX && bs >= TV_PLAN.minScore) out.push({ i, bull: true, score: bs });
      else if (bearX && rs >= TV_PLAN.minScore) out.push({ i, bull: false, score: rs });
    }
    return out;
  }

  // MACD + RSI pane series for a timeframe, Pine-seeded throughout.
  function momentumPanes(bars) {
    const cl = bars.map((b) => b.close);
    const m = macdPine(cl, TV_PLAN.macd[0], TV_PLAN.macd[1], TV_PLAN.macd[2]);
    const rsi = rsiPine(cl, TV_PLAN.rsiLen);
    const at = (arr) => bars.map((b, i) => (isFinite(arr[i]) ? { time: b.time, value: arr[i] } : null)).filter(Boolean);
    return {
      macd: at(m.line), macdSignal: at(m.signal),
      macdHist: bars.map((b, i) => (isFinite(m.hist[i])
        ? { time: b.time, value: m.hist[i],
            color: m.hist[i] >= 0 ? "rgba(47,208,127,0.7)" : "rgba(255,91,91,0.7)" } : null)).filter(Boolean),
      rsi: at(rsi),
    };
  }

  // Candles + volume + the Momentum stack. Same volume colouring as the VIVEK
  // block so the two charts read identically where they mean the same thing.
  function barsToMomentumTF(bars, mp) {
    const base = barsToVivekTF(bars);
    const cl = bars.map((b) => b.close);
    base.lines = momentumMAs(cl, mp)
      .filter((L) => isFinite(L.span) && L.span >= 1 && bars.length >= L.span)
      .map((L) => {
        const data = [];
        for (let i = 0; i < bars.length; i++) {
          if (isFinite(L.vals[i])) data.push({ time: bars[i].time, value: L.vals[i] });
        }
        return { name: L.name, color: L.color, data };
      });
    return base;
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
    const dailyP = isCrypto ? vivekCryptoBars(SYM, "5y", "1d", true)
                            : yahooBars(yfTickerFor(SYM, assetType), DAILY_RANGE, "1d", true);
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
          // 4H now works exactly like 3D: if the scan emitted a real 4H plan
          // (built from 4H bars, 2026-09-19) the toggle gets its OWN levels and
          // markers; on older payloads with no 4H plan it still falls back to
          // the Daily plan as a labelled reference (approx=true), which is what
          // every 4H view did before. Same bucketing as the engine's resampler
          // (epoch-anchored 4h), so the candles and the plan agree.
          const p4 = plans["4H"];
          if (h4.length >= 6) d.timeframes["4H"] = makeTF(h4, "4H", p4 || dailyPlan, !p4);
        }
        console.info(`[vivek] ${SYM} chart TFs: [${Object.keys(d.timeframes).join(", ")}] ` +
                     `(daily=${daily.length}, intraday=${(intraday || []).length}); ` +
                     `plans=[${Object.keys(plans).join(", ")}]`);
        renderDataHonesty();
        render(d);
      });
    }).catch(() => fail(`No chart data for ${SYM.toUpperCase()} yet, and live history is unavailable right now.`));
  }

  // VIVEK crypto history, forced to the scan-consistent Yahoo <base>-USD series
  // via the proxy (src=yahoo) — never a guessed Binance pair.
  function vivekCryptoBars(sym, range, interval, capture) {
    const usd = String(sym || "").toUpperCase().replace(/-USD$/, "") + "-USD";
    return fetch(`/api/price?symbol=${encodeURIComponent(usd)}&type=crypto&range=${range}&interval=${interval}&src=yahoo`,
      { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => {
        if (capture && j && j.ok) {
          DATA_META = { bars: j.bars || 0, flat: j.flat || 0,
                        basis: j.basis || null, degraded: !!j.degraded };
        }
        return (j && j.ok && Array.isArray(j.candles)) ? j.candles : [];
      });
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
      ? vivekCryptoBars(SYM, "5y", "1d", true)
      : yahooBars(yfTickerFor(SYM, assetType), DAILY_RANGE, "1d", true));
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
          renderDataHonesty();
          render(d);
        });
      })
      .catch(() => fail(`No chart data for ${String(SYM).toUpperCase()} yet, and live history is unavailable right now.`));
  }

  // ── MOMENTUM chart (2026-09-22) ────────────────────────────────────────────
  // Candles + the lens's own 20/50/200 + the Rule A divergence marked where it
  // was SEEN and where it became KNOWABLE. PhaseMap zones still ride along when
  // the ticker has a record (render() draws them from pmRec regardless of mode).
  //
  // IT DRAWS NO TRADE LEVELS, AND THAT IS A FINDING RATHER THAN AN OMISSION.
  // The spec is explicit: "The scored cross and the divergence screen are
  // *attention filters*, not entry systems" (VIVEK_5.0_SCANNER_SPEC.md 1.2).
  // The two position boxes it does define anchor somewhere else -- the trend box
  // to the most recent scored CROSS, the reversal box to an RSI EXTREME, and the
  // latter is flagged in the spec itself as "Not part of the screen" and a
  // "RECONSTRUCTION ... Not his rule". Neither is a stop/target for a
  // divergence, and the published row carries no entry/stop/target field to
  // draw one from. So the caption says what the chart is instead of inventing a
  // 5.0-style TP1-3 ladder over a shortlist.
  function momentumRow(SYM) {
    const want = String(SYM || "").toUpperCase();
    return fetch(`data/momentum/${market}.json`, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j) return null;
        const row = ((j.results) || []).find(
          (r) => String(r.symbol || "").toUpperCase() === want);
        // The params travel even when the symbol is not a hit, so the MA stack
        // is still the one the scanner ran rather than the hardcoded fallback.
        return { row: row || null, params: j.params || null, generated_at: j.generated_at || null };
      })
      .catch(() => null);
  }

  // Rule A on the DAILY pane. Two marks, deliberately unequal in weight:
  //   * the PIVOT bar -- where the divergence is drawn, the older of the two.
  //   * the CONFIRMATION bar -- where it could first be KNOWN, piv_right bars
  //     later. Quieter, because it is the bookkeeping half.
  // The gap between them is the lens's whole honesty claim (a divergence is
  // only knowable after its right-hand pivot closes), so drawing one without
  // the other would misstate when a reader could have acted.
  function momentumMarkers(row, bars) {
    if (!row || !row.rule_a || !bars || !bars.length) return [];
    const bull = String(row.rule_a_direction || row.direction || "bull") === "bull";
    const last = bars.length - 1;
    const byAgo = (n) => (Number.isFinite(+n) && +n >= 0 && last - +n >= 0 ? bars[last - +n] : null);
    // Prefer the explicit pivot DATE -- it survives a chart whose last bar is
    // not the scan's last bar (a live feed one session ahead of the committed
    // scan), where counting back N bars silently lands on the wrong candle.
    const pivotDate = String(row.rule_a_pivot_bar || "").slice(0, 10);
    const pivotBar = (pivotDate && barAtDate(bars, pivotDate)) ||
                     byAgo(row.rule_a_pivot_bars_ago);
    const confBar = byAgo(row.rule_a_bars_ago);
    const out = [];
    if (pivotBar) out.push({
      time: pivotBar.time, position: bull ? "belowBar" : "aboveBar",
      color: bull ? "#2fd07f" : "#ff5b5b",
      shape: bull ? "arrowUp" : "arrowDown",
      text: bull ? "BULL DIV" : "BEAR DIV",
    });
    // Skip the confirmation mark when it lands on the pivot itself (piv_right
    // = 0 would do it): two markers on one bar read as two events.
    if (confBar && (!pivotBar || confBar.time !== pivotBar.time)) out.push({
      time: confBar.time, position: bull ? "belowBar" : "aboveBar",
      color: "#8aa0c8", shape: "circle", text: "confirmed",
    });
    out.sort((a, b) => a.time - b.time);
    return out;
  }

  function momentumFallback(SYM, mom, rec) {
    const row = (mom && mom.row) || null;
    const mp = (mom && mom.params) || null;
    const assetType = market === "crypto" ? "crypto" : null;
    const bull = String((row && (row.rule_a_direction || row.direction)) || "bull") === "bull";
    const rulesTag = row && row.rules ? `Rule ${row.rules}` : "";
    const chips = [];
    if (row) {
      if (rulesTag) chips.push(rulesTag);
      if (row.rule_a) chips.push(bull ? "bull divergence" : "bear divergence");
      if (row.rule_b && row.rule_b_score != null) chips.push(`cross ${row.rule_b_score}/3`);
      if (row.trend) chips.push(`trend ${row.trend}`);
      if (row.is_product) chips.push("PRODUCT");
      if (row.history_warning) chips.push(row.history_warning);
    }
    const d = {
      symbol: String(SYM).toUpperCase(),
      name: (row && row.name) || SYM,
      asset_type: assetType,
      price: row && row.close != null ? row.close : null,
      grade: "", score: 0, score_max: 0,
      chips,
      sector: (row && row.sector) || "",
      currency_symbol: market === "asx" ? "A$" : "$",
      tv_symbol: SYM,
      dir: row && row.rule_a ? (bull ? "LONG" : "SHORT") : "",
      analysis: row
        ? `${MOM_CAPTION} ${bull ? "Bullish" : "Bearish"} RSI divergence` +
          (row.rule_a_pivot_bars_ago != null
            ? ` labelled ${row.rule_a_pivot_bars_ago} bars back, knowable ${row.rule_a_bars_ago} bars ago.`
            : ".") +
          ` The 20/50/200 drawn here are the averages the screen itself reads.`
        : `${MOM_CAPTION} ${String(SYM).toUpperCase()} is not on the latest ` +
          `${MARKET_LABEL[market] || market} momentum scan — showing the raw chart with the lens's own moving averages.`,
      default_tf: "1D", level_lines: [], timeframes: {},
      _fallback: true, _vivek: false, _momentum: true, _momRow: row, _momParams: mp,
    };
    const liveDaily = () => (isCryptoMarket(assetType)
      ? vivekCryptoBars(SYM, "5y", "1d", true)
      : yahooBars(yfTickerFor(SYM, assetType), DAILY_RANGE, "1d", true));
    liveDaily()
      .then((daily) => {
        if (!daily || daily.length < 6) throw new Error("thin");
        // The Momentum stack on every timeframe the page offers, but the Rule A
        // marks ONLY on 1D: the scan is a DAILY screen (`timeframe: "1d"`), so a
        // pivot index means nothing on a weekly or 3-day candle and snapping it
        // to one would invent a weekly divergence the lens never found.
        // EVERY timeframe recomputes the whole template on ITS OWN bars --
        // plan, panes, cross labels, divergences, ATH. Gluing the Daily box
        // onto a 3D chart would show a plan whose entry, stop and R are
        // measured in a different bar size from the candles under it, which is
        // exactly what the owner's 4H screenshot disproves: that pane carries
        // its own Entry 6.46 / SL 7.39, not the Daily's 5.88 / 6.76.
        const build = (bars) => {
          const tf = barsToMomentumTF(bars, mp);
          tf.panes = momentumPanes(bars);
          tf.plan = momentumPlan(bars, mp);
          tf.crosses = momentumCrosses(bars, mp);
          tf.divs = momentumDivs(bars, rsiPine(bars.map((b) => b.close), TV_PLAN.rsiLen), mp);
          tf.ath = bars.reduce((m, b) => (b.high > m ? b.high : m), -Infinity);
          return tf;
        };
        d.timeframes["1D"] = build(daily);
        // The scan row's OWN Rule A marks stay on the Daily pane: they are what
        // the published scan found, and they must not be silently replaced by
        // the chart's recomputation of the same rule.
        d.timeframes["1D"].markers = momentumMarkers(row, daily);
        const pl = d.timeframes["1D"].plan;
        if (pl) {
          d.dir = pl.dir === 1 ? "LONG" : "SHORT";
          d.entry = pl.entry; d.stop = pl.stop;
          d.tp1 = pl.tp1; d.tp2 = pl.tp2; d.tp3 = pl.tp3; d.target = pl.tp1;
          d.rr = 3;
        }
        const d3 = bucketBars(daily, 3 * 86400);
        if (d3.length >= 6) d.timeframes["3D"] = build(d3);
        const wk = resampleWeekly(daily);
        if (wk.length >= 6) d.timeframes["1W"] = build(wk);
        if (d.price == null) d.price = daily[daily.length - 1].close;
        renderDataHonesty();
        render(d);
      })
      .catch(() => fail(`No chart data for ${String(SYM).toUpperCase()} yet, and live history is unavailable right now.`));
  }

  // ── Held-plan chart: a REAL journal position, not a live scan guess ────────
  // Reached when the link carries he=/hs= (see `heldPlan` above, set by
  // journal.js's chart links). Same real D/3D/W/4H history build as
  // pmOnlyFallback, but the levels are the TRADE's own entry/stop/targets —
  // never the live scan's current read on the ticker, which can be a
  // different setup entirely (different entry, different direction, weeks
  // apart) from the position actually sitting in the journal.
  function heldPlanFallback(SYM, plan) {
    const assetType = market === "crypto" ? "crypto" : null;
    const isLong = plan.dir !== "SHORT";
    // Headline single target for the footer's "Target" metric — TP2 when a
    // ladder exists (same convention the live VIVEK chart uses), else
    // whichever TP is actually on the trade.
    const target = plan.tp1 != null || plan.tp2 != null || plan.tp3 != null
      ? (plan.tp2 ?? plan.tp1 ?? plan.tp3) : null;
    const risk = Math.abs(plan.entry - plan.stop);
    const rr = (risk > 0 && target != null)
      ? Math.round((Math.abs(target - plan.entry) / risk) * 100) / 100 : 0;
    const d = {
      symbol: String(SYM).toUpperCase(), name: SYM, asset_type: assetType,
      price: null, grade: "", score: 0, score_max: 0, chips: [], sector: "",
      currency_symbol: market === "asx" ? "A$" : "$",
      tv_symbol: SYM, dir: isLong ? "LONG" : "SHORT",
      entry: plan.entry, stop: plan.stop, target,
      tp1: plan.tp1, tp2: plan.tp2, tp3: plan.tp3,
      rr, low_rr: rr > 0 && rr < 1.5,
      analysis: "Your position, as taken — entry/stop/target(s) from the journal, not a live scan read.",
      default_tf: "1D", level_lines: [], timeframes: {},
      _fallback: true, _vivek: false, _pm: false, _heldPlan: true,
    };
    // Level lines: SL red, ENTRY white, TPs green — same palette as the live
    // VIVEK ladder. A single-target trade (no tp2/tp3) labels its one TP line
    // "TARGET" rather than "TP1" so it doesn't imply a ladder that isn't there.
    if (d.stop  != null) d.level_lines.push({ price: d.stop,  color: "#ff5b5b", title: "STOP" });
    if (d.entry != null) d.level_lines.push({ price: d.entry, color: "#e5e9f0", title: "ENTRY" });
    if (d.tp1   != null) d.level_lines.push({ price: d.tp1, color: "#2fd07f", title: (d.tp2 != null || d.tp3 != null) ? "TP1" : "TARGET" });
    if (d.tp2   != null) d.level_lines.push({ price: d.tp2, color: "#2fd07f", title: "TP2" });
    if (d.tp3   != null) d.level_lines.push({ price: d.tp3, color: "#2fd07f", title: "TP3" });

    const liveDaily = () => (isCryptoMarket(assetType)
      ? vivekCryptoBars(SYM, "5y", "1d", true)
      : yahooBars(yfTickerFor(SYM, assetType), DAILY_RANGE, "1d", true));
    const intradayP = (isCryptoMarket(assetType)
      ? vivekCryptoBars(SYM, "2y", "1h")
      : yahooBars(yfTickerFor(SYM, assetType), "2y", "1h")).catch(() => []);
    liveDaily()
      .then((daily) => {
        if (!daily || daily.length < 6) throw new Error("thin");
        d.timeframes["1D"] = barsToVivekTF(daily);
        const d3 = bucketBars(daily, 3 * 86400);
        if (d3.length >= 6) d.timeframes["3D"] = barsToVivekTF(d3);
        const wk = resampleWeekly(daily);
        if (wk.length >= 6) d.timeframes["1W"] = barsToVivekTF(wk);
        if (d.price == null) d.price = daily[daily.length - 1].close;
        return intradayP.then((intraday) => {
          if (intraday && intraday.length >= 24) {
            const h4 = bucketBars(intraday, 4 * 3600);
            if (h4.length >= 6) d.timeframes["4H"] = barsToVivekTF(h4);
          }
          renderDataHonesty();
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

  // Empty state (2026-08-20, Task 11). chart.html with no s= used to dead-end
  // on fail("No ticker specified.") — a Retry button that reloads into the
  // same dead end. A missing symbol is not an ERROR, it is an empty state:
  // give it a symbol search scoped to a market, fed by the SAME published
  // scan file the deck reads (symbols + names into a datalist). Degrades to a
  // plain input when the fetch fails — typing an exact ticker still
  // navigates. Options are built via DOM nodes, never innerHTML, so scan-fed
  // names cannot inject markup.
  function emptyState() {
    hideSkeleton();
    const h = document.createElement("header");
    h.className = "chart-top";
    h.innerHTML = `<a class="back-link" href="index.html">← Dashboard</a>`;
    const d = document.createElement("div");
    d.className = "chart-error chart-empty";
    d.innerHTML = `<h2>Pick a ticker</h2>
      <p>This page charts one symbol. Search one here, or open any row from the dashboard.</p>
      <form id="ce-form" autocomplete="off">
        <select id="ce-mkt" aria-label="Market">
          <option value="asx">ASX</option>
          <option value="nasdaq">NASDAQ</option>
          <option value="crypto">CRYPTO</option>
        </select>
        <input id="ce-sym" list="ce-list" placeholder="Symbol — e.g. BHP"
               aria-label="Ticker symbol" maxlength="15" spellcheck="false" />
        <datalist id="ce-list"></datalist>
        <button class="tv-btn" type="submit">Open chart →</button>
      </form>
      <p class="ce-hint" id="ce-hint"></p>`;
    document.body.replaceChildren(h, d);
    const mktSel = document.getElementById("ce-mkt");
    const inp = document.getElementById("ce-sym");
    const list = document.getElementById("ce-list");
    const hint = document.getElementById("ce-hint");
    mktSel.value = ["asx", "nasdaq", "crypto"].includes(market) ? market : "asx";
    const fill = async () => {
      list.replaceChildren();
      hint.textContent = "";
      try {
        const r = await fetch(`data/${mktSel.value}_vivek.json`, { cache: "no-cache" });
        if (!r.ok) return;
        const rows = (await r.json()).results || [];
        for (const row of rows.slice(0, 400)) {
          const o = document.createElement("option");
          o.value = String(row.symbol || "").toUpperCase();
          if (row.name) o.label = String(row.name);
          list.append(o);
        }
        if (rows.length) hint.textContent = `${rows.length} names on the latest ${mktSel.value.toUpperCase()} scan — start typing to match.`;
      } catch (_) { /* plain input still navigates */ }
    };
    mktSel.addEventListener("change", fill);
    fill();
    document.getElementById("ce-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const s = inp.value.trim().toUpperCase();
      if (!/^[A-Z0-9.\-]{1,15}$/.test(s)) { inp.focus(); return; }
      location.href = `chart.html?m=${encodeURIComponent(mktSel.value)}&s=${encodeURIComponent(s)}`;
    });
    inp.focus();
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

  // HIGH CONVICTION (matches the dashboard, owner ruling 2026-09-20): an A/A+
  // row with an ARMED plan in one of the four backtest-edge cells — 1W
  // reclaim, 1W break, 3D reclaim, 1D break. One 🎯 per cell it fires on.
  // PARITY: the HC_CELLS literal is parsed out of this file by
  // tests/test_conviction.py and must equal scanner/conviction.py HC_CELLS.
  function convictionCells(d) {
    const HC_CELLS = { "1W": ["reclaim", "break"], "3D": ["reclaim"], "1D": ["break"] };
    if (!d || (d.grade !== "A+" && d.grade !== "A")) return [];
    const out = [];
    for (const tf of Object.keys(HC_CELLS)) {
      // Prefer the raw scan plan (always present in the JSON); fall back to the
      // built timeframe when it is a genuine (non-approx) one.
      const built = d.timeframes && d.timeframes[tf];
      const p = (d.plans && d.plans[tf]) || (built && !built.approx && built.levels) || null;
      if (p && p.armed && HC_CELLS[tf].includes(p.entry_trigger)) out.push(tf + " " + p.entry_trigger);
    }
    return out;
  }
  function isHighConviction(d) {
    return convictionCells(d).length > 0;
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

  // DATA HONESTY chip (2026-08-15): label what this series cannot support
  // instead of drawing it with full confidence. Thin ASX names arrive with up
  // to HALF their sessions as flat no-trade padding (measured the day this
  // shipped: RML 49% of its "5y" window), and Yahoo silently degrades deep
  // ranges to coarser bars (max/1d observed returning monthly candles).
  // Structure TA over either is fiction; one chip says so at the moment of
  // reading. Severity order: degraded interval beats thin tape beats raw
  // basis — one message, the worst one, never a chip pile-up.
  const THIN_TAPE_MIN_SHARE = 0.10;   // >=10% flat sessions ⇒ the tape is unreliable
  function renderDataHonesty() {
    const el = $("#ct-datawarn");
    if (!el || !DATA_META) return;
    const m = DATA_META;
    if (m.degraded) {
      el.textContent = "⚠ COARSE BARS";
      el.title = "The data source returned coarser candles than requested at this depth — each bar " +
        "spans more time than the timeframe label claims, so SMA/structure readings are not comparable. " +
        "Use a shorter range.";
      el.hidden = false;
      return;
    }
    const share = m.bars ? m.flat / m.bars : 0;
    if (share >= THIN_TAPE_MIN_SHARE) {
      el.textContent = `⚠ THIN TAPE ${Math.round(share * 100)}%`;
      el.title = `${m.flat} of ${m.bars} sessions in this window printed no trade (flat, padded bars). ` +
        "Bases, SMAs and reactions on a tape this thin are unreliable — treat structure TA here " +
        "with suspicion and check the order book before believing a level.";
      el.hidden = false;
      return;
    }
    if (m.basis === "raw") {
      el.textContent = "RAW BASIS";
      el.title = "Adjusted history was unavailable for this series, so bars are raw while scan levels are " +
        "dividend/split-adjusted — levels can sit visibly off these bars.";
      el.hidden = false;
    }
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


  function header(d) {
    const cur = d.currency_symbol || "";
    hideSkeleton();
    $("#ct-sym").textContent = d.symbol;
    document.title = `${d.symbol} — Vivek 5.0`;
    const mk = $("#ct-market");
    if (mk) {
      const lbl = MARKET_LABEL[market] || market.toUpperCase();
      mk.textContent = lbl; mk.dataset.mk = chartMarket; mk.hidden = false;
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
    if (hc) {
      const cells = convictionCells(d);
      hc.hidden = !cells.length;
      if (cells.length) {
        hc.textContent = `${"🎯".repeat(Math.min(cells.length, 3))} HIGH CONVICTION`;
        hc.title = `High conviction: ${cells.join(" + ")} — armed A/A+ in the backtest's best cells; one 🎯 per cell`;
      }
    }
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

  // The Auto box as a metric strip: direction, the five levels, the R each one
  // sits at, and how old the signal is. `age` is the honest half -- the box is
  // drawn from a cross that may be 50 bars back, and a reader who cannot see
  // that will read a stale plan as a live one.
  function renderMomentumFooter(d, tfKey) {
    const cur = d.currency_symbol || "";
    const metric = (label, val, cls) =>
      `<div class="cf-metric"><span class="cfm-label">${label}</span>` +
      `<span class="cfm-val ${cls || ""}">${val}</span></div>`;
    const tf = (d.timeframes || {})[tfKey] || {};
    const pl = tf.plan;
    const el = $("#cf-metrics");
    if (!el) return;
    if (!pl) {
      el.innerHTML = metric("Auto plan", "none", "amber") +
        metric("Why", `no scored cross in the last ${TV_PLAN.autoMaxAge} bars`, "");
      const an = $("#cf-analysis");
      if (an) an.textContent = d.analysis || "";
      return;
    }
    const isLong = pl.dir === 1;
    el.innerHTML = [
      metric("Auto", isLong ? "LONG" : "SHORT", isLong ? "green" : "red"),
      metric("Entry", fmt(pl.entry, cur)),
      metric("SL", fmt(pl.stop, cur), "red"),
      metric("TP1", fmt(pl.tp1, cur), "green"),
      metric("TP2", fmt(pl.tp2, cur), "green"),
      metric("TP3", fmt(pl.tp3, cur), "green"),
      metric("R", fmt(pl.risk, cur), "amber"),
      metric("R:R", "3.00", "green"),
      metric("Signal", `${pl.age}b ago · score ${pl.score}`, ""),
      metric("Stop", pl.capped ? `swing, cut to ${TV_PLAN.maxStopPct}%` : "5-bar swing + ATR pad", ""),
    ].join("");
    const an = $("#cf-analysis");
    if (an) an.textContent = d.analysis || "";
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
    // MOMENTUM: the Auto box, not the 5.0 strip. The generic footer below
    // prints SCORE 0/0 and RISK — because this lens publishes neither, and a
    // row of blanks reads as a broken page rather than as a different system.
    if (d._momentum) {
      renderMomentumFooter(d, d.default_tf || "1D");
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
  //
  // TOP100 #39 (REFINEMENTS #1, verified still live). This used to read
  // `d.entry` / `d.stop` — the DEFAULT timeframe's plan — inside a closure that
  // nothing re-invoked, so switching W→D redrew every level line, relabelled
  // the whole R ladder, rewrote the footer, and left the share count sitting
  // there computed off the weekly stop. The failure is silent and it is
  // one-directional: a weekly stop is the widest in the ladder, so the stale
  // number is always TOO SMALL against a daily plan — a size that looks
  // conservative, reads as deliberate, and belongs to a trade you are no longer
  // looking at. Nothing on screen said which timeframe it meant, so there was
  // no way to catch it by eye either.
  //
  // The fix is `_activeLevels`, plus a recompute hook applyVivekLevels calls
  // after it swaps the plan.
  // DELIBERATELY not a re-invocation of wireSizeCalc: that rebuilds host
  // innerHTML, which would blow away focus and caret position mid-keystroke on
  // every switch. Only the output line is recomputed.
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
    // The plan actually on screen. Falls back to the top-level plan for the
    // non-VIVEK charts that have no per-timeframe levels, and for the first
    // paint — render() wires this before the chart has drawn once, so
    // `_activeLevels` does not exist yet and `d` is the correct answer.
    const planNow = () => {
      const lv = d._activeLevels;
      return (lv && lv.entry != null && lv.stop != null) ? lv : d;
    };
    const calc = () => {
      acct = +($("#ms-acct").value || 0);
      risk = +($("#ms-risk").value || 0);
      try { localStorage.setItem(LS_ACCT, String(acct)); localStorage.setItem(LS_RISK, String(risk)); } catch (_) {}
      const plan = planNow();
      const dist = Math.abs(plan.entry - plan.stop);
      if (!(acct > 0) || !(risk > 0) || !(dist > 0)) { out.textContent = ""; return; }
      const riskD = acct * risk / 100;
      const shares = riskD / dist;
      const units = shares >= 100 ? Math.floor(shares) : +shares.toFixed(4);
      const notional = shares * plan.entry;
      // NAME the timeframe. The number is only meaningful against one plan, and
      // the whole defect above was that it silently belonged to a different one.
      const tf = d._activeTf ? ` <span class="ms-tf">${esc(d._activeTf)} plan</span>` : "";
      out.innerHTML = `→ <strong>${units.toLocaleString()}</strong> units ` +
        `≈ ${cur}${Math.round(notional).toLocaleString()} notional · ` +
        `1R = ${cur}${riskD.toFixed(0)}${notional > acct ? ` · ×${(notional / acct).toFixed(1)} leverage` : ""}${tf}`;
    };
    $("#ms-acct").addEventListener("input", calc);
    $("#ms-risk").addEventListener("input", calc);
    // Hung off `d` rather than a module-scoped variable because applyVivekLevels
    // lives in another function and `d` is already the channel between them.
    // A stale handle is impossible: a new render() overwrites it before the new
    // chart can call it.
    d._recalcMySize = calc;
    calc();
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
    const isCryptoQuote = (d.asset_type === "crypto" || market === "crypto");
    const srcParam = isCryptoQuote ? "&src=yahoo" : "";
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
        // The "~15m delayed" chip is an EQUITIES exchange-licensing fact
        // (Yahoo delays ASX/NASDAQ quotes ~15-20m). Crypto quotes are
        // real-time on Yahoo's 24/7 feed — the API layer says the same
        // (livePrice: delayed = !crypto) — so unhiding the chip on a crypto
        // chart was a FALSE label (owner-reported 2026-08-15). The header
        // price still refreshes every 20s for both.
        if (delayEl && !isCryptoQuote) delayEl.hidden = false;
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
    // Was a beforeunload clearInterval, which is a no-op (page teardown clears
    // intervals anyway) AND a bfcache hazard. This poll writes into the price
    // element of the render that started it; the next render owns that element.
    onRenderTeardown(() => clearInterval(iv));
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
    // FIRST line, before anything is wired: whatever the previous render left
    // running is stopped here. render() is re-entrant (every timeframe button
    // is a call site), so this is the only place the previous pass's intervals,
    // listeners and tick subscribers can be reached — by the time the new box
    // node exists, the old one has already been orphaned.
    tearDownPreviousRender();
    header(d); footer(d); wireSizeCalc(d);
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
    // A held position gets its own badge below instead — "no saved scan chart"
    // would be misleading here, since the reason has nothing to do with a
    // missing scan.
    if (d._fallback && !d._vivek && !d._pm && !d._heldPlan) {
      const note = document.createElement("span");
      note.className = "ct-fallback-note";
      note.textContent = "live fallback";
      note.title = "No saved scan chart for this ticker — showing recent history pulled live.";
      const priceEl = $("#ct-price");
      if (priceEl && priceEl.parentNode) priceEl.parentNode.insertBefore(note, priceEl.nextSibling);
    }
    if (d._heldPlan) {
      const note = document.createElement("span");
      note.className = "ct-fallback-note";
      note.textContent = "your position";
      note.title = "Entry/stop/target(s) shown are this trade's own numbers from the journal, not a live scan read.";
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

    // ── MOMENTUM sub-panes (2026-09-22): MACD and RSI, the two panes the
    // owner's TradingView layout carries beside the price. Built with the same
    // priceScaleId + scaleMargins banding as the squeeze histogram above, so
    // the price is squeezed into the top and each pane owns a strip. Momentum
    // only -- a 5.0 chart adds no series and keeps its scale margins.
    let macdHistS = null, macdLineS = null, macdSigS = null, rsiS = null;
    if (d._momentum) {
      chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.03, bottom: 0.46 } });
      macdHistS = chart.addHistogramSeries({
        priceScaleId: "macd", lastValueVisible: false, priceLineVisible: false });
      macdLineS = chart.addLineSeries({
        priceScaleId: "macd", color: "#4d9fff", lineWidth: 1,
        lastValueVisible: false, priceLineVisible: false });
      macdSigS = chart.addLineSeries({
        priceScaleId: "macd", color: "#ffb020", lineWidth: 1,
        lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("macd").applyOptions({ scaleMargins: { top: 0.56, bottom: 0.24 } });
      rsiS = chart.addLineSeries({
        priceScaleId: "rsi", color: "#a78bfa", lineWidth: 1,
        lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("rsi").applyOptions({ scaleMargins: { top: 0.80, bottom: 0.02 } });
      // 70 / 50 / 30 guides, drawn on the RSI series so they ride its scale.
      [[70, "rgba(255,91,91,0.45)"], [50, "rgba(140,155,180,0.30)"], [30, "rgba(47,208,127,0.45)"]]
        .forEach(([v, c]) => {
          try {
            rsiS.createPriceLine({ price: v, color: c, lineWidth: 1,
              lineStyle: LC.LineStyle.Dotted, axisLabelVisible: false, title: String(v) });
          } catch (_) { /* a refused guide must never cost the pane */ }
        });
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
        // Seeded from the timeframe's own markers rather than []: a Momentum
        // chart sets Rule A marks with NO levels, which is exactly the branch
        // this block owns, and a bare [] would drop them the moment a ticker
        // also had a PhaseMap record. Behaviour-preserving elsewhere -- every
        // other path sets `markers` only alongside `levels`, which this block
        // already excludes.
        const mk = ((tfs[key] || {}).markers || []).slice();
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

    // MOMENTUM: the Pine template's AUTO trade box. Same five lines the owner's
    // TradingView layout draws (Entry / SL / TP1-3), from Final_Top_Script.pine's
    // own maths -- NOT from vivek.py, which is a different system and is not
    // consulted here. Redrawn per timeframe; only 1D carries a plan.
    let momHandles = [];
    // The two shaded zones the template draws: entry->stop in red, entry->TP3
    // in the direction colour. Baseline series with a PRICE baseline, the same
    // mechanism the PhaseMap bands use, so the fill is a real band rather than
    // a line pretending to be one.
    let momRiskBand = null, momRewardBand = null, momAthLine = null;
    if (d._momentum) {
      const mkBand = (fill) => chart.addBaselineSeries({
        baseValue: { type: "price", price: 0 },
        topFillColor1: fill, topFillColor2: fill,
        bottomFillColor1: fill, bottomFillColor2: fill,
        topLineColor: "transparent", bottomLineColor: "transparent",
        lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
      });
      momRiskBand = mkBand("rgba(239,68,68,0.16)");
      momRewardBand = mkBand("rgba(59,130,246,0.14)");
    }
    function paintMomentumZones(key) {
      if (!momRiskBand) return;
      const pl = (tfs[key] || {}).plan;
      const cs = (tfs[key] || {}).candles || [];
      if (!pl || !cs.length) { momRiskBand.setData([]); momRewardBand.setData([]); return; }
      // The box spans the signal bar to the right edge, as the Pine box does.
      const t0 = pl.bar && pl.bar.time ? pl.bar.time : cs[0].time;
      const tN = cs[cs.length - 1].time;
      const span = (base, top) => {
        const lo = Math.min(base, top), hi = Math.max(base, top);
        return { lo, hi, rows: [{ time: t0, value: hi }, { time: tN, value: hi }] };
      };
      const risk = span(pl.entry, pl.stop);
      momRiskBand.applyOptions({ baseValue: { type: "price", price: risk.lo } });
      momRiskBand.setData(risk.rows);
      const rew = span(pl.entry, pl.tp3);
      momRewardBand.applyOptions({ baseValue: { type: "price", price: rew.lo } });
      momRewardBand.setData(rew.rows);
    }
    // ATH — the horizontal the template pins at the highest high it can see.
    function paintMomentumAth(key) {
      if (!d._momentum) return;
      if (momAthLine) { try { candle.removePriceLine(momAthLine); } catch (_) {} momAthLine = null; }
      const ath = (tfs[key] || {}).ath;
      if (!isFinite(ath)) return;
      momAthLine = candle.createPriceLine({ price: ath, color: "#2fd07f", lineWidth: 1,
        lineStyle: LC.LineStyle.Solid, axisLabelVisible: true, title: "ATH" });
    }
    function applyMomentumPlan(key) {
      momHandles.forEach((h) => { try { candle.removePriceLine(h); } catch (_) {} });
      momHandles = [];
      paintMomentumZones(key);
      paintMomentumAth(key);
      const pl = (tfs[key] || {}).plan;
      if (!pl) { d._activeLevels = null; return; }
      const ep = pl.entry;
      const line = (price, color, label, weight) => {
        if (price == null || !isFinite(price)) return;
        let t = label;
        if (ep > 0 && price !== ep) {
          const pct = (price - ep) / ep * 100;
          t += ` ${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
          if (pl.risk > 0) t += ` · ${(Math.abs(price - ep) / pl.risk).toFixed(1)}R`;
        }
        momHandles.push(candle.createPriceLine({ price, color, lineWidth: weight || 1,
          lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: t }));
      };
      line(pl.stop, "#ef4444", "SL", 2);
      line(pl.entry, "#9ca3af", "ENTRY", 2);
      line(pl.tp1, "#22c55e", "TP1", 2);
      line(pl.tp2, "#22c55e", "TP2", 1);
      line(pl.tp3, "#22c55e", "TP3", 1);
      d._activeLevels = { entry: pl.entry, stop: pl.stop, tp1: pl.tp1, tp2: pl.tp2, tp3: pl.tp3, rr: 3 };
      d._activeTf = key;
    }

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
      // TOP100 #39 — the size on screen is derived from `entry - stop`, so the
      // two lines above just invalidated it. Recompute the OUTPUT LINE only:
      // calling wireSizeCalc again would rebuild host.innerHTML and destroy the
      // caret mid-keystroke of anyone typing their account size. Guarded because
      // render() wires the sizer AFTER the first applyVivekLevels on some paths,
      // and because a chart with no entry/stop hides the panel and never sets it.
      if (typeof d._recalcMySize === "function") d._recalcMySize();
    }

    // ── open-position context (entry marker + floating LIVE box) ──────────────
    const SYM    = (d.symbol || symbol).toUpperCase();
    const posDir = (d.dir || "LONG").toLowerCase() === "short" ? "short" : "long";
    // The ▶ ENTRY arrow marked YOUR open manual position's fill bar. The manual
    // journal was removed 2026-09-21, so there is never one to mark;
    // buildEntryMarker returns null on a null epoch, which is the no-op.
    const entryEpoch = null;

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
      // MOMENTUM Daily first paint. Runs AFTER fitContent so the fallback is
      // the shared behaviour: too few bars to window (a young listing) and the
      // chart simply fits what it has rather than padding empty history.
      if (d._momentum && key === "1D") {
        const cs = (tfs[key] || {}).candles || [];
        if (cs.length >= MOM_FIRST_PAINT_BARS) {
          try {
            chart.timeScale().setVisibleLogicalRange({
              from: cs.length - MOM_FIRST_PAINT_BARS,
              to: cs.length - 1 + 6,     // + rightOffset, so the last bar is not flush
            });
          } catch (_) { /* a refused range must never cost the chart */ }
        }
      }
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
      if (d._momentum) {
        // Panes follow the timeframe; a TF with no panes clears them rather
        // than leaving the Daily's series under a weekly chart.
        const pn = (tfs[key] || {}).panes || null;
        if (macdHistS) macdHistS.setData(pn ? pn.macdHist : []);
        if (macdLineS) macdLineS.setData(pn ? pn.macd : []);
        if (macdSigS) macdSigS.setData(pn ? pn.macdSignal : []);
        if (rsiS) {
          rsiS.setData(pn ? pn.rsi : []);
          // The Bear/Bull labels the owner's RSI+ pane carries, placed on the
          // RSI line at the divergence PIVOT -- the same bar the price pane
          // marks, so the two panes agree about when it happened.
          if (typeof rsiS.setMarkers === "function") {
            // EVERY divergence in the series, not just the newest one. The
            // scan row carries only the current hit; the pane is history, and
            // a reader judging whether this signal is worth anything needs to
            // see how the previous ones resolved. Placed on the PIVOT bar
            // (Pine's offset = -lbR), so the tag sits where the divergence is
            // drawn rather than where it was confirmed.
            const cs = (tfs[key] || {}).candles || [];
            const mk = ((tfs[key] || {}).divs || []).map((dv) => {
              const b = cs[dv.pivot];
              return b ? {
                time: b.time,
                position: dv.bull ? "belowBar" : "aboveBar",
                color: dv.bull ? "#3b82f6" : "#ef4444",
                shape: dv.bull ? "arrowUp" : "arrowDown",
                text: dv.bull ? "Bull" : "Bear",
              } : null;
            }).filter(Boolean);
            mk.sort((a, b) => a.time - b.time);
            rsiS.setMarkers(mk);
          }
        }
        applyMomentumPlan(key);
        renderMomentumFooter(d, key);       // the box changes per timeframe
      }
      if (d._momentum && typeof candle.setMarkers === "function") {
        // Rule A marks for THIS timeframe (only 1D carries any) PLUS the scored
        // cross labels the template writes on price: "+3 Bullish" / "-2 Bearish",
        // signed so the direction reads without the word. Runs before
        // applyPmZones, which re-composes them with the sweep/displacement
        // arrows when ?pm=1 brought a PhaseMap record along.
        const base = ((tfs[key] || {}).markers || []).slice();
        const cs = (tfs[key] || {}).candles || [];
        for (const x of ((tfs[key] || {}).crosses || [])) {
          const b = cs[x.i];
          if (!b) continue;
          base.push({
            time: b.time, position: x.bull ? "belowBar" : "aboveBar",
            color: x.bull ? "rgba(59,130,246,0.85)" : "rgba(239,68,68,0.85)",
            shape: "circle",
            text: `${x.bull ? "+" : "-"}${x.score} ${x.bull ? "Bullish" : "Bearish"}`,
          });
        }
        // setMarkers requires ascending unique times; a cross and a Rule A mark
        // can land on one bar, so sort and let the later one sit beside it.
        base.sort((a, b) => a.time - b.time);
        candle.setMarkers(base);
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
    // MOMENTUM caption — always on, never dismissible. A chart with markers and
    // moving averages and no levels looks like a plan whose lines have not
    // loaded yet; this says, on the canvas, that there are none to load.
    // textContent, not innerHTML: it is a fixed string but the habit is the
    // point (escaping.test.js pins the family).
    if (d._momentum) {
      const cap = document.createElement("div");
      cap.className = "mom-caption";
      cap.textContent = MOM_CAPTION;
      el.style.position = "relative";
      el.appendChild(cap);
    }

    const toggle = $("#tf-toggle");
    // Live Binance feed only for genuine crypto (by asset_type) — commodities and
    // stocks in the scalp universe stay on static scan data. VIVEK is a daily-200
    // SMA swing view, so it never switches into the intraday scalp stream (which
    // would recompute the BB/KC/EMA9/21 overlays we deliberately don't want here).
    // Same carve-out for a held journal position (_heldPlan) and a PhaseMap-only
    // chart (_pm): both already fetched real Daily/3D/Weekly/4H history above
    // (pmOnlyFallback / heldPlanFallback) specifically so it could be shown —
    // forcing the 15M/30M/1H live stream here discarded all of it and was the
    // reason a crypto position's chart never opened on Daily (2026-08-20).
    const pair = (!d._vivek && !d._heldPlan && !d._pm && (d.asset_type === "crypto" || market === "crypto")) ? cryptoPair(SYM) : null;
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

  // ── live-stream reconnect policy (TOP100 #82) ────────────────────────────
  // `ws.onclose = () => setTimeout(connect, 3000)` had three defects, and the
  // quiet one is the worst:
  //
  //   1. NO BACKOFF. Binance down, wifi off, a laptop lid closed on a coffee
  //      shop captive portal — the tab hammers a dead endpoint every 3s for as
  //      long as it is open. Overnight that is ~28,000 connection attempts from
  //      one tab, which is how an IP earns a rate-limit ban from the exchange
  //      whose prices the whole live box depends on.
  //   2. NO CAP, so nothing ever slows down; the failure never gets cheaper.
  //   3. THE DEAD END: `catch (_) { return; }` around `new WebSocket(...)`
  //      scheduled NOTHING. A constructor throw (blocked URL, exhausted socket
  //      pool) killed the feed permanently — the price box freezes on its last
  //      value and looks exactly like a market that has stopped moving.
  //
  // And the correctness bug underneath all three: a `setTimeout(connect, 3000)`
  // already in flight when `switchTo` fired kept its appointment, so socket B
  // (15m) came up beside socket A (1h) and both interleaved bars into the SAME
  // array and the SAME candle series. `wsGen` below is the fix — the same
  // generation-token shape as `_pollToken` in app.js (#79) — and it is what
  // makes the backoff safe to add rather than merely polite.
  const WS_BACKOFF_BASE_MS = 3000;    // ceiling for the first retry (the old fixed wait)
  const WS_BACKOFF_MAX_MS  = 60000;   // a dead feed retries once a minute, not 20x
  const WS_STABLE_MS       = 30000;   // uptime that counts as "this connection worked"
  // EQUAL jitter — the delay is drawn from [ceil/2, ceil], so it can never
  // exceed the cap. A ±25% scheme around the ceiling would overshoot MAX, and
  // the point of a cap is that it is one. Jitter at all because every open tab
  // on a network reconnects off the same outage: without it they retry in
  // lockstep for ever, which is a self-inflicted thundering herd.
  const wsBackoffMs = (fails, rnd) => {
    const ceil = Math.min(WS_BACKOFF_MAX_MS, WS_BACKOFF_BASE_MS * Math.pow(2, Math.max(0, fails | 0)));
    // The clamp is written to be TOTAL — every input maps to [0, 1], including
    // NaN. `Math.min(1, Math.max(0, rnd))` looks equivalent and is not: it
    // returns NaN for a NaN `rnd`, the delay comes back NaN, and
    // `setTimeout(fn, NaN)` fires IMMEDIATELY. That is a reconnect storm wearing
    // a backoff's clothes — the exact failure this function exists to prevent,
    // reachable only through the argument nobody checks. Unreachable today (the
    // one call site passes `Math.random()`), but "the delay never exceeds
    // WS_BACKOFF_MAX_MS" should be an invariant of the function, not a property
    // of its current caller.
    const j = rnd > 0 ? (rnd < 1 ? rnd : 1) : 0;   // NaN fails `> 0` and lands on 0
    return Math.round(ceil / 2 + (ceil / 2) * j);
  };
  // Reset on a STABLE close, never on `onopen`. Resetting when the socket opens
  // is the classic version of this bug: a server that accepts the handshake and
  // immediately hangs up would zero the counter every single time and put the
  // 3-second storm straight back, wearing a backoff's clothes. A failed
  // handshake (upMs 0) therefore counts as a failure, and so does a throw.
  const wsNextFails = (fails, upMs) => (upMs >= WS_STABLE_MS ? 0 : (fails | 0) + 1);

  // Live Binance feed controller. The forming candle ticks in real time, the
  // indicators recompute on each update, and the timeframe (15m/30m/1h) can be
  // switched on the fly. Falls back silently to whatever was painted if the
  // network/stream is unavailable.
  function makeLive(d, pair, S) {
    const cur = d.currency_symbol || "";
    const N_DISP = 120, KEEP = 1000;   // KEEP = Binance max per request → deepest intraday history
    const liveEl = $("#ct-live"), priceEl = $("#ct-price");
    let bars = [], ws = null, stopped = false, lastCalc = 0, lastPx = null;
    // wsGen is the generation token: every socket, every handler and every
    // pending retry timer is stamped with the generation that created it, and
    // anything from an older generation is inert. wsTimer holds the one pending
    // retry so closeWs can cancel it rather than merely outrun it.
    let wsGen = 0, wsFails = 0, wsTimer = null;
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

    function retry(gen) {
      if (stopped || gen !== wsGen) return;
      const wait = wsBackoffMs(wsFails - 1, Math.random());
      clearTimeout(wsTimer);
      wsTimer = setTimeout(() => { if (!stopped && gen === wsGen) connect(); }, wait);
    }

    function connect() {
      if (stopped) return;
      const gen = wsGen;                 // this socket belongs to THIS generation
      let upAt = 0;
      let sock;
      try { sock = new WebSocket(streamURL()); }
      catch (_) {
        // Previously `return`, which ended the feed for good. A throw is a
        // failure like any other and must be retried on the same schedule.
        wsFails = wsNextFails(wsFails, 0);
        retry(gen);
        return;
      }
      ws = sock;
      sock.onopen = () => { upAt = Date.now(); };
      sock.onmessage = (ev) => {
        if (gen !== wsGen) return;       // a socket from a superseded timeframe
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
      sock.onclose = () => {
        if (gen !== wsGen) return;       // closeWs() already moved on
        wsFails = wsNextFails(wsFails, upAt ? Date.now() - upAt : 0);
        retry(gen);
      };
      sock.onerror = () => { try { sock.close(); } catch (_) {} };
    }

    // Bumping the generation is what makes this a real cancel rather than a
    // request to stop: any handler or pending timer still holding the old `gen`
    // sees it no longer matches and does nothing. Clearing `onmessage` as well
    // as `onclose` matters — a socket already in the middle of closing can
    // still deliver a buffered frame into the wrong timeframe's bar array.
    function closeWs() {
      wsGen++;
      clearTimeout(wsTimer); wsTimer = null;
      if (ws) { try { ws.onclose = null; ws.onmessage = null; ws.close(); } catch (_) {} }
      ws = null;
    }

    function start() { load().then(connect).catch(() => {}); }
    function switchTo(ivKey) {
      const niv = BINANCE_IV[ivKey];
      if (!niv || niv === iv) return;
      iv = niv; ivSec = niv === "15m" ? 900 : niv === "30m" ? 1800 : 3600;
      closeWs(); lastPx = null;
      // Safe to zero the counter here because `load()` must RESOLVE before
      // connect runs: a deliberate user action that also proves the network is
      // up should not inherit an outage's accumulated wait.
      wsFails = 0;
      load().then(connect).catch(() => {});
    }

    // This one used to be a `beforeunload`, and unlike the clearInterval pairs
    // it did real work — but at the wrong moment. makeLive is called from
    // INSIDE render (the crypto branch), so a re-render built a second
    // controller while the first kept streaming into the PREVIOUS chart's
    // series objects: not just wasted sockets, but `S.candle.update()` calls
    // against a chart that has been disposed. Tearing down per render closes
    // the socket at the instant it stops having anything valid to paint into;
    // at real page unload the browser drops the socket regardless.
    onRenderTeardown(() => { stopped = true; closeWs(); });
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
    // The `mousedown`/`touchstart` pair above cannot leak — they are on `box`,
    // which the next render abandons wholesale. `resize` is on WINDOW, which
    // outlives every box, and `restore` closes over this one: without the
    // removal below, every timeframe click left another handler measuring and
    // repositioning a detached node on every resize event. The document-level
    // drag handlers are only attached mid-drag and `onUp` removes them, but a
    // fetch can resolve into a re-render while the mouse is still down, so they
    // are swept here too (removeEventListener on an unattached handler is a
    // no-op, which is why this is safe to do unconditionally).
    onRenderTeardown(() => {
      window.removeEventListener("resize", restore);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
    });
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



  // ── prev / next through the scanner result list ──────────────────────────────
  // Lets you step down the same scan (e.g. all ASX reversals) without bouncing
  // back to the dashboard. Reads the scan-results JSON that backs this chart,
  // finds the current symbol's position, and wires the header arrows + ←/→ keys.
  async function wireScanNav() {
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

    /* src=eyes (owner, 2026-09-20): "that arrow back and forward; this should
     * continue down the chain of FOR MY EYES ... once i've clicked forward or
     * back a few times it marks off the LIST."
     *
     * So the arrows walk the STRIP's order, not the 200-name deck, and every
     * name landed on is marked reviewed — arriving here IS reviewing it. The
     * order was saved by the deck when the chip was clicked (window.EYES), and
     * it is scoped to this market and this scan: a stale chain is treated as no
     * chain and the arrows fall back to the ordinary deck list below, because
     * stepping yesterday's order through today's data would walk names that are
     * no longer aligned.
     */
    if (navSrc === "eyes" && window.EYES) {
      // The scope is the trading DAY, so this no longer has to fetch the scan
      // file just to learn a timestamp — one less request per chart open.
      const stamp = window.EYES.day();
      const chain = window.EYES.chain(market, stamp);
      const cur = decodeURIComponent(symbol).toUpperCase();
      // Mark on ARRIVAL, so stepping with the arrows (or the keyboard, or a
      // swipe) crosses names off exactly as clicking a chip does.
      // No fingerprint from here: the chart knows WHICH name but not why it
      // was aligned, so this dismisses at EYES.UNKNOWN and the deck upgrades
      // it to the real fingerprint on its next render (see eyes-store.js).
      window.EYES.mark(market, cur);
      const idx = chain.indexOf(cur);
      if (idx >= 0 && chain.length > 1) {
        const hrefEyes = (t) =>
          `chart.html?m=${market}&s=${encodeURIComponent(t)}&pm=1&src=eyes`;
        nav.hidden = false;
        posEl.textContent = `${idx + 1} / ${chain.length} eyes`;
        const goE = (i) => { if (i >= 0 && i < chain.length) location.href = hrefEyes(chain[i]); };
        prevB.disabled = idx === 0;
        nextB.disabled = idx === chain.length - 1;
        prevB.onclick = () => goE(idx - 1);
        nextB.onclick = () => goE(idx + 1);
        document.addEventListener("keydown", (e) => {
          if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
          if (e.key === "ArrowLeft" && idx > 0) goE(idx - 1);
          if (e.key === "ArrowRight" && idx < chain.length - 1) goE(idx + 1);
        });
        return;
      }
      // Not in the chain (a stale link, or the chain expired): fall through to
      // the ordinary deck nav rather than leaving the arrows dead.
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
        // v5 payload split (2026-07-31): a split summary carries LITE plans
        // only, and the ladder below draws full per-TF plans + markers. Join
        // the detail sidecar for THIS symbol before handing the row on. A
        // failed sidecar fetch degrades to the summary row — the headline
        // entry/SL/TP fields still live there, so the chart still renders
        // its ladder; only per-TF depth is lost.
        if (row && j && +j.schema_version >= 5 && mode === "vivek" && !isScalp) {
          return fetch(`data/${market}_vivek_detail.json`, { cache: "no-cache" })
            .then((r) => (r.ok ? r.json() : null))
            .then((dj) => {
              const extra = dj && dj.rows && dj.rows[row.symbol];
              return extra ? Object.assign({}, row, extra) : row;
            })
            .catch(() => row);
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
    if (!symbol) { emptyState(); return; }
    wireScanNav();
    wireBotPosBanner();
    // A real journal position (he=/hs= on the link) always wins over whatever
    // the live scan or PhaseMap would guess for this ticker — see heldPlan /
    // heldPlanFallback above. Checked before the VIVEK/PhaseMap/live-fallback
    // ladder below so a held trade never gets shown someone else's setup.
    if (heldPlan) { heldPlanFallback(baseSymbol, heldPlan); return; }
    // VIVEK has no per-ticker static chart files — render the 200 SMA reaction
    // live (with the full 5.0 level ladder). Three-tier fallback so a ticker
    // link NEVER dead-ends (owner rule 2026-07-02 after a journal name whose
    // setup had ended showed "Chart unavailable"):
    //   1. live VIVEK plan  -> full ladder chart (+ zones overlay if any)
    //   2. PhaseMap setup   -> zones-as-ladder chart
    //   3. neither          -> plain candles + SMAs, always renders
    // MOMENTUM: its own payload, its own stack, no 5.0 ladder. Fetched
    // alongside the PhaseMap record so zones still ride along (requirement 1).
    if (isMomentum) {
      Promise.all([momentumRow(baseSymbol), fetchPhaseMapRec()]).then(([mom, rec]) => {
        pmRec = rec;
        momentumFallback(baseSymbol, mom, rec);
      });
      return;
    }
    if (isVivek) {
      Promise.all([fetchResultMeta(), fetchPhaseMapRec()]).then(([meta, rec]) => {
        pmRec = rec;
        const hasPlan = meta && meta.entry != null && meta.stop != null && meta.tp1 != null;
        if (hasPlan) { vivekFallback(baseSymbol, meta); return; }
        pmOnlyFallback(baseSymbol, meta, rec);   // rec may be null -> plain chart
      });
      return;
    }
    // Non-VIVEK modes: straight to live bars. The static-chart fetch that used
    // to sit here could only ever 404 (see the note at the top of the file).
    fallbackFromLive();
  }

  boot();
})();

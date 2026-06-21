/* =========================================================================
   Chart page — candlestick chart (lightweight-charts) showing the user's own
   system (EMA/SMA + SuperTrend + entry/stop/target levels) on every timeframe.
   Timeframe buttons (D / 3D / W / M / 3M) switch the data client-side.
   ========================================================================= */
(() => {
  "use strict";

  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B": "var(--grade-b)", "C": "var(--grade-c)" };
  const TF_LABEL = { "1H": "1H", "1D": "D", "3D": "3D", "1W": "W", "1M": "M", "3M": "3M" };
  const TF_ORDER = ["1H", "1D", "3D", "1W", "1M", "3M"];

  const params = new URLSearchParams(location.search);
  const VALID_MARKETS = new Set(["asx", "nasdaq", "crypto", "scalp"]);
  const marketRaw = (params.get("m") || "asx").toLowerCase();
  const market = VALID_MARKETS.has(marketRaw) ? marketRaw : "asx";
  const symbol = params.get("s") || "";
  const mode = (params.get("mode") || "pullback").toLowerCase();
  const modeDir = mode === "reversal" ? "_rev" : mode === "spec" ? "_spec" : "";
  const chartFile = `data/charts/${market}${modeDir}/${encodeURIComponent(symbol)}.json`;

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ── live crypto data (Binance public API — keyless, CORS-ok, 24/7) ──────────
  // <SYMBOL> -> Binance spot pair. All current crypto-scalp coins trade vs USDT.
  const BINANCE_MAP = {
    BTC: "BTCUSDT", ETH: "ETHUSDT", BNB: "BNBUSDT", SOL: "SOLUSDT",
    XRP: "XRPUSDT", ADA: "ADAUSDT", DOGE: "DOGEUSDT", AVAX: "AVAXUSDT",
    DOT: "DOTUSDT", LINK: "LINKUSDT", LTC: "LTCUSDT", BCH: "BCHUSDT",
  };
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

  // Build a chart-page "timeframe" object (candles + volume + 7 overlays + mom)
  // straight from live bars — lets a position chart render with no static JSON.
  function barsToTF(bars, nDisp = 120) {
    const n = Math.min(nDisp, bars.length), slice = bars.slice(-n);
    const candles = slice.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    const volume  = slice.map((b) => ({ time: b.time, value: Math.round(b.volume),
      color: b.close >= b.open ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.5)" }));
    const c = computeScalp(bars, nDisp);
    const meta = [["BB Upper", "#4477cc"], ["BB Mid", "#888888"], ["BB Lower", "#4477cc"],
                  ["KC Upper", "#cc7700"], ["KC Lower", "#cc7700"], ["EMA 9", "#ffd23f"], ["EMA 21", "#2fd07f"]];
    const lines = c.lineData.map((data, i) => ({ name: meta[i][0], color: meta[i][1], data }));
    return { candles, volume, histogram: c.hist, squeeze_dots: [], lines };
  }

  // Resample daily bars into weekly bars (keyed to Monday of each week).
  function resampleWeekly(bars) {
    const weeks = new Map();
    for (const b of bars) {
      const date = new Date(b.time * 1000);
      const dow = date.getUTCDay();
      const mon = b.time - (dow === 0 ? 6 : dow - 1) * 86400;
      if (!weeks.has(mon)) {
        weeks.set(mon, { time: mon, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume });
      } else {
        const w = weeks.get(mon);
        w.high = Math.max(w.high, b.high);
        w.low  = Math.min(w.low,  b.low);
        w.close  = b.close;
        w.volume += b.volume;
      }
    }
    return [...weeks.values()].sort((a, b) => a.time - b.time);
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
    d.innerHTML = "<h2>Chart unavailable</h2>";
    const p = document.createElement("p");
    p.textContent = msg;
    d.appendChild(p);
    document.body.replaceChildren(h, d);
  }

  function header(d) {
    const cur = d.currency_symbol || "";
    $("#ct-sym").textContent = d.symbol;
    document.title = `${d.symbol} — Googy Boys Scanner`;
    if (d.sector) { const s = $("#ct-sector"); s.textContent = d.sector; s.hidden = false; }
    $("#ct-price").textContent = fmt(d.price, cur);
    const g = $("#ct-grade"); g.textContent = d.grade; g.style.color = GRADE_VAR[d.grade] || "var(--grade-c)";
    const dirEl = $("#ct-dir");
    if (d.dir) { dirEl.textContent = d.dir; dirEl.classList.toggle("short", d.dir.toUpperCase() === "SHORT"); }
    dirEl.hidden = false;
    $("#ct-chips").innerHTML = (d.chips || [])
      .map((c) => `<span class="chip${String(c).startsWith("WEEKLY") ? " weekly" : ""}">${esc(c)}</span>`).join("");
  }

  function footer(d) {
    const cur = d.currency_symbol || "";
    const metric = (label, val, cls) =>
      `<div class="cf-metric"><span class="cfm-label">${label}</span><span class="cfm-val ${cls || ""}">${val}</span></div>`;
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
    const isCrypto = !!BINANCE_MAP[SYM] || market === "scalp" || market === "crypto";
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

    buyBtn.addEventListener("click", () => {
      if (openSimTrade()) return;
      const px    = +liveState.price || +d.price || +d.entry || 0;
      if (!px) { statusEl.textContent = "No price available."; return; }
      const margin   = isCrypto ? SIM_CRYPTO_MARGIN   : SIM_STOCK_SIZE;
      const leverage = isCrypto ? SIM_CRYPTO_LEVERAGE : 1;
      const exposure = margin * leverage;
      const data  = mjLoad();
      data.trades.push({
        id: mjUid(), symbol: SYM, direction: dir,
        asset_type: isCrypto ? "crypto" : (market === "asx" ? "asx" : "nasdaq"),
        chart_market: market, chart_symbol: symbol,
        entry: px, entry_date: nowDate(), entry_time: nowTime(),
        size_usd: margin, leverage, shares: +(exposure / px).toFixed(8),
        stop: d.stop ?? null, target: d.target ?? null,
        notes: `Simulated from chart · ${d.grade || ""} ${(d.chips && d.chips[0]) || ""}`.trim(),
        status: "open", exit: null, exit_date: null, exit_time: null, sim: true, mtime: Date.now(),
      });
      mjSave(data);
      refresh();
    });

    sellBtn.addEventListener("click", () => {
      const t = openSimTrade();
      if (!t) return;
      const px = +liveState.price || +d.price || +t.entry || 0;
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

  function render(d) {
    header(d); footer(d); wireSim(d);
    const tfs = d.timeframes || {};
    const available = TF_ORDER.filter((k) => tfs[k]);
    if (!available.length) { fail("No chart data for this ticker yet."); return; }
    let curTF = tfs[d.default_tf] ? d.default_tf : available[0];

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

    (d.level_lines || []).forEach((L) => {
      if (L.price != null) candle.createPriceLine({ price: L.price, color: L.color, lineWidth: 1,
        lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: L.title });
    });

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
      $("#chart-legend").innerHTML = tf.lines.map((l) => {
        const last = l.data.length ? l.data[l.data.length - 1].value : null;
        return `<span><span class="cl-name" style="color:${l.color}">${l.name}</span> ${last != null ? fmt(last, d.currency_symbol) : ""}</span>`;
      }).join("");
    }
    function applyTF(key) {
      const tf = tfs[key]; if (!tf) return;
      curTF = key;
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
    }

    const toggle = $("#tf-toggle");
    const pair = BINANCE_MAP[SYM];
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
        `<button class="tf-btn${k === curTF ? " is-active" : ""}" data-tf="${k}">${TF_LABEL[k]}</button>`).join("");
      toggle.querySelectorAll(".tf-btn").forEach((b) => b.addEventListener("click", () => {
        toggle.querySelectorAll(".tf-btn").forEach((x) => x.classList.toggle("is-active", x === b));
        applyTF(b.dataset.tf);
      }));
      applyTF(curTF);
    }

    wireChartPosition(candle, d);
    wireLiveBox(d, el, SYM, posDir, findOpen);

    // ── Ruler / measurement tool ──────────────────────────────────────────────
    // Click once to anchor, move to see the range, click again to lock it.
    // Click a third time (or toggle off) to clear.
    const cur = d.currency_symbol || "";
    let rulerOn = false, anchor = null, anchorLine = null, hoverLine = null;

    const rulerBtn = document.createElement("button");
    rulerBtn.className = "tf-btn ruler-btn"; rulerBtn.title = "Measure price range";
    rulerBtn.innerHTML = "📏 Ruler";
    toggle.appendChild(rulerBtn);

    // For scalp charts (1H only), asynchronously fetch daily+weekly bars from
    // Yahoo Finance so the user can toggle to D / W context views. Reuses the
    // same 7-indicator computeScalp path, so lineSeries count stays stable.
    if (market === "scalp" && !pair && available.length === 1 && curTF === "1H") {
      const assetType = d.currency_symbol === "A$" ? "asx" : "nasdaq";
      const ticket = assetType === "asx" && !SYM.includes(".") ? SYM + ".AX" : SYM;
      fetch(`/api/bars?sym=${encodeURIComponent(ticket)}&interval=1d&range=2y`)
        .then((r) => r.ok ? r.json() : null)
        .then((j) => {
          if (!j || !Array.isArray(j.bars) || j.bars.length < 30) return;
          tfs["1D"] = barsToTF(j.bars, 300);
          const weekly = resampleWeekly(j.bars);
          if (weekly.length >= 15) tfs["1W"] = barsToTF(weekly, 150);
          const all = TF_ORDER.filter((k) => tfs[k]);
          toggle.innerHTML = all.map((k) =>
            `<button class="tf-btn${k === curTF ? " is-active" : ""}" data-tf="${k}">${TF_LABEL[k]}</button>`
          ).join("");
          toggle.querySelectorAll(".tf-btn").forEach((b) => b.addEventListener("click", () => {
            toggle.querySelectorAll(".tf-btn").forEach((x) => x.classList.toggle("is-active", x === b));
            applyTF(b.dataset.tf);
          }));
          toggle.appendChild(rulerBtn);
        })
        .catch(() => {});
    }

    // Floating label that sits inside the chart canvas area.
    const measureLabel = Object.assign(document.createElement("div"), { className: "ruler-label" });
    el.style.position = "relative";
    el.appendChild(measureLabel);

    function clearRuler() {
      anchor = null;
      if (anchorLine) { try { candle.removePriceLine(anchorLine); } catch (_) {} anchorLine = null; }
      if (hoverLine)  { try { candle.removePriceLine(hoverLine);  } catch (_) {} hoverLine  = null; }
      measureLabel.style.display = "none";
    }

    function showLabel(pt, p1, p2) {
      const delta = p2 - p1;
      const pct   = (delta / p1 * 100);
      const sign  = delta >= 0 ? "+" : "";
      const col   = delta >= 0 ? "#2fd07f" : "#ff5b5b";
      const dp    = Math.abs(p1) >= 100 ? 2 : Math.abs(p1) >= 1 ? 3 : 4;
      measureLabel.style.cssText =
        `display:block; top:${pt.y}px; left:${pt.x}px; border-color:${col}; color:${col}`;
      measureLabel.innerHTML =
        `${sign}${pct.toFixed(2)}% &nbsp; ${sign}${cur}${Math.abs(delta).toFixed(dp)}`;
    }

    rulerBtn.addEventListener("click", () => {
      rulerOn = !rulerOn;
      rulerBtn.classList.toggle("is-active", rulerOn);
      el.style.cursor = rulerOn ? "crosshair" : "";
      if (!rulerOn) clearRuler();
    });

    chart.subscribeClick((param) => {
      if (!rulerOn || !param.point) return;
      const price = candle.coordinateToPrice(param.point.y);
      if (price == null) return;
      if (!anchor) {
        anchor = price;
        anchorLine = candle.createPriceLine({
          price: anchor, color: "#f0a500", lineWidth: 1,
          lineStyle: 2, axisLabelVisible: true, title: fmt(anchor, cur),
        });
      } else {
        // Lock the measurement — replace hover line with a permanent one.
        if (hoverLine) { try { candle.removePriceLine(hoverLine); } catch (_) {} hoverLine = null; }
        candle.createPriceLine({ price, color: "#4d9fff", lineWidth: 1, lineStyle: 2, axisLabelVisible: true });
        showLabel(param.point, anchor, price);
        anchor = null;
        if (anchorLine) { try { candle.removePriceLine(anchorLine); } catch (_) {} anchorLine = null; }
        // Auto-hide the label after 6 s; user can click again to measure next range.
        setTimeout(() => { measureLabel.style.display = "none"; }, 6000);
      }
    });

    chart.subscribeCrosshairMove((param) => {
      if (!rulerOn || !anchor || !param.point) return;
      const price = candle.coordinateToPrice(param.point.y);
      if (price == null) return;
      if (hoverLine) hoverLine.applyOptions({ price, title: `${price > anchor ? "+" : ""}${((price - anchor) / anchor * 100).toFixed(2)}%` });
      else hoverLine = candle.createPriceLine({ price, color: "#4d9fff", lineWidth: 1, lineStyle: 2, axisLabelVisible: true });
      showLabel(param.point, anchor, price);
    });

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
  }

  // Live Binance feed controller. The forming candle ticks in real time, the
  // indicators recompute on each update, and the timeframe (15m/30m/1h) can be
  // switched on the fly. Falls back silently to whatever was painted if the
  // network/stream is unavailable.
  function makeLive(d, pair, S) {
    const cur = d.currency_symbol || "";
    const N_DISP = 120, KEEP = 320;
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
    const isCryptoPos = !!BINANCE_MAP[SYM] || market === "scalp" || market === "crypto";
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
      currency_symbol: "$", dir: trade.direction === "short" ? "SHORT" : "LONG",
      rr: 0, low_rr: false, rr_text: "", risk_pct: null,
      analysis: trade.notes || "Your open position — live view.",
      default_tf: "1H", tv_symbol: SYM, level_lines: [], timeframes: {},
    };
    if (trade.stop   != null) d.level_lines.push({ price: trade.stop,   color: "#ff5b5b", title: "STOP" });
    d.level_lines.push({ price: trade.entry, color: "#f0a500", title: "ENTRY" });
    if (trade.target != null) d.level_lines.push({ price: trade.target, color: "#2fd07f", title: "TARGET" });

    const pair = BINANCE_MAP[SYM];
    if (pair) {
      binanceKlines(pair, "1h", 320)
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

  function boot() {
    if (posId) { renderPosition(posId); return; }
    if (!symbol) { fail("No ticker specified."); return; }
    fetch(chartFile, { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(render)
      .catch(() => fail(`No chart data for ${symbol.toUpperCase()} (${market.toUpperCase()}). Run a scan first.`));
  }

  // If cloud sync is on, pull the latest journal first so positions taken on
  // another device show here too. Never block rendering on it for long.
  if (window.GBSSync && window.GBSSync.enabled()) {
    Promise.race([window.GBSSync.syncIn(), new Promise((res) => setTimeout(res, 2500))]).finally(boot);
  } else {
    boot();
  }
})();

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

  // ── live crypto data (Binance public API — keyless, CORS-ok, 24/7) ──────────
  // <SYMBOL> -> Binance spot pair. All current crypto-scalp coins trade vs USDT.
  const BINANCE_MAP = {
    BTC: "BTCUSDT", ETH: "ETHUSDT", BNB: "BNBUSDT", SOL: "SOLUSDT",
    XRP: "XRPUSDT", ADA: "ADAUSDT", DOGE: "DOGEUSDT", AVAX: "AVAXUSDT",
    DOT: "DOTUSDT", LINK: "LINKUSDT", LTC: "LTCUSDT", BCH: "BCHUSDT",
  };
  // Shared with the simulate buttons so a buy/sell fills at the true live price.
  const liveState = { price: null };

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
      .map((c) => `<span class="chip${c.startsWith("WEEKLY") ? " weekly" : ""}">${c}</span>`).join("");
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
  function mjLoad() {
    try { const r = localStorage.getItem(MJ_KEY); if (r) return JSON.parse(r); } catch (_) {}
    return { capital: 10000, brokerage: 10, trades: [] };
  }
  function mjSave(x) { localStorage.setItem(MJ_KEY, JSON.stringify(x)); }
  function mjUid()   { return Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }
  const nowDate = () => new Date().toLocaleDateString("en-CA");          // YYYY-MM-DD (local)
  const nowTime = () => new Date().toTimeString().slice(0, 5);            // HH:MM (local)

  function wireSim(d) {
    const buyBtn  = $("#cf-sim-buy");
    const sellBtn = $("#cf-sim-sell");
    const statusEl = $("#cf-sim-status");
    if (!buyBtn || !sellBtn) return;

    const cur  = d.currency_symbol || "";
    const dir  = (d.dir || "LONG").toLowerCase() === "short" ? "short" : "long";
    const SYM  = (d.symbol || symbol).toUpperCase();

    // Re-label the entry button to match the setup direction.
    buyBtn.textContent  = dir === "short" ? "▲ Simulate Short" : "▲ Simulate Buy";
    sellBtn.textContent = dir === "short" ? "▼ Cover / Close"  : "▼ Simulate Sell";

    const openSimTrade = () =>
      mjLoad().trades.find((t) => t.sim && t.status === "open" &&
        (t.symbol || "").toUpperCase() === SYM && t.direction === dir);

    function refresh() {
      const t = openSimTrade();
      if (t) {
        buyBtn.disabled = true; sellBtn.disabled = false;
        statusEl.className = "sim-status live";
        statusEl.textContent = `● In ${dir} @ ${fmt(t.entry, cur)} · ${t.shares} units`;
      } else {
        buyBtn.disabled = false; sellBtn.disabled = true;
        statusEl.className = "sim-status";
        statusEl.textContent = "";
      }
    }

    buyBtn.addEventListener("click", () => {
      if (openSimTrade()) return;
      const px    = +liveState.price || +d.price || +d.entry || 0;
      if (!px) { statusEl.textContent = "No price available."; return; }
      const size  = 1000;
      const data  = mjLoad();
      data.trades.push({
        id: mjUid(), symbol: SYM, direction: dir,
        entry: px, entry_date: nowDate(), entry_time: nowTime(),
        size_usd: size, shares: +(size / px).toFixed(4),
        stop: d.stop ?? null, target: d.target ?? null,
        notes: `Simulated from chart · ${d.grade || ""} ${(d.chips && d.chips[0]) || ""}`.trim(),
        status: "open", exit: null, exit_date: null, exit_time: null, sim: true,
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
        mjSave(data);
      }
      const m   = dir === "long" ? 1 : -1;
      const pnl = (t.shares * m * (px - t.entry) - 2 * (data.brokerage || 0));
      statusEl.className = "sim-status" + (pnl >= 0 ? " live" : "");
      statusEl.textContent = `Closed @ ${fmt(px, cur)} · P&L ${pnl >= 0 ? "+" : ""}${cur}${pnl.toFixed(2)} — logged to My Trades`;
      buyBtn.disabled = false; sellBtn.disabled = true;
    });

    refresh();
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
        candle.setMarkers(marks);
      }
      chart.timeScale().fitContent();
      legend(tf);
    }

    const toggle = $("#tf-toggle");
    toggle.innerHTML = available.map((k) =>
      `<button class="tf-btn${k === curTF ? " is-active" : ""}" data-tf="${k}">${TF_LABEL[k]}</button>`).join("");
    toggle.querySelectorAll(".tf-btn").forEach((b) => b.addEventListener("click", () => {
      toggle.querySelectorAll(".tf-btn").forEach((x) => x.classList.toggle("is-active", x === b));
      applyTF(b.dataset.tf);
    }));

    applyTF(curTF);

    // ── go LIVE for crypto scalp charts (1H, Binance stream) ──────────────────
    const pair = BINANCE_MAP[(d.symbol || "").toUpperCase()];
    if (pair && tfs["1H"]) startLive(d, pair, { chart, candle, vol, lineSeries, momSeries, fitOnce: true });

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
  }

  // Replace static 1H data with a live Binance feed; the forming candle ticks in
  // real time and indicators recompute on each update. Falls back silently to the
  // static chart if the network/stream is unavailable.
  function startLive(d, pair, S) {
    const cur = d.currency_symbol || "";
    const N_DISP = 120, KEEP = 320, REST = `https://api.binance.com/api/v3/klines?symbol=${pair}&interval=1h&limit=${KEEP}`;
    const liveEl = $("#ct-live"), priceEl = $("#ct-price");
    let bars = [], ws = null, stopped = false, lastCalc = 0, lastPx = null;

    const applyAll = () => {
      S.candle.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
      S.vol.setData(bars.map((b) => ({ time: b.time, value: Math.round(b.volume),
        color: b.close >= b.open ? "rgba(47,208,127,0.5)" : "rgba(255,91,91,0.5)" })));
      const c = computeScalp(bars, N_DISP);
      c.lineData.forEach((ld, i) => S.lineSeries[i] && S.lineSeries[i].setData(ld));
      if (S.momSeries) S.momSeries.setData(c.hist);
      if (typeof S.candle.setMarkers === "function") S.candle.setMarkers(c.markers);
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
    };

    fetch(REST, { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((rows) => {
        bars = rows.map((k) => ({ time: Math.floor(k[0] / 1000), open: +k[1], high: +k[2],
          low: +k[3], close: +k[4], volume: +k[5] }));
        if (!bars.length) return;
        applyAll();
        if (S.fitOnce) S.chart.timeScale().fitContent();
        setPrice(bars[bars.length - 1].close);
        if (liveEl) liveEl.hidden = false;
        connect();
      })
      .catch(() => { /* keep static chart */ });

    function connect() {
      if (stopped) return;
      try { ws = new WebSocket(`wss://stream.binance.com:9443/ws/${pair.toLowerCase()}@kline_1h`); }
      catch (_) { return; }
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
          if (typeof S.candle.setMarkers === "function") S.candle.setMarkers(c.markers);
        }
      };
      ws.onclose = () => { if (!stopped) setTimeout(connect, 3000); };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    }

    window.addEventListener("beforeunload", () => { stopped = true; if (ws) try { ws.close(); } catch (_) {} });
  }

  if (!symbol) { fail("No ticker specified."); return; }
  fetch(chartFile, { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(() => fail(`No chart data for ${symbol.toUpperCase()} (${market.toUpperCase()}). Run a scan first.`));
})();

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
      const px    = +d.price || +d.entry || 0;
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
      const px = +d.price || +t.entry || 0;
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
    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
  }

  if (!symbol) { fail("No ticker specified."); return; }
  fetch(chartFile, { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(() => fail(`No chart data for ${symbol.toUpperCase()} (${market.toUpperCase()}). Run a scan first.`));
})();

/* =========================================================================
   Chart page — candlestick chart (lightweight-charts) showing the user's own
   system (EMA/SMA + SuperTrend + entry/stop/target levels) on every timeframe.
   Timeframe buttons (D / 3D / W / M / 3M) switch the data client-side.
   ========================================================================= */
(() => {
  "use strict";

  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B": "var(--grade-b)", "C": "var(--grade-c)" };
  const TF_LABEL = { "1D": "D", "3D": "3D", "1W": "W", "1M": "M", "3M": "3M" };
  const TF_ORDER = ["1D", "3D", "1W", "1M", "3M"];

  const params = new URLSearchParams(location.search);
  const market = (params.get("m") || "asx").toLowerCase();
  const symbol = params.get("s") || "";
  const mode = (params.get("mode") || "pullback").toLowerCase();
  const chartFile = `data/charts/${market}${mode === "reversal" ? "_rev" : ""}/${encodeURIComponent(symbol)}.json`;

  const $ = (s) => document.querySelector(s);

  function fmt(v, cur) {
    if (v == null || isNaN(v)) return "—";
    const a = Math.abs(v);
    const dp = a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : a >= 0.001 ? 6 : 8;
    return (cur || "") + v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }

  function fail(msg) {
    document.body.innerHTML = `<header class="chart-top"><a class="back-link" href="index.html">← Dashboard</a></header>
      <div class="chart-error"><h2>Chart unavailable</h2><p>${msg}</p></div>`;
  }

  function header(d) {
    const cur = d.currency_symbol || "";
    $("#ct-sym").textContent = d.symbol;
    document.title = `${d.symbol} — Googy Boys Scanner`;
    if (d.sector) { const s = $("#ct-sector"); s.textContent = d.sector; s.hidden = false; }
    $("#ct-price").textContent = fmt(d.price, cur);
    const g = $("#ct-grade"); g.textContent = d.grade; g.style.color = GRADE_VAR[d.grade] || "var(--grade-c)";
    $("#ct-dir").hidden = false;
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

  function render(d) {
    header(d); footer(d);
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

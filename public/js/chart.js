/* =========================================================================
   Chart page — renders a candlestick chart (TradingView lightweight-charts)
   with EMAs, SuperTrend, marked price levels and volume, from a per-ticker
   data file written by the scanner.
   ========================================================================= */
(() => {
  "use strict";

  const GRADE_VAR = { "A+": "var(--grade-aplus)", "A": "var(--grade-a)", "B": "var(--grade-b)", "C": "var(--grade-c)" };
  const params = new URLSearchParams(location.search);
  const market = (params.get("m") || "asx").toLowerCase();
  const symbol = params.get("s") || "";

  const $ = (s) => document.querySelector(s);

  function fmt(v, cur) {
    if (v == null || isNaN(v)) return "—";
    const dp = Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 3 : 4;
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
    const lv = d.levels || {};
    const metric = (label, val, cls) =>
      `<div class="cf-metric"><span class="cfm-label">${label}</span><span class="cfm-val ${cls || ""}">${val}</span></div>`;
    $("#cf-metrics").innerHTML = [
      metric("Entry", fmt(lv.entry, cur)),
      metric("Stop", fmt(lv.stop, cur), "red"),
      metric("Target", fmt(lv.target, cur), "green"),
      metric("Trail", "after entry", "amber"),
      metric("Score", `${d.score}/${d.score_max}`),
      metric("Risk", d.risk_pct != null ? `${d.risk_pct}%` : "—", "red"),
      metric("R:R", d.rr.toFixed(2), d.low_rr ? "red" : "green"),
    ].join("");
    $("#cf-analysis").textContent = d.analysis || "";
    if (d.low_rr) $("#cf-lowrr").innerHTML = `<span class="chip warn">LOW R:R (${d.rr_text})</span>`;
    const tv = $("#cf-tv");
    tv.href = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(d.tv_symbol || d.symbol)}`;
  }

  function legend(d) {
    const rows = [
      ["EMA 34", "#2fd07f", d.ema34], ["EMA 55", "#4d9fff", d.ema55],
      ["EMA 89", "#a78bfa", d.ema89], ["SuperTrend", "#2fd0c4", d.supertrend],
    ];
    $("#chart-legend").innerHTML = rows.map(([name, color, series]) => {
      const last = series && series.length ? series[series.length - 1].value : null;
      return `<span><span class="cl-name" style="color:${color}">${name}</span> ${last != null ? fmt(last, d.currency_symbol) : ""}</span>`;
    }).join("");
  }

  function render(d) {
    header(d); footer(d); legend(d);
    const el = $("#chart");
    const LC = window.LightweightCharts;
    const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const textColor = dark ? "#aeb9c9" : "#4b4b52";
    const gridColor = dark ? "rgba(84,84,88,0.28)" : "rgba(60,60,67,0.08)";
    const borderColor = dark ? "rgba(84,84,88,0.4)" : "rgba(60,60,67,0.14)";
    const chart = LC.createChart(el, {
      width: el.clientWidth, height: el.clientHeight,
      layout: { background: { color: "transparent" }, textColor,
        fontFamily: '-apple-system, "SF Pro Text", Inter, system-ui, sans-serif' },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      rightPriceScale: { borderColor },
      timeScale: { borderColor },
      crosshair: { mode: LC.CrosshairMode.Normal },
    });

    const candle = chart.addCandlestickSeries({
      upColor: "#2fd07f", downColor: "#ff5b5b",
      wickUpColor: "#2fd07f", wickDownColor: "#ff5b5b", borderVisible: false,
    });
    candle.setData(d.candles);

    const addLine = (data, color, width) => {
      const s = chart.addLineSeries({ color, lineWidth: width || 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(data || []);
      return s;
    };
    addLine(d.ema34, "#2fd07f");
    addLine(d.ema55, "#4d9fff");
    addLine(d.ema89, "#a78bfa");
    addLine(d.supertrend, "#2fd0c4", 1.5);

    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" } });
    vol.setData(d.volume || []);
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });

    const lv = d.levels || {};
    const line = (price, color, title) => {
      if (price == null) return;
      candle.createPriceLine({ price, color, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title });
    };
    line(lv.high, "#2fd0c4", "HIGH");
    line(lv.resistance, "#4d9fff", "RESISTANCE");
    line(lv.ema_watch, "#cbd5e1", "EMA WATCH");
    line(lv.stop, "#ff5b5b", "STOP");
    line(lv.leg_low, "#f5a623", "LEG LOW");
    line(lv.low, "#ff5b5b", "LOW");

    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
  }

  if (!symbol) { fail("No ticker specified."); return; }
  fetch(`data/charts/${market}/${encodeURIComponent(symbol)}.json`, { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(() => fail(`No chart data for ${symbol.toUpperCase()} (${market.toUpperCase()}). Run a scan first.`));
})();

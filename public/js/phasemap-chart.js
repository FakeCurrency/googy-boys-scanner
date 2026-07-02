/* PHASEMAP chart page — candles + every scanned zone drawn as a shaded band,
   with sweep/displacement markers. ?m=<market>&t=<ticker>&d=<direction> */
(() => {
  "use strict";

  const params = new URLSearchParams(window.location.search);
  const market = ["asx", "nasdaq", "crypto"].includes(params.get("m")) ? params.get("m") : "asx";
  const ticker = (params.get("t") || "").toUpperCase();
  const dir = params.get("d") || "";

  const $ = (sel) => document.querySelector(sel);

  /* zone colours — mirror css/phasemap.css bands */
  const ZONE_FILL = {
    TARGET: "rgba(47,208,127,0.16)",
    ENTRY_CONTINUATION: "rgba(55,208,196,0.14)",
    INVALIDATION_HARD: "rgba(255,91,91,0.16)",
    INVALIDATION_MOMENTUM: "rgba(255,91,91,0.16)",
    DEMAND: "rgba(255,178,36,0.18)",
    SUPPLY: "rgba(255,178,36,0.18)",
  };
  const ZONE_LINE = {
    TARGET: "#2fd07f",
    ENTRY_CONTINUATION: "#37d0c4",
    INVALIDATION_HARD: "#ff5b5b",
    INVALIDATION_MOMENTUM: "#ff5b5b",
    DEMAND: "#ffb224",
    SUPPLY: "#ffb224",
  };

  function fail(msg) {
    $("#pm-chart-head").innerHTML = `<span class="pm-ticker">${PM.esc(ticker || "?")}</span>`;
    $("#pm-chart-note").textContent = msg;
  }

  async function fetchJSON(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(url + " → HTTP " + res.status);
    return res.json();
  }

  function drawChart(candles, rec) {
    const el = $("#pm-chart");
    const chart = LightweightCharts.createChart(el, {
      height: Math.min(460, Math.max(320, window.innerHeight * 0.5)),
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: "#aab4c5",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(28,34,48,0.6)" },
        horzLines: { color: "rgba(28,34,48,0.6)" },
      },
      rightPriceScale: { borderColor: "#1c2230" },
      timeScale: { borderColor: "#1c2230", rightOffset: 6 },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    const times = candles.map((c) => c.t);
    const first = times[0];
    const last = times[times.length - 1];

    /* zone bands first, so candles draw on top */
    for (const z of rec.zones) {
      const dead = z.status === "CONSUMED" || z.status === "VIOLATED";
      const fill = ZONE_FILL[z.type] || "rgba(109,120,137,0.12)";
      const softFill = dead ? fill.replace(/[\d.]+\)$/, "0.06)") : fill;
      const band = chart.addBaselineSeries({
        baseValue: { type: "price", price: z.low },
        topFillColor1: softFill, topFillColor2: softFill,
        topLineColor: "transparent", bottomLineColor: "transparent",
        bottomFillColor1: "transparent", bottomFillColor2: "transparent",
        lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      band.setData([{ time: first, value: z.high }, { time: last, value: z.high }]);
      band.createPriceLine({
        price: z.high, color: ZONE_LINE[z.type] || "#6d7889",
        lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: false, title: "",
      });
      band.createPriceLine({
        price: (z.low + z.high) / 2, color: ZONE_LINE[z.type] || "#6d7889",
        lineWidth: 1, lineStyle: LightweightCharts.LineStyle.SparseDotted,
        axisLabelVisible: true,
        title: PM.zoneLabel(z) + (z.confluence > 1 ? " ×" + z.confluence : ""),
      });
      band.createPriceLine({
        price: z.low, color: ZONE_LINE[z.type] || "#6d7889",
        lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: false, title: "",
      });
    }

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#2fd07f", downColor: "#ff5b5b",
      wickUpColor: "#2fd07f", wickDownColor: "#ff5b5b",
      borderVisible: false,
    });
    candleSeries.setData(candles.map((c) => ({
      time: c.t, open: c.o, high: c.h, low: c.l, close: c.c,
    })));

    /* volume underlay */
    const vol = chart.addHistogramSeries({
      priceScaleId: "", priceFormat: { type: "volume" },
      color: "rgba(109,120,137,0.35)",
      priceLineVisible: false, lastValueVisible: false,
    });
    chart.priceScale("").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(candles.map((c) => ({ time: c.t, value: c.v || 0 })));

    /* sweep + displacement markers */
    const bull = rec.direction === "bullish";
    const m = rec.metrics || {};
    const markers = [];
    if (m.sweep_date && times.includes(m.sweep_date)) {
      markers.push({
        time: m.sweep_date,
        position: bull ? "belowBar" : "aboveBar",
        shape: bull ? "arrowUp" : "arrowDown",
        color: "#ffb224", text: "SWEEP",
      });
    }
    if (m.displacement_date && times.includes(m.displacement_date)) {
      markers.push({
        time: m.displacement_date,
        position: bull ? "belowBar" : "aboveBar",
        shape: bull ? "arrowUp" : "arrowDown",
        color: "#2fd07f", text: "DISPLACE",
      });
    }
    candleSeries.setMarkers(markers);

    chart.timeScale().fitContent();
    window.addEventListener("resize", () => chart.applyOptions({ width: el.clientWidth }));
  }

  function renderDetail(rec) {
    const speak = window.speechSynthesis
      ? `<button class="pm-speak" id="pm-speak-btn" title="Read aloud" aria-label="Read analysis aloud">▶ READ</button>` : "";
    $("#pm-chart-head").innerHTML = `
      <span class="pm-ticker">${PM.esc(rec.ticker)}</span>
      ${PM.headBadgesHTML(rec)}
      ${speak}`;
    $("#pm-chart-detail").innerHTML = `
      <div class="pm-card">
        <div class="pm-ladder">${PM.ladderHTML(rec)}</div>
        <p class="pm-narration">${PM.esc(rec.narration)}</p>
        <div class="pm-metrics">${PM.metricsHTML(rec)}</div>
      </div>`;
    const btn = $("#pm-speak-btn");
    if (btn) btn.addEventListener("click", () => PM.toggleSpeak(btn, rec.narration));
  }

  async function init() {
    if (!ticker) return fail("No ticker given.");
    document.title = `${ticker} · PHASEMAP — Vivek 5.0`;
    try {
      const [snap, chartData] = await Promise.all([
        fetchJSON(`data/phasemap/${market}/latest.json`),
        fetchJSON(`data/phasemap/charts/${market}/${encodeURIComponent(ticker)}.json`),
      ]);
      const recs = snap.results.filter((r) => r.ticker === ticker);
      const rec = recs.find((r) => r.direction === dir) || recs[0];
      if (!rec) return fail(`${ticker} isn't in the latest ${market.toUpperCase()} scan.`);
      renderDetail(rec);
      drawChart(chartData.candles, rec);
      $("#pm-chart-note").textContent =
        `${market.toUpperCase()} · scan ${snap.run_date} · zones drawn as scanned (dashed edges, dotted midline label)`;
    } catch (err) {
      fail(`Chart data unavailable — ${err.message}`);
    }
  }

  init();
})();

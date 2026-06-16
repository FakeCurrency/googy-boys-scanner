/* Markets & Sectors — renders public/data/sectors.json (ASX / US) and mounts
   live TradingView economic-calendar + news widgets per market. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  let DATA = null, market = "asx";
  const dark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

  const fmtNum = (v) => v == null ? "—"
    : v.toLocaleString(undefined, { minimumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2, maximumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2 });
  const fmtChg = (v) => v == null ? "" : (v >= 0 ? "+" : "") + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtPct = (v) => v == null ? "" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const cls = (v) => (v >= 0 ? "sec-up" : "sec-down");

  function renderIndices(list) {
    $("#sec-indices").innerHTML = list.map((i) => `
      <div class="idx-card">
        <div class="idx-sym">${i.name} · ${i.symbol}</div>
        <div class="idx-last">${fmtNum(i.last)}</div>
        <div class="idx-chg ${cls(i.chg_pct)}">${fmtPct(i.chg_pct)} <span style="color:var(--muted-2);font-weight:500">${fmtChg(i.chg)}</span></div>
      </div>`).join("");
  }

  function renderTable(list) {
    const maxAbs = Math.max(0.5, ...list.map((s) => Math.abs(s.chg_pct)));
    const rows = list.map((s) => {
      const w = Math.abs(s.chg_pct) / maxAbs * 50;
      const color = s.chg_pct >= 0 ? "var(--green)" : "var(--red)";
      const side = s.chg_pct >= 0 ? "left:50%" : "right:50%";
      const bar = `<span class="sec-bar"><i style="${side};width:${w}%;background:${color}"></i></span>`;
      return `<tr><td class="sec-sym">${s.symbol}</td><td class="sec-name">${s.name}</td>
        <td>${fmtNum(s.last)}</td><td class="${cls(s.chg)}">${fmtChg(s.chg)}</td>
        <td class="${cls(s.chg_pct)}">${fmtPct(s.chg_pct)}${bar}</td></tr>`;
    }).join("");
    $("#sec-table").innerHTML = `<table class="sec-table"><thead><tr>
      <th>Symbol</th><th>Sector</th><th>Last</th><th>Chg</th><th>Chg%</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function mountWidget(hostId, src, config) {
    const host = document.getElementById(hostId);
    if (!host) return;
    host.innerHTML = '<div class="tradingview-widget-container" style="height:100%;width:100%">'
      + '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div></div>';
    const s = document.createElement("script");
    s.type = "text/javascript"; s.async = true; s.src = src;
    s.innerHTML = JSON.stringify(config);
    host.firstChild.appendChild(s);
  }

  function mountWidgets() {
    const theme = dark() ? "dark" : "light";
    const country = market === "asx" ? "au" : "us";
    const newsSym = market === "asx" ? "ASX:XJO" : "SP:SPX";
    mountWidget("tv-calendar", "https://s3.tradingview.com/external-embedding/embed-widget-events.js", {
      colorTheme: theme, isTransparent: true, locale: "en",
      countryFilter: country, importanceFilter: "0,1", width: "100%", height: "100%",
    });
    mountWidget("tv-news", "https://s3.tradingview.com/external-embedding/embed-widget-timeline.js", {
      feedMode: "symbol", symbol: newsSym, isTransparent: true, displayMode: "regular",
      colorTheme: theme, locale: "en", width: "100%", height: "100%",
    });
  }

  function render() {
    const m = DATA.markets[market];
    $("#sec-market-label").textContent = m.label;
    $("#sec-summary-title").textContent = market === "asx" ? "What happened (last ASX session)" : "What happened overnight (US session)";
    $("#cal-title").textContent = market === "asx" ? "Economic calendar · Australia" : "Economic calendar · United States";
    $("#news-title").textContent = market === "asx" ? "ASX market news" : "US market news";
    renderIndices(m.indices || []);
    renderTable((m.sectors || []).slice().sort((a, b) => b.chg_pct - a.chg_pct));
    $("#sec-summary").textContent = m.summary || "—";
    $("#sec-rotation").textContent = m.rotation || "—";
    mountWidgets();
  }

  document.querySelectorAll("#sec-tabs .market-btn").forEach((b) => b.addEventListener("click", () => {
    if (b.classList.contains("is-active")) return;
    document.querySelectorAll("#sec-tabs .market-btn").forEach((x) => {
      x.classList.toggle("is-active", x === b);
      x.setAttribute("aria-selected", x === b ? "true" : "false");
    });
    market = b.dataset.market;
    render();
  }));

  fetch("data/sectors.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      DATA = d;
      try {
        const dt = new Date(d.generated_at);
        $("#sec-sub").textContent = `Read updated ${dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}, ${dt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} ${d.tz_label || ""} · calendar & news are live`;
      } catch (_) {}
      render();
    })
    .catch(() => {
      $("#sec-sub").textContent = "No sector data yet — calendar & news still load below.";
      // still mount the live widgets even if the auto-read data is missing
      DATA = { markets: { asx: {}, us: {} } };
      mountWidgets();
    });
})();

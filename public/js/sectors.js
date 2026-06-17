/* Markets & Sectors — single page, ASX (left) + US (right) side by side.
   Renders public/data/sectors.json and mounts live TradingView calendar + news
   widgets per market. */
(() => {
  "use strict";
  const dark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

  const fmtNum = (v) => v == null ? "—"
    : v.toLocaleString(undefined, { minimumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2, maximumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2 });
  const fmtChg = (v) => v == null ? "" : (v >= 0 ? "+" : "") + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtPct = (v) => v == null ? "" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const cls = (v) => (v >= 0 ? "sec-up" : "sec-down");

  function indicesHTML(list) {
    return `<div class="sec-indices">` + (list || []).map((i) => `
      <div class="idx-card">
        <div class="idx-sym">${esc(i.name)} · ${esc(i.symbol)}</div>
        <div class="idx-last">${fmtNum(i.last)}</div>
        <div class="idx-chg ${cls(i.chg_pct)}">${fmtPct(i.chg_pct)} <span style="color:var(--muted-2);font-weight:500">${fmtChg(i.chg)}</span></div>
      </div>`).join("") + `</div>`;
  }

  function tableHTML(list) {
    const sorted = (list || []).slice().sort((a, b) => b.chg_pct - a.chg_pct);
    const maxAbs = Math.max(0.5, ...sorted.map((s) => Math.abs(s.chg_pct)));
    const rows = sorted.map((s) => {
      const w = Math.abs(s.chg_pct) / maxAbs * 50;
      const color = s.chg_pct >= 0 ? "var(--green)" : "var(--red)";
      const side = s.chg_pct >= 0 ? "left:50%" : "right:50%";
      const bar = `<span class="sec-bar"><i style="${side};width:${w}%;background:${color}"></i></span>`;
      return `<tr><td class="sec-sym">${esc(s.symbol)}</td><td class="sec-name">${esc(s.name)}</td>
        <td>${fmtNum(s.last)}</td><td class="${cls(s.chg_pct)}">${fmtPct(s.chg_pct)}${bar}</td></tr>`;
    }).join("");
    return `<div class="sec-table-wrap"><table class="sec-table"><thead><tr>
      <th>Sym</th><th>Sector</th><th>Last</th><th>Chg%</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function moversHTML(tm) {
    if (!tm) return "";
    const list = (arr) => (arr || []).map((m) => `
      <li class="mv-item">
        <span class="mv-sym">${esc(m.symbol)}</span>
        <span class="mv-name">${esc(m.name)}${m.sector ? ` · ${esc(m.sector)}` : ""}</span>
        <span class="mv-pct ${cls(m.pct)}">${fmtPct(m.pct)}</span>
      </li>`).join("");
    return `<div class="mv-wrap">
      <div class="mv-col"><div class="mv-head up">▲ Biggest winners</div><ul class="mv-list">${list(tm.winners) || '<li class="mv-empty">—</li>'}</ul></div>
      <div class="mv-col"><div class="mv-head down">▼ Biggest losers</div><ul class="mv-list">${list(tm.losers) || '<li class="mv-empty">—</li>'}</ul></div>
    </div>`;
  }

  function upcomingHTML(upc) {
    if (!upc || !upc.length) return '<li class="upc-empty">No major scheduled events found.</li>';
    return upc.map((e) => {
      const fp = e.forecast ? `f/c ${esc(e.forecast)}${e.previous ? ` · prev ${esc(e.previous)}` : ""}`
        : (e.previous ? `prev ${esc(e.previous)}` : "");
      return `<li class="upc-item">
        <span class="upc-when">${esc(e.date)}${e.time ? ` · ${esc(e.time)}` : ""}</span>
        <span class="upc-title">${esc(e.title)}</span>
        <span class="upc-impact ${esc((e.impact || "").toLowerCase())}">${esc(e.impact)}</span>
        ${fp ? `<span class="upc-fp">${fp}</span>` : ""}
      </li>`;
    }).join("");
  }

  function columnHTML(key, m) {
    const isAsx = key === "asx";
    const summaryTitle = isAsx ? "What happened (last ASX session)" : "What happened overnight (US session)";
    const rotation = (m.rotation || "—") + (m.rotation_detail ? ` <span class="rot-detail">${esc(m.rotation_detail)}</span>` : "");
    return `
      <div class="col-head"><span class="col-flag">${isAsx ? "🇦🇺" : "🇺🇸"}</span><h3>${esc(m.label || (isAsx ? "ASX" : "US"))}</h3></div>

      <div class="sec-box overnight">
        <div class="sec-box-title">${summaryTitle}</div>
        <p class="sec-box-text">${esc(m.summary) || "—"}</p>
      </div>

      <div class="sec-box rotation">
        <div class="sec-box-title">Money rotation — which stocks moved</div>
        <p class="sec-box-text">${rotation}</p>
      </div>

      <div class="sec-box eli5">
        <div class="sec-box-title">🧒 Explain like I'm 5</div>
        <p class="sec-box-text">${esc(m.eli5) || "—"}</p>
      </div>

      <div class="sec-sub-title">Biggest winners &amp; losers</div>
      ${moversHTML(m.top_movers)}

      <div class="sec-sub-title">Indices</div>
      ${indicesHTML(m.indices)}

      <div class="sec-sub-title">Sectors</div>
      ${tableHTML(m.sectors)}

      <div class="sec-sub-title">📅 Major upcoming events</div>
      <div class="sec-upcoming"><ul class="upc-list">${upcomingHTML(m.upcoming)}</ul></div>

      <div class="sec-sub-title">Economic calendar</div>
      <div class="tv-host" id="tv-calendar-${key}"></div>
      <div class="sec-sub-title">Market news</div>
      <div class="tv-host" id="tv-news-${key}"></div>`;
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

  function mountWidgets(key) {
    const theme = dark() ? "dark" : "light";
    const country = key === "asx" ? "au" : "us";
    const newsSym = key === "asx" ? "ASX:XJO" : "SP:SPX";
    mountWidget(`tv-calendar-${key}`, "https://s3.tradingview.com/external-embedding/embed-widget-events.js", {
      colorTheme: theme, isTransparent: true, locale: "en",
      countryFilter: country, importanceFilter: "0,1", width: "100%", height: "100%",
    });
    mountWidget(`tv-news-${key}`, "https://s3.tradingview.com/external-embedding/embed-widget-timeline.js", {
      feedMode: "symbol", symbol: newsSym, isTransparent: true, displayMode: "regular",
      colorTheme: theme, locale: "en", width: "100%", height: "100%",
    });
  }

  function render(data) {
    ["asx", "us"].forEach((key) => {
      const m = (data.markets && data.markets[key]) || {};
      document.getElementById(`col-${key}`).innerHTML = columnHTML(key, m);
    });
    ["asx", "us"].forEach(mountWidgets);
  }

  fetch("data/sectors.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      try {
        const dt = new Date(d.generated_at);
        document.getElementById("sec-sub").textContent =
          `Read updated ${dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}, ${dt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} ${d.tz_label || ""} · calendar & news are live`;
      } catch (_) {}
      render(d);
    })
    .catch(() => {
      document.getElementById("sec-sub").textContent = "No sector data yet — calendar & news still load below.";
      render({ markets: { asx: {}, us: {} } });
    });
})();

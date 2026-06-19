/* Markets & Sectors — single page, ASX (left) + US (right) side by side.
   Renders public/data/sectors.json with sector explanations, biggest movers &
   volume, a live "next market-moving event" countdown and a data-derived
   hawkish/dovish read on the latest high-impact print. */
(() => {
  "use strict";
  const dark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

  // What each sector is, in plain words, with a few example tickers.
  const SECTOR_INFO = {
    // ASX
    XMJ: ["Miners & resources", "BHP, RIO, FMG"],
    XEJ: ["Oil, gas & uranium", "WDS, STO, PDN"],
    XFJ: ["Banks & insurers", "CBA, NAB, MQG"],
    XHJ: ["Healthcare & biotech", "CSL, COH, RMD"],
    XDJ: ["Discretionary retail", "WES, JBH, ALL"],
    XSJ: ["Food & staples", "WOW, COL, TWE"],
    XIJ: ["Technology", "WTC, XRO, TNE"],
    XUJ: ["Power & gas utilities", "ORG, AGL, APA"],
    XNJ: ["Industrials & transport", "TCL, BXB, QAN"],
    XTJ: ["Telcos & media", "TLS, TPG, CAR"],
    XPJ: ["A-REITs (property trusts)", "GMG, SCG, SGP"],
    XGD: ["Gold miners", "NST, EVN, NEM"],
    // US
    XLK: ["Tech & semiconductors", "AAPL, MSFT, NVDA"],
    XLF: ["Banks & financials", "JPM, BAC, BRK.B"],
    XLE: ["Oil & gas", "XOM, CVX, COP"],
    XLV: ["Healthcare & pharma", "LLY, UNH, JNJ"],
    XLI: ["Industrials & defense", "GE, CAT, BA"],
    XLY: ["Discretionary", "AMZN, TSLA, HD"],
    XLP: ["Consumer staples", "PG, KO, COST"],
    XLU: ["Utilities", "NEE, SO, DUK"],
    XLB: ["Materials & chemicals", "LIN, SHW, FCX"],
    XLRE: ["Real estate (REITs)", "PLD, AMT, EQIX"],
    XLC: ["Comms & media", "META, GOOGL, NFLX"],
  };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const fmtNum = (v) => v == null ? "—"
    : v.toLocaleString(undefined, { minimumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2, maximumFractionDigits: Math.abs(v) >= 1000 ? 1 : 2 });
  const fmtPct = (v) => v == null ? "" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const cls = (v) => (v >= 0 ? "sec-up" : "sec-down");
  const fmtMoney = (v) => {
    if (v == null) return "—";
    if (v >= 1e9) return "$" + (v / 1e9).toFixed(2) + "b";
    if (v >= 1e6) return "$" + (v / 1e6).toFixed(1) + "m";
    if (v >= 1e3) return "$" + (v / 1e3).toFixed(0) + "k";
    return "$" + Math.round(v);
  };

  // ---- macro: next market-moving event + latest result --------------------
  function nextEvent(m) {
    const up = (m.upcoming || []).filter((e) => e.when);
    const highs = up.filter((e) => e.impact === "High");
    return (highs[0] || up[0] || null);
  }

  function macroCardHTML(key, m) {
    const ev = nextEvent(m);
    const latest = m.latest_event;
    let html = "";
    if (ev) {
      const exp = ev.forecast ? `Market expects <b>${esc(ev.forecast)}</b>${ev.previous ? ` · prev ${esc(ev.previous)}` : ""}`
        : (ev.previous ? `Previous ${esc(ev.previous)}` : "High-impact event");
      html += `<div class="macro-card next">
        <div class="macro-label">⏳ Next market-moving event</div>
        <div class="macro-title">${esc(ev.title)}</div>
        <div class="macro-when">${esc(ev.date)}${ev.time ? ` · ${esc(ev.time)} AEST` : ""}</div>
        <div class="macro-countdown" data-countdown="${esc(ev.when)}">—</div>
        <div class="macro-exp">${exp}</div>
      </div>`;
    }
    if (latest && latest.tone) {
      const toneTxt = latest.tone === "hawkish" ? "🦅 Hawkish-leaning"
        : latest.tone === "dovish" ? "🕊️ Dovish-leaning" : "➖ In line";
      html += `<div class="macro-card result tone-${esc(latest.tone)}">
        <div class="macro-label">Latest result · ${esc(latest.when_lbl || "")}</div>
        <div class="macro-title">${esc(latest.title)}</div>
        <div class="macro-result-row">
          <span class="macro-actual">Actual <b>${esc(latest.actual)}</b></span>
          <span class="macro-vs">vs f/c ${esc(latest.forecast || "—")}</span>
          ${latest.previous ? `<span class="macro-vs">prev ${esc(latest.previous)}</span>` : ""}
        </div>
        <div class="macro-tone tone-${esc(latest.tone)}">${toneTxt} — came in ${esc(latest.surprise || "")}.</div>
        <div class="macro-note">Auto-read from the print (actual vs forecast) — not market sentiment.</div>
      </div>`;
    }
    return html;
  }

  // ---- sectors (with plain-English meaning + example tickers) --------------
  function sectorsHTML(list) {
    const sorted = (list || []).slice().sort((a, b) => b.chg_pct - a.chg_pct);
    const maxAbs = Math.max(0.5, ...sorted.map((s) => Math.abs(s.chg_pct)));
    return `<div class="sec-srows">` + sorted.map((s) => {
      const info = SECTOR_INFO[s.symbol];
      const desc = info ? `${info[0]} — e.g. ${info[1]}` : esc(s.name);
      const w = Math.abs(s.chg_pct) / maxAbs * 100;
      const color = s.chg_pct >= 0 ? "var(--green)" : "var(--red)";
      return `<div class="sec-srow">
        <div class="sec-sleft">
          <div class="sec-sname"><b>${esc(s.symbol)}</b> ${esc(s.name)}</div>
          <div class="sec-sdesc">${esc(desc)}</div>
        </div>
        <div class="sec-sright">
          <div class="sec-spct ${cls(s.chg_pct)}">${fmtPct(s.chg_pct)}</div>
          <div class="sec-sbar"><i style="width:${w}%;background:${color}"></i></div>
        </div>
      </div>`;
    }).join("") + `</div>`;
  }

  // ---- winners / losers ---------------------------------------------------
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

  // ---- biggest volume (most $ traded + how unusual) -----------------------
  function volumeHTML(tv) {
    if (!tv || !tv.length) return "";
    const rows = tv.map((m) => `
      <li class="mv-item vol">
        <span class="mv-sym">${esc(m.symbol)}</span>
        <span class="mv-name">${esc(m.name)}${m.sector ? ` · ${esc(m.sector)}` : ""}</span>
        <span class="vol-turn">${fmtMoney(m.turnover)}</span>
        <span class="vol-spike ${m.spike >= 2 ? "hot" : ""}">${m.spike ? m.spike.toFixed(1) + "× avg" : ""}</span>
        <span class="mv-pct ${cls(m.pct)}">${fmtPct(m.pct)}</span>
      </li>`).join("");
    return `<div class="mv-col vol-col"><div class="mv-head vol">📊 Biggest volume (most traded today)</div><ul class="mv-list">${rows}</ul></div>`;
  }

  function indicesHTML(list) {
    return `<div class="sec-indices">` + (list || []).map((i) => `
      <div class="idx-card">
        <div class="idx-sym">${esc(i.name)} · ${esc(i.symbol)}</div>
        <div class="idx-last">${fmtNum(i.last)}</div>
        <div class="idx-chg ${cls(i.chg_pct)}">${fmtPct(i.chg_pct)}</div>
      </div>`).join("") + `</div>`;
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
    const rotation = (esc(m.rotation) || "—") + (m.rotation_detail ? ` <span class="rot-detail">${esc(m.rotation_detail)}</span>` : "");
    const newsBlock = isAsx ? "" : `
      <div class="sec-sub-title">📰 US market-moving news (Fed, macro, top stories)</div>
      <div class="tv-host" id="tv-news-${key}"></div>`;
    return `
      <div class="col-head"><span class="col-flag">${isAsx ? "🇦🇺" : "🇺🇸"}</span><h3>${esc(m.label || (isAsx ? "ASX" : "US"))}</h3></div>

      ${macroCardHTML(key, m)}

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

      <div class="sec-sub-title">Biggest volume</div>
      ${volumeHTML(m.top_volume) || '<p class="sec-muted">No volume data yet.</p>'}

      <div class="sec-sub-title">Indices</div>
      ${indicesHTML(m.indices)}

      <div class="sec-sub-title">Sectors — what each one is</div>
      ${sectorsHTML(m.sectors)}

      <div class="sec-sub-title">📅 Major upcoming events</div>
      <div class="sec-upcoming"><ul class="upc-list">${upcomingHTML(m.upcoming)}</ul></div>

      <div class="sec-sub-title">Economic calendar</div>
      <div class="tv-host" id="tv-calendar-${key}"></div>
      ${newsBlock}`;
  }

  function mountWidget(hostId, src, config) {
    const host = document.getElementById(hostId);
    if (!host) return;
    host.innerHTML = '<div class="tradingview-widget-container" style="height:100%;width:100%">'
      + '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div></div>';
    const s = document.createElement("script");
    s.type = "text/javascript"; s.async = true; s.src = src;
    s.textContent = JSON.stringify(config);
    host.firstChild.appendChild(s);
  }

  function mountWidgets(key) {
    const theme = dark() ? "dark" : "light";
    const country = key === "asx" ? "au" : "us";
    mountWidget(`tv-calendar-${key}`, "https://s3.tradingview.com/external-embedding/embed-widget-events.js", {
      colorTheme: theme, isTransparent: true, locale: "en",
      countryFilter: country, importanceFilter: "0,1", width: "100%", height: "100%",
    });
    // US only: broad top-stories feed (Fed / macro / market-sensitive), not single-symbol.
    if (key === "us") {
      mountWidget("tv-news-us", "https://s3.tradingview.com/external-embedding/embed-widget-timeline.js", {
        feedMode: "all_symbols", isTransparent: true, displayMode: "regular",
        colorTheme: theme, locale: "en", width: "100%", height: "100%",
      });
    }
  }

  // ---- live countdown ticker ---------------------------------------------
  function tickCountdowns() {
    const now = Date.now();
    document.querySelectorAll("[data-countdown]").forEach((el) => {
      const t = Date.parse(el.getAttribute("data-countdown"));
      if (isNaN(t)) { el.textContent = ""; return; }
      let s = Math.floor((t - now) / 1000);
      if (s <= 0) { el.textContent = "Happening now / awaiting result"; el.classList.add("live"); return; }
      const d = Math.floor(s / 86400); s -= d * 86400;
      const h = Math.floor(s / 3600); s -= h * 3600;
      const m = Math.floor(s / 60); s -= m * 60;
      const parts = [];
      if (d) parts.push(d + "d");
      if (h || d) parts.push(h + "h");
      parts.push(m + "m");
      if (!d) parts.push(s + "s");
      el.textContent = "in " + parts.join(" ");
    });
  }

  function render(data) {
    ["asx", "us"].forEach((key) => {
      const m = (data.markets && data.markets[key]) || {};
      document.getElementById(`col-${key}`).innerHTML = columnHTML(key, m);
    });
    ["asx", "us"].forEach(mountWidgets);
    tickCountdowns();
    clearInterval(window._cdTimer);
    window._cdTimer = setInterval(tickCountdowns, 1000);
  }

  fetch("data/sectors.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      try {
        const dt = new Date(d.generated_at);
        document.getElementById("sec-sub").textContent =
          `Read updated ${dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}, ${dt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} ${d.tz_label || ""} · calendar, news & countdown are live`;
      } catch (_) {}
      render(d);
    })
    .catch(() => {
      document.getElementById("sec-sub").textContent = "No sector data yet — calendar & news still load below.";
      render({ markets: { asx: {}, us: {} } });
    });
})();

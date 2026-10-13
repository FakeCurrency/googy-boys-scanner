/* ALERTS page — the multi-lens alignment log, the durable record of every
   alignment (push delivery was removed 2026-08-27, so this page is the only
   place they show). Reads public/data/phasemap/alert_history.json.
   2026-07-10: market filter + collapsible day groups (the log grew fast —
   ~27 alignments/day — so only the newest day starts expanded). */
(() => {
  "use strict";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // One timestamp convention: Melbourne on screen, UTC in the tooltip.
  const melbFmtD = new Intl.DateTimeFormat("en-CA", { timeZone: "Australia/Melbourne",
    year: "numeric", month: "2-digit", day: "2-digit" });
  const melbFmtT = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne",
    hour: "numeric", minute: "2-digit" });
  const melbDay = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso).slice(0, 10) : melbFmtD.format(d); };
  const melbClock = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : melbFmtT.format(d); };
  const melbTime = (iso) => { const c = melbClock(iso); return c ? c + " Melb" : ""; };
  // #88: relative time on screen (the daily glance), full Melbourne + UTC in
  // the tooltip. The row also prints the Melbourne clock time beside it
  // ("5h · 4:46 pm"), since a phone has no hover; the day group's heading
  // carries the date. Compact on purpose ("now", "12m", "5h", "3d" -- no
  // "ago"): at 360px a 5-letter NASDAQ row's second line has no room for
  // "23h ago · 12:59 pm", and the time would drop onto a third line.
  const relTime = (iso) => {
    const t = Date.parse(iso || ""); if (!isFinite(t)) return "";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "now";
    const m = s / 60; if (m < 60) return Math.round(m) + "m";
    const h = m / 60; if (h < 24) return Math.round(h) + "h";
    return Math.floor(h / 24) + "d";
  };

  const state = { entries: [], market: "all", q: "", triplesOnly: false, failed: false };

  // "Since you last looked": entries newer than the previous visit get a NEW
  // dot. The watermark advances once per page load, not per render.
  const SEEN_KEY = "gbs:alerts-seen";
  let lastSeen = 0;
  try { lastSeen = +(localStorage.getItem(SEEN_KEY) || 0); } catch (_) {}
  const isNew = (e) => { const t = Date.parse(e.date || ""); return isFinite(t) && t > lastSeen; };

  function rowHTML(e) {
    const triple = e.count >= 3;
    const arrow = e.side === "short" ? "▼" : "▲";
    const dir = e.side === "short" ? "&dir=bearish" : "&dir=bullish";
    return `<a class="al-row${triple ? " al-row-triple" : ""}${isNew(e) ? " al-row-new" : ""}" ` +
      `href="chart.html?m=${esc(e.market)}&s=${encodeURIComponent(e.ticker)}&src=alerts${dir}">` +
      `${isNew(e) ? '<span class="al-new-dot" title="New since your last visit"></span>' : ""}` +
      `<span class="pm-conf${triple ? " pm-conf-3" : ""}">${triple ? "🎯 " : "⨂ "}${e.count}-LENS</span>` +
      `<span class="pm-ticker">${esc(e.ticker)}</span>` +
      `<span class="pm-dir ${e.side === "short" ? "pm-dir-short" : "pm-dir-long"}">${arrow} ${esc(String(e.side).toUpperCase())}</span>` +
      `<span class="pm-sector">${esc(String(e.market).toUpperCase())}</span>` +
      `<span class="al-lenses">${(e.lenses || []).map(esc).join(" + ")}</span>` +
      `<span class="al-time" title="${esc(melbTime(e.date))} · UTC ${esc(String(e.date).slice(11, 16))}">` +
        `${esc([relTime(e.date), melbClock(e.date)].filter(Boolean).join(" · "))}</span>` +
      `</a>`;
  }

  function render() {
    const list = document.getElementById("al-list");
    const sub = document.getElementById("al-sub");
    if (state.failed) {
      // A failed load is not an empty log: say so, and offer a retry (a filter
      // tap must not repaint it as "No alignments logged yet").
      sub.textContent = "Couldn't load the alert history (connection problem).";
      list.innerHTML = '<div class="pm-empty"><button type="button" class="pm-chip" ' +
        'id="al-retry">Tap to retry</button></div>';
      const retry = document.getElementById("al-retry");
      if (retry) retry.addEventListener("click", () => location.reload());
      return;
    }
    const q = state.q.trim().toUpperCase();
    const rows = state.entries.filter((e) =>
      (state.market === "all" || e.market === state.market) &&
      (!state.triplesOnly || e.count >= 3) &&
      (!q || String(e.ticker || "").toUpperCase().includes(q)));
    if (!rows.length) {
      sub.textContent = state.entries.length
        ? "No alignments match the current filters."
        : "No alignments logged yet — the log fills as the scans run.";
      list.innerHTML = "";
      return;
    }
    sub.textContent = `${rows.length} alignment event(s)` +
      (state.market === "all" ? "" : ` · ${state.market.toUpperCase()}`) + " · newest first";
    const byDay = {};
    rows.forEach((e) => {
      const day = melbDay(e.date || "");
      (byDay[day] = byDay[day] || []).push(e);
    });
    list.innerHTML = Object.keys(byDay).sort().reverse().map((day, i) => {
      const dayRows = byDay[day];
      const triples = dayRows.filter((e) => e.count >= 3).length;
      return `<details class="al-day-group"${i === 0 ? " open" : ""}>
        <summary class="al-day-summary">
          <span class="al-day-date">${esc(day)}</span>
          <span class="al-day-count">${dayRows.length} alignment${dayRows.length === 1 ? "" : "s"}${triples ? ` · 🎯 ${triples} triple${triples === 1 ? "" : "s"}` : ""}</span>
          <span class="al-day-chev" aria-hidden="true">▾</span>
        </summary>
        <div class="al-day">${dayRows.map(rowHTML).join("")}</div>
      </details>`;
    }).join("");
  }

  document.querySelectorAll("#al-market .pm-chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      document.querySelectorAll("#al-market .pm-chip").forEach((c) =>
        c.classList.toggle("is-active", c === chip));
      state.market = chip.dataset.market;
      render();
    }));

  const triplesChip = document.getElementById("al-triples");
  if (triplesChip) triplesChip.addEventListener("click", () => {
    state.triplesOnly = !state.triplesOnly;
    triplesChip.classList.toggle("is-active", state.triplesOnly);
    render();
  });
  const search = document.getElementById("al-search");
  if (search) search.addEventListener("input", () => { state.q = search.value || ""; render(); });

  fetch("data/phasemap/alert_history.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((j) => {
      state.entries = (j && j.entries) || [];
      render();
      // Advance the seen-watermark AFTER the first render so the NEW dots show
      // this visit and clear on the next one.
      try { localStorage.setItem(SEEN_KEY, String(Date.now())); } catch (_) {}
    })
    .catch(() => {
      state.failed = true;
      render();
    });

  // ── Fix-10 #2: YOUR price-alert lines, managed here ───────────────────────
  // Every ⏰ one-shot alert set with the chart's 🔔 tool (gbs:palerts:*), in
  // one place: level, direction it's waiting on, when it was set, one-tap
  // remove, and a link to the chart it lives on. Fires happen on the chart
  // page (live tick) and the dashboard (every scan) — this is the ledger.
  function paEsc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function paFmt(v) {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    return a >= 100 ? (+v).toFixed(2) : a >= 1 ? (+v).toFixed(3) : a >= 0.01 ? (+v).toFixed(4) : (+v).toFixed(6);
  }
  function renderPriceAlerts() {
    let host = document.getElementById("pa-manager");
    if (!host) {
      host = document.createElement("section");
      host.id = "pa-manager";
      host.className = "pa-manager";
      const anchor = document.querySelector(".pm-filters");
      if (!anchor || !anchor.parentNode) return;
      anchor.parentNode.insertBefore(host, anchor);
      host.addEventListener("click", (e) => {
        const del = e.target.closest("[data-pa-del]");
        if (!del) return;
        const [key, idx] = del.getAttribute("data-pa-del").split("|");
        try {
          const list = JSON.parse(localStorage.getItem(key) || "[]") || [];
          list.splice(+idx, 1);
          if (list.length) localStorage.setItem(key, JSON.stringify(list));
          else localStorage.removeItem(key);
        } catch (_) {}
        renderPriceAlerts();
      });
    }
    const rows = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k || k.indexOf("gbs:palerts:") !== 0) continue;
        const parts = k.split(":");
        const market = parts[2] || "", sym = parts[3] || "";
        let list = [];
        try { list = JSON.parse(localStorage.getItem(k) || "[]") || []; } catch (_) { continue; }
        list.forEach((a, idx) => rows.push({ k, idx, market, sym, a }));
      }
    } catch (_) {}
    if (!rows.length) { host.hidden = true; return; }
    rows.sort((x, y) => x.market.localeCompare(y.market) || x.sym.localeCompare(y.sym) || x.a.p - y.a.p);
    const MKT = { asx: "ASX", nasdaq: "NASDAQ", crypto: "CRYPTO", scalp: "SCALP" };
    const ago = (t) => {
      if (!t) return "";
      const m = Math.max(0, Math.round((Date.now() - t) / 60000));
      return m < 60 ? `${m}m ago` : m < 2880 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
    };
    host.hidden = false;
    host.innerHTML =
      `<div class="pa-mg-hd">⏰ Your price-alert lines <b>${rows.length}</b>` +
      `<span class="pa-mg-sub">set with the 🔔 tool on any chart · one-shot — they fire on the chart and on every scan, then clear</span></div>` +
      `<div class="pa-mg-rows">` +
      rows.map((r) => {
        const waitUp = r.a.ref != null && r.a.ref < r.a.p;
        return `<div class="pa-mg-row">` +
          `<a class="pa-mg-sym" href="chart.html?m=${paEsc(r.market)}&s=${encodeURIComponent(r.sym)}&mode=vivek" title="Open the chart">${paEsc(r.sym)}</a>` +
          `<span class="pa-mg-mkt">${MKT[r.market] || paEsc(r.market.toUpperCase())}</span>` +
          `<span class="pa-mg-px">${waitUp ? "▲ crosses above" : "▼ crosses below"} <b>${paFmt(r.a.p)}</b></span>` +
          `<span class="pa-mg-ago">${ago(r.a.t)}</span>` +
          `<button class="pa-mg-del" type="button" data-pa-del="${paEsc(r.k)}|${r.idx}" title="Remove this alert" aria-label="Remove alert">✕</button>` +
        `</div>`;
      }).join("") + `</div>`;
  }
  renderPriceAlerts();
  window.addEventListener("storage", (e) => { if (e.key && e.key.indexOf("gbs:palerts:") === 0) renderPriceAlerts(); });
})();

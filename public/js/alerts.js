/* ALERTS page — the multi-lens alignment log (Discord pings scroll away;
   this page doesn't). Reads public/data/phasemap/alert_history.json.
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
  const melbTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : melbFmtT.format(d) + " Melb"; };

  const state = { entries: [], market: "all" };

  function rowHTML(e) {
    const triple = e.count >= 3;
    const arrow = e.side === "short" ? "▼" : "▲";
    const dir = e.side === "short" ? "&dir=bearish" : "&dir=bullish";
    return `<a class="al-row${triple ? " al-row-triple" : ""}" ` +
      `href="chart.html?m=${esc(e.market)}&s=${encodeURIComponent(e.ticker)}&pm=1${dir}">` +
      `<span class="pm-conf${triple ? " pm-conf-3" : ""}">${triple ? "🎯 " : "⨂ "}${e.count}-LENS</span>` +
      `<span class="pm-ticker">${esc(e.ticker)}</span>` +
      `<span class="pm-dir ${e.side === "short" ? "pm-dir-short" : "pm-dir-long"}">${arrow} ${esc(String(e.side).toUpperCase())}</span>` +
      `<span class="pm-sector">${esc(String(e.market).toUpperCase())}</span>` +
      `<span class="al-lenses">${(e.lenses || []).map(esc).join(" + ")}</span>` +
      `<span class="al-time" title="UTC ${esc(String(e.date).slice(11, 16))}">${esc(melbTime(e.date))}</span>` +
      `</a>`;
  }

  function render() {
    const list = document.getElementById("al-list");
    const sub = document.getElementById("al-sub");
    const rows = state.market === "all"
      ? state.entries
      : state.entries.filter((e) => e.market === state.market);
    if (!rows.length) {
      sub.textContent = state.entries.length
        ? `No ${state.market.toUpperCase()} alignments on record.`
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

  fetch("data/phasemap/alert_history.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      state.entries = (j && j.entries) || [];
      render();
    })
    .catch(() => {
      document.getElementById("al-sub").textContent = "Alert history unavailable.";
    });
})();

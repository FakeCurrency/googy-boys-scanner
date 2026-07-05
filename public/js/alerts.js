/* ALERTS page — the multi-lens alignment log (Discord pings scroll away;
   this page doesn't). Reads public/data/phasemap/alert_history.json. */
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

  fetch("data/phasemap/alert_history.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then((j) => {
      const entries = (j && j.entries) || [];
      const sub = document.getElementById("al-sub");
      const list = document.getElementById("al-list");
      if (!entries.length) {
        sub.textContent = "No alignments logged yet — the log fills as the scans run.";
        return;
      }
      sub.textContent = `${entries.length} alignment event(s) on record · newest first`;
      const byDay = {};
      entries.forEach((e) => {
        const day = melbDay(e.date || "");
        (byDay[day] = byDay[day] || []).push(e);
      });
      list.innerHTML = Object.keys(byDay).sort().reverse().map((day) => {
        const rows = byDay[day].map((e) => {
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
        }).join("");
        return `<section class="pm-lg-section"><h3>${esc(day)}</h3><div class="al-day">${rows}</div></section>`;
      }).join("");
    })
    .catch(() => {
      document.getElementById("al-sub").textContent = "Alert history unavailable.";
    });
})();

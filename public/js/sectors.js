/* Markets & Sectors page — renders public/data/sectors.json (ASX / US). */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  let DATA = null, market = "asx";

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
      const w = Math.abs(s.chg_pct) / maxAbs * 50;   // up to 50% (half the bar)
      const color = s.chg_pct >= 0 ? "var(--green)" : "var(--red)";
      const side = s.chg_pct >= 0 ? "left:50%" : `right:50%`;
      const bar = `<span class="sec-bar"><i style="${side};width:${w}%;background:${color}"></i></span>`;
      return `<tr>
        <td class="sec-sym">${s.symbol}</td>
        <td class="sec-name">${s.name}</td>
        <td>${fmtNum(s.last)}</td>
        <td class="${cls(s.chg)}">${fmtChg(s.chg)}</td>
        <td class="${cls(s.chg_pct)}">${fmtPct(s.chg_pct)}${bar}</td>
      </tr>`;
    }).join("");
    $("#sec-table").innerHTML = `<table class="sec-table"><thead><tr>
      <th>Symbol</th><th>Sector</th><th>Last</th><th>Chg</th><th>Chg%</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function render() {
    const m = DATA.markets[market];
    renderIndices(m.indices || []);
    renderTable((m.sectors || []).slice().sort((a, b) => b.chg_pct - a.chg_pct));
    $("#sec-summary").textContent = m.summary || "—";
    $("#sec-rotation").textContent = m.rotation || "—";
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
        $("#sec-sub").textContent = `Updated ${dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}, ${dt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} ${d.tz_label || ""}`;
      } catch (_) {}
      render();
    })
    .catch(() => { $("#sec-sub").textContent = "No sector data yet — run a scan to generate it."; });
})();

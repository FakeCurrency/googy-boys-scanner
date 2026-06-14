/* Journal / track-record page — renders public/data/journal.json */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const GRADE_CLS = { "A+": "g-aplus", "A": "g-a", "B": "g-b", "C": "g-c" };

  const rcls = (r) => (r >= 0 ? "r-pos" : "r-neg");
  const rfmt = (r) => (r == null ? "—" : (r >= 0 ? "+" : "") + r.toFixed(2) + "R");
  const num = (v) => (v == null || isNaN(v) ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 4 }));

  function statCard(label, value, cls) {
    return `<div class="stat-card"><div class="stat-label">${label}</div>
      <div class="stat-value ${cls || ""}">${value}</div></div>`;
  }

  function renderStats(s) {
    $("#jr-stats").innerHTML = [
      statCard("Open", s.open),
      statCard("Closed", s.closed),
      statCard("Win rate", `${s.win_rate}%`),
      statCard("Realised", `${s.total_r >= 0 ? "+" : ""}${s.total_r}R`, s.total_r >= 0 ? "accent-green" : ""),
    ].join("");
  }

  function equity(closed) {
    const el = $("#jr-equity-chart");
    if (!closed.length) { el.innerHTML = `<div class="jr-empty">No closed trades yet — the curve appears as positions resolve.</div>`; return; }
    let cum = 0;
    const pts = closed.map((c) => (cum += c.r));
    pts.unshift(0);
    const w = 1000, h = 180, pad = 8;
    const min = Math.min(0, ...pts), max = Math.max(0, ...pts), rng = (max - min) || 1;
    const x = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
    const y = (v) => h - pad - ((v - min) / rng) * (h - 2 * pad);
    const path = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const zero = y(0).toFixed(1);
    const end = pts[pts.length - 1];
    const color = end >= 0 ? "#2fd07f" : "#ff5b5b";
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="0" y1="${zero}" x2="${w}" y2="${zero}" stroke="#1b2333" stroke-width="1"/>
      <polyline points="${path}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg>`;
  }

  function openTable(open) {
    if (!open.length) return `<div class="jr-empty">No open positions.</div>`;
    const rows = open.map((p) => `<tr>
      <td class="jr-sym">${p.symbol}</td>
      <td><span class="jr-grade ${GRADE_CLS[p.grade]}">${p.grade}</span></td>
      <td>${num(p.entry)}</td><td>${num(p.stop)}</td><td>${num(p.target)}</td>
      <td>${num(p.current)}</td>
      <td class="${rcls(p.unreal_r || 0)}">${rfmt(p.unreal_r)}</td>
      <td>${p.opened}</td></tr>`).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Grade</th><th>Entry</th><th>Stop</th><th>Target</th><th>Current</th><th>Unreal.</th><th>Opened</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function closedTable(closed) {
    if (!closed.length) return `<div class="jr-empty">No closed trades yet.</div>`;
    const rows = closed.slice().reverse().map((c) => `<tr>
      <td class="jr-sym">${c.symbol}</td>
      <td><span class="jr-grade ${GRADE_CLS[c.grade]}">${c.grade}</span></td>
      <td>${num(c.entry)}</td><td>${num(c.exit)}</td>
      <td><span class="reason">${c.reason}</span></td>
      <td class="${rcls(c.r)}">${rfmt(c.r)}</td>
      <td>${c.opened} → ${c.exit_date}</td></tr>`).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Grade</th><th>Entry</th><th>Exit</th><th>Exit on</th><th>Result</th><th>Held</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  }

  fetch("data/journal.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      renderStats(d.stats || {});
      equity(d.closed || []);
      $("#jr-open-n").textContent = `(${(d.open || []).length})`;
      $("#jr-closed-n").textContent = `(${(d.closed || []).length})`;
      $("#jr-open").innerHTML = openTable(d.open || []);
      $("#jr-closed").innerHTML = closedTable(d.closed || []);
    })
    .catch(() => {
      $("#jr-stats").innerHTML = `<div class="jr-empty" style="grid-column:1/-1">No journal yet. Run <code>python -m scanner.journal</code> (or Refresh Data) to start the forward test.</div>`;
    });
})();

/* Journal — Journal 1 (LONGS) + Journal 2 (SHORTS) */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const GRADE_CLS = { "A+": "g-aplus", "A": "g-a", "B": "g-b", "C": "g-c" };

  const rcls  = (r) => (r >= 0 ? "r-pos" : "r-neg");
  const rfmt  = (r) => (r == null ? "—" : (r >= 0 ? "+" : "") + r.toFixed(2) + "R");
  const pfmt  = (v) => (v == null || isNaN(v) ? "—" : (v >= 0 ? "+" : "-") + "$" + Math.abs(v).toFixed(2));
  const pcls  = (v) => (v >= 0 ? "r-pos" : "r-neg");
  const num   = (v) => (v == null || isNaN(v) ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 4 }));

  function statCard(label, value, cls) {
    return `<div class="stat-card"><div class="stat-label">${label}</div>
      <div class="stat-value ${cls || ""}">${value}</div></div>`;
  }

  function renderStats(s, prefix) {
    const kelly = s.kelly_pct != null
      ? statCard("½-Kelly size", `${s.kelly_pct}% of acct`, s.kelly_pct > 0 ? "accent-green" : "")
      : statCard("½-Kelly size", "Need 20+ trades", "");
    $(`#jr-${prefix}-stats`).innerHTML = [
      statCard("Open",         s.open),
      statCard("Closed",       s.closed),
      statCard("Win rate",     `${s.win_rate}%`),
      statCard("Realised R",   `${s.total_r >= 0 ? "+" : ""}${s.total_r}R`,
               s.total_r >= 0 ? "accent-green" : ""),
      s.total_pnl != null
        ? statCard("Realised $", pfmt(s.total_pnl), pcls(s.total_pnl)) : "",
      s.open_unrealised_pnl != null
        ? statCard("Unrealised $", pfmt(s.open_unrealised_pnl), pcls(s.open_unrealised_pnl)) : "",
      kelly,
    ].join("");
  }

  function equity(closed, elId) {
    const el = $(`#${elId}`);
    if (!closed.length) {
      el.innerHTML = `<div class="jr-empty">No closed trades yet — the curve appears as positions resolve.</div>`;
      return;
    }
    let cum = 0;
    const pts = closed.map((c) => (cum += c.r));
    pts.unshift(0);
    const w = 1000, h = 180, pad = 8;
    const min = Math.min(0, ...pts), max = Math.max(0, ...pts), rng = (max - min) || 1;
    const x = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
    const y = (v) => h - pad - ((v - min) / rng) * (h - 2 * pad);
    const path = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const zero  = y(0).toFixed(1);
    const color = pts[pts.length - 1] >= 0 ? "#2fd07f" : "#ff5b5b";
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="0" y1="${zero}" x2="${w}" y2="${zero}" stroke="#1b2333" stroke-width="1"/>
      <polyline points="${path}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg>`;
  }

  function openTable(open) {
    if (!open.length) return `<div class="jr-empty">No open positions.</div>`;
    const rows = open.map((p) => `<tr>
      <td class="jr-sym">${p.symbol}</td>
      <td><span class="jr-grade ${GRADE_CLS[p.grade] || ""}">${p.grade}</span></td>
      <td>${num(p.entry)}</td>
      <td>${num(p.stop)}</td>
      <td>${num(p.target)}</td>
      <td>${num(p.current)}</td>
      <td>${p.shares != null ? p.shares + " sh" : "—"}</td>
      <td class="${rcls(p.unreal_r || 0)}">${rfmt(p.unreal_r)}</td>
      <td class="${pcls(p.unreal_pnl || 0)}">${pfmt(p.unreal_pnl)}</td>
      <td>${p.opened}</td>
    </tr>`).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Grade</th><th>Entry</th><th>Stop</th><th>Target</th>
      <th>Current</th><th>Size</th><th>Unreal. R</th><th>Unreal. $</th><th>Opened</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function closedTable(closed) {
    if (!closed.length) return `<div class="jr-empty">No closed trades yet.</div>`;
    const rows = closed.slice().reverse().map((c) => `<tr>
      <td class="jr-sym">${c.symbol}</td>
      <td><span class="jr-grade ${GRADE_CLS[c.grade] || ""}">${c.grade}</span></td>
      <td>${num(c.entry)}</td>
      <td>${num(c.exit)}</td>
      <td>${c.shares != null ? c.shares + " sh" : "—"}</td>
      <td><span class="reason">${c.reason}</span></td>
      <td class="${rcls(c.r)}">${rfmt(c.r)}</td>
      <td class="${pcls(c.pnl || 0)}">${pfmt(c.pnl)}</td>
      <td>${c.opened} → ${c.exit_date}</td>
    </tr>`).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Grade</th><th>Entry</th><th>Exit</th>
      <th>Size</th><th>Exit on</th><th>Result R</th><th>P&amp;L $</th><th>Held</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  // Tab switching
  document.querySelectorAll(".jr-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".jr-tab").forEach((b) => {
        b.classList.remove("is-active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("is-active");
      btn.setAttribute("aria-selected", "true");
      const jrnl = btn.dataset.journal;
      $("#jr-long-section").classList.toggle("jr-hidden", jrnl !== "long");
      $("#jr-short-section").classList.toggle("jr-hidden", jrnl !== "short");
    });
  });

  fetch("data/journal.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      const stats = d.stats || {};
      const ol = d.open_longs    || [];
      const os = d.open_shorts   || [];
      const cl = d.closed_longs  || [];
      const cs = d.closed_shorts || [];

      // LONGS
      renderStats(stats.longs || {}, "long");
      equity(cl, "jr-long-equity");
      $("#jr-long-open-n").textContent   = `(${ol.length})`;
      $("#jr-long-closed-n").textContent = `(${cl.length})`;
      $("#jr-long-open").innerHTML   = openTable(ol);
      $("#jr-long-closed").innerHTML = closedTable(cl);

      // SHORTS
      renderStats(stats.shorts || {}, "short");
      equity(cs, "jr-short-equity");
      $("#jr-short-open-n").textContent   = `(${os.length})`;
      $("#jr-short-closed-n").textContent = `(${cs.length})`;
      $("#jr-short-open").innerHTML   = openTable(os);
      $("#jr-short-closed").innerHTML = closedTable(cs);
    })
    .catch(() => {
      $("#jr-long-stats").innerHTML = `<div class="jr-empty" style="grid-column:1/-1">
        No journal yet. Run <code>python -m scanner.journal</code> to start the forward test.</div>`;
    });
})();

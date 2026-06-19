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

  // ── Scalp helpers ──────────────────────────────────────────────────────────
  function fmtTs(ts) {
    if (!ts) return "—";
    const d = new Date(ts.endsWith("Z") ? ts : ts + "Z");
    return d.toLocaleString(undefined, { month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit", timeZone: "UTC" }) + " UTC";
  }

  function scalp_openTable(open) {
    if (!open.length) return `<div class="jr-empty">No open scalp positions.</div>`;
    const rows = open.map((p) => {
      const dirCls = p.direction === "long" ? "r-pos" : "r-neg";
      const assetBadge = p.asset_type ? `<span class="reason">${p.asset_type.toUpperCase()}</span>` : "";
      return `<tr>
        <td class="jr-sym">${p.symbol} ${assetBadge}</td>
        <td class="${dirCls}">${p.direction.toUpperCase()}</td>
        <td><span class="jr-grade ${GRADE_CLS[p.grade] || ""}">${p.grade}</span></td>
        <td>${num(p.entry)}</td>
        <td class="r-neg">${num(p.stop)}</td>
        <td class="r-pos">${num(p.target)}</td>
        <td>${num(p.current)}</td>
        <td>${p.units != null ? p.units + " u" : "—"}</td>
        <td class="${rcls(p.unreal_r || 0)}">${rfmt(p.unreal_r)}</td>
        <td class="${pcls(p.unreal_pnl || 0)}">${pfmt(p.unreal_pnl)}</td>
        <td class="muted">${fmtTs(p.opened_ts)}</td>
      </tr>`;
    }).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Dir</th><th>Grade</th><th>Entry</th><th>Stop</th><th>Target</th>
      <th>Current</th><th>Size</th><th>Unreal. R</th><th>Unreal. $</th><th>Opened</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function scalp_closedTable(closed) {
    if (!closed.length) return `<div class="jr-empty">No closed scalp trades yet.</div>`;
    const rows = closed.slice().reverse().map((c) => {
      const dirCls = c.direction === "long" ? "r-pos" : "r-neg";
      const dur    = c.bars != null ? `${c.bars}h` : "—";
      return `<tr>
        <td class="jr-sym">${c.symbol}</td>
        <td class="${dirCls}">${c.direction.toUpperCase()}</td>
        <td><span class="jr-grade ${GRADE_CLS[c.grade] || ""}">${c.grade}</span></td>
        <td>${num(c.entry)}</td>
        <td>${num(c.exit)}</td>
        <td>${c.units != null ? c.units + " u" : "—"}</td>
        <td><span class="reason">${c.reason}</span></td>
        <td class="${rcls(c.r)}">${rfmt(c.r)}</td>
        <td class="${pcls(c.pnl || 0)}">${pfmt(c.pnl)}</td>
        <td class="muted">${dur}</td>
        <td class="muted">${fmtTs(c.exit_ts)}</td>
      </tr>`;
    }).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Dir</th><th>Grade</th><th>Entry</th><th>Exit</th>
      <th>Size</th><th>Reason</th><th>R</th><th>P&amp;L $</th><th>Held</th><th>Closed</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function scalp_equity(allClosed, elId) {
    const el = $(`#${elId}`);
    if (!allClosed.length) {
      el.innerHTML = `<div class="jr-empty">No closed scalp trades yet — curve appears as trades resolve.</div>`;
      return;
    }
    let cum = 0;
    const pts = allClosed.map((c) => (cum += (c.pnl || 0)));
    pts.unshift(0);
    const w = 1000, h = 180, pad = 8;
    const min = Math.min(0, ...pts), max = Math.max(0, ...pts), rng = (max - min) || 1;
    const x = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
    const y = (v) => h - pad - ((v - min) / rng) * (h - 2 * pad);
    const path  = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const zero  = y(0).toFixed(1);
    const color = pts[pts.length - 1] >= 0 ? "#2fd07f" : "#ff5b5b";
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="0" y1="${zero}" x2="${w}" y2="${zero}" stroke="#1b2333" stroke-width="1"/>
      <polyline points="${path}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg>`;
  }

  function renderScalpStats(s) {
    const pnlCls = s.today_pnl >= 0 ? "accent-green" : "";
    const limCls = s.today_pnl <= -s.max_daily_loss ? "" : "accent-green";
    const sl  = s.longs  || {};
    const ss  = s.shorts || {};
    const all_closed = (sl.closed || 0) + (ss.closed || 0);
    const all_open   = (sl.open   || 0) + (ss.open   || 0);
    const total_pnl  = ((sl.total_pnl || 0) + (ss.total_pnl || 0)).toFixed(2);
    const unreal_pnl = ((sl.open_unrealised_pnl || 0) + (ss.open_unrealised_pnl || 0)).toFixed(2);
    $("#jr-scalp-stats").innerHTML = [
      statCard("Open",            all_open),
      statCard("Closed",          all_closed),
      statCard("Today's trades",  `${s.today_trades} / ${s.max_daily_trades}`),
      statCard("Today's P&L",     pfmt(s.today_pnl), pnlCls),
      statCard("Daily limit",     `-$${s.max_daily_loss}`, limCls),
      statCard("Realised $",      pfmt(parseFloat(total_pnl)),  parseFloat(total_pnl) >= 0 ? "accent-green" : ""),
      statCard("Unrealised $",    pfmt(parseFloat(unreal_pnl)), parseFloat(unreal_pnl) >= 0 ? "accent-green" : ""),
    ].join("");
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
      const allSec = $("#jr-all-section");
      if (allSec) allSec.classList.toggle("jr-hidden", jrnl !== "all");
      $("#jr-long-section").classList.toggle("jr-hidden",  jrnl !== "long");
      $("#jr-short-section").classList.toggle("jr-hidden", jrnl !== "short");
      $("#jr-scalp-section").classList.toggle("jr-hidden", jrnl !== "scalp");
    });
  });

  // Holds each journal's closed-trade $ P&L for the combined Overall view.
  const overall = { swing: [], scalp: [] };

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

      // Feed the Overall view (timestamped $ P&L from closed swing trades)
      overall.swing = [...cl, ...cs]
        .filter((c) => c.pnl != null)
        .map((c) => ({ ts: c.exit_date || c.opened || "", pnl: c.pnl, src: "swing" }));
      renderOverall();
    })
    .catch(() => {
      $("#jr-long-stats").innerHTML = `<div class="jr-empty" style="grid-column:1/-1">
        No journal yet. Run <code>python -m scanner.journal</code> to start the forward test.</div>`;
    });

  // ── SCALP journal (separate file, $-based) ───────────────────────────────
  fetch("data/scalp_journal.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      const s  = d.stats || {};
      const ol = d.open_longs   || [];
      const os = d.open_shorts  || [];
      const open = [...ol, ...os];
      const ac = d.all_closed || [...(d.closed_longs || []), ...(d.closed_shorts || [])];

      renderScalpStats(s);
      scalp_equity(ac, "jr-scalp-equity");
      $("#jr-scalp-open-n").textContent   = `(${open.length})`;
      $("#jr-scalp-closed-n").textContent = `(${ac.length})`;
      $("#jr-scalp-open").innerHTML   = scalp_openTable(open);
      $("#jr-scalp-closed").innerHTML = scalp_closedTable(ac);

      overall.scalp = ac
        .filter((c) => c.pnl != null)
        .map((c) => ({ ts: c.exit_ts || c.opened_ts || "", pnl: c.pnl, src: "scalp" }));
      renderOverall();
    })
    .catch(() => {
      const el = $("#jr-scalp-stats");
      if (el) el.innerHTML = `<div class="jr-empty" style="grid-column:1/-1">
        No scalp journal yet — it populates on the next scan.</div>`;
    });

  // ── Combined Overall dashboard (all journals, by $ P&L) ──────────────────
  function renderOverall() {
    const trades = [...overall.swing, ...overall.scalp]
      .filter((t) => t.pnl != null)
      .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
    if (!$("#jr-all-stats")) return;
    if (!trades.length) {
      $("#jr-all-stats").innerHTML = `<div class="jr-empty" style="grid-column:1/-1">
        No closed trades across any journal yet.</div>`;
      return;
    }
    const pnls = trades.map((t) => t.pnl);
    const wins = pnls.filter((p) => p > 0);
    const loss = pnls.filter((p) => p < 0);
    const grossWin  = wins.reduce((a, b) => a + b, 0);
    const grossLoss = Math.abs(loss.reduce((a, b) => a + b, 0));
    const pf  = grossLoss > 0 ? (grossWin / grossLoss).toFixed(2) : "∞";
    const tot = pnls.reduce((a, b) => a + b, 0);

    $("#jr-all-stats").innerHTML = [
      statCard("Total trades", trades.length),
      statCard("Win rate", `${(wins.length / trades.length * 100).toFixed(1)}%`),
      statCard("Profit factor", pf, grossWin >= grossLoss ? "accent-green" : ""),
      statCard("Realised $", pfmt(tot), pcls(tot)),
      statCard("Swing / Scalp", `${overall.swing.length} / ${overall.scalp.length}`),
      statCard("Expectancy", pfmt(tot / trades.length), pcls(tot)),
    ].join("");

    // Combined cumulative $ equity curve
    let cum = 0;
    const pts = trades.map((t) => (cum += t.pnl)); pts.unshift(0);
    const el = $("#jr-all-equity");
    const w = 1000, h = 180, pad = 8;
    const min = Math.min(0, ...pts), max = Math.max(0, ...pts), rng = (max - min) || 1;
    const x = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
    const y = (v) => h - pad - ((v - min) / rng) * (h - 2 * pad);
    const path = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const color = pts[pts.length - 1] >= 0 ? "#2fd07f" : "#ff5b5b";
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="0" y1="${y(0).toFixed(1)}" x2="${w}" y2="${y(0).toFixed(1)}" stroke="#1b2333" stroke-width="1"/>
      <polyline points="${path}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
  }
})();

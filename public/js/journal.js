/* Journal — Journal 1 (LONGS) + Journal 2 (SHORTS) */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const GRADE_CLS = { "A+": "g-aplus", "A": "g-a", "B": "g-b", "C": "g-c" };

  // Escape data-derived strings before injecting into innerHTML (incl. quotes
  // so values are safe inside quoted attributes too).
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const up = (s) => esc(String(s == null ? "" : s).toUpperCase());

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
      <td class="jr-sym">${esc(p.symbol)}</td>
      <td><span class="jr-grade ${GRADE_CLS[p.grade] || ""}">${esc(p.grade)}</span></td>
      <td>${num(p.entry)}</td>
      <td>${num(p.stop)}</td>
      <td>${num(p.target)}</td>
      <td>${num(p.current)}</td>
      <td>${p.shares != null ? p.shares + " sh" : "—"}</td>
      <td class="${rcls(p.unreal_r || 0)}">${rfmt(p.unreal_r)}</td>
      <td class="${pcls(p.unreal_pnl || 0)}">${pfmt(p.unreal_pnl)}</td>
      <td>${esc(p.opened)}</td>
    </tr>`).join("");
    return `<table class="jr-table"><thead><tr>
      <th>Symbol</th><th>Grade</th><th>Entry</th><th>Stop</th><th>Target</th>
      <th>Current</th><th>Size</th><th>Unreal. R</th><th>Unreal. $</th><th>Opened</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  }

  function closedTable(closed) {
    if (!closed.length) return `<div class="jr-empty">No closed trades yet.</div>`;
    const rows = closed.slice().reverse().map((c) => `<tr>
      <td class="jr-sym">${esc(c.symbol)}</td>
      <td><span class="jr-grade ${GRADE_CLS[c.grade] || ""}">${esc(c.grade)}</span></td>
      <td>${num(c.entry)}</td>
      <td>${num(c.exit)}</td>
      <td>${c.shares != null ? c.shares + " sh" : "—"}</td>
      <td><span class="reason">${esc(c.reason)}</span></td>
      <td class="${rcls(c.r)}">${rfmt(c.r)}</td>
      <td class="${pcls(c.pnl || 0)}">${pfmt(c.pnl)}</td>
      <td>${esc(c.opened)} → ${esc(c.exit_date)}</td>
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
      const assetBadge = p.asset_type ? `<span class="reason">${up(p.asset_type)}</span>` : "";
      return `<tr>
        <td class="jr-sym">${esc(p.symbol)} ${assetBadge}</td>
        <td class="${dirCls}">${up(p.direction)}</td>
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
        <td class="jr-sym">${esc(c.symbol)}</td>
        <td class="${dirCls}">${up(c.direction)}</td>
        <td><span class="jr-grade ${GRADE_CLS[c.grade] || ""}">${esc(c.grade)}</span></td>
        <td>${num(c.entry)}</td>
        <td>${num(c.exit)}</td>
        <td>${c.units != null ? c.units + " u" : "—"}</td>
        <td><span class="reason">${esc(c.reason)}</span></td>
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
      const mineSec = $("#jr-mine-section");
      if (mineSec) {
        mineSec.classList.toggle("jr-hidden", jrnl !== "mine");
        if (jrnl === "mine") mjRender();
      }
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
  // ═══════════════════════════════════ MY TRADES ═══════════════════════════════
  // Fully local — stored in localStorage, never sent to the server.
  // $10 brokerage each way, configurable. All P&L / R calculated on render.

  const MJ_KEY = "gbs:manual_journal";

  function mjLoad() {
    try { const r = localStorage.getItem(MJ_KEY); if (r) return JSON.parse(r); } catch (_) {}
    return { capital: 10000, brokerage: 10, trades: [] };
  }
  function mjSave(d) { localStorage.setItem(MJ_KEY, JSON.stringify(d)); }
  function mjUid()   { return Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }

  // Compute realised P&L and R for one closed trade.
  function mjCalc(t, brokerage) {
    if (t.status !== "closed" || t.exit == null) return { pnl: null, r: null };
    const m   = t.direction === "long" ? 1 : -1;
    const pnl = parseFloat((t.shares * m * (t.exit - t.entry) - 2 * brokerage).toFixed(2));
    let r = null;
    if (t.stop != null) {
      const risk = t.direction === "long" ? t.entry - t.stop : t.stop - t.entry;
      if (risk > 0) r = parseFloat(((m * (t.exit - t.entry)) / risk).toFixed(2));
    }
    return { pnl, r };
  }

  function mjRender() {
    const data = mjLoad();
    const { capital, brokerage, trades } = data;

    // Sync settings inputs
    const capEl = $("#mj-capital"), brkEl = $("#mj-brokerage");
    if (capEl) capEl.value = capital;
    if (brkEl) brkEl.value = brokerage;

    const open   = trades.filter((t) => t.status === "open");
    const closed = trades.filter((t) => t.status === "closed")
                         .map((t) => ({ ...t, ...mjCalc(t, brokerage) }));

    // stats
    const pnls       = closed.map((t) => t.pnl).filter((p) => p != null);
    const realised   = pnls.reduce((a, b) => a + b, 0);
    const balance    = capital + realised;
    const wins       = closed.filter((t) => (t.pnl || 0) > 0);
    const win_rate   = closed.length ? (wins.length / closed.length * 100).toFixed(0) : 0;
    const rs         = closed.map((t) => t.r).filter((r) => r != null);
    const total_r    = rs.reduce((a, b) => a + b, 0);
    const balCls     = balance >= capital ? "accent-green" : "";

    const statsEl = $("#jr-mine-stats");
    if (statsEl) statsEl.innerHTML = [
      statCard("Account balance", "$" + balance.toLocaleString(undefined, { maximumFractionDigits: 0 }), balCls),
      statCard("Open positions", open.length),
      statCard("Closed trades", closed.length),
      statCard("Win rate", `${win_rate}%`),
      statCard("Realised R", (total_r >= 0 ? "+" : "") + total_r.toFixed(2) + "R", total_r >= 0 ? "accent-green" : ""),
      statCard("Realised $", pfmt(realised), pcls(realised)),
    ].join("");

    // equity curve
    const eqEl = $("#jr-mine-equity");
    if (eqEl) {
      if (!closed.length) {
        eqEl.innerHTML = `<div class="jr-empty">Log your first closed trade — the curve appears here.</div>`;
      } else {
        let cum = 0;
        const pts = closed.map((t) => (cum += (t.pnl || 0)));
        pts.unshift(0);
        const w = 1000, h = 180, pad = 8;
        const mn = Math.min(0, ...pts), mx = Math.max(0, ...pts), rng = (mx - mn) || 1;
        const x  = (i) => pad + (i / (pts.length - 1)) * (w - 2 * pad);
        const y  = (v) => h - pad - ((v - mn) / rng) * (h - 2 * pad);
        const path = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        const color = pts[pts.length - 1] >= 0 ? "#2fd07f" : "#ff5b5b";
        eqEl.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
          <line x1="0" y1="${y(0).toFixed(1)}" x2="${w}" y2="${y(0).toFixed(1)}" stroke="#1b2333" stroke-width="1"/>
          <polyline points="${path}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
      }
    }

    // open table
    const openEl = $("#jr-mine-open");
    if (openEl) {
      $("#jr-mine-open-n").textContent = `(${open.length})`;
      if (!open.length) {
        openEl.innerHTML = `<div class="jr-empty">No open positions — tap "+ Log New Trade" to add one.</div>`;
      } else {
        const rows = open.map((t) => {
          const dc  = t.direction === "long" ? "dir-long" : "dir-short";
          const dir = t.direction === "long" ? "↑ LONG" : "↓ SHORT";
          let rr = "—";
          if (t.stop != null && t.target != null && t.entry > 0) {
            const risk = t.direction === "long" ? t.entry - t.stop : t.stop - t.entry;
            const rew  = t.direction === "long" ? t.target - t.entry : t.entry - t.target;
            if (risk > 0) rr = (rew / risk).toFixed(1) + "R";
          }
          return `<tr>
            <td class="jr-sym">${esc(t.symbol)}</td>
            <td><span class="dir-chip ${dc}">${dir}</span></td>
            <td>${t.entry != null ? "$" + num(t.entry) : "—"}</td>
            <td class="r-neg">${t.stop   != null ? "$" + num(t.stop)   : "—"}</td>
            <td class="r-pos">${t.target != null ? "$" + num(t.target) : "—"}</td>
            <td>${rr}</td>
            <td>${t.shares != null ? t.shares + " sh" : "—"}</td>
            <td class="muted">${esc(t.entry_date)}${t.entry_time ? " " + t.entry_time : ""}</td>
            <td>${t.notes ? `<span class="reason">${esc(t.notes)}</span>` : "—"}</td>
            <td style="white-space:nowrap">
              <button class="mj-close-btn" data-id="${esc(t.id)}">Close</button>
              <button class="mj-del-btn"   data-id="${esc(t.id)}" title="Delete">✕</button>
            </td>
          </tr>`;
        }).join("");
        openEl.innerHTML = `<table class="jr-table"><thead><tr>
          <th>Symbol</th><th>Dir</th><th>Entry</th><th>Stop</th><th>Target</th>
          <th>R:R</th><th>Size</th><th>Opened</th><th>Notes</th><th></th>
        </tr></thead><tbody>${rows}</tbody></table>`;
      }
    }

    // closed table
    const closedEl = $("#jr-mine-closed");
    if (closedEl) {
      $("#jr-mine-closed-n").textContent = `(${closed.length})`;
      if (!closed.length) {
        closedEl.innerHTML = `<div class="jr-empty">No closed trades yet.</div>`;
      } else {
        const rows = closed.slice().reverse().map((t) => {
          const dc   = t.direction === "long" ? "dir-long" : "dir-short";
          const dir  = t.direction === "long" ? "↑ L" : "↓ S";
          const rStr = t.r   != null ? (t.r   >= 0 ? "+" : "") + t.r.toFixed(2) + "R" : "—";
          const pStr = t.pnl != null ? (t.pnl >= 0 ? "+" : "−") + "$" + Math.abs(t.pnl).toFixed(2) : "—";
          const rCls = (t.r   || 0) >= 0 ? "r-pos" : "r-neg";
          const pCls = (t.pnl || 0) >= 0 ? "r-pos" : "r-neg";
          return `<tr>
            <td class="jr-sym">${esc(t.symbol)}</td>
            <td><span class="dir-chip ${dc}">${dir}</span></td>
            <td>${t.entry != null ? "$" + num(t.entry) : "—"}</td>
            <td>${t.exit  != null ? "$" + num(t.exit)  : "—"}</td>
            <td>${t.shares != null ? t.shares + " sh" : "—"}</td>
            <td class="${rCls}">${rStr}</td>
            <td class="${pCls}">${pStr}</td>
            <td class="muted">${esc(t.entry_date)} → ${esc(t.exit_date || "")}</td>
            <td>${t.notes ? `<span class="reason">${esc(t.notes)}</span>` : "—"}</td>
            <td><button class="mj-del-btn" data-id="${esc(t.id)}" title="Delete">✕</button></td>
          </tr>`;
        }).join("");
        closedEl.innerHTML = `<table class="jr-table"><thead><tr>
          <th>Symbol</th><th>Dir</th><th>Entry</th><th>Exit</th><th>Size</th>
          <th>Result R</th><th>P&amp;L $</th><th>Dates</th><th>Notes</th><th></th>
        </tr></thead><tbody>${rows}</tbody></table>`;
      }
    }
  }

  // ── Modal helpers ──────────────────────────────────────────────────────────
  function mjNow() {
    const d = new Date();
    return {
      date: d.toISOString().slice(0, 10),
      time: d.toTimeString().slice(0, 5),
    };
  }

  function mjSetDir(dir) {
    document.querySelectorAll(".mj-dir-btn").forEach((b) => {
      b.classList.toggle("mj-dir-active", b.dataset.dir === dir);
    });
  }
  function mjGetDir() {
    const a = document.querySelector(".mj-dir-btn.mj-dir-active");
    return a ? a.dataset.dir : "long";
  }

  function mjOpenModal() {
    const { date, time } = mjNow();
    const { capital }    = mjLoad();

    $("#mj-modal-title").textContent = "Log New Trade";
    $("#mj-trade-id").value   = "";
    $("#mj-symbol").value     = "";
    $("#mj-entry").value      = "";
    $("#mj-size").value       = 1000;
    $("#mj-entry-date").value = date;
    $("#mj-entry-time").value = time;
    $("#mj-stop").value       = "";
    $("#mj-target").value     = "";
    $("#mj-notes").value      = "";
    $("#mj-shares-preview").textContent = "";
    mjSetDir("long");
    $("#mj-open-fields").classList.remove("mj-hidden");
    $("#mj-close-fields").classList.add("mj-hidden");
    $("#mj-modal").classList.remove("mj-hidden");
    setTimeout(() => $("#mj-symbol") && $("#mj-symbol").focus(), 60);
  }

  function mjOpenCloseModal(tradeId) {
    const { trades } = mjLoad();
    const t = trades.find((x) => x.id === tradeId);
    if (!t) return;
    const { date, time } = mjNow();

    $("#mj-modal-title").textContent = `Close ${t.symbol} ${t.direction === "long" ? "LONG" : "SHORT"}`;
    $("#mj-trade-id").value   = tradeId;
    $("#mj-exit").value       = "";
    $("#mj-exit-date").value  = date;
    $("#mj-exit-time").value  = time;
    $("#mj-close-preview").textContent = "";
    $("#mj-open-fields").classList.add("mj-hidden");
    $("#mj-close-fields").classList.remove("mj-hidden");
    $("#mj-modal").classList.remove("mj-hidden");
    // stash trade data on the preview element so the input handler can use it
    $("#mj-close-preview").dataset.entry     = t.entry;
    $("#mj-close-preview").dataset.stop      = t.stop  || "";
    $("#mj-close-preview").dataset.shares    = t.shares || 0;
    $("#mj-close-preview").dataset.dir       = t.direction;
    setTimeout(() => $("#mj-exit") && $("#mj-exit").focus(), 60);
  }

  function mjCloseModal() {
    $("#mj-modal").classList.add("mj-hidden");
  }

  // Live preview: shares + P&L estimate while typing in the form
  function mjUpdateOpenPreview() {
    const entry = parseFloat($("#mj-entry").value);
    const size  = parseFloat($("#mj-size").value);
    const prev  = $("#mj-shares-preview");
    if (!prev) return;
    if (!entry || !size) { prev.textContent = ""; return; }
    const shares  = Math.floor(size / entry);
    const { brokerage } = mjLoad();
    const stopEl = parseFloat($("#mj-stop").value);
    let rr = "";
    if (stopEl && $("#mj-target").value) {
      const dir  = mjGetDir();
      const risk = dir === "long" ? entry - stopEl : stopEl - entry;
      const tgt  = parseFloat($("#mj-target").value);
      const rew  = dir === "long" ? tgt - entry : entry - tgt;
      if (risk > 0) rr = ` · R:R ${(rew / risk).toFixed(1)}`;
    }
    prev.innerHTML = `<span class="hl">${shares} shares</span> · max risk <span class="hl">$${(shares * Math.abs((entry - (stopEl || 0))).toFixed ? "$" : "")}</span>${rr}`;
    prev.textContent = `${shares} shares${rr ? "  ·  " + rr.trim() : ""}`;
  }

  function mjUpdateClosePreview() {
    const prev  = $("#mj-close-preview");
    const exit  = parseFloat($("#mj-exit").value);
    if (!prev || !exit) { if (prev) prev.textContent = ""; return; }
    const entry    = parseFloat(prev.dataset.entry  || 0);
    const stop     = parseFloat(prev.dataset.stop   || 0);
    const shares   = parseInt(prev.dataset.shares   || 0, 10);
    const dir      = prev.dataset.dir || "long";
    const { brokerage } = mjLoad();
    const m   = dir === "long" ? 1 : -1;
    const pnl = shares * m * (exit - entry) - 2 * brokerage;
    let r = "";
    if (stop) {
      const risk = dir === "long" ? entry - stop : stop - entry;
      if (risk > 0) r = ` · ${((m * (exit - entry)) / risk).toFixed(2)}R`;
    }
    const pCls = pnl >= 0 ? "pos" : "neg";
    prev.innerHTML = `P&amp;L: <span class="${pCls}">${pnl >= 0 ? "+" : "−"}$${Math.abs(pnl).toFixed(2)}</span>${r ? ` <span class="${pnl >= 0 ? "pos" : "neg"}">${r.trim()}</span>` : ""}`;
  }

  // ── Form submit ────────────────────────────────────────────────────────────
  function mjHandleSubmit(e) {
    e.preventDefault();
    const data     = mjLoad();
    const tradeId  = $("#mj-trade-id").value;

    if (tradeId) {
      // Close an existing position
      const t = data.trades.find((x) => x.id === tradeId);
      if (!t) return;
      t.exit       = parseFloat($("#mj-exit").value);
      t.exit_date  = $("#mj-exit-date").value;
      t.exit_time  = $("#mj-exit-time").value;
      t.status     = "closed";
    } else {
      // Open a new position
      const entry  = parseFloat($("#mj-entry").value);
      const size   = parseFloat($("#mj-size").value);
      const stop   = parseFloat($("#mj-stop").value)   || null;
      const target = parseFloat($("#mj-target").value) || null;
      data.trades.push({
        id:          mjUid(),
        symbol:      $("#mj-symbol").value.trim().toUpperCase(),
        direction:   mjGetDir(),
        entry,
        entry_date:  $("#mj-entry-date").value,
        entry_time:  $("#mj-entry-time").value,
        size_usd:    size,
        shares:      entry > 0 ? Math.floor(size / entry) : 0,
        stop,
        target,
        notes:       $("#mj-notes").value.trim(),
        status:      "open",
        exit:        null,
        exit_date:   null,
        exit_time:   null,
      });
    }

    mjSave(data);
    mjCloseModal();
    mjRender();
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  (function mjInit() {
    const newBtn = $("#mj-new-btn");
    if (newBtn) newBtn.addEventListener("click", mjOpenModal);

    const clearBtn = $("#mj-clear-btn");
    if (clearBtn) clearBtn.addEventListener("click", () => {
      if (confirm("Clear ALL your manual trades? This cannot be undone.")) {
        const data = mjLoad();
        data.trades = [];
        mjSave(data);
        mjRender();
      }
    });

    const modalX  = $("#mj-modal-x");
    const cancelBtn = $("#mj-cancel");
    if (modalX)    modalX.addEventListener("click",    mjCloseModal);
    if (cancelBtn) cancelBtn.addEventListener("click", mjCloseModal);

    const overlay = $("#mj-modal");
    if (overlay) overlay.addEventListener("click", (e) => { if (e.target === overlay) mjCloseModal(); });

    const form = $("#mj-form");
    if (form) form.addEventListener("submit", mjHandleSubmit);

    // Direction toggle
    document.querySelectorAll(".mj-dir-btn").forEach((b) => {
      b.addEventListener("click", () => { mjSetDir(b.dataset.dir); mjUpdateOpenPreview(); });
    });

    // Live preview on entry/size/stop/target change
    ["#mj-entry", "#mj-size", "#mj-stop", "#mj-target"].forEach((sel) => {
      const el = $(sel);
      if (el) el.addEventListener("input", mjUpdateOpenPreview);
    });
    const exitEl = $("#mj-exit");
    if (exitEl) exitEl.addEventListener("input", mjUpdateClosePreview);

    // Settings persistence
    ["#mj-capital", "#mj-brokerage"].forEach((sel) => {
      const el = $(sel);
      if (!el) return;
      el.addEventListener("change", () => {
        const data       = mjLoad();
        data.capital     = parseFloat($("#mj-capital").value)   || 10000;
        data.brokerage   = parseFloat($("#mj-brokerage").value) || 10;
        mjSave(data);
        mjRender();
      });
    });

    // Delegated: close / delete buttons in the open/closed tables
    document.addEventListener("click", (e) => {
      const closeBtn = e.target.closest(".mj-close-btn");
      const delBtn   = e.target.closest(".mj-del-btn");
      if (closeBtn) { mjOpenCloseModal(closeBtn.dataset.id); return; }
      if (delBtn) {
        if (confirm("Delete this trade? This cannot be undone.")) {
          const data   = mjLoad();
          data.trades  = data.trades.filter((t) => t.id !== delBtn.dataset.id);
          mjSave(data);
          mjRender();
        }
      }
    });
  })();

})();

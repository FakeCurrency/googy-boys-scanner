/* VIVEK track-record page — read-only view over data/vivek_journal.json.
   Renders the headline summary, expectancy split by grade/entry-type/timeframe,
   a cumulative-R equity curve, and the open + closed paper-trade tables. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (v == null || isNaN(v) ? 0 : +v);
  const fmtR = (r) => `${num(r) >= 0 ? "+" : ""}${num(r).toFixed(2)}R`;
  const tone = (r) => (num(r) > 0.02 ? "pos" : num(r) < -0.02 ? "neg" : "");
  const price = (v) => (v == null ? "—" : (Math.abs(v) >= 100 ? num(v).toFixed(2)
    : Math.abs(v) >= 1 ? num(v).toFixed(3) : num(v).toFixed(4)));
  const ENTRY_LABEL = { reclaim: "Reclaim", retest: "Retest", break: "Break" };

  function daysSince(iso) {
    const t = Date.parse(iso);
    if (!isFinite(t)) return null;
    return Math.max(0, Math.round((Date.now() - t) / 86400000));
  }

  // ── headline summary cards ────────────────────────────────────────────────
  function renderSummary(j, e) {
    const ov = e.overall || { n: 0 };
    const card = (label, val, cls) =>
      `<div class="stat-card"><div class="stat-label">${esc(label)}</div>` +
      `<div class="stat-value ${cls || ""}">${val}</div></div>`;
    $("#trkp-summary").innerHTML = [
      card("Expectancy", ov.n ? fmtR(ov.expectancy_r) : "—", ov.n ? tone(ov.expectancy_r) : ""),
      card("Win rate", ov.n ? `${ov.win_rate}%` : "—"),
      card("Total R", ov.n ? fmtR(ov.total_r) : "—", ov.n ? tone(ov.total_r) : ""),
      card("Closed", String((j.closed || []).length)),
      card("Open", String((j.open || []).length)),
    ].join("");
  }

  // ── expectancy breakdown (grade / entry type / timeframe) ─────────────────
  function renderBreakdown(e) {
    const row = (label, s) => {
      if (!s || !s.n) return `<tr class="trkp-empty"><td>${esc(label)}</td><td colspan="5">no closed trades</td></tr>`;
      return `<tr>
        <td class="trkp-k">${esc(label)}</td>
        <td class="trkp-r ${tone(s.expectancy_r)}">${fmtR(s.expectancy_r)}</td>
        <td>${s.win_rate}%</td>
        <td class="mono">${s.n}</td>
        <td class="mono pos">${fmtR(s.avg_win_r)}</td>
        <td class="mono neg">${fmtR(s.avg_loss_r)}</td>
      </tr>`;
    };
    const group = (title, obj, keys, labels) => {
      const body = keys.map((k) => row(labels ? (labels[k] || k) : k, (obj || {})[k])).join("");
      return `<div class="trkp-grp">
        <div class="trkp-grp-title">${esc(title)}</div>
        <table class="trkp-table trkp-bd">
          <thead><tr><th></th><th>Expectancy</th><th>Win</th><th>n</th><th>Avg win</th><th>Avg loss</th></tr></thead>
          <tbody>${body}</tbody>
        </table></div>`;
    };
    $("#trkp-breakdown").innerHTML =
      group("By entry type", e.by_entry_type, ["reclaim", "retest", "break"], ENTRY_LABEL) +
      group("By grade", e.by_grade, ["A+", "A"]) +
      group("By timeframe", e.by_timeframe, ["1D", "1W", "4H"]);
  }

  // ── equity curve (cumulative realized R over closed trades) ────────────────
  function renderEquity(closed) {
    const box = $("#trkp-equity");
    const done = (closed || []).filter((t) => t.exit_date)
      .sort((a, b) => String(a.exit_date).localeCompare(String(b.exit_date)));
    if (done.length < 2) {
      box.innerHTML = `<div class="trkp-emptybox">The equity curve appears once a few trades close. ` +
        `${done.length} closed so far.</div>`;
      return;
    }
    let cum = 0;
    const pts = done.map((t) => (cum += num(t.realized_r)));
    const min = Math.min(0, ...pts), max = Math.max(0, ...pts);
    const W = 640, H = 180, pad = 8;
    const x = (i) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
    const y = (v) => H - pad - ((v - min) / (max - min || 1)) * (H - 2 * pad);
    const path = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const zeroY = y(0).toFixed(1);
    const last = pts[pts.length - 1];
    box.innerHTML =
      `<svg viewBox="0 0 ${W} ${H}" class="trkp-svg" preserveAspectRatio="none">
        <line x1="0" y1="${zeroY}" x2="${W}" y2="${zeroY}" class="trkp-zero"/>
        <path d="${path}" class="trkp-line ${last >= 0 ? "pos" : "neg"}"/>
      </svg>
      <div class="trkp-eqfoot"><span>${done.length} trades</span>` +
      `<span class="${tone(last)}">${fmtR(last)} cumulative</span></div>`;
  }

  function dirBadge(dir) {
    const up = String(dir).toUpperCase() === "SHORT" ? "short" : "long";
    return `<span class="badge dir ${up}">${up === "short" ? "SHORT" : "LONG"}</span>`;
  }
  function typeChip(t) {
    return t ? `<span class="trkp-type">${esc(ENTRY_LABEL[t] || t)}</span>` : "—";
  }
  function progress(t) {
    const hits = ["tp1", "tp2", "tp3"].filter((k) => t[k + "_hit"]).length;
    if (t.status === "closed") return esc(t.exit_reason || "closed");
    if (hits) return `TP${hits} hit · ${Math.round(num(t.booked_pct) * 100)}% booked`;
    return "open";
  }

  // ── open positions table ──────────────────────────────────────────────────
  function renderOpen(open) {
    $("#trkp-open-count").textContent = open.length;
    const box = $("#trkp-open");
    if (!open.length) { box.innerHTML = `<div class="trkp-emptybox">No open paper trades right now.</div>`; return; }
    const order = { "A+": 0, A: 1 };
    open = open.slice().sort((a, b) => (order[a.grade] - order[b.grade]) || (num(b.mfe_r) - num(a.mfe_r)));
    const rows = open.map((t) => `<tr>
      <td><strong>${esc(t.symbol)}</strong> ${dirBadge(t.direction)}</td>
      <td><b class="grade-${esc((t.grade || "").replace("+", "p"))}">${esc(t.grade)}</b></td>
      <td>${typeChip(t.entry_type)}</td>
      <td class="mono">${esc(t.timeframe)}</td>
      <td class="mono">${price(t.entry)}</td>
      <td class="mono neg">${price(t.stop)}</td>
      <td class="mono">${price(t.tp1)} / ${price(t.tp2)} / ${price(t.tp3)}</td>
      <td class="mono">${daysSince(t.entry_date) ?? "—"}d</td>
      <td>${esc(progress(t))}</td>
      <td class="mono ${tone(t.realized_r)}">${fmtR(t.realized_r)}</td>
      <td class="mono pos">${t.mfe_r != null ? fmtR(t.mfe_r) : "—"}</td>
      <td class="mono neg">${t.mae_r != null ? fmtR(t.mae_r) : "—"}</td>
    </tr>`).join("");
    box.innerHTML = `<table class="trkp-table">
      <thead><tr><th>Setup</th><th>Grade</th><th>Type</th><th>TF</th><th>Entry</th><th>SL</th>
      <th>TP1/2/3</th><th>Held</th><th>Status</th><th>R booked</th><th>MFE</th><th>MAE</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  // ── closed trades table ───────────────────────────────────────────────────
  function renderClosed(closed) {
    $("#trkp-closed-count").textContent = closed.length;
    const box = $("#trkp-closed");
    if (!closed.length) { box.innerHTML = `<div class="trkp-emptybox">No closed trades yet — they resolve as price hits a target or stop over the coming sessions.</div>`; return; }
    const list = closed.slice().sort((a, b) => String(b.exit_date).localeCompare(String(a.exit_date)));
    const rows = list.map((t) => `<tr>
      <td><strong>${esc(t.symbol)}</strong> ${dirBadge(t.direction)}</td>
      <td><b class="grade-${esc((t.grade || "").replace("+", "p"))}">${esc(t.grade)}</b></td>
      <td>${typeChip(t.entry_type)}</td>
      <td class="mono">${esc(t.timeframe)}</td>
      <td class="mono">${price(t.entry)}</td>
      <td class="mono">${price(t.exit_price)}</td>
      <td class="mono ${tone(t.realized_r)}"><b>${fmtR(t.realized_r)}</b></td>
      <td>${esc(t.exit_reason || "")}</td>
      <td class="mono">${t.hold_days != null ? t.hold_days + "d" : "—"}</td>
      <td class="mono pos">${t.mfe_r != null ? fmtR(t.mfe_r) : "—"}</td>
      <td class="mono neg">${t.mae_r != null ? fmtR(t.mae_r) : "—"}</td>
    </tr>`).join("");
    box.innerHTML = `<table class="trkp-table">
      <thead><tr><th>Setup</th><th>Grade</th><th>Type</th><th>TF</th><th>Entry</th><th>Exit</th>
      <th>R</th><th>Reason</th><th>Held</th><th>MFE</th><th>MAE</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  function render(j) {
    const e = j.expectancy || {};
    renderSummary(j, e);
    renderBreakdown(e);
    renderEquity(j.closed || []);
    renderOpen(j.open || []);
    renderClosed(j.closed || []);
  }

  fetch("data/vivek_journal.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(() => {
      $("#trkp-summary").innerHTML = `<div class="trkp-emptybox">No journal data yet — it appears after the first scan that finds ARMED A+/A setups.</div>`;
    });
})();

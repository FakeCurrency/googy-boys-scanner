/* AI Bot terminal — Vivek's Beta Scanner
   Swing-trading dashboard: risk-first, futures/CFD instruments, paper journal. */
(function () {
  "use strict";

  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const RULES_KEY = "gbs_bot_rules_v2";
  const KILL_KEY = "gbs_bot_kill_v1";
  const COUNTER_KEY = "gbs_bot_counter_v1";

  // ── Instrument specs (CFD-style $/point, sane on a small account) ──────────
  const INSTRUMENTS = {
    "/NQ": { name: "NAS100", ppt: 1.0,  kind: "index" },
    "YM":  { name: "US30",   ppt: 1.0,  kind: "index" },
    "GC":  { name: "Gold",   ppt: 1.0,  kind: "metal" },
    "SI":  { name: "Silver", ppt: 5.0,  kind: "metal" },
    "CL":  { name: "Crude",  ppt: 1.0,  kind: "energy" },
    "NG":  { name: "NatGas", ppt: 100.0, kind: "energy" },
  };

  // ── Default rules ──────────────────────────────────────────────────────────
  const DEFAULT_RULES = {
    markets: ["NAS100", "US30", "XAU", "CL"],
    strategies: ["trend_pullback", "breakout"],
    bias_tf: "Daily",
    entry_tf: "4H",
    min_rr: 2,
    bias: "daily",
    risk_pct: 2,
    loss_limit: 3,
    max_positions: 3,
    use_scanner_targets: true,
    trail_supertrend: true,
    be_1r: true,
  };

  const loadRules = () => { try { return { ...DEFAULT_RULES, ...JSON.parse(localStorage.getItem(RULES_KEY)) }; } catch (_) { return { ...DEFAULT_RULES }; } };
  const saveRules = r => localStorage.setItem(RULES_KEY, JSON.stringify(r));

  // ── Formatting helpers ─────────────────────────────────────────────────────
  const money = (n, dec = 2) => n == null ? "—" : (n < 0 ? "−" : "") + "$" + Math.abs(n).toLocaleString("en-AU", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const moneyK = n => n == null ? "—" : "$" + n.toLocaleString("en-AU", { maximumFractionDigits: 0 });
  const px = (v) => v == null ? "—" : v >= 1000 ? v.toLocaleString("en-AU", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : v.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const signed = (n, dec = 2) => (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(dec);
  const pct = n => (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(2) + "%";

  function fmtTs(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Australia/Sydney" }); }
    catch (_) { return iso; }
  }
  function fmtDateShort(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("en-AU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Australia/Sydney" }); }
    catch (_) { return iso; }
  }
  function fmtAge(iso) {
    if (!iso) return "";
    const secs = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (secs < 0) return "just now";
    if (secs < 3600) return `${Math.floor(secs / 60)}m`;
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
    return h < 24 ? `${h}h ${m}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
  }

  // ── SVG sparkline ──────────────────────────────────────────────────────────
  function sparkline(vals, w, h, color) {
    if (!vals || vals.length < 2) return "";
    const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
    const pts = vals.map((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<svg class="pos-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
  }

  // ── Equity curve ───────────────────────────────────────────────────────────
  function renderEquityCurve(curve) {
    const svg = $("#equity-svg");
    if (!svg || !curve || curve.length < 2) return;
    const w = 300, h = 70;
    const min = Math.min(...curve), max = Math.max(...curve), range = max - min || 1;
    const up = curve[curve.length - 1] >= curve[0];
    const color = up ? getCSS("--green") : getCSS("--red");
    const pts = curve.map((v, i) => {
      const x = (i / (curve.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 8) - 4;
      return [x, y];
    });
    const line = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const area = `0,${h} ${line} ${w},${h}`;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.innerHTML = `
      <defs><linearGradient id="eqgrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.22"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
      </linearGradient></defs>
      <polygon points="${area}" fill="url(#eqgrad)"/>
      <polyline points="${line}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/>`;
  }
  const getCSS = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#34c759";

  // ── Connections ────────────────────────────────────────────────────────────
  function renderConnections(conns) {
    const wrap = $("#bot-conn-group");
    if (!wrap || !conns) return;
    const order = ["mode", "bybit", "ibkr"];
    wrap.innerHTML = order.filter(k => conns[k]).map(k => {
      const c = conns[k];
      return `<div class="bot-conn conn-${c.state}">
        <span class="bot-conn-dot"></span>
        <span class="bot-conn-text"><span class="bot-conn-label">${c.label}</span><span class="bot-conn-detail">${c.detail}</span></span>
      </div>`;
    }).join("");
  }

  // ── Risk status ────────────────────────────────────────────────────────────
  function getCounter(serverVal) {
    const stored = localStorage.getItem(COUNTER_KEY);
    return stored != null ? Number(stored) : (serverVal || 0);
  }
  function setCounter(n) { localStorage.setItem(COUNTER_KEY, String(n)); }

  function renderRiskStatus(rs, rules) {
    const limit = rules.loss_limit || rs.hard_limit || 3;
    const count = Math.min(getCounter(rs.consecutive_losses), limit);
    const card = $("#risk-status-card");
    $("#risk-counter").textContent = count;
    $("#risk-limit").textContent = limit;
    $("#risk-health-meta").textContent = count >= limit ? "PAUSED" : count >= limit - 1 ? "Warning" : "Healthy";

    // pips
    const pipsWrap = $("#risk-pips");
    pipsWrap.innerHTML = "";
    for (let i = 0; i < limit; i++) {
      const pip = document.createElement("div");
      pip.className = "risk-pip";
      if (i < count) pip.classList.add(`filled-${count >= limit ? 3 : count >= limit - 1 ? 2 : 1}`);
      pipsWrap.appendChild(pip);
    }

    const msg = $("#risk-status-msg");
    card.classList.remove("is-warn", "is-danger");
    if (count >= limit) {
      msg.className = "risk-status-msg danger";
      msg.textContent = "Trading paused — new entries blocked.";
      card.classList.add("is-danger");
    } else if (count >= limit - 1) {
      msg.className = "risk-status-msg warn";
      msg.textContent = "One more loss will pause new entries.";
      card.classList.add("is-warn");
    } else {
      msg.className = "risk-status-msg healthy";
      msg.textContent = "Trading normally.";
    }

    $("#risk-reset-btn").classList.toggle("show", count > 0);
    renderRiskBanner(count, limit);
  }

  function renderRiskBanner(count, limit) {
    const banner = $("#risk-banner");
    const killActive = getKill().active;
    if (killActive) { banner.classList.remove("show"); return; } // kill banner takes priority
    if (count >= limit) {
      banner.className = "bot-banner bot-banner-pause show";
      $("#risk-banner-icon").textContent = "⛔";
      $("#risk-banner-text").innerHTML = `<strong>TRADING PAUSED</strong> — ${count} consecutive losses. New entries blocked until manual reset.`;
    } else if (count >= limit - 1) {
      banner.className = "bot-banner bot-banner-warn show";
      $("#risk-banner-icon").textContent = "⚠";
      $("#risk-banner-text").innerHTML = `<strong>${count} consecutive losses</strong> — one more loss will pause new entries.`;
    } else {
      banner.classList.remove("show");
    }
  }

  // ── Kill switch state ──────────────────────────────────────────────────────
  function getKill() { try { return JSON.parse(localStorage.getItem(KILL_KEY)) || { active: false }; } catch (_) { return { active: false }; } }
  function setKill(obj) { localStorage.setItem(KILL_KEY, JSON.stringify(obj)); }

  function renderKill(serverKill) {
    const k = getKill();
    const banner = $("#kill-banner");
    const btn = $("#kill-btn");
    const bar = $("#bot-status-bar");
    if (k.active) {
      banner.classList.add("show");
      $("#kill-banner-text").innerHTML = `<strong>KILL SWITCH ACTIVE</strong> — Trading disabled. Reason: ${k.reason || "manual"} · ${k.action || ""}`;
      btn.classList.add("is-active");
      btn.textContent = "⏻ KILL ACTIVE";
      bar.dataset.status = "stopped";
    } else {
      banner.classList.remove("show");
      btn.classList.remove("is-active");
      btn.textContent = "⏻ KILL SWITCH";
    }
    // last event line
    const last = k.last_event || (serverKill && serverKill.last_event);
    if (last) {
      $("#roadmap-kill-line").innerHTML = `Last kill switch: <strong>${fmtDateShort(last.ts)} · ${last.reason}</strong> — ${last.action}`;
    }
  }

  // ── Positions (swing cards) ────────────────────────────────────────────────
  function renderPositions(positions) {
    const wrap = $("#positions-body");
    const countEl = $("#positions-count");
    if (!wrap) return;
    if (countEl) countEl.textContent = `${positions ? positions.length : 0} open`;
    if (!positions || !positions.length) {
      wrap.innerHTML = `<div class="bot-empty">No open positions — bot is scanning 4H charts for setups.</div>`;
      return;
    }
    wrap.innerHTML = positions.map(p => {
      const isLong = p.direction === "long";
      const risk = Math.abs(p.entry - p.stop) || 1;
      // R-multiples
      const profitR = (isLong ? (p.current - p.entry) : (p.entry - p.current)) / risk;
      const stopBufR = (isLong ? (p.current - p.stop) : (p.stop - p.current)) / risk;
      const toTargetR = (isLong ? (p.target - p.current) : (p.current - p.target)) / risk;
      const plannedR = (isLong ? (p.target - p.entry) : (p.entry - p.target)) / risk;
      // progress to target (0..100)
      let prog = isLong ? (p.current - p.entry) / (p.target - p.entry) : (p.entry - p.current) / (p.entry - p.target);
      prog = Math.max(-30, Math.min(100, prog * 100));
      const pnlPos = p.unrealized_pnl >= 0;
      const sparkColor = pnlPos ? getCSS("--green") : getCSS("--red");

      return `<div class="pos-card">
        <div class="pos-card-top">
          <span class="pos-ticker num">${p.symbol}</span>
          <span class="pos-name">${p.name || ""}</span>
          <span class="pos-dir ${isLong ? "dir-long" : "dir-short"}">${isLong ? "LONG" : "SHORT"}</span>
          <span class="pos-lev num">${p.leverage}×</span>
          <span class="pos-strat-chip">${p.strategy}</span>
          <span class="pos-tf-chip">${p.bias_tf}→${p.entry_tf}</span>
          <button class="pos-close-btn" data-symbol="${p.symbol}">Close</button>
        </div>
        <div class="pos-body">
          <div class="pos-metrics">
            <div class="pos-metric"><span class="pos-metric-k">Entry</span><span class="pos-metric-v num">${px(p.entry)}</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Current</span><span class="pos-metric-v num">${px(p.current)}</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Size</span><span class="pos-metric-v num">${p.size}</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Stop</span><span class="pos-metric-v stop num">${px(p.stop)}</span><span class="pos-metric-sub num">${stopBufR.toFixed(1)}R buffer</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Target</span><span class="pos-metric-v target num">${px(p.target)}</span><span class="pos-metric-sub num">${toTargetR.toFixed(1)}R to go</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Risk at entry</span><span class="pos-metric-v num">${money(p.risk_usd, 0)}</span><span class="pos-metric-sub num">${p.risk_pct.toFixed(1)}% · ${plannedR.toFixed(1)}R plan</span></div>
          </div>
          <div class="pos-side">
            <div class="pos-pnl-box ${pnlPos ? "pos-pnl-green" : "pos-pnl-red"}">
              <div class="pos-pnl-val num">${pnlPos ? "+" : "−"}${money(Math.abs(p.unrealized_pnl), 0).replace("$", "$")}</div>
              <div class="pos-pnl-pct num">${pct(p.unrealized_pct)} · ${signed(profitR, 1)}R</div>
            </div>
            ${sparkline(p.sparkline, 130, 34, sparkColor)}
          </div>
        </div>
        <div class="pos-progress">
          <div class="pos-progress-track">
            <div class="pos-progress-fill ${prog >= 0 ? "green" : "red"}" style="width:${Math.abs(prog)}%"></div>
          </div>
          <div class="pos-progress-labels">
            <span class="pos-progress-lab stop">SL ${px(p.stop)}</span>
            <span class="pos-progress-lab num">${p.bars_4h} bars · ${fmtAge(p.opened_at)} open</span>
            <span class="pos-progress-lab target">TP ${px(p.target)}</span>
          </div>
        </div>
      </div>`;
    }).join("");

    $$(".pos-close-btn", wrap).forEach(btn => btn.addEventListener("click", () => {
      if (confirm(`Close ${btn.dataset.symbol}? (paper trade)`)) {
        btn.closest(".pos-card").style.opacity = "0.4";
        btn.disabled = true; btn.textContent = "Closing…";
        showToast(`Close order sent for ${btn.dataset.symbol}`, "ok");
      }
    }));
  }

  // ── Stats ──────────────────────────────────────────────────────────────────
  function renderStats(d) {
    const today = d.today; if (!today) return;
    // header equity
    const eq = d.equity || d.capital;
    const startEq = (d.equity_curve && d.equity_curve[0]) || d.capital;
    const chgPct = ((eq - startEq) / startEq) * 100;
    $("#bot-equity-val").textContent = moneyK(eq);
    $("#equity-now").textContent = moneyK(eq);
    const chgEl = $("#equity-chg");
    chgEl.textContent = pct(chgPct);
    chgEl.className = "equity-chg num " + (chgPct >= 0 ? "up" : "down");
    renderEquityCurve(d.equity_curve);

    const total = today.realized_pnl + today.unrealized_pnl;
    const winRate = today.trades_closed ? Math.round(today.wins / today.trades_closed * 100) : 0;
    const usedPct = today.daily_loss_limit ? Math.min(100, today.daily_loss_used / today.daily_loss_limit * 100) : 0;
    const barCls = usedPct > 80 ? "risk-bar-danger" : usedPct > 50 ? "risk-bar-warn" : "risk-bar-ok";
    const g = n => n >= 0 ? "stat-green" : "stat-red";

    $("#stats-grid").innerHTML = `
      <div class="stat-tile"><div class="stat-tile-label">Realized P&amp;L</div><div class="stat-tile-val num ${g(today.realized_pnl)}">${signed(today.realized_pnl).replace("+", "+$").replace("−", "−$")}</div><div class="stat-tile-sub">${today.trades_closed} closed</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Unrealized</div><div class="stat-tile-val num ${g(today.unrealized_pnl)}">${signed(today.unrealized_pnl).replace("+", "+$").replace("−", "−$")}</div><div class="stat-tile-sub">open trades</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Total P&amp;L</div><div class="stat-tile-val num ${g(total)}">${signed(total).replace("+", "+$").replace("−", "−$")}</div><div class="stat-tile-sub">realized + open</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Win Rate</div><div class="stat-tile-val num">${today.trades_closed ? winRate + "%" : "—"}</div><div class="stat-tile-sub">${today.wins}W · ${today.losses}L</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Best Trade</div><div class="stat-tile-val num stat-green">+${money(today.best_trade, 0)}</div><div class="stat-tile-sub">${today.best_symbol}</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Worst Trade</div><div class="stat-tile-val num stat-red">−${money(Math.abs(today.worst_trade), 0)}</div><div class="stat-tile-sub">${today.worst_symbol}</div></div>
      <div class="stat-tile stat-tile-wide"><div class="stat-tile-label">Daily Stop Used</div><div class="stat-risk-bar-wrap"><div class="stat-risk-bar ${barCls}" style="width:${usedPct}%"></div></div><div class="stat-tile-sub num">${money(today.daily_loss_used, 0)} of ${money(today.daily_loss_limit, 0)} · ${Math.round(usedPct)}%</div></div>`;
  }

  // ── Execution log ──────────────────────────────────────────────────────────
  function renderLog(log) {
    const wrap = $("#bot-log"); if (!wrap || !log) return;
    const map = { enter: "▶", signal: "◉", win: "✓", loss: "✗", kill: "⏻", system: "·", error: "⚠" };
    wrap.innerHTML = log.map(e => `<div class="log-row log-${e.type}">
      <span class="log-icon">${map[e.type] || "·"}</span>
      <span class="log-time num">${fmtTs(e.ts)}</span>
      <span class="log-msg">${e.msg}</span>
    </div>`).join("");
  }

  // ── Position sizing ────────────────────────────────────────────────────────
  function renderSizing(d, rules) {
    const sz = d.sizing || {};
    const eq = sz.equity || d.equity || d.capital;
    const riskPct = rules.risk_pct || sz.max_risk_pct || 2;
    const maxRisk = eq * riskPct / 100;
    $("#sz-equity").textContent = moneyK(eq);
    $("#sz-risk-pct").textContent = riskPct + "%";
    $("#sz-max-risk").textContent = money(maxRisk);
    $("#sz-open-risk").textContent = money(sz.open_risk_usd || 0, 0) + (sz.open_risk_pct ? ` · ${sz.open_risk_pct.toFixed(1)}%` : "");
    const budgetPct = sz.daily_budget_usd ? Math.min(100, sz.daily_budget_used / sz.daily_budget_usd * 100) : 0;
    const bar = $("#sz-budget-bar");
    bar.style.width = budgetPct + "%";
    bar.classList.toggle("over", budgetPct > 80);
    $("#sz-budget-sub").textContent = `${money(sz.daily_budget_used || 0, 0)} of ${money(sz.daily_budget_usd || 0, 0)} used`;
    updateSizeCalc(eq, riskPct);
  }

  function updateSizeCalc(equity, riskPct) {
    const inst = $("#sz-instrument").value;
    const spec = INSTRUMENTS[inst] || { ppt: 1 };
    const stopDist = Number($("#sz-stop-dist").value) || 1;
    const maxRisk = equity * riskPct / 100;
    const ppt = spec.ppt;
    $("#sz-ppt").textContent = "$" + ppt.toFixed(2);
    const rawSize = maxRisk / (stopDist * ppt);
    // CFD-style fractional lots: whole numbers when ≥1, else round to 0.1 lot
    const size = rawSize >= 1 ? Math.floor(rawSize * 10) / 10 : Math.max(0.1, Math.round(rawSize * 10) / 10);
    const actualRisk = size * stopDist * ppt;
    $("#sz-result").textContent = size % 1 === 0 ? size.toFixed(0) : size.toFixed(1);
    $("#sz-result-risk").textContent = money(actualRisk, 0);
    $("#sz-result-pct").textContent = (actualRisk / equity * 100).toFixed(2) + "%";
  }

  // ── Journal ────────────────────────────────────────────────────────────────
  let JOURNAL = [];
  function renderJournalSummary(s) {
    if (!s) return;
    $("#journal-summary").innerHTML = `
      <div class="jsum-tile"><div class="jsum-label">Win Rate</div><div class="jsum-val num">${s.win_rate}%</div></div>
      <div class="jsum-tile"><div class="jsum-label">Profit Factor</div><div class="jsum-val num">${s.profit_factor.toFixed(1)}</div></div>
      <div class="jsum-tile"><div class="jsum-label">Expectancy</div><div class="jsum-val num">${money(s.expectancy, 0)}</div></div>
      <div class="jsum-tile"><div class="jsum-label">Max Consec Losses</div><div class="jsum-val num">${s.max_consec_losses}</div></div>`;
  }

  function populateJournalFilters(journal) {
    const sel = $("#jf-instrument");
    const instruments = [...new Set(journal.map(t => t.symbol))];
    sel.innerHTML = `<option value="all">All instruments</option>` + instruments.map(s => `<option value="${s}">${s}</option>`).join("");
  }

  function filteredJournal() {
    const inst = $("#jf-instrument").value;
    const result = $("#jf-result").value;
    const period = $("#jf-period").value;
    // anchor "now" to the latest closed trade so period filters work on mock data
    const anchor = JOURNAL.reduce((mx, t) => Math.max(mx, new Date(t.closed).getTime()), 0) || Date.now();
    return JOURNAL.filter(t => {
      if (inst !== "all" && t.symbol !== inst) return false;
      if (result === "win" && !t.win) return false;
      if (result === "loss" && t.win) return false;
      if (period !== "all") {
        const days = Number(period);
        if (new Date(t.closed).getTime() < anchor - days * 86400000) return false;
      }
      return true;
    });
  }

  function renderJournalTable() {
    const rows = filteredJournal();
    const tbody = $("#journal-tbody");
    $("#journal-count").textContent = `${rows.length} trade${rows.length !== 1 ? "s" : ""}`;
    if (!rows.length) { tbody.innerHTML = `<tr><td colspan="13" class="lft" style="color:var(--muted);padding:24px">No trades match these filters.</td></tr>`; return; }
    tbody.innerHTML = rows.map(t => `<tr>
      <td class="lft jt-id">${t.id}</td>
      <td class="lft">${fmtDateShort(t.opened)}</td>
      <td>${t.duration}</td>
      <td class="lft">${t.symbol}</td>
      <td class="lft ${t.dir === "long" ? "jt-dir-long" : "jt-dir-short"}">${t.dir === "long" ? "L" : "S"}</td>
      <td>${px(t.entry)}</td>
      <td>${px(t.exit)}</td>
      <td>${t.size}</td>
      <td>${signed(t.gross, 0).replace("+", "+$").replace("−", "−$")}</td>
      <td>−${money(t.costs, 0)}</td>
      <td class="${t.net >= 0 ? "jt-net-pos" : "jt-net-neg"}">${signed(t.net, 0).replace("+", "+$").replace("−", "−$")}</td>
      <td class="jt-reason">${t.reason}</td>
      <td class="${t.r >= 0 ? "jt-r-pos" : "jt-r-neg"}">${signed(t.r, 1)}R</td>
    </tr>`).join("");
  }

  // ── Exports ────────────────────────────────────────────────────────────────
  const JCOLS = ["id", "opened", "closed", "duration", "symbol", "name", "dir", "entry", "exit", "size", "gross", "costs", "net", "reason", "r", "strategy"];
  const JHEAD = ["Trade ID", "Opened", "Closed", "Duration", "Instrument", "Name", "Direction", "Entry", "Exit", "Size", "Gross P/L", "Costs", "Net P/L", "Exit Reason", "R-Multiple", "Strategy"];

  function download(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 100);
  }

  function exportCSV() {
    const rows = filteredJournal();
    const lines = [JHEAD.join(",")];
    rows.forEach(t => lines.push(JCOLS.map(c => {
      const v = t[c] == null ? "" : String(t[c]);
      return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    }).join(",")));
    download(`bot_journal_${Date.now()}.csv`, lines.join("\n"), "text/csv;charset=utf-8");
    showToast("CSV exported.", "ok");
  }

  function exportExcel() {
    const rows = filteredJournal();
    const head = JHEAD.map(h => `<th style="background:#1c1c1e;color:#fff;padding:6px 10px;text-align:left;border:1px solid #444">${h}</th>`).join("");
    const body = rows.map(t => `<tr>${JCOLS.map(c => {
      const neg = (c === "net" || c === "r") && t[c] < 0;
      const pos = (c === "net" || c === "r") && t[c] > 0;
      const color = neg ? "color:#c00" : pos ? "color:#080" : "";
      return `<td style="padding:5px 10px;border:1px solid #ccc;${color}">${t[c] == null ? "" : t[c]}</td>`;
    }).join("")}</tr>`).join("");
    const html = `<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8"></head><body>
      <h3>Vivek's Beta Scanner — Bot Trade Journal</h3>
      <table style="border-collapse:collapse;font-family:Calibri,sans-serif;font-size:12px"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
    </body></html>`;
    download(`bot_journal_${Date.now()}.xls`, html, "application/vnd.ms-excel");
    showToast("Excel exported.", "ok");
  }

  function exportHTMLReport() {
    const rows = filteredJournal();
    const s = window.__JSUMMARY || {};
    const totalNet = rows.reduce((a, t) => a + t.net, 0);
    const head = JHEAD.slice(0, 15).map(h => `<th>${h}</th>`).join("");
    const body = rows.map(t => `<tr class="${t.net >= 0 ? "w" : "l"}">
      <td>${t.id}</td><td>${fmtDateShort(t.opened)}</td><td>${fmtDateShort(t.closed)}</td><td>${t.duration}</td>
      <td>${t.symbol}</td><td>${t.name}</td><td>${t.dir}</td><td>${px(t.entry)}</td><td>${px(t.exit)}</td>
      <td>${t.size}</td><td>${signed(t.gross, 0)}</td><td>${t.costs}</td><td class="${t.net >= 0 ? "pos" : "neg"}">${signed(t.net, 0)}</td>
      <td>${t.reason}</td><td class="${t.r >= 0 ? "pos" : "neg"}">${signed(t.r, 1)}R</td></tr>`).join("");
    const doc = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bot Trade Report</title>
      <style>
        body{font-family:-apple-system,Inter,sans-serif;background:#0a0a0c;color:#e8e8ea;padding:32px;max-width:1100px;margin:0 auto}
        h1{font-size:20px;margin:0 0 4px} .sub{color:#888;font-size:13px;margin-bottom:24px}
        .summary{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:24px}
        .card{background:#1c1c1e;border-radius:10px;padding:14px}
        .card .k{font-size:10px;letter-spacing:.06em;color:#888;text-transform:uppercase} .card .v{font-size:20px;font-weight:700;margin-top:6px;font-family:monospace}
        table{width:100%;border-collapse:collapse;font-size:12px;font-family:monospace}
        th{text-align:left;padding:8px;border-bottom:1px solid #333;color:#888;font-size:10px;text-transform:uppercase}
        td{padding:7px 8px;border-bottom:1px solid #222}
        .pos{color:#30d158} .neg{color:#ff453a}
        tr.w td:first-child{border-left:2px solid #30d158} tr.l td:first-child{border-left:2px solid #ff453a}
        @media print{body{background:#fff;color:#000}.card{background:#f2f2f2}}
        .pbtn{margin-bottom:20px;padding:9px 16px;border:none;border-radius:8px;background:#0a84ff;color:#fff;cursor:pointer;font-weight:600}
      </style></head><body>
      <button class="pbtn" onclick="window.print()">🖨 Print / Save PDF</button>
      <h1>Vivek's Beta Scanner — Bot Trade Report</h1>
      <div class="sub">Generated ${new Date().toLocaleString("en-AU")} · ${rows.length} trades</div>
      <div class="summary">
        <div class="card"><div class="k">Win Rate</div><div class="v">${s.win_rate || "—"}%</div></div>
        <div class="card"><div class="k">Profit Factor</div><div class="v">${s.profit_factor ? s.profit_factor.toFixed(1) : "—"}</div></div>
        <div class="card"><div class="k">Expectancy</div><div class="v">${money(s.expectancy || 0, 0)}</div></div>
        <div class="card"><div class="k">Max Consec L</div><div class="v">${s.max_consec_losses || "—"}</div></div>
        <div class="card"><div class="k">Net P/L</div><div class="v ${totalNet >= 0 ? "pos" : "neg"}">${signed(totalNet, 0)}</div></div>
      </div>
      <table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
      </body></html>`;
    const w = window.open("", "_blank");
    if (w) { w.document.write(doc); w.document.close(); showToast("HTML report opened.", "ok"); }
    else { download(`bot_report_${Date.now()}.html`, doc, "text/html"); showToast("Report downloaded.", "ok"); }
  }

  // ── Rules form ─────────────────────────────────────────────────────────────
  function populateRulesForm(r) {
    $$("[data-market]").forEach(el => el.checked = r.markets.includes(el.dataset.market));
    $$("[data-strat]").forEach(el => el.checked = r.strategies.includes(el.dataset.strat));
    const set = (id, v) => { const el = $(id); if (el) el.value = v; };
    set("#rule-min-rr", r.min_rr); set("#rule-bias", r.bias);
    set("#rule-risk-pct", r.risk_pct); set("#rule-loss-limit", r.loss_limit);
    set("#rule-max-positions", r.max_positions);
    $("#rule-scanner-targets").checked = r.use_scanner_targets;
    $("#rule-trail-st").checked = r.trail_supertrend;
    $("#rule-be-1r").checked = r.be_1r;
    $("#rule-bias-tf").textContent = r.bias_tf || "Daily";
    $("#rule-entry-tf").textContent = r.entry_tf || "4H";
  }
  function collectRules() {
    const markets = $$("[data-market]").filter(e => e.checked).map(e => e.dataset.market);
    const strategies = $$("[data-strat]").filter(e => e.checked).map(e => e.dataset.strat);
    const g = (id, p = v => v) => { const el = $(id); return el ? p(el.value) : null; };
    return {
      markets: markets.length ? markets : ["NAS100"],
      strategies: strategies.length ? strategies : ["trend_pullback"],
      bias_tf: "Daily", entry_tf: "4H",
      min_rr: g("#rule-min-rr", Number), bias: g("#rule-bias"),
      risk_pct: g("#rule-risk-pct", Number), loss_limit: g("#rule-loss-limit", Number),
      max_positions: g("#rule-max-positions", Number),
      use_scanner_targets: $("#rule-scanner-targets").checked,
      trail_supertrend: $("#rule-trail-st").checked,
      be_1r: $("#rule-be-1r").checked,
    };
  }

  // ── Toast ──────────────────────────────────────────────────────────────────
  function showToast(msg, kind = "ok") {
    let el = $("#bot-toast");
    if (!el) { el = document.createElement("div"); el.id = "bot-toast"; document.body.appendChild(el); }
    el.textContent = msg;
    el.className = `bot-toast bot-toast-${kind} bot-toast-show`;
    clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("bot-toast-show"), 3000);
  }

  // ── Kill switch modal ──────────────────────────────────────────────────────
  function openKillModal(posCount) {
    $("#kill-modal-poscount").textContent = posCount;
    $("#kill-modal").classList.add("show");
  }
  function closeKillModal() { $("#kill-modal").classList.remove("show"); }

  function activateKill(action, reason) {
    const actionLabel = action === "close" ? "Closed all positions" : "Left positions to stops";
    const k = {
      active: true,
      reason: reason || "manual",
      action: actionLabel,
      ts: new Date().toISOString(),
      last_event: { ts: new Date().toISOString(), reason: reason || "manual", action: actionLabel },
    };
    setKill(k);
    renderKill();
    // log it
    prependLog({ ts: new Date().toISOString(), type: "kill", msg: `KILL SWITCH (${reason || "manual"}) — ${actionLabel} · trading disabled` });
    showToast("Kill switch activated — trading disabled.", "err");
  }
  function resetKill() {
    const k = getKill();
    k.active = false; k.reason = null;
    setKill(k);
    renderKill();
    prependLog({ ts: new Date().toISOString(), type: "system", msg: "Kill switch reset — trading re-enabled" });
    showToast("Kill switch reset — trading re-enabled.", "ok");
  }

  let LOG = [];
  function prependLog(entry) { LOG.unshift(entry); renderLog(LOG); }

  // ── Boot ───────────────────────────────────────────────────────────────────
  let RULES = loadRules();

  async function init() {
    RULES = loadRules();
    populateRulesForm(RULES);

    // rules buttons
    $("#rules-save-btn").addEventListener("click", () => { RULES = collectRules(); saveRules(RULES); populateRulesForm(RULES); applyRulesToUI(); showToast("Rules saved.", "ok"); });
    $("#rules-reset-btn").addEventListener("click", () => { if (confirm("Reset all rules to defaults?")) { RULES = { ...DEFAULT_RULES }; saveRules(RULES); populateRulesForm(RULES); applyRulesToUI(); showToast("Rules reset.", "ok"); } });

    // risk reset
    $("#risk-reset-btn").addEventListener("click", () => {
      if (confirm("Reset the consecutive-loss counter to 0?\n\nThis is a hard safety rule — only reset if you've reviewed why the losses happened.")) {
        setCounter(0); renderRiskStatus({ consecutive_losses: 0, hard_limit: RULES.loss_limit }, RULES);
        prependLog({ ts: new Date().toISOString(), type: "system", msg: "Consecutive-loss counter manually reset to 0" });
        showToast("Loss counter reset.", "ok");
      }
    });
    $("#risk-banner-reset").addEventListener("click", () => $("#risk-reset-btn").click());

    // bot toggle
    $("#bot-toggle").addEventListener("click", () => {
      const btn = $("#bot-toggle");
      const paused = btn.classList.toggle("is-paused");
      btn.classList.toggle("is-running", !paused);
      btn.textContent = paused ? "▶ START BOT" : "⏸ PAUSE BOT";
      prependLog({ ts: new Date().toISOString(), type: "system", msg: paused ? "Bot paused — no new entries" : "Bot resumed — scanning for entries" });
      showToast(paused ? "Bot paused." : "Bot running.", paused ? "warn" : "ok");
    });

    // kill switch modal flow
    $("#kill-btn").addEventListener("click", () => {
      if (getKill().active) { if (confirm("Kill switch is active. Reset and re-enable trading?")) resetKill(); return; }
      openKillModal(($("#positions-body").querySelectorAll(".pos-card") || []).length || 0);
    });
    $("#kill-cancel").addEventListener("click", closeKillModal);
    $("#kill-modal").addEventListener("click", e => { if (e.target.id === "kill-modal") closeKillModal(); });
    $("#kill-confirm").addEventListener("click", () => {
      const action = ($('input[name="kill-action"]:checked') || {}).value || "close";
      const reason = $("#kill-reason").value.trim();
      closeKillModal();
      activateKill(action, reason);
      if (action === "close") {
        $$("#positions-body .pos-card").forEach(c => c.style.opacity = "0.35");
      }
    });
    $("#kill-banner-reset").addEventListener("click", () => { if (confirm("Reset kill switch and re-enable trading?")) resetKill(); });

    // sizing calc live
    $("#sz-instrument").addEventListener("change", () => updateSizeCalc(window.__EQ || 10000, RULES.risk_pct));
    $("#sz-stop-dist").addEventListener("input", () => updateSizeCalc(window.__EQ || 10000, RULES.risk_pct));

    // journal filters + exports
    ["#jf-instrument", "#jf-result", "#jf-period"].forEach(id => $(id).addEventListener("change", renderJournalTable));
    $("#export-csv").addEventListener("click", exportCSV);
    $("#export-xls").addEventListener("click", exportExcel);
    $("#export-html").addEventListener("click", exportHTMLReport);

    await loadData();
    setInterval(loadData, 30000);
    startClocks();
  }

  function applyRulesToUI() {
    $("#sz-risk-pct").textContent = RULES.risk_pct + "%";
    $("#risk-limit").textContent = RULES.loss_limit;
    renderRiskStatus({ consecutive_losses: getCounter(0), hard_limit: RULES.loss_limit }, RULES);
    if (window.__DATA) renderSizing(window.__DATA, RULES);
  }

  async function loadData() {
    try {
      const r = await fetch("data/bot_status.json", { cache: "no-cache" });
      if (!r.ok) throw new Error("no data");
      const d = await r.json();
      window.__DATA = d;
      window.__EQ = d.equity || d.capital;
      window.__JSUMMARY = d.journal_summary;
      JOURNAL = d.journal || [];
      LOG = d.log || [];

      renderConnections(d.connections);
      renderRiskStatus(d.risk_status || {}, RULES);
      renderKill(d.kill_switch);
      renderPositions(d.positions);
      renderStats(d);
      renderLog(LOG);
      renderSizing(d, RULES);
      renderJournalSummary(d.journal_summary);
      populateJournalFilters(JOURNAL);
      renderJournalTable();
    } catch (e) {
      showToast("Bot data unavailable — showing empty state.", "warn");
      renderPositions([]); renderLog([]);
    }
  }

  function startClocks() {
    function tick() {
      const now = new Date();
      const t = (tz) => now.toLocaleTimeString("en-AU", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
      const dt = (tz) => now.toLocaleDateString("en-AU", { timeZone: tz, weekday: "short", day: "numeric", month: "short" });
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      set("clk-mel-time", t("Australia/Sydney")); set("clk-mel-date", dt("Australia/Sydney"));
      set("clk-ny-time", t("America/New_York")); set("clk-ny-date", dt("America/New_York"));
    }
    tick(); setInterval(tick, 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();

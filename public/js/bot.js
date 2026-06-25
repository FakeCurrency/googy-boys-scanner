/* AI Bot dashboard — Vivek's Beta Scanner */
(function () {
  "use strict";

  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
  const fmt = (n, dec = 2) => n == null ? "—" : Number(n).toLocaleString("en-AU", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const fmtK = n => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(0) + "K" : n.toFixed(0);
  const RULES_KEY = "gbs_bot_rules_v1";

  // ── Default rules ──────────────────────────────────────────────────────────
  const DEFAULT_RULES = {
    scans: ["googy", "scalp"],
    markets: ["crypto"],
    min_grade: "A+",
    min_score: 8,
    min_rr: 1.5,
    position_size: 1000,
    leverage: 5,
    max_positions: 3,
    daily_stop: 500,
    entry_timing: "signal",
    use_scanner_targets: true,
    trail_supertrend: true,
  };

  function loadRules() {
    try { return JSON.parse(localStorage.getItem(RULES_KEY)) || DEFAULT_RULES; }
    catch (_) { return DEFAULT_RULES; }
  }
  function saveRules(rules) {
    localStorage.setItem(RULES_KEY, JSON.stringify(rules));
  }

  // ── Format ISO timestamp ───────────────────────────────────────────────────
  function fmtTs(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Australia/Sydney" });
    } catch (_) { return iso; }
  }

  function fmtAge(iso) {
    if (!iso) return "";
    const secs = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (secs < 60) return `${secs}s`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m`;
    return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
  }

  // ── Render status bar ──────────────────────────────────────────────────────
  function renderStatusBar(d) {
    const statusMap = {
      paper: { label: "PAPER TRADING", cls: "paper" },
      testnet: { label: "TESTNET", cls: "testnet" },
      live: { label: "LIVE ⚠", cls: "live" },
      paused: { label: "PAUSED", cls: "paused" },
      stopped: { label: "STOPPED", cls: "stopped" },
      offline: { label: "OFFLINE", cls: "offline" },
    };
    const s = statusMap[d.status] || statusMap.offline;
    const bar = $("#bot-status-bar");
    if (!bar) return;
    bar.dataset.status = d.status;
    $("#bot-status-mode").textContent = s.label;
    $("#bot-status-mode").className = `bot-mode-badge bot-mode-${s.cls}`;
    $("#bot-broker-label").textContent = d.broker || "—";
    $("#bot-capital-label").textContent = `$${fmtK(d.capital)} capital`;
    const toggle = $("#bot-toggle");
    if (toggle) {
      const isPaused = d.status === "paused" || d.status === "stopped";
      toggle.textContent = isPaused ? "▶ START BOT" : "⏸ PAUSE BOT";
      toggle.className = "bot-action-btn " + (isPaused ? "bot-btn-start" : "bot-btn-pause");
    }
  }

  // ── Render open positions ──────────────────────────────────────────────────
  function renderPositions(positions) {
    const wrap = $("#positions-body");
    if (!wrap) return;
    if (!positions || !positions.length) {
      wrap.innerHTML = `<div class="bot-empty">No open positions — bot is watching for signals.</div>`;
      return;
    }
    wrap.innerHTML = positions.map(p => {
      const isLong = p.direction === "long";
      const pnlCls = p.unrealized_pnl >= 0 ? "pos-pnl-green" : "pos-pnl-red";
      const dirCls = isLong ? "dir-long" : "dir-short";
      const age = fmtAge(p.opened_at);
      const entryFmt = p.entry >= 1000 ? fmt(p.entry, 0) : fmt(p.entry, 2);
      const curFmt = p.current >= 1000 ? fmt(p.current, 0) : fmt(p.current, 2);
      const stopFmt = p.stop >= 1000 ? fmt(p.stop, 0) : fmt(p.stop, 2);
      const tgtFmt = p.target >= 1000 ? fmt(p.target, 0) : fmt(p.target, 2);
      const pnlSign = p.unrealized_pnl >= 0 ? "+" : "";
      return `<div class="pos-row">
        <div class="pos-header">
          <span class="pos-symbol">${p.symbol}</span>
          <span class="pos-dir ${dirCls}">${isLong ? "LONG" : "SHORT"}</span>
          <span class="pos-badge">${p.scan.toUpperCase()}</span>
          <span class="pos-badge pos-grade-${p.grade.toLowerCase().replace("+","plus")}">${p.grade} · ${p.score}</span>
          <span class="pos-age">${age}</span>
          <button class="pos-close-btn" data-symbol="${p.symbol}" title="Close position">Close</button>
        </div>
        <div class="pos-levels">
          <div class="pos-level-item">
            <span class="pos-level-label">Entry</span>
            <span class="pos-level-val">$${entryFmt}</span>
          </div>
          <div class="pos-level-item">
            <span class="pos-level-label">Current</span>
            <span class="pos-level-val">${curFmt !== entryFmt ? "$" + curFmt : "—"}</span>
          </div>
          <div class="pos-level-item">
            <span class="pos-level-label">Stop</span>
            <span class="pos-level-val stop-val">$${stopFmt}</span>
          </div>
          <div class="pos-level-item">
            <span class="pos-level-label">Target</span>
            <span class="pos-level-val target-val">$${tgtFmt}</span>
          </div>
          <div class="pos-level-item">
            <span class="pos-level-label">R:R</span>
            <span class="pos-level-val">${p.rr}:1</span>
          </div>
          <div class="pos-level-item">
            <span class="pos-level-label">Leverage</span>
            <span class="pos-level-val">${p.leverage}×</span>
          </div>
        </div>
        <div class="pos-pnl ${pnlCls}">
          <span class="pos-pnl-val">${pnlSign}$${fmt(Math.abs(p.unrealized_pnl), 2)}</span>
          <span class="pos-pnl-pct">${pnlSign}${fmt(Math.abs(p.unrealized_pct), 2)}%</span>
          <span class="pos-pnl-note">unrealized · ${p.size_usd ? `$${p.size_usd} margin` : ""}</span>
        </div>
      </div>`;
    }).join("");

    // wire up close buttons
    $$(".pos-close-btn", wrap).forEach(btn => {
      btn.addEventListener("click", () => {
        if (confirm(`Close ${btn.dataset.symbol} position? This is a paper trade.`)) {
          btn.closest(".pos-row").style.opacity = "0.4";
          btn.disabled = true;
          btn.textContent = "Closing…";
          showToast(`Close order sent for ${btn.dataset.symbol}`, "ok");
        }
      });
    });
  }

  // ── Render stats ───────────────────────────────────────────────────────────
  function renderStats(today) {
    if (!today) return;
    const realizedCls = today.realized_pnl >= 0 ? "stat-green" : "stat-red";
    const totalPnl = today.realized_pnl + today.unrealized_pnl;
    const totalCls = totalPnl >= 0 ? "stat-green" : "stat-red";
    const sign = n => n >= 0 ? "+" : "";
    const pct = today.daily_loss_limit > 0 ? Math.min(100, (today.daily_loss_used / today.daily_loss_limit) * 100) : 0;
    const barCls = pct > 80 ? "risk-bar-danger" : pct > 50 ? "risk-bar-warn" : "risk-bar-ok";
    const winRate = today.trades_closed > 0 ? Math.round(today.wins / today.trades_closed * 100) : 0;

    const el = $("#stats-panel");
    if (!el) return;
    el.innerHTML = `
      <div class="stat-tile">
        <div class="stat-tile-label">Realized P&amp;L</div>
        <div class="stat-tile-val ${realizedCls}">${sign(today.realized_pnl)}$${fmt(Math.abs(today.realized_pnl))}</div>
        <div class="stat-tile-sub">${today.trades_closed} trade${today.trades_closed !== 1 ? "s" : ""} closed</div>
      </div>
      <div class="stat-tile">
        <div class="stat-tile-label">Unrealized P&amp;L</div>
        <div class="stat-tile-val ${today.unrealized_pnl >= 0 ? "stat-green" : "stat-red"}">${sign(today.unrealized_pnl)}$${fmt(Math.abs(today.unrealized_pnl))}</div>
        <div class="stat-tile-sub">open positions</div>
      </div>
      <div class="stat-tile">
        <div class="stat-tile-label">Total P&amp;L</div>
        <div class="stat-tile-val ${totalCls}">${sign(totalPnl)}$${fmt(Math.abs(totalPnl))}</div>
        <div class="stat-tile-sub">realized + unrealized</div>
      </div>
      <div class="stat-tile">
        <div class="stat-tile-label">Win Rate</div>
        <div class="stat-tile-val">${today.trades_closed ? `${winRate}%` : "—"}</div>
        <div class="stat-tile-sub">${today.wins}W · ${today.losses}L</div>
      </div>
      <div class="stat-tile">
        <div class="stat-tile-label">Best Trade</div>
        <div class="stat-tile-val stat-green">+$${fmt(today.best_trade)}</div>
        <div class="stat-tile-sub">${today.best_symbol}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-tile-label">Worst Trade</div>
        <div class="stat-tile-val stat-red">−$${fmt(Math.abs(today.worst_trade))}</div>
        <div class="stat-tile-sub">${today.worst_symbol}</div>
      </div>
      <div class="stat-tile stat-tile-wide">
        <div class="stat-tile-label">Daily Stop Used</div>
        <div class="stat-risk-bar-wrap">
          <div class="stat-risk-bar ${barCls}" style="width:${pct}%"></div>
        </div>
        <div class="stat-tile-sub">$${fmt(today.daily_loss_used, 0)} of $${fmt(today.daily_loss_limit, 0)} limit · ${Math.round(pct)}% used</div>
      </div>`;
  }

  // ── Render execution log ───────────────────────────────────────────────────
  function renderLog(log) {
    const wrap = $("#bot-log");
    if (!wrap || !log) return;
    const typeMap = {
      enter: { cls: "log-enter", icon: "▶" },
      signal: { cls: "log-signal", icon: "◉" },
      win: { cls: "log-win", icon: "✓" },
      loss: { cls: "log-loss", icon: "✗" },
      system: { cls: "log-system", icon: "·" },
      error: { cls: "log-error", icon: "⚠" },
    };
    wrap.innerHTML = log.map(entry => {
      const t = typeMap[entry.type] || typeMap.system;
      return `<div class="log-row ${t.cls}">
        <span class="log-icon">${t.icon}</span>
        <span class="log-time">${fmtTs(entry.ts)}</span>
        <span class="log-msg">${entry.msg}</span>
      </div>`;
    }).join("");
  }

  // ── Rules form ─────────────────────────────────────────────────────────────
  function populateRulesForm(rules) {
    // Scan checkboxes
    $$("[data-scan]").forEach(el => {
      el.checked = rules.scans.includes(el.dataset.scan);
    });
    // Market checkboxes
    $$("[data-market]").forEach(el => {
      el.checked = rules.markets.includes(el.dataset.market);
    });
    // Selects / inputs
    const set = (id, val) => { const el = $(id); if (el) el.value = val; };
    set("#rule-min-grade", rules.min_grade);
    set("#rule-min-score", rules.min_score);
    set("#rule-min-rr", rules.min_rr);
    set("#rule-size", rules.position_size);
    set("#rule-leverage", rules.leverage);
    set("#rule-max-positions", rules.max_positions);
    set("#rule-daily-stop", rules.daily_stop);
    set("#rule-entry-timing", rules.entry_timing);
    const scanTargets = $("#rule-scanner-targets");
    if (scanTargets) scanTargets.checked = rules.use_scanner_targets;
    const trailST = $("#rule-trail-st");
    if (trailST) trailST.checked = rules.trail_supertrend;
  }

  function collectRulesFromForm() {
    const scans = $$("[data-scan]").filter(el => el.checked).map(el => el.dataset.scan);
    const markets = $$("[data-market]").filter(el => el.checked).map(el => el.dataset.market);
    const get = (id, parse = v => v) => { const el = $(id); return el ? parse(el.value) : null; };
    return {
      scans: scans.length ? scans : ["googy"],
      markets: markets.length ? markets : ["crypto"],
      min_grade: get("#rule-min-grade"),
      min_score: get("#rule-min-score", Number),
      min_rr: get("#rule-min-rr", Number),
      position_size: get("#rule-size", Number),
      leverage: get("#rule-leverage", Number),
      max_positions: get("#rule-max-positions", Number),
      daily_stop: get("#rule-daily-stop", Number),
      entry_timing: get("#rule-entry-timing"),
      use_scanner_targets: $("#rule-scanner-targets")?.checked ?? true,
      trail_supertrend: $("#rule-trail-st")?.checked ?? true,
    };
  }

  // ── Toast ──────────────────────────────────────────────────────────────────
  function showToast(msg, kind = "ok") {
    let el = $("#bot-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "bot-toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = `bot-toast bot-toast-${kind} bot-toast-show`;
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove("bot-toast-show"), 3000);
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  async function init() {
    const rules = loadRules();
    populateRulesForm(rules);

    // Save rules button
    const saveBtn = $("#rules-save-btn");
    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        const r = collectRulesFromForm();
        saveRules(r);
        showToast("Rules saved.", "ok");
      });
    }

    // Reset rules button
    const resetBtn = $("#rules-reset-btn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        if (confirm("Reset all rules to defaults?")) {
          saveRules(DEFAULT_RULES);
          populateRulesForm(DEFAULT_RULES);
          showToast("Rules reset to defaults.", "ok");
        }
      });
    }

    // Kill switch
    const killBtn = $("#kill-btn");
    if (killBtn) {
      killBtn.addEventListener("click", () => {
        if (confirm("⚠ KILL SWITCH: This will immediately flatten ALL open positions. Are you sure?")) {
          killBtn.textContent = "Flattening…";
          killBtn.disabled = true;
          showToast("Kill switch activated — all positions closing.", "warn");
          setTimeout(() => {
            killBtn.textContent = "⚠ KILL SWITCH";
            killBtn.disabled = false;
          }, 3000);
        }
      });
    }

    // Bot toggle
    const toggleBtn = $("#bot-toggle");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        showToast("Bot control not yet wired to live broker.", "warn");
      });
    }

    // Load mock data
    try {
      const r = await fetch("data/bot_status.json", { cache: "no-cache" });
      if (!r.ok) throw new Error("no data");
      const d = await r.json();
      renderStatusBar(d);
      renderPositions(d.positions);
      renderStats(d.today);
      renderLog(d.log);
    } catch (_) {
      showToast("Bot data unavailable — showing mock state.", "warn");
      renderStatusBar({ status: "offline", broker: "Not connected", capital: 0 });
      renderPositions([]);
      renderLog([]);
    }

    // Poll every 30s
    setInterval(async () => {
      try {
        const r = await fetch("data/bot_status.json", { cache: "no-cache" });
        if (!r.ok) return;
        const d = await r.json();
        renderStatusBar(d);
        renderPositions(d.positions);
        renderStats(d.today);
      } catch (_) {}
    }, 30000);

    // Live clocks
    function updateClocks() {
      const now = new Date();
      const melOpts = { timeZone: "Australia/Sydney", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
      const nyOpts  = { timeZone: "America/New_York",  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
      const dateOpts = { timeZone: "Australia/Sydney", weekday: "short", day: "numeric", month: "short" };
      const el = (id) => document.getElementById(id);
      if (el("clk-mel-time")) el("clk-mel-time").textContent = now.toLocaleTimeString("en-AU", melOpts);
      if (el("clk-mel-date")) el("clk-mel-date").textContent = now.toLocaleDateString("en-AU", dateOpts);
      if (el("clk-ny-time"))  el("clk-ny-time").textContent  = now.toLocaleTimeString("en-AU", nyOpts);
      if (el("clk-ny-date"))  el("clk-ny-date").textContent  = now.toLocaleDateString("en-AU", { timeZone: "America/New_York", weekday: "short", day: "numeric", month: "short" });
    }
    updateClocks();
    setInterval(updateClocks, 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();

/* AI Bot terminal — Vivek's Beta Scanner
   Swing-trading dashboard. Risk logic is owned by the RiskManager engine
   (risk_manager.js); this file is the view/binding layer only. */
(function () {
  "use strict";

  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const RULES_KEY = "gbs_bot_rules_v2";

  // ── The risk engine. Single source of truth for risk state. ────────────────
  // Created in init() once we know equity; bot.js never touches localStorage
  // for risk/kill state — it all goes through `risk`.
  let risk = null;

  // Last-resort equity ONLY if bot_status.json can't be fetched on boot (e.g.
  // offline first load). The real starting equity always comes from the feed
  // (d.equity / d.capital) — see init() which fetches it BEFORE constructing
  // the engine so we never run on a hardcoded number when data is available.
  const FALLBACK_EQUITY = 10000;
  const STATUS_URL = "data/bot_status.json";

  // Sizing-calculator instrument list (engine resolves aliases like YM→/YM).
  const CALC_INSTRUMENTS = ["/NQ", "YM", "GC", "SI", "CL", "NG"];

  // ── Default rules ──────────────────────────────────────────────────────────
  const DEFAULT_RULES = {
    markets: ["NAS100", "US30", "XAU", "CL"],
    strategies: ["trend_pullback"],
    bias_tf: "Weekly+3D", entry_tf: "H4",
    min_rr: 2, bias: "weekly_3d",
    risk_pct: 0.25, loss_limit: 3, max_positions: 5,
    leverage: 2.5,
    use_scanner_targets: true, trail_supertrend: true,
    scale_out_tp1: true, be_after_tp1: true, multi_entry: true,
  };
  const loadRules = () => { try { return { ...DEFAULT_RULES, ...JSON.parse(localStorage.getItem(RULES_KEY)) }; } catch (_) { return { ...DEFAULT_RULES }; } };
  const saveRules = r => localStorage.setItem(RULES_KEY, JSON.stringify(r));

  // ── Formatting helpers ─────────────────────────────────────────────────────
  const money = (n, dec = 2) => n == null ? "—" : (n < 0 ? "−" : "") + "$" + Math.abs(n).toLocaleString("en-AU", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const moneyK = n => n == null ? "—" : "$" + n.toLocaleString("en-AU", { maximumFractionDigits: 0 });
  const px = (v) => v == null ? "—" : v >= 1000 ? v.toLocaleString("en-AU", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : v.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const signed = (n, dec = 2) => (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(dec);
  const pct = n => (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(2) + "%";

  function fmtTs(iso) { if (!iso) return "—"; try { return new Date(iso).toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Australia/Sydney" }); } catch (_) { return iso; } }
  function fmtDateShort(iso) { if (!iso) return "—"; try { return new Date(iso).toLocaleString("en-AU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Australia/Sydney" }); } catch (_) { return iso; } }
  function fmtAge(iso) { if (!iso) return ""; const s = Math.floor((Date.now() - new Date(iso)) / 1000); if (s < 0) return "just now"; if (s < 3600) return `${Math.floor(s / 60)}m`; const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h < 24 ? `${h}h ${m}m` : `${Math.floor(h / 24)}d ${h % 24}h`; }
  function fmtDuration(ms) { if (ms == null || !Number.isFinite(ms) || ms < 0) return "—"; const mins = Math.round(ms / 60000); if (mins < 60) return `${mins}m`; const h = Math.floor(mins / 60), m = mins % 60; return h < 24 ? `${h}h ${m}m` : `${Math.floor(h / 24)}d ${h % 24}h`; }

  // Recompute the journal summary tiles live from the JOURNAL array so a trade
  // closed through the engine updates win-rate / profit-factor / expectancy /
  // max-consecutive-losses immediately (not just the static seed from JSON).
  function computeJournalSummary(trades) {
    if (!trades || !trades.length) return { win_rate: 0, profit_factor: 0, expectancy: 0, max_consec_losses: 0, period_trades: 0 };
    const wins = trades.filter(t => t.net > 0), losses = trades.filter(t => t.net <= 0);
    const grossWin = wins.reduce((a, t) => a + t.net, 0);
    const grossLoss = Math.abs(losses.reduce((a, t) => a + t.net, 0));
    // max consecutive losses across the (closed-desc) journal
    const chrono = [...trades].sort((a, b) => new Date(a.closed) - new Date(b.closed));
    let run = 0, maxRun = 0;
    chrono.forEach(t => { if (t.net <= 0) { run += 1; maxRun = Math.max(maxRun, run); } else run = 0; });
    return {
      win_rate: Math.round(wins.length / trades.length * 100),
      profit_factor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? 99 : 0),
      expectancy: trades.reduce((a, t) => a + t.net, 0) / trades.length,
      max_consec_losses: maxRun,
      period_trades: trades.length,
    };
  }

  // ── SVG sparkline / equity curve ───────────────────────────────────────────
  function sparkline(vals, w, h, color) {
    if (!vals || vals.length < 2) return "";
    const min = Math.min(...vals), max = Math.max(...vals), range = max - min || 1;
    const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - ((v - min) / range) * (h - 4) - 2).toFixed(1)}`).join(" ");
    return `<svg class="pos-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }
  const getCSS = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#34c759";
  function renderEquityCurve(curve) {
    const svg = $("#equity-svg"); if (!svg || !curve || curve.length < 2) return;
    const w = 300, h = 70, min = Math.min(...curve), max = Math.max(...curve), range = max - min || 1;
    const up = curve[curve.length - 1] >= curve[0], color = up ? getCSS("--green") : getCSS("--red");
    const pts = curve.map((v, i) => [(i / (curve.length - 1)) * w, h - ((v - min) / range) * (h - 8) - 4]);
    const line = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.innerHTML = `<defs><linearGradient id="eqgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity="0.22"/><stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><polygon points="0,${h} ${line} ${w},${h}" fill="url(#eqgrad)"/><polyline points="${line}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/>`;
  }

  // ── Connections ────────────────────────────────────────────────────────────
  function renderConnections(conns) {
    const wrap = $("#bot-conn-group"); if (!wrap || !conns) return;
    wrap.innerHTML = ["mode", "bybit", "ibkr"].filter(k => conns[k]).map(k => {
      const c = conns[k];
      return `<div class="bot-conn conn-${c.state}"><span class="bot-conn-dot"></span><span class="bot-conn-text"><span class="bot-conn-label">${c.label}</span><span class="bot-conn-detail">${c.detail}</span></span></div>`;
    }).join("");
  }

  /* ===========================================================================
     RISK UI — bound to the engine via risk.subscribe(renderRiskUI).
     Renders counter, pips, banners, kill state, entry-gate, sizing readouts and
     disables/enables the "Attempt Entry" control. Pure render off engine state.
     =========================================================================== */
  function renderRiskUI(state) {
    if (!state) return;
    const count = state.consecutiveLossCount, limit = state.maxConsecutiveLosses;

    // counter + meta
    $("#risk-counter").textContent = count;
    $("#risk-limit").textContent = limit;
    $("#risk-health-meta").textContent = state.isKillSwitchActive ? "KILL" : state.isPausedByLosses ? "PAUSED" : state.isWarning ? "Warning" : "Healthy";

    // pips
    const pipsWrap = $("#risk-pips"); pipsWrap.innerHTML = "";
    for (let i = 0; i < limit; i++) {
      const pip = document.createElement("div"); pip.className = "risk-pip";
      if (i < count) pip.classList.add(`filled-${count >= limit ? 3 : count >= limit - 1 ? 2 : 1}`);
      pipsWrap.appendChild(pip);
    }

    // status message + card accent
    const card = $("#risk-status-card"), msg = $("#risk-status-msg");
    card.classList.remove("is-warn", "is-danger");
    if (state.isPausedByLosses) { msg.className = "risk-status-msg danger"; msg.textContent = "Trading paused — new entries blocked."; card.classList.add("is-danger"); }
    else if (state.isWarning) { msg.className = "risk-status-msg warn"; msg.textContent = "One more loss will pause new entries."; card.classList.add("is-warn"); }
    else { msg.className = "risk-status-msg healthy"; msg.textContent = "Trading normally."; }

    $("#risk-reset-btn").classList.toggle("show", count > 0);

    // ── Entry-gate pill + "Attempt Entry" enable/disable ──────────────────
    const pill = $("#entry-gate-pill");
    if (pill) {
      if (state.canEnter) { pill.textContent = "ENTRIES ALLOWED"; pill.className = "entry-gate-pill allowed"; }
      else { pill.textContent = "ENTRIES BLOCKED · " + (state.blockReason || ""); pill.className = "entry-gate-pill blocked"; }
    }
    const attempt = $("#attempt-entry");
    if (attempt) { attempt.disabled = !state.canEnter; attempt.title = state.canEnter ? "Try a new entry" : state.blockReason; }

    // bot toggle: when entries are blocked, a "resume" must not imply entries
    const toggle = $("#bot-toggle");
    if (toggle && !state.canEnter && toggle.classList.contains("is-running")) {
      toggle.title = "Bot running but entries are blocked: " + state.blockReason;
    } else if (toggle) { toggle.title = ""; }

    // ── Banners (kill takes priority over loss banner) ────────────────────
    const killBanner = $("#kill-banner"), riskBanner = $("#risk-banner");
    if (state.isKillSwitchActive) {
      killBanner.classList.add("show");
      $("#kill-banner-text").innerHTML = `<strong>KILL SWITCH ACTIVE</strong> — Trading disabled. Reason: ${state.lastKillSwitchReason || "manual"}${state.lastKillSwitchAction ? " · " + state.lastKillSwitchAction : ""} — click to reset`;
      riskBanner.classList.remove("show");
    } else {
      killBanner.classList.remove("show");
      if (state.isPausedByLosses) {
        riskBanner.className = "bot-banner bot-banner-pause show";
        $("#risk-banner-icon").textContent = "⛔";
        $("#risk-banner-text").innerHTML = `<strong>TRADING PAUSED</strong> — ${count} consecutive losses. New entries blocked until manual reset.`;
      } else if (state.isWarning) {
        riskBanner.className = "bot-banner bot-banner-warn show";
        $("#risk-banner-icon").textContent = "⚠";
        $("#risk-banner-text").innerHTML = `<strong>${count} consecutive losses</strong> — one more loss will pause new entries.`;
      } else { riskBanner.classList.remove("show"); }
    }

    // ── Kill button + header status dot ───────────────────────────────────
    const killBtn = $("#kill-btn"), bar = $("#bot-status-bar");
    if (state.isKillSwitchActive) { killBtn.classList.add("is-active"); killBtn.textContent = "⏻ KILL ACTIVE"; bar.dataset.status = "stopped"; }
    else { killBtn.classList.remove("is-active"); killBtn.textContent = "⏻ KILL SWITCH"; bar.dataset.status = "paper"; }

    // ── Last kill event line (roadmap) ────────────────────────────────────
    if (state.lastKillSwitchTime) {
      $("#roadmap-kill-line").innerHTML = `Last kill switch: <strong>${fmtDateShort(state.lastKillSwitchTime)} · ${state.lastKillSwitchReason || "manual"}</strong>${state.lastKillSwitchAction ? " — " + state.lastKillSwitchAction : ""}`;
    }

    // ── Sizing readout (0.25% rule live from the engine) ──────────────────
    $("#sz-risk-pct").textContent = state.maxRiskPerTradePct + "%";
    $("#sz-max-risk").textContent = money(state.maxRiskUsd);
    $("#sz-equity").textContent = moneyK(state.equity);

    // ── Portfolio open-risk (live, book-level) ────────────────────────────
    // Aggregated from every open position; a runner at break-even contributes
    // $0, so this falls as TP1s are hit — that's what frees basket capacity.
    $("#sz-open-risk").textContent = money(state.openRiskUsd, 0) + ` · ${state.openRiskPct.toFixed(2)}%`;
    const usePct = state.portfolioCapUsd ? Math.min(100, state.openRiskUsd / state.portfolioCapUsd * 100) : 0;
    const pbar = $("#sz-budget-bar"); if (pbar) { pbar.style.width = usePct + "%"; pbar.classList.toggle("over", usePct > 80); }
    if ($("#sz-budget-sub")) $("#sz-budget-sub").textContent = `${money(state.openRiskUsd, 0)} of ${money(state.portfolioCapUsd, 0)} cap (${state.maxPortfolioRiskPct}%) · ${state.positionCount}/${state.maxPositions} positions`;

    updateSizeCalc(); // recompute calculator with the engine
  }

  // ── Position sizing calculator (routed through the engine) ─────────────────
  function updateSizeCalc() {
    if (!risk) return;
    const inst = $("#sz-instrument").value;
    const stopDist = Number($("#sz-stop-dist").value) || 0;
    const r = risk.calculatePositionSize(inst, stopDist);
    $("#sz-ppt").textContent = r.dollarsPerPoint != null ? "$" + r.dollarsPerPoint.toLocaleString("en-AU") : "—";
    if (r.error) {
      $("#sz-result").textContent = "—";
      $("#sz-result-risk").textContent = "—"; $("#sz-result-pct").textContent = r.error;
      if ($("#sz-result-note")) $("#sz-result-note").textContent = r.error;
      return;
    }
    const u = r.recommendedUnits;
    $("#sz-result").textContent = u >= 1 ? (u % 1 === 0 ? u.toFixed(0) : u.toFixed(1)) : u.toFixed(2);
    $("#sz-result-risk").textContent = money(r.actualRiskUsd, 0);
    $("#sz-result-pct").textContent = r.actualRiskPct.toFixed(2) + "% of equity";
    if ($("#sz-result-note")) $("#sz-result-note").textContent = r.feasibleWholeContract ? `${r.wholeContracts} whole contract(s)` : (r.note || "recommended size");
  }

  // ── Positions (swing cards) — rendered from ENGINE state ───────────────────
  // Cosmetic-only fields (name, strategy, sparkline …) live in POS_META keyed by
  // symbol; the authoritative numbers (entry, stop, tp1Hit, units, open risk)
  // come from the risk engine so breakeven / add-ons / risk are always live.
  let POS_META = {};

  function biasChip(align) {
    if (!align || align.strength === "unknown") return "";
    const cls = align.strength === "counter" ? "bias-counter" : align.strength === "partial" ? "bias-partial" : "bias-aligned";
    const b = align.bias || {};
    const arr = v => v === "bull" ? "▲" : v === "bear" ? "▼" : "■";
    return `<span class="pos-bias-chip ${cls}" title="${align.reason}">HTF W${arr(b.weekly)} 3D${arr(b.threeDay)}</span>`;
  }

  // Merge engine positions with cosmetic metadata + derived live numbers.
  function mergedBook() {
    if (!risk) return [];
    return risk.getOpenPositions().map(p => {
      const m = POS_META[p.symbol] || {};
      const dpp = p.dollarsPerPoint || 1, sign = p.direction === "long" ? 1 : -1;
      const unrealized_pnl = sign * (p.current - p.entry) * dpp * p.units;
      const unrealized_pct = p.entry ? sign * (p.current - p.entry) / p.entry * 100 : 0;
      const denomStop = p.initialStop != null && p.initialStop !== p.entry ? p.initialStop : p.stop;
      const riskPerR = Math.abs(p.entry - denomStop) || 1;
      return Object.assign({}, m, {
        symbol: p.symbol, direction: p.direction,
        entry: p.entry, current: p.current, stop: p.stop, tp1: p.tp1, target: p.target,
        units: p.units, entry_count: p.entryCount,
        tp1Hit: p.tp1Hit, stopAtBreakeven: p.stopAtBreakeven, remainingFraction: p.remainingFraction,
        openRiskUsd: risk.getPositionOpenRisk(p),
        unrealized_pnl, unrealized_pct, riskPerR,
        biasAlign: Object.assign({ bias: risk.getBias(p.symbol) }, risk.checkBiasAlignment(p.symbol, p.direction)),
      });
    });
  }

  function renderPositionsFromEngine() {
    const book = mergedBook();
    const wrap = $("#positions-body"), countEl = $("#positions-count"); if (!wrap) return;
    if (countEl) countEl.textContent = `${book.length} open`;
    if (!book.length) { wrap.innerHTML = `<div class="bot-empty">No open positions — bot is scanning H4 charts for Weekly+3D-aligned setups.</div>`; return; }
    wrap.innerHTML = book.map(p => {
      const isLong = p.direction === "long", risk_ = p.riskPerR;
      const profitR = (isLong ? (p.current - p.entry) : (p.entry - p.current)) / risk_;
      const stopBufR = (isLong ? (p.current - p.stop) : (p.stop - p.current)) / risk_;
      const toTargetR = (isLong ? (p.target - p.current) : (p.current - p.target)) / risk_;
      const plannedR = (isLong ? (p.target - p.entry) : (p.entry - p.target)) / risk_;
      let prog = isLong ? (p.current - p.entry) / (p.target - p.entry) : (p.entry - p.current) / (p.entry - p.target);
      prog = Math.max(-30, Math.min(100, prog * 100));
      const pnlPos = p.unrealized_pnl >= 0, sparkColor = pnlPos ? getCSS("--green") : getCSS("--red");
      const beBadge = p.stopAtBreakeven ? `<span class="pos-be-badge">● BE · risk-free runner</span>` : "";
      const stopMetric = p.stopAtBreakeven
        ? `<div class="pos-metric"><span class="pos-metric-k">Stop</span><span class="pos-metric-v num" style="color:var(--green)">${px(p.stop)} · BE</span><span class="pos-metric-sub num" style="color:var(--green)">break-even</span></div>`
        : `<div class="pos-metric"><span class="pos-metric-k">Stop</span><span class="pos-metric-v stop num">${px(p.stop)}</span><span class="pos-metric-sub num">${stopBufR.toFixed(1)}R buffer</span></div>`;
      const riskMetric = p.stopAtBreakeven
        ? `<div class="pos-metric"><span class="pos-metric-k">Open risk</span><span class="pos-metric-v num" style="color:var(--green)">$0</span><span class="pos-metric-sub num" style="color:var(--green)">runner · ${plannedR.toFixed(1)}R plan</span></div>`
        : `<div class="pos-metric"><span class="pos-metric-k">Open risk</span><span class="pos-metric-v num">${money(p.openRiskUsd, 0)}</span><span class="pos-metric-sub num">${(p.openRiskUsd / (window.__EQUITY || 10000) * 100).toFixed(2)}% · ${plannedR.toFixed(1)}R plan</span></div>`;
      const tpMetric = p.tp1
        ? `<div class="pos-metric"><span class="pos-metric-k">${p.tp1Hit ? "TP1 ✓ (booked 25%)" : "TP1 (25%→BE)"}</span><span class="pos-metric-v target num">${px(p.tp1)}</span><span class="pos-metric-sub target num">Final: ${px(p.target)} · ${toTargetR.toFixed(1)}R</span></div>`
        : `<div class="pos-metric"><span class="pos-metric-k">Target</span><span class="pos-metric-v target num">${px(p.target)}</span><span class="pos-metric-sub num">${toTargetR.toFixed(1)}R to go</span></div>`;
      const simBtn = (!p.tp1Hit && p.tp1 != null) ? `<button class="pos-sim-btn" data-symbol="${p.symbol}" data-tp1="${p.tp1}" title="Simulate price reaching TP1">▶ Sim → TP1</button>` : "";
      return `<div class="pos-card${p.stopAtBreakeven ? " is-breakeven" : ""}">
        <div class="pos-card-top">
          <span class="pos-ticker num">${p.symbol}</span><span class="pos-name">${p.name || ""}</span>
          <span class="pos-dir ${isLong ? "dir-long" : "dir-short"}">${isLong ? "LONG" : "SHORT"}</span>
          ${p.leverage ? `<span class="pos-lev num">${p.leverage}×</span>` : ""}
          ${p.strategy ? `<span class="pos-strat-chip">${p.strategy}</span>` : ""}
          ${p.bias_tf ? `<span class="pos-tf-chip">${p.bias_tf}→${p.entry_tf || "H4"}</span>` : ""}
          ${biasChip(p.biasAlign)}
          ${p.entry_count > 1 ? `<span class="pos-tf-chip">×${p.entry_count} entries</span>` : ""}
          ${beBadge}
          <button class="pos-close-btn" data-symbol="${p.symbol}">Close</button>
        </div>
        <div class="pos-body">
          <div class="pos-metrics">
            <div class="pos-metric"><span class="pos-metric-k">Entry${p.entry_count > 1 ? " (avg)" : ""}</span><span class="pos-metric-v num">${px(p.entry)}</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Current</span><span class="pos-metric-v num">${px(p.current)}</span></div>
            <div class="pos-metric"><span class="pos-metric-k">Size</span><span class="pos-metric-v num">${p.size || p.units}</span></div>
            ${stopMetric}
            ${tpMetric}
            ${riskMetric}
          </div>
          <div class="pos-side">
            <div class="pos-pnl-box ${pnlPos ? "pos-pnl-green" : "pos-pnl-red"}">
              <div class="pos-pnl-val num">${pnlPos ? "+" : "−"}${money(Math.abs(p.unrealized_pnl), 0)}</div>
              <div class="pos-pnl-pct num">${pct(p.unrealized_pct)} · ${signed(profitR, 1)}R</div>
            </div>
            ${sparkline(p.sparkline, 130, 34, sparkColor)}
            ${simBtn}
          </div>
        </div>
        <div class="pos-progress">
          <div class="pos-progress-track"><div class="pos-progress-fill ${prog >= 0 ? "green" : "red"}" style="width:${Math.abs(prog)}%"></div></div>
          <div class="pos-progress-labels">
            <span class="pos-progress-lab stop">SL ${px(p.stop)}${p.stopAtBreakeven ? " (BE)" : ""}</span>
            <span class="pos-progress-lab num">${p.bars_4h ? p.bars_4h + " bars · " : ""}${p.opened_at ? fmtAge(p.opened_at) + " open" : ""}</span>
            <span class="pos-progress-lab target">${p.tp1 ? `TP1 ${px(p.tp1)} · Final ${px(p.target)}` : `TP ${px(p.target)}`}</span>
          </div>
        </div>
      </div>`;
    }).join("");
    // Sim → TP1: feed the engine the TP1 price; breakeven fires in the engine.
    $$(".pos-sim-btn", wrap).forEach(btn => btn.addEventListener("click", () => {
      const sym = btn.dataset.symbol, tp1 = Number(btn.dataset.tp1);
      const res = risk.onPrice(sym, tp1);
      if (res.event === "tp1_breakeven") {
        prependLog({ ts: new Date().toISOString(), type: "win", msg: `${sym} TP1 hit @ ${tp1} — booked 25%, stop → break-even. Runner is now risk-free.` });
        showToast(`${sym}: TP1 hit → stop moved to break-even.`, "ok");
      }
    }));
    // Close → engine books the trade (feeds the loss counter + journal) and
    // removes it. The returned journalEntry carries the realized P/L breakdown.
    $$(".pos-close-btn", wrap).forEach(btn => btn.addEventListener("click", () => {
      const sym = btn.dataset.symbol;
      if (!confirm(`Close ${sym} at current price? (paper trade)`)) return;
      const meta = POS_META[sym] || {};
      const r = risk.closePosition(sym, (risk.getOpenPositions().find(x => x.symbol === sym) || {}).current);
      // Record the closed trade in the journal with start time, duration,
      // total cost (fees) and realized net P/L — rule 11 enforced in logic.
      if (r.journalEntry) {
        const je = r.journalEntry;
        JOURNAL.unshift({
          id: "T-" + String(Date.now()).slice(-4),
          opened: je.opened, closed: je.closed,
          duration: fmtDuration(je.durationMs),
          symbol: je.symbol, name: meta.name || je.symbol,
          dir: je.direction, entry: je.entry, exit: je.exit,
          size: meta.size || je.units,
          gross: je.gross, costs: je.costs, net: je.net,
          reason: je.reason, r: je.r, win: je.win,
          strategy: meta.strategy || "",
        });
        window.__JSUMMARY = computeJournalSummary(JOURNAL);
        populateJournalFilters(JOURNAL);
        renderJournalTable();
        renderJournalSummary(window.__JSUMMARY);
      }
      prependLog({ ts: new Date().toISOString(), type: r.netPnl >= 0 ? "win" : "loss", msg: `CLOSED ${sym} · gross ${r.gross >= 0 ? "+" : "−"}${money(Math.abs(r.gross), 0)} − ${money(r.costs, 0)} fees = net ${r.netPnl >= 0 ? "+" : "−"}${money(Math.abs(r.netPnl), 0)} (${r.r}R) · consec losses: ${r.state.consecutiveLossCount}` });
      showToast(`${sym} closed · net ${r.netPnl >= 0 ? "+" : "−"}${money(Math.abs(r.netPnl), 0)}`, r.netPnl >= 0 ? "ok" : "warn");
    }));
  }

  // ── Stats ──────────────────────────────────────────────────────────────────
  function renderStats(d) {
    const today = d.today; if (!today) return;
    const eq = d.equity || d.capital, startEq = (d.equity_curve && d.equity_curve[0]) || d.capital;
    const chgPct = ((eq - startEq) / startEq) * 100;
    $("#bot-equity-val").textContent = moneyK(eq);
    $("#equity-now").textContent = moneyK(eq);
    const chgEl = $("#equity-chg"); chgEl.textContent = pct(chgPct); chgEl.className = "equity-chg num " + (chgPct >= 0 ? "up" : "down");
    renderEquityCurve(d.equity_curve);
    const total = today.realized_pnl + today.unrealized_pnl;
    const winRate = today.trades_closed ? Math.round(today.wins / today.trades_closed * 100) : 0;
    const usedPct = today.daily_loss_limit ? Math.min(100, today.daily_loss_used / today.daily_loss_limit * 100) : 0;
    const barCls = usedPct > 80 ? "risk-bar-danger" : usedPct > 50 ? "risk-bar-warn" : "risk-bar-ok";
    const g = n => n >= 0 ? "stat-green" : "stat-red", sm = n => signed(n).replace("+", "+$").replace("−", "−$");
    $("#stats-grid").innerHTML = `
      <div class="stat-tile"><div class="stat-tile-label">Realized P&amp;L</div><div class="stat-tile-val num ${g(today.realized_pnl)}">${sm(today.realized_pnl)}</div><div class="stat-tile-sub">${today.trades_closed} closed</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Unrealized</div><div class="stat-tile-val num ${g(today.unrealized_pnl)}">${sm(today.unrealized_pnl)}</div><div class="stat-tile-sub">open trades</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Total P&amp;L</div><div class="stat-tile-val num ${g(total)}">${sm(total)}</div><div class="stat-tile-sub">realized + open</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Win Rate</div><div class="stat-tile-val num">${today.trades_closed ? winRate + "%" : "—"}</div><div class="stat-tile-sub">${today.wins}W · ${today.losses}L</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Best Trade</div><div class="stat-tile-val num stat-green">+${money(today.best_trade, 0)}</div><div class="stat-tile-sub">${today.best_symbol}</div></div>
      <div class="stat-tile"><div class="stat-tile-label">Worst Trade</div><div class="stat-tile-val num stat-red">−${money(Math.abs(today.worst_trade), 0)}</div><div class="stat-tile-sub">${today.worst_symbol}</div></div>
      <div class="stat-tile stat-tile-wide"><div class="stat-tile-label">Daily Stop Used</div><div class="stat-risk-bar-wrap"><div class="stat-risk-bar ${barCls}" style="width:${usedPct}%"></div></div><div class="stat-tile-sub num">${money(today.daily_loss_used, 0)} of ${money(today.daily_loss_limit, 0)} · ${Math.round(usedPct)}%</div></div>`;
  }

  // ── Execution log ──────────────────────────────────────────────────────────
  let LOG = [];
  function renderLog(log) {
    const wrap = $("#bot-log"); if (!wrap || !log) return;
    const map = { enter: "▶", signal: "◉", win: "✓", loss: "✗", kill: "⏻", system: "·", error: "⚠" };
    wrap.innerHTML = log.map(e => `<div class="log-row log-${e.type}"><span class="log-icon">${map[e.type] || "·"}</span><span class="log-time num">${fmtTs(e.ts)}</span><span class="log-msg">${e.msg}</span></div>`).join("");
  }
  function prependLog(entry) { LOG.unshift(entry); renderLog(LOG); }

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
    const sel = $("#jf-instrument"), instruments = [...new Set(journal.map(t => t.symbol))];
    sel.innerHTML = `<option value="all">All instruments</option>` + instruments.map(s => `<option value="${s}">${s}</option>`).join("");
  }
  function filteredJournal() {
    const inst = $("#jf-instrument").value, result = $("#jf-result").value, period = $("#jf-period").value;
    const anchor = JOURNAL.reduce((mx, t) => Math.max(mx, new Date(t.closed).getTime()), 0) || Date.now();
    return JOURNAL.filter(t => {
      if (inst !== "all" && t.symbol !== inst) return false;
      if (result === "win" && !t.win) return false;
      if (result === "loss" && t.win) return false;
      if (period !== "all" && new Date(t.closed).getTime() < anchor - Number(period) * 86400000) return false;
      return true;
    });
  }
  function renderJournalTable() {
    const rows = filteredJournal(), tbody = $("#journal-tbody");
    $("#journal-count").textContent = `${rows.length} trade${rows.length !== 1 ? "s" : ""}`;
    if (!rows.length) { tbody.innerHTML = `<tr><td colspan="13" class="lft" style="color:var(--muted);padding:24px">No trades match these filters.</td></tr>`; return; }
    tbody.innerHTML = rows.map(t => `<tr>
      <td class="lft jt-id">${t.id}</td><td class="lft">${fmtDateShort(t.opened)}</td><td>${t.duration}</td>
      <td class="lft">${t.symbol}</td><td class="lft ${t.dir === "long" ? "jt-dir-long" : "jt-dir-short"}">${t.dir === "long" ? "L" : "S"}</td>
      <td>${px(t.entry)}</td><td>${px(t.exit)}</td><td>${t.size}</td>
      <td>${signed(t.gross, 0).replace("+", "+$").replace("−", "−$")}</td><td>−${money(t.costs, 0)}</td>
      <td class="${t.net >= 0 ? "jt-net-pos" : "jt-net-neg"}">${signed(t.net, 0).replace("+", "+$").replace("−", "−$")}</td>
      <td class="jt-reason">${t.reason}</td><td class="${t.r >= 0 ? "jt-r-pos" : "jt-r-neg"}">${signed(t.r, 1)}R</td>
    </tr>`).join("");
  }

  // ── Exports ────────────────────────────────────────────────────────────────
  const JCOLS = ["id", "opened", "closed", "duration", "symbol", "name", "dir", "entry", "exit", "size", "gross", "costs", "net", "reason", "r", "strategy"];
  const JHEAD = ["Trade ID", "Opened", "Closed", "Duration", "Instrument", "Name", "Direction", "Entry", "Exit", "Size", "Gross P/L", "Costs", "Net P/L", "Exit Reason", "R-Multiple", "Strategy"];
  function download(filename, content, mime) {
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([content], { type: mime })); a.download = filename;
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 100);
  }
  function exportCSV() {
    const lines = [JHEAD.join(",")];
    filteredJournal().forEach(t => lines.push(JCOLS.map(c => { const v = t[c] == null ? "" : String(t[c]); return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; }).join(",")));
    download(`bot_journal_${Date.now()}.csv`, lines.join("\n"), "text/csv;charset=utf-8"); showToast("CSV exported.", "ok");
  }
  function exportExcel() {
    const head = JHEAD.map(h => `<th style="background:#1c1c1e;color:#fff;padding:6px 10px;text-align:left;border:1px solid #444">${h}</th>`).join("");
    const body = filteredJournal().map(t => `<tr>${JCOLS.map(c => { const neg = (c === "net" || c === "r") && t[c] < 0, pos = (c === "net" || c === "r") && t[c] > 0; return `<td style="padding:5px 10px;border:1px solid #ccc;${neg ? "color:#c00" : pos ? "color:#080" : ""}">${t[c] == null ? "" : t[c]}</td>`; }).join("")}</tr>`).join("");
    const html = `<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8"></head><body><h3>Vivek's Beta Scanner — Bot Trade Journal</h3><table style="border-collapse:collapse;font-family:Calibri,sans-serif;font-size:12px"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></body></html>`;
    download(`bot_journal_${Date.now()}.xls`, html, "application/vnd.ms-excel"); showToast("Excel exported.", "ok");
  }
  function exportHTMLReport() {
    const rows = filteredJournal(), s = window.__JSUMMARY || {}, totalNet = rows.reduce((a, t) => a + t.net, 0);
    const head = JHEAD.slice(0, 15).map(h => `<th>${h}</th>`).join("");
    const body = rows.map(t => `<tr class="${t.net >= 0 ? "w" : "l"}"><td>${t.id}</td><td>${fmtDateShort(t.opened)}</td><td>${fmtDateShort(t.closed)}</td><td>${t.duration}</td><td>${t.symbol}</td><td>${t.name}</td><td>${t.dir}</td><td>${px(t.entry)}</td><td>${px(t.exit)}</td><td>${t.size}</td><td>${signed(t.gross, 0)}</td><td>${t.costs}</td><td class="${t.net >= 0 ? "pos" : "neg"}">${signed(t.net, 0)}</td><td>${t.reason}</td><td class="${t.r >= 0 ? "pos" : "neg"}">${signed(t.r, 1)}R</td></tr>`).join("");
    const doc = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bot Trade Report</title><style>body{font-family:-apple-system,Inter,sans-serif;background:#0a0a0c;color:#e8e8ea;padding:32px;max-width:1100px;margin:0 auto}h1{font-size:20px;margin:0 0 4px}.sub{color:#888;font-size:13px;margin-bottom:24px}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:24px}.card{background:#1c1c1e;border-radius:10px;padding:14px}.card .k{font-size:10px;letter-spacing:.06em;color:#888;text-transform:uppercase}.card .v{font-size:20px;font-weight:700;margin-top:6px;font-family:monospace}table{width:100%;border-collapse:collapse;font-size:12px;font-family:monospace}th{text-align:left;padding:8px;border-bottom:1px solid #333;color:#888;font-size:10px;text-transform:uppercase}td{padding:7px 8px;border-bottom:1px solid #222}.pos{color:#30d158}.neg{color:#ff453a}tr.w td:first-child{border-left:2px solid #30d158}tr.l td:first-child{border-left:2px solid #ff453a}@media print{body{background:#fff;color:#000}.card{background:#f2f2f2}}.pbtn{margin-bottom:20px;padding:9px 16px;border:none;border-radius:8px;background:#0a84ff;color:#fff;cursor:pointer;font-weight:600}</style></head><body><button class="pbtn" onclick="window.print()">🖨 Print / Save PDF</button><h1>Vivek's Beta Scanner — Bot Trade Report</h1><div class="sub">Generated ${new Date().toLocaleString("en-AU")} · ${rows.length} trades</div><div class="summary"><div class="card"><div class="k">Win Rate</div><div class="v">${s.win_rate || "—"}%</div></div><div class="card"><div class="k">Profit Factor</div><div class="v">${s.profit_factor ? s.profit_factor.toFixed(1) : "—"}</div></div><div class="card"><div class="k">Expectancy</div><div class="v">${money(s.expectancy || 0, 0)}</div></div><div class="card"><div class="k">Max Consec L</div><div class="v">${s.max_consec_losses || "—"}</div></div><div class="card"><div class="k">Net P/L</div><div class="v ${totalNet >= 0 ? "pos" : "neg"}">${signed(totalNet, 0)}</div></div></div><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></body></html>`;
    const w = window.open("", "_blank");
    if (w) { w.document.write(doc); w.document.close(); showToast("HTML report opened.", "ok"); } else { download(`bot_report_${Date.now()}.html`, doc, "text/html"); showToast("Report downloaded.", "ok"); }
  }

  // ── Rules form ─────────────────────────────────────────────────────────────
  function populateRulesForm(r) {
    $$("[data-market]").forEach(el => el.checked = r.markets.includes(el.dataset.market));
    $$("[data-strat]").forEach(el => el.checked = r.strategies.includes(el.dataset.strat));
    const set = (id, v) => { const el = $(id); if (el) el.value = v; };
    set("#rule-min-rr", r.min_rr); set("#rule-bias", r.bias); set("#rule-risk-pct", r.risk_pct);
    set("#rule-loss-limit", r.loss_limit); set("#rule-max-positions", r.max_positions);
    set("#rule-leverage", r.leverage);
    const chk = (id, v) => { const el = $(id); if (el) el.checked = !!v; };
    chk("#rule-scanner-targets", r.use_scanner_targets);
    chk("#rule-trail-st", r.trail_supertrend);
    chk("#rule-scale-tp1", r.scale_out_tp1);
    chk("#rule-be-after-tp1", r.be_after_tp1);
    chk("#rule-multi-entry", r.multi_entry);
    $("#rule-bias-tf").textContent = r.bias_tf || "Weekly+3D";
    $("#rule-entry-tf").textContent = r.entry_tf || "H4";
  }
  function collectRules() {
    const markets = $$("[data-market]").filter(e => e.checked).map(e => e.dataset.market);
    const strategies = $$("[data-strat]").filter(e => e.checked).map(e => e.dataset.strat);
    const g = (id, p = v => v) => { const el = $(id); return el ? p(el.value) : null; };
    return {
      markets: markets.length ? markets : ["NAS100"], strategies: strategies.length ? strategies : ["trend_pullback"],
      bias_tf: "Weekly+3D", entry_tf: "H4", min_rr: g("#rule-min-rr", Number), bias: g("#rule-bias"),
      risk_pct: g("#rule-risk-pct", Number), loss_limit: g("#rule-loss-limit", Number), max_positions: g("#rule-max-positions", Number),
      leverage: g("#rule-leverage", Number),
      use_scanner_targets: $("#rule-scanner-targets").checked, trail_supertrend: $("#rule-trail-st").checked,
      scale_out_tp1: $("#rule-scale-tp1").checked, be_after_tp1: $("#rule-be-after-tp1").checked,
      multi_entry: $("#rule-multi-entry").checked,
    };
  }

  // ── Toast ──────────────────────────────────────────────────────────────────
  function showToast(msg, kind = "ok") {
    let el = $("#bot-toast"); if (!el) { el = document.createElement("div"); el.id = "bot-toast"; document.body.appendChild(el); }
    el.textContent = msg; el.className = `bot-toast bot-toast-${kind} bot-toast-show`;
    clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("bot-toast-show"), 3000);
  }

  // ── Kill modal ─────────────────────────────────────────────────────────────
  function openKillModal(posCount) { $("#kill-modal-poscount").textContent = posCount; $("#kill-modal").classList.add("show"); }
  function closeKillModal() { $("#kill-modal").classList.remove("show"); }

  // ── Boot ───────────────────────────────────────────────────────────────────
  let RULES = loadRules();

  async function init() {
    RULES = loadRules();
    populateRulesForm(RULES);

    // Fetch the status feed ONCE up front so the engine is constructed with the
    // REAL starting equity from bot_status.json, not a hardcoded placeholder.
    // The fallback is used only if this initial fetch fails (offline boot).
    const seed = await fetchStatus();
    const startingEquity = seed ? Number(seed.equity ?? seed.capital) || FALLBACK_EQUITY : FALLBACK_EQUITY;

    // Create the risk engine with the loaded equity.
    risk = new RiskManager({
      equity: startingEquity,
      maxRiskPerTradePct: RULES.risk_pct,
      maxConsecutiveLosses: RULES.loss_limit,
      maxPositions: RULES.max_positions,
    });
    // The engine drives ALL risk/kill/sizing UI via this subscription.
    risk.subscribe(renderRiskUI);
    // …and the open-position book re-renders on any engine mutation (a TP1→BE,
    // an add-on, or a close all flow through here — the cards are never stale).
    risk.subscribe(renderPositionsFromEngine);
    window.risk = risk; // exposed for console inspection / manual testing

    // rules buttons
    $("#rules-save-btn").addEventListener("click", () => {
      RULES = collectRules(); saveRules(RULES); populateRulesForm(RULES);
      risk.setConfig({ maxRiskPerTradePct: RULES.risk_pct, maxConsecutiveLosses: RULES.loss_limit, maxPositions: RULES.max_positions });
      showToast("Rules saved.", "ok");
    });
    $("#rules-reset-btn").addEventListener("click", () => {
      if (confirm("Reset all rules to defaults?")) {
        RULES = { ...DEFAULT_RULES }; saveRules(RULES); populateRulesForm(RULES);
        risk.setConfig({ maxRiskPerTradePct: RULES.risk_pct, maxConsecutiveLosses: RULES.loss_limit, maxPositions: RULES.max_positions });
        showToast("Rules reset.", "ok");
      }
    });

    // risk reset (counter)
    const doReset = () => {
      const st = risk.getCurrentRiskState();
      if (st.consecutiveLossCount === 0) return;
      if (confirm("Reset the consecutive-loss counter to 0?\n\nThis is a hard safety rule — only reset after reviewing why the losses happened.")) {
        risk.resetConsecutiveLossCounter();
        prependLog({ ts: new Date().toISOString(), type: "system", msg: "Consecutive-loss counter manually reset to 0" });
        showToast("Loss counter reset.", "ok");
      }
    };
    $("#risk-reset-btn").addEventListener("click", doReset);
    $("#risk-banner-reset").addEventListener("click", doReset);

    // ── Engine demo controls (live enforcement) ───────────────────────────
    $("#sim-win").addEventListener("click", () => {
      const pnl = 250 + Math.round(Math.random() * 250);
      risk.registerTradeClosed(pnl);
      prependLog({ ts: new Date().toISOString(), type: "win", msg: `CLOSED demo trade · +${money(pnl, 0)} · loss counter reset to 0` });
      showToast(`Win +${money(pnl, 0)} — counter reset.`, "ok");
    });
    $("#sim-loss").addEventListener("click", () => {
      const pnl = -(150 + Math.round(Math.random() * 150));
      const st = risk.registerTradeClosed(pnl);
      prependLog({ ts: new Date().toISOString(), type: "loss", msg: `CLOSED demo trade · −${money(Math.abs(pnl), 0)} · consecutive losses: ${st.consecutiveLossCount}` });
      if (st.isPausedByLosses) prependLog({ ts: new Date().toISOString(), type: "kill", msg: `HARD STOP — ${st.consecutiveLossCount} consecutive losses. New entries blocked until manual reset.` });
      showToast(st.isPausedByLosses ? "Hard stop tripped — entries blocked." : `Loss −${money(Math.abs(pnl), 0)} — count ${st.consecutiveLossCount}.`, st.isPausedByLosses ? "err" : "warn");
    });
    // Full pre-trade decision (base gate + Weekly+3D bias + portfolio risk).
    // Dry-run only (commit:false) — exercises the same path the bot uses.
    const sampleIntent = direction => {
      const st = risk.getCurrentRiskState();
      return { symbol: "/NQ", direction, riskUsd: st.maxRiskUsd };
    };
    const attempt = direction => {
      const d = risk.evaluateEntry(sampleIntent(direction));
      const tag = `/NQ ${direction.toUpperCase()}`;
      if (d.allowed) {
        prependLog({ ts: new Date().toISOString(), type: "enter", msg: `Entry check PASSED — ${tag} · ${d.bias ? d.bias.reason : "no bias"} · open risk would be ${money(d.projectedRiskUsd || 0, 0)}/${money(d.portfolioCapUsd || 0, 0)} cap` });
        showToast(`${tag}: entry allowed ✓`, "ok");
      } else {
        prependLog({ ts: new Date().toISOString(), type: "system", msg: `Entry BLOCKED — ${tag} · ${d.reason} [${d.code}]` });
        showToast(`${tag} blocked: ${d.reason}`, "err");
      }
    };
    $("#attempt-entry").addEventListener("click", () => attempt("long"));
    const counterBtn = $("#attempt-counter");
    if (counterBtn) counterBtn.addEventListener("click", () => attempt("short"));

    // bot toggle
    $("#bot-toggle").addEventListener("click", () => {
      const btn = $("#bot-toggle"), paused = btn.classList.toggle("is-paused");
      btn.classList.toggle("is-running", !paused);
      btn.textContent = paused ? "▶ START BOT" : "⏸ PAUSE BOT";
      prependLog({ ts: new Date().toISOString(), type: "system", msg: paused ? "Bot paused — no new entries" : "Bot resumed — scanning for entries" });
      showToast(paused ? "Bot paused." : "Bot running.", paused ? "warn" : "ok");
    });

    // kill switch flow
    $("#kill-btn").addEventListener("click", () => {
      if (risk.getCurrentRiskState().isKillSwitchActive) { if (confirm("Kill switch is active. Reset and re-enable trading?")) doDeactivateKill(); return; }
      openKillModal($$("#positions-body .pos-card").length || 0);
    });
    $("#kill-cancel").addEventListener("click", closeKillModal);
    $("#kill-modal").addEventListener("click", e => { if (e.target.id === "kill-modal") closeKillModal(); });
    $("#kill-confirm").addEventListener("click", () => {
      const action = ($('input[name="kill-action"]:checked') || {}).value || "close";
      const reason = $("#kill-reason").value.trim() || "manual";
      const actionLabel = action === "close" ? "Closed all positions" : "Left positions to stops";
      closeKillModal();
      risk.activateKillSwitch(reason, actionLabel);
      prependLog({ ts: new Date().toISOString(), type: "kill", msg: `KILL SWITCH (${reason}) — ${actionLabel} · trading disabled` });
      showToast("Kill switch activated — trading disabled.", "err");
      if (action === "close") $$("#positions-body .pos-card").forEach(c => c.style.opacity = "0.35");
    });
    $("#kill-banner-reset").addEventListener("click", () => { if (confirm("Reset kill switch and re-enable trading?")) doDeactivateKill(); });

    function doDeactivateKill() {
      risk.deactivateKillSwitch();
      prependLog({ ts: new Date().toISOString(), type: "system", msg: "Kill switch reset — trading re-enabled" });
      showToast("Kill switch reset — trading re-enabled.", "ok");
      $$("#positions-body .pos-card").forEach(c => c.style.opacity = "1");
    }

    // sizing calc live
    $("#sz-instrument").addEventListener("change", updateSizeCalc);
    $("#sz-stop-dist").addEventListener("input", updateSizeCalc);

    // journal filters + exports
    ["#jf-instrument", "#jf-result", "#jf-period"].forEach(id => $(id).addEventListener("change", renderJournalTable));
    $("#export-csv").addEventListener("click", exportCSV);
    $("#export-xls").addEventListener("click", exportExcel);
    $("#export-html").addEventListener("click", exportHTMLReport);

    // Reuse the payload we already fetched for the first render (no double-fetch).
    await loadData(seed);
    setInterval(loadData, 30000);
    startClocks();
  }

  // Fetch the bot status feed. Returns the parsed object, or null on failure.
  async function fetchStatus() {
    try {
      const r = await fetch(STATUS_URL, { cache: "no-cache" });
      if (!r.ok) throw new Error("no data");
      return await r.json();
    } catch (_) { return null; }
  }

  // Render from the status feed. Pass a prefetched payload (from init) to avoid
  // re-fetching on the very first render; later interval calls fetch fresh.
  async function loadData(prefetched) {
    try {
      const d = prefetched || await fetchStatus();
      if (!d) throw new Error("no data");
      window.__DATA = d; window.__JSUMMARY = d.journal_summary;
      window.__EQUITY = d.equity || d.capital;
      JOURNAL = d.journal || []; LOG = d.log || [];

      // Feed live equity to the engine; seed the loss counter on first run only.
      risk.setEquity(d.equity || d.capital);
      risk.seedConsecutiveLosses((d.risk_status && d.risk_status.consecutive_losses) || 0);

      // ── Seed the engine with bias + positions (only on first load) ─────────
      // Re-seeding every 30s would clobber an in-session breakeven the user
      // triggered, so we only seed positions once. Bias is cheap to refresh.
      POS_META = {};
      (d.positions || []).forEach(p => { POS_META[p.symbol] = p; });
      // HTF bias: per-position `bias` block, plus an optional instrument map.
      const biasMap = Object.assign({}, d.htf_bias || {});
      (d.positions || []).forEach(p => { if (p.bias) biasMap[p.symbol] = p.bias; });
      Object.keys(biasMap).forEach(sym => risk.setBias(sym, biasMap[sym]));
      window.__BIAS_MAP = biasMap;
      if (!window.__POS_SEEDED) { risk.loadPositions(d.positions || []); window.__POS_SEEDED = true; }

      renderConnections(d.connections);
      renderStats(d);
      renderLog(LOG);
      renderJournalSummary(d.journal_summary);
      populateJournalFilters(JOURNAL);
      renderJournalTable();
      // Risk/kill/sizing/portfolio UI + the position book are rendered by the
      // engine subscriptions; nudge them so equity-derived readouts refresh.
      renderRiskUI(risk.getCurrentRiskState());
      renderPositionsFromEngine();
    } catch (e) {
      showToast("Bot data unavailable — showing empty state.", "warn");
      renderPositionsFromEngine(); renderLog([]);
    }
  }

  function startClocks() {
    function tick() {
      const now = new Date();
      const t = tz => now.toLocaleTimeString("en-AU", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
      const dt = tz => now.toLocaleDateString("en-AU", { timeZone: tz, weekday: "short", day: "numeric", month: "short" });
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      set("clk-mel-time", t("Australia/Sydney")); set("clk-mel-date", dt("Australia/Sydney"));
      set("clk-ny-time", t("America/New_York")); set("clk-ny-date", dt("America/New_York"));
    }
    tick(); setInterval(tick, 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();

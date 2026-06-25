/* ===========================================================================
   risk_manager.js — Vivek's Beta Scanner / AI Bot
   ---------------------------------------------------------------------------
   A real, enforceable risk-management engine.

   DESIGN NOTES
   - This module is intentionally DOM-FREE. It holds state + rules + maths only.
     The UI (bot.js) subscribes via `subscribe(fn)` and re-renders whenever the
     engine emits a change. That keeps this file trivially portable to a Node /
     backend service later — swap the localStorage adapter for a DB and the rest
     is unchanged.
   - All mutating methods: validate input → mutate → persist → log → emit.
   - The engine is the single source of truth for: consecutive-loss count,
     kill-switch state, and the 2% position-sizing rule. The dashboard JSON is
     only a seed on first run and a feed for live equity.

   HARD RULES ENFORCED
     1. Max risk per trade = 2% of CURRENT equity (configurable).
     2. Block all new entries when consecutive losses >= 3 (configurable).
     3. The loss counter ONLY resets on a winning trade (net P/L > 0) or a
        manual reset. Break-even (net == 0) leaves it unchanged.
     4. An active kill switch also blocks all new entries.
     5. Position sizing respects the 0.25% rule AND per-instrument point values.
   =========================================================================== */
(function (global) {
  "use strict";

  // ── Persistence key (single namespaced blob — easy to migrate to a DB) ─────
  const STORE_KEY = "gbs_risk_state_v1";

  // Legacy keys from the pre-engine UI — migrated on first construction.
  const LEGACY_COUNTER_KEY = "gbs_bot_counter_v1";
  const LEGACY_KILL_KEY = "gbs_bot_kill_v1";

  // ── Instrument specifications ──────────────────────────────────────────────
  // dollarsPerPoint  : P/L for a 1.00 move in price, per 1 contract/lot.
  // volatilityFactor : scales the risk budget DOWN for jumpy instruments so the
  //                    engine sizes them smaller (NatGas especially).
  // minStopPoints    : a sane floor to reject absurdly tight stops.
  // tickValue is implied by dollarsPerPoint; keep it simple for now.
  const DEFAULT_INSTRUMENTS = {
    "/NQ": { name: "NAS100", dollarsPerPoint: 20,   volatilityFactor: 1.0, minStopPoints: 10 },
    "/YM": { name: "US30",   dollarsPerPoint: 5,    volatilityFactor: 1.0, minStopPoints: 10 },
    "GC":  { name: "Gold",   dollarsPerPoint: 100,  volatilityFactor: 1.0, minStopPoints: 1 },
    "SI":  { name: "Silver", dollarsPerPoint: 50,   volatilityFactor: 0.8, minStopPoints: 0.05 },
    "CL":  { name: "Crude",  dollarsPerPoint: 1000, volatilityFactor: 0.7, minStopPoints: 0.05 },
    // NatGas is the most volatile of the set — a deliberately reduced factor
    // shrinks its position size for the same nominal stop.
    "NG":  { name: "NatGas", dollarsPerPoint: 1000, volatilityFactor: 0.4, minStopPoints: 0.02 },
  };

  // Aliases so callers can pass either the ticker or the friendly name.
  const ALIASES = {
    "NAS100": "/NQ", "NQ": "/NQ",
    "US30": "/YM", "YM": "/YM", "/YM": "/YM",
    "GOLD": "GC", "XAU": "GC",
    "SILVER": "SI", "XAG": "SI",
    "CRUDE": "CL", "OIL": "CL", "WTI": "CL",
    "NATGAS": "NG", "NATURALGAS": "NG", "GAS": "NG",
  };

  // ── Block reason codes (stable identifiers for UI / telemetry) ─────────────
  const REASON = {
    OK: "OK",
    KILL_SWITCH: "KILL_SWITCH",
    CONSECUTIVE_LOSS_LIMIT: "CONSECUTIVE_LOSS_LIMIT",
    EQUITY_INVALID: "EQUITY_INVALID",
    BIAS_CONFLICT: "BIAS_CONFLICT",
    PORTFOLIO_RISK_LIMIT: "PORTFOLIO_RISK_LIMIT",
    MAX_POSITIONS: "MAX_POSITIONS",
  };

  // ───────────────────────────────────────────────────────────────────────────
  class RiskManager {
    /**
     * @param {Object} cfg
     * @param {number} cfg.equity                Current account equity (USD).
     * @param {number} [cfg.maxRiskPerTradePct]  Default 2.0.
     * @param {number} [cfg.maxConsecutiveLosses] Default 3.
     * @param {Object} [cfg.instruments]         Override/extend instrument specs.
     * @param {Storage} [cfg.storage]            Defaults to window.localStorage.
     * @param {boolean} [cfg.verbose]            Console logging (default true).
     */
    constructor(cfg = {}) {
      this.config = {
        maxRiskPerTradePct: cfg.maxRiskPerTradePct != null ? cfg.maxRiskPerTradePct : 0.25,
        maxConsecutiveLosses: cfg.maxConsecutiveLosses != null ? cfg.maxConsecutiveLosses : 3,
        // Total open risk across ALL positions may not exceed this % of equity.
        // With 0.25%/trade this allows a basket of several concurrent trades
        // while still capping book-level drawdown if every stop hits at once.
        maxPortfolioRiskPct: cfg.maxPortfolioRiskPct != null ? cfg.maxPortfolioRiskPct : 2.0,
        // Fraction of a position closed when TP1 is reached (the rest runs).
        scaleOutPct: cfg.scaleOutPct != null ? cfg.scaleOutPct : 0.25,
        // Hard cap on number of concurrent open positions.
        maxPositions: cfg.maxPositions != null ? cfg.maxPositions : 5,
      };
      this.instruments = Object.assign({}, DEFAULT_INSTRUMENTS, cfg.instruments || {});
      this.equity = this._num(cfg.equity, 0);
      this.verbose = cfg.verbose !== false;
      this._storage = cfg.storage || (typeof localStorage !== "undefined" ? localStorage : null);
      this._listeners = [];

      // Live open positions, keyed by symbol. Seeded from the dashboard feed via
      // loadPositions(); mutated by addEntry()/onPrice()/closePosition(). These
      // are intentionally in-memory (re-seeded each load) — only the risk counter
      // and kill state persist, because those are the safety rails that must
      // survive a refresh.
      this._positions = {};
      // Higher-timeframe bias per instrument: { weekly, threeDay } each
      // "bull" | "bear" | "neutral". Drives the Weekly+3D entry filter.
      this._bias = {};

      // Default state, then hydrate from storage / legacy keys.
      this._state = {
        consecutiveLossCount: 0,
        isKillSwitchActive: false,
        lastKillSwitchReason: null,
        lastKillSwitchTime: null,
        lastKillSwitchAction: null,
      };
      this.wasRestored = this._restore();
      this._log("info", `Engine ready. restored=${this.wasRestored}`, this.getCurrentRiskState());
    }

    /* ----------------------------------------------------------------- utils */
    _num(v, fallback) { const n = Number(v); return Number.isFinite(n) ? n : fallback; }

    _log(level, msg, data) {
      if (!this.verbose) return;
      const tag = "%c[RiskManager]";
      const style = level === "block" ? "color:#ff453a;font-weight:700"
        : level === "warn" ? "color:#ff9f0a;font-weight:700"
        : level === "kill" ? "color:#fff;background:#ff453a;font-weight:700;padding:1px 4px;border-radius:3px"
        : "color:#0a84ff;font-weight:700";
      try {
        if (data !== undefined) console.log(tag, style, msg, data);
        else console.log(tag, style, msg);
      } catch (_) { /* console may be unavailable */ }
    }

    /* ----------------------------------------------------- observer pattern */
    /** Subscribe to state changes. Returns an unsubscribe fn. */
    subscribe(fn) {
      if (typeof fn === "function") {
        this._listeners.push(fn);
        fn(this.getCurrentRiskState()); // emit current state immediately
      }
      return () => { this._listeners = this._listeners.filter(l => l !== fn); };
    }
    _emit() {
      const s = this.getCurrentRiskState();
      this._listeners.forEach(fn => { try { fn(s); } catch (e) { this._log("warn", "listener error", e); } });
    }

    /* ------------------------------------------------------------ persistence */
    _persist() {
      if (!this._storage) return;
      try { this._storage.setItem(STORE_KEY, JSON.stringify(this._state)); }
      catch (e) { this._log("warn", "persist failed", e); }
    }
    _restore() {
      if (!this._storage) return false;
      // 1) Preferred: namespaced blob.
      try {
        const raw = this._storage.getItem(STORE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          this._state = Object.assign(this._state, parsed);
          // defensive: clamp + coerce types
          this._state.consecutiveLossCount = Math.max(0, this._num(this._state.consecutiveLossCount, 0));
          this._state.isKillSwitchActive = !!this._state.isKillSwitchActive;
          return true;
        }
      } catch (e) { this._log("warn", "restore failed, ignoring", e); }

      // 2) Migrate legacy keys from the pre-engine UI, if present.
      let migrated = false;
      try {
        const c = this._storage.getItem(LEGACY_COUNTER_KEY);
        if (c != null) { this._state.consecutiveLossCount = Math.max(0, this._num(c, 0)); migrated = true; }
        const k = this._storage.getItem(LEGACY_KILL_KEY);
        if (k != null) {
          const ko = JSON.parse(k);
          this._state.isKillSwitchActive = !!ko.active;
          this._state.lastKillSwitchReason = ko.reason || (ko.last_event && ko.last_event.reason) || null;
          this._state.lastKillSwitchTime = (ko.last_event && ko.last_event.ts) || ko.ts || null;
          this._state.lastKillSwitchAction = ko.action || (ko.last_event && ko.last_event.action) || null;
          migrated = true;
        }
      } catch (e) { this._log("warn", "legacy migrate failed", e); }
      if (migrated) { this._persist(); this._log("info", "Migrated legacy risk state."); }
      return migrated;
    }

    /* -------------------------------------------------------------- config IO */
    /** Update live equity (e.g. from the broker / dashboard feed). */
    setEquity(equity) {
      const e = this._num(equity, this.equity);
      if (e !== this.equity) { this.equity = e; this._emit(); }
      return this.equity;
    }

    /** Patch config (risk %, loss limit). Re-emits so UI reflects new limits. */
    setConfig(patch = {}) {
      let changed = false;
      if (patch.maxRiskPerTradePct != null) {
        const v = this._num(patch.maxRiskPerTradePct, this.config.maxRiskPerTradePct);
        if (v !== this.config.maxRiskPerTradePct) { this.config.maxRiskPerTradePct = v; changed = true; }
      }
      if (patch.maxConsecutiveLosses != null) {
        const v = Math.max(1, this._num(patch.maxConsecutiveLosses, this.config.maxConsecutiveLosses));
        if (v !== this.config.maxConsecutiveLosses) { this.config.maxConsecutiveLosses = v; changed = true; }
      }
      if (patch.maxPortfolioRiskPct != null) {
        const v = Math.max(0, this._num(patch.maxPortfolioRiskPct, this.config.maxPortfolioRiskPct));
        if (v !== this.config.maxPortfolioRiskPct) { this.config.maxPortfolioRiskPct = v; changed = true; }
      }
      if (patch.maxPositions != null) {
        const v = Math.max(1, this._num(patch.maxPositions, this.config.maxPositions));
        if (v !== this.config.maxPositions) { this.config.maxPositions = v; changed = true; }
      }
      if (patch.scaleOutPct != null) {
        const v = Math.min(1, Math.max(0, this._num(patch.scaleOutPct, this.config.scaleOutPct)));
        if (v !== this.config.scaleOutPct) { this.config.scaleOutPct = v; changed = true; }
      }
      if (changed) { this._log("info", "Config updated.", this.config); this._emit(); }
      return this.config;
    }

    /** Seed the counter from external data, but ONLY on a fresh install. */
    seedConsecutiveLosses(count) {
      if (this.wasRestored) return; // never clobber persisted, real state
      this._state.consecutiveLossCount = Math.max(0, this._num(count, 0));
      this._persist();
      this._log("info", `Seeded consecutive losses = ${this._state.consecutiveLossCount} (first run).`);
      this._emit();
    }

    /* ----------------------------------------------------- instrument lookup */
    getInstrumentSpec(instrument) {
      if (!instrument) return null;
      const key = String(instrument).toUpperCase().trim();
      const resolved = this.instruments[instrument] ? instrument
        : (this.instruments[key] ? key
          : (ALIASES[key] && this.instruments[ALIASES[key]] ? ALIASES[key] : null));
      return resolved ? Object.assign({ symbol: resolved }, this.instruments[resolved]) : null;
    }

    /* --------------------------------------------------------- position size */
    /**
     * Size a trade so the loss-at-stop equals (at most) the 2% budget, adjusted
     * by the instrument's volatility factor.
     *
     * @param {string} instrument          e.g. "/NQ", "GC", "NAS100".
     * @param {number} stopDistancePoints  Distance from entry to stop, in points.
     * @param {number} [currentPrice]      Used for context (stop % / notional).
     * @returns {Object} full sizing breakdown (never throws; carries `error`).
     */
    calculatePositionSize(instrument, stopDistancePoints, currentPrice) {
      const spec = this.getInstrumentSpec(instrument);
      const out = {
        instrument, spec: spec ? spec.symbol : null, name: spec ? spec.name : null,
        dollarsPerPoint: spec ? spec.dollarsPerPoint : null,
        volatilityFactor: spec ? spec.volatilityFactor : null,
        stopDistancePoints: this._num(stopDistancePoints, NaN),
        maxRiskUsd: 0, riskPerUnit: 0, rawUnits: 0,
        recommendedUnits: 0, wholeContracts: 0,
        actualRiskUsd: 0, actualRiskPct: 0,
        feasibleWholeContract: false, withinLimit: false,
        error: null, note: null,
      };

      // ── Defensive validation ────────────────────────────────────────────
      if (!spec) { out.error = `Unknown instrument "${instrument}"`; this._log("warn", out.error); return out; }
      if (!Number.isFinite(this.equity) || this.equity <= 0) { out.error = "Equity not set / invalid"; this._log("warn", out.error); return out; }
      const stop = this._num(stopDistancePoints, NaN);
      if (!Number.isFinite(stop) || stop <= 0) { out.error = "Stop distance must be > 0"; return out; }
      if (stop < spec.minStopPoints) { out.note = `Stop below ${spec.name} minimum (${spec.minStopPoints} pts)`; }

      // ── The 2% rule, volatility-adjusted ─────────────────────────────────
      const maxRiskUsd = this.equity * (this.config.maxRiskPerTradePct / 100) * spec.volatilityFactor;
      const riskPerUnit = stop * spec.dollarsPerPoint;
      const rawUnits = riskPerUnit > 0 ? maxRiskUsd / riskPerUnit : 0;

      // Whole futures contracts (floor) + a CFD/micro-friendly fractional size.
      const wholeContracts = Math.floor(rawUnits);
      // Always FLOOR so the resulting risk can never exceed the 2% budget.
      const recommendedUnits = rawUnits >= 1
        ? Math.floor(rawUnits * 10) / 10      // 0.1-lot granularity once >= 1
        : Math.max(0, Math.floor(rawUnits * 100) / 100); // 0.01 granularity sub-1
      const actualRiskUsd = recommendedUnits * riskPerUnit;

      Object.assign(out, {
        maxRiskUsd: this._round(maxRiskUsd, 2),
        riskPerUnit: this._round(riskPerUnit, 2),
        rawUnits: this._round(rawUnits, 4),
        recommendedUnits,
        wholeContracts: Math.max(0, wholeContracts),
        actualRiskUsd: this._round(actualRiskUsd, 2),
        actualRiskPct: this._round(actualRiskUsd / this.equity * 100, 2),
        feasibleWholeContract: wholeContracts >= 1,
        withinLimit: actualRiskUsd <= maxRiskUsd + 1e-6,
      });
      if (!out.feasibleWholeContract && !out.note) {
        out.note = `< 1 full contract fits the ${this.config.maxRiskPerTradePct}% budget — use a micro/CFD lot.`;
      }
      if (Number.isFinite(currentPrice) && currentPrice > 0) {
        out.stopDistancePct = this._round(stop / currentPrice * 100, 2);
      }
      this._log("info", `Sized ${spec.symbol}: ${recommendedUnits} units, risk $${out.actualRiskUsd} (${out.actualRiskPct}%)`, out);
      return out;
    }
    _round(v, dp) { const f = Math.pow(10, dp); return Math.round(v * f) / f; }

    /* ------------------------------------------------------------ entry gate */
    /**
     * The single authoritative check before any new entry.
     * @returns {{allowed:boolean, reason:string, code:string}}
     */
    canEnterNewTrade() {
      if (this._state.isKillSwitchActive) {
        const r = { allowed: false, code: REASON.KILL_SWITCH, reason: `Kill switch active (${this._state.lastKillSwitchReason || "manual"})` };
        this._log("block", `Entry BLOCKED — ${r.reason}`);
        return r;
      }
      if (this._state.consecutiveLossCount >= this.config.maxConsecutiveLosses) {
        const r = { allowed: false, code: REASON.CONSECUTIVE_LOSS_LIMIT, reason: `${this._state.consecutiveLossCount} consecutive losses — hard stop` };
        this._log("block", `Entry BLOCKED — ${r.reason}`);
        return r;
      }
      if (!Number.isFinite(this.equity) || this.equity <= 0) {
        return { allowed: false, code: REASON.EQUITY_INVALID, reason: "Equity invalid" };
      }
      return { allowed: true, code: REASON.OK, reason: null };
    }

    /* ------------------------------------------------------- trade lifecycle */
    /**
     * Record a closed trade's net P/L and update the loss counter.
     * Win (net>0) → reset to 0. Loss (net<0) → +1. Break-even → unchanged.
     * @returns {Object} the new risk state.
     */
    registerTradeClosed(netPnl) {
      const net = this._num(netPnl, NaN);
      if (!Number.isFinite(net)) { this._log("warn", "registerTradeClosed: invalid netPnl", netPnl); return this.getCurrentRiskState(); }

      const before = this._state.consecutiveLossCount;
      if (net > 0) {
        this._state.consecutiveLossCount = 0;
        this._log("info", `WIN +$${net.toFixed(2)} → loss counter reset ${before} → 0`);
      } else if (net < 0) {
        this._state.consecutiveLossCount = before + 1;
        const lvl = this._state.consecutiveLossCount >= this.config.maxConsecutiveLosses ? "block" : "warn";
        this._log(lvl, `LOSS −$${Math.abs(net).toFixed(2)} → consecutive losses ${before} → ${this._state.consecutiveLossCount}`);
        if (this._state.consecutiveLossCount >= this.config.maxConsecutiveLosses) {
          this._log("block", `HARD STOP TRIPPED — ${this._state.consecutiveLossCount} consecutive losses. New entries blocked until manual reset.`);
        }
      } else {
        this._log("info", "Break-even trade — loss counter unchanged.");
      }
      this._persist();
      this._emit();
      return this.getCurrentRiskState();
    }

    /* --------------------------------------------------------- kill switch */
    activateKillSwitch(reason, action) {
      this._state.isKillSwitchActive = true;
      this._state.lastKillSwitchReason = reason || "manual";
      this._state.lastKillSwitchAction = action || null;
      this._state.lastKillSwitchTime = new Date().toISOString();
      this._persist();
      this._log("kill", `KILL SWITCH ACTIVATED — reason: ${this._state.lastKillSwitchReason}${action ? " · " + action : ""}. All new entries blocked.`);
      this._emit();
      return this.getCurrentRiskState();
    }
    deactivateKillSwitch() {
      this._state.isKillSwitchActive = false;
      // Keep lastKillSwitch* as an audit trail of the most recent activation.
      this._persist();
      this._log("info", "Kill switch deactivated — trading re-enabled (subject to loss counter).");
      this._emit();
      return this.getCurrentRiskState();
    }

    /* ------------------------------------------------------------- counter */
    resetConsecutiveLossCounter() {
      const before = this._state.consecutiveLossCount;
      this._state.consecutiveLossCount = 0;
      this._persist();
      this._log("info", `Consecutive-loss counter manually reset ${before} → 0.`);
      this._emit();
      return this.getCurrentRiskState();
    }

    /* ===================================================================
       HIGHER-TIMEFRAME BIAS (Weekly + 3D)
       The system only takes trades aligned with the higher-timeframe trend.
       A counter-trend entry is BLOCKED; a partially-aligned one is allowed
       but flagged so the UI can warn.
       =================================================================== */
    /** Set the Weekly + 3D bias for an instrument. */
    setBias(symbol, bias) {
      if (!symbol || !bias) return;
      const norm = v => {
        const s = String(v || "").toLowerCase();
        if (s.startsWith("bull") || s === "up" || s === "long") return "bull";
        if (s.startsWith("bear") || s === "down" || s === "short") return "bear";
        return "neutral";
      };
      this._bias[symbol] = { weekly: norm(bias.weekly), threeDay: norm(bias.threeDay != null ? bias.threeDay : bias.three_d) };
      this._emit();
      return this._bias[symbol];
    }
    getBias(symbol) { return this._bias[symbol] || null; }

    /**
     * Is `direction` aligned with the instrument's Weekly+3D bias?
     * @returns {{aligned:boolean, strength:"aligned"|"partial"|"counter"|"unknown", reason:string}}
     */
    checkBiasAlignment(symbol, direction) {
      const b = this._bias[symbol];
      if (!b) return { aligned: true, strength: "unknown", reason: "No HTF bias set — entry not bias-filtered" };
      const want = direction === "long" ? "bull" : "bear";
      const opp = direction === "long" ? "bear" : "bull";
      // Any higher timeframe pointing AGAINST the trade is a hard block.
      if (b.weekly === opp || b.threeDay === opp) {
        return { aligned: false, strength: "counter", reason: `Weekly+3D bias opposes ${direction} (W:${b.weekly} / 3D:${b.threeDay})` };
      }
      if (b.weekly === want && b.threeDay === want) {
        return { aligned: true, strength: "aligned", reason: "Weekly + 3D both confirm the direction" };
      }
      return { aligned: true, strength: "partial", reason: `Partial bias alignment (W:${b.weekly} / 3D:${b.threeDay}) — reduced conviction` };
    }

    /* ===================================================================
       OPEN POSITIONS · portfolio risk · TP1→breakeven
       =================================================================== */
    /** Open risk ($) still exposed on a single position, net of the BE move. */
    getPositionOpenRisk(pos) {
      if (!pos) return 0;
      const spec = this.getInstrumentSpec(pos.symbol);
      const dpp = this._num(pos.dollarsPerPoint, spec ? spec.dollarsPerPoint : 1);
      // After TP1 the stop sits at break-even (entry), so |entry-stop| → 0 and
      // the remaining runner carries essentially zero downside risk.
      const frac = pos.tp1Hit ? this._num(pos.remainingFraction, 1 - this.config.scaleOutPct) : 1;
      const perUnit = Math.abs(this._num(pos.entry, 0) - this._num(pos.stop, 0)) * dpp;
      return this._round(perUnit * this._num(pos.units, 0) * frac, 2);
    }
    getOpenPositions() { return Object.keys(this._positions).map(k => Object.assign({}, this._positions[k])); }
    getOpenRiskUsd() { return this._round(Object.keys(this._positions).reduce((s, k) => s + this.getPositionOpenRisk(this._positions[k]), 0), 2); }
    getOpenRiskPct() { return this.equity > 0 ? this._round(this.getOpenRiskUsd() / this.equity * 100, 2) : 0; }
    positionCount() { return Object.keys(this._positions).length; }

    /**
     * Seed open positions from the dashboard feed. Does NOT gate (these are
     * already-open trades), but DOES re-apply the TP1→BE rule against each
     * position's current price so restored state is internally consistent.
     */
    loadPositions(list) {
      this._positions = {};
      (list || []).forEach(p => {
        const spec = this.getInstrumentSpec(p.symbol);
        const pos = {
          symbol: p.symbol,
          direction: p.direction,
          entry: this._num(p.entry, 0),
          stop: this._num(p.stop, 0),
          initialStop: this._num(p.stop, 0),
          tp1: p.tp1 != null ? this._num(p.tp1, null) : null,
          target: this._num(p.target, 0),
          units: this._num(p.size_units, this._num(p.units, 0)),
          dollarsPerPoint: this._num(p.point_value, spec ? spec.dollarsPerPoint : 1),
          current: this._num(p.current, this._num(p.entry, 0)),
          entryCount: this._num(p.entry_count, 1),
          openedAt: p.opened_at || null,
          tp1Hit: !!p.tp1_hit,
          stopAtBreakeven: !!p.stop_at_breakeven,
          remainingFraction: p.tp1_hit ? (1 - this.config.scaleOutPct) : 1,
          scaleOutPct: this.config.scaleOutPct,
        };
        this._positions[p.symbol] = pos;
        // Re-evaluate TP1 against the latest price so a position whose price has
        // already passed TP1 shows the break-even stop immediately.
        this._applyTP1(pos, pos.current);
      });
      this._emit();
      return this.getOpenPositions();
    }

    /** Internal: apply the TP1 → break-even rule. Returns true if it fired. */
    _applyTP1(pos, price) {
      if (!pos || pos.tp1Hit || pos.tp1 == null) return false;
      const reached = pos.direction === "long" ? price >= pos.tp1 : price <= pos.tp1;
      if (!reached) return false;
      pos.tp1Hit = true;
      pos.scaledOutPct = this.config.scaleOutPct;          // booked 25% (default)
      pos.remainingFraction = 1 - this.config.scaleOutPct; // runner left on
      pos.stop = pos.entry;                                // ← MOVE STOP TO BREAK-EVEN
      pos.stopAtBreakeven = true;
      this._log("info", `TP1 hit on ${pos.symbol} @ ${pos.tp1} — scaled ${Math.round(pos.scaledOutPct * 100)}% out, stop moved to break-even (${pos.entry}). Runner is now risk-free.`);
      return true;
    }

    /**
     * Feed a fresh price for an instrument. The engine checks TP1 and, if hit,
     * automatically books the partial and moves the stop to break-even.
     * @returns {{event:string|null, position:Object|null}}
     */
    onPrice(symbol, price) {
      const pos = this._positions[symbol];
      if (!pos) return { event: null, position: null };
      pos.current = this._num(price, pos.current);
      const fired = this._applyTP1(pos, pos.current);
      if (fired) this._emit(); // open risk just dropped — UI + gates must refresh
      return { event: fired ? "tp1_breakeven" : null, position: Object.assign({}, pos) };
    }

    /**
     * Full pre-trade decision: base gate (kill/loss/equity) + HTF bias +
     * portfolio risk + max-positions. This is what the bot must call before
     * opening ANY new position or add-on.
     * @param {Object} intent {symbol, direction, riskUsd?, units?, entry?, stop?}
     */
    evaluateEntry(intent) {
      const base = this.canEnterNewTradeQuiet();
      if (!base.allowed) return base;
      if (!intent || !intent.symbol) return base;

      // Bias filter (Weekly + 3D).
      const bias = this.checkBiasAlignment(intent.symbol, intent.direction);
      if (!bias.aligned) {
        return { allowed: false, code: REASON.BIAS_CONFLICT, reason: bias.reason, bias };
      }

      // Max concurrent positions (a brand-new symbol only; add-ons don't count).
      const isAddOn = !!this._positions[intent.symbol];
      if (!isAddOn && this.positionCount() >= this.config.maxPositions) {
        return { allowed: false, code: REASON.MAX_POSITIONS, reason: `Max ${this.config.maxPositions} open positions reached`, bias };
      }

      // Portfolio risk cap — would this entry push total open risk over budget?
      const intentRisk = this._intentRiskUsd(intent);
      const projected = this.getOpenRiskUsd() + intentRisk;
      const cap = this.equity * (this.config.maxPortfolioRiskPct / 100);
      if (projected > cap + 1e-6) {
        return {
          allowed: false, code: REASON.PORTFOLIO_RISK_LIMIT,
          reason: `Open risk would be $${projected.toFixed(0)} > $${cap.toFixed(0)} cap (${this.config.maxPortfolioRiskPct}% of equity)`,
          bias, projectedRiskUsd: this._round(projected, 2), portfolioCapUsd: this._round(cap, 2),
        };
      }
      return { allowed: true, code: REASON.OK, reason: null, bias, projectedRiskUsd: this._round(projected, 2), portfolioCapUsd: this._round(cap, 2) };
    }

    // Risk ($) an intent would add: explicit riskUsd, else units×|entry-stop|×$pt.
    _intentRiskUsd(intent) {
      if (intent.riskUsd != null) return this._num(intent.riskUsd, 0);
      const spec = this.getInstrumentSpec(intent.symbol);
      const dpp = this._num(intent.dollarsPerPoint, spec ? spec.dollarsPerPoint : 1);
      const stopPts = Math.abs(this._num(intent.entry, 0) - this._num(intent.stop, 0));
      return this._round(stopPts * dpp * this._num(intent.units, 0), 2);
    }

    /**
     * Gated open / add-on. Runs evaluateEntry(); if allowed (or force), records
     * the position (or merges an add-on with weighted-average entry + summed
     * risk) and returns the decision with the resulting position attached.
     */
    addEntry(intent, opts = {}) {
      const decision = this.evaluateEntry(intent);
      if (!decision.allowed && !opts.force) {
        this._log("block", `Entry REJECTED (${intent.symbol} ${intent.direction}) — ${decision.reason}`);
        return Object.assign({}, decision, { committed: false, position: this._positions[intent.symbol] ? Object.assign({}, this._positions[intent.symbol]) : null });
      }
      const spec = this.getInstrumentSpec(intent.symbol);
      const dpp = this._num(intent.dollarsPerPoint, spec ? spec.dollarsPerPoint : 1);
      const existing = this._positions[intent.symbol];
      if (existing && existing.direction === intent.direction) {
        // Add-on: weighted-average entry, sum units, advance stop/tp1/target.
        const u0 = existing.units, u1 = this._num(intent.units, 0), uT = u0 + u1;
        existing.entry = uT > 0 ? this._round((existing.entry * u0 + this._num(intent.entry, existing.entry) * u1) / uT, 4) : existing.entry;
        existing.units = uT;
        existing.entryCount += 1;
        if (intent.stop != null) existing.stop = this._num(intent.stop, existing.stop);
        if (intent.tp1 != null) existing.tp1 = this._num(intent.tp1, existing.tp1);
        if (intent.target != null) existing.target = this._num(intent.target, existing.target);
        existing.tp1Hit = false; existing.stopAtBreakeven = false; existing.remainingFraction = 1;
        this._log("info", `ADD-ON ${intent.symbol} ${intent.direction} — entry #${existing.entryCount}, avg ${existing.entry}, units ${existing.units}`);
      } else {
        this._positions[intent.symbol] = {
          symbol: intent.symbol, direction: intent.direction,
          entry: this._num(intent.entry, 0), stop: this._num(intent.stop, 0), initialStop: this._num(intent.stop, 0),
          tp1: intent.tp1 != null ? this._num(intent.tp1, null) : null, target: this._num(intent.target, 0),
          units: this._num(intent.units, 0), dollarsPerPoint: dpp,
          current: this._num(intent.entry, 0), entryCount: 1, openedAt: new Date().toISOString(),
          tp1Hit: false, stopAtBreakeven: false, remainingFraction: 1, scaleOutPct: this.config.scaleOutPct,
        };
        this._log("info", `OPEN ${intent.symbol} ${intent.direction} — entry ${intent.entry}, stop ${intent.stop}, units ${intent.units}, risk $${this._intentRiskUsd(intent)}`);
      }
      this._emit();
      return Object.assign({}, decision, { committed: true, position: Object.assign({}, this._positions[intent.symbol]) });
    }

    /**
     * Close a position at exitPrice, register the net P/L against the loss
     * counter, and remove it from the book.
     */
    closePosition(symbol, exitPrice) {
      const pos = this._positions[symbol];
      if (!pos) return { closed: false, netPnl: 0, state: this.getCurrentRiskState() };
      const m = pos.direction === "long" ? 1 : -1;
      const netPnl = this._round(m * (this._num(exitPrice, pos.current) - pos.entry) * pos.dollarsPerPoint * pos.units, 2);
      delete this._positions[symbol];
      const state = this.registerTradeClosed(netPnl); // persists + emits
      this._log("info", `CLOSE ${symbol} @ ${exitPrice} — net $${netPnl}`);
      return { closed: true, netPnl, state };
    }

    /** Snapshot of the open book for the UI. */
    getPortfolioState() {
      return {
        positions: this.getOpenPositions(),
        positionCount: this.positionCount(),
        openRiskUsd: this.getOpenRiskUsd(),
        openRiskPct: this.getOpenRiskPct(),
        portfolioCapUsd: this._round(this.equity * this.config.maxPortfolioRiskPct / 100, 2),
        maxPortfolioRiskPct: this.config.maxPortfolioRiskPct,
        maxPositions: this.config.maxPositions,
      };
    }

    /* --------------------------------------------------------------- state */
    getCurrentRiskState() {
      const gate = this.canEnterNewTradeQuiet();
      const count = this._state.consecutiveLossCount;
      const max = this.config.maxConsecutiveLosses;
      return {
        consecutiveLossCount: count,
        maxConsecutiveLosses: max,
        isPausedByLosses: count >= max,
        isWarning: count === max - 1,
        isKillSwitchActive: this._state.isKillSwitchActive,
        lastKillSwitchReason: this._state.lastKillSwitchReason,
        lastKillSwitchTime: this._state.lastKillSwitchTime,
        lastKillSwitchAction: this._state.lastKillSwitchAction,
        equity: this.equity,
        maxRiskPerTradePct: this.config.maxRiskPerTradePct,
        maxRiskUsd: this._round(this.equity * this.config.maxRiskPerTradePct / 100, 2),
        canEnter: gate.allowed,
        blockReason: gate.reason,
        blockCode: gate.code,
        // portfolio / book-level risk
        positionCount: this.positionCount(),
        maxPositions: this.config.maxPositions,
        openRiskUsd: this.getOpenRiskUsd(),
        openRiskPct: this.getOpenRiskPct(),
        maxPortfolioRiskPct: this.config.maxPortfolioRiskPct,
        portfolioCapUsd: this._round(this.equity * this.config.maxPortfolioRiskPct / 100, 2),
        scaleOutPct: this.config.scaleOutPct,
      };
    }

    // Same logic as canEnterNewTrade but without logging — used by state getter
    // so simply reading state doesn't spam the console.
    canEnterNewTradeQuiet() {
      if (this._state.isKillSwitchActive) return { allowed: false, code: REASON.KILL_SWITCH, reason: `Kill switch active (${this._state.lastKillSwitchReason || "manual"})` };
      if (this._state.consecutiveLossCount >= this.config.maxConsecutiveLosses) return { allowed: false, code: REASON.CONSECUTIVE_LOSS_LIMIT, reason: `${this._state.consecutiveLossCount} consecutive losses — hard stop` };
      if (!Number.isFinite(this.equity) || this.equity <= 0) return { allowed: false, code: REASON.EQUITY_INVALID, reason: "Equity invalid" };
      return { allowed: true, code: REASON.OK, reason: null };
    }
  }

  // Expose constants for callers/tests.
  RiskManager.REASON = REASON;
  RiskManager.DEFAULT_INSTRUMENTS = DEFAULT_INSTRUMENTS;

  // UMD-ish export: window global for the browser, module.exports for Node.
  if (typeof module !== "undefined" && module.exports) module.exports = RiskManager;
  else global.RiskManager = RiskManager;

})(typeof window !== "undefined" ? window : this);

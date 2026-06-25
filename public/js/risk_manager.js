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
     5. Position sizing respects the 2% rule AND per-instrument point values.
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
        maxRiskPerTradePct: cfg.maxRiskPerTradePct != null ? cfg.maxRiskPerTradePct : 2.0,
        maxConsecutiveLosses: cfg.maxConsecutiveLosses != null ? cfg.maxConsecutiveLosses : 3,
      };
      this.instruments = Object.assign({}, DEFAULT_INSTRUMENTS, cfg.instruments || {});
      this.equity = this._num(cfg.equity, 0);
      this.verbose = cfg.verbose !== false;
      this._storage = cfg.storage || (typeof localStorage !== "undefined" ? localStorage : null);
      this._listeners = [];

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

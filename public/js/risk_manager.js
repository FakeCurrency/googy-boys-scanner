/* ===========================================================================
   risk_manager.js — Vivek 5.0 / AI Bot
   ---------------------------------------------------------------------------
   A real, enforceable risk-management engine.

   DESIGN NOTES
   - This module is intentionally DOM-FREE. It holds state + rules + maths only.
     The UI (bot.js) subscribes via `subscribe(fn)` and re-renders whenever the
     engine emits a change. That keeps this file trivially portable to a Node /
     backend service later — swap the localStorage adapter for a DB and the rest
     is unchanged.
   - All mutating methods: validate input → mutate → persist → log → emit.
   - The engine is the single source of truth for: consecutive-loss count and
     kill-switch state. It is NOT the source of truth for the RULES — every
     threshold is published by scanner/config.py via data/bot_rules.json and
     seeded in by bot.js; PUBLISHED_DEFAULTS below is a mirror for the offline
     case. The dashboard JSON is only a seed on first run and a feed for live
     equity.
   - SCOPE, so the rules below are not read as more than they are: this engine
     gates the entry checks that run IN THIS PAGE. It holds no broker
     connection, places no order, and nothing in scanner/broker/ reads it back.

   HARD RULES ENFORCED
     1. Max risk per trade = maxRiskPerTradePct of CURRENT equity.
     2. Block all new entries at maxConsecutiveLosses in a row.
     3. The loss counter ONLY resets on a winning trade (net P/L > 0) or a
        manual reset. Break-even (net == 0) leaves it unchanged.
     4. An active kill switch also blocks all new entries.
     5. Position sizing respects rule 1 AND per-instrument point values.
     6. TP1 → book scaleOutPct + move stop to break-even → risk-free runner.
     7. Weekly+3D higher-timeframe bias blocks counter-trend entries.
     8. closePosition() computes start time, duration, fees and realized P/L
        for the trade journal.
   =========================================================================== */
(function (global) {
  "use strict";

  // ── Persistence key (single namespaced blob — easy to migrate to a DB) ─────
  const STORE_KEY = "gbs_risk_state_v1";

  // Legacy keys from the pre-engine UI — migrated on first construction.
  const LEGACY_COUNTER_KEY = "gbs_bot_counter_v1";
  const LEGACY_KILL_KEY = "gbs_bot_kill_v1";

  // ── Published engine constants — MIRRORS, not opinions (TOP100 #34) ────────
  //
  // Every value here is a copy of a `scanner/config.py` constant, and each is
  // named beside the constant it mirrors. They used to be five bare literals
  // buried in the constructor's `!= null ? … : X` chain, where nothing declared
  // them as copies of anything and nothing could check them — so they drifted,
  // for months, in the direction that is hardest to notice: the page kept
  // saying a smaller, safer-sounding number than the engine was running.
  //
  //   maxRiskPerTradePct   0.25 → 0.35   VIVEK_BOT_RISK_PCT
  //   maxPortfolioRiskPct  2.0  → 7.0    PORTFOLIO_HEAT_LIMIT (0.07) × 100
  //   maxPositions         5    → 30     VIVEK_BOT_MAX_POSITIONS
  //   maxConsecutiveLosses 3    = 3      CONSEC_LOSS_PAUSE
  //   scaleOutPct          0.25 = 0.25   VIVEK_TP_SCALE_LONG[0]
  //
  // THE PORTFOLIO CAP IS THE ONE THAT MATTERED, and it broke the page's own
  // internal arithmetic rather than merely disagreeing with Python. bot.js
  // already adopted `risk_pct` (0.35) and `max_positions` (30) from
  // bot_rules.json but had no key to adopt the third with, so the live page ran
  // 0.35% per trade against a 2% book cap — a ceiling that binds at 5.7
  // positions while the panel two rows up advertises 30. Attempt Entry number
  // six was refused as a PORTFOLIO_RISK_LIMIT breach on a book the executing
  // bot considers a fifth full. Seeding two of three numbers is worse than
  // seeding none: it produces a coherent-looking engine that is internally
  // impossible.
  //
  // FLAGGED, because the direction is a LOOSENING: raising the cap lets this
  // page's entry checks pass trades the 2% version refused. It is in bounds
  // only because nothing here reaches a broker — this engine gates the advisory
  // checks that run in the browser, holds no connection, and is never read by
  // `scanner/broker/` (see the kill-switch note in bot.js). 7.0 is not a number
  // chosen here; it is PORTFOLIO_HEAT_LIMIT, which is what the Python twin of
  // this layer (`broker/risk_manager.py` → `pre_trade_check`) has enforced all
  // along.
  //
  // These are FALLBACKS. bot.js overrides all five from bot_rules.json on every
  // load; they are what an offline page, a unit test or a bare `new
  // RiskManager({equity})` gets. That is exactly why they must match: a fallback
  // that disagrees with the published value has not removed the drift, it has
  // moved it somewhere with no drift warning. `test/risk_defaults.test.js`
  // parses scanner/config.py and fails if any pair below stops agreeing.
  const PUBLISHED_DEFAULTS = {
    maxRiskPerTradePct: 0.35,   // config.VIVEK_BOT_RISK_PCT
    maxConsecutiveLosses: 3,    // config.CONSEC_LOSS_PAUSE
    maxPortfolioRiskPct: 7.0,   // config.PORTFOLIO_HEAT_LIMIT * 100
    scaleOutPct: 0.25,          // config.VIVEK_TP_SCALE_LONG[0]
    maxPositions: 30,           // config.VIVEK_BOT_MAX_POSITIONS
  };

  // ── Instrument specifications ──────────────────────────────────────────────
  // dollarsPerPoint  : P/L in USD for a 1.00 move in price, per 1 unit.
  // volatilityFactor : scales the risk budget DOWN for jumpy instruments so the
  //                    engine sizes them smaller (NatGas especially).
  // minStopPoints    : a sane floor to reject absurdly tight stops.
  // unitStep         : tradeable increment. ABSENT = the legacy futures/CFD
  //                    rounding (0.1 lots at or above 1, 0.01 below).
  // unitLabel        : what one unit is called, for the calculator's prose.
  // tickValue is implied by dollarsPerPoint; keep it simple for now.
  //
  // TOP100 #35 — THE THREE `STOCK*`/`CRYPTO` ROWS ARE THE ADDITION, and the
  // reason is that this table listed six futures contracts and nothing else,
  // while the system it belongs to trades ASX equities, NASDAQ equities and
  // crypto perps and has never sent an order for /NQ, YM, GC, SI, CL or NG in
  // its life. So the Size Calculator answered fluently for six instruments that
  // do not exist here and returned `Unknown instrument "BHP.AX"` for the three
  // that do — a calculator that works only on the trades you will never take.
  //
  // The futures rows STAY. They are not dead weight: 48 tests in
  // test/risk_manager.test.js exercise the sizing maths through them, and
  // deleting the rows would delete that coverage to make a cosmetic point. They
  // are simply no longer the only thing on offer.
  //
  // `unitStep: 1` on the equity rows is the substantive half. The legacy
  // rounding hands back 0.1-granularity sizes, so before this the calculator's
  // honest answer for a share would have been "buy 12.4 shares" — a size no
  // exchange will accept, presented to two decimal places as though it were
  // precise. Crypto keeps a fine step because fractional coins are real.
  const DEFAULT_INSTRUMENTS = {
    "/NQ": { name: "NAS100", dollarsPerPoint: 20,   volatilityFactor: 1.0, minStopPoints: 10 },
    "/YM": { name: "US30",   dollarsPerPoint: 5,    volatilityFactor: 1.0, minStopPoints: 10 },
    "GC":  { name: "Gold",   dollarsPerPoint: 100,  volatilityFactor: 1.0, minStopPoints: 1 },
    "SI":  { name: "Silver", dollarsPerPoint: 50,   volatilityFactor: 0.8, minStopPoints: 0.05 },
    "CL":  { name: "Crude",  dollarsPerPoint: 1000, volatilityFactor: 0.7, minStopPoints: 0.05 },
    // NatGas is the most volatile of the set — a deliberately reduced factor
    // shrinks its position size for the same nominal stop.
    "NG":  { name: "NatGas", dollarsPerPoint: 1000, volatilityFactor: 0.4, minStopPoints: 0.02 },

    // ── What this system actually trades ─────────────────────────────────
    // volatilityFactor is 1.0 on all three ON PURPOSE. The haircuts above are
    // per-CONTRACT judgements about six named instruments; there is no
    // equivalent per-name number for 2,212 ASX tickers, and the executing bot
    // applies none — it sizes every name at the same fixed notional
    // (VIVEK_BOT_POSITION_NOTIONAL). Inventing a 0.7 for "crypto is jumpy"
    // would be a risk parameter with no source, which is the whole class of
    // problem #34 just finished removing.
    // minStopPoints is 0 because a floor in POINTS cannot express what the
    // executing bot enforces: VIVEK_BOT_MIN_STOP_PCT is a PERCENTAGE, and 0.05
    // points is a wide stop on a 40c ASX name and a rounding error on MDB. A
    // wrong floor here would fire on the cheap names and never on the dear
    // ones, so there is none rather than a decorative one.
    "STOCK":    { name: "US stock",    dollarsPerPoint: 1,    volatilityFactor: 1.0, minStopPoints: 0, unitStep: 1,      unitLabel: "share", quoteCcy: "USD" },
    // dollarsPerPoint is the AUD/USD rate: a 1.00 AUD move on one share is
    // US$0.70, and the book is denominated in USD. 0.66 is only the offline
    // fallback — bot.js overrides it from data/fx.json, the same published rate
    // journal.js converts ASX P&L with, so the two pages cannot disagree about
    // what an ASX dollar is worth.
    "STOCK.AX": { name: "ASX stock",   dollarsPerPoint: 0.66, volatilityFactor: 1.0, minStopPoints: 0, unitStep: 1,      unitLabel: "share", quoteCcy: "AUD" },
    "CRYPTO":   { name: "Crypto perp", dollarsPerPoint: 1,    volatilityFactor: 1.0, minStopPoints: 0, unitStep: 0.0001, unitLabel: "unit",  quoteCcy: "USD" },
  };

  // Aliases so callers can pass either the ticker or the friendly name.
  // NOTE the new entries alias CLASSES, never individual tickers. Aliasing
  // "BHP.AX" → STOCK.AX for the whole ASX universe is the tempting next step
  // and it is a trap: `loadPositions` falls back to dollarsPerPoint 1 for an
  // unknown symbol, so a half-populated alias map would silently price SOME
  // ASX positions in AUD-as-USD and others correctly, with no way to tell which
  // from the screen. One explicit class, chosen by the user, or nothing.
  const ALIASES = {
    "NAS100": "/NQ", "NQ": "/NQ",
    "US30": "/YM", "YM": "/YM", "/YM": "/YM",
    "GOLD": "GC", "XAU": "GC",
    "SILVER": "SI", "XAG": "SI",
    "CRUDE": "CL", "OIL": "CL", "WTI": "CL",
    "NATGAS": "NG", "NATURALGAS": "NG", "GAS": "NG",
    "SHARE": "STOCK", "EQUITY": "STOCK", "US": "STOCK", "NASDAQ": "STOCK",
    "ASX": "STOCK.AX", "STOCKAX": "STOCK.AX", "AU": "STOCK.AX",
    "PERP": "CRYPTO", "COIN": "CRYPTO",
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
    // SOFT block from the Portfolio Intelligence layer — the hard rules all
    // passed, but the current book context says "not now / not this one".
    STANCE_DEFERRED: "STANCE_DEFERRED",
  };

  // ───────────────────────────────────────────────────────────────────────────
  class RiskManager {
    /**
     * @param {Object}  cfg
     * @param {number}  cfg.equity                 Account equity (USD). Seed from
     *                                             bot_status.json / broker wallet;
     *                                             never hardcode in production.
     * Every default below comes from PUBLISHED_DEFAULTS — a mirror of
     * scanner/config.py, not a second opinion. Do not restate the numbers in
     * this docblock: they moved once already while the prose said otherwise.
     *
     * @param {number}  [cfg.maxRiskPerTradePct]   Max risk per trade as % of equity.
     * @param {number}  [cfg.maxConsecutiveLosses] Hard-stop after N losses in a row.
     * @param {number}  [cfg.maxPortfolioRiskPct]  Cap on TOTAL open risk across the
     *                                             whole book, as % of equity.
     * @param {number}  [cfg.scaleOutPct]          Fraction booked at TP1 (rest runs).
     * @param {number}  [cfg.maxPositions]         Hard cap on concurrent open
     *                                             positions.
     * @param {number}  [cfg.roundTurnFeeUsd]      Entry+exit fees booked on close,
     *                                             used for net P/L. Default 2.0.
     * @param {Object}  [cfg.instruments]          Override/extend instrument specs.
     * @param {Storage} [cfg.storage]              Defaults to window.localStorage.
     * @param {boolean} [cfg.verbose]              Console logging (default true).
     */
    constructor(cfg = {}) {
      this.config = {
        // Risk budget per trade as a % of CURRENT equity. NOTE the executing
        // bot has been in FIXED-NOTIONAL mode since 2026-07-28, where this is a
        // derived per-trade figure rather than an input (CLAUDE.md "Position
        // sizing is FIXED NOTIONAL"); this page still sizes off it because the
        // sizing calculator's whole job is "what would N% of equity buy me".
        maxRiskPerTradePct: cfg.maxRiskPerTradePct != null ? cfg.maxRiskPerTradePct : PUBLISHED_DEFAULTS.maxRiskPerTradePct,
        // Block all new entries once this many consecutive losses is reached.
        maxConsecutiveLosses: cfg.maxConsecutiveLosses != null ? cfg.maxConsecutiveLosses : PUBLISHED_DEFAULTS.maxConsecutiveLosses,
        // Total open risk across ALL positions may not exceed this % of equity.
        // Must stay >= maxRiskPerTradePct × maxPositions or the position cap is
        // unreachable and the page contradicts itself — the exact state #34
        // found (0.35 × 30 = 10.5% of open risk allowed by one rule, 2% by the
        // other). It is still the tighter of the two at 7%, which is the point:
        // it is a book-level ceiling, not a restatement of the slot count.
        maxPortfolioRiskPct: cfg.maxPortfolioRiskPct != null ? cfg.maxPortfolioRiskPct : PUBLISHED_DEFAULTS.maxPortfolioRiskPct,
        // Fraction of a position closed when TP1 is reached (the rest runs).
        // The engine holds ONE number; the ladder is side-dependent upstream
        // (VIVEK_TP_SCALE_SHORT banks 0.50 at TP1). bot.js seeds the LONG value
        // because this page's book is long-only in practice — a short seeded
        // here would under-book its own runner, so it is left to the caller
        // rather than guessed per position.
        scaleOutPct: cfg.scaleOutPct != null ? cfg.scaleOutPct : PUBLISHED_DEFAULTS.scaleOutPct,
        // Hard cap on number of concurrent open positions.
        maxPositions: cfg.maxPositions != null ? cfg.maxPositions : PUBLISHED_DEFAULTS.maxPositions,
        // Round-turn cost (entry + exit fees/commission) booked against a trade
        // when it closes. Used by closePosition() to compute net P/L for the
        // journal. Override per-close via opts.costs if you have exact fills.
        // LEGACY FALLBACK ONLY (2026-07-20, review H8): when the bps model
        // below is configured (bot.js seeds it from bot_rules.json), costs
        // scale with notional like the Python book; this flat fee applies
        // only when no bps values are set.
        roundTurnFeeUsd: cfg.roundTurnFeeUsd != null ? cfg.roundTurnFeeUsd : 2.0,
        // Execution costs in BASIS POINTS of notional, mirroring the Python
        // book's model (scanner/config.py VIVEK_COMMISSION_BPS /
        // VIVEK_SLIPPAGE_BPS, published in bot_rules.json). Charged on the
        // entry leg and on the market-style exit leg of a close. 0 = unset.
        commissionBps: cfg.commissionBps != null ? cfg.commissionBps : 0,
        slippageBps: cfg.slippageBps != null ? cfg.slippageBps : 0,

        // ── Portfolio Intelligence (book-context layer) ───────────────────
        // A SOFT layer over the hard rules. It tunes how aggressively freed
        // risk is redeployed based on book health. It can only make the bot
        // MORE selective or size DOWN — it never raises per-trade risk above
        // maxRiskPerTradePct nor total risk above maxPortfolioRiskPct.
        //
        // stanceCapFraction: fraction of the HARD portfolio cap the bot will
        //   actually deploy in each posture (aggressive uses it all; neutral
        //   keeps a buffer; defensive deploys half).
        stanceCapFraction: cfg.stanceCapFraction || { aggressive: 1.0, neutral: 0.85, defensive: 0.5, locked: 0 },
        // stanceSizeMult: per-trade size multiplier by posture (advisory; the
        //   caller applies it). Capped at 1.0 so it can only ever size DOWN.
        stanceSizeMult: cfg.stanceSizeMult || { aggressive: 1.0, neutral: 1.0, defensive: 0.5, locked: 0 },
        // Book-health thresholds (0..100) that map to posture labels.
        healthAggressiveAt: cfg.healthAggressiveAt != null ? cfg.healthAggressiveAt : 68,
        healthDefensiveAt: cfg.healthDefensiveAt != null ? cfg.healthDefensiveAt : 42,
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
      // Optional callback fired with each closed trade's journalEntry, for
      // backend persistence. Null = browser-only (default). See setPersistHook.
      this._persistHook = null;

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
      if (patch.roundTurnFeeUsd != null) {
        const v = Math.max(0, this._num(patch.roundTurnFeeUsd, this.config.roundTurnFeeUsd));
        if (v !== this.config.roundTurnFeeUsd) { this.config.roundTurnFeeUsd = v; changed = true; }
      }
      // bps cost model (review H8) — patched from bot_rules.json by bot.js.
      for (const k of ["commissionBps", "slippageBps"]) {
        if (patch[k] != null) {
          const v = Math.max(0, this._num(patch[k], this.config[k]));
          if (v !== this.config[k]) { this.config[k] = v; changed = true; }
        }
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
     * POSITION SIZING — the 0.25% rule in code.
     * Sizes a trade so the loss-if-stopped equals AT MOST the per-trade risk
     * budget (maxRiskPerTradePct % of equity), scaled down by the instrument's
     * volatility factor and converted to units via its $/point value. Units are
     * always floored, so the realised risk can never exceed the budget.
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
        // TOP100 #35 — carried out so the calculator can say "shares" rather
        // than "contracts" and label the $/point row in the right currency.
        unitLabel: spec ? (spec.unitLabel || "contract") : null,
        unitStep: spec ? (spec.unitStep || null) : null,
        quoteCcy: spec ? (spec.quoteCcy || "USD") : null,
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

      // ── The per-trade risk rule, volatility-adjusted ─────────────────────
      // No number named here on purpose (TOP100 #34): this comment said "0.25%
      // default" for months after the default became 0.35%, in the one place no
      // test could catch it. The value is config.maxRiskPerTradePct, seeded from
      // bot_rules.json and mirrored by PUBLISHED_DEFAULTS.
      const maxRiskUsd = this.equity * (this.config.maxRiskPerTradePct / 100) * spec.volatilityFactor;
      const riskPerUnit = stop * spec.dollarsPerPoint;
      const rawUnits = riskPerUnit > 0 ? maxRiskUsd / riskPerUnit : 0;

      // Whole futures contracts (floor) + a CFD/micro-friendly fractional size.
      const wholeContracts = Math.floor(rawUnits);
      // Always FLOOR so the resulting risk can never exceed the risk budget.
      // That invariant is why there is no epsilon anywhere below: a nudge to
      // rescue 12.9999999 → 13 would also let a genuinely-13.0000001 answer
      // through, and this rounding is the only thing standing between the
      // budget and a size that exceeds it. One share light beats one over.
      //
      // TOP100 #35: `unitStep` is the tradeable increment. Absent (every
      // futures row, and therefore every pre-existing test) the legacy
      // 0.1/0.01 rounding applies unchanged; present, the size lands on a
      // multiple of it, so an equity comes back as whole shares instead of
      // "12.4 shares" and a crypto perp keeps its fractional precision.
      const step = this._num(spec.unitStep, 0);
      const recommendedUnits = step > 0
        ? +(Math.floor(rawUnits / step) * step).toFixed(Math.max(0, -Math.floor(Math.log10(step))))
        : (rawUnits >= 1
          ? Math.floor(rawUnits * 10) / 10      // 0.1-lot granularity once >= 1
          : Math.max(0, Math.floor(rawUnits * 100) / 100)); // 0.01 granularity sub-1
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
      // TOP100 #35: "use a micro/CFD lot" was the advice for every instrument
      // that could not carry one whole unit. It is sound for a futures contract,
      // and it is nonsense twice over otherwise — there is no micro-BHP, and a
      // crypto perp sized at 0.0038 has no problem to solve, that IS the size.
      // Three instruments, three readings, so the branch is on `step`:
      //   step >= 1 (shares)  — a sub-1 answer is genuinely unfillable, say so.
      //   0 < step < 1 (perp) — fractional is the normal case, say NOTHING. The
      //                         old text told you to fix a trade that was fine.
      //   step === 0 (future) — unchanged, and `feasibleWholeContract` means
      //                         what it says on a contract. (`_num(…, 0)` above
      //                         maps an absent unitStep to 0, never to null.)
      if (!out.feasibleWholeContract && !out.note && !(step > 0 && step < 1)) {
        const unit = spec.unitLabel || "contract";
        out.note = (step >= 1)
          ? `Not even 1 ${unit} fits the ${this.config.maxRiskPerTradePct}% budget at this stop — widen the budget or tighten the stop.`
          : `< 1 full ${unit} fits the ${this.config.maxRiskPerTradePct}% budget — use a micro/CFD lot.`;
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
     * CONSECUTIVE-LOSS HARD STOP — the counter that gates new entries.
     * Records a closed trade's net P/L and updates the loss counter:
     *   Win (net>0) → reset to 0. Loss (net<0) → +1. Break-even → unchanged.
     * When the counter reaches maxConsecutiveLosses the entry gate
     * (canEnterNewTrade) blocks ALL new entries until a manual reset. The
     * counter is persisted so the hard stop survives a page refresh.
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
      // TOP100 #27. This engine gates the ENTRY CHECKS THAT RUN IN THIS PAGE and
      // nothing else — it holds no broker connection and the server bot never
      // reads it. "All new entries blocked" read as a system-wide halt; it is a
      // halt of this device's advisory layer.
      this._log("kill", `KILL SWITCH ACTIVATED — reason: ${this._state.lastKillSwitchReason}${action ? " · " + action : ""}. New entries blocked in this browser; open positions and the server bot are unaffected.`);
      this._emit();
      return this.getCurrentRiskState();
    }
    deactivateKillSwitch() {
      this._state.isKillSwitchActive = false;
      // Keep lastKillSwitch* as an audit trail of the most recent activation.
      this._persist();
      this._log("info", "Kill switch deactivated — this browser accepts new entries again (subject to loss counter).");
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
     * WEEKLY+3D BIAS FILTER — blocks counter-trend entries.
     * Compares the intended `direction` against the instrument's stored Weekly
     * and 3-Day bias. If EITHER higher timeframe points against the trade it's a
     * hard block (strength "counter", aligned:false → evaluateEntry rejects it).
     * Both-confirm = "aligned"; mixed-but-not-opposing = "partial" (allowed,
     * flagged for the UI). No bias set = "unknown" (not filtered).
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
     *
     * POINT-VALUE PROVENANCE (2026-07-28). `dollarsPerPoint` decides what a
     * one-point move is WORTH, and it is resolved from three places of very
     * different authority: the feed's own `point_value`, the instrument table,
     * or — for anything the table does not know — a bare `1`. The ALIASES note
     * above already calls the unknown-symbol fallback a trap, and names the
     * reason it cannot be fixed by widening the alias map: a half-populated map
     * prices SOME ASX positions in AUD-as-USD and others correctly, "with no
     * way to tell which from the screen."
     *
     * `pointValueSource` is that way to tell. It does NOT change any number —
     * the arithmetic on the line below is byte-for-byte what it was — it
     * records which of the three answers was used, so an unpriced position is
     * a thing you can see and count rather than a thing you can only deduce.
     * Whether bare ASX tickers should resolve to the STOCK.AX class is a
     * sizing decision and stays the owner's.
     *
     * Worth knowing while reading this: NOTHING in the repo writes
     * `point_value` — the only reference is the read below — so today the feed
     * branch is unreachable and every position takes the spec-or-fallback
     * path. The `1` is correct for a US share (US$1 per US$1 of price) and
     * wrong for an ASX one by the AUD/USD rate.
     */
    loadPositions(list) {
      this._positions = {};
      const unpriced = [];
      (list || []).forEach(p => {
        const spec = this.getInstrumentSpec(p.symbol);
        const fed = Number.isFinite(Number(p.point_value));
        if (!fed && !spec) unpriced.push(p.symbol);
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
          pointValueSource: fed ? "feed" : (spec ? `spec:${spec.symbol}` : "fallback"),
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
      if (unpriced.length) {
        this._log("warn",
          `${unpriced.length} position(s) have no $/point source and fell back to 1: ` +
          `${unpriced.join(", ")}. For a US share that is correct; for an ASX one it ` +
          `prices an AUD move as USD (~43% overstated at 0.70). Open risk and ` +
          `unrealised P&L for these rows are in the quote currency, not the book's.`);
      }
      this._emit();
      return this.getOpenPositions();
    }

    /**
     * Which open positions are priced by the bare `1` fallback rather than by
     * the feed or the instrument table. The counterpart to `pointValueSource`:
     * a caller that wants to badge or refuse these rows asks here instead of
     * re-deriving the resolution rules and drifting from them.
     */
    getUnpricedPositions() {
      return this.getOpenPositions()
        .filter(p => p.pointValueSource === "fallback")
        .map(p => p.symbol);
    }

    /**
     * TP1 → SCALE OUT → BREAK-EVEN (the risk-free-runner rule), in code.
     * When `price` reaches a position's TP1, this books `scaleOutPct` (25%) of
     * the size and moves the stop to the entry price, so the remaining runner
     * carries ~zero downside (see getPositionOpenRisk). Fires at most once per
     * position (guarded by tp1Hit). Called from onPrice() on every fresh tick
     * and from loadPositions() when restoring state.
     * @returns {boolean} true if the rule fired on this call.
     */
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

    /* ===================================================================
       LIVE PRICE FEED — single entry point for market data.
       -------------------------------------------------------------------
       onPrice() is the ONLY place a fresh market price enters the engine.
       Today it is called manually (the dashboard "Sim → TP1" button). To go
       live, a price-feed adapter just needs to call onPrice() / onPrices() on
       every tick — no other engine code changes.

       TODO (integration phase): wire a Bybit or Binance WebSocket adapter, e.g.
         const ws = new WebSocket("wss://stream.bybit.com/v5/public/linear");
         ws.onmessage = (ev) => {
           const { symbol, price } = parseTick(ev.data);  // map venue symbol → engine symbol
           risk.onPrice(symbol, price);                   // TP1→BE fires automatically
         };
       The adapter is responsible ONLY for connection + symbol mapping; all
       risk/exit logic stays here. Keep the same contract for a Node/backend
       feed so this engine ports unchanged (see DESIGN NOTES at top of file).
       =================================================================== */

    /**
     * Feed a fresh price for ONE instrument. The engine checks TP1 and, if hit,
     * automatically books the partial and moves the stop to break-even, then
     * emits so the UI + entry gates refresh.
     * @param {string} symbol  Engine symbol (e.g. "/NQ", "GC") — already mapped
     *                         from the venue's symbol by the feed adapter.
     * @param {number} price   Latest traded/mark price.
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
     * Batch variant of onPrice() for a WebSocket adapter that receives a
     * snapshot of several symbols per frame. Applies each tick and emits ONCE
     * if any position changed (avoids a render storm on busy frames).
     * @param {Object<string,number>} priceMap  { "/NQ": 20440, "GC": 2620, … }
     * @returns {string[]} symbols whose TP1→BE fired on this batch.
     */
    onPrices(priceMap) {
      const fired = [];
      Object.keys(priceMap || {}).forEach(sym => {
        const pos = this._positions[sym];
        if (!pos) return;
        pos.current = this._num(priceMap[sym], pos.current);
        if (this._applyTP1(pos, pos.current)) fired.push(sym);
      });
      if (fired.length) this._emit();
      return fired;
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
     * CLOSE A TRADE — books P/L, updates the loss counter, journals the result.
     * Closes a position at exitPrice, registers net P/L against the consecutive-
     * loss counter, removes it from the book, and returns a full `journalEntry`
     * (start time, duration, gross, costs/fees, realized net P/L, R-multiple).
     *
     * The returned `journalEntry` is the single source of truth for one closed
     * trade. The browser prepends it to the on-page journal today; the SAME
     * object is the intended payload for backend persistence later (see the
     * JOURNAL PERSISTENCE block below for the snake_case mapping to
     * journal/scalp_journal.json).
     *
     * @param {string} symbol
     * @param {number} exitPrice
     * @param {Object} [opts]  {reason, costs}  — override exit reason / fees.
     * @returns {{closed, netPnl, gross, costs, r, state, journalEntry}}
     */
    /** Execution costs for one closed trade (review H8). Bps-of-notional on
     * both legs — entry fill + market-style exit (stop/manual/runner close),
     * matching the Python book's model — or the legacy flat fee when no bps
     * are configured. */
    _tradeCosts(pos, exit) {
      const c = this._num(this.config.commissionBps, 0), s = this._num(this.config.slippageBps, 0);
      if (!(c > 0 || s > 0)) return this.config.roundTurnFeeUsd;   // legacy fallback
      const dpp = pos.dollarsPerPoint || 1;
      const perLegBps = c + s;
      const entryNotional = Math.abs(pos.entry * dpp * pos.units);
      const exitNotional = Math.abs(exit * dpp * pos.units);
      return (entryNotional + exitNotional) * perLegBps / 10000;
    }

    closePosition(symbol, exitPrice, opts = {}) {
      const pos = this._positions[symbol];
      if (!pos) return { closed: false, netPnl: 0, gross: 0, costs: 0, r: 0, state: this.getCurrentRiskState(), journalEntry: null };

      const exit = this._num(exitPrice, pos.current);
      const m = pos.direction === "long" ? 1 : -1;
      // Gross = raw price move × point value × units. Costs = bps-of-notional
      // when the bot_rules model is configured (review H8), else the legacy
      // flat round-turn fee. A $50k notional now pays ~$35 at 7bps/leg, not $2.
      const gross = this._round(m * (exit - pos.entry) * pos.dollarsPerPoint * pos.units, 2);
      const costs = this._round(
        opts.costs != null ? this._num(opts.costs, 0) : this._tradeCosts(pos, exit), 2);
      const netPnl = this._round(gross - costs, 2);

      // R-multiple measured off the INITIAL stop (pre-breakeven), so a runner
      // closed beyond TP1 still reports the true reward-to-risk it was sized at.
      const denomStop = (pos.initialStop != null && pos.initialStop !== pos.entry) ? pos.initialStop : pos.stop;
      const riskUsd = Math.abs(pos.entry - denomStop) * pos.dollarsPerPoint * pos.units;
      const r = riskUsd > 0 ? this._round(gross / riskUsd, 2) : 0;

      const closedAt = new Date().toISOString();
      const openedAt = pos.openedAt || null;
      const durationMs = openedAt ? (Date.parse(closedAt) - Date.parse(openedAt)) : null;

      const journalEntry = {
        symbol, direction: pos.direction,
        entry: pos.entry, exit,
        units: pos.units, entryCount: pos.entryCount,
        opened: openedAt, closed: closedAt, durationMs,
        gross, costs, net: netPnl, r,
        win: netPnl > 0,
        reason: opts.reason || (pos.tp1Hit ? "Closed after TP1 (runner)" : "Manual close"),
      };

      delete this._positions[symbol];
      const state = this.registerTradeClosed(netPnl); // persists + emits + loss counter
      // Optional backend persistence (no-op unless setPersistHook() was called).
      if (this._persistHook) { try { this._persistHook(journalEntry); } catch (e) { this._log("warn", "persist hook failed", e); } }
      this._log("info", `CLOSE ${symbol} @ ${exit} — gross $${gross}, costs $${costs}, net $${netPnl} (${r}R)`);
      return { closed: true, netPnl, gross, costs, r, state, journalEntry };
    }

    /* ===================================================================
       JOURNAL PERSISTENCE — readiness hook (browser today, backend later).
       -------------------------------------------------------------------
       Closed trades are recorded in the browser today (bot.js prepends the
       journalEntry to the on-page table). To persist server-side, send the
       SAME journalEntry to a writer that appends to journal/scalp_journal.json.

       Engine (camelCase)        →  scalp_journal.json (snake_case)
         symbol                  →  symbol
         direction               →  direction
         entry / exit            →  entry / exit_price
         units                   →  units
         entryCount              →  entry_count
         opened / closed (ISO)   →  opened_ts / closed_ts
         durationMs              →  (derive hold_minutes)
         gross / costs / net     →  gross_pnl / fees / pnl
         r                       →  r_multiple
         reason                  →  exit_reason
         win                     →  (derive: pnl > 0)

       TODO (integration phase): implement ONE of —
         (a) Python: have bybit_run.py / reconcile.py append the broker fill
             (it already owns scalp_journal.json with _atomic_write); OR
         (b) Browser → backend: POST journalEntry to a Cloudflare Function that
             commits to the repo, e.g. setPersistHook(fn) wired in bot.js:
               risk.setPersistHook(e => fetch("/api/journal", {
                 method: "POST", body: JSON.stringify(e) }));
       Until then setPersistHook() is a no-op so the browser flow is unchanged.
       =================================================================== */

    /** Register an optional persistence callback for closed trades (see above). */
    setPersistHook(fn) { this._persistHook = (typeof fn === "function") ? fn : null; return this; }

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

    /* ===================================================================
       PORTFOLIO INTELLIGENCE LAYER
       -------------------------------------------------------------------
       Most bots are reactive and myopic: signal → rule check → enter or not,
       each trade in isolation. This layer gives the engine a sense of the
       WHOLE BOOK it is managing — how much risk is real vs already risk-free,
       whether runners are still working with the higher-timeframe trend, and
       whether the book's health argues for pressing or protecting. That
       context produces a POSTURE (aggressive / neutral / defensive / locked)
       which softly modulates new-risk appetite.

       Invariant: this layer NEVER loosens a hard rule. It can only defer or
       down-size. Every entry still passes evaluateEntry() (0.25% sizing,
       Weekly+3D bias, portfolio cap, max positions, 3-loss stop, kill switch)
       before the intelligence layer is even consulted.
       =================================================================== */

    /** Unrealized P/L ($) on a single position at its current price. */
    getPositionUnrealized(pos) {
      if (!pos) return 0;
      const spec = this.getInstrumentSpec(pos.symbol);
      const dpp = this._num(pos.dollarsPerPoint, spec ? spec.dollarsPerPoint : 1);
      const sign = pos.direction === "long" ? 1 : -1;
      return this._round(sign * (this._num(pos.current, pos.entry) - this._num(pos.entry, 0)) * dpp * this._num(pos.units, 0), 2);
    }

    /** Initial (as-sized) risk ($) on a position, measured off its ORIGINAL stop. */
    _initialRiskUsd(pos) {
      const spec = this.getInstrumentSpec(pos.symbol);
      const dpp = this._num(pos.dollarsPerPoint, spec ? spec.dollarsPerPoint : 1);
      const denom = (pos.initialStop != null && pos.initialStop !== pos.entry) ? pos.initialStop : pos.stop;
      return Math.abs(this._num(pos.entry, 0) - this._num(denom, 0)) * dpp * this._num(pos.units, 0);
    }

    /**
     * RUNNER AWARENESS — review every break-even runner against live HTF bias.
     * A runner that has turned counter to Weekly+3D is "weak" and a candidate
     * to scale out of / tighten (recycle its slot); a strong aligned runner in
     * good profit is a candidate to trail harder. Returns advisory actions the
     * dashboard (or a future executor) can act on.
     * @returns {Array<{symbol,direction,unrealizedR,biasStrength,status,action,reason}>}
     */
    reviewRunners() {
      return this.getOpenPositions().filter(p => p.stopAtBreakeven).map(p => {
        const align = this.checkBiasAlignment(p.symbol, p.direction);
        const ir = this._initialRiskUsd(p);
        const unrealR = ir > 0 ? this._round(this.getPositionUnrealized(p) / ir, 2) : 0;
        let status, action, reason;
        if (align.strength === "counter") {
          status = "weak"; action = "scale_out";
          reason = "Runner turned counter to Weekly+3D — scale out / tighten to recycle the slot";
        } else if (unrealR >= 2 && align.strength === "aligned") {
          status = "healthy"; action = "trail";
          reason = "Strong, fully-aligned runner — trail harder to lock more profit";
        } else {
          status = "healthy"; action = "hold";
          reason = "Aligned runner — hold toward the final target";
        }
        return { symbol: p.symbol, direction: p.direction, unrealizedR: unrealR, biasStrength: align.strength, status, action, reason };
      });
    }

    /**
     * BOOK HEALTH SNAPSHOT — the shape of the portfolio right now.
     * Separates "real" open risk from risk-free runners, aggregates unrealized
     * P/L (in $ and R), counts how the book lines up with HTF bias, flags weak
     * runners, and rolls it all into a 0..100 health score (50 = flat/neutral).
     */
    getBookHealth() {
      const positions = this.getOpenPositions();
      const n = positions.length;
      const portfolioCapUsd = this._round(this.equity * this.config.maxPortfolioRiskPct / 100, 2);

      // TOP100 #85 — the open-risk sum is accumulated IN this sweep rather than
      // by a `getOpenRiskUsd()` call above it. That call walked the same book
      // and called `getPositionOpenRisk` on every position, and the loop below
      // then called it a second time on most of them.
      //
      // Bit-identical, not merely close, and the reasons are worth stating
      // because a risk figure that drifts in the last cent is a support ticket
      // nobody can reproduce: `positions` is `Object.keys(_positions).map(...)`,
      // so it preserves the exact key order the old `reduce` summed in; the
      // accumulator still starts at 0 and still rounds ONCE at the end; and
      // `getPositionOpenRisk` reads only own scalar fields, which a shallow
      // clone carries verbatim.
      //
      // Note the old `atBE || this.getPositionOpenRisk(p) <= 0` SHORT-CIRCUITED,
      // so a break-even position skipped its second call. Hoisting the value
      // means it is now computed exactly once per position instead of once or
      // twice — strictly fewer calls in every case, never more.
      let riskOnCount = 0, riskFreeCount = 0, unrealizedUsd = 0, unrealizedR = 0, openRiskRaw = 0;
      const bias = { aligned: 0, partial: 0, counter: 0, unknown: 0 };
      const weakRunners = [];
      positions.forEach(p => {
        const atBE = !!p.stopAtBreakeven;
        const openRisk = this.getPositionOpenRisk(p);
        openRiskRaw += openRisk;
        if (atBE || openRisk <= 0) riskFreeCount++; else riskOnCount++;
        const u = this.getPositionUnrealized(p); unrealizedUsd += u;
        const ir = this._initialRiskUsd(p); if (ir > 0) unrealizedR += u / ir;
        const strength = this.checkBiasAlignment(p.symbol, p.direction).strength;
        bias[strength] = (bias[strength] || 0) + 1;
        if (atBE && strength === "counter") weakRunners.push(p.symbol);
      });
      const openRiskUsd = this._round(openRiskRaw, 2);
      const freeBudgetUsd = this._round(Math.max(0, portfolioCapUsd - openRiskUsd), 2);
      const budgetUsedPct = portfolioCapUsd > 0 ? this._round(openRiskUsd / portfolioCapUsd * 100, 1) : 0;
      unrealizedUsd = this._round(unrealizedUsd, 2);
      unrealizedR = this._round(unrealizedR, 2);

      // ── Health score 0..100 (50 = neutral / flat book) ──────────────────
      let score = 50;
      if (n > 0) {
        score += (riskFreeCount / n) * 20;                            // de-risked runners = healthy
        score += Math.max(-18, Math.min(18, (unrealizedR / n) * 6));  // avg position in profit (R)
        const biasNet = bias.aligned + 0.5 * bias.partial - bias.counter;
        score += (biasNet / n) * 16;                                  // book aligned with HTF
        score -= weakRunners.length * 8;                              // runners gone counter-trend
        if (budgetUsedPct > 70) score -= 10;                          // book heavy with real risk
      }
      score -= this._state.consecutiveLossCount * 12;                 // recent losses sap conviction
      score = Math.max(0, Math.min(100, Math.round(score)));

      return {
        positionCount: n, riskOnCount, riskFreeCount,
        openRiskUsd, freeBudgetUsd, budgetUsedPct, portfolioCapUsd,
        unrealizedUsd, unrealizedR,
        biasBreakdown: bias, weakRunners,
        healthScore: score,
        summary: this._bookSummary(n, riskOnCount, riskFreeCount, weakRunners, unrealizedUsd),
      };
    }
    _bookSummary(n, on, free, weak, unreal) {
      if (n === 0) return "Flat book — no open risk.";
      const parts = [`${n} open · ${free} risk-free · ${on} carrying risk`];
      if (weak.length) parts.push(`${weak.length} weak runner${weak.length > 1 ? "s" : ""}`);
      parts.push(`${unreal >= 0 ? "+" : "−"}$${Math.abs(unreal).toFixed(0)} unrealized`);
      return parts.join(" · ");
    }

    /**
     * PORTFOLIO STANCE — context-aware aggression.
     * Maps book health + safety state into a posture and the concrete knobs it
     * implies (how much of the portfolio cap to deploy, and a per-trade size
     * multiplier). Pass a precomputed health object to avoid recomputation.
     * @returns {{stance,reason,healthScore,riskMult,capFraction,effectiveCapUsd,effectiveCapPct}}
     */
    getPortfolioStance(health) {
      health = health || this.getBookHealth();
      const gate = this.canEnterNewTradeQuiet();
      const score = health.healthScore;
      const max = this.config.maxConsecutiveLosses;
      const warning = max > 1 && this._state.consecutiveLossCount === max - 1;
      const noCounter = health.biasBreakdown.counter === 0;
      const headroom = health.budgetUsedPct < 80;

      let stance, reason;
      if (!gate.allowed) {
        stance = "locked"; reason = gate.reason;
      } else if (warning) {
        stance = "defensive"; reason = "One loss from the hard stop — protect capital, take only A+ setups";
      } else if (health.weakRunners.length > 0) {
        stance = "defensive"; reason = `${health.weakRunners.length} runner(s) turned counter-trend — tidy the book before adding risk`;
      } else if (score >= this.config.healthAggressiveAt && noCounter && headroom) {
        stance = "aggressive"; reason = "Healthy de-risked book + clean HTF bias — open to redeploying freed risk";
      } else if (score <= this.config.healthDefensiveAt) {
        stance = "defensive"; reason = "Weak book health — be selective with new risk";
      } else {
        stance = "neutral"; reason = "Balanced book — standard selectivity";
      }

      const capFraction = this.config.stanceCapFraction[stance] != null ? this.config.stanceCapFraction[stance] : (stance === "locked" ? 0 : 1);
      const riskMult = this.config.stanceSizeMult[stance] != null ? this.config.stanceSizeMult[stance] : (stance === "locked" ? 0 : 1);
      return {
        stance, reason, healthScore: score,
        riskMult, capFraction,
        effectiveCapUsd: this._round(health.portfolioCapUsd * capFraction, 2),
        effectiveCapPct: this._round(this.config.maxPortfolioRiskPct * capFraction, 3),
      };
    }

    /**
     * INTELLIGENT RISK RECYCLING — the smart entry decision.
     * Runs the hard gate (evaluateEntry) first; if it blocks, that block is
     * returned untouched (hard:true). Only if the trade is hard-legal does the
     * intelligence layer weigh in, possibly DEFERRING it (hard:false) when the
     * current posture says the freed budget shouldn't be redeployed yet, or
     * when a defensive book demands full bias conviction. Also returns the
     * stance-scaled size multiplier the caller should apply.
     * @param {Object} intent {symbol, direction, riskUsd?, units?, entry?, stop?}
     */
    adviseEntry(intent) {
      const health = this.getBookHealth();
      const stance = this.getPortfolioStance(health);
      const hard = this.evaluateEntry(intent);

      // Hard rules ALWAYS win — the intelligence layer can never override them.
      if (!hard.allowed) {
        return Object.assign({}, hard, { hard: true, stance: stance.stance, healthScore: stance.healthScore, bookSummary: health.summary });
      }

      const sizeMult = stance.riskMult;                          // ≤ 1.0 → only sizes down
      const intentRisk = this._round(this._intentRiskUsd(intent) * sizeMult, 2);
      const projected = this._round(this.getOpenRiskUsd() + intentRisk, 2);

      // Soft gate 1 — stance-scaled budget (always ≤ the hard portfolio cap).
      if (projected > stance.effectiveCapUsd + 1e-6) {
        return {
          allowed: false, hard: false, code: REASON.STANCE_DEFERRED,
          reason: `${stance.stance} stance limits new risk to $${stance.effectiveCapUsd.toFixed(0)} (book health ${stance.healthScore}/100); this would take it to $${projected.toFixed(0)}`,
          stance: stance.stance, healthScore: stance.healthScore, bias: hard.bias,
          sizeMult, suggestedRiskUsd: intentRisk, projectedRiskUsd: projected,
          effectiveCapUsd: stance.effectiveCapUsd, bookSummary: health.summary,
        };
      }
      // Soft gate 2 — a defensive book demands FULL Weekly+3D conviction.
      if (stance.stance === "defensive" && hard.bias && hard.bias.strength === "partial") {
        return {
          allowed: false, hard: false, code: REASON.STANCE_DEFERRED,
          reason: `Defensive stance — only fully Weekly+3D-aligned entries; this one is partial (${hard.bias.reason})`,
          stance: stance.stance, healthScore: stance.healthScore, bias: hard.bias,
          sizeMult, suggestedRiskUsd: intentRisk, bookSummary: health.summary,
        };
      }
      return {
        allowed: true, hard: false, code: REASON.OK,
        reason: `${stance.stance} stance endorses entry — ${stance.reason}`,
        stance: stance.stance, healthScore: stance.healthScore, bias: hard.bias,
        sizeMult, suggestedRiskUsd: intentRisk, projectedRiskUsd: projected,
        effectiveCapUsd: stance.effectiveCapUsd, portfolioCapUsd: health.portfolioCapUsd,
        bookSummary: health.summary,
      };
    }

    /** One-call aggregate for the dashboard: health + stance + runner reviews. */
    getPortfolioIntel() {
      const health = this.getBookHealth();
      return { health, stance: this.getPortfolioStance(health), runners: this.reviewRunners() };
    }

    /* --------------------------------------------------------------- state */
    // TOP100 #85 — this is the single most-called method on the engine: every
    // `_emit()` after every mutation, every `subscribe()`, and bot.js's 30s
    // `loadData()`. It used to walk the open book SIX times per read —
    // `getOpenPositions()` (which CLONES every position), `getOpenRiskUsd()`
    // inside `getBookHealth()`, that method's own `forEach`, then
    // `positionCount()`, `getOpenRiskUsd()` again, and `getOpenRiskPct()` which
    // is a third `getOpenRiskUsd()`. Two of those walks now do the whole job.
    //
    // This is common-subexpression elimination, NOT a cache: no value is held
    // across calls, so nothing here can go stale. That was a deliberate choice
    // over memoising the result — `getPositionUnrealized` reads `pos.current`,
    // which `onPrice()`/`onPrices()` move without any signal a memo could key
    // on (they only `_emit()` when TP1 actually fires, so an ordinary tick
    // moves the number and announces nothing), and a risk read that answers
    // with a price from a minute ago is a worse failure than a slow one. The 3x
    // came free; the 4th would have cost correctness.
    //
    // (The TOP100 entry claims a 1-second caller in bot.js. Re-checked: the 1s
    // interval is `startClocks`, which touches nothing on this engine. The real
    // cadence is 30s plus every mutation. The cost per read was real; the
    // frequency in the item was not.)
    getCurrentRiskState() {
      const gate = this.canEnterNewTradeQuiet();
      const count = this._state.consecutiveLossCount;
      const max = this.config.maxConsecutiveLosses;
      const health = this.getBookHealth();
      const stance = this.getPortfolioStance(health);
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
        // portfolio / book-level risk — all four read off the single `health`
        // walk above. `health.positionCount` IS `positionCount()` (both are the
        // key count of `_positions`), `health.openRiskUsd` IS `getOpenRiskUsd()`
        // (same sum, same rounding), and the percent is `getOpenRiskPct()`'s
        // own body with the re-walk substituted out.
        positionCount: health.positionCount,
        maxPositions: this.config.maxPositions,
        openRiskUsd: health.openRiskUsd,
        openRiskPct: this.equity > 0 ? this._round(health.openRiskUsd / this.equity * 100, 2) : 0,
        maxPortfolioRiskPct: this.config.maxPortfolioRiskPct,
        portfolioCapUsd: health.portfolioCapUsd,
        scaleOutPct: this.config.scaleOutPct,
        // Portfolio Intelligence (lightweight) — full detail via getPortfolioIntel().
        bookPosture: stance.stance,
        bookHealthScore: stance.healthScore,
        bookEffectiveCapUsd: stance.effectiveCapUsd,
        bookStanceReason: stance.reason,
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
  // TOP100 #34 — exported so test/risk_defaults.test.js can compare each entry
  // against the scanner/config.py constant it claims to mirror. Frozen because
  // a caller mutating this would change the fallbacks of every RiskManager
  // built afterwards, which is the drift again with extra steps.
  RiskManager.PUBLISHED_DEFAULTS = Object.freeze({ ...PUBLISHED_DEFAULTS });

  // UMD-ish export: window global for the browser, module.exports for Node.
  if (typeof module !== "undefined" && module.exports) module.exports = RiskManager;
  else global.RiskManager = RiskManager;

})(typeof window !== "undefined" ? window : this);

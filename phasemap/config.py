"""PhaseMap configuration — EVERY tunable parameter lives here.

Spec rule: determinism + versioned ruleset. Bump RULESET_VERSION on any
parameter change. Do not change detection math without the owner's sign-off.

Spec ambiguity resolved here (flagged to owner): Module 2 says a sweep stays
"active for 10 bars awaiting displacement" while Module 3, the state machine
and fixture 3 all say displacement must print within 5 bars of the sweep
(inclusive). We use DISPLACEMENT_WINDOW_BARS = 5 (the majority reading);
SWEEP_ACTIVE_BARS = 10 is kept only as a re-detection cooldown.
"""

from dataclasses import dataclass, field


PRODUCT_NAME = "PhaseMap"          # working name — swappable, keep in this one constant
RULESET_VERSION = "1.3.0"          # 1.3.0: 24/7 markets scan CLOSED bars only — the
#                                    still-forming UTC daily candle is dropped before
#                                    detection (review H3; owner-approved 2026-07-20)
#                                    1.2.0: M4 backtest harness + {stats} slot wired
#                                    1.1.0: multi-market (asx/nasdaq/crypto) tick + turnover rules


@dataclass(frozen=True)
class PhaseMapConfig:
    # ---- Module 0: universe & liquidity guard -------------------------------
    min_history_bars: int = 250        # min daily bars to be scanned at all
    turnover_floor: float = 200_000.0  # avg 20d $ turnover; below => ILLIQUID tag (never hidden)
    turnover_window: int = 20
    halt_gap_days: int = 5             # calendar-day gap between bars > this => HALT_RISK
    halt_lookback_bars: int = 60       # only flag halts within this recent window

    # ---- Module 1: consolidation (TRAP_SET) ---------------------------------
    box_lookback: int = 40             # bars, excluding current
    compression_history_bars: int = 504    # ~2 years for the percentile baseline
    compression_percentile: float = 0.40   # fire when range <= own 40th pct
    fallback_atr_period: int = 14
    fallback_percentile: float = 0.30      # ATR14/Close <= own 30th pct
    compression_min_bars: int = 60         # min history before fallback path may fire

    # ---- Module 2: sweep (SWEPT) --------------------------------------------
    sweep_lookback: int = 40           # prior bars for keyLow/keyHigh (spec range 20-60)
    sweep_max_depth_pct: float = 0.08  # price >= $1: deeper than this = breakdown, reject
    sweep_max_depth_pct_sub1: float = 0.15  # price < $1
    sweep_depth_price_split: float = 1.00
    sweep_active_bars: int = 10        # re-detection cooldown (see module note above)
    swing_fractal_k: int = 2           # fractal swing: lower than k bars either side
    cluster_min_members: int = 2       # equal-lows/highs cluster needs >= this many swings

    # ---- Module 3: displacement (DISPLACED) ---------------------------------
    displacement_window_bars: int = 5      # within 5 bars of sweep, inclusive
    displacement_tr_mult: float = 1.75     # TrueRange >= mult * ATR20
    displacement_close_pos: float = 0.75   # close in top (bull) / bottom (bear) quarter
    displacement_wick_max: float = 0.30    # opposing wick <= 30% of range
    atr_period: int = 20                   # simple mean of TR, NOT Wilder-smoothed

    # ---- Module 4: regime & 50% engine --------------------------------------
    regime_displacement_lookback: int = 15  # EXPANSION if module-3 bar within last N bars
    stalled_expiry_bars: int = 20           # STALLED lingers this long, then NEUTRAL re-entry

    # ---- Zones ---------------------------------------------------------------
    target_swing_lookback: int = 120   # bars searched for prior/equal highs (lows) targets
    max_targets: int = 4               # cap emitted target zones (nearest first)
    fib_ext_bands: tuple = ((1.0, 1.272), (1.618, 2.0))
    entry_retrace_band: tuple = (0.236, 0.382)   # shallow continuation band
    price_decimals: int = 4            # rounding for output determinism

    # ---- Buffer function (Section 3.1) --------------------------------------
    buffer_atr_mult: float = 0.5
    buffer_tick_mult: float = 2.0
    pct_floor_sub10c: float = 0.020    # price < $0.10
    pct_floor_sub1: float = 0.010      # price < $1.00
    pct_floor_default: float = 0.005

    # ---- Tiering -------------------------------------------------------------
    # FAST_FLIP: weekly low printed on ISO weekday 1-2 => bonus tag;
    # weekday 4-5 => downgrade one tier (SLOW_FLIP).
    fast_flip_days: tuple = (1, 2)
    slow_flip_days: tuple = (4, 5)

    # ---- Output ---------------------------------------------------------------
    output_dir: str = "public/data/phasemap"   # frontend reads latest.json here
    timezone: str = "Australia/Melbourne"

    # ---- Data hygiene (v1.3.0) ------------------------------------------------
    # 24/7 markets have no session close: yfinance's newest daily row is the
    # STILL-FORMING UTC day, so detection ran on a partial candle whose
    # H/L/C mutate until midnight (non-reproducible tiers). These markets scan
    # closed bars only. Equity markets are scanned post-close by the nightly
    # schedule, so their last bar is already complete — listed markets only.
    drop_forming_bar_markets: tuple = ("crypto",)

    # ---- M4 backtest & proof harness -----------------------------------------
    fwd_return_bars: tuple = (5, 10, 20)   # forward-return horizons per signal
    stats_window_bars: int = 20            # "reached T1 within N sessions" window
    backtest_horizon_bars: int = 40        # how long a signal is tracked forward
    stats_min_signals: int = 30            # {stats} slot stays empty below this
    oos_split_date: str = "2025-07-01"     # in-sample before, out-of-sample after
    backtest_seed: int = 7                 # random-entry baseline (deterministic)

    # ---- Feature flags ---------------------------------------------------------
    enable_smt: bool = False           # Module 6 — Phase 2, do not build in v1
    enable_chop_zones: bool = False    # Phase 3 heatmap — deferred


CONFIG = PhaseMapConfig()

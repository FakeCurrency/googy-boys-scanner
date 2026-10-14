"""PhaseMap configuration — EVERY tunable parameter lives here.

Spec rule: determinism + versioned ruleset. Bump RULESET_VERSION on any
parameter change. Do not change detection math without the owner's sign-off.

Spec ambiguity resolved here (flagged to owner): Module 2 says a sweep stays
"active for 10 bars awaiting displacement" while Module 3, the state machine
and fixture 3 all say displacement must print within 5 bars of the sweep
(inclusive). We use DISPLACEMENT_WINDOW_BARS = 5 (the majority reading);
SWEEP_ACTIVE_BARS = 10 is kept only as a re-detection cooldown.
"""

from dataclasses import dataclass


PRODUCT_NAME = "PhaseMap"          # working name — swappable, keep in this one constant
RULESET_VERSION = "1.3.1"          # 1.3.1: backtest FILL REALISM — entry_mid is only
#                                    credited when price actually trades through it;
#                                    gappers fill at the signal close (review H4).
#                                    Detection maths unchanged; stats artefacts
#                                    regenerate at this version before {stats} speaks.
#                                    1.3.0: 24/7 markets scan CLOSED bars only — the
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
    # closed bars only. Session markets (asx, nasdaq) get the same treatment
    # from phasemap/data/session.py, keyed off each market's bar-final time:
    # the nightly cron lands hours late, i.e. inside the NASDAQ session
    # (REFINE200 #131) — this tuple stays the 24/7 list.
    drop_forming_bar_markets: tuple = ("crypto",)

    # ---- M4 backtest & proof harness -----------------------------------------
    fwd_return_bars: tuple = (5, 10, 20)   # forward-return horizons per signal
    stats_window_bars: int = 20            # "reached T1 within N sessions" window
    stats_min_signals: int = 30            # {stats} slot stays empty below this
    oos_split_date: str = "2025-07-01"     # in-sample before, out-of-sample after
    backtest_seed: int = 7                 # random-entry baseline (deterministic)

    # (REFINE200 #122, 2026-10-14: three fields nothing read were removed —
    # backtest_horizon_bars, whose "how long a signal is tracked forward" was
    # false (the harness tracks until the engine drops the setup); enable_smt,
    # which scanner.py never consulted (Module 6 is Phase 2: smt_confirmed is
    # a literal False until that module exists, and a flag flipped with no
    # module behind it would grade every setup on a confirmation never
    # computed); and enable_chop_zones (Phase 3, unbuilt). No output moved.)


CONFIG = PhaseMapConfig()


# ---- Publishing & data plumbing — NOT ruleset parameters ---------------------
# These decide WHETHER a snapshot ships, how many dated copies are kept, how
# the prototype feed is asked for bars and how many digits a price is printed
# with. None of them changes a detection, zone, state, tier or narration rule,
# so moving one does not bump RULESET_VERSION (the {stats} guardrail keys off
# that version; a bump silences every narration claim until the weekly replay).
#
# REFINE200 #197: a Yahoo outage published `results: []` over the last good
# snapshot and pruned every chart file. A market whose fetched frames are
# below this share of its universe keeps the last good files and exits
# non-zero. A healthy night fetches ~90% (the rest are names Yahoo does not
# carry); a throttled one 60-70%, which still publishes (and says so on the
# page, "fetched N of M").
PUBLISH_MIN_COVERAGE = 0.50
# REFINE200 #60: dated snapshots kept beside latest.json. Nothing reads a
# dated file (grep 2026-10-14: scanner/, scripts/, public/js, tests/,
# workflows) — they are the full-schema archival copy of the newest run plus
# the one before it, for a by-hand diff. Was 7 (~10 MB of ASX+NASDAQ JSON).
DATED_SNAPSHOTS_KEEP = 2
# REFINE200 #132: prices publish at price_decimals (4 dp) OR this many
# significant figures, whichever keeps MORE digits — 4 dp alone printed BONK
# (3e-06) as 0.0 and made sub-cent bands zero-width. Prices >= ~$100 are
# byte-identical to 4 dp; nothing below that loses a digit.
PRICE_SIG_FIGS = 6
# Chart-page candles: significant figures, not fixed decimals (8 dp kept 3
# digits of a 3e-06 coin and 11 of a $300 stock's float noise).
CHART_SIG_FIGS = 8
# REFINE200 #45: one recovery sweep over the symbols a throttled first pass
# returned empty, after this cooldown (scanner/data.py's pattern).
FETCH_RECOVERY_COOLDOWN_S = 20.0
# Per-ticker faults (a renderer KeyError, a malformed frame) are logged and
# skipped; more than this share of the fetched universe failing means the
# code, not the data, is broken — the market fails instead of publishing.
TICKER_FAULT_MAX_SHARE = 0.05

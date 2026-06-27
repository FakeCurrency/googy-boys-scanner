"""Central configuration for the scanner.

Everything tunable lives here: the EMA ladder, signal thresholds, the point
weights that make up a grade, the grade cut-offs, and per-market settings.
Reconstructed from the original app's "How it works" methodology — tune freely.
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Fibonacci EMA ladder (daily close)
# ---------------------------------------------------------------------------
EMA_PERIODS = [8, 13, 21, 34, 55, 89, 144]

# ---------------------------------------------------------------------------
# Signal point weights — the grade is simply the sum of the points scored.
# ---------------------------------------------------------------------------
POINTS = {
    "alignment": 3,     # full bullish EMA stack
    "pullback": 3,      # price pulled back to a core EMA
    "confluence": 3,    # several EMAs clustered at one price zone
    "compression": 2,   # EMAs bunched tightly
    "weekly": 1,        # higher-timeframe (weekly) uptrend confirmation
    "volume": 1,        # volume expansion vs recent average
    "adx": 1,           # ADX > threshold — market is actually trending, not ranging
    "rsi_pullback": 1,  # RSI(21) in 38–62 zone — healthy dip, not washed out
}
SCORE_MAX = sum(POINTS.values())   # 15

# Grade cut-offs on total points (checked high -> low). Max possible = 13.
GRADE_CUTOFFS = [
    ("A+", 10),
    ("A", 8),
    ("B", 5),
    ("C", 3),
]

# Grades considered "tradeable" vs "watch only" (drives counters / tabs)
TRADEABLE_GRADES = {"A+", "A"}
WATCH_GRADES = {"B", "C"}

# Score at/above which a row's sparkline+trend bar paints green (else blue) on the
# site. Per scan type because each has a different max score. Pure cosmetics.
TREND_THRESHOLDS = {
    "pullback": 10,
    "reversal": 11,
    "spec": 8,
    "short": 10,
    "scalp": 8,
    "googy": 9,
}

# Reward-to-risk below this is flagged with a red "LOW R:R" chip.
LOW_RR_THRESHOLD = 1.5

# Tuning toward R:R: when True, a tradeable grade (A+/A) must also offer at least
# MIN_TRADEABLE_RR reward-to-risk; weaker setups are demoted to the watch list (B).
# Backtesting showed this materially improves the strategy (fewer, better trades).
# Set DEMOTE_LOW_RR = False to revert to signal-only grading (flag, don't demote).
DEMOTE_LOW_RR = True
MIN_TRADEABLE_RR = 1.5

# Average daily turnover (local currency) at/above which a name is tagged
# "LIQUID" rather than just "OK".
LIQUID_TIER = {"asx": 1_000_000, "nasdaq": 20_000_000, "crypto": 100_000_000}

# ---------------------------------------------------------------------------
# Signal thresholds
# ---------------------------------------------------------------------------
PULLBACK_EMAS = [21, 34, 55]   # "core" EMAs price pulls back to (34/55 emphasised)
PULLBACK_TOL = 0.025           # within 2.5% of a core EMA counts as a pullback
COMPRESSION_TOL = 0.06         # (max EMA - min EMA) / price <= 6% => compressed
CONFLUENCE_BAND = 0.02         # an EMA within 2% of price counts toward confluence
CONFLUENCE_MIN = 3             # >= 3 EMAs clustered near price => confluence
VOLUME_MULT = 1.4              # latest volume >= 1.4x its recent average
VOLUME_LOOKBACK = 20
LIQUIDITY_LOOKBACK = 20        # bars used for the average-turnover liquidity test

# ADX — trend-strength chip
ADX_PERIOD = 14
ADX_TREND_MIN = 25             # ADX above this = trending (chip fires)

# RSI(21) pullback quality chip
RSI_PERIOD = 21                # Fibonacci period — more stable than 14 on daily bars
RSI_PULLBACK_LOW = 38          # RSI must be above this (not washed out / capitulation)
RSI_PULLBACK_HIGH = 62         # RSI must be below this (still has room to run)

# ---------------------------------------------------------------------------
# Entry / stop / target levels
# ---------------------------------------------------------------------------
SWING_LOOKBACK = 20            # bars to find the recent swing low (for the stop)
STOP_BUFFER = 0.01            # place stop 1% below the swing low
RESIST_LOOKBACK = 120         # bars to search for the nearest resistance above
PIVOT_WINDOW = 3              # bars each side that define a pivot high
ATR_PERIOD = 14
SUPERTREND_MULT = 3.0         # ATR multiplier for the Phase-2 trailing stop

# Weekly (higher-timeframe) trend confirmation
WEEKLY_FAST = 10
WEEKLY_SLOW = 20

# Per-row sparkline: how many recent daily closes to send to the UI
SPARK_BARS = 30

# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------
POSITION_SIZE_USD = 1_000    # target dollar amount invested per trade (AUD for ASX, USD for NASDAQ/Crypto)
BROKERAGE_EACH_WAY = 5       # brokerage cost per leg (buy + sell = 2x this)
MAX_POSITIONS_LONG = 10      # maximum concurrent open long positions across all markets
MAX_POSITIONS_SHORT = 10     # maximum concurrent open short positions across all markets

# ---------------------------------------------------------------------------
# PULSE — macro market indicators shown in the top bar.
# (key, label, yfinance ticker, divide_by, decimals)
# ---------------------------------------------------------------------------
PULSE = [
    ("ASX200",  "ASX 200",  "^AXJO",     1,  0),
    ("GOLD",    "Gold",     "GC=F",      1,  0),
    ("SILVER",  "Silver",   "SI=F",      1,  2),
    ("BRENT",   "Brent",    "BZ=F",      1,  2),
    ("WTI",     "WTI",      "CL=F",      1,  2),
    ("NATGAS",  "Nat Gas",  "NG=F",      1,  2),
    ("TECH",    "Tech",     "^IXIC",     1,  2),
    ("BIOTECH", "Biotech",  "XBI",       1,  2),
    ("YIELDS",  "10Y",      "^TNX",      1,  3),
    ("AUD",     "AUD/USD",  "AUDUSD=X",  1,  4),
    ("VIX",     "VIX",      "^VIX",      1,  2),
    ("USD",     "USD Idx",  "DX-Y.NYB",  1,  2),
]

# ---------------------------------------------------------------------------
# REVERSALS scanner — early trend-reversal / base-breakout setups.
# Uses the user's own indicators: SMA 9/26/43/200, RSI 14 (+ its MA), Vol 20.
# ---------------------------------------------------------------------------
REV_SMAS = [9, 26, 43, 200]
REV_RSI_PERIOD = 14
REV_RSI_MA = 14                # SMA of RSI (the yellow RSI line on the charts)
REV_VOL_LOOKBACK = 20          # Vol-20 average

# Signal points (grade = sum). Order reflects importance (see chat).
REV_POINTS = {
    "reclaim": 4,     # price reclaimed + 9 crossed up over 26 (the trigger)
    "base": 3,        # beaten-down / basing (room to run)
    "volume": 3,      # volume expansion confirms the move
    "breakout": 2,    # closing above the base high / descending resistance
    "rsi": 2,         # RSI turning up through its MA
}
REV_SCORE_MAX = sum(REV_POINTS.values())   # 14
REV_GRADE_CUTOFFS = [("A+", 11), ("A", 9), ("B", 6), ("C", 4)]

# Thresholds
REV_CROSS_LOOKBACK = 15        # 9-over-26 cross must be this fresh (bars)
REV_SLOPE_BARS = 5             # bars used to judge an MA is curling up
REV_BASE_OFF_HIGH = 0.20       # >=20% below the 1-year high => beaten down
REV_BASE_HIGH_LOOKBACK = 252   # window for the "1-year high"
REV_BELOW200_LOOKBACK = 45     # recently traded below the 200 SMA => recovering
REV_VOL_MULT = 1.4             # 5-day avg volume >= 1.4x Vol-20
REV_VOL_SPIKE = 2.0            # or a single day >= 2.0x Vol-20
REV_BREAKOUT_BASE = (45, 5)    # base = highs from bar -45 to -5; break = close above it
REV_RSI_BAND = (48, 72)        # RSI turned up but not yet overbought
REV_STOP_LOOKBACK = 12         # recent swing low for the stop
REV_MIN_HISTORY = 230          # need warm-up for SMA200 + base lookbacks
REV_BREAKOUT_TOL = 0.999       # price >= base_high * this => breakout (0.1% tolerance)
REV_STOP_FALLBACK_PCT = 0.95   # fallback stop = entry * this when swing low is above entry

# ---------------------------------------------------------------------------
# SPECS scanner — speculative volume-spike breakouts from a base (ASX-style).
# The setup Vivek circled: a beaten-down/basing small-cap that suddenly trades
# on a big VOLUME SPIKE and breaks out of its base while the short SMAs turn up.
# Volume spike + base + breakout are MANDATORY gates; the grade then reflects
# how strong the spike and breakout are. Reuses the SMA 9/26/43/200 + RSI 14.
# ---------------------------------------------------------------------------
SPEC_SMAS = [9, 26, 43, 200]
SPEC_VOL_LOOKBACK = 20         # Vol-20 average baseline
SPEC_VOL_RECENT = 5           # the spike must have happened within this many bars
SPEC_VOL_SPIKE = 3.0          # mandatory: a recent day >= 3x the 20-day avg volume
SPEC_OFF_HIGH = 0.40          # mandatory base: >=40% below the 1-year high (room to run)
SPEC_BASE_HIGH_LOOKBACK = 252 # window for the "1-year high"
SPEC_BELOW200_LOOKBACK = 60   # recently traded below the 200 SMA => beaten down
SPEC_BREAKOUT_BASE = (40, 3)  # base = highs from bar -40 to -3; breakout = close above it
SPEC_NEWHIGH_LONG = 63        # bonus if it's also a fresh ~3-month high
SPEC_CROSS_LOOKBACK = 12      # fresh 9-over-26 cross within this many bars (bonus)
SPEC_SLOPE_BARS = 5           # bars used to judge the 9-SMA is curling up
SPEC_RSI_BAND = (45, 85)      # specs can run hot — wider band than reversals
SPEC_MAX_EXT = 0.60           # skip if already >60% above the 9-SMA (too late / chased)
SPEC_STOP_LOOKBACK = 10       # recent swing low for the stop
SPEC_MIN_HISTORY = 230        # warm-up for SMA200 + base lookbacks

SPEC_GRADE_CUTOFFS = [("A+", 8), ("A", 6), ("B", 4), ("C", 2)]
SPEC_SCORE_MAX = 11           # see spec.score_and_grade for the breakdown
# Short scanner quality gates (hard filters — fail any one = skip the stock)
SHORT_DOWNTREND_BARS = 15     # price must have been below EMA 144 for this many bars (no recent dips)
SHORT_RESISTANCE_TOL = 0.005  # price may be up to 0.5% above resistance EMA and still count as a touch
SHORT_STOP_FALLBACK_PCT = 0.03  # fallback stop = entry * (1 + this) when swing high is below entry
SHORT_EMA_ALIGN_BARS = 10     # EMA 8 must have been below EMA 21 for this many bars
SHORT_BOUNCE_VOL_WINDOW = 8   # bars to compare up-day vs down-day volume on the bounce

SPEC_MAX_PRICE = 0.50         # specs only: skip anything pricier than this (market currency;

# ---------------------------------------------------------------------------
# GOOGY scanner — consolidation breakout setups.
# Finds price breaking above the highest high of the last N bars, confirmed by
# momentum (RSI > 50) and at least one SMA trend filter. More tolerant of low
# liquidity than the Pullback/Reversal scanners — surfaces aggressive breakouts
# that may not qualify for the tighter screens. No price cap, no beaten-down gate.
# ---------------------------------------------------------------------------
GOOGY_BREAKOUT_LOOKBACK  = 25  # bars to define the consolidation range (mandatory gate)
GOOGY_FRESH_LOOKBACK     = 5   # range high must have been set within last N bars (Rule 1)
GOOGY_NOT_EXTENDED_PCT   = 0.10 # price no more than 10% above range high (Rule 2)
GOOGY_VOL_LOOKBACK       = 20  # bars for the volume average baseline
GOOGY_VOL_MULT           = 1.8 # volume ≥ 1.8× avg — mandatory gate (Rule 4)
GOOGY_VOL_STRONG         = 2.5 # volume > 2.5× avg = strong volume bonus
GOOGY_VOL_SURGE          = 4.0 # volume > 4× avg = surge bonus
GOOGY_RSI_PERIOD         = 14  # RSI / ATR / ADX period
GOOGY_RSI_MIN            = 50  # RSI must be above this AND price > SMA20 (Rule 5)
GOOGY_SMA_FAST           = 20  # fast SMA — mandatory trend filter (Rule 5)
GOOGY_SMA_SLOW           = 50  # slow SMA — display only (above → bonus point)
GOOGY_COMPRESS_LOOKBACK  = 15  # bars ago to compare ATR for compression check (Rule 3)
GOOGY_ADX_MIN            = 18  # ADX must exceed this to score the strength bonus (Rule 6)
GOOGY_ADX_RISING_BARS    = 5   # ADX rising over last N bars = rising confirmation
GOOGY_RANGE_TIGHT_PCT    = 0.20 # tight range: (high-low)/high < 20% → quality bonus
GOOGY_RANGE_MIN_BARS     = 10  # minimum bars of consolidation for quality bonus
GOOGY_STOP_LOOKBACK      = 20  # bars to find the recent swing low for the stop
GOOGY_STOP_BUFFER        = 0.01 # place stop 1% below the swing low
GOOGY_STOP_FALLBACK_PCT  = 0.93 # fallback stop = entry * this when swing low >= entry
GOOGY_MIN_HISTORY        = 80  # minimum bars needed (increased to support ATR lookback)
# Turnover below this gets a LOW LIQUIDITY warning chip (but still shows up)
GOOGY_LOW_LIQ_TURNOVER = {"asx": 200_000, "nasdaq": 500_000, "crypto": 1_000_000}
# Hard minimum — below this, skip entirely (basically zero-activity tickers)
GOOGY_MIN_TURNOVER = {"asx": 5_000, "nasdaq": 10_000, "crypto": 50_000}
GOOGY_SCORE_MAX = 12
GOOGY_GRADE_CUTOFFS = [("A+", 9), ("A", 7), ("B", 4), ("C", 2)]
                              # disabled for crypto, where per-coin price is meaningless)

# ---------------------------------------------------------------------------
# VIVEK — 5.0Trading.Bull style: reactions at the 200 SMA on higher timeframes
# ---------------------------------------------------------------------------
# Core idea: price reacting (bounce / reject / break+retest) at the 200 SMA on
# the Weekly (and a higher-TF daily proxy for H4). Low leverage, tiny risk,
# pre-defined TP1/TP2/TP3 with structured scale-outs and SL that only ever moves
# in the trade's favour.
VIVEK_SMA              = 200       # the moving average everything keys off
VIVEK_AT_LEVEL_TOL     = 0.02      # within 2% of the 200 SMA = "at the level"
VIVEK_NEAR_TOL         = 0.04      # within 4% = "in play" (tightened from 6% for selectivity)
VIVEK_DATA_PERIOD      = "5y"      # long history so a Weekly SMA200 is meaningful
VIVEK_MIN_WEEKLY_BARS  = 60        # need at least this many weekly bars to use Weekly SMA
VIVEK_MIN_HISTORY      = 220       # min daily bars to compute a Daily SMA200 (~H4 proxy)
VIVEK_ATR_STOP_MULT    = 1.0       # stop sits ATR×this beyond the reaction extreme
VIVEK_PIVOT_WINDOW     = 4         # swing pivot lookback for structure + stops
VIVEK_SCORE_MAX        = 10
# Grade ladder (note: B+ and WATCH, not B/C, per 5.0 grading)
VIVEK_GRADE_CUTOFFS    = [("A+", 8), ("A", 6), ("B+", 4), ("WATCH", 2)]

# Structural take-profits — TP1/TP2/TP3 land on REAL prior structure (resistance
# above for longs, support below for shorts), so R:R varies and means something.
# R-multiples are only a fallback when there isn't enough structure to fill 3 TPs.
VIVEK_TARGET_LOOKBACK  = 180       # daily bars searched for prior swing structure
VIVEK_TP_MIN_R         = 0.8       # a target must sit at least this many R beyond entry
VIVEK_TP_MAX_R         = 10.0      # ignore structure further than this (unrealistic target)
VIVEK_TP_CLUSTER_R     = 0.6       # merge structural levels within this many R of each other
VIVEK_TP_R             = [1.5, 3.0, 5.0]   # fallback TP1/TP2/TP3 when structure is thin
VIVEK_MIN_TRADEABLE_RR = 1.5       # A/A+ need at least this R:R to TP2, else demote to B+
VIVEK_SHORT_TP_FLOOR   = 0.05      # a short's targets can't fall below 5% of entry (price→0 floor)

# 5.0 execution rules (used by the autonomous bot + dashboard)
VIVEK_RISK_PCT_DEFAULT = 0.25      # % of equity risked per trade (0.25–0.5 range)
VIVEK_RISK_PCT_MAX     = 0.5
VIVEK_MAX_LEVERAGE     = 5         # hard cap; 2.5–3× preferred
VIVEK_TP_SCALE_LONG    = [0.25, 0.50, 0.15]   # book at TP1 / TP2 / TP3 (10% runner left)
VIVEK_TP_SCALE_SHORT   = [0.50, 0.25, 0.15]   # shorts bank more, sooner

# Autonomous bot (Bybit testnet) — only take strong 5.0 matches.
VIVEK_BOT_MIN_GRADE    = "A"       # bot trades A or better (A+/A); not B+/WATCH
VIVEK_BOT_MIN_RR       = 1.5       # skip setups whose R:R (to TP2) is below this
VIVEK_BOT_MAX_POSITIONS = 5        # concurrent open positions cap
VIVEK_BOT_MAX_PER_SECTOR = 2       # at most N concurrent positions in one sector
VIVEK_BOT_TARGET_LEVERAGE = 3      # bot operates at ≤3× (5.0's 2.5–3× preference); hard cap stays 5×

# ---------------------------------------------------------------------------
# MOVERS — biggest winners/losers on the NEWS page, split by company size so
# you can read big-money rotation (mega) AND discovery (small caps) separately.
# ---------------------------------------------------------------------------
MOVER_PER_TIER = 5            # up to this many MEGA + this many SMALL per side
MOVER_TARGET_PER_SIDE = 10    # aim for ~this many names per side (mega+small)
MOVER_MEGA_CAP_USD = 10e9     # market cap >= $10B counts as a "mega" company
# Fallback when a name's market cap isn't cached: tier by 20-day average dollar
# volume (mega names trade vastly more $ than small caps). Per-market floors.
MOVER_MEGA_DVOL = {"asx": 30_000_000, "us": 300_000_000}

# ---------------------------------------------------------------------------
# SCALP — intraday scanner (1h bars, cross-asset)
# ---------------------------------------------------------------------------
SCALP_BROKERAGE_EACH_WAY = 20   # per-leg brokerage (CFD style)
SCALP_POSITION_SIZE = 1_000     # margin per trade
SCALP_LEVERAGE = 5              # 5× leverage → $5,000 notional per trade
SCALP_MAX_TRADES_PER_DAY = 5    # max A-grade alerts shown per scan
SCALP_STARTING_CAPITAL = 20_000 # starting account size (for display)
SCALP_MAX_DAILY_LOSS = 500      # daily stop-loss limit (for display)
# Pessimistic fill model: slippage applied on top of brokerage (one-way, as fraction of price).
# Captures the gap between the last 1h close (scan price) and the next bar open.
SCALP_FILL_SLIPPAGE_PCT = 0.0003  # 0.03% one-way — $1.50 on a $5,000 notional trade

# Trading-day boundary. Daily trade count / loss limit reset at calendar-day
# rollover in AEST (Australia/Sydney). Midnight AEST = 14:00 UTC standard /
# 13:00 UTC daylight — falls in the quiet window before the Sydney open (23:00 UTC).
SCALP_DAY_TZ = "Australia/Sydney"
SCALP_DAY_ANCHOR_UTC = 8  # kept for backward-compat; ignored when SCALP_DAY_TZ is set

# Portfolio risk — correlation caps. Highly-correlated instruments (e.g. Gold +
# Silver + Gold ETFs + a gold miner) are ONE bet, not five. Cap how many open
# scalp positions may share a correlation group at once. Symbols not listed fall
# back to a "<asset_type>:<sector>" bucket built from the universe CSV.
SCALP_MAX_PER_GROUP = 2
SCALP_CORRELATION_GROUPS = {
    # Precious metals — futures, ETFs and a gold miner all move together
    "GOLD": "metals", "SILVER": "metals", "GLD": "metals", "SLV": "metals", "NST": "metals",
    # Energy complex — crude/gas futures + energy producers
    "OIL": "energy", "BRENT": "energy", "NATGAS": "energy",
    "WDS": "energy", "STO": "energy", "ORG": "energy",
    # Base metals / diversified miners (iron ore tracks the broad materials bid)
    "COPPER": "materials_au", "BHP": "materials_au", "RIO": "materials_au", "FMG": "materials_au",
    # Soft commodities
    "WHEAT": "ags", "COFFEE": "ags",
    # Australian banks / financials
    "CBA": "au_financials", "NAB": "au_financials", "WBC": "au_financials",
    "ANZ": "au_financials", "MQG": "au_financials", "QBE": "au_financials", "SUN": "au_financials",
    # US mega-cap tech & semis (incl. index ETFs — one big beta bet)
    "AAPL": "us_tech", "MSFT": "us_tech", "NVDA": "us_tech", "META": "us_tech",
    "GOOGL": "us_tech", "AMZN": "us_tech", "TSLA": "us_tech", "AMD": "us_tech",
    "AVGO": "us_tech", "NFLX": "us_tech", "PLTR": "us_tech", "CRM": "us_tech",
    "ORCL": "us_tech", "ADBE": "us_tech", "MU": "us_tech", "QCOM": "us_tech",
    "SPY": "us_tech", "QQQ": "us_tech",
    # US index futures (NAS100 = NQ, US30 = YM). They ARE broad US-equity beta —
    # grouped with us_tech so NAS100 + QQQ + a megacap can't stack as one giant bet.
    "NAS100": "us_tech", "US30": "us_tech",
}

# ---------------------------------------------------------------------------
# Version tracking — bump SCANNER_VERSION on breaking engine or config changes
# so every scan output and health.json record carries the exact logic version.
# ---------------------------------------------------------------------------
SCANNER_VERSION = "7.0.0"   # <major>.<phase>.<patch>

# ---------------------------------------------------------------------------
# Phase 5: Risk Management — portfolio-level limits
# ---------------------------------------------------------------------------
# Note: SCALP_STARTING_CAPITAL (20_000) is used as the account baseline for
# drawdown and heat calculations. Override ACCOUNT_OVERRIDE_USD to use a
# different value if the live account size differs from the starting capital.
ACCOUNT_OVERRIDE_USD      = 0       # 0 = use SCALP_STARTING_CAPITAL; set to real balance to override

PORTFOLIO_HEAT_LIMIT      = 0.07    # max 7% of account at risk at any time across all open positions
MAX_DRAWDOWN_PAUSE        = 0.12    # pause new trades when drawdown from equity peak reaches 12%
MAX_DRAWDOWN_CLOSE        = 0.15    # close all positions when drawdown from peak reaches 15%
DRAWDOWN_HALVE_SIZE_AT    = 0.08    # apply 0.5× size multiplier once drawdown exceeds 8%
SECTOR_EXPOSURE_CAP       = 0.40    # max 40% of account in any single sector/theme
MAX_OPEN_POSITIONS        = 10      # hard cap on total concurrent open positions

# Phase 5: Circuit Breakers
CONSEC_LOSS_PAUSE         = 3       # pause after 3 consecutive losing trades (matches JS engine)
ANOMALY_PAUSE_ON_TRIGGER  = True    # block new orders when anomaly detector fires

# HTF bias filter — Weekly + 3D must not oppose trade direction
HTF_BIAS_REQUIRED         = True    # enforce bias alignment before placing any order

# Phase 5: Live Execution Safeguards
SLIPPAGE_WARN_PCT         = 0.003   # warn (but allow) when expected slippage > 0.3%
SLIPPAGE_REJECT_PCT       = 0.01    # block order when expected slippage > 1%
ORDER_SIZE_MIN_USD        = 10      # minimum order notional value — below this is a data error
ORDER_SIZE_MAX_USD        = 5_000   # maximum order notional value — fat-finger guard

# Phase 5: Environment guard — MUST be explicitly set to enable live capital.
# Set env var BYBIT_LIVE_CONFIRMED=true as a GitHub Secret alongside BYBIT_API_KEY.
# Without this, the system falls back to dry-run if BYBIT_TESTNET=false is detected.
REQUIRE_LIVE_CONFIRMED    = True    # set to False only in automated testing

# ---------------------------------------------------------------------------
# Phase 6: Live Deployment Protocol
# ---------------------------------------------------------------------------
# Stage controls how the system behaves during the gradual capital ramp-up.
#   1 = Structured Testnet Validation  (testnet only, no real capital)
#   2 = Live vs Expected Fill Analysis (testnet, full slippage tracking enabled)
#   3 = Small Live Capital Deployment  (live, reduced position sizes)
#   4 = Gradual Capital Scaling        (live, milestone-driven capital increases)
#   5 = Post-Trade Review & Refinement (live, full normal parameters)
LIVE_DEPLOYMENT_STAGE = 1           # advance manually after each stage's exit criteria are met

# Stage 3 — small live capital: position sizes are scaled down
LIVE_STAGE3_CAPITAL_MAX_USD  = 8_000   # never fund the live account above this during Stage 3
LIVE_STAGE3_POSITION_MULT    = 0.35    # 35% of normal calculated size (30–50% range; conservative)
LIVE_STAGE3_RISK_PCT_MAX     = 0.005   # enforced: effective risk per trade capped at 0.5% of account in Stage 3

# Stage 4 — scaling milestones (all require profitable weeks + controlled drawdown)
LIVE_STAGE4_L1_MIN_WEEKS     = 4       # Level 1 unlock: 4+ profitable completed weeks
LIVE_STAGE4_L1_MAX_DD        = 0.05    # Level 1 unlock: drawdown must be < 5%
LIVE_STAGE4_L1_BUMP          = 0.375   # capital increase (midpoint of 25–50% range)
LIVE_STAGE4_L2_MIN_WEEKS     = 4       # Level 2 unlock: another 4+ profitable weeks
LIVE_STAGE4_L2_MAX_DD        = 0.06    # Level 2 unlock: drawdown must be < 6%
LIVE_STAGE4_L2_BUMP          = 0.375   # capital increase (midpoint of 25–50% range)

# Stage 2 — fill analysis: minimum trades before weekly slippage averages are meaningful
FILL_ANALYSIS_MIN_TRADES     = 5       # skip weekly averages if fewer than this many filled trades

# ---------------------------------------------------------------------------
# Phase 7: Advanced Monitoring & Alerting
# ---------------------------------------------------------------------------

# Map event_type → severity level (CRITICAL / WARNING / INFO)
ALERT_SEVERITY = {
    "kill_switch":     "CRITICAL",
    "daily_loss":      "CRITICAL",
    "order_failed":    "CRITICAL",
    "scan_error":      "CRITICAL",
    "order_placed":    "INFO",
    "order_rejected":  "WARNING",
    "anomaly":         "WARNING",
    "circuit_breaker": "WARNING",
    "daily_report":    "INFO",
    "health":          "WARNING",
    "info":            "INFO",
}

# Set False to silence all Telegram sends without touching secrets.
# Flip back to True when the bot is ready to go live again.
TELEGRAM_ENABLED = False

# Map severity → alert channels (telegram / discord / email)
ALERT_CHANNELS = {
    "CRITICAL": ["telegram", "discord", "email"],
    "WARNING":  ["telegram", "discord"],
    "INFO":     [],  # log only — no push notification for routine events
}

# Per-event-type rate limit in seconds (0 = no limit; prevents alert storms)
ALERT_RATE_LIMITS = {
    "kill_switch":     0,        # always send — life-safety critical
    "daily_loss":      0,        # always send
    "order_failed":    0,        # always send
    "scan_error":      0,        # always send
    "order_placed":    300,      # max 1 per 5 min
    "order_rejected":  300,
    "anomaly":         1800,     # max 1 per 30 min (prevents storm on recurring anomaly)
    "circuit_breaker": 1800,
    "daily_report":    82800,    # max 1 per 23h
    "weekly_report":   518400,   # max 1 per 6 days
    "health":          3600,     # max 1 per hour
    "DEFAULT":         300,
}

# Phase 7: Health check thresholds
HEALTH_SCAN_STALE_WARN_H = 2    # warn if health.json is older than this many hours
HEALTH_SCAN_STALE_CRIT_H = 4    # critical if older than this
HEALTH_LOG_SIZE_WARN_MB  = 50   # warn if any log file exceeds this size (MB)
HEALTH_LOG_SIZE_CRIT_MB  = 200  # critical if any log file exceeds this size (MB)

# Phase 7: Expectancy tracking
EXPECTANCY_MIN_TRADES = 20      # minimum sample before expectancy estimate is reliable

# ---------------------------------------------------------------------------
# Phase 8: Enhanced Monitoring & Alerting
# ---------------------------------------------------------------------------

# Strategy degradation anomaly thresholds (used by anomaly.check_strategy_degradation)
ANOMALY_WIN_RATE_WINDOW    = 20    # rolling trade window for degradation checks
ANOMALY_WIN_RATE_DROP      = 15.0  # alert if rolling WR drops > 15 pp vs all-time
ANOMALY_EXPECTANCY_DROP    = 0.3   # alert if rolling E drops > 0.3R vs all-time expectancy

# Weekly report rate-limit bucket (separate from daily_report so each has its own cadence)
ALERT_RATE_LIMITS_EXTRA: dict = {
    "weekly_report": 518_400,  # max 1 per 6 days (604800 = 7d; 518400 = 6d allows a little slack)
}

# ---------------------------------------------------------------------------
# Discord digest — posts new tradeable setups to a Discord channel webhook
# ---------------------------------------------------------------------------
# Enable by setting the DISCORD_WEBHOOK_URL env var / GitHub secret. Without it
# the module writes a preview and no-ops (never fails the workflow).
DISCORD_USERNAME       = "Vivek's Beta Scanner"
DISCORD_AVATAR_URL     = ""          # optional avatar image URL for the webhook
DISCORD_MIN_GRADE      = "A"         # post setups graded at least this (A → A+/A; "A+" → only A+)
DISCORD_MAX_PER_MARKET = 8           # cap setups listed per market so the message stays clean
DISCORD_BRAND_COLOR    = 0x0A84FF    # default embed colour (iOS blue)
DISCORD_GRADE_COLORS   = {           # embed colour by the best grade present
    "A+": 0x30D158, "A": 0x0A84FF, "B": 0xFF9500, "C": 0x8E8E93,
}
DISCORD_GRADE_EMOJI    = {           # per-setup marker
    "A+": "🟢", "A": "🔵", "B": "🟠", "C": "⚪",
}
DISCORD_POST_RETRIES   = 4           # network/5xx retry attempts (with back-off)
# Grade precedence for the min-grade filter (lower index = stronger).
GRADE_PRECEDENCE       = ["A+", "A", "B", "C"]

# ---------------------------------------------------------------------------
# Phase 9: Capital Scaling Framework
# ---------------------------------------------------------------------------

# Hard cap on total capital under live management.  If the total notional
# of open positions reaches this value, new orders are blocked.  Set to 0
# to disable the cap entirely.
MAX_MANAGED_CAPITAL_USD  = 50_000   # USD; 0 = disabled

# If current scaling_advisor level >= this value, log a prominent warning
# reminding the operator to manually increase the funded capital before
# continuing.  Set to 0 to keep the advisor fully advisory (no blocking).
SCALING_ADVISORY_WARN_LEVEL = 1     # warn from Level 1 onward

# ---------------------------------------------------------------------------
# Bybit broker — crypto futures execution
# ---------------------------------------------------------------------------
# BYBIT_TESTNET env var controls endpoint (default "true" = safe/testnet).
# Set BYBIT_TESTNET=false in GitHub Secrets only when ready for real capital.
BYBIT_MIN_QTY_USD = 5.0        # skip signals where notional qty < $5 (Bybit min order)
BYBIT_ORDER_TYPE  = "Limit"    # "Limit" recommended; "Market" for instant fill

# ATR-based position sizing: risk a fixed dollar amount per trade (stop-distance method).
# qty = SCALP_RISK_PER_TRADE / |entry - stop|
# With SCALP_ATR_STOP_MULT=1.5, a $100 risk on a 2% stop → qty controls $5,000 notional
# implicitly — but sizing now adjusts to volatility rather than fixing notional.
SCALP_RISK_PER_TRADE = 100     # USD to risk per trade (loss if stopped out before brokerage)

# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
DATA_PERIOD = "1y"            # history pulled per ticker (~252 bars; enough for EMA144 + all lookbacks)
CHART_PERIOD = "10y"          # extended history fetched for result tickers only (powers weekly/monthly chart TFs)
MIN_HISTORY = 160             # need at least this many bars to evaluate a stock
DATA_STALENESS_HOURS = 4      # flag data as stale if last bar is older than this many hours
SCALP_DATA_MIN_BARS  = 65     # minimum 1h bars required for scalp evaluate() (matches SCALP_MIN_BARS)

# ---------------------------------------------------------------------------
# Market regime classification
# ---------------------------------------------------------------------------
REGIME_ADX_THRESHOLD    = 25    # ADX > 25 → "trending"; ≤ 25 → "ranging"
REGIME_RANGING_RISK_MULT = 0.5  # scale position size to this fraction in ranging markets
REGIME_RANGING_SKIP      = False # True = skip signals entirely in ranging; False = reduce size

# ---------------------------------------------------------------------------
# Execution robustness
# ---------------------------------------------------------------------------
ORDER_RETRY_ATTEMPTS     = 3    # retry Bybit API calls this many times on failure
ORDER_RETRY_BACKOFF_BASE = 2    # base seconds for exponential backoff (2s, 4s, 8s…)

# ---------------------------------------------------------------------------
# News/event calendar filter
# ---------------------------------------------------------------------------
EVENT_BLACKOUT_ENABLED   = True  # skip new orders on high-impact economic event days


@dataclass(frozen=True)
class MarketConfig:
    key: str
    label: str
    suffix: str            # yfinance ticker suffix (".AX" ASX, "" NASDAQ, "-USD" crypto)
    currency: str
    currency_symbol: str
    timezone: str          # IANA tz for the "scanned at" timestamp
    tz_label: str          # short label shown in the UI
    liquidity_min: float   # minimum average daily turnover, in local currency
    volume_is_usd: bool = False   # crypto: Yahoo volume is already USD dollar-volume


MARKETS = {
    "asx": MarketConfig(
        key="asx", label="ASX", suffix=".AX",
        currency="AUD", currency_symbol="A$",
        timezone="Australia/Sydney", tz_label="AEST",
        liquidity_min=100_000,
    ),
    "nasdaq": MarketConfig(
        key="nasdaq", label="NASDAQ", suffix="",
        currency="USD", currency_symbol="$",
        timezone="America/New_York", tz_label="ET",
        liquidity_min=1_000_000,
    ),
    "crypto": MarketConfig(
        key="crypto", label="CRYPTO", suffix="-USD",
        currency="USD", currency_symbol="$",
        timezone="UTC", tz_label="UTC",
        liquidity_min=3_000_000, volume_is_usd=True,
    ),
}

# ---------------------------------------------------------------------------
# Feeds — YouTube channels + AI narrative (feeds.py / feeds_run.py)
# ---------------------------------------------------------------------------
# Each entry: name (display), handle (YouTube @handle, no @), channel_id
# (leave "" to auto-resolve on first run — feeds.py will populate it).
YOUTUBE_CHANNELS = [
    {"name": "Camel Finance", "handle": "CamelFinance", "channel_id": ""},
]

# How many recent videos to pull per channel (RSS returns the latest 15 max).
FEEDS_MAX_VIDEOS = 8

# Max tokens for the Claude narrative (~400 words is plenty).
FEEDS_NARRATIVE_MAX_TOKENS = 600

# Model used for narrative generation (Haiku = cheapest/fastest).
FEEDS_NARRATIVE_MODEL = "claude-haiku-4-5-20251001"

# X/Twitter accounts preserved on the feeds page below the YouTube section.
X_ACCOUNTS = [
    {"handle": "omzcharts",       "name": "Omz"},
    {"handle": "CKCapitalxx",     "name": "CK Capital"},
    {"handle": "DazzaBABA",       "name": "R08"},
    {"handle": "Ruycorto",        "name": "Rui"},
    {"handle": "ChifoiCristian",  "name": "Cristian Chifoi"},
    {"handle": "_0_Trading",      "name": "5.0 INVERTED.BULL"},
    {"handle": "BollingerBanter", "name": "Bollinger Banter"},
    {"handle": "jakestrading18",  "name": "Jakestrading"},
    {"handle": "aleabitoreddit",  "name": "Serenity"},
    {"handle": "SailorManCrypto", "name": "Popeye"},
    {"handle": "kevinxu",         "name": "Kevin Xu"},
    {"handle": "TheBigBerbowski", "name": "The Big Berbowski"},
    {"handle": "BULLOFBRITAIN",   "name": "Bull of Britain"},
    {"handle": "PhotonBull",      "name": "Photon Bull"},
    {"handle": "babyfolio",       "name": "babyfolio"},
    {"handle": "mkfilko",         "name": "leki"},
    {"handle": "retail_mourinho", "name": "Retail Mourinho"},
    {"handle": "wolfgangkasper",  "name": "Wolf Capital"},
    {"handle": "Guv999",          "name": "Guv"},
]

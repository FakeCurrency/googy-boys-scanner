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
SHORT_EMA_ALIGN_BARS = 10     # EMA 8 must have been below EMA 21 for this many bars
SHORT_BOUNCE_VOL_WINDOW = 8   # bars to compare up-day vs down-day volume on the bounce

SPEC_MAX_PRICE = 0.50         # specs only: skip anything pricier than this (market currency;
                              # disabled for crypto, where per-coin price is meaningless)

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

# Trading-day boundary. The daily trade count / loss limit reset once per 24h at
# this fixed UTC hour. 08:00 UTC sits in the quiet window between ASX close
# (~06:00 UTC) and NASDAQ open (13:30 UTC), so it NEVER bisects a live session —
# even during AEDT (Oct–Apr) when the ASX session straddles 00:00 UTC.
SCALP_DAY_ANCHOR_UTC = 8

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
# Data
# ---------------------------------------------------------------------------
DATA_PERIOD = "1y"            # history pulled per ticker (~252 bars; enough for EMA144 + all lookbacks)
MIN_HISTORY = 160             # need at least this many bars to evaluate a stock


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

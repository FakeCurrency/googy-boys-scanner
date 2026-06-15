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
}
SCORE_MAX = sum(POINTS.values())   # 13

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
LIQUID_TIER = {"asx": 1_000_000, "nasdaq": 20_000_000}

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
# PULSE — macro market indicators shown in the top bar.
# (key, label, yfinance ticker, divide_by, decimals)
# ---------------------------------------------------------------------------
PULSE = [
    ("GOLD",    "Gold",     "GC=F",      1,  0),
    ("SILVER",  "Silver",   "SI=F",      1,  2),
    ("BRENT",   "Brent",    "BZ=F",      1,  2),
    ("WTI",     "WTI",      "CL=F",      1,  2),
    ("NATGAS",  "Nat Gas",  "NG=F",      1,  2),
    ("TECH",    "Tech",     "^IXIC",     1,  2),
    ("BIOTECH", "Biotech",  "XBI",       1,  2),
    ("YIELDS",  "10Y",      "^TNX",      10, 3),
    ("AUD",     "AUD/USD",  "AUDUSD=X",  1,  4),
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
# Data
# ---------------------------------------------------------------------------
DATA_PERIOD = "2y"            # history pulled per ticker (enough warm-up for EMA144)
MIN_HISTORY = 160             # need at least this many bars to evaluate a stock


@dataclass(frozen=True)
class MarketConfig:
    key: str
    label: str
    suffix: str            # yfinance ticker suffix (".AX" for ASX, "" for NASDAQ)
    currency: str
    currency_symbol: str
    timezone: str          # IANA tz for the "scanned at" timestamp
    tz_label: str          # short label shown in the UI
    liquidity_min: float   # minimum average daily turnover, in local currency


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
}

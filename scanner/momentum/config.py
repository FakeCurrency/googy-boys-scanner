"""MOMENTUM configuration -- EVERY tunable lives here.

Bump RULESET_VERSION on ANY parameter change, so a published file can always
be traced to the rules that produced it (the PhaseMap discipline).

Field NAMES deliberately mirror `tradingview/scanner-spec/reference/
vivek50_screen.py::ScreenConfig` one-for-one, so porting that file's 28
assertions is mechanical rather than a translation exercise.  Two deliberate
departures from it, both recorded below: `mode` is a LETTER here, and the
Pine DRAWING-ONLY inputs are not carried.

Every default is the value the owner's Pine template actually ships, and the
comment beside a number says where it comes from or what it measured -- not
what it is, which the name already says.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

RULESET_VERSION = "1.0.0"   # 1.0.0: first cut. Rule A (RSI divergence off
#                             strict pivots) + Rule B (scored 20/50 cross),
#                             daily bars, mode A default, 1-bar freshness.

# Frame columns the screen will accept as an indicator source. LOWERCASE on
# purpose, matching the reference. `scanner/data.py` hands back yfinance's
# TITLE-case columns ("Close"), and the normalisation belongs at the screen's
# own front door (the reference's `prepare_frame` lowercases every incoming
# column) rather than in the loader -- so the screen accepts either casing and
# the invariant is enforced where it is relied on.
# Getting the SOURCE NAME wrong is the silent failure worth guarding: a typo'd
# name used to fall back to `close` and compute a different indicator than the
# config claimed, which is why `validate()` refuses an unknown one outright.
OHLC_COLUMNS: Tuple[str, ...] = ("open", "high", "low", "close")

MARKETS: Tuple[str, ...] = ("asx", "nasdaq", "crypto")

# The three modes of spec 5.4. NOTE what "B" means: it is a UNION, not
# "Rule B alone". There is no B-only mode and inventing one would be a new
# filter.
#   A = rule_a
#   B = rule_a OR rule_b
#   C = rule_a AND rule_b AND directions agree
# The reference encodes A/B as the integers 1/2 and does not implement C.
# Letters are canonical here because that is what spec 5.8 puts in the
# published payload, and because "mode 2" reads like a magnitude.
MODES: Tuple[str, ...] = ("A", "B", "C")


@dataclass(frozen=True)
class MomentumConfig:
    """Every tunable, defaulted to the owner's shipped Pine inputs."""

    # ---- Final_RSI_Plus.pine ------------------------------------------------
    rsi_len: int = 14                  # rsiLen  = input.int(14)
    rsi_source: str = "close"          # rsiSrc  = input.source(close)
    rsi_ma_len: int = 14               # maLen   = input.int(14)
    rsi_ma_type: str = "SMA"           # maType  = input.string("SMA")
    rsi_midline: float = 50.0          # midL    = input.float(50)
    # The price-pane RSI columns fire at 75/25, NOT 70/30 -- a stale claim in
    # the template's own README that 80d4d44 corrected. Carried as evidence
    # fields only; no gate reads them.
    rsi_ob: float = 75.0
    rsi_os: float = 25.0

    # ---- RULE A: the divergence pivots --------------------------------------
    piv_left: int = 5                  # lbL = input.int(5)
    piv_right: int = 5                 # lbR = input.int(5) -- ALSO the
    #                                    detection lag: a divergence confirmed
    #                                    on bar i describes a pivot at i-lbR,
    #                                    so pivot_bars_ago == bars_ago + 5.
    #                                    Reporting sooner than this is a
    #                                    look-ahead bug (spec 7.1).
    range_lower: int = 5               # rangeLower = input.int(5)
    range_upper: int = 60              # rangeUpper = input.int(60) -- with
    #                                    Pine's barssince off-by-one these two
    #                                    make the real window 6..61 bars
    #                                    between pivots (spec 7.3).

    # STRICT PIVOTS, and this one is genuinely unsettled upstream.
    # Whether Pine's ta.pivotlow needs the centre bar strictly lower or merely
    # <= is NOT documented by TradingView; it was searched for and is absent.
    # The disagreement was MEASURED rather than guessed: over ~3,380
    # divergences from 300 tick-rounded random walks the conventions differ on
    # 27 (0.8%) -- and not in one direction (10 fire only under strict, 17 only
    # under non-strict, because an extra intervening pivot re-bases "the
    # previous pivot" and can push a valid divergence outside the 6..61 window).
    # Default strict: it is the only convention that cannot fire on a flat
    # series. Settling it is a five-minute check against a real chart and is
    # the owner's call -- see reviews/2026-09-22-momentum-phase0.md.
    pivot_strict_left: bool = True
    pivot_strict_right: bool = True

    # ---- RULE B: the scored cross, and MACD ---------------------------------
    macd_fast: int = 12                # fastLen = input.int(12)
    macd_slow: int = 26                # slowLen = input.int(26)
    macd_signal: int = 9               # sigLen  = input.int(9)
    macd_source: str = "close"         # src     = input.source(close)

    fast_len: int = 20                 # fastLen = input.int(20)
    mid_len: int = 50                  # midLen  = input.int(50)
    slow_len: int = 200                # slowLen = input.int(200)
    ma_type: str = "EMA"               # maType  = input.string("EMA")
    ma_source: str = "close"           # maSrc   = input.source(close)

    # THREE optional score terms, not two. score = 1 (the cross itself)
    # + macd agrees + price beyond slow + rsi agrees. use_rsi ships OFF, which
    # is why max_score is 3 and not 4.
    use_macd: bool = True              # useMacd = input.bool(true)
    use_slow: bool = True              # useSlow = input.bool(true)
    use_rsi: bool = False              # useRsi  = input.bool(false)

    # ---- the screen (the owner's rules; no Pine counterpart) ----------------
    mode: str = "A"                    # v1 default: divergence only.

    # FRESHNESS IS IN BARS, and both rules use the same window on purpose.
    # 1 = "confirmed on the latest closed bar" -- the purest new-today screen
    # and the smallest list. 3 is a firehose: ~105 Rule-A + ~125 Rule-B names a
    # day on ASX before liquidity gates. The spec recommends starting at 1 and
    # widening only if a market's daily list runs under ~15 names.
    # Equal windows are deliberate: they make the screen "newly KNOWABLE",
    # which is the defensible criterion because it is what could have been
    # acted on. Rule A's underlying event is already 5 bars older, and the row
    # reports both numbers rather than compensating for that silently
    # (spec 5.3B).
    div_fresh_bars: int = 1
    signal_fresh_bars: int = 1

    # RULE B's gate. NOT the same number as Pine's display threshold
    # (minScore = 1), and raising it is not a filter: over 1.95M simulated
    # symbol-days score 1 is 2% of crosses (2 is 37%, 3 is 61%), because the
    # scoring terms are correlated with the cross by construction.
    min_signal_score: int = 2

    div_directions: Tuple[str, ...] = ("bull", "bear")
    signal_directions: Tuple[str, ...] = ("bull", "bear")

    # ---- history ------------------------------------------------------------
    min_bars: int = 60                 # below this nothing here means anything
    warn_bars: int = 260               # = slow_len + a warm-up. Below it the
    #                                    200-EMA is absent or still carrying
    #                                    its seed, the "price beyond slow"
    #                                    term contributes 0, and the score is
    #                                    CAPPED AT 2. Published as a flag, not
    #                                    hidden -- a capped score must not read
    #                                    as a weak signal (spec 7.4).
    atr_len: int = 14                  # atrV = ta.atr(14); evidence only

    # ---- numerical conventions ----------------------------------------------
    # PINE SEEDS WITH THE SMA OF THE FIRST `length` VALUES and returns na
    # before that. pandas' ewm(adjust=False) seeds with the FIRST VALUE and
    # emits from bar 0. The seed error decays as (1-alpha)^n, so it matters in
    # inverse proportion to alpha -- irrelevant for RSI 14 (~1e-17 left at 500
    # bars) and EMA 20/50, but the EMA 200 still carries ~0.67%, MEASURED at
    # 0.247 price units adrift at bar 600 of a ramp. That is enough to flip
    # `close > slow`, one of the two live scoring terms, so a name near its
    # 200-EMA would score 3 under one convention and 2 under the other and
    # disagree visibly with the owner's chart. "first" exists only so the two
    # can be compared; do not ship it.
    ema_seed: str = "sma"
    rma_seed: str = "sma"

    def validate(self) -> "MomentumConfig":
        """Fail loudly on a configuration that cannot mean anything.

        A screener that silently reinterprets a bad setting produces a
        complete, plausible, wrong answer -- which is exactly the failure the
        spec's adversarial pass found and the one worth being noisy about.
        """
        if self.mode not in MODES:
            raise ValueError("mode must be one of %s, got %r" % (", ".join(MODES), self.mode))
        for name in ("rsi_len", "rsi_ma_len", "piv_left", "piv_right", "fast_len",
                     "mid_len", "slow_len", "macd_fast", "macd_slow", "macd_signal",
                     "atr_len", "min_bars", "warn_bars"):
            if int(getattr(self, name)) < 1:
                raise ValueError("%s must be >= 1" % name)
        if self.range_lower > self.range_upper:
            raise ValueError("range_lower must be <= range_upper")
        for name in ("rsi_source", "ma_source", "macd_source"):
            val = getattr(self, name)
            if val not in OHLC_COLUMNS:
                raise ValueError("%s must be one of %s, got %r"
                                 % (name, ", ".join(OHLC_COLUMNS), val))
        for name in ("ma_type", "rsi_ma_type"):
            if getattr(self, name) not in ("EMA", "SMA"):
                raise ValueError("%s must be EMA or SMA" % name)
        for name in ("ema_seed", "rma_seed"):
            if getattr(self, name) not in ("sma", "first"):
                raise ValueError("%s must be 'sma' or 'first'" % name)
        if self.div_fresh_bars < 1 or self.signal_fresh_bars < 1:
            raise ValueError("freshness windows are counted in bars and are >= 1")
        if not 1 <= self.min_signal_score <= self.max_score:
            raise ValueError("min_signal_score must be in 1..%d for these terms"
                             % self.max_score)
        return self

    @property
    def max_score(self) -> int:
        """1 + macd + beyond-slow + rsi. With the shipped defaults: 3, not 4."""
        return 1 + int(self.use_macd) + int(self.use_slow) + int(self.use_rsi)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULTS = MomentumConfig().validate()


# ---------------------------------------------------------------------------
# QUALITY GATES -- applied BEFORE the rules, per market (spec 5.6)
# ---------------------------------------------------------------------------
# These decide whether a symbol is screened at all. They exist so the
# shortlist is made of things the owner can actually trade, and so one bad
# frame cannot fabricate a signal.

# Sub-cent ASX names move one tick and print a 50% candle, which makes every
# indicator here noise. Crypto has no floor: a legitimate alt-coin can trade
# at 1e-5 and the percentage behaviour is still real.
MIN_PRICE: Dict[str, float] = {"asx": 0.02, "nasdaq": 1.00, "crypto": 0.0}

# 20-day mean of close*volume, in the market's own currency. A signal on a
# name that trades $3,000 a day is not actionable.
MIN_DOLLAR_ADV: Dict[str, float] = {"asx": 250_000.0, "nasdaq": 1_000_000.0,
                                    "crypto": 5_000_000.0}
ADV_WINDOW: int = 20

# Measured in the MARKET's own calendar, never the runner's clock -- an ASX
# frame looks a day fresher than it is under a naive local date. Computing a
# fresh signal off a stale last bar is the most dangerous silent failure a
# screener has.
MAX_DATA_AGE_DAYS: int = 3

# Reject a frame whose last N bars are all zero volume: suspended and
# delisted-but-quoted names keep printing a flat last price. A flat series
# produces no pivots under the strict rule but can still print a cross off
# stale EMAs.
ZERO_VOLUME_BARS: int = 5

# ...and reject one whose last N bars have no price range at all, which is the
# other half of the same guard (spec 7.5).
FLAT_RANGE_BARS: int = 20

# 750 daily bars is the spec's recommendation, and the reason is the 200-EMA:
# at 250 bars it is still carrying ~60% of its seed error under either
# convention and the "price beyond slow" term is not trustworthy at all.
DATA_PERIOD: str = "3y"

# Exclude non-operating listings (ASX LICs/ETFs/trusts, NASDAQ preferred,
# warrants, rights, notes). The patterns are REUSED from scanner/config.py
# rather than retyped -- spec 5.6 says so explicitly, and a second copy of a
# keyword list is a second thing to keep in step. The MATCHER is ours and uses
# word boundaries: the bot's is substring, where "ETF" in "NETFLIX" is True.
# A product is FLAGGED on every row regardless; this only decides exclusion.
EXCLUDE_PRODUCTS: bool = True

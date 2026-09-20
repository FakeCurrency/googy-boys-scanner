"""Central configuration for the scanner.

Everything tunable lives here: the EMA ladder, signal thresholds, the point
weights that make up a grade, the grade cut-offs, and per-market settings.
Reconstructed from the original app's "How it works" methodology — tune freely.
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Signal point weights — the grade is simply the sum of the points scored.
# ---------------------------------------------------------------------------

# Grade cut-offs on total points (checked high -> low). Max possible = 13.
GRADE_CUTOFFS = [
    ("A+", 10),
    ("A", 8),
    ("B", 5),
    ("C", 3),
]

# Grades considered "tradeable" vs "watch only" (drives counters / tabs)
TRADEABLE_GRADES = {"A+", "A"}


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
VOLUME_MULT = 1.4              # latest volume >= 1.4x its recent average
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


# Per-row sparkline: how many recent daily closes to send to the UI
SPARK_BARS = 30

# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------
POSITION_SIZE_USD = 1_000    # target dollar amount invested per trade (AUD for ASX, USD for NASDAQ/Crypto)
BROKERAGE_EACH_WAY = 5       # brokerage cost per leg (buy + sell = 2x this)
MAX_POSITIONS_LONG = 10      # maximum concurrent open long positions across all markets
MAX_POSITIONS_SHORT = 10     # maximum concurrent open short positions across all markets

# PULSE constant removed 2026-07-20 — the module was deleted (feature retired
# 2026-07-03/09); payloads keep an empty "pulse" key for cached-JS back-compat.

# ---------------------------------------------------------------------------
# REVERSALS scanner — early trend-reversal / base-breakout setups.
# Uses the user's own indicators: SMA 9/26/43/200, RSI 14 (+ its MA), Vol 20.
# ---------------------------------------------------------------------------
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
SPEC_MIN_HISTORY = 230        # warm-up for SMA200 + base lookbacks

SPEC_GRADE_CUTOFFS = [("A+", 8), ("A", 6), ("B", 4), ("C", 2)]
SPEC_SCORE_MAX = 11           # see spec.score_and_grade for the breakdown

SPEC_MAX_PRICE = 0.50         # specs only: skip anything pricier than this (market currency;
                              # disabled for crypto, where per-coin price is meaningless)

# ---------------------------------------------------------------------------
# VIVEK — 5.0Trading.Bull style: reactions at the 200 SMA on higher timeframes
# ---------------------------------------------------------------------------
# Core idea: price reacting (bounce / reject / break+retest) at the 200 SMA on
# the Weekly (and a higher-TF daily proxy for H4). Low leverage, tiny risk,
# pre-defined TP1/TP2/TP3 with structured scale-outs and SL that only ever moves
# in the trade's favour.
# Schema version stamped into every *_vivek.json. Bump when the row/payload
# shape the frontend depends on changes (e.g. a new per-row field). The UI reads
# this to tell "old data, missing fields" apart from "no setups", instead of
# silently hiding features. v2 = adds entry_types + freshness/version stamping.
# v4 (2026-07-20, reviews H1+H2) = adds grade_raw (unsmoothed grade the bot
# buys off) + headline_tf, and the row's headline entry/stop/TP/R:R now come
# from the TRADED plan (gated TF when armed, 1D fallback) instead of always 1D.
# v5 (2026-07-31, owner-ruled payload diet) = the PAYLOAD SPLIT: the summary
# file keeps every first-paint field with rows' `plans` pruned to
# VIVEK_SUMMARY_PLAN_FIELDS, and the four heavy row groups
# (VIVEK_DETAIL_ROW_FIELDS) move to `<market>_vivek_detail.json`, keyed by
# symbol, fetched by the deck on first row-expand. The scheduled bot path is
# untouched by construction (run_market receives the in-memory FULL rows
# before publish); the standalone vivek_run CLI re-joins the sidecar.
VIVEK_SCHEMA_VERSION   = 5

# THE LITE-PLAN DRIFT-PIN (owner clarification, 2026-07-31 ruling): the exact
# per-timeframe plan fields the SUMMARY keeps, named so they cannot drift.
# Every list-path consumer reads ONLY these:
#   app.js  convictionCells()   -> armed, entry_trigger (every TF the rule reads)
#   app.js  tfDots()            -> plan presence per TF + armed
#   app.js  star-watch alerts   -> armed, entry_trigger (via headline_tf)
#   (level_tf + direction ride along: cheap, and chart/hero fall back to them)
# recs.js, mynames.js, journal.js, phasemap-shared.js, confluence_alert.py,
# marketcaps/sectorcache/breadth/regime read ROW-level fields only — no plans.
# chart.js, the expanded row and the CSV/copy paths read FULL plans from the
# detail sidecar. tests/test_payload_split.py pins this tuple's contents and
# test/staleview.test.js proves isHighConviction passes on a lite-only plan.
# (structural_tps stays in the tuple for the row chips; the conviction rule
# stopped reading it on 2026-09-20 — see scanner/conviction.py.)
VIVEK_SUMMARY_PLAN_FIELDS = ("armed", "entry_trigger", "structural_tps",
                             "level_tf", "direction")
VIVEK_DETAIL_ROW_FIELDS   = ("plans", "detail", "analysis", "markers")
VIVEK_SMA              = 200       # the moving average everything keys off
VIVEK_AT_LEVEL_TOL     = 0.02      # within 2% of the 200 SMA = "at the level"
VIVEK_NEAR_TOL         = 0.04      # within 4% = "in play" (tightened from 6% for selectivity)
# Coins pinned into the crypto universe regardless of market-cap rank
# (2026-07-02, the FLASH gap: not in CoinGecko's top-100 -> invisible to
# every scanner). Add symbols here to guarantee coverage; Yahoo-less coins
# drop out at scan time harmlessly.
CRYPTO_EXTRA_SYMBOLS   = ["XMR", "FLASH"]

VIVEK_INCLUDE_3D_LEVEL = True      # 2026-07-02: also treat the 3-Day 200 SMA as an in-play
                                   # level (W > 3D > D). Found via XMR: price sat AT the 3D-200
                                   # (the level the community was watching) but was -23% from
                                   # the Daily and +10% from the Weekly -> invisible to the scan
VIVEK_DATA_PERIOD      = "5y"      # long history so a Weekly SMA200 is meaningful

# $0 forward-only adjusted daily archive (owner order 2026-08-15) — STORAGE
# ONLY; nothing in the scan/grade/bot path reads it. See scanner/history_archive.py.
HISTORY_ARCHIVE_MARKETS = ("asx",)   # ASX first — the market whose free history is weakest
HISTORY_ARCHIVE_MAX_BARS = 2600      # ~10y per symbol; oldest trimmed beyond this
HISTORY_ARCHIVE_MAX_FILES = 1500     # cap on distinct archived names per market
HISTORY_ARCHIVE_SPLICE_MAX_DRIFT = 0.25  # join-ratio drift beyond this flags splice_suspect
VIVEK_MIN_WEEKLY_BARS  = 60        # need at least this many weekly bars to use Weekly SMA
VIVEK_MIN_HISTORY      = 220       # min daily bars to compute a Daily SMA200 (~H4 proxy)
VIVEK_ATR_STOP_MULT    = 1.0       # stop sits ATR×this beyond the reaction extreme
VIVEK_PIVOT_WINDOW     = 4         # swing pivot lookback for structure + stops
VIVEK_SCORE_MAX        = 10
# Grade ladder (note: B+ and WATCH, not B/C, per 5.0 grading)
VIVEK_GRADE_CUTOFFS    = [("A+", 8), ("A", 6), ("B+", 4), ("WATCH", 2)]
# Grade hysteresis: a setup holds its PREVIOUS (higher) grade unless its score
# falls more than this many points below that grade's cutoff. Stops borderline
# names flip-flopping (e.g. A+↔A) on tiny scan-to-scan data differences. 0 = off.
VIVEK_GRADE_HYSTERESIS = 1
# ...but a hold may not RENEW itself forever: the previous grade came from the
# published (already-held) output, so a 7-scorer could stay A+ indefinitely and
# quietly lower the bot's A+ bar. After this many consecutive held scans the raw
# grade is published. A hold also never survives a LONG<->SHORT direction flip —
# the old badge belonged to the opposite trade.
VIVEK_GRADE_HYSTERESIS_MAX_RUNS = 3
# Drop a still-forming trailing daily bar (the current session's incomplete bar)
# so grades/plans key off COMPLETED bars only — removes partial-bar variance.
VIVEK_DROP_FORMING_BAR = True

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

# Trigger model — a setup is ARMED only when one of three mechanical triggers has
# fired on the latest completed bar; otherwise it is merely WATCHING (caps at B+).
# This replaces "entry = last close" with condition -> trigger -> armed.
VIVEK_TRIGGER_LOOKBACK = 5         # bars to look back for the pierce that precedes a reclaim
VIVEK_RETEST_VOL_MULT  = 1.0       # a retest should come on <= average volume (calm test)
VIVEK_BREAK_VOL_MULT   = 1.5       # a structure break needs >= this x average volume to count
VIVEK_TRIGGER_PRIORITY = ["reclaim", "retest", "break"]   # first match wins
VIVEK_MIN_TF_BARS      = 30        # min bars to build a per-timeframe plan (e.g. Weekly)

# ── 4H PLANS (owner, 2026-09-19) ─────────────────────────────────────────────
# "I need to see genuine set ups forming on d and weekly 3d and then if i toggle
# down i want to see a genuine set up on the 4hr."
#
# Until now the chart's 4H toggle borrowed the DAILY plan and said so in a
# tooltip, because the scan downloads daily bars only and never built a 4H plan.
# The engine still uses the Daily 200 SMA as its "h4" LEVEL in evaluate() -- that
# one is signal path (it feeds scoring and grading) and is deliberately NOT
# touched here. This block is the DISPLAY half: a real 4H plan, from real 4H
# bars, published as its own timeframe like 3D and 1W.
#
# Measured 2026-09-19 on a runner before building it: Yahoo serves 2 full years
# of 1h bars (~3,500), which buckets to ~1,200 4H bars -- six times the 200 a
# 200-period average needs -- at 0.18s a symbol, so the whole published row set
# costs about a minute of scan time.
VIVEK_H4_PLANS         = True      # build a real 4H plan for published rows
VIVEK_H4_PERIOD        = "2y"      # Yahoo's intraday ceiling is ~730 days
VIVEK_H4_INTERVAL      = "1h"      # bucketed to 4H locally (Yahoo has no 4h)
VIVEK_H4_BUCKET_HOURS  = 4
# Cap the extra download so a huge result set cannot stretch a scheduled scan.
# Rows beyond this simply keep today's behaviour (the chart falls back to the
# Daily plan and labels it), which is a degrade, never a failure.
VIVEK_H4_MAX_SYMBOLS   = 400

VIVEK_RISK_PCT_MAX     = 0.5
VIVEK_MAX_LEVERAGE     = 5         # hard cap; 2.5–3× preferred
VIVEK_TP_SCALE_LONG    = [0.25, 0.50, 0.15]   # book at TP1 / TP2 / TP3 (10% runner left)
VIVEK_TP_SCALE_SHORT   = [0.50, 0.25, 0.15]   # shorts bank more, sooner

# VIVEK paper journal — realistic intraday execution. Trades are only OPENED
# during the (delayed) market session and entered at the delayed intraday price
# at that moment; they then mark-to-market against the observed intraday price on
# every market-hours scan — mirroring manual trading off a ~15-min-delayed feed.
VIVEK_JOURNAL_MARKET_HOURS   = True    # gate new entries to the live session
VIVEK_JOURNAL_FEED_DELAY_MIN = 15      # ~15-min delayed feed → action window shifts +15m

# Execution-cost realism (fees + slippage). Modelled as an R-drag computed from
# each trade's own fills so the forward-test expectancy is NET, not gross:
#   • commission is paid on the entry and on every exit (a fraction of notional);
#   • slippage is paid only on MARKET-style fills — the entry and a stop/trail
#     close — never on a resting TP limit, which fills at its level.
# Values are in basis points (1 bp = 0.01%). Stocks are cheap/liquid; crypto
# perps carry a wider spread + taker fee, so they cost more. "default" backstops
# any market key not listed.
VIVEK_COSTS_ENABLED   = True
VIVEK_COMMISSION_BPS  = {"asx": 2.0, "nasdaq": 1.0, "crypto": 6.0, "default": 2.0}
VIVEK_SLIPPAGE_BPS    = {"asx": 5.0, "nasdaq": 4.0, "crypto": 8.0, "default": 5.0}
# Base local session per market (pre-delay), as (open_h, open_m, close_h, close_m).
# None = 24/7 (crypto). The feed delay is added to both ends at runtime.
VIVEK_JOURNAL_SESSION = {
    "asx":    (10, 0, 16, 0),
    "nasdaq": (9, 30, 16, 0),
    "crypto": None,
}

# Autonomous bot — strict VIVEK 5.0 rules (see scanner/broker/vivek_bot.py).
VIVEK_BOT_MIN_GRADE    = "A+"      # A+ ONLY — never A / B+ / WATCH
VIVEK_BOT_MIN_RR       = 1.5       # skip setups whose R:R (to TP2) is below this
# Skip non-operating vehicles (REITs / ETFs / LICs / managed funds) — they hug
# their 200 SMA so they over-produce reactions, but aren't what we want the bot
# trading. Affects the bot's selection only; the scanner still displays them.
VIVEK_BOT_EXCLUDE_FUNDS = True

# ── PRODUCT flag — DISPLAY-ONLY, published as `is_product` (2026-08-19) ──────
# Name patterns for the non-operating instrument classes the fund keyword list
# (vivek_bot._FUND_NAME_KEYWORDS) structurally misses. Measured on the live
# scans before writing: 4 ASX LICs graded A+ (AFI, BTI, HM1, RG8 — none carry
# FUND/TRUST/ETF in the name) and 4 NASDAQ preferred lines (STRF, STRD, STRC,
# MCHPP) were dressing as operating-company opportunities on the deck.
#
# THE FENCE, stated where the patterns live: scan.py publishes the flag for the
# UI to dim/mark/rank with. NOTHING in scanner/broker/ may read `is_product` or
# this constant — the bot's fund test is _is_fund_or_reit and it stays
# byte-untouched, because changing what the bot may take mid-w3-1 is a rule
# change by stealth. tests/test_product_flag.py greps the broker tree and goes
# red on the first reference.
#
# Pattern notes, each learned from a live near-miss:
#   * preferreds match on the WORDS "preferred stock/shares", which also nets
#     depositary-preferred lines (HBANP-class); bare "Depositary Shares" is
#     deliberately NOT a pattern — Sanofi/JD/Ryanair ADS are real companies.
#   * the LIC form is "InvestmentS Limited/Ltd" (PLURAL only) plus
#     "Investment Company/Co": the plural rule is what keeps Australian
#     Ethical Investment Ltd — an operating fund MANAGER — off the list.
#     Known borderline it does catch: NGI (Navigator Global Investments),
#     an asset-management holding co. Accepted: display-only, B+ today.
#   * notes-due / debentures / warrants / rights: zero hits on today's tape,
#     kept because these listing classes appear on NASDAQ routinely and each
#     would otherwise dress as a stock the moment one grades.
PRODUCT_NAME_PATTERNS = (
    r"\bPREFERRED (STOCK|STOCKS|SHARES)\b",
    r"\bINVESTMENTS (LIMITED|LTD)\b",
    r"\bINVESTMENT (COMPANY|CO)\b",
    r"\bNOTES DUE\b",
    r"\bDEBENTURES?\b",
    r"\bWARRANTS?\b",
    r"\bRIGHTS? \(",       # listing-class "Rights (…)" lines, not names containing Rights
)
# Favour the strongest trigger: the walk-forward backtest showed "retest" is
# flat-to-negative while "reclaim" carries the edge, so the bot skips these
# entry types. Selection-only; the scanner still shows them. Empty list = take all.
VIVEK_BOT_SKIP_ENTRY_TYPES = ["retest"]
# W3-ONLY LEVEL GATE (owner-signed 2026-08-02, pre-registered cycle "w3-1").
# The bot considers only candidate rows whose headline plan level_tf is in this
# tuple. Evidence: three disjoint pre-registered samples (IS / OOS / C3) each
# passed gates W-1/W-2/W-3 - weekly+3d is the program's only thrice-replicated
# positive cohort (+0.056R/trade, +0.031 R/slot-month pooled over 918 trades,
# survives 2x cost; survivorship caveat applies - see RESEARCH ledger and
# reviews/2026-08-02-c3-verdict in the project). Empty tuple = gate OFF (all
# levels, prior behaviour byte-identical). FAIL-CLOSED in vivek_run: a row with
# a missing/blank level_tf is dropped and counted, never waved through.
# Candidate ENTRIES only - held positions, exits, time-stops and loss guards
# are untouched by this gate.
VIVEK_BOT_LEVEL_TF_ALLOW = ("weekly", "3d")
# Audit-only cycle tag stamped on new book rows while a pre-registered live
# cycle runs (the sizing_mode precedent: nothing reads it to decide anything;
# it exists so pre-gate and in-cycle cohorts never blur in later reads).
# Empty string = no active cycle, no stamp.
VIVEK_BOT_CYCLE_TAG = "w3-1"
VIVEK_BOT_PREFER_TF    = "1W"      # Weekly plans are primary (less noise); fall back to 1D
# Per-market leverage: stocks 5× (positions sit smaller), crypto 3×.
VIVEK_BOT_LEVERAGE     = {"asx": 5, "nasdaq": 5, "crypto": 3}
# LONG-ONLY: the walk-forward backtest showed the short side loses ~0.5R per
# trade on every market tested (ASX/NASDAQ/Crypto) while longs carry the edge,
# so the bot is long-only for now — shorts disabled and no short slots reserved.
# The short machinery is retained behind the flag in case it's reworked later.
VIVEK_BOT_ALLOW_SHORTS   = False   # False → bot never opens a short
# Book size (owner, 2026-07-28): 30 open positions TOTAL across every market,
# free to distribute wherever the A+ setups actually are. The per-market number
# below is therefore NOT the binding constraint any more -- it is set equal to
# the global cap so one market CAN hold the whole book, and the ceiling that
# really bites is VIVEK_BOT_MAX_OPEN_TOTAL. The per-sector cap (3) still stops
# the book becoming one macro bet. Sizing is fixed-notional -- see
# VIVEK_BOT_POSITION_NOTIONAL below -- so 30 slots x $5,000 = the $150,000
# portfolio ceiling exactly.
VIVEK_BOT_MAX_POSITIONS  = 30      # max concurrent open positions PER MARKET
# Global ceiling across ALL markets, enforced in vivek_run by counting the other
# markets' canonical book files before deciding. This is race-free by
# construction: scan.yml and crypto_bot.yml share `concurrency: group: scan`
# with cancel-in-progress false, so no two market runs are ever live at once and
# a run's read of the other books cannot be stale. 0 = off (per-market only).
VIVEK_BOT_MAX_OPEN_TOTAL = 30
VIVEK_BOT_MIN_SHORTS     = 0       # reserved short slots (0 while long-only)
# ---------------------------------------------------------------------------
# SIZING — FIXED NOTIONAL (owner decision, 2026-07-28):
#   "5k position moving forward on each 30 stocks and a cap of 150k"
#
# THE 5,000 IS IN EACH MARKET'S OWN CURRENCY (owner decision, 2026-07-29:
# "It's fine make the US 5k USD and the AUS 5k AUD"). The constant is
# currency-less and `notional / entry` prices entry in the market's local
# currency, so an ASX position buys A$5,000 of stock and a NASDAQ one US$5,000
# — that asymmetry (~US$3,500 vs US$5,000 at 0.70) was flagged as #61's live
# half and the owner EXPLICITLY KEPT IT. Do not "fix" it by converting the
# notional through FX before sizing; that exact one-liner was offered and
# declined. Cross-market AGGREGATES (report dollars, drawdown) still convert
# to REPORT_CURRENCY — that half shipped in the backtest and stays.
#
# Every entry now buys a FIXED dollar amount, not a risk-derived one. Set
# VIVEK_BOT_POSITION_NOTIONAL = 0 to fall back to the old risk-% sizing path
# (VIVEK_BOT_RISK_PCT below), which is retained intact for exactly that reason.
#
# WHAT THIS CHANGES, stated plainly because it is a real trade-off:
#   * Risk per trade is no longer constant. Under risk-% sizing every loss was
#     the same dollar amount and the STOP DISTANCE moved the share count. Under
#     fixed notional the share count is constant and the STOP DISTANCE moves the
#     loss: risk_usd = 5,000 x (stop distance / entry). The stop-distance gates
#     bound it -- MIN_STOP_PCT 1% and MAX_STOP_PCT 25% -- so a 1R loss lands
#     between $50 and $1,250, typically $250-$500 on a 5-10% structural stop.
#   * Position count, not position size, is now the risk dial.
#
# WHY ACCOUNT_EQUITY MOVED WITH IT (see below): vivek_guard's daily/weekly
# circuit breakers are equity x pct. A $5,000-notional book measured against the
# old $10,000 paper equity would have tripped the 3% ($300) daily stop on the
# FIRST ordinary stop-out and halted the bot more or less permanently. Equity is
# therefore set to the owner's stated book size, which also makes the numbers
# self-consistent: 30 x $5,000 = $150,000 = 1.0x equity, no margin implied.
VIVEK_BOT_POSITION_NOTIONAL = 5_000     # target $ invested per position (0 = risk-% mode)
# Ceiling on TOTAL open notional across every market, enforced in decide() the
# same way the position ceiling is: the runner sums the sibling books and passes
# what the other markets already hold. Redundant with 30 x $5,000 by
# construction today -- deliberately so. It is the backstop that keeps the
# dollar exposure honest if the slot count or the per-position size is ever
# changed independently, and it is what actually binds if a future sizing mode
# makes positions unequal. 0 = off.
VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL = 150_000
VIVEK_BOT_RISK_PCT       = 0.35    # % equity risked per trade — ONLY used when
                                   # VIVEK_BOT_POSITION_NOTIONAL is 0 (0.25–0.5 band)
# Tradeability gates — quality-of-fill filters, NOT strategy changes. They only
# block pathological entries the paper model can't price honestly:
#  • MIN_PRICE: sub-5c ASX names (e.g. a $0.021 micro-cap) trade with spreads
#    worth multiple R — a paper fill at "the price" is fiction. Per-market floor.
#  • MAX_STOP_PCT: a structural stop >50% from entry (seen: −95% on a weekly
#    crypto plan) makes R sizing meaningless — risk-based units go microscopic
#    and the position is a lottery ticket, not a managed trade.
VIVEK_BOT_MIN_PRICE      = {"asx": 0.05, "nasdaq": 1.0, "crypto": 0.0, "default": 0.0}
VIVEK_BOT_MAX_STOP_PCT   = 25.0    # skip if |entry−stop| > this % of entry (0 = off).
                                   # Was 50 — which waved through 1D tickets whose stop
                                   # anchored to a distant higher-frame SMA (AXON: a 37%
                                   # stop, TP1 +62%, on a "daily" trade).
#  • MIN_STOP_PCT: the inverse pathology — a stop <1% from entry usually means a
#    dead/pegged instrument (stablecoin-likes, defensives glued to the SMA).
#    Risk sizing then buys a leverage-capped MAX position in something that
#    doesn't move, squatting in a scarce slot for months. 0 = off.
VIVEK_BOT_MIN_STOP_PCT   = 1.0
#  • MIN_ADV / MAX_NOTIONAL_PCT_ADV: liquidity honesty. Values are 20-day average
#    dollar volume in the market's QUOTE currency (A$ for ASX, US$ elsewhere).
#    Below MIN_ADV a real fill would eat multiple R in spread/impact, so the
#    paper edge is fiction exactly where it looks best. On top of the floor the
#    position's notional may not exceed MAX_NOTIONAL_PCT_ADV % of ADV. Crypto
#    top-100 is deep enough that the floor is off there. Unknown ADV = exempt
#    (fail-open, same as unknown sectors). 0 = off.
VIVEK_BOT_MIN_ADV        = {"asx": 250_000, "nasdaq": 2_000_000, "crypto": 0, "default": 0}
VIVEK_BOT_MAX_NOTIONAL_PCT_ADV = 2.0
# Slot hygiene — positions are capital even when flat:
#  • MAX_HOLD_DAYS: a position that hasn't reached TP1 after this many calendar
#    days is going nowhere — close it (exit_reason "time") and free the slot.
#    Runners past TP1 are exempt: they're already risk-free. 0 = off.
VIVEK_BOT_MAX_HOLD_DAYS  = 28
#  • REENTRY_COOLDOWN_DAYS: after a full stop-out, don't re-enter the same
#    symbol for this many days — stops the bot churning the same level and
#    re-donating 1R per scan cycle while a setup keeps re-arming. 0 = off.
VIVEK_BOT_REENTRY_COOLDOWN_DAYS = 7

# ── Parity backtest + n≥30 decision pack (simulation-only; live bot UNTOUCHED)
# These knobs exist so the parity replay and its variant grid read ONE place
# instead of scattering magic numbers through vivek_backtest / vivek_parity.
# Changing them does NOT change the live bot — vivek_bot.py / vivek_run.py never
# import the VIVEK_PARITY_* names. The live time-stop remains VIVEK_BOT_MAX_HOLD_DAYS.
VIVEK_PARITY_OUT_FILE = "public/data/vivek_backtest_parity.json"
VIVEK_PARITY_DEFAULT_PERIOD = "5y"
# MFE checkpoints stamped on every parity trade (calendar days from entry).
# Used by the V2 early-momentum variants and the decision pack.
VIVEK_PARITY_MFE_DAYS = (5, 10, 14, 21)
# V1 time-stop grid (calendar days, pre-TP1 only — same shape as live).
# 0 / None in a variant means "off". Baseline uses VIVEK_BOT_MAX_HOLD_DAYS.
VIVEK_PARITY_V1_HOLD_DAYS = (42, 56, 0)
# V2 early-momentum cut grid: (hold_day, mfe_r_floor). Cut if held >= day,
# still pre-TP1, and peak mfe_r is still below the floor.
VIVEK_PARITY_V2_CUTS = (
    (10, 0.25), (10, 0.50),
    (14, 0.25), (14, 0.50),
)
# A variant only PASSES if its R/slot-month improvement holds in BOTH ASX and
# NASDAQ and in BOTH time halves of the sample (crypto is reported but not a
# pass gate — thin N).
VIVEK_PARITY_PASS_MARKETS = ("asx", "nasdaq")
#  • STALE PROBE (owner ask, 2026-07-29: "no rotation rule. maybe a PROBE that
#    position has been open for 2 weeks with minimal movement for me then to
#    manually make a decision"). REPORT-ONLY — it closes nothing, changes
#    nothing, takes nothing; it pings so the OWNER decides. It fills the gap
#    the two automatic rules leave: MAX_HOLD_DAYS (28) auto-closes pre-TP1
#    stalls but says nothing at the half-way mark, and runners past TP1 are
#    exempt from it FOREVER — a +0.1R runner can squat a scarce slot for
#    months with nothing ever asking whether it should. "Minimal movement" is
#    |unreal_r| below the threshold; a row further red than that is the stop's
#    business, not this probe's. Re-pings while still stale every REPEAT days;
#    a row that starts moving drops its stamp, so a LATER re-stall is a fresh
#    episode. 0 days = probe off.
VIVEK_BOT_STALE_PROBE_DAYS       = 14
VIVEK_BOT_STALE_PROBE_MAX_ABS_R  = 0.5
VIVEK_BOT_STALE_PROBE_REPEAT_DAYS = 7
VIVEK_BOT_STALE_PROBE_PUSH       = True
#  • MAX_DATA_AGE_DAYS (2026-07-20): rows built from the last-good frame cache
#    carry data_age_days > 0 when Yahoo dropped the ticker this run. A trigger
#    "armed" on multi-day-old data is fiction — the real market has moved —
#    so the bot skips rows older than this. 0 = off. The scan still DISPLAYS
#    stale rows (age-badged); this gates the bot's entries only.
VIVEK_BOT_MAX_DATA_AGE_DAYS = 3
# Earnings gap-avoidance (best-effort, fail-open): skip NEW entries when the
# name reports within the buffer. Gapping through a stop is the one tail the
# stop can't manage. Lookup is one yfinance call per candidate FILL (a handful
# per run, not the universe) and any lookup failure lets the trade through.
VIVEK_BOT_EARNINGS_BUFFER_DAYS = 3
VIVEK_BOT_EARNINGS_MARKETS     = ("nasdaq",)   # ASX earnings data on yfinance is too patchy to trust
# Crypto correlation: coins have no GICS sector, so the per-sector cap never
# bound them — 4 alts are usually ONE beta-to-BTC bet. Synthetic sectors:
# majors below get "crypto-major", everything else "crypto-alt", then the
# normal VIVEK_BOT_MAX_PER_SECTOR cap applies.
VIVEK_BOT_CRYPTO_MAJORS  = ("BTC", "ETH")
# Correlation control: cap open positions per GICS sector per market so the book
# can't quietly become one macro bet (e.g. 6 ASX materials names = one iron-ore
# trade). Empty/unknown sectors (crypto) are exempt. 0 = off.
VIVEK_BOT_MAX_PER_SECTOR = 3

# ── SECTOR BREADTH / HORIZON (2026-07-28, scanner/sectorbreadth.py) ───────────
# REPORT-ONLY. None of these change which trades get taken; they decide what the
# rotation surface can see and remember. Written after the July post-mortem, in
# which an entire sector ran for four weeks while the only published sector
# number (a RAW setup count, dominated by how many names each sector lists) said
# nothing, and the book sat at its ceiling for 20 straight sessions unable to
# act even if it had.
SECTOR_BREADTH_ENABLED   = True
#  • MIN_NAMES: a sector with fewer listed names than this is computed but never
#    RANKED. Participation rate on a 3-name sector is 0% or 33% and would top
#    every leaderboard on noise alone.
SECTOR_BREADTH_MIN_NAMES = 15
#  • TOP_N: how many sectors count as "leading" for the unheld-leaders alarm.
SECTOR_BREADTH_TOP_N     = 3
#  • HISTORY_MAX: rows kept in data/sector_history.json (one per market per DAY,
#    ~2 markets x 250 sessions = a year at 500). This file is the ONLY long
#    sector memory in the system — the 7-day PhaseMap archive was too short to
#    reconstruct the July rotation after the fact — so keep it generous.
SECTOR_BREADTH_HISTORY_MAX = 2000
#  • PUBLISH_DAYS: how much of that history is republished for the page to plot.
SECTOR_BREADTH_PUBLISH_DAYS = 180
#  • RUN_ALERT: sessions a top-N sector may lead on breadth with NOTHING held
#    before the surface stops describing it and starts shouting. One day is a
#    coincidence and the page should stay calm; a run this long is a rotation
#    being missed in progress, which is the whole reason this module exists.
#    July ran nineteen. Report-only -- it changes the volume, never the trades.
SECTOR_BREADTH_RUN_ALERT = 5
#  • RUN_ALERT_PUSH: also push that run alarm through the NOTICE tier
#    (config.ALERT_CHANNELS; Discord until the 2026-08-27 removal, currently
#    no live channel) instead of only colouring the page. A
#    surface you have to open to be warned by is a surface that warns you after
#    you already looked, which in July was never. Rate-limited through
#    journal/alert_state.json so a 19-session run pings once, not nineteen times.
SECTOR_BREADTH_RUN_ALERT_PUSH = True
#  • RUN_ALERT_REPEAT_DAYS: re-ping an already-alerted sector only after this
#    many days. 0 = never repeat while the run continues.
SECTOR_BREADTH_RUN_ALERT_REPEAT_DAYS = 7

# ── REGIME / RELATIVE STRENGTH (2026-07-28, scanner/regime.py) ────────────────
# REPORT-ONLY, same as breadth above: nothing here reaches decide(). This block
# is the OTHER half of the July post-mortem. Breadth answers "which sector is
# setting up today"; this answers "is the market actually as bad as the index
# says, and who is beating it" — the two things the owner could feel but could
# not read anywhere. Every number below is arithmetic on daily closes, so the
# full history recomputes on each run: no state file, no backfill, correct on
# the first execution and able to describe JUNE.
REGIME_ENABLED = True
#  • DAYS: published sessions per market (~6 months). Long enough that a run
#    that started in June is visible in full; the cost is only JSON size.
REGIME_DAYS = 126
#  • RET_WINDOWS: (fast, slow) return lookbacks in sessions, ~1 and ~3 months.
#    The fast one is what "consumer discretionaries ran for a month" means.
REGIME_RET_WINDOWS = (21, 63)
#  • HL_WINDOW: lookback for new-highs-minus-new-lows.
REGIME_HL_WINDOW = 20
#  • FAST_SMA: the shorter participation line. The slow one is deliberately
#    VIVEK_SMA (200) — the engine's OWN level — so "above the average" on this
#    page means the same thing it means in a setup.
REGIME_FAST_SMA = 50
#  • TOP_N: how many sectors count as leading on relative strength, and the
#    membership the rs_streak counter tests against.
REGIME_TOP_N = 3
#  • BENCHMARK: the cap-weighted index per market, used ONLY to state the
#    divergence between it and the equal-weight median name. Markets absent
#    from this map are skipped entirely (crypto has no sectors to rank).
#    The relative-strength maths never uses it — the benchmark for rs21/rs63 is
#    the market's own median name, which is survivorship-consistent with the
#    numerator and cannot fail to download.
REGIME_BENCHMARK = {"asx": "^AXJO", "nasdaq": "^IXIC"}
#  • RISK_ON/RISK_OFF_ABOVE200: the two cut points of the three-way state read
#    (BROAD / MIXED / NARROW). Coarse on purpose — a count of names above a
#    moving average does not support a finer scale than thirds.
REGIME_RISK_ON_ABOVE200 = 0.55
REGIME_RISK_OFF_ABOVE200 = 0.35
#  • DIVERGENCE_MIN: how far the median name and the index must part before the
#    page says so. Below this they are the same story told twice.
REGIME_DIVERGENCE_MIN = 0.02
#  • MIN_DAY_COVERAGE: a date on which fewer than this share of the market's
#    best-covered session has a bar is a pseudo-session (a mis-dated bar, a
#    half day, a foreign holiday) and is dropped rather than published as a day
#    the market vanished.
REGIME_MIN_DAY_COVERAGE = 0.5

# Push a digest of the bot's opens/closes through alert_dispatch each run.
# OFF by default: the scan workflow exports SMTP creds, and alert_dispatch fires
# EVERY configured channel — enabling this without wanting it means an email per
# bot trade event (hourly-ish in session).
VIVEK_BOT_NOTIFY_TRADES = False
# Daily-loss guardrail (per market). Once today's realised + open-unrealised P&L
# falls to -this% of equity, the runner HALTS new entries for the rest of the
# session (it still manages/closes open positions). In a future live phase this
# is also where a flatten would fire; in paper it just stops adding risk.
VIVEK_BOT_MAX_DAILY_LOSS_PCT = 3.0
# Weekly circuit breaker (per market): the daily guard resets at midnight, so
# five max-loss days in a row were previously allowed. Once realised P&L over
# the trailing 7 calendar days + open unrealised falls to -this% of equity,
# new entries halt until the window rolls off. 0 = off.
VIVEK_BOT_MAX_WEEKLY_LOSS_PCT = 6.0
# REVIEW threshold (2026-07-28, owner's instruction). NOT a gate — nothing is
# ever skipped for crossing it. When a plan the bot has already decided to take
# would risk this % or more of the daily loss guard above, the ticket carries a
# `review` flag so the owner can decide whether to let the bot take it or take
# it himself, sized his own way. The two numbers it sits between: the hard
# MAX_STOP_PCT gate caps any new position at 25% x $5,000 = $1,250 of risk,
# which is 27.8% of the $4,500 guard, so a threshold at or above ~28 could
# never fire; a typical A+ plan runs a 5-12% stop, i.e. $250-$600, i.e. 6-13%
# of the guard. 15 therefore flags the genuinely wide half without crying wolf
# on ordinary trades. 0 = off.
VIVEK_BOT_REVIEW_DAILY_LOSS_PCT = 15.0

# Push the review flag through the NOTICE tier when a flagged position is opened
# (`vivek_run._notify_reviews`). ON, unlike VIVEK_BOT_NOTIFY_TRADES next to it,
# and the difference is the point: that one digests EVERY open and close through
# alert_dispatch, which fires every configured channel including email, so it is
# off to avoid emailing routine trades. This one fires only on the flagged
# minority, at NOTICE. A flag nobody sees on the day is not a
# flag -- the whole instruction was so the owner could decide before the trade
# has moved. Set False to keep the flag on the row and the page but stop the
# push.
VIVEK_BOT_REVIEW_PUSH = True

# ── Autonomous runner (scanner/broker/vivek_run.py) — Phase 1-2: dry-run + paper
# book. NO live execution is wired yet. Live trading requires, all together:
# VIVEK_BOT_ENABLED + per-market MODE "live" + VIVEK_LIVE_CONFIRMED + a real
# broker (only crypto/Bybit exists) + BYBIT_TESTNET=false. Until then the runner
# only ever builds a paper book.
VIVEK_BOT_ENABLED        = True    # master switch — runner maintains the PAPER book each scan
VIVEK_BOT_DRY_RUN        = False   # False = write the paper book so trades persist + show in the journal
                                   #   (paper only — places NO real order; live needs MODE=live +
                                   #    VIVEK_LIVE_CONFIRMED + a wired broker, none of which exist yet)
VIVEK_BOT_MODE           = {"asx": "paper", "nasdaq": "paper", "crypto": "paper"}  # "live" not wired yet
# Equity does NOT compound by deliberate decision (2026-07-16): realised P&L is
# never fed back into sizing, so per-trade figures stay comparable across the
# whole forward test — the point of the paper phase is measuring edge, not
# growth. Revisit when the book goes live (real accounts compound whether you
# like it or not). Values are in the market's quote currency (A$ ASX, US$ else).
#
# RAISED 10,000 -> 150,000 on 2026-07-28 with the fixed-notional switch. Since
# sizing is now VIVEK_BOT_POSITION_NOTIONAL, this number no longer sets position
# size at all — its ONE remaining job is scaling the loss guards, which are
# equity x pct (vivek_guard.check, kill_switch). Leaving it at 10,000 beside a
# $150,000 book would have made the 3% daily stop $300 — less than a single
# ordinary 1R loss — and the bot would have sat halted. At 150,000 the guard
# keeps roughly the same headroom in R that it had before: $4,500/day against a
# typical $250–$500 loss is ~9–18R, versus $300 against $35 (8.6R) before.
VIVEK_BOT_ACCOUNT_EQUITY = 150_000  # book size; scales the loss guards, NOT position size
VIVEK_LIVE_CONFIRMED     = False   # extra hard lock for any future live order

# WHICH BROKER ACTUALLY HOLDS EACH MARKET'S POSITIONS (2026-07-28).
# kill_switch.run_standalone checks the bot book PER MARKET — three separate
# limits, three separate verdicts — but a broker flatten is ACCOUNT-WIDE:
# bybit_client.close_all_positions() reduce-only-closes every position on the
# account and cancel_all_orders() kills every resting order. Without this map an
# ASX paper-book breach called cancel-all + close-all on Bybit, i.e. liquidated
# a live crypto book that was inside its own limit, in response to a loss that
# happened somewhere Bybit cannot see. Losing money on the ASX is not a reason
# to sell your crypto.
#
#   ()          — no broker holds this market. A breach still alerts, logs and
#                 counts as triggered; it just does not reach for an account
#                 that holds none of the positions that lost the money.
#   ("bybit",)  — flatten via bybit_client, and ONLY if BYBIT_API_KEY is set.
#   ("alpaca",) — flatten via alpaca_client, and ONLY if ALPACA_API_KEY is set.
#
# A market MISSING from this dict falls back to the legacy try-Bybit-then-Alpaca
# flatten and logs a WARNING. That default is deliberately the over-protective
# one: a new market added without a line here is noisy, never quietly unguarded.
VIVEK_KILL_SWITCH_BROKERS = {
    "asx":    (),             # paper only — IBKR is not built
    "nasdaq": ("alpaca",),    # legacy Alpaca path
    "crypto": ("bybit",),     # Bybit USDT perps
}


# ---------------------------------------------------------------------------
# MOVERS — biggest winners/losers on the NEWS page, split by company size so
# you can read big-money rotation (mega) AND discovery (small caps) separately.
# ---------------------------------------------------------------------------
MOVER_PER_TIER = 5            # up to this many MEGA + this many SMALL per side
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
# Phase 5: Risk Management — portfolio-level limits
# ---------------------------------------------------------------------------

PORTFOLIO_HEAT_LIMIT      = 0.07    # max 7% of account at risk at any time across all open positions

# Phase 5: Circuit Breakers
CONSEC_LOSS_PAUSE         = 3       # pause after 3 consecutive losing trades (matches JS engine)


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
    # HORIZON's sustained-run alarm (2026-07-28, scanner/sectorbreadth.notify).
    # Its own tier because neither existing one fits: INFO is silent, and the
    # module is REPORT-ONLY, so calling a rotation a WARNING would put it beside
    # order rejections and circuit breakers in the same feed and at the same
    # volume. Nothing is wrong when this fires -- something is HAPPENING.
    "sector_run":      "NOTICE",
    # A position was opened carrying a review flag (2026-07-28, owner: "Flag
    # this in the future so i can verify whether claude or I should take the
    # position or not"). Same tier and the same reason: the trade passed every
    # rule and was taken correctly, so nothing is broken -- but it is heavy
    # enough that the owner may want it as HIS position rather than the bot's,
    # and that decision has a shelf life measured in hours.
    "trade_review":    "NOTICE",
    # A position has sat ≥2 weeks with minimal movement (2026-07-29, owner:
    # "maybe a PROBE ... for me then to manually make a decision"). Same tier
    # as its siblings for the same reason: nothing is broken, a decision is
    # due — and it is explicitly the owner's, the probe takes none itself.
    "stale_position":  "NOTICE",
    # A market's scan came back EMPTY N runs in a row (2026-07-29, owner said
    # yes to the build after the 2026-07-29 outage: Yahoo throttled every ASX
    # scan of the morning session and the "no data - keeping existing JSON"
    # exit is deliberately GREEN, so nothing said the dashboard had quietly
    # stopped updating). One dry run is weather; several in a row is an
    # outage. NOTICE, not WARNING: the pipeline is healthy, the DATA SOURCE
    # is refusing, and the fix (wait / press SCAN later) is the owner's.
    "scan_dry":        "NOTICE",
    # The paper book's daily/weekly loss guard tripped and new entries are
    # halted for the session (2026-07-28, scanner/broker/vivek_run). CRITICAL
    # alongside `daily_loss` because it is the same event seen from the book
    # rather than from the broker: a real risk limit was hit and the system has
    # changed what it will do. It used to fire through alert_dispatch.send
    # directly, which meant no severity at all.
    "vivek_guard":     "CRITICAL",
    # Bybit holds a position the journal has never heard of (2026-07-28,
    # broker/bybit_reconcile._sweep_orphans). CRITICAL and not negotiable: it is
    # REAL exposure that no stop-watcher, no loss guard and no kill-switch is
    # counting, because every one of those reads the journal and the journal
    # does not know the position exists. The severity is the point -- it used to
    # go out through alert_dispatch.send, which has no tier at all, so this
    # could not be routed, deduped or acknowledged like anything else.
    "orphan_position": "CRITICAL",
}

# Set False to silence all Telegram sends without touching secrets.
# Flip back to True when the bot is ready to go live again.
TELEGRAM_ENABLED = False

# Map severity → alert channels (telegram / email; discord REMOVED 2026-08-27
# by owner ruling — "get rid of the discord aspect, I will work on
# implementing something new in the future". The router, tiers and rate
# limits all stay: the next channel plugs in here by adding its name to the
# tiers below and a sender to alert_dispatch. Until then CRITICAL/WARNING
# route to telegram+email, both currently unconfigured, so delivery is the
# router's "NOBODY WAS TOLD" log line plus GitHub's own red-run emails.)
ALERT_CHANNELS = {
    "CRITICAL": ["telegram", "email"],
    "WARNING":  ["telegram"],
    "INFO":     [],  # log only — no push notification for routine events
    # NOTICE was Discord-only by the 2026-07-28 ruling (market observations,
    # nothing broken). With that channel removed it pushes nowhere; the
    # events are still computed, logged and deduped by their owners, so the
    # future channel inherits them by adding itself to this list.
    "NOTICE":   [],
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
    # 0 = the router never suppresses this one; sectorbreadth.notify owns the
    # dedupe entirely (per market AND per sector, memory in the history file).
    # A limit here would be per EVENT TYPE, so the first market to fire would
    # silence the second — and scan.yml runs the markets sequentially inside a
    # single job, which makes that the normal case rather than an edge one.
    "sector_run":      0,
    # 0 for the same per-EVENT-TYPE reason, plus a sharper one: this fires only
    # when a flagged position was actually OPENED, which is inherently one-shot
    # -- a position is opened once and never again -- so there is no storm to
    # limit. What a limit WOULD do is silently drop the second flagged open of a
    # sequential multi-market run, i.e. lose a decision the owner asked to be
    # given. Missing one of these is the failure mode; repeating one is not.
    "trade_review":    0,
    # 0 — the probe owns its dedupe (per-position stale_pinged stamp in the
    # book, REPEAT_DAYS between reminders); a per-EVENT-TYPE limit here would
    # drop the second market's stale list in a sequential full cycle.
    "stale_position":  0,
    # 0 — same per-EVENT-TYPE reason as its neighbours (a full cycle scans
    # three markets sequentially in one job; a limit would drop the second
    # market's outage), and the dedupe is structural anyway: the counter in
    # data/scan_health.json fires only at EXACTLY the threshold, once per
    # outage episode, and resets on the first successful publish.
    "scan_dry":        0,
    # 0 for the third time, for the third variation of the same reason: the
    # limit is per EVENT TYPE and the markets run sequentially inside one job,
    # so any nonzero value here could only ever drop the SECOND market's breach.
    # vivek_run owns the dedupe instead, keyed on day + breach kind and stored
    # in the per-market book — tighter than a global timer everywhere it
    # differs, and it cannot disagree with itself about what day it is because
    # the same commit writes both.
    "vivek_guard":     0,
    # 0, and the dedupe is on the SET OF ORPHAN SYMBOLS rather than on a clock
    # (bybit_reconcile._sweep_orphans). A time window is the wrong tool here:
    # an orphan persists until a human adopts or closes it, so a window long
    # enough to stop the alert becoming wallpaper is also long enough to
    # swallow a genuinely NEW orphan appearing inside it -- and the new one is
    # the entire reason the probe runs.
    "orphan_position": 0,
    "DEFAULT":         300,
}

# ── Mark-sanity guard (2026-07-21, Phase 6 P1 — vivek_run + kill_switch) ─────
# Reject a position mark whose one-interval move vs the LAST ACCEPTED mark
# exceeds this fraction: splits (auto_adjust rewrites the price basis while
# stored entry/stop stay in the old one) and vendor bad prints would otherwise
# book fake catastrophic exits into the only track record. Alert fires on the
# 2nd consecutive suspect run; the price is ACCEPTED on the Nth so a real
# crash is delayed at most (N-1) runs, never ignored. Crypto gets more head-
# room (real 40%+ days happen).
VIVEK_MARK_SANITY_PCT = {"asx": 0.35, "nasdaq": 0.35, "crypto": 0.60}
VIVEK_MARK_SANITY_ACCEPT_RUNS = 3

# ── Freshness watchdog (2026-07-20, Phase 5 — scanner/watchdog.py) ────────────
# Runs inside kill_switch.yml (:15/:45) + crypto_bot.yml (hourly). Thresholds
# are >= 2x the worst GitHub cron drift ever observed in this repo (48 min) so
# scheduler jitter can never page anyone. CRITICAL routes per ALERT_CHANNELS
# (incl. email); WARNING skips email. One alert on first detection, one
# reminder every WATCHDOG_RENOTIFY_HOURS, one recovery notice — never more.
WATCHDOG_RENOTIFY_HOURS = 6.0
WATCHDOG_BOOK_MAX_AGE_H = 4.0          # combined book updated_at (money path)
WATCHDOG_CRYPTO_SCAN_MAX_AGE_H = 4.0   # crypto_vivek.json generated_at
WATCHDOG_PHASEMAP_MAX_LAG_DAYS = 2     # latest.json run_date lag
WATCHDOG_BACKUP_MAX_AGE_H = 26.0       # newest backups/ snapshot dir
# Ticker-roster freshness (data/universe_cache/<market>.json saved_at). The ASX
# directory fetch died silently for three days in 2026-07 because a dead source
# and a merely flaky one look identical from outside: the cache fallback covers
# both. These make a dead source say so.
# ASX/NASDAQ scan weekdays only, so their age is measured in WEEKDAY hours --
# a flat wall-clock limit would have to exceed the 65h Fri-close/Mon-open gap
# and would then take three days to notice anything. 40 weekday-hours lets one
# fully missed session pass in silence and fires on the second.
WATCHDOG_UNIVERSE_MAX_AGE_H = 40.0

# ── Confluence forward-return ledger (scripts/alert_returns.py, 2026-08-20) ──
# Research artefact only: measures whether multi-lens alignment predicts
# anything. Horizons are TRADING SESSIONS after the alert's own session close;
# the ledger (data/alert_forward_returns.json) is durable precisely because the
# public alert_history.json is a rolling 800-cap window that evicts entries at
# ~14 days on current volume - a 20-session return can never mature there.
ALERT_RETURNS_HORIZONS = (1, 5, 10, 20)   # 1-session added 2026-08-20: the
# fast-maturing curve — with a 14-day eviction upstream and 20-session answers
# a month out, the 1-session point is what makes the maturity curve readable
# while the batch's edge questions are still warm. Legacy rows' fwd dicts are
# padded (missing horizon = unstamped, filled on the next run), never wiped.
# Ledger cap: only FULLY-stamped entries are ever trimmed (dropping a waiting
# entry would silently un-measure the feature). ~57 alignments/day today, so
# 20,000 is roughly a year of memory.
ALERT_RETURNS_CAP = 20000
# Daily A+ roster ledger (scripts/edge_rosters.py, batch-100 WS-B): the
# single-lens BASELINE cohort, stamped with the same forward returns on the
# same Yahoo plumbing as the alerts — so "does alignment beat plain A+" keeps
# answering itself without git archaeology. ~160 A+ rows/day -> 20k is ~4
# months of memory; trim only ever drops fully-stamped rows.
ALERT_ROSTER_CAP = 20000
# Book tide-stress shocks (scripts/book_stress.py, batch-100 WS-D): uniform
# beta-1 mark drawdowns tested against every long's REAL stop. -3% is roughly
# a reversion of breadth to its 6-month mean as measured 2026-08-20; -10% is
# the February trough revisited.
BOOK_STRESS_SHOCKS = (0.03, 0.05, 0.08, 0.10)
# Crypto scans hourly 24/7, so its roster is judged on plain wall-clock.
WATCHDOG_UNIVERSE_CRYPTO_MAX_AGE_H = 12.0
# Run-history probes (GitHub Actions API): workflow file -> threshold on the
# LAST SUCCESSFUL run. A latest-run FAILURE is deliberately not alerted here —
# GitHub already emails failures; the watchdog only covers SILENT problems.
WATCHDOG_RUNS = {
    "kill_switch.yml": {"max_age_h": 2.0,  "severity": "CRITICAL"},
    "crypto_bot.yml":  {"max_age_h": 3.0,  "severity": "WARNING"},
    "scan.yml":        {"max_age_h": 24.0, "severity": "WARNING"},
    "phasemap.yml":    {"max_age_h": 26.0, "severity": "WARNING"},
    "backup_book.yml": {"max_age_h": 26.0, "severity": "CRITICAL"},
    "confluence.yml":  {"max_age_h": 26.0, "severity": "WARNING"},
    "reco_note.yml":   {"max_age_h": 26.0, "severity": "WARNING"},   # daily auto note (2026-07-23)
    "alert_returns.yml": {"max_age_h": 26.0, "severity": "WARNING"},  # confluence forward returns (2026-08-20)
    # 5-min cron, so 1h of no SUCCESSFUL run means ~12 misses (2026-07-28).
    # It commits nothing, which is exactly why it needs an entry here: every
    # other watchdog target is caught by its output going stale, and this one
    # has no output. This entry now answers exactly ONE question -- "is the
    # 5-minute cron still firing at all?" -- because the workflow deliberately
    # exits 0 on a 503 (see stop_watcher.yml and WATCHDOG_TICK_URL below), so a
    # green run no longer implies a healthy endpoint. Endpoint HEALTH is
    # probe_endpoints()'s job; schedule health is this one's. CRITICAL because
    # while the cron is dead no paper stop or target is evaluated unless a
    # chart page happens to be open.
    "stop_watcher.yml": {"max_age_h": 1.0, "severity": "CRITICAL"},
}

# Cloud stop/target watcher endpoint (functions/api/tick.js), probed directly by
# watchdog.probe_endpoints (2026-07-28). Committed files cannot vouch for this
# service: it writes nothing to the repo, so the ONLY way to know it works is to
# ask it.
#
# PROBED UNAUTHENTICATED, ON PURPOSE. tick.js validates its own configuration
# and then the caller's credential BEFORE it touches KV or evaluates a single
# position, so an anonymous GET can never fire a stop, close a trade or read a
# journal. Never add the real TICK_SECRET here to "probe it properly" -- that
# would make the monitor run an extra unscheduled tick every 30 minutes, i.e.
# the monitor would start moving the thing it is monitoring.
#
# The three answers, and why the middle one is the healthy one:
#   503 -> TICK_SECRET (or JOURNAL_KV) missing in Cloudflare. The watcher has
#          never been switched on; paper stops/targets only fire while a chart
#          page is open. WARNING: a setup gap the owner closes in Cloudflare.
#   401 -> configured, and correctly refusing an anonymous caller. HEALTHY --
#          this is the response a working deployment gives this probe, so no
#          finding is raised.
#   200 -> it ran for a caller with no secret at all. The endpoint is WIDE OPEN
#          and anyone who knows the URL can walk every synced journal. CRITICAL,
#          and a security finding rather than a freshness one.
WATCHDOG_TICK_URL = "https://googy-boys-scanner.pages.dev/api/tick"
WATCHDOG_TICK_ENABLED = True


# ---------------------------------------------------------------------------
# Phase 8: Enhanced Monitoring & Alerting
# ---------------------------------------------------------------------------


# Weekly report rate-limit bucket (separate from daily_report so each has its own cadence)
ALERT_RATE_LIMITS_EXTRA: dict = {
    "weekly_report": 518_400,  # max 1 per 6 days (604800 = 7d; 518400 = 6d allows a little slack)
}

# ---------------------------------------------------------------------------
# Alert credentials — the boundary every pasted secret crosses
# ---------------------------------------------------------------------------
# (The Discord digest that used to live under this heading was removed with
# the whole Discord channel on 2026-08-27; clean_secret stays because it
# guards EVERY pasted credential, not one channel's.)


def clean_secret(value) -> str:
    """Strip the invisible baggage a hand-pasted secret can carry.

    Found live 2026-08-01: the stored DISCORD_WEBHOOK_URL began with U+FEFF —
    a byte-order mark, invisible in the GitHub secrets box — which urllib
    rejects as `unknown url type: \\ufeffhttps`. Every sender wraps its post
    in try/log-warning, so the entire Discord channel (stale probes, trade
    reviews, sector alarms, kill-switch notices) failed SILENTLY for as long
    as that paste was in place; the evidence brief's first delivery was
    simply the first caller that let the exception fail a run out loud.

    Every consumer of a pasted credential routes through here, so the next
    stray BOM, zero-width character or trailing newline dies at the boundary
    instead of inside a swallowed exception. Interior characters are never
    touched — this trims ends only.
    """
    return str(value or "").strip(
        " \t\r\n\ufeff\u200b\u200c\u200d\u200e\u200f")
CONF_ALERT_MIN_LENSES  = 3           # only PUSH alignments with at least this many lenses
                                     # (3 = triples only — owner's call 2026-07-02; the site
                                     # still shows every 2-lens alignment visually. Channel-
                                     # independent POLICY, kept through the 2026-08-27 Discord
                                     # removal: confluence_alert still computes what deserves a
                                     # push and records it as undelivered, so the next channel
                                     # pings everything current on its first run.)
SITE_URL               = "https://googy-boys-scanner.pages.dev"   # chart links in alerts

# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
DATA_PERIOD = "1y"            # history pulled per ticker (~252 bars; enough for EMA144 + all lookbacks)
DATA_DAILY_BARS = 252         # bars the daily scanners see (tail-slice of VIVEK's deep download = 1y, unchanged behaviour)
DATA_STALENESS_HOURS = 4      # flag data as stale if last bar is older than this many hours
SCALP_DATA_MIN_BARS  = 65     # minimum 1h bars required for scalp evaluate() (matches SCALP_MIN_BARS)
# HOW OLD A CACHED FRAME MAY BE AND STILL COUNT AS DATA (2026-07-28, TOP100 #24).
# `data.merge_with_cache` back-fills tickers Yahoo dropped this run from the
# last-good cache, which is exactly right for the ordinary case: a name misses
# one batch and reappears. It had NO ceiling, so a ticker Yahoo has not returned
# since March was still handed to the scanner as if it were today's bars — its
# last close published as a live mark and used to mark held positions and test
# their stops. That is not last-good data, it is a fossil, and a fossil price
# can fabricate a stop-out as easily as it can hide one.
# Generous on purpose. The cache exists to ride out outages, so the ceiling must
# clear a multi-day Yahoo gap plus a long weekend without ever biting; only a
# suspension or a delisting should reach it. Refusing a frame can only ever
# REMOVE a name from the scan, never add one, and a held position that loses its
# frame this way is re-fetched directly by vivek_run's off-universe path or
# counted by `unpriced_runs` — visibly unpriced beats silently wrong.
# 0 = off (unbounded reuse, the pre-2026-07-28 behaviour).
FRAME_CACHE_MAX_AGE_DAYS = 10

# Yahoo download throttling control. Yahoo rate-limits bursty/concurrent
# requests (HTTP 429). The downloader stays FAST when Yahoo is healthy (short
# retry waits, no penalty on success) and only gets patient when it's clearly
# being throttled hard (a run of consecutive failed batches triggers a longer
# cooldown). This keeps coverage high without the old fixed 5→75s crawl.
DATA_CHUNK         = 120      # tickers per yfinance request (smaller = lighter, less likely to be throttled)
DATA_BATCH_PAUSE   = 0.4      # base seconds to pause between successive batches (+ jitter)
DATA_RETRIES       = 3        # attempts per batch before giving up on it
DATA_BACKOFF       = [2, 5, 12]        # short, escalating waits within a single batch's retries
DATA_HEAVY_AFTER   = 3        # consecutive failed batches => treat as heavy throttling
DATA_HEAVY_COOLDOWN = 25      # seconds to let Yahoo recover once heavy throttling is detected
DATA_RECOVERY_COOLDOWN = 20   # cooldown before the single recovery sweep re-tries failed tickers

# ---------------------------------------------------------------------------
# Execution robustness
# ---------------------------------------------------------------------------
ORDER_RETRY_ATTEMPTS     = 3    # retry Bybit API calls this many times on failure
ORDER_RETRY_BACKOFF_BASE = 2    # base seconds for exponential backoff (2s, 4s, 8s…)

# ---------------------------------------------------------------------------
# Scan error visibility (TOP100 #60/#66/#67)
# ---------------------------------------------------------------------------
# Per-ticker exceptions used to be swallowed behind `if progress:` (production
# passes progress=False) or a bare `pass`, so a name that threw EVERY session
# was indistinguishable from a name that simply never set up. These bound how
# much of that now travels in the published payload.
SCAN_ERROR_SAMPLE_MAX    = 12   # error rows published per market (0 = count only)
SCAN_ERROR_MSG_MAX       = 160  # chars kept per error message before truncation
SCAN_ERROR_KINDS_MAX     = 4    # distinct exception types named in the summary line
SCAN_ERROR_LOUD_PCT      = 5.0  # >= this % of names failing prints the '!!' marker

# ---------------------------------------------------------------------------
# Deliberate-skip marker (TOP100 #67 follow-up, 2026-07-28 incident)
# ---------------------------------------------------------------------------
# `run.py` has ONE path where a market publishes nothing and that is CORRECT:
# the download came back fully empty AND the frame cache had nothing to fall
# back on, so the market keeps yesterday's JSON rather than clobbering it with
# an empty scan. That path exits 0 on purpose — it is a reported decision, not
# a fault, and failing on it would turn every upstream Yahoo outage red.
#
# `scan.yml`'s per-market `assert_staged` gate cannot see that decision. All it
# sees is "<market>_vivek.json has no staged diff", which is byte-identical to
# the silent-staging bug the gate was built to catch (2026-07-20). It therefore
# failed the whole cycle for an outage nobody can fix — the failure-email
# problem this repo has now talked itself out of three times.
#
# This file is the discriminator between the two. run.py appends a market key
# here when (and only when) it takes that deliberate skip; scan.yml reads it and
# downgrades exactly those markets' asserts to a loud warning, leaving the gate
# hard for every market that claimed to scan. Untracked and per-workspace: CI
# checks out fresh each run, and the three sequential market processes share one
# checkout, hence append rather than overwrite.
SCAN_SKIP_MARKER = ".scan-skipped"

# Consecutive-dry-run alarm (2026-07-29, owner-approved threshold 3). A "dry"
# run is run.py's deliberate "no data - keeping existing JSON" exit: the source
# returned nothing and yesterday's artefact was kept rather than clobbered.
# That exit is GREEN by design, which the 2026-07-29 Yahoo throttling showed
# cuts both ways: every ASX scan of the morning session ran dry and nothing
# said so anywhere. The counter lives in SCAN_HEALTH_FILE (committed by
# scan.yml's SHARED staging list, so it survives the Actions container — the
# same lesson as sectorbreadth's ping memory), resets on the first successful
# publish, and pushes a NOTICE ONCE per episode, exactly at the threshold.
SCAN_DRY_ALERT_RUNS = 3
SCAN_HEALTH_FILE = "data/scan_health.json"

# Funnel detail (2026-07-29, owner's strategy-audit ask): of the names that HAD
# a setup and were dropped by the liquidity floor, publish the few where volume
# is ARRIVING — today's volume as a multiple of the name's own 20-day average.
# A sleepy average with a big today-multiple is the "breakout being born in a
# thin name" the owner is worried the floor is killing; a low multiple is just
# a thin name. REPORT-ONLY: the floor still drops every one of them — this is
# the evidence for whether the floor needs an owner-ruled exception, not the
# exception itself. Sample is capped (same reasoning as SCAN_ERROR_SAMPLE_MAX)
# and sorted by that multiple, so the payload cost stays ~1KB.
SCAN_FUNNEL_ILLIQUID_SAMPLE_MAX = 12

# ---------------------------------------------------------------------------
# The "liquidity arriving" list (owner-ruled 2026-07-30: "Green-light, narrow
# implementation only.") — public/data/<market>_arriving.json
# ---------------------------------------------------------------------------
# TWO-LEG entry rule, exactly as ruled, applied only to names the floor KILLED:
#   leg A: today's turnover ALONE clears the market's existing floor
#          (market.liquidity_min — the floor itself is BYTE-UNTOUCHED), and
#   leg B: today's volume >= SCAN_ARRIVING_MIN_RVOL x the name's own 20d avg.
# Leg A is load-bearing: rvol alone is the pump signature (an 18x day on A$500
# of dust). REPORT-ONLY and structurally fenced: the list lives in its own
# file, which nothing in scanner/broker/ opens (test-pinned); rows carry no
# grade/plan/entry fields; qualifying names are still DROPPED from the scan
# exactly as before. Never fed to Specs/VIVEK/PhaseMap, never re-graded.
SCAN_ARRIVING_MIN_RVOL = 3.0
SCAN_ARRIVING_MAX      = 12    # cap, sorted by today's turnover (participation,
                               # not multiple — the multiple is the pump smell)
                                # (0 = never loud)

# Funnel history (2026-07-30, owner-ruled Task 2) — an APPEND-ONLY record of
# each scan's funnel counts (scanned / with-data / published / floor-killed /
# arriving) so the one-scan snapshot ("299 killed today") becomes a trend
# ("does the floor tighten into rallies?"). Written by scanner/funnelhistory.py
# from run.py's publish loop; REPORT-ONLY — nothing in scanner/broker/ reads it
# back (test-pinned, same fence as the arriving list). Columnar per market to
# keep the committed artefact small.
SCAN_FUNNEL_HISTORY_FILE = "funnel_history.json"   # under the publish root
SCAN_FUNNEL_HISTORY_MAX  = 2000   # rows kept PER MARKET (crypto ~40 days at
                                  # 48 scans/day, ASX ~8 months at 8/day —
                                  # uneven on purpose: the cap is a size
                                  # guard, the chart buckets by day anyway)

# Specs -> VIVEK graduation watch (2026-07-31, owner-ruled) — the tally of
# names the Specs lens surfaced (sub-$0.50 discoveries) that LATER appeared in
# the published <m>_vivek.json, i.e. crossed the 50c line and/or the liquidity
# floor into VIVEK eligibility and set up there. Written by scanner/specgrad.py
# from spec_run's nightly publish path alone; REPORT-ONLY, same fence as the
# arriving list and the funnel history — nothing in scanner/broker/ reads
# spec_graduation.json back (test-pinned); the display is public/js/specs.js.
SPEC_GRAD_FILE     = "spec_graduation.json"   # under the publish root
SPEC_GRAD_SEEN_MAX = 2000   # per-market watch cap (oldest first_seen trimmed;
                            # Specs publishes ~0-10 names a night, so this is
                            # years of headroom, not a number that will bind)
SPEC_GRAD_MAX      = 400    # per-market graduations kept (newest tail); the
                            # lifetime tally survives trims in graduated_total


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

# Reporting currency for any figure that SUMS across markets, and the AUD/USD
# rate to use when the published `public/data/fx.json` cannot be read.
#
# TOP100 #61: an ASX position's dollars are A$ (it is sized off an A$ entry
# price) and NASDAQ/crypto dollars are US$, so a combined total added them at
# face value and overstated the AUD leg by ~1/rate — roughly 43% at 0.70. R is
# immune (it divides by the position's own risk, so the currency cancels), which
# is exactly why the R figures looked sane while the dollar ones did not.
#
# The fallback is deliberately the SAME number `public/js/journal.js` falls back
# to, so an offline page and an offline report cannot disagree about the rate
# while both claim US$. It is a fallback, not an estimate: anything that uses it
# must record that it did.
REPORT_CURRENCY   = "USD"
FX_AUDUSD_FALLBACK = 0.66

# Sanity band for the LIVE AUD/USD fetch (run.py) — a rate outside this range
# is a bad tick or the wrong instrument, and publishing it would poison every
# US$ conversion on the site until the next scan. AUD/USD has spent recent
# decades roughly between 0.48 (2001) and 1.10 (2011); the band is deliberately
# wider than any plausible print, so it only ever rejects garbage.
FX_AUDUSD_SANITY_MIN = 0.4
FX_AUDUSD_SANITY_MAX = 1.2

# ---------------------------------------------------------------------------
# Scan pipeline thresholds (run.py) — moved from inline literals 2026-07-29
# ---------------------------------------------------------------------------
# Coverage below this prints a "!! LOW" marker on the scan log line. Reporting
# only — the publish decision stays "did we get ANYTHING at all".
SCAN_COVERAGE_LOW_PCT = 80
# ...unless the universe is tiny (curated lists, --limit runs), where a couple
# of misses swing the percentage and the marker would be noise.
SCAN_COVERAGE_MIN_UNIVERSE = 50

# Minimum average daily dollar-volume for a name to qualify as a sector-page
# "mover" (sectors.enrich) — per PAGE market key. Movers are trade candidates
# in the owner's eye, so illiquid names that spike on nothing are excluded.
SECTOR_MOVER_MIN_DVOL = {"asx": 1_000_000, "us": 10_000_000}
SECTOR_MOVER_MIN_DVOL_DEFAULT = 1_000_000

# ---------------------------------------------------------------------------
# Feeds — YouTube channels + AI narrative (feeds.py / feeds_run.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# MORNING PLAYS — the daily Discord digest of HIGH-CONVICTION VIVEK 5.0 setups
# (owner ask, 2026-09-08; scheduling reworked 2026-09-09). scripts/morning_plays
# reads the COMMITTED scan JSON (no scan, no Yahoo, no scan mutex) and posts to
# Discord. The name is historical -- ASX now goes out in the AFTERNOON.
#
# TWO MARKET-SPECIFIC SLOTS, each ~30 min after its market's close (owner,
# 2026-09-09): ASX at 16:30 Melbourne, NASDAQ + Crypto at 06:30 Melbourne.
# Crypto trades 24/7 but rides the US slot so both sides land in one message.
#
# DELAY-PROOF SCHEDULING (rebuilt 2026-09-10 after the first design missed a
# whole day). GitHub batches free-tier crons and delayed them 2-5 HOURS on
# 2026-09-09, so an hour-EQUALITY gate ("send only when it is exactly hour 16")
# no-op'd every delayed run and nothing was delivered. Instead: morning_plays.yml
# maps each cron to a slot NAME, and the run sends that slot when Melbourne is AT
# OR PAST the slot's target time today AND the slot has not already gone out today
# (a per-day marker in the sent-list cache). "at or past" tolerates any delay;
# the marker stops the slot's second DST superset cron -- and any repeat run in
# the window -- from double-sending. Net effect: each slot delivers exactly once
# per day, on the first run at/after its target, however late GitHub is.
#
# THE CHANNEL IS DELIBERATELY NEW, NOT A REVIVAL. Discord as an ALERT channel
# was ruled out 2026-08-27 ("get rid of the discord aspect, I will work on
# implementing something new in the future"), and tests/test_alert_credentials
# pins that the removed alert webhook (DISCORD_WEBHOOK_URL) never creeps back
# into a workflow or scanner/scripts. That pin's own docstring names the
# sanctioned path for the "something new": its OWN secret name. So this digest
# uses a SEPARATE secret and is a standalone content push, NOT routed through
# the severity/rate-limit alert router (a once-a-day digest is not an alert).
MORNING_PLAYS_WEBHOOK_ENV = "DISCORD_MORNING_WEBHOOK_URL"   # owner sets this secret
MORNING_PLAYS_TZ = "Australia/Melbourne"
# The named send slots. Each cron in morning_plays.yml maps to a slot NAME (not
# to a wall-clock hour), so GitHub delaying a cron by hours can no longer make it
# miss: the run sends its slot as long as Melbourne is AT OR PAST the slot's
# target time today and the slot has not already gone out today (a per-day marker
# in the sent-list). "at or past" (not "==") is the whole delay fix; the marker
# is what stops the slot's OTHER DST superset cron from double-sending. `minute`
# is only the intended send time shown in the message; the gate keys on `hour`.
MORNING_PLAYS_SLOTS = {
    "asx": {"hour": 16, "minute": 30, "markets": ("asx",)},           # FLOOR: never before 16:30 Melbourne
    "us":  {"hour": 6,  "minute": 30, "markets": ("nasdaq", "crypto")},  # FLOOR: never before 06:30 Melbourne
}
# THE POST-CLOSE DATA GATE (2026-09-11). The slot floor above is a wall-clock
# floor; this is the gate that actually decides. A slot sends only once the scan
# it reads was GENERATED at/after the gating market's most recent weekday session
# close -- the 2026-09-11 06:35 US digest ran on time and read a 1:43pm New York
# MID-SESSION scan (the post-close scan committed at 07:06 Melbourne), so it
# missed the three names that set up in the last hours of trade and posted
# "nothing new". Keyed on the payload's own `generated_at` in the market's own
# zone, so DST on either side is irrelevant. Before the gate passes the run is a
# silent no-op that MARKS NOTHING, so the next trigger attempt retries -- the
# cron-job.org jobs are a ladder of attempts every 30 min after the close, and
# the first post-close one sends (the per-day marker silences the rest).
#   asx    16:12 Sydney   -- the closing auction prints ~16:10-16:12; a 16:09 scan
#                            is pre-close. scan.yml's 05:07 UTC cron generates
#                            ~16:0x-16:28 AEST; its 06:37 UTC closing cron ~17:4x.
#   nasdaq 16:05 New York -- the bell is 16:00 and the closing cross is done by
#                            16:00:xx. NOT 16:15: scan.yml's LAST NASDAQ cron is
#                            21:07 UTC, which is 16:07 New York under EST, so a
#                            later gate would refuse every winter session's only
#                            post-close scan and the US digest would never send
#                            Nov-Mar. Under EDT the 20:07 UTC hourly (16:07 NY)
#                            passes too and the digest lands an hour earlier.
# crypto trades 24/7 and rides the US slot ungated. `market` is the payload the
# gate reads (`<market>_vivek.json`'s generated_at).
MORNING_PLAYS_SLOT_GATE = {
    "asx": {"market": "asx",    "tz": "Australia/Sydney", "hour": 16, "minute": 12},
    "us":  {"market": "nasdaq", "tz": "America/New_York", "hour": 16, "minute": 5},
}
# {Melbourne local HOUR -> markets} for the legacy hour-gate fallback used only
# by a bare local run (no --slot, no --force); the scheduled path uses --slot.
MORNING_PLAYS_SCHEDULE = {v["hour"]: v["markets"] for v in MORNING_PLAYS_SLOTS.values()}
# Every market any slot sends, in printed order, de-duplicated. Derived so the
# slots stay the single source of truth (a manual --force test sends this union;
# build_messages labels the empty case from the live slot's keys).
MORNING_PLAYS_MARKETS = tuple(dict.fromkeys(
    m for v in MORNING_PLAYS_SLOTS.values() for m in v["markets"]))
# Don't repeat a ticker the digest already SENT within this many days -- the
# reader charts each name, so a name should not be re-shared while its weekly
# setup persists (weekly setups stay valid for days/weeks, so without this the
# same names recur morning after morning). Counted from when it was SENT, not
# from when it went high-conviction: a name reappears once the gap passes, if
# still qualifying. State is a small actions/cache file (below) -- the same
# ephemeral cross-run pattern as the watchdog state -- so the JOB STAYS
# READ-ONLY to the repo. Only ACTUALLY-DELIVERED tickers are recorded, so a
# failed post never silently buries a name. 0 = no dedup (repeat freely).
MORNING_PLAYS_DEDUP_DAYS = 7
MORNING_PLAYS_SEEN_FILE = ".cache/morning_plays_sent.json"
MORNING_PLAYS_MAX_ROWS = 20        # per market, to stay inside Discord's limits
# False = LONG high-conviction plays only (a tight, focused list, ~7/day).
# True = ALSO every plain LONG A+ play (~100/day across ASX+NASDAQ) -- a much
# longer watchlist, chunked across several Discord posts. Shorts and
# funds/REITs (is_product) are excluded either way.
MORNING_PLAYS_INCLUDE_ALL_APLUS = False
MORNING_PLAYS_UA = "vivek5-morning/1.0"   # named UA — Discord 403s Python's default
# A stale scan (weekend / dropped cron) still sends, but says so: flag a market
# whose newest scan is older than this many hours.
MORNING_PLAYS_STALE_H = 20.0
# Absolute URL of the deployed app, for a "open the SCAN page" link in the
# digest. Empty = omit the link (a dead link is worse than none). The owner
# can set their Cloudflare Pages URL here.
MORNING_PLAYS_APP_URL = ""

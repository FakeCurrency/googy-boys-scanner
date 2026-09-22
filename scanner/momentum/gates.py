"""Quality gates, ranking, and the mode-C view -- all pure.

THE GATES EXIST FOR TWO REASONS (spec 5.6): so the shortlist is made of things
the owner can actually trade, and so that ONE BAD FRAME CANNOT FABRICATE A
SIGNAL. They run BEFORE the rules, on every symbol.

Everything here is a pure function of a frame plus config: no clock, no network,
no I/O, so it is replayable and the causality proof over it means something.
The one gate that needs a clock -- "is the last bar actually the latest close?"
-- lives in `run.py` instead, because measuring staleness requires knowing what
time it is, and an engine that reads the wall clock cannot be replayed.

WHY THE PRODUCT WORD LISTS ARE COPIED HERE RATHER THAN IMPORTED. Spec 5.6 says
to reuse `scan.py::_product_tag` and `config.PRODUCT_NAME_PATTERNS` rather than
rewrite them. The patterns ARE imported, from `scanner/config.py`. The fund word
lists are not, because they live in `scanner/broker/vivek_bot.py` and this lens
must not be able to reach the bot -- that fence is the whole basis of the
report-only claim. So they are declared in `config.py` beside the patterns, and
`tests/test_momentum_publish.py` reads `vivek_bot.py` AS SOURCE and fails if the
two sets diverge. Reading a file is not importing it, and a parity test catches
the drift that a copy would otherwise hide.

The MATCHER here uses word boundaries, deliberately unlike the bot's. The bot's
is substring, where `"ETF" in "NETFLIX"` is True -- a real bug the front end
fixed with `\\b` on 2026-08-13 while the bot's ringfenced copy kept it. This is
a display surface, so it takes the corrected discipline.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import config

__all__ = [
    "dollar_adv", "is_product", "gate_frame", "rank_rows", "directions_agree",
    "select",
]

# Compiled once. Word boundaries on the keywords, the measured patterns as
# given. `re.escape` on the keywords because "GLOBAL X" carries a space and one
# of them could acquire a regex metacharacter later.
_KEYWORD_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(k) for k in config.FUND_NAME_KEYWORDS),
    re.IGNORECASE)
_PATTERN_RES = tuple(re.compile(p, re.IGNORECASE) for p in config.PRODUCT_NAME_PATTERNS)


def dollar_adv(frame: pd.DataFrame, market: str = "",
               window: Optional[int] = None) -> Optional[float]:
    """Mean daily turnover over the last `window` bars, in the market's own
    currency. None when it cannot be computed.

    CRYPTO IS NOT `close * volume`, and getting that wrong is a ~10,000x error
    in the direction that lets everything through. Yahoo reports crypto
    "Volume" as USD dollar-volume ALREADY, so multiplying by the close prices
    dollars in dollars. `config.MARKETS[<key>].volume_is_usd` is the flag, and
    `scan.py::_liquidity` is the precedent this mirrors.

    Turnover is NOT converted to a single reporting currency, and the
    thresholds are per-market for that reason: an A$250,000 floor and a
    US$1,000,000 floor are different numbers because they are different
    currencies.
    """
    window = config.ADV_WINDOW if window is None else window
    if frame is None or len(frame) == 0:
        return None
    cols = {c.lower(): c for c in frame.columns}
    if "volume" not in cols:
        return None
    v = pd.to_numeric(frame[cols["volume"]], errors="coerce").to_numpy(dtype=float)
    mkt = config.MARKETS_META.get(market)
    if mkt is not None and getattr(mkt, "volume_is_usd", False):
        turn = v[-window:]
    else:
        if "close" not in cols:
            return None
        c = pd.to_numeric(frame[cols["close"]], errors="coerce").to_numpy(dtype=float)
        turn = c[-window:] * v[-window:]
    turn = turn[np.isfinite(turn)]
    if turn.size == 0:
        return None
    return float(turn.mean())


def is_product(name: Any, sector: Any = "") -> bool:
    """True for a non-operating listing: a fund, REIT, ETF, LIC, preferred line,
    warrant, rights line or note.

    FAILS OPEN to False, like the display flag it mirrors: a missed tag on a
    report row is a cosmetic miss, whereas a false positive hides a real stock
    from a human-review shortlist.
    """
    try:
        nm = str(name or "")
        sec = str(sector or "").strip().lower()
        if any(h in sec for h in config.FUND_SECTOR_HINTS):
            return True
        if sec in config.NON_OPERATING_SECTORS:
            return True          # ETFs / LICs carry no operating sector at all
        if _KEYWORD_RE.search(nm):
            return True
        return any(p.search(nm) for p in _PATTERN_RES)
    except Exception:
        return False


def gate_frame(frame: pd.DataFrame, market: str, *, cfg=None,
               name: Any = "", sector: Any = "") -> Optional[str]:
    """The pre-rule gates. Returns a SKIP REASON, or None to screen the symbol.

    A reason rather than a bool so the summary can say what the gates removed
    and in what proportion -- "1,146 skipped" with no breakdown is a number
    nobody can act on.
    """
    cfg = cfg or config.DEFAULTS
    if frame is None or len(frame) == 0:
        return "no bars"
    if len(frame) < cfg.min_bars:
        return "short history (%d < %d bars)" % (len(frame), cfg.min_bars)

    cols = {c.lower(): c for c in frame.columns}
    if "close" not in cols:
        return "no close column"
    close = pd.to_numeric(frame[cols["close"]], errors="coerce").to_numpy(dtype=float)
    finite = close[np.isfinite(close)]
    if finite.size == 0:
        return "all-NaN close column"
    last = float(finite[-1])
    if last <= 0:
        return "last close is not positive (%r)" % last

    floor = config.MIN_PRICE.get(market, 0.0)
    if floor and last < floor:
        # A sub-floor name moves one tick and prints a 50% candle, which makes
        # every indicator here noise rather than signal.
        return "price %.4f below the %s floor %.4f" % (last, market, floor)

    if config.EXCLUDE_PRODUCTS and is_product(name, sector):
        return "non-operating listing (fund / REIT / LIC / preferred / warrant)"

    # SUSPENDED-BUT-QUOTED, caught two ways. A flat series produces no pivots
    # under the strict rule, but it can still print a cross off stale EMAs, so
    # neither check is redundant.
    if "volume" in cols:
        vol = pd.to_numeric(frame[cols["volume"]], errors="coerce").to_numpy(dtype=float)
        tail = vol[-config.ZERO_VOLUME_BARS:]
        if tail.size == config.ZERO_VOLUME_BARS and np.all(np.nan_to_num(tail) == 0.0):
            return "no volume in the last %d bars (suspended?)" % config.ZERO_VOLUME_BARS
    rng = finite[-config.FLAT_RANGE_BARS:]
    if rng.size == config.FLAT_RANGE_BARS and float(rng.max() - rng.min()) == 0.0:
        return "no price range in the last %d bars (halted?)" % config.FLAT_RANGE_BARS

    adv_floor = config.MIN_DOLLAR_ADV.get(market, 0.0)
    if adv_floor:
        adv = dollar_adv(frame, market)
        if adv is None:
            return "turnover not computable"
        if adv < adv_floor:
            return "turnover %.0f below the %s floor %.0f" % (adv, market, adv_floor)
    return None


def directions_agree(row: Dict[str, Any]) -> bool:
    """Mode C's test: both rules fired AND their directions match.

    NOTE the edge, reproduced from the reference rather than smoothed over:
    `rule_a_direction` can be "both" (a bull and a bear divergence confirmed on
    the same bar) while `rule_b_direction` never can, because a crossover and a
    crossunder are mutually exclusive on one bar. So a "both" Rule A can never
    satisfy mode C. That is faithful, and it is flagged in the phase-0 note
    rather than quietly "fixed".
    """
    if not (row.get("rule_a") and row.get("rule_b")):
        return False
    return row.get("rule_a_direction") == row.get("rule_b_direction")


def rank_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Spec 5.7, six levels, descending priority:

        confluence (both rules agreeing) -> Rule A present -> smaller bars_ago
        -> higher |score| -> higher turnover -> symbol

    The owner reviews by eye, top down, so the first ten rows have to be the ten
    most worth opening. The alphabetical final tie-break is not cosmetic: without
    a total order a re-run on identical data can reorder, and then diffing
    yesterday's list against today's is impossible.
    """
    def key(r: Dict[str, Any]) -> Tuple:
        ages = [a for a in (r.get("rule_a_bars_ago"), r.get("rule_b_bars_ago"))
                if isinstance(a, (int, float))]
        age = min(ages) if ages else 10 ** 6
        score = r.get("rule_b_score") or 0
        adv = r.get("dollar_adv_20") or 0.0
        return (0 if directions_agree(r) else 1,
                0 if r.get("rule_a") else 1,
                age,
                -abs(score),
                -float(adv),
                str(r.get("symbol") or ""))
    out = sorted(rows, key=key)
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def select(rows: Sequence[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    """The rows this mode publishes as hits, ranked.

    Mode C is applied HERE and not in the engine, following the reference's own
    reasoning: "both rules, directions agreeing" is a VIEW of the same
    computation rather than a different screen. So the engine screens the union
    for B and C alike and this filters.
    """
    hits = [r for r in rows if r.get("ok") and r.get("passes")]
    if mode == "C":
        hits = [r for r in hits if directions_agree(r)]
    return rank_rows(hits)

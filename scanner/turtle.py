"""TURTLE — the fourth lens: the 1983 Dennis/Eckhardt breakout system.

Implemented from the ORIGINAL Turtle Trading Rules, not from the popular
short version. Two rules separate them, and both change results materially:

  1. THE SYSTEM 1 FILTER. A 20-day breakout is SKIPPED when the previous
     20-day breakout in that market would have been a winner. The rule is
     evaluated on every breakout the market printed, taken or skipped alike,
     so it needs a shadow replay running beside the real one. Without it,
     System 1 is a plain 20-day Donchian and takes every whipsaw in a range.
  2. THE FAILSAFE. Because a skipped System 1 entry could miss a real trend,
     the 55-day breakout is taken unconditionally. In this implementation
     that falls out of checking System 2 before System 1 rather than being
     special-cased.

Everything else is the system as specified: N is Wilder's 20-period ATR, the
stop is 2N from the most recent unit, units are added every 1/2 N to a
maximum of four, and the exit is the 10-day channel for System 1 and the
20-day channel for System 2 — the system that ENTERED owns the exit.

REPORT-ONLY. Nothing under scanner/broker/ may import this module; a test
fails the push if it ever does. This lens describes a published, 40-year-old
rule set and has no opinion about the live paper book.

The engine is a deterministic replay rather than a "does today look like a
breakout" test, for one reason: the System 1 filter is a function of the
market's own breakout history, so the only way to know whether today's 20-day
breakout is takeable is to have walked the history that precedes it. Having
paid for the walk, the replay also yields each name's own track record under
these rules, which is what the page ranks on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .indicators import atr

# Exit reasons, in the vocabulary the page renders.
STOP = "stop"          # 2N against the most recent unit
CHANNEL = "channel"    # the system's own exit channel (10-day / 20-day)
OPEN = "open"          # still held at the last bar


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------

def compute_n(df: pd.DataFrame, period: int | None = None) -> pd.Series:
    """N — the Turtles' volatility unit.

    The original rules give it as a recurrence, N = (19 * PDN + TR) / 20 over
    True Range = max(H-L, H-PDC, PDC-L). That is Wilder smoothing at period 20,
    which is exactly what indicators.atr() already computes, so this calls it
    rather than re-typing the recurrence — one true-range implementation in the
    repo, no room for two that disagree.

    One documented difference from the paper rules: they seed N with a simple
    mean of the first 20 true ranges, pandas seeds with the first value. The
    seed's weight decays by (19/20) per bar, so after the 250-bar minimum this
    lens requires it is below 1e-5 of the result and below any price tick.
    """
    return atr(df, period or config.TURTLE_N_PERIOD)


def channels(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Donchian entry and exit levels, SHIFTED by one bar.

    The shift is the whole correctness of this function. A 20-day high that
    includes today's own high can never be exceeded by today's own high, so an
    unshifted channel silently reports zero breakouts; a channel shifted the
    wrong way reports tomorrow's. Every level here answers "what was the
    extreme over the N bars BEFORE this one", which is the level a trader
    could have had on screen at the open.
    """
    high, low = df["High"], df["Low"]
    c = config
    return {
        "s1_hi": high.rolling(c.TURTLE_S1_ENTRY).max().shift(1),
        "s2_hi": high.rolling(c.TURTLE_S2_ENTRY).max().shift(1),
        "s1_lo": low.rolling(c.TURTLE_S1_ENTRY).min().shift(1),
        "s2_lo": low.rolling(c.TURTLE_S2_ENTRY).min().shift(1),
        "x1_lo": low.rolling(c.TURTLE_S1_EXIT).min().shift(1),
        "x1_hi": high.rolling(c.TURTLE_S1_EXIT).max().shift(1),
        "x2_lo": low.rolling(c.TURTLE_S2_EXIT).min().shift(1),
        "x2_hi": high.rolling(c.TURTLE_S2_EXIT).max().shift(1),
    }


# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------

def unit_size(equity: float, n: float, dollars_per_point: float = 1.0,
              risk_pct: float | None = None) -> float:
    """Unit = (risk_pct * equity) / (N * dollars_per_point).

    Returned unbrokered and unrounded — fractional units are meaningful for
    crypto and the caller decides how to round for shares. Returns 0.0 rather
    than raising on a non-positive or non-finite N, because an unpriceable
    name must drop out of the scan, never size to infinity.
    """
    risk_pct = config.TURTLE_RISK_PCT if risk_pct is None else risk_pct
    denom = n * dollars_per_point
    if not (np.isfinite(denom) and denom > 0) or not np.isfinite(equity):
        return 0.0
    return (risk_pct * equity) / denom


def drawdown_equity(equity: float, peak: float,
                    step_pct: float | None = None,
                    cut_pct: float | None = None) -> float:
    """The Turtles' drawdown rule, and it COMPOUNDS.

    Cut the equity you size from by cut_pct for every step_pct the account is
    below its peak. Two steps is 0.8 * 0.8 = 0.64 of the account, not 0.6 —
    reading it as additive is the common error and it under-cuts exactly when
    the rule is trying hardest to keep you alive.
    """
    step_pct = config.TURTLE_DRAWDOWN_STEP_PCT if step_pct is None else step_pct
    cut_pct = config.TURTLE_DRAWDOWN_CUT_PCT if cut_pct is None else cut_pct
    if not (peak > 0) or not np.isfinite(equity) or equity >= peak or step_pct <= 0:
        return max(equity, 0.0)
    dd_pct = 100.0 * (peak - equity) / peak
    steps = int(dd_pct // step_pct)
    return max(equity * ((1.0 - cut_pct / 100.0) ** steps), 0.0)


def pyramid_ladder(entry: float, n: float, direction: str = "long",
                   max_units: int | None = None,
                   step_n: float | None = None,
                   stop_n: float | None = None) -> list[dict]:
    """The add levels and the stop AFTER each add, for display.

    The second column is the one people get wrong: adding a unit does not
    leave the earlier units on their original stop. The whole position runs
    one stop, 2N below the MOST RECENT fill, so the fourth unit's entry drags
    the first unit's stop up by 1.5N from where it started. That is why a full
    four-unit position risks 1/2N + 1N + 1.5N + 2N = 5N -- 5% of the account
    at 1% per N -- against 8N if every unit kept the stop it was issued.
    (This said "about 2% and not 4%" until 2026-08-21. Both were wrong, and
    both are the plausible-looking wrong answers tests/test_turtle.py exists
    to catch -- which is exactly how a correct implementation gets "fixed"
    into a broken one by someone trusting a comment over the code.)
    """
    max_units = config.TURTLE_MAX_UNITS if max_units is None else max_units
    step_n = config.TURTLE_PYRAMID_STEP_N if step_n is None else step_n
    stop_n = config.TURTLE_STOP_N if stop_n is None else stop_n
    sign = 1.0 if direction == "long" else -1.0
    out = []
    for u in range(max_units):
        fill = entry + sign * step_n * n * u
        out.append({
            "unit": u + 1,
            "price": fill,
            "stop": fill - sign * stop_n * n,
            "add_at": None if u == 0 else fill,
        })
    return out


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------

def _finite(x) -> bool:
    try:
        return bool(np.isfinite(x))
    except (TypeError, ValueError):
        return False


class _Shadow:
    """The System 1 filter's memory.

    It takes EVERY 20-day breakout, in either direction, whether or not the
    real book took it — the rule is explicit that a skipped breakout still
    counts as "the last breakout". One unit, a 2N stop, the 10-day exit, and
    the only thing it publishes is whether the last resolved breakout was a
    winner.

    "Loser" means the 2N stop was hit, exactly as the rules define it, NOT
    "exited below entry". A breakout that drifts sideways and leaves at the
    10-day channel a few cents down is a WINNER for filter purposes and
    therefore BLOCKS the next System 1 entry. That reads wrong and is right;
    a test pins it so it does not get quietly "fixed".
    """

    __slots__ = ("active", "entry", "stop", "dir", "last_was_winner")

    def __init__(self):
        self.active = False
        self.entry = 0.0
        self.stop = 0.0
        self.dir = 0
        self.last_was_winner: bool | None = None

    def step(self, o, h, l, n_prev, s1_hi, s1_lo, x1_lo, x1_hi, allow_shorts):
        if self.active:
            if self.dir > 0:
                if _finite(self.stop) and l <= self.stop:
                    self.active, self.last_was_winner = False, False
                elif _finite(x1_lo) and l <= x1_lo:
                    self.active, self.last_was_winner = False, True
            else:
                if _finite(self.stop) and h >= self.stop:
                    self.active, self.last_was_winner = False, False
                elif _finite(x1_hi) and h >= x1_hi:
                    self.active, self.last_was_winner = False, True
        if self.active or not _finite(n_prev) or n_prev <= 0:
            return
        if _finite(s1_hi) and h > s1_hi:
            self.entry = max(s1_hi, o)
            self.stop = self.entry - config.TURTLE_STOP_N * n_prev
            self.dir, self.active = 1, True
        elif allow_shorts and _finite(s1_lo) and l < s1_lo:
            self.entry = min(s1_lo, o)
            self.stop = self.entry + config.TURTLE_STOP_N * n_prev
            self.dir, self.active = -1, True


def _book(pos: dict, exit_px: float, reason: str, i: int, dates: list) -> dict:
    """Turn an open position into a closed trade.

    One function, THREE call sites -- the ordinary exit, the entry bar's own
    stop, and the stop a pyramid add just raised into the same bar's low.
    Three hand-written copies of this arithmetic is how two of them quietly
    stop agreeing.

    R is per unit of the ORIGINAL 2N risk: the denominator the sizing was done
    against, so R and dollars stay proportional however many units the
    position ended up holding. `cost_r` is charged separately (see
    config.TURTLE_COST_BPS) and `r` is NET of it, with `gross_r` kept beside
    it -- a backtest that quotes only the gross quotes a number nobody could
    have earned.
    """
    stop_n = config.TURTLE_STOP_N
    sign = 1.0 if pos["side"] == "long" else -1.0
    n_pos = pos["n"]
    avg = pos["cost"] / pos["units"]
    denom = stop_n * n_pos
    gross_r = pos["units"] * sign * (exit_px - avg) / denom if denom > 0 else 0.0
    bps = config.TURTLE_COST_BPS / 10_000.0
    cost_r = pos["units"] * bps * (abs(avg) + abs(exit_px)) / denom if denom > 0 else 0.0
    return {
        "side": pos["side"], "system": pos["system"],
        "entry_date": pos["entry_date"], "exit_date": dates[i],
        "entry": round(avg, 8), "exit": round(float(exit_px), 8),
        "units": pos["units"], "n": round(n_pos, 8),
        "reason": reason,
        "r": round(gross_r - cost_r, 4),
        "gross_r": round(gross_r, 4),
        "cost_r": round(cost_r, 4),
        "bars": i - pos["entry_i"],
        "mfe_r": round(pos["mfe"], 4), "mae_r": round(pos["mae"], 4),
    }


def replay(df: pd.DataFrame, *, allow_shorts: bool | None = None) -> dict | None:
    """Walk the frame bar by bar under the full rule set.

    Returns the closed trades, the open position if any, the filter state, and
    the levels that would trigger on the next bar. None when the frame is too
    short for the filter to have any history to read.

    Ordering inside a bar, stated because a daily bar cannot tell you the
    order things happened in it: exits are checked BEFORE adds. A bar that
    both makes a new high (an add) and breaks the exit channel is booked as
    an exit. That is the conservative reading and it can only ever make the
    recorded result worse than the real one, never better.

    Fills are honest about gaps: an entry fills at max(level, open) for a long
    (you cannot buy below the open) and the stop fills at min(stop, open). A
    frame that gaps through its stop books the gap, not the stop.
    """
    if df is None or len(df) < config.TURTLE_MIN_BARS:
        return None
    for col in ("Open", "High", "Low", "Close"):
        if col not in df.columns:
            return None

    allow_shorts = config.TURTLE_ALLOW_SHORTS if allow_shorts is None else allow_shorts

    ch = channels(df)
    n_ser = compute_n(df)
    o = df["Open"].to_numpy(dtype="float64")
    h = df["High"].to_numpy(dtype="float64")
    lo = df["Low"].to_numpy(dtype="float64")
    cl = df["Close"].to_numpy(dtype="float64")
    nn = n_ser.to_numpy(dtype="float64")
    s1_hi = ch["s1_hi"].to_numpy(dtype="float64")
    s2_hi = ch["s2_hi"].to_numpy(dtype="float64")
    s1_lo = ch["s1_lo"].to_numpy(dtype="float64")
    s2_lo = ch["s2_lo"].to_numpy(dtype="float64")
    x1_lo = ch["x1_lo"].to_numpy(dtype="float64")
    x1_hi = ch["x1_hi"].to_numpy(dtype="float64")
    x2_lo = ch["x2_lo"].to_numpy(dtype="float64")
    x2_hi = ch["x2_hi"].to_numpy(dtype="float64")
    dates = [str(d)[:10] for d in (df["Date"] if "Date" in df.columns else df.index)]

    stop_n = config.TURTLE_STOP_N
    step_n = config.TURTLE_PYRAMID_STEP_N
    max_units = config.TURTLE_MAX_UNITS

    shadow = _Shadow()
    trades: list[dict] = []
    pos: dict | None = None
    start = max(config.TURTLE_S2_ENTRY, config.TURTLE_N_PERIOD) + 1
    signal_today = ""
    added_today = 0

    for i in range(start, len(df)):
        n_prev = nn[i - 1]
        last_bar = (i == len(df) - 1)
        if last_bar:
            added_today = 0

        # ---- the filter's shadow, always, independent of the real book ----
        shadow.step(o[i], h[i], lo[i], n_prev, s1_hi[i], s1_lo[i],
                    x1_lo[i], x1_hi[i], allow_shorts)

        if pos is None:
            if not (_finite(n_prev) and n_prev > 0):
                continue
            # System 2 is tested FIRST, and that is the failsafe: a System 1
            # entry blocked by the filter is picked up here at 55 days rather
            # than being missed for the whole trend.
            side = sysno = None
            fill = 0.0
            if _finite(s2_hi[i]) and h[i] > s2_hi[i]:
                side, sysno, fill = "long", 2, max(s2_hi[i], o[i])
            elif shadow.last_was_winner is not True and _finite(s1_hi[i]) and h[i] > s1_hi[i]:
                side, sysno, fill = "long", 1, max(s1_hi[i], o[i])
            elif allow_shorts and _finite(s2_lo[i]) and lo[i] < s2_lo[i]:
                side, sysno, fill = "short", 2, min(s2_lo[i], o[i])
            elif (allow_shorts and shadow.last_was_winner is not True
                  and _finite(s1_lo[i]) and lo[i] < s1_lo[i]):
                side, sysno, fill = "short", 1, min(s1_lo[i], o[i])
            if side is None:
                continue
            sign = 1.0 if side == "long" else -1.0
            pos = {
                "side": side, "system": sysno, "n": float(n_prev),
                "entry": float(fill), "last_fill": float(fill),
                "units": 1, "cost": float(fill),
                "stop": float(fill - sign * stop_n * n_prev),
                "entry_date": dates[i], "entry_i": i,
                "mfe": 0.0, "mae": 0.0,
            }
            if last_bar:
                signal_today = f"s{sysno}_{side}"
            # THE ENTRY BAR CAN ALSO TAKE YOU OUT, and until 2026-08-21 this
            # never checked -- a bar that broke out at 101.20 and then traded
            # to 95.00 against a 97.20 stop booked NO trade at all, so the
            # replay simply did not see the loss. A daily bar cannot say
            # whether the low came before or after the breakout tick; booking
            # the stop is the conservative reading, and the direction of the
            # error matters: it can only ever make the record WORSE, never
            # flatter it.
            if ((side == "long" and lo[i] <= pos["stop"])
                    or (side == "short" and h[i] >= pos["stop"])):
                px = (min(pos["stop"], o[i]) if side == "long"
                      else max(pos["stop"], o[i]))
                trades.append(_book(pos, float(px), STOP, i, dates))
                pos = None
            continue

        sign = 1.0 if pos["side"] == "long" else -1.0
        n_pos = pos["n"]
        x_lo = x1_lo[i] if pos["system"] == 1 else x2_lo[i]
        x_hi = x1_hi[i] if pos["system"] == 1 else x2_hi[i]

        # ---- excursions, for the honesty columns the journal already uses --
        if pos["side"] == "long":
            pos["mfe"] = max(pos["mfe"], (h[i] - pos["entry"]) / (stop_n * n_pos))
            pos["mae"] = min(pos["mae"], (lo[i] - pos["entry"]) / (stop_n * n_pos))
        else:
            pos["mfe"] = max(pos["mfe"], (pos["entry"] - lo[i]) / (stop_n * n_pos))
            pos["mae"] = min(pos["mae"], (pos["entry"] - h[i]) / (stop_n * n_pos))

        # ---- exits first (see the docstring on intrabar ordering) ----------
        exit_px = reason = None
        if pos["side"] == "long":
            if lo[i] <= pos["stop"]:
                exit_px, reason = min(pos["stop"], o[i]), STOP
            elif _finite(x_lo) and lo[i] <= x_lo:
                exit_px, reason = min(x_lo, o[i]), CHANNEL
        else:
            if h[i] >= pos["stop"]:
                exit_px, reason = max(pos["stop"], o[i]), STOP
            elif _finite(x_hi) and h[i] >= x_hi:
                exit_px, reason = max(x_hi, o[i]), CHANNEL

        if exit_px is not None:
            trades.append(_book(pos, float(exit_px), reason, i, dates))
            pos = None
            continue

        # ---- adds -------------------------------------------------------
        while pos["units"] < max_units:
            level = pos["last_fill"] + sign * step_n * n_pos
            if pos["side"] == "long":
                if h[i] < level:
                    break
                fill = max(level, o[i])
            else:
                if lo[i] > level:
                    break
                fill = min(level, o[i])
            pos["last_fill"] = float(fill)
            pos["cost"] += float(fill)
            pos["units"] += 1
            pos["stop"] = float(fill - sign * stop_n * n_pos)
            if last_bar:
                added_today += 1

        # An add walks the stop UP under the whole position, and until
        # 2026-08-21 the bar that did the adding was never re-tested against
        # the stop it had just created. A bar that added at 102.20 (raising
        # the stop to 100.20) and then traded to 99.50 recorded nothing.
        # Same conservative reading as the entry bar, same direction of error.
        if pos is not None and pos["units"] > 1:
            if ((pos["side"] == "long" and lo[i] <= pos["stop"])
                    or (pos["side"] == "short" and h[i] >= pos["stop"])):
                px = (min(pos["stop"], o[i]) if pos["side"] == "long"
                      else max(pos["stop"], o[i]))
                trades.append(_book(pos, float(px), STOP, i, dates))
                pos = None

    # ---- what the next bar can do -------------------------------------
    i = len(df) - 1
    n_now = float(nn[i]) if _finite(nn[i]) else float("nan")
    out = {
        "bars": len(df),
        "close": float(cl[i]),
        "date": dates[i],
        "n": n_now,
        "trades": trades,
        "s1_blocked": shadow.last_was_winner is True,
        "s1_filter_known": shadow.last_was_winner is not None,
        "signal": signal_today,
        "added_today": added_today,
    }

    if pos is None:
        out["state"] = "flat"
        out["position"] = None
        # Tomorrow's triggers are today's channels INCLUDING today's bar —
        # the rolling window rolls forward one, so the level a flat name
        # breaks tomorrow is max(High) over the last S1/S2 bars up to today.
        hi = df["High"]
        low = df["Low"]
        out["triggers"] = {
            "s1_long": float(hi.iloc[-config.TURTLE_S1_ENTRY:].max()),
            "s2_long": float(hi.iloc[-config.TURTLE_S2_ENTRY:].max()),
            "s1_short": float(low.iloc[-config.TURTLE_S1_ENTRY:].min()),
            "s2_short": float(low.iloc[-config.TURTLE_S2_ENTRY:].min()),
        }
    else:
        avg = pos["cost"] / pos["units"]
        sign = 1.0 if pos["side"] == "long" else -1.0
        out["state"] = pos["side"]
        out["triggers"] = None
        exit_now = (float(df["Low"].iloc[-(config.TURTLE_S1_EXIT if pos["system"] == 1
                                           else config.TURTLE_S2_EXIT):].min())
                    if pos["side"] == "long" else
                    float(df["High"].iloc[-(config.TURTLE_S1_EXIT if pos["system"] == 1
                                            else config.TURTLE_S2_EXIT):].max()))
        out["position"] = {
            "side": pos["side"], "system": pos["system"],
            "entry": round(pos["entry"], 8), "avg": round(avg, 8),
            "units": pos["units"], "n": round(pos["n"], 8),
            "stop": round(pos["stop"], 8),
            "next_add": (None if pos["units"] >= max_units else
                         round(pos["last_fill"] + sign * step_n * pos["n"], 8)),
            "exit_level": round(exit_now, 8),
            "exit_channel": (config.TURTLE_S1_EXIT if pos["system"] == 1
                             else config.TURTLE_S2_EXIT),
            "entry_date": pos["entry_date"],
            "bars": i - pos["entry_i"],
            "open_r": round(pos["units"] * sign * (cl[i] - avg)
                            / (config.TURTLE_STOP_N * pos["n"]), 4),
            "mfe_r": round(pos["mfe"], 4), "mae_r": round(pos["mae"], 4),
        }

    out["record"] = summarize(trades)
    out["record"]["equity_curve_r"] = _curve(trades)
    return out


def _curve(trades: list[dict]) -> list[float]:
    """Cumulative R after each closed trade — the input to max drawdown."""
    total, out = 0.0, []
    for t in trades:
        total += float(t.get("r", 0.0) or 0.0)
        out.append(round(total, 4))
    return out


def summarize(trades: list[dict]) -> dict:
    """Per-name track record under these rules.

    Everything is in R, deliberately. A dollar column would have to pick an
    account size and a currency, and the same set of trades would then read
    as two different records depending on which — the lesson the live book
    paid for on 2026-07-28. R divides by the position's own initial risk, so
    it survives any sizing decision made later.
    """
    n = len(trades)
    if not n:
        return {"n": 0, "wins": 0, "win_pct": None, "total_r": 0.0,
                "avg_r": None, "max_dd_r": 0.0, "by_system": {},
                "by_reason": {}, "expectancy_r": None}
    rs = [float(t.get("r", 0.0) or 0.0) for t in trades]
    wins = sum(1 for r in rs if r > 0)
    curve, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        curve += r
        peak = max(peak, curve)
        dd = min(dd, curve - peak)
    by_system: dict[str, dict] = {}
    for s in (1, 2):
        sel = [t["r"] for t in trades if t.get("system") == s]
        if sel:
            by_system[str(s)] = {"n": len(sel), "total_r": round(sum(sel), 3),
                                 "avg_r": round(sum(sel) / len(sel), 4),
                                 "win_pct": round(100.0 * sum(1 for r in sel if r > 0) / len(sel), 1)}
    by_reason: dict[str, dict] = {}
    for reason in (STOP, CHANNEL):
        sel = [float(t["r"]) for t in trades if t.get("reason") == reason]
        if sel:
            by_reason[reason] = {"n": len(sel), "total_r": round(sum(sel), 3),
                                 "avg_r": round(sum(sel) / len(sel), 4)}
    # THE MEAN IS NOT THE STORY IN A TREND SYSTEM, and publishing only the mean
    # is how a fat tail gets read as an edge. A handful of enormous winners pay
    # for everything, so the MEDIAN trade and the share of the total carried by
    # the top ten are published beside the average -- if the median is deeply
    # negative and ten trades hold most of the profit, the average is a
    # statement about those ten names and not about the rules.
    srt = sorted(rs)
    mid = len(srt) // 2
    median_r = srt[mid] if len(srt) % 2 else 0.5 * (srt[mid - 1] + srt[mid])
    top = sorted(rs, reverse=True)[:10]
    total = sum(rs)
    gross = sum(t.get("gross_r", t.get("r", 0.0)) or 0.0 for t in trades)
    cost = sum(t.get("cost_r", 0.0) or 0.0 for t in trades)
    return {
        "n": n, "wins": wins, "win_pct": round(100.0 * wins / n, 1),
        "total_r": round(total, 3), "avg_r": round(total / n, 4),
        "median_r": round(median_r, 4),
        "gross_r": round(gross, 3), "cost_r": round(cost, 3),
        # share of the total carried by the ten best trades; None when the
        # total is not positive, because a "share of a loss" is not a number
        # anyone can read.
        "top10_share": (round(sum(top) / total, 3) if total > 0 else None),
        "max_dd_r": round(dd, 3),
        "expectancy_r": round(total / n, 4),
        "by_system": by_system, "by_reason": by_reason,
    }


# ---------------------------------------------------------------------------
# the published row
# ---------------------------------------------------------------------------

def liquidity(df: pd.DataFrame, market: str) -> tuple[float, bool]:
    """(average daily dollar volume, passes the market's floors).

    A Donchian breakout on a name that trades twelve thousand dollars a day is
    a real breakout and an unfillable one. Listing it without a gate would be
    lying by omission, so the gate is applied and the count of what it removed
    is published beside the rows.
    """
    close = df["Close"]
    px = float(close.iloc[-1])
    floor_px = config.TURTLE_MIN_PRICE.get(market, 0.0)
    if "Volume" not in df.columns:
        return 0.0, False
    look = config.TURTLE_DVOL_LOOKBACK
    dvol_ser = (close * df["Volume"]).iloc[-look:]
    dvol = float(dvol_ser.mean()) if len(dvol_ser) else 0.0
    if not np.isfinite(dvol):
        dvol = 0.0
    floor_dv = config.TURTLE_MIN_DVOL.get(market, 0.0)
    return dvol, bool(np.isfinite(px) and px >= floor_px and dvol >= floor_dv)


def build_row(symbol: str, info: dict, df: pd.DataFrame, market: str,
              equity: float | None = None) -> dict | None:
    """One published row: state, the exact numbers to act on, and the record."""
    rep = replay(df)
    if rep is None:
        return None
    dvol, liquid = liquidity(df, market)
    if not liquid:
        return None
    n = rep["n"]
    if not (np.isfinite(n) and n > 0):
        return None
    price = rep["close"]
    equity = config.TURTLE_ACCOUNT_EQUITY if equity is None else equity
    shares = unit_size(equity, n)

    row = {
        "symbol": symbol,
        "name": info.get("name", symbol),
        "sector": info.get("sector", ""),
        "price": round(price, 8),
        "n": round(n, 8),
        "n_pct": round(100.0 * n / price, 2) if price > 0 else None,
        "dvol": round(dvol, 0),
        "state": rep["state"],
        "signal": rep["signal"],
        "added_today": rep["added_today"],
        "s1_blocked": rep["s1_blocked"],
        "s1_filter_known": rep["s1_filter_known"],
        "bars": rep["bars"],
        "date": rep["date"],
        # sizing at the published equity — the browser recomputes these the
        # moment you type your own account size, so they are a starting point
        # and not a claim about anybody's book.
        "unit_shares": round(shares, 6),
        "unit_notional": round(shares * price, 2),
        "unit_risk": round(config.TURTLE_RISK_PCT * equity, 2),
        "record": rep["record"],
        "position": rep["position"],
        "triggers": rep["triggers"],
    }

    # Proximity: how far the nearest actionable level is, as a percentage.
    # For a flat name that is the nearest untaken breakout; for a held one it
    # is the distance to the stop, which is the number that matters when you
    # already own it.
    if rep["state"] == "flat" and rep["triggers"]:
        cands = []
        t = rep["triggers"]
        for key, lvl in (("s2_long", t["s2_long"]), ("s1_long", t["s1_long"])):
            if key == "s1_long" and rep["s1_blocked"]:
                continue
            if np.isfinite(lvl) and lvl > 0:
                cands.append((100.0 * (lvl - price) / price, key, lvl))
        if config.TURTLE_ALLOW_SHORTS:
            for key, lvl in (("s2_short", t["s2_short"]), ("s1_short", t["s1_short"])):
                if key == "s1_short" and rep["s1_blocked"]:
                    continue
                if np.isfinite(lvl) and lvl > 0:
                    cands.append((100.0 * (price - lvl) / price, key, lvl))
        cands = [c for c in cands if np.isfinite(c[0])]
        if cands:
            dist, key, lvl = min(cands, key=lambda c: abs(c[0]))
            row["nearest"] = {"key": key, "level": round(float(lvl), 8),
                              "distance_pct": round(float(dist), 2)}
            row["approaching"] = bool(0 <= dist <= config.TURTLE_APPROACH_PCT)
        else:
            row["nearest"], row["approaching"] = None, False
    else:
        row["nearest"], row["approaching"] = None, False
        p = rep["position"]
        if p:
            row["stop_distance_pct"] = (round(100.0 * abs(price - p["stop"]) / price, 2)
                                        if price > 0 else None)
    return row


def rank_key(row: dict) -> tuple:
    """Ranking, in the order the page reads.

    A signal that fired today outranks everything — that is the scanner's
    reason to exist. Then held positions (you have money in them), then names
    approaching a level, then the rest by liquidity. Track record deliberately
    does NOT rank: a name with a flattering replay is not more actionable
    today than one without, and letting it sort would quietly turn the page
    into a curve-fit leaderboard.
    """
    fired = 0 if row.get("signal") else 1
    held = 0 if row.get("state") in ("long", "short") else 1
    near = row.get("nearest") or {}
    dist = abs(near.get("distance_pct", 999.0)) if near else 999.0
    return (fired, held, dist, -(row.get("dvol") or 0.0))

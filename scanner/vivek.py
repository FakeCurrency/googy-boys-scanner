"""VIVEK engine — 5.0Trading.Bull-style setups built around the 200 SMA.

5.0's edge, distilled into mechanical rules:
  * The 200 SMA on the higher timeframes (Weekly, H4) is THE level. Trades are
    reactions at it — a bounce off it as support, a rejection at it as
    resistance, or a break-and-retest.
  * Direction follows the reaction: long when price holds the 200 SMA from above,
    short when it's rejected from below.
  * Every trade defines Entry, SL and TP1/TP2/TP3 up front, with structured
    scale-outs and an SL that only ever moves in the trade's favour.

Data note: the daily scan pipeline gives daily bars. We compute a true Weekly
200 SMA (resampled from a long daily history) and use the Daily 200 SMA as the
"higher-timeframe-below-weekly" proxy for 5.0's H4 level. A real H4 200 SMA needs
intraday infrastructure and is a future upgrade (see ROADMAP); the rules and
grading below are written so that swap is a drop-in.

Grading: A+ (clear Weekly/H4 200 SMA reaction + strong structure) · A (good
interaction + solid structure) · B+ (some relevance, weaker structure) · WATCH
(near the level but missing a clean reaction or structure).
"""

import numpy as np
import pandas as pd

from . import config
from .grading import grade_from_points
from .indicators import atr as calc_atr, pivot_highs, pivot_lows, sma


def _weekly_sma200(df: pd.DataFrame) -> tuple[float | None, int]:
    """Weekly 200 SMA from a daily frame (resampled W-FRI). Returns (value, n_weeks)."""
    try:
        wk = df["Close"].resample("W-FRI").last().dropna()
    except Exception:
        return None, 0
    n = len(wk)
    if n < config.VIVEK_MIN_WEEKLY_BARS:
        return None, n
    window = min(config.VIVEK_SMA, n)         # use full 200 when available, else best effort
    return float(sma(wk, window).iloc[-1]), n


def _structure(df: pd.DataFrame, direction: str) -> float:
    """0..1 structure score: are recent swings stacking in the trade's favour?

    Long wants higher lows (and ideally higher highs); short wants lower highs.
    """
    pw = config.VIVEK_PIVOT_WINDOW
    lows = pivot_lows(df, pw).dropna().tail(3).tolist()
    highs = pivot_highs(df, pw).dropna().tail(3).tolist()
    score = 0.0
    if direction == "long":
        if len(lows) >= 2 and lows[-1] > lows[0]:
            score += 0.6
        if len(highs) >= 2 and highs[-1] >= highs[0]:
            score += 0.4
    else:
        if len(highs) >= 2 and highs[-1] < highs[0]:
            score += 0.6
        if len(lows) >= 2 and lows[-1] <= lows[0]:
            score += 0.4
    return round(score, 2)


def evaluate(df: pd.DataFrame) -> dict | None:
    """Find a 200 SMA reaction. Returns a signal dict or None if no setup."""
    if df is None or len(df) < config.VIVEK_MIN_HISTORY:
        return None

    close = df["Close"]
    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    daily_sma = float(sma(close, config.VIVEK_SMA).iloc[-1])      # H4 proxy
    weekly_sma, n_weeks = _weekly_sma200(df)
    if not np.isfinite(daily_sma) or daily_sma <= 0:
        return None

    atr = float(calc_atr(df, 14).iloc[-1])
    pw = config.VIVEK_PIVOT_WINDOW
    recent = df.tail(max(2 * pw + 1, 12))
    swing_low = float(recent["Low"].min())
    swing_high = float(recent["High"].max())

    # 3-Day 200 SMA (2026-07-02, the XMR gap): a name can sit exactly AT the
    # 3D-200 while being far from both the Weekly and Daily 200s — previously
    # invisible. Same epoch-anchored resample the 3-Day plan/chart uses.
    sma_3d = None
    if getattr(config, "VIVEK_INCLUDE_3D_LEVEL", False):
        d3 = _resample_3day_ohlc(df)
        if d3 is not None and len(d3) >= config.VIVEK_SMA:
            v = float(sma(d3["Close"], config.VIVEK_SMA).iloc[-1])
            if np.isfinite(v) and v > 0:
                sma_3d = v

    # Evaluate each higher-timeframe 200 SMA level; keep the strongest "in play".
    levels = []
    if weekly_sma:
        levels.append(("weekly", weekly_sma))
    if sma_3d:
        levels.append(("3d", sma_3d))
    levels.append(("h4", daily_sma))   # Daily-200 proxy for the H4 200 SMA

    best = None
    for tf, lvl in levels:
        dist = (price - lvl) / price                  # >0: price above the level
        adist = abs(dist)
        if adist > config.VIVEK_NEAR_TOL:
            continue                                  # not in play
        at_level = adist <= config.VIVEK_AT_LEVEL_TOL

        # Direction + reaction type from how price is sitting relative to the level.
        if price >= lvl:
            direction = "long"                        # holding the level as support
            touched = swing_low <= lvl * (1 + config.VIVEK_AT_LEVEL_TOL)
            reaction = "bounce" if (touched and price > swing_low) else "hold"
        else:
            direction = "short"                       # rejected by the level as resistance
            touched = swing_high >= lvl * (1 - config.VIVEK_AT_LEVEL_TOL)
            reaction = "reject" if (touched and price < swing_high) else "fade"

        struct = _structure(df, direction)
        cand = {
            "tf": tf, "level": lvl, "dist_pct": round(dist * 100, 2),
            "at_level": at_level, "direction": direction, "reaction": reaction,
            "structure": struct,
        }
        # Rank: weekly beats 3d beats h4; then "at level"; then reaction
        # quality; then structure.
        cand["_rank"] = (
            {"weekly": 2, "3d": 1.5}.get(tf, 1)
            + (2 if at_level else 0)
            + (2 if reaction in ("bounce", "reject") else 0)
            + struct
        )
        if best is None or cand["_rank"] > best["_rank"]:
            best = cand

    if best is None:
        return None

    # Confluence bonus: both the Weekly AND Daily 200 SMA near price together.
    confluence = bool(weekly_sma) and abs((daily_sma - weekly_sma) / price) <= config.VIVEK_NEAR_TOL

    return {
        "close": price,
        "weekly_sma200": round(weekly_sma, 8) if weekly_sma else None,
        "daily_sma200": round(daily_sma, 8),
        "weekly_bars": n_weeks,
        "atr": round(atr, 8),
        "swing_low": round(swing_low, 8),
        "swing_high": round(swing_high, 8),
        "level_tf": best["tf"],
        "level": round(best["level"], 8),
        "dist_pct": best["dist_pct"],
        "at_level": best["at_level"],
        "direction": best["direction"],
        "reaction": best["reaction"],
        "structure": best["structure"],
        "confluence": confluence,
        "uptrend": best["direction"] == "long",   # for frontend filters that read `uptrend`
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    """Score out of VIVEK_SCORE_MAX, then map to A+/A/B+/WATCH."""
    pts = 0
    fired: list[str] = []

    # 1) Which 200 SMA is in play (the heart of the setup).
    if sig["level_tf"] == "weekly":
        pts += 4
        fired.append("WEEKLY 200 SMA")
    elif sig["level_tf"] == "3d":
        pts += 3
        fired.append("3D 200 SMA")
    else:
        pts += 3
        fired.append("H4 200 SMA")

    # 2) Right at the level vs merely near it (near-only adds nothing — that's
    #    what separates a WATCH from a tradeable grade).
    if sig["at_level"]:
        pts += 2
        fired.append("AT THE LEVEL")

    # 3) Reaction quality — a clean bounce/reject is what makes it actionable.
    if sig["reaction"] in ("bounce", "reject"):
        pts += 2
        fired.append("CLEAN REACTION")

    # 4) Structure stacking in the trade's favour.
    if sig["structure"] >= 0.8:
        pts += 2
        fired.append("STRONG STRUCTURE")
    elif sig["structure"] >= 0.5:
        pts += 1
        fired.append("OK STRUCTURE")

    # 5) Weekly + H4 confluence.
    if sig.get("confluence"):
        pts += 1
        fired.append("W+H4 CONFLUENCE")

    pts = min(pts, config.VIVEK_SCORE_MAX)
    grade = grade_from_points(pts, config.VIVEK_GRADE_CUTOFFS)
    return pts, grade, fired


def _structural_targets(df: pd.DataFrame, direction: str, entry: float, risk: float) -> list[float]:
    """Up to three REAL targets from prior structure, ordered away from entry.

    Longs aim at prior resistance (pivot highs above entry); shorts at prior
    support (pivot lows below entry). Targets must sit between MIN_R and MAX_R
    of risk away, and clustered pivots are merged so the three TPs are distinct.
    Returns [] when there's no usable structure (caller falls back to R-multiples).

    The `risk` guard is `not (risk > 0)` for the same reason `_build_levels`'s is
    (TOP100 #63) — but here it is DEPTH ONLY, and saying so matters more than the
    line: the sole production caller already refuses a non-positive risk before it
    gets here, so nothing reaches this with NaN today. It is written this way so
    the helper stays correct if it ever acquires a second caller, not because a
    path exists. Note the fallback would be worse than the bug it guards: []
    means "no structure, use R-multiples", and R-multiples off a NaN risk are NaN
    targets rather than no plan.
    """
    if not (risk > 0):
        return []
    pw = config.VIVEK_PIVOT_WINDOW
    look = df.tail(config.VIVEK_TARGET_LOOKBACK)
    lo = entry + config.VIVEK_TP_MIN_R * risk
    hi = entry + config.VIVEK_TP_MAX_R * risk
    if direction == "long":
        piv = pivot_highs(look, pw).dropna().tolist()
        cands = sorted(p for p in piv if lo <= p <= hi)
    else:
        lo = entry - config.VIVEK_TP_MAX_R * risk
        hi = entry - config.VIVEK_TP_MIN_R * risk
        piv = pivot_lows(look, pw).dropna().tolist()
        cands = sorted((p for p in piv if lo <= p <= hi), reverse=True)

    picked: list[float] = []
    for p in cands:
        if all(abs(p - q) >= config.VIVEK_TP_CLUSTER_R * risk for q in picked):
            picked.append(float(p))
        if len(picked) == 3:
            break
    return picked


def _build_levels(df: pd.DataFrame, direction: str, entry: float, level: float,
                  swing_low: float, swing_high: float, atr: float) -> dict:
    """The shared SL + TP1/TP2/TP3 construction, given a known entry.

    TPs land on real prior structure where it exists; any remaining slots fall
    back to R-multiples placed strictly beyond the last target so ordering holds.
    R:R is measured to the ACTUAL TP2, so it genuinely varies between setups.
    Returns {} (caller treats as "no plan") when the stop gives non-positive risk.

    TOP100 #63 — "non-positive" now means "not positive", which is not the same
    test and is the whole item. ``risk <= 0`` is False for NaN, so a plan whose
    risk was Not-a-Number was BUILT and published. NaN gets in easily: ``atr``
    is ``max(atr, entry * 0.001)`` and Python's ``max`` propagates NaN (it keeps
    the first argument because ``x > nan`` is False), and ``swing_low`` is a
    rolling min that is NaN over an all-missing window.

    What a NaN-risk plan then does downstream is the reason this is worth the
    token: every gate that should catch it is written as a ``>`` or a ``<``, and
    every one of those is False against NaN, so it passes all of them. ``rr``
    is NaN so ``gate_grade``'s R:R floor does not bite; the bot's ``wide_stop``
    and ``stop_too_tight`` tests both read ``stop_pct = NaN`` and both pass;
    ``size_position``'s ``stop_dist <= 0`` guard passes and books
    ``risk_usd = units * NaN = NaN``. That NaN then lands in the book, and a
    NaN inside a sum makes every later comparison False — which **disarms the
    daily and weekly loss guards for the entire book**, silently, off one bad
    ATR bar. A corrupt row does not merely mis-price itself; it turns off the
    thing that limits the damage.

    Writing it as ``not (risk > 0)`` rather than adding an ``isfinite`` call is
    deliberate: the positive test is the property the caller actually needs, and
    it cannot be satisfied by NaN, by None-turned-nan, or by anything else that
    is not a real positive number. **This can only ever REMOVE a plan, never add
    one** — the docstring above has always promised no plan unless risk is
    positive, so this is the contract being enforced rather than tightened. It
    is still a change to which plans exist and is flagged as such (TOP100 #63);
    reverting is one token.
    """
    atr = max(atr, entry * 0.001)
    buf = atr * config.VIVEK_ATR_STOP_MULT

    if direction == "long":
        stop = min(swing_low, level) - buf
        risk = entry - stop
        scale = config.VIVEK_TP_SCALE_LONG
        sign = 1
    else:
        stop = max(swing_high, level) + buf
        risk = stop - entry
        scale = config.VIVEK_TP_SCALE_SHORT
        sign = -1

    if not (risk > 0):          # TOP100 #63 — NaN fails this; `risk <= 0` did not.
        return {}

    struct = _structural_targets(df, direction, entry, risk)
    tps: list[float] = []
    basis: list[str] = []
    for i in range(3):
        if i < len(struct):
            tps.append(struct[i])
            basis.append("structural")
            continue
        # Fallback R-multiple, forced strictly beyond the previous TP.
        cand = entry + sign * risk * config.VIVEK_TP_R[i]
        if tps:
            min_next = tps[-1] + sign * risk * 0.5
            cand = max(cand, min_next) if direction == "long" else min(cand, min_next)
        tps.append(cand)
        basis.append("measured")

    # A short's price can't go below zero, so a far R-multiple fallback must not
    # imply a negative target. Floor short TPs at a small fraction of entry while
    # keeping them strictly descending.
    if direction == "short":
        floor = entry * config.VIVEK_SHORT_TP_FLOOR
        eps = entry * 0.001
        tps = [max(tps[i], floor + (2 - i) * eps) for i in range(3)]

    rr = round(abs(tps[1] - entry) / risk, 2)   # headline R:R to the ACTUAL TP2

    def rnd(v):
        return round(float(v), 8)

    return {
        "entry": rnd(entry),
        "stop": rnd(stop),
        "tp1": rnd(tps[0]), "tp2": rnd(tps[1]), "tp3": rnd(tps[2]),
        "risk": rnd(risk),
        "rr": rr,
        "direction": direction,
        "scale": scale,                      # fraction booked at TP1/TP2/TP3
        "target": rnd(tps[1]),               # generic field for shared row code
        "trail": rnd(entry),                 # SL→BE after TP1 (5.0 rule)
        "tp_basis": basis,                   # per-TP: "structural" vs "measured"
        "target_basis": basis[1],            # how the headline target was set
        "structural_tps": sum(1 for b in basis if b == "structural"),
    }


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    """Entry (= last close), SL, TP1/TP2/TP3 for a signal. Kept for callers/tests
    that want the detection-price plan; the live scan uses build_tf_plan (which
    sets the entry from the fired trigger instead)."""
    lv = _build_levels(df, sig["direction"], sig["close"], sig["level"],
                       sig["swing_low"], sig["swing_high"], sig["atr"])
    return lv or {"rr": 0}


def _resample_weekly_ohlc(df: pd.DataFrame) -> pd.DataFrame | None:
    """Daily OHLCV -> a true Weekly (W-FRI) OHLCV frame, for the Weekly plan."""
    try:
        wk = pd.DataFrame({
            "Open":   df["Open"].resample("W-FRI").first(),
            "High":   df["High"].resample("W-FRI").max(),
            "Low":    df["Low"].resample("W-FRI").min(),
            "Close":  df["Close"].resample("W-FRI").last(),
            "Volume": df["Volume"].resample("W-FRI").sum(),
        }).dropna()
        return wk if len(wk) else None
    except Exception:
        return None


def _resample_3day_ohlc(df: pd.DataFrame) -> pd.DataFrame | None:
    """Daily OHLCV -> a 3-Day OHLCV frame for the 3-Day plan.

    Bins are EPOCH-anchored 3-calendar-day buckets so they're identical to the
    chart's bucketBars(daily, 3·86400) — the plan, the 3-Day candles and the
    markers therefore line up exactly (same as the Weekly plan aligning with the
    chart's W-FRI resample)."""
    try:
        # "72h" (a tick-like freq) so origin="epoch" actually takes effect — a
        # plain "3D" silently ignores the origin and anchors to the data start.
        d3 = pd.DataFrame({
            "Open":   df["Open"].resample("72h", origin="epoch").first(),
            "High":   df["High"].resample("72h", origin="epoch").max(),
            "Low":    df["Low"].resample("72h", origin="epoch").min(),
            "Close":  df["Close"].resample("72h", origin="epoch").last(),
            "Volume": df["Volume"].resample("72h", origin="epoch").sum(),
        }).dropna()
        return d3 if len(d3) else None
    except Exception:
        return None


def detect_trigger(frame: pd.DataFrame, direction: str, level: float) -> dict | None:
    """Has a mechanical entry trigger fired on the LAST bar of `frame`?

    Three triggers, checked in VIVEK_TRIGGER_PRIORITY order (first match wins):
      * reclaim — price pierced the 200 SMA within the lookback and the last bar
        closed back through it (a bounce reclaim / rejection close-through).
      * retest  — the last bar tagged the level and closed back the right side of
        it on calm (<= average) volume — a retest that held.
      * break   — the last bar closed beyond the most recent minor swing pivot
        with >= BREAK_VOL_MULT x average volume — a break of small structure.

    Returns {type, entry, bar} (bar = integer index of the trigger bar) or None
    when the setup is merely WATCHING. `entry` is the trigger price, NOT just the
    close — a retest enters at the level, a break enters at the broken pivot.
    """
    n = len(frame)
    if n < 3:
        return None
    high = frame["High"].to_numpy(dtype=float)
    low = frame["Low"].to_numpy(dtype=float)
    close = frame["Close"].to_numpy(dtype=float)
    vol = frame["Volume"].to_numpy(dtype=float)
    last = n - 1
    lc = close[last]
    is_long = direction == "long"
    k = min(config.VIVEK_TRIGGER_LOOKBACK, n - 1)
    avg_vol = float(np.nanmean(vol[-20:])) if n >= 5 else float(np.nanmean(vol) or 0.0)
    at_tol = level * config.VIVEK_AT_LEVEL_TOL

    candidates: dict[str, dict] = {}

    # reclaim — pierced the level recently and the last bar is the FIRST close
    # back through it. Without the first-close condition a single touch kept
    # the setup "armed reclaim" for ~6 consecutive daily scans, with the entry
    # drifting to each new close (up to ~4% off the true trigger) — the bot
    # then bought the most whipsaw-prone bar, not the reclaim itself. Strictly
    # causal: uses only completed bars (last and last-1).
    if is_long:
        pierced = any(low[i] <= level for i in range(last - k, last + 1))
        if pierced and lc > level and close[last - 1] <= level:
            candidates["reclaim"] = {"type": "reclaim", "entry": float(lc), "bar": last}
    else:
        pierced = any(high[i] >= level for i in range(last - k, last + 1))
        if pierced and lc < level and close[last - 1] >= level:
            candidates["reclaim"] = {"type": "reclaim", "entry": float(lc), "bar": last}

    # retest — last bar tagged the level and held, on calm volume. Enter at the level.
    if is_long:
        held = low[last] <= level + at_tol and lc > level
    else:
        held = high[last] >= level - at_tol and lc < level
    if held and avg_vol > 0 and vol[last] <= avg_vol * config.VIVEK_RETEST_VOL_MULT:
        candidates["retest"] = {"type": "retest", "entry": float(level), "bar": last}

    # break — last bar closed beyond the most recent minor pivot with volume.
    piv = (pivot_highs if is_long else pivot_lows)(frame, config.VIVEK_PIVOT_WINDOW).dropna()
    if len(piv):
        brk = float(piv.iloc[-1])
        broke = (lc > brk) if is_long else (lc < brk)
        if broke and avg_vol > 0 and vol[last] >= avg_vol * config.VIVEK_BREAK_VOL_MULT:
            candidates["break"] = {"type": "break", "entry": brk, "bar": last}

    for name in config.VIVEK_TRIGGER_PRIORITY:
        if name in candidates:
            return candidates[name]
    return None


def _recent_reaction_bar(frame: pd.DataFrame, direction: str, level: float) -> int | None:
    """Index of the most recent bar that reacted AT the level (within AT_LEVEL_TOL)."""
    n = len(frame)
    low = frame["Low"].to_numpy(dtype=float)
    high = frame["High"].to_numpy(dtype=float)
    for i in range(n - 1, max(-1, n - 60) - 1, -1):
        near = (abs(low[i] - level) / level <= config.VIVEK_AT_LEVEL_TOL) if direction == "long" \
            else (abs(high[i] - level) / level <= config.VIVEK_AT_LEVEL_TOL)
        if near:
            return i
    return None


def build_tf_plan(frame: pd.DataFrame, direction: str) -> dict | None:
    """A full timeframe plan for `frame`: the 200 SMA level, structural SL/TPs,
    and the trigger state — all from ONE place (Python), so the row, chart and
    bot read identical numbers. Returns None when the frame is too short.

    TOP100 #72 — the level is NOT always a 200 SMA, and now it says so.
    ``w = min(VIVEK_SMA, n)`` with ``VIVEK_MIN_TF_BARS = 30`` means a plan can be
    built on a **30**-period average and published into a field the row, the
    chart and the bot all read as "the 200 SMA". Weekly is where this actually
    bites: five years of daily bars is only ~260 weeks, so a name listed three
    years ago resamples to ~156 and its "weekly 200 SMA" is a 3-year average.
    Two names side by side on the same page, same label, different indicator.

    ``sma_window`` has carried the real number since the beginning and NOTHING
    read it — grepped across ``.py``, ``.js`` and ``.html``, it appeared at this
    line and nowhere else. So the fix is to SURFACE it, not to delete an unused
    field: ``sma_proxy`` is the boolean a badge or a filter can act on, and it
    is derived here rather than recomputed by each reader against its own copy
    of 200.

    Deliberately NOT a gate. Refusing short-history plans would change which
    trades get taken, and the shorter average is often the honest best effort —
    a two-year-old listing has no 200-week history and never will until it ages.
    The defect was never the fallback; it was the fallback being silent.
    """
    n = len(frame)
    if n < config.VIVEK_MIN_TF_BARS:
        return None
    close = frame["Close"]
    w = min(config.VIVEK_SMA, n)
    level = float(sma(close, w).iloc[-1])
    if not np.isfinite(level) or level <= 0:
        return None
    atr = float(calc_atr(frame, 14).iloc[-1])
    pw = config.VIVEK_PIVOT_WINDOW
    recent = frame.tail(max(2 * pw + 1, 12))
    swing_low = float(recent["Low"].min())
    swing_high = float(recent["High"].max())

    trigger = detect_trigger(frame, direction, level)
    entry = trigger["entry"] if trigger else float(close.iloc[-1])
    lv = _build_levels(frame, direction, entry, level, swing_low, swing_high, atr)
    if not lv:
        return None

    def _date(i):
        try:
            return frame.index[i].strftime("%Y-%m-%d")
        except Exception:
            return None

    react_i = _recent_reaction_bar(frame, direction, level)
    return {
        **lv,
        "level": round(level, 8),
        "swing_high": round(swing_high, 8),
        "swing_low": round(swing_low, 8),
        "sma_window": w,                                  # < 200 on short histories
        "sma_proxy": bool(w < config.VIVEK_SMA),           # TOP100 #72 — say so
        "armed": trigger is not None,
        "entry_trigger": trigger["type"] if trigger else None,
        "trigger_bar": _date(trigger["bar"]) if trigger else None,
        "reaction_bar": _date(react_i) if react_i is not None else None,
        "bars": n,
    }


def build_plans(df: pd.DataFrame, sig: dict) -> dict:
    """Per-timeframe plans for a signal's direction. The Daily plan is the row/bot
    headline; the 3-Day and Weekly plans each get their OWN 200-SMA reaction so
    the chart's 3D and W toggles surface real setups (not a Daily reference)."""
    direction = sig["direction"]
    plans: dict[str, dict] = {}
    p1d = build_tf_plan(df, direction)
    if p1d:
        plans["1D"] = p1d
    d3 = _resample_3day_ohlc(df)
    if d3 is not None:
        p3d = build_tf_plan(d3, direction)
        if p3d:
            plans["3D"] = p3d
    wk = _resample_weekly_ohlc(df)
    if wk is not None:
        p1w = build_tf_plan(wk, direction)
        if p1w:
            plans["1W"] = p1w
    return plans


def build_markers(plans: dict) -> dict:
    """Chart markers per timeframe, derived from the plans so the chart no longer
    computes its own. At most two per TF (the reaction at the level + the trigger
    bar) — deliberately minimal to keep the chart readable."""
    out: dict[str, list] = {}
    for tf, p in plans.items():
        ms = []
        if p.get("reaction_bar"):
            ms.append({"date": p["reaction_bar"], "kind": "reaction"})
        if p.get("trigger_bar"):
            ms.append({"date": p["trigger_bar"], "kind": "trigger", "label": p.get("entry_trigger")})
        out[tf] = ms
    return out


def gate_grade(grade: str | None, sig: dict, rr: float, armed: bool = True) -> tuple[str | None, list[str]]:
    """Apply 5.0's hard requirements the raw structural score can't see.

    A tradeable grade (A+/A) needs BOTH a fired trigger (ARMED — not price merely
    sitting near the SMA) AND enough room to TP2. Otherwise the setup is demoted
    to B+ (WATCHING) with a chip explaining why. This keeps the A+/A list short
    and genuinely actionable.
    """
    if grade not in ("A+", "A"):
        return grade, []
    notes: list[str] = []
    if not armed:
        grade = "B+"
        notes.append("WATCHING (no trigger)")
    if rr < config.VIVEK_MIN_TRADEABLE_RR:
        grade = "B+"
        notes.append(f"LOW R:R ({rr:.1f})")
    return grade, notes


def apply_grade_hysteresis(score: int, raw_grade: str | None, prev_grade: str | None,
                           cutoffs: list | None = None, margin: int | None = None,
                           prev_dir: str | None = None, cur_dir: str | None = None,
                           held_runs: int = 0,
                           max_runs: int | None = None) -> tuple[str | None, int]:
    """Hold a setup's PREVIOUS (higher) grade across scans unless its score has
    clearly dropped — i.e. more than `margin` points below that grade's cutoff.

    This only smooths SCORE-boundary wobble (the A+↔A flip-flop from tiny
    scan-to-scan data differences); it is applied BEFORE gate_grade, so a genuine
    state change (un-armed, or R:R falling below the minimum) still demotes the
    setup. Promotions are never held back. A no-op when there's no prior grade.

    Two hard bounds (2026-07 — the ratchet fix):
      * A hold never survives a LONG<->SHORT direction flip: the previous badge
        described the OPPOSITE trade.
      * A hold may renew at most `max_runs` consecutive scans. prev_grade comes
        from the published (already-held) output, so an unbounded hold let a
        7-scorer stay A+ forever — silently lowering the bot's A+ bar.

    Returns (grade, held_runs) — persist held_runs on the row and feed it back.
    """
    cutoffs = config.VIVEK_GRADE_CUTOFFS if cutoffs is None else cutoffs
    margin = config.VIVEK_GRADE_HYSTERESIS if margin is None else margin
    max_runs = (getattr(config, "VIVEK_GRADE_HYSTERESIS_MAX_RUNS", 3)
                if max_runs is None else max_runs)
    if not prev_grade or prev_grade == raw_grade or margin <= 0:
        return raw_grade, 0
    if prev_dir and cur_dir and prev_dir != cur_dir:
        return raw_grade, 0                      # flipped sides — fresh grade
    rank = {g: i for i, (g, _) in enumerate(cutoffs)}   # A+ = 0 (best)
    cut = dict(cutoffs)
    if prev_grade not in rank or raw_grade not in rank:
        return raw_grade, 0
    # Only a demotion (raw is a worse tier than prev) is eligible to be held,
    # only while the score is within `margin` of the previous grade's cutoff,
    # and only for max_runs consecutive scans.
    if (rank[raw_grade] > rank[prev_grade] and score >= cut[prev_grade] - margin
            and held_runs < max_runs):
        return prev_grade, held_runs + 1
    return raw_grade, 0


# Entry-type categories — how price is interacting with the 200 SMA. Used by the
# dashboard's filter chips so the user can sort setups by the trade trigger and
# read overall market behaviour around the level. A setup can match more than one.
ENTRY_TYPES = ["reclaim", "retest", "break"]
ENTRY_TYPE_LABELS = {
    "reclaim": "Close back above 200 SMA after rejection",
    "retest":  "Retest with confirmation",
    "break":   "Break of small structure near 200 SMA",
}


def entry_types(sig: dict) -> list[str]:
    """Classify a 200-SMA interaction into one or more entry types (heuristic).

    * reclaim — a clean reaction at the level: price was pushed to the 200 SMA and
      closed back through it (bounce off support / rejection at resistance).
    * retest  — price is sitting right AT the level and holding, with confirming
      structure (a retest that held).
    * break   — recent swings are stacking strongly in the trade's direction near
      the level (a break of small structure / momentum entry).
    """
    react = sig.get("reaction")
    at = bool(sig.get("at_level"))
    struct = sig.get("structure", 0) or 0
    types: list[str] = []
    if react in ("bounce", "reject"):
        types.append("reclaim")
    if at and struct >= 0.5:
        types.append("retest")
    if struct >= 0.8:
        types.append("break")
    if not types:                      # every setup is near the level — default to retest
        types.append("retest")
    return types


def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
    """Detail payload for the VIVEK ticker view."""
    return {
        "setup_type": "vivek",
        "level_tf": sig["level_tf"],
        "level": sig["level"],
        "weekly_sma200": sig["weekly_sma200"],
        "daily_sma200": sig["daily_sma200"],
        "dist_pct": sig["dist_pct"],
        "at_level": sig["at_level"],
        "reaction": sig["reaction"],
        "structure": sig["structure"],
        "confluence": sig["confluence"],
        "weekly_bars": sig["weekly_bars"],
        "atr": sig["atr"],
        "entry": lv.get("entry"), "stop": lv.get("stop"),
        "tp1": lv.get("tp1"), "tp2": lv.get("tp2"), "tp3": lv.get("tp3"),
        "scale": lv.get("scale"),
        "risk": lv.get("risk"),
        "tp_basis": lv.get("tp_basis"),
        "structural_tps": lv.get("structural_tps"),
        "rr": lv.get("rr"),
    }


def narrative(symbol: str, sig: dict, lv: dict, detail: dict, currency_symbol: str = "$") -> str:
    """Plain-English explanation of the setup and why it earned its grade."""
    cur = currency_symbol
    tf = {"weekly": "Weekly", "3d": "3-Day"}.get(sig["level_tf"], "H4 (daily proxy)")
    side = "long" if sig["direction"] == "long" else "short"
    react = {
        "bounce": "bouncing off", "hold": "holding above",
        "reject": "being rejected at", "fade": "fading below",
    }.get(sig["reaction"], "reacting at")
    conf = " with Weekly+H4 200 SMA confluence" if sig["confluence"] else ""
    struct = ("a clean structure" if sig["structure"] >= 0.8
              else "a workable structure" if sig["structure"] >= 0.5
              else "thin structure")
    sc = lv.get("scale") or []
    sc_txt = " / ".join(f"{int(round(x*100))}%" for x in sc) if sc else "—"
    n_struct = lv.get("structural_tps") or 0
    where = "prior resistance" if side == "long" else "prior support"
    tgt_txt = (f"targets set at {where} ({n_struct}/3 from real structure)"
               if n_struct else "targets set by R-multiples (no clear structure nearby)")
    return (
        f"{symbol} is {react} the {tf} 200 SMA ({cur}{sig['level']:.4f}), "
        f"{abs(sig['dist_pct']):.1f}% away{conf}, with {struct}. "
        f"A {side} reaction setup: enter {cur}{lv['entry']:.4f}, stop {cur}{lv['stop']:.4f} "
        f"(beyond the reaction); {tgt_txt}. Scale {sc_txt} into TP1 {cur}{lv['tp1']:.4f} / "
        f"TP2 {cur}{lv['tp2']:.4f} / TP3 {cur}{lv['tp3']:.4f}; move SL to break-even at TP1, "
        f"then below new support at TP2. {lv['rr']:.1f}R to TP2."
    )

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

    # Evaluate each higher-timeframe 200 SMA level; keep the strongest "in play".
    levels = []
    if weekly_sma:
        levels.append(("weekly", weekly_sma))
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
        # Rank: weekly beats h4; then "at level"; then reaction quality; then structure.
        cand["_rank"] = (
            (2 if tf == "weekly" else 1)
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
    """
    if risk <= 0:
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


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    """Entry, SL, TP1/TP2/TP3 (5.0 style) + R:R and per-TP scale-outs.

    TPs land on real prior structure where it exists; any remaining slots fall
    back to R-multiples placed strictly beyond the last target so ordering holds.
    R:R is measured to the ACTUAL TP2, so it genuinely varies between setups.
    """
    direction = sig["direction"]
    entry = sig["close"]
    atr = max(sig["atr"], entry * 0.001)
    buf = atr * config.VIVEK_ATR_STOP_MULT

    if direction == "long":
        stop = min(sig["swing_low"], sig["level"]) - buf
        risk = entry - stop
        scale = config.VIVEK_TP_SCALE_LONG
        sign = 1
    else:
        stop = max(sig["swing_high"], sig["level"]) + buf
        risk = stop - entry
        scale = config.VIVEK_TP_SCALE_SHORT
        sign = -1

    if risk <= 0:
        return {"rr": 0}

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


def gate_grade(grade: str | None, sig: dict, rr: float) -> tuple[str | None, list[str]]:
    """Apply 5.0's hard requirements that the raw structural score can't see.

    A tradeable grade (A+/A) needs BOTH a real reaction (a clean bounce/reject,
    not price merely sitting near the SMA) AND enough room to TP2. Otherwise the
    setup is demoted to B+ (watch-list) with a chip explaining why. This is what
    keeps the A+/A list short and trustworthy.
    """
    if grade not in ("A+", "A"):
        return grade, []
    notes: list[str] = []
    if sig.get("reaction") not in ("bounce", "reject"):
        grade = "B+"
        notes.append("NO CLEAN REACTION")
    if rr < config.VIVEK_MIN_TRADEABLE_RR:
        grade = "B+"
        notes.append(f"LOW R:R ({rr:.1f})")
    return grade, notes


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
    tf = "Weekly" if sig["level_tf"] == "weekly" else "H4 (daily proxy)"
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

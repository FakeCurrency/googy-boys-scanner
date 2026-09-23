"""VIVEK MOMENTUM -- the replay and its R model. PURE: bars in, trades out.

Answers the question the screen cannot: when a Rule A or Rule B signal fired
in the past, what did trading it EARN, in R, after costs?

NO LOOK-AHEAD, BY CONSTRUCTION. `screen.evaluate()` is the causal per-bar
frame the live screen reads its tail from (assert_no_lookahead proves it
against truncated inputs), so a signal at bar j here is exactly what the
screen would have listed at the close of bar j. The quality gates are applied
to the frame AS IT STOOD at bar j -- price floor, product exclusion, volume
and turnover as of that day -- not as they stand today.

THE SIGNALS ARE THE SCREEN'S, not a paraphrase of them:
  Rule A  bull_div / bear_div (RSI regular divergence off a strict pivot).
  Rule B  bull_signal / bear_signal AND score >= cfg.min_signal_score -- the
          same score gate `screen_symbol` applies; evaluate()'s raw column
          uses Pine's display threshold (1), which the screen does not list.
A bar where both directions of one rule fire is a CONFLICT and is not traded,
the way the page shows it rather than picking a side. The first `warn_bars`
of every series are skipped: before then the 200-EMA is still carrying its
seed and Rule B's score is capped (config.MomentumConfig.warn_bars).

THE TRADE is the owner's Pine "Auto trade box" (config BT_*): entry at the
signal close, stop at the 5-bar swing extreme padded by 0.25 ATR and capped at
15% of entry, targets at 1R/2R/3R -- then the 5.0 house ladder via the shared
R ledger (scanner/rmodel.py), so the R is the same currency as 5.0's. One
open trade per rule and direction per symbol; a signal that fires while that
stream's trade is still open is not a new trade.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from scanner import rmodel

from . import config, gates
from .config import MomentumConfig
from .screen import evaluate

__all__ = ["box", "signal_masks", "replay_symbol", "summarise"]

STREAMS: Tuple[Tuple[str, str], ...] = (("A", "long"), ("A", "short"), ("B", "long"), ("B", "short"))


def box(ev: pd.DataFrame, j: int, direction: str) -> Optional[Dict[str, Any]]:
    """The Auto trade box at bar j, exactly as chart.js momentumPlan draws it."""
    c = float(ev["close"].iat[j])
    lo_j = max(0, j - config.BT_SWING_BARS + 1)
    a = float(ev["atr"].iat[j])
    a = a if math.isfinite(a) else 0.0
    if direction == "long":
        raw = float(ev["low"].iloc[lo_j:j + 1].min()) - a * config.BT_ATR_PAD
        stop = max(raw, c - c * config.BT_MAX_STOP_PCT / 100.0)
    else:
        raw = float(ev["high"].iloc[lo_j:j + 1].max()) + a * config.BT_ATR_PAD
        stop = min(raw, c + c * config.BT_MAX_STOP_PCT / 100.0)
    risk = abs(c - stop)
    if not (math.isfinite(c) and math.isfinite(risk) and risk > 0):
        return None
    sign = 1.0 if direction == "long" else -1.0
    targets = [max(c + sign * risk * r, c * config.BT_TP_FLOOR) for r in config.BT_R_LADDER]
    return {"entry": c, "stop": stop, "raw_stop": raw, "capped": stop != raw, "targets": targets}


def signal_masks(ev: pd.DataFrame, cfg: MomentumConfig) -> Dict[Tuple[str, str], np.ndarray]:
    """{(rule, direction): bool per bar}, conflicts removed, warm-up excluded."""
    n = len(ev)
    a_bull = ev["bull_div"].to_numpy(dtype=bool)
    a_bear = ev["bear_div"].to_numpy(dtype=bool)
    b_bull = ev["bull_signal"].to_numpy(dtype=bool) & (ev["bull_score"].to_numpy() >= cfg.min_signal_score)
    b_bear = ev["bear_signal"].to_numpy(dtype=bool) & (ev["bear_score"].to_numpy() >= cfg.min_signal_score)
    live = np.arange(n) >= cfg.warn_bars
    return {
        ("A", "long"): a_bull & ~a_bear & live, ("A", "short"): a_bear & ~a_bull & live,
        ("B", "long"): b_bull & ~b_bear & live, ("B", "short"): b_bear & ~b_bull & live,
    }


def _reason_key(reason: str) -> str:
    """'price 0.0070 below the asx floor' -> 'price'; the words before the
    first number or bracket, so counts group by gate rather than by value."""
    m = re.match(r"[a-z][a-z\- ]*[a-z]", reason)
    return m.group(0) if m else reason


def _costs(market: str) -> Tuple[float, float]:
    slip = config.BT_SLIPPAGE_BPS.get(market, config.BT_SLIPPAGE_BPS.get("default", 0.0))
    comm = config.BT_COMMISSION_BPS.get(market, config.BT_COMMISSION_BPS.get("default", 0.0))
    bps = 10_000.0
    return slip / bps, comm / bps


def replay_symbol(frame: pd.DataFrame, market: str, *, symbol: str = "", name: Any = "",
                  sector: Any = "", cfg: Optional[MomentumConfig] = None
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Every trade the momentum lens would have produced on one symbol, and a
    count of the signals the gates removed (by reason)."""
    cfg = cfg or config.DEFAULTS
    ev = evaluate(frame, cfg)
    n = len(ev)
    if n <= cfg.warn_bars + 1:
        return [], {}
    cols = [k for k in ("open", "high", "low", "close", "volume") if k in ev.columns]
    o, h, l, c = (ev[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    days = [str(ix)[:10] for ix in ev.index]
    costs = _costs(market)
    trades: List[Dict[str, Any]] = []
    gated: Dict[str, int] = {}
    gate_memo: Dict[int, Optional[str]] = {}
    for (rule, direction), mask in signal_masks(ev, cfg).items():
        busy_until = -1
        for j in np.flatnonzero(mask):
            j = int(j)
            if j <= busy_until or j + 1 >= n:
                continue
            if j not in gate_memo:
                gate_memo[j] = gates.gate_frame(ev.iloc[:j + 1][cols], market, cfg=cfg,
                                                name=name, sector=sector)
            reason = gate_memo[j]
            if reason is not None:
                gated[_reason_key(reason)] = gated.get(_reason_key(reason), 0) + 1
                continue
            plan = box(ev, j, direction)
            if plan is None:
                continue
            if abs(plan["entry"] - plan["stop"]) / plan["entry"] * 100.0 < config.BT_MIN_STOP_PCT:
                gated["stop_too_tight"] = gated.get("stop_too_tight", 0) + 1
                continue
            def make_bars(j=j):
                return ((days[k], o[k], h[k], l[k], c[k]) for k in range(j + 1, n))
            tr, worst = rmodel.simulate_both(make_bars, direction, plan["entry"], plan["stop"],
                                             plan["targets"], config.BT_SCALE[direction],
                                             days[j], costs=costs)
            if tr is None:
                continue
            busy_until = j + tr["bars"]              # identical under both fills
            score = None
            if rule == "B":
                score = int(ev["bull_score" if direction == "long" else "bear_score"].iat[j])
            trades.append({
                "symbol": symbol, "market": market, "rule": rule, "direction": direction,
                "score": score, "signal_date": days[j], "entry": tr["entry"],
                "stop": round(plan["stop"], 8), "capped": bool(plan["capped"]),
                "risk": tr["risk"], "targets": [round(x, 8) for x in plan["targets"]],
                "exit_date": tr.get("exit_date"), "exit_reason": tr.get("exit_reason"),
                "closed_by": tr.get("closed_by"),
                "bars": tr["bars"], "gross_r": tr["gross_r"], "cost_r": tr["cost_r"],
                "realized_r": tr["realized_r"], "mae_r": tr.get("mae_r"), "mfe_r": tr.get("mfe_r"),
                # the same trade under the 5.0 backtest's worst-print stop fill
                "gross_r_worst": worst["gross_r"], "cost_r_worst": worst["cost_r"],
                "realized_r_worst": worst["realized_r"],
            })
    trades.sort(key=lambda t: (t["signal_date"], t["rule"], t["direction"]))
    return trades, gated


def summarise(trades: Sequence[Dict[str, Any]], notional: Optional[float] = None,
              fill: str = "house") -> Dict[str, Any]:
    """Headline + every rule x direction stream + exit mix, via rmodel.summarise.

    `fill="worst_print"` scores the SAME trades with the 5.0 backtest's stop
    fill (realized_r_worst) -- the second column of a like-for-like table."""
    if fill == "worst_print":
        trades = [dict(t, realized_r=t["realized_r_worst"]) for t in trades]
    elif fill != "house":
        raise ValueError("fill must be 'house' or 'worst_print'")

    def s(sub):
        return rmodel.summarise(list(sub), notional)
    out: Dict[str, Any] = {"all": s(trades)}
    for rule, direction in STREAMS:
        out[f"rule_{rule.lower()}_{direction}"] = s(t for t in trades
                                                    if t["rule"] == rule and t["direction"] == direction)
    for direction in ("long", "short"):
        out[direction] = s(t for t in trades if t["direction"] == direction)
    out["by_exit"] = {e: s(t for t in trades if t["exit_reason"] == e)
                      for e in sorted({t["exit_reason"] for t in trades if t.get("exit_reason")})}
    out["by_year"] = {y: s(t for t in trades if t["signal_date"][:4] == y)
                      for y in sorted({t["signal_date"][:4] for t in trades})}
    return out

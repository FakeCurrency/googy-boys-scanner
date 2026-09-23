"""PhaseMap's R model -- the harness's signals, scored in R. ENGINE-NATIVE.

Added 2026-09-23. The harness (harness.py) already replays the SetupEngine
with zero look-ahead and records what each setup's zones went on to do; this
turns that record into a trade and a number in R, so PhaseMap can be read in
the same currency as VIVEK 5.0 and the momentum lens.

NOTHING HERE DEFINES A LEVEL. Every price comes from a zone the engine already
builds and the spec already defines, and every exit is an engine EVENT:
  entry   the displacement bar's close (the signal bar)
  risk    entry to the INVALIDATION_HARD floor (bull: its low; bear: its high)
  exit    whichever happens first --
            "t1"          T1 consumed: a daily close through its far edge
            "stop"        DEAD: a daily close through the hard floor
            "engine_end"  the engine dropped the setup (stall expiry, a new
                          sweep replacing it) -- flat at that bar's close
            "eod"         none of the above before the data ended
All fills are closes, because every PhaseMap event is decided on a close
("wicks through are a test only"), so a loss can exceed 1R by exactly the gap
between the floor and the close that broke it. Costs are the house table,
both legs market fills, through the shared ledger (scanner/rmodel.py). A
floor closer than the house minimum stop is not a trade (the same number the
bot refuses on), so a sub-spread stop cannot manufacture a -20R row.

The spec is untouched: no detection maths, no zone, no RULESET_VERSION
parameter moves -- this reads the engine, it does not steer it.
"""

from __future__ import annotations

import math

from scanner import config as house
from scanner import rmodel


def costs_for(market: str) -> tuple:
    slip = house.VIVEK_SLIPPAGE_BPS.get(market, house.VIVEK_SLIPPAGE_BPS["default"])
    comm = house.VIVEK_COMMISSION_BPS.get(market, house.VIVEK_COMMISSION_BPS["default"])
    return slip / 10_000.0, comm / 10_000.0


def score(sig: dict, ind, market: str) -> dict:
    """R fields for one measured signal ({} when it is not a tradeable plan).

    `sig` needs the recorder's zone snapshot (`inv_low` / `inv_high`) and its
    event bars; `ind` is the Indicators the engine ran on.
    """
    i = sig["signal_index"]
    close = ind.close
    n = len(close)
    bull = sig["direction"] == "bullish"
    entry = float(close[i])
    stop = float(sig.get("inv_low" if bull else "inv_high", math.nan))
    risk = (entry - stop) if bull else (stop - entry)
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(risk) and risk > 0):
        return {"r_tradeable": False, "r_skip": "no hard floor on the right side"}
    if risk / entry * 100.0 < house.VIVEK_BOT_MIN_STOP_PCT:
        return {"r_tradeable": False, "r_skip": "stop_too_tight"}
    events = [(b, why) for b, why in ((sig.get("dead_bar"), "stop"),
                                       (sig.get("t1_consumed_bar"), "t1"),
                                       (sig.get("end_index"), "engine_end"))
              if b is not None and b > i]
    if events:
        b, why = min(events)
    elif n - 1 > i:
        b, why = n - 1, "eod"
    else:
        return {"r_tradeable": False, "r_skip": "signal on the last bar"}
    exit_px = float(close[b])
    tr = {"entry": entry, "risk": risk,
          "exits": [{"reason": why, "price": exit_px, "pct": 1.0}]}
    gross = rmodel.r_of(exit_px, entry, risk, bull)
    cost = rmodel.cost_r(tr, *costs_for(market))
    return {
        "r_tradeable": True, "r_entry": round(entry, 12), "r_stop": round(stop, 12),
        "r_risk": round(risk, 12), "r_exit_bar": b, "r_exit_date": ind.dates[b].isoformat(),
        "r_exit_reason": why, "r_bars": b - i, "r_gross": round(gross, 4),
        "r_cost": round(cost, 4), "realized_r": round(gross - cost, 4),
    }


def trades(signals: list) -> list:
    """The signals that became trades, as rows rmodel.summarise can read."""
    out = []
    for s in signals:
        if not s.get("r_tradeable"):
            continue
        out.append({"realized_r": s["realized_r"], "entry": s["r_entry"], "risk": s["r_risk"],
                    "exit_reason": s["r_exit_reason"], "closed_by": s["r_exit_reason"],
                    "tier": s["tier"], "direction": s["direction"],
                    "illiquid": s.get("illiquid"), "signal_date": s["signal_date"]})
    return out


def summary(signals: list, notional: float | None = None) -> dict:
    """Headline (long A+/A), every tier x direction, the exit mix, skips."""
    ts = trades(signals)

    def s(pred):
        return rmodel.summarise([t for t in ts if pred(t)], notional)

    graded = ("A+", "A")
    out = {
        "definition": ("entry = signal close; risk = entry to the INVALIDATION_HARD floor; "
                       "exit on the first engine event: T1 consumed (close), DEAD (close "
                       "through the floor), engine drops the setup (close) or end of data; "
                       "house costs, both legs market fills"),
        "long_graded": s(lambda t: t["direction"] == "bullish" and t["tier"] in graded),
        "short_graded": s(lambda t: t["direction"] == "bearish" and t["tier"] in graded),
        "all": s(lambda t: True),
        "by_tier": {f"{d}_{tier}": s(lambda t, d=d, tier=tier: t["direction"] == d and t["tier"] == tier)
                    for d in ("bullish", "bearish") for tier in ("A+", "A", "Watch")},
        "by_exit": {e: s(lambda t, e=e: t["exit_reason"] == e)
                    for e in ("t1", "stop", "engine_end", "eod")},
        "long_graded_liquid": s(lambda t: t["direction"] == "bullish" and t["tier"] in graded
                                and not t.get("illiquid")),
        "skipped": {},
    }
    for sig in signals:
        if not sig.get("r_tradeable", True) and sig.get("r_skip"):
            out["skipped"][sig["r_skip"]] = out["skipped"].get(sig["r_skip"], 0) + 1
    return out

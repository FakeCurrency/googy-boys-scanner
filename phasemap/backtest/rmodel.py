"""PhaseMap's R model -- the harness's signals, scored in R. ENGINE-NATIVE.

Added 2026-09-23. The harness (harness.py) already replays the SetupEngine
with zero look-ahead and records what each setup's zones went on to do; this
turns that record into a trade and a number in R, so PhaseMap can be read in
the same currency as VIVEK 5.0 and the momentum lens.

NOTHING HERE DEFINES A LEVEL. Every price comes from a zone the engine already
builds and the spec already defines, and every exit is an engine EVENT or the
floor the engine drew:
  entry   the displacement bar's close (the signal bar)
  risk    entry to the INVALIDATION_HARD floor (bull: its low; bear: its high)
  exit    whichever happens first --
            "stop"        the floor, as a RESTING stop -- the house fill rule
                          every lens is scored with (2026-09-24): filled at
                          the floor, or at the open of a bar that gapped
                          through it
            "t1"          T1 consumed: a daily close through its far edge
            "engine_end"  the engine dropped the setup (stall expiry, a new
                          sweep replacing it) -- flat at that bar's close
            "eod"         none of the above before the data ended
TWO MORE COLUMNS ride with every signal, so no reading is hidden:
  worst   the same exits, a stop filled at the bar's worst print (the 5.0
          backtest's fill) -- the like-for-like second column
  close   the engine-NATIVE reading: every exit at a close and the stop is
          DEAD (a close through the floor; "wicks through are a test only").
          This is how PhaseMap itself judges a setup, and it is reported as a
          reference because the house rule is stricter than the spec here.
Costs are the house table, both legs market fills, through the shared ledger
(scanner/rmodel.py). A floor closer than the house minimum stop is not a trade
(the same number the bot refuses on), so a sub-spread stop cannot manufacture
a -20R row.

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


def _exit(sig: dict, ind, entry: float, stop: float, bull: bool, fill: str):
    """(bar, reason, price) for one fill rule, or None when nothing follows.

    "close"  engine-native: every exit at a close; the stop is DEAD (a close
             through the floor), wicks through the floor are a test.
    "house"  the house rule (2026-09-24): the floor is a RESTING stop, filled
             at the floor or at the open of a bar that gapped through it; T1
             consumed and the engine dropping the setup still exit at that
             bar's close, because those are close-decided engine events.
    "worst"  as "house", but a stop fills at the bar's worst print (the 5.0
             backtest's convention) -- the second column.
    House and worst exit on the SAME bar; only the stop's price differs.
    """
    i = sig["signal_index"]
    n = len(ind.close)
    events = {b: why for b, why in ((sig.get("end_index"), "engine_end"),
                                     (sig.get("t1_consumed_bar"), "t1"),
                                     (sig.get("dead_bar"), "stop"))
              if b is not None and b > i}
    for j in range(i + 1, n):
        if fill != "close":
            lo, hi, op = float(ind.low[j]), float(ind.high[j]), float(ind.open[j])
            through = lo <= stop if bull else hi >= stop
            if through:
                if fill == "worst":
                    return j, "stop", lo if bull else hi
                gapped = op <= stop if bull else op >= stop
                return j, "stop", op if gapped else stop
            if events.get(j) == "stop":
                continue                                  # unreachable: a close through implies a wick through
        if j in events:
            return j, events[j], float(ind.close[j])
    if n - 1 > i:
        return n - 1, "eod", float(ind.close[n - 1])
    return None


def score(sig: dict, ind, market: str) -> dict:
    """R fields for one measured signal ({} when it is not a tradeable plan).

    `sig` needs the recorder's zone snapshot (`inv_low` / `inv_high`) and its
    event bars; `ind` is the Indicators the engine ran on. The headline R
    (`realized_r`) is the HOUSE fill; `realized_r_worst` is the same trade with
    the 5.0 worst-print stop fill; `realized_r_close` is the engine-native,
    close-only reading kept as a reference.
    """
    i = sig["signal_index"]
    bull = sig["direction"] == "bullish"
    entry = float(ind.close[i])
    stop = float(sig.get("inv_low" if bull else "inv_high", math.nan))
    risk = (entry - stop) if bull else (stop - entry)
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(risk) and risk > 0):
        return {"r_tradeable": False, "r_skip": "no hard floor on the right side"}
    if risk / entry * 100.0 < house.VIVEK_BOT_MIN_STOP_PCT:
        return {"r_tradeable": False, "r_skip": "stop_too_tight"}
    if len(ind.close) - 1 <= i:
        return {"r_tradeable": False, "r_skip": "signal on the last bar"}
    costs = costs_for(market)
    out = {"r_tradeable": True, "r_entry": round(entry, 12), "r_stop": round(stop, 12),
           "r_risk": round(risk, 12)}
    for fill, sfx in (("house", ""), ("worst", "_worst"), ("close", "_close")):
        b, why, px = _exit(sig, ind, entry, stop, bull, fill)
        tr = {"entry": entry, "risk": risk, "exits": [{"reason": why, "price": px, "pct": 1.0}]}
        gross = rmodel.r_of(px, entry, risk, bull)
        cost = rmodel.cost_r(tr, *costs)
        out.update({f"r_exit_bar{sfx}": b, f"r_exit_date{sfx}": ind.dates[b].isoformat(),
                    f"r_exit_reason{sfx}": why, f"r_bars{sfx}": b - i,
                    f"r_gross{sfx}": round(gross, 4), f"r_cost{sfx}": round(cost, 4),
                    f"realized_r{sfx}": round(gross - cost, 4)})
    return out


FILLS = {"house": "", "worst_print": "_worst", "engine_close": "_close"}


def trades(signals: list, fill: str = "house") -> list:
    """The signals that became trades, as rows rmodel.summarise can read."""
    sfx = FILLS[fill]
    out = []
    for s in signals:
        if not s.get("r_tradeable"):
            continue
        out.append({"realized_r": s[f"realized_r{sfx}"], "entry": s["r_entry"], "risk": s["r_risk"],
                    "exit_reason": s[f"r_exit_reason{sfx}"], "closed_by": s[f"r_exit_reason{sfx}"],
                    "tier": s["tier"], "direction": s["direction"],
                    "illiquid": s.get("illiquid"), "signal_date": s["signal_date"]})
    return out


def summary(signals: list, notional: float | None = None, fill: str = "house") -> dict:
    """Headline (long A+/A), every tier x direction, the exit mix, skips.
    `fill` picks the column: "house" (headline), "worst_print", "engine_close".
    The house summary also carries the other two columns' graded lines."""
    ts = trades(signals, fill)

    def s(pred):
        return rmodel.summarise([t for t in ts if pred(t)], notional)

    graded = ("A+", "A")
    out = {
        "fill": fill,
        "definition": ("entry = signal close; risk = entry to the INVALIDATION_HARD floor; "
                       "house fill: the floor is a resting stop (filled at the floor or a "
                       "gapped open); T1 consumed and the engine dropping the setup exit at "
                       "that close; end of data marks at the last close; house costs, both "
                       "legs market fills; second column: stops at the bar's worst print; "
                       "reference: engine-native close-only exits (DEAD = a close through "
                       "the floor)"),
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
    if fill == "house":
        for other in ("worst_print", "engine_close"):
            o = summary(signals, notional, other)
            out[other] = {k: o[k] for k in ("long_graded", "short_graded", "long_graded_liquid")}
    return out

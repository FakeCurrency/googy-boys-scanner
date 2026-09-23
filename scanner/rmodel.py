"""The R ledger: one trade, one bar at a time, in risk multiples. PURE.

Built 2026-09-23 so every lens can answer the same question the VIVEK 5.0
backtest answers -- "what did this signal EARN, in R, after costs?" -- with one
piece of arithmetic instead of one per lens. The 5.0 backtest itself is NOT
rewired onto this module (its evidence file is what the bot's rules were
tuned on); instead `tests/test_rmodel.py` drives both over the same random
paths and requires identical results, so the two cannot drift.

WHAT IT MODELS -- the 5.0 house management, generalised to N targets:
  * a bar is processed ADVERSE extreme first, then FAVOURABLE (pessimistic:
    a bar whose range spans the stop and a target is a stop);
  * target k books `scale[k]` of the position at the target LEVEL (a resting
    limit); after the first target the stop moves to break-even, after the
    second to the first target, and a stop only ever moves in the trade's
    favour;
  * whatever the scale leaves unbooked is a runner, closed by the stop, a
    time stop or the end of the data;
  * costs are an R drag: the entry and every non-limit exit pay slippage +
    commission, a target fill pays commission only (vivek_journal._cost_r).

TWO STOP FILLS, and the difference is not cosmetic:
  STOP_FILL_LEVEL  the stop fills AT the stop, or at the open when the bar
                   gapped through it. What a resting stop order gets.
  STOP_FILL_BAR    the stop fills at the bar's adverse EXTREME. This is what
                   the 5.0 backtest does (it marks the whole bar at its low),
                   kept so the parity test can prove everything else is the
                   same machinery. It is harsher than any real stop order.

IT IMPORTS NOTHING FROM THE REPO. The momentum lens is fenced off from the
bot (tests/test_momentum_fences.py), and this module is on that lens's import
allowlist precisely because it cannot reach the bot, the grade tables or a
published file: bars in, a dict out. `tests/test_rmodel.py` pins the imports.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

STOP_FILL_LEVEL = "level"
STOP_FILL_BAR = "bar"
LIMIT_REASONS = ("tp",)          # exit reasons that filled as a resting limit


def r_of(price: float, entry: float, risk: float, is_long: bool) -> float:
    return (price - entry) / risk if is_long else (entry - price) / risk


def open_trade(direction: str, entry: float, stop: float, targets: Sequence[float],
               scale: Sequence[float], day: str = "", chase_guard: bool = True) -> Optional[dict]:
    """A new trade, or None when it is not takeable.

    `chase_guard` refuses an entry already at or beyond the first target, or on
    the wrong side of the stop -- the 5.0 `_snapshot` rule ("do not chase").
    """
    is_long = direction == "long"
    vals = [entry, stop, *targets]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
        return None
    if len(targets) == 0 or len(targets) != len(scale):
        return None
    if chase_guard:
        if is_long and (entry <= stop or entry >= targets[0]):
            return None
        if not is_long and (entry >= stop or entry <= targets[0]):
            return None
    risk = abs(entry - stop)
    if not risk > 0:
        return None
    return {
        "direction": "long" if is_long else "short",
        "entry": round(float(entry), 8), "stop": float(stop), "initial_stop": float(stop),
        "targets": [float(t) for t in targets], "scale": [float(s) for s in scale],
        "hit": [False] * len(targets), "risk": round(risk, 8),
        "entry_date": day, "status": "open",
        "booked_pct": 0.0, "gross_r": 0.0, "cost_r": 0.0, "realized_r": 0.0,
        "exits": [], "bars": 0,
        "mae": round(float(entry), 8), "mfe": round(float(entry), 8),
    }


def _favourable(new: float, old: float, is_long: bool) -> bool:
    return new > old if is_long else new < old


def _close_rest(tr: dict, price: float, day: str, reason: str) -> None:
    is_long = tr["direction"] == "long"
    remaining = round(1.0 - tr["booked_pct"], 6)
    if remaining > 1e-9:
        tr["exits"].append({"reason": reason, "price": round(price, 8), "pct": remaining, "date": day})
        tr["gross_r"] = round(tr["gross_r"] + remaining * r_of(price, tr["entry"], tr["risk"], is_long), 4)
        tr["booked_pct"] = 1.0
    tr["status"] = "closed"
    tr["exit_price"] = round(price, 8)
    tr["exit_date"] = day
    # HOW it closed, kept apart from `exit_reason`: the 5.0 convention names a
    # trade whose runner is marked at the end of the data "target" or "trail"
    # after its best rung, so exit_reason alone cannot say it is still open.
    tr["closed_by"] = reason
    last = len(tr["targets"]) - 1
    if tr["hit"][last]:
        tr["exit_reason"] = "target"
    elif tr["hit"][0]:
        tr["exit_reason"] = "trail"
    else:
        tr["exit_reason"] = reason


def _mark(tr: dict, price: float, day: str, stop_fill_price: Optional[float] = None) -> None:
    """One price observation. Stop first; otherwise book every target reached."""
    is_long = tr["direction"] == "long"
    tr["mfe"] = max(tr["mfe"], price) if is_long else min(tr["mfe"], price)
    tr["mae"] = min(tr["mae"], price) if is_long else max(tr["mae"], price)
    stop_hit = price <= tr["stop"] if is_long else price >= tr["stop"]
    if stop_hit:
        _close_rest(tr, price if stop_fill_price is None else stop_fill_price, day, "stop")
        return
    reached = (lambda lvl: price >= lvl) if is_long else (lambda lvl: price <= lvl)
    for k, lvl in enumerate(tr["targets"]):
        if tr["hit"][k] or not reached(lvl):
            continue
        tr["hit"][k] = True
        pct = tr["scale"][k]
        tr["exits"].append({"reason": f"tp{k + 1}", "price": lvl, "pct": pct, "date": day})
        tr["gross_r"] = round(tr["gross_r"] + pct * r_of(lvl, tr["entry"], tr["risk"], is_long), 4)
        tr["booked_pct"] = round(tr["booked_pct"] + pct, 6)
        if k == 0 and _favourable(tr["entry"], tr["stop"], is_long):
            tr["stop"] = tr["entry"]                     # break-even after the first target
        elif k == 1 and _favourable(tr["targets"][0], tr["stop"], is_long):
            tr["stop"] = tr["targets"][0]                # locked at the first target
    if tr["booked_pct"] >= 1.0 - 1e-9:
        tr["status"] = "closed"
        tr["exit_price"] = tr["exits"][-1]["price"]
        tr["exit_date"] = day
        tr["exit_reason"] = "target"
        tr["closed_by"] = "target"


def step(tr: dict, o: float, h: float, l: float, c: float, day: str,
         stop_fill: str = STOP_FILL_LEVEL) -> None:
    """Manage an open trade across one bar, adverse extreme first."""
    if tr["status"] != "open":
        return
    o, h, l, c = float(o), float(h), float(l), float(c)     # numpy scalars never leak out
    tr["bars"] += 1
    is_long = tr["direction"] == "long"
    adverse, favourable = (l, h) if is_long else (h, l)
    fill = None
    if stop_fill == STOP_FILL_LEVEL:
        gapped = (o <= tr["stop"]) if is_long else (o >= tr["stop"])
        fill = o if (gapped and math.isfinite(o)) else tr["stop"]
    _mark(tr, adverse, day, fill)
    if tr["status"] == "open":
        _mark(tr, favourable, day, fill)


def close(tr: dict, price: float, day: str, reason: str) -> None:
    """Close whatever is still open at `price` (a time stop, end of data...)."""
    if tr["status"] == "open":
        _close_rest(tr, float(price), day, reason)


def cost_r(tr: dict, slip_frac: float, comm_frac: float) -> float:
    """vivek_journal._cost_r, generalised: a limit exit is any `tpN` reason."""
    entry, risk = tr.get("entry"), tr.get("risk")
    if not risk or risk <= 0 or not entry:
        return 0.0
    price = entry * (slip_frac + comm_frac)
    for ex in tr.get("exits", []):
        is_market = not str(ex.get("reason", "")).startswith(LIMIT_REASONS)
        price += ex.get("pct", 0.0) * ex.get("price", entry) * (comm_frac + (slip_frac if is_market else 0.0))
    return price / risk


def finish(tr: dict, costs: Optional[tuple] = None) -> dict:
    """Net the costs off: gross_r, cost_r and realized_r, 5.0 rounding."""
    tr["gross_r"] = round(tr["gross_r"], 4)
    tr["cost_r"] = round(cost_r(tr, *costs), 4) if costs else 0.0
    tr["realized_r"] = round(tr["gross_r"] - tr["cost_r"], 4)
    tr["mae_r"] = round(r_of(tr["mae"], tr["entry"], tr["risk"], tr["direction"] == "long"), 3)
    tr["mfe_r"] = round(r_of(tr["mfe"], tr["entry"], tr["risk"], tr["direction"] == "long"), 3)
    return tr


def simulate(bars: Iterable[tuple], tr: dict, *, costs: Optional[tuple] = None,
             stop_fill: str = STOP_FILL_LEVEL, time_stop: Optional[int] = None) -> dict:
    """Run a trade over `(day, open, high, low, close)` bars. Pass them from
    the bar the entry FILLS on for a next-open fill (that bar's range is live,
    as in the 5.0 replay), or from the bar AFTER the signal for an entry at
    the signal close. Closes at the time stop (bars held) or the last bar
    ("eod", marked at its close)."""
    last = None
    for day, o, h, l, c in bars:
        last = (day, c)
        step(tr, o, h, l, c, day, stop_fill)
        if tr["status"] != "open":
            break
        if time_stop and tr["bars"] >= time_stop:
            close(tr, c, day, "time")
            break
    if tr["status"] == "open" and last is not None:
        close(tr, last[1], last[0], "eod")
    return finish(tr, costs)


def dollars(tr: dict, notional: float) -> float:
    """What the trade made on `notional` of position: R x risk as a share of entry."""
    entry, risk, r = tr.get("entry"), tr.get("risk"), tr.get("realized_r")
    if not entry or not risk or r is None:
        return 0.0
    return round(r * notional * risk / entry, 2)


def summarise(trades: Sequence[dict], notional: Optional[float] = None) -> dict:
    """R won / R lost / net, the way the owner reads a book. Wins are R > 0."""
    rs = [float(t.get("realized_r") or 0.0) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    out = {
        "trades": n, "wins": len(wins), "losses": len(losses),
        "win_pct": round(100.0 * len(wins) / n, 1) if n else None,
        "r_won": round(sum(wins), 2), "r_lost": round(sum(losses), 2),
        "net_r": round(sum(rs), 2),
        "expectancy_r": round(sum(rs) / n, 3) if n else None,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if sum(losses) < 0 else None,
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
        "open_at_end": sum(1 for t in trades if t.get("closed_by", t.get("exit_reason")) == "eod"),
    }
    if notional:
        usd = [dollars(t, notional) for t in trades]
        out.update({"notional": notional,
                    "usd_won": round(sum(u for u in usd if u > 0), 2),
                    "usd_lost": round(sum(u for u in usd if u <= 0), 2),
                    "net_usd": round(sum(usd), 2)})
    return out

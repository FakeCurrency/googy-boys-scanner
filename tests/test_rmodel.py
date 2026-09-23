"""scanner/rmodel.py -- the shared R ledger the lens replays use.

The load-bearing test here is PARITY: the 5.0 backtest's own trade path
(vivek_journal._snapshot + vivek_backtest._manage_bar) and rmodel are driven
over the same seeded random bars and must produce the same exits, the same
gross/cost/net R and the same exit reason. rmodel exists so PhaseMap-adjacent
lenses can be scored in the same currency as 5.0 without importing the bot;
this is what makes "the same currency" a fact rather than a claim.
"""

from __future__ import annotations

import ast
import pathlib
import random

import pytest

from scanner import config, rmodel
from scanner import vivek_backtest as vbt
from scanner.vivek_journal import _snapshot, costs_for

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCALE = list(config.VIVEK_TP_SCALE_LONG)


def _path(rng: random.Random, n: int, start: float):
    """Random OHLC bars with gaps, as (day, o, h, l, c)."""
    out, px = [], start
    for i in range(n):
        o = px * (1 + rng.gauss(0, 0.012))
        c = o * (1 + rng.gauss(0, 0.025))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.012)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.012)))
        out.append((f"2026-01-{i + 1:02d}" if i < 31 else f"2026-02-{i - 30:02d}", o, h, l, c))
        px = c
    return out


def _plan(rng: random.Random, entry: float, direction: str):
    risk = entry * rng.uniform(0.02, 0.12)
    sign = 1 if direction == "long" else -1
    stop = entry - sign * risk
    tps = [entry + sign * risk * r for r in (rng.uniform(0.8, 1.5), rng.uniform(1.6, 2.6),
                                              rng.uniform(2.7, 4.0))]
    return {"stop": round(stop, 8), "tp1": round(tps[0], 8), "tp2": round(tps[1], 8),
            "tp3": round(tps[2], 8), "scale": SCALE}


def _vivek(bars, plan, direction, market):
    row = {"symbol": "TST", "dir": "LONG" if direction == "long" else "SHORT", "grade": "A"}
    day, o = bars[0][0], bars[0][1]
    tr = _snapshot(row, "1D", plan, market, float(o), day)
    if tr is None:
        return None
    costs = costs_for(market)
    for k, (d, o_, h, l, c) in enumerate(bars):
        vbt._manage_bar(tr, h, l, c, d, costs, is_last=(k == len(bars) - 1))
        if tr["status"] == "closed":
            break
    return tr


def _ledger(bars, plan, direction, market):
    tr = rmodel.open_trade(direction, float(bars[0][1]), plan["stop"],
                           [plan["tp1"], plan["tp2"], plan["tp3"]], plan["scale"], bars[0][0])
    if tr is None:
        return None
    return rmodel.simulate(bars, tr, costs=costs_for(market), stop_fill=rmodel.STOP_FILL_BAR)


@pytest.mark.parametrize("direction", ["long", "short"])
@pytest.mark.parametrize("market", ["asx", "nasdaq", "crypto"])
def test_it_is_the_5_0_backtest_bar_for_bar(direction, market):
    """400 random paths per cell. A plan the 5.0 path refuses (chase guard),
    the ledger must refuse too; every other one must match exactly."""
    rng = random.Random(f"{direction}-{market}")
    compared = refused = 0
    for _ in range(400):
        bars = _path(rng, rng.randint(3, 50), rng.uniform(0.2, 200))
        plan = _plan(rng, bars[0][4], direction)       # levels off the prior close
        a, b = _vivek(bars, plan, direction, market), _ledger(bars, plan, direction, market)
        assert (a is None) == (b is None)
        if a is None:
            refused += 1
            continue
        compared += 1
        assert b["exits"] == a["exits"]
        for k in ("gross_r", "cost_r", "realized_r", "exit_reason", "exit_date"):
            assert b[k] == a[k], (k, a[k], b[k])
    assert compared > 250 and refused > 0, (compared, refused)


def test_level_fills_are_kinder_than_bar_fills_and_never_worse():
    """STOP_FILL_LEVEL fills a stop at the stop (or a gapped open), never at
    the bar's extreme -- so on the same path it can only be as good or better."""
    rng = random.Random("fills")
    better = 0
    for _ in range(300):
        bars = _path(rng, 30, 50.0)
        plan = _plan(rng, bars[0][4], "long")
        args = ("long", float(bars[0][1]), plan["stop"], [plan["tp1"], plan["tp2"], plan["tp3"]],
                plan["scale"], bars[0][0])
        a, b = rmodel.open_trade(*args), rmodel.open_trade(*args)
        if a is None:
            continue
        rmodel.simulate(bars, a, stop_fill=rmodel.STOP_FILL_BAR)
        rmodel.simulate(bars, b, stop_fill=rmodel.STOP_FILL_LEVEL)
        assert b["gross_r"] >= a["gross_r"] - 1e-9
        better += b["gross_r"] > a["gross_r"] + 1e-9
    assert better > 0


def test_a_stop_fills_at_the_level_or_the_gapped_open():
    tr = rmodel.open_trade("long", 10.0, 9.0, [11.0, 12.0, 13.0], SCALE, "d0")
    rmodel.simulate([("d1", 9.8, 9.9, 8.5, 8.7)], tr)
    assert tr["exits"] == [{"reason": "stop", "price": 9.0, "pct": 1.0, "date": "d1"}]
    assert tr["realized_r"] == -1.0 and tr["exit_reason"] == "stop"
    gap = rmodel.open_trade("long", 10.0, 9.0, [11.0, 12.0, 13.0], SCALE, "d0")
    rmodel.simulate([("d1", 8.0, 8.2, 7.5, 8.1)], gap)
    assert gap["exits"][0]["price"] == 8.0 and gap["realized_r"] == -2.0


def test_the_house_ladder_breakeven_and_lock():
    tr = rmodel.open_trade("long", 10.0, 9.0, [11.0, 12.0, 13.0], [0.25, 0.5, 0.15], "d0")
    bars = [("d1", 10.0, 11.2, 9.9, 11.1),      # TP1 -> stop to 10 (break-even)
            ("d2", 11.1, 12.3, 11.0, 12.0),     # TP2 -> stop to 11 (TP1)
            ("d3", 12.0, 12.1, 10.8, 10.9)]     # runner + 15% stopped at 11
    rmodel.simulate(bars, tr)
    assert [e["reason"] for e in tr["exits"]] == ["tp1", "tp2", "stop"]
    assert tr["exits"][-1]["price"] == 11.0 and tr["exits"][-1]["pct"] == 0.25
    assert tr["gross_r"] == round(0.25 * 1 + 0.5 * 2 + 0.25 * 1, 4)
    assert tr["exit_reason"] == "trail"


def test_a_single_target_closes_the_whole_trade_and_a_time_stop_ends_it():
    tr = rmodel.open_trade("long", 1.0, 0.9, [1.3], [1.0], "d0")
    rmodel.simulate([("d1", 1.0, 1.35, 0.95, 1.3), ("d2", 1.3, 2.0, 1.2, 1.9)], tr)
    assert tr["exit_reason"] == "target" and tr["gross_r"] == 3.0 and tr["exit_date"] == "d1"
    slow = rmodel.open_trade("long", 1.0, 0.9, [1.3], [1.0], "d0")
    bars = [(f"d{i}", 1.0, 1.02, 0.98, 1.01) for i in range(1, 10)]
    rmodel.simulate(bars, slow, time_stop=3)
    assert slow["exit_reason"] == "time" and slow["exit_date"] == "d3"


def test_costs_charge_slippage_on_market_exits_only():
    tr = rmodel.open_trade("long", 100.0, 90.0, [110.0], [1.0], "d0")
    rmodel.simulate([("d1", 100, 111, 99, 110)], tr, costs=(0.001, 0.0005))
    # entry 100*(0.0015) + target exit 1.0*110*0.0005, over risk 10
    assert tr["cost_r"] == round((0.15 + 0.055) / 10, 4)
    assert tr["realized_r"] == round(1.0 - tr["cost_r"], 4)


def test_summarise_splits_won_and_lost():
    trades = [{"realized_r": 2.0, "entry": 10, "risk": 1}, {"realized_r": -1.0, "entry": 10, "risk": 1},
              {"realized_r": 0.0, "entry": 10, "risk": 1}]
    s = rmodel.summarise(trades, notional=1000)
    assert (s["r_won"], s["r_lost"], s["net_r"], s["wins"], s["losses"]) == (2.0, -1.0, 1.0, 1, 2)
    assert s["net_usd"] == 100.0 and s["profit_factor"] == 2.0


def test_it_imports_nothing_from_the_repo():
    """On the momentum lens's import allowlist BECAUSE it cannot reach the
    bot: bars in, a dict out. Stdlib only."""
    tree = ast.parse((ROOT / "scanner" / "rmodel.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0] if node.level == 0 else ".")
    assert mods <= {"__future__", "math", "typing"}, mods

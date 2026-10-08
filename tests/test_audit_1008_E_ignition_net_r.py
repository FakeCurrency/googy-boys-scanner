"""2026-10-08 audit, cluster E -- IGNITION's net R (#23). Report-only lens.

#23  The page's exit R / R now were GROSS while every replay number is net of
     IGNITION_BT_COST_PCT, under a docstring and a tooltip promising "one
     number". The row now carries `cost_r` and its R is net, via the SAME
     helper the replay subtracts.

Network is never touched.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config
from scanner.ignition import backtest as BT
from scanner.ignition import engine as E
from scanner.ignition import run as RUN

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYD = ZoneInfo("Australia/Sydney")

_spec = importlib.util.spec_from_file_location("_ig_suite_e_netr", ROOT / "tests" / "test_ignition.py")
_ig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ig)
build, T = _ig.build, _ig.T


def asx_frame(n_after: int) -> pd.DataFrame:
    """The crypto suite's base -> breakout fixture on a weekday calendar,
    trimmed to the trigger bar + `n_after` bars."""
    df = build()
    df.index = pd.bdate_range("2021-01-04", periods=len(df))
    return df.iloc[:T + 1 + n_after]


def _at(day, hh, mm):
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=SYD)


# ---------------------------------------------------------------------------
# #23 -- the page's R is the replay's NET R
# ---------------------------------------------------------------------------

def _closed_frame(market):
    df = _ig.fx("failed").iloc[:T + 6].copy()
    if market == "asx":
        df.index = pd.bdate_range("2021-01-04", periods=len(df))
    return df


@pytest.mark.parametrize("market", ["crypto", "asx"])
def test_exit_r_is_the_replays_net_r_for_the_same_trade(market):
    df = _closed_frame(market)
    row = E.screen_frame(df, market)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "stop"
    want_cost = (E.mkt(market, "IGNITION_BT_COST_PCT") / 100.0
                 * row["entry"] / (row["entry"] - row["stop"]))
    assert row["cost_r"] == pytest.approx(round(want_cost, 4))
    # a stop fill is -1R gross; the page shows the NET number the replay books
    assert row["exit_r"] == round(-1.0 - want_cost, 2) < -1.0
    trades = BT.run_all(BT.prepare({"ZZZ": df}, market, {"ZZZ": "ZZZ"}),
                        E.Params.from_config(market))
    same = [t for t in trades if t.get("trigger_date") == row["trigger_date"]
            and "net_r" in t]
    assert len(same) == 1, "the replay books the same trigger"
    assert round(same[0]["net_r"], 2) == row["exit_r"]
    assert same[0]["cost_r"] == pytest.approx(row["cost_r"], abs=1e-4)


def test_r_now_is_net_of_the_same_cost():
    df = build()
    row = E.screen_frame(df.iloc[:T + 3], "crypto")
    en, st, px = row["entry"], row["stop"], row["price"]
    cost = config.IGNITION_BT_COST_PCT / 100.0 * en / (en - st)
    assert row["r_now"] == pytest.approx(round((px - en) / (en - st) - cost, 2))


def test_the_page_and_the_replay_share_one_cost_helper():
    src = (ROOT / "scanner" / "ignition" / "backtest.py").read_text()
    assert src.count("E.round_trip_cost_r(") == 2, "both replay legs price costs through the engine"
    assert "/ 100.0) * entry / risk" not in src, "a second copy of the cost arithmetic"
    assert E.round_trip_cost_r(1.0, 0.09, 0.009) == pytest.approx(0.1)


def test_the_payload_states_the_round_trip_it_is_net_of():
    df = asx_frame(2)
    day = df.index[-1].date()
    pay = RUN.screen_market("asx", frames={"ZZZ.AX": df}, rows=[], now=_at(day, 17, 30))
    assert pay["rules"]["cost_pct_round_trip"] == 1.0
    assert pay["results"][0]["cost_r"] > 0

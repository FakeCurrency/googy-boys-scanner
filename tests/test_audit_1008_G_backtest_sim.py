"""Audit 2026-10-08, cluster G -- the backtest's slim records and portfolio sim.

  #33  mfe_zero_rate read 1.0 everywhere because _slim dropped mfe_r
  #34  portfolio_sim ignored the live weekly/3d level gate
  #35  portfolio_sim took the 1D break where the bot takes the 3D reclaim
"""

from __future__ import annotations

import pytest

from scanner import config
from scanner import vivek_backtest as bt


# ------------------------------------------------------------ #33 mfe_r

def test_the_slim_record_keeps_the_mfe_the_rate_is_computed_from():
    winner = {"symbol": "W", "market": "asx", "realized_r": 3.0, "mfe_r": 3.4,
              "mae_r": -0.2, "entry": 10.0, "risk": 1.0, "direction": "long"}
    slim = bt._slim(winner)
    assert slim["mfe_r"] == 3.4
    # The production path aggregates SLIM records: a winner is not wrong-from-entry.
    assert bt._metrics([slim])["mfe_zero_rate"] == 0.0


# ------------------------------------------------------- #34 / #35 the sim

def _t(sym="AAA", tf="1W", et="reclaim", level="weekly", day="2026-01-05",
       exit_day="2026-02-01", r=1.0, **kw):
    t = {"symbol": sym, "market": "asx", "grade": "A+", "entry_type": et,
         "direction": "long", "timeframe": tf, "level_tf": level, "sector": f"s-{sym}",
         "entry": 100.0, "stop": 92.0, "risk": 8.0, "entry_date": day,
         "exit_date": exit_day, "exit_reason": "target", "realized_r": r}
    t.update(kw)
    return t


def test_the_sim_drops_what_the_live_level_gate_drops_fail_closed():
    trades = [_t("WK"), _t("D3", level="3d"), _t("H4", level="h4"),
              _t("NONE", level=None), _t("BLANK", level="  ")]
    sim = bt.portfolio_sim(trades)
    assert sim["eligible"]["n"] == 2 and sim["taken"] == 2
    assert sim["gated"]["level_gate"] == 3
    assert sim["params"]["level_tf_allow"] == list(config.VIVEK_BOT_LEVEL_TF_ALLOW)
    assert "level_gate" in sim["params"]["simulated_gates"]


def test_the_level_gate_off_admits_every_level(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ())
    sim = bt.portfolio_sim([_t("WK"), _t("H4", level="h4"), _t("NONE", level=None)])
    assert sim["taken"] == 3 and "level_gate" not in sim["gated"]


def test_a_signal_arming_3d_and_1d_trades_the_3d_reclaim_as_the_bot_does():
    """The replay lists the 1D break FIRST (it closed first); the bot's cell
    walk takes the 3D reclaim off the same row. PAXG 2022-12-14 was this shape:
    the sim booked the 1D at -0.165R where live would have made +7.24R."""
    d1 = _t("PAXG", tf="1D", et="break", r=-0.165, exit_day="2022-12-20", day="2022-12-15")
    d3 = _t("PAXG", tf="3D", et="reclaim", r=7.24, exit_day="2023-04-01", day="2022-12-15")
    sim = bt.portfolio_sim([d1, d3])
    assert sim["taken"] == 1
    assert sim["portfolio"]["total_r"] == pytest.approx(7.24)
    # ...and the sibling is not double-counted in `eligible` either.
    assert sim["eligible"]["n"] == 1 and sim["same_signal_dropped"] == 1
    assert "dup_symbol" not in sim["skipped"]


def test_the_cell_walk_ranks_1w_over_3d_over_1d():
    trades = [_t("X", tf="1D", et="break", r=0.1), _t("X", tf="3D", r=0.2),
              _t("X", tf="1W", et="break", r=0.3)]
    assert bt.portfolio_sim(trades)["portfolio"]["total_r"] == pytest.approx(0.3)


def test_a_picked_plan_that_fails_a_gate_skips_the_row_it_never_falls_through():
    """`evaluate_setup` tests the stop of the plan `_pick_plan` chose and skips
    the ROW on a wide stop -- it does not go back for the 1D plan."""
    wide = _t("Y", tf="3D", risk=40.0)                       # 40% stop > the 25% cap
    ok_1d = _t("Y", tf="1D", et="break", risk=5.0)
    sim = bt.portfolio_sim([ok_1d, wide])
    assert sim.get("taken", 0) == 0
    assert sim["gated"] == {"wide_stop": 1}


def test_different_days_are_different_signals_and_are_not_collapsed():
    trades = [_t("Z", tf="1D", et="break", day="2026-01-05", exit_day="2026-01-07"),
              _t("Z", tf="3D", day="2026-01-12", exit_day="2026-02-01")]
    sim = bt.portfolio_sim(trades)
    assert sim["taken"] == 2 and sim["same_signal_dropped"] == 0

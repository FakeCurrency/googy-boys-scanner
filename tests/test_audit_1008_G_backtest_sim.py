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

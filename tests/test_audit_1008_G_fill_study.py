"""Audit 2026-10-08 #64 -- scripts/lens_fill_confluence.py, two off-by-ones.

  * `resim_trade` started managing the bar AFTER the fill, so a trade the
    parity replay stopped out on its fill day survived in every fill model and
    the "pessimistic (live parity default)" column could not reproduce the
    baseline it is named after.
  * `pm_classify_at` sliced history to `<= entry_date`, and entry_date is the
    FILL bar: PhaseMap saw that bar's high/low/close at the open fill.
"""

from __future__ import annotations

import importlib.util
import pathlib

import numpy as np
import pandas as pd

from scanner import vivek_parity as vp
from scanner.vivek_journal import _snapshot, costs_for

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lens_fill_confluence",
                                               ROOT / "scripts" / "lens_fill_confluence.py")
lfc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lfc)


def _bars(n: int = 40, start: str = "2024-03-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="B")
    px = np.full(n, 100.0)
    return pd.DataFrame({"Open": px, "High": px + 1.0, "Low": px - 1.0,
                         "Close": px, "Volume": 1e6}, index=idx)


def _trade(df: pd.DataFrame, j0: int) -> dict:
    return {"symbol": "X", "market": "nasdaq", "direction": "long", "grade": "A+",
            "timeframe": "1W", "entry_type": "reclaim", "level_tf": "weekly",
            "entry": 100.0, "risk": 5.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0,
            "scale": [0.25, 0.5, 0.15], "entry_date": df.index[j0].date().isoformat()}


def _baseline(df: pd.DataFrame, trade: dict, j0: int) -> dict:
    """The parity replay's own lifecycle for this fill: open at bar j0's open,
    then manage bar j0 onwards (vivek_parity.replay_symbol_parity, step 1 + 2)."""
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG", "grade": "A+",
           "entry_types": ["reclaim"], "level_tf": "weekly"}
    plan = {"stop": 95.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0,
            "scale": [0.25, 0.5, 0.15], "entry_trigger": "reclaim", "armed": True}
    tr = _snapshot(row, "1W", plan, "nasdaq", float(df["Open"].iloc[j0]), trade["entry_date"])
    tr["mfe_r_at"], tr["close_r_at"] = {}, {}
    costs, rules, n = costs_for("nasdaq"), vp.baseline_rules(), len(df)
    for j in range(j0, n):
        vp._manage_parity_bar(tr, float(df["High"].iloc[j]), float(df["Low"].iloc[j]),
                              float(df["Close"].iloc[j]), df.index[j].date().isoformat(),
                              costs, is_last=(j == n - 1), rules=rules)
        if tr["status"] == "closed":
            break
    return tr


def test_a_fill_day_stop_is_a_stop_in_the_pessimistic_resim():
    """The audit's shape: fill at 100, stop 95, the fill bar trades down to 94."""
    df = _bars()
    j0 = 10
    df.iloc[j0, df.columns.get_loc("Low")] = 94.0
    df.iloc[j0 + 3, df.columns.get_loc("High")] = 115.0     # the survivor would bank TP1
    trade = _trade(df, j0)
    base = _baseline(df, trade, j0)
    assert base["exit_reason"] == "stop" and base["exit_date"] == trade["entry_date"]
    got = lfc.resim_trade(df, trade, "pessimistic")
    assert got["exit_reason"] == "stop"
    assert got["realized_r"] == base["realized_r"] < 0


def test_the_pessimistic_resim_reproduces_the_baseline_on_an_ordinary_path():
    df = _bars()
    j0 = 5
    df.iloc[j0 + 4, df.columns.get_loc("High")] = 121.0
    df.iloc[j0 + 9, df.columns.get_loc("Low")] = 90.0
    trade = _trade(df, j0)
    base = _baseline(df, trade, j0)
    got = lfc.resim_trade(df, trade, "pessimistic")
    assert (got["realized_r"], got["exit_reason"]) == (base["realized_r"], base["exit_reason"])


def test_phasemap_is_classified_on_the_signal_bar_not_the_fill_bar(monkeypatch):
    import phasemap.engine.scanner as pm_scanner
    from phasemap.config import CONFIG
    df = _bars(CONFIG.min_history_bars + 20, start="2020-01-01")
    entry = df.index[-5].date().isoformat()
    seen = {}

    def fake_scan(sym, d, market=None, volume_is_usd=False):
        seen["last"] = pd.Timestamp(d["Date"].iloc[-1]).date().isoformat()
        return []

    monkeypatch.setattr(pm_scanner, "scan_ticker", fake_scan)
    lfc.pm_classify_at(df, "nasdaq", entry, "long")
    assert seen["last"] == df.index[-6].date().isoformat(), "the bar before the fill"

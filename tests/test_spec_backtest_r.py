"""scanner/spec_backtest.py -- the Specs R model (r_trade / summarise_r).

The engine's own plan (entry at the signal close, its stop, its one target)
traded through the shared ledger. The load-bearing check: over real committed
ASX bars the R model and the existing stop/target race agree on who won --
the race says "target" exactly when R books the target, "stop" exactly when
R is stopped -- so the new number is the old evidence, scored.
"""

from __future__ import annotations

import collections
import json
import pathlib

import numpy as np
import pandas as pd

from scanner import config
from scanner import spec_backtest as sb

ROOT = pathlib.Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "history" / "asx"


def _bars(rows):
    days = [f"d{k}" for k in range(len(rows))]
    o, h, l, c = (np.array([r[i] for r in rows], dtype=float) for i in range(4))
    return days, o, h, l, c


def _sig(entry=1.0, stop=0.9, target=1.3):
    return {"entry": entry, "stop": stop, "target": target, "date": "d0"}


def test_a_target_books_the_whole_position_at_the_target():
    days, o, h, l, c = _bars([(1, 1, 1, 1), (1.0, 1.35, 0.95, 1.3)])
    r = sb.r_trade(_sig(), 0, days, o, h, l, c, "asx")
    assert r["r_exit"] == "target" and r["r_gross"] == 3.0 and r["r"] < 3.0


def test_the_stop_is_a_resting_order_and_a_gap_fills_at_the_open():
    days, o, h, l, c = _bars([(1, 1, 1, 1), (0.8, 0.82, 0.7, 0.75)])
    r = sb.r_trade(_sig(), 0, days, o, h, l, c, "asx")
    assert r["r_exit"] == "stop" and r["r_gross"] == -2.0          # (0.8 - 1.0) / 0.1
    assert r["r_gross_worst"] == -3.0                               # the 0.7 print


def test_the_worst_print_column_is_the_same_trade_never_better():
    days, o, h, l, c = _bars([(1, 1, 1, 1), (0.95, 0.97, 0.85, 0.9)])
    r = sb.r_trade(_sig(), 0, days, o, h, l, c, "asx")
    assert r["r_gross"] == -1.0 and r["r_gross_worst"] == -1.5
    sigs = [dict(_sig(), r=r["r"], r_worst=r["r_worst"], r_risk=r["r_risk"], r_exit="stop",
                 r_closed_by="stop")]
    assert sb.summarise_r(sigs, 1000, "worst_print")["net_r"] < sb.summarise_r(sigs, 1000)["net_r"]


def test_the_races_horizon_is_the_time_stop():
    rows = [(1, 1, 1, 1)] + [(1.0, 1.05, 0.95, 1.02)] * (sb.TRACK_BARS + 10)
    days, o, h, l, c = _bars(rows)
    r = sb.r_trade(_sig(), 0, days, o, h, l, c, "asx")
    assert r["r_exit"] == "time" and r["r_bars"] == sb.TRACK_BARS


def test_untradeable_plans_are_counted_not_scored():
    days, o, h, l, c = _bars([(1, 1, 1, 1), (1, 1.1, 0.99, 1)])
    assert sb.r_trade(_sig(stop=0.999), 0, days, o, h, l, c, "asx")["r_skip"] == "stop_too_tight"
    assert sb.r_trade(_sig(), 1, days, o, h, l, c, "asx")["r_skip"] == "signal on the last bar"
    sigs = [{"r": None, "r_skip": "stop_too_tight"},
            {"r": 1.0, "r_worst": 1.0, "entry": 1.0, "r_risk": 0.1, "r_exit": "target",
             "r_closed_by": "target"}]
    out = sb.summarise_r(sigs, 1000)
    assert out["trades"] == 1 and out["skipped"] == {"stop_too_tight": 1}
    assert out["net_usd"] == 100.0


def test_the_r_model_and_the_race_agree_on_who_won():
    agree = collections.Counter()
    for p in sorted(HIST.glob("*.json"))[:120]:
        bars = json.loads(p.read_text(encoding="utf-8"))["bars"]
        f = pd.DataFrame(bars, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        f.index = pd.to_datetime(f.pop("Date"))
        for s in sb.replay_ticker(p.stem, f, "asx"):
            if s.get("r") is None:
                continue
            want = {"target": {"target"}, "stop": {"stop"}, "open": {"time", "eod"}}[s["outcome"]]
            assert s["r_exit"] in want, (p.stem, s["date"], s["outcome"], s["r_exit"])
            agree[s["outcome"]] += 1
    assert agree["target"] and agree["stop"], agree


def test_the_report_carries_the_r_section(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "REPORT_DIR", str(tmp_path))
    sig = {"symbol": "X", "date": "2024-01-02", "grade": "A", "entry": 1.0, "stop": 0.9,
           "target": 1.3, "rr": 3.0, "fwd_5": 0.1, "fwd_10": 0.1, "fwd_20": 0.1, "mae": -0.05,
           "outcome": "target", "r": 2.9, "r_worst": 2.9, "r_risk": 0.1, "r_exit": "target",
           "r_closed_by": "target"}
    path = sb.write_report("asx", [sig], {"n": 0, "fwd_5": None, "fwd_10": None, "fwd_20": None},
                           1, "5y")
    md = open(path, encoding="utf-8").read()
    assert "## R model" in md and "| ALL SIGNALS | 1 |" in md
    assert f"${config.LENS_BACKTEST_NOTIONAL:,.0f}" in md

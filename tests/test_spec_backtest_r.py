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
import pytest

from scanner import config
from scanner import spec_backtest as sb

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Real bars frozen out of data/history/asx/ (2026-10-14): the race used to read
# the first 120 files of the LIVE archive, whose membership and bars the scan
# rewrites, so the sample and the runtime (24s, growing) moved on their own.
HIST = ROOT / "tests" / "fixtures" / "history" / "asx"


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


@pytest.mark.slow
def test_the_r_model_and_the_race_agree_on_who_won():
    agree = collections.Counter()
    for p in sorted(HIST.glob("*.json")):
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


# ---------------------------------------------------------------------------
# REFINE200 #181: the evidence's grade is the page's grade, and a throwing
# frame is counted, never swallowed
# ---------------------------------------------------------------------------

def test_published_grade_demotes_a_low_rr_plan_exactly_as_the_page_does():
    from scanner import spec
    lo = config.MIN_TRADEABLE_RR - 0.01
    assert spec.published_grade("A+", lo) == "B"
    assert spec.published_grade("A", lo) == "B"
    assert spec.published_grade("A+", config.MIN_TRADEABLE_RR) == "A+"
    assert spec.published_grade("B", 0.1) == "B"
    src = (ROOT / "scanner" / "spec_run.py").read_text(encoding="utf-8")
    assert "spec.published_grade(grade, lv[\"rr\"])" in src, "build_row must use the one helper"


def _spike_frame(n=config.SPEC_MIN_HISTORY + 30):
    idx = pd.bdate_range(end="2026-10-09", periods=n)
    c = np.full(n, 0.2)
    v = np.full(n, 1e5)
    v[-20] = 1e7                                   # the spike the pre-gate needs
    return pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c,
                         "Volume": v}, index=idx)


def test_the_replay_files_a_low_rr_A_plus_under_B_like_the_page(monkeypatch):
    """T88 scored 10 (A+ by points) with rr 0.67 and the page showed it as B;
    the replay filed the same signal under A+."""
    from scanner import spec
    monkeypatch.setattr(spec, "evaluate", lambda df, max_price=None: {"close": 0.2})
    monkeypatch.setattr(spec, "score_and_grade", lambda sig: (10, "A+", ["volume"]))
    monkeypatch.setattr(spec, "compute_levels",
                        lambda df, sig: {"entry": 0.2, "stop": 0.18, "target": 0.2134, "rr": 0.67})
    sigs = sb.replay_ticker("T88", _spike_frame(), "asx")
    assert sigs, "the fixture produced no signal - is the pre-gate still met?"
    assert {s["grade"] for s in sigs} == {"B"}
    assert {s["grade_raw"] for s in sigs} == {"A+"}


def test_a_frame_that_throws_is_counted_and_published_not_skipped_in_silence(monkeypatch, tmp_path):
    items = [{"symbol": "AAA", "yf": "AAA.AX"}, {"symbol": "BBB", "yf": "BBB.AX"}]
    monkeypatch.setattr(sb.universe, "load_universe", lambda m, full=True: items)
    monkeypatch.setattr(sb.data, "download", lambda t, **k: {i["yf"]: _spike_frame() for i in items})

    def boom(sym, df, market="asx"):
        raise ValueError("engine regression")
    monkeypatch.setattr(sb, "replay_ticker", boom)
    monkeypatch.setattr(sb, "write_report", lambda *a, **k: str(tmp_path / "r.md"))
    written = {}
    monkeypatch.setattr(sb.output, "write_json", lambda path, body, **k: written.update(body))
    assert sb.main(["--market", "asx"]) == 0
    assert written["errors"] == 2, written.get("errors")
    assert written["error_sample"] and "engine regression" in json.dumps(written["error_sample"])
    assert "grade_rule" in written

"""A REAL 4H plan for the chart's 4H toggle (owner, 2026-09-19).

"I need to see genuine set ups forming on d and weekly 3d and then if i toggle
down i want to see a genuine set up on the 4hr."

Most of this file is about the FENCE. The 4H plan is display only: it is built
after scoring, grading and gating, and nothing about which names appear or what
grade they carry may move because of it. The owner's standing constraint is "I
don't want to lose the edge of the scanner rules", so those are assertions here
rather than promises in a comment.
"""
import numpy as np
import pandas as pd
import pytest

from scanner import config, scan, vivek

HOUR = "1h"


def _hourly(n=1400, lo=18.0, hi=30.0):
    base = np.concatenate([np.linspace(hi, lo, n // 2), np.linspace(lo, hi * 0.9, n - n // 2)])
    idx = pd.date_range("2025-01-01", periods=n, freq=HOUR, tz="UTC")
    return pd.DataFrame({"Open": base, "High": base * 1.004, "Low": base * 0.996,
                         "Close": base, "Volume": np.ones(n) * 5000}, index=idx)


# ── the resampler ────────────────────────────────────────────────────────────

def test_hourly_buckets_into_4h_with_correct_ohlc():
    df = _hourly(24)
    h4 = vivek._resample_4h_ohlc(df)
    assert len(h4) == 6, "24 hourly bars is six 4H bars"
    first = df.iloc[:4]
    assert h4.iloc[0]["Open"] == first["Open"].iloc[0]
    assert h4.iloc[0]["High"] == first["High"].max()
    assert h4.iloc[0]["Low"] == first["Low"].min()
    assert h4.iloc[0]["Close"] == first["Close"].iloc[-1]
    assert h4.iloc[0]["Volume"] == first["Volume"].sum()


def test_buckets_are_EPOCH_anchored_so_they_match_the_chart():
    """public/js/chart.js buckets with `t - t % (4*3600)`. If the engine anchored
    to a session open instead, the candles a reader sees and the plan they read
    would be built from different bars -- which is the one outcome that makes a
    4H level untrustworthy."""
    df = _hourly(48)
    h4 = vivek._resample_4h_ohlc(df)
    for ts in h4.index:
        assert ts.hour % 4 == 0, f"bucket at {ts} is not on a 4-hour epoch boundary"
        assert (ts.minute, ts.second) == (0, 0)


def test_a_short_or_broken_frame_returns_None_rather_than_raising():
    assert vivek.build_h4_plan(None, "long") is None
    assert vivek.build_h4_plan(pd.DataFrame(), "long") is None
    assert vivek.build_h4_plan(_hourly(10), "long") is None          # under MIN_TF_BARS
    assert vivek._resample_4h_ohlc(pd.DataFrame({"Close": [1]})) is None


def test_the_plan_carries_the_same_shape_as_every_other_timeframe():
    p = vivek.build_h4_plan(_hourly(), "long")
    assert p is not None
    for k in ("entry", "stop", "tp1", "tp2", "tp3", "risk", "rr", "level",
              "armed", "entry_trigger", "sma_window", "sma_proxy", "structural_tps"):
        assert k in p, f"4H plan is missing {k} — the chart reads it like any other TF"


def test_two_years_of_hourly_bars_reach_a_full_200_period_average():
    """Measured on a runner before this was built: ~3,500 hourly bars over 2y,
    which buckets to ~1,200 4H bars against the 200 a 200-SMA needs."""
    p = vivek.build_h4_plan(_hourly(1400), "long")
    assert p["sma_window"] == config.VIVEK_SMA
    assert p["sma_proxy"] is False, "a 2-year hourly pull must not need a short proxy"


# ── THE FENCE: nothing about the edge may move ───────────────────────────────

def test_the_gate_still_considers_only_weekly_3day_and_daily():
    """gate_tf decides `armed`, which decides the grade, which decides who is on
    the deck. Adding "4H" to this tuple would make a 4H trigger arm a name and
    change the owner's list. It is the single line that must not move."""
    src = (scan.__file__ and open(scan.__file__, encoding="utf-8").read()) or ""
    assert 'for tf in ("1W", "3D", "1D")' in src, (
        "the gate tuple changed — if 4H was added, arming and grades now move")


def test_the_4h_pass_runs_after_scoring_and_grading():
    src = open(scan.__file__, encoding="utf-8").read()
    assert src.index("_report_sma_proxies(results)") < src.index("_attach_h4_plans(results"), (
        "the 4H pass must run after the scan loop, never inside the scoring path")


def test_attaching_a_4h_plan_changes_NOTHING_else_on_the_row(monkeypatch):
    df = _hourly()
    monkeypatch.setattr(scan, "download", lambda t, **k: {x: df for x in t})
    row = {"symbol": "ON", "yf": "ON", "dir": "LONG", "grade": "A+", "score": 10,
           "armed": True, "armed_tf": "1W", "entry": 1.5, "stop": 1.0,
           "plans": {"1D": {"entry": 1.5}, "3D": {"entry": 5.0, "armed": True},
                     "1W": {"entry": 9.9, "armed": True}},
           "markers": {"1D": [{"date": "2026-01-01", "kind": "reaction"}]}}
    before = {k: v for k, v in row.items() if k not in ("plans", "markers")}
    plans_before = {k: dict(v) for k, v in row["plans"].items()}
    markers_1d = list(row["markers"]["1D"])

    scan._attach_h4_plans([row], "nasdaq")

    assert {k: v for k, v in row.items() if k not in ("plans", "markers")} == before
    assert row["plans"]["1D"] == plans_before["1D"]
    assert row["plans"]["1W"] == plans_before["1W"], "the weekly plan drives high conviction"
    assert row["plans"]["3D"] == plans_before["3D"], "so does the 3D plan (reclaim cell)"
    assert row["markers"]["1D"] == markers_1d
    assert "4H" in row["plans"]


def test_high_conviction_never_reads_the_4H_plan_so_the_list_cannot_move():
    """convictionCells in app.js keys off the 1W / 3D / 1D plans (owner ruling
    2026-09-20). A 4H plan cannot reach it, which is why the owner's
    high-conviction list and the morning digest are unchanged by this feature."""
    import pathlib
    from scanner import conviction
    assert "4H" not in conviction.HC_CELLS
    app = pathlib.Path(__file__).resolve().parents[1] / "public" / "js" / "app.js"
    src = app.read_text(encoding="utf-8")
    body = src[src.index("function convictionCells"):]
    body = body[:body.index("\n  }") + 4]
    assert '"1W"' in body
    assert '"4H"' not in body, "high conviction started reading 4H — that changes the list"
# ── degrade, never fail ──────────────────────────────────────────────────────

def test_a_failed_download_leaves_every_row_exactly_as_it_was(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("yahoo said no")
    monkeypatch.setattr(scan, "download", boom)
    row = {"symbol": "ON", "yf": "ON", "dir": "LONG", "plans": {"1D": {"entry": 1}}}
    scan._attach_h4_plans([row], "nasdaq")
    assert "4H" not in row["plans"], "a dead download must not half-write a plan"
    assert "keep the Daily plan" in capsys.readouterr().out


def test_one_bad_ticker_does_not_take_the_others_down(monkeypatch):
    good = _hourly()
    monkeypatch.setattr(scan, "download", lambda t, **k: {"GOOD": good, "BAD": None})
    rows = [{"symbol": "GOOD", "yf": "GOOD", "dir": "LONG", "plans": {}},
            {"symbol": "BAD", "yf": "BAD", "dir": "LONG", "plans": {}}]
    scan._attach_h4_plans(rows, "asx")
    assert "4H" in rows[0]["plans"]
    assert "4H" not in rows[1]["plans"]


def test_the_feature_can_be_switched_off_entirely(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_H4_PLANS", False)
    monkeypatch.setattr(scan, "download", lambda *a, **k: pytest.fail("must not download"))
    row = {"symbol": "ON", "yf": "ON", "dir": "LONG", "plans": {}}
    scan._attach_h4_plans([row], "asx")
    assert row["plans"] == {}


def test_the_download_is_capped_so_a_huge_result_set_cannot_stall_a_scan(monkeypatch):
    seen = {}
    monkeypatch.setattr(config, "VIVEK_H4_MAX_SYMBOLS", 5)
    monkeypatch.setattr(scan, "download",
                        lambda t, **k: (seen.update(n=len(t)), {})[1])
    rows = [{"symbol": f"S{i}", "yf": f"S{i}", "dir": "LONG", "plans": {}} for i in range(50)]
    scan._attach_h4_plans(rows, "asx")
    assert seen["n"] == 5


def test_it_asks_for_hourly_bars_not_daily(monkeypatch):
    seen = {}
    monkeypatch.setattr(scan, "download",
                        lambda t, **k: (seen.update(k), {})[1])
    scan._attach_h4_plans([{"symbol": "ON", "yf": "ON", "dir": "LONG", "plans": {}}], "nasdaq")
    assert seen["interval"] == config.VIVEK_H4_INTERVAL == "1h"
    assert seen["period"] == config.VIVEK_H4_PERIOD


def test_short_rows_get_a_short_direction_plan(monkeypatch):
    df = _hourly()
    monkeypatch.setattr(scan, "download", lambda t, **k: {x: df for x in t})
    row = {"symbol": "ON", "yf": "ON", "dir": "SHORT", "plans": {}}
    scan._attach_h4_plans([row], "nasdaq")
    assert row["plans"]["4H"]["direction"] == "short"

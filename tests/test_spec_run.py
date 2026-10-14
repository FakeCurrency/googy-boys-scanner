"""scanner/spec_run.py -- what the Specs nightly REFUSES to publish.

REFINE200 #179: on a Yahoo blackout `data.download` returns {} and the nightly
used to write `"results": []` with a fresh stamp (so the must-change gate
passed) and then prune EVERY spec chart, because none was in `keep`. The page
then said "No spec setups in this view. The gates are strict" -- the "we could
not look" case dressed as "nothing set up". Now a market whose download covers
under SPEC_MIN_COVERAGE of its universe writes nothing and the CLI exits 3.

REFINE200 #180: a frame past SPEC_MAX_DATA_AGE_DAYS is not screened, and a
last bar still forming (before the market's bar-final) is dropped.

Offline: `scan_market` takes frames, items and the clock injected.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from scanner import config
from scanner import spec_run as SR


def _frame(n=300, end=None, close=0.2):
    end = pd.Timestamp(end or pd.Timestamp.now("UTC").tz_localize(None).normalize())
    idx = pd.bdate_range(end=end, periods=n)
    c = np.full(n, close)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Volume": np.full(n, 1e6)}, index=idx)


def _items(n):
    return [{"symbol": f"S{i}", "name": f"Name {i}", "sector": "", "yf": f"S{i}.AX"}
            for i in range(n)]


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(SR, "OUT_DIR", str(tmp_path))
    good = {"market": "asx", "generated_at": "2026-10-13T19:30:00+11:00",
            "results": [{"symbol": "KEEP"}]}
    (tmp_path / "asx_spec.json").write_text(json.dumps(good), encoding="utf-8")
    charts = tmp_path / "spec_charts" / "asx"
    charts.mkdir(parents=True)
    (charts / "KEEP.json").write_text("{}", encoding="utf-8")
    return tmp_path, good


@pytest.mark.parametrize("got", [0, 1])
def test_an_outage_KEEPS_the_last_good_file_and_every_chart(out, got):
    """0 of 4 (a blackout) and 1 of 4 (25%, under the 50% floor) write
    NOTHING -- not the spec file, not a single chart prune."""
    tmp, good = out
    items = _items(4)
    frames = {it["yf"]: _frame() for it in items[:got]}
    assert SR.scan_market("asx", frames=frames, items=items) is None
    assert json.loads((tmp / "asx_spec.json").read_text(encoding="utf-8")) == good
    assert (tmp / "spec_charts" / "asx" / "KEEP.json").exists(), "a chart was pruned"


def test_the_cli_exits_3_when_a_market_kept_its_file(monkeypatch):
    monkeypatch.setattr(SR, "scan_market", lambda m, limit=None: None)
    assert SR.main(["--market", "asx"]) == 3

    def ok(m, limit=None):
        return {"market": m, "results": []}
    monkeypatch.setattr(SR, "scan_market", ok)
    monkeypatch.setattr("scanner.specgrad.update", lambda *a, **k: None)
    assert SR.main(["--market", "asx"]) == 0


def test_a_covered_market_publishes_and_says_how_much_it_saw(out):
    tmp, _ = out
    items = _items(4)
    frames = {it["yf"]: _frame() for it in items[:3]}
    p = SR.scan_market("asx", frames=frames, items=items)
    assert p is not None
    assert p["universe_size"] == 4 and p["downloaded"] == 3
    assert p["stale_frames"] == 0
    assert json.loads((tmp / "asx_spec.json").read_text(encoding="utf-8"))["downloaded"] == 3


def test_a_stale_frame_is_skipped_not_screened(monkeypatch, out):
    """A suspended name whose last five bars hold the spike stayed a "fresh"
    setup every night. Past the ceiling it is not offered to build_row."""
    seen = []
    monkeypatch.setattr(SR, "build_row", lambda sym, info, df, cur: seen.append(sym))
    items = _items(2)
    old = pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=30)
    frames = {"S0.AX": _frame(), "S1.AX": _frame(end=old)}
    p = SR.scan_market("asx", frames=frames, items=items)
    assert seen == ["S0"]
    assert p["stale_frames"] == 1


@pytest.mark.parametrize("market,last,now,forming", [
    ("asx", "2026-10-14", "2026-10-14T05:39:00+00:00", True),     # 16:39 AEDT
    ("asx", "2026-10-14", "2026-10-14T05:40:00+00:00", False),    # 16:40 bar-final
    ("asx", "2026-10-13", "2026-10-14T03:00:00+00:00", False),
    ("nasdaq", "2026-10-13", "2026-10-13T16:25:00+00:00", True),  # 12:25 EDT, mid-session
    ("nasdaq", "2026-10-13", "2026-10-13T20:30:00+00:00", False),  # 16:30 bar-final
    ("nasdaq", "2026-10-14", "2026-10-13T23:00:00+00:00", True),   # dated after the local date
])
def test_bar_is_forming(market, last, now, forming):
    assert SR.bar_is_forming(market, pd.Timestamp(last), dt.datetime.fromisoformat(now)) is forming


def test_the_forming_bar_is_dropped_before_screening(monkeypatch, out):
    """The committed NASDAQ file was generated 12:25 New York: the half-day
    bar was screened as complete."""
    seen = {}

    def build_row(sym, info, df, cur):
        seen[sym] = str(df["Date"].iloc[-1])[:10]
    monkeypatch.setattr(SR, "build_row", build_row)
    items = [{"symbol": "AAA", "name": "A", "sector": "", "yf": "AAA"}]
    frames = {"AAA": _frame(end="2026-10-13")}
    now = dt.datetime.fromisoformat("2026-10-13T16:25:00+00:00")
    monkeypatch.setattr(SR.data, "_frame_age_days", lambda df, tz=None: 0)
    p = SR.scan_market("nasdaq", frames=frames, items=items, now=now)
    assert seen == {"AAA": "2026-10-12"}
    assert p["forming_dropped"] == 1


def test_the_floors_live_in_config():
    assert 0 < config.SPEC_MIN_COVERAGE < 1
    assert config.SPEC_MAX_DATA_AGE_DAYS >= 4, "must clear a long weekend"


def test_no_unreachable_C_grade_rank():
    """The minimum Specs score (volume 2 + breakout 2, both mandatory) grades
    B, so a C rank was dead code (REFINE200 #182)."""
    from scanner.grading import grade_from_points
    assert grade_from_points(4, config.SPEC_GRADE_CUTOFFS) == "B"
    assert set(SR.GRADE_RANK) == {"A+", "A", "B"}

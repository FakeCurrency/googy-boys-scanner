"""Audit #9 (2026-10-08) / REFINEMENTS #24: a Yahoo outage must not wipe the
published snapshot, and must not turn into a per-ticker re-download storm.

Before: YFinanceProvider.get_daily_bars re-ran fetch_all() whenever its cache
was EMPTY, so an outage night (yfinance swallows the errors into empty frames)
re-downloaded the whole universe once per ticker -- ~50,000 calls on the ASX,
past the nightly's 120-min timeout. When the calls failed fast instead,
run_market published results=[] over yesterday's latest.json and pruned every
chart file, and main() exited 0.
"""

import argparse
import datetime
import json
import os
import sys
import types

import pandas as pd

import phasemap.run as pm_run
from phasemap.config import CONFIG
from phasemap.data.provider import YFinanceProvider
from phasemap.tests import synth


def _stub_yfinance(monkeypatch, frame_for_chunk):
    calls = []

    def download(chunk, **kwargs):
        calls.append(list(chunk))
        return frame_for_chunk(list(chunk))

    mod = types.ModuleType("yfinance")
    mod.download = download
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return calls


def _universe(n):
    return {f"T{i:03d}": {"yf": f"T{i:03d}.AX", "name": f"T{i:03d}", "sector": ""}
            for i in range(n)}


def _seed(root, market, n_results):
    os.makedirs(os.path.join(root, market), exist_ok=True)
    os.makedirs(os.path.join(root, "charts", market), exist_ok=True)
    latest = os.path.join(root, market, "latest.json")
    with open(latest, "w", encoding="utf-8") as f:
        json.dump({"run_date": "2026-10-07", "ruleset_version": "x",
                   "universe_size": 30,
                   "results": [{"ticker": f"OLD{i}"} for i in range(n_results)]}, f)
    with open(os.path.join(root, "charts", market, "OLD0.json"), "w") as f:
        f.write("{}")
    with open(latest, "rb") as f:
        return f.read()


def _args(**kw):
    base = {"tickers": None, "limit": None, "period": "2y"}
    base.update(kw)
    return argparse.Namespace(**base)


def _healthy_frame(chunk):
    """Every symbol gets fixture 1 (a RUNNING setup -> one record each)."""
    bars = synth.fixture1().set_index("Date")
    bars.index = pd.DatetimeIndex(bars.index, name="Date")
    return pd.concat({sym: bars for sym in chunk}, axis=1)


# ------------------------------------------------------------ the provider
def test_an_empty_download_is_fetched_once_not_once_per_ticker(monkeypatch):
    calls = _stub_yfinance(monkeypatch, lambda chunk: pd.DataFrame())
    p = YFinanceProvider({t: v["yf"] for t, v in _universe(30).items()})
    p.fetch_all()
    for t in p.universe():
        assert p.get_daily_bars(t) is None
    assert len(calls) == 1          # one 30-symbol chunk, never re-run
    assert p.fetched_count() == 0


def test_a_lazy_first_read_still_fetches(monkeypatch):
    calls = _stub_yfinance(monkeypatch, _healthy_frame)
    p = YFinanceProvider({"AAA": "AAA.AX", "BBB": "BBB.AX"})
    assert p.get_daily_bars("AAA") is not None    # no explicit fetch_all()
    assert p.get_daily_bars("BBB") is not None
    assert len(calls) == 1 and p.fetched_count() == 2


# ------------------------------------------------------------ run_market
def test_an_outage_night_keeps_yesterdays_snapshot_and_charts(monkeypatch, tmp_path, capsys):
    root = str(tmp_path)
    before = _seed(root, "asx", 40)
    monkeypatch.setattr(pm_run, "load_symbols", lambda m: _universe(30))
    calls = _stub_yfinance(monkeypatch, lambda chunk: pd.DataFrame())
    out = pm_run.run_market("asx", _args(), "2026-10-08", root)
    assert out is None
    assert len(calls) == 1
    with open(os.path.join(root, "asx", "latest.json"), "rb") as f:
        assert f.read() == before                      # not overwritten
    assert os.listdir(os.path.join(root, "charts", "asx")) == ["OLD0.json"]  # not pruned
    assert not os.path.exists(os.path.join(root, "asx", "2026-10-08.json"))
    assert "::error::PhaseMap asx: REFUSED" in capsys.readouterr().out


def test_a_collapse_against_the_previous_snapshot_is_refused(monkeypatch, tmp_path):
    root = str(tmp_path)
    before = _seed(root, "asx", 200)          # yesterday: 200 results
    monkeypatch.setattr(pm_run, "load_symbols", lambda m: _universe(30))
    _stub_yfinance(monkeypatch, _healthy_frame)  # tonight: 60 results < 100
    assert pm_run.run_market("asx", _args(), "2026-10-08", root) is None
    with open(os.path.join(root, "asx", "latest.json"), "rb") as f:
        assert f.read() == before
    # the night's 30 chart files are held back with the snapshot, not
    # written ahead of a publish that is then refused
    assert os.listdir(os.path.join(root, "charts", "asx")) == ["OLD0.json"]


def test_a_healthy_night_publishes_and_prunes(monkeypatch, tmp_path):
    root = str(tmp_path)
    _seed(root, "asx", 40)                    # 60 tonight >= 0.5 x 40
    monkeypatch.setattr(pm_run, "load_symbols", lambda m: _universe(30))
    _stub_yfinance(monkeypatch, _healthy_frame)
    out = pm_run.run_market("asx", _args(), "2026-10-08", root)
    assert out and sum(out.values()) >= 30
    with open(os.path.join(root, "asx", "latest.json"), encoding="utf-8") as f:
        snap = json.load(f)
    assert snap["run_date"] == "2026-10-08" and len(snap["results"]) >= 30
    charts = set(os.listdir(os.path.join(root, "charts", "asx")))
    assert "OLD0.json" not in charts and "T000.json" in charts


def test_a_limited_test_run_is_not_judged_against_the_full_snapshot(monkeypatch, tmp_path):
    root = str(tmp_path)
    _seed(root, "asx", 400)
    monkeypatch.setattr(pm_run, "load_symbols", lambda m: _universe(30))
    _stub_yfinance(monkeypatch, _healthy_frame)
    out = pm_run.run_market("asx", _args(limit=3), "2026-10-08", root)
    assert out is not None                    # --limit 3: a deliberate quick test


def test_publish_refusal_rules():
    r = pm_run.publish_refusal
    assert r(0, 30, 0, None, True)                       # nothing fetched: always
    assert r(0, 30, 0, None, False)
    assert r(20, 30, 10, 100, True)                      # collapse
    assert r(20, 30, 10, 100, False) is None             # restricted run
    assert r(20, 30, 50, 100, True) is None              # exactly the ratio
    small = CONFIG.publish_collapse_min_prev - 1
    assert r(5, 30, 0, small, True) is None              # too small to judge
    assert r(5, 30, 0, None, True) is None               # no previous file


# ------------------------------------------------------------ audit #8 wiring
def test_a_bar_fetched_before_the_close_stays_forming_after_a_slow_download(
        monkeypatch, tmp_path):
    """run_market drops the forming bar, judged at the instant the download
    STARTED: bars fetched at 15:59 New York are pre-close even if the
    download finishes at 16:10 (audit #8 review, 2026-10-08)."""
    root = str(tmp_path)
    t0 = datetime.datetime(2026, 10, 7, 19, 59, tzinfo=datetime.timezone.utc)
    t1 = datetime.datetime(2026, 10, 7, 20, 10, tzinfo=datetime.timezone.utc)
    clock = {"t": t0}

    class _Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["t"]

    monkeypatch.setattr(pm_run, "datetime",
                        types.SimpleNamespace(datetime=_Clock,
                                              timezone=datetime.timezone))

    def session_frame(chunk):
        clock["t"] = t1                       # the download takes 11 minutes
        bars = synth.fixture1()
        bars["Date"] = pd.bdate_range(end="2026-10-07", periods=len(bars))
        bars = bars.set_index("Date")
        return pd.concat({sym: bars for sym in chunk}, axis=1)

    monkeypatch.setattr(pm_run, "load_symbols", lambda m: _universe(3))
    _stub_yfinance(monkeypatch, session_frame)
    out = pm_run.run_market("nasdaq", _args(), "2026-10-08", root)
    assert out                                 # still scanned and published
    with open(os.path.join(root, "charts", "nasdaq", "T000.json"), encoding="utf-8") as f:
        candles = json.load(f)["candles"]
    assert candles[-1]["t"] == "2026-10-06"    # the 10-07 partial bar is gone

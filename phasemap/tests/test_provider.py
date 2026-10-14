"""YFinanceProvider.fetch_all — Yahoo outage/degenerate-response guards.

Regression for PhaseMap nightly #22 (2026-07-22): a throttled/failed Yahoo
batch returns a DataFrame with NO per-field columns; the old code went
straight to df.dropna(subset=["Open", ...]) and the KeyError killed the whole
market run (red run -> failure email), even though every other batch was
fine. A symbol with no usable columns must be treated exactly like an empty
download: skipped.
"""

import math
import sys
import types

import pandas as pd
import pytest

from phasemap.data.provider import YFinanceProvider


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The recovery sweep cools down before retrying; tests never wait."""
    slept = []
    monkeypatch.setattr("phasemap.data.provider.time.sleep", slept.append)
    return slept


def _stub_yfinance(monkeypatch, frame):
    """Install a fake yfinance module whose download() returns `frame`."""
    calls = []

    def download(chunk, **kwargs):
        calls.append(list(chunk))
        return frame() if callable(frame) else frame

    mod = types.ModuleType("yfinance")
    mod.download = download
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return calls


def _bars(n=5, start="2026-01-05"):
    idx = pd.date_range(start, periods=n, freq="D", name="Date")
    return pd.DataFrame(
        {
            "Open": [1.0] * n,
            "High": [2.0] * n,
            "Low": [0.5] * n,
            "Close": [1.5] * n,
            "Volume": [100] * n,
        },
        index=idx,
    )


def test_whole_batch_failure_is_skipped_not_fatal(monkeypatch):
    # Yahoo outage: multi-symbol chunk comes back as a totally empty frame
    # (flat columns, none of them OHLC).
    _stub_yfinance(monkeypatch, pd.DataFrame())
    p = YFinanceProvider({"AAA": "AAA.AX", "BBB": "BBB.AX"})
    p.fetch_all()  # must not raise
    assert p.get_daily_bars("AAA") is None
    assert p.get_daily_bars("BBB") is None


def test_single_symbol_empty_frame_no_keyerror(monkeypatch):
    # The #22 crash shape: a single-symbol chunk (len(chunk) == 1) where the
    # response has no per-field columns at all. The old code passed the empty
    # frame straight to dropna(subset=[OHLC]) -> KeyError.
    _stub_yfinance(monkeypatch, pd.DataFrame())
    p = YFinanceProvider({"AAA": "AAA.AX"})
    p.fetch_all(chunk_size=1)  # must not raise
    assert p.get_daily_bars("AAA") is None


def test_symbol_with_missing_ohlc_columns_is_skipped(monkeypatch):
    # Degenerate per-ticker slice: symbol key exists but carries no OHLC
    # (e.g. Volume-only) — skip it, keep the healthy symbol.
    good = _bars()
    cols = pd.MultiIndex.from_product([["AAA.AX"], list(good.columns)])
    frame = pd.DataFrame(good.values, index=good.index, columns=cols)
    bad = pd.DataFrame({("BBB.AX", "Volume"): [1, 2, 3]},
                       index=pd.date_range("2026-01-05", periods=3, name="Date"))
    frame = frame.join(bad, how="outer")
    _stub_yfinance(monkeypatch, frame)
    p = YFinanceProvider({"AAA": "AAA.AX", "BBB": "BBB.AX"})
    p.fetch_all()
    assert p.get_daily_bars("AAA") is not None
    assert p.get_daily_bars("BBB") is None


def test_single_symbol_multiindex_response_is_selected(monkeypatch):
    # Newer yfinance returns MultiIndex (ticker, field) columns even for a
    # one-symbol list under group_by="ticker" — the provider must select the
    # symbol's slice rather than treating the frame as flat.
    good = _bars()
    cols = pd.MultiIndex.from_product([["AAA.AX"], list(good.columns)])
    frame = pd.DataFrame(good.values, index=good.index, columns=cols)
    _stub_yfinance(monkeypatch, frame)
    p = YFinanceProvider({"AAA": "AAA.AX"})
    p.fetch_all(chunk_size=1)
    bars = p.get_daily_bars("AAA")
    assert bars is not None and len(bars) == 5
    assert list(bars.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]


def test_healthy_multi_symbol_batch_still_caches_and_drops_nan(monkeypatch):
    a, b = _bars(), _bars()
    b.iloc[0, b.columns.get_loc("Close")] = float("nan")  # one unusable row
    frame = pd.concat({"AAA.AX": a, "BBB.AX": b}, axis=1)
    _stub_yfinance(monkeypatch, frame)
    p = YFinanceProvider({"AAA": "AAA.AX", "BBB": "BBB.AX"})
    p.fetch_all()
    assert len(p.get_daily_bars("AAA")) == 5
    assert len(p.get_daily_bars("BBB")) == 4  # NaN row dropped, not fatal


def test_a_dead_feed_is_fetched_once_not_once_per_ticker(monkeypatch):
    """REFINE200 #199: get_daily_bars lazily fetched whenever the CACHE was
    empty, so after an outage every ticker in run.py's loop re-downloaded
    the whole universe (300 tickers: 4 calls became 1,204). The attempt is
    what is remembered now, not its success."""
    calls = _stub_yfinance(monkeypatch, pd.DataFrame())
    syms = {f"T{i:03d}": f"T{i:03d}.AX" for i in range(300)}
    p = YFinanceProvider(syms)
    p.fetch_all()
    for t in p.universe():
        assert p.get_daily_bars(t) is None
    assert len(calls) == math.ceil(300 / 75)      # no sweep on a TOTAL outage
    assert p.fetched() == 0


def test_get_daily_bars_still_fetches_lazily_when_nobody_called_fetch_all(monkeypatch):
    calls = _stub_yfinance(monkeypatch, pd.concat({"AAA.AX": _bars()}, axis=1))
    p = YFinanceProvider({"AAA": "AAA.AX"})
    assert p.get_daily_bars("AAA") is not None
    assert p.get_daily_bars("AAA") is not None
    assert len(calls) == 1


def test_a_partial_throttle_gets_one_recovery_sweep(monkeypatch, _no_real_sleep):
    """REFINE200 #45: the swing between 549 and 773 ASX results on identical
    weekend bars was Yahoo starving the back chunks. Symbols a partial pass
    returned empty are asked for once more, after a cooldown."""
    good = pd.concat({"AAA.AX": _bars(), "BBB.AX": _bars()}, axis=1)
    responses = [pd.concat({"AAA.AX": _bars()}, axis=1),   # pass 1 chunk 1
                 pd.DataFrame(),                            # pass 1 chunk 2: throttled
                 good]                                      # the sweep
    calls = _stub_yfinance(monkeypatch, lambda: responses.pop(0))
    p = YFinanceProvider({"AAA": "AAA.AX", "BBB": "BBB.AX"})
    p.fetch_all(chunk_size=1)
    assert calls == [["AAA.AX"], ["BBB.AX"], ["BBB.AX"]]
    assert p.get_daily_bars("BBB") is not None and p.fetched() == 2
    assert len(_no_real_sleep) == 1


def test_a_raising_download_is_an_empty_chunk_not_a_dead_market(monkeypatch):
    def download(chunk, **kwargs):
        if chunk == ["AAA.AX"]:
            raise RuntimeError("YFRateLimitError")
        return pd.concat({chunk[0]: _bars()}, axis=1)
    mod = types.ModuleType("yfinance")
    mod.download = download
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    p = YFinanceProvider({"AAA": "AAA.AX", "BBB": "BBB.AX"})
    p.fetch_all(chunk_size=1)        # must not raise
    assert p.get_daily_bars("AAA") is None
    assert p.get_daily_bars("BBB") is not None

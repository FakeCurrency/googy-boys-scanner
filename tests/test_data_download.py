"""Downloader resilience: a throttled batch (Yahoo 429 / empty result) must
recover via retry + back-off so coverage stays high, instead of discarding a
whole chunk of tickers at the first sign of throttling.
"""

import numpy as np
import pandas as pd

from scanner import data


def _multi_frame(tickers):
    """A yfinance-style group_by='ticker' MultiIndex OHLCV frame."""
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    cols = [(t, f) for t in tickers for f in ("Open", "High", "Low", "Close", "Volume")]
    arr = np.column_stack([np.linspace(10, 12, 300) for _ in cols])
    return pd.DataFrame(arr, index=idx, columns=pd.MultiIndex.from_tuples(cols))


def test_download_recovers_throttled_batches(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda *a: None)   # no real waits
    tickers = [f"T{i}.AX" for i in range(250)]                 # 3 chunks at chunk=120
    calls = {"n": 0}

    def fake_dl(batch, **kw):
        calls["n"] += 1
        if calls["n"] % 2 == 1:            # throttle the first attempt of each batch
            return pd.DataFrame()          # empty = throttled
        return _multi_frame(list(batch))   # retry succeeds

    monkeypatch.setattr(data.yf, "download", fake_dl)
    frames = data.download(tickers)
    assert len(frames) == len(tickers)     # every batch recovered on retry — full coverage


def test_recovery_sweep_reclaims_transiently_throttled(monkeypatch):
    """A batch that fails the whole main pass is re-tried on the recovery sweep —
    so transient throttling doesn't permanently cost coverage."""
    from scanner import config
    monkeypatch.setattr(data.time, "sleep", lambda *a: None)
    tickers = [f"T{i}.AX" for i in range(240)]                 # 2 chunks at 120
    calls = {"b1": 0}

    def fake_dl(batch, **kw):
        if "T0.AX" in batch:                                   # the first chunk
            calls["b1"] += 1
            if calls["b1"] <= config.DATA_RETRIES + 1:         # throttled for the entire main pass
                return pd.DataFrame()
        return _multi_frame(list(batch))

    monkeypatch.setattr(data.yf, "download", fake_dl)
    frames = data.download(tickers)
    assert len(frames) == len(tickers)                         # recovery sweep reclaimed the first chunk
    assert "T0.AX" in frames


def test_download_stays_fast_until_heavy_throttling(monkeypatch):
    """Healthy batches incur no long waits; a long cooldown only kicks in after a
    run of consecutive failures (clear heavy throttling)."""
    from scanner import config
    sleeps = []
    monkeypatch.setattr(data.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: pd.DataFrame())  # everything throttled
    tickers = [f"T{i}.AX" for i in range(config.DATA_CHUNK * 5)]              # 5 dead batches
    assert data.download(tickers) == {}
    # The big recovery cooldown only appears after DATA_HEAVY_AFTER failures in a row.
    assert any(s >= config.DATA_HEAVY_COOLDOWN * 0.7 for s in sleeps)


def test_download_skips_dead_batch_but_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda *a: None)
    tickers = [f"T{i}.AX" for i in range(240)]                 # 2 chunks at chunk=120

    def fake_dl(batch, **kw):
        if "T0.AX" in batch:               # first chunk is permanently throttled
            return pd.DataFrame()
        return _multi_frame(list(batch))

    monkeypatch.setattr(data.yf, "download", fake_dl)
    frames = data.download(tickers)
    assert 0 < len(frames) < len(tickers)  # dead chunk dropped, healthy chunk kept
    assert "T120.AX" in frames and "T0.AX" not in frames

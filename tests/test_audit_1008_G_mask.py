"""Audit 2026-10-08 #10 -- the replay's candidate mask hid weekly-level setups.

`_candidate_mask` claims to be a SUPERSET of the engine's in-play test, so it
can only save work. It was not, for the weekly level: it needed 200 complete
weeks (the engine uses a min(200, n) proxy from week 60) and one empty W-FRI
bucket left a NaN in every window for 200 weeks (the engine drops it). A bar
near only the weekly 200 was never handed to `evaluate`, so the weekly cohort
in every published replay was an under-counted, non-random subset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner import config, vivek
from scanner import vivek_backtest as bt
from scanner.indicators import sma


# ---------------------------------------------------------------- frames

def _frame(n: int, seed: int, gap: tuple[int, int] | None = None, freq: str = "B") -> pd.DataFrame:
    """A deterministic OHLCV random walk (PCG64 is stable across numpy versions)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq=freq)
    px = 100 * np.cumprod(1 + rng.normal(0.0, 0.015, n))
    hi = px * (1 + np.abs(rng.normal(0, 0.008, n)))
    lo = px * (1 - np.abs(rng.normal(0, 0.008, n)))
    op = np.r_[px[0], px[:-1]]
    vol = rng.uniform(5e5, 2e6, n)
    df = pd.DataFrame({"Open": op, "High": np.maximum(hi, np.maximum(op, px)),
                       "Low": np.minimum(lo, np.minimum(op, px)), "Close": px,
                       "Volume": vol}, index=idx)
    if gap:
        df = df.drop(df.index[gap[0]:gap[1]])      # a halt: no rows at all
    return df


def _engine_levels(df: pd.DataFrame, j: int) -> tuple[float | None, float | None]:
    """The weekly and 3-day levels `vivek.evaluate` computes on the slice to j."""
    s = df.iloc[:j + 1]
    w, _n = vivek._weekly_sma200(s)
    d3 = vivek._resample_3day_ohlc(s)
    v3 = (float(sma(d3["Close"], config.VIVEK_SMA).iloc[-1])
          if d3 is not None and len(d3) >= config.VIVEK_SMA else None)
    return w, v3


# ------------------------------------------------------------ #10 the mask

@pytest.mark.parametrize("label,df", [
    # 140 weeks: the engine scores a weekly PROXY level from week 60; the old
    # mask needed 200 complete weeks and was NaN for all of it.
    ("short history", _frame(700, 3)),
    # 280 weeks with a 2-week halt at week ~60: the engine drops the empty
    # buckets; the old mask carried the NaN through 200 weeks of windows.
    ("halted two weeks", _frame(1400, 3, gap=(300, 312))),
    # 24/7 bars with a 3-week hole: weekly AND 3-day buckets go empty.
    ("crypto gap", _frame(1500, 5, gap=(500, 520), freq="D")),
])
def test_the_masks_levels_are_the_engines_levels_bar_for_bar(label, df):
    close = df["Close"]
    wsma = bt._bucket_sma_asof(close, "W-FRI", int(config.VIVEK_MIN_WEEKLY_BARS), proxy=True)
    s3 = bt._bucket_sma_asof(close, "72h", int(config.VIVEK_SMA), proxy=False, origin="epoch")
    checked = 0
    for j in range(config.VIVEK_MIN_HISTORY, len(df), 4):
        w, v3 = _engine_levels(df, j)
        assert (w is None) == (not np.isfinite(wsma[j])), (label, j, "weekly presence")
        if w is not None:
            assert wsma[j] == pytest.approx(w, rel=1e-12), (label, j)
            checked += 1
        assert (v3 is None) == (not np.isfinite(s3[j])), (label, j, "3d presence")
        if v3 is not None:
            assert s3[j] == pytest.approx(v3, rel=1e-12), (label, j)
    assert checked > 50, f"{label}: the frame never reached a weekly level"


def test_a_bar_the_engine_finds_at_the_weekly_level_is_a_candidate():
    """The docstring's promise -- a SUPERSET of the engine's in-play test --
    checked against `evaluate` itself, on a 90-week frame: the engine finds 43
    weekly-PROXY signals on it and the old mask hid 34 of them."""
    df = _frame(450, 4)
    cand = bt._candidate_mask(df)
    weekly = 0
    for j in range(config.VIVEK_MIN_HISTORY, len(df)):
        sig = vivek.evaluate(df.iloc[:j + 1])
        if sig is not None:
            assert cand[j], (j, sig["level_tf"])
            weekly += sig["level_tf"] == "weekly"
    assert weekly, "fixture lost its weekly-level signals"


def test_the_shipped_mask_replays_the_same_trades_as_no_mask_at_all(monkeypatch):
    """The mask may only ever save work. Seed 4 / 450 bars carries weekly-PROXY
    trades the old mask dropped (it replayed 4 of these 7)."""
    df = _frame(450, 4)

    def key(trades):
        return sorted((t["timeframe"], t["entry_date"], t["level_tf"], t["realized_r"])
                      for t in trades)

    shipped = bt.replay_symbol(df, "nasdaq", "X", "X", "Tech")
    monkeypatch.setattr(bt, "_candidate_mask", lambda d: np.ones(len(d), dtype=bool))
    every_bar = bt.replay_symbol(df, "nasdaq", "X", "X", "Tech")
    assert key(shipped) == key(every_bar)
    assert any(t["level_tf"] == "weekly" for t in shipped), "fixture lost its weekly trades"

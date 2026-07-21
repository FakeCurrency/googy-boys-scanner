"""Unit tests for data quality validation."""

import sys
import pathlib
import datetime as dt

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scanner.data import validate_bars, DataQualityError


def _make_df(n: int = 100, last_price: float = 100.0,
             nan_frac: float = 0.0, age_hours: float = 0.5) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame with configurable properties."""
    now = pd.Timestamp.now("UTC")
    idx = pd.date_range(end=now - pd.Timedelta(hours=age_hours), periods=n, freq="h", tz="UTC")
    close = np.full(n, last_price, dtype=float)
    if nan_frac > 0:
        n_nan = max(1, int(n * nan_frac))
        close[-n_nan:] = np.nan
    df = pd.DataFrame({"Open": close, "High": close, "Low": close,
                       "Close": close, "Volume": np.ones(n) * 1000}, index=idx)
    return df


class TestValidateBars:
    def test_good_data_passes(self):
        df = _make_df(n=100)
        validate_bars(df, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

    def test_too_few_bars_raises(self):
        df = _make_df(n=10)
        with pytest.raises(DataQualityError, match="only 10 bars"):
            validate_bars(df, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

    def test_empty_df_raises(self):
        df = pd.DataFrame(columns=["Close"])
        with pytest.raises(DataQualityError, match="empty"):
            validate_bars(df, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

    def test_none_raises(self):
        with pytest.raises(DataQualityError, match="empty"):
            validate_bars(None, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

    def test_excessive_nans_raises(self):
        df = _make_df(n=100, nan_frac=0.15)
        with pytest.raises(DataQualityError, match="NaN"):
            validate_bars(df, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

    def test_stale_data_raises(self):
        df = _make_df(n=100, age_hours=6)
        with pytest.raises(DataQualityError, match="stale"):
            validate_bars(df, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

    def test_daily_bars_skip_staleness_check(self):
        # Daily bars are always "stale" by intraday standards — check should be skipped
        df = _make_df(n=200, age_hours=20)
        validate_bars(df, symbol="TEST", interval="1d", min_bars=10, staleness_hours=4)

    def test_invalid_last_price_raises(self):
        df = _make_df(n=100, last_price=float("nan"))
        with pytest.raises(DataQualityError):
            validate_bars(df, symbol="TEST", interval="1h", min_bars=65, staleness_hours=4)

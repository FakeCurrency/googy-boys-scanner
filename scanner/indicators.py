"""Technical indicators built on pandas OHLCV frames.

Frames are expected to have columns: Open, High, Low, Close, Volume.
"""

import pandas as pd

from . import config


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (recursive form, no warm-up bias)."""
    return series.ewm(span=span, adjust=False).mean()


def ema_ladder(df: pd.DataFrame) -> dict[int, pd.Series]:
    """EMA series for every period in the Fibonacci ladder."""
    return {p: ema(df["Close"], p) for p in config.EMA_PERIODS}


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def supertrend(df: pd.DataFrame, period: int = 14, mult: float = 3.0) -> pd.Series:
    """SuperTrend trailing line (used for the Phase-2 trailing-stop display)."""
    atr_ = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = hl2 + mult * atr_
    lower = hl2 - mult * atr_
    close = df["Close"]

    final_upper = upper.copy()
    final_lower = lower.copy()
    st = pd.Series(index=df.index, dtype="float64")
    going_up = True

    for i in range(len(df)):
        if i == 0:
            st.iat[i] = lower.iat[i]
            continue
        final_upper.iat[i] = (
            upper.iat[i]
            if (upper.iat[i] < final_upper.iat[i - 1] or close.iat[i - 1] > final_upper.iat[i - 1])
            else final_upper.iat[i - 1]
        )
        final_lower.iat[i] = (
            lower.iat[i]
            if (lower.iat[i] > final_lower.iat[i - 1] or close.iat[i - 1] < final_lower.iat[i - 1])
            else final_lower.iat[i - 1]
        )
        if going_up and close.iat[i] < final_lower.iat[i]:
            going_up = False
        elif not going_up and close.iat[i] > final_upper.iat[i]:
            going_up = True
        st.iat[i] = final_lower.iat[i] if going_up else final_upper.iat[i]

    return st


def pivot_highs(df: pd.DataFrame, window: int = 3) -> pd.Series:
    """Local maxima of High: a bar whose High is >= the `window` bars on each side."""
    high = df["High"]
    cond = pd.Series(True, index=df.index)
    for k in range(1, window + 1):
        cond &= (high >= high.shift(k)) & (high >= high.shift(-k))
    return high[cond]


def pivot_lows(df: pd.DataFrame, window: int = 3) -> pd.Series:
    """Local minima of Low: a bar whose Low is <= the `window` bars on each side."""
    low = df["Low"]
    cond = pd.Series(True, index=df.index)
    for k in range(1, window + 1):
        cond &= (low <= low.shift(k)) & (low <= low.shift(-k))
    return low[cond]

"""Technical indicators built on pandas OHLCV frames.

Frames are expected to have columns: Open, High, Low, Close, Volume.
"""

import pandas as pd

from . import config


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average (recursive form, no warm-up bias)."""
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window).mean()


def weekly_ema_state(df: pd.DataFrame) -> tuple[float, float, float] | None:
    """Weekly (W-FRI) higher-timeframe EMA stack: (last_close, fast_ema, slow_ema).

    Returns None when the frame can't be resampled or has too little weekly
    history for a stable stack. Shared by the bullish (signals.py) and bearish
    (short.py) HTF-confirmation chips so the resample + EMA lives in one place;
    each caller just compares the three values in its own direction.
    """
    try:
        wk = df["Close"].resample("W-FRI").last().dropna()
    except Exception:
        return None
    if len(wk) < config.WEEKLY_SLOW + 2:
        return None
    fast = float(ema(wk, config.WEEKLY_FAST).iloc[-1])
    slow = float(ema(wk, config.WEEKLY_SLOW).iloc[-1])
    return float(wk.iloc[-1]), fast, slow


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(100)


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


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength (0=flat, 25+=trending, 50+=strong)."""
    high, low = df["High"], df["Low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    # When +DM and -DM both positive, only the larger one counts; an exact tie
    # zeroes both (standard DMI rule). Compare against snapshots so the
    # reassignment of plus_dm doesn't change the minus_dm comparison.
    _pdm, _mdm = plus_dm, minus_dm
    plus_dm  = _pdm.where(_pdm > _mdm, 0.0)
    minus_dm = _mdm.where(_mdm > _pdm, 0.0)

    atr_ = atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_.replace(0, float("nan"))

    di_sum = (plus_di + minus_di).replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)

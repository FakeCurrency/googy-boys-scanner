"""Technical indicators built on pandas OHLCV frames.

Frames are expected to have columns: Open, High, Low, Close, Volume.
"""

import numpy as np
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
    """Wilder's RSI. NaN where RSI is genuinely undefined, rather than 100.

    TOP100 #71. The old tail was ``.fillna(100)``, and the division above sends
    THREE unrelated situations into that NaN — so all three came out of this
    function reading "maximally overbought", which is right for exactly one of
    them:

    * **warm-up** — ``series.diff()`` is NaN on the first bar, so both averages
      are NaN there. RSI does not exist yet. Reported 100.
    * **no losses in the window** (``avg_loss == 0``, ``avg_gain > 0``) — RSI
      really is 100. This is the one the fill was written for, and it is kept,
      but it is now stated as its own rule instead of arriving as a side effect
      of ``replace(0, nan)``.
    * **a flat or halted series** (``avg_loss == 0`` AND ``avg_gain == 0``) — a
      price that has not moved at all. Reported 100: the single most extreme
      reading the indicator can produce, for the least eventful thing a price
      can do. Now NaN.

    The mask is written on the AVERAGES rather than on the output because that
    is where the three cases are still distinguishable; by the time they are NaN
    in ``out`` they are indistinguishable, which is precisely how one fill came
    to cover all three.

    **No live behaviour changes** (verified, not assumed): the two consumers —
    ``spec.py`` and ``reversal.py`` — both do ``rsi > rsi_ma``, ``rsi >
    rsi[-3]`` and ``lo <= rsi <= hi``, and every one of those is False against
    NaN just as it was against the old 100 (100 > 100 is False, and 100 is
    outside both bands). A halted name failed the RSI chip before and fails it
    now. What changes is that a NaN can no longer be mistaken for a reading by
    something new that consumes this series later.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out = 100 - 100 / (1 + rs)
    return out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)


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
    """SuperTrend trailing line (used for the Phase-2 trailing-stop display).

    TOP100 #73. The bands below ARE vectorised; the trailing line is not, and
    cannot be. Each final band is a running min/max whose RESET CONDITION reads
    the running value itself (`close[i-1] > final_upper[i-1]`), and the direction
    latch reads both finished bands, so bar i is not computable without bar i-1.
    What made it cost 100 ms a frame was never the recurrence -- it was doing the
    recurrence through `Series.iat`, ~7 pandas element lookups a bar over 1,300
    bars for every name in the universe (~3.7 min of an ASX scan). It now runs
    over plain numpy scalars: the same operations in the same order on the same
    float64 values, so the output is BIT-IDENTICAL, which is the only acceptable
    outcome for a line that sets trailing stops.
    `tests/test_engine_truth.py` pins that against a frozen copy of the old loop.
    """
    atr_ = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = np.asarray(hl2 + mult * atr_, dtype="float64")
    lower = np.asarray(hl2 - mult * atr_, dtype="float64")
    close = np.asarray(df["Close"], dtype="float64")

    n = len(df)
    st = np.full(n, np.nan, dtype="float64")
    if n:
        # NaN fails every comparison below, exactly as it did through `.iat` --
        # a NaN band therefore carries the previous one forward and never flips
        # the latch, rather than raising or silently reversing the trail.
        final_upper = upper[0]
        final_lower = lower[0]
        going_up = True
        st[0] = final_lower
        for i in range(1, n):
            prev_close = close[i - 1]
            if upper[i] < final_upper or prev_close > final_upper:
                final_upper = upper[i]
            if lower[i] > final_lower or prev_close < final_lower:
                final_lower = lower[i]
            if going_up and close[i] < final_lower:
                going_up = False
            elif not going_up and close[i] > final_upper:
                going_up = True
            st[i] = final_lower if going_up else final_upper

    return pd.Series(st, index=df.index, dtype="float64")


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

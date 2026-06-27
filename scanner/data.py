"""Batched OHLCV download from Yahoo Finance via yfinance."""

import datetime as dt
import logging
import time

import numpy as np
import pandas as pd
import yfinance as yf

from . import config

log = logging.getLogger(__name__)

# The full ASX universe has many thin/suspended names; silence yfinance's noisy
# per-ticker "possibly delisted" warnings — we skip those tickers anyway.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


class DataQualityError(Exception):
    """Raised when downloaded OHLCV data fails quality checks."""


def validate_bars(df: pd.DataFrame, symbol: str = "", interval: str = "1h",
                  min_bars: int | None = None, staleness_hours: float | None = None) -> None:
    """Check downloaded OHLCV for common quality problems.

    Raises DataQualityError with a human-readable reason.
    Callers can catch this to skip the ticker or log a warning.
    """
    min_bars = min_bars or config.SCALP_DATA_MIN_BARS
    staleness_hours = staleness_hours or config.DATA_STALENESS_HOURS

    if df is None or len(df) == 0:
        raise DataQualityError(f"{symbol}: empty dataframe")

    if len(df) < min_bars:
        raise DataQualityError(
            f"{symbol}: only {len(df)} bars (need {min_bars})"
        )

    close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
    nan_frac = close.isna().mean()
    if nan_frac > 0.1:
        raise DataQualityError(
            f"{symbol}: {nan_frac:.0%} of Close values are NaN"
        )

    last_val = close.dropna().iloc[-1] if not close.dropna().empty else None
    if last_val is None or not np.isfinite(last_val) or last_val <= 0:
        raise DataQualityError(f"{symbol}: last close is invalid ({last_val!r})")

    # Staleness check — only meaningful for intraday data
    if interval in ("1m", "5m", "15m", "30m", "1h"):
        idx = df.index
        if hasattr(idx, "tz") and idx.tz is None:
            last_ts = pd.Timestamp(idx[-1], tz="UTC")
        else:
            last_ts = pd.Timestamp(idx[-1]).tz_convert("UTC") if idx.tz else pd.Timestamp(idx[-1], tz="UTC")
        now_utc = pd.Timestamp.now("UTC")
        age_hours = (now_utc - last_ts).total_seconds() / 3600
        if age_hours > staleness_hours:
            raise DataQualityError(
                f"{symbol}: last bar is {age_hours:.1f}h old (stale, limit={staleness_hours}h)"
            )


def download(tickers: list[str], period: str | None = None,
             interval: str = "1d", chunk: int = 150, retries: int = 2) -> dict[str, pd.DataFrame]:
    """Download OHLCV for many tickers, returned as {ticker: DataFrame}.

    Pass interval="1h" (with period="60d") for intraday scalp data.
    Tickers are fetched in chunks with simple retry/back-off.
    """
    period = period or config.DATA_PERIOD
    frames: dict[str, pd.DataFrame] = {}
    failed_batches = 0        # whole batches that yielded nothing after retries
    skipped_tickers = 0       # individual tickers with no usable rows

    for start in range(0, len(tickers), chunk):
        if start:
            time.sleep(0.1)
        batch = tickers[start:start + chunk]
        data = None
        for attempt in range(retries + 1):
            try:
                data = yf.download(
                    batch, period=period, interval=interval,
                    group_by="ticker", auto_adjust=True,
                    threads=True, progress=False,
                )
                break
            except Exception as e:
                log.warning("batch download attempt %d/%d failed: %s: %s",
                            attempt + 1, retries + 1, type(e).__name__, e)
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))

        # Whole-batch failure: every ticker in this slice is unavailable this run.
        # Record it so the caller's logs show source degradation instead of a
        # silently short result set.
        if data is None or len(data) == 0:
            failed_batches += 1
            skipped_tickers += len(batch)
            log.warning("batch %d-%d (%d tickers) returned no data — skipping",
                        start, start + len(batch), len(batch))
            continue

        for ticker in batch:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    df = data[ticker].copy()
                else:
                    df = data.copy()
                df = df.dropna()
                if len(df):
                    frames[ticker] = df
                else:
                    skipped_tickers += 1
            except Exception as e:
                skipped_tickers += 1
                log.warning("%s: %s: %s", ticker, type(e).__name__, e)
                continue

    # One-line health summary — makes "the data source is failing" obvious at a
    # glance instead of having to infer it from a thin result set downstream.
    got = len(frames)
    if got < len(tickers):
        log.info("download: %d/%d tickers returned (%d skipped, %d batches failed)",
                 got, len(tickers), skipped_tickers, failed_batches)
    if tickers and got == 0:
        log.error("download: ZERO tickers returned for %d requested — upstream data source likely down",
                  len(tickers))

    return frames

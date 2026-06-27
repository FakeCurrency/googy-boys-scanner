"""Batched OHLCV download from Yahoo Finance via yfinance."""

import datetime as dt
import logging
import random
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


def _fetch_batch(batch: list[str], period: str, interval: str,
                 retries: int, backoff: list[float]) -> pd.DataFrame | None:
    """Download one batch, retrying with an escalating back-off on failure.

    Yahoo throttles bursty requests (429). A short 2–4s wait isn't enough to
    recover, so each retry waits progressively longer (config.DATA_BACKOFF, with
    jitter) before re-requesting the SAME batch — patience keeps coverage high
    rather than discarding 100+ tickers at the first sign of throttling.
    """
    for attempt in range(retries + 1):
        try:
            data = yf.download(
                batch, period=period, interval=interval,
                group_by="ticker", auto_adjust=True,
                threads=True, progress=False,
            )
            if data is not None and len(data):
                return data
            reason = "empty result (likely throttled)"
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
        if attempt < retries:
            wait = backoff[min(attempt, len(backoff) - 1)] * (0.8 + 0.4 * random.random())
            log.warning("batch attempt %d/%d failed (%s) — backing off %.1fs",
                        attempt + 1, retries + 1, reason, wait)
            time.sleep(wait)
    return None


def download(tickers: list[str], period: str | None = None,
             interval: str = "1d", chunk: int | None = None,
             retries: int | None = None) -> dict[str, pd.DataFrame]:
    """Download OHLCV for many tickers, returned as {ticker: DataFrame}.

    Pass interval="1h" (with period="60d") for intraday scalp data. Tickers are
    fetched in small chunks, with a brief pause between them and a long
    escalating back-off when a batch is throttled, so a full ASX-sized universe
    keeps high coverage even when Yahoo rate-limits.
    """
    period = period or config.DATA_PERIOD
    chunk = chunk or config.DATA_CHUNK
    retries = config.DATA_RETRIES if retries is None else retries
    backoff = config.DATA_BACKOFF
    pause = config.DATA_BATCH_PAUSE

    frames: dict[str, pd.DataFrame] = {}
    failed_batches = 0        # whole batches that yielded nothing after retries
    skipped_tickers = 0       # individual tickers with no usable rows
    n_batches = (len(tickers) + chunk - 1) // chunk

    for bi, start in enumerate(range(0, len(tickers), chunk)):
        if start:
            time.sleep(pause * (0.6 + 0.8 * random.random()))   # gentle, jittered spacing
        batch = tickers[start:start + chunk]
        data = _fetch_batch(batch, period, interval, retries, backoff)

        # Whole-batch failure: every ticker in this slice is unavailable this run.
        if data is None or len(data) == 0:
            failed_batches += 1
            skipped_tickers += len(batch)
            log.warning("batch %d/%d (%d tickers) returned no data after %d attempts — skipping",
                        bi + 1, n_batches, len(batch), retries + 1)
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
    cov = 100.0 * got / len(tickers) if tickers else 0.0
    log.info("download: %d/%d tickers (%.0f%% coverage, %d skipped, %d batches failed)",
             got, len(tickers), cov, skipped_tickers, failed_batches)
    if tickers and got == 0:
        log.error("download: ZERO tickers returned for %d requested — upstream data source likely down",
                  len(tickers))

    return frames

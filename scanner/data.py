"""Batched OHLCV download from Yahoo Finance via yfinance."""

import logging
import time

import pandas as pd
import yfinance as yf

from . import config

# The full ASX universe has many thin/suspended names; silence yfinance's noisy
# per-ticker "possibly delisted" warnings — we skip those tickers anyway.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def download(tickers: list[str], period: str | None = None,
             chunk: int = 75, retries: int = 2) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV for many tickers, returned as {ticker: DataFrame}.

    Tickers are fetched in chunks (kinder to Yahoo's endpoint) with simple
    retry/back-off. Tickers that fail or come back empty are silently skipped.
    Larger chunks = fewer round-trips = faster, while staying within Yahoo's
    tolerance (it serves the whole batch in one request).
    """
    period = period or config.DATA_PERIOD
    frames: dict[str, pd.DataFrame] = {}

    for start in range(0, len(tickers), chunk):
        if start:
            time.sleep(0.3)  # be gentle across many batches (full ASX ~27 chunks)
        batch = tickers[start:start + chunk]
        data = None
        for attempt in range(retries + 1):
            try:
                data = yf.download(
                    batch, period=period, interval="1d",
                    group_by="ticker", auto_adjust=True,
                    threads=True, progress=False,
                )
                break
            except Exception:
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))

        if data is None or len(data) == 0:
            continue

        for ticker in batch:
            try:
                # yfinance returns MultiIndex (ticker, field) columns when grouping;
                # extract the ticker's frame. A single-ticker download may be flat.
                if isinstance(data.columns, pd.MultiIndex):
                    df = data[ticker]
                else:
                    df = data
                df = df.dropna()
                if len(df):
                    frames[ticker] = df
            except Exception:
                continue

    return frames

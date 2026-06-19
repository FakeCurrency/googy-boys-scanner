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
             interval: str = "1d", chunk: int = 75, retries: int = 2) -> dict[str, pd.DataFrame]:
    """Download OHLCV for many tickers, returned as {ticker: DataFrame}.

    Pass interval="1h" (with period="60d") for intraday scalp data.
    Tickers are fetched in chunks with simple retry/back-off.
    """
    period = period or config.DATA_PERIOD
    frames: dict[str, pd.DataFrame] = {}

    for start in range(0, len(tickers), chunk):
        if start:
            time.sleep(0.3)
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
                print(f"  warning: batch download attempt {attempt + 1} failed: "
                      f"{type(e).__name__}: {e}", flush=True)
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))

        if data is None or len(data) == 0:
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
            except Exception as e:
                print(f"  warning: {ticker}: {type(e).__name__}: {e}", flush=True)
                continue

    return frames

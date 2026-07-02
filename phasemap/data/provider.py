"""Provider-agnostic daily-bar data layer.

Contract: get_daily_bars(ticker) returns an ascending DataFrame with columns
Date, Open, High, Low, Close, Volume (split-adjusted), or None.

YFinanceProvider is for PROTOTYPING ONLY (spec Section 9) — unreliable on ASX
microcaps; never ship the product on it. The production provider (EODHD /
Norgate) drops in behind the same interface.
"""

import pandas as pd


class FrameProvider:
    """In-memory provider for tests, fixtures and backtests."""

    def __init__(self, frames: dict):
        self._frames = dict(frames)

    def universe(self):
        return sorted(self._frames)

    def get_daily_bars(self, ticker: str):
        return self._frames.get(ticker)


class YFinanceProvider:
    """Prototype provider. `symbols` maps display ticker -> Yahoo symbol
    (e.g. {"BHP": "BHP.AX", "AAPL": "AAPL", "BTC": "BTC-USD"})."""

    def __init__(self, symbols: dict, period: str = "2y"):
        self._symbols = dict(symbols)
        self._period = period
        self._cache = {}

    def universe(self):
        return sorted(self._symbols)

    def fetch_all(self, chunk_size: int = 75):
        import yfinance as yf
        by_yf = {yf_sym: t for t, yf_sym in self._symbols.items()}
        yf_syms = sorted(by_yf)
        for start in range(0, len(yf_syms), chunk_size):
            chunk = yf_syms[start:start + chunk_size]
            data = yf.download(chunk, period=self._period, interval="1d",
                               auto_adjust=True, group_by="ticker",
                               progress=False, threads=True)
            for sym in chunk:
                try:
                    df = data[sym] if len(chunk) > 1 else data
                except KeyError:
                    continue
                df = df.dropna(subset=["Open", "High", "Low", "Close"])
                if df.empty:
                    continue
                out = df.reset_index()[["Date", "Open", "High", "Low",
                                        "Close", "Volume"]]
                self._cache[by_yf[sym]] = out

    def get_daily_bars(self, ticker: str):
        if not self._cache:
            self.fetch_all()
        return self._cache.get(ticker)

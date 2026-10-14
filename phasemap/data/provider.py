"""Provider-agnostic daily-bar data layer.

Contract: get_daily_bars(ticker) returns an ascending DataFrame with columns
Date, Open, High, Low, Close, Volume (split-adjusted), or None.

YFinanceProvider is for PROTOTYPING ONLY (spec Section 9) — unreliable on ASX
microcaps; never ship the product on it. The production provider (EODHD /
Norgate) drops in behind the same interface.
"""

import time

import pandas as pd

from phasemap.config import FETCH_RECOVERY_COOLDOWN_S


class FrameProvider:
    """In-memory provider for tests, fixtures and backtests."""

    def __init__(self, frames: dict):
        self._frames = dict(frames)

    def universe(self):
        return sorted(self._frames)

    def fetch_all(self):
        """Nothing to fetch — the frames are already in memory. Present so
        run.py drives either provider through the same calls."""

    def fetched(self) -> int:
        return sum(1 for df in self._frames.values() if df is not None and len(df))

    def get_daily_bars(self, ticker: str):
        return self._frames.get(ticker)


class YFinanceProvider:
    """Prototype provider. `symbols` maps display ticker -> Yahoo symbol
    (e.g. {"BHP": "BHP.AX", "AAPL": "AAPL", "BTC": "BTC-USD"})."""

    def __init__(self, symbols: dict, period: str = "2y",
                 recovery_cooldown_s: float = FETCH_RECOVERY_COOLDOWN_S,
                 sleep=None):
        self._symbols = dict(symbols)
        self._period = period
        self._cache = {}
        # REFINE200 #199: set by fetch_all even when it caches NOTHING. The
        # lazy fetch in get_daily_bars used to key off an empty cache, so on a
        # dead feed every ticker in run.py's loop re-downloaded the whole
        # universe (ASX: ~26 chunks per ticker x ~1,900 tickers = ~50,000
        # yf.download calls while Yahoo was throttling).
        self._fetched = False
        self._recovery_cooldown_s = recovery_cooldown_s
        self._sleep = sleep          # None = time.sleep, looked up at call time

    def universe(self):
        return sorted(self._symbols)

    def fetched(self) -> int:
        """Tickers that came back with usable bars — the coverage run.py's
        publish floor (REFINE200 #197) is measured on."""
        return len(self._cache)

    def _download_pass(self, yf_syms: list, by_yf: dict, chunk_size: int) -> list:
        """One pass in chunks; returns the Yahoo symbols that came back unusable."""
        import yfinance as yf
        missing = []
        for start in range(0, len(yf_syms), chunk_size):
            chunk = yf_syms[start:start + chunk_size]
            try:
                data = yf.download(chunk, period=self._period, interval="1d",
                                   auto_adjust=True, group_by="ticker",
                                   progress=False, threads=True)
            except Exception as e:   # a raising chunk is an empty chunk, not a dead market
                print(f"  yfinance chunk {start // chunk_size + 1} raised "
                      f"{type(e).__name__}: {e}")
                missing.extend(chunk)
                continue
            for sym in chunk:
                try:
                    # group_by="ticker" gives MultiIndex columns whenever the
                    # response is per-ticker keyed — select our symbol; a flat
                    # frame is only valid for a single-symbol chunk.
                    if isinstance(data.columns, pd.MultiIndex) or len(chunk) > 1:
                        df = data[sym]
                    else:
                        df = data
                except (KeyError, IndexError):
                    missing.append(sym)
                    continue
                # Yahoo outage/throttle guard (2026-07-22, PhaseMap nightly
                # #22): a failed batch comes back as a frame with NO per-field
                # columns at all — dropna(subset=...) then raises KeyError and
                # kills the whole market run. No usable columns = an empty
                # download for this symbol: skip it like the df.empty case.
                if df is None or df.empty or \
                        not {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
                    missing.append(sym)
                    continue
                df = df.dropna(subset=["Open", "High", "Low", "Close"])
                if df.empty:
                    missing.append(sym)
                    continue
                out = df.reset_index()[["Date", "Open", "High", "Low",
                                        "Close", "Volume"]]
                self._cache[by_yf[sym]] = out
        return missing

    def fetch_all(self, chunk_size: int = 75):
        """Download the universe, then ONE recovery sweep over what failed.

        The sweep runs only when the first pass got SOME data (partial
        throttling); a total outage is not retried here — run.py's coverage
        floor reports it. REFINE200 #45: on 2026-10-10..12 Yahoo starved the
        back third of the ASX chunks, so the same Friday bars published 549,
        773 and 475 results on three consecutive nights (every surviving
        chunk scanned identically; the swing was coverage, nothing else).
        """
        self._fetched = True
        by_yf = {yf_sym: t for t, yf_sym in self._symbols.items()}
        yf_syms = sorted(by_yf)
        missing = self._download_pass(yf_syms, by_yf, chunk_size)
        if missing and self._cache and len(missing) < len(yf_syms):
            print(f"  recovery sweep: {len(missing)}/{len(yf_syms)} symbols came back "
                  f"empty - cooling {self._recovery_cooldown_s:.0f}s, retrying once")
            (self._sleep or time.sleep)(self._recovery_cooldown_s)
            before = len(self._cache)
            self._download_pass(sorted(missing), by_yf, chunk_size)
            print(f"  recovery sweep: reclaimed {len(self._cache) - before}/{len(missing)}")

    def get_daily_bars(self, ticker: str):
        if not self._fetched:
            self.fetch_all()
        return self._cache.get(ticker)

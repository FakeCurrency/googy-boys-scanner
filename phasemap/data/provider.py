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
    (e.g. {"BHP": "BHP.AX", "AAPL": "AAPL", "BTC": "BTC-USD"}).

    `ref_prices` {display ticker: CoinGecko price} arms the IDENTITY CHECK
    (2026-09-28). A ticker is not an identity: measured from a runner, Yahoo's
    AERO-USD sat +2,623,839% off Binance's AEROUSDT, JUP +96,729%, ARB
    +35,210%, PRL, SKY, XCN, EDGE, MET -43% -- DIFFERENT TOKENS under the
    CoinGecko coin's symbol, so PhaseMap was mapping sweeps and zones on the
    wrong instrument. A series whose latest close is not within
    scanner.config.CRYPTO_IDENTITY_TOL of the reference is NOT served, and is
    named in `identity_rejected` ({ticker: ["yahoo"]}, the shape data.fetch
    reports). This is a data-integrity reject at the provider boundary, not
    a detection change: no spec maths, zone or threshold moves. No reference
    (stocks, or a coin CoinGecko gave no price for) checks nothing."""

    def __init__(self, symbols: dict, period: str = "2y", ref_prices: dict = None):
        self._symbols = dict(symbols)
        self._period = period
        self._cache = {}
        self._refs = {t: v for t, v in (ref_prices or {}).items() if v is not None}
        self.identity_rejected = {}

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
                    # group_by="ticker" gives MultiIndex columns whenever the
                    # response is per-ticker keyed — select our symbol; a flat
                    # frame is only valid for a single-symbol chunk.
                    if isinstance(data.columns, pd.MultiIndex) or len(chunk) > 1:
                        df = data[sym]
                    else:
                        df = data
                except (KeyError, IndexError):
                    continue
                # Yahoo outage/throttle guard (2026-07-22, PhaseMap nightly
                # #22): a failed batch comes back as a frame with NO per-field
                # columns at all — dropna(subset=...) then raises KeyError and
                # kills the whole market run. No usable columns = an empty
                # download for this symbol: skip it like the df.empty case.
                if df is None or df.empty or \
                        not {"Open", "High", "Low", "Close", "Volume"}.issubset(df.columns):
                    continue
                df = df.dropna(subset=["Open", "High", "Low", "Close"])
                if df.empty:
                    continue
                out = df.reset_index()[["Date", "Open", "High", "Low",
                                        "Close", "Volume"]]
                t = by_yf[sym]
                if t in self._refs and not _same_coin(out, self._refs[t]):
                    self.identity_rejected[t] = ["yahoo"]
                    continue
                self._cache[t] = out
        self.identity_rejected = dict(sorted(self.identity_rejected.items()))

    def get_daily_bars(self, ticker: str):
        if not self._cache:
            self.fetch_all()
        return self._cache.get(ticker)


def _same_coin(df, ref) -> bool:
    """The house identity check (scanner/exchange_data.same_coin -- the one
    the VIVEK scan, the bot and every other lens apply), imported lazily so
    the in-memory FrameProvider path stays free of the scanner package."""
    from scanner.exchange_data import same_coin
    return same_coin(df, ref)

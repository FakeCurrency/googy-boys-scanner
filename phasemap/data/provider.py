"""Provider-agnostic daily-bar data layer.

Contract: get_daily_bars(ticker) returns an ascending DataFrame with columns
Date, Open, High, Low, Close, Volume (split-adjusted), or None.

YFinanceProvider is for PROTOTYPING ONLY (spec Section 9) — unreliable on ASX
microcaps; never ship the product on it. The production provider (EODHD /
Norgate) drops in behind the same interface.

FetchProvider (2026-09-28, owner-approved: "Move to exchange") is how CRYPTO
is read: the house `scanner.data.fetch` -- exchange daily klines (Binance's
mirror, then Coinbase), Yahoo only for coins no exchange lists, every source
held to CoinGecko's price for the coin -- the same bars the VIVEK scan, the
paper bot and every other lens read. Stocks stay on YFinanceProvider.
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


class FetchProvider:
    """Crypto provider over `scanner.data.fetch` (owner, 2026-09-28: PhaseMap
    crypto "Move to exchange", following his VIVEK ruling "so it's all in
    SYNC"). Same contract as YFinanceProvider -- `universe()`, `fetch_all()`,
    `get_daily_bars(ticker)` -> Date/Open/High/Low/Close/Volume ascending --
    so the engine cannot tell them apart. Detection maths are untouched; only
    WHICH instrument's bars reach them changes: Yahoo's AERO/JUP/ARB/PRL/SKY/
    XCN/EDGE/MET were different tokens (measured from a runner), and an
    exchange-listed one (ARB, JUP...) is now scanned as the right coin rather
    than dropped.

    `identity_rejected` {ticker: [venues]} names the coins nothing confirmed
    (left out); `source_of` {ticker: venue} says where each served series came
    from (the scan stamps it on its rows as `data_source`, which the chart
    reads to draw the SAME series); `report` is the full fetch report. The
    identity check is also re-applied here after the fetch, so it holds even
    with scanner.config.CRYPTO_DATA_SOURCE reverted to "yahoo" (where `fetch`
    itself checks nothing): a revert of the venue must not re-open the
    wrong-token hole in this lens.
    """

    def __init__(self, market: str, symbols: dict, period: str = "2y",
                 ref_prices: dict = None):
        self._market = market
        self._symbols = dict(symbols)
        self._period = period
        self._refs = {t: v for t, v in (ref_prices or {}).items() if v is not None}
        self._cache = {}
        self._fetched = False
        self.identity_rejected = {}
        self.source_of = {}
        self.report = {}

    def universe(self):
        return sorted(self._symbols)

    def fetch_all(self):
        from scanner import config as house
        from scanner import data as sdata
        by_yf = {yf_sym: t for t, yf_sym in self._symbols.items()}
        yf_refs = {self._symbols[t]: v for t, v in self._refs.items() if t in self._symbols}
        frames, report = sdata.fetch(self._market, sorted(by_yf), period=self._period,
                                     ref_prices=yf_refs)
        self._fetched = True
        self.report = report
        # fetch keys its rejections by the BASE symbol ("ARB" for ARB-USD)
        sfx = getattr(house.MARKETS.get(self._market), "suffix", "") or ""
        base_to_t = {(yf_sym[:-len(sfx)] if sfx and yf_sym.endswith(sfx) else yf_sym).upper(): t
                     for yf_sym, t in by_yf.items()}
        rejected = {base_to_t.get(str(b).upper(), str(b)): list(v)
                    for b, v in (report.get("identity_rejected") or {}).items()}
        src_of = report.get("source_of") or {}
        for yf_sym, f in frames.items():
            t = by_yf.get(yf_sym)
            if t is None or f is None or f.empty or \
                    not {"Open", "High", "Low", "Close", "Volume"}.issubset(f.columns):
                continue
            src = src_of.get(yf_sym, "yahoo")
            if t in self._refs and not _same_coin(f, self._refs[t]):
                rejected.setdefault(t, []).append(src)
                continue
            df = f.dropna(subset=["Open", "High", "Low", "Close"])
            if df.empty:
                continue
            out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            out.insert(0, "Date", pd.DatetimeIndex(df.index))
            self._cache[t] = out.reset_index(drop=True)
            self.source_of[t] = src
        # LEFT OUT only: a coin one venue refused but a later source confirmed
        # is served (its data_source says which) -- listing it here would
        # publish a scanned coin as a gap (XMR: Binance's stale series refused,
        # Yahoo's Monero used; measured 2026-09-28).
        self.identity_rejected = dict(sorted((t, v) for t, v in rejected.items()
                                             if t not in self._cache))

    def get_daily_bars(self, ticker: str):
        if not self._fetched:
            self.fetch_all()
        return self._cache.get(ticker)


def _same_coin(df, ref) -> bool:
    """The house identity check (scanner/exchange_data.same_coin -- the one
    the VIVEK scan, the bot and every other lens apply), imported lazily so
    the in-memory FrameProvider path stays free of the scanner package."""
    from scanner.exchange_data import same_coin
    return same_coin(df, ref)

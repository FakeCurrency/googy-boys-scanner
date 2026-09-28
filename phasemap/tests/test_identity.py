"""PhaseMap's crypto source + identity check (2026-09-28).

A ticker is not an identity. Measured from a GitHub runner
(scripts/crypto_source_compare.py), Yahoo's `<SYM>-USD` is a DIFFERENT TOKEN
from the CoinGecko top-200 coin of the same symbol for AERO (+2,623,839% vs
Binance), JUP (+96,729%), ARB (+35,210%), PRL, SKY, XCN, EDGE and MET (-43%)
-- so PhaseMap was mapping sweeps and zones on the wrong instrument.

Two changes, neither touching detection maths, zones or thresholds:
  * a data-integrity reject at the provider boundary -- a series whose latest
    close is not CoinGecko's price for the coin is not served, and the coin is
    NAMED in the crypto snapshot's `identity_rejected` (both providers);
  * CRYPTO reads the house `scanner.data.fetch` (FetchProvider): exchange
    klines first, the bars the VIVEK scan and the bot read (owner, asked
    2026-09-28: "Move to exchange"). Stocks stay on YFinanceProvider.
Every test here stubs the venues (conftest.py) and Yahoo explicitly.
"""

import json
import sys
import types
import urllib.error

import pandas as pd
import pytest

from phasemap import run as PR
from phasemap.data.provider import FetchProvider, YFinanceProvider
from scanner import data as SD
from scanner import exchange_data as X
from phasemap.output.writer import (build_snapshot, split_narrations,
                                    validate_published, validate_snapshot)


def _bars(px, n=30, end="2026-09-20"):
    idx = pd.date_range(end=end, periods=n, freq="D", name="Date")
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Volume": 1e6}, index=idx)


def _stub_yahoo(monkeypatch, series: dict):
    """Fake yfinance: per-ticker MultiIndex frame, as group_by="ticker" serves."""
    def download(chunk, **kw):
        got = {s: series[s] for s in chunk if s in series}
        return pd.concat(got, axis=1) if got else pd.DataFrame()

    mod = types.ModuleType("yfinance")
    mod.download = download
    monkeypatch.setitem(sys.modules, "yfinance", mod)


YAHOO = {"ARB-USD": _bars(0.003), "BTC-USD": _bars(100.0), "XMR-USD": _bars(7.0)}
T0 = int(pd.Timestamp("2026-08-22").timestamp() * 1000)


def _klines(px, n=30):
    return [[T0 + i * 86_400_000, str(px), str(px * 1.01), str(px * 0.99), str(px), "1",
             T0 + i * 86_400_000 + 1, "5000000"] for i in range(n)]


@pytest.fixture
def venues(monkeypatch):
    """Binance's mirror lists BTC and ARB -- the RIGHT ARB, at 1.0 -- and
    nothing else; every other venue refuses. Yahoo (via scanner.data.download,
    the Yahoo leg of data.fetch) serves the ~0.003 ARB-USD stranger and XMR."""
    def router(url, timeout):
        if "binance.vision" in url:
            if "BTCUSDT" in url:
                return _klines(100.0)
            if "ARBUSDT" in url:
                return _klines(1.0)
            raise urllib.error.HTTPError(url, 400, "x", None, None)
        raise X.SourceDead("HTTP 451")

    monkeypatch.setattr(X, "_get_json", router)
    asked = []

    def download(tickers, period=None, **kw):
        asked.append(sorted(tickers))
        return {t: YAHOO[t].copy() for t in tickers if t in YAHOO}

    monkeypatch.setattr(SD, "download", download)
    return asked


def _yahoo_only(monkeypatch):
    """Every venue refuses (conftest); Yahoo serves YAHOO through data.fetch."""
    monkeypatch.setattr(SD, "download", lambda t, period=None, **k:
                        {x: YAHOO[x].copy() for x in t if x in YAHOO})


def test_the_provider_refuses_a_wrong_token_series_and_names_it(monkeypatch):
    _stub_yahoo(monkeypatch, YAHOO)
    p = YFinanceProvider({"ARB": "ARB-USD", "BTC": "BTC-USD", "XMR": "XMR-USD"},
                         ref_prices={"ARB": 1.0, "BTC": 101.0, "XMR": None})
    p.fetch_all()
    assert p.get_daily_bars("ARB") is None
    assert p.get_daily_bars("BTC") is not None
    assert p.get_daily_bars("XMR") is not None          # no reference: nothing to check
    assert p.identity_rejected == {"ARB": ["yahoo"]}


def test_without_references_the_provider_serves_exactly_as_before(monkeypatch):
    """Stocks carry no cg_price; the provider must be byte-for-byte the old one."""
    _stub_yahoo(monkeypatch, YAHOO)
    p = YFinanceProvider({"ARB": "ARB-USD", "BTC": "BTC-USD"})
    p.fetch_all()
    assert p.get_daily_bars("ARB") is not None and p.identity_rejected == {}


def test_the_snapshot_names_the_rejected_coins_and_stays_valid():
    snap = build_snapshot("2026-09-28", universe_size=3, results=[],
                          identity_rejected={"JUP": ["yahoo"], "ARB": ["yahoo"]})
    validate_snapshot(snap)
    assert list(snap) == ["run_date", "ruleset_version", "universe_size",
                          "identity_rejected", "results"]
    assert list(snap["identity_rejected"]) == ["ARB", "JUP"]      # sorted: determinism
    slim, narr = split_narrations(snap)
    assert slim["identity_rejected"] == {"ARB": ["yahoo"], "JUP": ["yahoo"]}
    validate_published(slim, narr)


def test_a_stock_snapshot_is_unchanged():
    snap = build_snapshot("2026-09-28", universe_size=1, results=[])
    assert list(snap) == ["run_date", "ruleset_version", "universe_size", "results"]
    slim, _ = split_narrations(snap)
    assert "identity_rejected" not in slim


def test_a_malformed_rejection_block_fails_the_schema_gate():
    snap = build_snapshot("2026-09-28", universe_size=1, results=[])
    snap["identity_rejected"] = ["ARB"]
    with pytest.raises(ValueError, match="identity_rejected"):
        validate_snapshot(snap)


def _run(monkeypatch, tmp_path, market, symbols, yahoo_only=True):
    """run_market on a stubbed universe. `yahoo_only=False` when the test has
    already installed its own venues (the `venues` fixture)."""
    _stub_yahoo(monkeypatch, YAHOO)          # the stock provider's Yahoo
    if yahoo_only:
        _yahoo_only(monkeypatch)             # crypto's Yahoo leg via data.fetch
    monkeypatch.setattr(PR, "load_symbols", lambda m: dict(symbols))
    args = types.SimpleNamespace(tickers=None, limit=None, period="2y")
    PR.run_market(market, args, "2026-09-28", str(tmp_path))
    return json.loads((tmp_path / market / "latest.json").read_text(encoding="utf-8"))


def test_the_nightly_crypto_run_leaves_the_stranger_out_and_says_so(monkeypatch, tmp_path, capsys):
    latest = _run(monkeypatch, tmp_path, "crypto", {
        "ARB": {"yf": "ARB-USD", "name": "Arbitrum", "sector": "", "cg_price": 1.0},
        "BTC": {"yf": "BTC-USD", "name": "Bitcoin", "sector": "", "cg_price": 100.0}})
    assert latest["identity_rejected"] == {"ARB": ["yahoo"]}
    assert all(r["ticker"] != "ARB" for r in latest["results"])
    assert not (tmp_path / "charts" / "crypto" / "ARB.json").exists()
    out = capsys.readouterr().out
    assert "identity check: 1 coin(s) left out" in out and "ARB" in out
    out.encode("ascii")                                  # rule 9: ASCII-only prints


def test_a_clean_crypto_run_still_records_that_the_check_ran(monkeypatch, tmp_path):
    latest = _run(monkeypatch, tmp_path, "crypto", {
        "BTC": {"yf": "BTC-USD", "name": "Bitcoin", "sector": "", "cg_price": 100.0}})
    assert latest["identity_rejected"] == {}


def test_the_nightly_run_and_the_backtest_read_crypto_from_one_factory():
    """Both go through make_provider, so a replay can never score a different
    series from the one the nightly scan read."""
    import inspect
    from phasemap.backtest import __main__ as BT
    for src in (inspect.getsource(PR.run_market), inspect.getsource(BT.main)):
        assert "make_provider(" in src and "report_identity(" in src
        assert "YFinanceProvider(" not in src
    assert "cg_price" in inspect.getsource(PR.load_symbols)


def test_crypto_reads_the_house_fetch_and_stocks_stay_on_yahoo():
    syms = {"BTC": {"yf": "BTC-USD", "cg_price": 100.0}}
    assert isinstance(PR.make_provider("crypto", syms, "2y"), FetchProvider)
    assert isinstance(PR.make_provider("asx", {"BHP": {"yf": "BHP.AX"}}, "2y"), YFinanceProvider)


# ---------------------------------------------------------------------------
# FetchProvider: PhaseMap crypto on exchange klines (owner, 2026-09-28)
# ---------------------------------------------------------------------------

def test_an_exchange_listed_collision_is_scanned_as_the_RIGHT_coin(venues):
    """ARB was Yahoo's stranger; Binance lists the real ARB. On the exchange
    path it comes BACK (as the right coin) instead of being dropped."""
    p = FetchProvider("crypto", {"ARB": "ARB-USD", "BTC": "BTC-USD", "XMR": "XMR-USD"},
                      ref_prices={"ARB": 1.0, "BTC": 100.0, "XMR": 7.0})
    p.fetch_all()
    assert p.source_of == {"ARB": "binance_vision", "BTC": "binance_vision", "XMR": "yahoo"}
    assert float(p.get_daily_bars("ARB")["Close"].iloc[-1]) == 1.0
    assert p.identity_rejected == {}
    assert venues == [["XMR-USD"]]                     # Yahoo only for the unlisted coin
    df = p.get_daily_bars("BTC")
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert df["Date"].is_monotonic_increasing
    assert float(df["Volume"].iloc[-1]) == 5_000_000.0     # quote volume: already USD


def test_a_coin_nothing_confirms_is_left_out_and_named(monkeypatch):
    _yahoo_only(monkeypatch)
    p = FetchProvider("crypto", {"ARB": "ARB-USD", "BTC": "BTC-USD"},
                      ref_prices={"ARB": 1.0, "BTC": 100.0})
    p.fetch_all()
    assert p.get_daily_bars("ARB") is None
    assert p.identity_rejected == {"ARB": ["yahoo"]}           # keyed by DISPLAY ticker
    assert p.source_of == {"BTC": "yahoo"}


def test_a_coin_one_venue_refuses_but_another_confirms_is_SCANNED_not_left_out(monkeypatch):
    """Measured 2026-09-28: Binance's XMRUSDT is the stale pre-delisting
    series (refused), Yahoo's XMR-USD is Monero. The coin is served from
    Yahoo and must not be published as a gap."""
    def router(url, timeout):
        if "binance.vision" in url and "XMRUSDT" in url:
            return _klines(300.0)                     # not Monero's price
        raise X.SourceDead("HTTP 451")
    monkeypatch.setattr(X, "_get_json", router)
    _yahoo_only(monkeypatch)
    p = FetchProvider("crypto", {"XMR": "XMR-USD"}, ref_prices={"XMR": 7.0})
    p.fetch_all()
    assert p.source_of == {"XMR": "yahoo"}
    assert float(p.get_daily_bars("XMR")["Close"].iloc[-1]) == 7.0
    assert p.identity_rejected == {}
    assert p.report["identity_rejected"] == {"XMR": ["binance_vision"]}   # the venue refusal stays on record


def test_the_check_holds_even_with_the_venue_switch_reverted(monkeypatch):
    """CRYPTO_DATA_SOURCE = "yahoo" is the one-line revert, and in that mode
    data.fetch checks nothing. The provider re-applies the check itself, so a
    venue revert cannot re-open the wrong-token hole in this lens."""
    from scanner import config
    monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", "yahoo")
    _yahoo_only(monkeypatch)
    p = FetchProvider("crypto", {"ARB": "ARB-USD", "BTC": "BTC-USD"},
                      ref_prices={"ARB": 1.0, "BTC": 100.0})
    p.fetch_all()
    assert p.get_daily_bars("ARB") is None and p.identity_rejected == {"ARB": ["yahoo"]}


def test_a_dead_fetch_is_not_retried_per_ticker(monkeypatch):
    """YFinanceProvider re-downloads the whole universe on EVERY lookup when
    its cache is empty; this one fetches once and answers None after."""
    calls = []
    monkeypatch.setattr(SD, "download", lambda t, period=None, **k: calls.append(1) or {})
    p = FetchProvider("crypto", {"A": "A-USD", "B": "B-USD"})
    assert p.get_daily_bars("A") is None and p.get_daily_bars("B") is None
    assert len(calls) == 1


def test_the_nightly_run_publishes_where_the_bars_came_from(venues, monkeypatch, tmp_path):
    """Rows carry `data_source` (the chart draws the SAME series) and the
    snapshot carries `data_sources`. Driven with a stubbed engine so a row
    exists; the engine itself is untouched by this change."""
    rec = {"direction": "bullish", "state": "DISPLACED", "tier": "A", "tags": [],
           "regime": "trend", "zones": [], "metrics": {}, "smt": None, "route_to": None}
    monkeypatch.setattr(PR, "scan_ticker", lambda t, df, **k: [(dict(rec, ticker=t), None)])
    monkeypatch.setattr(PR, "render", lambda r, s: "Setup. This is not financial advice.")
    monkeypatch.setattr(PR, "render_next", lambda r: "")
    latest = _run(monkeypatch, tmp_path, "crypto", {
        "ARB": {"yf": "ARB-USD", "name": "Arbitrum", "sector": "", "cg_price": 1.0},
        "XMR": {"yf": "XMR-USD", "name": "Monero", "sector": "", "cg_price": 7.0}},
        yahoo_only=False)
    by_t = {r["ticker"]: r for r in latest["results"]}
    assert by_t["ARB"]["data_source"] == "binance_vision"
    assert by_t["XMR"]["data_source"] == "yahoo"
    ds = latest["data_sources"]
    assert ds["mode"] == "exchange" and ds["by_source"] == {"binance_vision": 1, "yahoo": 1}
    assert "identity_rejected" not in ds and latest["identity_rejected"] == {}
    candles = json.loads((tmp_path / "charts" / "crypto" / "ARB.json").read_text())["candles"]
    assert candles[-1]["c"] == 1.0                 # the chart file is the RIGHT ARB


def test_a_stock_run_is_untouched(monkeypatch, tmp_path):
    latest = _run(monkeypatch, tmp_path, "asx", {"BHP": {"yf": "BHP.AX", "name": "BHP"}})
    assert "data_sources" not in latest and "identity_rejected" not in latest

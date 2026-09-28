"""scanner/exchange_data.py -- public exchange daily klines (2026-09-28).

Owner: "Can't we use binance/bybit or other LARGE crypto providers data?"
Every bar used to come from Yahoo's AGGREGATED crypto feed, which on the first
real IGNITION run had no usable 27 Sep bar at 02:00 UTC on the 28th, printed
QNT ~20% under Binance and missed 64 of 201 coins.

Everything here drives the SHIPPED fetchers with `_get_json` replaced by a fake
router (the sandbox and CI's test job cannot reach any exchange), so what is
pinned is each venue's real paging, column mapping and failure handling --
the places a silent unit or ordering mistake would corrupt every bar.
"""

import datetime as dt
import urllib.error
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from scanner import config, exchange_data as X

DAY = 86_400_000
T0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _http(code):
    return urllib.error.HTTPError("u", code, "x", None, None)


def binance_rows(n, start=T0, base=100.0):
    """[openTime, o, h, l, c, baseVol, closeTime, QUOTEVOL, ...] as Binance
    serves them (numbers as strings)."""
    out = []
    for i in range(n):
        c = base + i
        out.append([start + i * DAY, str(c - 1), str(c + 2), str(c - 2), str(c), "10",
                    start + i * DAY + DAY - 1, str(1000.0 + i), 5, "0", "0", "0"])
    return out


class Router:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        return self.handler(url)


@pytest.fixture
def route(monkeypatch):
    def install(handler):
        r = Router(handler)
        monkeypatch.setattr(X, "_get_json", r)
        monkeypatch.setattr(X.time, "sleep", lambda s: None)
        return r
    return install


def test_binance_pages_forward_and_maps_QUOTE_volume(route):
    rows = binance_rows(1500)

    def h(url):
        q = parse_qs(urlparse(url).query)
        assert q["symbol"] == ["QNTUSDT"] and q["interval"] == ["1d"]
        start = int(q["startTime"][0])
        page = [r for r in rows if r[0] >= start][:1000]
        return page

    r = route(h)
    df = X._binance(X.HOSTS["binance_vision"], "QNT", None, 5, "binance_vision")
    assert len(r.calls) == 2                       # 1000 + 500
    assert len(df) == 1500 and df.attrs["source"] == "binance_vision"
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    first = df.iloc[0]
    assert (first["Open"], first["High"], first["Low"], first["Close"]) == (99.0, 102.0, 98.0, 100.0)
    assert first["Volume"] == 1000.0               # quote volume (index 7), NOT base (index 5)
    assert df.index[0] == pd.Timestamp("2024-01-01") and df.index.tz is None
    assert df.index.is_monotonic_increasing


def test_an_unlisted_pair_is_None_not_an_error(route):
    route(lambda url: (_ for _ in ()).throw(_http(400)))
    assert X._binance(X.HOSTS["binance"], "NOPE", None, 5, "binance") is None


def test_bybit_is_newest_first_pages_backward_and_uses_TURNOVER(route):
    # 1500 bars; each page returns the newest 1000 at or before `end`.
    bars = [[str(T0 + i * DAY), str(10 + i), str(12 + i), str(8 + i), str(11 + i), "3", str(500 + i)]
            for i in range(1500)]

    def h(url):
        q = parse_qs(urlparse(url).query)
        assert q["category"] == ["spot"] and q["interval"] == ["D"] and q["symbol"] == ["QNTUSDT"]
        end = int(q["end"][0]) if "end" in q else 10 ** 15
        page = [b for b in bars if int(b[0]) <= end][-1000:][::-1]     # newest first
        return {"retCode": 0, "result": {"list": page}}

    r = route(h)
    df = X._bybit("QNT", None, 5)
    assert len(r.calls) == 2 and len(df) == 1500 and df.attrs["source"] == "bybit"
    last = df.iloc[-1]
    assert (last["Open"], last["Close"], last["Volume"]) == (1509.0, 1510.0, 1999.0)
    assert df.index.is_monotonic_increasing


def test_bybit_unknown_symbol_is_None(route):
    route(lambda url: {"retCode": 10001, "retMsg": "Not supported symbols", "result": {}})
    assert X._bybit("NOPE", None, 5) is None


def test_coinbase_column_order_and_approximate_quote_volume(route):
    now = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    t = int(now.timestamp())

    def h(url):
        q = parse_qs(urlparse(url).query)
        start = dt.datetime.fromisoformat(q["start"][0])
        if start < now - dt.timedelta(days=400):
            return []                               # before listing
        # [time, LOW, HIGH, OPEN, CLOSE, BASE volume], newest first
        return [[t, 9.0, 13.0, 10.0, 12.0, 5.0], [t - 86_400, 8.0, 11.0, 9.0, 10.0, 4.0]]

    route(h)
    df = X._coinbase("QNT", None, 5)
    assert df.attrs["source"] == "coinbase"
    row = df.loc[pd.Timestamp(now.date())]
    assert (row["Open"], row["High"], row["Low"], row["Close"]) == (10.0, 13.0, 9.0, 12.0)
    assert row["Volume"] == 60.0                    # close x base volume


def test_a_geo_blocked_venue_is_asked_ONCE_then_skipped(route, monkeypatch):
    """The whole point of the dead list: 200 coins must not each wait out a
    host that answers 451 to a US runner."""
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance", "bybit"))

    def h(url):
        if "api.binance.com" in url:
            raise X.SourceDead("HTTP 451")
        return {"retCode": 0, "result": {"list": [[str(T0), "1", "2", "0.5", "1.5", "1", "9"]]}}

    r = route(h)
    frames, rep = X.download_klines(["BTC", "ETH", "QNT", "SOL"], days=None)
    assert set(frames) == {"BTC", "ETH", "QNT", "SOL"}
    assert rep["dead"] == {"binance": "HTTP 451"}
    assert rep["by_source"] == {"bybit": 4}
    assert sum("api.binance.com" in u for u in r.calls) == 1


def test_the_first_venue_that_LISTS_a_coin_wins_and_the_rest_fall_through(route, monkeypatch):
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance_vision", "coinbase"))
    now = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def h(url):
        if "binance.vision" in url:
            if "QNTUSDT" in url:
                return binance_rows(3)
            raise _http(400)                        # not listed on Binance
        if "/products/XMR-USD/" in url:
            q = parse_qs(urlparse(url).query)
            if dt.datetime.fromisoformat(q["start"][0]) < now - dt.timedelta(days=301):
                return []
            return [[int(now.timestamp()), 1.0, 2.0, 1.5, 1.8, 3.0]]
        raise _http(404)

    route(h)
    frames, rep = X.download_klines(["QNT", "XMR", "ZZZ"], days=None)
    assert frames["QNT"].attrs["source"] == "binance_vision"
    assert frames["XMR"].attrs["source"] == "coinbase"
    assert rep["missing"] == ["ZZZ"]
    assert rep["by_source"] == {"binance_vision": 1, "coinbase": 1}


def test_a_venue_that_keeps_erroring_is_dropped_for_the_run(route, monkeypatch):
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance", "bybit"))
    monkeypatch.setattr(config, "EXCHANGE_DEAD_AFTER_ERRORS", 2)
    monkeypatch.setattr(config, "EXCHANGE_THREADS", 1)

    def h(url):
        if "api.binance.com" in url:
            if "C0USDT" in url:                     # the probe coin works...
                return binance_rows(2)
            raise TimeoutError("slow")              # ...then the venue degrades
        return {"retCode": 0, "result": {"list": [[str(T0), "1", "2", "0.5", "1.5", "1", "9"]]}}

    r = route(h)
    frames, rep = X.download_klines([f"C{i}" for i in range(6)], days=None)
    assert len(frames) == 6 and "binance" in rep["dead"]
    assert frames["C0"].attrs["source"] == "binance"
    assert sum("api.binance.com" in u for u in r.calls) == 3    # probe + 2 errors, then dropped


def test_frames_are_clean_daily_utc_dates():
    rows = [(T0 + DAY, 1, 2, 0.5, 1.5, 7), (T0, 1, 2, 0.5, 1.2, 6),
            (T0 + DAY, 1, 2, 0.5, 1.6, 8),            # duplicate day: the later print wins
            (T0 + 2 * DAY, 1, 2, 0.5, 0.0, 9)]        # a zero close is dropped
    df = X._frame(rows, "binance")
    assert list(df.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")]
    assert df.loc[pd.Timestamp("2024-01-02"), "Close"] == 1.6


def test_a_days_window_starts_the_binance_walk_at_the_right_place(route):
    seen = []

    def h(url):
        seen.append(int(parse_qs(urlparse(url).query)["startTime"][0]))
        return binance_rows(2)

    route(h)
    X._binance(X.HOSTS["binance"], "BTC", 30, 5, "binance")
    want = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=32)
    assert abs(seen[0] / 1000 - want.timestamp()) < 120


def test_no_credentials_and_no_order_endpoints_anywhere():
    """Market data only: the module must never grow a key, a signature or an
    order path -- that is scanner/broker/'s business, fenced separately."""
    src = (config.__file__.replace("config.py", "exchange_data.py"))
    text = open(src, encoding="utf-8").read().lower()
    for bad in ("api_key", "apikey", "secret", "signature", "/order", "hmac", "x-mbx-apikey"):
        assert bad not in text, bad


def test_a_network_error_on_the_probe_coin_drops_the_venue_at_once(route, monkeypatch):
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance", "bybit"))

    def h(url):
        if "api.binance.com" in url:
            raise TimeoutError("unreachable")
        return {"retCode": 0, "result": {"list": [[str(T0), "1", "2", "0.5", "1.5", "1", "9"]]}}

    r = route(h)
    frames, rep = X.download_klines(["BTC", "ETH", "SOL"], days=None)
    assert len(frames) == 3 and "binance" in rep["dead"]
    assert sum("api.binance.com" in u for u in r.calls) == 1

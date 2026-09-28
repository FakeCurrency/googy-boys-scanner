"""The crypto data-source switch (owner, 2026-09-28): "make the VIVEK crypto
scan and paper bot go to the binance or bybit ... That way it's all in SYNC".

Every path that prices crypto -- the scan's download (scanner/run.py), the
scan's own fallbacks and 4H bars (scanner/scan.py), the bot's off-universe
stragglers and CLI (scanner/broker/vivek_run.py), the kill switch's live
re-pricing and the IGNITION lens -- goes through ONE entry point,
`data.fetch`, so crypto can never come from two sources depending on which
path asked. These tests drive the shipped functions with the exchanges and
Yahoo both stubbed.
"""
import ast
import pathlib
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from scanner import config, data, exchange_data as X, run, scan

ROOT = pathlib.Path(__file__).resolve().parents[1]
T0 = int(pd.Timestamp("2024-01-01").timestamp() * 1000)


def _klines(n=3, px=100.0):
    return [[T0 + i * 86_400_000, str(px), str(px + 1), str(px - 1), str(px), "1",
             T0 + i * 86_400_000 + 1, "5000"] for i in range(n)]


def _yahoo_frame(px=7.0):
    idx = pd.date_range(end="2024-01-03", periods=3, freq="D")
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Volume": 1.0}, index=idx)


def test_the_switch_is_on_and_binance_leads():
    assert config.CRYPTO_DATA_SOURCE == "exchange"
    assert config.CRYPTO_YAHOO_FALLBACK is True
    assert config.EXCHANGE_KLINE_SOURCES[:2] == ("binance_vision", "binance")
    assert "bybit" in config.EXCHANGE_KLINE_SOURCES


def test_fetch_crypto_prices_from_the_exchange_and_falls_back_per_coin(monkeypatch):
    urls = []

    def router(url, timeout):
        urls.append(url)
        if "binance.vision" in url:
            return _klines() if "QNTUSDT" in url or "BTCUSDT" in url else (_ for _ in ()).throw(
                __import__("urllib.error").error.HTTPError(url, 400, "x", None, None))
        raise X.SourceDead("HTTP 451")

    monkeypatch.setattr(X, "_get_json", router)
    asked = []
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: (asked.append((list(t), k)) or
                                                                     {x: _yahoo_frame() for x in t}))
    frames, rep = data.fetch("crypto", ["BTC-USD", "QNT-USD", "XMR-USD"], period="5y")
    assert set(frames) == {"BTC-USD", "QNT-USD", "XMR-USD"}         # keys keep Yahoo spelling
    assert rep["source_of"] == {"BTC-USD": "binance_vision", "QNT-USD": "binance_vision",
                                "XMR-USD": "yahoo"}
    assert rep["by_source"] == {"binance_vision": 2, "yahoo": 1}
    assert rep["yahoo_fallback"] == 1 and rep["mode"] == "exchange"
    assert asked == [(["XMR-USD"], {})]            # only the unlisted coin, daily call shape
    assert frames["QNT-USD"]["Volume"].iloc[-1] == 5000.0              # quote volume


def test_stocks_never_touch_an_exchange(monkeypatch):
    monkeypatch.setattr(X, "_get_json", lambda *a: pytest.fail("a stock reached an exchange"))
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: {x: _yahoo_frame() for x in t})
    frames, rep = data.fetch("asx", ["BHP.AX"], period="5y")
    assert set(frames) == {"BHP.AX"} and rep["mode"] == "yahoo"


def test_the_yahoo_switch_restores_the_old_path_in_one_line(monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", "yahoo")
    monkeypatch.setattr(X, "_get_json", lambda *a: pytest.fail("yahoo mode reached an exchange"))
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: {x: _yahoo_frame() for x in t})
    frames, rep = data.fetch("crypto", ["BTC-USD"], period="5y")
    assert rep["source_of"] == {"BTC-USD": "yahoo"}


def test_4h_bars_come_from_exchange_4h_candles_and_yahoo_1h(monkeypatch):
    seen = []

    def router(url, timeout):
        seen.append(parse_qs(urlparse(url).query).get("interval", [None])[0])
        if "BTCUSDT" in url:
            return _klines()
        raise __import__("urllib.error").error.HTTPError(url, 400, "x", None, None)

    monkeypatch.setattr(X, "_get_json", router)
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance",))
    yk = []
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: (yk.append(k) or
                                                                     {x: _yahoo_frame() for x in t}))
    frames, _ = data.fetch("crypto", ["BTC-USD", "ZZZ-USD"], period="2y", interval="4h")
    assert set(seen) == {"4h"}
    assert yk == [{"interval": "1h"}]              # Yahoo has no 4h; the resampler buckets 1h
    # an intraday frame keeps its hour (a DAILY frame is normalised to the date)
    assert frames["BTC-USD"].index[0] == pd.Timestamp("2024-01-01 00:00:00")


def test_scan_routes_crypto_through_fetch_and_stocks_through_download(monkeypatch):
    calls = []
    monkeypatch.setattr(scan, "fetch", lambda m, t, period=None, interval="1d":
                        (calls.append(("fetch", m, interval)) or ({}, {})))
    monkeypatch.setattr(scan, "download", lambda t, period=None, interval="1d":
                        (calls.append(("download", interval)) or {}))
    scan._bars("crypto", ["BTC-USD"], "2y", "4h")
    scan._bars("asx", ["BHP.AX"], "2y", "1h")
    assert calls == [("fetch", "crypto", "4h"), ("download", "1h")]


def test_the_4H_plan_asks_crypto_for_exchange_4h_candles(monkeypatch):
    seen = []
    monkeypatch.setattr(scan, "_bars", lambda m, t, p, iv="1d": (seen.append((m, iv)) or {}))
    scan._attach_h4_plans([{"symbol": "BTC", "yf": "BTC-USD", "dir": "LONG"}], "crypto")
    scan._attach_h4_plans([{"symbol": "BHP", "yf": "BHP.AX", "dir": "LONG"}], "asx")
    assert seen == [("crypto", "4h"), ("asx", config.VIVEK_H4_INTERVAL)]


def test_crypto_rows_name_their_venue_and_stock_rows_stay_lean():
    rep = {"mode": "exchange", "by_source": {"binance_vision": 1, "yahoo": 1},
           "dead": {"binance": "HTTP 451"}, "source_of": {"BTC-USD": "binance_vision",
                                                          "XMR-USD": "yahoo"}}
    vk = {"results": [{"symbol": "BTC"}, {"symbol": "XMR"}, {"symbol": "OLD"}]}
    run.tag_sources(vk, "crypto", rep)
    assert [r["data_source"] for r in vk["results"]] == ["binance_vision", "yahoo", "cache"]
    assert vk["data_sources"]["by_source"] == {"binance_vision": 1, "yahoo": 1}
    assert vk["data_sources"]["dead"] == {"binance": "HTTP 451"}
    assert "source_of" not in vk["data_sources"]
    st = {"results": [{"symbol": "BHP"}]}
    run.tag_sources(st, "asx", {"mode": "yahoo", "source_of": {"BHP.AX": "yahoo"}})
    assert "data_source" not in st["results"][0] and st["data_sources"]["mode"] == "yahoo"


def _calls(path: pathlib.Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name):
                n += 1
    return n


@pytest.mark.parametrize("rel", ["scanner/run.py", "scanner/broker/vivek_run.py",
                                 "scanner/broker/kill_switch.py", "scanner/ignition/run.py",
                                 "scanner/momentum/run.py", "phasemap/data/provider.py"])
def test_every_crypto_pricing_path_goes_through_fetch(rel):
    """The sync guarantee, as structure: each of these files prices crypto,
    so each must call data.fetch. A future edit that reverts one to a bare
    `download` for everything would put two venues' prices in one book."""
    assert _calls(ROOT / rel, "fetch") >= 1, rel


# ---------------------------------------------------------------------------
# the IDENTITY CHECK: a ticker is not an identity (2026-09-28)
# ---------------------------------------------------------------------------

def test_same_coin_band():
    f = pd.DataFrame({"Close": [1.0, 100.0]})
    assert X.same_coin(f, 100.0) and X.same_coin(f, 139.0) and X.same_coin(f, 72.0)
    assert not X.same_coin(f, 145.0) and not X.same_coin(f, 70.0)
    assert not X.same_coin(f, 0.003)                      # the ARB-USD collision shape
    assert X.same_coin(f, None) and X.same_coin(f, 0)     # no reference: nothing to check
    assert not X.same_coin(None, 100.0)


def test_a_colliding_venue_is_skipped_for_the_next_that_IS_the_coin(monkeypatch):
    """Measured on the first run: Yahoo's ARB-USD sat 35,210% off Binance's
    ARBUSDT -- a different token under the same ticker. Whichever venue
    carries the stranger, the reference price rejects it."""
    import datetime as dt
    import urllib.error
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance_vision", "coinbase"))
    now = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def router(url, timeout):
        if "binance.vision" in url:
            return _klines(px=0.003) if "ARBUSDT" in url else _klines(px=100.0)
        if "/products/ARB-USD/" in url:
            q = parse_qs(urlparse(url).query)
            if dt.datetime.fromisoformat(q["start"][0]) < now - dt.timedelta(days=301):
                return []
            return [[int(now.timestamp()), 0.9, 1.1, 1.0, 1.02, 10.0]]
        raise urllib.error.HTTPError(url, 404, "x", None, None)

    monkeypatch.setattr(X, "_get_json", router)
    frames, rep = X.download_klines(["BTC", "ARB"], days=None,
                                    ref_prices={"BTC": 100.0, "ARB": 1.0})
    assert frames["ARB"].attrs["source"] == "coinbase"
    assert rep["identity_rejected"] == {"ARB": ["binance_vision"]}
    assert frames["BTC"].attrs["source"] == "binance_vision"


def test_a_coin_no_source_confirms_is_LEFT_OUT_not_scanned_as_a_stranger(monkeypatch):
    monkeypatch.setattr(X, "_get_json", lambda url, timeout: _klines(px=0.003))
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: {x: _yahoo_frame(0.004) for x in t})
    frames, rep = data.fetch("crypto", ["ARB-USD", "BTC-USD"], period="5y",
                             ref_prices={"ARB-USD": 1.0, "BTC-USD": 0.003})
    assert set(frames) == {"BTC-USD"}
    # every venue that served the stranger is named, in the order tried, and
    # the Yahoo leg is checked too -- nothing confirmed ARB, so it is left out
    rej = rep["identity_rejected"]["ARB"]
    assert rej[0] == "binance_vision" and rej[-1] == "yahoo"
    assert set(rej) <= set(config.EXCHANGE_KLINE_SOURCES) | {"yahoo"}
    assert "ARB-USD" not in rep["source_of"]


def test_the_universe_keeps_coingeckos_price_as_the_reference(monkeypatch):
    import json
    from scanner import universe
    coins = [{"symbol": "btc", "name": "Bitcoin", "current_price": 65000.5},
             {"symbol": "arb", "name": "Arbitrum", "current_price": None}]
    monkeypatch.setattr(universe, "_http_get", lambda *a, **k: json.dumps(coins))
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    items = universe._fetch_crypto("-USD", limit=5)
    assert items[0]["cg_price"] == 65000.5 and items[1]["cg_price"] is None


def test_the_scan_and_the_lens_pass_the_reference_prices():
    for rel in ("scanner/run.py", "scanner/ignition/run.py", "scanner/broker/vivek_run.py",
                "scanner/momentum/run.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "ref_prices=" in src and "cg_price" in src, rel


# ---------------------------------------------------------------------------
# the CACHE must not undo the identity check (2026-09-28, follow-up)
# ---------------------------------------------------------------------------

def _fresh_yahoo(px):
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=3, freq="D")
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Volume": 1.0}, index=idx)


def test_a_cached_stranger_is_not_readmitted_after_fetch_rejects_it():
    """Every Yahoo-era run cached Yahoo's SKY-USD (a different token, +454%
    vs the real coin). `fetch` now rejects it -- but `merge_with_cache` back-
    fills whatever `fetch` did not return, so without the reference prices the
    stranger walked straight back into the scan for FRAME_CACHE_MAX_AGE_DAYS.
    It is refused, named, and dropped from the cache; the real coin beside it
    is reused as before."""
    uni = ["SKY-USD", "BTC-USD"]
    data.save_frame_cache("crypto", {"SKY-USD": _fresh_yahoo(0.4), "BTC-USD": _fresh_yahoo(100.0)})
    refs = {"SKY-USD": 0.07, "BTC-USD": 101.0}
    merged, stats = data.merge_with_cache("crypto", {}, uni, ref_prices=refs)
    assert set(merged) == {"BTC-USD"}
    assert stats["identity_dropped"] == 1 and stats["identity_dropped_names"] == ["SKY-USD"]
    assert stats["reused"] == 1
    assert set(data.load_frame_cache("crypto")) == {"BTC-USD"}    # gone from disk too


def test_no_reference_means_the_cache_behaves_exactly_as_before():
    """Stocks carry no cg_price, and a coin CoinGecko gave no price for is
    unchecked everywhere -- the cache check must be the same no-op."""
    data.save_frame_cache("asx", {"BHP.AX": _fresh_yahoo(40.0)})
    merged, stats = data.merge_with_cache("asx", {}, ["BHP.AX"], ref_prices={"BHP.AX": None})
    assert set(merged) == {"BHP.AX"} and stats["identity_dropped"] == 0
    assert "identity_dropped_names" not in stats
    merged, _ = data.merge_with_cache("asx", {}, ["BHP.AX"])
    assert set(merged) == {"BHP.AX"}


def _merge_calls(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name == "merge_with_cache":
                yield node


@pytest.mark.parametrize("rel", ["scanner/run.py", "scanner/broker/vivek_run.py",
                                 "scanner/ignition/run.py", "scanner/momentum/run.py"])
def test_every_cache_merge_after_a_crypto_fetch_carries_the_reference_prices(rel):
    """Each of these files fetches crypto with ref_prices and then back-fills
    from the frame cache. A merge without the same map re-opens the leak the
    test above closes."""
    calls = list(_merge_calls(ROOT / rel))
    assert calls, f"{rel}: no merge_with_cache call found (test is stale)"
    for c in calls:
        assert any(k.arg == "ref_prices" for k in c.keywords), \
            f"{rel}:{c.lineno}: merge_with_cache without ref_prices"


def test_left_out_counts_only_coins_no_source_served():
    """identity_rejected names every venue that refused a coin -- including a
    coin a LATER source confirmed. Measured on a runner 2026-09-28: Binance's
    XMRUSDT is the stale pre-delisting series (refused), Yahoo's XMR-USD is
    Monero (used). Reading the map as "left out" overstated the gap."""
    rep = {"identity_rejected": {"XMR": ["binance_vision"], "ARB": ["yahoo"],
                                 "AI": ["binance_vision", "coinbase"]},
           "source_of": {"XMR-USD": "yahoo", "BTC-USD": "binance_vision"}}
    assert data.left_out(rep) == ["AI", "ARB"]
    assert data.left_out({}) == []

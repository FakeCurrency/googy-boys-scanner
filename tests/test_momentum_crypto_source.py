"""The momentum lens prices crypto through `data.fetch` (2026-09-28).

Until this, `scanner/momentum/run.py` called `data.download` directly, so for
crypto it screened Yahoo's `<SYM>-USD` series -- and for AERO, JUP, ARB, PRL,
SKY, XCN, EDGE and MET that series is a DIFFERENT TOKEN from the CoinGecko
coin of the same symbol (measured from a runner by
scripts/crypto_source_compare.py: AERO +2,623,839% vs Binance, JUP +96,729%,
ARB +35,210%, ... MET -43%). These tests drive the SHIPPED screen and replay
with the exchanges and Yahoo both stubbed: the lens asks `fetch` with the
universe's `cg_price`, a coin nothing confirms is LEFT OUT and named, the
frame cache cannot re-admit it, and stocks read exactly as before.
"""
import urllib.error

import pandas as pd
import pytest

from scanner import data, exchange_data as X
from scanner.momentum import config as MC
from scanner.momentum import run as R

T0 = int(pd.Timestamp("2024-01-01").timestamp() * 1000)


def _klines(n=3, px=100.0):
    return [[T0 + i * 86_400_000, str(px), str(px + 1), str(px - 1), str(px), "1",
             T0 + i * 86_400_000 + 1, "5000"] for i in range(n)]


def _yahoo(px):
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=3, freq="D")
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Volume": 1.0}, index=idx)


ROWS = [{"symbol": "BTC", "yf": "BTC-USD", "name": "Bitcoin", "cg_price": 100.0},
        {"symbol": "ARB", "yf": "ARB-USD", "name": "Arbitrum", "cg_price": 1.0},
        {"symbol": "XMR", "yf": "XMR-USD", "name": "Monero", "cg_price": 7.0}]


@pytest.fixture
def venues(monkeypatch):
    """Binance's mirror lists BTC only (the right coin); every other venue
    refuses the runner; Yahoo serves ARB-USD as the ~0.003 stranger and
    XMR-USD as the real coin."""
    def router(url, timeout):
        if "binance.vision" in url:
            if "BTCUSDT" in url:
                return _klines(px=100.0)
            raise urllib.error.HTTPError(url, 400, "x", None, None)
        raise X.SourceDead("HTTP 451")

    monkeypatch.setattr(X, "_get_json", router)
    asked = []
    yahoo = {"ARB-USD": _yahoo(0.003), "XMR-USD": _yahoo(7.0), "BTC-USD": _yahoo(100.0)}

    def download(tickers, period=None, **kw):
        asked.append((list(tickers), period, kw))
        return {t: yahoo[t].copy() for t in tickers if t in yahoo}

    monkeypatch.setattr(data, "download", download)
    return asked


def test_the_screen_leaves_the_wrong_token_out_and_names_it(venues):
    payload = R.screen_market("crypto", rows=[dict(r) for r in ROWS])
    assert payload is not None
    assert payload["summary"]["downloaded"] == 2                   # BTC + XMR, never ARB
    ds = payload["data_sources"]
    assert ds["mode"] == "exchange"
    assert ds["by_source"] == {"binance_vision": 1, "yahoo": 1}
    assert ds["identity_rejected"]["ARB"][-1] == "yahoo"
    # only the coins no exchange confirmed went to Yahoo, over the screen's window
    assert venues == [(["ARB-USD", "XMR-USD"], MC.DATA_PERIOD, {})]


def test_the_frame_cache_cannot_readmit_the_stranger(venues):
    """Every Yahoo-era momentum run cached Yahoo's ARB-USD. `fetch` refuses it;
    the cache merge must refuse it too, or it screens for another 10 days."""
    data.save_frame_cache("momentum-crypto", {"ARB-USD": _yahoo(0.003)})
    payload = R.screen_market("crypto", rows=[dict(r) for r in ROWS])
    assert payload["summary"]["downloaded"] == 2
    assert payload["summary"]["cache"]["identity_dropped_names"] == ["ARB-USD"]
    assert "ARB-USD" not in data.load_frame_cache("momentum-crypto")


def test_the_replay_prices_through_fetch_with_the_reference_prices(monkeypatch):
    seen = {}

    def fake_fetch(market, tickers, period=None, interval="1d", ref_prices=None, **kw):
        seen.update(market=market, tickers=list(tickers), period=period,
                    interval=interval, refs=dict(ref_prices or {}))
        return {}, {"mode": "exchange", "source_of": {}}

    monkeypatch.setattr(R.sdata, "fetch", fake_fetch)
    monkeypatch.setattr(R.sdata, "download",
                        lambda *a, **k: pytest.fail("the replay bypassed data.fetch"))
    assert R.backtest_market("crypto", rows=[dict(r) for r in ROWS]) is None   # no data -> None
    assert seen == {"market": "crypto", "tickers": ["BTC-USD", "ARB-USD", "XMR-USD"],
                    "period": MC.BT_PERIOD, "interval": "1d",
                    "refs": {"BTC-USD": 100.0, "ARB-USD": 1.0, "XMR-USD": 7.0}}


def test_stocks_read_exactly_as_before(monkeypatch):
    """No cg_price, no exchange: `fetch` hands a stock market straight to
    `download` with the screen's period and daily interval, as the lens's
    direct call always did."""
    monkeypatch.setattr(X, "_get_json", lambda *a: pytest.fail("a stock reached an exchange"))
    asked = []
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: (asked.append((list(t), period, k))
                                                                     or {x: _yahoo(40.0) for x in t}))
    payload = R.screen_market("asx", rows=[{"symbol": "BHP", "yf": "BHP.AX", "name": "BHP"}])
    assert asked == [(["BHP.AX"], MC.DATA_PERIOD, {})]
    assert payload["data_sources"]["mode"] == "yahoo"
    assert all("data_source" not in r for r in payload["results"])


def test_crypto_hits_name_their_venue_so_the_chart_draws_the_same_coin():
    rep = {"mode": "exchange", "by_source": {"binance_vision": 1, "yahoo": 1},
           "dead": {"bybit": "HTTP 403"}, "identity_rejected": {"ARB": ["yahoo"]},
           "source_of": {"BTC-USD": "binance_vision", "XMR-USD": "yahoo"}}
    p = {"results": [{"yf": "BTC-USD"}, {"yf": "XMR-USD"}, {"yf": "OLD-USD"}]}
    R.tag_sources(p, "crypto", rep)
    assert [r["data_source"] for r in p["results"]] == ["binance_vision", "yahoo", "cache"]
    assert p["data_sources"]["identity_rejected"] == {"ARB": ["yahoo"]}
    assert "source_of" not in p["data_sources"]
    st = {"results": [{"yf": "BHP.AX"}]}
    R.tag_sources(st, "asx", {"mode": "yahoo", "source_of": {"BHP.AX": "yahoo"}})
    assert "data_source" not in st["results"][0]


def test_injected_frames_publish_no_source_block():
    """The injectable path (tests, replays of fixtures) fetched nothing, so it
    must not claim a source it did not use."""
    assert R.screen_market("crypto", frames={}, rows=[]) is None


def test_the_log_names_only_coins_actually_left_out(capsys):
    rep = {"mode": "exchange", "by_source": {"yahoo": 1}, "dead": {}, "yahoo_fallback": 1,
           "identity_rejected": {"XMR": ["binance_vision"], "ARB": ["yahoo"]},
           "source_of": {"XMR-USD": "yahoo"}}
    R._print_sources("crypto", rep)
    out = capsys.readouterr().out
    assert "1 coin(s) left out" in out and "ARB" in out.split("left out")[1]
    assert "XMR" not in out.split("left out")[1]

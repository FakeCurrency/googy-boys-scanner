"""The test-suite's network and live-cache guards hold (REFINE200, 2026-10-14).

tests/conftest.py refuses every exchange venue, every Yahoo entry point, and
points the sector cache at tmp_path. Each guard exists because a test once
reached past it: eleven tests called Yahoo for real on every run (3.7 minutes
of retry sleep with no network, a throttling-dependent pass rate in CI), and
39 read the live data/sector_map.json the scan rewrites. If a guard stops
holding, these fail first and name it, instead of the suite quietly slowing
down or a scan commit moving a unit test.
"""

import time
import urllib.request

import pytest

from scanner import config, data, sectorcache


def test_yfinance_download_is_refused():
    import yfinance as yf
    with pytest.raises(ConnectionError, match="Yahoo disabled"):
        yf.download(["BHP.AX"], period="5d", progress=False)


def test_every_yfinance_request_is_refused_at_the_choke_point():
    """Ticker.history / .calendar / .get_info and marketcaps' bulk quote all
    go through YfData.get/post."""
    from yfinance.data import YfData
    with pytest.raises(ConnectionError, match="Yahoo disabled"):
        YfData().get("https://query1.finance.yahoo.com/v7/finance/quote")
    with pytest.raises(ConnectionError, match="Yahoo disabled"):
        YfData().post("https://query2.finance.yahoo.com/v1/x")


def test_a_plain_http_call_to_a_yahoo_host_is_refused():
    import requests
    with pytest.raises(ConnectionError, match="Yahoo disabled"):
        urllib.request.urlopen("https://query1.finance.yahoo.com/v8/finance/chart/BHP.AX")
    with pytest.raises(ConnectionError, match="Yahoo disabled"):
        urllib.request.urlopen(urllib.request.Request("https://finance.yahoo.com/"))
    with pytest.raises(ConnectionError, match="Yahoo disabled"):
        requests.get("https://query2.finance.yahoo.com/v8/finance/chart/X", timeout=1)


def test_a_refused_download_degrades_at_once_rather_than_sleeping_the_back_off():
    """The scan's 4H plans and the book's straggler fetch go through download();
    under test it must give up immediately, not sleep DATA_BACKOFF x retries."""
    assert config.DATA_BACKOFF == [0.0]
    t0 = time.monotonic()
    assert data.download(["BHP.AX", "CBA.AX"], period="5d") == {}
    assert time.monotonic() - t0 < 5.0


def test_a_test_can_still_install_its_own_yahoo_fake(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: pd.DataFrame())
    assert data.yf.download(["X"]).empty


def test_the_sector_cache_is_a_per_test_temp_file(tmp_path):
    assert sectorcache.CACHE_FILE == tmp_path / "sector_map.json"
    assert sectorcache.PUBLIC_FILE.parent == tmp_path
    assert sectorcache.load_cache() == {}          # never the live signal-path file


def test_exchange_venues_stay_refused():
    from scanner import exchange_data
    with pytest.raises(exchange_data.SourceDead):
        exchange_data._get_json("https://data-api.binance.vision/api/v3/klines", 5)

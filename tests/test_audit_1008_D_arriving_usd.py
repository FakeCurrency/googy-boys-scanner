"""Audit #21 (2026-10-08): the crypto "liquidity arriving" leg A read
Close x Volume, but crypto Volume is already USD.

The arriving list's first leg is "today's turnover ALONE clears the floor".
It computed today's turnover as Close x Volume for every market, so for crypto
(MarketConfig.volume_is_usd) it was price x dollar-volume: a $20 coin's $2.5M
day read $50M and was listed; a $0.05 coin's $5M day read $250k and never
qualified. The fix is `scan._turnover_today`, on the same basis as
`_liquidity`. Report-only file -- nothing here is traded.
"""
import json

import pandas as pd

from scanner import config, scan, vivek


def _coin(price: float, base_vol: float, today_vol: float, n: int = 40):
    idx = pd.date_range(end="2026-01-05", periods=n, freq="D")
    vol = [base_vol] * (n - 1) + [today_vol]
    return pd.DataFrame({"Open": price, "High": price * 1.01, "Low": price * 0.99,
                         "Close": price, "Volume": vol}, index=idx)


def _arriving(monkeypatch, tmp_path, frames):
    sig = {"direction": "long", "close": 1.0}
    monkeypatch.setattr(vivek, "evaluate", lambda df: dict(sig))
    uni = [{"yf": t, "symbol": t.split("-")[0], "name": t, "sector": ""} for t in frames]
    out = scan.scan_vivek_market("crypto", universe=uni, frames=frames,
                                 out_root=str(tmp_path), pulse_data=[], progress=False)
    assert out["funnel"]["illiquid_setup"] == len(frames)
    data = json.loads((tmp_path / "crypto_arriving.json").read_text(encoding="utf-8"))
    return {r["symbol"]: r for r in data["results"]}


def test_crypto_today_turnover_is_the_usd_volume_not_price_times_it(monkeypatch, tmp_path):
    assert config.MARKETS["crypto"].volume_is_usd is True
    floor = config.MARKETS["crypto"].liquidity_min            # $3M
    frames = {
        # $0.05 coin: $5M of real dollars today, 4.2x its 20d average, 20d avg $1.2M
        "CHEAP-USD": _coin(0.05, 1_000_000.0, 5_000_000.0),
        # $20 coin: only $2.5M of real dollars today (below the floor)
        "DEAR-USD": _coin(20.0, 500_000.0, 2_500_000.0),
    }
    rows = _arriving(monkeypatch, tmp_path, frames)
    assert "CHEAP" in rows, "real arriving dollars were dropped (price x USD volume)"
    assert rows["CHEAP"]["turnover_today"] == 5_000_000
    assert rows["CHEAP"]["turnover_today"] >= floor
    assert "DEAR" not in rows, "a $2.5M day was listed as clearing the $3M floor"


def test_stocks_still_measure_turnover_as_price_times_shares(monkeypatch, tmp_path):
    df = _coin(2.0, 50_000.0, 400_000.0)                       # shares, not dollars
    mkt = config.MARKETS["asx"]
    assert mkt.volume_is_usd is False
    assert scan._turnover_today(df, mkt) == 2.0 * 400_000.0
    assert scan._turnover_today(df, config.MARKETS["crypto"]) == 400_000.0


def test_the_one_bar_helper_and_the_average_share_a_basis():
    df = _coin(20.0, 1_000_000.0, 1_000_000.0)                # flat volume
    for key in ("asx", "nasdaq", "crypto"):
        mkt = config.MARKETS[key]
        assert scan._turnover_today(df, mkt) == scan._liquidity(df, mkt), key

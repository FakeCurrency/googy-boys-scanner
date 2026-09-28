"""vivek_run._enrich_adv honours `volume_is_usd` (owner, 2026-09-28: "Yeah fix it").

Crypto Volume is already DOLLAR volume (Yahoo and the exchange klines alike),
so multiplying it by Close again made crypto `adv_usd` price x dollar-volume.
A coin under ~4c then gated far below its real liquidity and the bot's
size_vs_adv check wrongly REFUSED it (XDC: ~$8.4M a day, gated at ~$252k),
while scan.py, vivek_parity._adv_usd_at and vivek_backtest all honoured the
flag. These tests pin the live stamp to the parity replay's, so the two can
never disagree about a coin's liquidity again.
"""

import inspect

import numpy as np
import pandas as pd
import pytest

from scanner import config
from scanner import vivek_parity
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_run

pytestmark = pytest.mark.risk


def _frame(close, volume, n=30):
    idx = pd.date_range("2026-08-01", periods=n, freq="D")
    rng = np.random.default_rng(7)
    c = close * (1 + rng.normal(0, 0.01, n))
    v = volume * (1 + rng.normal(0, 0.05, n))
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": v},
                        index=idx)


def _stamp(market, df, symbol="XDC"):
    rows = [{"symbol": symbol}]
    vivek_run._enrich_adv(rows, {"T": df}, {symbol: "T"}, market)
    return rows[0].get("adv_usd")


def test_the_markets_flag_the_way_the_fix_assumes():
    assert config.MARKETS["crypto"].volume_is_usd is True
    assert config.MARKETS["asx"].volume_is_usd is False
    assert config.MARKETS["nasdaq"].volume_is_usd is False


def test_crypto_averages_the_dollar_volume_it_is_given():
    df = _frame(0.03, 8_400_000)
    got = _stamp("crypto", df)
    assert got == pytest.approx(float(df.tail(20)["Volume"].mean()), abs=0.01)


@pytest.mark.parametrize("market", ["asx", "nasdaq"])
def test_stocks_still_multiply_close_by_share_volume(market):
    df = _frame(12.5, 400_000)
    got = _stamp(market, df, symbol="ABC")
    tail = df.tail(20)
    assert got == pytest.approx(float((tail["Close"] * tail["Volume"]).mean()), abs=0.01)


@pytest.mark.parametrize("market,close,volume", [
    ("crypto", 0.03, 8_400_000), ("crypto", 64_000.0, 30_000_000_000),
    ("asx", 0.85, 2_000_000), ("nasdaq", 150.0, 3_000_000)])
def test_the_live_stamp_equals_the_parity_replays(market, close, volume):
    """The live gate and the parity replay read ONE liquidity number."""
    df = _frame(close, volume)
    live = _stamp(market, df)
    parity = vivek_parity._adv_usd_at(df, len(df) - 1, market)
    assert live == pytest.approx(round(parity, 2), abs=0.01)


def test_no_market_keeps_the_old_close_times_volume():
    """A caller that passes no market gets the pre-fix behaviour, not a guess."""
    df = _frame(0.03, 8_400_000)
    tail = df.tail(20)
    assert _stamp(None, df) == pytest.approx(
        float((tail["Close"] * tail["Volume"]).mean()), abs=0.01)


def test_run_market_hands_its_market_to_the_stamp():
    src = inspect.getsource(vivek_run.run_market)
    assert "_enrich_adv(results, frames, yf_map, market)" in src


def test_a_cheap_liquid_coin_is_no_longer_refused_by_size_vs_adv():
    """The failure itself: a 3c coin trading ~$4M a day. Price x volume read
    ~$120k, under the $125k a $2,500 position needs at the 2% cap, so the bot
    refused it; its real ADV is ~$4M and it passes."""
    df = _frame(0.03, 4_000_000)
    need = config.VIVEK_BOT_POSITION_NOTIONAL * 100.0 / config.VIVEK_BOT_MAX_NOTIONAL_PCT_ADV
    tail = df.tail(20)
    assert float((tail["Close"] * tail["Volume"]).mean()) < need     # the old reading
    adv = _stamp("crypto", df)
    assert adv > need

    plan = {"armed": True, "entry_trigger": "reclaim", "entry": 0.03, "stop": 0.0288,
            "tp1": 0.0318, "tp2": 0.0336, "tp3": 0.036, "rr": 3.0,
            "scale": [0.25, 0.50, 0.15]}
    row = {"symbol": "XDC", "name": "XDC Network", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"], "price": 0.03,
           "plans": {"1W": plan}, "adv_usd": adv}
    out = vb.plan_trade(row, equity=150_000, market="crypto")
    assert out["plan"] is not None, out
    row["adv_usd"] = round(float((tail["Close"] * tail["Volume"]).mean()), 2)
    assert vb.plan_trade(row, equity=150_000, market="crypto")["code"] == "size_vs_adv"

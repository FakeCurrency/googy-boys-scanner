"""Audit 2026-10-08 #4 / #16 / #17: data.fetch's YAHOO FALLBACK LEG.

A coin no exchange lists (BDX, WBT, OKB have been held) or whose pair is
stale-rejected (BTT, LIT, XMR, BEAM) is priced off Yahoo. That leg had no
gate except identity, and identity read only the LAST ROW -- which on a Yahoo
crypto frame is yfinance's separate live quote, not the history VIVEK grades:

  #4  a frame whose newest bar is days old passed as fresh (the exchange legs
      refuse the same frozen series as `stale_rejected`), froze a held coin's
      mark and re-anchored it inside the frozen series;
  #17 history Yahoo stopped printing a year ago plus a live today row read
      0 days old (BTT: completed bars ending 2025-10-27, published B+ with
      data_age_days 0);
  #16 history rounded to 6 decimals passed identity on the live row's full
      precision (HTX: every close 2e-06 for a 1.71e-06 coin -- published B+
      with risk 0 and stop == entry == tp1).

Every refusal lands in the existing `refused` path, so the frame cache cannot
hand the same Yahoo frame back either. The exchanges are refused by conftest,
so every coin here reaches the Yahoo leg exactly as a coin no exchange lists.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from scanner import config, data, exchange_data as X

TODAY = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)


def _frame(closes, idx):
    closes = [float(c) for c in closes]
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                         "Volume": [1e6] * len(closes)}, index=pd.DatetimeIndex(idx))


def _walk(n, px=1.0, seed=7):
    """A real coin's closes: every one distinct."""
    rng = np.random.default_rng(seed)
    return list(px * np.exp(np.cumsum(rng.normal(0, 0.03, n))))


def _yahoo(df):
    return lambda t, period=None, **k: {x: df.copy() for x in t}


def _fetch(monkeypatch, df, ref=None, anchors=None, interval="1d", period="5y"):
    monkeypatch.setattr(data, "download", _yahoo(df))
    return data.fetch("crypto", ["ZZZ-USD"], period=period, interval=interval,
                      ref_prices={"ZZZ-USD": ref} if ref else None,
                      anchors={"ZZZ-USD": anchors} if anchors else None)


# ── #4: the quote itself froze ─────────────────────────────────────────────

def test_a_yahoo_series_frozen_six_days_ago_is_stale_not_a_live_price(monkeypatch):
    closes = _walk(300, px=0.7)
    closes[-1] = 1.0                                    # frozen at 1.00 ...
    df = _frame(closes, pd.date_range(end=TODAY - pd.Timedelta(days=6), periods=300))
    frames, rep = _fetch(monkeypatch, df, ref=0.75)     # ... real 0.75: inside the 40% band
    assert "ZZZ-USD" not in frames
    assert rep["stale_rejected"] == {"ZZZ": ["yahoo"]}
    assert rep["refused"] == ["ZZZ-USD"] and rep["rejected_venues"] == {"ZZZ-USD": ["yahoo"]}


def test_a_frozen_series_cannot_vouch_for_a_held_coin_through_its_anchor(monkeypatch):
    """The kill switch / held fetch path: the position's anchor sits INSIDE
    the frozen series, so anchor_ok passed and kept passing every run."""
    idx = pd.date_range(end=TODAY - pd.Timedelta(days=6), periods=30)
    df = _frame(_walk(30), idx)
    anchor = (idx[-2].strftime("%Y-%m-%d"), float(df["Close"].iloc[-2]))
    assert X.anchor_ok(df, anchor), "precondition: the anchor alone would vouch for it"
    frames, rep = _fetch(monkeypatch, df, anchors=anchor, period="1mo")
    assert "ZZZ-USD" not in frames and rep["stale_rejected"] == {"ZZZ": ["yahoo"]}


def test_the_frame_cache_does_not_hand_the_frozen_yahoo_frame_back(monkeypatch):
    idx = pd.date_range(end=TODAY - pd.Timedelta(days=6), periods=30)
    df = _frame(_walk(30), idx)
    df.attrs.update(source="yahoo", identity="ref")
    data.save_frame_cache("crypto", {"ZZZ-USD": df})
    frames, rep = _fetch(monkeypatch, df, ref=float(df["Close"].iloc[-1]))
    merged, stats = data.merge_with_cache("crypto", frames, ["ZZZ-USD"], refused=rep["refused"],
                                          rejected_venues=rep["rejected_venues"])
    assert "ZZZ-USD" not in merged and stats["refused"] == 1


def test_a_live_yahoo_series_still_prices_the_coin(monkeypatch):
    df = _frame(_walk(300), pd.date_range(end=TODAY, periods=300))
    frames, rep = _fetch(monkeypatch, df, ref=float(df["Close"].iloc[-1]))
    assert "ZZZ-USD" in frames and rep["source_of"] == {"ZZZ-USD": "yahoo"}
    assert frames["ZZZ-USD"].attrs["identity"] == "ref"
    assert rep["refused"] == [] and rep["stale_rejected"] == {}


def test_yesterday_as_the_newest_bar_is_inside_the_same_one_day_gate(monkeypatch):
    """Just after 00:00 UTC Yahoo may not have opened today's row yet."""
    df = _frame(_walk(300), pd.date_range(end=TODAY - pd.Timedelta(days=1), periods=300))
    frames, _ = _fetch(monkeypatch, df, ref=float(df["Close"].iloc[-1]))
    assert "ZZZ-USD" in frames


def test_the_4h_leg_gets_the_same_newest_bar_gate(monkeypatch):
    stale = _frame(_walk(200), pd.date_range(end=TODAY - pd.Timedelta(days=5), periods=200, freq="h"))
    frames, rep = _fetch(monkeypatch, stale, interval="4h", period="60d")
    assert "ZZZ-USD" not in frames and rep["stale_rejected"] == {"ZZZ": ["yahoo"]}
    live = _frame(_walk(200), pd.date_range(end=TODAY + pd.Timedelta(hours=1), periods=200, freq="h"))
    frames, _ = _fetch(monkeypatch, live, interval="4h", period="60d")
    assert "ZZZ-USD" in frames


# ── #17: a live row glued onto history Yahoo stopped printing ──────────────

def test_a_live_today_row_on_year_old_history_is_stale(monkeypatch):
    """BTT as committed: completed bars end 2025-10-27, the live row is today."""
    idx = pd.date_range(end="2025-10-27", periods=300).append(pd.DatetimeIndex([TODAY]))
    closes = _walk(300) + [1.0]
    df = _frame(closes, idx)
    assert X.bar_age_days(df) == 0, "precondition: the raw last row reads fresh"
    frames, rep = _fetch(monkeypatch, df, ref=1.0)
    assert "ZZZ-USD" not in frames and rep["stale_rejected"] == {"ZZZ": ["yahoo"]}


def test_yahoos_late_d_minus_1_is_tolerated_but_two_missing_sessions_are_not(monkeypatch):
    """Measured 2026-10-07 05:52Z: 31 healthy Yahoo frames ended D-2 plus the
    live row (Yahoo prints D-1 late). That shape must keep pricing."""
    for gap, ok in ((2, True), (3, False)):
        idx = pd.date_range(end=TODAY - pd.Timedelta(days=gap), periods=300) \
            .append(pd.DatetimeIndex([TODAY]))
        df = _frame(_walk(301), idx)
        assert X.completed_bar_age_days(df) == gap
        frames, _ = _fetch(monkeypatch, df, ref=float(df["Close"].iloc[-1]))
        assert ("ZZZ-USD" in frames) is ok, gap
    assert config.CRYPTO_YAHOO_MAX_COMPLETED_AGE_DAYS == 2


def test_a_frame_holding_only_todays_live_row_is_not_called_stale(monkeypatch):
    df = _frame([1.0], [TODAY])
    assert X.completed_bar_age_days(df) is None
    frames, _ = _fetch(monkeypatch, df, ref=1.0, period="5d")
    assert "ZZZ-USD" in frames


# ── #16: history quantized below the coin's own price grid ─────────────────

def test_quantized_history_under_a_full_precision_live_row_is_refused(monkeypatch):
    """HTX as committed: every completed close 2e-06, live row 1.71e-06,
    CoinGecko 1.70e-06 -- the live row passes the identity band."""
    df = _frame([2e-06] * 300 + [1.71e-06], pd.date_range(end=TODAY, periods=301))
    assert X.same_coin(df, 1.7e-06), "precondition: the live-row check passes"
    frames, rep = _fetch(monkeypatch, df, ref=1.7e-06)
    assert "ZZZ-USD" not in frames
    assert rep["identity_rejected"] == {"ZZZ": ["yahoo"]} and rep["refused"] == ["ZZZ-USD"]


def test_quantized_history_is_refused_under_an_anchor_too(monkeypatch):
    df = _frame([2e-06] * 300 + [1.71e-06], pd.date_range(end=TODAY, periods=301))
    anchor = ((TODAY - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), 2e-06)
    assert X.anchor_ok(df, anchor), "precondition: the anchor alone would vouch for it"
    frames, rep = _fetch(monkeypatch, df, anchors=anchor)
    assert "ZZZ-USD" not in frames and rep["identity_rejected"] == {"ZZZ": ["yahoo"]}


def test_a_two_level_grid_is_still_quantized_and_a_real_sub_cent_coin_is_not():
    two = _frame([1e-06, 2e-06] * 150 + [1.4e-06], pd.date_range(end=TODAY, periods=301))
    assert X.quantized(two)
    # Binance SHIB at 5.4e-06 printed 17 distinct closes of 20: a real coin.
    real = _frame(_walk(300, px=5.4e-06) + [5.4e-06], pd.date_range(end=TODAY, periods=301))
    assert not X.quantized(real)


def test_quantization_is_judged_on_completed_bars_only():
    """19 flat completed closes + 1 different one = 2 distinct: quantized,
    however different the live row is."""
    closes = [2e-06] * 299 + [3e-06] + [1.71e-06]
    assert X.quantized(_frame(closes, pd.date_range(end=TODAY, periods=301)))


def test_the_live_row_never_counts_toward_the_distinct_closes():
    """Four grid levels in the last 20 COMPLETED closes is quantized; the live
    row's full-precision fifth value must not lift it over the bar (counting
    the raw tail would read 5 distinct and let the junk history through)."""
    grid = [1e-06, 2e-06, 3e-06, 4e-06]
    closes = [2e-06] * 280 + [grid[i % 4] for i in range(20)] + [1.71e-06]
    df = _frame(closes, pd.date_range(end=TODAY, periods=301))
    assert df["Close"].iloc[-20:].nunique() == 5, "precondition: the raw tail reads 5"
    assert X.quantized(df)


def test_a_short_frame_is_not_judged(monkeypatch):
    """The kill switch asks for 5d: four completed bars cannot show a grid."""
    df = _frame([2e-06] * 4 + [1.71e-06], pd.date_range(end=TODAY, periods=5))
    assert not X.quantized(df)
    frames, _ = _fetch(monkeypatch, df, ref=1.7e-06, period="5d")
    assert "ZZZ-USD" in frames


def test_the_intraday_leg_is_not_judged_for_quantization(monkeypatch):
    df = _frame([2e-06] * 200, pd.date_range(end=TODAY + pd.Timedelta(hours=1), periods=200,
                                             freq="h"))
    frames, _ = _fetch(monkeypatch, df, interval="4h", period="60d")
    assert "ZZZ-USD" in frames


@pytest.mark.parametrize("name", ["CRYPTO_YAHOO_MAX_COMPLETED_AGE_DAYS",
                                  "CRYPTO_YAHOO_QUANT_BARS", "CRYPTO_YAHOO_QUANT_MIN_DISTINCT"])
def test_the_thresholds_live_in_config(name):
    assert int(getattr(config, name)) > 0


def test_the_quantization_bar_sits_far_below_every_real_coin_measured():
    """17-20 distinct of 20 on every real coin in the committed scans; 1 on
    BTT and HTX. A floor near the real coins would refuse real ones."""
    assert config.CRYPTO_YAHOO_QUANT_MIN_DISTINCT * 3 <= config.CRYPTO_YAHOO_QUANT_BARS


def test_completed_bar_age_reads_the_forming_bar_off_the_end():
    now = dt.datetime.now(dt.timezone.utc)
    df = _frame([1.0, 2.0, 3.0], pd.date_range(end=TODAY, periods=3))
    assert X.completed_bar_age_days(df, now) == 1 and X.bar_age_days(df, now) == 0

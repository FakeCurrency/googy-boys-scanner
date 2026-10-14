"""4H plans built on the chart's own bars, with exact marker times (REFINE200 #106).

Two defects, one outcome: the chart's 4H reaction/trigger marks were not on
the bar the engine meant.

1. yfinance returns intraday bars in the EXCHANGE's zone and pandas anchors
   "4h" bins on local midnight, so an ASX 4H plan was built on 21/01/05Z
   (AEDT) bins while the chart drew 20/00/04Z candles (public/js/chart.js
   bucketBars, `t - t % 14400`). The engine's docstring and
   test_h4_plans.test_buckets_are_EPOCH_anchored_so_they_match_the_chart
   promised the opposite, but that test feeds a UTC index, which yfinance
   never returns for a stock.
2. The plan's trigger/reaction bars were published as DATES, so on a chart
   with two or three 4H bars a session the marker snapped to the first.

Display only: build_h4_plan feeds the chart's 4H toggle and nothing else
(test_h4_plans pins that fence).
"""
import numpy as np
import pandas as pd

from scanner import vivek

HOUR = 3600


def _session_hours(tz, days, hours, closes):
    idx, vals = [], []
    k = 0
    for d in days:
        for h in hours:
            idx.append(pd.Timestamp(f"{d} {h}", tz=tz))
            vals.append(closes[k % len(closes)])
            k += 1
    v = np.array(vals, dtype=float)
    return pd.DataFrame({"Open": v, "High": v * 1.004, "Low": v * 0.996, "Close": v,
                         "Volume": np.ones(len(v)) * 5000}, index=pd.DatetimeIndex(idx))


def _chart_buckets(df):
    """chart.js bucketBars on the same hourly bars: floor(t / 4h) * 4h, UTC."""
    secs = [int(t.timestamp()) for t in df.index]
    return sorted({t - t % (4 * HOUR) for t in secs})


def test_asx_4h_bins_are_the_charts_bins_under_aedt_and_aest():
    hours = ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00"]
    for days in (["2026-10-05", "2026-10-06", "2026-10-07"],      # AEDT, UTC+11
                 ["2026-08-11", "2026-08-12", "2026-08-13"]):     # AEST, UTC+10
        df = _session_hours("Australia/Sydney", days, hours, [1.0, 1.1, 1.2])
        h4 = vivek._resample_4h_ohlc(df)
        got = [int(t.timestamp()) for t in h4.index]
        assert got == _chart_buckets(df), (
            f"engine 4H bins {[t.isoformat() for t in h4.index]} are not the chart's")


def test_nasdaq_4h_bins_match_in_winter_too():
    days = ["2026-12-14", "2026-12-15"]                            # EST, UTC-5
    hours = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    df = _session_hours("America/New_York", days, hours, [5.0, 5.1])
    h4 = vivek._resample_4h_ohlc(df)
    assert [int(t.timestamp()) for t in h4.index] == _chart_buckets(df)


def test_ohlc_survives_the_conversion():
    df = _session_hours("Australia/Sydney", ["2026-10-05"], ["10:00", "11:00", "12:00"], [1.0, 3.0, 2.0])
    h4 = vivek._resample_4h_ohlc(df)
    # 10:00 Sydney (23:00Z) sits in the 20:00Z bin alone; 11:00/12:00 (00/01Z) in the 00:00Z bin.
    assert list(h4["Close"]) == [1.0, 2.0]
    assert h4["High"].iloc[1] == 3.0 * 1.004


def _v_hourly(n=1400):
    base = np.concatenate([np.linspace(30.0, 18.0, n // 2), np.linspace(18.0, 27.0, n - n // 2)])
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="Australia/Sydney")
    return pd.DataFrame({"Open": base, "High": base * 1.004, "Low": base * 0.996,
                         "Close": base, "Volume": np.ones(n) * 5000}, index=idx)


def test_a_4h_plan_stamps_its_bars_to_the_second_and_markers_carry_it(monkeypatch):
    # The detectors are pinned to known bars: this is about STAMPING a bar the
    # engine chose, not about which bar it chooses (test_vivek owns that).
    monkeypatch.setattr(vivek, "detect_trigger",
                        lambda f, d, lvl: {"type": "reclaim", "entry": float(f["Close"].iloc[-1]), "bar": len(f) - 1})
    monkeypatch.setattr(vivek, "_recent_reaction_bar", lambda f, d, lvl: len(f) - 2)
    df = _v_hourly()
    p = vivek.build_h4_plan(df, "long")
    assert p is not None
    h4 = vivek._resample_4h_ohlc(df)
    assert p["trigger_ts"] == int(h4.index[-1].timestamp()), "the trigger is the LAST 4H bar, to the second"
    assert p["reaction_ts"] == int(h4.index[-2].timestamp())
    stamped = 0
    for kind in ("trigger", "reaction"):
        date, ts = p.get(f"{kind}_bar"), p.get(f"{kind}_ts")
        if date is None:
            assert ts is None
            continue
        stamped += 1
        assert isinstance(ts, int) and ts % (4 * HOUR) == 0, "a 4H bar starts on a 4-hour UTC boundary"
        assert pd.Timestamp(ts, unit="s", tz="UTC").strftime("%Y-%m-%d") == date, "the date is the ts's UTC date"
    assert stamped, "the fixture must exercise at least one stamped bar"
    ms = vivek.build_markers({"4H": p})["4H"]
    for m in ms:
        assert m.get("ts") == p.get(f"{m['kind']}_ts"), "the marker carries the exact bar"


def test_daily_plans_carry_no_timestamps():
    """Only intraday plans need them; the daily/3D/weekly payload is unchanged."""
    days = pd.date_range("2024-01-01", periods=400, freq="B")
    v = np.concatenate([np.linspace(30, 18, 200), np.linspace(18, 27, 200)])
    df = pd.DataFrame({"Open": v, "High": v * 1.01, "Low": v * 0.99, "Close": v,
                       "Volume": np.ones(400) * 1e6}, index=days)
    p = vivek.build_tf_plan(df, "long")
    assert p is not None
    assert "trigger_ts" not in p and "reaction_ts" not in p
    assert all("ts" not in m for m in vivek.build_markers({"1D": p})["1D"])

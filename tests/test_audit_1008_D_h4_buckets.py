"""Audits #19 + #20 (2026-10-08): the 4H plan's candles and markers.

#19 -- `_resample_4h_ohlc` promised epoch-anchored UTC buckets, "exactly as the
chart's t - t % (4*3600) does", but Yahoo's 1h stock bars arrive tz-aware in the
EXCHANGE zone and pandas anchors its bins in the index's own zone. ASX bins cut
at Sydney midnight (13:00/14:00Z: 2 bars a day against the chart's 3), so the
plan's 200-SMA, stop and trigger described candles the chart never drew; NASDAQ
matched only under EDT. The fix converts a tz-aware index to UTC first.

#20 -- the 4H plan's trigger/reaction markers carried a DATE only, and a date
names up to six 4H bars: the chart drew the trigger on the day's first candle.
Engine half of the cross-cluster contract: every marker built for the 4H plan
carries `ts` = UTC epoch SECONDS of that bar's open (the plan carries
`trigger_ts` / `reaction_ts` likewise); the date fields are unchanged and
Daily / 3-Day / Weekly markers carry no `ts`. (The chart half -- placing a `ts`
marker on the drawn candle whose bucket holds that instant -- is chart.js's.)
"""
import numpy as np
import pandas as pd

from scanner import scan, vivek

H4 = 4 * 3600


def _epoch(ts) -> int:
    return int(pd.Timestamp(ts).timestamp())


def _session_hourly(tz, start_hour, end_hour, days, end, minute=0):
    idx = []
    for d in pd.bdate_range(end=end, periods=days):
        for h in range(start_hour, end_hour + 1):
            idx.append(pd.Timestamp(f"{d.date()} {h:02d}:{minute:02d}", tz=tz))
    return pd.DatetimeIndex(idx)


def _flat(idx, close=100.0):
    c = np.full(len(idx), close)
    return pd.DataFrame({"Open": c, "High": c * 1.004, "Low": c * 0.996,
                         "Close": c, "Volume": 5000.0}, index=idx)


def _chart_buckets(idx) -> dict:
    """The chart's arithmetic: bucket = t - t % (4*3600) on epoch seconds."""
    out: dict[int, int] = {}
    for t in idx:
        e = _epoch(t)
        out[e - e % H4] = out.get(e - e % H4, 0) + 1
    return out


def _engine_buckets(df) -> dict:
    h4 = vivek._resample_4h_ohlc(df)
    assert h4 is not None
    # Volume is 5000 per hourly bar, so a bin's Volume / 5000 is its bar count.
    return {_epoch(t): int(round(v / 5000.0)) for t, v in zip(h4.index, h4["Volume"])}


# ── #19: the engine builds the chart's candles ───────────────────────────────

def test_asx_hourly_bars_bucket_exactly_like_the_chart_under_aedt():
    # every session after the 2026-10-04 switch to AEDT
    idx = _session_hourly("Australia/Sydney", 10, 16, days=8, end="2026-10-16")
    df = _flat(idx)
    eng, chart = _engine_buckets(df), _chart_buckets(idx)
    assert eng == chart, "4H plan built from different candles than the chart draws"
    for start in eng:
        assert start % H4 == 0
    # a 10:00-16:00 AEDT session is 23:00Z-05:00Z: three chart candles a day (1+4+2)
    per_day = sorted(chart.values())
    assert set(per_day) == {1, 2, 4}


def test_asx_buckets_match_the_chart_under_aest_too():
    idx = _session_hourly("Australia/Sydney", 10, 16, days=10, end="2026-07-08")
    assert _engine_buckets(_flat(idx)) == _chart_buckets(idx)


def test_nasdaq_buckets_match_the_chart_under_est():
    """From 2026-11-01 New York is UTC-5 and local midnight is 05:00Z, which
    is not a 4-hour boundary: the old resample shifted every bin an hour."""
    idx = _session_hourly("America/New_York", 9, 15, days=10, end="2026-11-20", minute=30)
    eng, chart = _engine_buckets(_flat(idx)), _chart_buckets(idx)
    assert eng == chart
    assert all(s % H4 == 0 for s in eng)


def test_the_same_instants_bucket_identically_whatever_the_index_zone():
    idx = _session_hourly("Australia/Sydney", 10, 16, days=5, end="2026-10-08")
    aware = vivek._resample_4h_ohlc(_flat(idx))
    naive = vivek._resample_4h_ohlc(_flat(idx.tz_convert("UTC").tz_localize(None)))
    assert [_epoch(t) for t in aware.index] == [_epoch(t) for t in naive.index]
    assert np.allclose(aware.to_numpy(), naive.to_numpy())


# ── #20: 4H markers carry the bar's instant, not just its day ────────────────

def _asx_reclaim_on_the_last_4h_candle():
    """~60 sessions flat at 100, a dip to 99 in the 00:00Z candle (11:00-14:00
    AEDT) and a reclaim to 103 in the 04:00Z candle (15:00-16:00) of the last day.
    The last candle's low sits >2% above the level, so the REACTION is the dip
    candle -- same calendar date as the trigger, a different bar."""
    idx = _session_hourly("Australia/Sydney", 10, 16, days=60, end="2026-10-08")
    df = _flat(idx)
    buckets = np.array([_epoch(t) - _epoch(t) % H4 for t in idx])
    last, prev = sorted(set(buckets))[-1], sorted(set(buckets))[-2]
    for col, v in (("Open", 99.0), ("High", 99.4), ("Low", 98.5), ("Close", 99.0)):
        df.loc[buckets == prev, col] = v
    for col, v in (("Open", 103.0), ("High", 103.4), ("Low", 102.6), ("Close", 103.0)):
        df.loc[buckets == last, col] = v
    return df, int(last), int(prev)


def test_the_4h_plan_carries_the_trigger_and_reaction_bar_instants():
    df, last, prev = _asx_reclaim_on_the_last_4h_candle()
    p = vivek.build_h4_plan(df, "long")
    assert p and p["armed"] and p["entry_trigger"] == "reclaim"
    assert p["trigger_ts"] == last == _epoch("2026-10-08 04:00Z")
    assert p["reaction_ts"] == prev == _epoch("2026-10-08 00:00Z")
    # the date fields are unchanged in shape, and now UTC dates like the chart's
    assert p["trigger_bar"] == p["reaction_bar"] == "2026-10-08"
    assert isinstance(p["trigger_ts"], int) and isinstance(p["reaction_ts"], int)


def test_4h_markers_carry_ts_and_daily_markers_do_not():
    df, last, prev = _asx_reclaim_on_the_last_4h_candle()
    p4 = vivek.build_h4_plan(df, "long")
    daily = {"armed": True, "entry_trigger": "break",
             "trigger_bar": "2026-10-08", "reaction_bar": "2026-10-07"}
    m = vivek.build_markers({"4H": p4, "1D": daily})
    by_kind = {x["kind"]: x for x in m["4H"]}
    assert by_kind["trigger"]["ts"] == last and by_kind["trigger"]["date"] == "2026-10-08"
    assert by_kind["reaction"]["ts"] == prev
    assert all("ts" not in x for x in m["1D"])


def test_daily_weekly_and_3day_plans_never_carry_instants():
    idx = pd.date_range(end="2026-10-08", periods=1400, freq="D")
    base = np.concatenate([np.linspace(30, 18, 700), np.linspace(18, 27, 700)])
    df = pd.DataFrame({"Open": base, "High": base * 1.01, "Low": base * 0.99,
                       "Close": base, "Volume": 1e6}, index=idx)
    plans = vivek.build_plans(df, {"direction": "long"})
    assert plans
    for tf, p in plans.items():
        assert "trigger_ts" not in p and "reaction_ts" not in p, tf
    for tf, ms in vivek.build_markers(plans).items():
        assert all("ts" not in x for x in ms), tf


def test_the_scan_publishes_4h_markers_with_ts(monkeypatch):
    df, last, prev = _asx_reclaim_on_the_last_4h_candle()
    monkeypatch.setattr(scan, "download", lambda t, **k: {x: df for x in t})
    row = {"symbol": "BHP", "dir": "LONG", "price": 103.0,
           "plans": {"1D": {"entry": 1.0}}, "markers": {"1D": []}}
    scan._attach_h4_plans([row], "asx")
    m4 = {x["kind"]: x for x in row["markers"]["4H"]}
    assert m4["trigger"]["ts"] == last
    assert row["plans"]["4H"]["trigger_ts"] == last
    assert row["markers"]["1D"] == []

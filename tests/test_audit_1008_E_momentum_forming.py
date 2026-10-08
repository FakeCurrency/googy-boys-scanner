"""2026-10-08 audit, cluster E -- #85: MOMENTUM crypto screened the
in-progress UTC candle and published it as `last_closed_bar`.

screen_symbol's contract (closed bars only; "on crypto it means dropping the
in-progress UTC day") was never met: the crypto run is due from 00:30 UTC,
Yahoo's daily series already carries today's candle, and nothing dropped it.
The committed crypto.json of 2026-10-08 (generated 01:13:24Z) reported
last_closed_bar 2026-10-08 and its only hit fired on that 73-minute-old bar.
Dropping the forming crypto bar is the owner's call the 2026-09-23 review
deferred; approved 2026-10-08 ("Do it all").
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from scanner.momentum import run as R

UTC = dt.timezone.utc


def _coin(end: dt.date, *, n: int = 400, usd_vol: float = 2e7) -> pd.DataFrame:
    """A daily crypto frame (calendar days, Volume already USD) ending `end`."""
    idx = pd.date_range(end=pd.Timestamp(end), periods=n, freq="D")
    rng = np.random.default_rng(n)
    c = 10.0 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    prev = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"Open": prev, "High": np.maximum(c, prev) * 1.01,
                         "Low": np.minimum(c, prev) * 0.99, "Close": c,
                         "Volume": np.full(n, usd_vol)}, index=idx)


def test_the_2026_10_08_run_reports_the_completed_bar_not_the_forming_one():
    now = dt.datetime(2026, 10, 8, 1, 13, 24, tzinfo=UTC)
    frames = {"GOMINING-USD": _coin(dt.date(2026, 10, 8)), "BTC-USD": _coin(dt.date(2026, 10, 8))}
    p = R.screen_market("crypto", frames=frames, rows=[], now=now)
    assert p["last_closed_bar"] == "2026-10-07"
    assert p["summary"]["forming_dropped"] == 2


def test_by_the_real_clock_todays_utc_candle_is_never_screened(monkeypatch):
    today = dt.datetime.now(UTC).date()
    seen = []
    real = R.screen_symbol

    def spy(df, cfg=None, symbol="", market=""):
        seen.append(pd.Timestamp(df.index[-1]).date())
        return real(df, cfg, symbol=symbol, market=market)
    monkeypatch.setattr(R, "screen_symbol", spy)
    p = R.screen_market("crypto", frames={"AAA-USD": _coin(today)}, rows=[])
    assert seen == [today - dt.timedelta(days=1)]
    assert p["last_closed_bar"] == (today - dt.timedelta(days=1)).isoformat()


def test_the_frame_cache_never_receives_the_partial_candle(monkeypatch):
    today = dt.datetime.now(UTC).date()
    saved = {}
    monkeypatch.setattr(R.sdata, "download", lambda tickers, **kw: {"AAA-USD": _coin(today)})

    def merge(key, fresh, tickers, **kw):
        saved.update(fresh)
        return dict(fresh), {}
    monkeypatch.setattr(R.sdata, "merge_with_cache", merge)
    R.screen_market("crypto", rows=[{"yf": "AAA-USD", "symbol": "AAA", "name": "Aaa"}])
    assert pd.Timestamp(saved["AAA-USD"].index[-1]).date() == today - dt.timedelta(days=1)


def test_a_run_straddling_utc_midnight_drops_the_bar_fetched_before_it():
    d = dt.date(2026, 10, 8)
    since = dt.datetime(2026, 10, 8, 23, 58, tzinfo=UTC)
    now = dt.datetime(2026, 10, 9, 0, 3, tzinfo=UTC)
    out, n = R.drop_forming({"AAA-USD": _coin(d)}, "crypto", now, since)
    assert n == 1 and out["AAA-USD"].index[-1].date() == d - dt.timedelta(days=1)
    # a completed day stays, and a coin fetched after midnight sheds only the new day
    out, n = R.drop_forming({"AAA-USD": _coin(d), "BBB-USD": _coin(d + dt.timedelta(days=1))},
                            "crypto", now)
    assert n == 1 and out["AAA-USD"].index[-1].date() == d
    assert out["BBB-USD"].index[-1].date() == d


def test_equity_frames_are_left_to_momentum_due_by_design():
    """Equities are kept out of their session by the due gate (spec 5.11), so
    the drop is a 24/7-market rule only and a scheduled equity screen is
    untouched."""
    idx = pd.bdate_range(end="2026-10-08", periods=300)
    f = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": 1.0, "Volume": 1e6}, index=idx)
    mid_session = dt.datetime(2026, 10, 8, 2, 0, tzinfo=UTC)      # 13:00 Sydney
    out, n = R.drop_forming({"Z.AX": f}, "asx", mid_session)
    assert n == 0 and out["Z.AX"] is not None and len(out["Z.AX"]) == 300


def test_the_live_run_asks_the_clock_before_the_download_too(monkeypatch):
    """screen_market reads the clock before AND after the download and hands
    both to drop_forming: a run fetching 23:58 -> 00:03 UTC got its coins
    while 2026-10-08's candle was still open, and the after-download clock
    alone calls that candle completed."""
    import types
    d = dt.date(2026, 10, 8)
    ticks = iter([dt.datetime(2026, 10, 8, 23, 58, tzinfo=UTC)])
    after = dt.datetime(2026, 10, 9, 0, 3, tzinfo=UTC)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return next(ticks, after)
    monkeypatch.setattr(R, "dt", types.SimpleNamespace(
        datetime=Clock, timezone=dt.timezone, timedelta=dt.timedelta, date=dt.date))
    monkeypatch.setattr(R.sdata, "download", lambda tickers, **kw: {"AAA-USD": _coin(d)})
    saved = {}

    def merge(key, fresh, tickers, **kw):
        saved.update(fresh)
        return dict(fresh), {}
    monkeypatch.setattr(R.sdata, "merge_with_cache", merge)
    p = R.screen_market("crypto", rows=[{"yf": "AAA-USD", "symbol": "AAA", "name": "Aaa"}])
    assert pd.Timestamp(saved["AAA-USD"].index[-1]).date() == d - dt.timedelta(days=1)
    assert p["summary"]["forming_dropped"] == 1


def test_an_undatable_last_bar_does_not_sink_the_market():
    """drop_forming runs outside the per-symbol try, so one frame whose last
    index is NaT must be kept (daily_bar_forming's contract) rather than
    raise and take every other coin's screen down with it."""
    bad = _coin(dt.date(2026, 10, 7))
    bad.index = bad.index[:-1].append(pd.DatetimeIndex([pd.NaT]))
    good = _coin(dt.date(2026, 10, 8))
    out, n = R.drop_forming({"BAD-USD": bad, "GOOD-USD": good}, "crypto",
                            dt.datetime(2026, 10, 8, 1, 0, tzinfo=UTC))
    assert len(out["BAD-USD"]) == len(bad)
    assert n == 1 and out["GOOD-USD"].index[-1].date() == dt.date(2026, 10, 7)

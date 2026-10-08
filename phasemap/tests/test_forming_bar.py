"""Detection sees CLOSED daily bars only.

v1.3.0 (review H3): 24/7 markets. The nightly job fires ~8.5h into the UTC
crypto day; before this rule the newest "daily" row was the still-forming
candle, so displacement/tier could print off a partial bar and then un-print
by midnight.

v1.3.2 (audit #8, 2026-10-08): equities too. The 08:30 UTC nightly is NOT
reliably post-close -- on 2026-10-07 it committed at 15:52 UTC = 11:52 EDT,
~2.5h into the NASDAQ session, and 95 published NASDAQ records hinged on the
partial 10-07 bar. The forming test is scanner.config.daily_bar_forming()
(ASX final 16:40 Sydney, NASDAQ 16:05 New York, crypto UTC midnight).
"""

import datetime as dt

import pandas as pd

from phasemap.config import CONFIG
from phasemap.engine.scanner import drop_forming_bar

UTC = dt.timezone.utc


def _df(dates):
    return pd.DataFrame({"Date": pd.to_datetime(list(dates)),
                         "Open": 1.0, "High": 2.0, "Low": 0.5,
                         "Close": 1.5, "Volume": 10.0})


# 08:30 UTC on 2026-07-20: the on-time nightly (crypto day 8.5h old)
NOW = dt.datetime(2026, 7, 20, 8, 30, tzinfo=UTC)


def test_crypto_forming_bar_is_dropped():
    df = _df(["2026-07-18", "2026-07-19", "2026-07-20"])
    out = drop_forming_bar(df, "crypto", now=NOW)
    assert len(out) == 2
    assert out["Date"].iloc[-1].date() == dt.date(2026, 7, 19)


def test_crypto_completed_last_bar_is_kept():
    df = _df(["2026-07-17", "2026-07-18", "2026-07-19"])   # newest bar already closed
    out = drop_forming_bar(df, "crypto", now=NOW)
    assert len(out) == 3


def test_every_published_market_is_guarded():
    # audit #8: equities were listed as exempt ("scanned post-close")
    for market in ("asx", "nasdaq", "crypto"):
        assert market in CONFIG.drop_forming_bar_markets


def test_the_late_nightly_of_2026_10_07_drops_nasdaqs_mid_session_bar():
    # 15:52:17 UTC = 11:52 EDT: the NASDAQ 10-07 session had 4h left to run
    late = dt.datetime(2026, 10, 7, 15, 52, 17, tzinfo=UTC)
    df = _df(["2026-10-05", "2026-10-06", "2026-10-07"])
    out = drop_forming_bar(df, "nasdaq", now=late)
    assert len(out) == 2
    assert out["Date"].iloc[-1].date() == dt.date(2026, 10, 6)


def test_a_nasdaq_bar_is_kept_once_it_is_final():
    # 20:06 UTC = 16:06 EDT, past the 16:05 New York final instant
    after = dt.datetime(2026, 10, 7, 20, 6, tzinfo=UTC)
    df = _df(["2026-10-05", "2026-10-06", "2026-10-07"])
    assert len(drop_forming_bar(df, "nasdaq", now=after)) == 3
    # and the on-time 08:30 UTC run (04:30 EDT) holds only closed bars
    early = dt.datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    assert len(drop_forming_bar(df, "nasdaq", now=early)) == 3


def test_the_asx_bar_is_forming_until_16_40_sydney():
    df = _df(["2026-10-06", "2026-10-07", "2026-10-08"])
    # 05:20 UTC = 16:20 AEDT: auction printed but not yet final on the feed
    pre = dt.datetime(2026, 10, 8, 5, 20, tzinfo=UTC)
    assert len(drop_forming_bar(df, "asx", now=pre)) == 2
    # 08:30 UTC = 19:30 AEDT: the on-time nightly keeps the closed bar
    post = dt.datetime(2026, 10, 8, 8, 30, tzinfo=UTC)
    assert len(drop_forming_bar(df, "asx", now=post)) == 3
    # a nightly so late it lands in the NEXT Sydney session (23:30 UTC =
    # 10:30 AEDT on the 9th) drops the 9th's partial row
    nxt = _df(["2026-10-07", "2026-10-08", "2026-10-09"])
    late = dt.datetime(2026, 10, 8, 23, 30, tzinfo=UTC)
    assert len(drop_forming_bar(nxt, "asx", now=late)) == 2


def test_only_one_bar_is_ever_dropped():
    df = _df(["2026-10-06", "2026-10-07"])
    late = dt.datetime(2026, 10, 7, 15, 52, tzinfo=UTC)
    out = drop_forming_bar(df, "nasdaq", now=late)
    assert len(out) == 1


def test_empty_and_none_frames_are_safe():
    assert drop_forming_bar(None, "crypto", now=NOW) is None
    empty = _df([]).iloc[0:0]
    assert len(drop_forming_bar(empty, "crypto", now=NOW)) == 0
    assert len(drop_forming_bar(empty, "nasdaq", now=NOW)) == 0

"""v1.3.0 (review H3): 24/7 markets scan CLOSED bars only.

The nightly job fires ~8.5h into the UTC crypto day; before this rule the
newest "daily" row was the still-forming candle, so displacement/tier could
print off a partial bar and then un-print by midnight.
"""

import datetime as dt

import pandas as pd

from phasemap.engine.scanner import drop_forming_bar


def _df(dates):
    return pd.DataFrame({"Date": pd.to_datetime(list(dates)),
                         "Open": 1.0, "High": 2.0, "Low": 0.5,
                         "Close": 1.5, "Volume": 10.0})


TODAY = dt.date(2026, 7, 20)


def test_crypto_forming_bar_is_dropped():
    df = _df(["2026-07-18", "2026-07-19", "2026-07-20"])
    out = drop_forming_bar(df, "crypto", today=TODAY)
    assert len(out) == 2
    assert out["Date"].iloc[-1].date() == dt.date(2026, 7, 19)


def test_crypto_completed_last_bar_is_kept():
    df = _df(["2026-07-17", "2026-07-18", "2026-07-19"])   # newest bar already closed
    out = drop_forming_bar(df, "crypto", today=TODAY)
    assert len(out) == 3


def test_equity_markets_pass_through_untouched():
    df = _df(["2026-07-18", "2026-07-19", "2026-07-20"])
    for market in ("asx", "nasdaq"):
        assert len(drop_forming_bar(df, market, today=TODAY)) == 3


def test_empty_and_none_frames_are_safe():
    assert drop_forming_bar(None, "crypto", today=TODAY) is None
    empty = _df([]).iloc[0:0]
    assert len(drop_forming_bar(empty, "crypto", today=TODAY)) == 0

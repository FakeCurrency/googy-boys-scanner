"""2026-10-08 audit, cluster E -- IGNITION's close (#22). Report-only lens.

#22  An ASX bar was COMPLETED from 16:00 Sydney (VIVEK_JOURNAL_SESSION's bell)
     while the repo's own close is 16:40 (config.DAILY_BAR_FINAL, the
     2026-10-06 ruling: Yahoo shows the auction ~20 min late). A run whose
     clock landed 16:00-16:40 published a breakout on a pre-auction bar as a
     CONFIRMED IGNITING row and saved that bar to the frame cache as final. The
     bar is now judged by config.daily_bar_forming, at BOTH the clock before
     the download and the one after it.

Network is never touched: the download is monkeypatched.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config
from scanner.ignition import run as RUN

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYD = ZoneInfo("Australia/Sydney")

_spec = importlib.util.spec_from_file_location("_ig_suite_e_close", ROOT / "tests" / "test_ignition.py")
_ig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ig)
build, T = _ig.build, _ig.T


def asx_frame(n_after: int) -> pd.DataFrame:
    """The crypto suite's base -> breakout fixture on a weekday calendar,
    trimmed to the trigger bar + `n_after` bars."""
    df = build()
    df.index = pd.bdate_range("2021-01-04", periods=len(df))
    return df.iloc[:T + 1 + n_after]


def _at(day, hh, mm):
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=SYD)


# ---------------------------------------------------------------------------
# #22 -- the ASX close is 16:40 Sydney, at both clocks, and never cached early
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hm,forming", [((15, 59), True), ((16, 1), True), ((16, 20), True),
                                        ((16, 39), True), ((16, 40), False), ((17, 24), False)])
def test_the_asx_bar_is_forming_until_the_1640_final_instant(hm, forming):
    day = dt.date(2026, 10, 8)
    assert RUN.bar_is_forming("asx", pd.Timestamp(day), _at(day, *hm)) is forming
    # one answer for the repo: the lens asks config, it keeps no close of its own
    assert RUN.bar_is_forming("asx", pd.Timestamp(day), _at(day, *hm)) is \
        config.daily_bar_forming("asx", day, _at(day, *hm))


def test_crypto_still_forms_until_utc_midnight():
    d = pd.Timestamp("2026-10-08")
    assert RUN.bar_is_forming("crypto", d, dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc))
    assert not RUN.bar_is_forming("crypto", d, dt.datetime(2026, 10, 9, 0, 0, tzinfo=dt.timezone.utc))
    # a bar dated after the clock (the day rolled while the download ran)
    assert RUN.bar_is_forming("crypto", pd.Timestamp("2026-10-09"),
                              dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc))


def test_a_bar_is_completed_only_if_final_at_the_clock_before_the_download_too():
    df = asx_frame(2)
    day = df.index[-1].date()
    # the download started 16:36 (pre-final) and ended 16:42 (post-final)
    done, forming = RUN._split_all({"Z.AX": df}, "asx", _at(day, 16, 42), _at(day, 16, 36))
    assert "Z.AX" in forming and done["Z.AX"].index[-1].date() < day
    # both clocks past 16:40 -> completed
    done, forming = RUN._split_all({"Z.AX": df}, "asx", _at(day, 16, 50), _at(day, 16, 41))
    assert forming == {} and done["Z.AX"].index[-1].date() == day


def _patch_download(monkeypatch, df, saved):
    rows = [{"yf": "ZZZ.AX", "symbol": "ZZZ", "name": "Zed Ltd"}]
    monkeypatch.setattr(RUN, "_download", lambda market, period, limit: (rows, {"ZZZ.AX": df}, {}))
    monkeypatch.setattr(RUN, "regime_frame", lambda market, period: None)
    monkeypatch.setattr(RUN.mcap, "known", lambda *a, **k: {})

    def merge(key, done, tickers, **kw):
        saved.update({k: v.copy() for k, v in done.items()})
        return dict(done), {"reused": 0}
    monkeypatch.setattr(RUN.sdata, "merge_with_cache", merge)


def test_a_1620_run_does_not_cache_todays_pre_auction_bar_as_final(monkeypatch):
    df = asx_frame(2)                     # a RUNNING trigger, last bar = "today"
    day = df.index[-1].date()
    saved: dict = {}
    _patch_download(monkeypatch, df, saved)
    pay = RUN.screen_market("asx", now=_at(day, 16, 20))
    assert saved["ZZZ.AX"].index[-1].date() < day, "the partial bar reached the frame cache"
    assert pay["last_closed_bar"] < day.isoformat()
    assert pay["summary"]["bars"]["raw_last"] == day.isoformat()   # still shown as forming


def test_the_live_run_reads_the_clock_before_the_download_too(monkeypatch):
    """16:36 when the fetch starts, 16:42 once the bars are in hand: the
    after-download clock alone would bank names fetched before the close was
    final on the feed."""
    import types
    df = asx_frame(2)
    day = df.index[-1].date()
    saved: dict = {}
    _patch_download(monkeypatch, df, saved)
    ticks = iter([_at(day, 16, 36), _at(day, 16, 42)])

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return next(ticks)
    monkeypatch.setattr(RUN, "dt", types.SimpleNamespace(
        datetime=Clock, timezone=dt.timezone, timedelta=dt.timedelta, date=dt.date))
    pay = RUN.screen_market("asx")
    assert saved["ZZZ.AX"].index[-1].date() < day
    # generated_at is the clock the bars were judged final against (review of
    # #22): the BEFORE-download one, so the backstop gate reads this file as
    # pre-close and re-screens -- see the gate test below
    assert pay["generated_at"].startswith(day.isoformat() + "T16:36")


def test_a_1620_breakout_is_provisional_not_a_confirmed_igniting(monkeypatch):
    df = asx_frame(0)                     # the trigger bar IS today's bar
    day = df.index[-1].date()
    saved: dict = {}
    _patch_download(monkeypatch, df, saved)
    pay = RUN.screen_market("asx", now=_at(day, 16, 20))
    row = pay["results"][0]
    assert row["state"] == "IGNITING" and row["provisional"] is True
    assert pay["summary"]["counts"]["igniting_confirmed"] == 0
    # after the final instant the same bar is the confirmed break
    saved.clear()
    pay = RUN.screen_market("asx", now=_at(day, 17, 24))
    assert pay["results"][0]["provisional"] is False
    assert pay["summary"]["counts"]["igniting_confirmed"] == 1
    assert saved["ZZZ.AX"].index[-1].date() == day


# ---------------------------------------------------------------------------
# review of #22 -- the backstop gate must agree with the forming-bar verdict
# ---------------------------------------------------------------------------

_due_spec = importlib.util.spec_from_file_location("_ig_asx_due_e22",
                                                   ROOT / "scripts" / "ignition_asx_due.py")
_due = importlib.util.module_from_spec(_due_spec)
_due_spec.loader.exec_module(_due)


def _clocked_run(monkeypatch, df, start, end):
    """screen_market('asx') with the download starting at `start` and the bars
    in hand at `end` (Sydney times on the frame's last day)."""
    import types
    day = df.index[-1].date()
    saved: dict = {}
    _patch_download(monkeypatch, df, saved)
    ticks = iter([_at(day, *start), _at(day, *end)])

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return next(ticks)
    monkeypatch.setattr(RUN, "dt", types.SimpleNamespace(
        datetime=Clock, timezone=dt.timezone, timedelta=dt.timedelta, date=dt.date))
    return RUN.screen_market("asx"), saved


def test_a_run_straddling_the_close_leaves_the_backstop_due(monkeypatch):
    """The AEST 06:24Z primary (16:24 Sydney), GitHub-delayed so its download
    runs 16:36 -> 16:42: today's bar is provisional (it was not final when the
    fetch started), so the 07:24Z backstop MUST still run and confirm it. With
    generated_at stamped after the download (16:42 >= the 16:40 close)
    ignition_asx_due skipped every backstop and the break stayed provisional
    until the next morning's intraday run."""
    df = asx_frame(0)                     # the trigger bar IS today's bar
    day = df.index[-1].date()
    pay, saved = _clocked_run(monkeypatch, df, (16, 36), (16, 42))
    assert pay["results"][0]["provisional"] is True
    assert saved["ZZZ.AX"].index[-1].date() < day
    run, why = _due.due(pay["generated_at"], _at(day, 17, 24).astimezone(dt.timezone.utc))
    assert run is True, why


def test_a_run_wholly_after_the_close_satisfies_the_backstop_gate(monkeypatch):
    df = asx_frame(0)
    day = df.index[-1].date()
    pay, saved = _clocked_run(monkeypatch, df, (16, 41), (16, 47))
    assert pay["results"][0]["provisional"] is False
    assert pay["summary"]["counts"]["igniting_confirmed"] == 1
    assert saved["ZZZ.AX"].index[-1].date() == day
    run, why = _due.due(pay["generated_at"], _at(day, 17, 24).astimezone(dt.timezone.utc))
    assert run is False, why


# ---------------------------------------------------------------------------
# review of #22 -- a cache written BEFORE the fix still holds partial bars
# ---------------------------------------------------------------------------

def _reused(df, fetched_at):
    out = df.copy()
    out.attrs = {RUN.sdata.CACHE_REUSED: True,
                 RUN.sdata.FETCHED_AT: fetched_at.astimezone(dt.timezone.utc).isoformat(timespec="seconds")}
    return out


def test_a_reused_frame_cached_before_the_close_loses_its_partial_bar():
    """The pre-#22 cache: a 15:54 AEDT run read its clock at ~16:01, called
    the 16:00 bar complete and saved it. The fix stops new ones, but a post-
    close run that reuses that frame for a ticker Yahoo dropped would still
    screen the 16:01 print as the day's close."""
    df = asx_frame(2)
    day = df.index[-1].date()
    out = RUN.trim_reused_forming({"OLD.AX": _reused(df, _at(day, 16, 1)),
                                   "FIN.AX": _reused(df, _at(day, 17, 24)),
                                   "NEW.AX": df.copy(),
                                   "UNK.AX": _reused(df, _at(day, 16, 1)).pipe(
                                       lambda f: (f.attrs.pop(RUN.sdata.FETCHED_AT), f)[1])},
                                  "asx")
    assert out["OLD.AX"].index[-1].date() < day        # fetched while forming
    assert out["FIN.AX"].index[-1].date() == day       # fetched after the close
    assert out["NEW.AX"].index[-1].date() == day       # not from the cache
    assert out["UNK.AX"].index[-1].date() == day       # no stamp: left alone


def test_screen_market_trims_what_the_cache_hands_back(monkeypatch):
    df = asx_frame(2)
    day = df.index[-1].date()
    rows = [{"yf": "ZZZ.AX", "symbol": "ZZZ", "name": "Zed Ltd"}]
    monkeypatch.setattr(RUN, "_download", lambda market, period, limit: (rows, {}, {}))
    monkeypatch.setattr(RUN, "regime_frame", lambda market, period: None)
    monkeypatch.setattr(RUN.mcap, "known", lambda *a, **k: {})
    monkeypatch.setattr(RUN.sdata, "merge_with_cache",
                        lambda key, done, tickers, **kw: ({"ZZZ.AX": _reused(df, _at(day, 16, 1))},
                                                          {"reused": 1}))
    pay = RUN.screen_market("asx", now=_at(day, 17, 24))
    assert pay["last_closed_bar"] < day.isoformat()

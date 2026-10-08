"""Audit 2026-10-08 #59: history_archive wrote a cache-reused frame's
mid-session forming bar as a FINAL bar, and the same-day no-op check (last
bar's DATE only) then blocked the correction.

run.py hands history_archive.update the merged frames, back-filled ones
included, and the frame cache stores RAW frames with the forming bar still on
the end. So when Yahoo throttles a name out of a scan, yesterday's 12:00
snapshot came back dated before today and was archived as yesterday's close.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pandas as pd

from scanner import data, history_archive

SYD = ZoneInfo("Australia/Sydney")
TODAY = history_archive._today("asx")
YDAY = TODAY - dt.timedelta(days=1)


def _df(closes, end=YDAY):
    idx = pd.DatetimeIndex([pd.Timestamp(end - dt.timedelta(days=len(closes) - 1 - i))
                            for i in range(len(closes))])
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                         "Volume": [100] * len(closes)}, index=idx)


def _reused(df, fetched_local: dt.datetime | None):
    """The shape merge_with_cache hands run.py for a name Yahoo skipped."""
    if fetched_local is not None:
        df.attrs[data.FETCHED_AT] = fetched_local.astimezone(dt.timezone.utc).isoformat()
    return data._as_reused(df)


def _bars(tmp_path, sym="RML"):
    return json.loads((tmp_path / "asx" / f"{sym}.json").read_text())["bars"]


def test_a_reused_frame_fetched_mid_session_does_not_archive_that_session_as_final(tmp_path):
    noon = dt.datetime.combine(YDAY, dt.time(12, 0), SYD)       # before the 16:40 final
    df = _reused(_df([1.0, 1.0, 1.10]), noon)                    # YDAY = the 12:00 snapshot
    history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": df}, root=tmp_path)
    days = [b[0] for b in _bars(tmp_path)]
    assert YDAY.isoformat() not in days, "a mid-session snapshot is not a final bar"
    assert days[-1] == (YDAY - dt.timedelta(days=1)).isoformat()


def test_a_reused_frame_fetched_after_the_close_keeps_that_final_bar(tmp_path):
    evening = dt.datetime.combine(YDAY, dt.time(17, 0), SYD)    # after 16:40 Sydney
    df = _reused(_df([1.0, 1.0, 0.90]), evening)
    history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": df}, root=tmp_path)
    assert _bars(tmp_path)[-1][0] == YDAY.isoformat()
    assert _bars(tmp_path)[-1][4] == 0.9


def test_a_reused_frame_with_no_fetch_stamp_drops_its_last_bar(tmp_path):
    df = _reused(_df([1.0, 1.0, 1.10]), None)                    # cached before stamps existed
    history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": df}, root=tmp_path)
    assert YDAY.isoformat() not in [b[0] for b in _bars(tmp_path)], \
        "an unknown fetch time cannot prove the last bar final"


def test_a_fresh_frame_is_unchanged_every_bar_before_today_is_archived(tmp_path):
    df = _df([1.0, 1.0, 1.10])                                   # not back-filled
    history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": df}, root=tmp_path)
    assert [b[0] for b in _bars(tmp_path)][-1] == YDAY.isoformat()


def test_the_real_cache_path_tags_the_frame_and_the_archive_honours_it(tmp_path, monkeypatch):
    """End to end through merge_with_cache: the fetch stamp survives the
    pickle and the reused tag reaches history_archive exactly as in run.py."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    noon = dt.datetime.combine(YDAY, dt.time(12, 0), SYD)
    cached = _df([1.0, 1.0, 1.10])
    cached.attrs[data.FETCHED_AT] = noon.astimezone(dt.timezone.utc).isoformat()
    data.save_frame_cache("asx", {"RML.AX": cached})
    merged, stats = data.merge_with_cache("asx", {}, ["RML.AX"])
    assert stats["reused"] == 1 and merged["RML.AX"].attrs.get(data.CACHE_REUSED)
    history_archive.update("asx", [{"symbol": "RML"}], merged, root=tmp_path)
    assert YDAY.isoformat() not in [b[0] for b in _bars(tmp_path)]


def test_a_same_day_corrected_bar_is_rewritten_not_skipped(tmp_path):
    """The no-op check compared only the last bar's DATE, so a wrong close
    already stored today blocked the true final close until tomorrow."""
    base = tmp_path / "asx"
    base.mkdir(parents=True)
    prior = (YDAY - dt.timedelta(days=1)).isoformat()
    stored = {"symbol": "RML", "market": "asx", "basis": "adj", "updated": TODAY.isoformat(),
              "last_seen": TODAY.isoformat(), "splice_suspect": False,
              "bars": [[prior, 1.0, 1.0, 1.0, 1.0, 100],
                       [YDAY.isoformat(), 1.1, 1.1, 1.1, 1.1, 100]]}   # the 12:00 snapshot
    (base / "RML.json").write_text(json.dumps(stored))
    out = history_archive.update("asx", [{"symbol": "RML"}],
                                 {"RML.AX": _df([1.0, 1.0, 0.90])}, root=tmp_path)
    assert out["written"] == 1
    assert _bars(tmp_path)[-1] == [YDAY.isoformat(), 0.9, 0.9, 0.9, 0.9, 100]


def test_a_same_day_identical_bar_is_still_a_byte_level_noop(tmp_path):
    df = _df([1.0, 1.0, 0.90])
    history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": df}, root=tmp_path)
    p = tmp_path / "asx" / "RML.json"
    before = p.read_text()
    out = history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": df}, root=tmp_path)
    assert out["written"] == 0 and p.read_text() == before

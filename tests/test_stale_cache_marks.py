"""A cache-reused frame is a PAST price (config VIVEK_BOT_MAX_MARK_AGE_H).

`data.merge_with_cache` back-fills tickers the source skipped this run from
the last-good frame cache. Until 2026-09-28 the paper bot managed held
positions off that frame's last close as if it were live: stops and time stops
tested, the loss guard fed, `unpriced_runs` reset -- so a coin a venue skipped
for days froze at an old price with nothing counting the freeze (owner:
"Fix it").

Now every frame fetched this run is stamped with WHEN, a reused one is tagged,
and `vivek_run` treats a held position whose frame is older than the limit as
UNPRICED (management and guard alike), while a NEW fill needs a price fetched
this run. These tests drive the shipped `merge_with_cache` (through a real
pickle round trip) and the shipped `run_market`.
"""

import datetime as dt
import json
import math
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, data
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk

NOW = dt.datetime(2024, 1, 2, 11, 0, tzinfo=ZoneInfo("Australia/Sydney"))


def _frame(close, end="2024-01-02"):
    idx = pd.date_range(end=end, periods=5, freq="D")
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": 1e6}, index=idx)


def _reused(close, hours_old=None):
    """A frame as merge_with_cache hands back a cached one: tagged reused,
    carrying the fetch time it was saved with (None = a cache written before
    fetch stamps existed)."""
    df = _frame(close)
    if hours_old is not None:
        df.attrs[data.FETCHED_AT] = (NOW - dt.timedelta(hours=hours_old)).astimezone(
            dt.timezone.utc).isoformat(timespec="seconds")
    return data._as_reused(df)


def _enable(monkeypatch, tmp_path):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_MARK_AGE_H", 2.0)


def _held(symbol="BHP", entry=100.0):
    return {"id": f"{symbol}-1", "symbol": symbol, "name": symbol, "sector": "",
            "market": "asx", "direction": "long", "grade": "A+",
            "entry_type": "break", "timeframe": "1D",
            "entry": entry, "stop": entry - 4.0,
            "tp1": entry + 6.0, "tp2": entry + 12.0, "tp3": entry + 20.0,
            "scale": list(config.VIVEK_TP_SCALE_LONG), "risk": 4.0, "rr": 3.0,
            "trigger_bar": None, "entry_date": "2024-01-01",
            "opened_at": "2024-01-01T00:00:00+00:00", "status": "open",
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "booked_pct": 0.0,
            "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0, "exits": [],
            "mae": entry, "mfe": entry, "mae_r": 0.0, "mfe_r": 0.0,
            "entry_type_label": "reclaim", "units": 25.0, "notional": 2500.0,
            "risk_usd": 100.0, "last_mark": entry}


def _run_held(tmp_path, monkeypatch, frame):
    _enable(monkeypatch, tmp_path)
    (tmp_path / "vivek_bot_book.asx.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": "asx", "open": [_held()], "closed": []}),
        encoding="utf-8")
    return vr.run_market("asx", [], {"BHP.AX": frame},
                         [{"symbol": "BHP", "yf": "BHP.AX"}], now=NOW)


def _row():
    plan = {"armed": True, "entry_trigger": "break", "trigger_bar": "2024-01-01",
            "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "rr": 3.0, "scale": config.VIVEK_TP_SCALE_LONG}
    return {"symbol": "BHP", "name": "BHP", "sector": "", "grade": "A+", "dir": "LONG",
            "entry_types": ["break"], "level_tf": "weekly", "plans": {"1D": plan}}


# ── 1. the age of a frame's price ──────────────────────────────────────────────

def test_a_frame_the_cache_did_not_back_fill_is_age_zero():
    assert data.mark_age_h(_frame(1.0), NOW) == 0.0
    assert data.mark_age_h(None, NOW) == 0.0          # no frame = no price anyway


def test_a_reused_frame_is_as_old_as_its_original_fetch():
    assert data.mark_age_h(_reused(1.0, hours_old=5), NOW) == pytest.approx(5.0)
    assert data.mark_age_h(_reused(1.0, hours_old=0.5), NOW) == pytest.approx(0.5)


def test_a_reused_frame_of_unknown_age_never_reads_as_fresh():
    assert math.isinf(data.mark_age_h(_reused(1.0), NOW))            # no stamp
    bad = _reused(1.0, hours_old=1)
    bad.attrs[data.FETCHED_AT] = "not a time"
    assert math.isinf(data.mark_age_h(bad, NOW))


def test_a_naive_fetch_stamp_is_read_as_utc():
    df = _reused(1.0)
    df.attrs[data.FETCHED_AT] = "2024-01-01T21:00:00"   # NOW is 00:00 UTC 2 Jan: 3h before
    assert data.mark_age_h(df, NOW) == pytest.approx(3.0)


def test_tagging_a_reused_frame_leaves_the_cached_object_untouched():
    src = _frame(1.0)
    src.attrs[data.FETCHED_AT] = "2024-01-01T00:00:00+00:00"
    out = data._as_reused(src)
    assert out.attrs[data.CACHE_REUSED] is True
    assert data.CACHE_REUSED not in src.attrs
    assert out.attrs[data.FETCHED_AT] == src.attrs[data.FETCHED_AT]


# ── 2. merge_with_cache stamps, tags, and never renews an old stamp ────────────

def _today_frame(close):
    return _frame(close, end=pd.Timestamp.now().normalize())


def test_merge_stamps_fresh_frames_and_tags_reused_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path)
    old = _today_frame(2.0)
    old.attrs[data.FETCHED_AT] = "2024-01-01T00:00:00+00:00"
    data.save_frame_cache("asx", {"B.AX": old})
    before = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    merged, stats = data.merge_with_cache("asx", {"A.AX": _today_frame(1.0)}, ["A.AX", "B.AX"])
    assert stats["fresh"] == 1 and stats["reused"] == 1
    a, b = merged["A.AX"], merged["B.AX"]
    assert data.CACHE_REUSED not in a.attrs
    assert pd.Timestamp(a.attrs[data.FETCHED_AT]) >= before
    assert b.attrs[data.CACHE_REUSED] is True
    assert b.attrs[data.FETCHED_AT] == "2024-01-01T00:00:00+00:00"   # NOT renewed
    saved = data.load_frame_cache("asx")                              # real pickle round trip
    assert data.CACHE_REUSED not in saved["B.AX"].attrs               # saved untagged ...
    assert saved["B.AX"].attrs[data.FETCHED_AT] == "2024-01-01T00:00:00+00:00"  # ... still old
    assert saved["A.AX"].attrs[data.FETCHED_AT] == a.attrs[data.FETCHED_AT]


def test_a_frame_reused_run_after_run_keeps_ageing(tmp_path, monkeypatch):
    """The failure this exists to prevent: a re-save that renewed the stamp
    would make a frame the source has skipped for days look fetched just now."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path)
    data.merge_with_cache("asx", {"A.AX": _today_frame(1.0)}, ["A.AX"])
    first = data.load_frame_cache("asx")["A.AX"].attrs[data.FETCHED_AT]
    for _ in range(3):                                   # the source skips A.AX
        merged, stats = data.merge_with_cache("asx", {}, ["A.AX"])
        assert stats["reused"] == 1
        assert merged["A.AX"].attrs[data.FETCHED_AT] == first
        assert data.load_frame_cache("asx")["A.AX"].attrs[data.FETCHED_AT] == first
    merged, _ = data.merge_with_cache("asx", {"A.AX": _today_frame(1.1)}, ["A.AX"])
    assert data.mark_age_h(merged["A.AX"]) == 0.0         # fetched again: live again


# ── 3. a held position is not managed off a stale frame ─────────────────────────

def test_a_fresh_frame_under_the_stop_stops_the_position_out(tmp_path, monkeypatch):
    """The control: the same price, fetched this run, fires the stop."""
    bk = _run_held(tmp_path, monkeypatch, _frame(95.0))
    assert bk["open"] == [] and bk["closed"][0]["symbol"] == "BHP"


def test_a_stale_reused_frame_leaves_the_position_unpriced_not_stopped(tmp_path, monkeypatch, caplog):
    bk = _run_held(tmp_path, monkeypatch, _reused(95.0, hours_old=5))
    (pos,) = bk["open"]
    assert bk["closed"] == []                             # no stop off a 5h-old price
    assert pos["unpriced_runs"] == 1                      # the freeze is COUNTED
    assert pos["last_mark"] == 100.0                      # the old price is not a mark
    assert "BHP" in (bk["guard"]["asx"].get("unpriced") or [])   # guard fails closed on it
    assert any("stale_cache" in r.message and "BHP" in r.message for r in caplog.records)


def test_a_reused_frame_of_unknown_age_is_unpriced(tmp_path, monkeypatch):
    bk = _run_held(tmp_path, monkeypatch, _reused(95.0))
    assert bk["closed"] == [] and bk["open"][0]["unpriced_runs"] == 1


def test_one_missed_fetch_inside_the_limit_is_still_a_mark(tmp_path, monkeypatch):
    """2h tolerates one skipped run after an on-time one: the price is the
    one the previous run already tested, not a stale one."""
    bk = _run_held(tmp_path, monkeypatch, _reused(95.0, hours_old=1))
    assert bk["open"] == [] and bk["closed"][0]["symbol"] == "BHP"


def test_zero_turns_the_limit_off(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_MARK_AGE_H", 0)
    (tmp_path / "vivek_bot_book.asx.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": "asx", "open": [_held()], "closed": []}),
        encoding="utf-8")
    bk = vr.run_market("asx", [], {"BHP.AX": _reused(95.0, hours_old=50)},
                       [{"symbol": "BHP", "yf": "BHP.AX"}], now=NOW)
    assert bk["open"] == []                               # the pre-2026-09-28 behaviour


# ── 4. a new fill needs a price fetched THIS run ────────────────────────────────

def _run_entry(tmp_path, monkeypatch, frame):
    _enable(monkeypatch, tmp_path)
    return vr.run_market("asx", [_row()], {"BHP.AX": frame},
                         [{"symbol": "BHP", "yf": "BHP.AX"}], now=NOW)


def test_a_fresh_frame_fills(tmp_path, monkeypatch):
    bk = _run_entry(tmp_path, monkeypatch, _frame(101.0))
    assert [p["symbol"] for p in bk["open"]] == ["BHP"]


def test_no_fill_off_a_reused_frame_even_inside_the_mark_limit(tmp_path, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO)
    bk = _run_entry(tmp_path, monkeypatch, _reused(101.0, hours_old=0.5))
    assert bk["open"] == []
    assert any("stale_cache" in r.message for r in caplog.records)


def test_fills_off_a_reused_frame_only_with_the_limit_off(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_MARK_AGE_H", 0)
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _reused(101.0, hours_old=0.5)},
                       [{"symbol": "BHP", "yf": "BHP.AX"}], now=NOW)
    assert [p["symbol"] for p in bk["open"]] == ["BHP"]


def test_the_shipped_limit_tolerates_one_missed_run_and_no_more():
    assert 1.0 < config.VIVEK_BOT_MAX_MARK_AGE_H <= 3.0

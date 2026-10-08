"""Audit #54 (2026-10-08): a transient Yahoo failure must not publish a blank
NEWS page read.

``sectors._fetch`` returns ``[]`` when ``yf.download`` raises, and when Yahoo
throttles a batch down to an empty / all-NaN frame (every ticker then fails
``len(close) < 2``). ``_read`` turns that into an empty summary and rotation,
and ``carry_forward`` used to carry only the enrichment keys - so one
throttled run (any scanner.run, the hourly crypto job included) committed
``sectors: []``, ``indices: []``, ``summary: ''`` for both markets under a
fresh ``generated_at``. These pin that the previous, more complete read is
carried forward WHOLE, with its own ``read_at`` age, and that a fresh read is
never displaced by an older one that is no better.
"""

import datetime as dt
import json

import pandas as pd

from scanner import sectors


PREV_AT = "2026-10-08T15:10:00+11:00"


def _good_read(tag="old"):
    return {"label": "ASX",
            "indices": [{"symbol": "XJO", "name": "S&P/ASX 200", "last": 8900.0,
                         "chg": -60.0, "chg_pct": -0.7}],
            "sectors": [{"symbol": "XMJ", "name": "Materials", "last": 18000.0,
                         "chg": 90.0, "chg_pct": 0.5},
                        {"symbol": "XUJ", "name": "Utilities", "last": 9000.0,
                         "chg": -45.0, "chg_pct": -0.5}],
            "summary": f"{tag} summary", "rotation": f"{tag} rotation",
            "read_at": "2026-10-08T04:10:00+00:00"}


def _prev_file(**asx_over):
    asx = dict(_good_read(), **asx_over)
    us = dict(_good_read("us-old"), label="US")
    return {"generated_at": PREV_AT, "markets": {"asx": asx, "us": us}}


def _throttled_fetch(monkeypatch):
    """Run the SHIPPED fetch() with Yahoo raising on every download."""
    def boom(*a, **k):
        raise RuntimeError("Too Many Requests")
    monkeypatch.setattr(sectors, "_calendar", lambda: {"upcoming": {}, "latest": {}})
    monkeypatch.setattr(sectors.yf, "download", boom)
    return sectors.fetch()


def test_a_throttled_run_keeps_the_previous_read_whole(monkeypatch):
    sec = _throttled_fetch(monkeypatch)
    # the bug's precondition, from the shipped code: the fresh read is blank
    assert sec["markets"]["asx"]["sectors"] == []
    assert sec["markets"]["asx"]["summary"] == ""
    moved = sectors.carry_forward(sec, _prev_file())
    assert moved > 0
    for key in ("asx", "us"):
        m = sec["markets"][key]
        assert len(m["sectors"]) == 2 and len(m["indices"]) == 1
        assert m["summary"].endswith("summary") and m["summary"] != ""
        assert m["rotation"].endswith("rotation")
        # the carried read keeps ITS age - it must not masquerade as fresh
        assert m["read_at"] == "2026-10-08T04:10:00+00:00"


def test_an_all_nan_frame_is_the_same_failure_and_is_carried(monkeypatch):
    # Yahoo's usual throttle shape is not an exception but an empty frame.
    monkeypatch.setattr(sectors, "_calendar", lambda: {"upcoming": {}, "latest": {}})
    monkeypatch.setattr(sectors.yf, "download", lambda *a, **k: pd.DataFrame())
    sec = sectors.fetch()
    assert sec["markets"]["us"]["sectors"] == []
    sectors.carry_forward(sec, _prev_file())
    assert len(sec["markets"]["us"]["sectors"]) == 2


def test_a_file_from_before_the_stamp_carries_its_generated_at_as_the_age(monkeypatch):
    sec = _throttled_fetch(monkeypatch)
    prev = _prev_file()
    prev["markets"]["asx"].pop("read_at")
    sectors.carry_forward(sec, prev)
    assert sec["markets"]["asx"]["read_at"] == PREV_AT


def test_unknown_age_is_null_never_now(monkeypatch):
    sec = _throttled_fetch(monkeypatch)
    prev = _prev_file()
    prev.pop("generated_at")
    prev["markets"]["asx"].pop("read_at")
    sectors.carry_forward(sec, prev)
    assert sec["markets"]["asx"]["read_at"] is None


def test_a_complete_fresh_read_is_never_replaced():
    fresh = {"markets": {"asx": _good_read("fresh")}}
    fresh["markets"]["asx"]["read_at"] = "2026-10-08T05:10:00+00:00"
    sectors.carry_forward(fresh, _prev_file())
    m = fresh["markets"]["asx"]
    assert m["summary"] == "fresh summary"
    assert m["read_at"] == "2026-10-08T05:10:00+00:00"


def test_a_tie_keeps_the_fresh_read():
    # Both reads lost their indices: the fresh one is no worse, so it stays.
    fresh = {"markets": {"asx": dict(_good_read("fresh"), indices=[])}}
    sectors.carry_forward(fresh, _prev_file(indices=[]))
    assert fresh["markets"]["asx"]["summary"] == "fresh summary"


def test_a_fresh_read_missing_only_its_indices_takes_the_complete_previous_one():
    # Moved WHOLE: a summary built without the index line would sit beside
    # sectors from a different fetch otherwise.
    fresh = {"markets": {"asx": dict(_good_read("fresh"), indices=[])}}
    sectors.carry_forward(fresh, _prev_file())
    m = fresh["markets"]["asx"]
    assert m["summary"] == "old summary" and len(m["indices"]) == 1


def test_an_emptier_previous_read_never_displaces_a_fresh_one():
    fresh = {"markets": {"asx": dict(_good_read("fresh"), indices=[])}}
    sectors.carry_forward(fresh, _prev_file(sectors=[], summary="", rotation=""))
    assert fresh["markets"]["asx"]["summary"] == "fresh summary"


def test_no_previous_file_publishes_the_fresh_read(monkeypatch):
    sec = _throttled_fetch(monkeypatch)
    assert sectors.carry_forward(sec, {}) == 0
    assert sec["markets"]["asx"]["sectors"] == []


def test_fetch_stamps_read_at_now(monkeypatch, freeze_now):
    freeze_now(sectors, dt.datetime(2026, 10, 8, 4, 26, tzinfo=dt.timezone.utc))
    sec = _throttled_fetch(monkeypatch)
    assert sec["markets"]["asx"]["read_at"] == "2026-10-08T04:26:00+00:00"


def test_the_carried_file_round_trips_through_json(monkeypatch):
    sec = _throttled_fetch(monkeypatch)
    sectors.carry_forward(sec, json.loads(json.dumps(_prev_file())))
    back = json.loads(json.dumps(sec))
    assert back["markets"]["asx"]["sectors"][0]["symbol"] == "XMJ"

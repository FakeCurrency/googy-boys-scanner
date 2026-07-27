"""Sector dashboard carry-forward (2026-07-28).

sectors.fetch() rebuilds public/data/sectors.json from scratch on EVERY run,
but enrich() only runs for the markets that run actually scanned. So the
hourly crypto-only job was republishing the ASX and US blocks with their
movers, volume, rotation line and eli5 deleted, and the sectors page fell
back to "No summary yet" until the next equity scan rebuilt them. Observed
in the history as a daily oscillation: scan +337/-99, crypto bot +6/-244.

These pin the carry-forward that stops it, and pin that a market this run DID
enrich is never overwritten by the older file.
"""

import json

import pytest

from scanner import sectors


def _published(eli5="yesterday's read", movers=None):
    return {"markets": {
        "asx": {"label": "ASX", "rotation": "Materials led",
                "top_movers": movers or {"winners": [{"symbol": "WTC"}], "losers": []},
                "top_volume": [{"symbol": "BHP"}],
                "rotation_detail": "Materials led the session",
                "eli5": eli5,
                "enriched_at": "2026-07-27T06:40:00+00:00"},
        "us": {"label": "US", "rotation": "Tech led"}}}


def _rebuilt():
    """What fetch() hands back on a crypto-only run: indices/sectors only."""
    return {"markets": {"asx": {"label": "ASX", "rotation": "Materials led"},
                        "us": {"label": "US", "rotation": "Tech led"}}}


def test_unenriched_market_keeps_the_last_published_depth():
    sec = _rebuilt()
    moved = sectors.carry_forward(sec, _published())
    assert moved == 5                       # all of ENRICHED_KEYS
    asx = sec["markets"]["asx"]
    assert asx["eli5"] == "yesterday's read"
    assert asx["top_movers"]["winners"][0]["symbol"] == "WTC"
    assert asx["top_volume"] == [{"symbol": "BHP"}]
    assert asx["rotation_detail"] == "Materials led the session"
    # The age must ride along or a carried block would masquerade as fresh.
    assert asx["enriched_at"] == "2026-07-27T06:40:00+00:00"


def test_freshly_enriched_market_is_never_overwritten():
    sec = _rebuilt()
    sec["markets"]["asx"]["eli5"] = "today's read"
    sec["markets"]["asx"]["top_movers"] = {"winners": [{"symbol": "CBA"}], "losers": []}
    sectors.carry_forward(sec, _published())
    assert sec["markets"]["asx"]["eli5"] == "today's read"
    assert sec["markets"]["asx"]["top_movers"]["winners"][0]["symbol"] == "CBA"
    # ...while the keys this run genuinely could not compute still come across.
    assert sec["markets"]["asx"]["top_volume"] == [{"symbol": "BHP"}]


def test_market_absent_from_the_old_file_is_left_alone():
    sec = _rebuilt()
    sectors.carry_forward(sec, {"markets": {}})
    assert "eli5" not in sec["markets"]["asx"]
    assert sectors.carry_forward(sec, {}) == 0


def test_garbage_previous_file_cannot_crash_the_publish():
    sec = _rebuilt()
    assert sectors.carry_forward(sec, {"markets": None}) == 0
    assert sectors.carry_forward(sec, {"markets": {"asx": None}}) == 0
    assert sec == _rebuilt()


def test_enrich_stamps_enriched_at():
    # enrich() sets the stamp on its own output; carry_forward relies on it
    # existing to make a carried block auditable.
    assert "enriched_at" in sectors.ENRICHED_KEYS
    m = {}
    sectors.enrich(m, {}, [], 1_000_000, market_key="asx")
    assert m.get("enriched_at", "").startswith("20")


def test_round_trips_through_json():
    # The real path writes and re-reads JSON; nothing carried may be non-serialisable.
    sec = _rebuilt()
    sectors.carry_forward(sec, json.loads(json.dumps(_published())))
    assert json.loads(json.dumps(sec))["markets"]["asx"]["eli5"] == "yesterday's read"

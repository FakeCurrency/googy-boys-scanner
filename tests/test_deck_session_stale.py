"""The 5.0 deck's session + 2h staleness rule reads the SAME sessions as the
Python side.

app.js cannot import scanner/config.py, so it carries `SESSION_STALE` as a
JSON literal (the HIGH CONVICTION table's pattern, test_conviction.py). This
parses that literal out of the shipped file and compares it with
VIVEK_JOURNAL_SESSION + VIVEK_DECK_SESSION_GRACE_H, and the zones it borrows
(WEEKEND_TZ) with each market's configured timezone. The behaviour is tested
by executing the shipped functions in test/staleview.test.js.
"""

from __future__ import annotations

import json
import pathlib
import re

from scanner import config

APP = (pathlib.Path(__file__).resolve().parents[1] / "public" / "js" / "app.js").read_text(encoding="utf-8")


def _literal(name: str) -> dict:
    m = re.search(rf"const {name} = (\{{[^;]*\}});", APP)
    assert m, f"app.js no longer declares {name} as a one-line literal"
    # WEEKEND_TZ uses bare keys; quote them so both literals parse as JSON.
    return json.loads(re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', m.group(1)))


def test_the_session_table_is_the_python_one():
    table = _literal("SESSION_STALE")
    assert table.pop("grace_h") == config.VIVEK_DECK_SESSION_GRACE_H
    expected = {m: list(s) for m, s in config.VIVEK_JOURNAL_SESSION.items() if s is not None}
    assert table == expected, (table, expected)


def test_the_zones_are_the_configured_ones():
    zones = _literal("WEEKEND_TZ")
    for market, tz in zones.items():
        assert config.MARKETS[market].timezone == tz, market
    assert set(zones) == set(_literal("SESSION_STALE")) - {"grace_h"}, (
        "a session with no zone would silently never go stale")


def test_the_grace_leaves_room_for_the_scan_cadence():
    """The first scan lands ~1h07 after the open and the last ~7-30 min after
    the close (config.MARKET_SCAN_WINDOWS). A grace under that would mark a
    healthy deck stale every session."""
    for market, (tz, start_min, end_min) in config.MARKET_SCAN_WINDOWS.items():
        open_h, open_m, close_h, close_m = config.VIVEK_JOURNAL_SESSION[market]
        first_scan_lag_h = (start_min - (open_h * 60 + open_m)) / 60
        assert first_scan_lag_h < config.VIVEK_DECK_SESSION_GRACE_H, market
        assert end_min > close_h * 60 + close_m, f"{market}: no scan window after the close"

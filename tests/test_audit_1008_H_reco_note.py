"""Audit #70 (2026-10-08): reco_note's 48h rule dropped a still-current read
every weekend.

Since scan_gate.py (2026-10-05) ASX and NASDAQ are scanned only inside their
weekday windows, so Friday's closing scan is ~51h old at Sunday's 08:52 UTC
run (ASX) and ~60h old at Monday's (NASDAQ) -- and the note said "scan data is
2 days old - no fresh read" about the most recent session, every week. The
rule exists to catch a STALLED pipeline; a weekend is not one. Weekday-only
markets now count weekday hours in their own zone; crypto keeps wall-clock.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
from zoneinfo import ZoneInfo

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reco_note", ROOT / "scripts" / "reco_note.py")
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)

SYD, NY, UTC = ZoneInfo("Australia/Sydney"), ZoneInfo("America/New_York"), dt.timezone.utc


def _at(tz, *when):
    return dt.datetime(*when, tzinfo=tz)


def _prices(generated_at):
    return {"generated_at": generated_at.isoformat(),
            "rows": {f"S{i}": {"dir": "LONG", "grade": "A+"} for i in range(10)}}


@pytest.mark.parametrize("market,label,scan,run,why", [
    ("asx", "ASX", _at(SYD, 2026, 10, 9, 16, 50), _at(UTC, 2026, 10, 11, 8, 52),
     "AEDT: Friday's close read at Sunday's run (~51h wall clock)"),
    ("nasdaq", "NASDAQ", _at(NY, 2026, 10, 9, 16, 50), _at(UTC, 2026, 10, 12, 8, 52),
     "EDT: Friday's close read at Monday's pre-open run (~60h wall clock)"),
    ("asx", "ASX", _at(SYD, 2026, 7, 10, 16, 50), _at(UTC, 2026, 7, 12, 8, 52),
     "AEST: same weekend, the other DST regime"),
    ("nasdaq", "NASDAQ", _at(NY, 2026, 11, 6, 16, 50), _at(UTC, 2026, 11, 9, 8, 52),
     "EST: same weekend, the other DST regime"),
])
def test_fridays_close_is_still_the_current_read_over_the_weekend(
        freeze_now, market, label, scan, run, why):
    freeze_now(rn, run)
    line = rn.market_line(label, _prices(scan), [], market)
    assert "no fresh read" not in line, why
    assert line.startswith(f"{label}: leaning long"), line


@pytest.mark.parametrize("scan,run,why", [
    (_at(SYD, 2026, 10, 7, 16, 50), _at(UTC, 2026, 10, 9, 8, 52),
     "Wednesday's close at Friday evening: Thursday AND Friday never scanned"),
    (_at(SYD, 2026, 10, 8, 16, 50), _at(UTC, 2026, 10, 12, 8, 52),
     "Thursday's close at Monday evening: Friday and Monday never scanned"),
])
def test_a_real_stall_is_still_called_stale(freeze_now, scan, run, why):
    freeze_now(rn, run)
    line = rn.market_line("ASX", _prices(scan), [], "asx")
    assert "no fresh read" in line, why


def test_crypto_keeps_the_wall_clock_rule(freeze_now):
    freeze_now(rn, _at(UTC, 2026, 10, 11, 8, 52))           # a Sunday
    line = rn.market_line("Crypto", _prices(_at(UTC, 2026, 10, 9, 7, 0)), [], "crypto")
    assert line == "Crypto: scan data is 2 days old - no fresh read."


def test_weekday_hours_counts_only_monday_to_friday_in_the_markets_zone():
    fri = _at(NY, 2026, 10, 9, 16, 50)
    mon = _at(NY, 2026, 10, 12, 4, 52)
    assert abs(rn.weekday_hours(fri, mon, "America/New_York") - (7 + 10 / 60 + 4 + 52 / 60)) < 1e-9
    assert rn.weekday_hours(mon, fri, "America/New_York") == 0.0


def test_main_hands_each_market_its_key(tmp_path, monkeypatch, freeze_now):
    run = _at(UTC, 2026, 10, 11, 8, 52)                     # Sunday
    freeze_now(rn, run)
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "vivek_bot_book.json").write_text(json.dumps({"open": []}))
    (d / "asx_prices.json").write_text(json.dumps(_prices(_at(SYD, 2026, 10, 9, 16, 50))))
    (d / "nasdaq_prices.json").write_text(json.dumps(_prices(_at(NY, 2026, 10, 9, 16, 50))))
    (d / "crypto_prices.json").write_text(json.dumps(_prices(_at(UTC, 2026, 10, 11, 8, 0))))
    monkeypatch.setattr(rn, "ROOT", str(tmp_path))
    monkeypatch.setattr(rn, "OUT", str(d / "reco_note.json"))
    assert rn.main() == 0
    note = json.loads((d / "reco_note.json").read_text())["note"]
    assert "no fresh read" not in note, note

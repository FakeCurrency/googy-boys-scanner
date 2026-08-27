"""The stale-position probe — "open for 2 weeks with minimal movement" pings.

Owner ask 2026-07-29, answering the rotation question: "no rotation rule.
maybe a PROBE that position has been open for 2 weeks with minimal movement
for me then to manually make a decision." REPORT-ONLY by construction: these
tests also pin that the probe never touches status, exits, or anything else
that would make it a rotation rule by the back door.

It exists for the gap the automatic rules leave: MAX_HOLD_DAYS (28) time-stops
pre-TP1 stalls but says nothing at day 14, and runners past TP1 are exempt
from it forever — the probe is the only thing that ever asks about a +0.1R
runner squatting a scarce slot for a month.
"""

from __future__ import annotations

import copy

import pytest

from scanner import config
from scanner.broker import vivek_run as vr

DAY = "2026-07-29"


def _pos(symbol="BGA", entry_date="2026-07-01", unreal_r=0.1, tp1_hit=False,
         status="open", market="asx", **over):
    p = {"symbol": symbol, "market": market, "direction": "long",
         "status": status, "entry": 5.0, "stop": 4.5, "entry_date": entry_date,
         "unreal_r": unreal_r, "tp1_hit": tp1_hit}
    p.update(over)
    return p


@pytest.fixture()
def probe(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_DAYS", 14, raising=False)
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_MAX_ABS_R", 0.5, raising=False)
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_REPEAT_DAYS", 7, raising=False)
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_PUSH", True, raising=False)
    saved: list[dict] = []
    monkeypatch.setattr(vr, "_save_market_book",
                        lambda market, book: saved.append(copy.deepcopy(book)))
    sent: list[tuple] = []

    def run(book, day=DAY):
        return vr._stale_probe("asx", book, day, send=lambda *a: sent.append(a))

    return type("P", (), {"run": staticmethod(run), "sent": sent, "saved": saved})


def test_two_weeks_and_going_nowhere_pings(probe):
    book = {"open": [_pos(entry_date="2026-07-15", unreal_r=0.12)]}   # 14 days
    assert probe.run(book) == ["BGA"]
    event, title, details = probe.sent[0]
    assert event == "stale_position"
    assert "BGA" in details and "14d" in details and "+0.12R" in details
    assert book["open"][0]["stale_pinged"] == DAY, "the dedupe stamp travels with the row"
    assert probe.saved, "the stamp must be persisted"


def test_thirteen_days_is_not_two_weeks(probe):
    book = {"open": [_pos(entry_date="2026-07-16", unreal_r=0.1)]}    # 13 days
    assert probe.run(book) == []
    assert probe.sent == []


def test_a_position_that_is_actually_moving_is_left_alone(probe):
    book = {"open": [_pos(entry_date="2026-07-01", unreal_r=0.8)]}
    assert probe.run(book) == []


def test_a_deep_red_row_is_the_stops_business_not_the_probes(probe):
    book = {"open": [_pos(entry_date="2026-07-01", unreal_r=-0.8)]}
    assert probe.run(book) == []
    # ...but a small red drift IS going-nowhere
    book = {"open": [_pos(entry_date="2026-07-01", unreal_r=-0.3)]}
    assert probe.run(book) == ["BGA"]


def test_one_ping_per_episode_then_a_weekly_reminder(probe):
    book = {"open": [_pos(entry_date="2026-07-01", unreal_r=0.1)]}
    assert probe.run(book, "2026-07-20") == ["BGA"]
    assert probe.run(book, "2026-07-21") == []            # next run: quiet
    assert probe.run(book, "2026-07-26") == []            # day 6: still quiet
    assert probe.run(book, "2026-07-27") == ["BGA"]       # day 7: reminder
    assert len(probe.sent) == 2


def test_recovery_clears_the_stamp_so_a_relapse_is_a_fresh_episode(probe):
    row = _pos(entry_date="2026-07-01", unreal_r=0.1)
    book = {"open": [row]}
    assert probe.run(book, "2026-07-20") == ["BGA"]
    row["unreal_r"] = 0.9                                  # it started working
    assert probe.run(book, "2026-07-21") == []
    assert "stale_pinged" not in row
    row["unreal_r"] = 0.1                                  # ...and stalled again
    assert probe.run(book, "2026-07-22") == ["BGA"], "a relapse must not inherit the old stamp"


def test_an_unpriced_row_is_skipped_not_flagged(probe):
    row = _pos(entry_date="2026-07-01")
    del row["unreal_r"]
    assert probe.run({"open": [row]}) == []


def test_closed_rows_and_other_markets_are_ignored(probe):
    book = {"open": [_pos(status="closed", entry_date="2026-07-01"),
                     _pos(symbol="NVDA", market="nasdaq", entry_date="2026-07-01")]}
    assert probe.run(book) == []


def test_a_past_tp1_runner_is_named_as_the_time_stops_blind_spot(probe):
    book = {"open": [_pos(entry_date="2026-06-01", unreal_r=0.1, tp1_hit=True)]}
    assert probe.run(book) == ["BGA"]
    _, _, details = probe.sent[0]
    assert "past TP1" in details


def test_the_probe_is_report_only(probe):
    row = _pos(entry_date="2026-07-01", unreal_r=0.1)
    before = {k: v for k, v in row.items()}
    probe.run({"open": [row]})
    after = {k: v for k, v in row.items() if k != "stale_pinged"}
    assert after == before, "the probe may stamp its memo and change NOTHING else"
    assert row["status"] == "open"


def test_zero_days_disables_the_probe(probe, monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_DAYS", 0, raising=False)
    book = {"open": [_pos(entry_date="2026-07-01", unreal_r=0.0)]}
    assert probe.run(book) == []


def test_the_message_is_plain_ascii(probe):
    book = {"open": [_pos(entry_date="2026-07-01", unreal_r=0.1)]}
    probe.run(book)
    _, title, details = probe.sent[0]
    (title + details).encode("ascii")


def test_the_event_is_registered_everywhere_it_needs_to_be():
    from scanner.broker import alert_router as ar
    assert ar.get_severity("stale_position") == "NOTICE"
    assert ar.get_channels("stale_position") == []  # no push channel since the 2026-08-27 Discord removal
    assert config.ALERT_RATE_LIMITS["stale_position"] == 0
    assert ar._SEV_MAP["stale_position"] == "NOTICE"
    assert ar._RATE_MAP["stale_position"] == 0

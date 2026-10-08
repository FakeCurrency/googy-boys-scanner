"""2026-10-08 audit, cluster E -- #66: momentum_due made the ASX due at
16:30 Sydney (session close + PUBLISH_AFTER_CLOSE_MIN), before the 16:40
instant the repo ruled (2026-10-06) is when Yahoo shows the ASX auction. Under
AEST momentum.yml's `30 6` cron lands exactly on 16:30, screened partly
pre-auction closes, and every later wake-up then read the file as fresh.

The due instant is now the LATER of close + 30 and scanner.config
.DAILY_BAR_FINAL, so the ASX is due at 16:40 and NASDAQ (final at 16:05 New
York) stays at 16:30.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib

import pytest

from scanner import config as scfg

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("momentum_due_e66",
                                               ROOT / "scripts" / "momentum_due.py")
due = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(due)


def Z(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


YESTERDAY_EVENING = Z("2027-06-08T08:00:00Z")      # an AEST Tuesday's file


@pytest.mark.parametrize("now, is_due", [
    ("2027-06-09T06:15:00Z", False),
    ("2027-06-09T06:30:00Z", False),   # the `30 6` cron, on time, under AEST
    ("2027-06-09T06:39:00Z", False),
    ("2027-06-09T06:40:00Z", True),    # 16:40 AEST: the close is final on the feed
    ("2027-06-09T06:45:00Z", True),
])
def test_an_aest_asx_screen_is_not_due_before_1640(now, is_due):
    ok, point, _ = due.status("asx", YESTERDAY_EVENING, Z(now))
    assert ok is is_due
    if is_due:
        assert point == Z("2027-06-09T06:40:00Z")


def test_a_screen_stamped_1631_no_longer_reads_fresh_at_1645():
    """The audit's scenario: a 16:31 publish used to satisfy the 16:30 due
    point, so the 06:45Z wake-up found the ASX 'fresh' on pre-auction closes."""
    ok, point, why = due.status("asx", Z("2027-06-09T06:31:00Z"), Z("2027-06-09T06:45:00Z"))
    assert ok and why == "file predates the close it owes"


def test_nasdaq_keeps_its_1630_new_york_due_point():
    assert due.due_point("nasdaq", Z("2026-10-08T22:00:00Z")) == Z("2026-10-08T20:30:00Z")
    assert due.due_point("nasdaq", Z("2026-11-12T23:00:00Z")) == Z("2026-11-12T21:30:00Z")


def test_the_due_instant_follows_the_one_config_constant(monkeypatch):
    monkeypatch.setitem(scfg.DAILY_BAR_FINAL, "asx", ("Australia/Sydney", 16, 50))
    assert due.due_point("asx", Z("2026-10-08T07:00:00Z")) == Z("2026-10-08T05:50:00Z")
    monkeypatch.delitem(scfg.DAILY_BAR_FINAL, "asx")
    assert due.due_point("asx", Z("2026-10-08T07:00:00Z")) == Z("2026-10-08T05:30:00Z")

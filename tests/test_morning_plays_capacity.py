"""The digest says when the paper bot cannot take what it lists (2 Nov, the
owner's "20 more" #18). The digest lists the Bot-cell longs either way; with
every slot full the bot opens none of them until a position closes, so one
line under the header says so, with the day the next time stops fall due on
the engine's own convention (journal.js timeStopOf). Never a guess: a free
slot or an unreadable file prints nothing."""
from __future__ import annotations

import datetime as dt
import json

from scripts import morning_plays as mp
from tests.test_morning_plays import _row


def _data(tmp_path, open_total=60, cap=60, hold=28, rows=()):
    (tmp_path / "bot_rules.json").write_text(json.dumps(
        {"open_total": open_total, "max_open_total": cap, "max_hold_days": hold}), encoding="utf-8")
    (tmp_path / "vivek_bot_book.json").write_text(json.dumps({"open": list(rows)}), encoding="utf-8")
    return tmp_path


def _pos(entry, market="asx", tp1=False):
    return {"entry_date": entry, "market": market, "tp1_hit": tp1}


def test_a_full_book_says_so_with_the_next_time_stop_day(tmp_path):
    # Fri 9 Oct + 29 = Sat 7 Nov -> Monday 9 Nov on a stock market
    d = _data(tmp_path, rows=[_pos("2026-10-09"), _pos("2026-10-20")])
    line = mp.bot_capacity_line(d, dt.date(2026, 11, 3))
    assert line == ("_Bot book full (60/60): the paper bot opens none of these until a "
                    "position closes; its next time stops fall due Mon 9 Nov._")


def test_crypto_is_not_rolled_and_runners_past_tp1_and_past_days_are_skipped(tmp_path):
    rows = [_pos("2026-10-09", market="crypto"),            # Sat 7 Nov, crypto keeps it
            _pos("2026-10-01", tp1=True),                    # past TP1: no time stop
            _pos("2026-09-01")]                              # already past `today`
    d = _data(tmp_path, rows=rows)
    assert mp.next_time_stop(d, 28, dt.date(2026, 11, 3)) == dt.date(2026, 11, 7)
    assert mp.next_time_stop(d, 0, dt.date(2026, 11, 3)) is None      # the rule off


def test_a_free_slot_or_an_unreadable_file_prints_nothing(tmp_path):
    assert mp.bot_capacity_line(_data(tmp_path, open_total=59)) is None
    (tmp_path / "bot_rules.json").write_text("{nope", encoding="utf-8")
    assert mp.bot_capacity_line(tmp_path) is None
    assert mp.bot_capacity_line(tmp_path / "missing") is None


def test_the_line_rides_under_the_header_only_when_there_are_plays():
    line = "_Bot book full (60/60): x._"
    msgs = mp.build_messages({"asx": [_row("NIC")]}, {"asx": 1.0}, "Tue 3 Nov", bot_line=line)
    first = msgs[0].split("\n")
    assert first[1] == line and first[0].startswith("\U0001f3af **VIVEK 5.0 plays")
    empty = mp.build_messages({"asx": []}, {"asx": 1.0}, "Tue 3 Nov", bot_line=line)
    assert line not in "\n".join(empty)

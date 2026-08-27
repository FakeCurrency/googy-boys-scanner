"""The confluence alert's state machine — the watchlist ping that could never fire.

WHY THIS FILE EXISTS (2026-07-29): `diff_new` used to record a bare +count for
EVERY current alignment, posted or not. With DISCORD_CONF_MIN_LENSES=3, every
2-lens alignment had its count burned into journal/confluence_state.json on the
run it formed — including runs where the watchlist was UNAVAILABLE (GBS_SYNC_CODE
unset, or the /api/journal fetch flaked; both return an empty watch set). Star
the name a day later and `count > prev` is `2 > 2`: the ping the watchlist
bypass exists for could never fire. The webhook secret already had exactly this
protection ("don't mark anything as seen"); state counts are now SIGNED so the
watchlist gets it too — +count means DELIVERED, -count means seen for the
ALERTS-page log but never posted.

These tests run the real module against a tmp filesystem (DATA/STATE_FILE/
HISTORY_FILE are monkeypatched module globals) with load_watch_keys stubbed at
the call boundary — no re-typed logic.

DELIVERY REMOVED 2026-08-27 (owner ruling): there is no webhook post anymore.
"Pings" in these tests became "push-worthy (undelivered)" run-log lines plus
NEGATIVE state counts — the machine still decides exactly what a channel OWES
the owner, and the pin is that nothing is ever burned while no channel exists,
so the replacement channel's first run pings everything still current.
"""

from __future__ import annotations

import json

import pytest

from scanner import confluence_alert as ca


def _align(count=2, ticker="WES", market="asx", side="long"):
    return {"market": market, "ticker": ticker, "side": side, "count": count,
            "lenses": ["PHASEMAP", "VIVEK", "SPECS"][:count],
            "labels": ["PHASEMAP SWEPT", "VIVEK A+", "SPECS A"][:count]}


# ── diff_new: the history feed ───────────────────────────────────────────────

class TestDiffNew:
    def test_a_new_alignment_is_fresh(self):
        assert ca.diff_new([_align(2)], {}) == [_align(2)]

    def test_an_upgrade_is_fresh(self):
        assert ca.diff_new([_align(3)], {"asx:WES:long": 2}) == [_align(3)]

    def test_a_persisting_alignment_is_not_fresh_whether_posted_or_not(self):
        # THE point of signed state: |−2| == 2, so an unposted-but-seen
        # alignment does not re-log to the ALERTS page every run.
        assert ca.diff_new([_align(2)], {"asx:WES:long": 2}) == []
        assert ca.diff_new([_align(2)], {"asx:WES:long": -2}) == []

    def test_a_downgrade_is_not_fresh(self):
        assert ca.diff_new([_align(2)], {"asx:WES:long": 3}) == []


# ── build_state: the signs ───────────────────────────────────────────────────

class TestBuildState:
    def test_posted_records_positive(self):
        s = ca.build_state([_align(2)], {}, {"asx:WES:long"})
        assert s == {"asx:WES:long": 2}

    def test_unposted_records_negative(self):
        s = ca.build_state([_align(2)], {}, set())
        assert s == {"asx:WES:long": -2}

    def test_an_unchanged_count_keeps_its_sign(self):
        # +2 must NOT decay to -2 (that would re-arm a ping already delivered),
        # and -2 must not promote itself to +2 (that would burn the pending one).
        assert ca.build_state([_align(2)], {"asx:WES:long": 2}, set()) == {"asx:WES:long": 2}
        assert ca.build_state([_align(2)], {"asx:WES:long": -2}, set()) == {"asx:WES:long": -2}

    def test_lapsed_keys_are_pruned(self):
        s = ca.build_state([], {"asx:WES:long": 3}, set())
        assert s == {}

    def test_a_changed_unposted_count_goes_negative(self):
        # Posted at 3, later downgraded to 2 and not posted: the 2 was never
        # delivered, so a later star (or re-upgrade) must still be able to ping.
        assert ca.build_state([_align(2)], {"asx:WES:long": 3}, set()) == {"asx:WES:long": -2}


# ── main(): the flow end-to-end against a tmp filesystem ─────────────────────

@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Real main() with DATA/STATE/HISTORY on tmp, webhook + watchlist stubbed."""
    data = tmp_path / "data"
    (data / "phasemap" / "asx").mkdir(parents=True)
    monkeypatch.setattr(ca, "DATA", data)
    monkeypatch.setattr(ca, "STATE_FILE", tmp_path / "confluence_state.json")
    monkeypatch.setattr(ca, "HISTORY_FILE", data / "phasemap" / "alert_history.json")
    monkeypatch.setattr(ca.config, "CONF_ALERT_MIN_LENSES", 3, raising=False)

    watch: set[str] = set()
    monkeypatch.setattr(ca, "load_watch_keys", lambda: set(watch))

    def scan(count=2):
        """Publish fixture artefacts that yield one WES alignment of `count` lenses."""
        vivek = {"results": [{"symbol": "WES", "dir": "LONG", "grade": "A+"}]}
        pm = {"results": [{"ticker": "WES", "direction": "bullish",
                           "state": "SWEPT", "tier": "T1"}] if count >= 2 else []}
        spec = {"results": [{"symbol": "WES", "grade": "A"}] if count >= 3 else []}
        (data / "asx_vivek.json").write_text(json.dumps(vivek), encoding="utf-8")
        (data / "phasemap" / "asx" / "latest.json").write_text(json.dumps(pm), encoding="utf-8")
        (data / "asx_spec.json").write_text(json.dumps(spec), encoding="utf-8")

    def state():
        return json.loads((tmp_path / "confluence_state.json").read_text(encoding="utf-8"))

    return type("W", (), {"scan": staticmethod(scan),
                          "watch": watch, "state": staticmethod(state),
                          "run": staticmethod(lambda: ca.main(["--market", "asx"]))})


class TestStarLater:
    def test_the_burned_count_scenario_stays_owed(self, wired, capsys):
        # Day 1: 2-lens forms, unwatched, threshold is triples-only → not
        # push-worthy, state records it as SEEN-NOT-DELIVERED (negative).
        wired.scan(count=2)
        assert wired.run() == 0
        assert "push-worthy" not in capsys.readouterr().out
        assert wired.state()["asx:WES:long"] == -2

        # Day 2: the owner stars WES. Same alignment, same count — the OLD code
        # was `2 > 2` here and stayed silent forever. It must now be recognised
        # as push-worthy, and — with no channel — stay recorded as OWED
        # (negative), so the future channel's first run delivers it.
        wired.watch.add("ASX:WES")
        assert wired.run() == 0
        assert "push-worthy (undelivered)" in capsys.readouterr().out
        assert wired.state()["asx:WES:long"] == -2

    def test_watchlist_outage_does_not_burn_the_count(self, wired, capsys):
        # The fetch-failed case is indistinguishable from "no stars" at the call
        # site (both are an empty set) — the sign is what keeps it safe.
        wired.scan(count=2)
        assert wired.run() == 0                      # outage run: watch empty
        capsys.readouterr()
        wired.watch.add("ASX:WES")                   # fetch recovers, name starred
        assert wired.run() == 0
        assert "push-worthy (undelivered)" in capsys.readouterr().out

    def test_an_upgrade_is_owed_over_a_negative(self, wired, capsys):
        wired.scan(count=2)
        wired.run()                                  # -2, unwatched
        capsys.readouterr()
        wired.scan(count=3)
        assert wired.run() == 0                      # 3 >= min_lenses, 3 > -2
        assert "push-worthy (undelivered)" in capsys.readouterr().out
        assert wired.state()["asx:WES:long"] == -3   # still owed, still signed

    def test_a_previously_delivered_count_never_re_pings(self, wired, capsys):
        # Rows delivered before the 2026-08-27 removal hold POSITIVE counts.
        # They must stay quiet: only counts ABOVE the signed prev are owed.
        wired.scan(count=3)
        ca.STATE_FILE.write_text(json.dumps({"asx:WES:long": 3}),
                                 encoding="utf-8")
        assert wired.run() == 0
        assert "push-worthy" not in capsys.readouterr().out

    def test_an_owed_triple_is_never_promoted_without_delivery(self, wired):
        # The failure that would silently strand the future channel: some code
        # path marking an alignment positive (delivered) when nothing sent it.
        wired.scan(count=3)
        for _ in range(3):
            assert wired.run() == 0
            assert wired.state()["asx:WES:long"] == -3


# ── the history dedup day is the MARKET's day ────────────────────────────────

class TestSessionDay:
    def test_an_aedt_evening_utc_stamp_lands_on_the_next_sydney_day(self):
        # 2026-10-30T23:30Z is 2026-10-31 10:30 in Sydney (AEDT, UTC+11) — the
        # session the alignment actually belongs to. A UTC key would say the
        # 30th and let the same alignment log again after midnight UTC.
        e = {"date": "2026-10-30T23:30:00+00:00", "market": "asx"}
        assert ca._entry_session_day(e) == "2026-10-31"

    def test_a_us_market_stays_on_its_own_date(self):
        # 2026-07-29T01:00Z is still 2026-07-28 in New York.
        e = {"date": "2026-07-29T01:00:00+00:00", "market": "nasdaq"}
        assert ca._entry_session_day(e) == "2026-07-28"

    def test_crypto_and_unknown_markets_read_as_utc(self):
        e = {"date": "2026-07-29T01:00:00+00:00", "market": "crypto"}
        assert ca._entry_session_day(e) == "2026-07-29"
        assert ca._entry_session_day({"date": "2026-07-29T01:00:00+00:00",
                                      "market": "nope"}) == "2026-07-29"

    def test_a_naive_stamp_is_treated_as_utc(self):
        e = {"date": "2026-10-30T23:30:00", "market": "asx"}
        assert ca._entry_session_day(e) == "2026-10-31"

    def test_garbage_falls_back_to_the_old_prefix_slice(self):
        assert ca._entry_session_day({"date": "not-a-date", "market": "asx"}) == "not-a-date"

    def test_append_history_dedups_within_a_day(self, wired, monkeypatch):
        monkeypatch.setattr(ca.config, "CONF_ALERT_MIN_LENSES", 99, raising=False)
        wired.scan(count=2)
        wired.run()
        # Second run same day: state now knows the count, nothing fresh — and
        # even a forced re-log would hit the (day, market, ticker, side, count)
        # dedup. Either way: exactly one entry.
        wired.run()
        hist = json.loads(ca.HISTORY_FILE.read_text(encoding="utf-8"))
        assert len(hist["entries"]) == 1

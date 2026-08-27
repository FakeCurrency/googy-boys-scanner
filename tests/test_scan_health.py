"""The consecutive-dry-run counter — the alert the 2026-07-29 outage was missing.

Yahoo throttled every ASX scan of the morning session; run.py's "no data —
keeping existing JSON" exit is deliberately green (TOP100 #67: an upstream
outage must not mail a red run), so the dashboard quietly served the pre-open
artefact for hours with no signal anywhere. `_scan_health` counts consecutive
dry runs per market in a COMMITTED file (scan.yml SHARED — container-death
lesson from sectorbreadth's ping memory) and pings Discord exactly ONCE per
episode, at the owner-approved threshold.
"""

from __future__ import annotations

import json

import pytest

from scanner import config
from scanner import run as runmod


@pytest.fixture()
def health(tmp_path, monkeypatch):
    path = tmp_path / "scan_health.json"
    monkeypatch.setattr(config, "SCAN_HEALTH_FILE", str(path), raising=False)
    monkeypatch.setattr(config, "SCAN_DRY_ALERT_RUNS", 3, raising=False)
    sent: list[tuple] = []
    send = lambda *a: sent.append(a)  # noqa: E731

    def dry(market="asx"):
        return runmod._scan_health(market, published=False, send=send)

    def ok(market="asx"):
        return runmod._scan_health(market, published=True, send=send)

    def state():
        return json.loads(path.read_text(encoding="utf-8"))

    return type("H", (), {"dry": staticmethod(dry), "ok": staticmethod(ok),
                          "sent": sent, "state": staticmethod(state),
                          "path": path})


def test_the_counter_counts_and_fires_exactly_at_the_threshold(health):
    assert health.dry() == 1
    assert health.dry() == 2
    assert health.sent == [], "two dry runs are weather, not an outage"
    assert health.dry() == 3
    assert len(health.sent) == 1, "the third consecutive dry run is the episode"
    event, title, details = health.sent[0]
    assert event == "scan_dry"
    assert "ASX" in title
    assert "3" in details


def test_a_dragging_outage_does_not_re_ping(health):
    # `==` not `>=` IS the dedupe: one ping per episode. The external
    # /api/health monitor owns escalation past this point.
    for _ in range(8):
        health.dry()
    assert len(health.sent) == 1


def test_a_successful_publish_resets_the_episode(health):
    health.dry(); health.dry()
    assert health.ok() == 0
    assert health.state()["asx"]["dry"] == 0
    assert health.state()["asx"]["last_publish"], "the recovery is stamped"
    # the NEXT outage is a new episode and pings again at its own third run
    health.dry(); health.dry()
    assert health.sent == []
    health.dry()
    assert len(health.sent) == 1


def test_markets_count_independently(health):
    health.dry("asx"); health.dry("asx")
    assert health.dry("nasdaq") == 1, "one market's outage must not borrow another's count"
    assert health.state()["asx"]["dry"] == 2


def test_a_corrupt_state_file_reads_as_fresh_and_never_crashes(health):
    health.path.write_text("not json{", encoding="utf-8")
    assert health.dry() == 1
    assert health.state()["asx"]["dry"] == 1


def test_bookkeeping_failure_cannot_kill_the_scan(health, monkeypatch, capsys):
    monkeypatch.setattr(runmod.output, "write_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert runmod._scan_health("asx", published=False) == -1
    out = capsys.readouterr().out
    assert "scan-health bookkeeping failed" in out
    out.encode("cp1252")   # scanner prints stay console-safe


def test_the_event_is_registered_everywhere_it_needs_to_be():
    """Same shape as sector_run's routing pin: a key missing from the router's
    fallback tables is not an error, it is a silent severity DOWNGRADE."""
    from scanner.broker import alert_router as ar
    assert ar.get_severity("scan_dry") == "NOTICE"
    assert ar.get_channels("scan_dry") == []  # no push channel since the 2026-08-27 Discord removal
    assert config.ALERT_RATE_LIMITS["scan_dry"] == 0
    # the config-less fallbacks must agree, or a config import failure
    # silently downgrades the event to WARNING and re-routes it
    assert ar._SEV_MAP["scan_dry"] == "NOTICE"
    assert ar._RATE_MAP["scan_dry"] == 0
    assert config.SCAN_DRY_ALERT_RUNS >= 2, "a threshold of 1 alarms on ordinary weather"


def test_the_ping_message_is_plain_ascii(health):
    for _ in range(3):
        health.dry()
    _, title, details = health.sent[0]
    (title + details).encode("ascii")

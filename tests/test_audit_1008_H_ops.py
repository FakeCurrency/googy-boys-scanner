"""Audit #55 (2026-10-08): cronjob-update widened a Mon-Fri job to every day.

cronjob_body() filled mdays/months/wdays = [-1] ("every") whenever ANY schedule
field was present -- right for a create, which must state every axis, wrong
for an update: a minutes-only retime PATCHed wdays:[-1] explicitly. An update
now merges the caller's schedule fields into the job's CURRENT schedule (read
with a GET first) and changes nothing if that cannot be read.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ops", ROOT / "scripts" / "ops.py")
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)

ENV = {"CRONJOB_API_KEY": "cronjob-key-FAKE-000001"}

# The live 'scan ASX close (Sydney)' job's shape: 16:40 Sydney, Mon-Fri.
CURRENT = {"jobDetails": {"jobId": 8587590, "title": "scan ASX close (Sydney)",
                          "schedule": {"timezone": "Australia/Sydney", "expiresAt": 0,
                                       "hours": [16], "minutes": [40], "mdays": [-1],
                                       "months": [-1], "wdays": [1, 2, 3, 4, 5]}}}


def _fake(monkeypatch, get_reply=(200, CURRENT)):
    calls = []

    def fake_call(method, url, headers=None, body=None, raw_body=None):
        calls.append((method, url, body))
        if method == "GET":
            return get_reply
        return 200, {}

    monkeypatch.setattr(ops, "call", fake_call)
    return calls


def _patch_body(calls):
    patches = [c for c in calls if c[0] == "PATCH"]
    assert len(patches) == 1
    return patches[0][2]


def test_a_minutes_only_retime_keeps_the_weekday_restriction(monkeypatch):
    calls = _fake(monkeypatch)
    status, _ = ops.run("cronjob-update", {"id": 8587590, "minutes": [42]}, env=ENV)
    assert status == 200
    sched = _patch_body(calls)["job"]["schedule"]
    assert sched["wdays"] == [1, 2, 3, 4, 5], "a retime must never widen Mon-Fri to every day"
    assert sched["minutes"] == [42]
    assert sched["hours"] == [16] and sched["timezone"] == "Australia/Sydney"


def test_a_given_axis_wins_over_the_current_one(monkeypatch):
    calls = _fake(monkeypatch)
    ops.run("cronjob-update", {"id": 8587590, "wdays": [-1], "hours": [17]}, env=ENV)
    sched = _patch_body(calls)["job"]["schedule"]
    assert sched["wdays"] == [-1] and sched["hours"] == [17] and sched["minutes"] == [40]


def test_the_patch_body_never_invents_an_axis_the_job_and_caller_both_lack(monkeypatch):
    calls = _fake(monkeypatch, (200, {"jobDetails": {"schedule": {"minutes": [5], "hours": [1]}}}))
    ops.run("cronjob-update", {"id": 3, "minutes": [6]}, env=ENV)
    sched = _patch_body(calls)["job"]["schedule"]
    assert sched == {"minutes": [6], "hours": [1]}, "no [-1] fill on an update"


def test_an_unreadable_current_schedule_changes_nothing(monkeypatch):
    calls = _fake(monkeypatch, (404, {"error": "not found"}))
    status, result = ops.run("cronjob-update", {"id": 3, "minutes": [6]}, env=ENV)
    assert status == 404 and "nothing was changed" in result["error"]
    assert not [c for c in calls if c[0] == "PATCH"]
    calls = _fake(monkeypatch, (200, {"jobDetails": {}}))
    with pytest.raises(ops.OpsError, match="nothing was changed"):
        ops.run("cronjob-update", {"id": 3, "minutes": [6]}, env=ENV)
    assert not [c for c in calls if c[0] == "PATCH"]


def test_a_non_schedule_update_still_sends_only_its_fields_and_reads_nothing(monkeypatch):
    calls = _fake(monkeypatch)
    ops.run("cronjob-update", {"id": 7, "enabled": False}, env=ENV)
    assert calls == [("PATCH", ops.CRONJOB_API + "/jobs/7", {"job": {"enabled": False}})]


def test_cronjob_body_fills_every_axis_for_a_create_only():
    assert ops.cronjob_body({"minutes": [42]}) == {"job": {"schedule": {"minutes": [42]}}}
    assert ops.cronjob_body({"minutes": [42]}, fill_defaults=True)["job"]["schedule"] == {
        "minutes": [42], "mdays": [-1], "months": [-1], "wdays": [-1]}

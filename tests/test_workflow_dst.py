"""Daylight-saving correctness of the ASX schedule gates (TOP100 #41).

Every ASX cron in scan.yml is written in UTC against an AEST (UTC+10) session:
10:00-16:00 Melbourne == 00:00-06:00 UTC. That equality holds only from April to
October. Under AEDT (UTC+11) the session becomes 23:00-05:00 UTC -- it OPENS ON
THE PREVIOUS UTC DAY -- so `cron: "7 0-5 * * 1-5"` covers 11:00-16:00 AEDT and
the open hour has no scan at all. Monday is worse: its open is Sunday 23:00 UTC,
which `* * 1-5` excludes outright.

The fix lets cron fire a superset (two 23:xx slots) and makes the GATE decide
from the tz database. These tests therefore run the gates' ACTUAL shipped shell
-- extracted from the YAML, with `date`, `curl` and `python3` stubbed -- rather
than asserting on cron strings, because the bug was never in the strings. It was
in what the gate concluded from them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"

AEST = "10"  # UTC+10, April-October
AEDT = "11"  # UTC+11, October-April
PROBE_BROKEN = None  # tz lookup failed -> gate must fail open


def _gate_script(workflow: str, job: str = "gate") -> str:
    """The `run:` body of the gate job's `check` step, verbatim from the YAML."""
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    steps = doc["jobs"][job]["steps"]
    runs = [s["run"] for s in steps if s.get("id") == "check"]
    assert len(runs) == 1, f"{workflow}:{job} no longer has exactly one `id: check` step"
    return runs[0]


def _run_gate(
    script: str,
    *,
    schedule: str,
    event_name: str = "schedule",
    dow: str = "1",
    hour: str = "00",
    offset: str | None = AEST,
    health_ok: bool = False,
) -> dict:
    """Execute the gate's shell with the runner's world stubbed out.

    Returns the parsed $GITHUB_OUTPUT plus `_curl_calls` (how many times the
    freshness probe was actually reached) and `_stdout`.
    """
    # GitHub substitutes ${{ }} before bash ever sees the script.
    script = script.replace("${{ github.event_name }}", event_name)
    script = script.replace("${{ github.event.schedule }}", schedule)
    assert "${{" not in script, "unstubbed ${{ }} expression left in the gate script"

    tmp = Path(tempfile.mkdtemp(prefix="gate-dst-"))
    try:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        curl_log = tmp / "curl.calls"

        # `date -u +%u` (day of week) and `date -u +%H` (hour) are the only
        # forms the gates use; anything else would be a change worth failing on.
        (bin_dir / "date").write_text(
            "#!/bin/sh\n"
            "for a in \"$@\"; do\n"
            "  case \"$a\" in\n"
            f"    +%u) echo {dow}; exit 0 ;;\n"
            f"    +%H) echo {hour}; exit 0 ;;\n"
            "  esac\n"
            "done\n"
            "echo 'unexpected date invocation' >&2; exit 1\n",
            encoding="utf-8",
        )
        health = '{"ok": true}' if health_ok else '{"ok": false}'
        (bin_dir / "curl").write_text(
            f"#!/bin/sh\necho x >> {curl_log}\ncat <<'EOF'\n{health}\nEOF\n",
            encoding="utf-8",
        )
        if offset is None:
            body = "exit 1\n"  # tz database unreadable / zoneinfo missing
        else:
            body = f"echo {offset}\n"
        (bin_dir / "python3").write_text("#!/bin/sh\n" + body, encoding="utf-8")
        for name in ("date", "curl", "python3"):
            (bin_dir / name).chmod(0o755)

        out_file = tmp / "github_output"
        out_file.touch()
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["GITHUB_OUTPUT"] = str(out_file)

        script_file = tmp / "gate.sh"
        script_file.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["bash", "-e", str(script_file)],
            capture_output=True, text=True, env=env, cwd=tmp, timeout=60,
        )
        assert proc.returncode == 0, (
            f"gate script exited {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )

        parsed: dict = {}
        for line in out_file.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                parsed[k] = v
        parsed["_curl_calls"] = curl_log.read_text(encoding="utf-8").count("x") if curl_log.exists() else 0
        parsed["_stdout"] = proc.stdout
        return parsed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# scan.yml -- the AEDT open slots
# --------------------------------------------------------------------------

AEDT_OPEN = "7 23 * * 0-4"
AEDT_OPEN_BACKSTOP = "47 23 * * 0-4"


def test_aedt_open_crons_are_registered():
    doc = yaml.safe_load((WORKFLOWS / "scan.yml").read_text(encoding="utf-8"))
    # PyYAML resolves the bare `on:` key to the boolean True.
    crons = {c["cron"] for c in doc[True]["schedule"]}
    for c in (AEDT_OPEN, AEDT_OPEN_BACKSTOP):
        assert c in crons, (
            f"scan.yml lost `{c}`. Without it the ASX open has no scan for the "
            "half of the year Melbourne is on AEDT (session 23:00-05:00 UTC)."
        )
    # Day-of-week MUST include Sunday: Monday's AEDT open is Sunday in UTC.
    for c in (AEDT_OPEN, AEDT_OPEN_BACKSTOP):
        assert c.endswith("0-4"), f"`{c}` must run Sun-Thu UTC, not Mon-Fri"


def test_aedt_open_slot_is_skipped_while_melbourne_is_on_aest():
    """23:07 UTC is 09:07 AEST -- an hour BEFORE the open. Must not scan."""
    got = _run_gate(_gate_script("scan.yml"), schedule=AEDT_OPEN, dow="1", hour="23", offset=AEST)
    assert got["run"] == "false", got["_stdout"]


def test_aedt_open_slot_runs_a_full_scan_under_aedt():
    got = _run_gate(_gate_script("scan.yml"), schedule=AEDT_OPEN, dow="1", hour="23", offset=AEDT)
    assert got["run"] == "true", got["_stdout"]
    assert got["market_override"] == "", "the AEDT open is a stock session, not crypto-only"


def test_sunday_night_aedt_open_is_not_downgraded_to_crypto():
    """The Sunday trap.

    Monday 10:07 AEDT is Sunday 23:07 UTC. `date -u +%u` says 7, and the weekend
    branch further down the gate turns DOW>=6 into a crypto-only scan. If the
    AEDT branch stopped returning early, Monday's ASX open would quietly become
    a crypto scan every week for half the year.
    """
    got = _run_gate(_gate_script("scan.yml"), schedule=AEDT_OPEN, dow="7", hour="23", offset=AEDT)
    assert got["run"] == "true", got["_stdout"]
    assert got["market_override"] == "", (
        "Sunday 23:00 UTC is Monday morning in Melbourne -- it reached the "
        "UTC-day weekend branch and was downgraded to crypto"
    )


def test_aedt_open_fails_open_when_the_timezone_probe_breaks():
    """An extra pre-open scan costs one run; a missed open costs the session."""
    got = _run_gate(_gate_script("scan.yml"), schedule=AEDT_OPEN, dow="1", hour="23", offset=PROBE_BROKEN)
    assert got["run"] == "true", got["_stdout"]


def test_aedt_open_backstop_skips_when_an_asx_scan_already_landed():
    got = _run_gate(
        _gate_script("scan.yml"), schedule=AEDT_OPEN_BACKSTOP,
        dow="1", hour="23", offset=AEDT, health_ok=True,
    )
    assert got["run"] == "false", got["_stdout"]
    assert got["_curl_calls"] == 1, "the backstop must actually probe before skipping"


def test_aedt_open_backstop_runs_the_missed_open_when_data_is_stale():
    got = _run_gate(
        _gate_script("scan.yml"), schedule=AEDT_OPEN_BACKSTOP,
        dow="1", hour="23", offset=AEDT, health_ok=False,
    )
    assert got["run"] == "true", got["_stdout"]


def test_aedt_open_backstop_does_not_probe_at_all_under_aest():
    """Cheap, but the point is ordering: the DST test gates the network call."""
    got = _run_gate(
        _gate_script("scan.yml"), schedule=AEDT_OPEN_BACKSTOP,
        dow="1", hour="23", offset=AEST, health_ok=True,
    )
    assert got["run"] == "false"
    assert got["_curl_calls"] == 0, "probed the health endpoint on a slot it had already ruled out"


# --------------------------------------------------------------------------
# scan.yml -- the pre-existing branches must be untouched by #41
# --------------------------------------------------------------------------

def test_aest_session_crons_still_run_a_full_scan():
    got = _run_gate(_gate_script("scan.yml"), schedule="7 0-5 * * 1-5", dow="2", hour="01")
    assert got["run"] == "true"
    assert got["market_override"] == ""


def test_weekend_cron_is_still_crypto_only():
    got = _run_gate(_gate_script("scan.yml"), schedule="7 2,8,14,20 * * 0,6", dow="6", hour="02")
    assert got["run"] == "true"
    assert got["market_override"] == "crypto"


def test_existing_47_backstop_still_skips_on_fresh_asx_data():
    got = _run_gate(
        _gate_script("scan.yml"), schedule="47 0-5 * * 1-5",
        dow="2", hour="01", health_ok=True,
    )
    assert got["run"] == "false"
    assert got["_curl_calls"] == 1


def test_existing_47_backstop_still_runs_on_stale_asx_data():
    got = _run_gate(
        _gate_script("scan.yml"), schedule="47 0-5 * * 1-5",
        dow="2", hour="01", health_ok=False,
    )
    assert got["run"] == "true"


def test_manual_dispatch_always_runs():
    got = _run_gate(
        _gate_script("scan.yml"), schedule="", event_name="workflow_dispatch",
        dow="6", hour="23", offset=AEST,
    )
    assert got["run"] == "true", "a manual SCAN press must never be gated by the clock"
    assert got["market_override"] == ""


# --------------------------------------------------------------------------
# crypto_bot.yml -- hour 23 changes owner with daylight saving
# --------------------------------------------------------------------------

def test_crypto_hands_hour_23_to_scan_under_aedt():
    """Otherwise the AEDT open puts two writers in the one-slot `scan` queue."""
    for dow in ("7", "1", "2", "3", "4"):
        got = _run_gate(
            _gate_script("crypto_bot.yml"), schedule="22 * * * *",
            dow=dow, hour="23", offset=AEDT,
        )
        assert got["run"] == "false", f"DOW={dow}: {got['_stdout']}"


def test_crypto_keeps_hour_23_under_aest():
    """Under AEST 23:00 UTC is 09:00 -- no ASX session, so it is crypto's hour."""
    got = _run_gate(
        _gate_script("crypto_bot.yml"), schedule="22 * * * *",
        dow="1", hour="23", offset=AEST,
    )
    assert got["run"] == "true", got["_stdout"]


def test_crypto_keeps_friday_night_even_under_aedt():
    """Friday 23:00 UTC is Saturday 10:00 AEDT -- the ASX is shut."""
    got = _run_gate(
        _gate_script("crypto_bot.yml"), schedule="22 * * * *",
        dow="5", hour="23", offset=AEDT,
    )
    assert got["run"] == "true", got["_stdout"]


def test_crypto_still_skips_the_aest_stock_windows():
    for hour in ("00", "03", "06", "14", "19", "21"):
        got = _run_gate(
            _gate_script("crypto_bot.yml"), schedule="22 * * * *",
            dow="2", hour=hour, offset=AEST,
        )
        assert got["run"] == "false", f"hour {hour}: {got['_stdout']}"


def test_crypto_still_owns_the_off_window_hours():
    for hour in ("07", "10", "13", "22"):
        got = _run_gate(
            _gate_script("crypto_bot.yml"), schedule="22 * * * *",
            dow="2", hour=hour, offset=AEST,
        )
        assert got["run"] == "true", f"hour {hour}: {got['_stdout']}"


def test_crypto_52_backstop_still_bypasses_ownership_when_stale():
    got = _run_gate(
        _gate_script("crypto_bot.yml"), schedule="52 * * * *",
        dow="2", hour="01", offset=AEST, health_ok=False,
    )
    assert got["run"] == "true", "the freshness backstop must ignore window ownership"


# --------------------------------------------------------------------------
# The tz lookup itself
# --------------------------------------------------------------------------

def test_melbourne_timezone_is_resolvable_and_dst_aware():
    """The gates trust zoneinfo over hardcoded changeover dates. Verify it works
    here, and that it really does report both offsets across the year."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    mel = ZoneInfo("Australia/Melbourne")
    jul = dt.datetime(2026, 7, 15, 12, tzinfo=mel).utcoffset().total_seconds() / 3600
    jan = dt.datetime(2026, 1, 15, 12, tzinfo=mel).utcoffset().total_seconds() / 3600
    assert jul == 10, f"July should be AEST (+10), got {jul}"
    assert jan == 11, f"January should be AEDT (+11), got {jan}"


def test_aedt_session_really_does_start_on_the_previous_utc_day():
    """The premise of #41, asserted rather than asserted-in-a-comment."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    mel = ZoneInfo("Australia/Melbourne")
    # A Monday in January: 10:00 open.
    open_mel = dt.datetime(2026, 1, 12, 10, 0, tzinfo=mel)
    assert open_mel.weekday() == 0, "picked a non-Monday"
    open_utc = open_mel.astimezone(dt.timezone.utc)
    assert open_utc.hour == 23, f"AEDT open should be 23:00 UTC, got {open_utc.hour}"
    assert open_utc.weekday() == 6, "AEDT Monday open falls on a UTC Sunday"

    # And in July it is exactly what the original crons assumed.
    open_utc_jul = dt.datetime(2026, 7, 13, 10, 0, tzinfo=mel).astimezone(dt.timezone.utc)
    assert open_utc_jul.hour == 0 and open_utc_jul.weekday() == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

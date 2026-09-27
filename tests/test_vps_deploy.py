"""The VPS host kit under deploy/ (deploy/DESIGN.md section 8, C2).

Every test reads the SHIPPED files -- deploy/systemd/*, deploy/bin/*.sh, the
two Caddyfiles, the two env templates -- never a re-typed mirror. The section
4 schedule table IS encoded here, deliberately: the unit files are compared
against it so a drifted OnCalendar or a renamed job arg fails a push instead
of surfacing as a silent dark market after cutover (the security review
reproduced exactly that: two calendar lines systemd rejects).

External tools: `systemd-analyze` (calendar + verify) and `caddy` are used
when present and the tests skip -- naming why -- when they are not. The pure
Python structural checks always run. `update.sh` and `gc.sh` are EXECUTED
against throw-away git repos under tmp_path with a fake `sudo`/`pip` on
PATH; nothing here touches journal/, public/data or the network.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
UNITS = DEPLOY / "systemd"
BIN = DEPLOY / "bin"
CADDY_DIR = DEPLOY / "caddy"
ENV_DIR = DEPLOY / "env"
WORKFLOWS = ROOT / ".github" / "workflows"

SYSTEMD_ANALYZE = shutil.which("systemd-analyze")
# A newer caddy may be pointed at with CADDY_BIN (Ubuntu's apt caddy is 2.6.2,
# which predates `basic_auth` and the log `query` filter -- D9).
CADDY_BIN = os.environ.get("CADDY_BIN") or shutil.which("caddy")

SCRIPTS = ["install.sh", "update.sh", "preflight.sh", "cutover.sh",
           "rollback.sh", "job.sh", "gc.sh"]

# --------------------------------------------------------------------------
# DESIGN section 4, encoded. timer -> (OnCalendar lines, runner args after
# `run`). Template instances are spelled out so every instance resolves.
# --------------------------------------------------------------------------
TABLE = {
    "vivek5-scan@asx.timer": (
        ["Mon..Fri *-*-* 11..15:07 Australia/Sydney", "Mon..Fri *-*-* 16:07 Australia/Sydney"],
        "scan.yml market=asx slot=hourly reason=cron"),
    "vivek5-scan-close@asx.timer": (
        ["Mon..Fri *-*-* 16:30 Australia/Sydney"],
        "scan.yml market=asx slot=close reason=cron"),
    "vivek5-scan-backstop@asx.timer": (
        ["Mon..Fri *-*-* 17:15 Australia/Sydney"],
        "scan.yml market=asx slot=backstop reason=cron"),
    "vivek5-scan@nasdaq.timer": (
        ["Mon..Fri *-*-* 10:37 America/New_York", "Mon..Fri *-*-* 11..15:07 America/New_York"],
        "scan.yml market=nasdaq slot=hourly reason=cron"),
    "vivek5-scan-close@nasdaq.timer": (
        ["Mon..Fri *-*-* 16:07 America/New_York"],
        "scan.yml market=nasdaq slot=close reason=cron"),
    "vivek5-scan-backstop@nasdaq.timer": (
        ["Mon..Fri *-*-* 17:15 America/New_York"],
        "scan.yml market=nasdaq slot=backstop reason=cron"),
    "vivek5-crypto-bot.timer": (["*-*-* *:22 UTC"], "crypto_bot.yml slot=hourly"),
    "vivek5-crypto-bot-backstop.timer": (["*-*-* *:52 UTC"], "crypto_bot.yml slot=backstop"),
    "vivek5-kill-switch.timer": (["*-*-* *:15,45 UTC"], "kill_switch.yml"),
    "vivek5-phasemap.timer": (["*-*-* 08:30 UTC"], "phasemap.yml"),
    "vivek5-confluence.timer": (["*-*-* 08:45 UTC"], "confluence.yml"),
    "vivek5-reco-note.timer": (["*-*-* 08:52 UTC"], "reco_note.yml"),
    "vivek5-backup-book.timer": (["*-*-* 21:35 UTC"], "backup_book.yml slot=primary"),
    "vivek5-backup-book-backstop.timer": (["*-*-* 23:35 UTC"], "backup_book.yml slot=backstop"),
    "vivek5-alert-returns.timer": (["*-*-* 22:20 UTC"], "alert_returns.yml slot=primary"),
    "vivek5-alert-returns-backstop.timer": (["*-*-* 23:50 UTC"], "alert_returns.yml slot=backstop"),
    "vivek5-evidence-brief.timer": (["*-*-* 21:00 UTC"], "evidence_brief.yml"),
    "vivek5-lens-backtest.timer": (["Sun *-*-* 08:00 UTC"], "lens_backtest.yml"),
    "vivek5-vivek-backtest.timer": (["*-*-01 08:00 UTC"], "vivek_backtest.yml"),
    "vivek5-morning-plays@asx.timer": (["Mon..Fri *-*-* 06..10:15,45 UTC"], "morning_plays.yml slot=asx"),
    "vivek5-morning-plays@us.timer": (["Mon..Fri *-*-* 20..23:15,45 UTC"], "morning_plays.yml slot=us"),
    "vivek5-momentum.timer": (
        ["Mon..Fri *-*-* 06:30 UTC", "Mon..Fri *-*-* 21:30 UTC", "*-*-* 00:30 UTC", "*-*-* 0/3:41 UTC"],
        "momentum.yml"),
}
# The two non-runner timers (their services run a script, not job.sh).
SCRIPT_TIMERS = {
    "vivek5-update.timer": (["*-*-* *:0/5 UTC"], "/opt/vivek5/app/deploy/bin/update.sh"),
    "vivek5-gc.timer": (["Sun *-*-* 03:00 UTC"], "/opt/vivek5/app/deploy/bin/gc.sh"),
}
# job -> lock family (DESIGN 3.2). TimeoutStartSec = workflow timeout + wait.
FAMILY = {
    "scan.yml": "scan", "crypto_bot.yml": "scan", "confluence.yml": "scan",
    "phasemap.yml": "heavy", "lens_backtest.yml": "heavy", "vivek_backtest.yml": "heavy",
    "alert_returns.yml": "heavy", "momentum.yml": "heavy",
    "kill_switch.yml": "default", "reco_note.yml": "default", "backup_book.yml": "default",
    "evidence_brief.yml": "default", "morning_plays.yml": "default",
}
HEAVY = {"phasemap.yml", "lens_backtest.yml", "vivek_backtest.yml", "alert_returns.yml", "momentum.yml"}
IO_IDLE = {"lens_backtest.yml", "vivek_backtest.yml"}
# Documented local scan minutes (CLAUDE.md scan.yml row: 7 ASX 11:07 -> 16:30,
# 7 NASDAQ 10:37 -> 16:07) that the hourly + close timers must reproduce.
DOCUMENTED = {
    "asx": ("Australia/Sydney", {"11:07", "12:07", "13:07", "14:07", "15:07", "16:07", "16:30"},
            ["vivek5-scan@asx.timer", "vivek5-scan-close@asx.timer"]),
    "nasdaq": ("America/New_York", {"10:37", "11:07", "12:07", "13:07", "14:07", "15:07", "16:07"},
               ["vivek5-scan@nasdaq.timer", "vivek5-scan-close@nasdaq.timer"]),
}
HARDENING = {
    "ProtectSystem=strict",
    "ReadWritePaths=/opt/vivek5/app /opt/vivek5/publish /opt/vivek5/state",
    "ProtectHome=yes", "PrivateTmp=yes", "NoNewPrivileges=yes",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _unit(name: str) -> str:
    return (UNITS / name).read_text(encoding="utf-8")


def _keys(text: str) -> dict[str, list[str]]:
    """key -> every value (a unit may repeat OnCalendar=/ReadWritePaths=)."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[", ";")):
            continue
        k, _, v = line.partition("=")
        out.setdefault(k.strip(), []).append(v.strip())
    return out


def _services() -> list[str]:
    return sorted(p.name for p in UNITS.glob("vivek5-*.service"))


def _timers() -> list[str]:
    return sorted(p.name for p in UNITS.glob("vivek5-*.timer"))


def _service_for(timer: str) -> str:
    return timer[: -len(".timer")] + ".service"


def _template(unit: str) -> str:
    """vivek5-scan@asx.service -> vivek5-scan@.service (the file that exists)."""
    m = re.match(r"^(.*@)([^@]*)(\.[a-z]+)$", unit)
    return f"{m.group(1)}{m.group(3)}" if m else unit


def _instance(unit: str) -> str:
    m = re.match(r"^.*@([^@]*)\.[a-z]+$", unit)
    return m.group(1) if m else ""


def _exec_args(service_unit: str) -> str:
    """ExecStart of the service (template resolved), %i substituted."""
    text = _unit(_template(service_unit))
    exec_ = _keys(text)["ExecStart"][0]
    return exec_.replace("%i", _instance(service_unit))


def _workflow_timeout(wf: str) -> int:
    text = (WORKFLOWS / wf).read_text(encoding="utf-8")
    mins = [int(m) for m in re.findall(r"^\s*timeout-minutes:\s*(\d+)", text, re.M)]
    assert mins, f"{wf} has no timeout-minutes"
    return max(mins)


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _calendar_elapses(spec: str, base: str, n: int) -> list[dt.datetime]:
    """UTC instants systemd would fire `spec` at, from `base`, n iterations."""
    env = dict(os.environ, TZ="UTC", LC_ALL="C")
    r = _run([SYSTEMD_ANALYZE, "calendar", f"--base-time={base}", f"--iterations={n}", spec], env=env)
    assert r.returncode == 0, f"{spec!r}: {r.stderr}"
    out = []
    for m in re.finditer(r"(?:Next elapse|Iteration #\d+):\s+\w{3} (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC", r.stdout):
        out.append(dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc))
    assert len(out) == n, f"{spec!r}: parsed {len(out)} of {n} elapses from:\n{r.stdout}"
    return out


def _live(text: str) -> str:
    """The lines bash would execute: comment-only lines dropped (the scripts
    DOCUMENT the rules they follow, e.g. "no set -x", and a pin must read the
    code, not the prose)."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _env_names(path: pathlib.Path) -> set[str]:
    return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8"), re.M)}


# --------------------------------------------------------------------------
# 1. every VPS workflow has a unit; the section 4 table is what ships
# --------------------------------------------------------------------------
def test_every_vps_workflow_maps_to_a_unit_and_close_position_rides_the_spool():
    jobs_on_timers = set()
    for svc in _services():
        args = _keys(_unit(svc)).get("ExecStart", [""])[0]
        m = re.search(r"deploy/bin/job\.sh (\S+\.yml)", args)
        if m:
            jobs_on_timers.add(m.group(1))
    wanted = set(config.VPS_WORKFLOWS_TO_DISABLE) - {"close_position.yml", "dispatch_scan.yml"}
    assert wanted <= jobs_on_timers, sorted(wanted - jobs_on_timers)
    assert jobs_on_timers <= wanted, f"units for workflows cutover does not disable: {sorted(jobs_on_timers - wanted)}"
    # close_position.yml arrives through the spool, not a timer
    spool = _keys(_unit("vivek5-spool.service"))
    assert spool["ExecStart"] == ["/opt/vivek5/venv/bin/python -m scanner.vps drain-spool"]
    path = _keys(_unit("vivek5-spool.path"))
    assert path["Unit"] == ["vivek5-spool.service"]
    assert path["PathExistsGlob"] == ["/opt/vivek5/state/spool/*.json"], (
        "DirectoryNotEmpty= would be permanently true: done/ and failed/ live INSIDE spool/")
    assert "StartLimitIntervalSec=0" in _unit("vivek5-spool.service")


def test_the_section_4_table_is_exactly_what_ships():
    assert set(_timers()) == set(TABLE) | set(SCRIPT_TIMERS)
    for timer, (cals, args) in TABLE.items():
        k = _keys(_unit(timer))
        assert k["OnCalendar"] == cals, timer
        svc = _service_for(timer)
        assert k["Unit"] == [svc], timer
        assert (UNITS / _template(svc)).exists(), f"{timer} starts {svc} but no unit file"
        assert _exec_args(svc) == f"/opt/vivek5/app/deploy/bin/job.sh {args}", svc
    for timer, (cals, script) in SCRIPT_TIMERS.items():
        k = _keys(_unit(timer))
        assert k["OnCalendar"] == cals, timer
        svc = _service_for(timer)
        assert k["Unit"] == [svc]
        assert _keys(_unit(svc))["ExecStart"] == [script]


def test_every_template_instance_named_in_the_table_resolves():
    for timer in TABLE:
        svc = _service_for(timer)
        if "@" in svc:
            assert _instance(svc), svc
            assert (UNITS / _template(svc)).exists()
    # and the failure hook / spool templates exist
    assert (UNITS / "vivek5-failed@.service").exists()


def test_job_args_use_only_the_jobs_table_vocabulary():
    """market/slot/reason values are the ones DESIGN 3.2/3.3 define."""
    allowed = {"market": {"asx", "nasdaq"}, "slot": {"hourly", "close", "backstop", "primary", "asx", "us"},
               "reason": {"cron"}}
    for timer, (_, args) in TABLE.items():
        parts = args.split()
        assert parts[0].endswith(".yml")
        for kv in parts[1:]:
            key, _, val = kv.partition("=")
            assert key in allowed and val in allowed[key], (timer, kv)
        # OPERATOR-ONLY args never appear on a timer (extra/args/force/dry_run)
        assert not any(kv.split("=")[0] in {"extra", "args", "force", "dry_run"} for kv in parts[1:]), timer


# --------------------------------------------------------------------------
# 2. calendars
# --------------------------------------------------------------------------
@pytest.mark.skipif(not SYSTEMD_ANALYZE, reason="systemd-analyze not installed")
def test_every_oncalendar_line_passes_systemd_analyze_calendar():
    seen = set()
    for timer in _timers():
        for cal in _keys(_unit(timer))["OnCalendar"]:
            if cal in seen:
                continue
            seen.add(cal)
            r = _run([SYSTEMD_ANALYZE, "calendar", cal])
            assert r.returncode == 0, f"{timer}: OnCalendar={cal!r} rejected: {r.stderr.strip()}"
    assert seen


@pytest.mark.skipif(not SYSTEMD_ANALYZE, reason="systemd-analyze not installed")
@pytest.mark.parametrize("base", [
    "2026-09-28 00:00:00 UTC",  # AEST + EDT
    "2026-10-12 00:00:00 UTC",  # AEDT + EDT (Sydney changed 2026-10-04)
    "2026-11-09 00:00:00 UTC",  # AEDT + EST (New York changed 2026-11-01)
    "2027-04-12 00:00:00 UTC",  # AEST + EDT again (Sydney 2027-04-04, NY 2027-03-14)
])
def test_scan_timer_elapses_equal_the_documented_market_local_minutes(base):
    """Seven scans per market per day, at the documented local minutes, in
    every DST regime, always on a weekday IN THE MARKET'S ZONE."""
    for market, (tzname, minutes, timers) in DOCUMENTED.items():
        tz = ZoneInfo(tzname)
        instants: list[dt.datetime] = []
        for timer in timers:
            for cal in _keys(_unit(timer))["OnCalendar"]:
                instants += _calendar_elapses(cal, base, 10)
        local = [t.astimezone(tz) for t in instants]
        assert {t.strftime("%H:%M") for t in local} == minutes, (market, base)
        assert all(t.weekday() < 5 for t in local), (market, base)
        # exactly one full weekday's worth of elapses is the documented seven
        first_day = min(local).date()
        assert sum(1 for t in local if t.date() == first_day) == 7, (market, base)


@pytest.mark.skipif(not SYSTEMD_ANALYZE, reason="systemd-analyze not installed")
def test_the_backstop_fires_after_the_close_scan_had_time_to_fail():
    for market, tzname in (("asx", "Australia/Sydney"), ("nasdaq", "America/New_York")):
        tz = ZoneInfo(tzname)
        cal = _keys(_unit(f"vivek5-scan-backstop@{market}.timer"))["OnCalendar"][0]
        t = _calendar_elapses(cal, "2026-09-28 00:00:00 UTC", 1)[0].astimezone(tz)
        assert t.strftime("%H:%M") == "17:15" and t.weekday() < 5


# --------------------------------------------------------------------------
# 3. systemd-analyze verify on a path-rewritten copy
# --------------------------------------------------------------------------
@pytest.mark.skipif(not SYSTEMD_ANALYZE, reason="systemd-analyze not installed")
def test_systemd_analyze_verify_passes_on_a_path_rewritten_copy(tmp_path):
    root = tmp_path / "root"
    (root / "opt/vivek5/venv/bin").mkdir(parents=True)
    (root / "opt/vivek5/app/deploy/bin").mkdir(parents=True)
    (root / "etc/vivek5").mkdir(parents=True)
    stub = root / "opt/vivek5/venv/bin/python"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    for s in SCRIPTS:
        shutil.copy(BIN / s, root / "opt/vivek5/app/deploy/bin" / s)
    shutil.copy(ENV_DIR / "jobs.env.example", root / "etc/vivek5/jobs.env")
    shutil.copy(ENV_DIR / "api.env.example", root / "etc/vivek5/api.env")
    node = shutil.which("node") or "/bin/true"
    units = tmp_path / "units"
    units.mkdir()
    for f in UNITS.glob("vivek5-*"):
        text = f.read_text(encoding="utf-8")
        text = text.replace("/opt/vivek5", str(root / "opt/vivek5")).replace("/etc/vivek5", str(root / "etc/vivek5"))
        text = text.replace("/usr/bin/node", node)
        (units / f.name).write_text(text, encoding="utf-8")
    r = _run([SYSTEMD_ANALYZE, "verify"] + sorted(str(p) for p in units.iterdir()))
    assert r.returncode == 0, r.stderr + r.stdout
    # verify is quiet on success; any line mentioning a unit is a problem
    noise = [l for l in (r.stderr + r.stdout).splitlines() if "vivek5-" in l]
    assert not noise, noise


# --------------------------------------------------------------------------
# 4. scripts: syntax, no tracing, executable, help
# --------------------------------------------------------------------------
@pytest.mark.parametrize("script", SCRIPTS)
def test_bash_n_on_every_script(script):
    r = _run(["bash", "-n", str(BIN / script)])
    assert r.returncode == 0, r.stderr
    assert (BIN / script).stat().st_mode & stat.S_IXUSR, f"{script} is not executable"
    assert (BIN / script).read_text(encoding="utf-8").startswith("#!/usr/bin/env bash\n")


def test_no_set_x_anywhere_in_deploy_bin():
    bad = re.compile(r"(set\s+-[a-zA-Z]*x|set\s+-o\s+xtrace|bash\s+-x|^#!.*\s-x)", re.M)
    for s in SCRIPTS:
        raw = (BIN / s).read_text(encoding="utf-8")
        text = raw.splitlines()[0] + "\n" + _live(raw)  # shebang + executable lines
        assert not bad.search(text), f"{s} traces (a trace prints every secret in the environment)"
        assert "printenv" not in text and not re.search(r"^\s*env\s*$", text, re.M), s


@pytest.mark.parametrize("script", ["install.sh", "preflight.sh", "cutover.sh", "rollback.sh"])
def test_operator_scripts_answer_help_without_root(script):
    r = _run([str(BIN / script), "--help"])
    assert r.returncode == 0, r.stderr
    assert "deploy/bin/" in r.stdout


def test_job_sh_is_thin_and_locks_nothing():
    text = (BIN / "job.sh").read_text(encoding="utf-8")
    assert 'exec "${VIVEK_VENV:-/opt/vivek5/venv}/bin/python" -m scanner.vps run "$@"' in text
    assert 'cd "${VIVEK_HOME:-/opt/vivek5/app}"' in text
    assert "export GITHUB_SHA" in text and "git rev-parse HEAD" in text
    assert "flock" not in _live(text), "locks are taken INSIDE the runner (C1); the unit must not double-lock"
    body = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    assert len(body) <= 8, body


# --------------------------------------------------------------------------
# 5. unit hygiene: users, env files, hardening, failure hook, timeouts
# --------------------------------------------------------------------------
def test_no_root_units_and_api_runs_as_its_own_user():
    for svc in _services():
        k = _keys(_unit(svc))
        user = k.get("User", [None])[0]
        if svc == "vivek5-api.service":
            assert user == "vivek5-api", svc
        else:
            assert user == "vivek5", f"{svc} runs as {user!r}"


def test_no_dash_environmentfile_anywhere():
    for f in UNITS.glob("vivek5-*"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("EnvironmentFile="):
                assert line.startswith("EnvironmentFile=/etc/vivek5/"), (f.name, line)
                assert not line.startswith("EnvironmentFile=-"), (f.name, line)


def test_api_unit_loads_api_env_only_and_is_shaped_per_design():
    k = _keys(_unit("vivek5-api.service"))
    assert k["EnvironmentFile"] == ["/etc/vivek5/api.env"]
    assert k["ExecStart"] == ["/usr/bin/node /opt/vivek5/app/deploy/api/server.mjs"]
    assert k["Restart"] == ["on-failure"] and k["RestartSec"] == ["5"]
    assert k["MemoryMax"] == ["512M"]
    assert k["StartLimitIntervalSec"] == ["0"]
    assert k["OnFailure"] == ["vivek5-failed@%n.service"]
    assert k["SupplementaryGroups"] == ["vivek5-spool"]
    for opt in ("ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes", "NoNewPrivileges=yes"):
        assert opt in _unit("vivek5-api.service"), opt
    # nobody else loads the adapter's env, and the adapter never loads jobs.env
    for svc in _services():
        if svc == "vivek5-api.service":
            continue
        assert _keys(_unit(svc))["EnvironmentFile"] == ["/etc/vivek5/jobs.env"], svc


def test_every_job_service_has_the_failure_hook_hardening_and_no_log_rate_limit():
    for svc in _services():
        text = _unit(svc)
        k = _keys(text)
        if svc == "vivek5-failed@.service":
            assert "OnFailure" not in k, "the hook must not fire itself"
        else:
            assert k["OnFailure"] == ["vivek5-failed@%n.service"], svc
        if svc == "vivek5-api.service":
            continue
        assert k["Type"] == ["oneshot"], svc
        assert k["KillMode"] == ["mixed"], svc
        assert k["WorkingDirectory"] == ["/opt/vivek5/app"], svc
        if svc != "vivek5-failed@.service":
            assert k["LogRateLimitIntervalSec"] == ["0"], svc
        if svc == "vivek5-update.service":
            # the one documented exception: sudo (setuid) for the api restart
            assert "NoNewPrivileges" not in k and "sudo" in text and k["ProtectSystem"] == ["full"]
            assert "ProtectHome=yes" in text and "PrivateTmp=yes" in text
            continue
        for opt in HARDENING:
            assert opt in text, (svc, opt)


def test_timeoutstartsec_is_the_workflow_timeout_plus_the_lock_wait():
    """The Actions timeout bounded the RUNNING job (a queued run waited for
    free); on the box the wait happens inside the unit, so the hang detector
    is timeout-minutes + the family's lock wait (config.VPS_LOCK_WAIT_S)."""
    for timer, (_, args) in TABLE.items():
        job = args.split()[0]
        svc = _service_for(timer)
        k = _keys(_unit(_template(svc)))
        want = _workflow_timeout(job) + config.VPS_LOCK_WAIT_S[FAMILY[job]] // 60
        assert k["TimeoutStartSec"] == [f"{want}min"], (svc, k["TimeoutStartSec"], want)
        text = _unit(_template(svc))
        if job in HEAVY:
            assert k["Nice"] == ["10"] and "MemoryHigh" in k, svc
        else:
            assert "Nice" not in k, svc
        assert ("IOSchedulingClass=idle" in text) == (job in IO_IDLE), svc


def test_timers_are_persistent_accurate_and_market_timers_are_not_jittered():
    for timer in _timers():
        k = _keys(_unit(timer))
        assert k["Persistent"] == ["true"], timer
        assert k["AccuracySec"] == ["1s"], timer
        assert "WantedBy=timers.target" in _unit(timer), timer
        if any(s in timer for s in ("scan", "crypto", "kill", "backstop", "update", "morning")):
            assert k["RandomizedDelaySec"] == ["0"], timer


def test_failed_hook_runs_notify_failure_with_the_failed_unit_name():
    k = _keys(_unit("vivek5-failed@.service"))
    assert k["ExecStart"] == ["/opt/vivek5/venv/bin/python -m scanner.vps notify-failure %i"]
    assert k["User"] == ["vivek5"]
    assert "journalctl" in _unit("vivek5-failed@.service")  # the group requirement is documented


# --------------------------------------------------------------------------
# 6. env templates
# --------------------------------------------------------------------------
API_FORBIDDEN = re.compile(r"\b(BYBIT_|ALPACA_|GBS_SMTP_|TELEGRAM_|DISCORD_|GIT_)")


def test_api_env_example_carries_no_job_secret_names():
    text = (ENV_DIR / "api.env.example").read_text(encoding="utf-8")
    assert not API_FORBIDDEN.search(text), API_FORBIDDEN.search(text).group(0)
    names = _env_names(ENV_DIR / "api.env.example")
    for n in ("PORT", "VIVEK_PUBLIC_DIR", "VIVEK_STATE_DIR", "VIVEK_BOOK", "DISPATCH_URL",
              "DISPATCH_TOKEN", "MORNING_PLAYS_TRIGGER_SECRET", "TRUST_PROXY", "VIVEK_PHASE"):
        assert n in names, n
    assert re.search(r"^DISPATCH_TOKEN=CHANGE_ME$", text, re.M)
    assert re.search(r"^DISPATCH_URL=http://127\.0\.0\.1:8787/api/dispatch$", text, re.M)
    assert re.search(r"^PORT=8787$", text, re.M)


DESIGN_3_8_JOBS = [
    "VIVEK_HOME", "VIVEK_PUBLISH", "VIVEK_STATE_DIR", "VIVEK_VENV", "VIVEK_GIT_PUBLISH",
    "VIVEK_RUNS_LEDGER", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL", "GIT_SSH_COMMAND", "HOME", "XDG_CACHE_HOME", "WATCHDOG_HOST",
    "VIVEK_BACKUP_TARGET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GBS_SMTP_HOST",
    "GBS_SMTP_PORT", "GBS_SMTP_USER", "GBS_SMTP_PASS", "GBS_ALERT_TO", "GBS_ALERT_FROM",
    "DISCORD_MORNING_WEBHOOK_URL", "BYBIT_API_KEY", "BYBIT_API_SECRET", "BYBIT_TESTNET",
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY",
]
# Variables the scripts read from the CALLING SHELL only, by design.
SHELL_ONLY = {"GH_ADMIN_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CF_PAGES_PROJECT",
              "VIVEK_ACCEPT_NO_ALERT_CHANNEL", "VIVEK_REPO_SSH"}
# Written by install.sh into /etc/caddy/vivek5.env for the Caddyfile placeholders.
CADDY_ENV = {"VIVEK_DOMAIN", "VIVEK_API_BASIC_USER", "VIVEK_API_BASIC_HASH"}
BASH_BUILTIN = {"PATH", "PWD", "RANDOM", "LINENO", "IFS", "OPTARG", "OPTIND", "REPLY", "SECONDS",
                "HOSTNAME", "PIPESTATUS", "BASH_SOURCE", "EUID", "UID", "DEBIAN_FRONTEND"}
OS_RELEASE = {"ID", "VERSION_ID", "PRETTY_NAME", "NAME"}


def test_jobs_env_example_names_every_variable_the_kit_reads():
    jobs = _env_names(ENV_DIR / "jobs.env.example")
    api = _env_names(ENV_DIR / "api.env.example")
    for n in DESIGN_3_8_JOBS:
        assert n in jobs, f"DESIGN 3.8 variable {n} missing from jobs.env.example"
    # every secret the VPS workflows pass through (`secrets.X`), minus GitHub's own token
    secrets = set()
    for wf in config.VPS_WORKFLOWS_TO_DISABLE:
        secrets |= set(re.findall(r"secrets\.([A-Z_]+)", (WORKFLOWS / wf).read_text(encoding="utf-8")))
    secrets -= {"GITHUB_TOKEN", "GH_TOKEN"}
    assert secrets <= jobs, sorted(secrets - jobs)
    # every $UPPER the scripts and units reference is accounted for
    referenced = set()
    for s in SCRIPTS:
        referenced |= set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", (BIN / s).read_text(encoding="utf-8")))
    for f in UNITS.glob("vivek5-*"):
        referenced |= set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", f.read_text(encoding="utf-8")))
    unknown = referenced - jobs - api - SHELL_ONLY - CADDY_ENV - BASH_BUILTIN - OS_RELEASE
    assert not unknown, sorted(unknown)
    # the two files share only the state dir; the runner identity stays out of api.env
    assert jobs & api == {"VIVEK_STATE_DIR"}, sorted(jobs & api)


def test_jobs_env_example_placeholders_and_identity():
    text = (ENV_DIR / "jobs.env.example").read_text(encoding="utf-8")
    assert "CHANGE_ME" in text
    assert re.search(rf"^GIT_AUTHOR_NAME={config.VPS_GIT_AUTHOR_NAME}$", text, re.M)
    assert re.search(rf"^GIT_AUTHOR_EMAIL={re.escape(config.VPS_GIT_AUTHOR_EMAIL_DEFAULT)}$", text, re.M)
    sentinel = (ROOT / "scripts" / "commit_sentinel.py").read_text(encoding="utf-8")
    assert config.VPS_GIT_AUTHOR_EMAIL_DEFAULT in sentinel, "the VPS email must be in ALLOWED_EMAILS"
    assert re.search(r"^GIT_SSH_COMMAND=\"ssh -i /etc/vivek5/deploy_key -o IdentitiesOnly=yes "
                     r"-o UserKnownHostsFile=/etc/vivek5/known_hosts -o StrictHostKeyChecking=yes\"$", text, re.M)
    assert re.search(r"^VIVEK_GIT_PUBLISH=1$", text, re.M)
    assert re.search(r"^VIVEK_RUNS_LEDGER=/opt/vivek5/state/runs\.json$", text, re.M)
    assert not re.search(r"^\s*GH_ADMIN_TOKEN\s*=", text, re.M)
    # every assignment has a comment above it explaining the variable
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^[A-Z][A-Z0-9_]*=", line):
            j = i - 1
            while j >= 0 and re.match(r"^[A-Z][A-Z0-9_]*=", lines[j]):
                j -= 1
            assert j >= 0 and lines[j].startswith("#"), f"{line.split('=')[0]} has no comment"


def test_no_discord_webhook_url_literal_anywhere_under_deploy():
    """The removed alert webhook's name must not reappear in anything the box
    RUNS or LOADS (units, scripts, env templates, Caddyfiles, journald).
    DESIGN.md/README.md are prose and may name it while stating this rule."""
    checked = 0
    for p in DEPLOY.rglob("*"):
        if p.is_file() and p.suffix != ".md":
            checked += 1
            assert "DISCORD_WEBHOOK_URL" not in p.read_text(encoding="utf-8", errors="replace"), p
    assert checked >= 60


# --------------------------------------------------------------------------
# 7. Caddyfiles
# --------------------------------------------------------------------------
def _caddy(name: str) -> str:
    return (CADDY_DIR / name).read_text(encoding="utf-8")


def _braces_balance(text: str) -> bool:
    depth = 0
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    return False
    return depth == 0


def test_caddyfile_phase1_is_dispatch_and_vps_only():
    t = _caddy("Caddyfile.phase1")
    assert _braces_balance(t)
    assert t.startswith("#") and "{$VIVEK_DOMAIN} {" in t
    assert "/api/dispatch" in t and "/api/vps" in t
    assert "reverse_proxy 127.0.0.1:8787" in t
    assert "header_up X-Forwarded-For {http.request.remote.host}" in t
    live = "\n".join(l for l in t.splitlines() if not l.strip().startswith("#"))
    assert "file_server" not in live and "root *" not in live, "phase 1 serves no files"
    assert re.search(r"handle\s*\{\s*respond 404\s*\}", live)
    assert "remote_ip" in t and "cloudflare.com/ips-v4" in t  # the optional allow-list, commented
    assert "delete key" in live and "request>uri query" in live
    assert ":80" not in live and "tls internal" not in live


def test_caddyfile_phase2_mirrors_public_headers_and_locks_scan_and_close():
    t = _caddy("Caddyfile.phase2")
    assert _braces_balance(t)
    live = "\n".join(l for l in t.splitlines() if not l.strip().startswith("#"))
    assert "root * /opt/vivek5/app/public" in live
    assert "file_server" in live and "encode zstd gzip" in live
    # public/_headers parity, read from the shipped _headers file
    headers = (ROOT / "public" / "_headers").read_text(encoding="utf-8")
    assert "Cache-Control: public, max-age=86400" in headers and "must-revalidate" in headers
    assert re.search(r'@versioned path /js/\* /css/\*\s*\n\s*header @versioned Cache-Control "public, max-age=86400"', live)
    assert 'Cache-Control "public, max-age=0, must-revalidate"' in live
    assert "X-Content-Type-Options nosniff" in live
    m = re.search(r"@scanclose path ([^\n]+)\n\s*basic_auth @scanclose \{\s*\{\$VIVEK_API_BASIC_USER\} \{\$VIVEK_API_BASIC_HASH\}\s*\}", live)
    assert m, "basic_auth must be ON for /api/scan and /api/close"
    assert set(m.group(1).split()) == {"/api/scan", "/api/close"}
    assert re.search(r"handle /api/\* \{\s*reverse_proxy 127\.0\.0\.1:8787", live)
    assert "handle_errors 404" in live and "/404.html" in live
    assert "delete key" in live and "request>uri query" in live
    assert ":80" not in live and "tls internal" not in live


def _caddy_version_ok() -> bool:
    if not CADDY_BIN:
        return False
    r = _run([CADDY_BIN, "version"])
    m = re.search(r"v?(\d+)\.(\d+)", r.stdout)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (2, 8)


@pytest.mark.skipif(not _caddy_version_ok(),
                    reason="caddy >= 2.8 not available (Ubuntu's apt 2.6.2 lacks basic_auth; set CADDY_BIN)")
@pytest.mark.parametrize("phase", ["phase1", "phase2"])
def test_caddyfiles_validate(phase):
    env = dict(os.environ, VIVEK_DOMAIN="example.com", VIVEK_API_BASIC_USER="vivek",
               VIVEK_API_BASIC_HASH="$2a$14$pRlTLZVol27g90asf6plYu6ePGgGWAd.xabL42NxNBhSdTs98N2WO")
    r = _run([CADDY_BIN, "validate", "--adapter", "caddyfile", "--config", str(CADDY_DIR / f"Caddyfile.{phase}")], env=env)
    assert r.returncode == 0, r.stderr + r.stdout


# --------------------------------------------------------------------------
# 8. cutover / rollback / install / preflight (static)
# --------------------------------------------------------------------------
def _workflow_array(script: str) -> list[str]:
    text = (BIN / script).read_text(encoding="utf-8")
    m = re.search(r"^workflows=\(\n(.*?)\n\)", text, re.M | re.S)
    assert m, f"{script} has no workflows=( ... ) array"
    return re.findall(r"[a-z_]+\.yml", m.group(1))


@pytest.mark.parametrize("script", ["cutover.sh", "rollback.sh"])
def test_cutover_and_rollback_name_exactly_the_workflows_config_disables(script):
    got = _workflow_array(script)
    assert sorted(got) == sorted(config.VPS_WORKFLOWS_TO_DISABLE)
    assert len(got) == len(set(got)) == 15


def test_cutover_follows_section_7_in_order_and_handles_the_token_safely():
    t = (BIN / "cutover.sh").read_text(encoding="utf-8")
    order = ["preflight.sh", "enable --now vivek5-api.service", "/api/vps",
             "DISPATCH_URL", "cf-set-var", "cf-delete-var", "GH_DISPATCH_TOKEN",
             "/disable", "disabled_manually", "VPS_ACTIVE", "status=$s", "1800",
             "reset -q --hard origin/main", "publish_head", "enable --now", "list-timers",
             "rollback.sh", "DELETE the GH_ADMIN_TOKEN"]
    pos = -1
    for needle in order:
        nxt = t.find(needle, pos + 1)
        assert nxt > pos, f"{needle!r} missing or out of order"
        pos = nxt
    assert "read -rs" in t and "trap 'unset GH_ADMIN_TOKEN" in t
    assert "-w '%{http_code}'" in t and "curl -v" not in t
    assert "actions/variables" in t and '"value":\\"1\\"' not in t
    assert "queued" in t and "in_progress" in t
    assert "pages/projects" in t and "CLOUDFLARE_API_TOKEN" in t and "CF_PAGES_PROJECT" in t
    assert "GH_ADMIN_TOKEN=" not in t.replace("GH_ADMIN_TOKEN=... sudo", "").replace("GH_ADMIN_TOKEN=github_pat", ""), \
        "the token is never assigned a literal"
    assert 'GH_ADMIN_TOKEN\\s*=' in t  # refuses an env-file assignment


def test_rollback_reverses_cutover():
    t = _live((BIN / "rollback.sh").read_text(encoding="utf-8"))
    assert 0 < t.find("disable --now") < t.find("/enable") < t.find("VPS_ACTIVE 0") < t.find("GH_DISPATCH_TOKEN")
    assert "read -rs" in t and "trap 'unset GH_ADMIN_TOKEN" in t
    assert 'state=="active"' in t.replace(" ", "") or '"$state" = "active"' in t
    assert "vivek5-spool.path" in t and "vivek5-api.service" in t
    assert "-w '%{http_code}'" in t and "curl -v" not in t


def test_install_sh_does_what_section_1_says_and_nothing_more():
    t = (BIN / "install.sh").read_text(encoding="utf-8")
    for needle in ["python3.12-venv", "python3-pip", "rsync", "ca-certificates", "gnupg",
                   "deb.nodesource.com/node_22.x", "dl.cloudsmith.io/public/caddy/stable",
                   "groupadd --system vivek5-spool", "useradd --system", "usermod -aG vivek5-spool vivek5-api",
                   "install -d -m 2770 -o vivek5 -g vivek5-spool", "--filter=blob:none",
                   "config gc.auto 0", "safe.directory", "python3 -m venv", "pip\" install -q -r",
                   "compileall", "install -m 0644 -o root -g root \"$f\" /etc/systemd/system/",
                   "systemctl daemon-reload", "openssl rand -hex 32", "ssh-keygen -q -t ed25519",
                   "ssh-keyscan", "ssh-keygen -lf", "githubs-ssh-key-fingerprints",
                   "journald.conf.d/vivek5.conf", "/etc/sudoers.d/vivek5", "visudo -cf",
                   "timedatectl set-timezone Etc/UTC", "Caddyfile.phase$phase", "--units",
                   "sudo deploy/bin/install.sh"]:
        assert needle in t, needle
    assert "ln -s" not in t, "units are copied, never symlinked"
    assert "apt-get install -y -q caddy" in t and "apt-get install -y -q nodejs" in t
    # the two sudoers commands, exactly
    m = re.search(r"^vivek5 ALL=\(root\) NOPASSWD: (.+)$", t, re.M)
    assert m and [c.strip() for c in m.group(1).split(",")] == [
        "/usr/bin/systemctl restart vivek5-api.service", "/usr/bin/systemctl reload caddy"]
    # timers are NOT enabled by install (cutover does that)
    assert not re.search(r"systemctl enable[^\n]*vivek5-", t)
    assert not re.search(r"enable --now[^\n]*\.timer", t)
    # env files only if absent, with the right owners
    assert 'if [ ! -e "$etc/jobs.env" ]' in t and 'if [ ! -e "$etc/api.env" ]' in t
    assert "-g vivek5 \"$kit/env/jobs.env.example\"" in t and "-g vivek5-api" in t
    assert "curl | bash" not in t.replace("never from `curl | bash`", "")


def test_preflight_covers_every_section_7_step_0_check():
    t = (BIN / "preflight.sh").read_text(encoding="utf-8")
    for needle in ["24.04", "timedatectl show -p Timezone", "NTPSynchronized", "node --version",
                   "caddy version", "Python 3.12.", "pandas", "yfinance", "pybit", "yaml",
                   "-ge 20", "systemd-analyze calendar", "systemd-analyze verify", "CHANGE_ME",
                   "0640", "GH_ADMIN_TOKEN", "push --dry-run origin HEAD:main", "getent ahosts",
                   "/api/vps", "query1.finance.yahoo.com", "api.binance.com", "api.github.com",
                   "--test-alert", "sent via (telegram|email)", "VIVEK_ACCEPT_NO_ALERT_CHANNEL",
                   "--measure", "--limit", "40", "VIVEK_GIT_PUBLISH=0", "ru_maxrss", "worktree",
                   "state/HALT", "PASS", "FAIL", "WARN", "remedy"]:
        assert needle in t, needle
    assert re.search(r'\[ "\$fails" -eq 0 \] \|\| exit 1', t)
    assert "set -uo pipefail" in t and "set -euo" not in t, "every check must run and report"
    # the alert check is a FAIL by default, a WARN only under the explicit override
    i_warn = t.find("VIVEK_ACCEPT_NO_ALERT_CHANNEL:-0")
    assert i_warn > 0 and "warn \"NO ALERT CHANNEL DELIVERS" in t and "fail \"no alert channel delivered" in t


# --------------------------------------------------------------------------
# 9. update.sh and gc.sh, executed against throw-away repos
# --------------------------------------------------------------------------
VPS = {"GIT_AUTHOR_NAME": config.VPS_GIT_AUTHOR_NAME,
       "GIT_AUTHOR_EMAIL": config.VPS_GIT_AUTHOR_EMAIL_DEFAULT,
       "GIT_COMMITTER_NAME": config.VPS_GIT_AUTHOR_NAME,
       "GIT_COMMITTER_EMAIL": config.VPS_GIT_AUTHOR_EMAIL_DEFAULT}
HUMAN = {"GIT_AUTHOR_NAME": "Vivek", "GIT_AUTHOR_EMAIL": "vivek@example.com",
         "GIT_COMMITTER_NAME": "Vivek", "GIT_COMMITTER_EMAIL": "vivek@example.com"}


def _git(cwd, *args, ident=VPS):
    env = dict(os.environ, **ident)
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


class Box:
    """A bare origin, the working checkout, the publish clone, a state dir, a
    fake venv (pip logs, python = the real interpreter) and a fake sudo."""

    def __init__(self, tmp: pathlib.Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.seed = tmp / "seed"
        self.app = tmp / "app"
        self.publish = tmp / "publish"
        self.state = tmp / "state"
        self.venv = tmp / "venv"
        self.fakebin = tmp / "fakebin"
        for d in (self.seed, self.state / "locks", self.venv / "bin", self.fakebin):
            d.mkdir(parents=True)
        _git(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        _git(tmp, "init", "-q", "-b", "main", str(self.seed))
        (self.seed / "scanner").mkdir()
        (self.seed / "scanner" / "vivek.py").write_text("VERSION = 1\n")
        (self.seed / "journal").mkdir()
        (self.seed / "journal" / "vivek_bot_book.asx.json").write_text('{"open": []}\n')
        (self.seed / "public" / "data").mkdir(parents=True)
        (self.seed / "public" / "data" / "asx_vivek.json").write_text('{"v": 1}\n')
        (self.seed / "functions" / "api").mkdir(parents=True)
        (self.seed / "functions" / "api" / "scan.js").write_text("// 1\n")
        (self.seed / "deploy" / "systemd").mkdir(parents=True)
        (self.seed / "deploy" / "systemd" / "x.service").write_text("[Unit]\n")
        (self.seed / "requirements.txt").write_text("requests==2.0.0\n")
        _git(self.seed, "add", "-A")
        _git(self.seed, "commit", "-q", "-m", "seed")
        _git(self.seed, "remote", "add", "origin", str(self.origin))
        _git(self.seed, "push", "-q", "origin", "main")
        _git(tmp, "clone", "-q", str(self.origin), str(self.app))
        _git(tmp, "clone", "-q", str(self.origin), str(self.publish))
        (self.venv / "bin" / "python").symlink_to(sys.executable)
        pip = self.venv / "bin" / "pip"
        pip.write_text('#!/bin/sh\necho "pip $*" >> "$(dirname "$0")/../pip.log"\nexit 0\n')
        pip.chmod(0o755)
        sudo = self.fakebin / "sudo"
        sudo.write_text('#!/bin/sh\necho "$*" >> "$(dirname "$0")/sudo.log"\nexit 0\n')
        sudo.chmod(0o755)

    def env(self):
        return dict(os.environ, VIVEK_HOME=str(self.app), VIVEK_PUBLISH=str(self.publish),
                    VIVEK_STATE_DIR=str(self.state), VIVEK_VENV=str(self.venv),
                    VIVEK_RUNS_LEDGER=str(self.state / "runs.json"),
                    PATH=f"{self.fakebin}:{os.environ.get('PATH', '')}", PYTHONPATH="", **VPS)

    def upstream(self, path: str, content: str, msg: str, ident=VPS):
        """Commit a change in the seed clone and push it, as `ident`."""
        _git(self.seed, "pull", "-q", "--rebase", "origin", "main", ident=ident)
        p = self.seed / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _git(self.seed, "add", "-A", ident=ident)
        _git(self.seed, "commit", "-q", "-m", msg, ident=ident)
        _git(self.seed, "push", "-q", "origin", "main", ident=ident)
        return _git(self.seed, "rev-parse", "HEAD")

    def update(self):
        return subprocess.run([str(BIN / "update.sh")], env=self.env(), capture_output=True, text=True)

    def ledger(self):
        return json.loads((self.state / "runs.json").read_text())


def test_update_sh_writes_an_ok_row_when_already_current(tmp_path):
    box = Box(tmp_path)
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    row = box.ledger()["update"]
    assert row["last_status"] == "ok" and row["last_exit"] == 0 and row["host"] == "vps"
    assert row["last_success_at"] and row["consecutive_failures"] == 0
    assert "up to date" in row["last_line"]


def test_update_sh_syncs_code_and_leaves_data_paths_to_the_working_tree(tmp_path):
    box = Box(tmp_path)
    (box.state / "publish_head").write_text(_git(box.app, "rev-parse", "HEAD") + "\n")
    # the box's own working file is newer than anything upstream
    (box.app / "journal" / "vivek_bot_book.asx.json").write_text('{"open": ["LOCAL"]}\n')
    box.upstream("scanner/vivek.py", "VERSION = 2\n", "code change")
    box.upstream("journal/vivek_bot_book.asx.json", '{"open": ["PUBLISHED"]}\n', "data: scan (vps)")
    sha = box.upstream("scanner/gone.py", "", "add then delete")
    box.upstream("scanner/keep.py", "K = 1\n", "another")
    # delete gone.py upstream
    _git(box.seed, "rm", "-q", "scanner/gone.py")
    _git(box.seed, "commit", "-q", "-m", "delete")
    _git(box.seed, "push", "-q", "origin", "main")
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    assert (box.app / "scanner" / "vivek.py").read_text() == "VERSION = 2\n"
    assert (box.app / "scanner" / "keep.py").exists() and not (box.app / "scanner" / "gone.py").exists()
    assert (box.app / "journal" / "vivek_bot_book.asx.json").read_text() == '{"open": ["LOCAL"]}\n', \
        "a data path must never be checked out over the working file"
    assert _git(box.app, "rev-parse", "HEAD") == _git(box.seed, "rev-parse", "HEAD")
    assert not (box.state / "HALT").exists()
    assert box.ledger()["update"]["last_status"] == "ok"
    assert sha  # used above


def test_update_sh_halts_on_a_foreign_data_commit_and_syncs_nothing(tmp_path):
    box = Box(tmp_path)
    (box.state / "publish_head").write_text(_git(box.app, "rev-parse", "HEAD") + "\n")
    box.upstream("scanner/vivek.py", "VERSION = 3\n", "code")
    sha = box.upstream("journal/vivek_bot_book.asx.json", '{"open": ["HAND"]}\n', "hand close", ident=HUMAN)
    r = box.update()
    assert r.returncode == 4, r.stderr + r.stdout
    halt = json.loads((box.state / "HALT").read_text())
    assert sha in halt["shas"] and "journal/vivek_bot_book.asx.json" in halt["paths"]
    assert any("Vivek" in a for a in halt["authors"])
    assert (box.app / "scanner" / "vivek.py").read_text() == "VERSION = 1\n", "HALT must sync nothing"
    assert _git(box.app, "rev-parse", "HEAD") != _git(box.seed, "rev-parse", "HEAD")
    row = box.ledger()["update"]
    assert row["last_status"] == "halted" and row["last_exit"] == 4 and row["consecutive_failures"] == 1
    assert "CRITICAL" in r.stdout


def test_update_sh_ignores_foreign_commits_that_touch_only_code(tmp_path):
    box = Box(tmp_path)
    (box.state / "publish_head").write_text(_git(box.app, "rev-parse", "HEAD") + "\n")
    box.upstream("scanner/vivek.py", "VERSION = 9\n", "owner code push", ident=HUMAN)
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    assert (box.app / "scanner" / "vivek.py").read_text() == "VERSION = 9\n"
    assert not (box.state / "HALT").exists()


def test_update_sh_skips_when_a_job_holds_the_repo_lock_and_alerts_after_an_hour(tmp_path):
    box = Box(tmp_path)
    lock = box.state / "locks" / "repo.lock"
    lock.touch()
    holder = subprocess.Popen(["bash", "-c", f'exec 9>"{lock}"; flock -s 9; sleep 30'])
    try:
        import time
        time.sleep(0.5)
        for n in range(1, 12):
            r = box.update()
            assert r.returncode == 0, (n, r.stderr + r.stdout)
            assert "skipped busy" in r.stdout
        row = box.ledger()["update"]
        assert row["last_status"] == "skipped" and row["last_skip_at"]
        assert (box.state / "update_skips").read_text().strip() == "11"
        r = box.update()  # the 12th consecutive skip = 1 h at */5 -> exit 1 so OnFailure alerts
        assert r.returncode == 1 and "consecutive busy skips" in r.stdout
    finally:
        holder.kill()
        holder.wait()
    # once the lock is free the counter resets
    r = box.update()
    assert r.returncode == 0 and not (box.state / "update_skips").exists()


def test_update_sh_runs_pip_restarts_the_api_and_flags_stale_units_on_the_right_paths(tmp_path):
    box = Box(tmp_path)
    box.upstream("requirements.txt", "requests==2.1.0\n", "bump")
    box.upstream("functions/api/scan.js", "// 2\n", "function")
    box.upstream("deploy/systemd/x.service", "[Unit]\n# changed\n", "unit")
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    assert "install -q -r requirements.txt" in (box.venv / "pip.log").read_text()
    assert (box.fakebin / "sudo.log").read_text().strip() == "-n systemctl restart vivek5-api.service"
    assert (box.state / "UNITS_STALE").exists()
    assert "install.sh --units" in r.stdout
    row = box.ledger()["update"]
    assert row["last_status"] == "ok" and "pip-installed" in row["last_line"] and "units-stale" in row["last_line"]
    # a plain code change does none of that
    (box.venv / "pip.log").unlink()
    (box.fakebin / "sudo.log").unlink()
    (box.state / "UNITS_STALE").unlink()
    box.upstream("scanner/vivek.py", "VERSION = 4\n", "code")
    r = box.update()
    assert r.returncode == 0
    assert not (box.venv / "pip.log").exists() and not (box.fakebin / "sudo.log").exists()
    assert not (box.state / "UNITS_STALE").exists()


def test_update_sh_never_touches_etc_or_runs_install(tmp_path):
    t = (BIN / "update.sh").read_text(encoding="utf-8")
    live = "\n".join(l for l in t.splitlines() if not l.strip().startswith("#"))
    assert "/etc/" not in live and "install.sh" not in live.replace("install.sh --units", "")
    assert "reset -q --mixed" in live and "reset --hard" not in live
    assert "flock -x -n 9" in live and 'locks/repo.lock' in live
    assert "sudo -n systemctl restart vivek5-api.service" in live


def test_gc_sh_collects_both_clones_under_the_exclusive_lock(tmp_path):
    box = Box(tmp_path)
    r = subprocess.run([str(BIN / "gc.sh")], env=box.env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    assert r.stdout.count("gc: ") >= 2
    row = box.ledger()["gc"]
    assert row["last_status"] == "ok" and row["host"] == "vps"
    t = (BIN / "gc.sh").read_text(encoding="utf-8")
    assert "pack.threads=1" in t and "gc --prune=2.weeks.ago" in t and "flock -x -n 9" in t
    # busy -> skipped, exit 0
    lock = box.state / "locks" / "repo.lock"
    holder = subprocess.Popen(["bash", "-c", f'exec 9>"{lock}"; flock -s 9; sleep 30'])
    try:
        import time
        time.sleep(0.5)
        r = subprocess.run([str(BIN / "gc.sh")], env=box.env(), capture_output=True, text=True)
        assert r.returncode == 0 and "skipping" in r.stdout
        assert box.ledger()["gc"]["last_status"] == "skipped"
    finally:
        holder.kill()
        holder.wait()


def test_journald_dropin_bounds_the_journal():
    t = (DEPLOY / "journald.conf").read_text(encoding="utf-8")
    assert "[Journal]" in t and "SystemMaxUse=2G" in t and "MaxRetentionSec=45day" in t

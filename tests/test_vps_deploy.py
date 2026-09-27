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
against throw-away git repos under tmp_path with a fake `sudo`/`pip`/
`systemctl` on PATH; `ports.sh` against a fake `ss`/`ps`; nothing here
touches journal/, public/data or the network.

COEXISTENCE (M6, 2026-09-27): the owner's box also runs his two trading bots
("ICT LIVE" trades REAL money). The C1-C12 pins below are the static proof
that the kit changes no machine-wide state they depend on: no timezone
change, our own Node and Caddy, no port taken from another process, no
firewall, no swap unless asked, nothing started at install, heavy jobs yield,
no systemctl/kill on anything that is not vivek5-*, no journald drop-in, and
a printed plan + typed `yes` before install.sh changes anything.
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
           "rollback.sh", "job.sh", "gc.sh", "ports.sh"]

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
    "vivek5-phasemap.timer": (["*-*-* 08:30 UTC"], "phasemap.yml reason=cron"),
    "vivek5-confluence.timer": (["*-*-* 08:45 UTC"], "confluence.yml reason=cron"),
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
# M6 C8: the units that must yield to the owner's live trading bot.
C8_HEAVY = {"scan.yml", "crypto_bot.yml", "phasemap.yml", "lens_backtest.yml", "vivek_backtest.yml",
            "alert_returns.yml", "momentum.yml"}
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
    "ProtectHome=yes", "PrivateTmp=yes", "NoNewPrivileges=yes", "ProtectProc=invisible",
}
# The ONE root unit (2026-09-27 host review): it replaced a sudoers grant that
# update.sh could never have used (NoNewPrivileges=yes forbids setuid sudo).
ROOT_UNIT = "vivek5-api-restart.service"
ROOT_UNIT_EXEC = "/usr/bin/systemctl --no-ask-password try-restart vivek5-api.service"
API_RESTART_FLAG = "/opt/vivek5/state/api-restart"


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


def test_timers_of_reason_bearing_jobs_pass_the_schedule_branch_explicitly():
    """Parity minor: phasemap/confluence default to `manual` for an operator
    run (workflow_dispatch parity); the TIMER must say reason=cron."""
    from scanner.vps import jobs as J
    for timer, (_, args) in TABLE.items():
        job = J.JOBS[args.split()[0]]
        if "reason" in job.args and not job.args["reason"].get("default_by_slot"):
            assert "reason=cron" in args.split(), (timer, args)
            assert J.is_scheduled(job, J.parse_args(job, J.parse_kv(args.split()[1:]))), timer


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
    every DST regime, always on a weekday IN THE MARKET'S ZONE. (NASDAQ's
    second scan is 11:07 in both regimes; GitHub's EDT 11:37 is normalised --
    recorded in workflows.json's scan.yml dropped list.)"""
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


def test_the_nasdaq_edt_normalisation_is_recorded_in_the_transcription():
    from scanner.vps import jobs as J
    dropped = " ".join(" ".join(d) for d in J.JOBS["scan.yml"].dropped)
    assert "11:37" in dropped and "37 14,15" in dropped


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
    for d in ("opt/vivek5/venv/bin", "opt/vivek5/app/deploy/bin", "opt/vivek5/node/bin",
              "opt/vivek5/caddy", "etc/vivek5"):
        (root / d).mkdir(parents=True)
    for stub in ("opt/vivek5/venv/bin/python", "opt/vivek5/node/bin/node", "opt/vivek5/caddy/caddy"):
        (root / stub).write_text("#!/bin/sh\nexit 0\n")
        (root / stub).chmod(0o755)
    for s in SCRIPTS:
        shutil.copy(BIN / s, root / "opt/vivek5/app/deploy/bin" / s)
    shutil.copy(ENV_DIR / "jobs.env.example", root / "etc/vivek5/jobs.env")
    shutil.copy(ENV_DIR / "api.env.example", root / "etc/vivek5/api.env")
    (root / "etc/vivek5/caddy.env").write_text("VIVEK_DOMAIN=example.com\n")
    units = tmp_path / "units"
    units.mkdir()
    for f in UNITS.glob("vivek5-*"):
        text = f.read_text(encoding="utf-8")
        text = text.replace("/opt/vivek5", str(root / "opt/vivek5")).replace("/etc/vivek5", str(root / "etc/vivek5"))
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


def test_every_script_in_deploy_bin_is_in_the_gated_list():
    assert sorted(p.name for p in BIN.glob("*.sh")) == sorted(SCRIPTS)


def test_no_set_x_anywhere_in_deploy_bin():
    bad = re.compile(r"(set\s+-[a-zA-Z]*x|set\s+-o\s+xtrace|bash\s+-x|^#!.*\s-x)", re.M)
    for s in SCRIPTS:
        raw = (BIN / s).read_text(encoding="utf-8")
        text = raw.splitlines()[0] + "\n" + _live(raw)  # shebang + executable lines
        assert not bad.search(text), f"{s} traces (a trace prints every secret in the environment)"
        assert "printenv" not in text and not re.search(r"^\s*env\s*$", text, re.M), s


@pytest.mark.parametrize("script", ["install.sh", "preflight.sh", "cutover.sh", "rollback.sh", "ports.sh"])
def test_operator_scripts_answer_help_without_root(script):
    r = _run([str(BIN / script), "--help"])
    assert r.returncode == 0, r.stderr
    assert "deploy/bin/" in r.stdout or "/usr/local/lib/vivek5/bin/" in r.stdout


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
def test_no_root_units_but_the_api_restart_hook_and_the_two_daemons_run_as_their_own_users():
    for svc in _services():
        k = _keys(_unit(svc))
        user = k.get("User", [None])[0]
        if svc == "vivek5-api.service":
            assert user == "vivek5-api", svc
        elif svc == "vivek5-caddy.service":
            assert user == "vivek5-caddy" and k["Group"] == ["vivek5-caddy"], svc
        elif svc == ROOT_UNIT:
            assert user is None, "root by design -- test_the_api_restart_hook_... pins its ONE command"
        else:
            assert user == "vivek5", f"{svc} runs as {user!r}"


def test_no_dash_environmentfile_anywhere():
    for f in UNITS.glob("vivek5-*"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("EnvironmentFile="):
                assert line.startswith("EnvironmentFile=/etc/vivek5/"), (f.name, line)
                assert not line.startswith("EnvironmentFile=-"), (f.name, line)


def test_api_unit_loads_api_env_only_runs_our_node_and_is_hardened():
    text = _unit("vivek5-api.service")
    k = _keys(text)
    assert k["EnvironmentFile"] == ["/etc/vivek5/api.env"]
    assert k["ExecStart"] == ["/opt/vivek5/node/bin/node /opt/vivek5/app/deploy/api/server.mjs"], \
        "the VENDORED node (M6 C2), never the system's"
    assert k["Restart"] == ["on-failure"] and k["RestartSec"] == ["5"]
    assert k["MemoryMax"] == ["512M"], "the api keeps its hard cap (M6 C8)"
    assert k["StartLimitIntervalSec"] == ["0"]
    assert k["OnFailure"] == ["vivek5-failed@%n.service"]
    assert k["SupplementaryGroups"] == ["vivek5-spool"]
    assert k["UMask"] == ["0007"], "spool files 0660 for the runner (security review BLOCKER)"
    assert k["ReadWritePaths"] == ["/opt/vivek5/state/spool -/opt/vivek5/state/kv.json"], \
        "only the two paths the adapter writes; a missing kv.json must not block the unit's start"
    assert "state/kv.json is 0660 vivek5-api:vivek5-spool" in (BIN / "preflight.sh").read_text(encoding="utf-8")
    for opt in ("ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes", "NoNewPrivileges=yes",
                "ProtectProc=invisible", "ProcSubset=pid", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
                "LockPersonality=yes", "ProtectKernelTunables=yes", "ProtectKernelModules=yes",
                "ProtectKernelLogs=yes", "ProtectControlGroups=yes", "RestrictNamespaces=yes"):
        assert opt in text, opt
    # nobody else loads the adapter's env, and the adapter never loads jobs.env
    for svc in _services():
        if svc == "vivek5-api.service":
            continue
        if svc == ROOT_UNIT:
            assert "EnvironmentFile" not in _keys(_unit(svc)), "the root hook reads no env file"
            continue
        want = ["/etc/vivek5/caddy.env"] if svc == "vivek5-caddy.service" else ["/etc/vivek5/jobs.env"]
        assert _keys(_unit(svc))["EnvironmentFile"] == want, svc


def test_every_job_service_has_the_failure_hook_hardening_and_no_log_rate_limit():
    for svc in _services():
        text = _unit(svc)
        k = _keys(text)
        if svc == "vivek5-failed@.service":
            assert "OnFailure" not in k, "the hook must not fire itself"
        else:
            assert k["OnFailure"] == ["vivek5-failed@%n.service"], svc
        if svc in ("vivek5-api.service", "vivek5-caddy.service", ROOT_UNIT):
            continue
        assert k["Type"] == ["oneshot"], svc
        assert k["KillMode"] == ["mixed"], svc
        assert k["WorkingDirectory"] == ["/opt/vivek5/app"], svc
        if svc != "vivek5-failed@.service":
            assert k["LogRateLimitIntervalSec"] == ["0"], svc
        assert "ProtectProc=invisible" in text, svc
        # EVERY vivek5 job unit, vivek5-update.service included (its old
        # ProtectSystem=full / no-NoNewPrivileges exception existed only for a
        # sudo call NoNewPrivileges would have refused anyway)
        for opt in HARDENING:
            assert opt in text, (svc, opt)
        assert k["NoNewPrivileges"] == ["yes"] and k["ProtectSystem"] == ["strict"], svc


def test_timeoutstartsec_is_the_workflow_timeout_plus_the_lock_wait():
    """The Actions timeout bounded the RUNNING job (a queued run waited for
    free); on the box the wait happens inside the unit, so the hang detector
    is timeout-minutes + the family's lock wait (config.VPS_LOCK_WAIT_S)."""
    for timer, (_, args) in TABLE.items():
        job = args.split()[0]
        svc = _service_for(timer)
        k = _keys(_unit(_template(svc)))
        want = (_workflow_timeout(job) + config.VPS_LOCK_WAIT_S[FAMILY[job]] // 60
                + config.VPS_UNIT_TIMEOUT_MARGIN_MIN)
        assert k["TimeoutStartSec"] == [f"{want}min"], (svc, k["TimeoutStartSec"], want)
    assert config.VPS_UNIT_TIMEOUT_MARGIN_MIN >= 10, "the margin must cover a publish (fetch+push+rebuild)"


def test_heavy_jobs_yield_to_the_live_trading_bot():
    """M6 C8: scan, crypto-bot, phasemap, the backtests, alert-returns and
    momentum (and the spool drainer that runs dispatched scans) yield CPU and
    I/O and are throttled -- never OOM-killed -- above a soft 1G; the rest
    carry none of it; the api keeps MemoryMax=512M."""
    heavy_units = set()
    for timer, (_, args) in TABLE.items():
        if args.split()[0] in C8_HEAVY:
            heavy_units.add(_template(_service_for(timer)))
    heavy_units.add("vivek5-spool.service")
    for svc in _services():
        text = _unit(svc)
        k = _keys(text)
        if svc in heavy_units:
            assert k["Nice"] == ["10"] and k["CPUWeight"] == ["20"], svc
            assert k["IOSchedulingPriority"] == ["7"] and k["MemoryHigh"] == ["1G"], svc
            job = next((a.split()[0] for t, (_, a) in TABLE.items() if _template(_service_for(t)) == svc), None)
            want_io = "idle" if job in IO_IDLE else "best-effort"
            assert k["IOSchedulingClass"] == [want_io], svc
            assert "MemoryMax" not in k, f"{svc}: a hard cap would OOM-kill a scan mid-publish"
            assert "live trading bot" in text.lower() or "LIVE trading bot" in text, f"{svc}: rationale comment"
        elif svc not in ("vivek5-gc.service",):
            assert "Nice" not in k and "CPUWeight" not in k, svc
        if svc != "vivek5-api.service":
            assert "MemoryMax" not in k, svc
    assert _keys(_unit("vivek5-api.service"))["MemoryMax"] == ["512M"]
    assert heavy_units >= {"vivek5-scan@.service", "vivek5-crypto-bot.service", "vivek5-phasemap.service",
                           "vivek5-lens-backtest.service", "vivek5-vivek-backtest.service",
                           "vivek5-alert-returns.service", "vivek5-momentum.service"}


def test_timers_are_persistent_accurate_and_market_timers_are_not_jittered():
    for timer in _timers():
        k = _keys(_unit(timer))
        assert k["Persistent"] == ["true"], timer
        assert k["AccuracySec"] == ["1s"], timer
        assert "WantedBy=timers.target" in _unit(timer), timer
        if any(s in timer for s in ("scan", "crypto", "kill", "backstop", "update", "morning")):
            assert k["RandomizedDelaySec"] == ["0"], timer


def test_failed_hook_runs_notify_failure_and_alone_reads_the_journal():
    k = _keys(_unit("vivek5-failed@.service"))
    assert k["ExecStart"] == ["/opt/vivek5/venv/bin/python -m scanner.vps notify-failure %i"]
    assert k["User"] == ["vivek5"]
    assert k["SupplementaryGroups"] == ["systemd-journal"], \
        "journal access for the failure hook only (security review), not vivek5 globally"
    assert "usermod -aG systemd-journal" not in _live((BIN / "install.sh").read_text(encoding="utf-8"))


def test_the_caddy_unit_is_ours_not_the_machines():
    """M6 C3: our pinned binary, our user, our config and data dirs; one
    capability; never the distro caddy.service."""
    text = _unit("vivek5-caddy.service")
    k = _keys(text)
    assert k["ExecStart"] == ["/opt/vivek5/caddy/caddy run --adapter caddyfile --config /etc/vivek5/Caddyfile"]
    assert k["ExecReload"] == ["/opt/vivek5/caddy/caddy reload --adapter caddyfile --config /etc/vivek5/Caddyfile --force"]
    assert "--environ" not in _live(text), "--environ prints the basic-auth hash into the journal"
    assert k["User"] == ["vivek5-caddy"] and k["AmbientCapabilities"] == ["CAP_NET_BIND_SERVICE"]
    assert k["CapabilityBoundingSet"] == ["CAP_NET_BIND_SERVICE"]
    assert k["EnvironmentFile"] == ["/etc/vivek5/caddy.env"]
    env = k["Environment"]
    assert "XDG_DATA_HOME=/opt/vivek5/caddy/data" in env and "XDG_CONFIG_HOME=/opt/vivek5/caddy/config" in env
    assert "TZ=UTC" in env
    assert k["ReadWritePaths"] == ["/opt/vivek5/caddy/data /opt/vivek5/caddy/config"]
    assert k["OnFailure"] == ["vivek5-failed@%n.service"]


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
# Variables the scripts read from the CALLING SHELL (or a hidden prompt) only, by design.
SHELL_ONLY = {"GH_ADMIN_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CF_PAGES_PROJECT",
              "VIVEK_ACCEPT_NO_ALERT_CHANNEL", "VIVEK_REPO_SSH"}
# Written by install.sh into /etc/vivek5/caddy.env for the Caddyfile placeholders.
CADDY_ENV = {"VIVEK_DOMAIN", "VIVEK_API_BASIC_USER", "VIVEK_API_BASIC_HASH"}
# install.sh's pinned-runtime constants (M6 C2/C3).
SCRIPT_CONSTANTS = {"NODE_VERSION", "NODE_SHA256", "CADDY_VERSION", "CADDY_SHA512", "GITHUB_FPS"}
# gc.sh's lock waits / publish-clone bound: design defaults in the script, the
# env names exist only so the tests reach the busy paths without waiting minutes.
SCRIPT_TUNABLES = {"VIVEK_GC_REPO_WAIT_S", "VIVEK_GC_PUBLISH_WAIT_S", "VIVEK_GC_PUBLISH_BOUND_S"}
# Environment the caddy unit sets itself.
UNIT_ENV = {"TZ", "XDG_DATA_HOME", "XDG_CONFIG_HOME"}
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
    unknown = (referenced - jobs - api - SHELL_ONLY - CADDY_ENV - SCRIPT_CONSTANTS - SCRIPT_TUNABLES
               - UNIT_ENV - BASH_BUILTIN - OS_RELEASE)
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
                     r"-o UserKnownHostsFile=/etc/vivek5/known_hosts -o StrictHostKeyChecking=yes "
                     r"-o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=4\"$",
                     text, re.M), "a stalled fetch/push must fail in ~1 min, not hang holding the book lock"
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


def test_install_writes_a_host_scoped_vps_identity():
    """Book minor: an identity-only second-writer rule cannot see a second box
    installed from the same template; install.sh scopes the NAME per host."""
    live = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    assert 's|^GIT_AUTHOR_NAME=.*|GIT_AUTHOR_NAME=vivek5-vps@$host|' in live
    assert 's|^GIT_COMMITTER_NAME=.*|GIT_COMMITTER_NAME=vivek5-vps@$host|' in live
    assert "hostname -s" in live


def test_no_discord_webhook_url_literal_anywhere_under_deploy():
    """The removed alert webhook's name must not reappear in anything the box
    RUNS or LOADS (units, scripts, env templates, Caddyfiles).
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
    assert re.search(r"request_body \{\s*max_size 64KB\s*\}", live), "the edge caps request bodies"


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
    assert re.search(r"handle /api/\* \{\s*request_body \{\s*max_size 64KB\s*\}\s*reverse_proxy 127\.0\.0\.1:8787", live)
    assert "handle_errors 404" in live and "/404.html" in live
    assert "delete key" in live and "request>uri query" in live
    assert ":80" not in live and "tls internal" not in live


def test_the_caddyfiles_name_our_paths_never_the_system_caddys():
    for name in ("Caddyfile.phase1", "Caddyfile.phase2"):
        t = _caddy(name)
        assert "/etc/vivek5/Caddyfile" in t and "/etc/vivek5/caddy.env" in t, name
        assert "/etc/caddy" not in t and "caddy.service drop-in" not in t, name


def _caddy_version_ok() -> bool:
    if not CADDY_BIN:
        return False
    r = _run([CADDY_BIN, "version"])
    m = re.search(r"v?(\d+)\.(\d+)", r.stdout)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (2, 8)


RAW_HASH = "$2a$14$pRlTLZVol27g90asf6plYu6ePGgGWAd.xabL42NxNBhSdTs98N2WO"


@pytest.mark.skipif(not _caddy_version_ok(),
                    reason="caddy >= 2.8 not available (Ubuntu's apt 2.6.2 lacks basic_auth; set CADDY_BIN)")
@pytest.mark.parametrize("phase", ["phase1", "phase2"])
def test_caddyfiles_validate(phase):
    env = dict(os.environ, VIVEK_DOMAIN="example.com", VIVEK_API_BASIC_USER="vivek", VIVEK_API_BASIC_HASH=RAW_HASH)
    r = _run([CADDY_BIN, "validate", "--adapter", "caddyfile", "--config", str(CADDY_DIR / f"Caddyfile.{phase}")], env=env)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.skipif(not _caddy_version_ok(), reason="caddy >= 2.8 not available (set CADDY_BIN)")
def test_a_raw_bcrypt_hash_validates_through_envfile_and_is_mangled_by_bash(tmp_path):
    """Security review S4: `. caddy.env` in bash expands `$2a$14$...` (and
    dies under `set -u`); caddy's own --envfile / systemd's EnvironmentFile
    read it raw. The kit validates with --envfile and never sources it."""
    envf = tmp_path / "caddy.env"
    envf.write_text(f"# comment\nVIVEK_DOMAIN=example.com\nVIVEK_API_BASIC_USER=vivek\nVIVEK_API_BASIC_HASH={RAW_HASH}\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("VIVEK_")}
    r = _run([CADDY_BIN, "validate", "--adapter", "caddyfile", "--config", str(CADDY_DIR / "Caddyfile.phase2"),
              "--envfile", str(envf)], env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    sourced = _run(["bash", "-c", f'set -a; . "{envf}"; set +a; printf %s "$VIVEK_API_BASIC_HASH"'])
    assert sourced.stdout != RAW_HASH, "control: bash really does mangle it"


def test_no_script_sources_an_env_file_and_caddy_validates_with_envfile():
    for s in SCRIPTS:
        live = _live((BIN / s).read_text(encoding="utf-8"))
        assert not re.search(r'(^\s*|[;&|{(]\s*|\b(?:then|do|else)\s+)(\.|source)\s+"?(\$etc|/etc/vivek5|/etc/caddy)',
                             live, re.M), f"{s} sources an env file"
        assert "set -a" not in live, s
    for s in ("install.sh", "preflight.sh"):
        live = _live((BIN / s).read_text(encoding="utf-8"))
        assert re.search(r'validate --adapter caddyfile --config "\$etc/Caddyfile" --envfile "\$etc/caddy.env"', live), s


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


def test_cutover_follows_section_7_in_order():
    t = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    order = ["preflight.sh", "ports.sh\" --check", "enable --now vivek5-caddy.service vivek5-api.service", "/api/vps",
             "DISPATCH_URL", "cf-set-var", "cf-delete-var", "GH_DISPATCH_TOKEN",
             "/disable", "disabled_manually", "VPS_ACTIVE", "status=$s", "1800",
             "reset -q --hard origin/main", "publish_head", "vivek5-api-restart.path", 'v5ctl enable --now "$t"',
             "NextElapseUSecRealtime", "is-enabled", "auto_rollback", "list-timers",
             "DELETE the GH_ADMIN_TOKEN"]
    pos = -1
    for needle in order:
        nxt = t.find(needle, pos + 1)
        assert nxt > pos, f"{needle!r} missing or out of order"
        pos = nxt
    assert "for s in queued in_progress pending waiting requested" in t, "every pre-finish run status is drained"
    assert "polling once more in 60 s" in t


@pytest.mark.parametrize("script", ["cutover.sh", "rollback.sh"])
def test_admin_tokens_never_ride_a_command_line(script):
    """Security review: /proc/*/cmdline is world-readable; the tokens reach
    curl through a 0600 -K config file and request bodies through files."""
    t = (BIN / script).read_text(encoding="utf-8")
    live = _live(t)
    assert "read -rs" in live and "trap 'unset GH_ADMIN_TOKEN" in live
    assert "-w '%{http_code}'" in live and "curl -v" not in live
    assert not re.search(r'-H\s+"Authorization: Bearer \$', live), "a Bearer header on curl's argv"
    assert '-K "$gh_cfg"' in live and "printf 'header = \"Authorization: Bearer %s\"\\n' \"$GH_ADMIN_TOKEN\" > \"$gh_cfg\"" in live
    assert 'chmod 0600 "$gh_body" "$gh_cfg"' in live
    assert "GH_ADMIN_TOKEN=" not in t, "no documented `GH_ADMIN_TOKEN=... sudo -E` form (shell history)"
    assert "sudo -E" not in t
    if script == "cutover.sh":
        assert '--data-binary @"$cf_body"' in live and '-K "$cf_cfg"' in live
        assert 'Bearer $CLOUDFLARE_API_TOKEN" -H' not in live
        assert 'GH_ADMIN_TOKEN\\s*=' in live, "refuses an env-file assignment"
        assert "actions/variables" in live and '"value":\\"1\\"' not in live
        assert "pages/projects" in live and "CLOUDFLARE_API_TOKEN" in live and "CF_PAGES_PROJECT" in live


def test_rollback_stops_the_api_first_then_reverses_cutover_and_lists_orphans():
    t = _live((BIN / "rollback.sh").read_text(encoding="utf-8"))
    i_api = t.find("v5ctl disable --now vivek5-api.service")
    i_path = t.find("v5ctl disable --now vivek5-spool.path")
    i_timers = t.find('v5ctl disable --now "$t"')
    i_caddy = t.find("v5ctl disable --now vivek5-caddy.service")
    assert 0 < i_api < i_path < i_timers < i_caddy, "API first: no new 202 while the writer stops"
    assert i_caddy < t.find("/enable") < t.find("VPS_ACTIVE 0") < t.find("GH_DISPATCH_TOKEN")
    assert 'state=="active"' in t.replace(" ", "") or '"$state" = "active"' in t
    assert "ACCEPTED BUT NOT EXECUTED" in t and ".json\\.(halted|retry|stuck)" in t


def test_install_sh_does_what_section_1_says_and_nothing_machine_wide():
    t = (BIN / "install.sh").read_text(encoding="utf-8")
    live = _live(t)
    for needle in ["python3.12-venv", "python3-pip", "rsync", "ca-certificates", "xz-utils",
                   "groupadd --system vivek5-spool", "useradd --system", "usermod -aG vivek5-spool vivek5-api",
                   "usermod -aG vivek5-spool vivek5\n", "install -d -m 3770 -o vivek5 -g vivek5-spool",
                   "--filter=blob:none", "config gc.auto 0", "python3 -m venv", "pip\" install -q -r",
                   "compileall", "install -m 0644 -o root -g root \"$f\" /etc/systemd/system/",
                   "systemctl daemon-reload", "openssl rand -hex 32", "ssh-keygen -q -t ed25519",
                   "ssh-keyscan", "ssh-keygen -lf", "githubs-ssh-key-fingerprints",
                   "remove_stale_sudoers", "Caddyfile.phase$phase", "--units",
                   "/usr/local/lib/vivek5", "openssl", "cd /\n"]:
        assert needle in live, needle
    assert "ln -s" not in live, "units are copied, never symlinked"
    assert "safe.directory" not in live, "no system-wide safe.directory (root would run a jobs-user fsmonitor)"
    assert 'install -d -m 0755 -o vivek5 -g vivek5 "$app" "$publish" "$venv"' in live, "vivek5 must own the venv dir"
    # NO sudo grant any more (2026-09-27 host review): nothing writes sudoers
    assert "NOPASSWD" not in t and "visudo" not in live and "install -m 0440" not in live
    assert not re.search(r">\s*\"?/etc/sudoers", live)
    # env files only if absent, with the right owners
    assert 'if [ ! -e "$etc/jobs.env" ]' in live and 'if [ ! -e "$etc/api.env" ]' in live
    assert 'if [ ! -e "$etc/caddy.env" ]' in live and "chown root:vivek5-caddy" in live
    assert "curl | bash" not in t.replace("never `curl | bash`", "")


# ---- M6 coexistence pins (the box also runs the owner's LIVE trading bot) --
def _code_only(text: str) -> str:
    """Live lines minus heredoc BODIES (plan text, sudoers file, python) --
    what bash executes as commands in this file."""
    out, term = [], None
    for line in _live(text).splitlines():
        if term is not None:
            if line.strip() == term:
                term = None
            continue
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            term = m.group(1)
    return "\n".join(out)


def _without_v5ctl(text: str) -> str:
    if "v5ctl() {" not in text:
        return text
    i = text.index("v5ctl() {")
    return text[:i] + text[text.index("\n}\n", i) + 3:]


def _all_deploy_files():
    return [p for p in DEPLOY.rglob("*") if p.is_file()]


def test_c1_the_kit_never_sets_the_timezone_and_every_unit_runs_on_utc():
    for p in _all_deploy_files():
        assert "set-timezone" not in p.read_text(encoding="utf-8", errors="replace"), p
    for svc in _services():
        assert "TZ=UTC" in _keys(_unit(svc)).get("Environment", []), svc
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert 'info "system timezone: $tz' in pf, "the zone is INFO"
    assert 'fail "box timezone' not in pf
    assert re.search(r'if \[ "\$ntp" = "yes" \]; then pass "NTP synchronized"; else fail', pf), "NTP is the FAIL"


def test_c2_node_is_vendored_pinned_and_verified_never_the_system_one():
    t = (BIN / "install.sh").read_text(encoding="utf-8")
    live = _live(t)
    top = "\n".join(t.splitlines()[:40])
    assert re.search(r"^NODE_VERSION=22\.\d+\.\d+\b", top, re.M), "one pinned Node 22 constant at the top"
    assert re.search(r"^NODE_SHA256=[0-9a-f]{64}$", top, re.M)
    assert "https://nodejs.org/dist/v${NODE_VERSION}/${tarball}" in live
    assert "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" in live and "sha256sum -c" in live
    assert 'node-v${NODE_VERSION}-linux-x64.tar.xz' in live and "node_dir=/opt/vivek5/node" in live
    for bad in ("nodesource", "apt-get install -y -q nodejs", "sources.list.d"):
        assert bad not in live, bad
    assert re.search(r"apt-get install[^\n]*\bnodejs\b", live) is None
    for p in _all_deploy_files():
        if p.suffix != ".md":
            assert "/usr/bin/node" not in p.read_text(encoding="utf-8", errors="replace"), p
    assert "/opt/vivek5/node/bin/node" in _keys(_unit("vivek5-api.service"))["ExecStart"][0]


def test_c3_caddy_is_vendored_pinned_verified_and_runs_as_its_own_unit():
    t = (BIN / "install.sh").read_text(encoding="utf-8")
    live = _live(t)
    top = "\n".join(t.splitlines()[:40])
    m = re.search(r"^CADDY_VERSION=(\d+)\.(\d+)\.\d+\b", top, re.M)
    assert m and (int(m.group(1)), int(m.group(2))) >= (2, 8)
    assert re.search(r"^CADDY_SHA512=[0-9a-f]{128}$", top, re.M)
    assert 'base="https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}"' in live
    assert 'sums="caddy_${CADDY_VERSION}_checksums.txt"' in live and "sha512sum -c" in live
    assert "caddy_${CADDY_VERSION}_linux_amd64.tar.gz" in live and "caddy_bin=$caddy_home/caddy" in live
    assert "cloudsmith" not in live and not re.search(r"apt-get install[^\n]*\bcaddy\b", live)
    for p in _all_deploy_files():
        if p.name == "DESIGN.md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "/etc/caddy" not in text, p
        for line in _code_only(text).splitlines():
            if re.search(r"(?<![-\w])caddy\.service", line):
                assert re.match(r"\s*(log|info|echo|warn|pass|fail|printf)\b", line), \
                    f"{p}: the system caddy.service may only be NAMED in a message, never acted on: {line.strip()}"


def test_c4_ports_are_only_ever_read_and_a_busy_80_or_443_stops_the_kit(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    lines = tmp_path / "ss.out"
    users = tmp_path / "users"
    (fake / "ss").write_text(f'#!/bin/sh\n[ "$1" = "-Htlnp" ] || exit 9\ncat "{lines}"\n')
    (fake / "ps").write_text(
        '#!/bin/sh\n# ps -o user=|comm= -p PID\n'
        f'pid="$4"; field="$2"\nline="$(grep "^$pid " "{users}")" || exit 1\n'
        'set -- $line\nif [ "$field" = "user=" ]; then echo "$2"; else echo "$3"; fi\n')
    for f in ("ss", "ps"):
        (fake / f).chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}")

    def run(ss_lines, user_rows):
        lines.write_text("".join(l + "\n" for l in ss_lines))
        users.write_text("".join(r + "\n" for r in user_rows))
        return _run([str(BIN / "ports.sh"), "--check"], env=env)
    bot = 'LISTEN 0 4096 127.0.0.1:9001 0.0.0.0:* users:(("ictlive",pid=77,fd=3))'
    r = run([bot], ["77 trader ictlive"])
    assert r.returncode == 0 and "ictlive" in r.stdout, "other listeners are printed, not judged"
    ours = 'LISTEN 0 4096 0.0.0.0:443 0.0.0.0:* users:(("caddy",pid=10,fd=7))'
    assert run([bot, ours], ["77 trader ictlive", "10 vivek5-caddy caddy"]).returncode == 0
    theirs = 'LISTEN 0 511 [::]:80 [::]:* users:(("nginx",pid=55,fd=6),("nginx",pid=56,fd=6))'
    r = run([bot, theirs], ["77 trader ictlive", "55 root nginx", "56 www-data nginx"])
    assert r.returncode == 1 and "'nginx' (pid 55, user root)" in r.stdout
    assert "Cloudflare Tunnel" in r.stdout and "OWN server" in r.stdout and "will NOT stop" in r.stdout
    distro = 'LISTEN 0 4096 *:443 *:* users:(("caddy",pid=30,fd=7))'
    assert run([distro], ["30 caddy caddy"]).returncode == 1, "the distro caddy is somebody else's"
    live = _live((BIN / "ports.sh").read_text(encoding="utf-8"))
    assert not re.search(r"\b(kill|pkill|killall|systemctl|fuser)\b", live), "ports.sh only ever READS"
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert '"$here/ports.sh" --check' in pf and 'fail ":80/:443 are held by another process' in pf
    co = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    assert re.search(r'"\$here/ports.sh" --check >/dev/null \|\| die', co), "cutover refuses on a busy port"
    assert co.find("ports.sh\" --check") < co.find("enable --now vivek5-caddy.service")
    assert '"$here/ports.sh" || true' in _live((BIN / "install.sh").read_text(encoding="utf-8")), "install prints them"


def test_c5_no_firewall_configuration_anywhere_and_preflight_only_reports_it():
    for s in SCRIPTS:
        live = _live((BIN / s).read_text(encoding="utf-8"))
        assert not re.search(r"\bufw\s+(allow|deny|enable|disable|reset|limit|default|reject|insert|delete|route)\b",
                             live), s
        assert "iptables" not in live and "nft " not in live, s
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert "ufw status 2>&1" in pf and 'info "firewall' in pf


def test_c6_swap_only_on_request_idempotent_and_preflight_warns_on_small_boxes():
    live = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    i_fn = live.find("add_swap() {")
    assert i_fn > 0, "swap lives in one function"
    block = live[i_fn:live.index("\n}\n", i_fn) + 3]
    for needle in ("swapon --show --noheadings", "fallocate -l 4G /swapfile", "mkswap /swapfile",
                   "grep -qE '^/swapfile[[:space:]]' /etc/fstab", "vm.swappiness=10"):
        assert needle in block, needle
    assert live.count("swapon /swapfile") == 1 and "fallocate" not in live.replace(block, ""), \
        "no swap outside add_swap()"
    code = _code_only(live)
    calls = re.findall(r"^\s*(.*\badd_swap\b.*)$", code.replace(block, ""), re.M)
    assert calls and all(c.strip() == 'if [ "$with_swap" = "1" ]; then add_swap; fi' for c in calls), calls
    # honoured in BOTH modes: preflight's remedy is `install.sh --units --with-swap`
    units_block = code[code.index('if [ "$units_only" = "1" ]; then\n  install_units'):]
    units_block = units_block[:units_block.index("exit 0")]
    assert "add_swap" in units_block, "--units --with-swap must add swap (preflight tells the operator to run it)"
    assert len(calls) == 2
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert '[ "$mem_total_mb" -lt 4096 ] && [ "$swap_mb" -eq 0 ]' in pf and "MemAvailable" in pf
    assert "install.sh --units --with-swap" in pf


_SYSTEMCTL_READ_ONLY = {"daemon-reload", "list-timers", "list-units", "is-active", "is-enabled", "status",
                        "show", "cat", "is-system-running"}
_SYSTEMCTL_MUTATING = {"enable", "disable", "start", "stop", "restart", "reload", "try-restart",
                       "try-reload-or-restart", "reload-or-restart", "kill", "mask", "unmask", "reset-failed",
                       "edit", "set-property", "isolate"}


def _systemctl_calls(text: str):
    """(verb, targets) for every systemctl invocation in the live lines."""
    out = []
    for line in _live(text).splitlines():
        for m in re.finditer(r"\bsystemctl\b", line):
            rest = re.split(r"\|\||&&|\||;|\d*>|<|\)|`|\bthen\b|\\$", line[m.end():])[0]
            toks = [t.strip("'\",.;:") for t in rest.split()]
            toks = [t for t in toks if t]
            verb = next((t for t in toks if not t.startswith("-")), None)
            targets = [t for t in toks[toks.index(verb) + 1:] if not t.startswith("-")] if verb else []
            out.append((verb, targets, line.strip()))
    return out


def test_c10_blast_radius_every_systemctl_or_kill_targets_only_vivek5_units():
    """M6 C10: nothing in deploy/bin may systemctl / kill / pkill / killall /
    restart a unit or process whose name does not start with vivek5-."""
    seen_mutating = 0
    for s in SCRIPTS:
        text = (BIN / s).read_text(encoding="utf-8")
        live = _live(text)
        assert not re.search(r"(^|[\s;|&(])(kill|pkill|killall|fuser)\s", live, re.M), f"{s}: a kill-family call"
        if "v5ctl()" in live:
            fn = live[live.index("v5ctl()"):live.index("\n}\n", live.index("v5ctl()"))]
            assert "-*|vivek5-*) ;;" in fn and "return 97" in fn, f"{s}: v5ctl lost its vivek5-only guard"
        # executed code only: heredoc bodies are prose (the plan) or the
        # sudoers grant, which test_install_sh_... pins exactly
        for verb, targets, line in _systemctl_calls(_without_v5ctl(_code_only(text))):
            assert verb is not None, (s, line)
            if verb in _SYSTEMCTL_MUTATING:
                seen_mutating += 1
            assert verb in _SYSTEMCTL_READ_ONLY | _SYSTEMCTL_MUTATING, (s, line)
            for t in targets:
                ok = t.startswith("vivek5-") or t.startswith("$") or t.startswith('"$')
                assert ok, f"{s}: `{line}` targets {t!r}, not a vivek5-* unit"
                if verb in _SYSTEMCTL_MUTATING and t.startswith("$"):
                    pytest.fail(f"{s}: `{line}` mutates a unit named by a variable outside v5ctl's guard")
        for m in re.finditer(r"\bv5ctl[ \t]+(\S+)((?:[ \t]+[^\s;|&>]+)*)", _without_v5ctl(_code_only(text))):
            seen_mutating += 1
            for t in m.group(2).split():
                t = t.strip("'\"")
                assert t.startswith(("-", "vivek5-", "$")), f"{s}: v5ctl {m.group(1)} {t}"
    assert seen_mutating >= 8, "the parser found every guarded v5ctl call"


def test_c10_the_v5ctl_guard_really_refuses_a_foreign_unit(tmp_path):
    """Execute the shipped helper against a fake systemctl."""
    src = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    fn = src[src.index("v5ctl() {"):src.index("\n}\n", src.index("v5ctl() {")) + 3]
    fake = tmp_path / "systemctl"
    log = tmp_path / "log"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    ok = _run(["bash", "-c", fn + '\nv5ctl enable --now vivek5-api.service vivek5-caddy.service'], env=env)
    assert ok.returncode == 0 and log.read_text().strip() == "enable --now vivek5-api.service vivek5-caddy.service"
    for foreign in ("caddy.service", "ictlive.service", "systemd-journald"):
        r = _run(["bash", "-c", fn + f'\nv5ctl restart vivek5-api.service {foreign}'], env=env)
        assert r.returncode == 97 and "not a vivek5-* unit" in r.stderr, foreign
    assert log.read_text().count("\n") == 1, "the refused calls never reached systemctl"


def test_c7_install_starts_nothing_cutover_starts_after_preflight_rollback_stops_all():
    code = _without_v5ctl(_code_only((BIN / "install.sh").read_text(encoding="utf-8")))
    calls = _systemctl_calls(code)
    assert calls, "the parser sees install.sh's systemctl calls"
    for verb, targets, line in calls:
        assert verb not in {"enable", "start", "restart", "reload", "reload-or-restart"}, line
    for m in re.finditer(r"\bv5ctl\s+(\S+)", code):
        assert m.group(1) in {"disable", "try-restart", "try-reload-or-restart"}, m.group(0)
    assert "enable --now" not in code.replace("v5ctl disable --now", "")
    co = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    assert co.find('"$here/preflight.sh" || die') < co.find("v5ctl enable --now vivek5-caddy.service vivek5-api.service")
    assert 'v5ctl enable --now "$t"' in co
    rb = _live((BIN / "rollback.sh").read_text(encoding="utf-8"))
    for unit in ("vivek5-api.service", "vivek5-spool.path", "vivek5-api-restart.path", "vivek5-caddy.service"):
        assert f"v5ctl disable --now {unit}" in rb, unit
    assert 'for f in "$kit"/systemd/vivek5-*.timer' in rb and 'v5ctl disable --now "$t"' in rb


def test_c8_and_c9_preflight_warns_on_one_vcpu_and_on_blocked_mail_ports():
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert 'if [ "$cpus" -lt 2 ]; then' in pf and "nproc" in pf
    assert 'tcp_open "$smtp_host" 587' in pf and 'tcp_open "$smtp_host" 465' in pf
    assert 'if [ "$s587" = "closed" ] && [ "$s465" = "closed" ]; then\n  warn' in pf and "use Telegram" in pf
    assert "bash -c 'exec 3<>\"/dev/tcp/$1/$2\"' _" in pf, "the host is an argument, never spliced into code"


def test_c11_no_journald_dropin_and_preflight_reports_the_journal_size():
    assert not (DEPLOY / "journald.conf").exists()
    for s in SCRIPTS:
        live = _live((BIN / s).read_text(encoding="utf-8"))
        assert "journald.conf" not in live and "systemd-journald" not in live, s
    assert "journalctl --disk-usage" in _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    for svc in _services():
        if svc != "vivek5-failed@.service":
            assert _keys(_unit(svc))["LogRateLimitIntervalSec"] == ["0"], svc


def test_c12_install_prints_the_plan_and_asks_before_changing_anything():
    live = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    i_plan = live.find("install.sh will make these system-wide changes")
    i_units_plan = live.find("install.sh --units will make these system-wide changes")
    i_ask = live.find('read -r -p "Type yes to make these changes: " reply')
    i_check = live.find('[ "$reply" = "yes" ] || die')
    assert 0 < i_units_plan < i_ask and 0 < i_plan < i_ask < i_check, "both plans print before the prompt"
    code = _code_only(live)
    top_level = [m.start() for m in re.finditer(
        r"^(apt-get|useradd|groupadd|usermod|install |systemctl |v5ctl |visudo|install_units$|install_caddy_config$|"
        r"as_vivek5|ssh-keygen|ssh-keyscan|fetch |tar |mv |rm |chown |chmod |sed -i|\"\$here/ports\.sh\")",
        code, re.M)]
    ask_code = code.find('read -r -p "Type yes to make these changes: " reply')
    assert top_level and ask_code > 0 and min(top_level) > ask_code, "no change runs before the typed yes"
    assert 'if [ "$assume_yes" != "1" ]; then' in live and "--yes) assume_yes=1" in live
    for item in ("vivek5-api", "vivek5-caddy", "vivek5-spool", "/etc/sudoers.d/vivek5", "/opt/vivek5",
                 "/etc/vivek5", "NOT enabled and NOT started"):
        assert item in live[i_plan:i_ask], item


# ---- root never runs what the jobs user can write (security review S2) ----
ROOT_SCRIPTS = ["install.sh", "preflight.sh", "cutover.sh", "rollback.sh", "ports.sh"]


def _refuse_fn(script: str) -> str:
    src = (BIN / script).read_text(encoding="utf-8")
    i = src.index("refuse_unsafe_path() {")
    return src[i:src.index("\n}\n", i) + 3]


def test_every_root_script_refuses_a_path_a_non_root_user_can_write():
    fns = {s: _refuse_fn(s) for s in ROOT_SCRIPTS}
    assert len(set(fns.values())) == 1, "one definition, identical everywhere"
    for s in ROOT_SCRIPTS:
        code = _code_only((BIN / s).read_text(encoding="utf-8"))
        call = code.index("\nrefuse_unsafe_path\n") if s != "ports.sh" else code.index("|| refuse_unsafe_path")
        work = [m.start() for m in re.finditer(
            r'^(apt-get|git |curl |sudo |v5ctl |systemctl |"\$here/|url=|install |useradd|usermod|'
            r'as_vivek5|as_job|if ! listeners=|vivek_home=|log )', code, re.M)]
        assert work and call < min(work), f"{s}: the path check must run before any work"


@pytest.mark.skipif(os.geteuid() != 0, reason="the ownership half needs root to chown")
def test_the_path_check_accepts_root_paths_and_refuses_writable_ones(tmp_path):
    fn = _refuse_fn("preflight.sh")
    harness = 'die() { echo "DIE: $*" >&2; exit 42; }\n' + fn + "\nrefuse_unsafe_path\necho SAFE\n"
    safe = tmp_path / "safe"
    safe.mkdir(mode=0o755)
    script = safe / "tool.sh"
    script.write_text("#")
    script.chmod(0o755)
    os.chmod(tmp_path, 0o755)
    r = _run(["bash", "-c", harness, str(script)])
    assert r.returncode == 0 and "SAFE" in r.stdout, r.stderr
    os.chmod(safe, 0o777)                                   # world-writable, NOT sticky
    r = _run(["bash", "-c", harness, str(script)])
    assert r.returncode == 42 and "writable by group/other" in r.stderr
    os.chmod(safe, 0o1777)                                  # like /tmp: root-owned + sticky
    assert _run(["bash", "-c", harness, str(script)]).returncode == 0
    os.chmod(safe, 0o755)
    os.chown(script, 65534, 65534)                          # the file itself owned by someone else
    r = _run(["bash", "-c", harness, str(script)])
    assert r.returncode == 42 and "owned by uid 65534" in r.stderr


def test_root_scripts_run_venv_and_git_as_vivek5_with_a_clean_env():
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert "sudo -u vivek5 -H env -i -C" in pf
    for bad in ('"$py" -', '"$py" --version', '"$py" -c', '"$py" -m scanner.watchdog'):
        for line in pf.splitlines():
            if bad in line:
                assert "as_vivek5_clean" in line or "as_job" in line, line
    assert re.search(r"systemd-run --quiet --wait --pipe --collect --unit=\"vivek5-preflight-", pf)
    assert '-p User=vivek5 -p EnvironmentFile="$etc/jobs.env" -p Environment=TZ=UTC' in pf
    assert 'as_job "$py" -m scanner.watchdog --test-alert' in pf
    assert 'as_job git -C "$publish" push --dry-run origin HEAD:main' in pf
    for s in ("preflight.sh", "cutover.sh", "rollback.sh"):
        live = _live((BIN / s).read_text(encoding="utf-8"))
        for line in live.splitlines():
            if re.search(r'(^|[\s(])git -C "\$(publish|vivek_home)"', line):
                assert re.search(r"as_vivek5\w*|as_job|sudo -u vivek5", line), f"{s}: root git: {line.strip()}"


def test_preflight_covers_every_section_7_step_0_check():
    t = (BIN / "preflight.sh").read_text(encoding="utf-8")
    for needle in ["24.04", "timedatectl show -p Timezone", "NTPSynchronized", '"$node_bin" --version',
                   '"$caddy_bin" version', "Python 3.12.", "pandas", "yfinance", "pybit", "yaml",
                   "-ge 20", "systemd-analyze calendar", "systemd-analyze verify", "CHANGE_ME",
                   "0640", "GH_ADMIN_TOKEN", "push --dry-run origin HEAD:main", "getent ahosts",
                   "/api/vps", "query1.finance.yahoo.com", "api.binance.com", "api.github.com",
                   "--test-alert", "sent via (telegram|email)", "VIVEK_ACCEPT_NO_ALERT_CHANNEL",
                   "--measure", "--limit", "40", "VIVEK_GIT_PUBLISH=0", "ru_maxrss", "worktree",
                   "state/HALT", "PASS", "FAIL", "WARN", "INFO", "remedy",
                   "rev-parse --is-shallow-repository", "fetch --unshallow",
                   "-name '*.lock'", "vivek5 is not in vivek5-spool", "3770 vivek5:vivek5-spool"]:
        assert needle in t or needle.replace("vivek5 is not", "$u is not") in t, needle
    assert re.search(r'\[ "\$fails" -eq 0 \] \|\| exit 1', t)
    assert "set -uo pipefail" in t and "set -euo" not in t, "every check must run and report"
    # the alert check is a FAIL by default, a WARN only under the explicit override
    i_warn = t.find("VIVEK_ACCEPT_NO_ALERT_CHANNEL:-0")
    assert i_warn > 0 and "warn \"NO ALERT CHANNEL DELIVERS" in t and "fail \"no alert channel delivered" in t
    assert 'for u in vivek5-api vivek5; do' in t, "BOTH sides of the spool are group members (security BLOCKER)"


def test_install_puts_both_spool_users_in_the_group_and_a_sticky_spool():
    live = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    assert "usermod -aG vivek5-spool vivek5-api" in live and re.search(r"^usermod -aG vivek5-spool vivek5$", live, re.M)
    assert 'install -d -m 3770 -o vivek5 -g vivek5-spool "$state/spool" "$state/spool/.tmp"' in live
    assert 'install -d -m 2750 -o vivek5 -g vivek5-spool "$state/spool/done" "$state/spool/failed"' in live


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
    fake venv (pip logs; python = a wrapper that execs THIS interpreter, so the
    runner's `ledger-note` sees the test venv's packages), a fake sudo and a
    fake systemctl (list-units prints whatever `running` holds)."""

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
        py = self.venv / "bin" / "python"
        py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        py.chmod(0o755)
        pip = self.venv / "bin" / "pip"
        pip.write_text('#!/bin/sh\necho "pip $*" >> "$(dirname "$0")/../pip.log"\nexit 0\n')
        pip.chmod(0o755)
        sudo = self.fakebin / "sudo"
        sudo.write_text('#!/bin/sh\necho "$*" >> "$(dirname "$0")/sudo.log"\nexit 0\n')
        sudo.chmod(0o755)
        self.running = self.fakebin / "running"
        self.running.write_text("")
        ctl = self.fakebin / "systemctl"
        ctl.write_text(f'#!/bin/sh\n[ "$1" = "list-units" ] && cat "{self.running}"\nexit 0\n')
        ctl.chmod(0o755)

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
    assert "up to date at" in r.stdout, "the up-to-date path says so, not only the ledger"
    row = box.ledger()["update"]
    assert row["last_status"] == "ok" and row["last_exit"] == 0 and row["host"] == "vps"
    assert row["last_success_at"] and row["consecutive_failures"] == 0
    assert "up to date" in row["last_line"]
    assert stat.S_IMODE((box.state / "runs.json").stat().st_mode) == 0o640


def test_update_and_gc_write_their_rows_through_the_runners_ledger_note_verb():
    """M3: the shell scripts carry no mirror of the ledger writer any more."""
    for s in ("update.sh", "gc.sh"):
        live = _live((BIN / s).read_text(encoding="utf-8"))
        assert "-m scanner.vps ledger-note --started" in live, s
        assert "fcntl" not in live and "json.dump(book" not in live and "consecutive_failures" not in live, s


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


def _hold_repo_shared(box):
    lock = box.state / "locks" / "repo.lock"
    lock.touch()
    holder = subprocess.Popen(["bash", "-c", f'exec 9>"{lock}"; flock -s 9; sleep 30'])
    import time
    time.sleep(0.5)
    return holder


def test_update_sh_alerts_only_on_an_unexplained_busy_repo_lock(tmp_path):
    box = Box(tmp_path)
    holder = _hold_repo_shared(box)
    try:
        for n in range(1, 12):
            r = box.update()
            assert r.returncode == 0, (n, r.stderr + r.stdout)
            assert "skipped busy" in r.stdout and "unexplained" in r.stdout
        row = box.ledger()["update"]
        assert row["last_status"] == "skipped" and row["last_skip_at"]
        assert (box.state / "update_skips").read_text().strip() == "11"
        r = box.update()  # the 12th consecutive UNEXPLAINED skip = 1 h at */5 -> exit 1 so OnFailure alerts
        assert r.returncode == 1 and "consecutive unexplained busy skips" in r.stdout
    finally:
        holder.kill()
        holder.wait()
    # once the lock is free the counter resets
    r = box.update()
    assert r.returncode == 0 and not (box.state / "update_skips").exists()


def test_update_sh_never_counts_a_busy_lock_while_a_vivek5_job_is_running(tmp_path):
    """Book review K4: a 40-80 min ASX scan (and the crypto runs around it)
    legitimately hold the repo lock for most of a session. That produced ~5
    false 'job may be hung' alarms per session. A RUNNING job unit explains
    the busy lock (its own TimeoutStartSec is the hang detector)."""
    box = Box(tmp_path)
    box.running.write_text("vivek5-scan@asx.service loaded active running Vivek 5.0 hourly VIVEK scan\n"
                           "vivek5-api.service loaded active running adapter\n")
    holder = _hold_repo_shared(box)
    try:
        for n in range(30):
            r = box.update()
            assert r.returncode == 0, (n, r.stdout)
        assert "running: vivek5-scan@asx.service" in r.stdout and "vivek5-api" not in r.stdout
        assert not (box.state / "update_skips").exists()
        assert "running" in box.ledger()["update"]["last_line"]
    finally:
        holder.kill()
        holder.wait()


def test_update_sh_clears_a_killed_gits_lock_files_in_the_checkout(tmp_path):
    box = Box(tmp_path)
    (box.app / ".git" / "index.lock").write_text("")
    ref_lock = box.app / ".git" / "refs" / "remotes" / "origin" / "main.lock"
    ref_lock.parent.mkdir(parents=True, exist_ok=True)
    ref_lock.write_text("")
    box.upstream("scanner/vivek.py", "VERSION = 5\n", "code")
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    assert "removed stale .git/index.lock" in r.stdout and "main.lock" in r.stdout
    assert (box.app / "scanner" / "vivek.py").read_text() == "VERSION = 5\n"


def test_update_sh_runs_pip_restarts_the_api_and_flags_stale_units_on_the_right_paths(tmp_path):
    box = Box(tmp_path)
    box.upstream("requirements.txt", "requests==2.1.0\n", "bump")
    box.upstream("functions/api/scan.js", "// 2\n", "function")
    box.upstream("deploy/systemd/x.service", "[Unit]\n# changed\n", "unit")
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    assert "install -q -r requirements.txt" in (box.venv / "pip.log").read_text()
    flag = box.state / "api-restart"
    assert flag.exists() and _git(box.seed, "rev-parse", "HEAD") in flag.read_text(), \
        "the restart is REQUESTED through the flag the root .path unit watches"
    assert not (box.fakebin / "sudo.log").exists(), "no sudo: NoNewPrivileges=yes forbids it"
    assert (box.state / "UNITS_STALE").exists()
    assert "install.sh --units" in r.stdout and "ROOT-OWNED source clone" in r.stdout
    row = box.ledger()["update"]
    assert row["last_status"] == "ok" and "pip-installed" in row["last_line"] and "units-stale" in row["last_line"]
    assert "api-restart-requested" in row["last_line"]
    assert not (box.state / "update_pending").exists(), "a finished sync leaves no resume marker"
    # a plain code change does none of that
    (box.venv / "pip.log").unlink()
    flag.unlink()
    (box.state / "UNITS_STALE").unlink()
    box.upstream("scanner/vivek.py", "VERSION = 4\n", "code")
    r = box.update()
    assert r.returncode == 0
    assert not (box.venv / "pip.log").exists() and not flag.exists()
    assert not (box.state / "UNITS_STALE").exists()


def test_update_sh_never_touches_etc_or_runs_install(tmp_path):
    t = (BIN / "update.sh").read_text(encoding="utf-8")
    live = "\n".join(l for l in t.splitlines() if not l.strip().startswith("#"))
    assert "/etc/" not in live and "install.sh" not in live.replace("install.sh --units", "")
    assert "reset -q --mixed" in live and "reset --hard" not in live
    assert "flock -x -n 9" in live and 'locks/repo.lock' in live
    # nothing EXECUTES sudo (the WARNING text may name `sudo ... install.sh --units` for the operator)
    assert "sudo -n" not in live
    unquoted = re.sub(r'"[^"\n]*"', '""', _code_only(t))      # message strings may NAME sudo
    assert not re.search(r"\bsudo\b", unquoted), "update.sh must not execute sudo"
    assert '> "$state_dir/api-restart"' in live


def _hold(box, name, mode, secs=30):
    """Hold state/locks/<name>.lock with flock -s|-x in a background process."""
    lock = box.state / "locks" / f"{name}.lock"
    lock.touch()
    holder = subprocess.Popen(["bash", "-c", f'exec 9>"{lock}"; flock {mode} 9; sleep {secs}'])
    import time
    time.sleep(0.5)
    return holder


def _gc(box, **env):
    e = box.env()
    e.update({"VIVEK_GC_REPO_WAIT_S": "1", "VIVEK_GC_PUBLISH_WAIT_S": "1"}, **env)
    return subprocess.run([str(BIN / "gc.sh")], env=e, capture_output=True, text=True)


def test_gc_sh_collects_both_clones_beside_a_running_job(tmp_path):
    """Ops review 2026-09-27: gc held the repo lock EXCLUSIVE for the whole
    repack, so the kill switch (10-min lock budget) failed every Sunday. It
    now takes it SHARED -- a running job (also SHARED) never waits on it."""
    box = Box(tmp_path)
    job = _hold(box, "repo", "-s")          # a running job holds repo SHARED
    try:
        r = _gc(box)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "working checkout, repo lock shared" in r.stdout and "publish lock exclusive" in r.stdout
        row = box.ledger()["gc"]
        assert row["last_status"] == "ok" and row["host"] == "vps"
    finally:
        job.kill()
        job.wait()
    t = (BIN / "gc.sh").read_text(encoding="utf-8")
    live = _live(t)
    assert "pack.threads=1" in live and "pack.windowMemory=256m" in live and "gc --prune=2.weeks.ago" in live
    assert 'flock -s -w "$repo_wait" 9' in live and "flock -x" not in live.replace('flock -x -w "$pub_wait" 8', "")
    assert 'repo_wait="${VIVEK_GC_REPO_WAIT_S:-60}"' in live
    assert 'pub_wait="${VIVEK_GC_PUBLISH_WAIT_S:-150}"' in live and 'pub_bound="${VIVEK_GC_PUBLISH_BOUND_S:-420}"' in live
    # a publish waits config.VPS_LOCK_WAIT_S["default"] for the publish lock:
    # gc's own wait + its bound must fit inside it
    assert 150 + 420 < config.VPS_LOCK_WAIT_S["default"]
    assert 'timeout "$2"' in live


def test_gc_sh_skips_when_update_or_an_operator_verb_holds_the_repo_exclusive(tmp_path):
    box = Box(tmp_path)
    holder = _hold(box, "repo", "-x")
    try:
        r = _gc(box)
        assert r.returncode == 0 and "skipping this week" in r.stdout, r.stdout + r.stderr
        assert box.ledger()["gc"]["last_status"] == "skipped"
    finally:
        holder.kill()
        holder.wait()


def test_gc_sh_leaves_the_publish_clone_to_a_running_publish(tmp_path):
    box = Box(tmp_path)
    pub = _hold(box, "publish", "-x")       # a publish in progress
    try:
        r = _gc(box)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "working checkout" in r.stdout and "publish clone is skipped this week" in r.stdout
        row = box.ledger()["gc"]
        assert row["last_status"] == "ok" and "publish-skipped-busy" in row["last_line"]
    finally:
        pub.kill()
        pub.wait()


def test_gc_unit_yields_like_a_heavy_job():
    k = _keys(_unit("vivek5-gc.service"))
    assert k["Nice"] == ["10"] and k["CPUWeight"] == ["20"] and k["IOSchedulingClass"] == ["idle"]
    assert k["MemoryHigh"] == ["1G"] and "MemoryMax" not in k


def test_update_sh_counts_a_running_gc_as_an_explained_busy_lock(tmp_path):
    box = Box(tmp_path)
    box.running.write_text("vivek5-gc.service loaded activating start Vivek 5.0 weekly git gc\n")
    holder = _hold_repo_shared(box)
    try:
        for _ in range(13):
            r = box.update()
            assert r.returncode == 0, r.stdout
        assert "running: vivek5-gc.service" in r.stdout and not (box.state / "update_skips").exists()
    finally:
        holder.kill()
        holder.wait()


def test_the_ledger_note_verb_writes_a_section_3_6_row(tmp_path):
    led = tmp_path / "runs.json"
    env = dict(os.environ, VIVEK_RUNS_LEDGER=str(led), VIVEK_STATE_DIR=str(tmp_path), WATCHDOG_HOST="vps")
    r = _run([sys.executable, "-m", "scanner.vps", "ledger-note", "--started", "2026-09-27T00:00:00Z",
              "update", "skipped", "0", "skipped", "busy", "x3"], env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    row = json.loads(led.read_text())["update"]
    assert row["last_status"] == "skipped" and row["last_line"] == "skipped busy x3"
    assert row["last_start"] == "2026-09-27T00:00:00Z" and row["last_skip_at"] and row["host"] == "vps"
    r = _run([sys.executable, "-m", "scanner.vps", "ledger-note", "gc", "failed", "1", "git", "gc", "failed"],
             env=env, cwd=str(ROOT))
    assert r.returncode == 0 and json.loads(led.read_text())["gc"]["consecutive_failures"] == 1
    assert _run([sys.executable, "-m", "scanner.vps", "ledger-note", "gc", "bogus", "0"], env=env,
                cwd=str(ROOT)).returncode == 2


# --------------------------------------------------------------------------
# 10. 2026-09-27 host review (production systemd fleet pass)
# --------------------------------------------------------------------------
def test_the_api_restart_hook_is_the_only_root_unit_and_runs_one_fixed_command():
    """update.sh runs NoNewPrivileges=yes, so `sudo systemctl restart` (setuid)
    could never have worked from it. It now WRITES a flag; a root .path unit
    fires a oneshot that runs exactly one fixed command -- try-restart, so a
    request before cutover / after rollback never STARTS the API (C7)."""
    path = _keys(_unit("vivek5-api-restart.path"))
    assert path["PathChanged"] == [API_RESTART_FLAG], "fires on a WRITE, never on the file merely existing"
    assert path["Unit"] == [ROOT_UNIT]
    assert "WantedBy=multi-user.target" in _unit("vivek5-api-restart.path")
    text = _unit(ROOT_UNIT)
    k = _keys(text)
    assert k["ExecStart"] == [ROOT_UNIT_EXEC] and "User" not in k and "EnvironmentFile" not in k
    assert k["Type"] == ["oneshot"] and k["WorkingDirectory"] == ["/"]
    assert not any(key.startswith("ExecStart") and key != "ExecStart" for key in k), "one command, no Pre/Post"
    for opt in ("ProtectSystem=strict", "ProtectHome=yes", "PrivateTmp=yes", "NoNewPrivileges=yes"):
        assert opt in text, opt
    assert "ReadWritePaths" not in k, "the root hook writes nothing"
    assert "%" not in k["ExecStart"][0] and "$" not in k["ExecStart"][0], "nothing from the request reaches the command"
    # every unit that runs systemctl at all is this one, on vivek5-api only
    for f in UNITS.glob("vivek5-*"):
        for line in _live(f.read_text(encoding="utf-8")).splitlines():
            if "systemctl" in line and line.startswith("Exec"):
                assert f.name == ROOT_UNIT and line == f"ExecStart={ROOT_UNIT_EXEC}", (f.name, line)
    # update.sh writes exactly the flag the path unit watches (state default = /opt/vivek5/state)
    up = _live((BIN / "update.sh").read_text(encoding="utf-8"))
    assert 'state_dir="${VIVEK_STATE_DIR:-/opt/vivek5/state}"' in up and '> "$state_dir/api-restart"' in up
    assert API_RESTART_FLAG == "/opt/vivek5/state/" + "api-restart"
    # cutover arms it, rollback disarms it
    assert "vivek5-api-restart.path" in _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    assert "v5ctl disable --now vivek5-api-restart.path" in _live((BIN / "rollback.sh").read_text(encoding="utf-8"))


def test_the_update_unit_carries_the_full_hardening_and_alone_may_write_the_venv():
    text = _unit("vivek5-update.service")
    k = _keys(text)
    assert k["NoNewPrivileges"] == ["yes"] and k["ProtectSystem"] == ["strict"]
    assert k["ReadWritePaths"] == ["/opt/vivek5/app /opt/vivek5/publish /opt/vivek5/state", "/opt/vivek5/venv"]
    for svc in _services():
        if svc != "vivek5-update.service":
            rw = " ".join(_keys(_unit(svc)).get("ReadWritePaths", []))
            assert "/opt/vivek5/venv" not in rw, f"{svc} may not write the venv"


def test_install_writes_no_sudoers_and_removes_only_its_own_earlier_file(tmp_path):
    src = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    fn = src[src.index("remove_stale_sudoers() {"):src.index("\n}\n", src.index("remove_stale_sudoers() {")) + 3]
    ours = tmp_path / "ours"
    ours.write_text("# Vivek 5.0: update.sh restarts the API adapter when functions/ or deploy/api/\n"
                    "vivek5 ALL=(root) NOPASSWD: /usr/bin/systemctl restart vivek5-api.service\n")
    theirs = tmp_path / "theirs"
    theirs.write_text("vivek5 ALL=(ALL) NOPASSWD: ALL\n")
    r = _run(["bash", "-c", fn + f'\nremove_stale_sudoers "{ours}"; remove_stale_sudoers "{theirs}"; '
              f'remove_stale_sudoers "{tmp_path / "absent"}"'])
    assert r.returncode == 0, r.stderr
    assert not ours.exists() and theirs.exists(), "only a file carrying this kit's header is removed"
    assert "left alone" in r.stdout
    code = _code_only(src)
    assert code.count("remove_stale_sudoers\n") == 2, "called by the full install AND by --units"
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert 'if [ -e /etc/sudoers.d/vivek5 ]; then\n  warn' in pf and 'pass "no sudo grant for any vivek5 user"' in pf


def test_the_front_door_and_the_path_units_survive_a_reboot():
    """Without an [Install] section `systemctl enable --now` (cutover step 1)
    only STARTED vivek5-api/-caddy: after a reboot the timers ran while the
    dispatch endpoint and the TLS front door stayed dead."""
    for u in ("vivek5-api.service", "vivek5-caddy.service", "vivek5-spool.path", "vivek5-api-restart.path"):
        text = _unit(u)
        assert "[Install]" in text and "WantedBy=multi-user.target" in text, u
    for timer in _timers():
        assert "WantedBy=timers.target" in _unit(timer), timer
    co = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    assert 'systemctl is-enabled "$u"' in co and "for u in vivek5-api.service vivek5-caddy.service; do" in co


def _rewritten_units(tmp_path) -> pathlib.Path:
    root = tmp_path / "root"
    for d in ("opt/vivek5/venv/bin", "opt/vivek5/app/deploy/bin", "opt/vivek5/node/bin",
              "opt/vivek5/caddy", "etc/vivek5"):
        (root / d).mkdir(parents=True)
    for stub in ("opt/vivek5/venv/bin/python", "opt/vivek5/node/bin/node", "opt/vivek5/caddy/caddy"):
        (root / stub).write_text("#!/bin/sh\nexit 0\n")
        (root / stub).chmod(0o755)
    for s in SCRIPTS:
        shutil.copy(BIN / s, root / "opt/vivek5/app/deploy/bin" / s)
    for n in ("jobs", "api"):
        shutil.copy(ENV_DIR / f"{n}.env.example", root / f"etc/vivek5/{n}.env")
    (root / "etc/vivek5/caddy.env").write_text("VIVEK_DOMAIN=example.com\n")
    units = tmp_path / "units"
    units.mkdir()
    for f in UNITS.glob("vivek5-*"):
        text = f.read_text(encoding="utf-8")
        text = text.replace("/opt/vivek5", str(root / "opt/vivek5")).replace("/etc/vivek5", str(root / "etc/vivek5"))
        (units / f.name).write_text(text, encoding="utf-8")
    return units


@pytest.mark.skipif(not SYSTEMD_ANALYZE, reason="systemd-analyze not installed")
def test_systemd_analyze_verify_on_every_template_instance_and_hook_the_kit_starts(tmp_path):
    """Verifying the template FILES does not load an instance: every instance a
    timer starts, the failure hook as systemd names it, and the root restart
    hook are verified as the units systemd will actually load."""
    units = _rewritten_units(tmp_path)
    names = sorted({_service_for(t) for t in TABLE} | {"vivek5-failed@vivek5-scan@asx.service.service",
                                                       ROOT_UNIT, "vivek5-api-restart.path"})
    env = dict(os.environ, SYSTEMD_UNIT_PATH=f"{units}:")
    r = _run([SYSTEMD_ANALYZE, "verify", *names], env=env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert not [l for l in (r.stderr + r.stdout).splitlines() if "vivek5-" in l]


# Every tree each unit writes (the code that runs in it), and the only trees
# ProtectSystem=strict lets it write. The job set is the runner + its steps:
# the checkout (data, .cache, __pycache__, .git for the momentum fetch), the
# publish clone, state/ (ledger, locks, spool, HOME, XDG cache, tmp).
_JOB_RW = {"/opt/vivek5/app", "/opt/vivek5/publish", "/opt/vivek5/state"}
_UNIT_WRITES = {
    "vivek5-update.service": _JOB_RW | {"/opt/vivek5/venv"},      # + pip install on requirements change
    "vivek5-api.service": {"/opt/vivek5/state/spool", "/opt/vivek5/state/kv.json"},
    "vivek5-caddy.service": {"/opt/vivek5/caddy/data", "/opt/vivek5/caddy/config"},
    ROOT_UNIT: set(),
}


def _rw(svc: str) -> set[str]:
    return {p.lstrip("-") for line in _keys(_unit(svc)).get("ReadWritePaths", []) for p in line.split()}


def test_protect_system_strict_everywhere_and_the_write_paths_cover_every_tree_written():
    for svc in _services():
        k = _keys(_unit(svc))
        assert k["ProtectSystem"] == ["strict"], svc
        assert k["ProtectHome"] == ["yes"] and k["PrivateTmp"] == ["yes"], svc
        assert _rw(svc) == _UNIT_WRITES.get(svc, _JOB_RW), (svc, sorted(_rw(svc)))
    # every place the job environment points a writer at lies inside the job trees
    env = {}
    for line in (ENV_DIR / "jobs.env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_]+)=(/\S*)$", line)
        if m:
            env[m.group(1)] = m.group(2)
    for name in ("HOME", "XDG_CACHE_HOME", "VIVEK_HOME", "VIVEK_PUBLISH", "VIVEK_STATE_DIR", "VIVEK_RUNS_LEDGER"):
        assert any(env[name] == r or env[name].startswith(r + "/") for r in _JOB_RW), (name, env.get(name))
    # the flag update.sh writes and the api-restart path unit watches
    assert API_RESTART_FLAG.startswith("/opt/vivek5/state/")
    # the adapter writes spool files and kv.json only
    api = {m.group(1): m.group(2) for m in re.finditer(r"^([A-Z_]+)=(\S*)$",
                                                       (ENV_DIR / "api.env.example").read_text(), re.M)}
    assert api["VIVEK_STATE_DIR"] == "/opt/vivek5/state"
    # Caddy's certificates, autosave and admin socket
    for name in ("Caddyfile.phase1", "Caddyfile.phase2"):
        assert "admin unix//opt/vivek5/caddy/data/admin.sock" in _caddy(name)


@pytest.mark.skipif(not SYSTEMD_ANALYZE, reason="systemd-analyze not installed")
def test_every_weekday_through_the_2026_27_dst_changes_gets_the_documented_scans():
    """Walk EVERY day from 2026-09-28 to 2027-04-30 -- Sydney 2026-10-04 and
    2027-04-04, New York 2026-11-01 and 2027-03-14 -- not four sample weeks:
    each market weekday gets exactly the seven documented local minutes plus
    the 17:15 backstop, and no weekend day gets anything."""
    end = dt.date(2027, 4, 30)
    for market, (tzname, minutes, timers) in DOCUMENTED.items():
        tz = ZoneInfo(tzname)
        days: dict[dt.date, list[str]] = {}
        for timer in timers + [f"vivek5-scan-backstop@{market}.timer"]:
            for cal in _keys(_unit(timer))["OnCalendar"]:
                for t in _calendar_elapses(cal, "2026-09-28 00:00:00 UTC", 900):
                    local = t.astimezone(tz)
                    if local.date() <= end:
                        days.setdefault(local.date(), []).append(local.strftime("%H:%M"))
        weekdays = [dt.date(2026, 9, 28) + dt.timedelta(n) for n in range((end - dt.date(2026, 9, 28)).days + 1)]
        weekdays = [d for d in weekdays if d.weekday() < 5]
        assert sorted(days) == weekdays, (market, sorted(set(days) ^ set(weekdays))[:5])
        for d, got in days.items():
            assert sorted(got) == sorted(minutes | {"17:15"}), (market, d, sorted(got))


def _interrupt_after_reset(box):
    """What a SIGKILL between `git reset --mixed` and the checkouts leaves:
    HEAD + index at origin/main, the code files still old, the marker written."""
    old = _git(box.app, "rev-parse", "HEAD")
    _git(box.app, "fetch", "-q", "origin", "main")
    (box.state / "update_pending").write_text(old + "\n")
    _git(box.app, "reset", "-q", "--mixed", "origin/main")
    return old


def test_update_sh_finishes_a_sync_a_kill_interrupted_on_the_next_run(tmp_path):
    box = Box(tmp_path)
    (box.state / "publish_head").write_text(_git(box.app, "rev-parse", "HEAD") + "\n")
    box.upstream("scanner/vivek.py", "VERSION = 7\n", "code")
    box.upstream("functions/api/scan.js", "// 7\n", "function")
    _interrupt_after_reset(box)
    assert (box.app / "scanner" / "vivek.py").read_text() == "VERSION = 1\n"
    assert _git(box.app, "rev-parse", "HEAD") == _git(box.seed, "rev-parse", "HEAD"), "HEAD already moved"
    r = box.update()
    assert r.returncode == 0, r.stderr + r.stdout
    assert "resuming an interrupted sync" in r.stdout and "up to date" not in r.stdout
    assert (box.app / "scanner" / "vivek.py").read_text() == "VERSION = 7\n"
    assert (box.state / "api-restart").exists(), "the restart the interrupted run owed is still requested"
    assert not (box.state / "update_pending").exists()
    r = box.update()
    assert r.returncode == 0 and "up to date" in r.stdout


def test_update_sh_retries_a_failed_pip_install_instead_of_calling_it_up_to_date(tmp_path):
    box = Box(tmp_path)
    pip = box.venv / "bin" / "pip"
    pip.write_text('#!/bin/sh\necho "pip $*" >> "$(dirname "$0")/../pip.log"\nexit 1\n')
    box.upstream("requirements.txt", "requests==2.2.0\n", "bump")
    r = box.update()
    assert r.returncode == 1 and box.ledger()["update"]["last_status"] == "failed"
    assert (box.state / "update_pending").exists(), "the failed follow-up stays owed"
    pip.write_text('#!/bin/sh\necho "pip $*" >> "$(dirname "$0")/../pip.log"\nexit 0\n')
    r = box.update()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (box.venv / "pip.log").read_text().count("install -q -r requirements.txt") == 2, \
        "HEAD == origin/main already, yet the owed pip install ran"
    assert "pip-installed" in box.ledger()["update"]["last_line"]
    assert not (box.state / "update_pending").exists()


def test_the_caddy_admin_api_is_a_unix_socket_in_our_data_dir():
    """localhost:2019 (Caddy's default admin listener) is where a distro Caddy
    on the box already listens -- ours would fail to start -- and any local
    process could rewrite our routes through it."""
    for name in ("Caddyfile.phase1", "Caddyfile.phase2"):
        live = "\n".join(l for l in _caddy(name).splitlines() if not l.strip().startswith("#"))
        m = re.search(r"^\{\s*admin (\S+)\s*\}", live.strip(), re.S)
        assert m and m.group(1) == "unix//opt/vivek5/caddy/data/admin.sock", name
        assert "2019" not in live and "admin off" not in live, "reload (ExecReload) needs the admin API"
    k = _keys(_unit("vivek5-caddy.service"))
    assert "/opt/vivek5/caddy/data" in k["ReadWritePaths"][0], "the socket's directory is writable"


@pytest.mark.skipif(not _caddy_version_ok(), reason="caddy >= 2.8 not available (set CADDY_BIN)")
def test_the_admin_socket_is_what_caddy_adapts(tmp_path):
    envf = tmp_path / "caddy.env"
    envf.write_text(f"VIVEK_DOMAIN=example.com\nVIVEK_API_BASIC_USER=vivek\nVIVEK_API_BASIC_HASH={RAW_HASH}\n")
    for phase in ("phase1", "phase2"):
        r = _run([CADDY_BIN, "adapt", "--adapter", "caddyfile", "--config", str(CADDY_DIR / f"Caddyfile.{phase}"),
                  "--envfile", str(envf)])
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["admin"] == {"listen": "unix//opt/vivek5/caddy/data/admin.sock"}, phase


GITHUB_PUBLISHED = {"SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s",   # RSA
                    "SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM",   # ECDSA
                    "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"}   # Ed25519


def test_github_host_keys_are_checked_against_the_published_fingerprints(tmp_path):
    """ssh-keyscan is trust-on-first-use; install.sh now refuses any key GitHub
    does not publish (and preflight FAILs on one), same pinned list in both."""
    lines = {}
    for s in ("install.sh", "preflight.sh"):
        m = re.search(r'^GITHUB_FPS="([^"]+)"$', (BIN / s).read_text(encoding="utf-8"), re.M)
        assert m, s
        lines[s] = m.group(1)
    assert lines["install.sh"] == lines["preflight.sh"] and set(lines["install.sh"].split()) == GITHUB_PUBLISHED
    src = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    i = src.index('unknown_fp=""')
    block = src[i:src.index('echo "    ok: every key is one GitHub publishes"', i)]
    fake = tmp_path / "bin"
    fake.mkdir()
    out = tmp_path / "keygen.out"
    (fake / "ssh-keygen").write_text(f'#!/bin/sh\ncat "{out}"\n')
    (fake / "ssh-keygen").chmod(0o755)
    kh = tmp_path / "known_hosts"
    harness = (f'GITHUB_FPS="{lines["install.sh"]}"; etc="{tmp_path}"\n'
               'die() { echo "DIE: $*"; exit 42; }\n' + block + '\necho KEPT\n')
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}")
    good = "".join(f"256 {fp} github.com (X)\n" for fp in sorted(GITHUB_PUBLISHED))
    out.write_text(good)
    kh.write_text("github.com ssh-ed25519 AAAA\n")
    r = _run(["bash", "-c", harness], env=env)
    assert r.returncode == 0 and "KEPT" in r.stdout and kh.exists(), r.stdout
    out.write_text(good + "256 SHA256:AAAAmitmAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA github.com (ED25519)\n")
    r = _run(["bash", "-c", harness], env=env)
    assert r.returncode == 42 and "does not publish" in r.stdout and "SHA256:AAAAmitm" in r.stdout
    assert not kh.exists(), "an unverified known_hosts is not kept"
    assert src.index("GITHUB_FPS") < src.index("ssh-keyscan")
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert 'fail "known_hosts carries key(s) GitHub does not publish' in pf


def _cutover_step7(tmp_path, states: dict[str, str]):
    """Run cutover.sh's shipped step 7 against a fake systemctl."""
    src = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    block = src[src.index('step "7:'):src.index('step "8:')]
    table = tmp_path / "states"
    table.write_text("".join(f"{k} {v}\n" for k, v in states.items()))
    fake = tmp_path / "systemctl"
    fake.write_text(
        '#!/bin/bash\n'
        f'look() {{ awk -v k="$1" \'$1==k {{ $1=""; sub(/^ /,""); print; f=1 }} END {{ exit !f }}\' "{table}"; }}\n'
        'case "$1" in\n'
        '  show) prop="${2#--property=}"; look "$4:$prop" ;;\n'
        '  is-enabled) look "$2:enabled" ;;\n'
        '  is-active) [ "$(look "$3:ActiveState")" = active ] ;;\n'
        '  list-timers) exit 0 ;;\n'
        '  *) exit 9 ;;\n'
        'esac\n')
    fake.chmod(0o755)
    harness = ("expected=(vivek5-a.timer vivek5-b.timer); paths=(vivek5-spool.path vivek5-api-restart.path)\n"
               "step() { :; }\nauto_rollback() { echo ROLLBACK; exit 1; }\nset -euo pipefail\n" + block + "\necho ARMED\n")
    return _run(["bash", "-c", harness], env=dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}"))


def test_cutover_step7_arms_only_when_every_timer_path_and_daemon_is_really_up(tmp_path):
    good = {"vivek5-a.timer:ActiveState": "active", "vivek5-a.timer:NextElapseUSecRealtime": "Mon 2026-09-28 01:07:00 UTC",
            "vivek5-b.timer:ActiveState": "active", "vivek5-b.timer:NextElapseUSecRealtime": "Mon 2026-09-28 01:22:00 UTC",
            "vivek5-spool.path:ActiveState": "active", "vivek5-api-restart.path:ActiveState": "active",
            "vivek5-api.service:enabled": "enabled", "vivek5-api.service:ActiveState": "active",
            "vivek5-caddy.service:enabled": "enabled", "vivek5-caddy.service:ActiveState": "active"}
    r = _cutover_step7(tmp_path, good)
    assert r.returncode == 0 and "ARMED" in r.stdout and "ROLLBACK" not in r.stdout, r.stdout + r.stderr
    for broken, why in ((("vivek5-b.timer:NextElapseUSecRealtime", ""), "no-next"),
                        (("vivek5-b.timer:NextElapseUSecRealtime", "n/a"), "no-next"),
                        (("vivek5-a.timer:ActiveState", "failed"), "failed"),
                        (("vivek5-api-restart.path:ActiveState", "inactive"), "inactive"),
                        (("vivek5-caddy.service:enabled", "static"), "not-enabled")):
        states = dict(good)
        states[broken[0]] = broken[1]
        r = _cutover_step7(tmp_path, states)
        assert r.returncode == 1 and "ROLLBACK" in r.stdout and why in r.stdout, (broken, r.stdout + r.stderr)
    # the automatic rollback gets the SAME token through the environment
    co = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    fn = co[co.index("auto_rollback() {"):co.index("\n}\n", co.index("auto_rollback() {"))]
    assert "export GH_ADMIN_TOKEN" in fn and '"$here/rollback.sh" --yes' in fn and "exit 1" in fn
    assert "--output=json" not in co, "no JSON table output assumed of systemctl"


def test_cutover_drain_counts_runs_by_workflow_id_and_by_ref_suffixed_paths(tmp_path):
    co = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    i = co.index("n=\"$(python3 -c '") + len("n=\"$(python3 -c '")
    code = co[i:co.index("' \"$gh_body\"", i)]
    body = tmp_path / "runs.json"
    body.write_text(json.dumps({"workflow_runs": [
        {"workflow_id": 11, "path": ".github/workflows/scan.yml"},
        {"workflow_id": 99, "path": ".github/workflows/crypto_bot.yml@refs/heads/main"},
        {"workflow_id": 12, "path": ".github/workflows/something_else.yml"},
        {"workflow_id": 77, "path": ".github/workflows/test.yml"},
    ]}))
    r = _run([sys.executable, "-c", code, str(body), "11,12", "scan.yml", "crypto_bot.yml"])
    assert r.returncode == 0 and r.stdout.strip() == "3", r.stdout + r.stderr
    assert 'wf_ids+=("$(json_field id)")' in co


def test_install_sh_rejects_a_bare_phase_flag_before_touching_anything():
    r = _run([str(BIN / "install.sh"), "--phase"])
    assert r.returncode == 1 and "--phase needs a value" in r.stderr, r.stdout + r.stderr


def test_install_units_restarts_only_changed_long_running_units_and_never_a_job():
    live = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    fn = live[live.index("install_units() {"):live.index("\n}\n", live.index("install_units() {"))]
    assert 'cmp -s "$f" "/etc/systemd/system/$b" || changed+=("$b")' in fn
    assert "vivek5-api.service|vivek5-caddy.service|vivek5-*.path|vivek5-*.timer)" in fn
    assert 'v5ctl try-restart "$b"' in fn, "try-restart: only if it is already running (C7)"
    assert fn.index("systemctl daemon-reload") < fn.index('v5ctl try-restart "$b"')
    assert "vivek5-*.service" not in fn.split("case")[1].split("esac")[0].replace("vivek5-api.service", "") \
        .replace("vivek5-caddy.service", ""), "a oneshot job is never restarted (it would kill a running scan)"


def test_no_command_substitution_hides_in_an_unquoted_heredoc():
    """An unquoted heredoc EXECUTES backticks and $( ): a plan line quoting
    `systemctl try-restart vivek5-api.service` ran that command before the
    typed-yes prompt (found in this review, C12). The static systemctl/C10
    parsers skip heredoc bodies as prose, so this is the gate for them."""
    allowed = {'$(hostname)', '$(cat "$etc/deploy_key.pub")'}
    seen_unquoted = 0
    for s in SCRIPTS:
        lines = (BIN / s).read_text(encoding="utf-8").splitlines()
        term = None
        for n, line in enumerate(lines, 1):
            if term is not None:
                if line.strip() == term:
                    term = None
                    continue
                assert "`" not in line, f"{s}:{n}: a backtick in an unquoted heredoc runs a command: {line.strip()}"
                for m in re.finditer(r"\$\((?:[^()]|\([^()]*\))*\)", line):
                    assert m.group(0) in allowed, f"{s}:{n}: {m.group(0)} in an unquoted heredoc"
                continue
            if line.lstrip().startswith("#"):
                continue
            m = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", line)
            if m and not m.group(1):
                term = m.group(2)
                seen_unquoted += 1
    assert seen_unquoted >= 6, "the scanner found the plan/DONE/KEYMSG/CF heredocs"


def _fn(script: str, name: str) -> str:
    src = _live((BIN / script).read_text(encoding="utf-8"))
    i = src.index(f"{name}() {{")
    j = src.find("\n}\n", i)
    one_line_end = src.find("; }\n", i)
    if one_line_end != -1 and (j == -1 or one_line_end < j) and "\n" not in src[i:one_line_end]:
        return src[i:one_line_end + 4]
    return src[i:j + 3]


@pytest.mark.parametrize("script,fn", [("cutover.sh", "gh"), ("rollback.sh", "gh"), ("preflight.sh", "probe")])
def test_a_transport_failure_reads_000_never_000000(tmp_path, script, fn):
    """curl -w '%{http_code}' already prints 000 when nothing answers; the old
    `|| echo 000` appended a second one (the stop_watcher bug CLAUDE.md
    records) -- preflight printed `yahoo=000000` on this very sandbox."""
    fake = tmp_path / "curl"
    mode = tmp_path / "mode"
    fake.write_text(f'#!/bin/sh\nif [ "$(cat "{mode}")" = down ]; then printf 000; exit 7; fi\nprintf 204\n')
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    harness = (f'gh_body="{tmp_path}/b"; gh_cfg="{tmp_path}/c"\nset -euo pipefail\n' + _fn(script, fn) +
               f'\nout="$({fn} GET /x)"; printf "[%s]" "$out"\n')
    for m, want in (("down", "[000]"), ("up", "[204]")):
        mode.write_text(m)
        r = _run(["bash", "-c", harness], env=env)
        assert r.returncode == 0 and r.stdout == want, (m, r.stdout, r.stderr)
    for s in ("cutover.sh", "rollback.sh", "preflight.sh"):
        assert "|| echo 000" not in _code_only(_live((BIN / s).read_text(encoding="utf-8"))), s


def test_preflight_never_passes_a_check_on_a_file_that_is_missing():
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    loop = pf[pf.index('for f in "$etc/jobs.env" "$etc/api.env"; do'):]
    assert loop.index('[ -r "$f" ] || continue') < loop.index('pass "$f has no CHANGE_ME"'), \
        "a missing env file used to print 'has no CHANGE_ME' as a PASS"


def test_preflight_tells_a_busy_port_from_a_port_check_that_could_not_run():
    pf = _live((BIN / "preflight.sh").read_text(encoding="utf-8"))
    assert 'ports_out="$("$here/ports.sh" --check 2>&1)" || ports_rc=$?' in pf
    block = pf[pf.index('case "$ports_rc" in'):pf.index("esac", pf.index('case "$ports_rc" in'))]
    assert '0) pass' in block and '1) fail ":80/:443 are held by another process' in block
    assert '*) fail "could not list the TCP listeners' in block, "ss missing is not 'someone holds :80'"
    po = _live((BIN / "ports.sh").read_text(encoding="utf-8"))
    assert '[ "$check" = "1" ] && exit 2' in po


def test_cutover_yes_never_auto_confirms_the_manual_cloudflare_step():
    co = _live((BIN / "cutover.sh").read_text(encoding="utf-8"))
    guard = ('if [ "$assume_yes" = "1" ] && { [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || '
             '[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ] || [ -z "${CF_PAGES_PROJECT:-}" ]; }; then')
    assert guard in co, "--yes with no Pages API inputs must stop, not skip the manual step"
    assert co.index(guard) < co.index("v5ctl enable --now vivek5-caddy.service"), "refused before anything starts"


def test_install_precreates_the_api_restart_flag_for_the_jobs_user():
    live = _live((BIN / "install.sh").read_text(encoding="utf-8"))
    assert '[ -e "$state/api-restart" ] || install -m 0644 -o vivek5 -g vivek5-spool /dev/null "$state/api-restart"' in live


def test_a_killed_runner_releases_its_flocks_even_while_a_step_child_lives_on(tmp_path):
    """KillMode=mixed SIGTERMs the runner (python dies without running its
    finally) and SIGKILLs the rest of the cgroup. The locks must not depend on
    that second half: the runner's lock fds are close-on-exec, so a step
    child that outlives it (here: deliberately orphaned) holds NO lock."""
    from scanner.vps import locks as L
    pidfile = tmp_path / "step.pid"
    # the step is started exactly as the runner starts one (default_exec)
    code = ("import os, threading, time\n"
            "from scanner.vps import locks as L\n"
            "from scanner.vps.__main__ import default_exec\n"
            f"ls = L.LockSet({str(tmp_path)!r}, ('scan', 'crypto_bot.yml'))\n"
            "ls.acquire(5)\n"
            f"argv = ['sh', '-c', 'echo $$ > {pidfile}; exec sleep 60']\n"
            "threading.Thread(target=lambda: default_exec(argv, cwd='.', env=dict(os.environ)), daemon=True).start()\n"
            "print('held', flush=True)\n"
            "time.sleep(60)\n")
    runner = subprocess.Popen([sys.executable, "-c", code], cwd=str(ROOT), stdout=subprocess.PIPE, text=True)
    assert runner.stdout.readline().strip() == "held"
    import time
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    child_pid = int(pidfile.read_text())
    try:
        probe = L.LockSet(tmp_path, ("scan", "crypto_bot.yml"), repo_shared=False)
        with pytest.raises(L.LockTimeout):
            probe.acquire(0.3)                                   # held while the runner lives
        runner.kill()                                            # SIGKILL: no finally, no release()
        runner.wait()
        os.kill(child_pid, 0)                                    # the step child is still alive...
        assert probe.acquire(2) < 2                              # ...and every lock is free anyway
        probe.release()
    finally:
        try:
            os.kill(child_pid, 9)
        except ProcessLookupError:
            pass
    for svc in _services():
        if _keys(_unit(svc)).get("Type") == ["oneshot"]:
            assert _keys(_unit(svc))["KillMode"] == ["mixed"], svc

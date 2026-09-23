"""scripts/momentum_due.py -- the gate that decides which Momentum market a
wake-up screens. The workflow-shape pins live in test_momentum_workflow.py;
these drive the shipped functions.

Nothing here reads the live public/data/momentum files. A test that reads the
tape goes red on a quiet day (CLAUDE.md, "The Lighthouse budget was measuring
the TAPE"), so the 2026-09-23 incident is replayed from its recorded stamps.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import pathlib
import sys
import zoneinfo

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "momentum_due.py"
UTC = dt.timezone.utc

_spec = importlib.util.spec_from_file_location("momentum_due", SCRIPT)
due = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(due)

from scanner import config as scfg  # noqa: E402
from scanner.momentum import config as mcfg  # noqa: E402


def Z(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


# The committed stamps on 2026-09-23, when the 06:30 UTC ASX cron was dropped.
INCIDENT = {
    "asx": Z("2026-09-22T07:25:32Z"),
    "nasdaq": Z("2026-09-22T23:45:15Z"),
    "crypto": Z("2026-09-23T04:56:53Z"),
}


# ---------------------------------------------------------------------------
# the due instant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("now, market, expected", [
    # AEST (winter): 16:30 Sydney = 06:30Z
    ("2026-09-23T11:00:00Z", "asx", "2026-09-23T06:30:00Z"),
    # AEDT (summer): 16:30 Sydney = 05:30Z
    ("2026-01-14T07:00:00Z", "asx", "2026-01-14T05:30:00Z"),
    # EDT: 16:30 New York = 20:30Z
    ("2026-09-23T22:00:00Z", "nasdaq", "2026-09-23T20:30:00Z"),
    # EST: 16:30 New York = 21:30Z
    ("2026-01-14T22:00:00Z", "nasdaq", "2026-01-14T21:30:00Z"),
    # before today's close it is still yesterday's
    ("2026-09-23T03:00:00Z", "asx", "2026-09-22T06:30:00Z"),
    # the weekend owes Friday
    ("2026-09-26T12:00:00Z", "asx", "2026-09-25T06:30:00Z"),
    ("2026-09-28T03:00:00Z", "asx", "2026-09-25T06:30:00Z"),
    ("2026-09-27T12:00:00Z", "nasdaq", "2026-09-25T20:30:00Z"),
    # crypto every day at 00:30Z, weekends included
    ("2026-09-26T00:29:00Z", "crypto", "2026-09-25T00:30:00Z"),
    ("2026-09-26T00:30:00Z", "crypto", "2026-09-26T00:30:00Z"),
])
def test_due_point(now, market, expected):
    assert due.due_point(market, Z(now)) == Z(expected)


def test_the_sessions_are_read_from_scanner_config_not_restated():
    """One session table in the repo. The gate must not carry its own hours or
    zones -- a second copy is a second thing to keep in step."""
    src = SCRIPT.read_text(encoding="utf-8")
    for literal in ("Australia/Sydney", "America/New_York", "(10, 0", "(9, 30"):
        assert literal not in src, literal
    assert "scfg.VIVEK_JOURNAL_SESSION" in src
    assert "scfg.MARKETS[market].timezone" in src
    assert mcfg.PUBLISH_AFTER_CLOSE_MIN == 30
    assert mcfg.CRYPTO_DUE_UTC == (0, 30)


# ---------------------------------------------------------------------------
# never inside a session
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("monday", [dt.date(2026, 1, 12), dt.date(2026, 7, 13)])
@pytest.mark.parametrize("market", ["asx", "nasdaq"])
def test_an_equity_market_is_NEVER_picked_inside_its_session(monday, market):
    """Swept, not sampled: every 10 minutes for a full week in each DST regime,
    with a file so stale it is always owed something. The screen does not drop
    a forming bar (spec 5.11), so the gate is the only thing standing between
    a late wake-up and a signal computed off a bar that is still moving."""
    tz = zoneinfo.ZoneInfo(scfg.MARKETS[market].timezone)
    oh, om, ch, cm = scfg.VIVEK_JOURNAL_SESSION[market]
    ancient = Z("2020-01-01T00:00:00Z")
    stamps = {"asx": None, "nasdaq": None, "crypto": Z("2099-01-01T00:00:00Z")}
    stamps[market] = ancient
    other = "nasdaq" if market == "asx" else "asx"
    stamps[other] = Z("2099-01-01T00:00:00Z")

    start = dt.datetime.combine(monday, dt.time(0), tzinfo=UTC)
    picked = 0
    for step in range(7 * 24 * 6):
        now = start + dt.timedelta(minutes=10 * step)
        chosen, _ = due.pick(stamps, now)
        local = now.astimezone(tz)
        opens = local.replace(hour=oh, minute=om, second=0, microsecond=0)
        settles = local.replace(hour=ch, minute=cm, second=0, microsecond=0) \
            + dt.timedelta(minutes=mcfg.PUBLISH_AFTER_CLOSE_MIN)
        in_blackout = local.weekday() < 5 and opens <= local < settles
        if in_blackout:
            assert chosen != market, f"{market} picked at {local:%a %H:%M %Z}"
        elif chosen == market:
            picked += 1
    assert picked > 0, "the sweep never picked the market - it proves nothing"


def test_a_missed_window_waits_for_the_next_close_rather_than_screening_mid_session():
    # Tuesday's ASX run never happened; it is now Wednesday 12:00 Sydney.
    now = Z("2026-09-23T02:00:00Z")
    ok, point, why = due.status("asx", Z("2026-09-21T07:00:00Z"), now)
    assert not ok and point == Z("2026-09-22T06:30:00Z") and "session" in why
    # ...and at Wednesday's 16:30 it is due again, for Wednesday's close.
    ok, point, _ = due.status("asx", Z("2026-09-21T07:00:00Z"), Z("2026-09-23T06:30:00Z"))
    assert ok and point == Z("2026-09-23T06:30:00Z")


# ---------------------------------------------------------------------------
# which one, when several are due
# ---------------------------------------------------------------------------

def test_the_2026_09_23_incident_replayed_on_the_piggyback_ladder():
    """With the recorded stamps, the first morning_plays run after the close
    (the pinger's 06:45Z) picks ASX; the 06:15Z one does not, because it is
    before the close ASX owes."""
    assert due.pick(INCIDENT, Z("2026-09-23T06:15:30Z"))[0] is None
    assert due.pick(INCIDENT, Z("2026-09-23T06:45:30Z"))[0] == "asx"
    # once ASX publishes, the rest of the ladder finds nothing due
    after = dict(INCIDENT, asx=Z("2026-09-23T06:52:00Z"))
    for hhmm in ("07:15", "07:45", "08:15", "10:45"):
        assert due.pick(after, Z(f"2026-09-23T{hhmm}:30Z"))[0] is None


def test_newest_due_first_so_a_stuck_market_cannot_starve_the_others():
    """Crypto is stuck (it keeps failing, so its file never moves). ASX then
    becomes due and must be screened first; crypto retries in the gaps."""
    stamps = {"asx": Z("2026-09-22T07:00:00Z"), "nasdaq": Z("2026-09-22T23:00:00Z"),
              "crypto": Z("2026-09-21T01:00:00Z")}
    assert due.pick(stamps, Z("2026-09-23T05:00:00Z"))[0] == "crypto"
    assert due.pick(stamps, Z("2026-09-23T07:00:00Z"))[0] == "asx"
    stamps["asx"] = Z("2026-09-23T07:10:00Z")
    assert due.pick(stamps, Z("2026-09-23T07:30:00Z"))[0] == "crypto"


def test_a_missing_or_unreadable_file_counts_as_due(tmp_path):
    (tmp_path / "asx.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "nasdaq.json").write_text(json.dumps({"generated_at": 7}), encoding="utf-8")
    stamps = due.read_stamps(tmp_path)          # crypto.json absent
    assert stamps == {"asx": None, "nasdaq": None, "crypto": None}
    chosen, lines = due.pick(stamps, Z("2026-09-23T22:00:00Z"))
    assert chosen == "nasdaq"                    # newest due instant
    assert sum("DUE" in ln for ln in lines) == 3


@pytest.mark.parametrize("raw, expected", [
    ("2026-09-22T07:25:32+00:00", "2026-09-22T07:25:32Z"),
    ("2026-09-22T07:25:32Z", "2026-09-22T07:25:32Z"),
    ("2026-09-22T17:25:32+10:00", "2026-09-22T07:25:32Z"),
    ("2026-09-22T07:25:32", "2026-09-22T07:25:32Z"),      # naive = UTC
])
def test_parse_stamp(raw, expected):
    assert due.parse_stamp(raw) == Z(expected)


@pytest.mark.parametrize("raw", [None, "", "yesterday", 1695368732])
def test_parse_stamp_refuses_junk(raw):
    assert due.parse_stamp(raw) is None


# ---------------------------------------------------------------------------
# the CLI the workflow calls
# ---------------------------------------------------------------------------

def _write(dirpath, stamps):
    for market, stamp in stamps.items():
        (dirpath / f"{market}.json").write_text(
            json.dumps({"generated_at": stamp.isoformat()}), encoding="utf-8")


def test_the_cli_writes_the_pick_to_github_output(tmp_path, monkeypatch, capsys):
    _write(tmp_path, INCIDENT)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert due.main(["--dir", str(tmp_path), "--now", "2026-09-23T06:45:30Z"]) == 0
    assert out.read_text(encoding="utf-8") == "market=asx\n"
    printed = capsys.readouterr().out
    assert "picked: asx" in printed
    assert printed.isascii(), "scanner-side prints stay ASCII (cp1252 consoles)"


def test_the_cli_writes_an_EMPTY_market_when_nothing_is_due(tmp_path, monkeypatch):
    _write(tmp_path, INCIDENT)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert due.main(["--dir", str(tmp_path), "--now", "2026-09-23T06:15:30Z"]) == 0
    assert out.read_text(encoding="utf-8") == "market=\n", (
        "the workflow skips every later step on an empty market")


# ---------------------------------------------------------------------------
# it runs before pip install
# ---------------------------------------------------------------------------

def _imports(path: pathlib.Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            names.add("." + (node.module or ""))
    return names


def test_the_gate_and_everything_it_imports_is_stdlib_only():
    """The gate runs on the runner's own python3 BEFORE setup-python and pip,
    so it -- and the two constants modules it reads -- may import nothing
    outside the standard library. pandas arriving in scanner/config.py would
    turn every no-op wake-up into an ImportError."""
    allowed_first_party = {"scanner", "scanner.config", "scanner.momentum",
                           "scanner.momentum.config", ".config"}
    files = [SCRIPT, ROOT / "scanner" / "__init__.py", ROOT / "scanner" / "config.py",
             ROOT / "scanner" / "momentum" / "__init__.py",
             ROOT / "scanner" / "momentum" / "config.py"]
    for path in files:
        for name in _imports(path):
            top = name.split(".")[0]
            if name in allowed_first_party or name.startswith("scanner.config.") \
                    or name.startswith("scanner.momentum.config") or name.startswith(".config"):
                continue
            if name.startswith("scanner."):
                pytest.fail(f"{path.relative_to(ROOT)} imports {name}")
            assert top in sys.stdlib_module_names or top == "__future__", (
                f"{path.relative_to(ROOT)} imports non-stdlib {name}")

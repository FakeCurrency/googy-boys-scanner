"""The vivek5-checkin skill (.claude/skills/vivek5-checkin/, 2026-10-08).

The owner says "how's the scanner going" and gets a plain-English report. Its
script, scripts/scanner_status.py, reads committed files only and prints what
the repo says about today's scans, the after-close lenses and the paper book.
It is stdlib-only (it runs with `python3 -I` from any checkout), so it COPIES
a few times out of config instead of importing them. These tests are what stop
that copy drifting:

* parity: the copied windows, close gates and Momentum due times equal config;
* read-only: the script can only run `git show/log/ls-tree/rev-parse` and
  `git fetch`, opens no file, imports nothing outside the stdlib list, and the
  skill's never-list still names the four endpoints that dispatch real work;
* behaviour: a fixture repo with a known day in it (a missed ASX hour, an
  unpriced coin, a position near its stop, an open and a stop-out) produces the
  right lines and flags, and the same day without the faults says nothing looks
  wrong. None of it reads the live repo's data, so a quiet tape cannot turn it
  red (the Lighthouse lesson, CLAUDE.md).
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scanner import config
from scanner.momentum import config as mcfg

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "vivek5-checkin"
SCRIPT = SKILL / "scripts" / "scanner_status.py"
MEL = ZoneInfo("Australia/Melbourne")


def _mod():
    spec = importlib.util.spec_from_file_location("scanner_status_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# parity with config
def test_scan_windows_match_config():
    m = _mod()
    for market, (tz, start, end) in config.MARKET_SCAN_WINDOWS.items():
        (h0, h1, wtz) = m.WINDOW[market]
        assert wtz.key == tz, market
        assert h0[0] * 60 + h0[1] == start, market
        assert h1[0] * 60 + h1[1] == end, market
    assert set(m.WINDOW) == set(config.MARKET_SCAN_WINDOWS)


def test_close_gates_match_the_digest_gate():
    m = _mod()
    for gate in config.MORNING_PLAYS_SLOT_GATE.values():
        assert m.CLOSE_GATE[gate["market"]] == (gate["hour"], gate["minute"]), gate
        assert m.WINDOW[gate["market"]][2].key == gate["tz"], gate
    assert set(m.CLOSE_GATE) == {g["market"] for g in config.MORNING_PLAYS_SLOT_GATE.values()}


def test_momentum_due_times_match_momentum_due():
    """scripts/momentum_due.py: a stock market owes its file from the session
    close + PUBLISH_AFTER_CLOSE_MIN; crypto from CRYPTO_DUE_UTC."""
    m = _mod()
    for market, ((h, mi), tz) in m.MOMENTUM_OWE.items():
        close_h, close_m = config.VIVEK_JOURNAL_SESSION[market][2:]
        assert h * 60 + mi == close_h * 60 + close_m + mcfg.PUBLISH_AFTER_CLOSE_MIN, market
        assert tz.key == config.MARKETS[market].timezone, market
    assert tuple(m.MOMENTUM_CRYPTO_DUE_UTC) == tuple(mcfg.CRYPTO_DUE_UTC)


def test_every_cron_job_id_in_the_skill_is_one_claude_md_knows():
    known = set(re.findall(r"\b8\d{6}\b", (ROOT / "CLAUDE.md").read_text(encoding="utf-8")))
    for doc in (SKILL / "SKILL.md", SKILL / "references" / "schedule.md", SKILL / "references" / "runs.md"):
        ids = set(re.findall(r"\b8\d{6}\b", doc.read_text(encoding="utf-8")))
        assert ids <= known, f"{doc.name} names cron-job.org jobs CLAUDE.md does not: {sorted(ids - known)}"


# ---------------------------------------------------------------------------
# read-only by construction
STDLIB = {"__future__", "argparse", "datetime", "json", "subprocess", "sys", "zoneinfo"}
GIT_READS = {"show", "log", "ls-tree", "rev-parse"}


def _tree():
    return ast.parse(SCRIPT.read_text(encoding="utf-8"))


def test_the_script_imports_only_the_stdlib_list():
    mods = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= STDLIB, f"not in the reviewed stdlib list: {sorted(mods - STDLIB)}"


def test_the_script_only_reads_git_and_writes_nothing():
    calls = [n for n in ast.walk(_tree()) if isinstance(n, ast.Call)]
    names = {getattr(c.func, "id", None) or getattr(c.func, "attr", None) for c in calls}
    assert "open" not in names, "the status script must not open (or write) any file"
    assert not names & {"system", "popen", "Popen", "call", "check_call", "check_output", "urlopen"}
    git_subs = [c.args[0].value for c in calls
                if getattr(c.func, "id", None) == "git" and c.args and isinstance(c.args[0], ast.Constant)]
    git_dyn = [c for c in calls if getattr(c.func, "id", None) == "git"
               and (not c.args or not isinstance(c.args[0], ast.Constant))]
    assert git_subs and set(git_subs) <= GIT_READS, sorted(set(git_subs) - GIT_READS)
    assert not git_dyn, "every git() call must name its subcommand literally"
    runs = [c for c in calls if getattr(c.func, "attr", None) == "run"]
    argvs = []
    for c in runs:
        argv = c.args[0]
        assert isinstance(argv, ast.List), "subprocess.run must take a literal argv"
        head = [e.value for e in argv.elts if isinstance(e, ast.Constant)]
        argvs.append(head)
        assert head[:1] == ["git"], head
    # exactly two: the git() helper (its subcommand is checked above) and the fetch
    assert sorted(argvs) == [["git", "-C"], ["git", "-C", "fetch", "-q", "origin", "main"]], argvs


def test_the_script_is_ascii_for_windows_consoles():
    """Project rule 9: cp1252 consoles choke on arrows and em dashes."""
    SCRIPT.read_bytes().decode("ascii")


def test_the_never_list_still_names_the_endpoints_that_dispatch_real_work():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    never = text[text.index("Never, during a check-in"):]
    for ep in ("/api/heartbeat", "/api/scan", "/api/close", "/api/morning_plays"):
        assert ep in never, ep
    assert "Re-send the digest" in never and "PhaseMap by hand" in never


def test_skill_frontmatter():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    front = text.split("---", 2)[1]
    name = re.search(r"^name:\s*(\S+)\s*$", front, re.M).group(1)
    desc = re.search(r'^description:\s*"(.+)"\s*$', front, re.M).group(1)
    assert name == SKILL.name == "vivek5-checkin"
    assert 100 < len(desc) <= 1024 and "<" not in desc and ">" not in desc


# ---------------------------------------------------------------------------
# helpers
def test_last_weekday_at_skips_the_weekend_and_follows_new_york_dst():
    m = _mod()
    sun = dt.datetime(2026, 10, 11, 12, 0, tzinfo=MEL)
    got = m.last_weekday_at(sun, (16, 40), m.SYD)
    assert got.astimezone(m.SYD).strftime("%a %H:%M") == "Fri 16:40"
    # New York leaves EDT on 1 Nov 2026: its 16:05 close moves from 07:05 to 08:05 Melbourne.
    for now, want in ((dt.datetime(2026, 10, 30, 9, 0, tzinfo=MEL), "Fri 07:05"),
                      (dt.datetime(2026, 11, 3, 9, 0, tzinfo=MEL), "Tue 08:05")):
        assert m.last_weekday_at(now, (16, 5), m.NY).astimezone(MEL).strftime("%a %H:%M") == want


def test_in_window_is_inclusive_and_weekday_only():
    m = _mod()
    syd = m.SYD
    assert m.in_window("asx", dt.datetime(2026, 10, 8, 11, 0, tzinfo=syd))
    assert m.in_window("asx", dt.datetime(2026, 10, 8, 16, 45, tzinfo=syd))
    assert not m.in_window("asx", dt.datetime(2026, 10, 8, 16, 46, tzinfo=syd))
    assert not m.in_window("asx", dt.datetime(2026, 10, 10, 12, 0, tzinfo=syd))  # Saturday


# ---------------------------------------------------------------------------
# behaviour on a fixture repo
NOW = "2026-10-08T17:25:00+11:00"   # Thu, after the ASX close and the digest
UTC = dt.timezone.utc


def _u(s):
    return dt.datetime.fromisoformat(s).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _asx_scans(skip_1pm):
    hm = ["11:15", "12:16", "13:14", "14:16", "15:16", "16:15", "16:45"]
    if skip_1pm:
        hm.remove("13:14")
    return [_u(f"2026-10-08T{x}:00+11:00") for x in hm]


NASDAQ = [_u(f"2026-10-07T{x}:00-04:00") for x in
          ("10:43", "11:14", "12:14", "13:14", "14:14", "15:14", "16:10", "16:16")]
CRYPTO = [_u((dt.datetime.fromisoformat(NOW) - dt.timedelta(hours=h)).replace(minute=25).isoformat())
          for h in range(23, -1, -1)]


def _pos(pid, sym, **kw):
    p = {"id": pid, "symbol": sym, "grade": "A+", "timeframe": "3D", "entry_type": "reclaim",
         "entry": 10.0, "stop": 9.0, "risk": 1.0, "last_mark": 10.5, "entry_date": "2026-10-01"}
    p.update(kw)
    return p


def _book(market, open_, closed, updated):
    return {"updated_at": updated, "summary": {"updated_day": "2026-10-08"},
            "guard": {market: {"breached": False, "session_usd": -393.28, "limit_usd": 4500,
                               "week_usd": -1131.2, "week_limit_usd": 9000}},
            "open": open_, "closed": closed}


def _files(*, faults):
    wafd = _pos("n1", "WAFD", entry=30.0, stop=28.0, risk=2.0, last_mark=29.0)
    adp = _pos("n2", "ADP", entry=263.12, stop=247.41, risk=15.71, last_mark=265.0)
    aar = _pos("a1", "AAR", entry=0.18, stop=0.1609, risk=0.0191,
               last_mark=0.165 if faults else 0.19)
    nic = _pos("a2", "NIC", entry_date="2026-09-13" if faults else "2026-10-01")
    bnb = _pos("c1", "BNB", **({"unpriced_runs": 2} if faults else {}))
    closed_wafd = dict(wafd, exit_reason="stop", exit_date="2026-10-07", realized_r=-1.11)
    asx = _asx_scans(skip_1pm=faults)
    then = {
        "journal/vivek_bot_book.asx.json": _book("asx", [aar, nic], [], "2026-10-07T05:46:00Z"),
        "journal/vivek_bot_book.nasdaq.json": _book("nasdaq", [wafd], [], "2026-10-06T20:16:00Z"),
        "journal/vivek_bot_book.crypto.json": _book("crypto", [bnb], [], "2026-10-07T00:25:00Z"),
    }
    now = {
        "public/data/funnel_history.json": {"markets": {
            "asx": {"t": asx, "trigger": ["heartbeat"] * len(asx)},
            "nasdaq": {"t": NASDAQ, "trigger": ["heartbeat"] * 6 + ["cron", "heartbeat"]},
            "crypto": {"t": CRYPTO, "trigger": ["heartbeat"] * len(CRYPTO)}}},
        "data/scan_health.json": {"asx": {"dry": 0}, "nasdaq": {"dry": 0}, "crypto": {"dry": 0}},
        "public/data/asx_prices.json": {"generated_at": "2026-10-08T16:45:13+11:00"},
        "public/data/nasdaq_prices.json": {"generated_at": "2026-10-07T16:16:04-04:00"},
        "public/data/crypto_prices.json": {"generated_at": CRYPTO[-1]},
        "public/data/asx_vivek.json": {"scanned": 1726, "universe_size": 1923, "from_cache": 0,
                                       "errors": 0, "funnel": {"setups": 225}},
        "public/data/nasdaq_vivek.json": {"scanned": 1430, "universe_size": 1430, "from_cache": 0,
                                          "errors": 0, "funnel": {"setups": 300}},
        "public/data/momentum/asx.json": {"generated_at": "2026-10-08T06:19:00Z", "last_closed_bar": "2026-10-08",
                                          "summary": {"hits": 6}},
        "public/data/momentum/nasdaq.json": {"generated_at": "2026-10-07T20:49:00Z",
                                             "last_closed_bar": "2026-10-07", "summary": {"hits": 4}},
        "public/data/momentum/crypto.json": {"generated_at": "2026-10-08T01:13:00Z",
                                             "last_closed_bar": "2026-10-07", "summary": {"hits": 2}},
        "public/data/ignition/crypto.json": {"generated_at": "2026-10-08T05:57:00Z", "last_closed_bar": "2026-10-07"},
        "public/data/ignition/asx.json": {"generated_at": "2026-10-07T13:43:00Z", "last_closed_bar": "2026-10-07"},
        "public/data/phasemap/asx/latest.json": {"run_date": "2026-10-08"},
        "data/alert_forward_returns.json": {"updated_at": "2026-10-08T02:03:00Z"},
        "public/data/reco_note.json": {"generated_at": "2026-10-07T15:49:00Z"},
        "backups/2026-10-08T01-14-45/vivek_bot_book.json": {},
        "public/data/bot_rules.json": {"max_open_total": 4, "max_hold_days": 28},
        "journal/vivek_bot_book.asx.json": _book("asx", [aar, nic], [], "2026-10-08T05:46:08Z"),
        "journal/vivek_bot_book.nasdaq.json": _book("nasdaq", [adp], [closed_wafd], "2026-10-07T20:16:00Z"),
        "journal/vivek_bot_book.crypto.json": _book("crypto", [bnb], [], "2026-10-08T06:22:00Z"),
        "public/data/phasemap/alert_history.json": {"entries": [
            {"date": "2026-10-08T05:46:00Z", "count": 3, "market": "asx", "ticker": "DOW", "side": "long"},
            {"date": "2026-10-08T05:46:00Z", "count": 2, "market": "asx", "ticker": "GNC", "side": "long"},
            {"date": "2026-10-01T05:46:00Z", "count": 3, "market": "asx", "ticker": "OLD", "side": "long"}]},
    }
    return then, now


def _commit(repo, files, when):
    for path, doc in files.items():
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(doc), encoding="utf-8")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", when], check=True, env=env)


def _run(tmp_path, *, faults, extra=()):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    then, now = _files(faults=faults)
    _commit(repo, then, "2026-10-07T12:00:00+11:00")
    _commit(repo, now, "2026-10-08T17:20:00+11:00")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(repo), "--rev", "HEAD",
                          "--now", NOW, *extra], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "could not read a section" not in out.stdout, out.stdout
    return out.stdout


def _verdict(text):
    """(the whole verdict, only its LOOKS WRONG list)"""
    v = text[text.index("== VERDICT"):]
    end = v.index("NOT DUE YET") if "NOT DUE YET" in v else v.index("NOT CHECKED HERE")
    return v, v[:end]


def test_a_day_with_faults_is_reported_line_by_line(tmp_path):
    text = _run(tmp_path, faults=True)
    v, wrong = _verdict(text)
    # scans
    assert "asx: the Thu 08 Oct session: 6 scans" in text
    assert "closing scan: Thu 16:45 (counts from 16:40 Sydney)" in text
    assert "nasdaq: the Wed 07 Oct New York session: 8 scans" in text
    assert "closing scan: Thu 07:10 (counts from 16:05 New York)" in text
    assert "crypto: 24 scans in the last 24 h" in text
    assert "ASX: 1 gap(s) over 80 min" in wrong and "12:16-14:16" in wrong
    assert "NASDAQ" not in wrong                       # a full NASDAQ session is not news
    # lenses
    assert "momentum asx: Thu 17:19" in text and "6 hits - fresh" in text
    assert "ignition crypto: Thu 16:57" in text and "STALE" not in text
    assert "ignition ASX not screened since the Thu 16:40 close (0.8 h)" in v
    assert "ignition" not in wrong.lower()            # not due yet is not wrong
    # paper bot
    assert "OPENED ADP A+ 3D reclaim at 263.12, stop 247.41" in text
    assert "CLOSED WAFD 2026-10-07 stop (the rules) -1.11R" in text
    assert "WATCH AAR: 0.21R above its stop" in text
    assert "WATCH NIC: time stop in 4 day(s)" in text
    assert "total: 4/4 open - book FULL" in text
    assert "crypto: 1 held name(s) had no price on the last run" in wrong and "BNB (2 runs)" in wrong
    assert "A$-393 of -A$4,500" in text
    # confluence: two new since yesterday, one of them a triple; the 1 Oct one is old
    assert "new multi-lens alignments since Wed 17:25: 2" in text
    assert "TRIPLES (all three lenses agree): asx DOW long" in text and "asx OLD" not in text


def test_the_same_day_without_faults_says_nothing_looks_wrong(tmp_path):
    text = _run(tmp_path, faults=False)
    v, wrong = _verdict(text)
    assert "LOOKS WRONG: nothing in the repo data" in v, wrong
    assert "asx: the Thu 08 Oct session: 7 scans" in text
    assert "WATCH" not in text
    assert "NOT DUE YET" in v                            # Ignition ASX after the close


def test_since_takes_git_dates_and_bare_times_mean_melbourne(tmp_path):
    # 17:21 Thursday is after the last commit (17:20), so nothing changed since
    text = _run(tmp_path, faults=False, extra=("--since", "2026-10-08 17:21"))
    assert "PAPER BOT (changes since Thu 08 Oct 17:21)" in text
    assert "OPENED" not in text and "CLOSED" not in text


def test_since_accepts_git_relative_dates(tmp_path):
    """Not ISO, so it goes through `git rev-parse --since` (no GNU date needed)."""
    text = _run(tmp_path, faults=False, extra=("--since", "3 days ago"))
    assert "PAPER BOT (changes since " in text


def test_a_market_missing_its_close_is_flagged_once_the_gate_has_passed(tmp_path):
    late = "2026-10-08T17:25:00+11:00"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    then, now = _files(faults=False)
    now["public/data/funnel_history.json"]["markets"]["asx"]["t"] = _asx_scans(False)[:-1]  # no 16:45
    now["public/data/funnel_history.json"]["markets"]["asx"]["trigger"] = ["heartbeat"] * 6
    _commit(repo, then, "2026-10-07T12:00:00+11:00")
    _commit(repo, now, "2026-10-08T17:20:00+11:00")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(repo), "--rev", "HEAD",
                          "--now", late], capture_output=True, text=True, check=True).stdout
    _, wrong = _verdict(out)
    assert "ASX: no closing scan for the Thu 08 Oct session" in wrong
    # ...and before 16:55 Sydney it is only "not due yet"
    early = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(repo), "--rev", "HEAD",
                            "--now", "2026-10-08T16:50:00+11:00"], capture_output=True, text=True,
                           check=True).stdout
    v, wrong = _verdict(early)
    assert "no closing scan" not in wrong and "ASX closing scan not due yet" in v


@pytest.mark.parametrize("bad", ["public/data/funnel_history.json", "journal/vivek_bot_book.asx.json"])
def test_one_unreadable_file_costs_one_section_not_the_report(tmp_path, bad):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    then, now = _files(faults=False)
    _commit(repo, then, "2026-10-07T12:00:00+11:00")
    _commit(repo, now, "2026-10-08T17:20:00+11:00")
    (repo / bad).write_text("{not json", encoding="utf-8")
    _commit(repo, {}, "2026-10-08T17:21:00+11:00")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(repo), "--rev", "HEAD",
                          "--now", NOW], capture_output=True, text=True)
    assert out.returncode == 0
    assert "== VERDICT FROM REPO DATA" in out.stdout and "could not read a section" in out.stdout
    assert "== CONFLUENCE" in out.stdout

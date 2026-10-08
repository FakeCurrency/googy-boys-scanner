"""The vivek5-checkin skill (.claude/skills/vivek5-checkin/, 2026-10-08).

The owner says "how's the scanner going" and gets a plain-English report. Its
script, scripts/scanner_status.py, reads committed files only and prints what
the repo says about today's scans, the after-close lenses and the paper book.
It is stdlib-only (it runs with `python3 -I` from any checkout), so it COPIES
a few times out of config instead of importing them. These tests are what stop
that copy drifting:

* parity: the copied windows, close gates, Momentum due times and Ignition
  bar-final times equal config, and every cron-job.org id the skill names is
  one CLAUDE.md knows;
* read-only: the script can only run `git show/log/ls-tree/rev-parse` and two
  shapes of `git fetch`, opens no file, imports nothing outside a stdlib list,
  and the skill's never-list still carries all five rules;
* behaviour: fixture repos with known days in them (a missed hour, a lost first
  scan, a close still covered by its backstop, a stale everything, a weekend, a
  shallow clone like a cloud session's) produce the right lines in the right
  verdict list, and a clean day says nothing looks wrong. None of it reads the
  live repo's data, so a quiet tape cannot turn it red (the Lighthouse lesson,
  CLAUDE.md), and every git call runs with the user's git config switched off.
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
UTC = dt.timezone.utc
# A developer's commit.gpgsign / init.defaultBranch / hooks must not reach the fixtures.
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


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
    assert set(m.FIRST_PING) == set(m.WINDOW) == set(m.CLOSE_GRACE_MIN)
    for market, hm in m.FIRST_PING.items():   # the first ping sits inside the window
        assert m.WINDOW[market][0] <= hm <= m.WINDOW[market][1]


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


def test_ignition_markets_and_bar_final_times_match_config():
    """scripts/ignition_due.py owes each stock market a screen from
    IGNITION_BAR_FINAL; a market added to IGNITION_MARKETS must be checked too."""
    m = _mod()
    assert {"crypto", *m.IGNITION_BAR_FINAL} == set(config.IGNITION_MARKETS)
    assert set(m.IGNITION_BAR_FINAL) == set(config.IGNITION_BAR_FINAL)
    for market, (tz, hour, minute) in config.IGNITION_BAR_FINAL.items():
        hm, mtz = m.IGNITION_BAR_FINAL[market]
        assert (hm, mtz.key) == ((hour, minute), tz), market


def test_every_cron_job_id_in_the_skill_is_one_claude_md_knows():
    known = set(re.findall(r"\b8\d{6}\b", (ROOT / "CLAUDE.md").read_text(encoding="utf-8")))
    docs = [SKILL / "SKILL.md", SCRIPT, *sorted((SKILL / "references").glob("*.md"))]
    for doc in docs:
        ids = set(re.findall(r"\b8\d{6}\b", doc.read_text(encoding="utf-8")))
        assert ids <= known, f"{doc.name} names cron-job.org jobs CLAUDE.md does not: {sorted(ids - known)}"


# ---------------------------------------------------------------------------
# read-only by construction
STDLIB = {"__future__", "argparse", "datetime", "json", "os", "subprocess", "sys", "zoneinfo"}
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
    tree = _tree()
    # an ALLOW-list of what the os and subprocess modules may be used for
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "subprocess":
                assert node.attr in {"run", "CalledProcessError"}, f"subprocess.{node.attr}"
            if node.value.id == "os":
                assert node.attr == "environ", f"os.{node.attr}"
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {getattr(c.func, "id", None) or getattr(c.func, "attr", None) for c in calls}
    assert not names & {"open", "write_text", "write_bytes", "mkdir", "remove", "unlink", "rename", "rmtree"}
    git_calls = [c for c in calls if getattr(c.func, "id", None) == "git"]
    assert git_calls and all(c.args and isinstance(c.args[0], ast.Constant) for c in git_calls), \
        "every git() call must name its subcommand literally"
    assert {c.args[0].value for c in git_calls} <= GIT_READS
    argvs = []
    for c in calls:
        if getattr(c.func, "attr", None) == "run":
            argv = c.args[0]
            assert isinstance(argv, ast.List), "subprocess.run must take a literal argv"
            argvs.append([e.value for e in argv.elts if isinstance(e, ast.Constant)])
    # the git() helper (subcommand checked above), the fetch, and the deepen fetch
    assert sorted(argvs) == [["git", "-C"],
                             ["git", "-C", "fetch", "-q", "--deepen=300", "origin", "main"],
                             ["git", "-C", "fetch", "-q", "origin", "main"]], argvs


def test_the_script_is_ascii_for_windows_consoles():
    """Project rule 9: cp1252 consoles choke on arrows and em dashes."""
    SCRIPT.read_bytes().decode("ascii")


def test_the_never_list_still_carries_every_rule():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    start = text.index("- **Never, during a check-in:**")
    end = text.index("\n- **", start + 1)          # the next top-level bullet
    never = text[start:end]
    for ep in ("/api/heartbeat", "/api/scan", "/api/close", "/api/morning_plays"):
        assert ep in never, ep
    for rule in ("Re-send the digest", "Dispatch PhaseMap by hand", "Dispatch a mutating ops action",
                 "Rerun or cancel a run you did not start"):
        assert rule in never, rule


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
# behaviour on fixture repos
NOW = "2026-10-08T17:25:00+11:00"   # Thu, after the ASX close and the digest
T0 = "2026-10-07T12:00:00+11:00"    # before the default 24 h window
T1 = "2026-10-08T17:20:00+11:00"


def _u(s):
    return dt.datetime.fromisoformat(s).astimezone(UTC).isoformat().replace("+00:00", "Z")


ASX_HM = ["11:15", "12:16", "13:14", "14:16", "15:16", "16:15", "16:45"]
NASDAQ_HM = ["10:43", "11:14", "12:14", "13:14", "14:14", "15:14", "16:10", "16:16"]


def _asx(hm):
    return [_u(f"2026-10-08T{x}:00+11:00") for x in hm]


def _nasdaq(hm):
    return [_u(f"2026-10-07T{x}:00-04:00") for x in hm]


def _crypto(end_iso, n=24):
    end = dt.datetime.fromisoformat(end_iso)
    return [_u((end - dt.timedelta(hours=h)).isoformat()) for h in range(n - 1, -1, -1)]


def _pos(pid, sym, **kw):
    p = {"id": pid, "symbol": sym, "grade": "A+", "timeframe": "3D", "entry_type": "reclaim",
         "entry": 10.0, "stop": 9.0, "risk": 1.0, "last_mark": 10.5, "entry_date": "2026-10-01"}
    p.update(kw)
    return p


def _book(market, open_, closed, updated, **guard):
    g = {"breached": False, "session_usd": -393.28, "limit_usd": 4500, "week_usd": -1131.2, "week_limit_usd": 9000}
    g.update(guard)
    return {"updated_at": updated, "summary": {"updated_day": "2026-10-08"},
            "guard": {market: g}, "open": open_, "closed": closed}


def _files(*, faults=False):
    """(then, now): the repo before the 24 h window and at the check-in."""
    wafd = _pos("n1", "WAFD", entry=30.0, stop=28.0, risk=2.0, last_mark=29.0)
    abc = _pos("n3", "ABC")
    xyz = _pos("n4", "XYZ")
    adp = _pos("n2", "ADP", entry=263.12, stop=247.41, risk=15.71, last_mark=265.0)
    aar = _pos("a1", "AAR", entry=0.18, stop=0.1609, risk=0.0191, last_mark=0.165 if faults else 0.19)
    nic = _pos("a2", "NIC", entry_date="2026-09-13" if faults else "2026-10-01")
    bnb = _pos("c1", "BNB", **({"unpriced_runs": 2} if faults else {}))
    closed = [dict(wafd, exit_reason="stop", exit_date="2026-10-07", realized_r=-1.11),
              dict(xyz, exit_reason="manual", exit_date="2026-10-07", realized_r=0.5),
              dict(abc, exit_date="2026-10-07", realized_r=-0.2)]          # no exit_reason: a human act
    asx = _asx([x for x in ASX_HM if not (faults and x == "13:14")])
    crypto = _crypto(NOW)
    then = {
        "journal/vivek_bot_book.asx.json": _book("asx", [aar, nic], [], "2026-10-07T05:46:00Z"),
        "journal/vivek_bot_book.nasdaq.json": _book("nasdaq", [wafd, abc, xyz], [], "2026-10-06T20:16:00Z"),
        "journal/vivek_bot_book.crypto.json": _book("crypto", [bnb], [], "2026-10-07T00:25:00Z"),
        "public/data/phasemap/asx/latest.json": {"run_date": "2026-10-07"},
    }
    now = {
        "public/data/funnel_history.json": {"markets": {
            "asx": {"t": asx, "trigger": ["heartbeat"] * len(asx)},
            "nasdaq": {"t": _nasdaq(NASDAQ_HM), "trigger": ["heartbeat"] * 6 + ["cron", "heartbeat"]},
            "crypto": {"t": crypto, "trigger": ["heartbeat"] * len(crypto)}}},
        "data/scan_health.json": {"asx": {"dry": 0}, "nasdaq": {"dry": 0}, "crypto": {"dry": 0}},
        "public/data/asx_prices.json": {"generated_at": "2026-10-08T16:45:13+11:00"},
        "public/data/nasdaq_prices.json": {"generated_at": "2026-10-07T16:16:04-04:00"},
        "public/data/crypto_prices.json": {"generated_at": crypto[-1]},
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
        "public/data/ignition/nasdaq.json": {"generated_at": "2026-10-07T21:40:00Z", "last_closed_bar": "2026-10-07"},
        "public/data/phasemap/asx/latest.json": {"run_date": "2026-10-08"},
        "data/alert_forward_returns.json": {"updated_at": "2026-10-08T02:03:00Z"},
        "public/data/reco_note.json": {"generated_at": "2026-10-07T15:49:00Z"},
        "backups/2026-10-08T01-14-45/vivek_bot_book.json": {},
        "public/data/bot_rules.json": {"max_open_total": 4, "max_hold_days": 28},
        "journal/vivek_bot_book.asx.json": _book("asx", [aar, nic], [], "2026-10-08T05:46:08Z"),
        "journal/vivek_bot_book.nasdaq.json": _book("nasdaq", [adp], closed, "2026-10-07T20:16:00Z"),
        "journal/vivek_bot_book.crypto.json": _book("crypto", [bnb], [], "2026-10-08T06:22:00Z"),
        "public/data/phasemap/alert_history.json": {"entries": [
            {"date": "2026-10-08T05:46:00Z", "count": 3, "market": "asx", "ticker": "DOW", "side": "long"},
            {"date": "2026-10-08T05:46:00Z", "count": 2, "market": "asx", "ticker": "GNC", "side": "long"},
            {"date": "2026-10-01T05:46:00Z", "count": 3, "market": "asx", "ticker": "OLD", "side": "long"}]},
    }
    return then, now


def _git(*args):
    subprocess.run(["git", *args], check=True, env=GIT_ENV, capture_output=True)


def _commit(repo, files, when):
    for path, doc in files.items():
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    env = dict(GIT_ENV, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", when], check=True, env=env)


def _repo(tmp_path, then, now, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    _git("init", "-q", "-b", "main", str(repo))
    _commit(repo, {"README": "fixture"}, "2026-10-01T12:00:00+10:00")   # a root that touches nothing else
    _commit(repo, then, T0)
    _commit(repo, now, T1)
    return repo


def _status(repo, now=NOW, *extra, rev="HEAD"):
    args = [sys.executable, "-I", str(SCRIPT), "--repo", str(repo), "--now", now, *extra]
    if rev:
        args += ["--rev", rev]
    out = subprocess.run(args, capture_output=True, text=True, env=GIT_ENV)
    assert out.returncode == 0, out.stderr
    assert "could not read a section" not in out.stdout, out.stdout
    return out.stdout


def _run(tmp_path, *, faults=False, now=NOW, extra=(), edit=None):
    then, files = _files(faults=faults)
    if edit:
        edit(then, files)
    return _status(_repo(tmp_path, then, files), now, *extra)


def _verdict(text):
    """(LOOKS WRONG list, NOT DUE YET list) as text."""
    v = text[text.index("== VERDICT"):]
    tail = v.index("NOT CHECKED HERE")
    if "NOT DUE YET" in v:
        mid = v.index("NOT DUE YET")
        return v[:mid], v[mid:tail]
    return v[:tail], ""


def _set_asx(files, hm):
    t = _asx(hm)
    files["public/data/funnel_history.json"]["markets"]["asx"] = {"t": t, "trigger": ["heartbeat"] * len(t)}


def _set_nasdaq(files, hm):
    t = _nasdaq(hm)
    files["public/data/funnel_history.json"]["markets"]["nasdaq"] = {"t": t, "trigger": ["heartbeat"] * len(t)}


def test_a_day_with_faults_is_reported_line_by_line(tmp_path):
    text = _run(tmp_path, faults=True)
    wrong, waiting = _verdict(text)
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
    assert "ignition nasdaq: Thu 08:40" in text
    assert "ignition ASX not screened since the Thu 16:40 bar went final (0.8 h)" in waiting
    assert "ignition" not in wrong.lower()            # not due yet is not wrong
    assert "phasemap: run_date 2026-10-08, last ran Thu 08 Oct 17:20" in text
    # paper bot
    assert "OPENED ADP A+ 3D reclaim at 263.12, stop 247.41" in text
    assert "CLOSED WAFD 2026-10-07 stop (the rules) -1.11R" in text
    assert "CLOSED XYZ 2026-10-07 manual (you) +0.50R" in text
    assert "CLOSED ABC 2026-10-07 by hand (you) -0.20R" in text
    assert "OPENED ABC" not in text and "OPENED XYZ" not in text
    assert "WATCH AAR: 0.21R above its stop" in text
    assert "WATCH NIC: time stop in 4 day(s)" in text
    assert "total: 4/4 open - book FULL" in text
    assert "crypto: 1 held name(s) had no price on the last run" in wrong and "BNB (2 runs)" in wrong
    assert "A$-393 of -A$4,500" in text
    # confluence: two new since yesterday, one of them a triple; the 1 Oct one is old
    assert "new multi-lens alignments since Wed 17:25: 2" in text
    assert "    TRIPLES (all three lenses agree): asx DOW long\n" in text


def test_the_same_day_without_faults_says_nothing_looks_wrong(tmp_path):
    text = _run(tmp_path)
    wrong, waiting = _verdict(text)
    assert "LOOKS WRONG: nothing in the repo data" in wrong, wrong
    assert "asx: the Thu 08 Oct session: 7 scans" in text
    assert "WATCH" not in text
    assert "ignition ASX" in waiting                 # after the close, not yet screened


@pytest.mark.parametrize("hm,flagged", [
    (["10:43", "12:14", "13:14", "14:14", "15:14", "16:10", "16:16"], True),    # the real 8 Oct miss: 91 min
    (["10:43", "11:58", "13:13", "14:14", "15:14", "16:10", "16:16"], False),   # 75 min spacing is normal jitter
])
def test_the_gap_alarm_threshold_is_pinned_from_both_sides(tmp_path, hm, flagged):
    text = _run(tmp_path, edit=lambda then, files: _set_nasdaq(files, hm))
    wrong, _ = _verdict(text)
    assert ("NASDAQ: 1 gap(s) over 80 min" in wrong) is flagged, wrong


def test_a_lost_first_scan_is_flagged_although_no_gap_reaches_80_minutes(tmp_path):
    text = _run(tmp_path, edit=lambda then, files: _set_asx(files, ASX_HM[1:]))
    wrong, _ = _verdict(text)
    assert "gap(s)" not in wrong
    assert "ASX: the session's first scan (due ~11:15 Melbourne) did not land until 12:16" in wrong


@pytest.mark.parametrize("now,where", [
    ("2026-10-08T16:30:00+11:00", "not due yet"),
    ("2026-10-08T17:05:00+11:00", "pending"),    # the 17:20 close probe has not had its turn
    ("2026-10-08T17:35:00+11:00", "wrong"),
])
def test_a_missing_asx_close_waits_for_its_17_20_probe(tmp_path, now, where):
    text = _run(tmp_path, now=now, edit=lambda then, files: _set_asx(files, ASX_HM[:-1]))
    wrong, waiting = _verdict(text)
    if where == "not due yet":
        assert "ASX closing scan not due yet (from 16:40 Melbourne)" in waiting
    elif where == "pending":
        assert "ASX closing scan not in yet" in waiting and "17:20 close probe" in waiting
        assert "closing scan" not in wrong
    else:
        assert "ASX: no closing scan for the Thu 08 Oct session" in wrong


def test_a_stale_everything_is_flagged_item_by_item(tmp_path):
    now = "2026-10-08T18:00:00+11:00"

    def stale(then, files):
        crypto = _crypto("2026-10-08T14:00:00+11:00")
        files["public/data/funnel_history.json"]["markets"]["crypto"] = {"t": crypto, "trigger": ["heartbeat"] * 24}
        files["public/data/crypto_prices.json"] = {"generated_at": crypto[-1]}
        files["data/scan_health.json"]["asx"]["dry"] = 3
        files["journal/vivek_bot_book.asx.json"]["guard"]["asx"].update(breached=True, breach_kind="daily")
        files["journal/vivek_bot_book.crypto.json"]["updated_at"] = "2026-10-08T03:00:00Z"
        files["public/data/momentum/nasdaq.json"]["generated_at"] = "2026-10-06T20:49:00Z"
        files["public/data/momentum/crypto.json"]["generated_at"] = "2026-10-07T01:13:00Z"
        files["public/data/ignition/crypto.json"] = {"generated_at": "2026-10-06T05:57:00Z", "last_closed_bar": "2026-10-05"}
        files["public/data/ignition/nasdaq.json"]["generated_at"] = "2026-10-06T21:40:00Z"
        files["public/data/phasemap/asx/latest.json"] = {"run_date": "2026-10-06"}
        files["data/alert_forward_returns.json"] = {"updated_at": "2026-10-06T22:00:00Z"}
        del files["backups/2026-10-08T01-14-45/vivek_bot_book.json"]
        then["backups/2026-10-06T01-00-00/vivek_bot_book.json"] = {}

    wrong, _ = _verdict(_run(tmp_path, now=now, edit=stale))
    for want in ("crypto has not scanned for 4.0 h",
                 "asx: 3 dry scan run(s) in a row",
                 "asx loss guard breached (daily)",
                 "crypto bot book not updated for 4.0 h",
                 "momentum nasdaq owed since Thu 07:30",
                 "momentum crypto owed since Thu 11:30",
                 "ignition crypto is STALE",
                 "ignition NASDAQ not screened since the Thu 07:30 bar went final (10.5 h)",
                 "PhaseMap has not run since 2026-10-06",
                 "edge ledgers not updated for",
                 "newest bot-book backup is"):
        assert want in wrong, (want, wrong)


@pytest.mark.parametrize("now,stamp,weekend", [
    ("2026-10-11T16:00:00+11:00", "2026-10-10T01:13:00Z", True),    # Sunday: GitHub's crons only
    ("2026-10-13T16:00:00+11:00", "2026-10-12T01:13:00Z", False),   # Tuesday: 4.5 h late is wrong
])
def test_crypto_momentum_gets_its_measured_weekend_lag(tmp_path, now, stamp, weekend):
    def edit(then, files):
        files["public/data/momentum/crypto.json"]["generated_at"] = stamp
    wrong, waiting = _verdict(_run(tmp_path, now=now, edit=edit))
    if weekend:
        assert "momentum crypto owed" in waiting and "Sundays and Mondays" in waiting
        assert "momentum crypto" not in wrong
    else:
        assert "momentum crypto owed" in wrong


def test_a_bare_now_means_melbourne(tmp_path):
    then, files = _files()
    repo = _repo(tmp_path, then, files)
    bare = _status(repo, "2026-10-08T17:25:00")
    assert bare.splitlines()[0].startswith("Vivek 5.0 status at Thu 08 Oct 17:25 AEDT Melbourne")
    assert bare == _status(repo, NOW)


@pytest.mark.parametrize("since,header,opened", [
    ("2026-10-08 17:21", "Thu 08 Oct 17:21", False),        # ISO without offset: Melbourne; after T1
    ("2026-10-07 13:00", "Wed 07 Oct 13:00", True),         # between T0 and T1: ADP is new since then
    # git's own parser, read in Melbourne: in UTC 09:00 would be 20:00 Melbourne,
    # after the check-in, and the header would fall back to Wed 17:25
    ("Oct 8 2026 09:00", "Thu 08 Oct 09:00", True),
])
def test_since_sets_the_book_window_in_melbourne_time(tmp_path, since, header, opened):
    text = _run(tmp_path, extra=("--since", since))
    assert f"PAPER BOT (changes since {header})" in text
    assert ("OPENED ADP" in text) is opened


def test_a_since_after_the_check_in_falls_back_to_24_hours(tmp_path):
    text = _run(tmp_path, extra=("--since", "2026-10-09 09:00"))
    assert "is after the check-in time; using the last 24 h instead" in text
    assert "PAPER BOT (changes since Wed 07 Oct 17:25)" in text and "OPENED ADP" in text


def test_a_shallow_clone_never_dates_phasemap_from_its_boundary(tmp_path):
    """A cloud session's clone is ~a day deep. git reports the boundary commit
    as touching every file, so its date is not when PhaseMap ran."""
    then, files = _files()
    del files["public/data/phasemap/asx/latest.json"]          # PhaseMap last ran at T0
    src = _repo(tmp_path, then, files)
    shallow = tmp_path / "shallow"
    _git("clone", "-q", "--depth", "1", "--no-local", f"file://{src}", str(shallow))
    text = _status(shallow, NOW, "--no-fetch")
    wrong, _ = _verdict(text)
    assert "phasemap: run_date 2026-10-07, run time unknown (history too shallow)" in text
    assert "PhaseMap" not in wrong                     # yesterday's run_date is fine on a shallow clone
    assert "git history too shallow to diff" in text
    full = _status(src, NOW)
    assert "phasemap: run_date 2026-10-07, last ran Wed 07 Oct 12:00" in full


@pytest.mark.parametrize("now,run_date,expect", [
    ("2026-10-08T17:25:00+11:00", "2026-10-07", "clean"),      # last night's run, stamped before midnight (AEST shape)
    ("2026-10-09T13:00:00+11:00", "2026-10-07", "stale_date"), # a whole night missed
    ("2026-10-09T10:00:00+11:00", "2026-10-08", "stale_time"), # the date rule passes; 46 h since the commit does not
])
def test_phasemap_is_judged_by_run_date_then_by_commit_age(tmp_path, now, run_date, expect):
    then, files = _files()
    if expect == "stale_time":        # committed at T0 (Wed 12:00), untouched since
        then["public/data/phasemap/asx/latest.json"] = {"run_date": run_date}
        del files["public/data/phasemap/asx/latest.json"]
    else:
        files["public/data/phasemap/asx/latest.json"] = {"run_date": run_date}
    wrong, _ = _verdict(_status(_repo(tmp_path, then, files), now))
    if expect == "clean":
        assert "PhaseMap" not in wrong, wrong
    elif expect == "stale_date":
        assert f"PhaseMap has not run since {run_date}" in wrong
    else:
        assert "PhaseMap last ran 46.0 h ago" in wrong


def test_ignition_crypto_stale_badge_waits_for_its_cron_before_it_is_wrong(tmp_path):
    def edit(then, files):
        files["public/data/ignition/crypto.json"]["last_closed_bar"] = "2026-10-06"
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    wrong, waiting = _verdict(_run(tmp_path / "a", now="2026-10-08T17:30:00+11:00", edit=edit))   # 06:30 UTC
    assert "ignition crypto is STALE" in waiting and "ignition crypto" not in wrong
    wrong, _ = _verdict(_run(tmp_path / "b", now="2026-10-08T19:30:00+11:00", edit=edit))         # 08:30 UTC
    assert "ignition crypto is STALE" in wrong


@pytest.mark.parametrize("market", ["crypto", "asx", "nasdaq"])
def test_a_missing_ignition_file_is_named_not_skipped(tmp_path, market):
    def edit(then, files):
        del files[f"public/data/ignition/{market}.json"]
    wrong, _ = _verdict(_run(tmp_path, edit=edit))
    assert f"ignition {market}: file missing" in wrong


def test_a_shallow_clone_is_deepened_when_the_book_window_needs_it(tmp_path):
    then, files = _files()
    src = _repo(tmp_path, then, files)
    shallow = tmp_path / "shallow"
    _git("clone", "-q", "--depth", "1", "--no-local", f"file://{src}", str(shallow))
    text = _status(shallow, NOW, rev=None)          # the default: origin/main, fetched
    assert "too shallow" not in text
    assert "OPENED ADP" in text and "phasemap: run_date 2026-10-08, last ran Thu 08 Oct 17:20" in text


@pytest.mark.parametrize("bad", ["public/data/funnel_history.json", "journal/vivek_bot_book.asx.json"])
def test_one_unreadable_file_costs_one_section_not_the_report(tmp_path, bad):
    then, files = _files()
    repo = _repo(tmp_path, then, files)
    (repo / bad).write_text("{not json", encoding="utf-8")
    _commit(repo, {}, "2026-10-08T17:21:00+11:00")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(repo), "--rev", "HEAD",
                          "--now", NOW], capture_output=True, text=True, env=GIT_ENV)
    assert out.returncode == 0
    assert "== VERDICT FROM REPO DATA" in out.stdout and "could not read a section" in out.stdout
    assert "== CONFLUENCE" in out.stdout

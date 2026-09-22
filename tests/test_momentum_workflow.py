"""momentum.yml -- its own invariants, and the omissions that are DECISIONS.

The five repo-wide workflow invariants already apply automatically, because
`tests/test_workflow_hardening.py` globs `.github/workflows/*.yml`: valid shell
in every `run:`, one pathspec per `git add`, a swallowed `git add` paired with a
must-change gate, a declared `permissions:` block, and the tripwire that the
`actions/*` set stays exactly the five that were reviewed.

What is pinned HERE is what is specific to this lens, plus -- in the repo's own
style -- the things it deliberately does NOT do. An absence that is not pinned
reads as an oversight to the next person, and gets "fixed".
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import zoneinfo

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "momentum.yml"
SRC = WF.read_text(encoding="utf-8")
DOC = yaml.safe_load(SRC)
JOB = DOC["jobs"]["momentum"]
# PyYAML parses a bare `on:` key as the boolean True, which is why every test
# in this repo that reads a trigger block reaches for DOC[True].
ON = DOC.get("on") or DOC[True]

def _market_cron() -> dict:
    """Read the cron -> market mapping OUT OF THE SHIPPED WORKFLOW.

    The first version of this file carried the mapping as a hardcoded dict, and
    the DST test below then proved a property of that dict rather than of the
    file -- change the cron in the YAML and the DST test would have kept
    passing while a different test complained about the mismatch. Parsing the
    `case` arms means the timezone arithmetic is checked against what actually
    fires.
    """
    scan = next(s for s in JOB["steps"] if s.get("id") == "scan")
    arms = re.findall(r'"([^"]+)"\)\s*MARKET=(\w+)', scan["run"])
    assert arms, "the cron -> market case statement is no longer parseable"
    return {market: cron for cron, market in arms}


MARKET_CRON = _market_cron()
CLOSES = {                       # market: (tz, local close hour)
    "asx": ("Australia/Sydney", 16),
    "nasdaq": ("America/New_York", 16),
}


def test_it_has_its_own_concurrency_group_and_is_not_in_the_scan_mutex():
    """`group: scan` is the paper-book mutex. This lens writes no book, so it
    has no business in that queue -- and the cost is not hypothetical: GitHub
    keeps only ONE pending run per group and cancels the previously-pending
    one, so joining it would start evicting the freshness backstops. It would
    also make this workflow a member that
    `test_workflow_mutex.py::test_the_wait_loop_watches_every_member_of_the_group`
    requires in close_position.yml's watch list."""
    assert JOB.get("concurrency") is None, "the group belongs at workflow level here"
    assert DOC["concurrency"]["group"] == "momentum"
    assert DOC["concurrency"]["cancel-in-progress"] is False, (
        "cancelling in progress would drop a market's only scan of the day")


def test_it_declares_least_privilege_and_a_timeout():
    assert DOC["permissions"] == {"contents": "write"}
    assert isinstance(JOB.get("timeout-minutes"), int), (
        "an unbounded job holds a runner for six hours and, holding this "
        "group, stalls every later refresh rather than only itself")


@pytest.mark.parametrize("market", sorted(MARKET_CRON))
def test_every_market_has_exactly_one_cron(market):
    crons = [c["cron"] for c in ON["schedule"]]
    assert crons.count(MARKET_CRON[market]) == 1, crons
    assert len(crons) == len(MARKET_CRON), f"an unmapped cron would fall through: {crons}"
    assert set(crons) == set(MARKET_CRON.values()), (
        "a scheduled cron with no case arm falls through to the dispatch input "
        f"and silently screens the wrong market: {sorted(set(crons) ^ set(MARKET_CRON.values()))}")


@pytest.mark.parametrize("market", sorted(CLOSES))
def test_the_cron_clears_the_close_IN_BOTH_HALVES_OF_THE_DST_YEAR(market):
    """COMPUTED, not asserted from arithmetic done in my head.

    Every ASX cron in this repo was originally written for AEST and would have
    silently lost an hour of every session for four weeks each October. The fix
    is to pick a UTC time that is past the close under BOTH offsets -- which for
    a post-close screener is possible, unlike for an intraday one, and is why
    this workflow needs no in-job timezone gate at all.

    A forming bar's RSI and EMA move all session, so a run that lands before the
    close produces a signal that may not exist at the close (spec 5.11).
    """
    tz = zoneinfo.ZoneInfo(CLOSES[market][0])
    close_hour = CLOSES[market][1]
    minute, hour = (int(x) for x in MARKET_CRON[market].split()[:2])
    # A day in each DST regime, for the tz in question.
    for probe in (dt.date(2026, 1, 15), dt.date(2026, 7, 15)):
        fire = dt.datetime(probe.year, probe.month, probe.day, hour, minute,
                           tzinfo=dt.timezone.utc).astimezone(tz)
        close = fire.replace(hour=close_hour, minute=0, second=0, microsecond=0)
        assert fire > close, (
            f"{market}: firing at {hour:02d}:{minute:02d}Z lands "
            f"{fire:%Y-%m-%d %H:%M %Z}, which is BEFORE that day's "
            f"{close_hour}:00 close - a forming bar would be screened")
        assert fire.date() == close.date(), (
            f"{market}: the firing rolled to {fire.date()} but the close it "
            f"must follow is on {close.date()} - the cron's weekday field is "
            "then selecting the wrong sessions")


def test_crypto_runs_every_day_because_it_has_no_weekend():
    assert MARKET_CRON["crypto"].endswith("* * *")
    for market in ("asx", "nasdaq"):
        assert MARKET_CRON[market].endswith("1-5"), (
            "an equity market publishes nothing new at the weekend")


def test_the_commit_step_runs_ONLY_when_the_scanner_really_published():
    """Exit 3 -- "the download came back empty, the previous file stands" -- is
    a reported DECISION, not a fault. Letting it reach the commit step would
    fire `assert_staged` on a gate that is correctly unmet, and a must-change
    gate that cries wolf is one that gets deleted rather than fixed."""
    commit = next(s for s in JOB["steps"] if s.get("name") == "Commit and push")
    cond = commit["if"]
    assert "steps.scan.outputs.published == 'true'" in cond
    assert "dry_run" in cond, "a dry run must not commit either"

    scan = next(s for s in JOB["steps"] if s.get("id") == "scan")
    body = scan["run"]
    assert "published=false" in body and "published=true" in body
    assert re.search(r'\n\s*3\)\s*\n', body), "exit 3 needs its own branch"
    assert "::warning::" in body, "the no-publish path must say so on the run page"
    assert '|| RC=$?' in body, (
        "the status must be neutralised WITHOUT appending to the output - the "
        "`|| echo` form is what produced the old '000000' bug")


def test_the_must_change_gate_names_the_canonical_path():
    commit = next(s for s in JOB["steps"] if s.get("name") == "Commit and push")
    body = commit["run"]
    assert "scripts/assert_staged.sh" in body
    assert 'public/data/momentum/$MARKET.json' in body
    assert "git add -- " in body, "one pathspec at a time"


def test_the_workflow_writes_nothing_outside_the_lens_directory():
    """The write-set fence, at the workflow layer this time. A path added here
    would bypass the one in test_momentum_fences.py, which only reads run.py."""
    paths = re.findall(r'PATHS="([^"]+)"', SRC)
    assert paths, "no PATHS assignment found - has the commit step been rewritten?"
    for group in paths:
        for p in group.split():
            assert p.startswith("public/data/momentum/"), p
    for forbidden in ("journal/", "public/data/phasemap", "_vivek.json",
                      "_spec.json", "bot_rules.json", "alert_history.json",
                      "funnel_history.json", "backups/"):
        assert forbidden not in SRC, f"momentum.yml names {forbidden}"


def test_it_uses_its_own_frame_cache_namespace():
    """Sharing `vivek-frames-` would mix a 3y download window with the scan's 5y
    one under the same keys, and a separate namespace is one more thing that
    disappears cleanly when the lens does."""
    cache = next(s for s in JOB["steps"] if s.get("uses", "").startswith("actions/cache"))
    with_ = cache["with"]
    # Checked on the KEY VALUES, not on the file text: the first version of
    # this test asserted `"vivek-frames" not in SRC` and went red on the
    # COMMENT above the step explaining why that namespace is not used. Same
    # false-positive class as a fence that bans a word instead of a reference.
    keys = [with_["key"], *str(with_.get("restore-keys", "")).split()]
    assert all(k.startswith("momentum-frames-") for k in keys if k), keys
    assert with_["path"] == ".cache/frames"


# ---------------------------------------------------------------------------
# the omissions, pinned as DECISIONS
# ---------------------------------------------------------------------------

def test_there_is_DELIBERATELY_no_watchdog_entry():
    """HANDOFF 17.5's checklist asks for a `WATCHDOG_RUNS` entry when a
    workflow commits data, and this one deliberately has none.

    Two reasons, and both are reversible in one line. First, the watchdog
    alarms when a workflow has not RUN recently, and for a report-only lens a
    quiet day costs a stale page and nothing else -- there is no book to
    mis-price and no alert to miss. Second, an entry means editing
    `scanner/config.py`, which is one more file to remove when the lens goes,
    for an alarm about a surface nobody trades off.

    IT IS THE OWNER'S CALL, not a permanent ruling, and it is recorded in
    reviews/2026-09-22-momentum-phase0.md as an open decision. This test exists
    so the absence reads as a decision rather than an oversight -- the same
    reason `confluence.yml`'s missing `assert_staged` is pinned. If the owner
    wants the alarm, add `"momentum.yml": {"max_age_h": 26.0, "severity":
    "WARNING"}` beside phasemap's and DELETE THIS TEST in the same commit.
    """
    cfg = (ROOT / "scanner" / "config.py").read_text(encoding="utf-8")
    assert '"momentum.yml"' not in cfg, (
        "a WATCHDOG_RUNS entry now exists - that is a fine change, but this "
        "test records its previous absence as deliberate and should be "
        "deleted in the same commit")


def test_no_other_workflow_learned_about_the_lens():
    """Removability, checked at the workflow layer. Exactly one workflow may
    mention this lens, and it is this one."""
    others = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        if path.name == "momentum.yml":
            continue
        if re.search(r"scanner[./]momentum|data/momentum|momentum\.yml",
                     path.read_text(encoding="utf-8")):
            others.append(path.name)
    assert others == [], others

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


def _step(**match):
    key, value = next(iter(match.items()))
    return next(s for s in JOB["steps"] if s.get(key) == value)


def test_no_scheduled_run_picks_its_market_off_the_cron_string():
    """2026-09-23: the ASX cron was DROPPED by GitHub's scheduler -- no run, no
    failure, nothing to retry -- because the market was a property of which
    cron fired. The market is now a property of the DATA: the gate reads
    main's files and names the one that is due. A `github.event.schedule`
    case arm coming back would re-tie a market to a single cron, and a dropped
    cron would again silently skip that market for the day."""
    assert "github.event.schedule" not in SRC
    scan = _step(id="scan")
    assert 'MARKET="${{ steps.due.outputs.market }}"' in scan["run"]


def test_every_step_after_the_gate_is_skipped_when_nothing_is_due():
    """A no-op wake-up must stop before `pip install`: the piggyback fires ~18
    times a weekday and the backstop 8 times a day, and all but one of them
    find nothing due."""
    names = [s.get("id") or s.get("name") or s.get("uses") for s in JOB["steps"]]
    gate = names.index("due")
    assert JOB["steps"][0]["uses"].startswith("actions/checkout"), names
    for step in JOB["steps"][gate + 1:]:
        cond = step.get("if", "")
        label = step.get("name") or step.get("uses")
        if step.get("name") == "Commit and push":
            # gated transitively: it needs the screen's published=true
            assert "steps.scan.outputs.published == 'true'" in cond, label
            continue
        assert "steps.due.outputs.market != ''" in cond, label


def test_the_gate_reads_main_as_it_is_NOW_and_runs_before_any_install():
    """A run that waited behind the previous one was created at an older SHA;
    its checkout would call a market due that was published minutes ago."""
    body = _step(id="due")["run"]
    assert "git fetch --quiet --depth=1 origin main" in body
    assert 'git show "origin/main:public/data/momentum/$m.json"' in body
    assert "python3 scripts/momentum_due.py" in body, (
        "the gate runs on the runner's python3, before setup-python/pip")
    assert "pipefail" in body, "`| tee` would otherwise hide a gate failure"
    assert 'github.event_name }}" = "workflow_dispatch"' in body, (
        "a manual dispatch screens the market it names, with no due check")


def test_the_piggyback_rides_a_workflow_that_exists_and_is_not_githubs_cron():
    """workflow_run matches on the other workflow's `name:`; a typo is a
    trigger that silently never fires. morning_plays.yml is the one chosen
    because its runs are DISPATCHED by the external cron-job.org pinger (see
    CLAUDE.md MORNING PLAYS), so they arrive even when GitHub's scheduler
    does not -- which on 2026-09-23 it did not, for three hours."""
    wr = ON["workflow_run"]
    assert wr["types"] == ["completed"]
    assert wr["branches"] == ["main"]
    names = {}
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        names[doc.get("name")] = path.name
    for wanted in wr["workflows"]:
        assert wanted in names, f"no workflow is named {wanted!r}"
    assert names["Morning plays (Discord)"] == "morning_plays.yml"
    mp = yaml.safe_load((ROOT / ".github/workflows/morning_plays.yml").read_text())
    assert "workflow_dispatch" in (mp.get("on") or mp[True]), (
        "the piggyback is only worth having while morning_plays is dispatched "
        "from outside GitHub's scheduler")


def _fires(cron: str, day: dt.date) -> list:
    """Every UTC instant on `day` a cron line fires, for the fields used here
    (minute, hour as N, */N or *, day-of-month and month *, day-of-week
    * or a-b)."""
    minute, hour, dom, month, dow = cron.split()
    assert dom == "*" and month == "*", cron
    if dow != "*":
        lo, hi = (int(x) for x in dow.split("-"))
        if not lo <= (day.isoweekday() % 7) <= hi:
            return []
    if hour == "*":
        hours = range(24)
    elif hour.startswith("*/"):
        hours = range(0, 24, int(hour[2:]))
    else:
        hours = [int(hour)]
    return [dt.datetime(day.year, day.month, day.day, h, int(minute),
                        tzinfo=dt.timezone.utc) for h in hours]


CLOSES = {                       # market: (tz, local close hour)
    "asx": ("Australia/Sydney", 16),
    "nasdaq": ("America/New_York", 16),
}


def _gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "momentum_due", ROOT / "scripts" / "momentum_due.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("market", ["asx", "nasdaq", "crypto"])
@pytest.mark.parametrize("probe", [dt.date(2026, 1, 14), dt.date(2026, 7, 15)])
def test_the_crons_ALONE_still_deliver_every_market_IN_BOTH_HALVES_OF_THE_DST_YEAR(market, probe):
    """COMPUTED against the shipped gate and the shipped crons.

    Take a Wednesday in each DST regime, stamp the market's file so it owes
    that day's close, and walk the workflow's own cron firings through
    `momentum_due.pick`. One must pick the market within three hours of the
    close it owes, and none may pick it before that close -- a forming bar is
    never screened. The piggyback is not counted, so this holds even on a day
    the external pinger is down.
    """
    due = _gate()
    utc = dt.timezone.utc
    if market in CLOSES:
        tz = zoneinfo.ZoneInfo(CLOSES[market][0])
        close = dt.datetime.combine(probe, dt.time(CLOSES[market][1]), tzinfo=tz)
    else:
        tz = utc
        close = dt.datetime.combine(probe, dt.time(0), tzinfo=utc)
    owed = due.due_point(market, close + dt.timedelta(hours=1))
    assert owed.astimezone(tz).date() == probe
    stamps = {m: owed + dt.timedelta(days=3) for m in ("asx", "nasdaq", "crypto")}
    stamps[market] = due.due_point(market, owed - dt.timedelta(minutes=1))

    crons = [c["cron"] for c in ON["schedule"]]
    picks = []
    for offset in (-1, 0, 1):
        for cron in crons:
            for fire in _fires(cron, probe + dt.timedelta(days=offset)):
                if close - dt.timedelta(hours=12) <= fire < owed + dt.timedelta(hours=18):
                    if due.pick(stamps, fire)[0] == market:
                        picks.append(fire)
    assert picks, f"{market}: no cron picks it up after {owed:%Y-%m-%d %H:%MZ}"
    assert min(picks) >= owed > close, (
        f"{market}: a cron picked it at {min(picks):%Y-%m-%d %H:%MZ}, before "
        f"the {close:%H:%M %Z} close it owes")
    assert min(picks) - owed <= dt.timedelta(hours=3), (
        f"{market}: first cron pick {min(picks):%H:%MZ} is over 3h after it "
        f"became due at {owed:%H:%MZ}")


def test_the_three_original_crons_are_kept():
    """Editing a workflow re-registers its schedules, and the original times
    are still the first instant each market is due in the winter half of the
    year. They stay; the backstop is added, not substituted."""
    crons = [c["cron"] for c in ON["schedule"]]
    for cron in ("30 6 * * 1-5", "30 21 * * 1-5", "30 0 * * *"):
        assert crons.count(cron) == 1, crons
    assert any(c.split()[1].startswith("*/") for c in crons), "the backstop went"


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
    assert 'bash scripts/assert_staged.sh "momentum $MARKET" "public/data/momentum/$FILE"' in body
    assert 'FILE="${{ steps.scan.outputs.file }}"' in body
    assert "git add -- " in body, "one pathspec at a time"


def test_the_file_is_the_screen_unless_a_human_asked_for_the_backtest():
    """Two write targets, both in the lens's own directory, and the second is
    reachable ONLY through the manual `backtest` input -- no cron, no
    workflow_run wake-up can publish a backtest (or skip a screen for one)."""
    body = next(s for s in JOB["steps"] if s.get("id") == "scan")["run"]
    assert 'FILE="$MARKET.json"' in body
    assert 'if [ "${{ inputs.backtest }}" = "true" ]; then' in body
    assert 'FILE="${MARKET}_backtest.json"' in body
    assert 'ARGS="$ARGS --backtest"' in body
    files = set(re.findall(r'FILE="([^"$]*\$\{?MARKET\}?[^"]*)"', body))
    assert files == {"$MARKET.json", "${MARKET}_backtest.json"}, files
    assert ON["workflow_dispatch"]["inputs"]["backtest"]["default"] is False


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

"""The Lighthouse gate must be a function of the COMMIT, not of the tape.

Sibling to `test_screenshot_determinism.py`, and the same defect one layer over.
That gate was failing on the CALENDAR; this one was failing on MARKET BREADTH,
which is worse, because a date is at least predictable.

`test/e2e/lighthouse.e2e.js` served `public/` wholesale, so `total-byte-weight`
was measuring the live scan JSON. Measured at 9d6221fe: **5.00MB against a 5.0MB
budget, 4.15MB of it committed scan data**, and the growth was legitimate --
204 -> 343 ASX rows, identical schema, per-field sizes proportional (plans
282.8 -> 497.4 KB, detail 87.3 -> 147.8, analysis 75.0 -> 127.3). Nothing had
bloated. More ASX names had simply set up that morning.

Two things made that quietly awful rather than merely wrong. test.yml's path
filter deliberately EXCLUDES `public/data/**`, so the ~20 scheduled scan commits
a day never trigger the gate -- the payload grows in silence and the next
unrelated CODE push wears the red. And because a failing step aborts the job,
lighthouse failing meant `screenshot-diff` never ran at all: the gate that had
just been repaired was skipped for the whole of the day it was repaired.

The fix pins `/data/` to `test/e2e/fixtures/data` -- the SAME set
`screenshot-diff.e2e.js` routes to -- at the server root, since lighthouse
drives chrome-launcher rather than Playwright and `ctx.route()` is unavailable.
Measured over three consecutive runs afterwards: transfer 1.850 / 1.861 / 1.861
MB, CLS 0.123 / 0.123 / 0.123, against 5.00MB and a moving CLS before.

These tests pin the property, not the plumbing: the gate cannot read a byte the
commit does not contain, the two e2e gates cannot drift apart about which page
they are measuring, and the real 5MB payload -- which is a genuine user-facing
cost and a product decision -- is REPORTED on every run and can never fail one.

Deliberately tape-independent, including the assertions themselves. Nothing here
reads `public/data/`: a test that sized the budget against today's scan output
would rebuild the very bug it exists to prevent, one level up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LH = REPO / "test" / "e2e" / "lighthouse.e2e.js"
SHOT = REPO / "test" / "e2e" / "screenshot-diff.e2e.js"
FIXTURES = REPO / "test" / "e2e" / "fixtures" / "data"
TEST_YML = REPO / ".github" / "workflows" / "test.yml"


@pytest.fixture(scope="module")
def src() -> str:
    return LH.read_text(encoding="utf-8")


def _const(src: str, name: str) -> float:
    m = re.search(rf"^const\s+{name}\s*=\s*([0-9.]+);", src, re.M)
    assert m, f"{name} is no longer a named constant at the top of lighthouse.e2e.js"
    return float(m.group(1))


def _fn(src: str, name: str) -> str:
    """The body of a top-level `function name(...) {...}`, closing brace included."""
    start = src.index(f"function {name}(")
    end = src.index("\n}\n", start)
    return src[start:end + 3]


# --------------------------------------------------------------------------- #
# The pin itself: the gate cannot see a byte the commit does not carry.
# --------------------------------------------------------------------------- #

def test_the_server_root_is_STAGED_never_public(src: str) -> None:
    """Serving public/ is the bug, in one line.

    Everything else in this file is downstream of which directory the http
    server is pointed at, so this is the assertion that actually holds the fix.
    """
    spawned = re.search(r"spawn\(\s*\"python3\".*?\{\s*cwd:\s*(\w+)", src, re.S)
    assert spawned, "the local http server is gone or no longer spawned with an explicit cwd"
    assert spawned.group(1) == "root", (
        f"the server is rooted at `{spawned.group(1)}` -- if that is public/ (or anything derived "
        "from it), total-byte-weight is measuring the live scan JSON again and the budget goes red "
        "on a broad tape, on whatever unrelated code push lands next"
    )
    assert re.search(r"root\s*=\s*stageRoot\(\)", src), (
        "`root` is no longer the staged directory -- stageRoot() is what redirects /data/"
    )


def test_data_is_pinned_to_the_fixture_set(src: str) -> None:
    """The one entry that is redirected, and the one that must stay redirected."""
    fixtures = re.search(
        r"^const\s+FIXTURES\s*=\s*path\.join\(\s*__dirname\s*,\s*\"fixtures\"\s*,\s*\"data\"\s*\);",
        src, re.M,
    )
    assert fixtures, "FIXTURES no longer resolves to test/e2e/fixtures/data"
    assert FIXTURES.is_dir(), f"{FIXTURES} does not exist -- the symlink target is a typo"
    assert list(FIXTURES.glob("*.json")), "the fixture directory carries no payload to serve"

    stage = _fn(src, "stageRoot")
    assert re.search(r"if\s*\(\s*entry\s*===\s*\"data\"\s*\)\s*continue;", stage), (
        "stageRoot no longer skips public/data -- it would be symlinked alongside the fixtures "
        "and one of the two would win by directory order"
    )
    assert re.search(r"symlinkSync\(\s*FIXTURES\s*,\s*path\.join\(\s*dir\s*,\s*\"data\"\s*\)\s*\)", stage), (
        "the staged root no longer points /data/ at the fixture set"
    )


def test_an_unfixtured_file_404s_rather_than_falling_through_to_public(src: str) -> None:
    """A fallback would put the live JSON back inside the budget, file by file.

    `screenshot-diff.e2e.js` 404s an unfixtured path on purpose, and this gate
    inherits that semantics for free by symlinking the fixture DIRECTORY -- the
    filesystem does the 404. The tempting future edit is a helpful fall-through
    for whichever file someone notices is missing, which reintroduces the defect
    for exactly that file and looks like a fix while doing it.
    """
    stage = _fn(src, "stageRoot")
    # PUBLIC is reachable inside stageRoot -- it HAS to be, that is where every
    # non-data entry is staged from. The property is what it may be joined to:
    # the loop variable, which the `entry === "data"` skip above has already
    # filtered, and nothing else. A literal is how a fall-through gets written.
    joins = re.findall(r"path\.join\(\s*PUBLIC\s*,\s*([^)]+)\)", stage)
    assert joins == ["entry"], (
        f"stageRoot joins PUBLIC to {joins!r} -- the only thing that may be staged out of public/ "
        'is a non-data entry, and the only expression that can be one is the loop variable the '
        '`entry === "data"` skip filters'
    )
    # Exactly two uses are legitimate: LISTING public/ (to learn the entry names)
    # and joining it to one of them. Anything else is a third way in.
    residue = re.sub(r"fs\.readdirSync\(\s*PUBLIC\s*\)", "", stage)
    residue = re.sub(r"path\.join\(\s*PUBLIC\s*,\s*entry\s*\)", "", residue)
    assert "PUBLIC" not in residue, (
        "stageRoot reaches into public/ by some route other than readdirSync(PUBLIC) + "
        "path.join(PUBLIC, entry) -- an unfixtured file must 404 off the filesystem, not fall "
        "through to the live scan JSON"
    )
    assert not re.search(r"path\.join\(\s*PUBLIC\s*,\s*[\"']data", src), (
        "something in this file joins PUBLIC to 'data' -- an unfixtured file must 404, not fall "
        "through (livePayload's path.resolve(PUBLIC, ...) is a stat for the size REPORT and is a "
        "different thing: nothing is served off it)"
    )


def test_both_e2e_gates_measure_the_SAME_page(src: str) -> None:
    """Two gates photographing different pages is two blind spots, not one.

    They share the fixture set so that a fixture refresh moves both together and
    a CLS regression the screenshot gate can see is a CLS regression this gate
    can see. Point one of them somewhere else and they start disagreeing about
    what the dashboard even renders, silently, in the direction of whichever ran
    first.
    """
    shot = SHOT.read_text(encoding="utf-8")
    shot_root = re.search(r"path\.join\(\s*__dirname\s*,\s*\"fixtures\"\s*,\s*rel\s*\)", shot)
    assert shot_root, (
        "screenshot-diff no longer resolves /data/ under test/e2e/fixtures -- re-point this test "
        "and make sure the two gates still share one fixture set"
    )
    assert 'ctx.route("**/data/**"' in shot, "screenshot-diff no longer intercepts /data/ at all"
    # Both land on test/e2e/fixtures/data: one by joining the request pathname
    # ("data/x.json") under fixtures/, one by symlinking fixtures/data as the
    # served root. Same directory, two mechanisms, because only one of the two
    # runners has Playwright routing available.
    assert "FIXTURES" in src and 'path.join(__dirname, "fixtures", "data")' in src


# --------------------------------------------------------------------------- #
# The budgets. Sized off the pinned baseline, and stated once.
# --------------------------------------------------------------------------- #

def test_the_transfer_budget_is_below_the_one_that_was_measuring_the_tape(src: str) -> None:
    """5.0MB was not a budget, it was a coin toss on market breadth."""
    budget = _const(src, "TRANSFER_BUDGET_MB")
    assert budget < 5.0, (
        f"the transfer budget is back at {budget}MB. At 5.0 it carried 2.4x dead headroom over the "
        "fixture-pinned 1.86MB baseline, which is not a tripwire -- it was sized to clear the live "
        "scan payload, and that is the thing this gate no longer measures"
    )


def test_the_budget_clears_the_baseline_the_file_itself_claims(src: str) -> None:
    """The stated baseline and the budget have to move together or neither means anything.

    The failure message names a deterministic baseline so that a red is
    self-explaining (`if this moved and no asset did, the fixtures were
    refreshed`). A baseline claim that drifts away from the budget above it
    turns that sentence into a lie at the exact moment somebody is reading it to
    work out what broke.
    """
    budget = _const(src, "TRANSFER_BUDGET_MB")
    claim = re.search(r"deterministic\s+([0-9.]+)MB baseline", src)
    assert claim, "the transfer failure message no longer states the baseline it was sized against"
    baseline = float(claim.group(1))
    assert baseline < budget, (
        f"the file claims a {baseline}MB baseline against a {budget}MB budget -- the gate is red on "
        "a clean checkout"
    )
    assert budget <= baseline * 2, (
        f"a {budget}MB budget over a {baseline}MB baseline is {budget / baseline:.1f}x headroom. "
        "Past ~2x this stops being a tripwire and starts being decoration; re-measure and "
        "re-baseline rather than widening it"
    )


def test_the_budgets_are_stated_once_and_the_message_is_derived(src: str) -> None:
    """A hand-typed number in the label is the `PUBLISHED_DEFAULTS` bug in miniature.

    TOP100 #34 was a mirror that drifted from the thing it mirrored and was only
    ever shown to someone who could not check it. A budget label carrying its own
    literal is the same shape: the gate fires at one number and tells you a
    different one, and the run page is exactly where nobody can verify which.
    """
    assert "${TRANSFER_BUDGET_MB.toFixed(1)}MB" in src, (
        "the transfer label no longer derives its number from TRANSFER_BUDGET_MB"
    )
    assert "${CLS_BUDGET.toFixed(2)}" in src, "the CLS label no longer derives its number from CLS_BUDGET"
    checks = re.findall(r"check\(([^,]+),", src)
    assert len(checks) == 2, f"expected exactly 2 gated checks, found {len(checks)}: {checks}"
    for expr in checks:
        assert "BUDGET" in expr, (
            f"gated check `{expr.strip()}` compares against something other than a named budget "
            "constant -- put the number at the top of the file with the others"
        )


def test_the_notice_line_sits_above_the_gate_not_below_it(src: str) -> None:
    """A warning that fires before the failure would just be a second failure."""
    budget = _const(src, "TRANSFER_BUDGET_MB")
    warn = _const(src, "LIVE_PAYLOAD_WARN_MB")
    assert warn > budget, (
        f"the live-payload notice line ({warn}MB) is at or below the gated transfer budget "
        f"({budget}MB) -- they measure different things and the notice is the LOOSER of the two "
        "by construction, because it covers the real scan data the gate deliberately excludes"
    )


# --------------------------------------------------------------------------- #
# The real payload. Reported every run, never able to fail one.
# --------------------------------------------------------------------------- #

def test_the_live_payload_is_STRUCTURALLY_incapable_of_failing_the_run(src: str) -> None:
    """The asymmetry is the item, exactly as it is for the screenshot sentinel.

    5MB uncompressed is a real cost and worth saying out loud on every run. It is
    NOT worth a red, because no commit can fix it -- it moves with how many names
    set up that morning, and slimming public/data/ is a product decision. A gate
    that reds on something the pusher cannot act on is how a channel gets muted,
    and a muted channel is what makes the next genuine red invisible. That is not
    hypothetical here: it is what this gate had been doing daily.

    So the reporter must be incapable of failing, not merely currently not
    failing. The tempting future edit is "make it strict".
    """
    fn = _fn(src, "livePayload")
    for banned, why in (
        ("failures", "the reporter increments the failure counter"),
        ("process.exit", "the reporter exits the process"),
        ("throw", "the reporter throws"),
    ):
        assert banned not in fn, f"{why} -- the real payload must be reported, never gated"

    # The call site is the other half: a reporter that cannot fail, wired into a
    # branch that can, is the same bug one line further down.
    call = src[src.index("const live = livePayload(a);"):src.index("perf score:")]
    assert "failures" not in call, (
        "the live-payload branch touches `failures` -- reporting the payload must not be able to "
        "red the build"
    )
    assert "::warning::" in call, (
        "the escalation is no longer a ::warning:: -- it must reach the run page as a notice, "
        "which is the whole reason it is allowed to be non-fatal"
    )
    assert "does NOT fail the build" in call, (
        "the warning no longer states that it is not a failure -- a loud line that reads like a red "
        "is how a green run gets treated as a broken one"
    )


def test_the_payload_url_list_is_DERIVED_not_hard_coded(src: str) -> None:
    """A hard-coded manifest is a list that silently stops being complete.

    The URLs come out of the run's own `network-requests` audit, which records
    404s too -- so the unfixtured files (phasemap, regime, backtest, prices) are
    counted at their REAL size even though the gate served them as misses, and a
    new /data/ file the page starts fetching is counted the day it lands with
    nothing to remember to update.
    """
    fn = _fn(src, "livePayload")
    assert '"network-requests"' in fn, (
        "livePayload no longer reads the network-requests audit -- any other source is a list "
        "somebody has to maintain, and it will be wrong within a month"
    )
    assert re.search(r"pathname\.startsWith\(\s*\"/data/\"\s*\)", fn), (
        "livePayload no longer selects /data/ requests by path"
    )
    assert "statSync" in fn, (
        "livePayload no longer stats the REAL file -- reporting the size of the fixture it just "
        "served would report the number the gate already gates on, which is not the question"
    )
    hard_coded = re.findall(r"[\"'][\w/]+\.json[\"']", fn)
    assert not hard_coded, (
        f"livePayload names data files directly ({hard_coded}) -- derive the list from the audit "
        "so it cannot fall out of date"
    )


def test_an_unreadable_audit_reports_NOTHING_rather_than_a_guess(src: str) -> None:
    """This number's only job is to be quoted at a decision. A fabricated one is worse than none."""
    fn = _fn(src, "livePayload")
    assert re.search(r"if\s*\(\s*!Array\.isArray\(items\)[^)]*\)\s*return null;", fn), (
        "livePayload no longer returns null on a missing audit -- a partial sum presented as the "
        "page weight would be quoted as fact"
    )
    assert "no network-requests audit" in src, (
        "the run no longer says when the payload was not measured -- an absent INFO line reads "
        "identically to a healthy small payload"
    )


# --------------------------------------------------------------------------- #
# Housekeeping that the gate's determinism actually depends on.
# --------------------------------------------------------------------------- #

def test_the_page_is_loaded_in_measurement_mode(src: str) -> None:
    """?lite=1 removes the deferred work; the fixture pin removes the data. Both halves are needed.

    Asserted against the URL CONSTANT and its use, never against `src` as a
    whole. The header comment explains ?lite=1 at length, so a bare
    `"?lite=1" in src` stays green on prose after the query string has fallen off
    the URL -- caught by mutation, and it is the mirror-drift shape from TOP100
    #34 in its cheapest possible form.
    """
    url = re.search(r"^const\s+URL_UNDER_TEST\s*=\s*`([^`]+)`;", src, re.M)
    assert url, "URL_UNDER_TEST is no longer a single template-literal constant"
    assert "?lite=1" in url.group(1), (
        f"the gate loads `{url.group(1)}` -- without ?lite=1 the idle prefetch and background polls "
        "land inside the trace at random and the budget goes back to being a dice roll"
    )
    assert re.search(r"lighthouse\(\s*URL_UNDER_TEST\s*,", src), (
        "the run no longer navigates to URL_UNDER_TEST -- the constant can carry ?lite=1 and be "
        "measuring nothing"
    )


def test_the_staging_root_is_torn_down_even_when_the_run_throws(src: str) -> None:
    """A leaked temp dir per run is minor; leaking one per run for ever is not."""
    finally_block = src[src.index("} finally {"):]
    assert "unstageRoot(root)" in finally_block, (
        "the staged root is not removed in the finally block -- a thrown lighthouse run would leave "
        "it behind on every failure"
    )
    fn = _fn(src, "unstageRoot")
    assert "unlinkSync" in fn and "rmdirSync" in fn, (
        "unstageRoot no longer removes the symlinks explicitly -- keep the teardown obvious, the "
        "blast radius of following a link here is public/ and the fixture set"
    )


def test_the_workflow_comment_does_not_advertise_the_old_budgets() -> None:
    """The step comment is the first thing read when this gate goes red.

    It described `CLS < 1.30, transfer < 5MB` long after both had moved, and a
    comment that disagrees with the code sends the reader looking for a
    regression that is not there.
    """
    yml = TEST_YML.read_text(encoding="utf-8")
    block = re.search(r"# Lighthouse budget tripwire(.*?)node test/e2e/lighthouse\.e2e\.js", yml, re.S)
    assert block, "the lighthouse step is gone from test.yml"
    body = block.group(1)
    src = LH.read_text(encoding="utf-8")
    budget = _const(src, "TRANSFER_BUDGET_MB")
    cls = _const(src, "CLS_BUDGET")
    quoted = re.findall(r"transfer\s*<\s*([0-9.]+)MB", body)
    assert quoted, "the step comment no longer states the transfer budget it gates on"
    assert all(abs(float(q) - budget) < 1e-9 for q in quoted), (
        f"the step comment says transfer < {quoted} but the gate uses {budget}MB"
    )
    quoted_cls = re.findall(r"CLS\s*<\s*([0-9.]+)", body)
    assert quoted_cls and all(abs(float(q) - cls) < 1e-9 for q in quoted_cls), (
        f"the step comment says CLS < {quoted_cls} but the gate uses {cls}"
    )
    assert "fixture" in body.lower(), (
        "the step comment does not mention that /data/ is fixture-pinned -- that is the single "
        "fact a reader needs before they start hunting for a payload regression"
    )

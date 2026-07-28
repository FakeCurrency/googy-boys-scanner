"""The screenshot gate must be a function of the code, not of the calendar.

`test/e2e/screenshot-diff.e2e.js` compares each view against a baseline that is
cached and, by design, NEVER re-saved on a cache hit -- a frozen reference is
the whole point, because a baseline that re-saves every run lets a slow creep
ratchet past any budget one sub-threshold step at a time.

A frozen reference only works if the picture is reproducible. Two inputs move
underneath it. The scan JSON was pinned to a fixture set on 2026-07-26. The
CLOCK was not, and that was the half with a date on it: journal.js renders the
fixture set through `Date.now()` -- "3h ago"/"2d ago" per row, stale badges by
age in days, a week grid bucketed by day -- so the same bytes drew a different
picture every hour. Measured 1.41%/1.42% drift on the journal pages 22 hours
after a baseline was cut, against a 2% budget, with two rows of the "new
positions" panel already aged out.

The failure was dated, not gradual. `NEW_POS_WINDOW_MS` is 7 days; the newest
position in the fixture book opened 2026-07-23T17:46Z; so on 2026-07-30 both
panels would have collapsed to a one-line "No new positions in the last 7 days."
and the journal shots would have blown the budget on a commit that changed
nothing, forever, with no way back except accepting the collapsed panel as the
new truth -- which would have retired the gate while leaving it green.

These tests pin the fix and, more usefully, pin the RELATIONSHIP the fix depends
on: the frozen instant has to sit inside the window the fixtures are supposed to
exercise. Refresh the fixtures without refreshing the clock (or the other way
round) and the gate quietly starts photographing an empty panel; that is what
`test_frozen_clock_keeps_the_new_positions_panel_populated` exists to catch.
"""

from __future__ import annotations

import fnmatch
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
E2E = REPO / "test" / "e2e" / "screenshot-diff.e2e.js"
FIXTURES = REPO / "test" / "e2e" / "fixtures" / "data"
BOOK = FIXTURES / "vivek_bot_book.json"
JOURNAL_JS = REPO / "public" / "js" / "journal.js"
TEST_YML = REPO / ".github" / "workflows" / "test.yml"


@pytest.fixture(scope="module")
def src() -> str:
    return E2E.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def book() -> dict:
    return json.loads(BOOK.read_text(encoding="utf-8"))


def _parse(ts: str) -> datetime:
    """ISO-8601 with a Z or an offset, as the fixtures actually write them."""
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _frozen_instant(book: dict) -> datetime:
    return _parse(book["updated_at"])


def _opened_at(trade: dict) -> str | None:
    return trade.get("opened_at") or trade.get("entry_date")


# --------------------------------------------------------------------------- #
# The freeze exists, and is installed early enough to matter.
# --------------------------------------------------------------------------- #

def test_clock_is_frozen_before_the_page_loads(src: str) -> None:
    """A freeze installed after navigation is no freeze at all.

    Playwright's `addInitScript` is the only hook that runs before page scripts.
    Calling it on the CONTEXT rather than the page also covers iframes, and
    doing it before `newPage()` means nothing can read the real clock first.
    """
    assert "freezeClock" in src, "the screenshot run no longer freezes the clock"
    install = re.search(r"await\s+ctx\.addInitScript\(\s*freezeClock\s*,", src)
    assert install, (
        "freezeClock is defined but not installed via ctx.addInitScript -- a page-level "
        "or post-goto install lets the real clock reach the first render"
    )
    assert install.start() < src.index("ctx.newPage()"), (
        "the clock is frozen after newPage() -- install it on the context first"
    )


def test_frozen_clock_is_read_from_the_fixture_not_hard_coded(src: str) -> None:
    """A hard-coded instant is a second thing to remember, so it will be forgotten.

    Reading the timestamp out of the fixture means refreshing the fixtures moves
    the clock with them and the two can never disagree.
    """
    assert re.search(r"FROZEN_MS\s*=\s*\(\s*\(\s*\)\s*=>", src), "FROZEN_MS is no longer computed"
    frozen_block = src[src.index("const FROZEN_MS"):src.index("const FROZEN_MS") + 500]
    assert "BOOK_FIXTURE" in frozen_block and "updated_at" in frozen_block, (
        "FROZEN_MS no longer derives from the fixture's own updated_at"
    )
    # A literal epoch or ISO date assigned into the freeze is the regression:
    # it decouples the clock from the fixtures it is supposed to match.
    assert not re.search(r"FROZEN_MS\s*=\s*1[0-9]{12}", src), "FROZEN_MS is hard-coded to an epoch literal"
    assert not re.search(r"FROZEN_MS\s*=\s*Date\.parse\(\s*[\"']20", src), "FROZEN_MS is hard-coded to a date string"


def test_an_unparseable_fixture_throws_rather_than_falling_back(src: str) -> None:
    """Silently falling back to the real clock rebuilds the exact bug, invisibly.

    A gate that quietly stops being deterministic is worse than one that stops
    running, because it keeps reporting.
    """
    assert re.search(r"if\s*\(\s*!isFinite\(t\)\s*\)\s*throw", src), (
        "a fixture with no parseable updated_at no longer throws -- if this degrades to the "
        "real clock, the gate goes back to drifting and nothing says so"
    )


def test_date_api_survives_the_freeze(src: str) -> None:
    """`class extends Date` would break a bare `Date()` call; a Proxy does not.

    The page parses the fixtures' own timestamps with `new Date(t.opened_at)`,
    so explicit arguments have to pass straight through -- only the zero-argument
    construction and `now()` are pinned.
    """
    freeze = src[src.index("function freezeClock"):]
    freeze = freeze[:freeze.index("\n}\n") + 3]
    assert "new Proxy" in freeze, "the freeze no longer uses a Proxy -- a bare Date() call will throw"
    assert re.search(r"construct:.*args\.length\s*\?", freeze, re.S), (
        "the construct trap no longer passes explicit arguments through -- `new Date(t.opened_at)` "
        "would return the frozen instant and every position would render as opened at once"
    )
    assert "apply:" in freeze, "no apply trap -- calling Date() without `new` throws under a class"
    assert re.search(r'prop\s*===\s*"now"', freeze), "Date.now() is no longer pinned"
    assert "Reflect.get" in freeze, "Date.parse / Date.UTC are no longer reachable through the proxy"


# --------------------------------------------------------------------------- #
# The relationship the freeze depends on. This is the one with teeth.
# --------------------------------------------------------------------------- #

def test_frozen_instant_is_not_before_the_fixtures_it_renders(book: dict) -> None:
    """You cannot photograph a book that has not happened yet."""
    frozen = _frozen_instant(book)
    trades = (book.get("open") or []) + (book.get("closed") or [])
    stamped = [(t.get("symbol"), _parse(ts)) for t in trades if (ts := _opened_at(t))]
    assert stamped, "the fixture book carries no dated positions -- the journal panels render nothing"
    newest_sym, newest = max(stamped, key=lambda pair: pair[1])
    assert newest <= frozen, (
        f"the frozen clock ({frozen.isoformat()}) predates {newest_sym}, opened {newest.isoformat()} -- "
        "the page would render a position from the future"
    )


def test_frozen_clock_keeps_the_new_positions_panel_populated(book: dict) -> None:
    """The gate has to photograph the panel, not its empty state.

    This is the assertion that would have caught the original defect two days
    early. `renderNewPositions` only lists trades opened within
    NEW_POS_WINDOW_MS; once the newest fixture position falls outside it, both
    panels collapse to one line and the shot the gate compares stops containing
    the thing it was built to watch. The window is read from journal.js so that
    changing it there moves this test with it rather than against it.
    """
    window_src = re.search(
        r"NEW_POS_WINDOW_MS\s*=\s*([0-9.]+)\s*\*\s*([0-9.]+)\s*\*\s*([0-9.e+]+)",
        JOURNAL_JS.read_text(encoding="utf-8"),
    )
    assert window_src, "NEW_POS_WINDOW_MS is gone from journal.js -- this test needs re-pointing"
    window_ms = float(window_src.group(1)) * float(window_src.group(2)) * float(window_src.group(3))

    frozen = _frozen_instant(book)
    trades = (book.get("open") or []) + (book.get("closed") or [])
    stamped = [(t.get("symbol"), _parse(ts)) for t in trades if (ts := _opened_at(t))]
    newest_sym, newest = max(stamped, key=lambda pair: pair[1])
    age_ms = (frozen - newest).total_seconds() * 1000.0

    assert age_ms < window_ms, (
        f"at the frozen instant the newest fixture position ({newest_sym}, opened {newest.isoformat()}) "
        f"is {age_ms / 3.6e6:.1f}h old, outside the {window_ms / 3.6e6:.0f}h 'new positions' window -- "
        "both panels render empty and the screenshot gate is watching a blank box. Refresh "
        "test/e2e/fixtures/data/ (which moves the clock with it) rather than widening this test."
    )

    # Not merely inside the window -- inside it with room. Once the clock is
    # frozen nothing ages on its own, so the only way the panel degrades is a
    # PARTIAL refresh: new fixtures against an old clock, or a moved clock
    # against old positions. Both land the newest row near the edge of the
    # window rather than outside it, which the bare `age_ms < window_ms` check
    # above would wave through and the next refresh would then tip over.
    # 75% is the line: at the instant this was written the newest position sat
    # at 35% with 109 hours to spare, so a set cut anywhere near correctly clears
    # it easily, and only a half-done refresh does not.
    HEADROOM = 0.75
    assert age_ms <= window_ms * HEADROOM, (
        f"the newest fixture position ({newest_sym}) sits at {100 * age_ms / window_ms:.0f}% of the "
        f"new-positions window -- inside it, but with under {100 * (1 - HEADROOM):.0f}% to spare. That is "
        "the signature of a half-done refresh (fixtures moved but not the clock, or the reverse); "
        "re-cut test/e2e/fixtures/data/ as one set."
    )

    inside = [s for s, ts in stamped if (frozen - ts).total_seconds() * 1000.0 < window_ms]
    assert len(inside) >= 3, (
        f"only {len(inside)} fixture position(s) fall inside the new-positions window at the frozen "
        "instant -- the panel the gate exists to photograph is nearly empty, so a layout regression "
        "inside it would no longer move enough pixels to fail. Fixtures need re-cutting."
    )


def test_fixture_payloads_are_internally_dated_as_one_set(book: dict) -> None:
    """Mixed vintages make the frozen clock right for one file and wrong for the rest.

    Every fixture that carries its own timestamp has to sit at or before the
    instant the clock is frozen to, or the page renders one payload as live and
    another as impossible.
    """
    frozen = _frozen_instant(book)
    late = []
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        stamp = payload.get("generated_at") or payload.get("updated_at")
        if not stamp:
            continue
        when = _parse(stamp)
        if when > frozen:
            late.append(f"{path.name} @ {when.isoformat()}")
    assert not late, (
        f"fixture(s) stamped after the frozen clock ({frozen.isoformat()}): {', '.join(late)} -- "
        "the shot would render them as data from the future"
    )


# --------------------------------------------------------------------------- #
# The cache key is the only way to retire a baseline. It has to move with the fix.
# --------------------------------------------------------------------------- #

def test_baseline_cache_key_is_versioned_and_never_restore_keyed() -> None:
    """`restore-keys` would defeat the freeze by resurrecting a pre-freeze baseline.

    An exact-key-only cache is what makes a bump a clean break. Adding a prefix
    fallback means a bumped key silently restores the old baseline it was bumped
    to escape, and the run diffs against a picture drawn by a clock that no
    longer exists.
    """
    yml = TEST_YML.read_text(encoding="utf-8")
    block = re.search(
        r"- name: Restore screenshot baselines(.*?)(?=\n      - name:)", yml, re.S
    )
    assert block, "the screenshot baseline cache step is gone from test.yml"
    body = block.group(1)
    key = re.search(r"key:\s*screenshot-baselines-v(\d+)-", body)
    assert key, "the baseline cache key is no longer versioned -- there is no way to retire a baseline"
    assert int(key.group(1)) >= 11, (
        "the baseline cache key is below v11, the bump that discarded every baseline cut before the "
        "clock was frozen. A pre-freeze baseline diffs against a clock that no longer exists."
    )
    assert "restore-keys" not in body, (
        "restore-keys on the baseline cache resurrects the baseline a version bump exists to discard"
    )


def _cache_block() -> str:
    yml = TEST_YML.read_text(encoding="utf-8")
    block = re.search(r"- name: Restore screenshot baselines(.*?)(?=\n      - name:)", yml, re.S)
    assert block, "the screenshot baseline cache step is gone from test.yml"
    return block.group(1)


def test_the_cache_key_digests_the_FIXTURES_the_clock_is_read_from() -> None:
    """The digest is what makes the freeze survive a fixture refresh.

    FROZEN_MS is read out of the fixture book, so refreshing the fixtures MOVES
    the clock and repaints every relative-time row at once -- a legitimate,
    unavoidable, whole-page diff. With the fixtures in the cache key that cuts a
    FRESH cache entry, which self-baselines and SAVES. Without it the run falls
    through to the `.clock` sentinel, which discards and re-cuts but cannot
    persist (`actions/cache@v4` does not re-save on a key HIT), so every
    subsequent run discards again and the gate compares nothing until a human
    bumps the version.

    So the glob has to actually cover the file FROZEN_MS is derived from. A
    digest over the wrong directory is worse than none: it looks like the
    protection is there.
    """
    body = _cache_block()
    globs = re.findall(r"hashFiles\(\s*'([^']+)'\s*\)", body)
    assert globs, (
        "the baseline cache key no longer digests the fixtures -- a fixture refresh moves "
        "FROZEN_MS, repaints every relative-time row, and leans on the .clock sentinel, which "
        "cannot save a re-cut baseline on a key hit"
    )
    # BOOK_FIXTURE in the e2e script is the file the clock is read from. Express
    # it repo-relative with forward slashes, the way hashFiles() globs are written.
    book_rel = BOOK.relative_to(REPO).as_posix()
    assert any(fnmatch.fnmatch(book_rel, g) for g in globs), (
        f"the cache key digests {globs} but the frozen clock is read from {book_rel} -- the digest "
        "does not move when the clock does, so a fixture refresh would restore a baseline drawn by "
        "the previous clock"
    )


def test_the_clock_stamp_lives_INSIDE_the_directory_the_cache_restores() -> None:
    """The stamp and the pictures it describes have to be restored as one unit.

    Put `.clock` beside `__baseline__` instead of inside it and the cache brings
    back the PNGs without the stamp -- which the sentinel reads as a pre-freeze
    baseline and discards, on every single run, for ever. The gate stays green
    and stops comparing anything, which is the quiet failure this whole item
    exists to avoid.
    """
    src = E2E.read_text(encoding="utf-8")
    assert re.search(r"const\s+CLOCK\s*=\s*path\.join\(\s*BASE\s*,", src), (
        "the .clock stamp is no longer built on BASE -- if it does not live inside the cached "
        "baseline directory it cannot be restored with the pictures it describes"
    )
    base = re.search(r'const\s+BASE\s*=\s*path\.join\(\s*__dirname\s*,\s*"([^"]+)"\s*\)', src)
    assert base, "BASE is no longer a simple __dirname join -- re-point this test"
    cached = re.search(r"path:\s*(\S+)", _cache_block())
    assert cached, "the baseline cache step no longer names a path"
    assert cached.group(1).strip().rstrip("/").endswith(base.group(1)), (
        f"test.yml caches {cached.group(1)} but the baselines (and the .clock stamp inside them) "
        f"are written to {base.group(1)} -- the stamp would never survive a run"
    )


def test_a_baseline_from_a_dead_clock_is_DISCARDED_not_failed() -> None:
    """The asymmetry is the item, not an implementation detail.

    A re-baseline costs one run of comparison. A red costs a person's attention
    on a push they cannot act on -- and this gate produced roughly one of those
    a day for weeks, which is how a channel gets muted. Muting is the real
    damage, because the next red is a genuine one.

    So the reconcile must be structurally incapable of failing the run: no exit,
    no failure counter, no rethrow. The JS suite proves the behaviour; this pins
    the shape, because the tempting future edit is exactly "make it strict".
    """
    src = E2E.read_text(encoding="utf-8")
    body = re.search(r"function reconcileBaselineClock\(\)\s*\{(.*?)\n\}", src, re.S)
    assert body, "reconcileBaselineClock is gone -- the baseline can no longer answer for its own clock"
    fn = body.group(1)
    assert "process.exit" not in fn, "the reconcile exits the process -- a stale baseline must not fail the run"
    assert "failures" not in fn, "the reconcile increments the failure counter -- a discard is not a failure"
    assert "throw" not in fn, "the reconcile throws -- a stale baseline must be re-cut, not fatal"


def test_a_silent_discard_LOOP_is_visible_in_the_run_log() -> None:
    """The sentinel's own limitation has to be observable, or it hides the bug.

    `actions/cache@v4` does not re-save on a key HIT, so a discard cannot
    persist: if the fixtures ever move without the cache key moving, every run
    discards, re-cuts and passes -- green for ever, comparing nothing. The only
    thing standing between that state and going unnoticed is the run log, so the
    reset count has to reach the summary line and the message has to name the
    remedy in words rather than leaving it to be re-derived.
    """
    src = E2E.read_text(encoding="utf-8")
    summary = re.search(r"console\.log\(`\\n\$\{created\}[^`]*`\)", src)
    assert summary, "the run summary line no longer reports its counts in the expected form"
    assert "${reset}" in summary.group(0), (
        "the summary line does not report how many baselines were discarded -- a run that discards "
        "and re-cuts on EVERY pass looks identical to a healthy one"
    )
    reset_log = re.search(r"BASELINE RESET(.*?)\);", src, re.S)
    assert reset_log, "the reset no longer says anything on the run page"
    msg = reset_log.group(1)
    assert "test.yml" in msg and "bump" in msg, (
        "the reset message no longer names the file and the action that breaks a discard loop"
    )
    assert "PASSING" in msg, (
        "the reset message no longer states that the run is passing -- a loud line that looks like a "
        "failure is how a green run gets read as a red one"
    )


# --------------------------------------------------------------------------- #
# The convention that keeps every OTHER suite honest, turned into a gate.
# --------------------------------------------------------------------------- #

def test_every_javascript_suite_has_a_step_in_the_workflow() -> None:
    """An unregistered suite is not a weak gate, it is no gate at all.

    Unlike `tests/*.py` -- which pytest collects by walking the directory -- each
    `test/*.test.js` file only ever runs because a step in test.yml names it.
    Adding a suite and forgetting the step produces a file full of green
    assertions locally and zero coverage in CI, and nothing anywhere says so.
    The project rule has been written down since Tier 5; this is the first thing
    that enforces it.
    """
    yml = TEST_YML.read_text(encoding="utf-8")
    suites = sorted(p.name for p in (REPO / "test").glob("*.test.js"))
    assert suites, "no JS suites found -- re-point this test"
    missing = [s for s in suites if f"node test/{s}" not in yml]
    assert not missing, (
        f"{len(missing)} JS suite(s) exist but no workflow step runs them: {', '.join(missing)}. "
        "Add a `- name: ... / run: node test/<file>` step to the `javascript` job in test.yml -- "
        "until then those assertions pass on your machine and are never checked on a push."
    )

"""Deploy-stamp gate — public/version.json (2026-08-13).

WHY THIS EXISTS, and it is not tidiness.

`public/js/telemetry.js` is the only thing that tells a person their open tab is
running a bundle the server has replaced. It has two legs:

  1. version.json changed between load and the next focus   -> nudge
  2. a NEW service worker took control (controllerchange)   -> nudge

**Leg 2 only fires when `sw.js` ITSELF changes bytes** — the browser installs a
new worker on a byte diff, not on a deploy. An ordinary deploy (edit a JS file,
bump its `?v=`) leaves sw.js untouched, so leg 2 stays silent and leg 1 is the
ONLY signal there is. version.json's own note used to claim the opposite ("the
service-worker controllerchange event catches every deploy regardless"). It does
not, and that sentence is why nobody noticed the stamp had been frozen at
`2026.07.29-1` across a fortnight of asset deploys with the nudge structurally
dead in both legs at once.

The cost is not cosmetic. `?v=` assets are CACHE-FIRST in the service worker, so
a tab held open across a deploy keeps serving the old bundle from cache
indefinitely — and that stale bundle keeps talking to a live `/api/`. The close
path changed shape this week (single -> `closes[]` batch); a tab from before it
is a client posting the old contract at the new endpoint.

SO THE STAMP IS ENFORCED, NOT REMEMBERED. `version` carries a digest of the
shipped asset fingerprint. Change any `?v=` in any page, or sw.js's CACHE name,
and the digest moves and this test goes red — and the only way to fix it is to
edit the very string telemetry.js compares. There is deliberately NO separate
generator script to drift out of step with this file (TOP100 #34 is what that
looks like): the failure message prints the exact value to write.

It lives in `tests/` rather than `test/` because it executes nothing — it reads
four shipped files as source, exactly like test_workflow_hardening.py. New
`tests/*.py` need no registration; pytest collects the directory.
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
STAMP = PUB / "version.json"
SW = PUB / "sw.js"
TELEMETRY = PUB / "js" / "telemetry.js"

_REF_RE = re.compile(r'(?:href|src)="([^"]+\?v=\d+)"')
_STAMP_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})-([0-9a-f]{8})$")


def asset_refs():
    """Every versioned asset reference across every shipped page, deduped+sorted.

    Sorted so the digest cannot depend on directory listing order or on which
    page happens to mention an asset first.
    """
    seen = set()
    for page in sorted(PUB.glob("*.html")):
        seen.update(_REF_RE.findall(page.read_text(encoding="utf-8")))
    return sorted(seen)


def sw_cache_name():
    m = re.search(r'const\s+CACHE\s*=\s*"([^"]+)"', SW.read_text(encoding="utf-8"))
    assert m, "sw.js no longer declares a CACHE constant - the fingerprint lost an input"
    return m.group(1)


def fingerprint():
    body = "\n".join(asset_refs()) + "\nsw:" + sw_cache_name()
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]


@pytest.fixture(scope="module")
def stamp():
    return json.loads(STAMP.read_text(encoding="utf-8"))


# ---- shape ------------------------------------------------------------------


def test_the_stamp_is_SURFACED_on_the_pages(stamp):
    """Task 14 (2026-08-20): nav.js renders the stamp into the MORE menu, the
    mobile MORE sheet and the shared footer. Two pinned properties: it reads
    version.json with cache no-store (a cached stamp is a stamp that cannot
    change inside a session - the same discipline telemetry.js is pinned to
    below), and it renders textContent, never innerHTML (the stamp is data)."""
    nav = (PUB / "js" / "nav.js").read_text(encoding="utf-8")
    at = nav.index('fetch("version.json"')
    window = nav[at:at + 200]
    assert '"no-store"' in window, "the stamp fetch must bypass the HTTP cache"
    fn = nav[nav.index("function stampVersion"):nav.index("function init()")]
    assert "textContent" in fn and "innerHTML" not in fn
    for cls in ("nav-version", "more-sheet-version"):
        assert cls in fn, f"the {cls} surface disappeared"


def test_version_json_is_valid_json_with_a_string_version(stamp):
    assert isinstance(stamp.get("version"), str)


def test_the_stamp_is_a_date_and_a_digest_and_the_date_is_real(stamp):
    m = _STAMP_RE.match(stamp["version"])
    assert m, f'version "{stamp["version"]}" must read YYYY.MM.DD-<8 hex>'
    date(int(m.group(1)), int(m.group(2)), int(m.group(3)))  # raises on 2026.13.99


# ---- THE GATE ---------------------------------------------------------------


def test_the_stamp_digest_matches_the_shipped_asset_fingerprint(stamp):
    want = fingerprint()
    got = stamp["version"].rsplit("-", 1)[-1]
    assert got == want, (
        "\nAn asset version or the sw.js CACHE name moved without the deploy stamp."
        "\nEvery open tab loses its only new-deploy signal until this is bumped."
        "\nSet public/version.json version to: <today YYYY.MM.DD>-" + want + "\n"
    )


def test_the_fingerprint_actually_covers_the_assets():
    """Guards the gate itself.

    A refs regex that silently matched nothing would make the digest a constant
    and every future asset bump invisible - green for ever, checking nothing.
    That is the failure mode the screenshot sentinel's own reset-loop note
    describes, and it is worth one cheap assertion here.
    """
    refs = asset_refs()
    assert len(refs) >= 20, f"expected >=20 versioned asset refs across the pages, saw {len(refs)}"
    index = (PUB / "index.html").read_text(encoding="utf-8")
    shared = re.search(r"css/styles\.css\?v=\d+", index).group(0)
    assert shared in refs, "the shared stylesheet is missing from the fingerprint"


# ---- the mechanism pins -----------------------------------------------------
# Each of these is a way to leave the gate above green while the thing it
# protects is dead, so they are asserted rather than assumed.


def test_telemetry_reads_the_stamp_with_cache_no_store():
    src = TELEMETRY.read_text(encoding="utf-8")
    assert re.search(r'fetch\(\s*"version\.json"\s*,\s*\{\s*cache:\s*"no-store"\s*\}', src), (
        "telemetry.js must fetch version.json with cache:no-store, or the HTTP cache freezes the stamp"
    )


def test_the_stamp_is_never_requested_with_a_v_query():
    """sw.js routes ANY url whose search contains "v=" to cacheFirst.

    A cache-first version.json is a stamp that can never change inside an
    installed PWA - which is the exact failure this whole file exists to
    prevent, wearing a helpful cache-busting hat.
    """
    src = TELEMETRY.read_text(encoding="utf-8")
    m = re.search(r'fetch\(\s*"(version\.json[^"]*)"', src)
    assert m, "telemetry.js no longer fetches version.json by that literal"
    assert "v=" not in m.group(1), f'version.json must be fetched unqueried, saw "{m.group(1)}"'
    assert 'url.search.includes("v=")' in SW.read_text(encoding="utf-8"), (
        "sw.js no longer routes ?v= to cacheFirst - re-read this docstring before editing the test"
    )


def test_the_controllerchange_leg_is_still_guarded_by_hadController():
    """Leg 2 must NOT fire on the FIRST service-worker install.

    There was no previous bundle to be stale. Drop the guard and every first
    visit gets a "new version available" nudge, and the nudge stops meaning
    anything - which is how the stamp came to be ignorable in the first place.
    """
    src = TELEMETRY.read_text(encoding="utf-8")
    assert re.search(r"controllerchange[\s\S]{0,160}hadController", src), (
        "the controllerchange handler must stay gated on hadController"
    )


def test_the_service_worker_is_in_this_workflows_path_filter():
    """public/js/** does NOT cover public/sw.js - it sits at the public/ root.

    Every edit to the service worker used to ship with the whole test gate
    skipped. This test reads sw.js, so the filter must trigger on it (TOP100
    #48's rule: a path a suite READS belongs in the filter).
    """
    wf = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    for path in ('- "public/sw.js"', '- "public/version.json"'):
        assert path in wf, f"{path} must be in test.yml's push path filter"

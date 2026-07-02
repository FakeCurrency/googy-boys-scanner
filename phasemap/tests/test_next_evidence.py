"""'Wanted next' line: full (state x direction) coverage, computed slots only."""

import pytest

from phasemap.engine.scanner import scan_ticker
from phasemap.narrate.renderer import render_next
from phasemap.narrate.templates import NEXT_EVIDENCE
from phasemap.output.writer import VALID_STATES
from phasemap.tests import synth


def test_next_evidence_covers_every_state_and_direction():
    for state in VALID_STATES:
        for direction in ("bullish", "bearish"):
            assert (state, direction) in NEXT_EVIDENCE, \
                f"missing next-evidence template: {state} {direction}"


@pytest.mark.parametrize("fixture,direction", [
    (synth.fixture_trap_only, "bullish"),
    (synth.fixture2, "bullish"),
    (synth.fixture1, "bullish"),
    (synth.fixture5, "bullish"),
    (synth.fixture6, "bullish"),
    (synth.fixture_complete, "bullish"),
    (synth.fixture7, "bearish"),
])
def test_next_evidence_renders_cleanly(fixture, direction):
    recs = [r for r, _ in scan_ticker("TST", fixture())
            if r["direction"] == direction]
    assert recs
    text = render_next(recs[0])
    assert "{" not in text and "}" not in text
    lowered = text.lower()
    for verb in ("you should", "buy ", "sell "):
        assert verb not in lowered


def test_running_next_points_at_first_unconsumed_target():
    recs = [r for r, _ in scan_ticker("TST", synth.fixture1())
            if r["direction"] == "bullish"]
    text = render_next(recs[0])
    # fixture 1's T1 is consumed — the line must point at T2
    assert "T2" in text

"""M2 acceptance: full template coverage (every state x direction), slot
filling from computed fields only, empty-stats guardrail, disclaimer."""

import pytest

from phasemap.engine.scanner import scan_ticker
from phasemap.narrate.renderer import fmt_price, render
from phasemap.narrate.templates import DISCLAIMER, TEMPLATES
from phasemap.output.writer import VALID_STATES
from phasemap.tests import synth


def test_template_coverage_every_state_and_direction():
    for state in VALID_STATES:
        for direction in ("bullish", "bearish"):
            assert (state, direction) in TEMPLATES, \
                f"missing template: {state} {direction}"


FIXTURE_STATES = [
    (synth.fixture_trap_only, "bullish", "TRAP_SET"),
    (synth.fixture2, "bullish", "SWEPT"),
    (synth.fixture1, "bullish", "RUNNING"),
    (synth.fixture5, "bullish", "STALLED"),
    (synth.fixture6, "bullish", "DEAD"),
    (synth.fixture_complete, "bullish", "COMPLETE"),
    (synth.fixture7, "bearish", "RUNNING"),
]


@pytest.mark.parametrize("fixture,direction,state", FIXTURE_STATES)
def test_narration_renders_cleanly(fixture, direction, state):
    recs = [r for r, _ in scan_ticker("TST", fixture())
            if r["direction"] == direction]
    assert recs, f"no {direction} record for {state}"
    rec = recs[0]
    assert rec["state"] == state
    text = render(rec)
    assert text.endswith(DISCLAIMER)
    assert "{" not in text and "}" not in text     # every slot filled
    # the spec's worked RUNNING template deliberately opens with the
    # displacement date, not the ticker — only check where the slot exists
    if "{ticker}" in TEMPLATES[(state, direction)]:
        assert rec["ticker"] in text
    # no advice verbs (guardrail 2)
    lowered = text.lower()
    for verb in ("you should", "buy ", "sell "):
        assert verb not in lowered


def test_stats_slot_empty_until_backtest_exists():
    recs = [r for r, _ in scan_ticker("TST", synth.fixture1())
            if r["direction"] == "bullish"]
    text = render(recs[0])
    assert "historically" not in text.lower()      # no claims before M4


def test_stats_slot_fills_when_m4_supplies_numbers():
    recs = [r for r, _ in scan_ticker("TST", synth.fixture1())
            if r["direction"] == "bullish"]
    text = render(recs[0], stats={"window_sessions": 20, "hit_rate_pct": 63,
                                  "market": "ASX"})
    assert "Historically" in text
    assert "63%" in text


def test_displaced_day_of_narration():
    """Truncate fixture 1 at the displacement bar -> day-of DISPLACED text."""
    df = synth.fixture1().iloc[:262].reset_index(drop=True)
    recs = [r for r, _ in scan_ticker("TST", df) if r["direction"] == "bullish"]
    assert recs and recs[0]["state"] == "DISPLACED"
    text = render(recs[0])
    assert "displacement candle today" in text
    assert text.endswith(DISCLAIMER)


def test_price_formatting_magnitude_aware():
    assert fmt_price(0.0485) == "0.0485"
    assert fmt_price(0.965) == "0.965"
    assert fmt_price(21.5) == "21.50"

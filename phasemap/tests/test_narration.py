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


def _displaced():
    """Fixture 1 truncated at the displacement bar: T1 is still open."""
    df = synth.fixture1().iloc[:262].reset_index(drop=True)
    recs = [r for r, _ in scan_ticker("TST", df) if r["direction"] == "bullish"]
    assert recs and recs[0]["state"] == "DISPLACED"
    return recs[0]


def test_stats_slot_fills_when_m4_supplies_numbers():
    text = render(_displaced(), stats={"window_sessions": 20, "hit_rate_pct": 63,
                                       "market": "ASX"})
    assert "Historically" in text
    assert "63% of the time on the ASX." in text


def test_stats_names_the_market_in_words_not_its_code():
    """REFINE200 #195: the artefact's upper-cased code read 'on the CRYPTO'."""
    text = render(_displaced(), stats={"window_sessions": 20, "hit_rate_pct": 41,
                                       "market": "CRYPTO"})
    assert "in crypto." in text and "CRYPTO" not in text


def test_stats_claim_is_dropped_once_t1_is_consumed():
    """REFINE200 #195: 78 live cards carried 'Historically this pattern
    reached its first target zone...' under a T1 that was already consumed."""
    recs = [r for r, _ in scan_ticker("TST", synth.fixture1())
            if r["direction"] == "bullish"]
    assert recs[0]["zones"] and any(z["id"] == "t1" and z["status"] == "CONSUMED"
                                    for z in recs[0]["zones"])
    text = render(recs[0], stats={"window_sessions": 20, "hit_rate_pct": 63,
                                  "market": "ASX"})
    assert "historically" not in text.lower()


def test_a_consumed_t1_is_never_called_the_first_draw():
    """REFINE200 #195: render() named targets[0] the 'First draw' regardless
    of status, while render_next() (the WANTED NEXT line) pointed at T2."""
    recs = [r for r, _ in scan_ticker("TST", synth.fixture1())
            if r["direction"] == "bullish"]
    rec = recs[0]
    assert rec["state"] == "RUNNING"
    t1 = next(z for z in rec["zones"] if z["id"] == "t1")
    t2 = next(z for z in rec["zones"] if z["id"] == "t2")
    text = render(rec)
    assert "First draw" not in text
    assert "T1 is already consumed; the next draw is the " \
        f"{fmt_price(t2['low'])}–{fmt_price(t2['high'])} zone" in text
    assert f"{fmt_price(t1['low'])}–{fmt_price(t1['high'])} zone" not in text


def test_an_open_t1_is_still_the_first_draw():
    rec = _displaced()
    t1 = next(z for z in rec["zones"] if z["id"] == "t1")
    assert f"First draw is the {fmt_price(t1['low'])}–{fmt_price(t1['high'])} zone" \
        in render(rec)


def test_displaced_day_of_narration():
    """Truncate fixture 1 at the displacement bar -> day-of DISPLACED text.
    REFINE200 #196: the bar is the record's LATEST session, not 'today' — the
    nightly lands after Melbourne midnight, a day after the bar it reads."""
    text = render(_displaced())
    assert "displacement candle on its latest session" in text
    assert "today" not in text
    assert text.endswith(DISCLAIMER)


def test_price_formatting_magnitude_aware():
    assert fmt_price(0.0485) == "0.0485"
    assert fmt_price(0.965) == "0.965"
    assert fmt_price(21.5) == "21.50"

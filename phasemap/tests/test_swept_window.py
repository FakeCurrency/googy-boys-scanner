"""REFINE200 #195: SWEPT's bars_remaining equals what the ENGINE will accept.

The engine tests bars sweep+1 .. sweep+displacement_window_bars for a
displacement, and tests displacement BEFORE expiry, so bar sweep+window can
still displace. The metric was published one short ("0 sessions to prove it"
on 98 live cards while the engine still accepted a displacement next bar).
These tests drive the real engine rather than restating the formula.
"""

import pytest

from phasemap.config import CONFIG
from phasemap.engine.scanner import scan_ticker
from phasemap.narrate.renderer import render, render_next, sessions
from phasemap.tests import synth

WAIT = synth.flat(1, 0.972, 0.007, synth.VOL)[0]


def _bull(bars):
    recs = [r for r, _ in scan_ticker("TST", synth.bars_df(bars))
            if r["direction"] == "bullish"]
    return recs[0] if recs else None


@pytest.mark.parametrize("waited", range(CONFIG.displacement_window_bars))
def test_bars_remaining_is_exactly_the_bars_the_engine_still_accepts(waited):
    base = synth.base_to_box() + [synth.SWEEP_BAR] + [WAIT] * waited
    rec = _bull(base)
    assert rec["state"] == "SWEPT"
    left = rec["metrics"]["bars_remaining"]
    assert left == CONFIG.displacement_window_bars - waited
    assert left >= 1, "a SWEPT record always has at least one session left"
    # the LAST session it promises still displaces...
    assert _bull(base + [WAIT] * (left - 1) + [synth.DISPLACEMENT_BAR])["state"] \
        == "DISPLACED"
    # ...and one session later the sweep has expired
    late = _bull(base + [WAIT] * left + [synth.DISPLACEMENT_BAR])
    assert late is None or late["state"] != "DISPLACED"


def test_sessions_is_pluralised():
    assert sessions(1) == "1 session"
    assert sessions(3) == "3 sessions"
    assert sessions("?") == "? sessions"


def test_the_last_session_reads_singular_in_both_lines():
    waited = CONFIG.displacement_window_bars - 1
    rec = _bull(synth.base_to_box() + [synth.SWEEP_BAR] + [WAIT] * waited)
    assert rec["metrics"]["bars_remaining"] == 1
    assert "now has 1 session to prove it" in render(rec)
    assert "within 1 session, or the setup expires" in render_next(rec)


def test_stalled_copy_describes_what_the_engine_does_next():
    """REFINE200 #195: STALLED never resumes and there is no rotation/Fib
    scanner to hand it to; it dies on a close through the floor or drops off
    after stalled_expiry_bars."""
    recs = [r for r, _ in scan_ticker("TST", synth.fixture5())
            if r["direction"] == "bullish"]
    rec = recs[0]
    assert rec["state"] == "STALLED"
    text, nxt = render(rec), render_next(rec)
    for s in (text, nxt):
        assert "watchlist" not in s and "deep-retracement" not in s
        assert f"{CONFIG.stalled_expiry_bars} sessions" in s

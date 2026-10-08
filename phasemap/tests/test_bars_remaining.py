"""Audit #29 (2026-10-08): the SWEPT countdown matches the engine's window.

The engine accepts a displacement on bars sweep..sweep+5 (it tests bar
sweep+5 before expiring the sweep -- config: "within 5 bars of sweep,
inclusive"), but the published bars_remaining was sweep + 5 - 1 - i, so the
sweep+4 record said "The market now has 0 sessions to prove it" while a
qualifying candle next session still turned it DISPLACED (live: ASX GGE
displaced on sweep+5, the day after its record said 0 remained).
"""

import re

from phasemap.config import CONFIG
from phasemap.engine.scanner import scan_ticker
from phasemap.narrate.renderer import render, render_next
from phasemap.tests import synth

VOL = synth.VOL
SWEEP = 260
BARS = synth.base_to_box() + [synth.SWEEP_BAR] + synth.flat(4, 0.972, 0.007, VOL)


def _bull(bars):
    return [r for r, _ in scan_ticker("T", synth.bars_df(bars))
            if r["direction"] == "bullish"]


def test_the_countdown_names_every_session_the_engine_still_accepts():
    n = CONFIG.displacement_window_bars
    for k in range(SWEEP, SWEEP + n):
        rec = _bull(BARS[:k + 1])[0]
        assert rec["state"] == "SWEPT"
        assert rec["metrics"]["bars_remaining"] == SWEEP + n - k
    last = _bull(BARS)[0]                         # bar sweep+4
    assert last["metrics"]["bars_remaining"] == 1
    assert re.search(r"has 1 sessions? to prove it", render(last))
    assert re.search(r"within 1 sessions?,", render_next(last))


def test_the_last_counted_session_really_is_accepted():
    # one session remained on sweep+4; a displacement candle on sweep+5 counts
    rec = _bull(BARS + [synth.DISPLACEMENT_BAR])[0]
    assert rec["state"] == "DISPLACED"


def test_no_swept_record_ever_reads_zero():
    # sweep+5 without displacement expires the sweep, so 0 is never published
    rec = _bull(BARS + synth.flat(1, 0.972, 0.007, VOL))
    assert not rec or rec[0]["state"] != "SWEPT"

"""Audit #24 (2026-10-08): the box belongs to ONE setup.

box_low/box_high used to survive _reset() and the TRAP_SET -> NEUTRAL exit,
so after a ticker's first box the sweep-time fallback ("the 40-bar box is
always defined") never ran again. A later sweep from NEUTRAL inherited a box
from an earlier price regime and published its edge as a "top/bottom of the
range" TARGET (live: ASX APE's box_low target 16.32-16.74 against a real
40-bar box of 20.21-24.52 at its sweep).
"""

import math

from phasemap.engine.indicators import compute_indicators
from phasemap.engine.setup_engine import SetupEngine
from phasemap.tests import synth

VOL = synth.VOL


def _complete_then_decline_then_sweep():
    """fixture_complete (box 0.96-1.04 -> COMPLETE), a 120-bar decline to
    ~0.70, then a fresh sweep + displacement far below the old range."""
    bars = synth.base_to_box() + [synth.SWEEP_BAR, synth.DISPLACEMENT_BAR] + synth.RUN_BARS
    bars += [(1.076, 1.100, 1.070, 1.095, VOL), (1.096, 1.120, 1.090, 1.115, VOL),
             (1.116, 1.150, 1.110, 1.145, VOL)]
    bars += synth.trend(120, 1.145, -0.0037, 0.02, VOL)
    ind = compute_indicators(synth.bars_df(bars))
    kl = float(ind.key_low[len(bars) - 1])
    last = bars[-1][3]
    bars.append((last, last + 0.005, kl - 0.03, kl + 0.01, VOL))      # sweep
    ind = compute_indicators(synth.bars_df(bars))
    rng = 2.2 * float(ind.atr20[len(bars) - 1])
    o = kl + 0.012
    bars.append((o, o + rng, o - 0.001, o + 0.97 * rng, VOL))         # displacement
    return synth.bars_df(bars)


def _run(df, bull=True):
    """Engine run that records (sweep bar, box the engine used) at every sweep."""
    ind = compute_indicators(df)
    seen = []

    def rec(i, eng):
        if eng.sweep_index == i:
            seen.append((i, eng.box_low, eng.box_high))

    eng = SetupEngine(ind=ind, bull=bull, recorder=rec)
    eng.process()
    return eng, ind, seen


def test_a_later_sweep_uses_the_box_at_that_sweep_not_a_stale_one():
    eng, ind, _ = _run(_complete_then_decline_then_sweep())
    assert eng.state == "DISPLACED"
    s = eng.sweep_index
    assert eng.box_low == float(ind.box_low[s])
    assert eng.box_high == float(ind.box_high[s])
    # no target may be built off the old 0.96-1.04-era range
    for z in eng.targets:
        if "box_high" in z.sources:
            assert z.low <= float(ind.box_high[s]) <= z.high
    assert all(z.low < 1.0 for z in eng.targets)


def test_every_sweep_takes_the_40_bar_box_of_its_own_bar():
    # the invariant, over every sweep either direction prints, on every
    # fixture that sweeps (TRAP_SET sweeps included: module 1 re-reads the
    # box on each compressed bar, so the two paths agree by construction)
    frames = [_complete_then_decline_then_sweep(), synth.fixture1(), synth.fixture2(),
              synth.fixture3(), synth.fixture5(), synth.fixture6(),
              synth.fixture7(), synth.fixture8(), synth.fixture_complete()]
    checked = 0
    for df in frames:
        for bull in (True, False):
            _eng, ind, seen = _run(df, bull)
            for i, lo, hi in seen:
                assert lo == float(ind.box_low[i]) and hi == float(ind.box_high[i])
                checked += 1
    assert checked >= 8


def test_reset_and_trap_exit_clear_the_box():
    eng, ind, _ = _run(synth.fixture_complete())
    assert eng.state == "COMPLETE"
    eng._reset(len(ind.close))
    assert math.isnan(eng.box_low) and math.isnan(eng.box_high)

    # a TRAP_SET that decompresses without a sweep leaves no box behind
    eng = SetupEngine(ind=ind, bull=True)
    eng.box_low, eng.box_high, eng.state = 0.96, 1.04, "TRAP_SET"
    i = next(j for j in range(len(ind.close)) if not ind.compressed[j])
    eng._module1_consolidation(i)
    assert eng.state == "NEUTRAL"
    assert math.isnan(eng.box_low) and math.isnan(eng.box_high)

"""Audit #27 (2026-10-08): no zone edge at or below zero.

The bull INVALIDATION_HARD band is [extreme - buffer, extreme] and the buffer
is at least two ticks, so on a 1-2 tick ASX stock its floor went negative
(ENV/FHS -0.0002..0.0018, narrated "intact above -0.0002"). The bear fib
extension's far edge is sweep_extreme - 2.0 x leg, negative whenever the leg
exceeds half the sweep high (a 50%+ crash day): crypto JUP published a t2
band entirely below zero. chart.js reads inv_hard.low as the plan stop.
"""

from phasemap.backtest.harness import run_ticker
from phasemap.engine.scanner import scan_ticker
from phasemap.narrate.renderer import render, render_next
from phasemap.tests import synth

VOL = synth.VOL


def _bear_crash():
    """Fixture 7's box + sweep of the highs, then a 60% crash displacement."""
    base = synth.mirror_df(synth.bars_df(synth.base_to_box() + [synth.SWEEP_BAR]))
    rows = [tuple(r) for r in
            base[["Open", "High", "Low", "Close", "Volume"]].itertuples(index=False)]
    rows.append((1.025, 1.030, 0.400, 0.410, VOL))
    return synth.bars_df(rows)


def _penny(k=0.002):
    """Fixture 1 scaled to a ~0.002 ASX name (buffer = 2 ticks > the low)."""
    df = synth.fixture1()
    for c in ("Open", "High", "Low", "Close"):
        df[c] = df[c] * k
    df["Volume"] = 1e9
    return df


def _rec(df, direction, market="asx"):
    for rec, eng in scan_ticker("TST", df, market=market):
        if rec["direction"] == direction:
            return rec, eng
    return None, None


def test_a_crash_day_never_projects_a_target_below_zero():
    rec, eng = _rec(_bear_crash(), "bearish")
    assert rec["state"] == "DISPLACED"
    targets = [z for z in rec["zones"] if z["type"] == "TARGET"]
    assert targets                                    # the 1.0-1.272 band stays
    for z in rec["zones"]:
        assert 0 < z["low"] < z["high"], z
    # the 1.618-2.0 band's far edge (1.055 - 2.0 x 0.655) is below zero: dropped
    assert not any("fib_ext_1618" in z.get("sources", []) for z in targets)


def test_a_one_tick_floor_is_clamped_positive():
    rec, eng = _rec(_penny(), "bullish")
    inv = next(z for z in rec["zones"] if z["id"] == "inv_hard")
    assert 0 < inv["low"] < inv["high"]
    text = render(rec) + " " + render_next(rec)
    assert "-0." not in text
    for z in rec["zones"]:
        assert z["low"] > 0


def test_the_backtest_stop_is_positive_too():
    for sig in run_ticker("TST", _penny(), "asx"):
        assert sig["inv_low"] is None or sig["inv_low"] > 0


def test_no_published_zone_is_non_positive_across_scales():
    for price, market in ((0.002, "asx"), (0.004, "asx"), (2e-5, "crypto"),
                          (0.6, "nasdaq")):
        for seed in range(16):
            df = synth.seeded_walk(seed, 520, price)
            for rec, _eng in scan_ticker("S", df, market=market):
                for z in rec["zones"]:
                    assert z["low"] > 0, (price, seed, z)

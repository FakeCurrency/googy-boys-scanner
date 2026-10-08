"""Audit #26 (2026-10-08): a zone is a BAND, never a single price.

Equal lows (highs) printed on one exact tick and tapped exactly on that tick
built DEMAND = [l, chi] with l == chi (live: 42 zero-width zones, e.g. DUN
demand 0.048-0.048, narrated "ran the 0.0480-0.0480 lows"), and the schema
gate only checked low <= high.
"""

import pytest

import phasemap.engine.setup_engine as setup_engine_mod
from phasemap.engine.scanner import scan_ticker
from phasemap.engine.setup_engine import SetupEngine
from phasemap.narrate.renderer import render
from phasemap.output.writer import build_snapshot, validate_snapshot
from phasemap.tests import synth


def _equal_tick_taps(bull=True):
    """Fixture 2 with both swing lows on the SAME tick (0.0480), tapped
    exactly on it and reclaimed -- the equal_lows variant's degenerate case."""
    vol = 500_000.0
    bars = synth.trend(240, 0.060, -0.00003, 0.0008, vol)
    bars += synth.flat(5, 0.0520, 0.0008, vol)
    bars.append((0.0510, 0.0512, 0.0480, 0.0490, vol))
    bars += synth.flat(6, 0.0505, 0.0008, vol)
    bars.append((0.0505, 0.0507, 0.0480, 0.0495, vol))
    bars += synth.flat(7, 0.0500, 0.0008, vol)
    bars.append((0.0500, 0.0502, 0.0480, 0.0495, vol))
    bars += synth.flat(2, 0.0495, 0.0008, vol)
    df = synth.bars_df(bars)
    return df if bull else synth.mirror_df(df, pivot=0.1)


def _rec(df, direction):
    for rec, eng in scan_ticker("DUN", df):
        if rec["direction"] == direction:
            return rec, eng
    return None, None


def test_an_exact_equal_lows_tap_publishes_a_demand_band():
    rec, eng = _rec(_equal_tick_taps(), "bullish")
    assert rec["state"] == "SWEPT" and eng.sweep_variant == "equal_lows"
    demand = next(z for z in rec["zones"] if z["id"] == "demand")
    inv = next(z for z in rec["zones"] if z["id"] == "inv_hard")
    assert demand["low"] == pytest.approx(0.0480)        # the swept tick
    assert demand["high"] == pytest.approx(0.0480 + 0.5 * eng.sweep_buffer)
    assert demand["low"] < demand["high"]
    assert inv["high"] == demand["low"]                  # invalidation unchanged
    assert "0.0480–0.0480" not in render(rec)


def test_the_bearish_mirror_publishes_a_supply_band():
    rec, eng = _rec(_equal_tick_taps(bull=False), "bearish")
    assert rec is not None and eng.sweep_variant == "equal_highs"
    supply = next(z for z in rec["zones"] if z["id"] == "supply")
    assert supply["low"] < supply["high"]
    assert supply["high"] == pytest.approx(0.1 - 0.0480)  # the swept tick


def test_a_padded_supply_never_reaches_zero(monkeypatch):
    # the bearish pad points DOWN from the swept tick, so it takes the #27
    # positive floor: a buffer over twice the price must not publish a
    # SUPPLY low at or below zero
    _rec0, eng = _rec(_equal_tick_taps(bull=False), "bearish")
    k, ind = eng.sweep_index, eng.ind
    extreme = float(ind.high[k])
    fresh = SetupEngine(ind=ind, bull=False)
    for i in range(k):
        fresh.on_bar(i)
    monkeypatch.setattr(fresh, "_buffer", lambda i: 4 * extreme)
    monkeypatch.setattr(setup_engine_mod, "cluster_levels",
                        lambda levels, tol: [(extreme, extreme, 3)])
    fresh.on_bar(k)
    assert fresh.sweep_index == k and fresh.sweep_variant == "equal_highs"
    assert 0 < fresh.demand.low < fresh.demand.high == extreme


def test_the_schema_gate_rejects_a_single_price_zone():
    rec, _eng = _rec(synth.fixture1(), "bullish")
    rec["narration"] = render(rec)
    snap = build_snapshot("2026-10-08", 1, [rec])
    validate_snapshot(snap)
    snap["results"][0]["zones"][0]["high"] = snap["results"][0]["zones"][0]["low"]
    with pytest.raises(ValueError):
        validate_snapshot(snap)


@pytest.mark.parametrize("price,market", [(2e-5, "crypto"), (0.003, "crypto"),
                                          (0.004, "asx"), (0.05, "asx"),
                                          (0.6, "nasdaq"), (1.0, "asx"),
                                          (48.0, "nasdaq"), (61000.0, "crypto")])
def test_every_published_zone_passes_the_strict_gate(price, market):
    # the tightened validator must never trip on what the engine builds --
    # a hit would abort the whole market's publish
    results = []
    for seed in range(16):
        df = synth.seeded_walk(seed, 520, price)
        for rec, _eng in scan_ticker(f"S{seed}", df, market=market,
                                     volume_is_usd=(market == "crypto")):
            rec["narration"] = render(rec)
            results.append(rec)
    assert results
    validate_snapshot(build_snapshot("2026-10-08", 16, results))

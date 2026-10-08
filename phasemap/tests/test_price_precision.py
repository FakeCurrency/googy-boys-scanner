"""Audit #28 (2026-10-08): sub-cent prices keep their significant figures.

Zone.to_dict and _metrics rounded to a flat CONFIG.price_decimals = 4, so a
coin priced below 1e-4 (BONK ~2e-5) published every band and its close as
0.0 and narrated "touched the 50% area at 0.0000-0.0000". At/above $0.10 the
published bytes must not move.
"""

import re

from phasemap.engine.scanner import scan_ticker
from phasemap.engine.zones import band_round, price_round
from phasemap.narrate.renderer import fmt_price, render, render_next
from phasemap.tests import synth


def _scaled(k):
    df = synth.fixture1()
    for c in ("Open", "High", "Low", "Close"):
        df[c] = df[c] * k
    df["Volume"] = 1e12
    return df


def test_a_bonk_class_coin_publishes_real_prices():
    recs = scan_ticker("BONK", _scaled(2e-5), market="crypto", volume_is_usd=True)
    assert recs
    for rec, _eng in recs:
        assert rec["metrics"]["close"] > 0
        for z in rec["zones"]:
            assert 0 < z["low"] < z["high"], z
        text = render(rec) + " " + render_next(rec)
        assert "0.0000–0.0000" not in text
        assert not re.search(r"(?<![\d.])0\.0000(?!\d)", text), text


def test_ordinary_prices_publish_exactly_as_before():
    # fixture 1 trades ~0.7-1.1: the 4 dp rounding is unchanged there
    for rec, eng in scan_ticker("TST", synth.fixture1()):
        raw = {z.id: z for z in [eng.demand, eng.inv_hard, eng.inv_soft, eng.entry,
                                 *eng.targets] if z is not None}
        for z in rec["zones"]:
            assert z["low"] == round(raw[z["id"]].low, 4)
            assert z["high"] == round(raw[z["id"]].high, 4)
    for x in (0.1, 0.1234567, 0.965, 1.5, 21.4873, 62345.123456):
        assert price_round(x) == round(x, 4)


def test_small_prices_keep_four_significant_figures():
    assert price_round(2.0123456e-5) == 2.012e-5
    assert price_round(0.0483726) == 0.04837
    assert price_round(0.0) == 0.0


def test_a_band_with_width_is_never_published_as_one_price():
    lo, hi = band_round(0.500041, 0.500049)     # 4 dp would give 0.5 / 0.5
    assert lo < hi
    lo, hi = band_round(2.00001e-5, 2.00003e-5)
    assert lo < hi
    assert band_round(0.048, 0.048) == (0.048, 0.048)   # a real zero stays zero


def test_fmt_price_speaks_sub_cent_prices():
    assert fmt_price(2e-5) == "0.0000200"
    assert fmt_price(0.00045) == "0.000450"
    assert fmt_price(0.0035) == "0.00350"
    # unchanged magnitudes
    assert fmt_price(0.0485) == "0.0485"
    assert fmt_price(0.965) == "0.965"
    assert fmt_price(21.5) == "21.50"


def test_a_sub_cent_trap_set_publishes_its_box_and_cluster():
    # the TRAP_SET pre-alert's box/cluster levels went through the same flat
    # 4 dp rounding: a ~2e-5 coin's range read 0.0-0.0001
    df = synth.fixture_trap_only()
    for c in ("Open", "High", "Low", "Close"):
        df[c] = df[c] * 2e-5
    df["Volume"] = 1e12
    traps = [(r, e) for r, e in scan_ticker("BONK", df, market="crypto", volume_is_usd=True)
             if r["state"] == "TRAP_SET"]
    assert traps
    for rec, eng in traps:
        m = rec["metrics"]
        assert m["box_low"] == price_round(eng.box_low) > 0
        assert m["box_high"] == price_round(eng.box_high) > m["box_low"]
        assert m["cluster_low"] == price_round(eng.trap_cluster[0]) > 0
        assert m["cluster_high"] == price_round(eng.trap_cluster[1]) > 0
        assert "0.0000–" not in render(rec) + " " + render_next(rec)


def test_a_band_narrower_than_the_decimal_cap_keeps_its_raw_edges():
    # 12 dp cannot separate these two edges; a collapsed band would fail the
    # strict low < high gate and abort the market's whole publish
    lo, hi = band_round(1.0000000000001e-9, 1.0000000000002e-9)
    assert lo < hi

"""REFINE200 #132: publish rounding keeps sub-cent prices.

Fixed 4 dp published BONK's close as 0.0 and every one of its zones as
[0.0, 0.0]; NES/BLU/RSR bands printed as single points. Prices now keep 4 dp
OR 6 significant figures, whichever is more — display only, the engine's
floats are untouched, and a normally priced name publishes the same bytes.
"""

import math

from phasemap.engine.scanner import scan_ticker
from phasemap.engine.zones import Zone, round_price, round_sig
from phasemap.narrate.renderer import fmt_price, render
from phasemap.tests import synth


def _scaled(df, k):
    out = df.copy()
    for c in ("Open", "High", "Low", "Close"):
        out[c] = out[c] * k
    return out


def test_sub_cent_prices_keep_significant_figures():
    assert round_price(3.12345678e-06) == 3.12346e-06
    assert round_price(0.0016234567) == 0.00162346
    assert round_price(0.0) == 0.0


def test_normal_prices_publish_exactly_as_four_decimals_did():
    for x in (12.3456789, 123.456789, 4567.891234, 25.2, 2.39):
        if x >= 10:
            assert round_price(x) == round(x, 4)
        assert round_price(x) >= round(x, 4) - 1e-4   # never fewer digits


def test_a_sub_cent_zone_is_still_a_band():
    z = Zone(id="supply", type="SUPPLY", low=0.0035, high=0.0039, side="above")
    d = z.to_dict()
    assert d["low"] < d["high"]
    bonk = Zone(id="t1", type="TARGET", low=2.91e-06, high=3.07e-06, side="above").to_dict()
    assert 0 < bonk["low"] < bonk["high"]


def test_a_micro_priced_ticker_publishes_a_real_close_and_real_bands():
    df = _scaled(synth.fixture1(), 1e-6)            # a BONK-class coin
    recs = scan_ticker("BONK", df, market="crypto", volume_is_usd=True)
    assert recs
    for rec, eng in recs:
        assert rec["metrics"]["close"] > 0
        engine_bands = {z.id: z for z in [eng.demand, eng.inv_hard, eng.inv_soft,
                                          eng.entry, *eng.targets] if z is not None}
        for z in rec["zones"]:
            src = engine_bands[z["id"]]
            if src.high > src.low * (1 + 1e-5):     # a real band in the engine
                assert z["low"] < z["high"], z
        text = render(rec)
        assert "0.0000–0.0000" not in text and "0.0000-0.0000" not in text


def test_narration_prices_keep_three_significant_figures_below_a_cent():
    assert fmt_price(3e-06) == "0.00000300"
    assert fmt_price(0.00158) == "0.00158"
    assert fmt_price(0.05) == "0.0500"        # unchanged above a cent
    assert fmt_price(1.5) == "1.500"
    assert fmt_price(25.0) == "25.00"


def test_round_sig_passes_non_finite_and_zero_through():
    assert round_sig(0.0, 8) == 0.0
    assert math.isnan(round_sig(float("nan"), 8))
    assert round_sig(344.1700134277344, 8) == 344.17001

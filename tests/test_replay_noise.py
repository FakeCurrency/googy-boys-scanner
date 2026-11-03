"""The replay's own statistics (scanner/replay_noise.py; NEXT100 #16, #17).

#16 a random-timing baseline: same names, same exit model, random signal
    days within +/- a window of the real one, never the real bar, only bars
    with a next open; the plan re-anchored as the same fraction of the fill
#17 entry-month block-bootstrap bands, a paired P(no gain) per variant and a
    dropout-placebo pass rate scored with the real pass gate

Synthetic trade lists and series only; nothing reaches the network.
"""

from __future__ import annotations

import numpy as np
import pytest

from scanner import config
from scanner import replay_noise as rs
from scanner import vivek_parity as vp

from tests.test_decision_replay import W1R, _series

pytestmark = pytest.mark.risk


def _trades(n: int = 60, seed: int = 7) -> list[dict]:
    """n closed trades over 12 entry months, two markets, R in [-1, +1]."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        m = (i % 12) + 1
        out.append({"market": "nasdaq" if i % 2 else "asx", "symbol": f"S{i}",
                    "entry_date": f"2023-{m:02d}-{(i % 20) + 1:02d}",
                    "exit_date": f"2024-{m:02d}-01",
                    "realized_r": round(float(rng.uniform(-1.0, 1.0)), 4)})
    return out


# ------------------------------------------------------------ #16 random timing

def _only_up_day_series() -> vp.SymbolSeries:
    """Flat at 100; every bar before the real fill (bar 11) dips to 90, so a
    fill there is stopped; bar 12 gaps up to 121 so only a fill at bar 11
    rides the spike (a fill AT 121 is stopped by the same bar's low)."""
    s = _series("X", signals=[(10, W1R, "A+", "weekly")], n=120)
    s.l[:11] = 90.0
    s.o[12], s.h[12] = 121.0, 121.0
    return s


def test_the_real_entry_beats_random_timing_on_the_only_up_day_series():
    s = _only_up_day_series()
    book = vp.run_book([s])
    assert len(book["taken"]) == 1 and book["taken"][0]["realized_r"] > 1.0
    res = rs.random_timing([s], book["taken"], draws=20, window=182, seed=5)
    o = res["overall"]
    assert o["n"] == 1 and o["random"]["draws"] == 20 and res["draws_total"] == 20
    assert o["real"]["mean_r"] == book["taken"][0]["realized_r"]
    assert o["random"]["mean_r"] < 0 < o["delta_r"]
    assert o["p_value"] == 0.0
    assert res["by_market"]["nasdaq"]["n"] == 1
    assert res["skipped"] == {"no_series": 0, "no_bar": 0, "no_draw": 0}
    assert res == rs.random_timing([s], book["taken"], draws=20, window=182, seed=5)  # seeded


def test_the_draws_stay_in_the_window_skip_the_real_bar_and_need_a_next_open():
    s = _series("X", n=120)
    s.o[8] = float("nan")                                   # signal bar 7 has no fill open
    rng = np.random.default_rng(1)
    d = rs.draw_signal_bars(rng, s, 10, 200, 5)
    assert len(d) == 200
    assert set(d.tolist()) <= {5, 6, 8, 9, 11, 12, 13, 14, 15}
    assert 10 not in d and 7 not in d
    # the window clips at both ends of the series: the last bar never signals
    assert set(rs.draw_signal_bars(rng, s, 0, 50, 3).tolist()) <= {1, 2, 3}
    assert set(rs.draw_signal_bars(rng, s, 119, 50, 3).tolist()) <= {116, 117, 118}
    assert len(rs.draw_signal_bars(rng, _series("Y", n=2), 0, 5, 3)) == 0


def test_a_draw_re_anchors_the_plan_as_the_same_fraction_of_its_fill():
    tr = {"entry": 100.0, "initial_stop": 95.0, "stop": 101.0, "tp1": 110.0, "tp2": 120.0,
          "tp3": 130.0, "scale": [0.4, 0.3, 0.3], "entry_type": "reclaim"}
    p = rs._reanchored_plan(tr, 50.0)
    assert (p["stop"], p["tp1"], p["tp2"], p["tp3"]) == (47.5, 55.0, 60.0, 65.0)
    assert p["scale"] == tr["scale"] and p["entry_trigger"] == "reclaim"
    assert rs._reanchored_plan({**tr, "initial_stop": None}, 50.0)["stop"] == 50.5


def test_random_timing_counts_a_trade_without_a_series():
    s = _only_up_day_series()
    taken = vp.run_book([s])["taken"]
    res = rs.random_timing([], taken, draws=3)
    assert res["trades"] == 0 and res["skipped"]["no_series"] == 1
    assert res["overall"]["n"] == 0 and res["overall"]["p_value"] is None
    assert res["draws_per_trade"] == 3
    assert res["window_bars"] == config.VIVEK_PARITY_RANDOM_WINDOW_BARS


# ------------------------------------------------------- #17 bootstrap bands

def test_bootstrap_bands_resample_entry_months_whole():
    base = _trades()
    b = rs.bootstrap_bands(base, n=300, seed=3)
    band = b["r_per_slot_month"]
    assert b["n"] == 300 and b["months"] == 12 and b["trades"] == 60
    assert band["p5"] <= band["mean"] <= band["p95"]
    assert band["p5"] <= b["point_r_per_slot_month"] <= band["p95"]
    assert b == rs.bootstrap_bands(base, n=300, seed=3)
    # one month only: every resample IS the list, so the band collapses on the point
    one = [dict(t, entry_date=f"2023-01-{(i % 28) + 1:02d}") for i, t in enumerate(base)]
    b1 = rs.bootstrap_bands(one, n=50, seed=3)
    assert b1["months"] == 1
    assert b1["r_per_slot_month"]["p5"] == b1["r_per_slot_month"]["p95"] == b1["point_r_per_slot_month"]
    assert rs.bootstrap_bands([], n=50)["n"] == 0


def test_an_identical_variant_never_gains_and_a_plus_one_r_variant_always_does():
    base = _trades()
    same = rs.paired_bands(base, list(base), n=200, seed=3)
    assert same["p_no_gain"] == 1.0
    assert same["delta_r_per_slot_month"] == {"mean": 0.0, "p5": 0.0, "p95": 0.0}
    plus = rs.paired_bands(base, [dict(t, realized_r=t["realized_r"] + 1.0) for t in base],
                           n=200, seed=3)
    assert plus["p_no_gain"] == 0.0
    assert plus["delta_r_per_slot_month"]["p5"] > 0


def test_a_statistically_identical_variant_reads_a_coin_flip():
    """Same months, same distribution, independent draws: over many such
    twins the variant beats the baseline about half the time (one twin's P
    sits wherever its own sample mean landed; the average over twins is the
    coin flip)."""
    base = _trades(seed=7)
    rng = np.random.default_rng(11)
    ps = []
    for _ in range(40):
        twin = [dict(t, realized_r=round(float(rng.uniform(-1.0, 1.0)), 4)) for t in base]
        ps.append(rs.paired_bands(base, twin, n=60, seed=3)["p_no_gain"])
    assert 0.35 < float(np.mean(ps)) < 0.65
    assert min(ps) < 0.5 < max(ps)


def test_the_placebo_drops_the_variants_share_and_scores_with_the_real_gate():
    base = _trades()
    pl = rs.placebo_pass_rate(base, base[:40], n=40, seed=3)
    assert pl["n"] == 40 and pl["dropped"] == 20
    assert pl["drop_share"] == pytest.approx(1 / 3, abs=1e-4)
    assert pl["rate"] == pl["passes"] / 40
    assert pl == rs.placebo_pass_rate(base, base[:40], n=40, seed=3)
    # a variant that drops nothing: every placebo IS the baseline, which a strict gate fails
    none = rs.placebo_pass_rate(base, list(base), n=10, seed=3)
    assert none["dropped"] == 0 and none["rate"] == 0.0
    assert rs.placebo_pass_rate([], [], n=10)["rate"] is None


def test_a_placebo_is_a_real_gate_verdict(monkeypatch):
    seen = []

    def fake(b, v, skip_markets=()):
        seen.append((len(b), len(v), skip_markets))
        return {"pass": True}

    monkeypatch.setattr(vp, "variant_passes", fake)
    base = _trades()
    pl = rs.placebo_pass_rate(base, base[:30], n=5, seed=1, skip_markets=("asx",))
    assert pl["rate"] == 1.0 and len(seen) == 5
    assert all(s == (60, 30, ("asx",)) for s in seen)


def test_variant_stats_carry_the_band_and_the_placebo_and_print_as_three_cells():
    base = _trades()
    plus = [dict(t, realized_r=t["realized_r"] + 1.0) for t in base]
    st = rs.variant_stats(base, plus, name="V_plus", n_boot=100, n_placebo=20)
    assert st["band"]["p_no_gain"] == 0.0 and st["placebo"]["n"] == 20
    cells = rs.stats_cells(st)
    assert cells.count("|") == 2 and "0.00" in cells and "% of 20" in cells
    assert rs.stats_cells(None) == "n/a | n/a | n/a"
    assert cells.isascii()
    # the name salts the seed: two variants with the same lists get their own streams
    a = rs.variant_stats(base, base[:40], name="A", n_boot=50, n_placebo=20)
    b = rs.variant_stats(base, base[:40], name="B", n_boot=50, n_placebo=20)
    assert a != b


# ------------------------------------------------------------------ the hooks

def test_the_variant_table_and_the_report_carry_the_stats(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_PARITY_BOOTSTRAP_N", 30)
    monkeypatch.setattr(config, "VIVEK_PARITY_PLACEBO_N", 10)
    monkeypatch.setattr(config, "VIVEK_PARITY_RANDOM_DRAWS", 4)
    ss = [_series(f"S{i}", market=mk, signals=[(j, W1R, "A+", "weekly")])
          for i, (mk, j) in enumerate([("asx", 0), ("asx", 20), ("nasdaq", 5), ("nasdaq", 40),
                                       ("crypto", 3)])]
    ss.append(_only_up_day_series())
    book = vp.run_book(ss, shadow=True)
    variants = vp.run_variant_books(ss, book["taken"])
    for name, vr in variants.items():
        assert set(vr["stats"]) == {"band", "placebo"}, name
        assert vr["stats"]["placebo"]["n"] == 10 and vr["stats"]["band"]["n"] == 30
    rep = vp.build_parity_report(book["taken"], {}, {"markets": ["asx", "nasdaq", "crypto"]},
                                 variants, book=book)
    rs.attach(rep, ss, book["taken"], vp.baseline_rules())
    rt = rep["versus"]["random_timing"]
    assert rt["draws_per_trade"] == 4 and rt["trades"] == len(book["taken"])
    assert set(rt["by_market"]) == {"asx", "nasdaq", "crypto"}
    assert rep["baseline"]["stats"]["bootstrap"]["n"] == 30
    md = vp.summary_markdown(rep)
    assert "| 90% band dR/sm | P(no gain) | placebo pass |" in md
    assert "### Versus random timing" in md
    assert "| overall | " in md and "| nasdaq | " in md
    assert "entry-month block resamples" in md
    assert md.isascii() or all(ord(ch) < 128 or ch in "Δ—·≈" for ch in md)


def test_the_knobs_live_in_config_and_are_read_by_default():
    for name, want in (("VIVEK_PARITY_RANDOM_WINDOW_BARS", 182), ("VIVEK_PARITY_RANDOM_DRAWS", 20),
                       ("VIVEK_PARITY_BOOTSTRAP_N", 1000), ("VIVEK_PARITY_PLACEBO_N", 200)):
        assert getattr(config, name) == want
    assert isinstance(config.VIVEK_PARITY_RANDOM_SEED, int)
    assert rs._seed() == config.VIVEK_PARITY_RANDOM_SEED and rs._seed(4) == 4

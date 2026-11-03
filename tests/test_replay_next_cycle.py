"""The decision replay after hc4-2 (2 Nov, the owner's "20 more").

* it mirrors hc4-2: a break's R:R re-checked at the fill (#152) and one
  position per company (#12)
* a day's candidates are taken in the live scan's order (grade, score, R:R)
* the next-cycle candidates are variants: no 1W break, 1D break on crypto
  only, an adverse cut at -0.5R (house + worst print)
* ``ranking`` compares what the book took with what it refused for a full
  book, on the days the two competed
* the log carries every table (a cloud session reads logs, not artifacts)
"""

from __future__ import annotations

import pytest

from scanner import config
from scanner import vivek_parity as vp

from tests.test_decision_replay import W1R, _series

pytestmark = pytest.mark.risk


def _variant(name: str) -> vp.ParityRules:
    return next(r for r in vp.variant_grid() if r.name == name)


# ------------------------------------------------- the next-cycle variants

def test_the_grid_carries_the_next_cycle_candidates():
    names = [r.name for r in vp.variant_grid()]
    for want in ("V9_no_1w_break", "V10_1d_break_crypto_only", "V11_cut_mae0.5"):
        assert want in names
    v9 = _variant("V9_no_1w_break").cells_for("nasdaq")
    assert v9.get("1W") == ("reclaim",) and "1D" in v9 and "3D" in v9
    v10 = _variant("V10_1d_break_crypto_only")
    assert "1D" not in v10.cells_for("asx") and "1D" not in v10.cells_for("nasdaq")
    assert "break" in v10.cells_for("crypto")["1D"]
    assert _variant("V11_cut_mae0.5").mae_cut_r == 0.5
    assert config.VIVEK_PARITY_MAE_CUTS == (0.5,)


def test_the_adverse_cut_books_worst_print_and_house_like_a_stop():
    """Entry 100, stop 95 (1R = 5): a bar whose low reaches 97.5 is -0.5R. The
    headline fills at that bar's low (97 = -0.6R), the house twin at the cut
    level; the baseline, whose stop is 95, rides on."""
    s = _series("X", signals=[(0, W1R, "A+", "weekly")], lows={10: 97.0})
    cut = vp.run_book([s], _variant("V11_cut_mae0.5"))["taken"][0]
    assert cut["exit_reason"] == "mae_cut" and cut["exit_date"] == s.iso(10)
    cost = cut.get("cost_r") or 0.0
    assert cut["realized_r"] == pytest.approx(-0.6 - cost, abs=0.02)
    assert cut["realized_r_house"] == pytest.approx(-0.5 - cost, abs=0.02)
    base = vp.run_book([s], vp.baseline_rules())["taken"][0]
    assert base["exit_reason"] != "mae_cut"


def test_a_bar_that_gaps_through_the_cut_fills_house_at_the_open():
    s = _series("X", signals=[(0, W1R, "A+", "weekly")], lows={10: 95.5})
    s.o[10] = 96.0                                   # opened below the 97.5 cut level
    cut = vp.run_book([s], _variant("V11_cut_mae0.5"))["taken"][0]
    assert cut["exit_reason"] == "mae_cut"
    assert cut["realized_r_house"] == pytest.approx(-0.8 - (cut.get("cost_r") or 0.0), abs=0.02)


def test_the_cut_is_an_exit_rule_and_says_what_it_does():
    v = _variant("V11_cut_mae0.5")
    assert vp._delta_desc(v) == "cut pre-TP1 at -0.5R adverse"
    assert vp._delta_desc(_variant("V9_no_1w_break")).startswith("cells 1W reclaim")
    assert "asx cells" in vp._delta_desc(_variant("V10_1d_break_crypto_only"))


# ------------------------------------------------- hc4-2 mirrored

def test_a_break_whose_rr_is_gone_at_the_fill_is_refused_and_a_reclaim_is_not():
    """Plan: entry 100, stop 95, TP1 110, TP2 120. Filled at 108 (under TP1,
    so don't-chase lets it through) the R:R is 12/13 = 0.92 < 1.5."""
    brk = _series("B", signals=[(0, {"1W": "break"}, "A+", "weekly")])
    rec = _series("R", signals=[(0, {"1W": "reclaim"}, "A+", "weekly")])
    for s in (brk, rec):
        s.o[1], s.h[1] = 108.0, 109.0
    book = vp.run_book([brk, rec], vp.baseline_rules())
    assert [t["symbol"] for t in book["taken"]] == ["R"]
    assert book["gated"].get("fill_rr") == 1


def test_one_position_per_company_like_the_live_bot(monkeypatch):
    a = _series("FWONA", signals=[(0, W1R, "A+", "weekly")])
    k = _series("FWONK", signals=[(0, W1R, "A+", "weekly")])
    a.name, k.name = "Liberty Media - Series A", "Liberty Media - Series C"
    book = vp.run_book([a, k], vp.baseline_rules())
    assert len(book["taken"]) == 1 and book["skipped"].get("dup_company") == 1
    monkeypatch.setattr(config, "VIVEK_BOT_ONE_PER_COMPANY", False)
    assert len(vp.run_book([a, k], vp.baseline_rules())["taken"]) == 2


# ------------------------------------------------- the live scan's order

def test_a_days_candidates_go_in_the_live_scans_order():
    """One slot, three candidates the same day: A+ beats A whatever the
    symbol; within a grade the higher score; then the higher R:R."""
    def one(sym, grade, score, rr):
        s = _series(sym, signals=[(0, W1R, grade, "weekly")])
        s.signals[0][1].update({"score": score, "rr": rr})
        return s

    pick = lambda *ss: vp.run_book(list(ss), vp.baseline_rules(), max_total=1)["taken"][0]["symbol"]  # noqa: E731
    assert pick(one("AAA", "A", 9, 5.0), one("ZZZ", "A+", 6, 2.0)) == "ZZZ"
    assert pick(one("AAA", "A+", 6, 5.0), one("ZZZ", "A+", 8, 2.0)) == "ZZZ"
    assert pick(one("AAA", "A+", 8, 2.0), one("ZZZ", "A+", 8, 3.0)) == "ZZZ"
    assert pick(one("AAA", "A+", 8, 3.0), one("ZZZ", "A+", 8, 3.0)) == "AAA"


def test_a_record_without_the_rank_key_keeps_the_old_weekly_first_order():
    assert vp._rank_key({"grade": "A"}, "1W") < vp._rank_key({"grade": "A"}, "3D")
    assert vp._rank_key({"grade": "A", "score": float("nan")}, "1W") == (1, 0.0, 0.0, 0)


# ------------------------------------------------- does the order pick better?

def test_a_signal_refused_for_a_full_book_is_shadowed_once_and_compared():
    win = _series("WIN", signals=[(0, W1R, "A", "weekly"), (1, W1R, "A", "weekly")])
    win.h[5] = 131.0                                  # the refused one runs through TP3
    top = _series("TOP", signals=[(0, W1R, "A+", "weekly")])
    book = vp.run_book([win, top], vp.baseline_rules(), max_total=1, shadow=True)
    assert [t["symbol"] for t in book["taken"]] == ["TOP"]
    assert [t["symbol"] for t in book["shadow_book_full"]] == ["WIN"]     # once, not twice
    assert book["skipped"]["book_full"] == 2
    rk = vp.ranking_block(book["taken"], book["shadow_book_full"])
    assert rk["contested_days"] == 1
    assert rk["contested_taken"]["n"] == rk["contested_skipped"]["n"] == 1
    assert rk["contested_skipped"]["expectancy_r"] > rk["contested_taken"]["expectancy_r"]
    assert "shadow_book_full" not in vp.run_book([win, top], vp.baseline_rules(), max_total=1)


# ------------------------------------------------- the log keeps every table

def test_the_log_and_the_summary_carry_the_new_tables(monkeypatch, capsys):
    def fake_load(mk, limit, period, exclude_symbols=None, workers=1):
        ss = [_series(f"{mk[:1].upper()}{i}", market=mk,
                      signals=[(i, {"3D": "reclaim", "1D": "break"}, "A+" if i % 2 else "A", "3d"),
                               (40 + i, W1R, "A+", "weekly")],
                      lows={i + 4: 90.0} if i % 3 == 0 else None)
              for i in range(6)]
        return ss, {"symbols": 6, "universe": 60, "sampled_pct": 10.0, "replayed": 6,
                    "signals": 12, "data_sources": {"by_source": {"x": 6}},
                    "sampled_symbols": [s.symbol for s in ss]}

    monkeypatch.setattr(vp, "load_market_series", fake_load)
    monkeypatch.setattr(vp, "fx_rates", lambda: {"audusd": 0.66, "source": "fallback"})
    rep = vp.run_parity(["asx", "nasdaq", "crypto"], 6, "5y", workers=1)
    port = rep["baseline"]["portfolio"]
    assert port["r_per_slot_month_house"] is not None
    assert {"fill_rr_recheck", "one_per_company", "live_rank_order"} <= set(port["params"]["simulated"])
    assert rep["baseline"]["ranking"]["taken"]["n"] == port["taken"]
    assert "by_stocks_cell" in rep["baseline"]["portfolio_slices"]
    vp.print_parity(rep)
    out = capsys.readouterr().out
    for want in ("house R/slot-month=", "### By cell (book)", "| stocks (asx+nasdaq) |",
                 "### Does the bot's order pick the better trades?", "V11_cut_mae0.5",
                 f"(parity, {config.VIVEK_BOT_CYCLE_TAG})"):
        assert want in out, want

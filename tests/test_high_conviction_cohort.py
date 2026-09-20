"""HIGH CONVICTION must mean the same thing in the backtest as on the deck.

Owner, 2026-09-20: "run a back test ... and see whether the high conviction
status still has the edge? I remember running a back test and this formed the
reasoning behind the high conviction status."

The badge's own tooltip says it is "the best-performing setup in the backtest",
and until now the report it cites had no cohort for it -- the claim could not be
recomputed from its own evidence. These tests exist so the answer, whatever it
turns out to be, is about the rule the deck actually applies.
"""
import pathlib

from scanner.vivek_backtest import aggregate, is_high_conviction

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_it_is_the_shared_rule_not_a_copy():
    """Parity with app.js is pinned in tests/test_conviction.py by parsing the
    HC_CELLS literal out of the shipped file; here we only need the backtest to
    be READING that rule rather than carrying one of its own."""
    from scanner import conviction
    assert is_high_conviction({"timeframe": "1W", "entry_type": "reclaim", "grade": "A+"})
    for tr in ({"timeframe": "1W", "entry_type": "break", "grade": "A"},
               {"timeframe": "3D", "entry_type": "reclaim", "grade": "A+"},
               {"timeframe": "1D", "entry_type": "break", "grade": "A+"}):
        assert is_high_conviction(tr) == conviction.trade_is_high_conviction(tr) is True


def test_the_four_cells_the_grade_gate_and_the_dropped_structure_branch():
    hc = lambda tf, et, **k: is_high_conviction(dict({"timeframe": tf, "entry_type": et,
                                                       "grade": "A+"}, **k))
    assert hc("1W", "reclaim") and hc("1W", "break") and hc("3D", "reclaim") and hc("1D", "break")
    assert hc("1W", "reclaim", grade="A")
    assert not hc("1W", "reclaim", grade="B+", structural_tps=5), \
        "the structure branch stood alone under the OLD rule; it measured -0.07R and was dropped"
    assert not hc("1W", "retest") and not hc("3D", "break") and not hc("3D", "retest")
    assert not hc("1D", "reclaim") and not hc("1D", "retest") and not hc("4H", "reclaim")


def test_missing_or_junk_fields_never_raise_and_never_qualify():
    for bad in ({}, {"timeframe": None}, {"timeframe": "1W", "entry_type": None},
                {"timeframe": "1W", "entry_type": "reclaim", "grade": None,
                 "structural_tps": None},
                {"timeframe": "1W", "entry_type": "reclaim", "structural_tps": "two"}):
        assert is_high_conviction(bad) is False, bad


def test_the_report_carries_the_cohort_and_splits_it_from_the_rest():
    trades = [
        {"timeframe": "1W", "entry_type": "reclaim", "grade": "A+", "direction": "long",
         "realized_r": 1.5, "risk": 1, "entry": 10, "stop": 9},
        {"timeframe": "1D", "entry_type": "break", "grade": "A", "direction": "long",
         "realized_r": -1.0, "risk": 1, "entry": 10, "stop": 9},
    ]
    rep = aggregate(trades)
    assert "by_conviction" in rep and "by_conviction_long" in rep
    assert rep["by_conviction"]["high"]["n"] == 2, "a 1D break at grade A is a cell now"
    assert rep["by_conviction"]["rest"]["n"] == 0
    assert rep["by_conviction_long"]["high"]["n"] == 2
    # the rule travels with the report, and the cells are split out one by one
    from scanner import conviction
    assert rep["conviction_rule"] == conviction.RULE_TEXT
    cells = rep["by_conviction_cell_long"]
    assert list(cells) == ["1W reclaim", "1W break", "3D reclaim", "1D break"]
    assert cells["1W reclaim"]["n"] == 1 and cells["1D break"]["n"] == 1
    assert cells["1W break"]["n"] == 0 and cells["3D reclaim"]["n"] == 0


def test_structural_tps_reaches_the_trade_record():
    """It lives on the PLAN and is still published on every trade (the rule
    stopped reading it on 2026-09-20, but the edge explorer and any future
    re-argument of the structure branch need it in the record)."""
    src = (ROOT / "scanner" / "vivek_backtest.py").read_text(encoding="utf-8")
    assert 'tr["structural_tps"] = plan.get("structural_tps")' in src
    i = src.index("_SLIM_KEYS = (")
    assert '"structural_tps"' in src[i:src.index(")", i)], \
        "dropped from the slim projection — the published trades would lose it"


def test_the_existing_cohorts_are_untouched():
    """Additive only: the report's existing keys must not move, or every
    consumer of the published backtest changes meaning at once."""
    rep = aggregate([{"timeframe": "1W", "entry_type": "reclaim", "grade": "A+",
                      "direction": "long", "realized_r": 1.0, "risk": 1,
                      "entry": 10, "stop": 9}])
    for k in ("by_entry_type", "by_timeframe", "by_grade", "by_direction",
              "by_level_tf", "by_market", "by_entry_type_long", "by_timeframe_long"):
        assert k in rep, f"{k} disappeared from the report"

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
import re

from scanner.vivek_backtest import aggregate, is_high_conviction

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "js" / "app.js").read_text(encoding="utf-8")


def _app_rule() -> str:
    i = APP.index("function isHighConviction")
    return APP[i:APP.index("\n  }", i) + 4]


def test_it_matches_the_shipped_app_js_rule():
    """Sliced from app.js so a change there fails here instead of silently
    measuring a cohort the deck no longer promotes."""
    rule = _app_rule()
    assert 'plans["1W"]' in rule, "app.js no longer keys off the weekly plan"
    assert 'entry_trigger !== "reclaim"' in rule, "app.js no longer requires a reclaim"
    assert 'p.armed' in rule, "app.js no longer requires the plan to be armed"
    assert re.search(r'grade === "A\+" \|\| r\.grade === "A"', rule), "grade branch moved"
    assert re.search(r'structural_tps \|\| 0\) >= 2', rule), "structure branch moved"


def test_the_two_branches_and_the_three_gates():
    hc = lambda **k: is_high_conviction(dict({"timeframe": "1W", "entry_type": "reclaim"}, **k))
    assert hc(grade="A+") and hc(grade="A")
    assert hc(grade="B+", structural_tps=2), "the structure branch must stand alone"
    assert hc(grade="B+", structural_tps=5)
    assert not hc(grade="B+", structural_tps=1)
    assert not hc(grade="B+")
    assert not hc(grade="WATCH", structural_tps=0)
    # the three gates
    assert not is_high_conviction({"timeframe": "1D", "entry_type": "reclaim", "grade": "A+"})
    assert not is_high_conviction({"timeframe": "3D", "entry_type": "reclaim", "grade": "A+"})
    assert not is_high_conviction({"timeframe": "1W", "entry_type": "break", "grade": "A+"})
    assert not is_high_conviction({"timeframe": "1W", "entry_type": "retest", "grade": "A+"})


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
    assert rep["by_conviction"]["high"]["n"] == 1
    assert rep["by_conviction"]["rest"]["n"] == 1
    assert rep["by_conviction_long"]["high"]["n"] == 1


def test_structural_tps_reaches_the_trade_record():
    """It lives on the PLAN; if it stops being copied onto the trade the
    structure branch silently becomes unreachable and the cohort shrinks
    without anything failing."""
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

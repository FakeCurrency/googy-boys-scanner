"""hc4-2's rules (owner approved items 2, 3, 4, 6 and 7 on 2026-11-02).

docs/DECISIONS_2026-10-14.md, "hc4-2 proposal" and "Approved, Mon 2 Nov".
Every rule below changes which trades the bot takes or how a row is graded, so
each is pinned on the shipped code, with the case it exists for:

  2   #152  a break's R:R is re-measured from the FILL (`fill_rr`);
  3a  #7    a row is graded and headlined on the plan the bot walks to;
  3b  #12   one position per company (`dup_company`);
  3c  #13 / #143  the sector cap counts the 11 GICS sectors in both markets;
  3d  #148  the W+H4 point needs both averages near the PRICE;
  4         the day-14 stamp, report only.

Items 6 (the plain "Bot cell" tag) and 7 (the hc4-2 register) are pinned in
tests/test_conviction.py and tests/test_decision_pack.py /
tests/test_checkpoint_mirror.py.
"""
from __future__ import annotations

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import config, scan, vivek_backtest
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk


# ── 2 · #152: a break's R:R is measured again at the fill ────────────────────

def _plan(**kw):
    """A decide()-shaped plan, the input _ticket_to_position sees: entry 100,
    stop 96 (1R = 4), TP1 106, TP2 112 -> R:R 3.0 at the plan entry."""
    p = {"symbol": "BHP", "name": "BHP", "sector": "", "direction": "long",
         "grade": "A+", "entry_type": "break", "entry_type_label": "Break",
         "timeframe": "1D", "entry": 100.0, "stop": 96.0,
         "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.50, 0.15],
         "trigger_bar": None, "units": 10.0, "notional": 1000.0, "rr": 3.0,
         "leverage": 1.0, "leverage_target": 5, "risk_pct": 0.25, "risk_usd": 40.0}
    p.update(kw)
    return p


def test_a_break_filling_where_its_rr_is_gone_is_refused():
    # fill 104: 8 to the stop, 8 to TP2 -> 1.0 < 1.5 (under TP1, so the old
    # don't-chase guard let it through: the WBC shape)
    assert vr._ticket_to_position({"plan": _plan()}, 104.0, "asx", "2026-11-03") is None


def test_a_break_whose_fill_still_clears_the_floor_is_taken():
    # fill 101: 5 to the stop, 11 to TP2 -> 2.2
    pos = vr._ticket_to_position({"plan": _plan()}, 101.0, "asx", "2026-11-03")
    assert pos is not None and pos["rr"] == 2.2 and pos["entry"] == 101.0


def test_the_floor_is_the_plan_gates_floor_and_it_binds_at_the_same_rounding():
    # fill 102.24: 6.24 to the stop, 9.76 to TP2 -> 1.564 -> 1.56 (taken);
    # fill 102.4: 6.4 / 9.6 -> 1.5 exactly (taken: the gate is `<`, as decide's)
    assert vr._ticket_to_position({"plan": _plan()}, 102.24, "asx", "2026-11-03") is not None
    assert vr._ticket_to_position({"plan": _plan()}, 102.4, "asx", "2026-11-03") is not None
    assert vr._ticket_to_position({"plan": _plan()}, 102.5, "asx", "2026-11-03") is None


def test_a_reclaim_is_not_re_checked(monkeypatch):
    """Only the triggers config names (break): a reclaim's entry IS its
    trigger close, and the approval was for breaks."""
    assert config.VIVEK_BOT_FILL_RECHECK_TRIGGERS == ("break",)
    pos = vr._ticket_to_position({"plan": _plan(entry_type="reclaim")}, 104.0, "asx", "2026-11-03")
    assert pos is not None
    monkeypatch.setattr(config, "VIVEK_BOT_FILL_RECHECK_TRIGGERS", ())
    assert vr._ticket_to_position({"plan": _plan()}, 104.0, "asx", "2026-11-03") is not None


# ── 3a · #7: grade on the plan the bot walks to ──────────────────────────────

def _p(entry, armed=True, trigger="reclaim", rr=2.0):
    return {"armed": armed, "entry": entry, "stop": entry - 4.0,
            "tp1": entry + 6.0, "tp2": entry + 4.0 * rr, "tp3": entry + 12.0 + 4.0 * rr,
            "scale": [0.25, 0.50, 0.15], "risk": 4.0, "rr": rr,
            "entry_trigger": trigger if armed else None,
            "trigger_bar": "2024-01-02" if armed else None}


CELLS = config.VIVEK_BOT_ENTRY_CELLS


def test_first_cell_tf_walks_the_cells_like_the_bot():
    plans = {"1W": _p(103, trigger="retest", rr=1.0), "3D": _p(101), "1D": _p(100, trigger="break")}
    assert vivek.first_cell_tf(plans, CELLS) == "3D"
    row = {"symbol": "X", "plans": plans, "entry_types": ["retest"]}
    assert vb._pick_plan(row, CELLS)[0] == "3D", "the scanner and the bot must walk to the same plan"


def test_first_cell_tf_needs_armed_complete_and_a_cell_trigger():
    assert vivek.first_cell_tf({"1W": _p(103, armed=False)}, CELLS) is None
    assert vivek.first_cell_tf({"1W": _p(103, trigger="retest")}, CELLS) is None
    assert vivek.first_cell_tf({"3D": _p(101, trigger="break")}, CELLS) is None
    incomplete = dict(_p(101), tp3=None)
    assert vivek.first_cell_tf({"3D": incomplete}, CELLS) is None
    assert vivek.first_cell_tf({}, CELLS) is None and vivek.first_cell_tf({"1W": _p(1)}, None) is None


_SIG = {"direction": "long", "close": 100.0, "level_tf": "weekly", "level": 99.0,
        "at_level": True, "reaction": "bounce", "structure": 0.8, "confluence": False}


def _stub(monkeypatch, plans):
    monkeypatch.setattr(vivek, "evaluate", lambda df, **kw: dict(_SIG))
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (9, "A+", ["CHIP"]))
    monkeypatch.setattr(vivek, "build_plans", lambda df, sig, **kw: dict(plans))
    monkeypatch.setattr(vivek, "build_markers", lambda plans: {})
    monkeypatch.setattr(vivek, "build_detail", lambda df, sig, lv: {})
    monkeypatch.setattr(vivek, "narrative", lambda *a, **k: "n/a")
    monkeypatch.setattr(vivek, "entry_types", lambda sig: ["reclaim"])


def _scan_row():
    idx = pd.date_range(end="2024-01-02", periods=30, freq="D")
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
                       "Volume": 1_000_000.0}, index=idx)
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"}]
    (row,) = scan.scan_vivek_market("asx", universe=uni, frames={"BHP.AX": df},
                                    pulse_data=[], progress=False)["results"]
    return row


def test_a_non_cell_weekly_with_a_poor_rr_no_longer_marks_the_row_down(monkeypatch):
    """The case #7 is for: an armed 1W RETEST (no cell) at R:R 1.0 used to be
    the headline, demoting the row to B+ -- while the bot would have traded
    the armed 3D reclaim underneath it."""
    _stub(monkeypatch, {"1W": _p(103, trigger="retest", rr=1.0), "3D": _p(101), "1D": _p(100, armed=False)})
    row = _scan_row()
    assert row["headline_tf"] == "3D" and row["entry"] == 101
    assert row["grade_raw"] == "A+" and row["grade"] == "A+"


def test_without_a_cell_plan_the_old_gate_stands(monkeypatch):
    _stub(monkeypatch, {"1W": _p(103, trigger="retest", rr=1.0), "1D": _p(100, armed=False)})
    row = _scan_row()
    assert row["headline_tf"] == "1W"
    assert row["grade_raw"] == "B+", "a lone non-cell plan is still graded on its own R:R"


def test_the_backtest_grades_the_same_way(monkeypatch):
    _stub(monkeypatch, {"1W": _p(103, trigger="retest", rr=1.0), "3D": _p(101), "1D": _p(100, armed=False)})
    idx = pd.date_range(end="2024-01-02", periods=30, freq="D")
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
                       "Volume": 1_000_000.0}, index=idx)
    row, plans, grade = vivek_backtest._build_row(dict(_SIG), df, "BHP", "BHP", "Materials")
    assert grade == "A+" and row["entry_types"] == ["reclaim"]


# ── 3b · #12: one position per company ───────────────────────────────────────

def test_the_company_key_is_the_issuer_part_of_the_name():
    a = vb._company_key("Liberty Media Corporation - Series A Common Stock", "FWONA", "nasdaq")
    c = vb._company_key("Liberty Media Corporation - Series C Common Stock", "FWONK", "nasdaq")
    assert a == c == "liberty media corporation"
    assert vb._company_key("Alphabet Inc. - Class C Capital Stock", "GOOG", "nasdaq") == \
        vb._company_key("Alphabet Inc. - Class A Common Stock", "GOOGL", "nasdaq")
    assert vb._company_key("BHP Group Limited", "BHP", "asx") == "bhp group limited"
    assert vb._company_key("Bitcoin", "BTC", "crypto") == "", "crypto has no issuer"
    assert vb._company_key("FWONA", "FWONA", "nasdaq") == "", "a bare-symbol name never collides"
    assert vb._company_key(None, "X", "asx") == ""


def _row(sym, name, sector="Technology"):
    return {"symbol": sym, "name": name, "sector": sector, "dir": "LONG", "grade": "A+",
            "grade_raw": "A+", "entry_types": ["reclaim"], "price": 101.0,
            "plans": {"1W": _p(100.0)}}


def _decide(rows, book=()):
    return vb.decide(rows, 150_000, market="nasdaq", open_book=list(book))


def test_a_second_line_of_a_held_company_is_refused():
    held = [{"symbol": "FWONA", "direction": "long", "sector": "Communication Services",
             "notional": 2500, "name": "Liberty Media Corporation - Series A Common Stock"}]
    out = _decide([_row("FWONK", "Liberty Media Corporation - Series C Common Stock")], held)
    assert not out["plans"] and out["summary"]["skip_reasons"] == {"dup_company": 1}


def test_two_lines_of_one_company_in_the_same_run_take_only_the_first():
    out = _decide([_row("GOOGL", "Alphabet Inc. - Class A Common Stock"),
                   _row("GOOG", "Alphabet Inc. - Class C Capital Stock")])
    assert [p["plan"]["symbol"] for p in out["plans"]] == ["GOOGL"]
    assert out["summary"]["skip_reasons"].get("dup_company") == 1


def test_different_companies_and_the_switch_off_are_untouched(monkeypatch):
    out = _decide([_row("AAPL", "Apple Inc. - Common Stock"), _row("MSFT", "Microsoft Corporation - Common Stock")])
    assert len(out["plans"]) == 2
    monkeypatch.setattr(config, "VIVEK_BOT_ONE_PER_COMPANY", False)
    out = _decide([_row("GOOGL", "Alphabet Inc. - Class A Common Stock"),
                   _row("GOOG", "Alphabet Inc. - Class C Capital Stock")])
    assert len(out["plans"]) == 2


def test_the_runner_hands_decide_the_names_it_needs():
    book = {"open": [{"symbol": "FWONA", "market": "nasdaq", "direction": "long", "sector": "",
                      "notional": 2500, "name": "Liberty Media Corporation - Series A Common Stock"}]}
    (view,) = vr._open_book_view(book, "nasdaq")
    assert view["name"].startswith("Liberty Media"), "without the name the company rule is blind"


# ── 3c · #13 / #143: the 11 GICS sectors ─────────────────────────────────────

def test_both_label_sets_land_on_the_gics_sectors():
    k = lambda s, m="asx": vb._sector_key("X", s, m)   # noqa: E731
    assert k("Banks") == k("Insurance") == k("Financial Services") == "financials"
    assert k("Financial Services", "nasdaq") == "financials"
    assert k("Software & Services") == k("Technology", "nasdaq") == "information technology"
    assert k("Healthcare", "nasdaq") == k("Pharmaceuticals, Biotechnology & Life Sciences") == "health care"
    assert k("Consumer Cyclical", "nasdaq") == k("Consumer Services") == "consumer discretionary"
    assert k("Media & Entertainment") == k("Communication Services", "nasdaq") == "communication services"
    assert k(" MATERIALS ") == k("Basic Materials", "nasdaq") == "materials"


def test_not_applic_and_class_pend_are_exempt_and_unknown_labels_kept():
    assert vb._sector_key("ETF", "Not Applic", "asx") == ""
    assert vb._sector_key("NEW", "Class Pend", "asx") == ""
    assert vb._sector_key("X", "Space Mining", "asx") == "space mining"
    assert vb._sector_key("BTC", "", "crypto") == "crypto-major"
    # the bot's fund test still reads the RAW label: a Not Applic ETF stays out
    assert vb._is_fund_or_reit({"name": "Some Fund", "sector": "Not Applic"})


def test_every_gics_value_is_one_of_the_eleven_or_blank():
    eleven = {"energy", "materials", "industrials", "consumer discretionary", "consumer staples",
              "health care", "financials", "information technology", "communication services",
              "utilities", "real estate"}
    assert set(config.VIVEK_BOT_SECTOR_GICS.values()) <= eleven | {""}
    assert all(k == k.strip().lower() for k in config.VIVEK_BOT_SECTOR_GICS), "keys are compared lower-case"


def test_the_cap_now_counts_three_asx_financial_groups_as_one():
    book = ([{"symbol": f"B{i}", "direction": "long", "sector": "Banks", "notional": 2500}
             for i in range(2)]
            + [{"symbol": f"I{i}", "direction": "long", "sector": "Insurance", "notional": 2500}
               for i in range(2)]
            + [{"symbol": f"F{i}", "direction": "long", "sector": "Financial Services", "notional": 2500}
               for i in range(2)])
    out = vb.decide([_row("NEWFIN", "New Financial Ltd", sector="Banks")], 150_000,
                    market="asx", open_book=book)
    assert not out["plans"] and out["summary"]["skip_reasons"] == {"sector_cap": 1}


def test_bot_rules_publishes_the_table_the_deck_mirrors():
    from scanner import run
    p = run.bot_rules_payload()
    assert p["sector_gics"] == config.VIVEK_BOT_SECTOR_GICS
    assert p["one_per_company"] is True and p["fill_recheck_triggers"] == ["break"]
    assert p["cycle_tag"] == "hc4-2"


# ── 3d · #148: the W+H4 point needs both averages near the PRICE ─────────────

def test_the_w_h4_point_needs_both_averages_near_the_price():
    tol = config.VIVEK_NEAR_TOL
    assert vivek.w_h4_confluence(100, 103, 97)
    # the bug: both averages 8-10% away, but within 4% of EACH OTHER
    assert not vivek.w_h4_confluence(100, 110, 108)
    assert not vivek.w_h4_confluence(100, 103, 100 * (1 + tol) + 0.5)
    assert not vivek.w_h4_confluence(100, None, 100)
    assert not vivek.w_h4_confluence(100, float("nan"), 100)
    assert vivek.w_h4_confluence(100, 100 * (1 + tol), 100 * (1 - tol)), "the tolerance is inclusive"


def test_evaluate_scores_the_point_through_the_helper():
    import inspect
    src = inspect.getsource(vivek.evaluate)
    assert "confluence = w_h4_confluence(price, weekly_sma, daily_sma)" in src


# ── 4 · the day-14 stamp (report only) ───────────────────────────────────────

def _open(entry_date="2026-11-03", **kw):
    p = {"symbol": "X", "market": "asx", "direction": "long", "status": "open",
         "entry": 100.0, "stop": 96.0, "risk": 4.0, "entry_date": entry_date,
         "tp1_hit": False, "mfe_r": 0.3}
    p.update(kw)
    return p


def test_the_stamp_lands_once_on_day_14_with_what_the_cut_needs():
    pos = _open()
    vr._stamp_d14(pos, 101.0, "2026-11-16")                 # day 13: nothing
    assert "d14" not in pos
    vr._stamp_d14(pos, 101.0, "2026-11-17")                 # day 14
    assert pos["d14"] == {"day": "2026-11-17", "held": 14, "mfe_r": 0.3, "r": 0.25, "tp1_hit": False}
    vr._stamp_d14(pos, 90.0, "2026-11-18")                  # never re-stamped
    assert pos["d14"]["r"] == 0.25


def test_the_stamp_is_short_aware_nan_safe_and_switchable(monkeypatch):
    short = _open(direction="short", stop=104.0)
    vr._stamp_d14(short, 99.0, "2026-11-17")
    assert short["d14"]["r"] == 0.25
    bad = _open(risk=float("nan"))
    vr._stamp_d14(bad, 101.0, "2026-11-17")
    assert "d14" not in bad
    monkeypatch.setattr(config, "VIVEK_BOT_D14_STAMP_DAYS", 0)
    off = _open()
    vr._stamp_d14(off, 101.0, "2026-11-20")
    assert "d14" not in off


def test_the_stamp_survives_the_close_and_runs_before_any_exit():
    from scanner import vivek_journal as vj
    assert vj._OPEN_ONLY_FIELDS and "d14" not in vj._OPEN_ONLY_FIELDS, "a closing row would drop its stamp"
    import inspect
    src = inspect.getsource(vr.run_market)
    assert src.index("_stamp_d14(pos, price, day)") < src.index("_close_time_stop(pos, price, day, costs)")


def test_nothing_reads_the_stamp_to_decide():
    import inspect
    for fn in (vb.decide, vb.plan_trade, vb.evaluate_setup, vb.manage_position):
        assert "d14" not in inspect.getsource(fn), fn.__name__

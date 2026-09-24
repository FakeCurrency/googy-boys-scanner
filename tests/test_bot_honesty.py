"""The two bot-honesty patches (owner: "change the rule", 2026-09-24).

reviews/2026-09-24-bot-vs-cells.md found the live gate matches the four-cell
sleeve except in two places, and the owner had both closed:

  1. THE STOP CAP IS RE-READ AT THE FILL. evaluate_setup tests
     VIVEK_BOT_MAX_STOP_PCT against the plan's entry (the signal close); the
     book fills later at a live quote. vivek_run._ticket_to_position now
     refuses a fill whose stop sits wider than the cap from the FILL -- the
     measure PR #42's sleeve used. Entry only: a held position never passes
     through it, so CVLT / SMCI / BNB (booked before the change) stay open.
  2. THE BOOK RECORDS THE GRADE THE GATE READ. plan_trade stamped "A+" on
     every ticket, so since A became takeable (2026-09-21) an A take was
     booked as A+. It now carries decision["grade"] (grade_raw). A label only:
     no takeability, sizing or ordering moves.
"""

from __future__ import annotations

import pathlib

import pytest

from scanner import config
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_run as vr

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAP = config.VIVEK_BOT_MAX_STOP_PCT


def _ticket(stop, fill, signal=100.0, direction="long", grade="A+"):
    sign = 1 if direction == "long" else -1
    return {"symbol": "X", "name": "X", "sector": "", "direction": direction, "grade": grade,
            "entry_type": "reclaim", "entry_type_label": "x", "timeframe": "3D",
            "entry": signal, "stop": stop,
            "tp1": fill * (1 + sign * 0.3), "tp2": fill * (1 + sign * 0.6),
            "tp3": fill * (1 + sign * 0.9),
            "scale": [0.25, 0.5, 0.15], "trigger_bar": None, "leverage_target": 5.0,
            "units": 1.0, "notional": 5000.0, "leverage": 1.0, "risk_pct": 0.1, "risk_usd": 1.0}


def _fill(plan, price):
    return vr._ticket_to_position({"plan": plan}, price, "nasdaq", "2026-09-24")


# -- 1. the stop cap at the fill -------------------------------------------

@pytest.mark.parametrize("plan_pct,fill_pct", [(23.73, 26.58), (22.53, 26.32), (23.49, 25.04)])
def test_the_three_the_note_named_would_now_be_refused(plan_pct, fill_pct):
    """CVLT, SMCI and BNB's own plan/fill stop distances: inside the cap at the
    signal close, outside it at the fill."""
    stop = 100.0 * (1 - plan_pct / 100.0)
    fill = stop / (1 - fill_pct / 100.0)
    assert (100.0 - stop) / 100.0 * 100 <= CAP < (fill - stop) / fill * 100
    assert _fill(_ticket(stop, fill), fill) is None


def test_a_fill_that_stays_inside_the_cap_is_booked_as_before():
    stop = 100.0 * (1 - (CAP - 5) / 100.0)
    for fill in (95.0, 100.0, 103.0):                  # gapped down, on the close, paid up a little
        pos = _fill(_ticket(stop, fill), fill)
        assert pos is not None and pos["entry"] == fill
        assert pos["risk"] / pos["entry"] * 100 <= CAP


def test_the_boundary_is_the_gates_own_greater_than():
    """evaluate_setup refuses `stop_pct > cap`, so exactly the cap is allowed;
    the fill check uses the same comparison."""
    stop = 100.0 * (1 - (CAP - 3) / 100.0)
    at_cap = stop / (1 - CAP / 100.0)
    assert _fill(_ticket(stop, at_cap), at_cap) is not None
    assert _fill(_ticket(stop, at_cap * 1.001), at_cap * 1.001) is None


def test_a_short_is_measured_the_same_way():
    stop = 100.0 * (1 + (CAP - 2) / 100.0)             # above the entry: a short's stop
    wide = stop / (1 + (CAP + 2) / 100.0)              # sold lower, stop now further away
    assert _fill(_ticket(stop, wide, direction="short"), wide) is None
    ok = stop / (1 + (CAP - 1) / 100.0)
    assert _fill(_ticket(stop, ok, direction="short"), ok) is not None


def test_a_cap_of_zero_is_off(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_STOP_PCT", 0)
    stop = 70.0
    fill = 110.0                                       # a 36% stop at the fill
    assert _fill(_ticket(stop, fill), fill) is not None


def test_it_runs_at_entry_only():
    """Held positions are marked, stopped, time-stopped and closed off the book
    and never pass through _ticket_to_position, so nothing already open --
    CVLT, SMCI, BNB -- can be closed or skipped by this check."""
    src = (ROOT / "scanner" / "broker" / "vivek_run.py").read_text(encoding="utf-8")
    assert src.count("_ticket_to_position(") == 2, "one definition, one call: the new-entry fill"
    call = src.index("pos = _ticket_to_position(")
    loop = src.rindex('for out in decision["plans"]:', 0, call)
    assert src.count("\n", loop, call) < 20, "the call sits in the new-entry loop"
    assert "[wide_stop_at_fill]" in src, "a refusal is logged with its own code"


# -- 2. the grade the gate read ----------------------------------------------

def _row(grade_raw="A", grade="A+", stop=90.0):
    plan = {"entry": 100.0, "stop": stop, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0,
            "armed": True, "entry_trigger": "reclaim", "rr": 2.0, "scale": [0.25, 0.5, 0.15]}
    return {"symbol": "X", "name": "Operating Co", "sector": "Industrials", "dir": "LONG",
            "grade": grade, "grade_raw": grade_raw, "plans": {"3D": plan}, "data_age_days": 0}


@pytest.mark.parametrize("raw", ["A", "A+"])
def test_the_ticket_carries_the_grade_the_gate_read(raw):
    out = vb.plan_trade(_row(grade_raw=raw), config.VIVEK_BOT_ACCOUNT_EQUITY, market="nasdaq")
    assert out["plan"]["grade"] == raw == out["grade"]


def test_the_raw_grade_not_the_displayed_one():
    out = vb.plan_trade(_row(grade_raw="A", grade="A+"), config.VIVEK_BOT_ACCOUNT_EQUITY,
                        market="nasdaq")
    assert out["plan"]["grade"] == "A"


def test_the_book_row_carries_it():
    out = vb.plan_trade(_row(grade_raw="A"), config.VIVEK_BOT_ACCOUNT_EQUITY, market="nasdaq")
    pos = vr._ticket_to_position(out, 100.0, "nasdaq", "2026-09-24")
    assert pos is not None and pos["grade"] == "A"


def test_the_label_moves_no_take():
    """A and A+ rows with the same plan get the same decision and the same
    ticket in every field but the grade."""
    a = vb.plan_trade(_row(grade_raw="A"), config.VIVEK_BOT_ACCOUNT_EQUITY, market="nasdaq")
    ap = vb.plan_trade(_row(grade_raw="A+"), config.VIVEK_BOT_ACCOUNT_EQUITY, market="nasdaq")
    assert a["take"] is ap["take"] is True
    strip = lambda d: {k: v for k, v in d.items() if k not in ("grade", "reason")}  # noqa: E731
    assert strip(a["plan"]) == strip(ap["plan"])
    assert vb.evaluate_setup(_row(grade_raw="B+"))["code"] == "grade_excluded"

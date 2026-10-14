"""Book tide-stress report (scripts/book_stress.py, batch-100 WS-D).

The number this publishes is what tells the owner how much of the paper
profit is tide, so its math is verified against a hand-computed fixture and
its honesty rules (unpriced rows counted not zeroed, shorts untouched,
no-op means no rewrite) are pinned.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("book_stress", ROOT / "scripts" / "book_stress.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def _pos(mark=110.0, stop=95.0, entry=100.0, risk=10.0, ur=1.0, direction="long", **kw):
    return {"last_mark": mark, "stop": stop, "entry": entry, "risk": risk,
            "unreal_r": ur, "direction": direction, **kw}


def test_the_math_by_hand():
    # One position: entry 100, stop 95, mark 110, risk 10 -> ur +1.0R.
    # -5%: 110*0.95 = 104.5 > stop -> re-marks to (104.5-100)/10 = +0.45R.
    # -20%: 110*0.80 = 88 <= 95 -> stopped, lands at (95-100)/10 = -0.5R.
    out = bs.stress([_pos()], shocks=(0.05, 0.20))
    assert out["n_long"] == 1 and out["base_unreal_r"] == 1.0
    s5, s20 = out["shocks"]
    assert s5["stopped"] == 0 and abs(s5["unreal_r"] - 0.45) < 1e-9
    assert abs(s5["given_back_r"] - 0.55) < 1e-9
    assert s20["stopped"] == 1 and abs(s20["unreal_r"] - (-0.5)) < 1e-9


def test_a_partially_banked_row_is_shocked_on_the_same_R_basis_as_its_base():
    """REFINE200 (2026-10-14): the book stamps unreal_r on the REMAINING open
    fraction (vivek_guard._unreal_r). The live INTR row read +0.498R stored
    (+1.992R full size, 75% booked) and a -3% shock re-marked it at full size,
    so a drawdown 'gave back' NEGATIVE R. Both sides now share one basis."""
    # entry 100, risk 10, mark 120 -> +2.0R full size; 75% booked -> +0.5R.
    intr = _pos(mark=120.0, stop=100.0, entry=100.0, risk=10.0, ur=0.5, booked_pct=0.75)
    out = bs.stress([intr], shocks=(0.03, 0.20))
    s3, s20 = out["shocks"]
    # -3%: 116.4 -> +1.64R full, x0.25 = +0.41R; gives back 0.09R, never a gain.
    assert abs(s3["unreal_r"] - 0.41) < 1e-9
    assert s3["given_back_r"] >= 0, "a drawdown can never add R"
    assert abs(s3["given_back_r"] - 0.09) < 1e-9
    # -20%: 96 <= stop 100 -> stopped at breakeven: 0R on the remainder.
    assert s20["stopped"] == 1 and abs(s20["unreal_r"]) < 1e-9
    # Nothing booked behaves exactly as before.
    plain = bs.stress([_pos(booked_pct=0.0)], shocks=(0.05,))["shocks"][0]
    assert abs(plain["unreal_r"] - 0.45) < 1e-9


def test_every_shock_gives_back_R_on_the_live_book_shape():
    # Monotone: a deeper tape never leaves more unrealized R than a shallower
    # one, and none gives back a negative amount, whatever is banked.
    rows = [_pos(mark=120.0, stop=100.0, ur=0.5, booked_pct=0.75),
            _pos(mark=117.6, stop=104.0, ur=1.32, booked_pct=0.25),
            _pos(mark=104.3, stop=95.0, ur=0.43)]
    out = bs.stress(rows, shocks=(0.03, 0.05, 0.08, 0.10))
    assert all(s["given_back_r"] >= 0 for s in out["shocks"])
    vals = [s["unreal_r"] for s in out["shocks"]]
    assert vals == sorted(vals, reverse=True)


def test_a_stop_boundary_hit_counts_as_stopped():
    # mark*(1-d) EXACTLY at the stop is a fill, not a survival.
    out = bs.stress([_pos(mark=100.0, stop=95.0)], shocks=(0.05,))
    assert out["shocks"][0]["stopped"] == 1


def test_unpriced_rows_are_counted_never_valued_at_zero():
    rows = [_pos(), _pos(mark=None), _pos(risk=0.0), _pos(mark=float("nan"))]
    out = bs.stress(rows, shocks=(0.05,))
    assert out["n_long"] == 1
    assert out["n_skipped_unpriced"] == 3, "None, zero-risk and NaN all skip loudly"
    assert out["base_unreal_r"] == 1.0, "skipped rows contribute nothing, not zero-R rows"


def test_shorts_are_untouched_and_counted():
    out = bs.stress([_pos(), _pos(direction="short", ur=5.0)], shocks=(0.05,))
    assert out["n_long"] == 1 and out["n_short_untouched"] == 1
    assert out["base_unreal_r"] == 1.0, "a short's R never enters the long-shock table"


def test_shocks_come_from_config():
    from scanner import config
    assert bs.SHOCKS == tuple(config.BOOK_STRESS_SHOCKS)


def test_finite_only_payload_shape():
    out = bs.stress([_pos()], shocks=(0.03,))
    flat = json.dumps(out)
    assert "NaN" not in flat and "Infinity" not in flat


def test_nothing_in_the_engine_reads_the_stress_file():
    for p in list((ROOT / "scanner").rglob("*.py")):
        if p.name == "config.py":
            continue                      # declares BOOK_STRESS_SHOCKS (rule 3)
        assert "book_stress" not in p.read_text(encoding="utf-8"), \
            f"the stress report is display/research only: {p}"


def test_unchanged_content_is_a_stated_noop_not_a_redate():
    src = (ROOT / "scripts" / "book_stress.py").read_text(encoding="utf-8")
    assert "BOOK_STRESS_UNCHANGED" in src
    assert 'k != "generated_at"' in src, "the comparison must ignore only the timestamp"


def test_the_workflow_runs_and_stages_it():
    wf = (ROOT / ".github" / "workflows" / "alert_returns.yml").read_text(encoding="utf-8")
    assert "python scripts/book_stress.py" in wf
    assert "git add -- public/data/book_stress.json" in wf
    assert "BOOK_STRESS_UNCHANGED" in wf

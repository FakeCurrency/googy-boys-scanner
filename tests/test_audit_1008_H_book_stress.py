"""Audit #31 (2026-10-08): book_stress valued a RUNNER at full size.

The base (`base_unreal_r`) is the sum of the engine's published `unreal_r`,
which vivek_guard._unreal_r scales by the un-booked remainder
(1 - booked_pct). The shocked and stopped values were full-size, so for any
position that had banked a partial the two sides of `given_back_r` were on
different bases: a 0% shock reported a GAIN and every published row
understated what a drawdown takes back. Both sides now use the remainder.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("book_stress", ROOT / "scripts" / "book_stress.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def _runner(mark=120.0, stop=100.0, entry=100.0, risk=10.0, booked=0.5):
    """The audit's synthetic case: half booked, so the engine's unreal_r is
    (120-100)/10 x 0.5 = +1.0R."""
    from scanner.broker import vivek_guard
    pos = {"last_mark": mark, "stop": stop, "entry": entry, "risk": risk,
           "booked_pct": booked, "direction": "long"}
    pos["unreal_r"] = vivek_guard._unreal_r(pos, mark)
    return pos


def test_a_zero_shock_gives_back_nothing_on_a_runner():
    out = bs.stress([_runner()], shocks=(0.0,))
    assert out["base_unreal_r"] == 1.0
    s0 = out["shocks"][0]
    assert s0["unreal_r"] == 1.0, "no move must reproduce the base (was +2.0R)"
    assert s0["given_back_r"] == 0.0, "no move gives nothing back (was -1.0R)"


def test_a_runner_is_shocked_on_its_remainder():
    # -3%: 120 x 0.97 = 116.4 -> (116.4-100)/10 = 1.64R full size, x 0.5 = 0.82R.
    s3 = bs.stress([_runner()], shocks=(0.03,))["shocks"][0]
    assert abs(s3["unreal_r"] - 0.82) < 1e-9
    assert abs(s3["given_back_r"] - 0.18) < 1e-9, "was -0.64R: a drawdown read as a gain"


def test_a_stopped_runner_lands_on_its_remainders_stop_R():
    # stop 90 (below entry), -30%: 120 x 0.7 = 84 <= 90 -> stopped, (90-100)/10
    # = -1.0R full size, x 0.75 remaining = -0.75R.
    pos = _runner(stop=90.0, booked=0.25)
    s = bs.stress([pos], shocks=(0.30,))["shocks"][0]
    assert s["stopped"] == 1 and abs(s["unreal_r"] - (-0.75)) < 1e-9


def test_a_flat_position_is_unchanged_by_the_fix():
    # booked_pct absent/0: remainder 1, identical to the pre-fix arithmetic.
    pos = {"last_mark": 110.0, "stop": 95.0, "entry": 100.0, "risk": 10.0,
           "unreal_r": 1.0, "direction": "long"}
    s5 = bs.stress([pos], shocks=(0.05,))["shocks"][0]
    assert abs(s5["unreal_r"] - 0.45) < 1e-9


def test_a_malformed_booked_pct_is_skipped_and_counted_never_guessed():
    bad = _runner()
    bad["booked_pct"] = float("nan")
    out = bs.stress([bad, _runner()], shocks=(0.0,))
    assert out["n_long"] == 1 and out["n_skipped_unpriced"] == 1


def test_the_committed_book_reproduces_its_own_base_at_a_zero_shock():
    """Whatever the live book holds, a 0% shock must give back ~nothing: the
    base and the shocked side measure the same exposure. (At the audit the
    one runner, INTR, made this read -0.43R.)"""
    book = json.loads((ROOT / "journal" / "vivek_bot_book.json").read_text(encoding="utf-8"))
    out = bs.stress(book.get("open") or [], shocks=(0.0,))
    assert abs(out["shocks"][0]["given_back_r"]) <= 0.05, out["shocks"][0]

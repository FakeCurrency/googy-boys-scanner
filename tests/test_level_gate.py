"""W3-ONLY LEVEL GATE (owner-signed 2026-08-02, cycle "w3-1").

The gate narrows which CANDIDATE rows vivek_bot.decide() is shown to the
levels in config.VIVEK_BOT_LEVEL_TF_ALLOW - the only cohort that passed all
three pre-registered confirmation samples (IS / OOS / C3, gates W-1/2/3).

What these tests pin, in order of importance:
  1. Gate OFF is byte-identical to the pre-gate world (empty tuple = no-op,
     SAME list object back, zero dropped) - so reverting the cycle is one
     constant, not a code change.
  2. Gate ON keeps only allowlisted levels, case/whitespace-normalised.
  3. FAIL-CLOSED: a row with a missing/blank/None level_tf is dropped and
     counted, never waved through.
  4. The gate lives OUTSIDE the ringfenced vivek_bot.py, runs exactly once,
     BEFORE decide(), and never touches the book (held positions / exits /
     time-stops / guards are structurally out of its reach).
  5. The cycle marker is stamped on new rows only while a cycle tag is set,
     and is absent (not empty) otherwise - the sizing_mode convention.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from scanner import config
from scanner.broker import vivek_run

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rows():
    return [
        {"symbol": "AAA", "level_tf": "weekly"},
        {"symbol": "BBB", "level_tf": "3d"},
        {"symbol": "CCC", "level_tf": "h4"},
        {"symbol": "DDD", "level_tf": "  Weekly "},   # normalisation
        {"symbol": "EEE", "level_tf": ""},            # blank -> fail-closed
        {"symbol": "FFF"},                            # missing -> fail-closed
        {"symbol": "GGG", "level_tf": None},          # None -> fail-closed
    ]


def test_gate_off_is_a_byte_identical_no_op(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", (), raising=False)
    rows = _rows()
    kept, dropped = vivek_run._apply_level_gate(rows)
    assert kept is rows          # SAME object - not even a copy
    assert dropped == 0


def test_gate_on_keeps_only_allowlisted_levels(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ("weekly", "3d"),
                        raising=False)
    kept, dropped = vivek_run._apply_level_gate(_rows())
    assert [r["symbol"] for r in kept] == ["AAA", "BBB", "DDD"]
    assert dropped == 4


def test_missing_blank_or_none_level_is_dropped_fail_closed(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ("weekly", "3d"),
                        raising=False)
    bad = [{"symbol": "X"}, {"symbol": "Y", "level_tf": ""},
           {"symbol": "Z", "level_tf": None}]
    kept, dropped = vivek_run._apply_level_gate(bad)
    assert kept == [] and dropped == 3


def test_h4_only_book_takes_nothing_under_the_gate(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ("weekly", "3d"),
                        raising=False)
    kept, dropped = vivek_run._apply_level_gate(
        [{"symbol": "H1", "level_tf": "h4"}, {"symbol": "H2", "level_tf": "h4"}])
    assert kept == [] and dropped == 2


def test_empty_and_none_input_are_safe(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ("weekly", "3d"),
                        raising=False)
    assert vivek_run._apply_level_gate([]) == ([], 0)
    assert vivek_run._apply_level_gate(None) == ([], 0)


def test_the_gate_runs_once_and_before_decide_and_never_sees_the_book():
    """Structural pin: one call site, ahead of decide(), rows-only signature."""
    src = inspect.getsource(vivek_run)
    calls = src.count("_apply_level_gate(results)")
    assert calls == 1, "the gate must have exactly ONE call site"
    assert src.index("_apply_level_gate(results)") < src.index(
        "decision = vivek_bot.decide("), "the gate must run BEFORE decide()"
    sig = inspect.signature(vivek_run._apply_level_gate)
    assert list(sig.parameters) == ["results"], (
        "the gate takes the candidate rows and NOTHING else - handing it the "
        "book is how an entry filter grows into an exit engine")


def test_the_ringfenced_bot_file_never_reads_the_gate_constant():
    bot_src = (ROOT / "scanner" / "broker" / "vivek_bot.py").read_text(
        encoding="utf-8")
    assert "VIVEK_BOT_LEVEL_TF_ALLOW" not in bot_src, (
        "the gate must stay OUTSIDE the ringfenced decision engine")


def test_cycle_tag_is_stamped_only_while_a_cycle_is_active():
    """Source-contract pin (house pattern): the stamp exists, guards on the
    config tag, and follows sizing_mode so the audit block stays together."""
    src = inspect.getsource(vivek_run._ticket_to_position)
    assert 'snap["sizing_mode"]' in src
    assert 'VIVEK_BOT_CYCLE_TAG' in src
    assert 'snap["cycle"] = _cycle' in src
    assert src.index('snap["sizing_mode"]') < src.index('snap["cycle"]')
    assert "if _cycle:" in src, (
        "no cycle -> NO key at all (absent != empty, the review-flags rule)")


def test_config_ships_the_gate_and_the_cycle_tag():
    assert tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW) == ("weekly", "3d")
    assert config.VIVEK_BOT_CYCLE_TAG == "w3-1"
    # The gate must never be widenable to an unknown level by accident: the
    # allowlist may only ever contain levels the engine actually publishes.
    assert set(config.VIVEK_BOT_LEVEL_TF_ALLOW) <= {"weekly", "3d", "h4"}

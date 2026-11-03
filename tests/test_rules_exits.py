"""One definition of a rules exit (NEXT100 #9): config.VIVEK_BOT_RULES_EXITS.

Every "rules close" figure -- the decision pack's checkpoints, the journal's
decider split and cycle board, the deck's record line and per-cell note, the
status sheet's cohort, the system page's evidence card, the bot-vs-cells and
live-vs-replay studies -- turns on which `exit_reason` values count as the
rules acting. The tuple was typed out in eight places -- four in Python (one
of them, in scripts/bot_vs_cells.py, with an extra "tp") and four JS literals,
two of them in app.js. Now it lives once in config;
Python imports it and the site reads it from bot_rules.json `rules_exits`
(tests/test_js_config_mirrors.py pins the JS offline fallbacks).

The pins here:
  * the list's shape: lowercase, unique, never "manual", and APPEND-ONLY over
    the reasons the frozen hc4-1 / hc4-2 checkpoints already count;
  * every trade-level reason the book's close writers can stamp, other than
    the hand close's "manual", is in it -- so a new exit path cannot ship as a
    silent "hand close". The sweep reads every reason slot of the one close
    writer (vivek_journal._close_remaining: `reason`, `exit_reason`, by position
    or keyword) and every `["exit_reason"] = ...` in vivek_journal.py and
    vivek_run.py; a writer in another module is outside it (the replays stamp
    their own reasons, so the sweep cannot widen to the whole tree);
  * no Python file outside config re-types it, and every reader follows it;
  * bot_rules.json publishes it;
  * config stays stdlib-only, so the bare-Python decision pack can import it.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

import pytest

from scanner import config, live_vs_replay, run

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The reasons the rules had written when the decision pack's checkpoints were
# frozen (2026-10-14; hc4-2's PR-9..PR-16 count the same four). FROZEN here on
# purpose: config may ADD a reason, never drop one of these, or a frozen
# checkpoint would silently stop counting closes it has already counted.
FROZEN_FLOOR = ("stop", "time", "trail", "target")


def _load_script(name):
    spec = importlib.util.spec_from_file_location(f"_rx_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- the list itself -------------------------------------------------------------

def test_the_list_is_lowercase_unique_and_never_a_hand_close():
    ex = config.VIVEK_BOT_RULES_EXITS
    assert isinstance(ex, tuple) and ex, "a tuple, and never empty (empty = no rules close at all)"
    assert all(isinstance(r, str) and r and r == r.strip().lower() for r in ex), ex
    assert len(set(ex)) == len(ex), f"duplicate reason in {ex}"
    assert "manual" not in ex, "a hand close is never a rules exit"


def test_the_list_is_append_only_over_the_frozen_checkpoints():
    missing = [r for r in FROZEN_FLOOR if r not in config.VIVEK_BOT_RULES_EXITS]
    assert not missing, (
        f"VIVEK_BOT_RULES_EXITS dropped {missing}: closed rows keep their reason forever and "
        "the decision pack's frozen checkpoints count them as rules closes")
    assert config.VIVEK_BOT_RULES_EXITS[:len(FROZEN_FLOOR)] == FROZEN_FLOOR, (
        "append new reasons at the END: the journal prints its mechanism line in this order")


# -- every reason the book's close writers stamp is classified ------------------

_WRITERS = (ROOT / "scanner" / "vivek_journal.py", ROOT / "scanner" / "broker" / "vivek_run.py")


def _strs(node):
    """String constants an expression can evaluate to (a ternary's branches,
    an `a or b`), never the strings inside its tests (pos["tp1_hit"])."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _strs(node.body) | _strs(node.orelse)
    if isinstance(node, ast.BoolOp):
        return set().union(*(_strs(v) for v in node.values))
    return set()               # a Name: a caller's label (the hand close's `reason`)


def _written_reasons(paths=_WRITERS):
    out = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                f = node.func
                if (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) != "_close_remaining":
                    continue
                if len(node.args) > 3:
                    out |= _strs(node.args[3])     # the exit record's reason (the default verdict)
                if len(node.args) > 5:
                    out |= _strs(node.args[5])     # exit_reason passed by position
                for kw in node.keywords:
                    if kw.arg in ("reason", "exit_reason"):
                        out |= _strs(kw.value)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "exit_reason"):
                        out |= _strs(node.value)
    return out


def test_every_reason_a_close_writer_stamps_is_classified():
    written = _written_reasons()
    # the sweep must see the writers it exists to watch, or it passes vacuously
    assert {"stop", "trail", "target", "time", "manual"} <= written, (
        f"the close-writer sweep found only {sorted(written)} -- re-point it")
    unclassified = sorted(written - set(config.VIVEK_BOT_RULES_EXITS) - {"manual"})
    assert not unclassified, (
        f"the book can now close a row with exit_reason {unclassified}, which no reader counts as "
        "the rules: add it to config.VIVEK_BOT_RULES_EXITS (or it reads as a hand close everywhere)")


def test_the_close_writer_sweep_reads_every_reason_slot(tmp_path):
    """Mutation check for the sweep itself: `reason` and `exit_reason`, by
    position or by keyword, a ternary's branches and a direct assignment are
    all seen; a caller's label (a Name) and a ternary's TEST are not reasons."""
    planted = tmp_path / "writer.py"
    planted.write_text(
        'vj._close_remaining(t, p, d, "pos4", c, "pos6")\n'
        '_close_remaining(t, p, d, "pos4b", c, exit_reason="kw_exit")\n'
        '_close_remaining(t, p, d, reason="kw_reason", costs=c)\n'
        '_close_remaining(t, p, d, "manual", c, exit_reason=label)\n'
        't["exit_reason"] = "if_body" if t["not_a_reason"] else "if_else"\n', encoding="utf-8")
    assert _written_reasons((planted,)) == {
        "pos4", "pos6", "pos4b", "kw_exit", "kw_reason", "manual", "if_body", "if_else"}


# -- one definition: nobody re-types it, everybody follows it ------------------

_SIGNATURE = {"stop", "trail", "target"}
# A list that only LOOKS like it (a replay engine's own exit reasons, say)
# carries this marker on its line and is left alone.
_NOT_A_COPY = "not-rules-exits"


def _retyped_copies():
    hits = []
    for base in ("scanner", "scripts", "phasemap"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if path == ROOT / "scanner" / "config.py" or "tests" in path.relative_to(ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, (ast.Tuple, ast.List, ast.Set)) or not node.elts:
                    continue
                if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
                    continue
                if _SIGNATURE <= {e.value for e in node.elts} and _NOT_A_COPY not in lines[node.lineno - 1]:
                    # as_posix: the owner runs the gate on Windows, where a bare
                    # relative path prints with backslashes
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    return hits


def test_no_python_file_retypes_the_list():
    hits = _retyped_copies()
    assert not hits, (
        f"a rules-exit list is typed out again at {hits}: read config.VIVEK_BOT_RULES_EXITS")


def test_the_retype_sweep_catches_a_copy(tmp_path, monkeypatch):
    """Mutation check for the sweep itself: a planted copy is found."""
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "x.py").write_text(
        'MECHANICAL = ("stop", "trail", "target", "time", "tp")\n'
        'REPLAY = ["stop", "trail", "target", "eod"]  # not-rules-exits: the replay\'s own\n'
        'OTHER = ("stop", "trail")\n', encoding="utf-8")
    for d in ("scanner", "phasemap"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert _retyped_copies() == ["scripts/x.py:1"]


def test_the_decision_pack_counts_with_config():
    dp = _load_script("decision_pack")
    assert dp.MECHANICAL_EXITS is config.VIVEK_BOT_RULES_EXITS
    assert dp.is_rules({"exit_reason": " Trail "}) and not dp.is_rules({"exit_reason": "manual"})
    assert not dp.is_rules({})


def test_every_python_reader_follows_config(monkeypatch, tmp_path):
    """Add a reason to config and every reader counts it -- the proof that
    none of them kept a private copy. (decision_pack binds the tuple at import,
    covered by the identity pin above.)"""
    monkeypatch.setattr(config, "VIVEK_BOT_RULES_EXITS", config.VIVEK_BOT_RULES_EXITS + ("d14",))
    new, hand, none = {"exit_reason": "d14"}, {"exit_reason": "manual"}, {}
    assert live_vs_replay.is_rules_exit(new) and not live_vs_replay.is_rules_exit(hand)
    assert not live_vs_replay.is_rules_exit(none)
    bvc = _load_script("bot_vs_cells")
    assert bvc.is_rules_exit(new) and not bvc.is_rules_exit(hand) and not bvc.is_rules_exit(none)
    # run.py's evidence card (the live rules closes per market)
    from scanner.broker import vivek_run
    monkeypatch.setattr(vivek_run, "BOOK_DIR", tmp_path)
    import json
    (tmp_path / "vivek_bot_book.asx.json").write_text(json.dumps({"open": [], "closed": [
        dict(new, realized_r=0.5), dict(hand, realized_r=2.0), {"realized_r": 1.0},
        {"exit_reason": "stop", "realized_r": -1.0}]}), encoding="utf-8")
    live = run._evidence_by_market(tmp_path / "absent.json")["asx"]["live"]
    assert live == {"n": 2, "avg_r": -0.25}, live


def test_bot_vs_cells_no_longer_counts_tp():
    """The differing copy carried "tp"; no book row has ever been closed with
    it, and now nothing would count one as the rules."""
    bvc = _load_script("bot_vs_cells")
    assert not bvc.is_rules_exit({"exit_reason": "tp"})
    assert not hasattr(bvc, "MECHANICAL")


# -- published for the site --------------------------------------------------------

def test_bot_rules_json_publishes_the_list():
    p = run.bot_rules_payload()
    assert p["rules_exits"] == list(config.VIVEK_BOT_RULES_EXITS)
    assert "rules_exits" not in p["not_enforced"], "a classification, published beside the rules"


# -- config stays importable from a bare-Python script ---------------------------

@pytest.mark.parametrize("rel", ["scanner/__init__.py", "scanner/config.py"])
def test_config_imports_only_the_standard_library(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{rel}: relative import {node.module!r}"
            mods.add((node.module or "").split(".")[0])
    foreign = sorted(m for m in mods if m not in sys.stdlib_module_names and m != "__future__")
    assert not foreign, (
        f"{rel} imports {foreign}: scripts/decision_pack.py imports scanner.config with no "
        "pip install, so config must stay stdlib-only")

"""The bot path reads config DIRECTLY, so a renamed constant fails loudly
(REFINE200 #124).

`getattr(config, "VIVEK_BOT_MAX_STOP_PCT", 0)` is a second, silent copy of a
rule: rename or mistype the constant and the gate falls back to its default --
for the stop caps, the sector cap, the global position/notional ceilings and
the max hold that default is 0 = OFF -- without a sound. Several defaults also
encoded RETIRED rulings (A+ only, shorts allowed). Every name existed in
config, so no default was reachable; they only ever stood ready to disarm a
gate on the day someone renamed one.

Two static pins over the bot/run/guard path, plus one behavioural example:
  * no `getattr(<config module>, "<literal>", ...)` remains;
  * every `<config module>.NAME` attribute read names a real config constant,
    so a rename fails HERE, at test time, even on a branch no test executes.
"""

import ast
import pathlib

import pytest

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOT_PATH = sorted(p for p in (ROOT / "scanner" / "broker").glob("*.py")) + [
    ROOT / "scanner" / "vivek_journal.py"]


def _config_aliases(tree: ast.AST) -> set[str]:
    """Names the config MODULE is bound to in this file (any import form)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "config":
                    out.add(a.asname or "config")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "scanner.config" and a.asname:
                    out.add(a.asname)
    return out


def _trees():
    for p in BOT_PATH:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        yield p, tree, _config_aliases(tree)


def test_the_bot_path_has_config_aliases_to_check():
    """Guard against the scan going vacuous (a renamed alias, a moved file)."""
    seen = {p.name: al for p, _t, al in _trees()}
    for name in ("vivek_bot.py", "vivek_run.py", "vivek_guard.py",
                 "kill_switch.py", "vivek_journal.py"):
        assert seen.get(name), f"{name}: no config import found"


@pytest.mark.parametrize("path", BOT_PATH, ids=lambda p: p.name)
def test_no_fail_open_getattr_on_config(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    al = _config_aliases(tree)
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and node.args
                and isinstance(node.args[0], ast.Name) and node.args[0].id in al):
            name = node.args[1].value if (len(node.args) > 1 and isinstance(
                node.args[1], ast.Constant)) else "?"
            bad.append(f"line {node.lineno}: getattr({node.args[0].id}, {name!r}, ...)")
    assert bad == [], (f"{path.name}: read config directly (config.NAME) so a rename "
                       f"fails loudly instead of disarming the rule: {bad}")


@pytest.mark.parametrize("path", BOT_PATH, ids=lambda p: p.name)
def test_every_config_attribute_read_names_a_real_constant(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    al = _config_aliases(tree)
    missing = sorted({f"{node.value.id}.{node.attr} (line {node.lineno})"
                      for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute)
                      and isinstance(node.value, ast.Name) and node.value.id in al
                      and not hasattr(config, node.attr)})
    assert missing == [], f"{path.name} reads constants config does not define: {missing}"


def test_a_missing_constant_now_fails_loudly_instead_of_switching_a_gate_off(monkeypatch):
    """The behaviour the change buys, on the gate the finding named first: with
    the stop cap renamed away, evaluate_setup used to read 0 and take a 95%
    stop; it now raises."""
    from scanner.broker import vivek_bot as vb
    row = {"symbol": "X", "name": "X Ltd", "sector": "Industrials", "dir": "LONG",
           "grade": "A+", "grade_raw": "A+", "data_age_days": 0,
           "plans": {"1W": {"armed": True, "entry_trigger": "reclaim", "entry": 100.0,
                            "stop": 5.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0,
                            "rr": 3.0}}}
    assert vb.evaluate_setup(row)["code"] == "wide_stop"
    monkeypatch.delattr(config, "VIVEK_BOT_MAX_STOP_PCT")
    with pytest.raises(AttributeError):
        vb.evaluate_setup(row)

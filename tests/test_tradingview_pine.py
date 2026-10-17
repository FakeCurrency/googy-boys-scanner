"""The TradingView chart scripts in tradingview/ -- a syntax and plot-budget gate.

There is no Pine compiler in CI, and every one of these scripts was written
without one. The history in tradingview/README.md is the case for this file:
v5 of the Top script failed its first paste at 71 plot slots, v5.2 at 68 (the
limit is 64), and every fix was found by the owner pasting it into TradingView.
pynescript is a real Pine grammar (ANTLR), so a bracket, indentation or
continuation-line slip fails here instead of in the owner's Pine Editor. It
does not type-check, so the plot budget is estimated separately, on the high
side.

Chart-only scripts: nothing in the scanner reads them. This gate pins only what
can break a paste, the brand on the chart header, and the measured defaults of
5_0_Strategy.pine (see its header and the README for the measurements).
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TV = ROOT / "tradingview"
SCRIPTS = sorted(TV.glob("*.pine"))

pine = pytest.importorskip(
    "pynescript.ast",
    reason="pynescript is not installed (pip install -r requirements-dev.txt); "
           "the Pine scripts are UNCHECKED in this run")

# TradingView refuses a script with more than 64 plot slots.
PLOT_LIMIT = 64
# Calls that take plot slots, their base cost, and where their colour
# arguments sit (named, and positional index). A colour that is not a literal
# (#hex or color.<name>) costs one more slot -- the rule that broke v5 / v5.2.
PLOT_CALLS = {
    "plot": (1, {"color": 2}),
    "plotshape": (1, {"color": 4, "textcolor": 7}),
    "plotchar": (1, {"color": 4, "textcolor": 8}),
    "plotarrow": (1, {"colorup": 2, "colordown": 3}),
    "plotcandle": (4, {"color": 5, "wickcolor": 6, "bordercolor": 9}),
    "plotbar": (4, {"color": 5}),
    "bgcolor": (1, {"color": 0}),
    "barcolor": (1, {"color": 0}),
    "fill": (1, {"color": 2}),
    "hline": (1, {}),
    "alertcondition": (1, {}),
}
# ta.* calls whose history breaks when they do not run on every bar
CONDITIONAL_SCOPES = ("If", "Switch", "Conditional", "ForTo", "ForIn", "While")


def _name(node):
    return pine.unparse(node.func) if type(node).__name__ == "Call" else None


def _calls(tree):
    return [n for n in pine.walk(tree) if type(n).__name__ == "Call"]


def _is_literal_colour(value):
    kind = type(value).__name__
    if kind == "Constant":
        return True
    return kind == "Attribute" and pine.unparse(value).startswith("color.")


def _slots(call):
    base, colour_args = PLOT_CALLS[_name(call)]
    cost = base
    positional = [a for a in call.args if getattr(a, "name", None) is None]
    named = {a.name: a.value for a in call.args if getattr(a, "name", None)}
    for arg, index in colour_args.items():
        value = named.get(arg)
        if value is None and index < len(positional):
            value = positional[index].value
        if value is not None and not _is_literal_colour(value):
            cost += 1
    return cost


def _ta_calls_in_conditional_scope(node, scopes=()):
    """(call text, enclosing scope) for every ta.* call under an if / switch /
    ternary / loop, outside function bodies (a function's own body is judged
    where it is called, which this gate does not follow)."""
    kind = type(node).__name__
    if kind == "FunctionDef":
        return []
    found = []
    if kind == "Call" and _name(node).startswith("ta.") and scopes:
        found.append((pine.unparse(node), scopes[-1]))
    inner = scopes + (kind,) if kind in CONDITIONAL_SCOPES else scopes
    for child in pine.iter_child_nodes(node):
        found += _ta_calls_in_conditional_scope(child, inner)
    return found


@pytest.fixture(scope="module", params=SCRIPTS, ids=[p.name for p in SCRIPTS])
def script(request):
    src = request.param.read_text(encoding="utf-8")
    return request.param, src, pine.parse(src)


def test_the_folder_has_the_scripts_the_readme_describes():
    names = {p.name for p in SCRIPTS}
    assert {"Final_Top_Script.pine", "Final_Bottom_MACD.pine",
            "Final_RSI_Plus.pine", "5_0_Strategy.pine"} <= names
    readme = (TV / "README.md").read_text(encoding="utf-8")
    for name in names:
        assert name in readme, f"{name} is not documented in tradingview/README.md"


def test_every_script_is_pine_v6(script):
    path, src, _ = script
    assert src.splitlines()[0].strip() == "//@version=6", path.name


def test_every_script_carries_the_brand_on_the_chart_header(script):
    path, src, tree = script
    decl = [c for c in _calls(tree) if _name(c) in ("indicator", "strategy")]
    assert len(decl) == 1, f"{path.name}: expected one indicator()/strategy() call"
    args = decl[0].args
    title = pine.unparse(args[0].value).strip("'\"")
    short = next((pine.unparse(a.value).strip("'\"") for a in args
                  if getattr(a, "name", None) == "shorttitle"), title)
    for shown in (title, short):
        assert shown.startswith("Vivek 5.0"), f"{path.name}: header reads {shown!r}"
    assert not re.search(r"googy", src, re.I), f"{path.name} names the old brand"


def test_every_script_fits_the_plot_budget(script):
    path, _, tree = script
    slots = sum(_slots(c) for c in _calls(tree) if _name(c) in PLOT_CALLS)
    assert 0 < slots <= PLOT_LIMIT, f"{path.name}: about {slots} plot slots (limit {PLOT_LIMIT})"


def test_no_ta_call_runs_only_on_some_bars_in_the_new_script():
    tree = pine.parse((TV / "5_0_Strategy.pine").read_text(encoding="utf-8"))
    assert _ta_calls_in_conditional_scope(tree) == []


def test_the_gate_catches_what_it_claims_to():
    # a missing bracket, a conditional ta.* call and a series-coloured plot
    with pytest.raises(Exception):
        pine.parse('//@version=6\nindicator("Vivek 5.0 x")\na = ta.sma(close, 9\nplot(a)\n')
    bad = pine.parse('//@version=6\nindicator("Vivek 5.0 x")\n'
                     'a = close > open ? ta.sma(close, 9) : close\nplot(a)\n')
    assert [scope for _, scope in _ta_calls_in_conditional_scope(bad)] == ["Conditional"]
    two = pine.parse('//@version=6\nindicator("Vivek 5.0 x")\n'
                     'plot(close, "c", close > open ? color.green : color.red)\n'
                     'plot(close, "d", #ff0000)\n')
    assert [_slots(c) for c in _calls(two) if _name(c) == "plot"] == [2, 1]


def test_5_0_strategy_keeps_the_measured_defaults():
    # Fitted to the author's screenshot (README "5_0_Strategy"): the header
    # values pin SMA 12 / 26 / 200; EMA or 20/50/200 sets miss by 12-30 points.
    src = (TV / "5_0_Strategy.pine").read_text(encoding="utf-8")
    for name, value in (("fastLen", 12), ("midLen", 26), ("slowLen", 200)):
        assert re.search(rf"^{name}\s*=\s*input\.int\({value},", src, re.M), name
    for line in ("fast   = ta.sma(maSrc, fastLen)", "mid    = ta.sma(maSrc, midLen)",
                 "slow   = ta.sma(maSrc, slowLen)"):
        assert line in src

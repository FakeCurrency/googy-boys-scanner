"""Every config value the browser carries as a literal is pinned to config (REFINE200 #126).

The pages cannot import scanner/config.py, so a handful of rule numbers live
in the shipped JS as OFFLINE FALLBACKS: what journal.js prices a trade with,
what chart.js costs a leg at, what the stalled strip calls a time-stop, what a
row's exit ladder reads when its own plan carries no `scale`, what PhaseMap's
ILLIQUID copy names as the floor. Each is overridden by bot_rules.json or by
the row's own field when those arrive -- which is exactly why nobody sees a
fallback drift: it only renders when the fetch failed, the moment the reader
is least able to check it (TOP100 #34, the mirror that drifted for months).

tests/test_close_ceiling_parity.py already pins the cap and the notional;
tests/test_backtest_truth.py pins the FX rate. This file pins the rest. Each
literal is parsed out of the SHIPPED file (never re-typed here) and compared to
the config value it mirrors, so moving either side alone fails with both
numbers in the message.
"""

import json
import pathlib
import re

import pytest

from phasemap.config import CONFIG as PM_CONFIG
from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"


def _src(name):
    return (JS / name).read_text(encoding="utf-8")


def _js_value(literal):
    """A JS number / array / flat object literal -> the Python value.

    Object keys are bare identifiers in the source ({ asx: 2, default: 5 });
    quoting them is the only change needed for json to read the rest."""
    quoted = re.sub(r"([{,]\s*)([A-Za-z_$][\w$]*)\s*:", r'\1"\2":', literal)
    return json.loads(quoted)


def _decl(src, name, where):
    """The literal assigned to `name` by its one `const|let NAME = ...;` line."""
    found = re.findall(rf"(?:const|let|var)\s+{name}\s*=\s*([^;]+);", src)
    assert len(found) == 1, f"{where}: expected one declaration of {name}, got {found}"
    return _js_value(found[0].strip())


def _num_eq(js, py):
    """Numbers compare by value (JS 2 == config 2.0); dicts/lists recurse."""
    if isinstance(py, dict):
        assert isinstance(js, dict) and set(js) == set(py), (js, py)
        return all(_num_eq(js[k], py[k]) for k in py)
    if isinstance(py, (list, tuple)):
        assert isinstance(js, list) and len(js) == len(py), (js, py)
        return all(_num_eq(a, b) for a, b in zip(js, py))
    return float(js) == float(py)


# -- journal.js: the fallback rulebook ------------------------------------------

@pytest.mark.parametrize("name, value", [
    ("EQUITY", lambda: config.VIVEK_BOT_ACCOUNT_EQUITY),
    ("RISK_PCT", lambda: config.VIVEK_BOT_RISK_PCT),
    ("LEVERAGE", lambda: config.VIVEK_BOT_LEVERAGE),
    ("SCALE", lambda: {"long": config.VIVEK_TP_SCALE_LONG,
                       "short": config.VIVEK_TP_SCALE_SHORT}),
    ("COMMISSION_BPS", lambda: config.VIVEK_COMMISSION_BPS),
    ("SLIPPAGE_BPS", lambda: config.VIVEK_SLIPPAGE_BPS),
])
def test_journal_fallbacks_match_config(name, value):
    js = _decl(_src("journal.js"), name, "journal.js")
    py = value()
    assert _num_eq(js, py), (
        f"journal.js {name} = {js} but scanner/config.py says {py} -- the journal "
        "prices every trade with this whenever bot_rules.json fails to load")


# -- chart.js: the per-leg cost model -------------------------------------------

@pytest.mark.parametrize("name, value", [
    ("COMMISSION_BPS", lambda: config.VIVEK_COMMISSION_BPS),
    ("SLIPPAGE_BPS", lambda: config.VIVEK_SLIPPAGE_BPS),
])
def test_chart_costs_match_config(name, value):
    js = _decl(_src("chart.js"), name, "chart.js")
    assert _num_eq(js, value()), (
        f"chart.js {name} = {js} but scanner/config.py says {value()} -- the chart's "
        "cost of a leg would disagree with the journal's and the backtest's")


# -- the default exit ladder a row reads when it carries no `scale` -------------

DEFAULT_SCALE = re.compile(r"\.scale\s*\|\|\s*(\[[0-9.,\s]+\])\)")


@pytest.mark.parametrize("name", ["app.js", "chart.js"])
def test_the_default_exit_ladder_is_the_long_scale(name):
    found = DEFAULT_SCALE.findall(_src(name))
    assert found, f"{name}: no `... .scale || [..])` default ladder found -- re-point this test"
    for lit in found:
        assert _num_eq(_js_value(lit), config.VIVEK_TP_SCALE_LONG), (
            f"{name} defaults a row's exit ladder to {lit} but VIVEK_TP_SCALE_LONG is "
            f"{config.VIVEK_TP_SCALE_LONG} -- a row without its own scale would show "
            "booking percentages the bot does not use")


# -- stalled.js: the time-stop the strip frames its decision around -------------

def test_stalled_time_stop_fallback_matches_config():
    src = _src("stalled.js")
    found = re.findall(r"rules\.max_hold_days\s*:\s*(\d+)\s*;", src)
    assert len(found) == 1, f"stalled.js: expected one max_hold_days fallback, got {found}"
    assert int(found[0]) == int(config.VIVEK_BOT_MAX_HOLD_DAYS), (
        f"stalled.js falls back to a {found[0]}d time-stop but VIVEK_BOT_MAX_HOLD_DAYS is "
        f"{config.VIVEK_BOT_MAX_HOLD_DAYS}")


# -- PhaseMap's ILLIQUID copy names the floor the engine tags against -----------

@pytest.mark.parametrize("path", [
    "public/js/phasemap-shared.js",
    "public/phasemap.html",
])
def test_the_illiquid_floor_in_the_copy_is_the_engines(path):
    text = (ROOT / path).read_text(encoding="utf-8")
    floors = re.findall(r"\$(\d+)k/day", text)
    assert floors, f"{path}: no '$Nk/day' floor in the ILLIQUID copy -- re-point this test"
    want = PM_CONFIG.turnover_floor / 1000
    assert all(float(f) == want for f in floors), (
        f"{path} tells the reader the ILLIQUID floor is ${floors}k/day but "
        f"phasemap/config.py turnover_floor is {PM_CONFIG.turnover_floor:,.0f}")

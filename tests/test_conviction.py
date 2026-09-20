"""HIGH CONVICTION — one rule, five readers, zero drift (scanner/conviction.py).

Owner ruling 2026-09-20 off the 600-name long-only replay: HIGH CONVICTION =
grade A/A+ with an ARMED plan in one of four backtest-edge cells (1W reclaim,
1W break, 3D reclaim, 1D break); the "strong structure" branch is DROPPED; the
deck shows one target mark per cell a name fires on.

The rule used to be re-typed in six places (app.js, chart.js, morning_plays,
edge_rosters, vivek_backtest, and a comment in config.py). It now lives once in
Python and once as a JSON literal in each of the two browser files, and these
tests parse the literals OUT OF THE SHIPPED FILES and compare them to the
Python table — so a change in any one place fails here instead of quietly
letting the digest, the badge, the chart chip, the roster baseline and the
backtest cohort disagree about what the owner is trading.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from scanner import conviction as c

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUB = ROOT / "public" / "js"


def _plan(trigger="reclaim", armed=True, **kw):
    return dict({"armed": armed, "entry_trigger": trigger}, **kw)


def _row(grade="A+", **plans):
    return {"grade": grade, "plans": plans}


# ── the table itself ─────────────────────────────────────────────────────────

def test_the_four_cells_are_exactly_the_owners_ruling():
    assert c.HC_CELLS == {"1W": ("reclaim", "break"), "3D": ("reclaim",), "1D": ("break",)}
    assert c.cell_names() == ["1W reclaim", "1W break", "3D reclaim", "1D break"]
    assert c.HC_GRADES == ("A+", "A")
    assert "4H" not in c.HC_CELLS, "the 4H plan is display-only and must not reach the list"
    assert "retest" not in {et for ets in c.HC_CELLS.values() for et in ets}, \
        "retest measured worst in every timeframe and is in no cell"


# ── a scan row ───────────────────────────────────────────────────────────────

def test_each_cell_fires_alone_and_nothing_else_does():
    assert c.conviction_cells(_row(**{"1W": _plan("reclaim")})) == ["1W reclaim"]
    assert c.conviction_cells(_row(**{"1W": _plan("break")})) == ["1W break"]
    assert c.conviction_cells(_row(**{"3D": _plan("reclaim")})) == ["3D reclaim"]
    assert c.conviction_cells(_row(**{"1D": _plan("break")})) == ["1D break"]
    # the cells that are NOT in the rule
    for tf, et in (("1W", "retest"), ("3D", "break"), ("3D", "retest"),
                   ("1D", "reclaim"), ("1D", "retest"), ("4H", "reclaim"), ("4H", "break")):
        assert c.conviction_cells(_row(**{tf: _plan(et)})) == [], (tf, et)


def test_the_marks_stack_one_per_cell_and_cap_at_three():
    r = _row(**{"1W": _plan("reclaim"), "3D": _plan("reclaim"), "1D": _plan("break"),
                "4H": _plan("reclaim")})
    assert c.conviction_cells(r) == ["1W reclaim", "3D reclaim", "1D break"]
    assert c.conviction_count(r) == 3 == c.MAX_MARKS
    two = _row(**{"1W": _plan("break"), "3D": _plan("reclaim"), "1D": _plan("retest")})
    assert c.conviction_count(two) == 2
    assert c.conviction_count(_row(**{"1D": _plan("break")})) == 1
    assert c.conviction_count(_row()) == 0


def test_grade_A_or_A_plus_is_required_and_the_structure_branch_is_gone():
    strong = _plan("reclaim", structural_tps=3)
    assert c.is_high_conviction(_row("A+", **{"1W": strong}))
    assert c.is_high_conviction(_row("A", **{"1W": strong}))
    assert not c.is_high_conviction(_row("B+", **{"1W": strong})), \
        "a B+ with strong structure used to qualify (the OLD rule); it measured -0.07R and was dropped"
    assert not c.is_high_conviction(_row("WATCH", **{"1W": strong}))


def test_the_plan_must_be_armed():
    assert not c.is_high_conviction(_row(**{"1W": _plan("reclaim", armed=False)}))
    assert not c.is_high_conviction(_row(**{"1W": _plan("reclaim", armed=None)}))


def test_junk_never_raises_and_never_qualifies():
    for bad in (None, {}, [], {"grade": "A+"}, {"grade": "A+", "plans": None},
                {"grade": "A+", "plans": []}, {"grade": "A+", "plans": {"1W": None}},
                {"grade": "A+", "plans": {"1W": "reclaim"}},
                {"grade": "A+", "plans": {"1W": {"armed": True}}}):
        assert c.conviction_cells(bad) == [], bad
        assert c.conviction_count(bad) == 0
        assert c.is_high_conviction(bad) is False


def test_a_lite_plan_carrying_only_the_summary_fields_is_enough():
    """The deck reads the SLIM payload; the rule must never need a detail field."""
    from scanner import config
    lite = {k: v for k, v in {"armed": True, "entry_trigger": "reclaim",
                              "structural_tps": 0, "level_tf": "weekly",
                              "direction": "long"}.items()
            if k in config.VIVEK_SUMMARY_PLAN_FIELDS}
    assert set(lite) <= set(config.VIVEK_SUMMARY_PLAN_FIELDS)
    assert c.is_high_conviction({"grade": "A", "plans": {"3D": lite}})


# ── a backtest trade (one timeframe = at most one cell) ──────────────────────

def test_a_trade_sits_in_at_most_one_cell():
    t = lambda tf, et, g="A+": {"timeframe": tf, "entry_type": et, "grade": g}
    assert c.trade_cell(t("1W", "reclaim")) == "1W reclaim"
    assert c.trade_cell(t("1W", "break", "A")) == "1W break"
    assert c.trade_cell(t("3D", "reclaim")) == "3D reclaim"
    assert c.trade_cell(t("1D", "break")) == "1D break"
    for tf, et in (("1W", "retest"), ("3D", "break"), ("1D", "reclaim"), ("4H", "reclaim")):
        assert c.trade_cell(t(tf, et)) is None
    assert c.trade_cell(t("1W", "reclaim", "B+")) is None
    for bad in (None, {}, {"timeframe": None}, {"timeframe": "1W", "entry_type": None,
                                                  "grade": "A+"}):
        assert c.trade_is_high_conviction(bad) is False


# ── PARITY with the two browser copies ───────────────────────────────────────

def _js_cells(file: str, fn: str) -> dict:
    src = (PUB / file).read_text(encoding="utf-8")
    i = src.index(f"function {fn}(")
    body = src[i:src.index("\n  }", i)]
    m = re.search(r"const HC_CELLS = (\{.*?\});", body)
    assert m, f"{file}: {fn} no longer carries the HC_CELLS literal"
    return json.loads(m.group(1)), body


@pytest.mark.parametrize("file,fn", [("app.js", "convictionCells"),
                                     ("chart.js", "convictionCells")])
def test_the_browser_copy_carries_the_same_table(file, fn):
    cells, body = _js_cells(file, fn)
    assert cells == {tf: list(ets) for tf, ets in c.HC_CELLS.items()}, \
        f"{file} disagrees with scanner/conviction.py about what HIGH CONVICTION is"
    assert '"A+"' in body and '"A"' in body, "the grade gate moved"
    assert "p.armed" in body, "the armed gate moved"
    assert "structural_tps" not in body, "the dropped structure branch is back"
    assert '"4H"' not in body


def test_app_js_still_defines_isHighConviction_over_the_cells():
    src = (PUB / "app.js").read_text(encoding="utf-8")
    i = src.index("function isHighConviction(")
    assert "convictionCells(r).length > 0" in src[i:i + 200]


def test_the_badge_stacks_one_mark_per_cell():
    src = (PUB / "app.js").read_text(encoding="utf-8")
    i = src.index("function hiconvBadge(")
    body = src[i:src.index("\n  }", i)]
    assert '"\U0001F3AF".repeat(Math.min(cells.length, 3))' in body
    j = src.index("function vkBadges(")
    assert "hiconvBadge(r)" in src[j:j + 2500], "vkBadges stopped using the stacking badge"
    chart = (PUB / "chart.js").read_text(encoding="utf-8")
    assert '"\U0001F3AF".repeat(Math.min(cells.length, 3))' in chart, "chart chip does not stack"


# ── the Python readers IMPORT the rule rather than re-typing it ──────────────

@pytest.mark.parametrize("path", ["scripts/morning_plays.py", "scripts/edge_rosters.py",
                                  "scanner/vivek_backtest.py"])
def test_every_python_reader_imports_the_rule(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert re.search(r"^from (\.|scanner) import .*\bconviction\b", src, re.M), \
        f"{path} no longer imports scanner.conviction"
    assert 'entry_trigger") == "reclaim"' not in src and "entry_trigger !== " not in src, \
        f"{path} re-typed the cell test instead of importing it"


# ── the FENCE: display only, the bot does not read it ────────────────────────

def test_nothing_under_broker_imports_the_conviction_rule():
    """The bot's eligibility is its OWN ruleset (VIVEK_BOT_GRADES /
    VIVEK_BOT_ENTRY_CELLS in config). It was aligned to these cells on the
    owner's word (2026-09-21) and tests/test_bot_alignment.py pins the two
    tables equal — but the broker never IMPORTS the display module, so a
    display-side edit can never silently change what gets traded."""
    hits = [p.name for p in (ROOT / "scanner" / "broker").glob("*.py")
            if re.search(r"^\s*(from|import)\s+.*\bconviction\b", p.read_text(encoding="utf-8"), re.M)]
    assert hits == [], f"scanner/broker now imports the display rule: {hits}"

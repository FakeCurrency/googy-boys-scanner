"""HIGH CONVICTION — the one definition every Python surface imports.

Owner ruling, 2026-09-20, off the 600-name-per-market long-only replay
(8,239 trades): the old rule ("a 1W reclaim that is A/A+ or has >= 2
structural targets") was ONE cell of the backtest. The widened rule is the
four cells that carried a real edge, and it drops the structure branch
(structural_tps >= 2 measured -0.067R against +0.207R without it):

    1W reclaim   +0.299R  n=691    1W break   +0.161R  n=122
    3D reclaim   +0.196R  n=1309   1D break   +0.091R  n=281
    (the tier together: n=2403, +0.212R, PF 1.47)

A row is HIGH CONVICTION when its DISPLAYED grade is A or A+ and at least one
of those cells is ARMED on it. It can fire on up to three cells at once (a
1W plan has one trigger, so 1W reclaim and 1W break never stack), and the
deck shows one mark per cell: "If the ticker fires on all 2 have 2 symbols,
if it fires on all 3 have 3, if it fires on 1 just have one symbol."

PARITY IS THE WHOLE POINT. public/js/app.js `convictionCells` and
public/js/chart.js carry the same cell table as a JSON literal;
tests/test_conviction.py parses those literals out of the shipped files and
asserts they equal HC_CELLS, so the badge, the chart chip, the Discord digest,
the roster baseline and the backtest cohort cannot drift apart silently.

THE BOT AGREES, BUT DOES NOT IMPORT THIS. On 2026-09-21 the owner aligned the
paper bot's entries to these cells (config.VIVEK_BOT_GRADES /
VIVEK_BOT_ENTRY_CELLS; shorts declined on the numbers). The bot keeps its OWN
copy of the table in config so a display-side edit can never silently change
what gets traded: tests/test_bot_alignment.py pins the two tables equal, and
tests/test_conviction.py pins that nothing under scanner/broker/ imports this
module.
"""
from __future__ import annotations

# timeframe -> the entry triggers that count in that timeframe. Order matters
# only for the tooltip text (1W first, the strongest cell).
HC_CELLS: dict[str, tuple[str, ...]] = {
    "1W": ("reclaim", "break"),
    "3D": ("reclaim",),
    "1D": ("break",),
}
HC_GRADES: tuple[str, ...] = ("A+", "A")
MAX_MARKS = 3                                # one mark per timeframe, at most
RULE_TEXT = "1W reclaim/break, 3D reclaim or 1D break - armed, grade A/A+"


def conviction_cells(row: dict) -> list[str]:
    """The cells a scan ROW fires on, e.g. ["1W reclaim", "3D reclaim"].
    Empty when the grade is not A/A+ or no listed cell is armed. Never raises
    on a malformed row - an unreadable plan simply does not count."""
    if not isinstance(row, dict) or row.get("grade") not in HC_GRADES:
        return []
    plans = row.get("plans")
    if not isinstance(plans, dict):
        return []
    out = []
    for tf, triggers in HC_CELLS.items():
        p = plans.get(tf)
        if isinstance(p, dict) and p.get("armed") and p.get("entry_trigger") in triggers:
            out.append(f"{tf} {p.get('entry_trigger')}")
    return out


def conviction_count(row: dict) -> int:
    return min(len(conviction_cells(row)), MAX_MARKS)


def is_high_conviction(row: dict) -> bool:
    return bool(conviction_cells(row))


def trade_cell(tr: dict) -> str | None:
    """A backtest TRADE is one timeframe's plan, so it sits in at most one
    cell. Returns "1W reclaim" etc., or None when it is not a conviction cell
    (wrong grade, wrong trigger, or a timeframe the rule does not read)."""
    if not isinstance(tr, dict) or tr.get("grade") not in HC_GRADES:
        return None
    tf, et = tr.get("timeframe"), tr.get("entry_type")
    if tf in HC_CELLS and et in HC_CELLS[tf]:
        return f"{tf} {et}"
    return None


def trade_is_high_conviction(tr: dict) -> bool:
    return trade_cell(tr) is not None


def cell_names() -> list[str]:
    """Every cell in table order: ["1W reclaim", "1W break", "3D reclaim", "1D break"]."""
    return [f"{tf} {et}" for tf, ets in HC_CELLS.items() for et in ets]

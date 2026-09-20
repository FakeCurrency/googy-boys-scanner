"""The paper bot trades what the deck calls HIGH CONVICTION (owner, 2026-09-21).

Owner: "The paper bot should only take the highest R and conviction plays so I
feel like it needs to take what we're changing the high conviction list [to]."
Shorts were asked for in the same breath and DECLINED on the numbers (every
short cell negative; the four cells short: n=793, -0.360R, PF 0.43) — "Yeah
lets not do shorts."

What changed (config.py): VIVEK_BOT_GRADES ("A+", "A") replaces the A+-only
gate; VIVEK_BOT_ENTRY_CELLS (the deck's four cells) replaces the
prefer-1W + skip-retest pair; the cycle tag moved w3-1 -> hc4-1. What did NOT
change: long-only, the weekly/3d LEVEL gate, every size / R:R / liquidity /
sector / loss guard.

These pins hold the two tables equal WITHOUT the bot importing the display
module (tests/test_conviction.py keeps that fence).
"""
from scanner import config, conviction
from scanner.broker import vivek_bot


def test_the_bot_cells_are_the_deck_cells():
    assert {tf: tuple(ets) for tf, ets in config.VIVEK_BOT_ENTRY_CELLS.items()} == conviction.HC_CELLS
    assert tuple(config.VIVEK_BOT_GRADES) == conviction.HC_GRADES


def test_the_walk_order_is_weekly_first():
    assert list(config.VIVEK_BOT_ENTRY_CELLS) == ["1W", "3D", "1D"]


def test_shorts_stay_off_and_the_level_gate_stands():
    assert config.VIVEK_BOT_ALLOW_SHORTS is False
    assert tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW) == ("weekly", "3d")


def test_the_retired_rule_names_are_gone_so_nothing_reads_a_stale_gate():
    for name in ("VIVEK_BOT_MIN_GRADE", "VIVEK_BOT_SKIP_ENTRY_TYPES", "VIVEK_BOT_PREFER_TF"):
        assert not hasattr(config, name), f"{name} is back — two rules for one decision"


def test_bot_rules_json_publishes_the_new_keys_and_not_the_old():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "scanner" / "run.py").read_text(encoding="utf-8")
    i = src.index("rules = {"); block = src[i:src.index("bot_rules.json", i)]
    for k in ('"grades"', '"entry_cells"', '"cycle_tag"'):
        assert k in block, f"bot_rules.json no longer publishes {k}"
    for k in ('"min_grade"', '"skip_entry_types"', '"prefer_tf"'):
        assert k not in block, f"bot_rules.json still publishes the retired {k}"


def test_a_row_the_deck_calls_high_conviction_is_takeable_by_the_bot():
    """Same row, both readers. The deck reads `grade`, the bot reads
    `grade_raw`; with both set the two must agree on every cell."""
    plan = {"armed": True, "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0,
            "tp3": 120.0, "rr": 3.0, "scale": config.VIVEK_TP_SCALE_LONG}
    for tf, ets in conviction.HC_CELLS.items():
        for et in ets:
            for g in ("A+", "A"):
                row = {"symbol": "X", "dir": "LONG", "grade": g, "grade_raw": g,
                       "entry_types": [et], "plans": {tf: dict(plan, entry_trigger=et)}}
                assert conviction.is_high_conviction(row)
                d = vivek_bot.evaluate_setup(row)
                assert d["take"] is True and d["timeframe"] == tf and d["entry_type"] == et, (tf, et, g, d)
    # and the non-cells the deck ignores, the bot ignores
    for tf, et in (("1W", "retest"), ("3D", "break"), ("3D", "retest"), ("1D", "reclaim"), ("1D", "retest")):
        row = {"symbol": "X", "dir": "LONG", "grade": "A+", "grade_raw": "A+",
               "entry_types": [et], "plans": {tf: dict(plan, entry_trigger=et)}}
        assert not conviction.is_high_conviction(row)
        assert vivek_bot.evaluate_setup(row)["code"] == "no_cell_plan"

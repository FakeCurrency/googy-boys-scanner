"""Narration renderer — fills template slots from computed record fields only.

render(record) -> str. The optional `stats` argument is reserved for the M4
backtest harness; until it supplies real numbers the {stats} slot renders
empty (guardrail: no performance claims before M4).
"""

from phasemap.config import CONFIG
from phasemap.narrate.templates import (DISCLAIMER, NEXT_EVIDENCE,
                                        SOURCE_NAMES, TEMPLATES)


def fmt_price(x: float) -> str:
    if x is None:
        return "?"
    if x < 0.10:
        return f"{x:.4f}"
    if x < 2.00:
        return f"{x:.3f}"
    return f"{x:.2f}"


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}"


def _sources_text(zone: dict) -> str:
    names = [SOURCE_NAMES.get(s, s.replace("_", " ")) for s in zone.get("sources", [])]
    if not names:
        return "liquidity objective"
    return " + ".join(names)


def _zone_by_id(record: dict, zid: str) -> dict:
    for z in record.get("zones", []):
        if z["id"] == zid:
            return z
    return None


def _stats_text(stats: dict) -> str:
    """M4 wires this. Until then it must stay empty — never hardcode a claim."""
    if not stats:
        return ""
    return (" Historically this pattern reached its first target zone within "
            f"{stats['window_sessions']} sessions {stats['hit_rate_pct']}% of the "
            f"time on the {stats['market']}.")


def render(record: dict, stats: dict = None) -> str:
    state = record["state"]
    direction = record["direction"]
    template = TEMPLATES[(state, direction)]
    m = record.get("metrics", {})

    slots = {
        "ticker": record["ticker"],
        "stats": _stats_text(stats),
        "tr_mult": f"{CONFIG.displacement_tr_mult:g}",
        "sweep_date": m.get("sweep_date", "?"),
        "displacement_date": m.get("displacement_date", "?"),
        "bars_in_box": m.get("bars_in_box", "?"),
        "bars_remaining": m.get("bars_remaining", "?"),
    }
    if "box_height_pct" in m:
        slots["box_height_pct"] = fmt_pct(m["box_height_pct"])
    if "cluster_low" in m:
        slots["cluster_low"] = fmt_price(m["cluster_low"])
        slots["cluster_high"] = fmt_price(m["cluster_high"])

    demand = _zone_by_id(record, "demand") or _zone_by_id(record, "supply")
    if demand:
        slots["demand_low"] = fmt_price(demand["low"])
        slots["demand_high"] = fmt_price(demand["high"])

    inv_hard = _zone_by_id(record, "inv_hard")
    if inv_hard:
        slots["inv_hard_low"] = fmt_price(inv_hard["low"])
        slots["inv_hard_high"] = fmt_price(inv_hard["high"])
        slots["inv_hard_floor"] = fmt_price(inv_hard["low"])
        slots["inv_hard_ceiling"] = fmt_price(inv_hard["high"])

    inv_soft = _zone_by_id(record, "inv_soft")
    if inv_soft:
        slots["inv_soft_low"] = fmt_price(inv_soft["low"])
        slots["inv_soft_high"] = fmt_price(inv_soft["high"])

    targets = [z for z in record.get("zones", []) if z["type"] == "TARGET"]
    if targets:
        t1 = targets[0]
        slots["t1_low"] = fmt_price(t1["low"])
        slots["t1_high"] = fmt_price(t1["high"])
        slots["t1_sources"] = _sources_text(t1)
        slots["t_final_low"] = fmt_price(targets[-1]["low"])
        slots["t_final_high"] = fmt_price(targets[-1]["high"])
        if len(targets) > 1:
            t2 = targets[1]
            slots["t2_clause"] = (
                f"; beyond that, {fmt_price(t2['low'])}–{fmt_price(t2['high'])} "
                f"({_sources_text(t2)})")
        else:
            slots["t2_clause"] = ""

    text = template.format(**slots)
    return f"{text} {DISCLAIMER}"


def render_next(record: dict) -> str:
    """The 'what completes the picture' line — the evidence the state machine
    is waiting for. Computed slots only, like everything else."""
    template = NEXT_EVIDENCE[(record["state"], record["direction"])]
    m = record.get("metrics", {})
    slots = {
        "window": CONFIG.displacement_window_bars,
        "tr_mult": f"{CONFIG.displacement_tr_mult:g}",
        "bars_remaining": m.get("bars_remaining", "?"),
    }
    if "cluster_low" in m:
        slots["cluster_low"] = fmt_price(m["cluster_low"])
        slots["cluster_high"] = fmt_price(m["cluster_high"])
    inv_soft = _zone_by_id(record, "inv_soft")
    if inv_soft:
        slots["inv_soft_low"] = fmt_price(inv_soft["low"])
        slots["inv_soft_high"] = fmt_price(inv_soft["high"])
    targets = [z for z in record.get("zones", []) if z["type"] == "TARGET"]
    live = next((z for z in targets if z["status"] != "CONSUMED"),
                targets[-1] if targets else None)
    if live:
        slots["next_target"] = (f"the {fmt_price(live['low'])}–"
                                f"{fmt_price(live['high'])} zone "
                                f"({live['id'].upper()})")
    return template.format(**slots)

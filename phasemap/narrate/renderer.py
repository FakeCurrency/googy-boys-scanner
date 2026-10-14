"""Narration renderer — fills template slots from computed record fields only.

render(record) -> str. The optional `stats` argument is reserved for the M4
backtest harness; until it supplies real numbers the {stats} slot renders
empty (guardrail: no performance claims before M4).
"""

import math

from phasemap.config import CONFIG
from phasemap.narrate.templates import (DISCLAIMER, NEXT_EVIDENCE,
                                        SOURCE_NAMES, TEMPLATES)


def fmt_price(x: float) -> str:
    if x is None:
        return "?"
    if x < 0.10:
        # >= 3 significant figures below a cent (REFINE200 #132): a fixed
        # 4 dp read FLOKI's equal highs as "0.0000-0.0000" and printed RSR's
        # 0.00158-0.00162 band as the single price "0.0016-0.0016"
        mag = math.floor(math.log10(abs(x))) if x else 0
        return f"{x:.{max(4, 2 - mag)}f}"
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


# The stats artefact stores the market code upper-cased ("CRYPTO"), which
# rendered "on the CRYPTO" (REFINE200 #195).
MARKET_PHRASE = {"ASX": "on the ASX", "NASDAQ": "on NASDAQ", "CRYPTO": "in crypto"}


def sessions(n) -> str:
    """'1 session' / '3 sessions' — the live cards said '1 sessions'."""
    if not isinstance(n, int):
        return f"{n} sessions"
    return f"{n} session" if n == 1 else f"{n} sessions"


def _stats_text(stats: dict) -> str:
    """M4 wires this. Until then it must stay empty — never hardcode a claim."""
    if not stats:
        return ""
    market = str(stats.get("market", ""))
    where = MARKET_PHRASE.get(market.upper(), f"on {market}")
    return (" Historically this pattern reached its first target zone within "
            f"{stats['window_sessions']} sessions {stats['hit_rate_pct']}% of the "
            f"time {where}.")


def _names(ids: list) -> str:
    ids = [i.upper() for i in ids]
    return ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def _draw_slots(targets: list) -> dict:
    """The draw clause names the first UNCONSUMED target (REFINE200 #195):
    78 of 193 live RUNNING/DISPLACED cards called an already-CONSUMED T1 the
    'First draw' while their own WANTED NEXT line pointed at T2/T3."""
    consumed = []
    for z in targets:
        if z["status"] != "CONSUMED":
            break
        consumed.append(z["id"])
    live = [z for z in targets if z["status"] != "CONSUMED"]
    if not live:
        return {"draw_clause": ("Every mapped target zone is already consumed"
                                if targets else "No target zone is mapped beyond price"),
                "t2_clause": ""}
    d = live[0]
    zone = f"the {fmt_price(d['low'])}–{fmt_price(d['high'])} zone ({_sources_text(d)})"
    if consumed:
        verb = "is" if len(consumed) == 1 else "are"
        clause = f"{_names(consumed)} {verb} already consumed; the next draw is {zone}"
    else:
        clause = f"First draw is {zone}"
    t2 = ""
    if len(live) > 1:
        n = live[1]
        t2 = (f"; beyond that, {fmt_price(n['low'])}–{fmt_price(n['high'])} "
              f"({_sources_text(n)})")
    return {"draw_clause": clause, "t2_clause": t2}


def render(record: dict, stats: dict = None) -> str:
    state = record["state"]
    direction = record["direction"]
    template = TEMPLATES[(state, direction)]
    m = record.get("metrics", {})

    targets = [z for z in record.get("zones", []) if z["type"] == "TARGET"]
    # The {stats} claim is about reaching the FIRST target — once T1 is
    # consumed it describes something that already happened (REFINE200 #195).
    t1_open = not (targets and targets[0]["status"] == "CONSUMED")
    slots = {
        "ticker": record["ticker"],
        "stats": _stats_text(stats) if t1_open else "",
        "tr_mult": f"{CONFIG.displacement_tr_mult:g}",
        "sweep_date": m.get("sweep_date", "?"),
        "displacement_date": m.get("displacement_date", "?"),
        "bars_in_box": m.get("bars_in_box", "?"),
        "bars_in_box_sessions": sessions(m.get("bars_in_box", "?")),
        "bars_remaining": m.get("bars_remaining", "?"),
        "bars_remaining_sessions": sessions(m.get("bars_remaining", "?")),
        "stalled_expiry": CONFIG.stalled_expiry_bars,
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

    slots.update(_draw_slots(targets))
    if targets:
        slots["t_final_low"] = fmt_price(targets[-1]["low"])
        slots["t_final_high"] = fmt_price(targets[-1]["high"])

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
        "bars_remaining_sessions": sessions(m.get("bars_remaining", "?")),
        "stalled_expiry": CONFIG.stalled_expiry_bars,
    }
    inv_hard = _zone_by_id(record, "inv_hard")
    if inv_hard:
        slots["inv_hard_floor"] = fmt_price(inv_hard["low"])
        slots["inv_hard_ceiling"] = fmt_price(inv_hard["high"])
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

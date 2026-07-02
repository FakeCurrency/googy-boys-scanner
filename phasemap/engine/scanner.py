"""Scan orchestration: Module 0 (universe & liquidity guard), runs both
directions per ticker, assigns tiers, assembles output records.
"""

import math

import pandas as pd

from phasemap.config import CONFIG
from phasemap.engine.indicators import compute_indicators
from phasemap.engine.setup_engine import SetupEngine

TIER_ORDER = {"A+": 0, "A": 1, "Watch": 2, None: 3}
STATE_ORDER = {"RUNNING": 0, "DISPLACED": 1, "SWEPT": 2, "TRAP_SET": 3,
               "STALLED": 4, "COMPLETE": 5, "DEAD": 6}


def module0_tags(ind) -> list:
    """Liquidity + halt tags. ILLIQUID is a warning, never a filter."""
    tags = []
    t = ind.turnover20[-1]
    if math.isnan(t) or t < CONFIG.turnover_floor:
        tags.append("ILLIQUID")
    recent = ind.dates[-CONFIG.halt_lookback_bars:]
    for a, b in zip(recent, recent[1:]):
        if (b - a).days > CONFIG.halt_gap_days:
            tags.append("HALT_RISK")
            break
    return tags


def _tier(eng: SetupEngine) -> str:
    """Spec Section 5 tier table + FAST_FLIP downgrade rule."""
    smt_confirmed = False   # Module 6 is Phase 2 — never set in v1
    if eng.state in ("DISPLACED", "RUNNING") and not eng.momentum_touched:
        tier = "A+" if (eng.anchor_context or smt_confirmed) else "A"
        if eng.flip_tag == "SLOW_FLIP":
            tier = {"A+": "A", "A": "Watch"}[tier]
        return tier
    if eng.state == "SWEPT":
        return "Watch"
    if eng.state == "TRAP_SET" and eng.trap_cluster:
        return "Watch"
    return None


def _tags(eng: SetupEngine, base_tags: list) -> list:
    tags = []
    smt_confirmed = False   # Module 6 is Phase 2 — never set in v1
    if eng.anchor_context and smt_confirmed:
        tags.append("TEXTBOOK")   # both confluences present
    if eng.flip_tag == "FAST_FLIP":
        tags.append("FAST_FLIP")
    if eng.anchor_context:
        tags.append("ANCHOR_CONTEXT")
    if eng.anchor_caution:
        tags.append("ANCHOR_CAUTION")
    tags.extend(base_tags)
    return tags


def _zones_list(eng: SetupEngine) -> list:
    zones = []
    for z in (eng.demand, eng.inv_hard, eng.inv_soft, eng.entry):
        if z is not None:
            zones.append(z.to_dict())
    for z in eng.targets:
        zones.append(z.to_dict())
    return zones


def _metrics(eng: SetupEngine, ind, i: int) -> dict:
    nd = CONFIG.price_decimals
    c = float(ind.close[i])
    yo = ind.yearly_open[i]
    m = {
        "retrace_pct": None,
        "dist_to_yearly_open_pct": None if math.isnan(yo) else round((c - yo) / yo, nd),
        "avg_turnover_20d": None if math.isnan(ind.turnover20[i]) else int(round(ind.turnover20[i])),
        "close": round(c, nd),
    }
    r = eng.retrace_pct(i)
    if not math.isnan(r):
        m["retrace_pct"] = round(r, nd)
    if eng.sweep_index >= 0:
        m["sweep_date"] = ind.dates[eng.sweep_index].isoformat()
        m["sweep_depth_pct"] = round(eng.sweep_depth_pct, nd)
        if eng.state == "SWEPT":
            # sessions left for a displacement candle to print (window incl. sweep bar)
            m["bars_remaining"] = max(
                0, eng.sweep_index + CONFIG.displacement_window_bars - 1 - i)
    if eng.displacement_index >= 0:
        m["displacement_date"] = ind.dates[eng.displacement_index].isoformat()
    if eng.state == "TRAP_SET":
        m["bars_in_box"] = eng.bars_in_box
        m["box_low"] = round(eng.box_low, nd)
        m["box_high"] = round(eng.box_high, nd)
        m["box_height_pct"] = round((eng.box_high - eng.box_low) / eng.box_low, nd)
        if eng.trap_cluster:
            m["cluster_low"] = round(eng.trap_cluster[0], nd)
            m["cluster_high"] = round(eng.trap_cluster[1], nd)
    return m


def scan_ticker(ticker: str, df: pd.DataFrame, market: str = "asx",
                volume_is_usd: bool = False) -> list:
    """Run both directions over one ticker's daily bars. Returns 0-2 records."""
    if df is None or len(df) < CONFIG.min_history_bars:
        return []
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    if len(df) < CONFIG.min_history_bars:
        return []
    ind = compute_indicators(df, volume_is_usd=volume_is_usd)
    base_tags = module0_tags(ind)
    last = len(df) - 1

    records = []
    for bull in (True, False):
        eng = SetupEngine(ind=ind, bull=bull, market=market)
        eng.process()
        state = eng.state
        if state not in ("TRAP_SET", "SWEPT", "DISPLACED", "RUNNING",
                         "STALLED", "COMPLETE", "DEAD"):
            continue
        # terminal states only surface on the run where they transitioned
        if state in ("COMPLETE", "DEAD") and eng.terminal_index != last:
            continue
        # TRAP_SET only surfaces as a pre-alert when resting liquidity exists
        if state == "TRAP_SET" and not eng.trap_cluster:
            continue
        rec = {
            "ticker": ticker,
            "direction": "bullish" if bull else "bearish",
            "state": state,
            "tier": _tier(eng),
            "tags": _tags(eng, base_tags),
            "regime": eng.regime(last),
            "zones": _zones_list(eng),
            "metrics": _metrics(eng, ind, last),
            "smt": None,
            "route_to": eng.route_to,
        }
        records.append((rec, eng))
    return records


def sort_records(recs: list) -> list:
    """Determinism: tier rank, then state rank, then ticker, then direction."""
    return sorted(recs, key=lambda r: (TIER_ORDER.get(r["tier"], 3),
                                       STATE_ORDER.get(r["state"], 9),
                                       r["ticker"], r["direction"]))

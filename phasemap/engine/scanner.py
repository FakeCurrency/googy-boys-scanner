"""Scan orchestration: Module 0 (universe & liquidity guard), runs both
directions per ticker, assigns tiers, assembles output records.
"""

import math

import pandas as pd

from phasemap.config import CONFIG
from phasemap.engine.indicators import compute_indicators
from phasemap.engine.setup_engine import SetupEngine
from phasemap.engine.zones import price_round

TIER_ORDER = {"A+": 0, "A": 1, "Watch": 2, None: 3}
STATE_ORDER = {"RUNNING": 0, "DISPLACED": 1, "SWEPT": 2, "TRAP_SET": 3,
               "STALLED": 4, "COMPLETE": 5, "DEAD": 6}


def drop_forming_bar(df, market: str, now=None):
    """Drop the newest daily row while it is the STILL-FORMING session.

    v1.3.0 (review H3): 24/7 markets have no close, so yfinance's latest
    "daily" row is the in-progress UTC day, and sweeps/displacement were being
    detected off a partial candle that mutates until midnight -- the same
    pathology VIVEK guards against with VIVEK_DROP_FORMING_BAR.

    v1.3.2 (audit #8, 2026-10-08): equity markets too. They were trusted to be
    "scanned post-close by the nightly schedule", but GitHub fires the 08:30
    UTC cron hours late: on 2026-10-07 the nightly committed at 11:52 EDT,
    ~2.5h into the NASDAQ session, and 95 published NASDAQ records (sweeps,
    displacements, DEAD kills) plus 16 confluence alerts hinged on that
    partial bar. "Forming" is the repo's ONE answer,
    scanner.config.daily_bar_forming(): a stock's bar dated market-local
    today is forming until DAILY_BAR_FINAL in its own calendar (ASX 16:40
    Sydney, NASDAQ 16:05 New York); crypto's until UTC midnight.

    `now` is injectable for tests (an aware datetime; naive = UTC; None = the
    current instant). Markets outside CONFIG.drop_forming_bar_markets pass
    through untouched.
    """
    if market not in CONFIG.drop_forming_bar_markets or df is None or not len(df):
        return df
    from scanner.config import daily_bar_forming
    return df.iloc[:-1] if daily_bar_forming(market, df["Date"].iloc[-1], now) else df


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
        "close": price_round(c),
    }
    r = eng.retrace_pct(i)
    if not math.isnan(r):
        m["retrace_pct"] = round(r, nd)
    if eng.sweep_index >= 0:
        m["sweep_date"] = ind.dates[eng.sweep_index].isoformat()
        m["sweep_depth_pct"] = round(eng.sweep_depth_pct, nd)
        if eng.state == "SWEPT":
            # sessions left for a displacement candle to print. The engine
            # accepts one on bars sweep..sweep+N inclusive (it tests bar
            # sweep+N BEFORE expiring), so after bar i that is sweep+N-i; the
            # old "- 1" (a window counted from the sweep bar) said 0 sessions
            # on sweep+4 while sweep+5 still counted (audit #29, 2026-10-08).
            m["bars_remaining"] = max(
                0, eng.sweep_index + CONFIG.displacement_window_bars - i)
    if eng.displacement_index >= 0:
        m["displacement_date"] = ind.dates[eng.displacement_index].isoformat()
    if eng.state == "TRAP_SET":
        m["bars_in_box"] = eng.bars_in_box
        m["box_low"] = price_round(eng.box_low)
        m["box_high"] = price_round(eng.box_high)
        m["box_height_pct"] = round((eng.box_high - eng.box_low) / eng.box_low, nd)
        if eng.trap_cluster:
            m["cluster_low"] = price_round(eng.trap_cluster[0])
            m["cluster_high"] = price_round(eng.trap_cluster[1])
    return m


def scan_ticker(ticker: str, df: pd.DataFrame, market: str = "asx",
                volume_is_usd: bool = False) -> list:
    """Run both directions over one ticker's daily bars. Returns 0-2 records."""
    if df is None or len(df) < CONFIG.min_history_bars:
        return []
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    # zero-priced rows are feed glitches — they poison ATR, buffers and depth
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)].reset_index(drop=True)
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

"""Parity-mode VIVEK backtest + variant grid (simulation only).

Replays the LIVE bot lifecycle over history — not the looser Insights walk-forward:

  * A+ only (raw grade), long-only, funds excluded, retest skipped
  * one plan per symbol via bot prefer_tf order (1W > 3D > 1D)
  * live TP ladder + trail (same ``_mark`` / ``manage_position`` path)
  * pre-TP1 time-stop at ``VIVEK_BOT_MAX_HOLD_DAYS`` (default 28)
  * tradeability gates (min price, stop width) + ADV floor at entry
  * global slot cap + one-per-symbol + sector cap + stop-out cooldown
  * stamps ``level_tf``, ``entry_type``, ``hold_days``, ``mfe_r_at`` {5,10,14,21}

Variants share the baseline ENTRY population and apply ONE delta each. A
variant PASSES only if R/slot-month improves on ASX and NASDAQ and on both
time halves. Live bot code is never imported for mutation — only read.

CLI entry lives on ``python -m scanner.vivek_backtest --parity``.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from . import config, vivek
from .broker.vivek_bot import _is_fund_or_reit, _sector_key, size_position
from .vivek_backtest import (
    EQUITY,
    LEVEL_TFS,
    TIMEFRAMES,
    _build_row,
    _candidate_mask,
    _dollars,
    _force_close,
    _manage_bar,
    _metrics,
    _risk_usd,
    _sample,
    _sizing_basis,
    _split,
    _turnover_series,
    fx_rates,
)
from .vivek_journal import _apply_costs, _mark, _r_of, _snapshot, costs_for

log = logging.getLogger("vivek_parity")

MFE_DAYS = tuple(getattr(config, "VIVEK_PARITY_MFE_DAYS", (5, 10, 14, 21)))


# ── rules ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParityRules:
    """One complete lifecycle. Baseline mirrors live config; variants flip one knob."""
    name: str = "baseline"
    max_hold_days: int | None = None          # None → read live config; 0 → off
    early_cut_day: int | None = None          # calendar days; None = off
    early_cut_mfe: float | None = None        # cut if peak mfe_r still below this
    level_tfs: tuple[str, ...] | None = None  # None = all; e.g. ("weekly",)
    entry_types: tuple[str, ...] | None = None  # None = bot default (skip retest)
    grades: tuple[str, ...] = ("A+",)
    long_only: bool = True
    apply_adv_gate: bool = True
    apply_tradeability: bool = True

    def resolved_hold(self) -> int:
        if self.max_hold_days is None:
            return int(getattr(config, "VIVEK_BOT_MAX_HOLD_DAYS", 0) or 0)
        return int(self.max_hold_days or 0)

    def allowed_entry_types(self) -> set[str] | None:
        if self.entry_types is not None:
            return set(self.entry_types)
        skip = set(getattr(config, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ())
        # Live takes reclaim + break (retest skipped). Open set = known triggers − skip.
        known = set(getattr(config, "VIVEK_TRIGGER_PRIORITY", ("reclaim", "retest", "break")))
        return known - skip if known else None


def baseline_rules() -> ParityRules:
    return ParityRules(name="baseline")


def variant_grid() -> list[ParityRules]:
    """One-delta variants. Names are stable keys in the decision pack."""
    out: list[ParityRules] = []
    for d in getattr(config, "VIVEK_PARITY_V1_HOLD_DAYS", (42, 56, 0)):
        label = "off" if not d else f"{int(d)}d"
        out.append(ParityRules(name=f"V1_hold_{label}", max_hold_days=int(d)))
    for day, floor in getattr(config, "VIVEK_PARITY_V2_CUTS", ((10, 0.25), (10, 0.5), (14, 0.25), (14, 0.5))):
        out.append(ParityRules(
            name=f"V2_cut_d{int(day)}_mfe{floor:g}",
            early_cut_day=int(day),
            early_cut_mfe=float(floor),
        ))
    out.append(ParityRules(name="V3_weekly_level", level_tfs=("weekly",)))
    out.append(ParityRules(name="V4_break_only", entry_types=("break",)))
    out.append(ParityRules(name="V4_reclaim_break", entry_types=("reclaim", "break")))
    return out


# ── entry detection + management ──────────────────────────────────────────────

def _prefer_plan(plans: dict) -> tuple[str | None, dict | None]:
    """Mirror vivek_bot._pick_plan without importing private botside mutation surface."""
    prefer = getattr(config, "VIVEK_BOT_PREFER_TF", "1W")
    order = [prefer] + [tf for tf in ("1W", "3D", "1D") if tf != prefer]
    for tf in order:
        p = plans.get(tf)
        if not p or not p.get("armed"):
            continue
        if any(p.get(k) is None for k in ("stop", "tp1", "tp2", "tp3")):
            continue
        return tf, p
    return None, None


def _adv_usd_at(df: pd.DataFrame, j: int, market: str) -> float | None:
    """20d average dollar volume ending at bar j (fail-open → None)."""
    if j < 1:
        return None
    lo = max(0, j - 19)
    sl = df.iloc[lo:j + 1]
    try:
        if getattr(config.MARKETS[market], "volume_is_usd", False):
            adv = float(sl["Volume"].mean())
        else:
            adv = float((sl["Close"] * sl["Volume"]).mean())
        return adv if adv > 0 else None
    except Exception:
        return None


def _tradeability_ok(entry: float, stop: float, market: str) -> str | None:
    """Return skip code or None. Same thresholds as vivek_bot evaluate/plan."""
    if entry <= 0:
        return "bad_entry"
    pct = abs(entry - stop) / entry * 100.0
    hi = float(getattr(config, "VIVEK_BOT_MAX_STOP_PCT", 0) or 0)
    if hi > 0 and pct > hi:
        return "wide_stop"
    lo = float(getattr(config, "VIVEK_BOT_MIN_STOP_PCT", 0) or 0)
    if lo > 0 and pct < lo:
        return "stop_too_tight"
    floors = getattr(config, "VIVEK_BOT_MIN_PRICE", None) or {}
    floor = float(floors.get(market, floors.get("default", 0)) or 0)
    if floor > 0 and entry < floor:
        return "min_price"
    return None


def _adv_ok(adv: float | None, notional: float, market: str) -> str | None:
    if adv is None or adv <= 0:
        return None  # fail-open, same as live
    floors = getattr(config, "VIVEK_BOT_MIN_ADV", None) or {}
    min_adv = float(floors.get(market, floors.get("default", 0)) or 0)
    if min_adv > 0 and adv < min_adv:
        return "illiquid"
    max_pct = float(getattr(config, "VIVEK_BOT_MAX_NOTIONAL_PCT_ADV", 0) or 0)
    if max_pct > 0 and notional > adv * (max_pct / 100.0):
        return "size_vs_adv"
    return None


def _stamp_mfe_checkpoints(tr: dict, held: int) -> None:
    mfe = tr.get("mfe_r") or 0.0
    bucket = tr.setdefault("mfe_r_at", {})
    for d in MFE_DAYS:
        key = str(d)
        if held >= d and key not in bucket:
            bucket[key] = round(float(mfe), 4)


def _close_special(tr: dict, price: float, day: str, reason: str, costs) -> None:
    """Time-stop / early-cut close — market fill accounting, mirrors vivek_run."""
    is_long = tr["direction"] == "long"
    remaining = round(1.0 - tr.get("booked_pct", 0.0), 6)
    tr.setdefault("gross_r", tr.get("realized_r", 0.0) or 0.0)
    if remaining > 1e-9:
        tr.setdefault("exits", []).append(
            {"reason": reason, "price": round(price, 8), "pct": remaining, "date": day})
        tr["gross_r"] = round(
            tr["gross_r"] + remaining * _r_of(price, tr["entry"], tr["risk"], is_long), 4)
        tr["booked_pct"] = 1.0
    tr["status"] = "closed"
    tr["exit"] = round(price, 8)
    tr["exit_price"] = round(price, 8)
    tr["exit_date"] = day
    tr["exit_reason"] = reason
    _apply_costs(tr, costs)
    try:
        tr["hold_days"] = (dt.date.fromisoformat(day)
                           - dt.date.fromisoformat(tr["entry_date"])).days
    except Exception:
        tr["hold_days"] = None


def _held_days(tr: dict, day: str) -> int:
    try:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(tr["entry_date"])).days
    except Exception:
        return 0


def _manage_parity_bar(tr: dict, high: float, low: float, close: float, day: str,
                       costs, is_last: bool, rules: ParityRules) -> None:
    """Stop-first intrabar mark, then time-stop / early-cut, then eod force."""
    if tr["status"] != "open":
        return
    is_long = tr["direction"] == "long"
    adverse, favourable = (low, high) if is_long else (high, low)
    _mark(tr, adverse, day, costs)
    if tr["status"] == "open":
        _mark(tr, favourable, day, costs)

    held = _held_days(tr, day)
    if tr["status"] == "open":
        _stamp_mfe_checkpoints(tr, held)

    # Early momentum cut (variant V2) — pre-TP1 only.
    if (tr["status"] == "open" and rules.early_cut_day and rules.early_cut_mfe is not None
            and not tr.get("tp1_hit") and held >= rules.early_cut_day):
        peak = float(tr.get("mfe_r") or 0.0)
        if peak < float(rules.early_cut_mfe):
            _close_special(tr, close, day, "early_cut", costs)
            return

    # Live time-stop: held > MAX_HOLD and still pre-TP1.
    max_hold = rules.resolved_hold()
    if (tr["status"] == "open" and max_hold > 0 and not tr.get("tp1_hit")
            and held > max_hold):
        _close_special(tr, close, day, "time", costs)
        return

    if tr["status"] == "open" and is_last:
        _force_close(tr, close, day, costs)


def _entry_passes_rules(level_tf, entry_type, rules: ParityRules) -> bool:
    if rules.level_tfs is not None and level_tf not in rules.level_tfs:
        return False
    allowed = rules.allowed_entry_types()
    if allowed is not None and entry_type not in allowed:
        return False
    return True


def replay_symbol_parity(df: pd.DataFrame, market: str, symbol: str, name: str,
                         sector: str, rules: ParityRules | None = None) -> list[dict]:
    """Walk one symbol under parity rules; return closed trades (full records)."""
    rules = rules or baseline_rules()
    if df is None or len(df) < config.VIVEK_MIN_HISTORY + 5:
        return []
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if market == "crypto" and len(df) and df.index[-1].date() == dt.datetime.now(dt.timezone.utc).date():
        df = df.iloc[:-1]
        if len(df) < config.VIVEK_MIN_HISTORY + 5:
            return []

    n = len(df)
    idx = df.index
    o = df["Open"].to_numpy()
    h = df["High"].to_numpy()
    l = df["Low"].to_numpy()
    c = df["Close"].to_numpy()
    cand = _candidate_mask(df)
    turnover = _turnover_series(df, market)
    liq_min = config.MARKETS[market].liquidity_min
    costs = costs_for(market)
    min_rr = float(getattr(config, "VIVEK_BOT_MIN_RR", 1.5) or 1.5)

    closed: list[dict] = []
    open_tr: dict | None = None
    pending: tuple | None = None  # (tf, plan, row)

    for j in range(config.VIVEK_MIN_HISTORY, n):
        day = idx[j].date().isoformat()

        # 1) open queued entry at this bar's open (one-per-symbol)
        if pending is not None and open_tr is None and np.isfinite(o[j]):
            tf, plan, row = pending
            tr = _snapshot(row, tf, plan, market, float(o[j]), day)
            if tr is not None:
                # tradeability on FILL price
                code = None
                if rules.apply_tradeability:
                    code = _tradeability_ok(tr["entry"], tr["stop"], market)
                if code is None and rules.apply_adv_gate:
                    adv = _adv_usd_at(df, j - 1, market)  # known as of prior close
                    # notional from live sizer
                    sz = size_position(EQUITY, tr["entry"], tr["stop"])
                    code = _adv_ok(adv, float(sz.get("notional") or 0), market)
                    tr["adv_usd"] = adv
                if code is None:
                    tr["market"] = market
                    tr["level_tf"] = row.get("level_tf")
                    tr["mfe_r_at"] = {}
                    tr["path"] = []  # compact OHLC path for exit-variant re-sim
                    open_tr = tr
                else:
                    tr = None  # gated
            pending = None

        # 2) manage open
        if open_tr is not None:
            # record path bar for variant re-exits
            open_tr.setdefault("path", []).append({
                "d": day, "h": float(h[j]), "l": float(l[j]), "c": float(c[j]),
            })
            _manage_parity_bar(open_tr, float(h[j]), float(l[j]), float(c[j]), day,
                               costs, is_last=(j == n - 1), rules=rules)
            if open_tr["status"] == "closed":
                # final mfe checkpoints up to hold
                _stamp_mfe_checkpoints(open_tr, open_tr.get("hold_days") or 0)
                # V1 variants need price data AFTER a time-stop exit so a longer
                # (or off) hold can be re-simulated. Append ~90 calendar bars of
                # passive OHLC; re_exit replays management over the whole path
                # under the variant rule and will stop earlier/later on its own.
                if open_tr.get("exit_reason") == "time":
                    for k in range(j + 1, min(n, j + 1 + 90)):
                        open_tr["path"].append({
                            "d": idx[k].date().isoformat(),
                            "h": float(h[k]), "l": float(l[k]), "c": float(c[k]),
                        })
                closed.append(open_tr)
                open_tr = None

        # 3) detect — only if flat (one-per-symbol) and liquid candidate bar
        if open_tr is not None or pending is not None:
            continue
        if not (cand[j] and not (turnover[j] < liq_min)):
            continue
        try:
            sig = vivek.evaluate(df.iloc[: j + 1])
        except Exception:
            sig = None
        if sig is None:
            continue
        row, plans, grade = _build_row(sig, df.iloc[: j + 1], symbol, name, sector)
        if not row or grade not in rules.grades:
            continue
        if rules.long_only and row["dir"] == "SHORT":
            continue
        if not plans:
            continue
        # Attach plans so prefer_plan can read them; also keep row shape scan-like.
        row = dict(row)
        row["plans"] = plans
        tf, plan = _prefer_plan(plans)
        if plan is None:
            continue
        rr = float(plan.get("rr") or 0)
        if rr < min_rr:
            continue
        entry_type = plan.get("entry_trigger") or (row.get("entry_types") or [None])[0]
        level_tf = row.get("level_tf")
        if not _entry_passes_rules(level_tf, entry_type, rules):
            continue
        # Pre-check tradeability on plan levels (entry may differ slightly at fill)
        plan_entry = float(plan.get("entry") or c[j])
        if rules.apply_tradeability:
            code = _tradeability_ok(plan_entry, float(plan["stop"]), market)
            if code:
                continue
        pending = (tf, plan, row)

    return closed


def _slim_parity(tr: dict) -> dict:
    """Persist enough to recompute metrics + variants without full path bloat optional."""
    keys = ("symbol", "market", "timeframe", "level_tf", "entry_type", "grade",
            "direction", "entry", "stop", "risk", "exit", "entry_date", "exit_date",
            "exit_reason", "realized_r", "gross_r", "cost_r", "mae_r", "mfe_r",
            "hold_days", "mfe_r_at", "sector", "tp1_hit", "tp2_hit", "tp3_hit",
            "path")
    return {k: tr.get(k) for k in keys}


# ── portfolio (global slots) + R/slot-month ───────────────────────────────────

def portfolio_sim_parity(trades: list[dict], max_total: int | None = None) -> dict:
    """Chronological global book — true cross-market slot contention."""
    skip_types = set(getattr(config, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ())
    long_only = not getattr(config, "VIVEK_BOT_ALLOW_SHORTS", True)
    max_total = int(max_total if max_total is not None
                    else (getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0)
                          or config.VIVEK_BOT_MAX_POSITIONS))
    max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    cooldown = int(getattr(config, "VIVEK_BOT_REENTRY_COOLDOWN_DAYS", 0) or 0)

    elig = [t for t in trades
            if t.get("grade") == "A+"
            and t.get("entry_type") not in skip_types
            and (not long_only or t.get("direction") == "long")
            and t.get("entry_date") and t.get("exit_date")]
    if not elig:
        return {"note": "no bot-eligible parity trades",
                "eligible": _metrics([]), "portfolio": _metrics([]),
                "taken": 0, "skipped": {}, "peak_open": 0,
                "slot_months": 0.0, "r_per_slot_month": None}

    def add_days(day: str, n: int) -> str:
        return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()

    trs = sorted(elig, key=lambda t: (t["entry_date"],
                                      0 if t.get("timeframe") == "1W" else 1,
                                      t.get("symbol") or ""))
    open_pos: list[dict] = []
    open_syms: set[str] = set()  # market:symbol
    sector_count: Counter = Counter()  # (market, sector_key)
    cooldown_until: dict[str, str] = {}
    taken_all: list[dict] = []
    skips: Counter = Counter()
    peak_open = 0
    # slot-day integral for R/slot-month
    # walk event timeline
    events: list[tuple[str, str, dict]] = []  # (date, kind, trade) kind=enter|exit

    for t in trs:
        day = t["entry_date"]
        # free exits strictly before today
        still = []
        for p in open_pos:
            if p["exit_date"] < day:
                key = f"{p['market']}:{p['symbol']}"
                open_syms.discard(key)
                sk = _sector_key(p["symbol"], p.get("sector"), p["market"])
                if sk:
                    sector_count[(p["market"], sk)] -= 1
                if cooldown and p.get("exit_reason") == "stop":
                    cooldown_until[key] = add_days(p["exit_date"], cooldown)
            else:
                still.append(p)
        open_pos = still

        key = f"{t['market']}:{t['symbol']}"
        sk = _sector_key(t["symbol"], t.get("sector"), t["market"])
        if key in open_syms:
            skips["dup_symbol"] += 1
        elif cooldown_until.get(key, "") >= day:
            skips["cooldown"] += 1
        elif len(open_pos) >= max_total:
            skips["book_full"] += 1
        elif max_sector and sk and sector_count[(t["market"], sk)] >= max_sector:
            skips["sector_cap"] += 1
        else:
            open_pos.append(t)
            open_syms.add(key)
            if sk:
                sector_count[(t["market"], sk)] += 1
            taken_all.append(t)
            peak_open = max(peak_open, len(open_pos))

    slot_months, r_psm = _slot_month_stats(taken_all)

    return {
        "params": {
            "max_open_total": max_total,
            "max_per_sector": max_sector,
            "cooldown_days": cooldown,
            "long_only": long_only,
            "skip_entry_types": sorted(skip_types),
            "simulated": ["time_stop", "tp_ladder_trail", "one_per_symbol",
                          "global_slot_cap", "sector_cap", "cooldown",
                          "min_price", "stop_width", "adv_gates",
                          "a_plus_only", "long_only", "skip_retest",
                          "prefer_tf_one_plan"],
        },
        "eligible": _metrics(elig),
        "portfolio": _metrics(taken_all),
        "taken": len(taken_all),
        "skipped": dict(skips),
        "peak_open": peak_open,
        "slot_months": slot_months,
        "r_per_slot_month": r_psm,
    }


def _slot_month_stats(trades: list[dict]) -> tuple[float, float | None]:
    """Integrate concurrent open slots over calendar days → slot-months; R / that."""
    if not trades:
        return 0.0, None
    events: list[tuple[dt.date, int]] = []  # (date, delta)
    total_r = 0.0
    for t in trades:
        try:
            e = dt.date.fromisoformat(t["entry_date"])
            x = dt.date.fromisoformat(t["exit_date"])
        except Exception:
            continue
        if x < e:
            continue
        events.append((e, +1))
        events.append((x, -1))  # free on exit day (not occupying next)
        total_r += float(t.get("realized_r") or 0.0)
    if not events:
        return 0.0, None
    events.sort(key=lambda z: (z[0], z[1]))  # exits (-1) before entries (+1) on same day
    # Actually we want exit freeing before entry on same day: -1 before +1 ✓
    open_n = 0
    slot_days = 0
    prev = events[0][0]
    i = 0
    while i < len(events):
        d = events[i][0]
        # accumulate open_n * days since prev
        gap = (d - prev).days
        if gap > 0 and open_n > 0:
            slot_days += open_n * gap
        # apply all deltas on this day
        while i < len(events) and events[i][0] == d:
            open_n += events[i][1]
            i += 1
        prev = d
    slot_months = round(slot_days / 30.4375, 4)
    r_psm = round(total_r / slot_months, 4) if slot_months > 0 else None
    return slot_months, r_psm


# ── exit-variant re-sim from stored path ──────────────────────────────────────

def re_exit_trade(tr: dict, rules: ParityRules) -> dict | None:
    """Re-manage one baseline trade's path under a different exit rule set.

    Entry is frozen (same population). Returns a new closed trade dict, or None
    if the path is missing.
    """
    path = tr.get("path") or []
    if not path:
        return None
    # Rebuild an open snapshot at entry.
    row = {
        "symbol": tr["symbol"], "name": tr.get("symbol"), "sector": tr.get("sector", ""),
        "dir": "LONG" if tr.get("direction") == "long" else "SHORT",
        "grade": tr.get("grade") or "A+", "entry_types": [tr.get("entry_type")],
        "level_tf": tr.get("level_tf"),
    }
    # We don't have the original plan tps on slim... they must be on the trade.
    # Path re-sim needs stop/tp ladder. Baseline slim keeps stop (trailed!) —
    # use ORIGINAL stop via entry/risk and require tp fields if present.
    if not tr.get("risk") or not tr.get("entry"):
        return None
    entry = float(tr["entry"])
    risk = float(tr["risk"])
    is_long = tr.get("direction") == "long"
    orig_stop = entry - risk if is_long else entry + risk
    # Recover TPs from first path management? We need them on the trade.
    # Parity slim stores path only — attach tp1/2/3 during baseline before slim.
    if any(tr.get(k) is None for k in ("tp1", "tp2", "tp3")):
        return None
    plan = {
        "stop": orig_stop, "tp1": tr["tp1"], "tp2": tr["tp2"], "tp3": tr["tp3"],
        "scale": tr.get("scale") or list(
            config.VIVEK_TP_SCALE_LONG if is_long else config.VIVEK_TP_SCALE_SHORT),
        "entry_trigger": tr.get("entry_type"), "armed": True,
    }
    costs = costs_for(tr.get("market") or "nasdaq")
    snap = _snapshot(row, tr.get("timeframe") or "1W", plan,
                     tr.get("market") or "nasdaq", entry, tr["entry_date"])
    if snap is None:
        return None
    snap["market"] = tr.get("market")
    snap["level_tf"] = tr.get("level_tf")
    snap["mfe_r_at"] = {}
    snap["path"] = list(path)
    for i, bar in enumerate(path):
        _manage_parity_bar(snap, bar["h"], bar["l"], bar["c"], bar["d"], costs,
                           is_last=(i == len(path) - 1), rules=rules)
        if snap["status"] == "closed":
            break
    if snap["status"] != "closed":
        last = path[-1]
        _force_close(snap, last["c"], last["d"], costs)
    _stamp_mfe_checkpoints(snap, snap.get("hold_days") or 0)
    # drop bulky path from variant output (keep mfe_r_at)
    out = _slim_parity(snap)
    out.pop("path", None)
    # carry original entry identity
    out["baseline_exit_reason"] = tr.get("exit_reason")
    out["baseline_realized_r"] = tr.get("realized_r")
    return out


# ── aggregation / halves / pass criteria ──────────────────────────────────────

def _time_half(trades: list[dict]) -> tuple[list[dict], list[dict]]:
    dated = [t for t in trades if t.get("entry_date")]
    if not dated:
        return [], []
    dates = sorted(t["entry_date"] for t in dated)
    mid = dates[len(dates) // 2]
    return ([t for t in dated if t["entry_date"] < mid],
            [t for t in dated if t["entry_date"] >= mid])


def _cohort_stats(trades: list[dict]) -> dict:
    m = _metrics(trades)
    sm, rpsm = _slot_month_stats(trades)
    m = dict(m)
    m["slot_months"] = sm
    m["r_per_slot_month"] = rpsm
    # exit mix — the live book's smoking gun
    reasons = Counter(t.get("exit_reason") for t in trades)
    m["exit_reasons"] = dict(reasons)
    holds = [t["hold_days"] for t in trades if t.get("hold_days") is not None]
    m["avg_hold_days"] = round(sum(holds) / len(holds), 1) if holds else None
    return m


def report_by_slices(trades: list[dict]) -> dict:
    by_mkt = {mk: _cohort_stats([t for t in trades if t.get("market") == mk])
              for mk in sorted({t.get("market") for t in trades if t.get("market")})}
    h1, h2 = _time_half(trades)
    return {
        "overall": _cohort_stats(trades),
        "by_market": by_mkt,
        "by_level_tf": {k: _cohort_stats(v) for k, v in
                        ((lt, [t for t in trades if t.get("level_tf") == lt])
                         for lt in LEVEL_TFS)},
        "by_entry_type": {k: _cohort_stats(v) for k, v in
                          ((et, [t for t in trades if t.get("entry_type") == et])
                           for et in sorted({t.get("entry_type") for t in trades if t.get("entry_type")}))},
        "by_exit_reason": {k: _cohort_stats(v) for k, v in
                           ((r, [t for t in trades if t.get("exit_reason") == r])
                            for r in sorted({t.get("exit_reason") for t in trades if t.get("exit_reason")}))},
        "time_half": {"first": _cohort_stats(h1), "second": _cohort_stats(h2),
                      "split_entry_date": (sorted(t["entry_date"] for t in trades
                                                  if t.get("entry_date")) or [None])[
                          len([t for t in trades if t.get("entry_date")]) // 2
                          if trades else 0] if trades else None},
    }


def variant_passes(baseline_taken: list[dict], variant_taken: list[dict]) -> dict:
    """PASS only if R/slot-month improves on ASX+NASDAQ and both time halves."""
    pass_mkts = tuple(getattr(config, "VIVEK_PARITY_PASS_MARKETS", ("asx", "nasdaq")))

    def rpsm(trs, pred=None):
        sub = [t for t in trs if pred is None or pred(t)]
        _, v = _slot_month_stats(sub)
        return v

    base_all = rpsm(baseline_taken)
    var_all = rpsm(variant_taken)
    checks = {}
    ok = True
    # overall
    checks["overall"] = {
        "baseline": base_all, "variant": var_all,
        "delta": None if base_all is None or var_all is None else round(var_all - base_all, 4),
        "pass": (base_all is not None and var_all is not None and var_all > base_all),
    }
    if not checks["overall"]["pass"]:
        ok = False
    for mk in pass_mkts:
        b, v = rpsm(baseline_taken, lambda t, m=mk: t.get("market") == m), \
               rpsm(variant_taken, lambda t, m=mk: t.get("market") == m)
        p = b is not None and v is not None and v > b
        checks[f"market:{mk}"] = {"baseline": b, "variant": v,
                                  "delta": None if b is None or v is None else round(v - b, 4),
                                  "pass": p}
        if not p:
            ok = False
    bh1, bh2 = _time_half(baseline_taken)
    vh1, vh2 = _time_half(variant_taken)
    for label, bt, vt in (("half:first", bh1, vh1), ("half:second", bh2, vh2)):
        b, v = rpsm(bt), rpsm(vt)
        p = b is not None and v is not None and v > b
        checks[label] = {"baseline": b, "variant": v,
                         "delta": None if b is None or v is None else round(v - b, 4),
                         "pass": p}
        if not p:
            ok = False
    return {"pass": ok, "checks": checks}


# ── driver ────────────────────────────────────────────────────────────────────

def run_market_parity(mk: str, limit: int | None, period: str,
                      rules: ParityRules | None = None) -> tuple[list[dict], dict]:
    from .universe import load_universe
    from .data import download

    rules = rules or baseline_rules()
    uni_all = load_universe(mk, full=True)
    if getattr(config, "VIVEK_BOT_EXCLUDE_FUNDS", True):
        uni_all = [u for u in uni_all
                   if not _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")})]
    uni = _sample(uni_all, limit)
    log.info("[parity/%s] %s — downloading %d of %d (%s)",
             rules.name, mk, len(uni), len(uni_all), period)
    frames = download([u["yf"] for u in uni], period=period)
    meta = {u["yf"]: u for u in uni}
    trades: list[dict] = []
    for yf, df in frames.items():
        u = meta.get(yf, {})
        try:
            raw = replay_symbol_parity(df, mk, u.get("symbol", yf), u.get("name", yf),
                                       u.get("sector", ""), rules=rules)
            for t in raw:
                # keep tp ladder on slim for exit re-sim
                slim = _slim_parity(t)
                for k in ("tp1", "tp2", "tp3", "scale"):
                    slim[k] = t.get(k)
                trades.append(slim)
        except Exception as e:
            log.warning("[parity/%s] %s %s replay error: %s", rules.name, mk, yf, e)
    log.info("[parity/%s] %s — %d trades from %d symbols",
             rules.name, mk, len(trades), len(uni))
    return trades, {
        "symbols": len(uni), "universe": len(uni_all),
        "sampled_pct": round(100 * len(uni) / max(len(uni_all), 1), 1),
        "trades": len(trades),
    }


def build_parity_report(baseline_trades: list[dict], coverage: dict,
                        params: dict, variant_results: dict | None = None) -> dict:
    # Drop paths from published baseline trades (keep mfe_r_at); paths stay only
    # inside the process for variant re-exit. Caller may strip before write.
    published = []
    for t in baseline_trades:
        p = dict(t)
        p.pop("path", None)
        published.append(p)

    port = portfolio_sim_parity(baseline_trades)
    taken_ids = {(t.get("symbol"), t.get("market"), t.get("entry_date"), t.get("timeframe"))
                 for t in baseline_trades}
    # portfolio_sim returns metrics only — recover taken list the same way
    taken = _taken_list(baseline_trades)

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "parity",
        "status": "complete",
        "currency": config.REPORT_CURRENCY,
        "fx": fx_rates(),
        "params": params,
        "coverage": coverage,
        "baseline": {
            "rules": {
                "max_hold_days": baseline_rules().resolved_hold(),
                "grades": ["A+"],
                "long_only": True,
                "skip_entry_types": list(getattr(config, "VIVEK_BOT_SKIP_ENTRY_TYPES", []) or []),
                "prefer_tf": getattr(config, "VIVEK_BOT_PREFER_TF", "1W"),
                "max_open_total": int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 30) or 30),
            },
            "all_signals": report_by_slices(published),
            "portfolio": port,
            "portfolio_slices": report_by_slices(taken),
        },
        "variants": variant_results or {},
        "trades": published,
        "caveats": [
            "Survivorship bias — today's universe excludes delisted names.",
            "yfinance daily data (dividend-adjusted); occasional gaps.",
            "Intrabar fills assume the stop fills before the target within a bar.",
            "Parity mode mirrors live bot lifecycle (A+/long-only/skip-retest/"
            "one-plan-per-symbol/28d pre-TP1 time-stop/ADV+tradeability gates/"
            "global slot cap). Earnings buffer is NOT replayed (no historical calendar).",
            "R units are primary. Dollar columns inherit the live sizing mode "
            f"({_sizing_basis().get('sizing_mode')}) and are secondary.",
            "Variant PASS requires R/slot-month improvement on ASX AND NASDAQ "
            "AND both time halves. Crypto is reported but not a pass gate.",
        ],
    }
    return report


def _taken_list(trades: list[dict]) -> list[dict]:
    """Re-run portfolio selection and return the taken trade dicts."""
    # Duplicate the selection logic returning objects.
    skip_types = set(getattr(config, "VIVEK_BOT_SKIP_ENTRY_TYPES", ()) or ())
    long_only = not getattr(config, "VIVEK_BOT_ALLOW_SHORTS", True)
    max_total = int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0)
                    or config.VIVEK_BOT_MAX_POSITIONS)
    max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    cooldown = int(getattr(config, "VIVEK_BOT_REENTRY_COOLDOWN_DAYS", 0) or 0)

    elig = [t for t in trades
            if t.get("grade") == "A+"
            and t.get("entry_type") not in skip_types
            and (not long_only or t.get("direction") == "long")
            and t.get("entry_date") and t.get("exit_date")]
    trs = sorted(elig, key=lambda t: (t["entry_date"],
                                      0 if t.get("timeframe") == "1W" else 1,
                                      t.get("symbol") or ""))

    def add_days(day: str, n: int) -> str:
        return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()

    open_pos: list[dict] = []
    open_syms: set[str] = set()
    sector_count: Counter = Counter()
    cooldown_until: dict[str, str] = {}
    taken: list[dict] = []
    for t in trs:
        day = t["entry_date"]
        still = []
        for p in open_pos:
            if p["exit_date"] < day:
                key = f"{p['market']}:{p['symbol']}"
                open_syms.discard(key)
                sk = _sector_key(p["symbol"], p.get("sector"), p["market"])
                if sk:
                    sector_count[(p["market"], sk)] -= 1
                if cooldown and p.get("exit_reason") == "stop":
                    cooldown_until[key] = add_days(p["exit_date"], cooldown)
            else:
                still.append(p)
        open_pos = still
        key = f"{t['market']}:{t['symbol']}"
        sk = _sector_key(t["symbol"], t.get("sector"), t["market"])
        if key in open_syms:
            continue
        if cooldown_until.get(key, "") >= day:
            continue
        if len(open_pos) >= max_total:
            continue
        if max_sector and sk and sector_count[(t["market"], sk)] >= max_sector:
            continue
        open_pos.append(t)
        open_syms.add(key)
        if sk:
            sector_count[(t["market"], sk)] += 1
        taken.append(t)
    return taken


def run_variants_on_baseline(baseline_trades: list[dict]) -> dict:
    """Apply each variant as one delta on the baseline entry population."""
    base_taken = _taken_list(baseline_trades)
    # Index baseline trades by identity for entry filters (V3/V4 work on full elig)
    results = {}
    for rules in variant_grid():
        # Entry-filter variants (V3/V4): filter signals, re-portfolio, keep baseline exits
        if rules.level_tfs is not None or (
                rules.entry_types is not None and rules.early_cut_day is None
                and rules.max_hold_days is None):
            filtered = [t for t in baseline_trades
                        if _entry_passes_rules(t.get("level_tf"), t.get("entry_type"), rules)]
            # For pure entry filters, exits stay as recorded under baseline management
            taken = _taken_list(filtered)
            # strip paths
            taken_pub = []
            for t in taken:
                p = dict(t)
                p.pop("path", None)
                taken_pub.append(p)
            port = portfolio_sim_parity(filtered)
            verdict = variant_passes(base_taken, taken)
            results[rules.name] = {
                "delta": _delta_desc(rules),
                "kind": "entry_filter",
                "portfolio": port,
                "slices": report_by_slices(taken_pub),
                "verdict": verdict,
            }
            continue

        # Exit variants (V1/V2): re-exit each baseline-taken trade from its path
        re_exited = []
        for t in base_taken:
            if not _entry_passes_rules(t.get("level_tf"), t.get("entry_type"), rules):
                # still include? same population — V1/V2 don't filter entries
                pass
            nt = re_exit_trade(t, rules)
            if nt is not None:
                re_exited.append(nt)
            else:
                # no path — keep baseline outcome (conservative)
                p = dict(t)
                p.pop("path", None)
                re_exited.append(p)
        port = portfolio_sim_parity(re_exited)
        # already the taken set (re-exit doesn't change entries)
        sm, rpsm = _slot_month_stats(re_exited)
        port = dict(port)
        port["slot_months"] = sm
        port["r_per_slot_month"] = rpsm
        port["portfolio"] = _metrics(re_exited)
        port["taken"] = len(re_exited)
        verdict = variant_passes(base_taken, re_exited)
        results[rules.name] = {
            "delta": _delta_desc(rules),
            "kind": "exit_rule",
            "portfolio": port,
            "slices": report_by_slices(re_exited),
            "verdict": verdict,
        }
    return results


def _delta_desc(rules: ParityRules) -> str:
    if rules.name.startswith("V1_"):
        h = rules.resolved_hold()
        return f"time-stop {h}d" if h else "time-stop off"
    if rules.name.startswith("V2_"):
        return f"early cut day {rules.early_cut_day} if mfe_r < {rules.early_cut_mfe}"
    if rules.name.startswith("V3_"):
        return f"level_tf in {rules.level_tfs}"
    if rules.name.startswith("V4_"):
        return f"entry_types {rules.entry_types}"
    return rules.name


def best_variant(variant_results: dict) -> dict:
    """Pick the single best PASSING variant by overall R/slot-month delta; else none."""
    best = None
    for name, vr in variant_results.items():
        v = vr.get("verdict") or {}
        if not v.get("pass"):
            continue
        delta = (v.get("checks") or {}).get("overall", {}).get("delta")
        if delta is None:
            continue
        if best is None or delta > best["delta"]:
            best = {"name": name, "delta": delta, "delta_desc": vr.get("delta"),
                    "verdict": v}
    return best or {"name": None, "delta": None,
                    "reason": "no variant passed ASX+NASDAQ+both-halves gate"}


def run_parity(markets: list[str], limit: int | None, period: str,
               run_variants: bool = True) -> dict:
    trades, coverage = [], {}
    rules = baseline_rules()
    for mk in markets:
        tr, cov = run_market_parity(mk, limit, period, rules=rules)
        trades += tr
        coverage[mk] = cov
    params = {
        "mode": "parity",
        "markets": list(markets),
        "limit": limit,
        "period": period,
        "exclude_funds": True,
        "long_only": True,
        "grades": ["A+"],
        "time_stop_days": rules.resolved_hold(),
        "mfe_days": list(MFE_DAYS),
        **_sizing_basis(),
        "intrabar": "pessimistic (stop-first)",
    }
    variant_results = run_variants_on_baseline(trades) if run_variants else {}
    report = build_parity_report(trades, coverage, params, variant_results)
    report["best_variant"] = best_variant(variant_results) if variant_results else {}
    return report


def print_parity(report: dict) -> None:
    b = report.get("baseline") or {}
    port = b.get("portfolio") or {}
    pm = port.get("portfolio") or {}
    print("\n=== VIVEK PARITY BACKTEST ===")
    print("params:", report.get("params"))
    print("coverage:", report.get("coverage"))
    print(f"\nPORTFOLIO n={pm.get('n')}  expR={pm.get('expectancy_r')}  "
          f"totR={pm.get('total_r')}  win={pm.get('win_rate')}%  "
          f"R/slot-month={port.get('r_per_slot_month')}  "
          f"slot-months={port.get('slot_months')}  "
          f"taken={port.get('taken')} peak_open={port.get('peak_open')}")
    print("skips:", port.get("skipped"))
    slices = b.get("portfolio_slices") or {}
    er = (slices.get("by_exit_reason") or {})
    if er:
        print("\nBY EXIT REASON (portfolio taken)")
        for k, m in er.items():
            if m.get("n"):
                print(f"  {k:<12} n={m['n']:<4} expR {m.get('expectancy_r'):+}  "
                      f"totR {m.get('total_r'):+}")
    print("\nVARIANTS")
    for name, vr in (report.get("variants") or {}).items():
        v = vr.get("verdict") or {}
        flag = "PASS" if v.get("pass") else "fail"
        d = (v.get("checks") or {}).get("overall", {})
        print(f"  [{flag}] {name:<28} {vr.get('delta')}  "
              f"R/sm {d.get('baseline')} → {d.get('variant')}  Δ={d.get('delta')}")
    bv = report.get("best_variant") or {}
    print("\nBEST:", bv)

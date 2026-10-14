"""Parity-mode VIVEK backtest + decision variants (simulation only).

Replays the LIVE bot lifecycle (hc4-1) over history as ONE chronological book
across every market -- not the looser Insights walk-forward:

  * grades A/A+ (``VIVEK_BOT_GRADES``, grade_raw), long-only, funds excluded
  * one plan per symbol via the bot's cell walk (``VIVEK_BOT_ENTRY_CELLS``:
    1W reclaim/break > 3D reclaim > 1D break; the trigger must sit in its cell)
  * the LEVEL gate (``VIVEK_BOT_LEVEL_TF_ALLOW``: weekly/3d, fail-closed)
  * live TP ladder + trail (same ``_mark`` / ``manage_position`` path)
  * pre-TP1 time-stop at ``VIVEK_BOT_MAX_HOLD_DAYS`` (28)
  * tradeability gates (min price, stop width) + ADV floor at the fill
  * global slot cap + one-per-symbol + per-market sector cap + stop cooldown
  * stamps ``level_tf``, ``entry_type``, ``hold_days``, ``mfe_r_at`` {5,10,14,21}
  * every stop is scored twice: the worst print (headline, as the 5.0
    backtest) and the house fill (``realized_r_house``, REFINE200 #146)

HOW (REFINE200 #150). Two phases. (1) Per symbol, every candidate bar is
evaluated ONCE and its armed plans recorded (``symbol_signals``) -- that does
not depend on any book, so it runs in parallel (``workers``). (2) ONE event
loop (``run_book``) walks every fill date of every market in order and asks the
book: a signal the book refuses leaves its symbol FLAT, so the next bar's
signal can still be taken -- what the live bot does on its next scan. The old
design replayed each symbol alone, one trade at a time, and applied the book
AFTERWARDS, so a trade the book rejected still held its symbol for its whole
life and hid every signal behind it (IS 150 such phantoms over 4,556
symbol-days, OOS 538 over 17,852) and re-entered within the stop cooldown only
for the book to refuse it.

Variants re-run phase 2 with ONE delta each -- entry filters and exit rules
alike, so a longer hold also blocks the entries it would really have blocked.
A variant PASSES only if R/slot-month improves overall, on ASX and NASDAQ and
on both time halves, the halves split at the BASELINE's median entry date
(REFINE200 #151). Live bot code is never imported for mutation -- only read.

CLI entry lives on ``python -m scanner.vivek_backtest --parity``.
"""

from __future__ import annotations

import datetime as dt
import heapq
import logging
import math
import os
import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config, vivek
from .broker.vivek_bot import _is_fund_or_reit, _sector_key, size_position
from .vivek_backtest import (
    EQUITY,
    LEVEL_TFS,
    _build_row,
    _candidate_mask,
    _force_close,
    _mark_bar,
    _metrics,
    _sample,
    _sizing_basis,
    _turnover_series,
    cooldown_days,
    data_source_caveat,
    fetch_market_frames,
    fx_rates,
    level_allow,
    level_ok,
    replay_params,
)
from .vivek_journal import _apply_costs, _r_of, _snapshot, costs_for

log = logging.getLogger("vivek_parity")

MFE_DAYS = tuple(getattr(config, "VIVEK_PARITY_MFE_DAYS", (5, 10, 14, 21)))
# What a recorded signal keeps of each armed plan (everything _snapshot and
# the gates read). The rest of a plan (labels, notes) is display.
_PLAN_KEYS = ("stop", "tp1", "tp2", "tp3", "scale", "entry", "rr", "entry_trigger",
              "trigger_bar", "structural_tps")
_EPOCH = dt.date(1970, 1, 1)


# ── rules ─────────────────────────────────────────────────────────────────────

Cells = tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class ParityRules:
    """One complete lifecycle. Baseline mirrors live config; variants flip one knob."""
    name: str = "baseline"
    max_hold_days: int | None = None          # None → read live config; 0 → off
    early_cut_day: int | None = None          # calendar days; None = off
    early_cut_mfe: float | None = None        # cut if peak mfe_r still below this
    # None = the LIVE level gate (VIVEK_BOT_LEVEL_TF_ALLOW); () = gate off
    # (every level, as the config reads an empty allowlist); e.g. ("weekly",).
    level_tfs: tuple[str, ...] | None = None
    entry_types: tuple[str, ...] | None = None  # None = bot default (the cell table)
    grades: tuple[str, ...] | None = None       # None = config.VIVEK_BOT_GRADES
    cells: Cells | None = None                  # None = config.VIVEK_BOT_ENTRY_CELLS
    market_cells: tuple[tuple[str, Cells], ...] | None = None  # per-market cell override
    drop_markets: tuple[str, ...] = ()          # markets the variant does not trade
    long_only: bool = True
    apply_adv_gate: bool = True
    apply_tradeability: bool = True

    def resolved_hold(self) -> int:
        if self.max_hold_days is None:
            return int(getattr(config, "VIVEK_BOT_MAX_HOLD_DAYS", 0) or 0)
        return int(self.max_hold_days or 0)

    def allowed_entry_types(self) -> set[str] | None:
        """Triggers a variant may take (any timeframe). None = the live cell
        table decides per timeframe (see _choose_plan)."""
        if self.entry_types is not None:
            return set(self.entry_types)
        return None

    def allowed_grades(self) -> tuple[str, ...]:
        if self.grades is not None:
            return tuple(self.grades)
        return tuple(getattr(config, "VIVEK_BOT_GRADES", ("A+",)) or ("A+",))

    def level_allow(self) -> tuple[str, ...]:
        if self.level_tfs is None:
            return level_allow()
        return tuple(str(x).strip().lower() for x in self.level_tfs)

    def cells_for(self, market: str) -> dict[str, tuple[str, ...]]:
        if self.market_cells is not None:
            per = dict(self.market_cells)
            if market in per:
                return dict(per[market])
        if self.cells is not None:
            return dict(self.cells)
        return _bot_cells()

    def trades_market(self, market: str) -> bool:
        return market not in (self.drop_markets or ())


def baseline_rules() -> ParityRules:
    return ParityRules(name="baseline")


def _without_cell(cells: dict, tf: str, trigger: str) -> Cells:
    """The cell table with one (timeframe, trigger) cell removed (a timeframe
    left with no trigger drops out of the walk entirely)."""
    out = []
    for t, trigs in cells.items():
        keep = tuple(x for x in trigs if not (t == tf and x == trigger))
        if keep:
            out.append((t, keep))
    return tuple(out)


def variant_grid() -> list[ParityRules]:
    """One-delta variants. Names are stable keys in the decision pack.

    V1/V2 are exit rules (the time stop's own effect is V1 against the
    baseline); V3..V8 are entry rules. V5..V8 are the owner's 2026-10 decision
    questions: A+ only vs A/A+, drop the 3D reclaim cell, drop ASX, and ASX
    without its 3D reclaim cell."""
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
    out.append(ParityRules(name="V5_aplus_only", grades=("A+",)))
    no_3dr = _without_cell(_bot_cells(), "3D", "reclaim")
    out.append(ParityRules(name="V6_no_3d_reclaim", cells=no_3dr))
    out.append(ParityRules(name="V7_no_asx", drop_markets=("asx",)))
    out.append(ParityRules(name="V8_asx_3d_reclaim_off", market_cells=(("asx", no_3dr),)))
    return out


# ── entry detection + management ──────────────────────────────────────────────

def _bot_cells() -> dict:
    cells = getattr(config, "VIVEK_BOT_ENTRY_CELLS", None)
    return {tf: tuple(trigs or ()) for tf, trigs in cells.items()} \
        if isinstance(cells, dict) and cells else {}


def _in_cell(timeframe, entry_type) -> bool:
    """Is (timeframe, trigger) one of the bot's entry cells?"""
    return entry_type in set(_bot_cells().get(timeframe) or ())


def _cell_of(tr: dict) -> str:
    return f"{tr.get('timeframe')} {tr.get('entry_type')}"


def _choose_plan(plans: dict, cells: dict, allowed: set[str] | None = None
                 ) -> tuple[str | None, dict | None]:
    """Mirror vivek_bot._pick_plan without importing private botside mutation
    surface: walk the CELL table (1W > 3D > 1D) and take the first armed,
    complete plan whose trigger the cell allows. `allowed`, when given by a
    variant, replaces the cell's trigger set on every timeframe."""
    for tf, triggers in cells.items():
        p = plans.get(tf)
        if not p or not p.get("armed", True):
            continue
        if any(p.get(k) is None for k in ("stop", "tp1", "tp2", "tp3")):
            continue
        ok = set(allowed) if allowed is not None else set(triggers or ())
        if p.get("entry_trigger") not in ok:
            continue
        return tf, p
    return None, None


def _prefer_plan(plans: dict, allowed: set[str] | None = None) -> tuple[str | None, dict | None]:
    """The live cell walk over ``config.VIVEK_BOT_ENTRY_CELLS``."""
    return _choose_plan(plans, _bot_cells(), allowed)


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


def _adv_series(df: pd.DataFrame, market: str) -> np.ndarray:
    """``_adv_usd_at`` for every bar at once (NaN where it returns None)."""
    try:
        if getattr(config.MARKETS[market], "volume_is_usd", False):
            dv = df["Volume"].astype(float)
        else:
            dv = df["Close"].astype(float) * df["Volume"].astype(float)
        out = dv.rolling(20, min_periods=1).mean().to_numpy(dtype=float)
    except Exception:
        return np.full(len(df), np.nan)
    out = np.where(out > 0, out, np.nan)
    if len(out):
        out[0] = np.nan
    return out


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


def _stamp_mfe_checkpoints(tr: dict, held: int, close: float | None = None) -> None:
    """Stamp peak MFE and day-close mark-to-market R at calendar checkpoints."""
    mfe = tr.get("mfe_r") or 0.0
    bucket = tr.setdefault("mfe_r_at", {})
    close_bucket = tr.setdefault("close_r_at", {})
    close_r = None
    if close is not None and tr.get("risk"):
        is_long = tr.get("direction") == "long"
        try:
            close_r = _r_of(float(close), float(tr["entry"]), float(tr["risk"]), is_long)
        except Exception:
            close_r = None
    for d in MFE_DAYS:
        key = str(d)
        if held >= d and key not in bucket:
            bucket[key] = round(float(mfe), 4)
        if held >= d and key not in close_bucket and close_r is not None:
            close_bucket[key] = round(float(close_r), 4)


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


def _parity_bar(tr: dict, high: float, low: float, close: float, day: str,
                costs, is_last: bool, rules: ParityRules, open_) -> None:
    _mark_bar(tr, open_, high, low, day, costs)

    held = _held_days(tr, day)
    if tr["status"] == "open":
        _stamp_mfe_checkpoints(tr, held, close)

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


def _manage_parity_bar(tr: dict, high: float, low: float, close: float, day: str,
                       costs, is_last: bool, rules: ParityRules, open_: float | None = None) -> None:
    """Stop-first intrabar mark, then time-stop / early-cut, then eod force.
    ``open_`` feeds only the house-fill twin of a stop exit (REFINE200 #146);
    a time stop, a cut or the end of data is one fill under both rules."""
    if tr["status"] != "open":
        return
    _parity_bar(tr, high, low, close, day, costs, is_last, rules, open_)
    if tr["status"] == "closed":
        tr.setdefault("realized_r_house", tr.get("realized_r"))


# ── phase 1: every signal, per symbol (book-independent) ─────────────────────

@dataclass
class SymbolSeries:
    """One symbol's bars + every armed A/A+ signal it ever printed."""
    market: str
    symbol: str
    name: str
    sector: str
    days: np.ndarray                       # int64 days since 1970-01-01, one per bar
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    adv: np.ndarray                        # 20d ADV ending at each bar (NaN = unknown)
    signals: list = field(default_factory=list)   # [(bar j, record)]
    evaluated: int = 0                     # engine calls it took (runtime accounting)

    def iso(self, k: int) -> str:
        return (_EPOCH + dt.timedelta(days=int(self.days[k]))).isoformat()


def _iso_to_int(day: str) -> int:
    return (dt.date.fromisoformat(day) - _EPOCH).days


def symbol_signals(df: pd.DataFrame, market: str, symbol: str, name: str,
                   sector: str) -> SymbolSeries | None:
    """Phase 1. Evaluate the engine on EVERY candidate bar (liquid, near a 200
    SMA) and record each armed, complete plan of an A/A+ row -- independent
    of whether the symbol is held, because in the book that depends on every
    other symbol. A signal on the last bar is skipped (no next open to fill)."""
    if df is None or len(df) < config.VIVEK_MIN_HISTORY + 5:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if market == "crypto" and len(df) and df.index[-1].date() == dt.datetime.now(dt.timezone.utc).date():
        df = df.iloc[:-1]
        if len(df) < config.VIVEK_MIN_HISTORY + 5:
            return None
    n = len(df)
    days = np.array([(ts.date() - _EPOCH).days for ts in df.index], dtype=np.int64)
    s = SymbolSeries(market=market, symbol=symbol, name=name, sector=sector or "", days=days,
                     o=df["Open"].to_numpy(dtype=float), h=df["High"].to_numpy(dtype=float),
                     l=df["Low"].to_numpy(dtype=float), c=df["Close"].to_numpy(dtype=float),
                     adv=_adv_series(df, market))
    cand = _candidate_mask(df)
    turnover = _turnover_series(df, market)
    liq_min = config.MARKETS[market].liquidity_min
    for j in range(config.VIVEK_MIN_HISTORY, n - 1):
        if not (cand[j] and not (turnover[j] < liq_min)):
            continue
        s.evaluated += 1
        try:
            sig = vivek.evaluate(df.iloc[: j + 1])
        except Exception:
            sig = None
        if sig is None:
            continue
        row, plans, grade = _build_row(sig, df.iloc[: j + 1], symbol, name, sector)
        if not row or grade not in ("A+", "A") or not plans:
            continue
        armed = {tf: {k: p.get(k) for k in _PLAN_KEYS}
                 for tf, p in plans.items()
                 if p and p.get("armed")
                 and all(p.get(k) is not None for k in ("stop", "tp1", "tp2", "tp3"))}
        if not armed:
            continue
        s.signals.append((j, {"grade": grade, "dir": row["dir"], "level_tf": row.get("level_tf"),
                              "entry_types": list(row.get("entry_types") or []),
                              "plans": armed}))
    return s


def _series_job(job: tuple):
    """Process-pool entry: (series | None, error text | None)."""
    df, market, symbol, name, sector = job
    try:
        return symbol_signals(df, market, symbol, name, sector), None
    except Exception as e:                     # one bad frame never costs the run
        return None, f"{symbol}: {type(e).__name__}: {e}"


def default_workers() -> int:
    return max(1, os.cpu_count() or 1)


def collect_series(market: str, frames: dict, meta: dict, workers: int = 1) -> list[SymbolSeries]:
    """Phase 1 over a market's frames, in parallel when ``workers`` > 1.

    Each symbol is independent, so this is the one place the replay can use
    more than one core -- it is also where nearly all of its time goes
    (``vivek.evaluate`` on every candidate bar). ``spawn`` rather than
    ``fork``: the download leaves threads behind, and forking a threaded
    process can deadlock. Results come back in input order either way."""
    jobs = [(df, market, (meta.get(yf) or {}).get("symbol", yf),
             (meta.get(yf) or {}).get("name", yf), (meta.get(yf) or {}).get("sector", ""))
            for yf, df in frames.items()]
    out: list[SymbolSeries] = []
    t0 = time.time()
    step = max(1, len(jobs) // 10)

    def take(k: int, res) -> None:
        series, err = res
        if err:
            log.warning("[parity] %s %s", market, err)
        elif series is not None:
            out.append(series)
        if (k + 1) % step == 0 or k + 1 == len(jobs):
            log.info("[parity] %s signals %d/%d symbols (%.1f min)", market, k + 1, len(jobs),
                     (time.time() - t0) / 60)

    if workers > 1 and len(jobs) > 1:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
            for k, res in enumerate(ex.map(_series_job, jobs, chunksize=2)):
                take(k, res)
    else:
        for k, job in enumerate(jobs):
            take(k, _series_job(job))
    return out


# ── phase 2: one chronological book across every market ──────────────────────

def _events(series: list[SymbolSeries], rules: ParityRules) -> list[tuple]:
    """Every fill this rule set would ATTEMPT, sorted the way the book sees
    them: fill date, weekly plans first on a tie (the bot's walk order),
    then symbol. The detection-time filters (grade, side, level gate, cell
    walk, R:R, tradeability on the plan's own levels) are applied here --
    they are the replay's old `continue`s, and none of them reads the book."""
    min_rr = float(getattr(config, "VIVEK_BOT_MIN_RR", 1.5) or 1.5)
    grades = set(rules.allowed_grades())
    allow = rules.level_allow()
    allowed = rules.allowed_entry_types()
    out = []
    for si, s in enumerate(series):
        if not rules.trades_market(s.market):
            continue
        cells = rules.cells_for(s.market)
        for j, rec in s.signals:
            if rec["grade"] not in grades or (rules.long_only and rec["dir"] == "SHORT"):
                continue
            if not level_ok(rec, allow):
                continue
            tf, plan = _choose_plan(rec["plans"], cells, allowed)
            if plan is None or float(plan.get("rr") or 0) < min_rr:
                continue
            if rules.apply_tradeability and _tradeability_ok(
                    float(plan.get("entry") or s.c[j]), float(plan["stop"]), s.market):
                continue
            out.append((int(s.days[j + 1]), 0 if tf == "1W" else 1, s.symbol, s.market,
                        si, j, tf))
    out.sort()
    return out


def _open_at_fill(s: SymbolSeries, j: int, rec: dict, tf: str,
                  rules: ParityRules) -> tuple[dict | None, str | None]:
    """The trade the signal on bar j opens at bar j+1's open, or the gate that
    refused it there (the same checks, in the same order, as the old replay)."""
    plan = rec["plans"][tf]
    k = j + 1
    if not np.isfinite(s.o[k]):
        return None, "no_open"
    row = {"symbol": s.symbol, "name": s.name, "sector": s.sector, "dir": rec["dir"],
           "grade": rec["grade"], "entry_types": rec["entry_types"], "level_tf": rec["level_tf"]}
    tr = _snapshot(row, tf, {**plan, "armed": True}, s.market, float(s.o[k]), s.iso(k))
    if tr is None:
        return None, "no_chase"
    if rules.apply_tradeability:
        code = _tradeability_ok(tr["entry"], tr["stop"], s.market)
        if code:
            return None, code
    adv = None if not np.isfinite(s.adv[j]) else float(s.adv[j])   # known at the prior close
    if rules.apply_adv_gate:
        sz = size_position(EQUITY, tr["entry"], tr["stop"])
        code = _adv_ok(adv, float(sz.get("notional") or 0), s.market)
        if code:
            return None, code
    tr["market"] = s.market
    tr["level_tf"] = rec["level_tf"]
    tr["initial_stop"] = tr["stop"]
    tr["adv_usd"] = adv
    tr["signal_date"] = s.iso(j)
    tr["structural_tps"] = plan.get("structural_tps")
    tr["mfe_r_at"] = {}
    tr["close_r_at"] = {}
    return tr, None


def _run_trade(tr: dict, s: SymbolSeries, k0: int, rules: ParityRules) -> dict:
    """Manage an opened trade bar by bar until it closes (or the data ends)."""
    costs = costs_for(s.market)
    n = len(s.days)
    for k in range(k0, n):
        _manage_parity_bar(tr, float(s.h[k]), float(s.l[k]), float(s.c[k]), s.iso(k), costs,
                           is_last=(k == n - 1), rules=rules, open_=float(s.o[k]))
        if tr["status"] == "closed":
            _stamp_mfe_checkpoints(tr, tr.get("hold_days") or 0, float(s.c[k]))
            break
    tr["cell"] = _cell_of(tr)
    return tr


def run_book(series: list[SymbolSeries], rules: ParityRules | None = None, *,
             max_total: int | None = None, max_sector: int | None = None,
             cooldown: int | None = None) -> dict:
    """Phase 2: walk every attempted fill in date order through ONE book.

    ``max_total`` (default the live global cap) and ``max_sector`` (default
    the live per-market cap; 0 = off) bound the book; ``math.inf`` / 0 give
    the UNCONSTRAINED population (one position per symbol and the cooldown
    still apply -- they are not capacity). A position frees its slot for
    fills dated AFTER its exit (the old sims' rule). A held symbol's further
    signals are not looked at, as live. A stop-out blocks the symbol for
    ``cooldown`` days counted to the SIGNAL bar (the live
    ``_cooldown_symbols`` window). Returns the taken trades and the counts."""
    rules = rules or baseline_rules()
    if max_total is None:
        max_total = int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0) or config.VIVEK_BOT_MAX_POSITIONS)
    if max_sector is None:
        max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    cool = cooldown_days() if cooldown is None else int(cooldown or 0)
    by_j = [{j: rec for j, rec in s.signals} for s in series]

    heap: list[tuple] = []                    # (exit day, seq, key, market, sector key, reason)
    held: set[str] = set()
    sector_count: Counter = Counter()
    cool_until: dict[str, int] = {}
    taken: list[dict] = []
    skips: Counter = Counter()
    gated: Counter = Counter()
    peak = 0
    for seq, (fill_day, _rank, sym, mk, si, j, tf) in enumerate(_events(series, rules)):
        while heap and heap[0][0] < fill_day:
            ex_day, _, key, mkk, sk, reason = heapq.heappop(heap)
            held.discard(key)
            if sk:
                sector_count[(mkk, sk)] -= 1
            if cool and reason == "stop":
                cool_until[key] = max(cool_until.get(key, -1), ex_day + cool)
        key = f"{mk}:{sym}"
        if key in held:
            continue                          # holding it: the bot never looks again
        s = series[si]
        if cool_until.get(key, -1) >= int(s.days[j]):
            skips["cooldown"] += 1
            continue
        tr, code = _open_at_fill(s, j, by_j[si][j], tf, rules)
        if tr is None:
            gated[code] += 1
            continue
        if len(held) >= max_total:
            skips["book_full"] += 1
            continue
        sk = _sector_key(sym, s.sector, mk)
        if max_sector and sk and sector_count[(mk, sk)] >= max_sector:
            skips["sector_cap"] += 1
            continue
        _run_trade(tr, s, j + 1, rules)
        taken.append(tr)
        held.add(key)
        if sk:
            sector_count[(mk, sk)] += 1
        heapq.heappush(heap, (_iso_to_int(tr["exit_date"]), seq, key, mk, sk, tr.get("exit_reason")))
        peak = max(peak, len(held))
    return {"taken": taken, "skipped": dict(skips), "gated": dict(gated), "peak_open": peak,
            "max_open_total": max_total, "max_per_sector": max_sector, "cooldown_days": cool}


def replay_symbol_parity(df: pd.DataFrame, market: str, symbol: str, name: str,
                         sector: str, rules: ParityRules | None = None) -> list[dict]:
    """One symbol through the parity lifecycle with no book capacity limits
    (one position at a time, the cooldown, every gate) -- closed trades."""
    s = symbol_signals(df, market, symbol, name, sector)
    if s is None:
        return []
    return run_book([s], rules, max_total=math.inf, max_sector=0)["taken"]


def _slim_parity(tr: dict) -> dict:
    """The published record: enough to recompute every metric by hand.
    ``stop`` is the INITIAL stop and ``exit`` the exit price (REFINE200 #138);
    ``realized_r_house`` the house-fill twin of ``realized_r`` (#146)."""
    keys = ("symbol", "market", "timeframe", "level_tf", "entry_type", "cell", "grade",
            "direction", "entry", "stop", "stop_final", "risk", "exit", "signal_date",
            "entry_date", "exit_date", "exit_reason", "realized_r", "realized_r_house",
            "gross_r", "cost_r", "mae_r", "mfe_r", "hold_days", "mfe_r_at", "close_r_at",
            "sector", "tp1_hit", "tp2_hit", "tp3_hit", "adv_usd", "taken",
            # the ladder, so a committed trade can be re-managed from its entry
            # (scripts/lens_fill_confluence.py re-simulates fill models from it)
            "tp1", "tp2", "tp3", "scale")
    src = {"stop": ("initial_stop", "stop"), "stop_final": ("stop",),
           "exit": ("exit_price", "exit")}
    out = {k: next((tr[s] for s in src.get(k, (k,)) if tr.get(s) is not None), None) for k in keys}
    if out["cell"] is None and tr.get("timeframe"):
        out["cell"] = _cell_of(tr)
    return out


# ── post-hoc selection over a committed trade list ────────────────────────────
# The replay runs the book LIVE (run_book). These two re-select from a list of
# already-closed trades -- for re-reading a published file -- and so cannot see
# the signals a book refusal would have freed (#150); they apply the same
# gates otherwise, the level gate included (#149).

def _post_hoc_select(trades: list[dict], max_total: int | None = None
                     ) -> tuple[list[dict], list[dict], Counter, int, int]:
    grades = tuple(getattr(config, "VIVEK_BOT_GRADES", ("A+",)) or ("A+",))
    long_only = not getattr(config, "VIVEK_BOT_ALLOW_SHORTS", True)
    max_total = int(max_total if max_total is not None
                    else (getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0)
                          or config.VIVEK_BOT_MAX_POSITIONS))
    max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    cooldown = cooldown_days()
    allow = level_allow()
    elig = [t for t in trades
            if t.get("grade") in grades
            and _in_cell(t.get("timeframe"), t.get("entry_type"))
            and (not long_only or t.get("direction") == "long")
            and level_ok(t, allow)
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
    skips: Counter = Counter()
    peak = 0
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
            taken.append(t)
            peak = max(peak, len(open_pos))
    return elig, taken, skips, peak, max_total


def _taken_list(trades: list[dict]) -> list[dict]:
    """Post-hoc portfolio selection over a closed-trade list (see above)."""
    return _post_hoc_select(trades)[1]


def _portfolio_block(eligible: list[dict], taken: list[dict], skipped: dict, gated: dict,
                     peak_open: int, max_total, max_sector: int, cooldown: int,
                     rules: ParityRules, note: str | None = None) -> dict:
    slot_months, r_psm = _slot_month_stats(taken)
    out = {
        "params": {
            "max_open_total": max_total,
            "max_per_sector": max_sector,
            "cooldown_days": cooldown,
            "long_only": rules.long_only,
            "grades": list(rules.allowed_grades()),
            "level_tf_allow": list(rules.level_allow()),
            "entry_cells": {tf: list(ets) for tf, ets in
                            (dict(rules.cells) if rules.cells is not None else _bot_cells()).items()},
            "market_cells": {mk: {tf: list(ets) for tf, ets in cells}
                             for mk, cells in (rules.market_cells or ())},
            "drop_markets": list(rules.drop_markets),
            "simulated": ["time_stop", "tp_ladder_trail", "one_per_symbol",
                          "global_slot_cap", "sector_cap", "cooldown",
                          "min_price", "stop_width", "adv_gates",
                          "grade_gate", "long_only", "entry_cells", "level_gate",
                          "cell_walk_one_plan", "chronological_book"],
        },
        "eligible": _metrics(eligible),
        "portfolio": _metrics(taken),
        "taken": len(taken),
        "skipped": dict(skipped),
        "gated": dict(gated),
        "peak_open": peak_open,
        "slot_months": slot_months,
        "r_per_slot_month": r_psm,
    }
    if note:
        out["note"] = note
    return out


def portfolio_sim_parity(trades: list[dict], max_total: int | None = None) -> dict:
    """Post-hoc global book over a closed-trade list (see _post_hoc_select)."""
    elig, taken, skips, peak, cap = _post_hoc_select(trades, max_total)
    note = None if elig else "no bot-eligible parity trades"
    return _portfolio_block(elig, taken, skips, {}, peak, cap,
                            int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0),
                            cooldown_days(), baseline_rules(), note)


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
    open_n = 0
    slot_days = 0
    prev = events[0][0]
    i = 0
    while i < len(events):
        d = events[i][0]
        gap = (d - prev).days
        if gap > 0 and open_n > 0:
            slot_days += open_n * gap
        while i < len(events) and events[i][0] == d:
            open_n += events[i][1]
            i += 1
        prev = d
    slot_months = round(slot_days / 30.4375, 4)
    r_psm = round(total_r / slot_months, 4) if slot_months > 0 else None
    return slot_months, r_psm


# ── aggregation / halves / pass criteria ──────────────────────────────────────

def _split_date(trades: list[dict]) -> str | None:
    """The median entry date of `trades` -- the one date both sides of a
    variant comparison are split at."""
    dates = sorted(t["entry_date"] for t in trades if t.get("entry_date"))
    return dates[len(dates) // 2] if dates else None


def _time_half(trades: list[dict], split: str | None = None) -> tuple[list[dict], list[dict]]:
    """(entered before `split`, entered on/after it). `split` defaults to the
    list's OWN median -- pass the baseline's to compare two lists (#151)."""
    dated = [t for t in trades if t.get("entry_date")]
    if split is None:
        split = _split_date(dated)
    if split is None:
        return [], []
    return ([t for t in dated if t["entry_date"] < split],
            [t for t in dated if t["entry_date"] >= split])


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


def _quarter(day: str) -> str:
    return f"{day[:4]}Q{(int(day[5:7]) - 1) // 3 + 1}"


def report_by_slices(trades: list[dict], split: str | None = None) -> dict:
    by_mkt = {mk: _cohort_stats([t for t in trades if t.get("market") == mk])
              for mk in sorted({t.get("market") for t in trades if t.get("market")})}
    cells = sorted({_cell_of(t) for t in trades if t.get("timeframe")})
    split = split or _split_date(trades)
    h1, h2 = _time_half(trades, split)
    # A cell's expectancy quarter by quarter: the evidence a kill threshold
    # on one cell (e.g. 3D reclaim) has to be read against.
    by_cell_quarter: dict = {}
    for t in trades:
        if t.get("timeframe") and t.get("entry_date"):
            by_cell_quarter.setdefault(_cell_of(t), {}).setdefault(
                _quarter(t["entry_date"]), []).append(t)
    return {
        "overall": _cohort_stats(trades),
        "by_market": by_mkt,
        "by_level_tf": {k: _cohort_stats(v) for k, v in
                        ((lt, [t for t in trades if t.get("level_tf") == lt])
                         for lt in LEVEL_TFS)},
        "by_entry_type": {k: _cohort_stats(v) for k, v in
                          ((et, [t for t in trades if t.get("entry_type") == et])
                           for et in sorted({t.get("entry_type") for t in trades if t.get("entry_type")}))},
        "by_cell": {c: _cohort_stats([t for t in trades if _cell_of(t) == c]) for c in cells},
        "by_grade": {g: _cohort_stats([t for t in trades if t.get("grade") == g])
                     for g in ("A+", "A")},
        "by_market_cell": {mk: {c: _cohort_stats([t for t in trades if t.get("market") == mk
                                                  and _cell_of(t) == c]) for c in cells}
                           for mk in by_mkt},
        "by_cell_quarter": {c: {q: {k: m[k] for k in ("n", "expectancy_r", "total_r",
                                                       "expectancy_r_house")}
                                    for q, m in ((q, _metrics(v)) for q, v in sorted(qs.items()))}
                            for c, qs in sorted(by_cell_quarter.items())},
        "by_exit_reason": {k: _cohort_stats(v) for k, v in
                           ((r, [t for t in trades if t.get("exit_reason") == r])
                            for r in sorted({t.get("exit_reason") for t in trades if t.get("exit_reason")}))},
        "time_half": {"first": _cohort_stats(h1), "second": _cohort_stats(h2),
                      "split_entry_date": split},
    }


def variant_passes(baseline_taken: list[dict], variant_taken: list[dict],
                   skip_markets: tuple[str, ...] = ()) -> dict:
    """PASS only if R/slot-month improves overall, on ASX+NASDAQ and on both
    time halves. The halves are split at the BASELINE's median entry date for
    BOTH lists (REFINE200 #151: each list used to split at its own median, so
    a variant that filters entries compared a different calendar window --
    V3_weekly_level split at 2023-12-14 against the baseline's 2024-04-10).
    A market in `skip_markets` (one the variant does not trade) is reported
    and not gated: its R/slot-month is None by construction."""
    pass_mkts = tuple(getattr(config, "VIVEK_PARITY_PASS_MARKETS", ("asx", "nasdaq")))

    def rpsm(trs, pred=None):
        sub = [t for t in trs if pred is None or pred(t)]
        _, v = _slot_month_stats(sub)
        return v

    def check(b, v) -> dict:
        return {"baseline": b, "variant": v,
                "delta": None if b is None or v is None else round(v - b, 4),
                "pass": b is not None and v is not None and v > b}

    checks = {"overall": check(rpsm(baseline_taken), rpsm(variant_taken))}
    ok = checks["overall"]["pass"]
    for mk in pass_mkts:
        c = check(rpsm(baseline_taken, lambda t, m=mk: t.get("market") == m),
                  rpsm(variant_taken, lambda t, m=mk: t.get("market") == m))
        if mk in skip_markets:
            c.update({"pass": None, "note": "the variant does not trade this market"})
        elif not c["pass"]:
            ok = False
        checks[f"market:{mk}"] = c
    split = _split_date(baseline_taken)
    bh1, bh2 = _time_half(baseline_taken, split)
    vh1, vh2 = _time_half(variant_taken, split)
    for label, bt_, vt in (("half:first", bh1, vh1), ("half:second", bh2, vh2)):
        checks[label] = check(rpsm(bt_), rpsm(vt))
        if not checks[label]["pass"]:
            ok = False
    return {"pass": bool(ok), "checks": checks, "split_entry_date": split}


# ── driver ────────────────────────────────────────────────────────────────────

def load_market_series(mk: str, limit: int | None, period: str,
                       exclude_symbols: set[str] | None = None,
                       workers: int = 1) -> tuple[list[SymbolSeries], dict]:
    """Sample a market, price it through data.fetch, run phase 1."""
    from .universe import load_universe

    uni_all = load_universe(mk, full=True)
    if getattr(config, "VIVEK_BOT_EXCLUDE_FUNDS", True):
        uni_all = [u for u in uni_all
                   if not _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")})]
    excl = {str(s).upper() for s in (exclude_symbols or set())}
    uni_before = len(uni_all)
    if excl:
        uni_all = [u for u in uni_all if str(u.get("symbol") or "").upper() not in excl]
        log.info("[parity] %s - excluded %d in-sample symbols (%d remain)",
                 mk, uni_before - len(uni_all), len(uni_all))
    uni = _sample(uni_all, limit)
    log.info("[parity] %s - downloading %d of %d eligible (%s)", mk, len(uni), len(uni_all), period)
    frames, sources = fetch_market_frames(mk, uni, period)
    meta = {u["yf"]: u for u in uni}
    t0 = time.time()
    series = collect_series(mk, frames, meta, workers)
    log.info("[parity] %s - %d symbols, %d signals, %d engine calls in %.1f min",
             mk, len(series), sum(len(s.signals) for s in series),
             sum(s.evaluated for s in series), (time.time() - t0) / 60)
    return series, {
        "symbols": len(uni), "universe": len(uni_all),
        "universe_before_exclude": uni_before,
        "excluded": len(excl),
        "sampled_pct": round(100 * len(uni) / max(len(uni_all), 1), 1),
        "priced": len(frames),
        "replayed": len(series),
        "signals": sum(len(s.signals) for s in series),
        "engine_calls": sum(s.evaluated for s in series),
        "phase1_minutes": round((time.time() - t0) / 60, 2),
        "data_sources": sources,
        "sampled_symbols": [u.get("symbol") for u in uni],
    }


def _published_trades(eligible: list[dict], taken: list[dict]) -> list[dict]:
    """Every unconstrained trade with a `taken` flag, plus any book trade the
    unconstrained run never made (the book's own timing can differ)."""
    def ident(t: dict) -> tuple:
        return (t.get("market"), t.get("symbol"), t.get("entry_date"), t.get("timeframe"))

    taken_ids = {ident(t) for t in taken}
    out = []
    seen = set()
    for t in eligible:
        p = _slim_parity(t)
        p["taken"] = ident(t) in taken_ids
        p.setdefault("mfe_r_at", {})
        p.setdefault("close_r_at", {})
        out.append(p)
        seen.add(ident(t))
    for t in taken:
        if ident(t) not in seen:
            p = _slim_parity(t)
            p["taken"] = True
            out.append(p)
    return out


def _caveats() -> list[str]:
    return [
        "Survivorship bias — today's universe excludes delisted names.",
        data_source_caveat(),
        "Intrabar fills assume the stop fills before the target within a bar. "
        "Stop fill: the headline (realized_r, expectancy_r) books a stop at the "
        "bar's worst print; *_house re-prices the same exits at the stop, or at "
        "the open when the bar gapped through it (the owner's house rule).",
        "Parity mode mirrors the live hc4-1 lifecycle: grades A/A+ (grade_raw), "
        "long-only, the four-cell walk (one plan per symbol), the weekly/3d LEVEL "
        "gate (fail-closed), the 28d pre-TP1 time stop, ADV + tradeability gates "
        "at the fill, the 7-day stop cooldown, the global slot cap and the "
        "per-market sector cap, run as ONE chronological book across markets "
        "(a refused signal leaves its symbol free for the next one). The "
        "earnings buffer and the daily/weekly loss guards are NOT replayed.",
        "Slot contention scales with the universe: a run that samples part of "
        "a market sees only coverage[market].sampled_pct of its signals, so "
        "book_full counts are a LOWER bound unless --limit 0. Read R/trade and "
        "R/slot-month by cell and market.",
        "R units are primary. Dollar columns inherit the live sizing mode "
        f"({_sizing_basis().get('sizing_mode')}) and are secondary.",
        "Variant PASS requires R/slot-month improvement overall, on ASX AND "
        "NASDAQ, and on both time halves split at the BASELINE's median entry "
        "date. Crypto is reported but not a pass gate; a market a variant does "
        "not trade is reported, not gated. Every variant re-runs the book.",
    ]


def build_parity_report(baseline_trades: list[dict], coverage: dict,
                        params: dict, variant_results: dict | None = None,
                        book: dict | None = None) -> dict:
    """The decision pack. `baseline_trades` is the UNCONSTRAINED population;
    `book` the baseline ``run_book`` result. Without `book` (re-reading a
    trade list) the book is re-selected post hoc (see _post_hoc_select)."""
    rules = baseline_rules()
    if book is None:
        elig, taken, skips, peak, cap = _post_hoc_select(baseline_trades)
        port = _portfolio_block(elig, taken, skips, {}, peak, cap,
                                int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0),
                                cooldown_days(), rules)
    else:
        taken = book["taken"]
        port = _portfolio_block(baseline_trades, taken, book["skipped"], book["gated"],
                                book["peak_open"], book["max_open_total"],
                                book["max_per_sector"], book["cooldown_days"], rules)
    published = _published_trades(baseline_trades, taken)
    split = _split_date(taken)
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
                "max_hold_days": rules.resolved_hold(),
                "grades": list(rules.allowed_grades()),
                "long_only": True,
                "level_tf_allow": list(rules.level_allow()),
                "entry_cells": {tf: list(ets) for tf, ets in _bot_cells().items()},
                "max_open_total": int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0)
                                      or config.VIVEK_BOT_MAX_POSITIONS),
                "max_per_sector": int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0),
                "cooldown_days": cooldown_days(),
            },
            "all_signals": report_by_slices(baseline_trades, split),
            "portfolio": port,
            "portfolio_slices": report_by_slices(taken, split),
        },
        "variants": variant_results or {},
        "trades": published,
        "caveats": _caveats(),
    }
    return report


def run_variant_books(series: list[SymbolSeries], base_taken: list[dict]) -> dict:
    """Each one-delta variant re-runs the whole book (phase 2 only)."""
    results = {}
    split = _split_date(base_taken)
    for rules in variant_grid():
        t0 = time.time()
        book = run_book(series, rules)
        taken = book["taken"]
        port = _portfolio_block([], taken, book["skipped"], book["gated"], book["peak_open"],
                                book["max_open_total"], book["max_per_sector"],
                                book["cooldown_days"], rules)
        port.pop("eligible", None)
        exit_rule = rules.max_hold_days is not None or rules.early_cut_day is not None
        results[rules.name] = {
            "delta": _delta_desc(rules),
            "kind": "exit_rule" if exit_rule else "entry_rule",
            "portfolio": port,
            "slices": report_by_slices(taken, split),
            "verdict": variant_passes(base_taken, taken, skip_markets=tuple(rules.drop_markets)),
        }
        log.info("[parity] variant %s: %d taken (%.1fs)", rules.name, len(taken), time.time() - t0)
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
    if rules.name.startswith("V5_"):
        return f"grades {rules.grades}"
    if rules.name.startswith("V6_"):
        return "cells " + ", ".join(f"{tf} {'/'.join(t)}" for tf, t in (rules.cells or ()))
    if rules.name.startswith("V7_"):
        return f"markets except {', '.join(rules.drop_markets)}"
    if rules.name.startswith("V8_"):
        return "; ".join(f"{mk} cells " + ", ".join(f"{tf} {'/'.join(t)}" for tf, t in cells)
                         for mk, cells in (rules.market_cells or ()))
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


def load_exclude_map(path) -> dict[str, set[str]]:
    """Load {market: [symbols]} exclusion file written by a prior parity run."""
    import json
    from pathlib import Path
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "by_market" in raw:
        raw = raw["by_market"]
    out: dict[str, set[str]] = {}
    for mk, syms in (raw or {}).items():
        out[str(mk)] = {str(s).upper() for s in (syms or [])}
    return out


def sample_symbol_map(coverage: dict) -> dict[str, list[str]]:
    return {mk: list(cov.get("sampled_symbols") or [])
            for mk, cov in (coverage or {}).items()}


def run_parity(markets: list[str], limit: int | None, period: str,
               run_variants: bool = True,
               exclude_map: dict[str, set[str]] | None = None,
               tag: str = "parity", workers: int = 1) -> dict:
    t0 = time.time()
    series: list[SymbolSeries] = []
    coverage: dict = {}
    exclude_map = exclude_map or {}
    for mk in markets:
        ss, cov = load_market_series(mk, limit, period, exclude_map.get(mk), workers)
        series += ss
        coverage[mk] = cov
    rules = baseline_rules()
    t1 = time.time()
    book = run_book(series, rules)
    eligible = run_book(series, rules, max_total=math.inf, max_sector=0)["taken"]
    params = {
        "mode": tag,
        "markets": list(markets),
        "limit": limit,
        "period": period,
        "exclude_funds": True,
        "long_only": True,
        "grades": list(rules.allowed_grades()),
        "level_tf_allow": list(rules.level_allow()),
        "time_stop_days": rules.resolved_hold(),
        "mfe_days": list(MFE_DAYS),
        "excluded_counts": {mk: len(exclude_map.get(mk) or []) for mk in markets},
        "workers": workers,
        **_sizing_basis(),
        **replay_params(),
    }
    variant_results = run_variant_books(series, book["taken"]) if run_variants else {}
    report = build_parity_report(eligible, coverage, params, variant_results, book=book)
    report["mode"] = tag
    report["best_variant"] = best_variant(variant_results) if variant_results else {}
    report["sampled_symbols"] = sample_symbol_map(coverage)
    report["runtime_minutes"] = {"total": round((time.time() - t0) / 60, 2),
                                 "phase1": round((t1 - t0) / 60, 2),
                                 "books": round((time.time() - t1) / 60, 2)}
    return report


# ── output ────────────────────────────────────────────────────────────────────

def _fmt_r(v) -> str:
    return "—" if v is None else f"{v:+.3f}"


def _cell_txt(m: dict | None) -> str:
    """'n · expR (house)' for a table cell."""
    if not m or not m.get("n"):
        return "—"
    return f"{m['n']} · {_fmt_r(m.get('expectancy_r'))} ({_fmt_r(m.get('expectancy_r_house'))})"


def summary_markdown(report: dict) -> str:
    """The decision pack as markdown (the workflow's step summary). Prints only
    the report's own numbers; nothing here computes a statistic."""
    b = report.get("baseline") or {}
    port = b.get("portfolio") or {}
    p = report.get("params") or {}
    cov = report.get("coverage") or {}
    variants = report.get("variants") or {}
    lines = ["## VIVEK decision replay (parity, hc4-1)", ""]
    lines.append(f"- markets {', '.join(p.get('markets') or [])}; limit {p.get('limit') or 'all'} "
                 f"per market; period {p.get('period')}; workers {p.get('workers')}")
    for mk, c in cov.items():
        src = (c.get("data_sources") or {}).get("by_source")
        lines.append(f"- {mk}: {c.get('replayed')} replayed of {c.get('symbols')} sampled "
                     f"({c.get('sampled_pct')}% of {c.get('universe')}); "
                     f"{c.get('signals')} signal bars; sources {src}")
    rt = report.get("runtime_minutes") or {}
    if rt:
        lines.append(f"- runtime {rt.get('total')} min (signals {rt.get('phase1')}, "
                     f"books {rt.get('books')})")
    lines += ["", "Cells read `n · expectancy R (house-fill R)`; R/slot-month is the "
              "pass metric. The headline R is the worst-print stop fill.", ""]

    names = ["baseline", *variants]

    def book_of(name):
        return b if name == "baseline" else variants[name]

    def slices(name, key):
        sl = b.get("portfolio_slices") if name == "baseline" else (variants[name].get("slices"))
        return (sl or {}).get(key) or {}

    lines += ["### Overall (book)", "",
              "| rule | delta | taken | expR | expR house | win% | R/slot-month | Δ vs base | peak | book_full | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    base_rpsm = port.get("r_per_slot_month")
    for name in names:
        bk = book_of(name)
        pt = bk.get("portfolio") or {}
        m = pt.get("portfolio") or {}
        rpsm = pt.get("r_per_slot_month")
        d = None if rpsm is None or base_rpsm is None else rpsm - base_rpsm
        ver = "—" if name == "baseline" else ("PASS" if (bk.get("verdict") or {}).get("pass") else "fail")
        lines.append(f"| {name} | {bk.get('delta', 'live rules')} | {pt.get('taken')} | "
                     f"{_fmt_r(m.get('expectancy_r'))} | {_fmt_r(m.get('expectancy_r_house'))} | "
                     f"{m.get('win_rate')} | {_fmt_r(rpsm)} | {_fmt_r(d)} | {pt.get('peak_open')} | "
                     f"{(pt.get('skipped') or {}).get('book_full', 0)} | {ver} |")
    mkts = sorted(cov)
    cells = sorted({c for name in names for c in slices(name, "by_cell")})
    for title, key, cols in (("By market (book)", "by_market", mkts),
                             ("By cell (book)", "by_cell", cells),
                             ("By grade (book)", "by_grade", ["A+", "A"])):
        lines += ["", f"### {title}", "", "| rule | " + " | ".join(cols) + " |",
                  "|---|" + "---|" * len(cols)]
        for name in names:
            sl = slices(name, key)
            lines.append(f"| {name} | " + " | ".join(_cell_txt(sl.get(c)) for c in cols) + " |")
    mc = slices("baseline", "by_market_cell")
    lines += ["", "### Baseline book: market x cell", "", "| market | " + " | ".join(cells) + " |",
              "|---|" + "---|" * len(cells)]
    for mk in mkts:
        lines.append(f"| {mk} | " + " | ".join(_cell_txt((mc.get(mk) or {}).get(c)) for c in cells) + " |")
    allsig = (b.get("all_signals") or {}).get("by_cell") or {}
    lines += ["", "### Every signal the rules would take (no slot cap), by cell", "",
              "| cell | n · expR (house) | R/slot-month |", "|---|---|---|"]
    for c in sorted(allsig):
        lines.append(f"| {c} | {_cell_txt(allsig[c])} | {_fmt_r(allsig[c].get('r_per_slot_month'))} |")
    er = slices("baseline", "by_exit_reason")
    if er:
        lines += ["", "### Baseline book by exit reason", "", "| exit | n · expR (house) |", "|---|---|"]
        for k in sorted(er):
            lines.append(f"| {k} | {_cell_txt(er[k])} |")
    bv = report.get("best_variant") or {}
    lines += ["", f"Best passing variant: {bv.get('name') or 'none'}"
              + (f" ({bv.get('delta_desc')}, Δ R/slot-month {_fmt_r(bv.get('delta'))})"
                 if bv.get("name") else f" -- {bv.get('reason', '')}"), ""]
    lines += ["### Caveats", ""] + [f"- {c}" for c in report.get("caveats") or []] + [""]
    return "\n".join(lines)


def print_parity(report: dict) -> None:
    b = report.get("baseline") or {}
    port = b.get("portfolio") or {}
    pm = port.get("portfolio") or {}
    print("\n=== VIVEK PARITY BACKTEST ===")
    print("params:", report.get("params"))
    print("coverage:", {mk: {k: v for k, v in c.items() if k != "sampled_symbols"}
                        for mk, c in (report.get("coverage") or {}).items()})
    print(f"\nPORTFOLIO n={pm.get('n')}  expR={pm.get('expectancy_r')}  "
          f"house={pm.get('expectancy_r_house')}  "
          f"totR={pm.get('total_r')}  win={pm.get('win_rate')}%  "
          f"R/slot-month={port.get('r_per_slot_month')}  "
          f"slot-months={port.get('slot_months')}  "
          f"taken={port.get('taken')} peak_open={port.get('peak_open')}")
    print("skips:", port.get("skipped"), " gated:", port.get("gated"))
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
              f"R/sm {d.get('baseline')} -> {d.get('variant')}  delta={d.get('delta')}")
    bv = report.get("best_variant") or {}
    print("\nBEST:", bv)

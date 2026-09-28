"""IGNITION replay -- does the coil -> ignition shape carry an edge, and whose?

WHAT IT ANSWERS, in the order a sceptic would ask:

  1. primary      the pre-registered rule (config IGNITION_*): fill at the
                  NEXT open after the trigger close, structural stop, exit on
                  a daily close below the 9-SMA, round-trip costs charged.
  2. baselines    the same exit on the SAME coins at RANDOM times (does the
                  SIGNAL add anything over the exit rule on a survivor list?);
                  the same breakout WITHOUT the coil (does the coil matter?);
                  the coil + breakout WITHOUT volume (does the volume matter?).
  3. out-of-sample  entries before / from IGNITION_BT_SPLIT_DATE, by year, and
                  by BTC's own trend (alt ignitions cluster in alt seasons).
  4. tail dependence  top-5 trades' share of the total, expectancy with the
                  best five removed, a bootstrap band on the mean. A fat-tailed
                  edge that is three trades is a story, not an edge.
  5. exits        trail9 vs trail26 vs a 1R/3R/5R ladder vs half-at-measured-
                  move vs a flat 20-bar hold, same entries -- the ladder is the
                  VIVEK-style cut that booked ~4R of QNT's ~15R.
  6. robustness   one-at-a-time threshold moves and the whole 3^5 grid,
                  summarised as a DISTRIBUTION. Not a menu: choosing the best
                  cell and calling it the rule is the overfit the pre-
                  registration exists to prevent.
  7. cases        named symbols (QNT) trade by trade, plus the rule's own
                  bar-by-bar diagnostics for their most recent 30 bars.

HONEST LIMITS, published inside the payload (`caveats`), not just here:
  * SURVIVORSHIP, and worse than usual for THIS rule: the universe is today's
    CoinGecko top ~200. A coin that pumped INTO it is in, with its pump; one
    that pumped and died OUT of it is not. Long-breakout results are biased
    UP. The random-timing baseline runs on the same survivor list, which is
    why beating IT is the bar, not beating zero.
  * Per-trade R, not a portfolio: overlapping trades across coins are each
    counted at 1R; no capital constraint, no position cap.
  * Yahoo daily crypto bars; thin early history on young coins.
"""

from __future__ import annotations

import datetime as dt
import itertools
import zlib
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from scanner import config

from . import engine as E

SCHEMA_VERSION = 1

EXIT_SPECS = ("trail9", "trail26", "ladder_1_3_5", "half_mm_trail9", "hold_20")
GRID = {
    "rvol_min": (2.0, 3.0, 5.0),
    "ribbon_max": (0.08, 0.12, 0.18),
    "atr_pctl_max": (0.15, 0.25, 0.40),
    "vol_pctl_max": (0.25, 0.35, 0.50),
    "min_drawdown": (0.30, 0.50, 0.70),
}


class Prepared:
    """One symbol's cleaned frame + threshold-free features, computed ONCE."""
    __slots__ = ("symbol", "df", "bf", "o", "h", "lo", "c", "trail9", "trail26",
                 "btc_up")

    def __init__(self, symbol: str, df: pd.DataFrame, market: str,
                 btc_up: Optional[pd.Series] = None):
        self.symbol = symbol
        self.df = df
        self.bf = E.base_features(df, market)
        self.o = df["Open"].to_numpy()
        self.h = df["High"].to_numpy()
        self.lo = df["Low"].to_numpy()
        self.c = df["Close"].to_numpy()
        self.trail9 = self.bf["trail"].to_numpy()
        self.trail26 = df["Close"].rolling(26).mean().to_numpy()
        self.btc_up = (btc_up.reindex(df.index) if btc_up is not None
                       else pd.Series(np.nan, index=df.index))


def _btc_regime(frames: Dict[str, pd.DataFrame]) -> Optional[pd.Series]:
    """1.0 where BTC closed above its 200-SMA, 0.0 below, NaN unknown."""
    btc = frames.get("BTC-USD")
    if btc is None:
        return None
    b = E.clean(btc)
    if len(b) < 200:
        return None
    s = b["Close"].rolling(200).mean()
    up = (b["Close"] > s).astype(float)
    return up.where(s.notna())


def prepare(frames: Dict[str, pd.DataFrame], market: str,
            symbols: Optional[Dict[str, str]] = None) -> List[Prepared]:
    """Clean every frame, drop the too-short, compute base features once."""
    btc = _btc_regime(frames)
    out = []
    for yf in sorted(frames):
        df = E.clean(frames[yf])
        if len(df) < config.IGNITION_MIN_BARS:
            continue
        sym = (symbols or {}).get(yf) or yf.split("-")[0]
        out.append(Prepared(sym, df, market, btc))
    return out


def _ladder(spec: str, entry: float, risk: float, mm: float) -> tuple:
    if spec == "ladder_1_3_5":
        return ((0.25, entry + 1 * risk), (0.50, entry + 3 * risk), (0.15, entry + 5 * risk))
    if spec == "half_mm_trail9":
        # A measured move already under the fill is no target: the trade
        # rides the trail whole rather than "taking profit" at a loss.
        return ((0.50, mm),) if np.isfinite(mm) and mm > entry else ()
    return ()


def trades_for(pr: Prepared, rules: pd.DataFrame, *, exit_spec: str = "trail9",
               stop_spec: str = "struct", cost_pct: Optional[float] = None,
               max_hold: Optional[int] = None) -> List[dict]:
    """Every trade the rule takes on one symbol, one position at a time.

    Entry is the OPEN of the bar after the trigger close -- the first price a
    trader who saw the completed signal could actually get. A next open at or
    below the stop is not a trade (the setup failed before it could be
    entered); it is counted by the caller, never silently dropped.
    """
    cost_pct = config.IGNITION_BT_COST_PCT if cost_pct is None else cost_pct
    max_hold = config.IGNITION_BT_MAX_HOLD if max_hold is None else max_hold
    trig = np.flatnonzero(rules["trigger"].to_numpy())
    stops = rules["stop"].to_numpy() if stop_spec == "struct" else pr.bf["base_low"].to_numpy()
    mm = rules["mm_target"].to_numpy()
    trail = {"trail26": pr.trail26, "hold_20": np.full(len(pr.c), np.nan)}.get(exit_spec, pr.trail9)
    hold = 20 if exit_spec == "hold_20" else max_hold
    n = len(pr.c)
    out: List[dict] = []
    free_from = 0
    for t0 in trig:
        if t0 < free_from or t0 + 1 >= n:
            continue
        entry, stop = float(pr.o[t0 + 1]), float(stops[t0])
        if not (np.isfinite(entry) and np.isfinite(stop)) or stop <= 0:
            continue
        if entry <= stop:
            out.append({"symbol": pr.symbol, "skipped": "gap_below_stop",
                        "trigger_date": E._date(pr.df.index[t0])})
            continue
        risk = entry - stop
        sim = E.simulate(pr.o, pr.h, pr.lo, pr.c, trail, start=t0 + 1, entry=entry,
                         stop=stop, ladder=_ladder(exit_spec, entry, risk, mm[t0]),
                         max_hold=hold)
        cost_r = (cost_pct / 100.0) * entry / risk
        r = pr.bf.iloc[t0]
        btc = pr.btc_up.iloc[t0]
        out.append({
            "symbol": pr.symbol,
            "trigger_date": E._date(pr.df.index[t0]),
            "entry_date": E._date(pr.df.index[t0 + 1]),
            "exit_date": E._date(pr.df.index[sim["exit_bar"]]),
            "entry": entry, "stop": stop,
            "risk_pct": round(risk / entry * 100, 2),
            "reason": sim["reason"],
            "gross_r": round(sim["gross_r"], 4),
            "cost_r": round(cost_r, 4),
            "net_r": round(sim["gross_r"] - cost_r, 4),
            "mfe_r": round(sim["mfe_r"], 3),
            "mae_r": round(sim["mae_r"], 3),
            "bars": sim["bars"],
            "rvol": round(float(r["rvol"]), 2) if np.isfinite(r["rvol"]) else None,
            "ext_pct": round(float(r["ext"]) * 100, 1) if np.isfinite(r["ext"]) else None,
            "btc_up": None if not np.isfinite(btc) else bool(btc),
        })
        free_from = sim["exit_bar"] + 1
    return out


def random_timing(prepared: List[Prepared], real: List[dict], *, draws: int,
                  seed: int) -> List[dict]:
    """For every real trade, `draws` entries on the SAME coin at random bars,
    with the SAME risk % and the SAME trail exit. Seeded per symbol (crc32),
    so the baseline is identical on every re-run of the same data."""
    by_sym = {pr.symbol: pr for pr in prepared}
    out: List[dict] = []
    for t in real:
        pr = by_sym.get(t["symbol"])
        if pr is None:
            continue
        # Eligible: every input the rule reads exists, and a next open exists.
        ok = np.flatnonzero(pr.bf["base_high"].notna().to_numpy()
                            & pr.bf["trail"].notna().to_numpy())
        ok = ok[ok + 1 < len(pr.c)]
        if not len(ok):
            continue
        rng = np.random.default_rng(seed + zlib.crc32(
            f"{t['symbol']}|{t['trigger_date']}".encode()))
        for t0 in rng.choice(ok, size=draws, replace=True):
            entry = float(pr.o[t0 + 1])
            stop = entry * (1 - t["risk_pct"] / 100.0)
            risk = entry - stop
            if not (risk > 0):
                continue
            sim = E.simulate(pr.o, pr.h, pr.lo, pr.c, pr.trail9, start=t0 + 1,
                             entry=entry, stop=stop, max_hold=config.IGNITION_BT_MAX_HOLD)
            cost_r = (config.IGNITION_BT_COST_PCT / 100.0) * entry / risk
            out.append({"symbol": t["symbol"], "entry_date": E._date(pr.df.index[t0 + 1]),
                        "exit_date": E._date(pr.df.index[sim["exit_bar"]]),
                        "reason": sim["reason"], "net_r": round(sim["gross_r"] - cost_r, 4),
                        "bars": sim["bars"]})
    return out


def stats(trades: List[dict], *, key: str = "net_r", boot: int = 0,
          seed: int = 0) -> dict:
    """Everything a fat-tailed R distribution needs said about it."""
    rs = np.array([t[key] for t in trades if t.get(key) is not None
                   and np.isfinite(t[key])], dtype=float)
    n = int(len(rs))
    skipped = sum(1 for t in trades if t.get("skipped"))
    if n == 0:
        return {"n": 0, "skipped": skipped}
    pos, neg = rs[rs > 0], rs[rs <= 0]
    order = sorted(range(len(trades)), key=lambda i: trades[i].get("exit_date") or "")
    seq = np.array([trades[i][key] for i in order if trades[i].get(key) is not None
                    and np.isfinite(trades[i][key])], dtype=float)
    eq = np.cumsum(seq)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    top = np.sort(rs)[::-1]
    total = float(rs.sum())
    out = {
        "n": n, "skipped": skipped,
        "wins": int(len(pos)), "win_pct": round(100.0 * len(pos) / n, 1),
        "exp_r": round(float(rs.mean()), 3),
        "median_r": round(float(np.median(rs)), 3),
        "total_r": round(total, 2),
        "pf": round(float(pos.sum() / -neg.sum()), 2) if neg.sum() < 0 else None,
        "avg_win_r": round(float(pos.mean()), 3) if len(pos) else None,
        "avg_loss_r": round(float(neg.mean()), 3) if len(neg) else None,
        "pct_ge_3r": round(100.0 * float((rs >= 3).mean()), 1),
        "pct_ge_5r": round(100.0 * float((rs >= 5).mean()), 1),
        "pct_ge_10r": round(100.0 * float((rs >= 10).mean()), 1),
        "max_r": round(float(rs.max()), 2),
        "top5_share_pct": (round(100.0 * float(top[:5].sum()) / total, 1)
                           if total > 0 else None),
        "exp_r_ex_top5": (round(float(top[5:].mean()), 3) if n > 5 else None),
        "max_dd_r": round(float((eq - peak).min()), 2) if len(eq) else 0.0,
        "avg_bars": round(float(np.mean([t["bars"] for t in trades if "bars" in t])), 1),
        "stop_pct": round(100.0 * sum(1 for t in trades if t.get("reason") == "stop") / n, 1),
        "open_at_end": sum(1 for t in trades if t.get("reason") == "open"),
    }
    if boot and n >= 5:
        rng = np.random.default_rng(seed)
        means = rng.choice(rs, size=(int(boot), n), replace=True).mean(axis=1)
        out["exp_r_ci90"] = [round(float(np.percentile(means, 5)), 3),
                             round(float(np.percentile(means, 95)), 3)]
        out["p_exp_le_0"] = round(float((means <= 0).mean()), 3)
    return out


def _group(trades: List[dict], keyfn) -> dict:
    groups: Dict[str, List[dict]] = {}
    for t in trades:
        if t.get("skipped"):
            continue
        groups.setdefault(keyfn(t), []).append(t)
    return {k: stats(v) for k, v in sorted(groups.items())}


def _rules_for(prepared: List[Prepared], p: E.Params) -> List[pd.DataFrame]:
    return [E.apply_rules(pr.bf, p) for pr in prepared]


def run_all(prepared: List[Prepared], p: E.Params, rules=None, **kw) -> List[dict]:
    rules = rules if rules is not None else _rules_for(prepared, p)
    out: List[dict] = []
    for pr, ru in zip(prepared, rules):
        out.extend(trades_for(pr, ru, **kw))
    return out


def _case(pr: Prepared, rules: pd.DataFrame, trades: List[dict], bars: int = 30) -> dict:
    """A named symbol's trades plus the rule's own reading of its last bars --
    so "did it catch QNT, and if not, which leg failed?" is read, not guessed."""
    tail = pr.bf.join(rules).iloc[-bars:]
    rows = []
    for idx, r in tail.iterrows():
        rows.append({
            "date": E._date(idx), "close": E._f(r["close"], 6),
            "ribbon_pct": E._f(r["ribbon"] * 100, 1), "atr_pctl": E._f(r["atr_rank"] * 100, 0),
            "vol_pctl": E._f(r["vol_rank"] * 100, 0), "drawdown_pct": E._f(r["drawdown"] * 100, 0),
            "coiled": bool(r["coiled"]), "coil_window": bool(r["coil_window"]),
            "base_high": E._f(r["base_high"], 6), "breakout": bool(r["breakout"]),
            "rvol": E._f(r["rvol"], 2), "ext_pct": E._f(r["ext"] * 100, 1),
            "turnover_base": E._f(r["turnover_base"], 0), "turnover_day": E._f(r["turnover_day"], 0),
            "trigger": bool(r["trigger"]),
        })
    return {"trades": [t for t in trades if t["symbol"] == pr.symbol and not t.get("skipped")],
            "recent_bars": rows}


def backtest(frames: Dict[str, pd.DataFrame], market: str, *,
             symbols: Optional[Dict[str, str]] = None,
             universe_size: Optional[int] = None,
             now: Optional[dt.datetime] = None) -> dict:
    """The whole replay -> one publishable payload. Deterministic given the
    frames: every random draw is seeded, no clock is read except `now`."""
    p = E.Params.from_config(market)
    prepared = prepare(frames, market, symbols)
    split = config.IGNITION_BT_SPLIT_DATE
    seed = int(config.IGNITION_BT_SEED)

    rules = _rules_for(prepared, p)
    primary = run_all(prepared, p, rules)
    taken = [t for t in primary if not t.get("skipped")]

    exits = {spec: stats(run_all(prepared, p, rules, exit_spec=spec)) for spec in EXIT_SPECS}
    stops = {"struct": stats(primary),
             "floor": stats(run_all(prepared, p, rules, stop_spec="floor"))}
    cost_x2 = stats(run_all(prepared, p, rules, cost_pct=2 * config.IGNITION_BT_COST_PCT))
    rand = random_timing(prepared, taken, draws=int(config.IGNITION_BT_RANDOM_DRAWS), seed=seed)
    baselines = {
        "random_timing": stats(rand, boot=int(config.IGNITION_BT_BOOTSTRAP), seed=seed),
        "breakout_only": stats(run_all(prepared, p.replace(require_coil=False)),
                               boot=int(config.IGNITION_BT_BOOTSTRAP), seed=seed),
        "no_rvol": stats(run_all(prepared, p.replace(require_rvol=False))),
    }

    # Robustness: one-at-a-time, then the whole grid as a distribution.
    oat = []
    for name, values in GRID.items():
        for v in values:
            q = p.replace(**{name: v})
            s = stats(run_all(prepared, q))
            oat.append({"param": name, "value": v, "default": v == getattr(p, name),
                        "n": s["n"], "exp_r": s.get("exp_r"), "pf": s.get("pf"),
                        "median_r": s.get("median_r")})
    cells = []
    for combo in itertools.product(*GRID.values()):
        q = p.replace(**dict(zip(GRID.keys(), combo)))
        s = stats(run_all(prepared, q))
        if s["n"]:
            cells.append((s["n"], s["exp_r"]))
    exps = np.array([e for _, e in cells]) if cells else np.array([])
    grid = {
        "cells": int(np.prod([len(v) for v in GRID.values()])),
        "cells_with_trades": len(cells),
        "exp_r_min": round(float(exps.min()), 3) if len(exps) else None,
        "exp_r_median": round(float(np.median(exps)), 3) if len(exps) else None,
        "exp_r_max": round(float(exps.max()), 3) if len(exps) else None,
        "pct_cells_positive": round(100.0 * float((exps > 0).mean()), 1) if len(exps) else None,
        "n_median": int(np.median([n for n, _ in cells])) if cells else 0,
    }

    by_sym = {pr.symbol: (pr, ru) for pr, ru in zip(prepared, rules)}
    cases = {s: _case(*by_sym[s], primary) for s in config.IGNITION_BT_CASES if s in by_sym}

    starts = [pr.df.index[0] for pr in prepared]
    ends = [pr.df.index[-1] for pr in prepared]
    now = now or dt.datetime.now(dt.timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "lens": "ignition",
        "market": market,
        "generated_at": now.isoformat(timespec="seconds"),
        "ruleset_version": config.IGNITION_RULESET_VERSION,
        "period": config.IGNITION_BT_PERIOD,
        "universe": universe_size,
        "with_data": len(frames),
        "symbols_replayed": len(prepared),
        "date_range": [E._date(min(starts)), E._date(max(ends))] if prepared else None,
        "params": p.as_dict(),
        "pre_registered": {
            "entry": "next open after the trigger close",
            "stop": "max(base low, base high - %.1f x ATR(t-1)), intrabar"
                    % config.IGNITION_STOP_ATR_MULT,
            "exit": "next open after a daily close below the %d-SMA" % config.IGNITION_TRAIL_SMA,
            "cost_pct_round_trip": config.IGNITION_BT_COST_PCT,
            "max_hold_bars": config.IGNITION_BT_MAX_HOLD,
            "split_date": split,
            "registered": "2026-09-28, before the first run",
        },
        "caveats": [
            "SURVIVORSHIP: today's top ~200 coins only. Coins that pumped INTO the list are "
            "included with their pump; coins that pumped and died OUT of it are missing. "
            "Long-breakout results are biased UP -- judge against random_timing, not zero.",
            "Per-trade R, not a portfolio: overlapping trades are each counted at 1R, with no "
            "capital constraint or position cap.",
            "Yahoo daily crypto bars; young coins have thin early history.",
            "The sensitivity grid is a robustness read, not a menu: its best cell is in-sample.",
        ],
        "primary": {
            **stats(primary, boot=int(config.IGNITION_BT_BOOTSTRAP), seed=seed),
            "by_split": _group(primary, lambda t: "in_sample" if t["entry_date"] < split
                               else "out_of_sample"),
            "by_year": _group(primary, lambda t: t["entry_date"][:4]),
            "by_btc_regime": _group(primary, lambda t: {True: "btc_above_200",
                                                        False: "btc_below_200"}.get(
                                                            t.get("btc_up"), "unknown")),
        },
        "exits": exits,
        "stops": stops,
        "cost_stress": {"x2": cost_x2},
        "baselines": baselines,
        "sensitivity": {"one_at_a_time": oat, "full_grid": grid},
        "cases": cases,
        "trades": sorted(taken, key=lambda t: (t["entry_date"], t["symbol"])),
    }


def summary_lines(payload: dict) -> List[str]:
    """The printed read (ASCII only). Written for a step summary."""
    P, B = payload.get("primary") or {}, payload.get("baselines") or {}
    sp = (P.get("by_split") or {})
    lines = [
        f"IGNITION backtest [{payload.get('market')}] ruleset {payload.get('ruleset_version')}"
        f" - {payload.get('symbols_replayed')} coins, {payload.get('date_range')}",
        f"primary (pre-registered): n={P.get('n')} win={P.get('win_pct')}% "
        f"exp={P.get('exp_r')}R median={P.get('median_r')}R PF={P.get('pf')} "
        f"CI90={P.get('exp_r_ci90')} top5={P.get('top5_share_pct')}% "
        f"ex-top5={P.get('exp_r_ex_top5')}R maxDD={P.get('max_dd_r')}R",
        f"  in-sample: {_brief(sp.get('in_sample'))}   out-of-sample: {_brief(sp.get('out_of_sample'))}",
        f"random timing (same coins, same exit): {_brief(B.get('random_timing'))}",
        f"breakout only (no coil): {_brief(B.get('breakout_only'))}",
        f"no volume confirmation: {_brief(B.get('no_rvol'))}",
    ]
    for k, v in (payload.get("exits") or {}).items():
        lines.append(f"exit {k}: {_brief(v)}")
    g = (payload.get("sensitivity") or {}).get("full_grid") or {}
    lines.append(f"grid {g.get('cells_with_trades')}/{g.get('cells')} cells: exp min/med/max "
                 f"{g.get('exp_r_min')}/{g.get('exp_r_median')}/{g.get('exp_r_max')}R, "
                 f"{g.get('pct_cells_positive')}% positive")
    for sym, case in (payload.get("cases") or {}).items():
        tr = case.get("trades") or []
        last = tr[-1] if tr else None
        lines.append(f"case {sym}: {len(tr)} trade(s)"
                     + (f"; last {last['trigger_date']} -> {last['reason']} {last['net_r']}R"
                        if last else ""))
    return lines


def _brief(s: Optional[dict]) -> str:
    if not s or not s.get("n"):
        return "n=0"
    return (f"n={s['n']} exp={s.get('exp_r')}R med={s.get('median_r')}R "
            f"PF={s.get('pf')} win={s.get('win_pct')}%")

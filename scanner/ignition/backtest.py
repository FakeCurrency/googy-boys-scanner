"""IGNITION replay -- does the coil -> ignition shape carry an edge, and whose?

WHAT IT ANSWERS, in the order a sceptic would ask:

  1. primary      the pre-registered rule (config IGNITION_*): fill at the
                  NEXT open after the trigger close, structural stop, exit on
                  a daily close below the 9-SMA, round-trip costs charged.
  2. baselines    the same exit on the SAME coin, in the SAME season (within
                  IGNITION_BT_RANDOM_WINDOW bars of the real trigger), on a
                  random bar the rule COULD have traded (does the SIGNAL add
                  anything over the exit rule, on a survivor list, in that
                  regime?); the same breakout WITHOUT the coil (does the coil
                  matter?); the coil + breakout WITHOUT volume. Each is
                  compared with the primary by a DIFFERENCE statistic -- the
                  decision number -- not by two means side by side.
  3. periods      entries before / from IGNITION_BT_SPLIT_DATE, the FORWARD
                  bucket (from the registration date: the only data no one had
                  seen), by year, by BTC's own trend.
  4. tail dependence  top-5 trades' share of the total, expectancy with the
                  best five removed, a CLUSTER bootstrap band (entry months
                  resampled whole: alt ignitions bunch in alt seasons, so
                  trades are not independent and an iid band is too narrow).
  5. exits        trail9 vs trail26 vs a 1R/3R/5R ladder vs half-at-measured-
                  move vs a flat 20-bar hold, on EXACTLY the primary's entries
                  -- the ladder is the VIVEK-style cut that booked ~4R of
                  QNT's ~15R.
  6. robustness   one-at-a-time threshold moves and the whole 3^5 grid,
                  summarised as a DISTRIBUTION over cells with enough trades.
                  Not a menu: choosing the best cell and calling it the rule is
                  the overfit the pre-registration exists to prevent.
  7. cases        named symbols (QNT) trade by trade, plus the rule's own
                  bar-by-bar diagnostics for their most recent 30 bars.

WHAT IS SCORED (audit, 2026-09-28 -- each rule here closes a finding):
  * REALISED trades only. A trade still open at the end of the data, or whose
    trail exit is still pending, is a MARK, not a result: counting it made the
    headline move with one coin's price every day. Open trades are published
    beside the stats (`open`, `open_mtm_r`), never inside them.
  * Never the DESIGN CASES (config IGNITION_BT_DESIGN_CASES): QNT's Sep-2026
    move informed the thresholds, so it is reported under `cases` and nowhere
    else.

HONEST LIMITS, published inside the payload (`caveats`), not just here:
  * SURVIVORSHIP, and worse than usual for THIS rule: the universe is today's
    CoinGecko top ~200. A coin that pumped INTO it is in, with its pump; one
    that pumped and died OUT of it is not. Long-breakout results are biased
    UP. The random-timing baseline runs on the same survivor list, which is
    why beating IT is the bar, not beating zero.
  * Per-trade R, not a portfolio: overlapping trades across coins are each
    counted at 1R; no capital constraint, no position cap.
  * Daily bars from whichever venue served each coin (`data_note`, and the
    `sources` block run.py adds); thin early history on young coins.
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

SCHEMA_VERSION = 2

EXIT_SPECS = ("trail9", "trail26", "ladder_1_3_5", "half_mm_trail9", "hold_20")
EXIT_DESCRIPTIONS = {
    "trail9": "PRIMARY: all out at the next open after a daily close below the 9-SMA",
    "trail26": "all out at the next open after a daily close below the 26-SMA",
    "ladder_1_3_5": "25% at +1R, 50% at +3R, 15% at +5R; the last 10% rides the 9-SMA trail",
    "half_mm_trail9": "50% at the measured move (when it is above the fill); the rest rides the 9-SMA trail",
    "hold_20": "no trail: out at the close of the 20th bar held (the stop still applies)",
}
GRID = {
    "rvol_min": (2.0, 3.0, 5.0),
    "ribbon_max": (0.08, 0.12, 0.18),
    "atr_pctl_max": (0.15, 0.25, 0.40),
    "vol_pctl_max": (0.25, 0.35, 0.50),
    "min_drawdown": (0.30, 0.50, 0.70),
}


class Prepared:
    """One symbol's cleaned frame + threshold-free features, computed ONCE."""
    __slots__ = ("symbol", "market", "df", "bf", "o", "h", "lo", "c", "trail9", "trail26",
                 "btc_up")

    def __init__(self, symbol: str, df: pd.DataFrame, market: str,
                 btc_up: Optional[pd.Series] = None):
        self.symbol = symbol
        self.market = market
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


def _btc_regime(frames: Dict[str, pd.DataFrame],
                market: str = "crypto") -> Optional[pd.Series]:
    """1.0 where the market's regime index (BTC for crypto, the ASX 200 for
    the ASX -- config.IGNITION_REGIME_INDEX) closed above its 200-SMA, 0.0
    below, NaN unknown. The name is historical: crypto came first."""
    idx = (config.IGNITION_REGIME_INDEX.get(market) or ("BTC-USD", "BTC"))[0]
    btc = frames.get(idx)
    if btc is None:
        return None
    b = E.clean(btc)
    if len(b) < 200:
        return None
    s = b["Close"].rolling(200).mean()
    up = (b["Close"] > s).astype(float)
    return up.where(s.notna())


def prepare(frames: Dict[str, pd.DataFrame], market: str,
            symbols: Optional[Dict[str, str]] = None,
            regime: Optional[pd.DataFrame] = None) -> List[Prepared]:
    """Clean every frame, drop the too-short, compute base features once.

    `regime` is the market's regime-index frame when it is NOT one of the
    screened frames (the ASX 200 is fetched beside the universe, never
    replayed); crypto's BTC is read out of `frames` itself.

    A symbol whose turnover NEVER clears both floors on the same bar is
    dropped here: no rule variant, baseline or grid cell can trade it (none
    of them moves a floor), so replaying it only costs time -- and the ASX
    universe is ~2,000 names, most of them too thin for either floor."""
    idx = (config.IGNITION_REGIME_INDEX.get(market) or ("BTC-USD", "BTC"))[0]
    btc = _btc_regime({**frames, **({idx: regime} if regime is not None else {})}, market)
    p = E.Params.from_config(market)
    out = []
    min_bars = E.bars(market, "IGNITION_MIN_BARS")
    for yf in sorted(frames):
        if yf == idx and market != "crypto":
            continue
        df = E.clean(frames[yf])
        if len(df) < min_bars:
            continue
        if market != "crypto" and not _ever_liquid(df, market, p):
            continue
        sym = (symbols or {}).get(yf) or yf.split("-")[0]
        out.append(Prepared(sym, df, market, btc))
    return out


def _ever_liquid(df: pd.DataFrame, market: str, p: E.Params) -> bool:
    """Does any bar clear BOTH turnover floors (the rule's own definitions)?"""
    dv = E.dollar_volume(df, market)
    base = dv.shift(1).rolling(config.IGNITION_RVOL_LEN,
                               min_periods=config.IGNITION_RVOL_LEN).mean()
    return bool(((base >= p.min_base_turnover) & (dv >= p.min_trigger_turnover)).any())


def _ladder(spec: str, entry: float, risk: float, mm: float) -> tuple:
    if spec == "ladder_1_3_5":
        return ((0.25, entry + 1 * risk), (0.50, entry + 3 * risk), (0.15, entry + 5 * risk))
    if spec == "half_mm_trail9":
        # A measured move already under the fill is no target: the trade
        # rides the trail whole rather than "taking profit" at a loss.
        return ((0.50, mm),) if np.isfinite(mm) and mm > entry else ()
    return ()


def design_cases(market: str) -> dict:
    """{symbol: first excluded trigger date} for this market."""
    over = getattr(config, "IGNITION_BT_DESIGN_CASES_BY_MARKET", {}) or {}
    if market in over:
        return dict(over[market] or {})
    return dict(getattr(config, "IGNITION_BT_DESIGN_CASES", {}) or {})


def is_design_case(t: dict) -> bool:
    """A trade the thresholds were drawn from -- never scored (see config)."""
    first = design_cases(t.get("_mkt") or "crypto").get(t.get("symbol"))
    return first is not None and (t.get("trigger_date") or "") >= first


def scored(trades: List[dict]) -> List[dict]:
    return [t for t in trades if not is_design_case(t)]


def trades_for(pr: Prepared, rules: pd.DataFrame, *, exit_spec: str = "trail9",
               stop_spec: str = "struct", cost_pct: Optional[float] = None,
               max_hold: Optional[int] = None,
               entries: Optional[List[int]] = None) -> List[dict]:
    """Every trade the rule takes on one symbol.

    Entry is the OPEN of the bar after the trigger close -- the first price a
    trader who saw the completed signal could actually get. A next open at or
    below the stop is not a trade (the setup failed before it could be
    entered); it is returned as a `skipped` row, never silently dropped.

    One position at a time, UNLESS `entries` (trigger bars) is given: then
    exactly those triggers are traded, whatever this exit would have
    overlapped -- which is how every exit variant is measured on the primary's
    own entries rather than on a set its own holding period chose.

    A trigger on a bar the live screen could not have seen (fewer than
    IGNITION_MIN_BARS completed bars) is not a trade: the page and the
    evidence must describe the same population.
    """
    cost_pct = E.mkt(pr.market, "IGNITION_BT_COST_PCT") if cost_pct is None else cost_pct
    max_hold = E.bars(pr.market, "IGNITION_BT_MAX_HOLD") if max_hold is None else max_hold
    fixed = entries is not None
    trig = (np.asarray(sorted(entries), dtype=int) if fixed
            else np.flatnonzero(rules["trigger"].to_numpy()))
    stops = rules["stop"].to_numpy() if stop_spec == "struct" else pr.bf["base_low"].to_numpy()
    mm = rules["mm_target"].to_numpy()
    trail = {"trail26": pr.trail26, "hold_20": np.full(len(pr.c), np.nan)}.get(exit_spec, pr.trail9)
    hold = 20 if exit_spec == "hold_20" else max_hold
    n = len(pr.c)
    min_t0 = E.bars(pr.market, "IGNITION_MIN_BARS") - 1
    out: List[dict] = []
    free_from = 0
    for t0 in trig:
        t0 = int(t0)
        if t0 < min_t0 or t0 + 1 >= n or (not fixed and t0 < free_from):
            continue
        entry, stop = float(pr.o[t0 + 1]), float(stops[t0])
        if not (np.isfinite(entry) and np.isfinite(stop)) or stop <= 0:
            continue
        if entry <= stop:
            out.append({"symbol": pr.symbol, "skipped": "gap_below_stop", "_t0": t0,
                        "_mkt": pr.market,
                        "trigger_date": E._date(pr.df.index[t0])})
            continue
        risk = entry - stop
        sim = E.simulate(pr.o, pr.h, pr.lo, pr.c, trail, start=t0 + 1, entry=entry,
                         stop=stop, ladder=_ladder(exit_spec, entry, risk, mm[t0]),
                         max_hold=hold)
        cost_r = E.round_trip_cost_r(cost_pct, entry, risk)   # the live row's too
        r = pr.bf.iloc[t0]
        btc = pr.btc_up.iloc[t0]
        out.append({
            "symbol": pr.symbol,
            "_t0": t0,
            "_mkt": pr.market,
            "trigger_date": E._date(pr.df.index[t0]),
            "entry_date": E._date(pr.df.index[t0 + 1]),
            "exit_date": E._date(pr.df.index[sim["exit_bar"]]),
            "entry": entry, "stop": stop,
            "risk_pct": round(risk / entry * 100, 2),
            "reason": sim["reason"],
            "pending": bool(sim["pending"]),
            "gross_r": round(sim["gross_r"], 4),
            "cost_r": round(cost_r, 4),
            "net_r": round(sim["gross_r"] - cost_r, 4),
            "mfe_r": round(sim["mfe_r"], 3),
            "mae_r": round(sim["mae_r"], 3),
            "bars": sim["bars"],
            "rvol": round(float(r["rvol"]), 2) if np.isfinite(r["rvol"]) else None,
            "ext_pct": round(float(r["ext"]) * 100, 1) if np.isfinite(r["ext"]) else None,
            ("btc_up" if pr.market == "crypto" else "index_up"):
                None if not np.isfinite(btc) else bool(btc),
        })
        free_from = sim["exit_bar"] + 1
    return out


def eligible_bars(pr: Prepared, p: E.Params) -> np.ndarray:
    """Bars the rule COULD have traded, minus the signal itself: every input
    exists, both turnover floors pass, the live screen could see the bar, and
    a next open exists. The random-timing baseline draws only from these --
    drawing from a coin's launch year or its illiquid stretches would compare
    the rule with regimes it never trades."""
    bf = pr.bf
    ok = (bf["ribbon"].notna() & bf["atr_rank"].notna() & bf["vol_rank"].notna()
          & bf["drawdown"].notna() & bf["base_high"].notna() & bf["rvol"].notna()
          & bf["ext"].notna() & bf["trail"].notna()
          & (bf["turnover_base"] >= p.min_base_turnover)
          & (bf["turnover_day"] >= p.min_trigger_turnover)).to_numpy()
    idx = np.flatnonzero(ok)
    return idx[(idx >= E.bars(pr.market, "IGNITION_MIN_BARS") - 1) & (idx + 1 < len(pr.c))]


def random_timing(prepared: List[Prepared], real: List[dict], *, draws: int,
                  seed: int, p: Optional[E.Params] = None,
                  window: Optional[int] = None) -> List[dict]:
    """For every real trade, `draws` entries on the SAME coin at random
    ELIGIBLE bars within +/- `window` bars of its trigger (same season), with
    the SAME risk % and the SAME trail exit. Seeded per trade (crc32), so the
    baseline is identical on every re-run of the same data. `window=0` draws
    from the coin's whole eligible history (reported as random_timing_any)."""
    mk = prepared[0].market if prepared else "crypto"
    window = E.bars(mk, "IGNITION_BT_RANDOM_WINDOW") if window is None else window
    cost = float(E.mkt(mk, "IGNITION_BT_COST_PCT"))
    hold = E.bars(mk, "IGNITION_BT_MAX_HOLD")
    by_sym = {pr.symbol: pr for pr in prepared}
    elig: Dict[str, np.ndarray] = {}
    out: List[dict] = []
    for t in real:
        if t.get("skipped"):
            continue
        pr = by_sym.get(t["symbol"])
        if pr is None:
            continue
        if pr.symbol not in elig:
            elig[pr.symbol] = eligible_bars(pr, p or E.Params.from_config(pr.market))
        ok = elig[pr.symbol]
        if window and "_t0" in t:
            near = ok[np.abs(ok - int(t["_t0"])) <= window]
            ok = near if len(near) else ok
        if not len(ok):
            continue
        rng = np.random.default_rng(seed + zlib.crc32(
            f"{t['symbol']}|{t['trigger_date']}".encode()))
        for t0 in rng.choice(ok, size=draws, replace=True):
            t0 = int(t0)
            entry = float(pr.o[t0 + 1])
            stop = entry * (1 - t["risk_pct"] / 100.0)
            risk = entry - stop
            if not (risk > 0):
                continue
            sim = E.simulate(pr.o, pr.h, pr.lo, pr.c, pr.trail9, start=t0 + 1,
                             entry=entry, stop=stop, max_hold=hold)
            cost_r = E.round_trip_cost_r(cost, entry, risk)
            out.append({"symbol": t["symbol"], "_t0": t0, "_mkt": pr.market,
                        "trigger_date": E._date(pr.df.index[t0]),
                        "entry_date": E._date(pr.df.index[t0 + 1]),
                        "exit_date": E._date(pr.df.index[sim["exit_bar"]]),
                        "reason": sim["reason"], "pending": bool(sim["pending"]),
                        "net_r": round(sim["gross_r"] - cost_r, 4),
                        "bars": sim["bars"]})
    return out


def _realised(t: dict) -> bool:
    return not t.get("skipped") and t.get("reason") != "open" and not t.get("pending")


def _values(trades: List[dict], key: str) -> np.ndarray:
    return np.array([t[key] for t in trades if t.get(key) is not None
                     and np.isfinite(t[key])], dtype=float)


def _boot_means(trades: List[dict], key: str, boot: int, seed: int) -> np.ndarray:
    """Bootstrap means with ENTRY MONTHS resampled whole (a cluster
    bootstrap): trades that entered in the same month share a regime, so
    resampling them independently understates the uncertainty."""
    groups: Dict[str, List[float]] = {}
    for t in trades:
        v = t.get(key)
        if v is None or not np.isfinite(v):
            continue
        groups.setdefault((t.get("entry_date") or "")[:7], []).append(float(v))
    if not groups:
        return np.array([])
    sums = np.array([sum(g) for g in groups.values()])
    cnts = np.array([len(g) for g in groups.values()], dtype=float)
    k = len(sums)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(int(boot), k))
    return sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)


def stats(trades: List[dict], *, key: str = "net_r", boot: int = 0,
          seed: int = 0) -> dict:
    """Everything a fat-tailed R distribution needs said about it -- computed
    on REALISED trades only (see the module docstring); open and pending
    trades are counted and marked beside the numbers, never inside them."""
    live = [t for t in trades if not t.get("skipped")]
    skipped = len(trades) - len(live)
    closed = [t for t in live if _realised(t)]
    opn = [t for t in live if not _realised(t)]
    ov = _values(opn, key)
    rs = _values(closed, key)
    n = int(len(rs))
    out = {
        "n": n, "skipped": skipped,
        "open": len(opn),
        "open_mtm_r": round(float(ov.sum()), 2) if len(ov) else 0.0,
        "open_at_end": sum(1 for t in opn if t.get("reason") == "open"),
        "pending": sum(1 for t in opn if t.get("pending")),
    }
    if n == 0:
        return out
    pos, neg = rs[rs > 0], rs[rs < 0]
    # Daily equity: same-day exits netted first, so the drawdown cannot depend
    # on the (alphabetical) order of trades that closed on one date.
    daily: Dict[str, float] = {}
    for t in closed:
        v = t.get(key)
        if v is not None and np.isfinite(v):
            daily[t.get("exit_date") or ""] = daily.get(t.get("exit_date") or "", 0.0) + float(v)
    eq = np.cumsum([daily[d] for d in sorted(daily)])
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    top = np.sort(rs)[::-1]
    total = float(rs.sum())
    out.update({
        "wins": int(len(pos)), "losses": int(len(neg)), "flat": int(n - len(pos) - len(neg)),
        "win_pct": round(100.0 * len(pos) / n, 1),
        "exp_r": round(float(rs.mean()), 3),
        "median_r": round(float(np.median(rs)), 3),
        "total_r": round(total, 2),
        "pf": round(float(pos.sum() / -neg.sum()), 2) if len(neg) else None,
        "pf_note": ("no losing trades" if not len(neg) and len(pos) else None),
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
        "avg_bars": round(float(np.mean([t["bars"] for t in closed if "bars" in t])), 1),
        "stop_pct": round(100.0 * sum(1 for t in closed if t.get("reason") == "stop") / n, 1),
    })
    if boot and n >= 5:
        means = _boot_means(closed, key, boot, seed)
        out["exp_r_ci90"] = [round(float(np.percentile(means, 5)), 3),
                             round(float(np.percentile(means, 95)), 3)]
        out["boot_p_exp_le_0"] = round(float((means <= 0).mean()), 3)
        out["ci_method"] = "cluster bootstrap, entry months resampled whole"
    return out


def versus(primary: List[dict], baseline: List[dict], *, key: str = "net_r",
           boot: int, seed: int) -> dict:
    """THE DECISION STATISTIC: primary expectancy MINUS the baseline's, with
    a 90% band and the bootstrap share of draws in which the primary did NOT
    beat the baseline. Realised trades only; both sides cluster-resampled by
    entry month, independently."""
    a = [t for t in primary if _realised(t)]
    b = [t for t in baseline if _realised(t)]
    va, vb = _values(a, key), _values(b, key)
    if len(va) < 5 or len(vb) < 5:
        return {"n_primary": int(len(va)), "n_baseline": int(len(vb))}
    ma = _boot_means(a, key, boot, seed)
    mb = _boot_means(b, key, boot, seed + 1)
    d = ma - mb
    return {
        "n_primary": int(len(va)), "n_baseline": int(len(vb)),
        "diff_r": round(float(va.mean() - vb.mean()), 3),
        "diff_ci90": [round(float(np.percentile(d, 5)), 3), round(float(np.percentile(d, 95)), 3)],
        "p_diff_le_0": round(float((d <= 0).mean()), 3),
    }


def _group(trades: List[dict], keyfn, *, boot: int = 0, seed: int = 0) -> dict:
    groups: Dict[str, List[dict]] = {}
    for t in trades:
        if t.get("skipped"):
            continue
        k = keyfn(t)
        if k is None:
            continue
        groups.setdefault(k, []).append(t)
    return {k: stats(v, boot=boot, seed=seed) for k, v in sorted(groups.items())}


def _split_key(t: dict) -> str:
    return "in_sample" if t["entry_date"] < config.IGNITION_BT_SPLIT_DATE else "out_of_sample"


def _by_split(trades: List[dict], *, boot: int, seed: int) -> dict:
    out = _group(trades, _split_key, boot=boot, seed=seed)
    fwd = [t for t in trades if not t.get("skipped")
           and t["entry_date"] >= E.mkt(t.get("_mkt") or "crypto", "IGNITION_BT_REGISTERED_DATE")]
    out["forward"] = stats(fwd, boot=boot, seed=seed)
    return out


def _rules_for(prepared: List[Prepared], p: E.Params) -> List[pd.DataFrame]:
    return [E.apply_rules(pr.bf, p) for pr in prepared]


def run_all(prepared: List[Prepared], p: E.Params, rules=None, *,
            entries: Optional[Dict[str, List[int]]] = None, **kw) -> List[dict]:
    rules = rules if rules is not None else _rules_for(prepared, p)
    out: List[dict] = []
    for pr, ru in zip(prepared, rules):
        e = None if entries is None else entries.get(pr.symbol, [])
        out.extend(trades_for(pr, ru, entries=e, **kw))
    return out


def _entries_of(trades: List[dict]) -> Dict[str, List[int]]:
    """The trigger bars a trade list actually took (skips included, so a
    variant sees the same gap-below-stop outcome on the same trigger)."""
    out: Dict[str, List[int]] = {}
    for t in trades:
        if "_t0" in t:
            out.setdefault(t["symbol"], []).append(int(t["_t0"]))
    return out


def _public(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.startswith("_")}


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
    return {"trades": [{**_public(t), "design_case": is_design_case(t)} for t in trades
                       if t["symbol"] == pr.symbol and not t.get("skipped")],
            "design_case": pr.symbol in design_cases(pr.market),
            "recent_bars": rows}


def _grid_summary(prepared: List[Prepared], p: E.Params) -> dict:
    min_n = int(config.IGNITION_BT_GRID_MIN_N)
    cells = []
    for combo in itertools.product(*GRID.values()):
        q = p.replace(**dict(zip(GRID.keys(), combo)))
        s = stats(scored(run_all(prepared, q)))
        cells.append((s["n"], s.get("exp_r")))
    counted = [(n, e) for n, e in cells if n >= min_n and e is not None]
    exps = np.array([e for _, e in counted]) if counted else np.array([])
    ns = np.array([n for n, _ in counted], dtype=float) if counted else np.array([])
    return {
        "cells": len(cells),
        "min_n": min_n,
        "cells_counted": len(counted),
        "cells_below_min_n": sum(1 for n, _ in cells if n < min_n),
        "n_min_counted": int(ns.min()) if len(ns) else 0,
        "n_median_counted": int(np.median(ns)) if len(ns) else 0,
        "exp_r_min": round(float(exps.min()), 3) if len(exps) else None,
        "exp_r_median": round(float(np.median(exps)), 3) if len(exps) else None,
        "exp_r_max": round(float(exps.max()), 3) if len(exps) else None,
        "pct_cells_positive": round(100.0 * float((exps > 0).mean()), 1) if len(exps) else None,
        "pct_positive_trade_weighted": (round(100.0 * float(ns[exps > 0].sum() / ns.sum()), 1)
                                        if len(ns) else None),
        "note": "cells overlap heavily (they share most trades); this is a robustness "
                "read, not independent evidence, and never a menu",
    }


def backtest(frames: Dict[str, pd.DataFrame], market: str, *,
             symbols: Optional[Dict[str, str]] = None,
             universe_size: Optional[int] = None,
             now: Optional[dt.datetime] = None,
             data_note: Optional[str] = None,
             regime: Optional[pd.DataFrame] = None) -> dict:
    """The whole replay -> one publishable payload. Deterministic given the
    frames: every random draw is seeded, no clock is read except `now`.
    `data_note` is the caveat line naming where the bars came from (run.py
    writes it from the fetch report; the replay itself cannot know)."""
    p = E.Params.from_config(market)
    prepared = prepare(frames, market, symbols, regime=regime)
    cost = float(E.mkt(market, "IGNITION_BT_COST_PCT"))
    max_hold = E.bars(market, "IGNITION_BT_MAX_HOLD")
    rwin = E.bars(market, "IGNITION_BT_RANDOM_WINDOW")
    registered = E.mkt(market, "IGNITION_BT_REGISTERED_DATE")
    rg_idx, rg_label = config.IGNITION_REGIME_INDEX.get(market) or ("BTC-USD", "BTC")
    seed = int(config.IGNITION_BT_SEED)
    boot = int(config.IGNITION_BT_BOOTSTRAP)

    rules = _rules_for(prepared, p)
    primary_all = run_all(prepared, p, rules)
    primary = scored(primary_all)
    entries = _entries_of(primary)

    exits = {spec: stats(run_all(prepared, p, rules, entries=entries, exit_spec=spec))
             for spec in EXIT_SPECS}
    stops = {"struct": stats(primary),
             "floor": stats(run_all(prepared, p, rules, entries=entries, stop_spec="floor"))}
    cost_x2 = stats(run_all(prepared, p, rules, entries=entries,
                            cost_pct=2 * cost))

    draws = int(config.IGNITION_BT_RANDOM_DRAWS)
    rand = random_timing(prepared, primary, draws=draws, seed=seed, p=p)
    rand_any = random_timing(prepared, primary, draws=draws, seed=seed, p=p, window=0)
    brk = scored(run_all(prepared, p.replace(require_coil=False)))
    norv = scored(run_all(prepared, p.replace(require_rvol=False)))
    baselines = {
        "random_timing": {**stats(rand, boot=boot, seed=seed),
                          "by_split": _by_split(rand, boot=0, seed=seed)},
        "random_timing_any": stats(rand_any, boot=boot, seed=seed),
        "breakout_only": {**stats(brk, boot=boot, seed=seed),
                          "by_split": _by_split(brk, boot=0, seed=seed)},
        "no_rvol": stats(norv, boot=boot, seed=seed),
    }
    vs = {
        "random_timing": versus(primary, rand, boot=boot, seed=seed),
        "random_timing_any": versus(primary, rand_any, boot=boot, seed=seed),
        "breakout_only": versus(primary, brk, boot=boot, seed=seed),
        "no_rvol": versus(primary, norv, boot=boot, seed=seed),
        "random_timing_out_of_sample": versus(
            [t for t in primary if not t.get("skipped") and _split_key(t) == "out_of_sample"],
            [t for t in rand if _split_key(t) == "out_of_sample"], boot=boot, seed=seed),
    }

    oat = []
    for name, values in GRID.items():
        for v in values:
            s = stats(scored(run_all(prepared, p.replace(**{name: v}))))
            oat.append({"param": name, "value": v, "default": v == getattr(p, name),
                        "n": s["n"], "open": s["open"], "exp_r": s.get("exp_r"),
                        "pf": s.get("pf"), "median_r": s.get("median_r")})
    defaults_in_grid = {name: getattr(p, name) in values for name, values in GRID.items()}

    by_sym = {pr.symbol: (pr, ru) for pr, ru in zip(prepared, rules)}
    cases = {s: _case(*by_sym[s], primary_all)
             for s in E.mkt(market, "IGNITION_BT_CASES") if s in by_sym}

    starts = [pr.df.index[0] for pr in prepared]
    ends = [pr.df.index[-1] for pr in prepared]
    now = now or dt.datetime.now(dt.timezone.utc)
    design = design_cases(market)
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
            "cost_pct_round_trip": cost,
            "max_hold_bars": max_hold,
            "split_date": config.IGNITION_BT_SPLIT_DATE,
            "registered": registered,
            "note": "thresholds fixed before the first run; the only market data that "
                    "informed them is the design cases' chart, which is never scored",
        },
        "scoring": {
            "realised_only": True,
            "design_cases_excluded": design,
            "design_trades_excluded": sum(1 for t in primary_all
                                          if not t.get("skipped") and is_design_case(t)),
            "baseline_rule": ("random_timing: per real trade, %d draws on the same coin within "
                              "+/-%d bars of its trigger, from bars where every rule input exists "
                              "and both turnover floors pass; same risk %%, same 9-SMA trail, "
                              "same costs. random_timing_any: the same, from the whole eligible "
                              "history." % (draws, rwin)),
            "decision_statistic": "versus.random_timing: primary minus baseline expectancy, "
                                  "cluster-bootstrapped by entry month",
        },
        "caveats": _caveats(market, data_note, design),
        "primary": {
            **stats(primary, boot=boot, seed=seed),
            "by_split": _by_split(primary, boot=boot, seed=seed),
            "by_year": _group(primary, lambda t: t["entry_date"][:4]),
            **({"by_btc_regime": _group(primary, lambda t: {True: "btc_above_200",
                                                            False: "btc_below_200"}.get(
                                                                t.get("btc_up"), "unknown"))}
               if market == "crypto" else
               {"by_regime": _group(primary, lambda t: {True: "index_above_200",
                                                        False: "index_below_200"}.get(
                                                            t.get("index_up"), "unknown")),
                "regime_index": {"symbol": rg_idx, "label": rg_label}}),
        },
        "versus": vs,
        "exits": exits,
        "exit_specs": EXIT_DESCRIPTIONS,
        "stops": stops,
        "cost_stress": {"x2": cost_x2},
        "baselines": baselines,
        "sensitivity": {"one_at_a_time": oat, "defaults_in_grid": defaults_in_grid,
                        "full_grid": _grid_summary(prepared, p)},
        "cases": cases,
        "open_trades": [_public(t) for t in primary if not t.get("skipped") and not _realised(t)],
        "trades": [{**_public(t), "design_case": is_design_case(t)} for t in sorted(
            (t for t in primary_all if not t.get("skipped")),
            key=lambda t: (t["entry_date"], t["symbol"]))],
    }


def _caveats(market: str, data_note: Optional[str], design: dict) -> List[str]:
    """The published honesty block. Crypto's wording is unchanged."""
    if market == "crypto":
        return [
            "SURVIVORSHIP: today's top ~200 coins only. Coins that pumped INTO the list are "
            "included with their pump; coins that pumped and died OUT of it are missing. "
            "Long-breakout results are biased UP -- judge against random_timing, not zero.",
            "Realised trades only: open and pending trades are shown as marks beside the "
            "numbers, never inside them.",
            "QNT's Sep-2026 move informed the thresholds, so it is excluded from every scored "
            "number and reported only as a case study.",
            "Per-trade R, not a portfolio: overlapping trades are each counted at 1R, with no "
            "capital constraint or position cap.",
            data_note or "Daily bars; young coins have thin early history.",
            "The sensitivity grid is a robustness read, not a menu: its best cell is in-sample.",
        ]
    label = getattr(config.MARKETS.get(market), "label", market.upper())
    names = ", ".join(sorted(design)) or "none"
    return [
        "SURVIVORSHIP: today's %s listings only. A company that broke out and was later "
        "delisted, suspended or taken over is missing, along with every failed breakout it "
        "had. Long-breakout results are biased UP -- judge against random_timing, not "
        "zero." % label,
        "Realised trades only: open and pending trades are shown as marks beside the "
        "numbers, never inside them.",
        "The rule is crypto's, thresholds unchanged; calendar windows are converted to "
        "%d trading days a year. %s prompted the port, so it is excluded from every scored "
        "number and reported only as a case study."
        % (int(config.IGNITION_BARS_PER_YEAR.get(market, 365)), names),
        "Per-trade R, not a portfolio: overlapping trades are each counted at 1R, with no "
        "capital constraint or position cap.",
        "Costs %.1f%% round trip (brokerage both ways + the spread; under 10c an ASX tick "
        "is ~1%% of the price). Thin names can move more than that on the open."
        % float(E.mkt(market, "IGNITION_BT_COST_PCT")),
        data_note or "Yahoo daily bars (split-adjusted); free history is thinner and "
        "noisier than a paid provider's.",
        "The sensitivity grid is a robustness read, not a menu: its best cell is in-sample.",
    ]


def _fmt_pf(s: dict) -> str:
    if s.get("pf") is not None:
        return str(s["pf"])
    return "inf (no losses)" if s.get("pf_note") else "n/a"


def _brief(s: Optional[dict]) -> str:
    if not s or not s.get("n"):
        extra = f" (open {s.get('open')})" if s and s.get("open") else ""
        return "n=0" + extra
    ci = f" CI90={s['exp_r_ci90']}" if s.get("exp_r_ci90") else ""
    op = f" open={s['open']} (excluded, MTM {s.get('open_mtm_r')}R)" if s.get("open") else ""
    return (f"n={s['n']} exp={s.get('exp_r')}R med={s.get('median_r')}R "
            f"PF={_fmt_pf(s)} win={s.get('win_pct')}%{ci}{op}")


def _vs(v: Optional[dict]) -> str:
    if not v or "diff_r" not in v:
        return "too few trades to compare"
    return (f"diff={v['diff_r']:+}R CI90={v['diff_ci90']} "
            f"P(no edge)={v['p_diff_le_0']} (n {v['n_primary']} vs {v['n_baseline']})")


def summary_lines(payload: dict) -> List[str]:
    """The printed read (ASCII only). Written for a step summary."""
    P, B, V = (payload.get("primary") or {}, payload.get("baselines") or {},
               payload.get("versus") or {})
    sp = (P.get("by_split") or {})
    sc = payload.get("scoring") or {}
    lines = [
        f"IGNITION backtest [{payload.get('market')}] ruleset {payload.get('ruleset_version')}"
        f" - {payload.get('symbols_replayed')} "
        f"{'coins' if payload.get('market') == 'crypto' else 'symbols'}, {payload.get('date_range')}",
        f"scored: realised trades only; design cases excluded "
        f"{sc.get('design_cases_excluded')} ({sc.get('design_trades_excluded')} trade(s))",
        f"primary (pre-registered): {_brief(P)} top5={P.get('top5_share_pct')}% "
        f"ex-top5={P.get('exp_r_ex_top5')}R maxDD={P.get('max_dd_r')}R",
        f"  in-sample: {_brief(sp.get('in_sample'))}",
        f"  out-of-sample: {_brief(sp.get('out_of_sample'))}",
        f"  forward (from {(payload.get('pre_registered') or {}).get('registered')}): "
        f"{_brief(sp.get('forward'))}",
        f"VERSUS random timing (same symbol, same season): {_vs(V.get('random_timing'))}",
        f"VERSUS random timing, out-of-sample only: {_vs(V.get('random_timing_out_of_sample'))}",
        f"VERSUS random timing (any time): {_vs(V.get('random_timing_any'))}",
        f"VERSUS breakout without the coil: {_vs(V.get('breakout_only'))}",
        f"VERSUS no volume confirmation: {_vs(V.get('no_rvol'))}",
        f"random timing (same season): {_brief(B.get('random_timing'))}",
        f"breakout only (no coil): {_brief(B.get('breakout_only'))}",
    ]
    for k, v in (payload.get("exits") or {}).items():
        lines.append(f"exit {k}: {_brief(v)}")
    g = (payload.get("sensitivity") or {}).get("full_grid") or {}
    lines.append(f"grid {g.get('cells_counted')}/{g.get('cells')} cells with n>={g.get('min_n')}: "
                 f"exp min/med/max {g.get('exp_r_min')}/{g.get('exp_r_median')}/"
                 f"{g.get('exp_r_max')}R, {g.get('pct_cells_positive')}% positive "
                 f"({g.get('pct_positive_trade_weighted')}% trade-weighted)")
    for sym, case in (payload.get("cases") or {}).items():
        tr = case.get("trades") or []
        last = tr[-1] if tr else None
        lines.append(f"case {sym}{' (design case - not scored)' if case.get('design_case') else ''}: "
                     f"{len(tr)} trade(s)"
                     + (f"; last {last['trigger_date']} -> {last['reason']} {last['net_r']}R"
                        if last else ""))
    return lines

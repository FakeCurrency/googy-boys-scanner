#!/usr/bin/env python3
"""Fill-model sensitivity + PhaseMap confluence on committed parity trades.

Read-only vs live rules / PhaseMap detection maths. Uses existing IS+OOS
artefacts' taken trades; downloads OHLC once per symbol.

Writes:
  public/data/vivek_fill_sensitivity.json
  public/data/vivek_confluence_study.json
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import config, output  # noqa: E402
from scanner import vivek_parity as vp  # noqa: E402
from scanner.vivek_journal import _apply_costs, _mark, _r_of, _snapshot, costs_for  # noqa: E402

log = logging.getLogger("lens_fill_confluence")

PM_ACTIVE = {"SWEPT", "DISPLACED", "RUNNING"}  # same as confluence_alert.PM_ACTIVE
FILL_MODELS = ("pessimistic", "midpoint", "optimistic")


# ── fill-model management ─────────────────────────────────────────────────────

def manage_bar_fill(tr, high, low, close, day, costs, is_last, fill_model, rules=None):
    """Intrabar mark under one of three fill assumptions (sim-only)."""
    rules = rules or vp.baseline_rules()
    if tr["status"] != "open":
        return
    is_long = tr["direction"] == "long"
    if fill_model == "midpoint":
        mid = (float(high) + float(low)) / 2.0
        _mark(tr, mid, day, costs)
    else:
        adverse, favourable = (low, high) if is_long else (high, low)
        if fill_model == "optimistic":
            # targets before stop within the bar
            _mark(tr, favourable, day, costs)
            if tr["status"] == "open":
                _mark(tr, adverse, day, costs)
        else:
            # pessimistic (live parity default): stop before target
            _mark(tr, adverse, day, costs)
            if tr["status"] == "open":
                _mark(tr, favourable, day, costs)

    held = vp._held_days(tr, day)
    if tr["status"] == "open":
        vp._stamp_mfe_checkpoints(tr, held, close)

    max_hold = rules.resolved_hold()
    if (tr["status"] == "open" and max_hold > 0 and not tr.get("tp1_hit")
            and held > max_hold):
        vp._close_special(tr, close, day, "time", costs)
        return
    if tr["status"] == "open" and is_last:
        vp._force_close(tr, close, day, costs)


def resim_trade(df: pd.DataFrame, trade: dict, fill_model: str) -> dict | None:
    """Re-manage one committed trade from its entry under a fill model."""
    if df is None or len(df) < 5:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    try:
        entry_day = trade["entry_date"]
    except KeyError:
        return None
    # locate entry bar
    dates = [ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
             for ts in df.index]
    try:
        j0 = dates.index(entry_day)
    except ValueError:
        # nearest on/after
        j0 = next((i for i, d in enumerate(dates) if d >= entry_day), None)
        if j0 is None:
            return None

    if any(trade.get(k) is None for k in ("entry", "risk", "tp1", "tp2", "tp3")):
        return None
    entry = float(trade["entry"])
    risk = float(trade["risk"])
    is_long = trade.get("direction") == "long"
    orig_stop = entry - risk if is_long else entry + risk
    row = {
        "symbol": trade["symbol"], "name": trade.get("symbol"),
        "sector": trade.get("sector", ""),
        "dir": "LONG" if is_long else "SHORT",
        "grade": trade.get("grade") or "A+",
        "entry_types": [trade.get("entry_type")],
        "level_tf": trade.get("level_tf"),
    }
    plan = {
        "stop": orig_stop, "tp1": trade["tp1"], "tp2": trade["tp2"], "tp3": trade["tp3"],
        "scale": trade.get("scale") or list(config.VIVEK_TP_SCALE_LONG if is_long
                                            else config.VIVEK_TP_SCALE_SHORT),
        "entry_trigger": trade.get("entry_type"), "armed": True,
    }
    market = trade.get("market") or "nasdaq"
    costs = costs_for(market)
    # Open at the committed fill (keeps entry fixed; only PATH fills change)
    snap = _snapshot(row, trade.get("timeframe") or "1W", plan, market, entry, entry_day)
    if snap is None:
        # force open even if don't-chase would skip — we are resimming a known fill
        snap = {
            "symbol": trade["symbol"], "direction": "long" if is_long else "short",
            "entry": entry, "stop": orig_stop, "risk": risk,
            "tp1": trade["tp1"], "tp2": trade["tp2"], "tp3": trade["tp3"],
            "scale": plan["scale"], "entry_date": entry_day, "status": "open",
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "booked_pct": 0.0, "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0,
            "exits": [], "mae": entry, "mfe": entry, "mae_r": 0.0, "mfe_r": 0.0,
            "market": market, "grade": "A+", "entry_type": trade.get("entry_type"),
            "level_tf": trade.get("level_tf"), "mfe_r_at": {}, "close_r_at": {},
        }
    else:
        snap["market"] = market
        snap["level_tf"] = trade.get("level_tf")
        snap["mfe_r_at"] = {}
        snap["close_r_at"] = {}

    h = df["High"].to_numpy(); l = df["Low"].to_numpy(); c = df["Close"].to_numpy()
    n = len(df)
    rules = vp.baseline_rules()
    # manage from NEXT bar after entry (entry bar already filled)
    for j in range(j0 + 1, n):
        day = dates[j]
        manage_bar_fill(snap, float(h[j]), float(l[j]), float(c[j]), day, costs,
                        is_last=(j == n - 1), fill_model=fill_model, rules=rules)
        if snap["status"] == "closed":
            break
    if snap["status"] != "closed":
        vp._force_close(snap, float(c[-1]), dates[-1], costs)
    return {
        "symbol": trade.get("symbol"), "market": market,
        "entry_date": entry_day, "level_tf": trade.get("level_tf"),
        "baseline_realized_r": trade.get("realized_r"),
        "baseline_exit_reason": trade.get("exit_reason"),
        "fill_model": fill_model,
        "realized_r": snap.get("realized_r"),
        "exit_reason": snap.get("exit_reason"),
        "hold_days": snap.get("hold_days"),
        "gross_r": snap.get("gross_r"),
        "cost_r": snap.get("cost_r"),
    }


# ── PhaseMap confluence at entry ──────────────────────────────────────────────

def pm_classify_at(df: pd.DataFrame, market: str, entry_date: str,
                   trade_dir: str) -> dict:
    """Return ALIGNED / OPPOSED / NONE using PhaseMap engine (read-only)."""
    from phasemap.engine.scanner import scan_ticker, drop_forming_bar
    from phasemap.config import CONFIG

    if df is None or len(df) < CONFIG.min_history_bars:
        return {"confluence": "NONE", "pm_state": None, "pm_dir": None, "reason": "short_history"}

    d = df.copy()
    # PhaseMap indicators expect a Date column
    if "Date" not in getattr(d, "columns", []):
        d = d.reset_index()
        # first col is the former index
        col0 = d.columns[0]
        if col0 != "Date":
            d = d.rename(columns={col0: "Date"})
    # flatten MultiIndex columns if any
    if hasattr(d.columns, "nlevels") and d.columns.nlevels > 1:
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    d = drop_forming_bar(d, market)
    # slice to entry_date inclusive (no look-ahead)
    try:
        target = pd.Timestamp(entry_date)
        mask = pd.to_datetime(d["Date"]) <= target
        d = d.loc[mask].reset_index(drop=True)
    except Exception:
        return {"confluence": "NONE", "pm_state": None, "pm_dir": None, "reason": "bad_date"}
    if len(d) < CONFIG.min_history_bars:
        return {"confluence": "NONE", "pm_state": None, "pm_dir": None, "reason": "short_slice"}

    vol_usd = bool(getattr(config.MARKETS.get(market), "volume_is_usd", False))
    try:
        recs = scan_ticker("X", d, market=market, volume_is_usd=vol_usd)
    except Exception as e:
        return {"confluence": "NONE", "pm_state": None, "pm_dir": None, "reason": f"eng:{e}"}

    # recs is list of (rec, eng) or list of rec — handle both
    records = []
    for item in recs:
        records.append(item[0] if isinstance(item, tuple) else item)

    want = "bullish" if trade_dir == "long" else "bearish"
    opp = "bearish" if want == "bullish" else "bullish"
    same = next((r for r in records if r.get("direction") == want
                 and r.get("state") in PM_ACTIVE), None)
    other = next((r for r in records if r.get("direction") == opp
                  and r.get("state") in PM_ACTIVE), None)
    if same:
        return {"confluence": "ALIGNED", "pm_state": same.get("state"),
                "pm_dir": same.get("direction"), "pm_tier": same.get("tier")}
    if other:
        return {"confluence": "OPPOSED", "pm_state": other.get("state"),
                "pm_dir": other.get("direction"), "pm_tier": other.get("tier")}
    # surface non-active state if any
    any_rec = next((r for r in records if r.get("direction") == want), None)
    return {"confluence": "NONE",
            "pm_state": (any_rec or {}).get("state"),
            "pm_dir": (any_rec or {}).get("direction"),
            "reason": "no_active"}


# ── download helpers ──────────────────────────────────────────────────────────

def load_taken(path: Path) -> list[dict]:
    r = json.loads(path.read_text(encoding="utf-8"))
    return [t for t in r.get("trades") or [] if t.get("taken")]


def download_frames(trades: list[dict], period: str = "5y") -> dict:
    """(market, symbol) -> df"""
    from scanner.data import download
    by_m = defaultdict(list)
    meta = {}
    for t in trades:
        mk, sym = t["market"], t["symbol"]
        key = (mk, sym)
        if key in meta:
            continue
        mkt = config.MARKETS[mk]
        yf = sym + mkt.suffix
        by_m[mk].append(yf)
        meta[yf] = key
    frames = {}
    for mk, yfs in by_m.items():
        log.info("downloading %s: %d tickers", mk, len(yfs))
        got = download(yfs, period=period)
        for yf, df in got.items():
            key = meta.get(yf)
            if key and df is not None and len(df):
                frames[key] = df
    return frames


def metrics(trs):
    if not trs:
        return {"n": 0, "expectancy_r": None, "total_r": 0.0, "win_rate": 0.0}
    rs = [t.get("realized_r") or 0.0 for t in trs]
    wins = [r for r in rs if r > 0]
    return {
        "n": len(trs),
        "expectancy_r": round(sum(rs) / len(rs), 4),
        "total_r": round(sum(rs), 2),
        "win_rate": round(100 * len(wins) / len(rs), 1),
        "stop_n": sum(1 for t in trs if t.get("exit_reason") == "stop"),
        "stop_total_r": round(sum((t.get("realized_r") or 0) for t in trs
                                  if t.get("exit_reason") == "stop"), 2),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    is_path = ROOT / "public/data/vivek_backtest_parity.json"
    oos_path = ROOT / "public/data/vivek_backtest_parity_oos.json"
    is_t = load_taken(is_path)
    oos_t = load_taken(oos_path)
    # tag sample
    for t in is_t:
        t["_sample"] = "IS"
    for t in oos_t:
        t["_sample"] = "OOS"
    all_t = is_t + oos_t
    log.info("taken trades: IS=%d OOS=%d total=%d", len(is_t), len(oos_t), len(all_t))

    frames = download_frames(all_t, period="5y")
    log.info("frames ready: %d", len(frames))

    # ── Part 1: fill sensitivity ──────────────────────────────────────────
    fill_rows = []
    for i, t in enumerate(all_t):
        df = frames.get((t["market"], t["symbol"]))
        if df is None:
            continue
        for fm in FILL_MODELS:
            try:
                row = resim_trade(df, t, fm)
            except Exception as e:
                log.warning("fill resim %s %s %s: %s", t.get("symbol"), fm, e)
                row = None
            if row:
                row["sample"] = t["_sample"]
                fill_rows.append(row)
        if (i + 1) % 100 == 0:
            log.info("fill progress %d/%d", i + 1, len(all_t))

    def pool(sample=None, fm=None):
        rows = fill_rows
        if sample:
            rows = [r for r in rows if r.get("sample") == sample]
        if fm:
            rows = [r for r in rows if r.get("fill_model") == fm]
        return metrics(rows)

    # baseline from original realised_r on same trade set that resimmed
    def baseline_pool(sample=None):
        # unique trades that got at least one fill row
        keys = {(r["symbol"], r["market"], r["entry_date"], r["sample"])
                for r in fill_rows if sample is None or r["sample"] == sample}
        src = all_t if sample is None else (is_t if sample == "IS" else oos_t)
        trs = [t for t in src
               if (t["symbol"], t["market"], t["entry_date"], t["_sample"]) in keys]
        # map to fake realized dicts
        return metrics([{"realized_r": t.get("realized_r"),
                         "exit_reason": t.get("exit_reason")} for t in trs])

    fill_summary = {
        "n_resim_rows": len(fill_rows),
        "by_model": {},
        "delta_vs_pessimistic": {},
        "pre_registered": {
            "rule": "if midpoint − pessimistic pooled expR ≥ +0.04 → sim overstated stop hole",
            "threshold_R": 0.04,
        },
    }
    for fm in FILL_MODELS:
        fill_summary["by_model"][fm] = {
            "pooled": pool(fm=fm),
            "IS": pool("IS", fm),
            "OOS": pool("OOS", fm),
        }
    pess = fill_summary["by_model"]["pessimistic"]["pooled"].get("expectancy_r") or 0
    mid = fill_summary["by_model"]["midpoint"]["pooled"].get("expectancy_r") or 0
    opt = fill_summary["by_model"]["optimistic"]["pooled"].get("expectancy_r") or 0
    d_mid = round(mid - pess, 4)
    d_opt = round(opt - pess, 4)
    fill_summary["delta_vs_pessimistic"] = {
        "midpoint": d_mid,
        "optimistic": d_opt,
        "stop_hole_pess": fill_summary["by_model"]["pessimistic"]["pooled"].get("stop_total_r"),
        "stop_hole_mid": fill_summary["by_model"]["midpoint"]["pooled"].get("stop_total_r"),
        "stop_hole_opt": fill_summary["by_model"]["optimistic"]["pooled"].get("stop_total_r"),
    }
    fill_summary["pre_registered"]["triggered"] = bool(d_mid >= 0.04)
    fill_summary["read"] = (
        "SIM OVERSTATED STOP HOLE — deprioritise stop redesign"
        if d_mid >= 0.04 else
        "Fill-model move < +0.04R — stop hole is not an artefact of pessimistic fills; "
        "stop redesign stays on the table"
    )
    fill_summary["baseline_artefact"] = {
        "IS": baseline_pool("IS"),
        "OOS": baseline_pool("OOS"),
        "pooled": baseline_pool(),
    }
    # keep a slim per-trade delta table (symbol-level not full dump)
    fill_summary["n_trades_covered"] = len({(r["symbol"], r["market"], r["entry_date"], r["sample"])
                                            for r in fill_rows})

    out_fill = ROOT / "public/data/vivek_fill_sensitivity.json"
    output.write_json(out_fill, {
        "generated_from": {"is": is_path.name, "oos": oos_path.name},
        "fill_models": list(FILL_MODELS),
        "summary": fill_summary,
        # compact rows for recompute (no path bloat)
        "rows": fill_rows,
        "caveats": [
            "Survivorship bias — today's universe.",
            "Re-sim uses committed entry/TP/stop; only intrabar fill order changes.",
            "Entry fill is held fixed at the artefact entry price.",
        ],
    })
    log.info("wrote %s  mid-pess Δ=%s trigger=%s", out_fill, d_mid,
             fill_summary["pre_registered"]["triggered"])

    # ── Part 2: confluence ────────────────────────────────────────────────
    conf_rows = []
    for i, t in enumerate(all_t):
        df = frames.get((t["market"], t["symbol"]))
        cls = pm_classify_at(df, t["market"], t["entry_date"], t.get("direction") or "long")
        conf_rows.append({
            "symbol": t.get("symbol"), "market": t.get("market"),
            "entry_date": t.get("entry_date"), "sample": t["_sample"],
            "direction": t.get("direction"), "level_tf": t.get("level_tf"),
            "realized_r": t.get("realized_r"), "exit_reason": t.get("exit_reason"),
            **cls,
        })
        if (i + 1) % 100 == 0:
            log.info("confluence progress %d/%d", i + 1, len(all_t))

    def conf_metrics(sample=None, conf=None):
        rows = conf_rows
        if sample:
            rows = [r for r in rows if r["sample"] == sample]
        if conf:
            rows = [r for r in rows if r.get("confluence") == conf]
        return metrics([{"realized_r": r.get("realized_r"),
                         "exit_reason": r.get("exit_reason")} for r in rows])

    def gap(a, b):
        if a.get("expectancy_r") is None or b.get("expectancy_r") is None:
            return None
        return round(a["expectancy_r"] - b["expectancy_r"], 4)

    def eval_gates():
        # C1: aligned vs none — gap ≥ +0.10, n_aligned ≥ 80, sign holds IS and OOS
        # C2: opposed vs none — gap ≤ 0, consistent both samples
        results = {}
        for sample in ("IS", "OOS", "pooled"):
            al = conf_metrics(None if sample == "pooled" else sample, "ALIGNED")
            op = conf_metrics(None if sample == "pooled" else sample, "OPPOSED")
            no = conf_metrics(None if sample == "pooled" else sample, "NONE")
            results[sample] = {
                "ALIGNED": al, "OPPOSED": op, "NONE": no,
                "gap_aligned_minus_none": gap(al, no),
                "gap_opposed_minus_none": gap(op, no),
            }
        c1_pooled = results["pooled"]["gap_aligned_minus_none"]
        c1_n = results["pooled"]["ALIGNED"]["n"]
        c1_is = results["IS"]["gap_aligned_minus_none"]
        c1_oos = results["OOS"]["gap_aligned_minus_none"]
        c1 = (c1_pooled is not None and c1_pooled >= 0.10
              and c1_n >= 80
              and c1_is is not None and c1_is > 0
              and c1_oos is not None and c1_oos > 0)

        c2_is = results["IS"]["gap_opposed_minus_none"]
        c2_oos = results["OOS"]["gap_opposed_minus_none"]
        c2_pooled = results["pooled"]["gap_opposed_minus_none"]
        c2 = (c2_pooled is not None and c2_pooled <= 0
              and c2_is is not None and c2_is <= 0
              and c2_oos is not None and c2_oos <= 0)

        return {
            "C1": {
                "pass": c1,
                "rule": "aligned vs none exp gap ≥ +0.10R, n_aligned≥80, sign holds IS+OOS",
                "gap_pooled": c1_pooled, "n_aligned": c1_n,
                "gap_IS": c1_is, "gap_OOS": c1_oos,
            },
            "C2": {
                "pass": c2,
                "rule": "opposed vs none gap ≤ 0, consistent IS+OOS",
                "gap_pooled": c2_pooled, "gap_IS": c2_is, "gap_OOS": c2_oos,
            },
            "slices": results,
            "counts": dict(Counter(r.get("confluence") for r in conf_rows)),
        }

    gates = eval_gates()
    out_conf = ROOT / "public/data/vivek_confluence_study.json"
    output.write_json(out_conf, {
        "generated_from": {"is": is_path.name, "oos": oos_path.name},
        "pm_active_states": sorted(PM_ACTIVE),
        "gates": gates,
        "rows": conf_rows,
        "caveats": [
            "Survivorship bias.",
            "PhaseMap engine run on history sliced to entry_date (no look-ahead).",
            "Detection maths untouched — read-only classify.",
            "ALIGNED = same-direction state in {SWEPT,DISPLACED,RUNNING} at entry.",
        ],
    })
    log.info("wrote %s  C1=%s C2=%s counts=%s", out_conf, gates["C1"]["pass"],
             gates["C2"]["pass"], gates["counts"])

    print(json.dumps({
        "fill": {
            "pess_exp": pess, "mid_exp": mid, "opt_exp": opt,
            "delta_mid": d_mid, "trigger": fill_summary["pre_registered"]["triggered"],
            "read": fill_summary["read"],
            "stop_hole": fill_summary["delta_vs_pessimistic"],
        },
        "confluence": {
            "C1": gates["C1"], "C2": gates["C2"], "counts": gates["counts"],
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Out-of-sample level_tf gates + ASX diagnosis + capacity (read-only analysis).

Reads:
  public/data/vivek_backtest_parity.json       (IS)
  public/data/vivek_backtest_parity_oos.json   (OOS)
  journal/vivek_bot_book.json                 (live 21)

Writes:
  public/data/vivek_parity_oos_gates.json
  stdout summary
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import vivek_parity as vp  # noqa: E402
from scanner import output  # noqa: E402


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def taken_trades(report: dict) -> list[dict]:
    tr = report.get("trades") or []
    if tr and "taken" in tr[0]:
        return [t for t in tr if t.get("taken")]
    return vp._taken_list(tr)


def rsm(trs: list[dict]) -> float | None:
    _, v = vp._slot_month_stats(trs)
    return v


def cohort(trs, **pred):
    out = trs
    for k, v in pred.items():
        if k == "level_in":
            out = [t for t in out if t.get("level_tf") in v]
        elif k == "level_eq":
            out = [t for t in out if t.get("level_tf") == v]
        elif k == "market":
            out = [t for t in out if t.get("market") == v]
        else:
            out = [t for t in out if t.get(k) == v]
    return out


def metrics(trs):
    m = vp._metrics(trs)
    sm, r = vp._slot_month_stats(trs)
    m = dict(m)
    m["slot_months"] = sm
    m["r_per_slot_month"] = r
    return m


def cost_stress(trs, mult=2.0):
    """Reprice realized_r = gross_r - mult*cost_r (fail-soft if missing gross)."""
    out = []
    for t in trs:
        nt = dict(t)
        gross = t.get("gross_r")
        cost = t.get("cost_r") or 0.0
        if gross is None:
            # approximate: realized already net; peel one cost then re-apply
            realized = t.get("realized_r") or 0.0
            gross = realized + cost
        nt["realized_r"] = round(float(gross) - mult * float(cost), 4)
        out.append(nt)
    return out


def eval_gates(oos_taken: list[dict]) -> dict:
    w3 = cohort(oos_taken, level_in=("weekly", "3d"))
    h4 = cohort(oos_taken, level_eq="h4")
    nas_w3 = cohort(w3, market="nasdaq")
    asx_w3 = cohort(w3, market="asx")
    nas_h4 = cohort(h4, market="nasdaq")
    asx_h4 = cohort(h4, market="asx")

    g1_overall = rsm(w3)
    g1_nas = rsm(nas_w3)
    g1 = (g1_overall is not None and g1_overall > 0
          and g1_nas is not None and g1_nas > 0)

    def lt(a, b):
        return a is not None and b is not None and a < b

    g2_asx = lt(rsm(asx_h4), rsm(asx_w3))
    g2_nas = lt(rsm(nas_h4), rsm(nas_w3))
    g2 = g2_asx and g2_nas

    stressed = cost_stress(nas_w3, 2.0)
    g3_val = rsm(stressed)
    g3 = g3_val is not None and g3_val > 0

    return {
        "G1": {
            "pass": g1,
            "weekly_3d_overall_rsm": g1_overall,
            "weekly_3d_nasdaq_rsm": g1_nas,
            "n_overall": len(w3),
            "n_nasdaq": len(nas_w3),
            "rule": "weekly+3d R/sm > 0 overall AND on NASDAQ alone",
        },
        "G2": {
            "pass": g2,
            "asx_h4_rsm": rsm(asx_h4),
            "asx_w3_rsm": rsm(asx_w3),
            "nasdaq_h4_rsm": rsm(nas_h4),
            "nasdaq_w3_rsm": rsm(nas_w3),
            "rule": "h4 R/sm < weekly+3d R/sm on ASX and NASDAQ separately",
        },
        "G3": {
            "pass": g3,
            "nasdaq_w3_2x_cost_rsm": g3_val,
            "n": len(stressed),
            "rule": "G1 NASDAQ weekly+3d survives 2× cost_r",
        },
        "confirmed": bool(g1 and g2 and g3),
        "slices": {
            "weekly_3d": metrics(w3),
            "h4": metrics(h4),
            "weekly": metrics(cohort(oos_taken, level_eq="weekly")),
            "3d": metrics(cohort(oos_taken, level_eq="3d")),
            "by_market_level": {
                f"{mk}:{lv}": metrics(cohort(oos_taken, market=mk, level_eq=lv))
                for mk in ("asx", "nasdaq")
                for lv in ("weekly", "3d", "h4")
            },
        },
    }


def asx_diagnosis(is_taken: list[dict], oos_taken: list[dict]) -> dict:
    asx = [t for t in is_taken + oos_taken if t.get("market") == "asx"]
    if not asx:
        return {"n": 0, "conclusion": "no ASX trades"}

    # cost vs price-move share of total R
    gross = sum(t.get("gross_r") or 0 for t in asx)
    cost = sum(t.get("cost_r") or 0 for t in asx)
    net = sum(t.get("realized_r") or 0 for t in asx)

    # stop-gap overshoot: stop exits with |realized_r| > 1.05 (beyond 1R + costs)
    stops = [t for t in asx if t.get("exit_reason") == "stop"]
    overshoot = [t for t in stops if (t.get("realized_r") or 0) < -1.05]
    mild = [t for t in stops if -1.05 <= (t.get("realized_r") or 0) < 0]

    # liquidity bands via adv_usd if present
    bands = {"unknown": [], "thin": [], "mid": [], "deep": []}
    for t in asx:
        adv = t.get("adv_usd")
        if not adv:
            bands["unknown"].append(t)
        elif adv < 500_000:
            bands["thin"].append(t)
        elif adv < 5_000_000:
            bands["mid"].append(t)
        else:
            bands["deep"].append(t)

    # residual fund leakage — names that look like funds but slipped in
    fundish = []
    for t in asx:
        name = (t.get("name") or t.get("symbol") or "").upper()
        if any(k in name for k in ("ETF", "FUND", "TRUST", "REIT", "LIC ")):
            fundish.append(t.get("symbol"))

    by_level = {lv: metrics(cohort(asx, level_eq=lv)) for lv in ("weekly", "3d", "h4")}
    by_exit = {}
    for rsn, n in Counter(t.get("exit_reason") for t in asx).items():
        by_exit[str(rsn)] = metrics([t for t in asx if t.get("exit_reason") == rsn])

    # conclusion heuristic
    cost_share = abs(cost) / max(abs(gross) + abs(cost), 1e-9)
    overshoot_rate = len(overshoot) / max(len(stops), 1)
    if by_level.get("weekly", {}).get("expectancy_r", 0) > 0 and by_level.get("h4", {}).get("expectancy_r", 0) < 0:
        conclusion = (
            "ASX underperformance is partly a LEVEL MIX artefact (h4 drag), "
            "not pure market edgelessness — weekly still weak-to-flat; costs "
            f"are {cost_share:.0%} of |gross|+|cost| mass; stop overshoot "
            f"{overshoot_rate:.0%} of stops."
        )
        kind = "mixed_artefact"
    elif net >= 0:
        conclusion = "ASX net non-negative in combined sample — not edgeless."
        kind = "not_edgeless"
    else:
        conclusion = (
            "ASX remains net-negative even after level split — treat as weaker "
            "market under current entries; suspension is on the table if OOS "
            "weekly+3d also fails on ASX alone."
        )
        kind = "weak_market"

    return {
        "n": len(asx),
        "total_r": round(net, 3),
        "gross_r": round(gross, 3),
        "cost_r": round(cost, 3),
        "cost_share_of_abs_mass": round(cost_share, 3),
        "stops_n": len(stops),
        "stop_overshoot_n": len(overshoot),
        "stop_overshoot_rate": round(overshoot_rate, 3),
        "stop_mean_r": round(sum(t.get("realized_r") or 0 for t in stops) / max(len(stops), 1), 3),
        "liquidity_bands": {k: metrics(v) for k, v in bands.items()},
        "fundish_symbols": sorted(set(fundish)),
        "by_level": by_level,
        "by_exit": {k: {kk: vv for kk, vv in m.items() if kk in ("n", "expectancy_r", "total_r")}
                   for k, m in by_exit.items()},
        "kind": kind,
        "conclusion": conclusion,
    }


def capacity(surviving: list[dict], slots: int = 30) -> dict:
    """Historical concurrent open path under surviving entry set."""
    if not surviving:
        return {"n": 0, "fill_rate": None, "peak_open": 0, "avg_open": 0,
                "slot_months": 0, "r_per_slot_month": None}
    # chronological occupancy
    events = []
    for t in surviving:
        try:
            e = t["entry_date"]; x = t["exit_date"]
        except Exception:
            continue
        events.append((e, 1, t))
        events.append((x, -1, t))
    events.sort(key=lambda z: (z[0], z[1]))  # exits before entries same day
    open_n = peak = 0
    # day integral
    from datetime import date, timedelta
    if not events:
        return {"n": 0}
    # rebuild via taken list under slot cap
    port = vp.portfolio_sim_parity(surviving, max_total=slots)
    taken = vp._taken_list(surviving)  # uses config cap — temporarily ok
    # re-sim with explicit max
    # count fills vs signals
    elig = surviving
    return {
        "eligible_n": len(elig),
        "taken_n": port.get("taken"),
        "fill_rate": round(port.get("taken", 0) / max(len(elig), 1), 3),
        "peak_open": port.get("peak_open"),
        "skipped": port.get("skipped"),
        "slot_months": port.get("slot_months"),
        "r_per_slot_month": port.get("r_per_slot_month"),
        "expectancy_r": (port.get("portfolio") or {}).get("expectancy_r"),
        "total_r": (port.get("portfolio") or {}).get("total_r"),
        "slots": slots,
    }


def counterfactual_live(book_closed: list[dict], keep_levels=("weekly", "3d"),
                        apply_v2=False) -> dict:
    """What the bundle would have done to the 21 real closes (simulation)."""
    kept, dropped = [], []
    for t in book_closed:
        ltf = t.get("level_tf")
        if ltf in keep_levels:
            kept.append(t)
        else:
            dropped.append(t)
    # V2 on kept: if hold>=14 and mfe_r<0.5 and not tp1 and exit was time/stop
    # approximate: if mfe_r < 0.5 and hold_days >= 14 and exit in (time, stop, manual)
    v2_adj = []
    for t in kept:
        nt = dict(t)
        if apply_v2:
            mfe = t.get("mfe_r") or 0
            hold = t.get("hold_days") or 0
            if (not t.get("tp1_hit") and hold >= 14 and mfe < 0.5
                    and t.get("exit_reason") in ("time", "stop", "manual")):
                # cut at day 14 approx: use close-ish = entry + mfe*risk roughly
                # we don't have path; use realized as upper bound of damage
                # Conservative: assign realized_r = min(realized, 0) * 0? 
                # Better: mark as early_cut with realized ~= mfe (optimistic) or 0
                nt["exit_reason"] = "early_cut_cf"
                nt["realized_r"] = round(min(float(mfe), float(t.get("realized_r") or 0)), 4)
                nt["counterfactual"] = True
        v2_adj.append(nt)

    def tot(trs):
        return round(sum(t.get("realized_r") or 0 for t in trs), 4)

    return {
        "live_n": len(book_closed),
        "live_total_r": tot(book_closed),
        "kept_levels": list(keep_levels),
        "kept_n": len(kept),
        "kept_total_r": tot(kept),
        "dropped_n": len(dropped),
        "dropped_total_r": tot(dropped),
        "dropped_symbols": [t.get("symbol") for t in dropped],
        "with_v2_total_r": tot(v2_adj),
        "v2_applied": apply_v2,
    }


def main() -> int:
    is_path = ROOT / "public/data/vivek_backtest_parity.json"
    oos_path = ROOT / "public/data/vivek_backtest_parity_oos.json"
    book_path = ROOT / "journal/vivek_bot_book.json"
    if not oos_path.exists():
        print("OOS artifact missing:", oos_path)
        return 1
    is_r = load(is_path)
    oos_r = load(oos_path)
    book = load(book_path)
    is_t = taken_trades(is_r)
    oos_t = taken_trades(oos_r)

    # disjointness check
    is_syms = {mk: set(s) for mk, s in (is_r.get("sampled_symbols")
               or json.loads((ROOT / "public/data/vivek_parity_is_symbols.json").read_text())
               .get("by_market", {})).items()}
    oos_syms = {mk: set(s) for mk, s in (oos_r.get("sampled_symbols") or {}).items()}
    overlap = {mk: sorted(is_syms.get(mk, set()) & oos_syms.get(mk, set()))
               for mk in set(is_syms) | set(oos_syms)}

    gates = eval_gates(oos_t)
    asx = asx_diagnosis(is_t, oos_t)
    surv = cohort(oos_t, level_in=("weekly", "3d"))
    # also pool IS+OOS surviving for capacity sense-check
    surv_all = cohort(is_t, level_in=("weekly", "3d")) + surv
    cap = capacity(surv, slots=30)
    cap_all = capacity(surv_all, slots=30)
    cf = counterfactual_live(book.get("closed") or [], keep_levels=("weekly", "3d"),
                             apply_v2=True)
    cf_levels_only = counterfactual_live(book.get("closed") or [],
                                         keep_levels=("weekly", "3d"), apply_v2=False)

    out = {
        "generated_from": {
            "is": str(is_path.name),
            "oos": str(oos_path.name),
            "is_generated_at": is_r.get("generated_at"),
            "oos_generated_at": oos_r.get("generated_at"),
        },
        "disjointness": {
            "overlap": {k: v for k, v in overlap.items() if v},
            "ok": all(len(v) == 0 for v in overlap.values()),
            "oos_counts": {k: len(v) for k, v in oos_syms.items()},
            "is_counts": {k: len(v) for k, v in is_syms.items()},
        },
        "gates": gates,
        "asx_diagnosis": asx,
        "capacity_oos_weekly_3d": cap,
        "capacity_is_plus_oos_weekly_3d": cap_all,
        "live_counterfactual": {
            "levels_only": cf_levels_only,
            "levels_plus_v2": cf,
        },
        "verdict": (
            "CONFIRMED — level split holds OOS under G1/G2/G3"
            if gates["confirmed"] else
            "NOT CONFIRMED — level split failed one or more pre-registered gates; "
            "entry signal needs redesign or narrower proposal"
        ),
    }
    dest = ROOT / "public/data/vivek_parity_oos_gates.json"
    output.write_json(dest, out)
    print(json.dumps({
        "verdict": out["verdict"],
        "G1": gates["G1"],
        "G2": gates["G2"],
        "G3": gates["G3"],
        "asx_kind": asx.get("kind"),
        "asx_conclusion": asx.get("conclusion"),
        "capacity_fill_rate": cap.get("fill_rate"),
        "live_cf_levels_only_R": cf_levels_only.get("kept_total_r"),
        "live_cf_levels_v2_R": cf.get("with_v2_total_r"),
        "disjoint_ok": out["disjointness"]["ok"],
    }, indent=2))
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

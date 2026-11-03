"""Replicate a passing replay variant on a disjoint sample (NEXT100 #18).

SIMULATION ONLY. V7 passed the grid on one fixed draw of names: ``_sample``
takes an even stride, so every run replays the same 300 names a market.
After the variant grid, every variant that PASSES ``variant_passes`` is
re-run (baseline + that variant only) on a second sample that shares NO
name with the first -- the even stride over the names the first draw left,
which are the names between its picks -- at the same book caps. The verdict
then reads "PASS (replicated)" or "PASS (not replicated)". Cost is bounded:
at most one extra sample per market per run, loaded only when something
passed, and a market the first draw sampled whole has no disjoint names and
is left out of the second sample (said so in the block).
"""

from __future__ import annotations

import logging
import time

from . import config

log = logging.getLogger("vivek.replay_replicate")


def passing_variants(variant_results: dict) -> list[str]:
    return [name for name, vr in (variant_results or {}).items()
            if (vr.get("verdict") or {}).get("pass")]


def verdict_label(verdict: dict | None) -> str:
    """The one wording the markdown and the JSON share."""
    v = verdict or {}
    if not v.get("pass"):
        return "fail"
    rep = v.get("replicated")
    if rep is None:
        return "PASS"
    return "PASS (replicated)" if rep else "PASS (not replicated)"


def _overall(verdict: dict) -> dict:
    c = ((verdict or {}).get("checks") or {}).get("overall") or {}
    return {"baseline": c.get("baseline"), "variant": c.get("variant"), "delta": c.get("delta")}


def replicate_passes(markets: list[str], limit: int | None, period: str,
                     exclude_map: dict[str, set[str]], workers: int,
                     variant_results: dict, coverage: dict, caps: dict) -> dict:
    """Re-run the baseline and every passing variant on the complementary
    sample. Stamps ``verdict["replicated"]`` and ``verdict["label"]`` on each
    passing variant in ``variant_results`` and returns the block the summary
    prints. ``caps`` = {max_open_total, max_per_sector} from the first run."""
    from . import vivek_parity as vp

    for vr in (variant_results or {}).values():
        v = vr.get("verdict")
        if isinstance(v, dict):
            v["label"] = verdict_label(v)
    names = passing_variants(variant_results)
    if not getattr(config, "VIVEK_PARITY_REPLICATE", True):
        return {"ran": False, "reason": "VIVEK_PARITY_REPLICATE is off", "passing": names}
    if not names:
        return {"ran": False, "reason": "no variant passed the grid", "passing": []}
    t0 = time.time()
    series = []
    sample: dict = {}
    for mk in markets:
        cov = (coverage or {}).get(mk) or {}
        first = {str(s).upper() for s in (cov.get("sampled_symbols") or [])}
        if cov.get("universe") and int(cov.get("symbols") or 0) >= int(cov["universe"]):
            sample[mk] = {"symbols": 0, "universe": int(cov["universe"]), "overlap_dropped": 0,
                          "note": "the first draw sampled the whole market: no disjoint names"}
            continue
        excl = set(exclude_map.get(mk) or set()) | first
        ss, cov2 = vp.load_market_series(mk, limit, period, excl, workers)
        second = {str(s).upper() for s in (cov2.get("sampled_symbols") or [])}
        overlap = len(first & second)                 # 0 by construction; a loader that
        if overlap:                                   # ignored the exclusion is cut, not trusted
            log.warning("[parity] replication: %d %s names overlap the first draw; dropped",
                        overlap, mk)
            ss = [s for s in ss if str(s.symbol).upper() not in first]
        sample[mk] = {"symbols": len(second - first), "universe": int(cov.get("universe") or 0),
                      "overlap_dropped": overlap, "replayed": len(ss),
                      "signals": sum(len(s.signals) for s in ss)}
        series += ss
    kw = {"max_total": caps.get("max_open_total"), "max_sector": caps.get("max_per_sector")}
    base = vp.run_book(series, vp.baseline_rules(), **kw)
    grid = {r.name: r for r in vp.variant_grid()}
    out_variants: dict = {}
    for name in names:
        rules = grid[name]
        book = vp.run_book(series, rules, **kw)
        second = vp.variant_passes(base["taken"], book["taken"],
                                   skip_markets=tuple(rules.drop_markets))
        first_v = variant_results[name]["verdict"]
        first_v["replicated"] = bool(second.get("pass"))
        first_v["label"] = verdict_label(first_v)
        out_variants[name] = {
            "label": first_v["label"],
            "first": {"taken": variant_results[name].get("portfolio", {}).get("taken"),
                      **_overall(first_v)},
            "second": {"pass": bool(second.get("pass")), "taken": len(book["taken"]),
                       "baseline_taken": len(base["taken"]),
                       "checks": {k: {kk: c.get(kk) for kk in ("baseline", "variant", "delta", "pass")}
                                  for k, c in (second.get("checks") or {}).items()}},
        }
        log.info("[parity] replication %s: %s", name, first_v["label"])
    return {"ran": True, "passing": names, "sample": sample, "caps": dict(kw),
            "variants": out_variants, "minutes": round((time.time() - t0) / 60, 2)}

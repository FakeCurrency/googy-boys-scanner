"""Merge bt/out/*.json shards into bt/RESULTS.md + bt/results.json (throwaway)."""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
LENSES = ("vivek", "phasemap", "momentum")
TITLE = {"vivek": "VIVEK 5.0 (long A+/A, armed plans)",
         "phasemap": "PhaseMap (bullish A+/A)",
         "momentum": "Momentum (long signals)"}


def stats(trades):
    rs = [t["r"] for t in trades]
    usd = [t["usd"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    return {
        "trades": n,
        "wins": len(wins), "losses": len(losses),
        "win_pct": round(100 * len(wins) / n, 1) if n else None,
        "r_won": round(sum(wins), 2), "r_lost": round(sum(losses), 2),
        "net_r": round(sum(rs), 2),
        "expectancy_r": round(sum(rs) / n, 3) if n else None,
        "pf": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "usd_won": round(sum(u for u in usd if u > 0), 2),
        "usd_lost": round(sum(u for u in usd if u <= 0), 2),
        "net_usd": round(sum(usd), 2),
        "open_at_end": sum(1 for t in trades if t.get("exit_reason") == "eod"),
        "first": min((t["entry_date"] for t in trades), default=None),
        "last": max((t["entry_date"] for t in trades), default=None),
    }


def main() -> int:
    shards = [json.loads(p.read_text()) for p in sorted((ROOT / "out").glob("*.json"))]
    trades = [t for s in shards for t in s["trades"]]
    cov = collections.defaultdict(lambda: {"universe": set(), "shards": 0, "symbols": 0,
                                           "downloaded": 0, "errors": collections.Counter(),
                                           "periods": set()})
    for s in shards:
        c = cov[s["market"]]
        c["universe"].add(s["universe"]); c["shards"] += 1
        c["symbols"] += s["shard_symbols"]; c["downloaded"] += s["downloaded"]
        c["errors"].update(s.get("errors") or {}); c["periods"].add(s["period"])
        c.setdefault("of", s["of"])
    coverage = {m: {"universe": sorted(c["universe"]), "shards_in": c["shards"], "shards_of": c.get("of"),
                    "symbols": c["symbols"], "downloaded": c["downloaded"],
                    "errors": dict(c["errors"]), "period": sorted(c["periods"])}
                for m, c in sorted(cov.items())}

    res = {"coverage": coverage, "lenses": {}}
    for lens in LENSES:
        lt = [t for t in trades if t["lens"] == lens]
        block = {"all": stats(lt),
                 "by_market": {m: stats([t for t in lt if t["market"] == m])
                               for m in sorted({t["market"] for t in lt})},
                 "by_cohort": {c: stats([t for t in lt if t["cohort"] == c])
                               for c in sorted({t["cohort"] for t in lt})},
                 "by_exit": {e: stats([t for t in lt if t["exit_reason"] == e])
                             for e in sorted({t["exit_reason"] for t in lt})}}
        if lens == "vivek":
            block["by_timeframe"] = {tf: stats([t for t in lt if t["timeframe"] == tf])
                                     for tf in sorted({t["timeframe"] for t in lt})}
            block["high_conviction"] = stats([t for t in lt if t.get("hc_cell")])
            block["by_hc_cell"] = {c: stats([t for t in lt if t.get("hc_cell") == c])
                                   for c in sorted({t["hc_cell"] for t in lt if t.get("hc_cell")})}
        if lens == "phasemap":
            block["liquid_only"] = stats([t for t in lt if not t.get("illiquid")])
        res["lenses"][lens] = block
    res["combined"] = stats(trades)
    (ROOT / "results.json").write_text(json.dumps(res, indent=1) + "\n")

    def row(label, s):
        return (f"| {label} | {s['trades']:,} | {s['wins']:,} / {s['losses']:,} | {s['win_pct']}% | "
                f"+{s['r_won']:,.1f}R | {s['r_lost']:,.1f}R | **{s['net_r']:+,.1f}R** | "
                f"{s['expectancy_r']:+.3f}R | {s['pf']} | ${s['net_usd']:+,.0f} |")

    head = ("| | Trades | W / L | Win % | R won | R lost | Net R | Per trade | PF | Net $ at $1k |\n"
            "|---|---|---|---|---|---|---|---|---|---|")
    md = ["# Three-lens backtest — results", ""]
    md += ["## Headline", "", head]
    for lens in LENSES:
        md.append(row(TITLE[lens], res["lenses"][lens]["all"]))
    md.append(row("**All three together**", res["combined"]))
    for lens in LENSES:
        b = res["lenses"][lens]
        md += ["", f"## {TITLE[lens]}", "", head]
        for m, s in b["by_market"].items():
            md.append(row(m.upper(), s))
        for c, s in b["by_cohort"].items():
            md.append(row(f"cohort {c}", s))
        for e, s in b["by_exit"].items():
            md.append(row(f"exit {e}", s))
        for tf, s in (b.get("by_timeframe") or {}).items():
            md.append(row(f"timeframe {tf}", s))
        if "high_conviction" in b:
            md.append(row("HIGH CONVICTION cells", b["high_conviction"]))
            for c, s in b["by_hc_cell"].items():
                md.append(row(f"cell {c}", s))
        if "liquid_only" in b:
            md.append(row("liquid only", b["liquid_only"]))
    md += ["", "## Coverage", "", "```", json.dumps(coverage, indent=1), "```", ""]
    (ROOT / "RESULTS.md").write_text("\n".join(md))
    print("\n".join(md[:9]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

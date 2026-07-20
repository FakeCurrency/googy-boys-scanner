"""PhaseMap CLI — nightly scan entry point, one snapshot per market.

Usage:
    python -m phasemap.run                          # all markets (asx, nasdaq, crypto)
    python -m phasemap.run --market asx
    python -m phasemap.run --market nasdaq --limit 50
    python -m phasemap.run --tickers BHP,CBA        # specific ASX tickers

Outputs, per market:
    public/data/phasemap/<market>/YYYY-MM-DD.json + latest.json   (scan snapshot)
    public/data/phasemap/charts/<market>/<TICKER>.json            (candles for the chart page)
"""

import argparse
import csv
import datetime
import json
import os
import sys
import zoneinfo

from phasemap.config import CONFIG, PRODUCT_NAME, RULESET_VERSION
from phasemap.data.provider import YFinanceProvider
from phasemap.engine.scanner import scan_ticker, sort_records
from phasemap.narrate.renderer import render, render_next
from phasemap.output.writer import build_snapshot, write_snapshot

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASX_UNIVERSE_CSV = os.path.join(REPO_ROOT, "data_universe", "asx_tickers.csv")
STATS_DIR = os.path.join(REPO_ROOT, "phasemap", "backtest", "stats")

MARKETS = ("asx", "nasdaq", "crypto")
CHART_BARS = 220          # daily candles shipped to the chart page


def load_stats(market: str):
    """The M4 backtest's {stats} artefact — refused unless the sample is big
    enough AND it was produced by the current ruleset (guardrail 5: no
    performance claims that the harness didn't actually measure)."""
    try:
        with open(os.path.join(STATS_DIR, f"{market}.json"), encoding="utf-8") as f:
            s = json.load(f)
        if (s.get("sample", 0) >= CONFIG.stats_min_signals
                and s.get("ruleset_version") == RULESET_VERSION
                and s.get("hit_rate_pct") is not None):
            return s
    except Exception:
        pass
    return None


def load_symbols(market: str) -> dict:
    """{display ticker -> {yf, name, sector}} for a market. Uses the repo's
    live universe loaders (full ASX directory, curated NASDAQ, CoinGecko
    top-100); falls back to the bundled ASX CSV."""
    try:
        from scanner.universe import load_universe as repo_universe
        items = repo_universe(market, full=True)
        if items:
            return {it["symbol"]: {"yf": it["yf"], "name": it.get("name") or it["symbol"],
                                   "sector": it.get("sector") or ""}
                    for it in items}
    except Exception:
        pass
    if market == "asx":
        with open(ASX_UNIVERSE_CSV, newline="", encoding="utf-8-sig") as f:
            return {row["symbol"].strip(): {"yf": row["symbol"].strip() + ".AX",
                                            "name": (row.get("name") or row["symbol"]).strip(),
                                            "sector": (row.get("sector") or "").strip()}
                    for row in csv.DictReader(f) if row.get("symbol", "").strip()}
    return {}


def prune_stale_files(dir_path: str, keep: set, suffix: str = ".json") -> int:
    """Repo hygiene: chart candles for tickers no longer in the results would
    otherwise accumulate forever (bloat). The chart page falls back to live
    history for anything pruned, so nothing user-facing breaks."""
    removed = 0
    try:
        for name in os.listdir(dir_path):
            if name.endswith(suffix) and name[:-len(suffix)] not in keep:
                os.remove(os.path.join(dir_path, name))
                removed += 1
    except FileNotFoundError:
        pass
    return removed


def prune_dated_snapshots(out_dir: str, keep_last: int = 7) -> int:
    """Keep the trailing week of dated snapshots (latest.json untouched)."""
    removed = 0
    try:
        dated = sorted(n for n in os.listdir(out_dir)
                       if n.endswith(".json")
                       and n not in ("latest.json", "narrations.json"))
        for name in dated[:-keep_last]:
            os.remove(os.path.join(out_dir, name))
            removed += 1
    except FileNotFoundError:
        pass
    return removed


# Windows-reserved device names: a file called PRN.json (PRN is a real ASX
# ticker — Perenti) breaks every git checkout/pull on Windows. Skip writing
# chart files for these tickers; the chart page's live fallback covers them.
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                     *(f"COM{i}" for i in range(1, 10)),
                     *(f"LPT{i}" for i in range(1, 10))}


def write_chart_json(out_dir: str, ticker: str, df) -> None:
    """Last CHART_BARS daily candles, 8 dp (sub-cent crypto needs it)."""
    if ticker.upper() in _WINDOWS_RESERVED:
        print(f"  chart skip: {ticker} is a Windows-reserved filename")
        return
    tail = df.tail(CHART_BARS)
    candles = [
        {"t": str(r.Date)[:10],
         "o": round(float(r.Open), 8), "h": round(float(r.High), 8),
         "l": round(float(r.Low), 8), "c": round(float(r.Close), 8),
         "v": int(r.Volume) if r.Volume == r.Volume else 0}
        for r in tail.itertuples()
    ]
    path = os.path.join(out_dir, f"{ticker}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"ticker": ticker, "candles": candles}, f,
                  ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, path)


def run_market(market: str, args, run_date: str, data_root: str) -> dict:
    symbols = load_symbols(market)
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",")]
        symbols = {t: yf for t, yf in symbols.items() if t in wanted}
    if args.limit:
        symbols = dict(sorted(symbols.items())[:args.limit])
    if not symbols:
        print(f"[{market}] no universe — skipped")
        return {}

    provider = YFinanceProvider({t: info["yf"] for t, info in symbols.items()},
                                period=args.period)
    provider.fetch_all()
    stats = load_stats(market)

    chart_dir = os.path.join(data_root, "charts", market)
    os.makedirs(chart_dir, exist_ok=True)

    results = []
    charted = set()
    for t in provider.universe():
        df = provider.get_daily_bars(t)
        if df is None:
            continue
        recs = scan_ticker(t, df, market=market,
                           volume_is_usd=(market == "crypto"))
        info = symbols.get(t, {})
        for rec, _eng in recs:
            rec["name"] = info.get("name") or t
            rec["sector"] = info.get("sector") or ("Crypto" if market == "crypto" else "")
            # {stats} only speaks on graded continuation setups — the claim it
            # makes ("reached its first target zone…") is about this pattern.
            use_stats = stats if (rec["state"] in ("DISPLACED", "RUNNING")
                                  and rec["tier"] in ("A+", "A")) else None
            rec["narration"] = render(rec, use_stats)
            rec["next"] = render_next(rec)
            results.append(rec)
        if recs and t not in charted:
            write_chart_json(chart_dir, t, df)
            charted.add(t)

    snap = build_snapshot(run_date, universe_size=len(symbols),
                          results=sort_records(results))
    out_dir = os.path.join(data_root, market)
    write_snapshot(snap, out_dir)
    pruned = prune_stale_files(chart_dir, charted) + prune_dated_snapshots(out_dir)
    if pruned:
        print(f"[{market}] pruned {pruned} stale data file(s)")

    by_state = {}
    for r in results:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    # ASCII only — Windows consoles are cp1252 and choke on arrows/dashes
    print(f"[{market}] universe {len(symbols)} -> {len(results)} results {by_state}")
    return by_state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=f"{PRODUCT_NAME} scanner")
    ap.add_argument("--market", default="all",
                    help="asx | nasdaq | crypto | all (default all)")
    ap.add_argument("--tickers", help="comma-separated tickers to restrict to")
    ap.add_argument("--limit", type=int, help="scan only the first N of the universe")
    ap.add_argument("--out", help="data root override (default public/data/phasemap)")
    ap.add_argument("--period", default="2y", help="history period for yfinance")
    args = ap.parse_args(argv)

    markets = MARKETS if args.market == "all" else tuple(args.market.split(","))
    for m in markets:
        if m not in MARKETS:
            print(f"unknown market: {m}")
            return 2

    tz = zoneinfo.ZoneInfo(CONFIG.timezone)
    run_date = datetime.datetime.now(tz).date().isoformat()
    data_root = args.out or os.path.join(REPO_ROOT, CONFIG.output_dir)

    print(f"{PRODUCT_NAME} v{RULESET_VERSION} - {run_date}")
    for m in markets:
        run_market(m, args, run_date, data_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

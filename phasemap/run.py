"""PhaseMap CLI — nightly scan entry point, one snapshot per market.

Usage:
    python -m phasemap.run                          # all markets (asx, nasdaq, crypto)
    python -m phasemap.run --market asx
    python -m phasemap.run --market nasdaq --limit 50   # quick test: scratch dir
    python -m phasemap.run --tickers BHP,CBA        # specific ASX tickers (scratch dir)
    python -m phasemap.run --market asx --force     # rescan even with no new bar

Outputs, per market:
    public/data/phasemap/<market>/YYYY-MM-DD.json + latest.json   (scan snapshot)
    public/data/phasemap/<market>/narrations.json                 (narration sidecar)
    public/data/phasemap/<market>/confluence.json                 (ticker/direction/state)
    public/data/phasemap/charts/<market>/<TICKER>.json            (candles + record)

Exit codes (per market; the worst wins when several run):
    0  published a fresh scan
    3  CARRIED — no new completed bar since the last snapshot, so the last
       scan's records were re-published under today's run_date (REFINE200
       #45: weekend runs rescanned identical stock bars and swung 549 -> 773
       -> 475 results on Yahoo coverage alone)
    4  REFUSED — fetched coverage below PUBLISH_MIN_COVERAGE: the last good
       snapshot and every chart file were kept (REFINE200 #197)
    1  failed (no universe, a crash, or too many per-ticker faults)
    2  bad arguments
"""

import argparse
import csv
import datetime
import json
import os
import sys
import tempfile
import zoneinfo

from phasemap.config import (CHART_SIG_FIGS, CONFIG, DATED_SNAPSHOTS_KEEP,
                             PRODUCT_NAME, PUBLISH_MIN_COVERAGE, RULESET_VERSION,
                             TICKER_FAULT_MAX_SHARE)
from phasemap.data import session
from phasemap.data.provider import YFinanceProvider
from phasemap.engine.scanner import drop_forming_bar, scan_ticker, sort_records
from phasemap.engine.zones import round_sig
from phasemap.narrate.renderer import render, render_next
from phasemap.output.writer import (build_snapshot, write_confluence,
                                    write_snapshot)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASX_UNIVERSE_CSV = os.path.join(REPO_ROOT, "data_universe", "asx_tickers.csv")
STATS_DIR = os.path.join(REPO_ROOT, "phasemap", "backtest", "stats")

MARKETS = ("asx", "nasdaq", "crypto")
CHART_BARS = 220          # daily candles shipped to the chart page

PUBLISHED, CARRIED, REFUSED, FAILED = "published", "carried", "refused", "failed"
EXIT_CODES = {PUBLISHED: 0, CARRIED: 3, REFUSED: 4, FAILED: 1}
# The run's exit code when several markets run: the worst outcome wins.
_SEVERITY = (FAILED, REFUSED, CARRIED, PUBLISHED)


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
    history for anything pruned, so nothing user-facing breaks. Only ever
    called after a FULL-universe publish that cleared the coverage floor —
    a partial or refused run must not delete what it never looked at."""
    removed = 0
    try:
        for name in os.listdir(dir_path):
            if name.endswith(suffix) and name[:-len(suffix)] not in keep:
                os.remove(os.path.join(dir_path, name))
                removed += 1
    except FileNotFoundError:
        pass
    return removed


# Published files in a market dir that are NOT dated snapshots.
_UNDATED = ("latest.json", "narrations.json", "confluence.json")


def prune_dated_snapshots(out_dir: str, keep_last: int = DATED_SNAPSHOTS_KEEP) -> int:
    """Keep the newest `keep_last` dated snapshots (REFINE200 #60: nothing
    reads a dated file; latest/narrations/confluence untouched)."""
    removed = 0
    try:
        dated = sorted(n for n in os.listdir(out_dir)
                       if n.endswith(".json") and n not in _UNDATED)
        for name in dated[:-keep_last] if keep_last > 0 else dated:
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


def _write_if_changed(path: str, payload: str) -> bool:
    """REFINE200 #59: rewrite a file only when its bytes change. ~1,400 chart
    files were rewritten every night even when the bars were identical (a
    weekend, a carried run); identical bytes are now left alone."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            if f.read() == payload:
                return False
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    os.replace(tmp, path)
    return True


def _chart_payload(ticker: str, candles: list, records: list) -> str:
    """One chart file: the candles plus, per direction, the row exactly as
    latest.json carries it and its narration (REFINE200 #71 — the chart page
    loaded latest.json + narrations.json to show one record). `record` /
    `narration` describe the FIRST row (sort order) for readers that want a
    single setup; `records` keeps both directions when a name has two."""
    body = {"ticker": ticker, "candles": candles}
    if records:
        slim = [{k: v for k, v in r.items() if k != "narration"} for r in records]
        body["record"] = slim[0]
        body["narration"] = records[0].get("narration", "")
        if len(records) > 1:
            body["records"] = [{"record": s, "narration": r.get("narration", "")}
                               for s, r in zip(slim, records)]
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_chart_json(out_dir: str, ticker: str, df, records: list = None) -> bool:
    """Last CHART_BARS daily candles at CHART_SIG_FIGS significant figures
    (8 dp kept three digits of a 3e-06 coin), plus the ticker's published
    records. Returns True when the file's bytes changed."""
    if ticker.upper() in _WINDOWS_RESERVED:
        print(f"  chart skip: {ticker} is a Windows-reserved filename")
        return False
    tail = df.tail(CHART_BARS)
    sig = CHART_SIG_FIGS
    candles = [
        {"t": str(r.Date)[:10],
         "o": round_sig(float(r.Open), sig), "h": round_sig(float(r.High), sig),
         "l": round_sig(float(r.Low), sig), "c": round_sig(float(r.Close), sig),
         "v": int(r.Volume) if r.Volume == r.Volume else 0}
        for r in tail.itertuples()
    ]
    return _write_if_changed(os.path.join(out_dir, f"{ticker}.json"),
                             _chart_payload(ticker, candles, records or []))


def _refresh_chart_records(out_dir: str, ticker: str, records: list) -> bool:
    """A CARRIED run has no new bars: keep the file's candles, refresh only
    the record/narration (a re-render can change the words, not the bars)."""
    path = os.path.join(out_dir, f"{ticker}.json")
    try:
        with open(path, encoding="utf-8") as f:
            candles = json.load(f).get("candles") or []
    except (FileNotFoundError, ValueError):
        return False
    return _write_if_changed(path, _chart_payload(ticker, candles, records))


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def _generated_at(now: datetime.datetime) -> str:
    return now.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def _narrate(rec: dict, stats) -> None:
    # {stats} only speaks on graded continuation setups — the claim it makes
    # ("reached its first target zone…") is about this pattern.
    use_stats = stats if (rec["state"] in ("DISPLACED", "RUNNING")
                          and rec["tier"] in ("A+", "A")) else None
    rec["narration"] = render(rec, use_stats)
    rec["next"] = render_next(rec)


def _carry_forward(market: str, prev: dict, run_date: str, data_root: str,
                   now: datetime.datetime) -> str:
    """Re-publish the last scan's records under today's run_date: no new
    completed bar exists, so a rescan could only differ by Yahoo's coverage
    that night. Narrations are re-rendered (stats/wording may have moved);
    as_of stays the bar the records were computed on, and carried_from names
    the run that computed them, so nothing claims a fresh look."""
    out_dir = os.path.join(data_root, market)
    narr = (_read_json(os.path.join(out_dir, "narrations.json")) or {}).get("narrations", {})
    stats = load_stats(market)
    results = []
    for r in prev.get("results", []):
        rec = dict(r)
        rec.pop("narration", None)
        try:
            _narrate(rec, stats)
        except Exception:           # keep what was published rather than fail the carry
            rec["narration"] = narr.get(f"{rec['ticker']}|{rec['direction']}", "")
            rec["next"] = r.get("next", "")
        results.append(rec)
    snap = build_snapshot(run_date, universe_size=prev.get("universe_size", 0),
                          results=sort_records(results), as_of=prev.get("as_of"),
                          fetched=prev.get("fetched"),
                          carried_from=prev.get("carried_from") or prev.get("run_date"))
    write_snapshot(snap, out_dir)
    write_confluence(snap, out_dir, _generated_at(now))
    chart_dir = os.path.join(data_root, "charts", market)
    by_ticker = {}
    for rec in snap["results"]:
        by_ticker.setdefault(rec["ticker"], []).append(rec)
    touched = sum(_refresh_chart_records(chart_dir, t, recs) for t, recs in by_ticker.items())
    prune_dated_snapshots(out_dir)
    print(f"[{market}] no completed bar since {prev.get('as_of')} - carried "
          f"{len(results)} results forward from {snap['carried_from']} "
          f"({touched} chart record(s) refreshed)")
    return CARRIED


def run_market(market: str, args, run_date: str, data_root: str,
               now: datetime.datetime = None, provider=None) -> str:
    """Scan one market and publish it. Returns PUBLISHED / CARRIED / REFUSED /
    FAILED (see the module docstring). `now` and `provider` are injectable
    for tests; production reads the clock and builds a YFinanceProvider."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    partial = bool(getattr(args, "tickers", None) or getattr(args, "limit", None))
    out_dir = os.path.join(data_root, market)

    # REFINE200 #45: a stock market with no newly completed bar since the
    # last snapshot is not rescanned. Never for a partial run, a --force, a
    # ruleset change (the schema gate requires the current version) or a
    # previous file without as_of (the first run after this change).
    expected = session.latest_final_session(market, now)
    prev = _read_json(os.path.join(out_dir, "latest.json"))
    if (expected is not None and not partial and not getattr(args, "force", False)
            and prev and prev.get("ruleset_version") == RULESET_VERSION
            and prev.get("as_of") and prev["as_of"] >= expected.isoformat()):
        return _carry_forward(market, prev, run_date, data_root, now)

    symbols = load_symbols(market) if provider is None else \
        {t: {"yf": t, "name": t, "sector": ""} for t in provider.universe()}
    if args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",")]
        symbols = {t: yf for t, yf in symbols.items() if t in wanted}
    if args.limit:
        symbols = dict(sorted(symbols.items())[:args.limit])
    if not symbols:
        print(f"[{market}] no universe - nothing scanned")
        return FAILED

    if provider is None:
        provider = YFinanceProvider({t: info["yf"] for t, info in symbols.items()},
                                    period=args.period)
    provider.fetch_all()
    fetched = provider.fetched()
    coverage = fetched / len(symbols)
    # REFINE200 #197: an outage used to publish `results: []` over the last
    # good snapshot, prune every chart file and exit 0 — every gate passed.
    if fetched == 0 or coverage < PUBLISH_MIN_COVERAGE:
        print(f"[{market}] REFUSED: fetched {fetched}/{len(symbols)} tickers "
              f"({coverage:.0%} < {PUBLISH_MIN_COVERAGE:.0%} floor) - the last good "
              f"snapshot and chart files are kept")
        return REFUSED
    stats = load_stats(market)

    chart_dir = os.path.join(data_root, "charts", market)
    os.makedirs(chart_dir, exist_ok=True)

    results, faults, last_bars = [], [], []
    per_ticker = {}
    for t in provider.universe():
        if t not in symbols:
            continue
        try:
            df = provider.get_daily_bars(t)
            if df is None:
                continue
            # 24/7 markets: detection sees CLOSED bars only (v1.3.0, review H3);
            # session markets: no bar before its bar-final time (#131).
            df = drop_forming_bar(df, market, today=now.astimezone(datetime.timezone.utc).date())
            df = session.drop_unfinal_bar(df, market, now)
            if df is None or not len(df):
                continue
            last = df["Date"].iloc[-1]
            last_bars.append(str(last.date() if hasattr(last, "date") else last)[:10])
            recs = scan_ticker(t, df, market=market,
                               volume_is_usd=(market == "crypto"))
            info = symbols.get(t, {})
            done = []
            for rec, _eng in recs:
                rec["name"] = info.get("name") or t
                rec["sector"] = info.get("sector") or ("Crypto" if market == "crypto" else "")
                _narrate(rec, stats)
                done.append(rec)
        except Exception as e:      # one bad ticker never costs the market
            faults.append(f"{t}: {type(e).__name__}: {e}")
            continue
        results.extend(done)
        if done:
            per_ticker[t] = (df, done)

    if faults:
        print(f"[{market}] {len(faults)} ticker fault(s), first: {faults[:3]}")
    if len(faults) > max(1, TICKER_FAULT_MAX_SHARE * fetched):
        print(f"[{market}] FAILED: {len(faults)} of {fetched} tickers raised - "
              f"that is the code, not the data; nothing published")
        return FAILED

    snap = build_snapshot(run_date, universe_size=len(symbols),
                          results=sort_records(results),
                          as_of=max(last_bars) if last_bars else None,
                          fetched=fetched)
    write_snapshot(snap, out_dir)
    write_confluence(snap, out_dir, _generated_at(now))

    # Charts: written in the published sort order so `record` is the row a
    # reader lands on first; only files whose bytes changed are rewritten.
    order = {}
    for rec in snap["results"]:
        order.setdefault(rec["ticker"], []).append(rec)
    changed = 0
    for t, recs in order.items():
        changed += write_chart_json(chart_dir, t, per_ticker[t][0], recs)
    pruned = prune_dated_snapshots(out_dir)
    if not partial:
        pruned += prune_stale_files(chart_dir, set(order))
    if pruned:
        print(f"[{market}] pruned {pruned} stale data file(s)")

    by_state = {}
    for r in results:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    # ASCII only — Windows consoles are cp1252 and choke on arrows/dashes
    print(f"[{market}] universe {len(symbols)}, fetched {fetched} ({coverage:.0%}), "
          f"bars to {snap.get('as_of')} -> {len(results)} results {by_state} "
          f"({changed} chart file(s) changed)")
    return PUBLISHED


def main(argv=None, now: datetime.datetime = None) -> int:
    ap = argparse.ArgumentParser(prog=f"{PRODUCT_NAME} scanner")
    ap.add_argument("--market", default="all",
                    help="asx | nasdaq | crypto | all (default all)")
    ap.add_argument("--tickers", help="comma-separated tickers to restrict to")
    ap.add_argument("--limit", type=int, help="scan only the first N of the universe")
    ap.add_argument("--out", help="data root override (default public/data/phasemap)")
    ap.add_argument("--publish", action="store_true",
                    help="with --limit/--tickers: write into the LIVE data root anyway")
    ap.add_argument("--force", action="store_true",
                    help="rescan even when no new completed bar exists")
    ap.add_argument("--period", default="2y", help="history period for yfinance")
    args = ap.parse_args(argv)

    markets = MARKETS if args.market == "all" else tuple(args.market.split(","))
    for m in markets:
        if m not in MARKETS:
            print(f"unknown market: {m}")
            return 2

    now = now or datetime.datetime.now(datetime.timezone.utc)
    tz = zoneinfo.ZoneInfo(CONFIG.timezone)
    run_date = now.astimezone(tz).date().isoformat()
    data_root = args.out or os.path.join(REPO_ROOT, CONFIG.output_dir)
    # REFINE200 #198: the documented "quick test" (--limit 25) overwrote the
    # live snapshot with 25 names and pruned every other chart file, and the
    # workflow committed it. A partial run writes to a scratch dir unless
    # told otherwise.
    if (args.limit or args.tickers) and not args.out and not args.publish:
        data_root = tempfile.mkdtemp(prefix="phasemap-quick-")
        print(f"partial run (--limit/--tickers): writing to {data_root}, "
              f"not the live data (pass --publish to override)")

    print(f"{PRODUCT_NAME} v{RULESET_VERSION} - {run_date}")
    outcomes = []
    for m in markets:
        try:
            outcomes.append(run_market(m, args, run_date, data_root, now=now))
        except Exception as e:
            print(f"[{m}] FAILED: {type(e).__name__}: {e}")
            outcomes.append(FAILED)
    worst = min(outcomes, key=_SEVERITY.index)
    return EXIT_CODES[worst]


if __name__ == "__main__":
    sys.exit(main())

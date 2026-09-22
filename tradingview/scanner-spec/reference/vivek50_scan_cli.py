#!/usr/bin/env python3
"""Vivek 5.0 daily screener - end-to-end command line runner.

Ties the reference implementation in ``vivek50_screen.py`` to a real data source
and publishes the JSON payload described in Part 5.8 of the specification.

This is a SCAFFOLD, not a finished product. It has been syntax-checked and its
logic reviewed, but it has NEVER been run against live market data, because the
sandbox it was written in cannot reach a data provider. Treat the download path
as the part most likely to need work.

Usage
-----
    python vivek50_scan_cli.py --market crypto --mode B --out ./out
    python vivek50_scan_cli.py --market asx --mode A --limit 200 --verbose
    python vivek50_scan_cli.py --market nasdaq --symbols AAPL,MSFT,NVDA

Exit codes
----------
    0  scan completed and published
    1  scan failed outright (no market data at all, or a write failure)
    2  scan completed but coverage was below the floor (a degraded run)
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Iterable

import pandas as pd

from vivek50_screen import ScreenConfig, screen_frames

# --------------------------------------------------------------------------
# Market metadata. Everything market-specific lives here and nowhere else.
# --------------------------------------------------------------------------

MARKETS: dict[str, dict] = {
    "asx": {
        "suffix": ".AX",
        "timezone": "Australia/Sydney",
        "min_price": 0.02,
        "min_dollar_adv": 250_000.0,
        "currency": "AUD",
        "coverage_floor": 0.85,
    },
    "nasdaq": {
        "suffix": "",
        "timezone": "America/New_York",
        "min_price": 1.00,
        "min_dollar_adv": 1_000_000.0,
        "currency": "USD",
        "coverage_floor": 0.85,
    },
    "crypto": {
        "suffix": "-USD",
        "timezone": "UTC",
        "min_price": 0.0,
        "min_dollar_adv": 5_000_000.0,
        "currency": "USD",
        "coverage_floor": 0.90,
    },
}

# A tiny built-in universe so the script is runnable before a real universe
# loader is wired in. Replace load_universe() with the real thing.
FALLBACK_UNIVERSE: dict[str, list[str]] = {
    "asx": ["BHP", "CBA", "CSL", "NAB", "WBC", "FMG", "WES", "MQG", "TLS", "WOW"],
    "nasdaq": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD",
               "NFLX", "INTC"],
    "crypto": ["BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "LINK", "DOT", "INJ",
               "ENS"],
}


def load_universe(market: str, limit: int | None = None) -> list[str]:
    """Return the list of provider symbols for a market.

    REPLACE THIS. In the owner's repository the real loader is
    ``scanner.universe.load_universe(market_key, full=True)``, which returns a
    list of dicts carrying symbol, name and (for ASX) sector, already suffixed
    for the provider and already filtered for stablecoins. See Part 9.
    """
    suffix = MARKETS[market]["suffix"]
    syms = [f"{s}{suffix}" for s in FALLBACK_UNIVERSE[market]]
    return syms[:limit] if limit else syms


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def download_daily(symbols: list[str], bars: int, batch: int = 150,
                   verbose: bool = False) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV for every symbol, batched.

    Returns a dict of symbol -> DataFrame with columns Open/High/Low/Close/Volume
    and a DatetimeIndex. Symbols the provider does not return are simply absent;
    the caller decides what to do about that.

    The ``period`` is expressed in years because providers handle a bar count
    poorly. 750 daily bars is about three years.
    """
    try:
        import yfinance as yf
    except ImportError:  # pragma: no cover
        raise SystemExit("yfinance not installed: pip install yfinance")

    years = max(2, int(bars / 252) + 1)
    period = f"{years}y"
    frames: dict[str, pd.DataFrame] = {}

    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        if verbose:
            print(f"[data] batch {i // batch + 1}: {len(chunk)} symbols", flush=True)
        try:
            raw = yf.download(chunk, period=period, interval="1d",
                              group_by="ticker", auto_adjust=False,
                              progress=False, threads=True)
        except Exception as exc:  # network, rate limit, malformed response
            print(f"[data] batch failed: {exc}", file=sys.stderr, flush=True)
            continue

        for sym in chunk:
            try:
                df = raw[sym] if len(chunk) > 1 else raw
                df = df.dropna(how="all")
                if df.empty:
                    continue
                df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
                frames[sym] = df.tail(bars)
            except Exception:
                continue
        time.sleep(1.0)  # be polite; a throttled run is slower than a paced one

    return frames


def last_closed_bar_ok(df: pd.DataFrame, timezone: str, max_age_days: int) -> bool:
    """True when the frame's newest bar is recent enough IN THE MARKET's calendar.

    Fails CLOSED: an unusable timezone must never read as 'perfectly fresh'.
    See Part 7.8.
    """
    try:
        now = pd.Timestamp.now(tz=timezone).normalize()
    except Exception:
        return False
    try:
        last = pd.Timestamp(df.index[-1])
        if last.tzinfo is not None:
            last = last.tz_convert(timezone)
        else:
            last = last.tz_localize(timezone)
        return (now - last.normalize()).days <= max_age_days
    except Exception:
        return False


# --------------------------------------------------------------------------
# Publish
# --------------------------------------------------------------------------

def _json_default(o):
    """Make numpy scalars and NaN JSON-safe. allow_nan=False would otherwise
    raise on a field the screener legitimately leaves undefined."""
    try:
        import numpy as _np
        if isinstance(o, (_np.integer,)):
            return int(o)
        if isinstance(o, (_np.floating,)):
            f = float(o)
            return None if f != f else f
        if isinstance(o, (_np.bool_,)):
            return bool(o)
    except Exception:
        pass
    if isinstance(o, float) and o != o:
        return None
    return str(o)


def write_json_atomic(path: pathlib.Path, payload: dict) -> None:
    """Write JSON atomically: temp file in the same directory, then os.replace.

    A half-written payload that a front end reads is worse than no payload. The
    owner's repository requires this for every published artefact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1, allow_nan=False, sort_keys=False,
                      default=_json_default)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def build_payload(market: str, mode: str, cfg: ScreenConfig, hits: pd.DataFrame,
                  stats: dict, errors: list[dict]) -> dict:
    """Assemble the Part 5.8 payload."""
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market": market,
        "timeframe": "1d",
        "mode": mode,
        "params": dataclasses.asdict(cfg),
        "summary": stats,
        "results": json.loads(hits.to_json(orient="records"))
                   if not hits.empty else [],
        "errors": errors,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vivek 5.0 daily screener")
    ap.add_argument("--market", required=True, choices=sorted(MARKETS))
    ap.add_argument("--mode", default="B", choices=["A", "B", "C"],
                    help="A = divergence only; B = divergence OR score>=2; "
                         "C = both, direction-aligned")
    ap.add_argument("--symbols", default=None,
                    help="comma-separated override of the universe")
    ap.add_argument("--limit", type=int, default=None,
                    help="scan only the first N symbols (for testing)")
    ap.add_argument("--bars", type=int, default=750)
    ap.add_argument("--div-fresh", type=int, default=1,
                    help="RULE A recency window in CLOSED bars (see Part 5.3)")
    ap.add_argument("--signal-fresh", type=int, default=1,
                    help="RULE B recency window in CLOSED bars")
    ap.add_argument("--min-score", type=int, default=2,
                    help="RULE B threshold on abs(score); reachable set is {1,2,3}")
    ap.add_argument("--out", default="./out", help="output directory")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    meta = MARKETS[args.market]
    started = time.time()

    if args.symbols:
        universe = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        universe = load_universe(args.market, args.limit)
    if args.verbose:
        print(f"[run] {args.market}: {len(universe)} symbols, mode {args.mode}",
              flush=True)

    frames = download_daily(universe, args.bars, verbose=args.verbose)
    coverage = len(frames) / len(universe) if universe else 0.0
    if not frames:
        print("[run] no data returned for any symbol", file=sys.stderr)
        return 1

    errors: list[dict] = []
    gated: dict[str, pd.DataFrame] = {}
    skipped = {"stale": 0, "price": 0, "liquidity": 0, "flat": 0}
    for sym, df in frames.items():
        if not last_closed_bar_ok(df, meta["timezone"], 3):
            skipped["stale"] += 1
            errors.append({"symbol": sym, "stage": "freshness",
                           "error": "last bar older than max_data_age_days"})
            continue
        last = float(df["Close"].iloc[-1])
        if last < meta["min_price"]:
            skipped["price"] += 1
            continue
        adv = float((df["Close"] * df["Volume"]).tail(20).mean())
        if adv < meta["min_dollar_adv"]:
            skipped["liquidity"] += 1
            continue
        tail = df["Close"].tail(20)
        if float(tail.max() - tail.min()) == 0.0:
            skipped["flat"] += 1           # halted / stablecoin: see Part 7.5
            continue
        gated[sym] = df

    # ScreenConfig mirrors the Pine inputs; mode 1 = RULE A only, 2 = A or B.
    # Mode C (confluence) is not a ScreenConfig mode: it is mode 2 plus a
    # post-filter, because "both rules, directions agreeing" is a view of the
    # same computation rather than a different screen.
    cfg = ScreenConfig(
        mode=1 if args.mode == "A" else 2,
        min_signal_score=args.min_score,
        div_fresh_bars=args.div_fresh,
        signal_fresh_bars=args.signal_fresh,
    )

    hits = screen_frames(gated, cfg, market=args.market)
    if args.mode == "C" and not hits.empty:
        both = hits["rules"].astype(str).str.contains(r"A") & \
               hits["rules"].astype(str).str.contains(r"B")
        agree = hits["rule_a_direction"] == hits["rule_b_direction"]
        hits = hits[both & agree].reset_index(drop=True)

    stats = {
        "universe": len(universe),
        "downloaded": len(frames),
        "scanned": len(gated),
        "skipped": skipped,
        "coverage": round(coverage, 4),
        "hits": int(len(hits)),
        "errors": len(errors),
        "elapsed_s": round(time.time() - started, 1),
    }
    if not hits.empty:
        stats["hits_rule_a"] = int(hits["rule_a"].astype(bool).sum())
        stats["hits_rule_b"] = int(hits["rule_b"].astype(bool).sum())
        d = hits["direction"].astype(str)
        stats["hits_bull"] = int((d == "bull").sum())
        stats["hits_bear"] = int((d == "bear").sum())
        stats["hits_conflict"] = int((d == "conflict").sum())

    out = pathlib.Path(args.out) / f"{args.market}_rsidiv.json"
    payload = build_payload(args.market, args.mode, cfg, hits, stats, errors)
    write_json_atomic(out, payload)

    print(f"[run] {args.market}: {stats['hits']} hits from {stats['scanned']} "
          f"scanned ({stats['coverage']:.0%} coverage) in {stats['elapsed_s']}s "
          f"-> {out}")
    if not hits.empty:
        cols = [c for c in ("symbol", "rules", "direction", "score",
                            "best_bars_ago", "rule_a_pivot_bars_ago",
                            "rsi", "regime", "close") if c in hits.columns]
        print(hits[cols].head(25).to_string(index=False))

    if coverage < meta["coverage_floor"]:
        print(f"[run] WARNING coverage {coverage:.0%} below floor "
              f"{meta['coverage_floor']:.0%}: results are degraded",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

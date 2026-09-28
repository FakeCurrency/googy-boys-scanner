"""CLI: python -m scanner.ignition.run --market crypto [--backtest] [--dry-run]

Screens one market and publishes ONE file, `public/data/ignition/<market>.json`;
with --backtest it replays the market and publishes
`public/data/ignition/<market>_backtest.json` instead.

THE WRITE-SET IS THE FENCE. This module writes those two paths and nothing
else; `tests/test_ignition_fences.py` reads it to prove that -- it may not name
another lens's artefact, the bot book, the alert history or the funnel ledger.

A MARKET WITH NO DATA KEEPS ITS LAST GOOD FILE (the momentum lens's rule):
an empty download is a REPORTED decision -- exit 3, nothing written -- so the
page never says "nothing is coiling" when the truth is "we could not look".

EXIT CODES
    0  screened (or replayed) and published
    3  deliberately published nothing (no data); the previous file stands
    1  a real failure
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import time
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from scanner import config, output, scanerrors
from scanner import data as sdata
from scanner import universe as suniverse

from . import backtest as bt
from . import engine as E

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "public" / "data" / "ignition"
SCHEMA_VERSION = 1


def out_path(market: str) -> pathlib.Path:
    return OUT_DIR / f"{market}.json"


def backtest_path(market: str) -> pathlib.Path:
    return OUT_DIR / f"{market}_backtest.json"


def bar_is_forming(market: str, last_idx, now: dt.datetime) -> bool:
    """Is the trailing daily bar the current, still-forming session?

    Mirrors scan._bar_is_forming (crypto forms until UTC midnight; a stock bar
    forms until its session close) WITHOUT importing the VIVEK scan module --
    the lens keeps no edge into the files that decide trades.
    """
    mkt = config.MARKETS.get(market)
    tz = ZoneInfo(getattr(mkt, "timezone", "UTC") or "UTC")
    local = now.astimezone(tz)
    try:
        last = pd.Timestamp(last_idx).date()
    except Exception:
        return False
    if last != local.date():
        return False
    sess = config.VIVEK_JOURNAL_SESSION.get(market)
    if not sess:
        return True
    return (local.hour * 60 + local.minute) < (sess[2] * 60 + sess[3])


def split_forming(frame: pd.DataFrame, market: str, now: dt.datetime):
    """(completed bars, forming bar or None)."""
    df = E.clean(frame)
    if len(df) and bar_is_forming(market, df.index[-1], now):
        return df.iloc[:-1], df.iloc[-1:]
    return df, None


def _age_days(frame: pd.DataFrame, market: str) -> Optional[int]:
    tz = getattr(config.MARKETS.get(market), "timezone", None)
    try:
        return int(sdata._frame_age_days(frame, tz))
    except Exception:
        return None


def _load(market: str, period: str, limit: int, cache_key: Optional[str]):
    rows = suniverse.load_universe(market)
    if limit:
        rows = rows[:limit]
    fresh = sdata.download([r["yf"] for r in rows], period=period)
    stats: dict = {}
    frames = fresh
    if cache_key:
        frames, stats = sdata.merge_with_cache(cache_key, fresh, [r["yf"] for r in rows])
    return rows, frames, stats


def screen_market(market: str, *, frames: Optional[Dict[str, pd.DataFrame]] = None,
                  rows: Optional[List[dict]] = None, limit: int = 0,
                  now: Optional[dt.datetime] = None) -> Optional[dict]:
    """Screen one market -> payload, or None when there is no data at all.
    `frames`/`rows` are injectable so everything but the download is testable."""
    started = time.time()
    now = now or dt.datetime.now(dt.timezone.utc)
    cache_stats: dict = {}
    if frames is None:
        rows, frames, cache_stats = _load(market, config.IGNITION_DATA_PERIOD, limit,
                                          f"ignition-{market}")
    rows = rows or []
    if not frames:
        print(f"ignition: no data for {market} (download blocked/empty) - "
              f"keeping the existing file", flush=True)
        return None
    by_yf = {r["yf"]: r for r in rows}
    p = E.Params.from_config(market)
    errs = scanerrors.ErrorLog(f"ignition [{market}]")
    results: List[dict] = []
    skipped: Dict[str, int] = {}
    screened = 0
    for yf in sorted(frames):
        meta = by_yf.get(yf, {})
        symbol = meta.get("symbol") or yf.split("-")[0]
        try:
            age = _age_days(frames[yf], market)
            if age is not None and age > config.IGNITION_MAX_DATA_AGE_DAYS:
                skipped["stale frame"] = skipped.get("stale frame", 0) + 1
                continue
            done, forming = split_forming(frames[yf], market, now)
            if len(done) < config.IGNITION_MIN_BARS:
                skipped["short history"] = skipped.get("short history", 0) + 1
                continue
            screened += 1
            row = E.screen_frame(done, market, forming=forming, p=p)
            if row is None:
                continue
            row = {"symbol": symbol, "name": meta.get("name") or symbol, "yf": yf, **row}
            results.append(row)
        except Exception as exc:                          # noqa: BLE001
            errs.record(symbol, exc)
    results.sort(key=E.state_rank)
    counts = {s: sum(1 for r in results if r["state"] == s)
              for s in ("IGNITING", "RUNNING", "CLOSED", "COILED")}
    counts["provisional"] = sum(1 for r in results if r.get("provisional"))
    counts["igniting_confirmed"] = sum(1 for r in results if r["state"] == "IGNITING"
                                       and not r.get("provisional"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "lens": "ignition",
        "market": market,
        "generated_at": now.isoformat(timespec="seconds"),
        "ruleset_version": config.IGNITION_RULESET_VERSION,
        "timeframe": "1d",
        "last_closed_bar": max((r["last_bar"] for r in results), default=None),
        "report_only": True,
        "params": p.as_dict(),
        "rules": {
            "fresh_bars": config.IGNITION_FRESH_BARS,
            "keep_bars": config.IGNITION_KEEP_BARS,
            "base_bars": config.IGNITION_BASE_BARS,
            "trail_sma": config.IGNITION_TRAIL_SMA,
            "wide_stop_pct": config.IGNITION_WIDE_STOP_PCT,
        },
        "summary": {
            "universe": len(rows) or len(frames),
            "downloaded": len(frames),
            "screened": screened,
            "skipped": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
            "counts": counts,
            "errors": sum(errs.kinds().values()),
            "cache": cache_stats,
            "elapsed_s": round(time.time() - started, 1),
        },
        "results": results,
        "errors": errs.sample(),
    }
    print(errs.report(screened), flush=True)
    return payload


def backtest_market(market: str, *, limit: int = 0,
                    frames: Optional[Dict[str, pd.DataFrame]] = None,
                    rows: Optional[List[dict]] = None,
                    now: Optional[dt.datetime] = None) -> Optional[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if frames is None:
        rows, frames, _ = _load(market, config.IGNITION_BT_PERIOD, limit, None)
    rows = rows or []
    if not frames:
        print(f"ignition: backtest has no data for {market} - nothing written", flush=True)
        return None
    # Completed bars only: the forming bar of the run day is not history yet.
    done = {}
    for yf, f in frames.items():
        d, _ = split_forming(f, market, now)
        if len(d):
            done[yf] = d
    symbols = {r["yf"]: r["symbol"] for r in rows}
    started = time.time()
    payload = bt.backtest(done, market, symbols=symbols,
                          universe_size=len(rows) or len(frames), now=now)
    payload["elapsed_s"] = round(time.time() - started, 1)
    return payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scanner.ignition.run",
        description="IGNITION - report-only coil->ignition lens (%s)"
                    % config.IGNITION_RULESET_VERSION)
    p.add_argument("--market", default="crypto", choices=sorted(config.IGNITION_MARKETS))
    p.add_argument("--limit", type=int, default=0, help="at most N symbols (smoke tests)")
    p.add_argument("--dry-run", action="store_true", help="print, publish nothing")
    p.add_argument("--backtest", action="store_true",
                   help="replay and publish <market>_backtest.json instead of screening")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "backtest" if args.backtest else "screen"
    print(f"ignition: {mode} ruleset {config.IGNITION_RULESET_VERSION} "
          f"market={args.market}", flush=True)
    try:
        payload = (backtest_market(args.market, limit=args.limit) if args.backtest
                   else screen_market(args.market, limit=args.limit))
    except Exception as exc:                              # noqa: BLE001
        print(f"::error::ignition: {mode} {args.market} FAILED - "
              f"{type(exc).__name__}: {exc}", flush=True)
        return 1
    if payload is None:
        return 3
    if args.backtest:
        for line in bt.summary_lines(payload):
            print(line, flush=True)
    else:
        s = payload["summary"]
        c = s["counts"]
        print(f"ignition: {args.market} screened {s['screened']}/{s['downloaded']}  "
              f"IGNITING {c['IGNITING']} ({c['provisional']} provisional)  "
              f"RUNNING {c['RUNNING']}  CLOSED {c['CLOSED']}  COILED {c['COILED']}  "
              f"errors {s['errors']}  {s['elapsed_s']}s", flush=True)
        for r in payload["results"][:12]:
            print(f"    {r['state']:<9} {r['symbol']:<8} price {r.get('price')}"
                  f"{'  (provisional)' if r.get('provisional') else ''}", flush=True)
    if args.dry_run:
        print("ignition: dry run - nothing written", flush=True)
        return 0
    path = output.write_json(backtest_path(args.market) if args.backtest
                             else out_path(args.market), payload, newline=True)
    print(f"ignition: wrote {path.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())

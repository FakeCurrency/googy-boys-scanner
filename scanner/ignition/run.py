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
from collections import Counter
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
    if last < local.date():
        return False
    if last > local.date():
        # A bar dated AFTER the clock: the day rolled over while the download
        # ran (a run that starts at 23:5x UTC and finishes past midnight gets
        # the new day's minutes-old bar). It is forming by definition -- the
        # old `!=` test called it completed and screened a partial bar.
        return True
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


def _age_days(frame: pd.DataFrame, market: str, now: dt.datetime) -> Optional[int]:
    """Days between the frame's last bar and `now`, in the MARKET's calendar.

    Measured against the SAME clock the rest of the run uses (the injected
    `now`), never a second reading of the wall clock: two clocks inside one
    call once made a screen at an injected time call every frame stale. An
    unreadable frame or zone FAILS CLOSED (a huge age -> skipped), because
    "unknown" must never be read as "fresh".
    """
    df = E.clean(frame)
    if not len(df):
        return None
    try:
        tz = ZoneInfo(getattr(config.MARKETS.get(market), "timezone", "UTC") or "UTC")
        last = pd.Timestamp(df.index[-1]).date()
        return max(0, (now.astimezone(tz).date() - last).days)
    except Exception:
        return 10 ** 6


def _download(market: str, period: str, limit: int):
    """(universe rows, {yf: frame}, source report) through `data.fetch` -- the
    SAME market-aware entry point the VIVEK scan, the paper bot and the kill
    switch price through, so this lens can never disagree with them about a
    price. For crypto that is exchange daily klines (config
    CRYPTO_DATA_SOURCE) with Yahoo only for coins no exchange lists."""
    rows = suniverse.load_universe(market)
    if limit:
        rows = rows[:limit]
    frames, report = sdata.fetch(market, [r["yf"] for r in rows], period=period,
                                 ref_prices={r["yf"]: r.get("cg_price") for r in rows})
    return rows, frames, report


def _split_all(frames: Dict[str, pd.DataFrame], market: str, now: dt.datetime):
    """({yf: completed bars}, {yf: forming bar}) -- the forming bar is kept
    OUT of anything that persists, so the frame cache only ever holds
    completed bars (a cached mid-day snapshot, re-used the next day when
    Yahoo drops the ticker, would otherwise be screened as a finished bar)."""
    done: Dict[str, pd.DataFrame] = {}
    forming: Dict[str, pd.DataFrame] = {}
    for yf, f in frames.items():
        d, fm = split_forming(f, market, now)
        if len(d):
            done[yf] = d
        if fm is not None and len(fm):
            forming[yf] = fm
    return done, forming


def bar_freshness(frames: Dict[str, pd.DataFrame], forming: Dict[str, pd.DataFrame],
                  market: str, now: dt.datetime) -> dict:
    """How current the bars really are -- MEASURED, never assumed.

    The first real run (2026-09-28 02:00 UTC) screened through 26 Sep when
    27 Sep should have been complete: Yahoo had not yet served a usable
    27 Sep row. A lens whose value is catching a break the morning after it
    closes has to say when its data is a day behind, so the payload records
    the distribution of last COMPLETED and last RAW bar dates, the date that
    should be complete by now (crypto: yesterday UTC; a stock market: None,
    its calendar is not this function's business), and how many frames lag
    it. The page reads `lagging` to say so in words.
    """
    def day(df):
        try:
            return pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")
        except Exception:
            return None

    completed = [day(E.clean(f)) for f in frames.values() if len(f)]
    # `lagging` counts only frames the screen will actually READ: one past
    # IGNITION_MAX_DATA_AGE_DAYS is skipped as a "stale frame" (its own
    # count), and calling a coin last printed in 2022 "a day behind" was the
    # page overstating what it screens (re-review, 2026-09-28).
    screened = [day(E.clean(f)) for f in frames.values() if len(f)
                and (_age_days(f, market, now) or 0) <= config.IGNITION_MAX_DATA_AGE_DAYS]
    raw = [day(forming[yf]) if yf in forming else day(E.clean(f))
           for yf, f in frames.items() if len(f)]
    expected = None
    if not config.VIVEK_JOURNAL_SESSION.get(market):     # 24/7: yesterday is complete
        tz = ZoneInfo(getattr(config.MARKETS.get(market), "timezone", "UTC") or "UTC")
        expected = (now.astimezone(tz).date() - dt.timedelta(days=1)).isoformat()
    dist = lambda xs: dict(sorted(Counter(x for x in xs if x).items(), reverse=True)[:5])
    return {
        "completed_last": max((c for c in completed if c), default=None),
        "raw_last": max((r for r in raw if r), default=None),
        "expected_completed": expected,
        "lagging": (sum(1 for c in screened if c and c < expected) if expected else 0),
        "completed_dist": dist(completed),
        "raw_dist": dist(raw),
    }


def btc_regime(frames: Dict[str, pd.DataFrame]) -> Optional[dict]:
    """BTC's last COMPLETED close against its 200-SMA -- CONTEXT, never a gate.

    The first real replay split this way (pre-registered as a reported
    dimension, not a filter): BTC above its 200-SMA n=59 +1.90R, below n=8
    -0.46R. Eight trades cannot carry a rule, so nothing is filtered on it;
    the page states the regime the evidence came from and lets the reader
    weigh it. None when BTC is not in the frames or lacks 200 bars.
    """
    b = frames.get("BTC-USD")
    if b is None:
        return None
    b = E.clean(b)
    if len(b) < 200:
        return None
    sma = float(b["Close"].rolling(200).mean().iloc[-1])
    close = float(b["Close"].iloc[-1])
    return {"btc_close": round(close, 2), "btc_sma200": round(sma, 2),
            "btc_above_200": bool(close > sma),
            "btc_vs_200_pct": round((close / sma - 1) * 100, 1),
            "as_of": pd.Timestamp(b.index[-1]).strftime("%Y-%m-%d")}


def screen_market(market: str, *, frames: Optional[Dict[str, pd.DataFrame]] = None,
                  rows: Optional[List[dict]] = None, limit: int = 0,
                  now: Optional[dt.datetime] = None) -> Optional[dict]:
    """Screen one market -> payload, or None when there is no data at all.
    `frames`/`rows` are injectable so everything but the download is testable."""
    started = time.time()
    cache_stats: dict = {}
    src_report: dict = {}
    if frames is None:
        rows, fresh, src_report = _download(market, config.IGNITION_DATA_PERIOD, limit)
        # The clock is read AFTER the download, so "forming" is judged at the
        # moment the bars are actually in hand (the download takes minutes).
        now = now or dt.datetime.now(dt.timezone.utc)
        done, forming = _split_all(fresh, market, now)
        frames, cache_stats = sdata.merge_with_cache(
            f"ignition-{market}", done, [r["yf"] for r in rows])
    else:
        now = now or dt.datetime.now(dt.timezone.utc)
        frames, forming = _split_all(frames, market, now)
    rows = rows or []
    if not frames:
        print(f"ignition: no data for {market} (download blocked/empty) - "
              f"keeping the existing file", flush=True)
        return None
    bars = bar_freshness(frames, forming, market, now)
    print(f"ignition: bars - completed through {bars['completed_last']} "
          f"(expected {bars['expected_completed']}, {bars['lagging']} lagging), "
          f"raw through {bars['raw_last']}", flush=True)
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
            done = E.clean(frames[yf])
            age = _age_days(done, market, now)
            if age is not None and age > config.IGNITION_MAX_DATA_AGE_DAYS:
                skipped["stale frame"] = skipped.get("stale frame", 0) + 1
                continue
            if len(done) < config.IGNITION_MIN_BARS:
                skipped["short history"] = skipped.get("short history", 0) + 1
                continue
            screened += 1
            row = E.screen_frame(done, market, forming=forming.get(yf), p=p)
            if row is None:
                continue
            row = {"symbol": symbol, "name": meta.get("name") or symbol, "yf": yf,
                   "source": (src_report.get("source_of") or {}).get(yf, "cache" if src_report else "given"),
                   **row}
            results.append(row)
        except Exception as exc:                          # noqa: BLE001
            errs.record(symbol, exc)
    if screened == 0:
        # Frames came back but NONE could be screened (every one stale or
        # short -- e.g. a multi-day Yahoo outage leaving only cached frames
        # past the age ceiling). Publishing an empty list would tell the page
        # "nothing is coiling" when the truth is "we could not look": keep
        # the last good file instead, exactly like the no-data path.
        print(f"ignition: nothing screenable for {market} ({skipped}) - "
              f"keeping the existing file", flush=True)
        return None
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
        "regime": btc_regime(frames),
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
            "bars": bars,
            "sources": sdata.source_summary(src_report),
            "errors": sum(errs.kinds().values()),
            "cache": cache_stats,
            "elapsed_s": round(time.time() - started, 1),
        },
        "results": results,
        "errors": errs.sample(),
    }
    errs.report(screened)   # prints its own line
    return payload


def backtest_market(market: str, *, limit: int = 0,
                    frames: Optional[Dict[str, pd.DataFrame]] = None,
                    rows: Optional[List[dict]] = None,
                    now: Optional[dt.datetime] = None) -> Optional[dict]:
    src_report: dict = {}
    if frames is None:
        rows, frames, src_report = _download(market, config.IGNITION_BT_PERIOD, limit)
    now = now or dt.datetime.now(dt.timezone.utc)   # after the download
    rows = rows or []
    if not frames:
        print(f"ignition: backtest has no data for {market} - nothing written", flush=True)
        return None
    # Completed bars only: the forming bar of the run day is not history yet.
    done, _ = _split_all(frames, market, now)
    symbols = {r["yf"]: r["symbol"] for r in rows}
    sources = sdata.source_summary(src_report)
    started = time.time()
    payload = bt.backtest(done, market, symbols=symbols,
                          universe_size=len(rows) or len(frames), now=now,
                          data_note=data_note(sources))
    payload["elapsed_s"] = round(time.time() - started, 1)
    payload["sources"] = sources
    return payload


def data_note(sources: dict) -> str:
    """The backtest caveat naming where the bars came from. On exchange data
    it also says the one consequence a reader could not guess: the volume is
    ONE venue's, smaller than Yahoo's cross-exchange aggregate, so the
    turnover floors bind harder than they did on Yahoo."""
    by = (sources or {}).get("by_source") or {}
    if (sources or {}).get("mode") != "exchange" or not by:
        return "Yahoo daily crypto bars; young coins have thin early history."
    split = ", ".join("%s %d" % (k, v) for k, v in
                      sorted(by.items(), key=lambda kv: (-kv[1], kv[0])))
    return ("Daily bars per source (coins): %s. Exchange volume is one venue's, "
            "smaller than Yahoo's aggregate, so the turnover floors bind harder; "
            "young coins have thin early history." % split)


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

"""CLI: python -m scanner.momentum.run --market asx|nasdaq|crypto

Screens one market and publishes ONE file, `public/data/momentum/<market>.json`.

THE WRITE-SET IS THE FENCE. This module may write nowhere else, and
`tests/test_momentum_fences.py` reads it to prove that -- it may not name
another lens's artefact, the bot book, the alert history or the funnel ledger.

A MARKET WITH NO DATA KEEPS ITS LAST GOOD FILE. This copies `scanner/run.py`
rather than `scanner/spec_run.py`, deliberately: `spec_run.scan_market` has no
empty-frames guard, so a Yahoo-blocked market still publishes `"results": []`
OVER the previous good file, and the page then shows "nothing set up today" when
the truth is "we could not look". Here an empty download is a reported decision
-- exit code 3, a `::warning::`-friendly line on stdout, nothing written -- and
the workflow branches on it instead of failing a must-change gate that is
correctly unmet.

EXIT CODES, because the workflow needs to tell three outcomes apart:
    0  screened and published
    3  deliberately published nothing (no data); the previous file stands
    1  a real failure
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from scanner import data as sdata
from scanner import output
from scanner import scanerrors
from scanner import universe as suniverse

from . import config, gates
from .screen import screen_symbol

# The ONE output location. A subdirectory rather than
# `public/data/<market>_momentum.json` on purpose: nothing in the repo globs
# `public/data/*.json` today, but a subdirectory cannot be caught by one that
# appears later, and deletion is a single `git rm -r`.
ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "public" / "data" / "momentum"

TIMEFRAME = "1d"


def out_path(market: str) -> pathlib.Path:
    """The only path this lens is allowed to write."""
    return OUT_DIR / f"{market}.json"


def _frame_age_days(frame: pd.DataFrame, market: str) -> Optional[int]:
    """Bars-stale, measured in the MARKET's own calendar.

    Borrowed from `scanner.data` rather than reimplemented. It is a private
    name, which is impolite, but it is the tested implementation of a bug this
    repo has already paid for: a naive local date understates ASX staleness by
    a day, and the tz fallback there fails CLOSED rather than returning 0
    ("perfectly fresh") on an unusable zone. A second implementation would
    reintroduce exactly that.
    """
    meta = config.MARKETS_META.get(market)
    tz = getattr(meta, "timezone", None)
    try:
        return int(sdata._frame_age_days(frame, tz))
    except Exception:
        return None


def _last_bar(frame: pd.DataFrame) -> Optional[str]:
    try:
        return str(pd.Timestamp(frame.index[-1]).date())
    except Exception:
        return None


def screen_market(market: str, *, cfg=None, limit: int = 0,
                  frames: Optional[Dict[str, pd.DataFrame]] = None,
                  rows: Optional[List[dict]] = None) -> Optional[dict]:
    """Screen one market and return the payload, or None when there is no data.

    `frames` and `rows` are injectable so the whole path is testable without a
    network call -- the download is the only part that cannot be exercised in
    CI, so it is the only part left out.
    """
    cfg = (cfg or config.DEFAULTS).validate().assert_screenable()
    started = time.time()

    if rows is None:
        rows = suniverse.load_universe(market)
    if limit:
        rows = rows[:limit]
    by_yf = {r["yf"]: r for r in rows}

    cache_stats: Dict[str, Any] = {}
    if frames is None:
        fresh = sdata.download([r["yf"] for r in rows], period=config.DATA_PERIOD,
                               interval=TIMEFRAME)
        frames, cache_stats = sdata.merge_with_cache(
            f"momentum-{market}", fresh, [r["yf"] for r in rows])

    if not frames:
        # Nothing fresh AND nothing cached: the source is fully blocked. Keep
        # the existing JSON rather than clobbering it with an empty list.
        print(f"momentum: no data for {market} (download blocked/empty) - "
              f"keeping the existing file", flush=True)
        return None

    errs = scanerrors.ErrorLog(f"momentum [{market}]")
    results: List[dict] = []
    skipped: Dict[str, int] = {}
    stale = 0

    for yf_ticker in sorted(frames):
        frame = frames[yf_ticker]
        meta = by_yf.get(yf_ticker, {})
        symbol = meta.get("symbol") or yf_ticker
        try:
            reason = gates.gate_frame(frame, market, cfg=cfg,
                                      name=meta.get("name"), sector=meta.get("sector"))
            if reason is None:
                age = _frame_age_days(frame, market)
                if age is not None and age > config.MAX_DATA_AGE_DAYS:
                    # THE most dangerous silent failure a screener has: a fresh
                    # signal computed off a last bar that is not today's.
                    reason = f"stale frame ({age} sessions old)"
                    stale += 1
            if reason is not None:
                skipped[reason.split(" (")[0]] = skipped.get(reason.split(" (")[0], 0) + 1
                continue

            row = screen_symbol(frame, cfg, symbol=symbol, market=market)
            row["name"] = meta.get("name") or ""
            row["sector"] = meta.get("sector") or ""
            row["yf"] = yf_ticker
            row["is_product"] = gates.is_product(meta.get("name"), meta.get("sector"))
            row["dollar_adv_20"] = gates.dollar_adv(frame, market)
            row["data_age_days"] = _frame_age_days(frame, market)
            results.append(row)
        except Exception as exc:                      # noqa: BLE001
            # One symbol must never take down the market (spec 7.12), and the
            # error is PUBLISHED rather than logged: a name that throws every
            # night is otherwise indistinguishable from one that never sets up.
            errs.record(symbol, exc)

    hits = gates.select(results, cfg.mode)
    aligned = sum(1 for r in hits if gates.directions_agree(r))
    screened = len(results)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "market": market,
        "timeframe": TIMEFRAME,
        "last_closed_bar": max((_last_bar(f) for f in frames.values() if _last_bar(f)),
                               default=None),
        "ruleset_version": config.RULESET_VERSION,
        "mode": cfg.mode,
        "params": cfg.to_dict(),
        "summary": {
            "universe": len(rows),
            "downloaded": len(frames),
            "scanned": screened,
            "skipped_gates": sum(skipped.values()),
            "skipped_by_reason": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
            "stale_frames": stale,
            "hits": len(hits),
            "hits_rule_a": sum(1 for r in hits if r.get("rule_a")),
            "hits_rule_b": sum(1 for r in hits if r.get("rule_b")),
            "hits_both_aligned": aligned,
            "products_flagged": sum(1 for r in results if r.get("is_product")),
            "errors": sum(errs.kinds().values()),
            "cache": cache_stats,
            "elapsed_s": round(time.time() - started, 1),
        },
        "results": hits,
        # A first-class part of the payload, not a log line.
        "errors": errs.sample(),
    }
    print(errs.report(screened), flush=True)
    return payload


def publish(market: str, payload: dict) -> pathlib.Path:
    """Atomic, NaN-safe, LF-pinned -- `output.write_json` does all three.

    Never a hand-rolled publish: a bare NaN token makes the browser reject the
    WHOLE file (a blank page for one bad bar), and a non-atomic write can leave
    a truncated one. `tests/test_publish_integrity.py` sweeps `scanner/`
    recursively for the hand-rolled shapes, so this package is already enrolled
    in that gate.
    """
    return output.write_json(out_path(market), payload, newline=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scanner.momentum.run",
        description="VIVEK MOMENTUM - report-only divergence lens (%s)"
                    % config.RULESET_VERSION)
    p.add_argument("--market", default="asx", choices=sorted(config.MARKETS),
                   help="market to screen")
    p.add_argument("--mode", default=None, choices=sorted(config.MODES),
                   help="A = divergence only (default); B = A or B; "
                        "C = both, directions agreeing")
    p.add_argument("--window", type=int, default=None,
                   help="freshness, in BARS, for both rules (default 1)")
    p.add_argument("--limit", type=int, default=0,
                   help="screen at most N symbols (0 = no limit); for smoke tests")
    p.add_argument("--dry-run", action="store_true",
                   help="screen and print the summary, publish nothing")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    kw: Dict[str, Any] = {}
    if args.mode:
        kw["mode"] = args.mode
    if args.window:
        kw["div_fresh_bars"] = kw["signal_fresh_bars"] = args.window
    cfg = config.DEFAULTS.replace(**kw) if kw else config.DEFAULTS

    print(f"momentum: ruleset {config.RULESET_VERSION}  market={args.market}  "
          f"mode={cfg.mode}  window={cfg.div_fresh_bars}", flush=True)
    try:
        payload = screen_market(args.market, cfg=cfg, limit=args.limit)
    except Exception as exc:                          # noqa: BLE001
        print(f"::error::momentum: {args.market} FAILED - "
              f"{type(exc).__name__}: {exc}", flush=True)
        return 1

    if payload is None:
        return 3

    s = payload["summary"]
    print(f"momentum: {args.market} scanned {s['scanned']}/{s['universe']}  "
          f"skipped {s['skipped_gates']}  hits {s['hits']} "
          f"(A {s['hits_rule_a']}, B {s['hits_rule_b']}, aligned "
          f"{s['hits_both_aligned']})  errors {s['errors']}  "
          f"{s['elapsed_s']}s", flush=True)
    for reason, n in list(s["skipped_by_reason"].items())[:6]:
        print(f"    gate: {n:5d}  {reason}", flush=True)

    if args.dry_run:
        print("momentum: dry run - nothing written", flush=True)
        return 0
    path = publish(args.market, payload)
    print(f"momentum: wrote {path.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())

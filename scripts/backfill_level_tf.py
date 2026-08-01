#!/usr/bin/env python3
"""Backfill audit-only ``level_tf`` onto every bot-book row.

WHY
---
The n≥30 iterate-or-scale ruling needs expectancy by the 200-SMA that produced
the signal (weekly / 3d / h4). New tickets are stamped at fill time by
``vivek_run._ticket_to_position``; the existing ~48 open+closed rows predate
that stamp. This script fills the gap without touching any trade rule.

WHAT IT WRITES
--------------
Only ``level_tf`` and ``level_tf_source`` (audit stamp: ``scan`` / ``evaluate`` /
``backfill``). Everything else is FROZEN and verified before/after exactly like
``scripts/resize_book_notional.py``.

HOW IT RESOLVES level_tf
------------------------
1. Current scan payload (``public/data/<m>_vivek.json``) for OPEN rows still in
   the scan — cheap and matches what the bot would stamp today.
2. Otherwise: download history, run ``vivek.evaluate`` on the slice ending at
   ``entry_date`` (no look-ahead past the fill day), read ``sig["level_tf"]``.
3. If both fail: leave the row untouched (missing stays missing).

USAGE
-----
    python -m scripts.backfill_level_tf           # dry run
    python -m scripts.backfill_level_tf --apply   # write per-market books + combined
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config, vivek                                      # noqa: E402
from scanner.broker import vivek_run                                   # noqa: E402
from scanner.journal_common import atomic_write                        # noqa: E402

log = logging.getLogger("backfill_level_tf")

# Only fields we intend to introduce/change on a row.
WRITES = ("level_tf", "level_tf_source")

# Everything the track record is judged on — must not move. Same spirit as the
# resize script's FROZEN set (R fields, fills, ladder, status).
FROZEN = (
    "id", "symbol", "market", "direction", "entry", "stop", "risk",
    "tp1", "tp2", "tp3", "scale", "last_mark", "mae", "mfe",
    "mae_r", "mfe_r", "unreal_r", "realized_r", "gross_r", "cost_r",
    "booked_pct", "tp1_hit", "tp2_hit", "tp3_hit", "exits",
    "entry_date", "opened_at", "status", "rr", "exit_date", "exit_price",
    "exit_reason", "hold_days", "entry_type", "timeframe", "grade",
    "units", "notional", "risk_usd",
)


def frozen_fingerprint(pos: dict) -> str:
    return json.dumps({k: pos.get(k) for k in FROZEN}, sort_keys=True,
                      separators=(",", ":"))


def _scan_level_map(market: str) -> dict[str, str]:
    path = ROOT / "public" / "data" / f"{market}_vivek.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in payload.get("results") or []:
        sym = str(r.get("symbol") or "").upper()
        ltf = r.get("level_tf")
        if sym and ltf:
            out[sym] = ltf
    return out


def _evaluate_level_tf(market: str, symbol: str, entry_date: str,
                       frames_cache: dict) -> str | None:
    """Historical evaluate at entry_date close — no look-ahead past that bar."""
    mkt = config.MARKETS.get(market)
    if not mkt or not entry_date:
        return None
    yf = symbol + mkt.suffix
    df = frames_cache.get(yf)
    if df is None:
        try:
            from scanner.data import download
            got = download([yf], period="max")
            df = got.get(yf)
            frames_cache[yf] = df
        except Exception as e:
            log.warning("download %s failed: %s", yf, e)
            return None
    if df is None or len(df) < config.VIVEK_MIN_HISTORY + 5:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    try:
        target = dt.date.fromisoformat(entry_date)
    except Exception:
        return None
    # last bar on or before entry_date
    idx_dates = [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
    j = None
    for i, d in enumerate(idx_dates):
        if d <= target:
            j = i
        else:
            break
    if j is None or j < config.VIVEK_MIN_HISTORY:
        return None
    try:
        sig = vivek.evaluate(df.iloc[: j + 1])
    except Exception:
        return None
    if not sig:
        return None
    return sig.get("level_tf")


def backfill_market(market: str, apply: bool, stamp: str,
                    frames_cache: dict) -> dict:
    book = vivek_run._load_market_book(market)
    scan_map = _scan_level_map(market)
    rows = list(book.get("open") or []) + list(book.get("closed") or [])
    before = [frozen_fingerprint(p) for p in rows]

    filled = skipped = already = failed = 0
    changes = []
    for pos in rows:
        if pos.get("level_tf"):
            already += 1
            continue
        sym = str(pos.get("symbol") or "").upper()
        ltf = None
        src = None
        # Prefer live scan for still-open names (same stamp the runner would write).
        if pos.get("status") == "open" and sym in scan_map:
            ltf = scan_map[sym]
            src = "scan"
        else:
            ltf = _evaluate_level_tf(market, sym, pos.get("entry_date") or "",
                                     frames_cache)
            src = "evaluate"
        if not ltf:
            failed += 1
            continue
        pos["level_tf"] = ltf
        pos["level_tf_source"] = src or "backfill"
        filled += 1
        changes.append({"id": pos.get("id"), "symbol": sym, "level_tf": ltf,
                        "source": src})

    after = [frozen_fingerprint(p) for p in rows]
    if before != after:
        # Identify which frozen field moved
        for i, (b, a) in enumerate(zip(before, after)):
            if b != a:
                raise AssertionError(
                    f"frozen field moved on {rows[i].get('id')} during level_tf "
                    f"backfill — aborting (before={b} after={a})")

    result = {
        "market": market,
        "rows": len(rows),
        "filled": filled,
        "already": already,
        "failed": failed,
        "changes": changes,
        "applied": False,
    }
    if apply and filled:
        vivek_run._save_market_book(market, book)
        result["applied"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write books (default is dry-run)")
    ap.add_argument("--market", action="append", choices=[*config.MARKETS])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    markets = args.market or list(config.MARKETS)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    frames_cache: dict = {}
    summary = []
    for mk in markets:
        r = backfill_market(mk, args.apply, stamp, frames_cache)
        summary.append(r)
        print(f"[{mk}] rows={r['rows']} filled={r['filled']} "
              f"already={r['already']} failed={r['failed']} "
              f"applied={r['applied']}")
        for c in r["changes"][:12]:
            print(f"   {c['symbol']:<8} → {c['level_tf']:<8} ({c['source']})")
        if len(r["changes"]) > 12:
            print(f"   ... +{len(r['changes']) - 12} more")

    if args.apply:
        # Rebuild combined view the same way the runner does.
        vivek_run._write_combined()
        v = vivek_run._combined_view()
        print(f"rebuilt combined book: {len(v['open'])} open / {len(v['closed'])} closed")
    else:
        print("\nDRY RUN — re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

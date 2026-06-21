"""Alpaca paper-trading orchestrator — runs after every scalp scan.

Usage:
  python -m scanner.broker.paper_run          # normal
  python -m scanner.broker.paper_run --dry-run  # log only, submit nothing

Required env vars (GitHub secrets in CI):
  ALPACA_API_KEY     Alpaca key ID
  ALPACA_SECRET_KEY  Alpaca secret key

Optional:
  ALPACA_LIVE=true   Use live endpoint instead of paper (DO NOT set until
                     real-money go-live is deliberately approved)

Flow each run:
  1. Load scalp_journal.json
  2. Reconcile: pull Alpaca state, update / close journal positions
  3. Kill-switch: halt and flatten if daily loss limit breached
  4. Load scalp.json (latest scan output)
  5. Pre-trade gate: same daily caps + correlation caps as the paper journal
  6. Submit Alpaca bracket orders for new A+/A NASDAQ signals
  7. Save updated journal (both journal/ and public/data/)

Alpaca currently covers NASDAQ/NYSE equities only.
ASX and commodity signals are logged as skipped; IBKR integration TBD.
"""

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scanner.scalp_journal import (
    SCALP_JOURNAL_FILE, _session_day, _corr_group, _save,
    MAX_DAILY, MAX_LOSS, MAX_GROUP, NOTIONAL,
)
from scanner.broker.reconcile import reconcile_journal
from scanner.broker.bracket_order import submit as submit_bracket
from scanner.broker.kill_switch import check_and_kill


def _load_journal() -> dict:
    if SCALP_JOURNAL_FILE.exists():
        try:
            return json.loads(SCALP_JOURNAL_FILE.read_text())
        except Exception:
            pass
    return {"open": [], "closed": []}


def _load_scan() -> dict | None:
    scalp_file = ROOT / "public" / "data" / "scalp.json"
    if not scalp_file.exists():
        print("  paper_run: scalp.json not found — run the scanner first")
        return None
    try:
        return json.loads(scalp_file.read_text())
    except Exception as e:
        print(f"  paper_run: could not read scalp.json — {e}")
        return None


def run(dry_run: bool = False) -> None:
    if not os.environ.get("ALPACA_API_KEY"):
        print("  paper_run: ALPACA_API_KEY not set — broker sync skipped")
        return

    live = os.environ.get("ALPACA_LIVE", "").lower() == "true"
    mode = "LIVE ⚠️" if live else "PAPER"
    print(f"  paper_run: mode={mode}  dry_run={dry_run}")

    # Fail-closed live gate: surface blockers up front rather than erroring deep
    # in the first API call. Any live API call also re-checks this in _base().
    if live:
        from scanner.broker.safety import live_blockers, edge_summary
        blockers = live_blockers()
        s = edge_summary()
        print(f"  paper_run: edge so far — {s['n']} trades over {s['days']}d, "
              f"${s['total_pnl']:.2f} / {s['total_r']:.2f}R")
        if blockers:
            print("  paper_run: LIVE BLOCKED (fail-closed) — staying safe, not trading:")
            for b in blockers:
                print(f"    - {b}")
            return

    j = _load_journal()

    # ── 1. Reconcile existing broker positions ────────────────────────────────
    print("  paper_run: reconciling Alpaca state...")
    j = reconcile_journal(j)

    # ── 2. Kill-switch ────────────────────────────────────────────────────────
    if check_and_kill(j, dry_run=dry_run):
        print("  paper_run: kill-switch active — halting new orders")
        _save(j)
        return

    # ── 3. Load latest scan ───────────────────────────────────────────────────
    scan = _load_scan()
    if not scan:
        _save(j)
        return

    scan_ts  = scan.get("generated_at", "")
    sess_day = _session_day(scan_ts)

    # ── 4. Pre-trade gate ─────────────────────────────────────────────────────
    today_closed = [c for c in j["closed"] if c.get("session_day") == sess_day]
    today_open   = [p for p in j["open"]   if p.get("session_day") == sess_day]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    trades_used  = len(today_closed) + len(today_open)

    open_keys   = {(p["symbol"], p["direction"]) for p in j["open"]}
    group_count = {}
    for p in j["open"]:
        g = p.get("corr_group") or _corr_group(
            p["symbol"], p.get("asset_type", ""), p.get("sector", ""))
        group_count[g] = group_count.get(g, 0) + 1

    submitted = skipped_cap = skipped_asset = 0

    # ── 5. Evaluate each A+/A signal ─────────────────────────────────────────
    for r in scan.get("results", []):
        if r["grade"] not in ("A+", "A"):
            continue

        direction = r["dir"].lower()
        if (r["symbol"], direction) in open_keys:
            continue

        if trades_used + submitted >= MAX_DAILY:
            print(f"  paper_run: daily cap ({MAX_DAILY} trades) reached")
            break
        if today_pnl < -MAX_LOSS:
            print(f"  paper_run: daily loss cap (-${MAX_LOSS}) reached")
            break

        group = _corr_group(r["symbol"], r.get("asset_type", ""), r.get("sector", ""))
        if group_count.get(group, 0) >= MAX_GROUP:
            skipped_cap += 1
            continue

        entry = float(r["entry"])
        units = int(NOTIONAL / entry) if entry > 0 else 0
        if units == 0:
            continue

        pos = {
            "symbol":      r["symbol"],
            "name":        r.get("name", r["symbol"]),
            "asset_type":  r.get("asset_type", ""),
            "sector":      r.get("sector", ""),
            "corr_group":  group,
            "direction":   direction,
            "grade":       r["grade"],
            "score":       r["score"],
            "entry":       entry,
            "stop":        float(r["stop"]),
            "target":      float(r["target"]),
            "rr":          r["rr"],
            "units":       units,
            "yf_ticker":   r["symbol"],
            "opened_ts":   scan_ts,
            "session_day": sess_day,
            "status":      "open",
        }

        if dry_run:
            print(f"  paper_run [DRY]: {r['symbol']} {direction} "
                  f"entry={entry:.4f}  stop={r['stop']:.4f}  target={r['target']:.4f}  "
                  f"units={units}  group={group}")
            submitted += 1
            continue

        result = submit_bracket(pos)

        if result.get("skipped"):
            print(f"  paper_run: {r['symbol']} skipped — {result['reason']}")
            skipped_asset += 1
            continue

        pos["broker_order_id"]   = result["order_id"]
        pos["broker_client_oid"] = result.get("client_order_id", "")
        pos["broker_status"]     = result.get("status", "new")

        j["open"].append(pos)
        open_keys.add((r["symbol"], direction))
        group_count[group] = group_count.get(group, 0) + 1
        submitted += 1
        print(f"  paper_run: ✓ {r['symbol']} {direction} — order {result['order_id']}")

    print(f"  paper_run: {submitted} submitted, "
          f"{skipped_cap} skipped (corr cap), "
          f"{skipped_asset} skipped (asset type)")

    _save(j)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Alpaca paper-trading orchestrator")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be submitted but don't call the API")
    args = p.parse_args()
    run(dry_run=args.dry_run)

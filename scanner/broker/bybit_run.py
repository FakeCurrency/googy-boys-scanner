"""Bybit live-execution orchestrator — runs after every crypto scalp scan.

Usage:
  python -m scanner.broker.bybit_run            # normal
  python -m scanner.broker.bybit_run --dry-run  # log only, submit nothing

Required env vars (set as GitHub Secrets):
  BYBIT_API_KEY      Bybit key ID
  BYBIT_API_SECRET   Bybit secret key

Optional:
  BYBIT_TESTNET=false  Use live endpoint (default is testnet — must deliberately opt in)

Flow each run:
  1. Load scalp_journal.json
  2. Reconcile: pull Bybit positions/closed-PnL, update journal
  3. Kill-switch: halt and flatten if daily loss limit breached
  4. Load scalp.json (latest crypto scan output)
  5. Pre-trade gate: daily cap + correlation caps + daily loss cap
  6. Submit Bybit bracket orders for new A+/A crypto signals
  7. Save updated journal (journal/ and public/data/)
"""

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scanner.scalp_journal import (
    SCALP_JOURNAL_FILE, _atomic_write, _session_day, _corr_group,
    MAX_DAILY, MAX_LOSS, MAX_GROUP, NOTIONAL,
)
from scanner.broker import bybit_client as bc
from scanner.broker.bybit_reconcile import reconcile_journal
from scanner.broker.bybit_bracket import submit as submit_bracket, calc_qty
from scanner.broker.kill_switch import check_and_kill


PUBLIC_SCALP_JOURNAL = ROOT / "public" / "data" / "scalp_journal.json"


def _load_journal() -> dict:
    if SCALP_JOURNAL_FILE.exists():
        try:
            return json.loads(SCALP_JOURNAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"open": [], "closed": []}


def _load_scan() -> dict | None:
    # Try crypto-specific file first, fall back to combined scalp.json
    for fname in ("scalp_crypto.json", "scalp.json"):
        f = ROOT / "public" / "data" / fname
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception as e:
                print(f"  bybit_run: could not read {fname} — {e}")
    print("  bybit_run: no scalp scan output found — run the scanner first")
    return None


def _save(j: dict) -> None:
    payload = json.dumps(j, indent=2)
    _atomic_write(SCALP_JOURNAL_FILE, payload)
    _atomic_write(PUBLIC_SCALP_JOURNAL, payload)


def run(dry_run: bool = False) -> None:
    if not os.environ.get("BYBIT_API_KEY"):
        print("  bybit_run: BYBIT_API_KEY not set — skipping broker execution")
        return

    print(f"  bybit_run: mode={bc.mode()}  dry_run={dry_run}")

    j = _load_journal()

    # ── 1. Reconcile ─────────────────────────────────────────────────────────
    print("  bybit_run: reconciling Bybit positions…")
    j = reconcile_journal(j)

    # ── 2. Kill-switch ────────────────────────────────────────────────────────
    if check_and_kill(j, dry_run=dry_run):
        print("  bybit_run: kill-switch active — halting new orders")
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
    today_closed = [c for c in j["closed"] if c.get("session_day") == sess_day
                    and not c.get("skip_daily_count")]
    today_open   = [p for p in j["open"]   if p.get("session_day") == sess_day]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    trades_used  = len(today_closed) + len(today_open)

    open_keys   = {(p["symbol"], p["direction"]) for p in j["open"]}
    group_count: dict[str, int] = {}
    for p in j["open"]:
        g = p.get("corr_group") or _corr_group(
            p["symbol"], p.get("asset_type", ""), p.get("sector", ""))
        group_count[g] = group_count.get(g, 0) + 1

    submitted = skipped_cap = skipped_asset = 0

    # ── 5. Evaluate each A+/A crypto signal ──────────────────────────────────
    for r in scan.get("results", []):
        if r.get("grade") not in ("A+", "A"):
            continue
        if r.get("asset_type", "").lower() != "crypto":
            skipped_asset += 1
            continue

        direction = r["dir"].lower()
        symbol    = r["symbol"]
        if (symbol, direction) in open_keys:
            continue

        if trades_used + submitted >= MAX_DAILY:
            print(f"  bybit_run: daily cap ({MAX_DAILY}) reached")
            break
        if today_pnl < -MAX_LOSS:
            print(f"  bybit_run: daily loss cap (-${MAX_LOSS}) reached")
            break

        group = _corr_group(symbol, r.get("asset_type", ""), r.get("sector", ""))
        if group_count.get(group, 0) >= MAX_GROUP:
            skipped_cap += 1
            continue

        entry = float(r["entry"])
        units = calc_qty(entry, NOTIONAL)
        if units <= 0:
            continue

        pos = {
            "symbol":      symbol,
            "name":        r.get("name", symbol),
            "asset_type":  "crypto",
            "sector":      r.get("sector", "crypto"),
            "corr_group":  group,
            "direction":   direction,
            "grade":       r["grade"],
            "score":       r["score"],
            "entry":       entry,
            "stop":        float(r["stop"]),
            "target":      float(r["target"]),
            "rr":          r["rr"],
            "units":       units,
            "yf_ticker":   r.get("yf_ticker", symbol + "-USD"),
            "opened_ts":   scan_ts,
            "session_day": sess_day,
            "status":      "open",
        }

        if dry_run:
            print(f"  bybit_run [DRY]: {symbol} {direction}  "
                  f"entry={entry:.4f}  stop={r['stop']:.4f}  target={r['target']:.4f}  "
                  f"qty={units:.4f}  group={group}")
            submitted += 1
            continue

        result = submit_bracket(pos)

        if result.get("skipped"):
            print(f"  bybit_run: {symbol} skipped — {result['reason']}")
            skipped_asset += 1
            continue

        pos["broker_order_id"]   = result["order_id"]
        pos["broker_link_id"]    = result.get("order_link_id", "")
        pos["bybit_symbol"]      = result.get("bybit_symbol", "")
        pos["broker_status"]     = result.get("status", "New")

        j["open"].append(pos)
        open_keys.add((symbol, direction))
        group_count[group] = group_count.get(group, 0) + 1
        submitted += 1
        print(f"  bybit_run: ✓ {symbol} {direction} → order {result['order_id']}")

    print(f"  bybit_run: {submitted} submitted, "
          f"{skipped_cap} skipped (corr cap), "
          f"{skipped_asset} skipped (non-crypto)")

    _save(j)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Bybit execution orchestrator")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be submitted but don't call the API")
    args = p.parse_args()
    run(dry_run=args.dry_run)

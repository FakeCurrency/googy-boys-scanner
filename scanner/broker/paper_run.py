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
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / "journal" / "paper_run.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S UTC",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("paper_run")

from scanner.scalp_journal import (
    SCALP_JOURNAL_FILE, _session_day, _corr_group, _save,
    MAX_DAILY, MAX_LOSS, MAX_GROUP,
)
from scanner import config as _cfg
from scanner.broker.bybit_bracket import calc_qty_risk
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
        log.warning("ALPACA_API_KEY not set — broker sync skipped")
        return

    live = os.environ.get("ALPACA_LIVE", "").lower() == "true"
    mode = "LIVE ⚠️" if live else "PAPER"
    log.info("starting  mode=%s  dry_run=%s", mode, dry_run)

    j = _load_journal()

    # ── 1. Reconcile existing broker positions ────────────────────────────────
    log.info("reconciling Alpaca state…")
    j = reconcile_journal(j)

    # ── 2. Kill-switch ────────────────────────────────────────────────────────
    if check_and_kill(j, dry_run=dry_run):
        log.warning("kill-switch active — halting new orders")
        _save(j)
        return

    # ── 3. Load latest scan ───────────────────────────────────────────────────
    scan = _load_scan()
    if not scan:
        _save(j)
        return

    scan_ts  = scan.get("generated_at", "")
    sess_day = _session_day(scan_ts)
    log.info("scan ts=%s  session_day=%s", scan_ts, sess_day)

    # ── 4. Pre-trade gate ─────────────────────────────────────────────────────
    today_closed = [c for c in j["closed"]
                    if c.get("session_day") == sess_day and not c.get("skip_daily_count")]
    today_open   = [p for p in j["open"]   if p.get("session_day") == sess_day]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    trades_used  = len(today_closed) + len(today_open)
    log.info("pre-trade gate  trades_used=%d/%d  today_pnl=%.2f  loss_limit=%.2f",
             trades_used, MAX_DAILY, today_pnl, -MAX_LOSS)

    open_keys   = {(p["symbol"], p["direction"]) for p in j["open"]}
    group_count: dict[str, int] = {}
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
        symbol    = r["symbol"]
        if (symbol, direction) in open_keys:
            continue

        if trades_used + submitted >= MAX_DAILY:
            log.warning("daily cap (%d) reached", MAX_DAILY)
            break
        if today_pnl < -MAX_LOSS:
            log.warning("daily loss cap (-$%.2f) reached", MAX_LOSS)
            break

        group = _corr_group(symbol, r.get("asset_type", ""), r.get("sector", ""))
        if group_count.get(group, 0) >= MAX_GROUP:
            log.info("skip %s — corr group '%s' at cap", symbol, group)
            skipped_cap += 1
            continue

        entry = float(r["entry"])
        stop  = float(r["stop"])
        units = calc_qty_risk(entry, stop, _cfg.SCALP_RISK_PER_TRADE)
        if units <= 0:
            log.warning("skip %s — qty=0  entry=%.6f  stop=%.6f", symbol, entry, stop)
            continue

        pos = {
            "symbol":        symbol,
            "name":          r.get("name", symbol),
            "asset_type":    r.get("asset_type", ""),
            "sector":        r.get("sector", ""),
            "corr_group":    group,
            "direction":     direction,
            "grade":         r["grade"],
            "score":         r["score"],
            "entry":         entry,
            "stop":          stop,
            "target":        float(r["target"]),
            "rr":            r["rr"],
            "units":         units,
            "risk_per_trade": _cfg.SCALP_RISK_PER_TRADE,
            "atr":           r.get("atr", 0.0),
            "market_regime": r.get("market_regime", "unknown"),
            "yf_ticker":     symbol,
            "opened_ts":     scan_ts,
            "session_day":   sess_day,
            "status":        "open",
        }

        if dry_run:
            log.info("[DRY] %s %s  entry=%.4f  stop=%.4f  target=%.4f  qty=%.4f  group=%s  rr=%s",
                     symbol, direction, entry, stop, float(r["target"]), units, group, r["rr"])
            submitted += 1
            continue

        result = submit_bracket(pos)

        if result.get("skipped"):
            log.warning("order skipped  %s — %s", symbol, result["reason"])
            skipped_asset += 1
            continue

        pos["broker_order_id"]   = result["order_id"]
        pos["broker_client_oid"] = result.get("client_order_id", "")
        pos["broker_status"]     = result.get("status", "new")

        j["open"].append(pos)
        open_keys.add((symbol, direction))
        group_count[group] = group_count.get(group, 0) + 1
        submitted += 1
        log.info("ORDER PLACED  %s %s → order_id=%s", symbol, direction, result["order_id"])

    log.info("run complete  submitted=%d  skipped_corr_cap=%d  skipped_asset=%d",
             submitted, skipped_cap, skipped_asset)

    _save(j)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Alpaca paper-trading orchestrator")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be submitted but don't call the API")
    args = p.parse_args()
    run(dry_run=args.dry_run)

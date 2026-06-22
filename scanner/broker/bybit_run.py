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
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / "journal" / "bybit_run.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S UTC",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("bybit_run")

from scanner.scalp_journal import (
    SCALP_JOURNAL_FILE, _atomic_write, _session_day, _corr_group,
    MAX_DAILY, MAX_LOSS, MAX_GROUP,
)
from scanner import config as _cfg
from scanner.broker import bybit_client as bc
from scanner.broker.bybit_reconcile import reconcile_journal
from scanner.broker.bybit_bracket import submit as submit_bracket, calc_qty_risk
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


def _save(j: dict, broker_mode: str = "") -> None:
    if broker_mode:
        j["broker_mode"] = broker_mode
    payload = json.dumps(j, indent=2)
    _atomic_write(SCALP_JOURNAL_FILE, payload)
    _atomic_write(PUBLIC_SCALP_JOURNAL, payload)


def run(dry_run: bool = False) -> None:
    has_api_key = bool(os.environ.get("BYBIT_API_KEY"))
    simulated   = not has_api_key

    if simulated:
        log.warning("BYBIT_API_KEY not set — running in SIMULATED mode "
                    "(orders logged but NOT submitted to any broker)")
    else:
        log.info("starting  mode=%s  dry_run=%s", bc.mode(), dry_run)

    j = _load_journal()

    # ── 1. Reconcile ─────────────────────────────────────────────────────────
    if simulated:
        log.info("skipping Bybit reconcile (no API key — SIMULATED mode)")
    else:
        log.info("reconciling Bybit positions…")
        j = reconcile_journal(j)

    # ── 2. Kill-switch ────────────────────────────────────────────────────────
    if check_and_kill(j, dry_run=dry_run or simulated):
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
    today_closed = [c for c in j["closed"] if c.get("session_day") == sess_day
                    and not c.get("skip_daily_count")]
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

    # ── 5. Evaluate each A+/A crypto signal ──────────────────────────────────
    for r in scan.get("results", []):
        if r.get("grade") not in ("A+", "A"):
            continue
        if r.get("asset_type", "").lower() != "crypto":
            skipped_asset += 1
            log.debug("skip %s — not crypto (asset_type=%s)", r.get("symbol"), r.get("asset_type"))
            continue

        direction = r["dir"].lower()
        symbol    = r["symbol"]
        if (symbol, direction) in open_keys:
            log.debug("skip %s %s — already open", symbol, direction)
            continue

        if trades_used + submitted >= MAX_DAILY:
            log.warning("daily cap (%d) reached — no more orders this session", MAX_DAILY)
            break
        if today_pnl < -MAX_LOSS:
            log.warning("daily loss cap (-$%.2f) reached — no more orders this session", MAX_LOSS)
            break

        group = _corr_group(symbol, r.get("asset_type", ""), r.get("sector", ""))
        if group_count.get(group, 0) >= MAX_GROUP:
            log.info("skip %s — corr group '%s' at cap (%d)", symbol, group, MAX_GROUP)
            skipped_cap += 1
            continue

        entry = float(r["entry"])
        stop  = float(r["stop"])
        units = calc_qty_risk(entry, stop, _cfg.SCALP_RISK_PER_TRADE)
        if units <= 0:
            log.warning("skip %s — qty=0 at entry=%.6f  stop=%.6f  risk_per_trade=%.2f",
                        symbol, entry, stop, _cfg.SCALP_RISK_PER_TRADE)
            continue

        regime = r.get("market_regime", "unknown")
        log.info("sizing  %s  entry=%.6f  stop=%.6f  stop_dist=%.6f  risk=$%.2f  qty=%.4f  regime=%s",
                 symbol, entry, stop, abs(entry - stop), _cfg.SCALP_RISK_PER_TRADE, units, regime)

        pos = {
            "symbol":        symbol,
            "name":          r.get("name", symbol),
            "asset_type":    "crypto",
            "sector":        r.get("sector", "crypto"),
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
            "adx":           r.get("adx", 0.0),
            "market_regime": regime,
            "yf_ticker":     r.get("yf_ticker", symbol + "-USD"),
            "opened_ts":     scan_ts,
            "session_day":   sess_day,
            "status":        "open",
        }

        if dry_run:
            log.info("[DRY] %s %s  entry=%.4f  stop=%.4f  target=%.4f  qty=%.4f  "
                     "group=%s  rr=%s  regime=%s",
                     symbol, direction, entry, stop, float(r["target"]),
                     units, group, r["rr"], regime)
            submitted += 1
            continue

        if simulated:
            # No API key — record as a simulated position so the full pipeline
            # (gate checks, correlation caps, journal, risk dashboard) still runs.
            pos["broker_order_id"] = f"SIM-{symbol}-{direction}-{sess_day}"
            pos["broker_status"]   = "SIMULATED"
            j["open"].append(pos)
            open_keys.add((symbol, direction))
            group_count[group] = group_count.get(group, 0) + 1
            submitted += 1
            log.info("[SIM] %s %s  entry=%.4f  stop=%.4f  target=%.4f  qty=%.4f  regime=%s",
                     symbol, direction, entry, stop, float(r["target"]), units, regime)
            continue

        log.info("submitting bracket  %s %s  entry=%.4f  stop=%.4f  target=%.4f  qty=%.4f",
                 symbol, direction, entry, stop, float(r["target"]), units)
        result = submit_bracket(pos)

        if result.get("skipped"):
            log.warning("order skipped  %s — %s", symbol, result["reason"])
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
        log.info("ORDER PLACED  %s %s → order_id=%s  link_id=%s",
                 symbol, direction, result["order_id"], result.get("order_link_id", ""))

    log.info("run complete  submitted=%d  skipped_corr_cap=%d  skipped_non_crypto=%d",
             submitted, skipped_cap, skipped_asset)

    broker_mode = "SIMULATED" if simulated else bc.mode()
    _save(j, broker_mode=broker_mode)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Bybit execution orchestrator")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be submitted but don't call the API")
    args = p.parse_args()
    run(dry_run=args.dry_run)

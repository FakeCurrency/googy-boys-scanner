"""Daily-loss kill-switch.

Checks the session P&L (realised + unrealised) against SCALP_MAX_DAILY_LOSS.
If the limit is breached, flattens all broker positions and cancels all orders,
then fires an alert via alert_dispatch.

Runs:
  • At the start of bybit_run / paper_run (pre-trade gate)
  • As a standalone hourly workflow to catch moves between scans
    (python -m scanner.broker.kill_switch)
"""

import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

log = logging.getLogger(__name__)


def check_and_kill(j: dict, dry_run: bool = False,
                   limit_usd: float | None = None, label: str = "session") -> bool:
    """Return True if the kill switch fired (caller must abort new orders).

    j          — journal-shaped dict: open[].unreal_pnl + closed[].{session_day,pnl}
    limit_usd  — loss limit; defaults to the legacy SCALP_MAX_DAILY_LOSS so the
                 pre-2026-07-20 call sites/tests behave identically. The bot-book
                 path (run_standalone) passes the VIVEK guard limit instead.
    label      — names the P&L source in logs/alerts (e.g. "bot book [asx]").
    """
    from scanner.config import SCALP_MAX_DAILY_LOSS
    from scanner.scalp_journal import _session_day

    limit = SCALP_MAX_DAILY_LOSS if limit_usd is None else float(limit_usd)
    today        = _session_day()
    today_closed = [c for c in j.get("closed", []) if c.get("session_day") == today]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    unrealised   = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
    total_session = today_pnl + unrealised

    if total_session >= -limit:
        return False

    log.warning("KILL SWITCH TRIGGERED — %s P&L = $%.2f (limit -$%.2f)",
                label, total_session, limit)

    # Dispatch alert to all configured channels
    try:
        from .alert_dispatch import send as _alert
        _alert(
            "kill_switch",
            f"Kill switch triggered — {label} P&L ${total_session:.2f}",
            f"Daily loss limit: -${limit:.2f}. "
            f"{'DRY RUN — not flattening.' if dry_run else 'Flattening all positions now.'}",
        )
    except Exception as e:
        log.warning("could not send kill-switch alert: %s", e)

    if dry_run:
        log.info("kill-switch: dry_run=True — not flattening")
        return True

    if os.environ.get("BYBIT_API_KEY"):
        from scanner.broker import bybit_client as bc
        try:
            bc.cancel_all_orders()
            log.info("kill-switch: Bybit orders cancelled")
        except Exception as e:
            log.error("kill-switch: error cancelling Bybit orders: %s", e)
        try:
            bc.close_all_positions()
            log.info("kill-switch: Bybit positions closed")
        except Exception as e:
            log.error("kill-switch: error closing Bybit positions: %s", e)

    elif os.environ.get("ALPACA_API_KEY"):
        from scanner.broker import alpaca_client as ac
        try:
            resp = ac.close_all_positions()
            log.info("kill-switch: Alpaca positions closed: %s", resp)
        except Exception as e:
            log.error("kill-switch: error closing Alpaca positions: %s", e)
        try:
            resp = ac.cancel_all_orders()
            log.info("kill-switch: Alpaca orders cancelled: %s", resp)
        except Exception as e:
            log.error("kill-switch: error cancelling Alpaca orders: %s", e)

    else:
        log.warning("kill-switch: no broker API keys set — skipping flatten")

    return True


def _book_market_journal(book: dict, market: str, market_day: str) -> dict:
    """Adapt ONE market's slice of the BOT BOOK to check_and_kill's journal shape.

    Selection is by the market-local day (exit_date), but rows are stamped with
    the AEST _session_day() key because that is what check_and_kill compares
    against. Open positions carry the marks the runner stamped LAST SCAN
    (unreal_usd on the remaining fraction + banked realized_r) — no live
    re-pricing here, so the reading can be up to one scan interval old.
    """
    from scanner.scalp_journal import _session_day
    key = _session_day()
    closed = [{"session_day": key,
               "pnl": (t.get("realized_r") or 0.0) * (t.get("risk_usd") or 0.0)}
              for t in book.get("closed", [])
              if t.get("market") == market and t.get("exit_date") == market_day]
    open_ = [{"unreal_pnl": ((p.get("unreal_usd") or 0.0)
                             + (p.get("realized_r") or 0.0) * (p.get("risk_usd") or 0.0))}
             for p in book.get("open", []) if p.get("market") == market]
    return {"open": open_, "closed": closed}


def run_standalone(dry_run: bool = False) -> dict:
    """Check the BOT BOOK — the one-and-only track record — per market.

    Rewritten 2026-07-20 (review C5): the old version read the retired scalp
    journal, whose file no longer exists — session P&L was always $0.00 and
    the switch could never fire. It now reads journal/vivek_bot_book.json and
    applies the same per-market limit the runner's own guard uses
    (VIVEK_BOT_MAX_DAILY_LOSS_PCT of VIVEK_BOT_ACCOUNT_EQUITY).
    Returns {"triggered": [markets], "checked": [markets]} for tests/callers.
    """
    import datetime as dt
    import json
    from zoneinfo import ZoneInfo

    from scanner import config
    from scanner.broker.vivek_run import BOOK_FILE

    book = {"open": [], "closed": []}
    if BOOK_FILE.exists():
        try:
            book = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            # Fail LOUD (C2 spirit): an unreadable track record must alert,
            # not silently report "all clear" on an empty dict.
            log.error("kill-switch: could not read bot book (%s)", e)
            try:
                from .alert_dispatch import send as _alert
                _alert("scan_error", "Kill-switch could not read the bot book",
                       f"{BOOK_FILE}: {e} - loss guard is flying blind until fixed.")
            except Exception:
                pass
    else:
        log.warning("kill-switch: no bot book at %s yet - nothing to guard", BOOK_FILE)

    equity = config.VIVEK_BOT_ACCOUNT_EQUITY
    pct = getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0) or 0.0
    limit = equity * pct / 100.0
    out = {"triggered": [], "checked": []}
    for market, mkt in config.MARKETS.items():
        market_day = dt.datetime.now(ZoneInfo(mkt.timezone)).strftime("%Y-%m-%d")
        j = _book_market_journal(book, market, market_day)
        out["checked"].append(market)
        if check_and_kill(j, dry_run=dry_run, limit_usd=limit,
                          label=f"bot book [{market}]"):
            out["triggered"].append(market)
        else:
            pnl = (sum(c["pnl"] for c in j["closed"])
                   + sum(p["unreal_pnl"] for p in j["open"]))
            log.info("kill-switch OK [%s] - book P&L $%.2f / limit -$%.2f "
                     "(%d open, marks from last scan)",
                     market, pnl, limit, len(j["open"]))
    return out


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S UTC",
    )
    p = argparse.ArgumentParser(description="Run the daily-loss kill-switch check")
    p.add_argument("--dry-run", action="store_true", help="Log only, don't flatten")
    args = p.parse_args()
    run_standalone(dry_run=args.dry_run)

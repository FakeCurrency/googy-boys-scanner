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


def check_and_kill(j: dict, dry_run: bool = False) -> bool:
    """Return True if the kill switch fired (caller must abort new orders).

    j  — the scalp journal dict (open + closed lists)
    """
    from scanner.config import SCALP_MAX_DAILY_LOSS
    from scanner.scalp_journal import _session_day

    today        = _session_day()
    today_closed = [c for c in j.get("closed", []) if c.get("session_day") == today]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    unrealised   = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
    total_session = today_pnl + unrealised

    if total_session >= -SCALP_MAX_DAILY_LOSS:
        return False

    log.warning("KILL SWITCH TRIGGERED — session P&L = $%.2f (limit -$%.2f)",
                total_session, SCALP_MAX_DAILY_LOSS)

    # Dispatch alert to all configured channels
    try:
        from .alert_dispatch import send as _alert
        _alert(
            "kill_switch",
            f"Kill switch triggered — session P&L ${total_session:.2f}",
            f"Daily loss limit: -${SCALP_MAX_DAILY_LOSS}. "
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


def run_standalone(dry_run: bool = False) -> None:
    """Load the journal and run the kill-switch check (for the hourly workflow)."""
    import json
    from scanner.scalp_journal import SCALP_JOURNAL_FILE

    j = {"open": [], "closed": []}
    if SCALP_JOURNAL_FILE.exists():
        try:
            j = json.loads(SCALP_JOURNAL_FILE.read_text())
        except Exception as e:
            log.error("could not read journal: %s", e)

    triggered = check_and_kill(j, dry_run=dry_run)
    if not triggered:
        from scanner.config import SCALP_MAX_DAILY_LOSS
        from scanner.scalp_journal import _session_day
        today = _session_day()
        pnl   = sum(c.get("pnl", 0) for c in j.get("closed", [])
                    if c.get("session_day") == today)
        unreal = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
        log.info("kill-switch OK — session P&L $%.2f / limit -$%.2f",
                 pnl + unreal, SCALP_MAX_DAILY_LOSS)


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

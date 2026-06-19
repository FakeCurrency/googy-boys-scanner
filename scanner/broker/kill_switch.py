"""Daily-loss kill-switch.

Checks the session P&L (realised + unrealised) against SCALP_MAX_DAILY_LOSS.
If the limit is breached, flattens all Alpaca positions and cancels all orders.

Runs:
  • At the start of paper_run (pre-trade gate)
  • As a standalone hourly workflow to catch moves between scans
    (python -m scanner.broker.kill_switch)
"""

import os
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


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

    print(f"  KILL SWITCH TRIGGERED — session P&L = ${total_session:.2f} "
          f"(limit -${SCALP_MAX_DAILY_LOSS})")

    if not os.environ.get("ALPACA_API_KEY"):
        print("  KILL SWITCH: ALPACA_API_KEY not set — skipping broker flatten")
        return True

    if dry_run:
        print("  KILL SWITCH: dry_run=True — not flattening")
        return True

    from scanner.broker import alpaca_client as ac

    try:
        resp = ac.close_all_positions()
        print(f"  KILL SWITCH: closed all positions → {resp}")
    except Exception as e:
        print(f"  KILL SWITCH: ERROR closing positions → {e}")

    try:
        resp = ac.cancel_all_orders()
        print(f"  KILL SWITCH: cancelled all orders → {resp}")
    except Exception as e:
        print(f"  KILL SWITCH: ERROR cancelling orders → {e}")

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
            print(f"  kill_switch: could not read journal — {e}")

    triggered = check_and_kill(j, dry_run=dry_run)
    if not triggered:
        from scanner.config import SCALP_MAX_DAILY_LOSS
        from scanner.scalp_journal import _session_day
        today = _session_day()
        today_pnl = sum(c.get("pnl", 0) for c in j.get("closed", [])
                        if c.get("session_day") == today)
        unreal = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
        print(f"  kill_switch: OK — session P&L ${today_pnl + unreal:.2f} "
              f"/ limit -${SCALP_MAX_DAILY_LOSS}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Run the daily-loss kill-switch check")
    p.add_argument("--dry-run", action="store_true", help="Log only, don't flatten")
    args = p.parse_args()
    run_standalone(dry_run=args.dry_run)

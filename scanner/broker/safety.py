"""Live-trading interlock — a fail-closed gate so real orders can NEVER fire on
a single mis-set env var.

`ALPACA_LIVE=true` is necessary but **not sufficient**. Live mode is permitted
only when EVERY condition below holds; otherwise `assert_live_allowed()` raises
and the broker layer refuses to talk to the live endpoint at all.

Go-live requirements (all must hold):
  1. LIVE_TRADING_CONFIRMED == CONFIRM_TOKEN          (explicit human acknowledgement)
  2. ≥ MIN_PAPER_TRADES closed paper trades on record
  3. ≥ MIN_PAPER_DAYS days spanned by that paper record
  4. Positive total paper P&L *and* positive total R across the record

This encodes the standing rule: ALPACA_LIVE must never be live until ≥1 month
of proven paper edge.
"""

import datetime as dt
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCALP_JOURNAL_FILE = ROOT / "journal" / "scalp_journal.json"

CONFIRM_TOKEN    = "I_UNDERSTAND_THE_RISK"
MIN_PAPER_TRADES = 30
MIN_PAPER_DAYS   = 30


def live_requested() -> bool:
    return os.environ.get("ALPACA_LIVE", "").lower() == "true"


def _closed_trades() -> list:
    if not SCALP_JOURNAL_FILE.exists():
        return []
    try:
        return json.loads(SCALP_JOURNAL_FILE.read_text()).get("closed", [])
    except Exception:
        return []


def edge_summary() -> dict:
    """Proof-of-edge stats drawn from the closed scalp paper trades."""
    closed = _closed_trades()
    total_pnl = sum(c.get("pnl", 0) or 0 for c in closed)
    total_r   = sum(c.get("r", 0) or 0 for c in closed)
    stamps = sorted(c.get("opened_ts", "") for c in closed if c.get("opened_ts"))
    days = 0
    if len(stamps) >= 2:
        try:
            a = dt.datetime.fromisoformat(stamps[0][:19])
            b = dt.datetime.fromisoformat(stamps[-1][:19])
            days = (b - a).days
        except ValueError:
            days = 0
    return {"n": len(closed), "total_pnl": round(total_pnl, 2),
            "total_r": round(total_r, 2), "days": days}


def live_blockers() -> list[str]:
    """Reasons live trading is NOT allowed. Empty list ⇒ permitted."""
    reasons = []
    if os.environ.get("LIVE_TRADING_CONFIRMED") != CONFIRM_TOKEN:
        reasons.append(f"LIVE_TRADING_CONFIRMED is not set to '{CONFIRM_TOKEN}'")
    s = edge_summary()
    if s["n"] < MIN_PAPER_TRADES:
        reasons.append(f"only {s['n']} closed paper trades (need ≥{MIN_PAPER_TRADES})")
    if s["days"] < MIN_PAPER_DAYS:
        reasons.append(f"only {s['days']} days of paper history (need ≥{MIN_PAPER_DAYS})")
    if s["total_pnl"] <= 0:
        reasons.append(f"paper P&L ${s['total_pnl']:.2f} is not positive")
    if s["total_r"] <= 0:
        reasons.append(f"paper total R {s['total_r']:.2f}R is not positive")
    return reasons


def assert_live_allowed() -> None:
    """Fail-closed: raise if live is requested but the edge gate isn't satisfied.

    Called from the lowest level (alpaca_client._base) so it guards *every* live
    API call, not just the order-submit path.
    """
    if not live_requested():
        return
    blockers = live_blockers()
    if blockers:
        raise RuntimeError(
            "ALPACA_LIVE=true but LIVE TRADING IS BLOCKED (fail-closed gate):\n  - "
            + "\n  - ".join(blockers)
            + "\nRefusing to place real orders. Unset ALPACA_LIVE to trade on paper."
        )

"""Shared journal helpers used by both the swing journal (journal.py) and the
scalp journal (scalp_journal.py), plus broker modules that persist JSON.

Extracted to remove the duplication that had `_atomic_write`, `_load`, the
direction-stats core, and the mark-to-market maths copy-pasted across files
(each a separate place a sign bug or a non-atomic write could creep in).
"""

import datetime as dt
import json
import os
import pathlib
import tempfile

import numpy as np


def utc_now_iso() -> str:
    """Current UTC time as a 'Z'-suffixed, second-precision ISO string.

    Uses a timezone-AWARE datetime (datetime.utcnow() is deprecated in 3.12 and
    returns a naive value). The 'Z' suffix is kept for the existing public-JSON
    consumers rather than the '+00:00' that isoformat() would emit.
    """
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(path: pathlib.Path, payload: str) -> None:
    """Write payload to path atomically via a temp file + rename (POSIX-safe).

    Guarantees the destination is never left half-written on a crash: the data
    lands in a sibling temp file first, then os.replace() swaps it in one step.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        f.write(payload)
        tmp = f.name
    os.replace(tmp, path)


def load_journal(path: pathlib.Path) -> dict:
    """Load a journal JSON file, returning an empty {open, closed} on any error."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"open": [], "closed": []}


def dir_stats_core(closed_list: list, open_list: list) -> dict:
    """Common per-direction stats shared by both journals.

    Each journal extends this with its own extras (the swing journal adds Kelly
    and unrealised-R; the scalp journal adds unrealised-PnL).
    """
    rs = np.array([c["r"] for c in closed_list], dtype=float) if closed_list else np.array([])
    pnls = np.array([c.get("pnl", 0) or 0 for c in closed_list], dtype=float) if closed_list else np.array([])
    wins = rs[rs > 0]
    return {
        "open":      len(open_list),
        "closed":    len(closed_list),
        "win_rate":  round(len(wins) / len(rs) * 100, 1) if len(rs) else 0.0,
        "total_r":   round(float(rs.sum()), 2) if len(rs) else 0.0,
        "total_pnl": round(float(pnls.sum()), 2) if len(pnls) else 0.0,
    }


def mark_to_market(entry: float, price: float, stop: float, direction: str,
                   qty: float, fees: float = 0.0) -> tuple[float, float]:
    """Unrealised (R, PnL) for an open position at `price`.

    Long and short are mirror images; `fees` lets the scalp journal bake in its
    round-trip brokerage while the swing journal passes 0. Returns (0.0, pnl)
    for a non-positive risk distance so a bad stop never divides by zero.
    """
    is_long = direction != "short"
    risk = (entry - stop) if is_long else (stop - entry)
    move = (price - entry) if is_long else (entry - price)
    unreal_r = round(move / risk, 2) if risk > 0 else 0.0
    unreal_pnl = round(qty * move - fees, 2)
    return unreal_r, unreal_pnl

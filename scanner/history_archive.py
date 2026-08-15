"""$0 forward-only adjusted daily archive (owner order 2026-08-15).

WHY: ASX Yahoo history is thin (practical ~5y window) and survivorship-biased —
delisted names vanish from the universe file and take their history with them.
This module persists, per scanned symbol, the adjusted daily bars the scan
ALREADY downloaded, so a survivorship-honest ASX record accumulates from today
forward at zero vendor cost. It is STORAGE ONLY: nothing in the scan, grading,
bot or w3-1 path reads these files (tests/test_history_archive.py pins that).

DESIGN DECISIONS (each deliberate):
- SCOPE: symbols in the day's RESULT ROWS only (the ~300-350 names that set up),
  NOT the full ~2,200-name download — the full set would grow the repo ~125MB
  and every CI clone pays for it. HISTORY_ARCHIVE_MAX_FILES caps the union.
- COMPLETED BARS ONLY: the frame's forming bar (today, market-local) is dropped,
  so each file gains at most one FINAL bar per session and quiet days produce
  byte-identical files (no commit churn from intraday marks).
- ADJUSTED BASIS, SPLICE-EXTENDED: yfinance auto_adjust re-bases the WHOLE
  series on every dividend/split, so yesterday's stored bars and today's frame
  can sit on different bases. On every write the file is REBUILT from today's
  frame (internally consistent), and stored bars OLDER than the frame window
  are kept by rescaling them with the overlap ratio at the join — the standard
  back-adjustment splice. A join ratio drifting past
  HISTORY_ARCHIVE_SPLICE_MAX_DRIFT marks the file "splice_suspect" rather than
  silently publishing a broken series.
- SURVIVORSHIP: a name that stops appearing keeps its file untouched (frozen
  last-known series, "last_seen" unchanged) — that frozen file IS the record a
  delisting would otherwise erase. Files are never deleted here.
- NO FANTASY FILLS: bars are copied from the frame as-is; no-trade days are
  absent because they were absent upstream. Nothing synthesises a date.
- FAIL-SOFT: update() is wrapped by its caller; an archive problem must never
  cost a scan. It is deliberately NOT in scan.yml's assert_staged must-change
  list (most scans of a day are legitimate no-ops).

Layout: data/history/<market>/<SYMBOL>.json
Schema: {"symbol","market","basis":"adj","updated":"YYYY-MM-DD",
         "last_seen":"YYYY-MM-DD","splice_suspect":bool,
         "bars":[["YYYY-MM-DD",open,high,low,close,volume], ...]}  # ascending
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
from zoneinfo import ZoneInfo

from . import config
from .journal_common import atomic_write

ROOT = pathlib.Path("data/history")

_MARKET_TZ = {"asx": "Australia/Sydney", "nasdaq": "America/New_York", "crypto": "UTC"}


def _today(market: str) -> _dt.date:
    return _dt.datetime.now(ZoneInfo(_MARKET_TZ.get(market, "UTC"))).date()


def _frame_bars(df, today: _dt.date) -> list[list]:
    """Frame → [[date, o, h, l, c, v], ...], completed bars only, no invention."""
    out = []
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        if d >= today:            # forming bar — final close not printed yet
            continue
        try:
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if any(x != x for x in (o, h, l, c)):   # NaN row — absent print stays absent
            continue
        v = row.get("Volume", 0)
        out.append([d.isoformat(), round(o, 8), round(h, 8), round(l, 8), round(c, 8),
                    int(v) if v == v else 0])
    return out


def _splice(old_bars: list[list], new_bars: list[list], max_drift: float) -> tuple[list[list], bool]:
    """Keep old bars older than the new window, rescaled onto the new basis."""
    if not old_bars or not new_bars:
        return new_bars, False
    first_new = new_bars[0][0]
    tail = [b for b in old_bars if b[0] < first_new]
    if not tail:
        return new_bars, False
    # Ratio at the join: the newest stored bar that also exists in the new frame.
    new_by_date = {b[0]: b for b in new_bars}
    anchor = next((b for b in reversed(old_bars) if b[0] in new_by_date), None)
    if anchor is None:            # no overlap (name returned after a long gap)
        return new_bars, True     # keep only the consistent new series; flag it
    r = new_by_date[anchor[0]][4] / anchor[4] if anchor[4] else 1.0
    suspect = not (1.0 - max_drift <= r <= 1.0 + max_drift) if r > 0 else True
    if r <= 0 or r != r:
        return new_bars, True
    scaled = [[b[0], round(b[1] * r, 8), round(b[2] * r, 8), round(b[3] * r, 8),
               round(b[4] * r, 8), b[5]] for b in tail]
    return scaled + new_bars, suspect


def update(market: str, rows: list[dict], frames: dict, root: pathlib.Path | None = None) -> dict:
    """Archive the day's result-row symbols from the already-downloaded frames."""
    if market not in getattr(config, "HISTORY_ARCHIVE_MARKETS", ("asx",)):
        return {}
    base = (root or ROOT) / market
    base.mkdir(parents=True, exist_ok=True)
    max_bars = getattr(config, "HISTORY_ARCHIVE_MAX_BARS", 2600)
    max_files = getattr(config, "HISTORY_ARCHIVE_MAX_FILES", 1500)
    drift = getattr(config, "HISTORY_ARCHIVE_SPLICE_MAX_DRIFT", 0.25)
    today = _today(market)
    existing = {p.stem for p in base.glob("*.json")}
    written = new_bars = 0
    suffix = config.MARKETS[market].suffix if market in getattr(config, "MARKETS", {}) else ""

    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        df = frames.get(sym + suffix)
        if df is None:                     # `or` would ask a DataFrame for truth
            df = frames.get(sym)
        if df is None or not len(df):
            continue
        if sym not in existing and len(existing) + (written and 0) >= max_files and len(existing) >= max_files:
            continue                       # cap new names; existing files still refresh
        bars = _frame_bars(df, today)
        if not bars:
            continue
        path = base / f"{sym}.json"
        old = None
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                old = None
        if old and old.get("bars"):
            if old.get("updated") == today.isoformat() and old["bars"] and old["bars"][-1][0] == bars[-1][0]:
                continue                   # same session already archived — no-op
            merged, suspect = _splice(old["bars"], bars, drift)
        else:
            merged, suspect = bars, False
        merged = merged[-max_bars:]
        prev = len(old["bars"]) if old and old.get("bars") else 0
        payload = {"symbol": sym, "market": market, "basis": "adj",
                   "updated": today.isoformat(), "last_seen": today.isoformat(),
                   "splice_suspect": bool(suspect), "bars": merged}
        atomic_write(path, json.dumps(payload, separators=(",", ":")), newline="\n")
        written += 1
        new_bars += max(0, len(merged) - prev)
        existing.add(sym)
    return {"written": written, "new_bars": new_bars, "total_files": len(existing)}

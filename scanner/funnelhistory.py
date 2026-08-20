"""Funnel history — the append-only trend behind the deck's one-scan funnel.

Owner-ruled (2026-07-30, Task 2): each scan appends its funnel counts —
scanned -> with-data -> published -> floor-killed -> arriving — to ONE small
committed artefact, ``public/data/funnel_history.json``, so the snapshot the
funnel disclosure shows ("299 killed by the floor today, 9 arriving") gains a
past ("is that tightening or loosening?"). The deck's existing funnel
disclosure lazy-loads this file and draws the trend; nothing else opens it.

REPORT-ONLY, and the fence is the point (same construction as the arriving
list): this module is imported by ``run.py`` alone — never by ``scan.py``,
never by anything in ``broker/`` — and NOTHING reads the file back into the
scanner, the bot, or any decision path. It records what the pipeline did; it
never influences what the pipeline does. ``tests/test_funnel_history.py``
pins both directions.

Shape (columnar per market, to keep the committed file small — the same
reasoning as ``sector_breadth.json``'s ``series`` block)::

    {"schema_version": 1, "updated_at": "...",
     "markets": {"asx": {"t": [...iso...], "scanned": [...],
                          "with_data": [...], "published": [...],
                          "floor_killed": [...], "arriving": [...]}}}

Append semantics: one row per PUBLISH, trimmed to the newest
``SCAN_FUNNEL_HISTORY_MAX`` rows per market. A corrupt or missing file starts
fresh with a WARNING rather than killing a scan — this is a report artefact,
and the scan that feeds the book must never die for it. Real rows are never
rewritten; there is nothing here for a re-run to make more true (contrast the
sector-history backfill, which reconstructs — this file only ever RECORDS).
"""
from __future__ import annotations

import os
import pathlib

from . import config, output

_COLS = ("scanned", "with_data", "published", "floor_killed", "arriving", "trigger")

# What started the scan (2026-08-20). Three values, matching how a run can
# actually begin: a scheduled cron, a human/manual workflow_dispatch (the SCAN
# button included), or the heartbeat healer's rescue dispatch. Anything else —
# including a local `python -m scanner.run` with no env set — records "" (an
# honest absence, never a guess).
_TRIGGERS = ("cron", "manual", "heartbeat")


def trigger_from_env() -> str:
    """The SCAN_TRIGGER env var, validated. scan.yml/crypto_bot.yml derive it
    from ``github.event_name`` (schedule -> cron, workflow_dispatch -> manual)
    and heartbeat.js marks its own dispatches via the ``reason`` input."""
    t = str(os.environ.get("SCAN_TRIGGER") or "").strip().lower()
    return t if t in _TRIGGERS else ""


def path_for(out_root: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(out_root) / getattr(
        config, "SCAN_FUNNEL_HISTORY_FILE", "funnel_history.json")


def row_from(vk: dict, trigger: str | None = None) -> dict:
    """The five owner-named counts, derived from the published payload, plus
    what TRIGGERED the run (cron / manual / heartbeat, "" when unknown).

    Reads the SAME numbers the deck's funnel summary shows — ``scanned`` from
    the payload top level, the rest from ``vk["funnel"]`` — so the history can
    never disagree with the snapshot it extends. ``published`` is the funnel's
    ``setups`` (rows that reached the page); ``floor_killed`` is
    ``illiquid_setup`` (had a setup, sat under the floor).
    """
    f = (vk or {}).get("funnel") or {}

    def n(x):
        return int(x) if isinstance(x, (int, float)) and x == x else 0

    t = str(trigger or "").strip().lower()
    return {
        "t": str((vk or {}).get("generated_at") or ""),
        "scanned": n((vk or {}).get("scanned")),
        "with_data": n(f.get("with_data")),
        "published": n(f.get("setups")),
        "floor_killed": n(f.get("illiquid_setup")),
        "arriving": n(f.get("arriving")),
        "trigger": t if t in _TRIGGERS else "",
    }


def _fresh() -> dict:
    return {"schema_version": 1, "updated_at": "", "markets": {}}


def load(out_root: str | pathlib.Path) -> dict:
    """The history as it stands, or a fresh shell — never an exception.

    Narrow on purpose (the repo bans broad handlers that swallow into a pass):
    a missing file is the ordinary first-run case, an unreadable one is named
    in a WARNING and replaced — losing a report trend beats losing a scan.
    """
    import json

    p = path_for(out_root)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fresh()
    except (OSError, ValueError) as e:
        print(f"  WARNING funnel history unreadable ({e.__class__.__name__}) - starting fresh")
        return _fresh()
    if not isinstance(d, dict) or not isinstance(d.get("markets"), dict):
        print("  WARNING funnel history malformed - starting fresh")
        return _fresh()
    return d


def append(market: str, vk: dict, out_root: str | pathlib.Path,
           trigger: str | None = None) -> pathlib.Path:
    """Append this publish's row for ``market`` and write atomically."""
    hist = load(out_root)
    row = row_from(vk, trigger)
    blk = hist["markets"].setdefault(market, {})
    cap = int(getattr(config, "SCAN_FUNNEL_HISTORY_MAX", 2000) or 0)
    cols = ("t",) + _COLS
    # SCHEMA MIGRATION, not corruption: a file written before the `trigger`
    # column existed (2026-08-20) has full-length numeric columns and NO
    # trigger array. Without this pad the truncate-to-shortest guard below
    # would read the new 1-long column as "the shortest" and WIPE the entire
    # history on the first post-upgrade scan. Pre-2026-08-20 rows get "" —
    # trigger unknown — which is also what a local run records.
    n_have = len(blk["t"]) if isinstance(blk.get("t"), list) else 0
    tcol = blk.get("trigger")
    if not isinstance(tcol, list):
        tcol = []
    if n_have and len(tcol) < n_have:
        tcol = [""] * (n_have - len(tcol)) + tcol
    blk["trigger"] = tcol
    for c in cols:
        seq = blk.get(c)
        if not isinstance(seq, list):
            seq = []
        seq.append(row[c])
        blk[c] = seq[-cap:] if cap else seq
    # A malformed block could carry unequal columns; truncate to the shortest
    # so the arrays always zip — dropping a broken tail beats publishing rows
    # whose timestamp belongs to a different scan's counts.
    shortest = min(len(blk[c]) for c in cols)
    for c in cols:
        blk[c] = blk[c][-shortest:]
    hist["updated_at"] = row["t"]
    p = path_for(out_root)
    output.write_json(p, hist, indent=None, separators=(",", ":"))
    print(f"  funnel history: +1 {market} row ({shortest} kept)")
    return p

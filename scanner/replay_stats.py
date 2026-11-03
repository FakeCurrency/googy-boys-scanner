"""Replay-only statistics for the decision replay (NEXT100 #15, #20).

SIMULATION ONLY. Nothing here is read by a trade path: ``vivek_parity``
imports it to (a) scale the replay's book caps to the sample's share of the
live universe so the replay book is as crowded as live, (b) print total R
and a live-mix R per trade beside every R/slot-month figure, and (c) fill
the blank sectors the NASDAQ directory carries (``universe.py`` sets
``sector: ""`` for every NASDAQ name) from the committed sources so the
6-per-sector cap binds in the replay as it does live. Every file read here
is read-only: ``data/sector_map.json``, ``data/universe_cache/<mk>.json``
and ``journal/vivek_bot_book.json``.
"""

from __future__ import annotations

import json
import logging
import pathlib
from collections import Counter

from . import config
from .broker.vivek_bot import _sector_key   # import only; the bot is ringfenced

log = logging.getLogger("vivek.replay_stats")

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── #15 slot scale ────────────────────────────────────────────────────────────

def _live_caps() -> tuple[int, int]:
    total = int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0) or config.VIVEK_BOT_MAX_POSITIONS)
    sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    return total, sector


def _half_up(x: float) -> int:
    return int(x + 0.5)


def slot_scale(coverage: dict, mode: str | None = None) -> dict:
    """The caps the replay's books run at. ``coverage`` is run_parity's
    per-market coverage (``symbols`` sampled of ``universe`` names;
    ``universe_before_exclude`` when an OOS exclusion shrank it). Mode
    "universe" scales the live caps by the pooled share, never below
    ``VIVEK_PARITY_SLOT_SCALE_MIN`` slots in total and 1 per sector; mode
    "none" returns the live caps."""
    mode = str(mode if mode is not None else getattr(config, "VIVEK_PARITY_SLOT_SCALE", "none")).lower()
    live_total, live_sector = _live_caps()
    floor = int(getattr(config, "VIVEK_PARITY_SLOT_SCALE_MIN", 3) or 0)
    by_market = {}
    sampled = universe = 0
    for mk, cov in (coverage or {}).items():
        n = int(cov.get("symbols") or 0)
        u = int(cov.get("universe_before_exclude") or cov.get("universe") or 0)
        by_market[mk] = {"symbols": n, "universe": u,
                         "share": round(n / u, 4) if u else None}
        sampled += n
        universe += u
    share = round(sampled / universe, 4) if universe else None
    out = {"mode": mode, "share": share, "by_market": by_market,
           "live": {"max_open_total": live_total, "max_per_sector": live_sector}}
    if mode == "universe" and share is not None and share < 1.0:
        out["max_open_total"] = max(floor, _half_up(live_total * share))
        out["max_per_sector"] = max(1, _half_up(live_sector * share)) if live_sector else 0
    else:
        if mode not in ("universe", "none"):
            out["note"] = f"unknown VIVEK_PARITY_SLOT_SCALE {mode!r}: live caps used"
        out["max_open_total"] = live_total
        out["max_per_sector"] = live_sector
    return out


# ── #15 total R and the live-mix R per trade ──────────────────────────────────

def total_r(trades: list[dict], r_key: str = "realized_r") -> float:
    return round(sum(float(t.get(r_key) or 0.0) for t in trades), 4)


def live_market_mix(root: pathlib.Path | str | None = None,
                    cycles: tuple[str, ...] | None = None) -> dict:
    """The live book's market mix at entry: the share of open + closed rows
    tagged with the live cycles, per market. Falls back to equal weights over
    the live markets, with a note, when the book cannot be read or holds no
    row of those cycles."""
    root = pathlib.Path(root) if root is not None else ROOT
    cycles = tuple(cycles if cycles is not None
                   else getattr(config, "VIVEK_PARITY_LIVE_CYCLES", ("hc4-1", "hc4-2")))
    path = root / "journal" / "vivek_bot_book.json"
    counts: Counter = Counter()
    note = None
    try:
        book = json.loads(path.read_text(encoding="utf-8"))
        rows = list(book.get("open") or []) + list(book.get("closed") or [])
        for r in rows:
            if r.get("cycle") in cycles and r.get("market"):
                counts[str(r["market"])] += 1
        if not counts:
            note = f"no {'/'.join(cycles)} rows in the book: equal weights"
    except Exception as e:                                   # unreadable, absent, malformed
        note = f"book unreadable ({type(e).__name__}): equal weights"
    n = sum(counts.values())
    if n:
        weights = {mk: round(c / n, 4) for mk, c in sorted(counts.items())}
        source = "book"
    else:
        mkts = sorted(config.MARKETS)
        weights = {mk: round(1.0 / len(mkts), 4) for mk in mkts}
        source = "equal"
    out = {"weights": weights, "n": n, "cycles": list(cycles), "source": source}
    if note:
        out["note"] = note
    return out


def live_mix_r(trades: list[dict], mix: dict, r_key: str = "realized_r") -> float | None:
    """Per-market average R, reweighted to the live mix. A market the live
    mix weights but the trade list never traded is dropped and the remaining
    weights renormalised; None when nothing overlaps."""
    weights = (mix or {}).get("weights") or {}
    by_mk: dict[str, list[float]] = {}
    for t in trades:
        mk = t.get("market")
        if mk in weights:
            by_mk.setdefault(mk, []).append(float(t.get(r_key) or 0.0))
    if not by_mk:
        return None
    w_sum = sum(weights[mk] for mk in by_mk)
    if not w_sum > 0:
        return None
    return round(sum(weights[mk] / w_sum * (sum(rs) / len(rs)) for mk, rs in by_mk.items()), 4)


# ── #20 sector fill ───────────────────────────────────────────────────────────

def _load_sector_map(root: pathlib.Path) -> dict:
    try:
        return json.loads((root / "data" / "sector_map.json").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_cache_items(root: pathlib.Path, mk: str) -> list[dict]:
    try:
        d = json.loads((root / "data" / "universe_cache" / f"{mk}.json").read_text(encoding="utf-8"))
        return list(d.get("items") or []) if isinstance(d, dict) else list(d or [])
    except Exception:
        return []


def _load_book_rows(root: pathlib.Path) -> list[dict]:
    try:
        b = json.loads((root / "journal" / "vivek_bot_book.json").read_text(encoding="utf-8"))
        return list(b.get("open") or []) + list(b.get("closed") or [])
    except Exception:
        return []


def fill_sectors(mk: str, uni: list[dict], *, sector_map: dict | None = None,
                 cache_items: list[dict] | None = None, book_rows: list[dict] | None = None,
                 root: pathlib.Path | str | None = None) -> dict:
    """Fill every blank ``sector`` in ``uni`` (in place) from, in order,
    data/sector_map.json ("<mk>:<SYM>" -> {"sector"}), the market's
    universe_cache items, then the live book's rows. The raw label is stored;
    run_book maps it to its GICS bucket through the bot's ``_sector_key``.
    Returns the coverage: names whose bucket is non-blank / total, and where
    each fill came from. Blank stays exempt from the cap, as live."""
    root = pathlib.Path(root) if root is not None else ROOT
    if sector_map is None:
        sector_map = _load_sector_map(root)
    if cache_items is None:
        cache_items = _load_cache_items(root, mk)
    if book_rows is None:
        book_rows = _load_book_rows(root)
    cache_by = {str(u.get("symbol") or "").upper(): str(u.get("sector") or "").strip()
                for u in cache_items}
    book_by: dict[str, str] = {}
    for r in book_rows:
        if r.get("market") == mk and r.get("symbol") and r.get("sector"):
            book_by.setdefault(str(r["symbol"]).upper(), str(r["sector"]).strip())
    filled: Counter = Counter()
    for u in uni:
        if str(u.get("sector") or "").strip():
            filled["universe"] += 1
            continue
        sym = str(u.get("symbol") or "").upper()
        ent = sector_map.get(f"{mk}:{sym}")
        label = str((ent or {}).get("sector") or "").strip() if isinstance(ent, dict) else ""
        src = "sector_map"
        if not label:
            label, src = cache_by.get(sym, ""), "universe_cache"
        if not label:
            label, src = book_by.get(sym, ""), "book"
        if label:
            u["sector"] = label
            filled[src] += 1
    named = sum(1 for u in uni if _sector_key(u.get("symbol"), u.get("sector"), mk))
    return {"named": named, "total": len(uni), "filled": dict(filled)}

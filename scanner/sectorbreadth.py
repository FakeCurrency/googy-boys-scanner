"""SECTOR BREADTH + HORIZON — the rotation surface (2026-07-28).

WHY THIS EXISTS. Between 30 June and 27 July 2026 the ASX Consumer
Discretionary complex ran hard and the book held none of it. The post-mortem
found three separate holes, and this module closes the reporting half of all
three:

  1. The only sector number the system published was ``sector_counts`` -- a RAW
     count of setups. Materials has 766 listed ASX names and out-counts every
     other sector on every scan forever, regardless of what it is doing. On raw
     counts Consumer Discretionary ranked 6th that day; divided by the number of
     names listed in the sector it ranked 3rd, at nearly 3x the Materials rate.
     The one number available to eyeball was actively misleading. -> ``rate``.

  2. Nothing anywhere kept a sector-shaped series. The longest memory in the
     system was the 7-day PhaseMap archive, which is far too short to show a
     three-week rotation: the July move was not merely undetected, it was
     UNRECOVERABLE after the fact. -> the append-only history below, which is
     why this ships even though it can only start accumulating from today.

  3. Nothing compared what was LEADING against what was HELD, and nothing
     related either to whether the book had the capacity to act. The book sat at
     its ceiling for 20 consecutive ASX sessions; every candidate, the whole
     sector included, was declined `book_full` before a single quality check
     ran. Detection was never the binding constraint. -> ``horizon``.

REPORT-ONLY BY CONSTRUCTION. Nothing here is imported by vivek_bot, and no
value it produces reaches a trade decision. It changes what the owner can SEE,
never what gets taken -- that distinction is deliberate and load-bearing: a
sector tilt or a sector floor changes which trades get taken and is the owner's
call, not an autonomous one. If you later wire a number from here into
`decide()`, that is a trade change and needs asking first.

Best-effort like every other publish step: any failure leaves the previous
files untouched and returns None rather than failing a scan.

    python -m scanner.sectorbreadth --market asx      # recompute from committed data
"""

import argparse
import datetime as dt
import json
import os
import pathlib

from . import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data" / "sector_history.json"
PUBLIC_FILE = ROOT / "public" / "data" / "sector_breadth.json"
BOOK_FILE = ROOT / "journal" / "vivek_bot_book.json"
SECTOR_CACHE_FILE = ROOT / "data" / "sector_map.json"

HISTORY_VERSION = 1

# Scan market -> the key `sectors.json` files that market's index tape under.
_TAPE_KEY = {"asx": "asx", "nasdaq": "us"}

# GICS sector (as the universe files spell it) -> the sector INDEX already
# fetched into public/data/sectors.json every scan. Joining these is free: the
# tape is downloaded and then thrown away today. Names are matched lower-cased
# and loosely (see `_index_for`) because the ASX directory, Yahoo profiles and
# the index list each spell the same sector differently.
_INDEX_ASX = {
    "materials": "XMJ", "energy": "XEJ", "financials": "XFJ",
    "health care": "XHJ", "consumer discretionary": "XDJ",
    "consumer staples": "XSJ", "information technology": "XIJ",
    "utilities": "XUJ", "industrials": "XNJ",
    "communication services": "XTJ", "real estate": "XPJ",
}
_INDEX_US = {
    "technology": "XLK", "information technology": "XLK",
    "financial services": "XLF", "financials": "XLF",
    "energy": "XLE", "healthcare": "XLV", "health care": "XLV",
    "industrials": "XLI", "consumer cyclical": "XLY",
    "consumer discretionary": "XLY", "consumer defensive": "XLP",
    "consumer staples": "XLP", "utilities": "XLU",
    "basic materials": "XLB", "materials": "XLB",
    "real estate": "XLRE", "communication services": "XLC",
}
_INDEX = {"asx": _INDEX_ASX, "nasdaq": _INDEX_US}

# NOT SECTORS. These are the absence of a sector wearing a sector's clothes, and
# they must never be RANKED — 389 of the 2,212 ASX names carry "Unclassified"
# (shells, listed trusts, recent listings, the long micro-cap tail), and on the
# first run of this module that bucket came out top of the leaderboard at 23.4%,
# pushing every real sector down a place. That is precisely the failure this
# module exists to correct, just wearing a different disguise: a bucket that is
# big and undifferentiated will always look like breadth. They are still
# COMPUTED and published, because "a quarter of today's A+ setups are in names
# with no sector" is worth seeing — it just is not a rotation.
_NOT_A_SECTOR = {"unclassified", "unknown", "n/a", "na", "none", "other",
                 "miscellaneous", "not applicable"}


def _norm(sector) -> str:
    return " ".join(str(sector or "").strip().split()).lower()


def _index_for(market: str, sector: str) -> str:
    """The sector index ticker for a GICS name, '' when there is no clean map.

    Deliberately conservative: an exact match, then a containment match for the
    handful of near-synonyms ('Cons. Disc.' style abbreviations do not appear in
    universe data, but Yahoo's 'Consumer Cyclical' does). Never guesses -- a
    wrong index would put a sector's relative strength on the wrong tape, which
    is worse than showing none.
    """
    table = _INDEX.get(market) or {}
    key = _norm(sector)
    if not key:
        return ""
    if key in table:
        return table[key]
    for name, idx in table.items():
        if key.startswith(name) or name.startswith(key):
            return idx
    return ""


# ── the denominator ───────────────────────────────────────────────────────────

def _cache_sectors(market: str) -> dict:
    """SYMBOL -> sector for every name this market's sector cache has classified.

    Best-effort: an absent, unreadable or wrong-shaped cache is an empty map,
    never an exception. Used two ways below -- as a denominator of last resort,
    and to fill a BLANK sector on a scan row (never to overwrite one).
    """
    try:
        cache = json.loads(pathlib.Path(SECTOR_CACHE_FILE).read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001 - best-effort
        return {}
    if not isinstance(cache, dict):
        return {}
    prefix = f"{market}:"
    out = {}
    for key, val in cache.items():
        if not str(key).startswith(prefix):
            continue
        sector = (val.get("sector") if isinstance(val, dict) else val) or ""
        if str(sector).strip():
            out[str(key)[len(prefix):].upper()] = str(sector)
    return out


def _denominator(market: str, universe, cached: dict) -> tuple[list, str]:
    """The names the rate divides by, and an honest label for where they came from.

    ASX ships GICS with its directory, so the universe IS the listing count and
    the rate means exactly what it says. NASDAQ's symbol file carries no sector
    column at all -- that is the whole reason `scanner/sectorcache.py` exists --
    so every US bucket came out with names=0, nothing ranked, and the panel was
    blank for half the book. Fall back to the sector CACHE: every US name a scan
    has ever classified (340 of ~1,425 today, and it only grows).

    That denominator is a SUBSET of the listing count, so a US rate is comparable
    ACROSS SECTORS on the same day -- which is what the ranking and the alarm
    need -- but is NOT comparable to an ASX rate, and will drift down as the
    cache fills. `names_source` is published for exactly that reason: the page
    says which one it is instead of implying a like-for-like number.
    """
    rows = [u for u in (universe or []) if str(u.get("sector") or "").strip()]
    if rows:
        return rows, "universe"
    if cached:
        return ([{"symbol": s, "sector": sec} for s, sec in cached.items()],
                "classified")
    return [], "none"


# ── the per-scan computation ──────────────────────────────────────────────────

def compute(market: str, results, universe, positions=None, tape=None) -> dict:
    """One scan's sector picture for one market.

    ``rate`` is the headline: A+/A setups divided by the number of names LISTED
    in that sector, so a 104-name sector and a 766-name sector are comparable.
    Sectors below `SECTOR_BREADTH_MIN_NAMES` are computed but never ranked -- a
    3-name sector with one setup reads as 33% and would top every list forever.
    """
    results = list(results or [])
    cached = _cache_sectors(market)
    universe, names_source = _denominator(market, universe, cached)
    positions = [p for p in (positions or []) if p.get("market") == market]
    tradeable = set(getattr(config, "TRADEABLE_GRADES", {"A+", "A"}))
    min_names = int(getattr(config, "SECTOR_BREADTH_MIN_NAMES", 15) or 0)

    rows: dict[str, dict] = {}

    def _bucket(sector):
        key = _norm(sector)
        if not key:
            return None
        if key not in rows:
            rows[key] = {"sector": " ".join(str(sector).strip().split()),
                         "names": 0, "setups": 0, "ag": 0, "armed": 0,
                         "longs": 0, "shorts": 0, "held": 0}
        return rows[key]

    def _sector_of(row):
        """A row's sector, filled from the cache ONLY when the row has none.

        NASDAQ scan rows ship sector-less (`output.write` runs before
        `vivek_run` enriches them), so without this the US numerator was zero in
        every bucket while the denominator was fine -- every sector "leading" at
        0.0%. Blank-only, exactly like `sectorcache.enrich_rows`: a sector that
        came with the data always wins.
        """
        sec = str(row.get("sector") or "").strip()
        return sec or cached.get(str(row.get("symbol") or "").upper(), "")

    for u in universe:
        b = _bucket(u.get("sector"))
        if b is not None:
            b["names"] += 1
    for r in results:
        b = _bucket(_sector_of(r))
        if b is None:
            continue
        b["setups"] += 1
        if str(r.get("grade") or "") in tradeable:
            b["ag"] += 1
            if r.get("armed"):
                b["armed"] += 1
            if str(r.get("dir") or "").upper() == "SHORT":
                b["shorts"] += 1
            else:
                b["longs"] += 1
    for p in positions:
        b = _bucket(_sector_of(p))
        if b is not None:
            b["held"] += 1

    # Sector index tape, joined in from the fetch that already happens.
    # `sectors.json` stores each market's indices as a LIST of
    # {symbol, name, last, chg, chg_pct}; a dict keyed by symbol is accepted too
    # so a future shape change here degrades to "no tape", never to a crash.
    tape_rows = (tape or {}).get("sectors") or []
    if isinstance(tape_rows, dict):
        tape_rows = [{"symbol": k, **(v if isinstance(v, dict) else {})}
                     for k, v in tape_rows.items()]
    chg = {}
    for row in tape_rows:
        try:
            chg[str(row.get("symbol") or "").upper()] = round(float(row["chg_pct"]), 3)
        except (TypeError, ValueError, KeyError, AttributeError):
            continue

    out = []
    for key, b in rows.items():
        names = b["names"]
        b["rate"] = round(b["ag"] / names, 4) if names else None
        b["setup_rate"] = round(b["setups"] / names, 4) if names else None
        b["real"] = key not in _NOT_A_SECTOR
        b["ranked"] = bool(b["real"] and names >= min_names and b["rate"] is not None)
        idx = _index_for(market, b["sector"])
        b["index"] = idx
        b["index_chg"] = chg.get(idx)
        out.append(b)

    # Rank by participation RATE, best first. Unranked sectors (too few listed
    # names, or none at all) sort last and carry rank None so no consumer can
    # accidentally treat them as leaders.
    ranked = sorted([b for b in out if b["ranked"]],
                    key=lambda b: (-(b["rate"] or 0), -b["ag"], b["sector"]))
    for i, b in enumerate(ranked, 1):
        b["rank"] = i
    for b in out:
        b.setdefault("rank", None)
    out.sort(key=lambda b: (b["rank"] is None, b["rank"] or 0, b["sector"]))
    return {"market": market, "sectors": out,
            "names_source": names_source,
            # Published so the page can say WHY a row carries no rank instead of
            # showing a blank. NASDAQ Real Estate came out at 85.7% -- 6 of the 7
            # names classified so far -- sitting rankless at the bottom of the
            # board under the highest bar on it. On a surface whose whole job is
            # "do not be fooled by a sector number", that is the exact failure
            # mode it exists to prevent.
            "min_names": min_names,
            "universe_size": sum(b["names"] for b in out),
            "setups": sum(b["setups"] for b in out),
            "ag": sum(b["ag"] for b in out),
            "held": sum(b["held"] for b in out)}


def book_state(positions=None) -> dict:
    """Capacity, globally. The single most important number on the page.

    Cause number one of the July miss was not blindness, it was a full book:
    the position ceiling is what decides whether a detected rotation can be
    acted on at all, so breadth without capacity beside it is half a picture.
    """
    positions = list(positions or [])
    max_open = int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0) or 0)
    max_notional = float(getattr(config, "VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL", 0) or 0)
    notional = 0.0
    for p in positions:
        try:
            notional += float(p.get("notional") or 0)
        except (TypeError, ValueError):
            pass
    # Published so the page can say what free SLOTS are worth in dollars. The
    # two ceilings currently disagree by an order of magnitude -- 24 of 30 slots
    # used reads 80% full, $6.1k of $150k deployed reads 4% invested -- because
    # the legacy holdings average ~$250 each, sized off the old $10,000 equity.
    # Free slots x this number is the only figure that answers "how much can I
    # actually put to work", which is the question the July miss turned on.
    return {"open": len(positions), "max_open": max_open,
            "free": max(0, max_open - len(positions)) if max_open else None,
            "at_cap": bool(max_open and len(positions) >= max_open),
            "notional": round(notional, 2), "max_notional": max_notional,
            "position_notional": float(
                getattr(config, "VIVEK_BOT_POSITION_NOTIONAL", 0) or 0)}


# ── the persisted series ──────────────────────────────────────────────────────

def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("rows"), list):
                return data
        except Exception:
            pass
    return {"version": HISTORY_VERSION, "rows": []}


def _write_json(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_history(hist: dict, snap: dict, book: dict, day: str) -> dict:
    """One compact row per market per DAY, last write wins.

    Per-day rather than per-scan on purpose: several scans run each session and
    a rotation is a multi-week object, so intraday resolution buys nothing and
    would bloat a file that has to stay cheap enough to keep forever. Replacing
    the day's row rather than appending means the last scan of the session is
    the one that survives, which is the one with the fullest picture.
    """
    row = {"d": day, "m": snap["market"], "open": book["open"],
           "max": book["max_open"], "cap": 1 if book["at_cap"] else 0,
           "s": {b["sector"]: [b["ag"], b["names"], b["held"],
                               b.get("index_chg")]
                 for b in snap["sectors"] if b["names"]}}
    rows = [r for r in hist.get("rows", [])
            if not (r.get("d") == day and r.get("m") == snap["market"])]
    rows.append(row)
    rows.sort(key=lambda r: (str(r.get("d")), str(r.get("m"))))
    keep = int(getattr(config, "SECTOR_BREADTH_HISTORY_MAX", 2000) or 0)
    if keep and len(rows) > keep:
        rows = rows[-keep:]
    hist["version"] = HISTORY_VERSION
    hist["rows"] = rows
    return hist


def trend(hist: dict, market: str, sector: str, window: int = 5) -> dict:
    """Mean rate over the last `window` DAYS, and the change against the window
    before it. This is the number that would have shown Consumer Discretionary
    lifting through July rather than merely being third today."""
    seq = [r for r in hist.get("rows", []) if r.get("m") == market]
    vals = []
    for r in seq:
        cell = (r.get("s") or {}).get(sector)
        if not cell or not cell[1]:
            continue
        vals.append(cell[0] / cell[1])
    if not vals:
        return {"days": 0, "mean": None, "prev": None, "chg": None}
    recent = vals[-window:]
    prior = vals[-2 * window:-window]
    mean = sum(recent) / len(recent)
    prev = (sum(prior) / len(prior)) if prior else None
    return {"days": len(vals), "mean": round(mean, 4),
            "prev": None if prev is None else round(prev, 4),
            "chg": None if prev is None else round(mean - prev, 4)}


# ── the alarm ─────────────────────────────────────────────────────────────────

def horizon(snap: dict, book: dict, hist: dict, cap_streak: int = 0) -> dict:
    """"Look further" -- the one line that would have fired every day in July.

    Two independent questions, answered together because either alone is
    misleading. WHERE is participation strongest (by rate, not raw count), and
    CAN the book act on it. A leading sector held at zero is only interesting if
    there was room to take it; a full book is only interesting if something was
    worth taking. In July both were true for nineteen straight sessions and
    nothing said so.
    """
    top_n = int(getattr(config, "SECTOR_BREADTH_TOP_N", 3) or 3)
    # rate > 0, not merely ranked: on a quiet day the whole board can sit at
    # zero, and the first live NASDAQ run duly announced three sectors "leading
    # on breadth with ZERO held" at 0.0% each. Nothing is running there. An
    # alarm that fires on an empty market is an alarm that gets ignored.
    leaders = [b for b in snap["sectors"] if b.get("rank") and (b.get("rate") or 0) > 0][:top_n]
    unheld = [b for b in leaders if not b["held"]]
    max_sector = int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0)
    notes = []
    if book["at_cap"]:
        notes.append(
            f"Book is FULL at {book['open']}/{book['max_open']}"
            + (f" and has been for {cap_streak} straight sessions" if cap_streak > 1 else "")
            + " - nothing new can be taken until something closes, however "
              "good the setup.")
    elif book.get("free") is not None and book["free"] <= max(1, book["max_open"] // 10):
        notes.append(f"Only {book['free']} of {book['max_open']} slots free - "
                     f"the book is nearly out of room.")
    if unheld:
        notes.append(
            "Leading on breadth with ZERO held: "
            + ", ".join(f"{b['sector']} ({b['ag']}/{b['names']} = "
                        f"{100 * (b['rate'] or 0):.1f}%)" for b in unheld) + ".")
    for b in leaders:
        if max_sector and b["held"] >= max_sector:
            notes.append(f"{b['sector']} is leading and already at the "
                         f"{max_sector}-per-sector cap - the cap, not the "
                         f"market, is what is limiting it.")
    # `expand` is the actionable state: something is running that the book is
    # not in, AND the book cannot or can barely act. That pair is the condition
    # the owner asked to be told about.
    expand = bool(unheld and (book["at_cap"] or (book.get("free") or 0) <= 3))
    return {"leaders": [b["sector"] for b in leaders],
            "unheld_leaders": [b["sector"] for b in unheld],
            "at_cap": book["at_cap"], "cap_streak": cap_streak,
            "expand": expand, "notes": notes}


def cap_streak(hist: dict, market: str) -> int:
    """Consecutive most-recent days this market's scans saw a FULL book."""
    n = 0
    for r in reversed([r for r in hist.get("rows", []) if r.get("m") == market]):
        if not r.get("cap"):
            break
        n += 1
    return n


# ── the publish step ──────────────────────────────────────────────────────────

def _load_positions() -> list:
    try:
        return list(json.loads(BOOK_FILE.read_text(encoding="utf-8")).get("open", []))
    except Exception:
        return []


def update(markets: dict, out_dir=None, positions=None, day: str | None = None) -> dict | None:
    """Recompute every market, append today's history row, publish the page file.

    `markets` is ``{market: {"results": [...], "universe": [...]}}`` -- whatever
    this run actually scanned. A market missing from it keeps its previous
    published block rather than being blanked, so a crypto-only weekend run does
    not erase the ASX picture.
    """
    if not getattr(config, "SECTOR_BREADTH_ENABLED", True):
        return None
    out_dir = pathlib.Path(out_dir) if out_dir else PUBLIC_FILE.parent
    positions = _load_positions() if positions is None else list(positions)
    day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    try:
        tape = json.loads((out_dir / "sectors.json").read_text(encoding="utf-8"))
    except Exception:
        tape = {}

    try:
        prev = json.loads((out_dir / "sector_breadth.json").read_text(encoding="utf-8"))
        blocks = dict(prev.get("markets") or {})
    except Exception:
        blocks = {}

    hist = load_history()
    book = book_state(positions)
    for market, data in (markets or {}).items():
        if market not in _INDEX:                 # crypto has no sectors
            continue
        snap = compute(market, data.get("results"), data.get("universe"),
                       positions,
                       ((tape.get("markets") or {}).get(_TAPE_KEY.get(market, market))))
        hist = append_history(hist, snap, book, day)
        streak = cap_streak(hist, market)
        for b in snap["sectors"]:
            b["trend"] = trend(hist, market, b["sector"])
        blocks[market] = {**snap, "book": book,
                          "horizon": horizon(snap, book, hist, streak),
                          "generated_at": dt.datetime.now(dt.timezone.utc)
                          .isoformat(timespec="seconds")}

    payload = {"schema_version": 1, "day": day,
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "book": book, "markets": blocks,
               "series": series(hist)}
    _write_json(HISTORY_FILE, hist)
    _write_json(out_dir / "sector_breadth.json", payload)
    return payload


def series(hist: dict, days: int = 0) -> dict:
    """The history reshaped for plotting: ``{market: {"days": [...],
    "book": [...], "sectors": {name: [rate|None, ...]}}}``.

    Rates are emitted aligned to the day axis with None for days a sector had no
    listed names, so the front end can draw straight from it without carrying
    any of the reconstruction logic that made the original post-mortem
    impossible.
    """
    days = days or int(getattr(config, "SECTOR_BREADTH_PUBLISH_DAYS", 180) or 180)
    out: dict = {}
    for market in sorted({r.get("m") for r in hist.get("rows", []) if r.get("m")}):
        rows = [r for r in hist["rows"] if r.get("m") == market][-days:]
        axis = [r.get("d") for r in rows]
        names = sorted({s for r in rows for s in (r.get("s") or {})})
        sect: dict = {}
        for name in names:
            vals = []
            for r in rows:
                cell = (r.get("s") or {}).get(name)
                vals.append(round(cell[0] / cell[1], 4)
                            if cell and cell[1] else None)
            sect[name] = vals
        out[market] = {"days": axis, "sectors": sect,
                       "open": [r.get("open") for r in rows],
                       "at_cap": [bool(r.get("cap")) for r in rows]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Recompute sector breadth from committed scan data")
    ap.add_argument("--market", action="append", help="asx | nasdaq (repeatable)")
    ap.add_argument("--out", default=str(ROOT / "public" / "data"))
    args = ap.parse_args()
    from .universe import load_universe
    wanted = args.market or ["asx", "nasdaq"]
    markets = {}
    for m in wanted:
        try:
            scan = json.loads((pathlib.Path(args.out) / f"{m}_vivek.json")
                              .read_text(encoding="utf-8"))
        except Exception as exc:                        # noqa: BLE001
            print(f"  breadth: no scan file for {m} ({exc}) - skipped")
            continue
        try:
            uni = load_universe(m, full=True)
        except Exception as exc:                        # noqa: BLE001
            print(f"  breadth: no universe for {m} ({exc}) - skipped")
            continue
        markets[m] = {"results": scan.get("results") or [], "universe": uni}
    payload = update(markets, out_dir=args.out)
    if not payload:
        print("  breadth: disabled")
        return
    for market, blk in (payload.get("markets") or {}).items():
        lead = ", ".join(blk["horizon"]["leaders"]) or "-"
        print(f"  breadth [{market}]: leaders {lead} | "
              f"book {blk['book']['open']}/{blk['book']['max_open']}"
              f"{' AT CAP' if blk['book']['at_cap'] else ''}")
        for note in blk["horizon"]["notes"]:
            print(f"    ! {note}")


if __name__ == "__main__":
    main()

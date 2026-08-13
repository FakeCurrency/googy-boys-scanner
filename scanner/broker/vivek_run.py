"""VIVEK execution/runner layer — Phase 1–2 (dry-run + paper book).

This is the thin orchestration layer that sits between the pure decision engine
(`vivek_bot.decide`) and a broker. In Phase 1–2 there is NO broker: it keeps a
persistent PAPER book per market and resolves it with the same intraday
mark-to-market the journal uses. Live execution is deliberately NOT wired here —
the runner refuses to place a real order regardless of config (see the hard
gates below), so this can run on every scan with zero risk.

What it does each run, per market:

  1. Loads the persistent book (journal/vivek_bot_book.json) — Gap 1. The book
     survives across runs, so the position caps, short-slot reserve and one-per-
     symbol rules hold over time, not just within a single scan. The book-size
     ceiling is GLOBAL (config.VIVEK_BOT_MAX_OPEN_TOTAL, 30 open across every
     market), so this step also counts the sibling markets' canonical book
     files via `_open_elsewhere` — and refuses new entries outright if any of
     them is unreadable, rather than guessing low and blowing the cap.
  2. Marks every OPEN position to the observed intraday price (reusing the
     journal's `_mark` / `manage_position`), booking scale-outs and closing on
     stops — but only during the delay-adjusted market session.
  3. Asks `vivek_bot.decide(..., open_book=...)` what NEW A+ entries to add,
     filling the remaining capacity. New fills enter at the current intraday
     price with the journal's don't-chase guard.
  4. Writes the book back — UNLESS dry-run is on, in which case it logs the
     decisions and leaves the book untouched (final safety gate).

Every position the runner records carries the entry-type label, timeframe and
grade end-to-end (Gap 3), so the audit trail never loses why a trade was taken.

SAFETY — three independent gates, all must be cleared for a live order, and the
third is not implemented in this phase so a live order is impossible here:

    VIVEK_BOT_ENABLED       master switch (False → runner is a no-op)
    VIVEK_BOT_DRY_RUN       True → decide + log only, never mutate the book
    VIVEK_BOT_MODE[market]  "live" is logged and TREATED AS PAPER in this phase
    VIVEK_LIVE_CONFIRMED    extra hard lock checked by the (future) broker layer
"""

import datetime as dt
import json
import os
import logging
import pathlib
from zoneinfo import ZoneInfo

from .. import config
from . import vivek_bot, vivek_guard
from ..vivek_journal import (_apply_costs, _current_price, _mark, _r_of,
                             _snapshot, costs_for, market_open)
from ..journal_common import atomic_write

log = logging.getLogger("vivek_run")

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOOK_DIR = ROOT / "journal"
# BOOK LAYOUT v2 (2026-07-20, Phase 3 — structural fix for the C1 race class):
#   CANONICAL: journal/vivek_bot_book.<market>.json — one file per market.
#     run_market(m) can only ever touch market m's file, so one market's run
#     clobbering another's closes is impossible BY CONSTRUCTION (not merely
#     by workflow scheduling, which remains as belt-and-braces).
#   DERIVED:   journal/vivek_bot_book.json (+ the public/data twin) — the
#     combined view, regenerated from the canonical files on every save.
#     Same name + schema as the old single book, so the frontend, backup
#     tooling, kill switch and older tests keep working unchanged. If it is
#     ever stale/corrupt it is REGENERABLE: python -m scanner.broker.vivek_run
#     --rebuild-combined. The canonical files are the track record.
#   MIGRATION: first load of a market whose canonical file doesn't exist
#     splits that market's slice out of the legacy combined file (read-only —
#     the legacy file itself is never mutated by migration; git history holds
#     the pre-split state). Entries with an unrecognised market go to
#     vivek_bot_book.unassigned.json so nothing can be silently dropped.
BOOK_FILE = BOOK_DIR / "vivek_bot_book.json"           # combined, DERIVED
PUBLIC_FILE = ROOT / "public" / "data" / "vivek_bot_book.json"
UNASSIGNED_FILE = BOOK_DIR / "vivek_bot_book.unassigned.json"

BOOK_VERSION = 2                   # v2 = per-market canonical files
TIMEFRAMES = ("1D", "1W")          # server-side intraday timeframes (4H is browser-only)
MAX_CLOSED = 4000                  # per MARKET file now (was: whole book)
# How many daily reference marks to keep per position (vivek_guard windows).
# The widest window the guard measures is the trailing SEVEN CALENDAR days, so
# 9 stored sessions covers it on crypto (7 sessions a week) with slack, and
# covers it nearly twice over on ASX/NASDAQ (5 a week ~= 13 calendar days).
_DAY_MARK_KEEP = 9


def _market_book_file(market: str) -> pathlib.Path:
    return BOOK_DIR / f"vivek_bot_book.{market}.json"


# ── persistence (separate from the signal journal — Decision §9.2) ────────────

class BookCorruptError(SystemExit):
    """The bot book EXISTS but cannot be read/parsed.

    Deliberately a SystemExit subclass (2026-07-20, review C2): the paper book
    is the system's ONLY track record, so an unreadable book must ABORT the
    process with a non-zero exit instead of silently restarting from an empty
    book — the old behaviour parked the file on the ephemeral CI runner and
    then committed a blank book over the real history. SystemExit is NOT
    caught by the best-effort `except Exception` wrappers in scanner/run.py,
    so the workflow fails loudly and nothing overwrites the file. Recovery is
    manual: inspect/fix the file (or restore from git / backups/) and re-run.
    """


def _alert_book_corrupt(err: Exception) -> None:
    """Best-effort CRITICAL alert — must never mask the abort itself."""
    try:
        from .alert_dispatch import send as _alert
        _alert("scan_error",
               "VIVEK bot book CORRUPT — run aborted, book NOT modified",
               f"{BOOK_FILE} failed to parse: {err}\n"
               f"The runner exited before writing anything. Restore or fix the "
               f"book (git history or backups/), then re-run the scan.")
    except Exception as e:                       # alerting must not hide the abort
        log.warning("could not send corrupt-book alert: %s", e)


def _read_json_or_abort(path: pathlib.Path, what: str) -> dict:
    """Parse a book file or ABORT the process (C2 rule: an unreadable track
    record must never be silently replaced; the file is left untouched)."""
    try:
        b = json.loads(path.read_text(encoding="utf-8"))
        b.setdefault("open", [])
        b.setdefault("closed", [])
        return b
    except Exception as e:
        log.error("vivek %s CORRUPT (%s) - aborting run, file left untouched at %s",
                  what, e, path)
        _alert_book_corrupt(e)
        raise BookCorruptError(
            f"vivek_run: corrupt {what} at {path} ({e}) - run aborted, "
            f"file left untouched; restore from git/backups before re-running"
        ) from e


def _split_from_legacy(market: str) -> dict | None:
    """One-time migration: derive `market`'s slice from the legacy combined
    file. Read-only on the legacy file. Returns None when there is nothing to
    migrate (fresh install). On the first split, entries whose market isn't in
    config.MARKETS are preserved to UNASSIGNED_FILE — never dropped."""
    if not BOOK_FILE.exists():
        return None
    legacy = _read_json_or_abort(BOOK_FILE, "legacy combined book (migration)")
    known = set(config.MARKETS)
    if not UNASSIGNED_FILE.exists():
        stray = ([p for p in legacy["open"] if p.get("market") not in known]
                 + [p for p in legacy["closed"] if p.get("market") not in known])
        if stray:
            atomic_write(UNASSIGNED_FILE, json.dumps(
                {"version": BOOK_VERSION, "note": "entries with unknown market, "
                 "preserved by the v2 per-market split", "entries": stray}, indent=2))
            log.warning("book migration: %d entries with unknown market preserved "
                        "to %s", len(stray), UNASSIGNED_FILE.name)
    mbook = {
        "version": BOOK_VERSION, "mode": legacy.get("mode", "paper"),
        "market": market,
        "open": [p for p in legacy["open"] if p.get("market") == market],
        "closed": [p for p in legacy["closed"] if p.get("market") == market],
        "guard": {market: (legacy.get("guard") or {}).get(market)}
                 if (legacy.get("guard") or {}).get(market) else {},
    }
    log.info("book migration: split %s slice from legacy combined "
             "(%d open, %d closed)", market, len(mbook["open"]), len(mbook["closed"]))
    return mbook


def _load_market_book(market: str) -> dict:
    """CANONICAL per-market book. Missing file -> migrate from legacy combined,
    else a legitimate fresh start. Corrupt file -> abort (C2)."""
    p = _market_book_file(market)
    if not p.exists():
        migrated = _split_from_legacy(market)
        if migrated is not None:
            return migrated
        return {"version": BOOK_VERSION, "mode": "paper", "market": market,
                "open": [], "closed": []}
    return _read_json_or_abort(p, f"bot book [{market}]")


def _book_elsewhere(market: str) -> dict | None:
    """What every market EXCEPT `market` is holding right now — both the
    position COUNT and the open NOTIONAL — read straight from the canonical
    per-market book files.

    This is the runner's half of the two global ceilings
    (config.VIVEK_BOT_MAX_OPEN_TOTAL and VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL):
    vivek_bot.decide() only ever sees one market's scan, so it cannot know what
    the others hold. Reading the sibling files is safe and race-free by
    construction -- scan.yml and crypto_bot.yml share `concurrency: group: scan`
    with cancel-in-progress false, so no two market runs are ever live at once.
    A run still WRITES only its own file, so the layout-v2 guarantee
    (cross-market clobber impossible) is untouched.

    Returns None when a sibling book cannot be parsed. The caller must then take
    NO new entries: a risk cap that silently ignores the markets it cannot see
    is worse than one that pauses. That state is never quiet -- the owning
    market's own run aborts on a corrupt book and fires a CRITICAL alert.
    """
    total, notional = 0, 0.0

    def _add(rows) -> None:
        nonlocal total, notional
        for p in rows:
            total += 1
            notional += float(p.get("notional") or 0)

    for m in config.MARKETS:
        if m == market:
            continue
        p = _market_book_file(m)
        if not p.exists():
            continue                    # fresh clone / never scanned -> 0 open
        try:
            mb = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:          # noqa: BLE001 - logged; caller fails closed
            log.error("vivek_run [%s]: cannot read %s for the global position "
                      "cap (%s) - taking no new entries until it is readable",
                      market, p.name, e)
            return None
        # Count every open row in the file rather than filtering on the market
        # tag: the file IS that market's book, and an untagged row must not go
        # uncounted against a risk cap. Matches how _combined_view merges them.
        _add(mb.get("open") or [])
    # Positions whose market is not in config.MARKETS live in UNASSIGNED_FILE.
    # They show on the journal page as open risk, and they belong to no market's
    # own open_book, so without this they would be invisible to the ceiling.
    # They are "elsewhere" from every market's point of view -> always counted.
    if UNASSIGNED_FILE.exists():
        try:
            stray = json.loads(UNASSIGNED_FILE.read_text(encoding="utf-8"))
        except Exception as e:          # noqa: BLE001 - same fail-closed rule
            log.error("vivek_run [%s]: cannot read %s for the global position "
                      "cap (%s) - taking no new entries until it is readable",
                      market, UNASSIGNED_FILE.name, e)
            return None
        _add([p for p in stray.get("entries", []) if p.get("status") == "open"])
    return {"count": total, "notional": round(notional, 2)}


def _open_elsewhere(market: str) -> int | None:
    """Position count half of `_book_elsewhere` (None = a sibling is unreadable)."""
    seen = _book_elsewhere(market)
    return None if seen is None else seen["count"]


def _combined_view(override: dict | None = None) -> dict:
    """The combined book, merged from the canonical per-market files (plus any
    preserved unassigned entries). `override` = {market: mbook} lets a dry-run
    show its in-memory slice without touching disk."""
    override = override or {}
    out = {"version": BOOK_VERSION, "mode": "paper", "open": [], "closed": [],
           "guard": {}}
    for market in config.MARKETS:
        if market in override:
            mb = override[market]
        else:
            p = _market_book_file(market)
            if p.exists():
                mb = _read_json_or_abort(p, f"bot book [{market}]")
            else:
                mb = _split_from_legacy(market) or {"open": [], "closed": []}
        out["open"].extend(mb.get("open") or [])
        out["closed"].extend(mb.get("closed") or [])
        out["guard"].update(mb.get("guard") or {})
        if mb.get("mode") and mb["mode"] != "paper":
            out["mode"] = mb["mode"]
    if UNASSIGNED_FILE.exists():
        try:
            stray = json.loads(UNASSIGNED_FILE.read_text(encoding="utf-8"))
            out["open"].extend([p for p in stray.get("entries", [])
                                if p.get("status") == "open"])
            out["closed"].extend([p for p in stray.get("entries", [])
                                  if p.get("status") != "open"])
        except Exception as e:                     # display-only; never fatal
            log.warning("could not fold unassigned entries into combined view: %s", e)
    out["summary"] = {
        "open": len(out["open"]),
        "unreal_usd": round(sum(p.get("unreal_usd", 0.0) or 0.0 for p in out["open"]), 2),
        "updated_day": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
    }
    out["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return out


def _write_combined() -> None:
    """Regenerate the DERIVED combined view (journal + public twin) from the
    canonical files. Written after the canonical save, so a crash in between
    leaves combined at most one run stale - and always regenerable."""
    payload = json.dumps(_combined_view(), indent=2)
    atomic_write(BOOK_FILE, payload)
    atomic_write(PUBLIC_FILE, payload)


def verify_books() -> list[str]:
    """Integrity audit of book layout v2. Returns problem strings ([] = healthy).

    READ-ONLY. Run by the scan/close workflows AFTER their write steps (Phase 4
    monitoring): a bad book state fails the run loudly — failure email + no
    commit — instead of a broken track record quietly reaching main. Checks:
      1. every canonical market file parses and is shaped {open:[], closed:[]}
      2. no entry sits in the WRONG market's file (cross-contamination)
      3. no duplicate open symbols inside a market (one-per-symbol rule)
      4. the derived combined file + its public twin match what the canonical
         files derive to right now (volatile timestamps ignored) — staleness
         is recoverable with --rebuild-combined, and the next scan self-heals
    """
    problems: list[str] = []
    market_files = [m for m in config.MARKETS if _market_book_file(m).exists()]
    parse_ok = True
    for market in market_files:
        p = _market_book_file(market)
        try:
            mb = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"{p.name}: UNPARSEABLE ({e})")
            parse_ok = False
            continue
        for section in ("open", "closed"):
            rows = mb.get(section)
            if not isinstance(rows, list):
                problems.append(f"{p.name}: '{section}' is not a list")
                parse_ok = False
                continue
            strays = [t.get("symbol") for t in rows if t.get("market") != market]
            if strays:
                problems.append(f"{p.name}: {len(strays)} {section} entr"
                                f"{'y' if len(strays) == 1 else 'ies'} belong to a "
                                f"DIFFERENT market: {strays[:5]}")
        counts: dict = {}
        for t in (mb.get("open") or []) if isinstance(mb.get("open"), list) else []:
            counts[t.get("symbol")] = counts.get(t.get("symbol"), 0) + 1
        dupes = sorted(s for s, n in counts.items() if n > 1)
        if dupes:
            problems.append(f"{p.name}: duplicate open symbols {dupes} "
                            f"(one-per-symbol rule)")
    if not market_files:
        return problems          # pre-migration / fresh install: nothing to cross-check
    if not parse_ok:
        return problems          # combined comparison would abort on a corrupt file

    def _stable(d: dict) -> dict:
        d = json.loads(json.dumps(d))                     # deep copy
        d.pop("updated_at", None)
        (d.get("summary") or {}).pop("updated_day", None)
        return d

    derived = _stable(_combined_view())
    for path, label in ((BOOK_FILE, "combined book"),
                        (PUBLIC_FILE, "public combined book")):
        if not path.exists():
            problems.append(f"{label}: MISSING ({path.name}) - run "
                            f"python -m scanner.broker.vivek_run --rebuild-combined")
            continue
        try:
            disk = _stable(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            problems.append(f"{label}: unparseable ({e}) - run --rebuild-combined")
            continue
        if disk != derived:
            problems.append(f"{label}: STALE - does not match the canonical "
                            f"market files (run --rebuild-combined)")
    return problems


def _save_market_book(market: str, mbook: dict) -> None:
    """Persist ONE market's canonical file, then refresh the combined view."""
    mbook["version"] = BOOK_VERSION
    mbook["market"] = market
    mbook["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if len(mbook["closed"]) > MAX_CLOSED:
        mbook["closed"] = mbook["closed"][-MAX_CLOSED:]
    atomic_write(_market_book_file(market), json.dumps(mbook, indent=2))
    _write_combined()


def _summary_of(book: dict, day: str) -> dict:
    """Book-level snapshot for the UI/header: open count + live unrealised P&L.

    ONE WRITER (2026-07-28, TOP100 #21). `run_market` built this dict inline and
    every other path that mutated the book left the previous run's copy in place,
    so the two could not be kept in step by inspection.
    """
    open_ = book.get("open") or []
    return {
        "open": len(open_),
        "unreal_usd": round(sum(p.get("unreal_usd", 0.0) or 0.0 for p in open_), 2),
        "updated_day": day,
    }


def _book_mark(pos: dict) -> float | None:
    """The last price this position was accepted at, or None if it has none."""
    try:
        px = float(pos.get("last_mark") or 0.0)
    except (TypeError, ValueError):
        return None
    return px if px > 0 else None


def _restamp(book: dict, market: str, day: str) -> None:
    """Bring `summary` and `guard` back in step with the book about to be saved.

    WHY THIS EXISTS (2026-07-28, TOP100 #21). `close_bot_position` moved a row
    from `open` to `closed`, realised its R, and persisted — while `summary` still
    counted the closed position as open and reported the P&L of a book that no
    longer existed, and `guard` still described a session whose realised total had
    just changed. The window was meant to be brief (the next scan recomputes both
    from scratch) but nothing guarantees a next scan: close the last position of
    the day on a Friday and the book carries a summary contradicting its own rows
    all weekend, which is what the dashboard, the health check and any human
    reading the file actually see.

    NOT a trade change, and the distinction matters. `run_market` recomputes the
    guard itself before `decide()` is ever called, so no entry decision has ever
    been made against the stale copy and none is made differently now. What
    changes is only what the SAVED book says about itself.

    Priced off each position's own `last_mark`, the same fallback `kill_switch`
    uses between scans: there is no quote feed on the manual-close path, and
    handing the guard a `price_of` that returns None for everything would mark the
    whole book unpriced and manufacture an `unmeasured` fail-closed breach out of
    a routine close. `notified` is carried forward verbatim so the recompute
    cannot make the next scan re-announce a breach it has already announced.
    """
    book["summary"] = _summary_of(book, day)

    prev = ((book.get("guard") or {}).get(market) or {})
    try:
        equity = float(getattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 0) or 0)
        marks  = {str(p.get("symbol") or "").upper(): _book_mark(p)
                  for p in book.get("open") or []}
        guard  = vivek_guard.check(book, market, day, equity,
                                   lambda s: marks.get(str(s or "").upper()))
    except Exception as e:                                 # noqa: BLE001
        # A stale guard is worse than a fresh one, but a book that failed to save
        # is worse than both. Never let the restamp be the reason a close is lost.
        log.warning("could not restamp the %s guard after a close: %s", market, e)
        return
    guard["notified"] = prev.get("notified") or ""
    book.setdefault("guard", {})[market] = guard


def _stamp_day_ref(pos: dict, day: str, price: float | None) -> None:
    """Record the mark this position CARRIED INTO `day` (vivek_guard reference).

    WHY (2026-07-28, TOP100 #13). A daily loss guard has to measure a day. To
    do that it needs to know what each open position was worth when the day
    began — otherwise the only reference it has is the ENTRY price, and it
    charges a position's whole life to every session until it closes. So the
    runner leaves a breadcrumb: `day_marks[day]` = the price the position was
    last marked at BEFORE this day's first run touched it.

    THE ORDERING IS LOAD-BEARING — this must be called BEFORE `_mark_sanity`,
    which overwrites `last_mark` with today's observation. The reference has to
    be the PREVIOUS run's mark, so that an overnight gap is charged to the
    session it gapped INTO. Stamp it after the mark and the gap lands in no
    session at all: it would sit between the two references and escape the
    daily guard entirely, which is precisely the move the guard exists to catch.

    Written once per day and never overwritten (crypto runs 48 scans a day), on
    priced AND unpriced runs alike — a position nobody could price still
    carried a value into the session, and `vivek_guard` fails closed against
    exactly those. Falls back to the observed price only when there is no prior
    mark at all (a book row that has never been through a stamping run).
    """
    if not day:
        return
    try:
        ref = float(pos.get("last_mark") or 0.0)
    except (TypeError, ValueError):
        ref = 0.0
    if ref != ref or ref <= 0:                       # missing, NaN or nonsense
        ref = float(price) if price is not None else 0.0
    if ref <= 0:
        return
    marks = pos.get("day_marks")
    if not isinstance(marks, dict):
        marks = {}
    marks.setdefault(str(day), round(ref, 8))
    if len(marks) > _DAY_MARK_KEEP:
        for stale in sorted(marks)[:-_DAY_MARK_KEEP]:
            marks.pop(stale, None)
    pos["day_marks"] = marks


def _mark_sanity(pos: dict, price: float, market: str,
                 session_open: bool = True) -> float | None:
    """Gate an observed price before it may manage `pos`. Returns the price to
    use, or None to SKIP managing this run (freeze, like an unpriced run).

    WHY (2026-07-21, Phase 6 P1): the data layer runs auto_adjust=True, so a
    stock SPLIT rewrites the whole price basis overnight while the position's
    stored entry/stop stay in the OLD basis — the next observed price reads as
    an impossible collapse/spike against a stale stop and would book a fake
    catastrophic exit into the ONLY track record. Same for a vendor bad print.

    Discipline (all constants in config, per-market):
      * move vs the LAST ACCEPTED mark <= VIVEK_MARK_SANITY_PCT -> accept.
      * beyond it -> reject; count suspect_price_runs on the position (visible
        in the book, like unpriced_runs); ALERT on the 2nd consecutive hit.
      * on the VIVEK_MARK_SANITY_ACCEPT_RUNS-th consecutive hit -> ACCEPT the
        price and resume managing: a REAL crash is delayed a couple of runs,
        never ignored (and the live-quote kill switch watches it meanwhile).
    Seeding: the first guarded observation of a position (no last_mark yet)
    is accepted unconditionally — legacy runners far from entry must not
    false-positive on rollout.

    `session_open=False` FREEZES BUT DOES NOT SPEND (2026-07-28, TOP100 #18).
    The accept-run budget is a promise that a real crash is delayed "a couple of
    runs, never ignored" — and a run is only worth spending if it could have
    acted. Managing is gated on `is_open` at the call site, so a closed-market
    run never fills a stop no matter what this returns. Left counting, the three
    runs of grace were consumed by scans that could not have used them: scan.yml
    walks all three markets in every window, so while ASX is in session NASDAQ
    gets scanned CLOSED. A split on a NASDAQ name overnight was therefore
    auto-accepted after three ASX-window scans, `last_mark` was rebased to the
    post-split price, and the guard passed the very first in-session tick — into
    a stop still stored in the pre-split basis, which books a fake catastrophic
    exit into the one and only track record. That is precisely the sequence this
    function exists to prevent, arriving through its own escape hatch.

    A closed-market suspect price still freezes (so `unreal_r`/`unreal_usd` are
    not stamped from a bad print, and the loss guard reads no lie) and still
    alerts ONCE on the transition into suspect, because a split showing up
    before the open is worth knowing about before the open. It just does not
    advance the counter, so the position enters its next session with the full
    budget it was promised.
    """
    limit = (getattr(config, "VIVEK_MARK_SANITY_PCT", {}) or {}).get(market, 0.0)
    ref = pos.get("last_mark") or 0.0
    if limit <= 0 or ref <= 0:
        pos["last_mark"] = round(price, 8)               # seed; guard from next run
        return price
    move = abs(price / ref - 1.0)
    if move <= limit:
        pos["last_mark"] = round(price, 8)
        pos.pop("suspect_price_runs", None)
        pos.pop("suspect_price", None)
        pos.pop("suspect_closed", None)
        return price

    if not session_open:
        # Freeze without spending the budget. `suspect_closed` is the dedupe for
        # the announcement, not a counter — there is nothing to count, because
        # every one of these runs is worth the same zero.
        first = not pos.get("suspect_closed")
        pos["suspect_price"]  = round(price, 8)
        pos["suspect_closed"] = True
        log.warning("vivek_run: SUSPECT price for %s [%s] while the market is "
                    "CLOSED: %.6g is %+.0f%% vs last mark %.6g (limit %.0f%%) - "
                    "frozen, accept-run budget NOT spent",
                    pos.get("symbol"), market, price, move * 100, ref, limit * 100)
        if first:
            try:
                from .alert_dispatch import send as _alert
                _alert("anomaly",
                       f"SUSPECT price on {pos.get('symbol')} [{market}] - "
                       f"appeared while the market was closed",
                       f"Observed {price:.6g} vs last mark {ref:.6g} "
                       f"({move * 100:+.0f}%; limit {limit * 100:.0f}%). Likely a "
                       f"split/bad print. Marking is frozen and the position will "
                       f"start its next session with the full "
                       f"{int(getattr(config, 'VIVEK_MARK_SANITY_ACCEPT_RUNS', 3) or 3)}"
                       f"-run challenge budget - check the stop basis before then.")
            except Exception as e:
                log.warning("could not send suspect-price alert: %s", e)
        return None

    pos.pop("suspect_closed", None)
    n = int(pos.get("suspect_price_runs") or 0) + 1
    pos["suspect_price_runs"] = n
    pos["suspect_price"] = round(price, 8)
    accept_n = int(getattr(config, "VIVEK_MARK_SANITY_ACCEPT_RUNS", 3) or 3)
    if n >= accept_n:
        log.warning("vivek_run: %s [%s] price %.6g is %+.0f%% vs last mark %.6g "
                    "for the %dth consecutive run - ACCEPTING as real",
                    pos.get("symbol"), market, price, move * 100, ref, n)
        pos["last_mark"] = round(price, 8)
        pos.pop("suspect_price_runs", None)
        pos.pop("suspect_price", None)
        return price
    log.warning("vivek_run: SUSPECT price for %s [%s]: %.6g is %+.0f%% vs last "
                "mark %.6g (limit %.0f%%) - managing SUSPENDED (%d/%d)",
                pos.get("symbol"), market, price, move * 100, ref,
                limit * 100, n, accept_n)
    if n == 2:                       # second consecutive hit -> tell the owner
        try:
            from .alert_dispatch import send as _alert
            _alert("anomaly",
                   f"SUSPECT price on {pos.get('symbol')} [{market}] - "
                   f"managing suspended",
                   f"Observed {price:.6g} vs last mark {ref:.6g} "
                   f"({move * 100:+.0f}%; limit {limit * 100:.0f}%). Likely a "
                   f"split/bad print. Auto-accepts on run {accept_n} if it "
                   f"persists; stop/TP handling is paused until then.")
        except Exception as e:
            log.warning("could not send suspect-price alert: %s", e)
    return None


def _apply_level_gate(results: list[dict]) -> tuple[list[dict], int]:
    """Return (rows decide() may consider, dropped count) under the W3 gate.

    VIVEK_BOT_LEVEL_TF_ALLOW empty/unset -> gate OFF: the input list is
    returned unchanged (same object, zero dropped) so prior behaviour is
    byte-identical. Gate ON -> only rows whose level_tf normalises into the
    allowlist survive; missing/blank level_tf is dropped (FAIL-CLOSED - see
    the call site and config comment for the evidence trail). Pure function
    over the rows list: it never reads or writes the book.
    """
    allow = tuple(str(a).strip().lower()
                  for a in (getattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ()) or ()))
    if not allow:
        return results, 0
    kept = [r for r in (results or [])
            if str(r.get("level_tf") or "").strip().lower() in allow]
    return kept, len(results or []) - len(kept)


def _ticket_to_position(out: dict, entry_price: float, market: str, day: str,
                        level_tf: str | None = None) -> dict | None:
    """Build a paper book position from a decide() plan, filling at the current
    intraday price with the journal's don't-chase guard. Carries entry_type +
    label + timeframe + grade + sector end-to-end. Returns None to not-chase.

    ``level_tf`` is AUDIT-ONLY (which 200-SMA produced the signal: weekly/3d/h4).
    It never gates entry, sizing, or management — stamped so the n≥30 ruling can
    split expectancy by level without re-deriving history. vivek_bot.py is not
    touched; the runner copies it off the scan row at fill time.
    """
    plan = out["plan"]
    tf = plan["timeframe"]
    # Reuse the journal's snapshot so the fill model (don't-chase, risk, MAE/MFE,
    # ids) is identical to the forward-test journal — single source of truth.
    row = {
        "symbol": plan["symbol"],
        "name": plan.get("name", plan["symbol"]),
        "sector": plan.get("sector", ""),   # persists so the sector cap holds across runs
        "dir": "SHORT" if plan["direction"] == "short" else "LONG",
        "grade": plan["grade"],
        "entry_types": [plan["entry_type"]],
    }
    jplan = {
        "stop": plan["stop"], "tp1": plan["tp1"], "tp2": plan["tp2"], "tp3": plan["tp3"],
        "scale": plan["scale"], "entry_trigger": plan["entry_type"],
        "armed": True, "trigger_bar": plan.get("trigger_bar"),
    }
    snap = _snapshot(row, tf, jplan, market, entry_price, day)
    if snap is None:
        return None
    # Bolt the bot-specific sizing + the auditable entry-type label onto the
    # position so the book records exactly what the bot decided.
    snap["entry_type_label"] = plan["entry_type_label"]
    snap["units"] = plan["units"]
    snap["notional"] = plan["notional"]
    snap["leverage"] = plan["leverage"]
    snap["leverage_target"] = plan["leverage_target"]
    snap["risk_pct"] = plan["risk_pct"]
    snap["risk_usd"] = plan["risk_usd"]
    # WHICH SIZER PRODUCED THIS ROW (2026-07-28). size_position returns it and
    # decide() splats it onto the ticket, but nothing was copying it down here,
    # so the book recorded the NUMBERS of a sizing decision without recording
    # which mode made them. The book is now a permanent mixture -- positions
    # opened before 03:34 UTC today were sized risk-% off a $10,000 equity
    # (~$400 notional, $35 risk), everything after is fixed $5,000 -- and
    # without this label the only way to tell a legacy row from a new one is to
    # infer it from the notional, which stops working the moment either number
    # is retuned. Audit field: nothing reads it to make a decision.
    snap["sizing_mode"] = plan.get("sizing_mode", "")
    # CYCLE MARKER (2026-08-02, w3 gate enablement). Audit-only tag so pre-gate
    # and in-cycle cohorts never blur in later reads - the sizing_mode
    # precedent one line up: nothing reads it to make a decision, and a row
    # written while no cycle is active simply has no key (absent != empty,
    # same convention as the review flags below).
    _cycle = str(getattr(config, "VIVEK_BOT_CYCLE_TAG", "") or "")
    if _cycle:
        snap["cycle"] = _cycle
    # REVIEW FLAGS ride down onto the book row (2026-07-28, owner: "Flag this in
    # the future so i can verify whether claude or I should take the position or
    # not"). The flag is computed on the TICKET, which lives for the length of
    # one decide() call and is then gone -- if it does not land here it exists
    # only in a log line inside a finished Actions run, which is not a place a
    # decision gets made. On the row it reaches the journal page, the Discord
    # ping below, and any later post-mortem asking "was this one marked when it
    # was taken?". Stored as the plan's list verbatim, empty list when clean, so
    # "no flags" and "written before flags existed" stay distinguishable at
    # every reader. Report-only, exactly as on the ticket: nothing downstream
    # branches on it -- vivek_run does not size, skip or close differently for a
    # flagged row, and the daily/weekly guards never read it.
    snap["review"] = list(plan.get("review") or [])
    snap["source"] = "vivek_bot"
    snap["lens"] = "vivek"     # lens attribution — journal lens tracker reads it
    # AUDIT-ONLY level_tf (n≥30 pack). Prefer the scan-row value the runner
    # passed in; fall back to anything already on the ticket. Never default to
    # a guessed timeframe — missing stays missing so backfill can fill it.
    ltf = level_tf if level_tf is not None else plan.get("level_tf")
    if ltf:
        snap["level_tf"] = ltf
    # Signal-vs-fill: record the plan's entry level next to the actual fill so
    # the scan-cadence slippage is MEASURED, not assumed. Positive bps = the
    # fill was worse than the signal (paid up on a long / sold down on a short).
    sig = float(plan.get("entry") or 0)
    if sig > 0:
        slip_bps = (float(snap["entry"]) - sig) / sig * 1e4
        if plan["direction"] == "short":
            slip_bps = -slip_bps
        snap["signal_entry"] = round(sig, 8)
        snap["fill_slip_bps"] = round(slip_bps, 1)
    # Mark-sanity reference (Phase 6 P1): a NEW position is guarded from its
    # very first re-mark — the fill price is the first accepted mark. (Legacy
    # positions without last_mark get seeded on their first guarded run.)
    snap["last_mark"] = round(float(snap["entry"]), 8)
    return snap


def _notify_reviews(market: str, opened: list[dict], send=None) -> list[str]:
    """Ping Discord for positions opened carrying a review flag.

    Owner, 2026-07-28: "Flag this in the future so i can verify whether claude
    or I should take the position or not." This is the delivery half of that.
    The flag itself is computed in `vivek_bot.review_flags` and is REPORT-ONLY;
    so is this. By the time it runs the position is open and saved -- nothing
    here can un-take it, and nothing here tries.

    What it is actually for: the owner's choice is not take-or-skip (the bot has
    already taken it, correctly, under rules that are his) but WHOSE position it
    is. Leave it and it is the bot's, sized $5,000 like everything else. Close
    it in the book and it is his, sized however he wants. That choice has a
    shelf life of hours, so it has to arrive as a push and not as a row on a
    page he might open on Thursday.

    Called AFTER `_save_market_book`, deliberately: a dry run returns before
    that line and must stay silent, and pinging about a position that then
    failed to persist would be worse than not pinging at all.

    The COMBINED share is the number worth the message on its own. One flagged
    open at 27% of the daily guard is a judgement call; three in one run at 27%
    each is 81% of the day gone on three names, and nobody is summing that by
    hand from three separate notifications -- which is the argument for one
    message per run rather than one per position, quite apart from the noise.

    Rate limiting is ours, not the router's (`ALERT_RATE_LIMITS["trade_review"]`
    is 0). Opens are inherently one-shot, so there is no storm to suppress; a
    limit could only ever drop the second market's flagged open in a sequential
    run, and losing one of these is the whole failure mode.

    Returns the symbols it pinged about (empty if none, or if the push is off).
    """
    flagged = [p for p in (opened or []) if p.get("review")]
    if not flagged:
        return []
    if not getattr(config, "VIVEK_BOT_REVIEW_PUSH", True):
        return []
    if send is None:
        try:
            from .alert_router import smart_send as send
        except Exception:                                  # noqa: BLE001
            return []

    limit = 0.0
    try:
        from . import vivek_bot as _vb
        limit = _vb.daily_loss_limit()
    except Exception:                                      # noqa: BLE001
        pass

    lines, total = [], 0.0
    for p in flagged:
        risk = float(p.get("risk_usd") or 0)
        total += risk
        note = ""
        for f in p.get("review") or []:
            if f.get("note"):
                note = str(f["note"])
                break
        lines.append(f"{str(p.get('symbol','?')).upper()} "
                     f"{str(p.get('direction','?')).upper()} @ {p.get('entry')} "
                     f"(stop {p.get('stop')}) - {note}")
    if limit > 0 and len(flagged) > 1:
        lines.append(f"Together they put ${total:,.0f} at risk, "
                     f"{total / limit * 100:.0f}% of the ${limit:,.0f} daily guard, "
                     f"in one run.")
    lines.append("The bot has taken these under your rules and they stay taken. "
                 "Leave them and they are the bot's at $"
                 f"{float(getattr(config, 'VIVEK_BOT_POSITION_NOTIONAL', 0) or 0):,.0f} "
                 "each; close them in the book and take them yourself if you want "
                 "them sized your way.")
    site = str(getattr(config, "SITE_URL", "") or "").rstrip("/")
    if site:
        lines.append(f"{site}/journal.html")

    n = len(flagged)
    try:
        send("trade_review",
             f"YOUR CALL - {market.upper()}: {n} heavy position"
             f"{'s' if n != 1 else ''} opened",
             "\n".join(lines))
    except Exception as e:                                 # noqa: BLE001
        log.warning("could not send trade-review alert: %s", e)
        return []
    syms = [str(p.get("symbol", "")).upper() for p in flagged]
    log.info("trade-review alert [%s]: %s", market, ", ".join(syms))
    return syms


def _stale_probe(market: str, book: dict, day: str, send=None) -> list[str]:
    """Ping the owner about positions that have sat still long enough to need
    a human decision. REPORT-ONLY: it closes nothing and takes nothing.

    Owner ask, 2026-07-29 (answering "what rotation rule do you want" with):
    "no rotation rule. maybe a PROBE that position has been open for 2 weeks
    with minimal movement for me then to manually make a decision."

    Who this catches that the automatic rules never will: MAX_HOLD_DAYS (28)
    time-stops a pre-TP1 stall but says nothing at the half-way mark, and a
    runner past TP1 is exempt from it FOREVER — a +0.1R runner can squat one
    of 30 scarce slots for months with nothing ever asking about it. "Minimal
    movement" is |unreal_r| < STALE_PROBE_MAX_ABS_R: a row further red than
    that is the stop's business, further green is a working position.

    Dedupe is per POSITION, stamped into the row (`stale_pinged`, a date) so
    it commits with the book and survives the container — the same lesson as
    every other alert memory in this repo. Re-pings every REPEAT_DAYS while
    the row still qualifies; a row that starts moving loses its stamp, so a
    later re-stall is a fresh episode. Rows without `unreal_r` (unpriced this
    run) are SKIPPED, not flagged — no price means no movement claim, and the
    unpriced-runs warning above already owns that failure.

    Called after `_save_market_book`; re-saves iff a stamp changed. A save
    that then fails re-pings next run — for a reminder, failing toward
    repetition beats failing toward silence.
    """
    days_min = int(getattr(config, "VIVEK_BOT_STALE_PROBE_DAYS", 0) or 0)
    if days_min <= 0 or not getattr(config, "VIVEK_BOT_STALE_PROBE_PUSH", True):
        return []
    max_r = float(getattr(config, "VIVEK_BOT_STALE_PROBE_MAX_ABS_R", 0.5) or 0.5)
    repeat = int(getattr(config, "VIVEK_BOT_STALE_PROBE_REPEAT_DAYS", 7) or 0)

    def _days_between(a: str, b: str) -> int | None:
        try:
            return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
        except Exception:
            return None

    stale, changed = [], False
    for pos in book.get("open") or []:
        if pos.get("status") != "open" or pos.get("market", market) != market:
            continue
        held = _held_days(pos, day)
        ur = pos.get("unreal_r")
        qualifies = (held is not None and held >= days_min
                     and isinstance(ur, (int, float)) and abs(ur) < max_r)
        if not qualifies:
            if pos.pop("stale_pinged", None) is not None:
                changed = True                     # moving again — fresh episode later
            continue
        stamp = pos.get("stale_pinged")
        since = _days_between(str(stamp), day) if stamp else None
        if stamp and (since is None or since < repeat):
            continue                               # already pinged this episode
        pos["stale_pinged"] = day
        changed = True
        stale.append((pos, held, float(ur)))

    if changed:
        _save_market_book(market, book)
    if not stale:
        return []
    if send is None:
        try:
            from .alert_router import smart_send as send
        except Exception:                                  # noqa: BLE001
            return []

    lines = []
    for pos, held, ur in stale:
        leg = "past TP1, runner" if pos.get("tp1_hit") else \
            f"pre-TP1 (time stop at {int(getattr(config, 'VIVEK_BOT_MAX_HOLD_DAYS', 0) or 0)}d)"
        lines.append(f"{str(pos.get('symbol', '?')).upper()} "
                     f"{str(pos.get('direction', '?')).upper()} - {held}d held, "
                     f"{ur:+.2f}R, {leg}")
    lines.append("Going nowhere is a decision too - these hold "
                 f"{len(stale)} of the book's slots. Close in the book to free "
                 "the slot, or leave them and this asks again in "
                 f"{repeat} day(s).")
    site = str(getattr(config, "SITE_URL", "") or "").rstrip("/")
    if site:
        lines.append(f"{site}/journal.html")
    n = len(stale)
    try:
        send("stale_position",
             f"YOUR CALL - {market.upper()}: {n} position"
             f"{'s' if n != 1 else ''} sitting still",
             "\n".join(lines))
    except Exception as e:                                 # noqa: BLE001
        log.warning("could not send stale-position probe: %s", e)
        return []
    syms = [str(p.get("symbol", "")).upper() for p, _h, _u in stale]
    log.info("stale-position probe [%s]: %s", market, ", ".join(syms))
    return syms


def _close_time_stop(pos: dict, price: float, day: str,
                     costs: tuple[float, float] | None) -> None:
    """Close a stalled position at the observed price (exit_reason 'time') —
    same accounting as the journal's stop-close path."""
    is_long = pos.get("direction") == "long"
    remaining = round(1.0 - (pos.get("booked_pct") or 0.0), 6)
    pos.setdefault("gross_r", pos.get("realized_r", 0.0))
    if remaining > 1e-9:
        pos.setdefault("exits", []).append(
            {"reason": "time", "price": round(price, 8), "pct": remaining, "date": day})
        pos["gross_r"] = round(
            pos["gross_r"] + remaining * _r_of(price, pos["entry"], pos["risk"], is_long), 4)
        pos["booked_pct"] = 1.0
    pos["status"] = "closed"
    pos["exit_price"] = round(price, 8)
    pos["exit_date"] = day
    pos["exit_reason"] = "time"
    _apply_costs(pos, costs)
    try:
        pos["hold_days"] = (dt.date.fromisoformat(day)
                            - dt.date.fromisoformat(pos["entry_date"])).days
    except Exception:
        pos["hold_days"] = None


def _held_days(pos: dict, day: str) -> int | None:
    try:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(pos["entry_date"])).days
    except Exception:
        return None


def close_bot_position(symbol: str, market: str, price: float,
                       direction: str | None = None, day: str | None = None,
                       reason: str = "manual") -> dict | None:
    """Close ONE open bot-book position at `price` and persist the book.

    The REAL manual close for the one-and-only track record (2026-07-20,
    review C4 — the old "Close position" workflow edited the RETIRED journals
    and never touched the book, so a stuck position could squat a slot
    forever). Same accounting as every other close path: the remaining
    un-booked fraction exits at `price` (a market fill, so slippage applies
    via the cost model), costs are applied, exit_* fields stamped. Returns
    the closed position, or None if no matching OPEN position exists — the
    book is then left untouched and unsaved.
    """
    price = float(price)
    if price <= 0:
        raise ValueError(f"close price must be positive, got {price!r}")
    book = _load_market_book(market)     # corrupt book -> BookCorruptError (C2)
    sym = str(symbol or "").upper()
    if day is None:
        tz = config.MARKETS[market].timezone if market in config.MARKETS else "UTC"
        day = dt.datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")

    match = None
    for p in book["open"]:
        if (str(p.get("symbol") or "").upper() == sym
                and p.get("market") == market
                and (direction is None or p.get("direction") == direction)):
            match = p
            break
    if match is None:
        log.warning("close_bot_position: no open %s position for %s [%s] - book untouched",
                    direction or "any-direction", sym, market)
        return None

    is_long = match.get("direction") == "long"
    remaining = round(1.0 - (match.get("booked_pct") or 0.0), 6)
    match.setdefault("gross_r", match.get("realized_r", 0.0))
    if remaining > 1e-9:
        match.setdefault("exits", []).append(
            {"reason": "manual", "price": round(price, 8), "pct": remaining, "date": day})
        match["gross_r"] = round(
            match["gross_r"] + remaining * _r_of(price, match["entry"], match["risk"], is_long), 4)
        match["booked_pct"] = 1.0
    match["status"] = "closed"
    match["exit_price"] = round(price, 8)
    match["exit_date"] = day
    match["exit_reason"] = reason
    _apply_costs(match, costs_for(market))
    try:
        match["hold_days"] = (dt.date.fromisoformat(day)
                              - dt.date.fromisoformat(match["entry_date"])).days
    except Exception:
        match["hold_days"] = None

    book["open"] = [p for p in book["open"] if p is not match]
    book["closed"].append(match)
    # The book's own description of itself has to change with it (TOP100 #21).
    # `_close_time_stop` needs no equivalent: it only ever runs inside
    # `run_market`, which recomputes both further down the same call.
    _restamp(book, market, day)
    _save_market_book(market, book)
    log.info("close_bot_position: CLOSED %s %s [%s] @ %g -> %+.2fR (%s)",
             sym, match.get("direction"), market, price,
             match.get("realized_r") or 0.0, reason)
    return match


def close_bot_batch(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Close MANY bot-book positions in ONE process — one checkout, one commit.

    WHY (2026-08-13, owner: "I want to close each one FAST"). The serial UI
    was correct about the collision (two RUNS racing the same book files) and
    wrong about the unit of work: nine closes as nine workflow runs is nine
    dispatch->run->deploy round trips behind the `scan` mutex — ~half an hour
    of babysitting to clear a stalled strip. The collision was never between
    closes; it was between RUNS. N closes inside one run touch the book
    sequentially in-process, commit once, deploy once, and take roughly the
    wall-clock of one.

    PER-ENTRY TOLERANCE, not all-or-nothing. `bash -e` semantics on a loop of
    single `--close` calls would let one stale row (a symbol whose time-stop
    landed between the strip rendering and the batch arriving) kill eight good
    closes. Here each entry closes independently: a no-match is reported and
    skipped, and the batch succeeds if ANY entry closed. The skipped symbol is
    not lost either way — if it is already closed it leaves the open book, so
    the UI's book-poll settles it as done; if it genuinely failed it stays
    open and the UI times out to "check the book". Honest per-row outcomes.

    Returns (closed, failed) — failed entries carry a "why". The CLI wrapper
    exits 2 only when NOTHING closed, mirroring --close's loud-failure rule.
    """
    closed_all: list[dict] = []
    failed: list[dict] = []
    for e in entries:
        sym = str(e.get("symbol") or "").upper()
        market = str(e.get("market") or "").lower()
        try:
            price = float(e.get("price"))
        except (TypeError, ValueError):
            price = 0.0
        if market not in config.MARKETS or not sym or price <= 0:
            failed.append({**e, "why": "invalid entry (symbol/market/price)"})
            continue
        try:
            row = close_bot_position(sym, market, price,
                                     direction=e.get("direction") or None,
                                     day=e.get("day") or None)
        except Exception as exc:                       # noqa: BLE001 — one bad
            # entry must not take down the rest; the book save for it never
            # happened (close_bot_position persists only on success).
            failed.append({**e, "why": f"{type(exc).__name__}: {exc}"})
            continue
        if row is None:
            failed.append({**e, "why": "no matching open position (already closed?)"})
        else:
            closed_all.append(row)
    return closed_all, failed


def _cooldown_symbols(book: dict, market: str, day: str) -> set[str]:
    """Symbols fully stopped out within VIVEK_BOT_REENTRY_COOLDOWN_DAYS of `day`."""
    days = int(getattr(config, "VIVEK_BOT_REENTRY_COOLDOWN_DAYS", 0) or 0)
    if days <= 0:
        return set()
    try:
        cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=days)).isoformat()
    except ValueError:
        return set()
    return {str(t.get("symbol") or "").upper()
            for t in book.get("closed", [])
            if t.get("market") == market and t.get("exit_reason") == "stop"
            and cutoff <= str(t.get("exit_date") or "") <= day}


def _earnings_within(yf_symbol: str | None, buffer_days: int) -> bool:
    """Best-effort: does this name report within `buffer_days`? Fail-OPEN —
    any lookup problem returns False so a data hiccup never blocks trading.
    Called only for the handful of fills per run, never the universe."""
    if not yf_symbol or buffer_days <= 0:
        return False
    try:
        import yfinance as yf
        cal = yf.Ticker(yf_symbol).calendar
        dates = []
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or []
            dates = raw if isinstance(raw, (list, tuple)) else [raw]
        elif cal is not None and hasattr(cal, "loc"):        # legacy DataFrame shape
            dates = list(cal.loc["Earnings Date"]) if "Earnings Date" in getattr(cal, "index", []) else []
        today = dt.date.today()
        horizon = today + dt.timedelta(days=buffer_days)
        for d in dates:
            # Normalise datetime/pandas-Timestamp → plain date. A datetime IS a
            # date subclass, so comparing it against a date raises TypeError —
            # without this the gate would silently fail-open on Timestamps.
            if isinstance(d, dt.datetime):
                d = d.date()
            if isinstance(d, dt.date) and today <= d <= horizon:
                return True
    except Exception:
        pass
    return False


def _enrich_adv(results: list[dict], frames: dict, yf_map: dict) -> None:
    """Stamp row['adv_usd'] (20-day average dollar volume, quote currency) on
    each scan row so the decision engine's liquidity gates can read it.
    Missing/broken data leaves the row un-stamped (exempt, fail-open)."""
    for row in results:
        df = frames.get(yf_map.get(row.get("symbol")))
        if df is None or "Volume" not in getattr(df, "columns", ()):
            continue
        try:
            tail = df.tail(20)
            adv = float((tail["Close"] * tail["Volume"]).mean())
            if adv > 0:
                row["adv_usd"] = round(adv, 2)
        except Exception:
            continue


# ── per-market run ────────────────────────────────────────────────────────────

def run_market(market: str, results: list[dict], frames: dict, universe: list[dict],
               equity: float | None = None, dry_run: bool | None = None,
               now: dt.datetime | None = None) -> dict:
    """Run the execution layer for ONE market and return the (updated) book.

    No-op (returns the loaded book unchanged) when VIVEK_BOT_ENABLED is False.
    When `dry_run` (defaults to VIVEK_BOT_DRY_RUN) is True it decides + logs but
    does NOT write the book — the final safety gate.
    """
    if not config.VIVEK_BOT_ENABLED:
        log.info("vivek_run [%s]: disabled (VIVEK_BOT_ENABLED=False) — no-op", market)
        return _combined_view()

    equity = config.VIVEK_BOT_ACCOUNT_EQUITY if equity is None else equity
    dry_run = config.VIVEK_BOT_DRY_RUN if dry_run is None else dry_run
    mode = config.VIVEK_BOT_MODE.get(market, "paper")
    # Phase 1–2 NEVER places a live order. A "live" mode is logged loudly and
    # treated as paper until the broker layer (Phase 3) is wired and reviewed.
    if mode == "live":
        if not (config.VIVEK_LIVE_CONFIRMED and not dry_run):
            log.warning("vivek_run [%s]: MODE=live but live execution is NOT wired "
                        "(LIVE_CONFIRMED=%s, dry_run=%s) — treating as PAPER",
                        market, config.VIVEK_LIVE_CONFIRMED, dry_run)
        mode = "paper"

    mkt = config.MARKETS[market]
    if now is None:
        now = dt.datetime.now(ZoneInfo(mkt.timezone))
    day = now.strftime("%Y-%m-%d")
    is_open = market_open(market, now)
    yf_map = {u["symbol"]: u["yf"] for u in universe}
    costs = costs_for(market)                         # fees + slippage R-drag (None = off)

    def price_of(sym):
        return _current_price(frames, yf_map.get(sym))

    # CANONICAL per-market slice: this run can only ever write THIS market's
    # file (Phase 3 book layout v2) — cross-market interference is impossible.
    book = _load_market_book(market)
    book["mode"] = mode

    # Open-book symbols can fall OUT of the universe while still being live
    # positions (delisting, index-tier change, curated-list swap — MDB froze
    # exactly this way after the 2026-07-09 NASDAQ expansion: unpriceable, so
    # its stop could never fire and it squatted a slot). The caller only
    # downloads universe tickers, so fetch the stragglers directly here — a
    # handful at most, best-effort, never breaks the run.
    missing = sorted({p["symbol"] for p in book["open"]
                      if p.get("market") == market and p["symbol"] not in yf_map})
    if missing:
        yf_missing = {s: s + mkt.suffix for s in missing}
        try:
            from ..data import download
            extra = download(list(yf_missing.values()), period="6mo")
            priced = sum(1 for v in extra.values() if v is not None and len(v))
            frames = {**frames, **extra}
            yf_map = {**yf_map, **yf_missing}
            log.info("vivek_run [%s]: %d open position(s) no longer in the "
                     "universe — fetched directly (%d priced): %s",
                     market, len(missing), priced, ", ".join(missing))
        except Exception as e:
            log.warning("vivek_run [%s]: could not fetch off-universe book "
                        "symbols %s: %s", market, ", ".join(missing), e)

    # 1) manage open positions for THIS market — mark to the observed price.
    closed_now = 0
    closed_events: list[dict] = []          # for the end-of-run alert digest
    still_open = []
    max_hold = int(getattr(config, "VIVEK_BOT_MAX_HOLD_DAYS", 0) or 0)
    for pos in book["open"]:
        if pos.get("market") != market:
            still_open.append(pos)
            continue
        price = price_of(pos["symbol"])
        # Auditable freeze detection: a position that can't be priced can't be
        # stopped out. Count consecutive unpriced runs on the position itself
        # so the book (and anyone reading it) SEES the freeze instead of a
        # silently stale mark.
        if price is None:
            pos["unpriced_runs"] = int(pos.get("unpriced_runs") or 0) + 1
            if pos["unpriced_runs"] in (3, 10, 30):
                log.warning("vivek_run [%s]: %s has had NO price for %d "
                            "consecutive runs — stop cannot fire",
                            market, pos["symbol"], pos["unpriced_runs"])
        else:
            pos.pop("unpriced_runs", None)
        # Loss-guard day reference (2026-07-28, TOP100 #13) — BEFORE the sanity
        # guard, which overwrites last_mark. See _stamp_day_ref: the reference
        # must be the PREVIOUS run's mark or an overnight gap escapes the guard.
        _stamp_day_ref(pos, day, price)
        # Mark-sanity guard (2026-07-21, Phase 6 P1): an impossible one-interval
        # move (split / bad print) must not book fake exits into the track
        # record. None -> skip managing this run, exactly like unpriced.
        # `session_open` is what stops a closed-market scan burning the 3-run
        # challenge budget on a run that could never have managed anything.
        if price is not None:
            price = _mark_sanity(pos, price, market, session_open=is_open)
        if is_open and price is not None:
            _mark(pos, price, day, costs)
            # Time stop: hasn't reached TP1 after MAX_HOLD_DAYS → it's going
            # nowhere and squatting in a scarce slot. Runners past TP1 are
            # exempt (already risk-free). Session-only, like every other fill.
            if (pos.get("status") == "open" and max_hold > 0
                    and not pos.get("tp1_hit")
                    and (_held_days(pos, day) or 0) > max_hold):
                _close_time_stop(pos, price, day, costs)
                log.info("vivek_run [%s]: TIME-STOP %s — %s days without TP1, "
                         "closed @ %g (%+.2fR)", market, pos["symbol"],
                         _held_days(pos, day), price, pos.get("realized_r") or 0)
        if pos.get("status") == "closed":
            book["closed"].append(pos)
            closed_events.append(pos)
            closed_now += 1
        else:
            # stamp live unrealised P&L so the book/UI/guard can read it
            if price is not None:
                ur = vivek_guard._unreal_r(pos, price)
                pos["unreal_r"] = round(ur, 3)
                pos["unreal_usd"] = round(ur * (pos.get("risk_usd", 0.0) or 0.0), 2)
            still_open.append(pos)
    book["open"] = still_open

    # 2) daily-loss guardrail — once the session is down ≥ the limit, stop adding
    #    risk for the rest of the day (open positions are still managed above).
    # The previous run's ping memory has to be read BEFORE the new guard dict
    # replaces it on the next line, or every scan re-announces the same breach.
    _prev_notified = ((book.get("guard") or {}).get(market) or {}).get("notified") or ""
    guard = vivek_guard.check(book, market, day, equity, price_of)
    guard["notified"] = _prev_notified          # carried forward, stamped below
    book.setdefault("guard", {})[market] = guard
    if guard["breached"]:
        kind = guard.get("breach_kind") or "daily"
        blind = list(guard.get("unpriced") or [])
        if kind == "unmeasured":
            # TOP100 #15. Nothing has breached on what we can SEE; the halt is
            # because the part we could NOT see is big enough to carry a window
            # over on its own stops. The message has to say that in the subject,
            # not the body: "you are down $X" and "I cannot tell what you are
            # down" call for completely different responses from him, and the
            # second one is fixed by a price feed, not by closing anything.
            hit_usd = guard.get("worst_session_usd", 0.0)
            hit_lim = guard["limit_usd"]
            subject = (f"VIVEK loss guard [{market}] — UNMEASURED, halting on the "
                       f"worst case (${hit_usd:.2f})")
            body = (
                f"{len(blind)} open position(s) could not be priced this run, so "
                f"the loss guard cannot rule out a breach and has failed CLOSED. "
                f"Unpriced: {', '.join(blind) or '?'}.\n"
                f"Measured P&L today ${guard['session_usd']:.2f} vs limit "
                f"-${hit_lim:.2f}; worst case if every unpriced name gapped to "
                f"its own stop ${hit_usd:.2f} today / "
                f"${guard.get('worst_week_usd', 0.0):.2f} this week (weekly limit "
                f"-${guard.get('week_limit_usd', 0.0):.2f}).\n"
                f"New entries are halted for {day}. Open positions are still "
                f"managed — but a position with no price cannot be stopped out, "
                f"so check these names yourself. "
                f"{'DRY RUN.' if dry_run else 'Paper book.'}")
        else:
            hit_usd = guard["session_usd"] if kind == "daily" else guard.get("week_usd", 0.0)
            hit_lim = guard["limit_usd"] if kind == "daily" else guard.get("week_limit_usd", 0.0)
            subject = f"VIVEK {kind}-loss guard [{market}] — P&L ${hit_usd:.2f}"
            body = (f"Limit -${hit_lim:.2f}. New entries halted for {day}. "
                    f"{'DRY RUN.' if dry_run else 'Paper book — managing open positions only.'}")
            if blind:
                body += (f" NOTE: {len(blind)} position(s) unpriced this run "
                         f"({', '.join(blind)}) — the real number may be worse.")
        log.warning("vivek_run [%s]: %s-LOSS GUARD — P&L $%.2f <= -$%.2f "
                    "— halting new entries for %s",
                    market, kind.upper(), hit_usd, hit_lim, day)
        # ROUTED, and deduped in the BOOK (2026-07-28). Three things were wrong
        # with the old `alert_dispatch.send` call here:
        #   1. it skipped the router, so a CRITICAL guard breach arrived with no
        #      severity, no channel policy and the generic fallback emoji;
        #   2. nothing deduped it, so a breached crypto guard — 48 scans a day,
        #      24/7 — would have fired 48 identical CRITICALs down every channel;
        #   3. the router's own rate limit could not have fixed (2), because it
        #      is keyed per EVENT TYPE and scan.yml runs the markets sequentially
        #      in ONE job: any nonzero limit silently swallows the second
        #      market's breach, which is the message you cannot afford to lose.
        # So the dedupe lives where `sector_run`'s does — in the file the same
        # run commits — keyed by day AND kind AND (by construction, since the
        # per-market book files are canonical) market. The stamp is written only
        # after a channel accepts, so a failed send retries on the next scan.
        _stamp = f"{day}:{kind}"
        if _prev_notified == _stamp:
            log.info("vivek_run [%s]: guard breach already announced for %s",
                     market, _stamp)
        else:
            try:
                from .alert_router import smart_send as _smart
                _smart("vivek_guard", subject, body)
                guard["notified"] = _stamp
            except Exception as e:
                log.warning("could not send guard alert: %s", e)

    # 3) decide NEW entries against the CURRENT book (caps/short-bias across runs).
    # Sector rides along so decide() can enforce the per-sector correlation cap;
    # ADV is stamped on the rows for the liquidity gates; recently-stopped
    # symbols are handed over for the re-entry cooldown.
    _enrich_adv(results, frames, yf_map)
    # Sector merge (2026-07-28, owner-authorised — REFINEMENTS #38). The
    # 3-per-sector cap exempts rows with no sector, so NASDAQ had no
    # correlation control whatsoever: its universe file ships no sector column.
    # data/sector_map.json already covered every scanned NASDAQ row; nothing
    # merged it in. Best-effort by design — a failure here leaves rows exactly
    # as they were and decide() then logs its own loud "the cap cannot bind"
    # warning, so this can never fail a scan.
    #
    # The SAME merge is applied to the open book, which back-fills positions
    # opened before this existed (18 of the 23 rows carried sector:'') so the
    # cap counts what is actually held, not just what is being added today.
    try:
        from .. import sectorcache
        cache = sectorcache.load_cache()
        filled_rows = sectorcache.enrich_rows(results, market, cache)
        # Back-fill the OPEN BOOK from two sources, this scan's own rows FIRST:
        # ASX ships GICS sectors on the universe rows themselves and so never
        # lands in the Yahoo-sourced cache at all (0 asx keys in it today) —
        # cache-only back-fill would leave every legacy ASX position exempt
        # from the cap it should be occupying. `held` is a new list of the SAME
        # dicts, so filling them mutates book["open"] in place, which is what
        # persists the back-fill when the book is written back.
        held = [p for p in book["open"] if p.get("market") == market]
        from_scan = {str(r.get("symbol") or "").upper(): str(r.get("sector") or "").strip()
                     for r in results if str(r.get("sector") or "").strip()}
        filled_book = 0
        for pos in held:
            if str(pos.get("sector") or "").strip():
                continue
            sec = from_scan.get(str(pos.get("symbol") or "").upper())
            if sec:
                pos["sector"] = sec
                filled_book += 1
        # ...then this market's UNIVERSE file, which is the canonical taxonomy
        # (#112) and the only source with full coverage: today it carries a
        # sector for 2,212 of 2,212 ASX names, while a scan lists only the ~336
        # that produced a setup. A holding that has dropped out of the scan is
        # exactly the row the cap most needs to see — it occupies a slot and,
        # blank, is exempt from the cap it should be filling. Without this the
        # back-fill reached only names still setting up, which is why three ASX
        # positions (BGA/FPH/AIA) sat sector-less through every scan.
        from_universe = {str(u.get("symbol") or "").upper():
                         str(u.get("sector") or "").strip()
                         for u in (universe or [])
                         if str(u.get("sector") or "").strip()}
        if from_universe:
            for pos in held:
                if str(pos.get("sector") or "").strip():
                    continue
                sec = from_universe.get(str(pos.get("symbol") or "").upper())
                if sec:
                    pos["sector"] = sec
                    filled_book += 1
        # ...then the cache, for holdings neither the scan nor the universe
        # lists (NASDAQ ships no sector column, so this is its only source).
        filled_book += sectorcache.enrich_rows(held, market, cache)
        if filled_rows or filled_book:
            log.info("vivek_run [%s]: sector map filled %d scan rows and "
                     "back-filled %d open positions", market, filled_rows, filled_book)
        # Taxonomy divergence is REPORTED, never rewritten (2026-07-28) — see
        # sectorcache.diverging. Blank-filling above is unaffected: that fills
        # nothing-shaped holes, this would overwrite an answer, and overwriting
        # changes which trades get taken (owner's call, REFINEMENTS #112).
        odd = sectorcache.diverging(held, results)
        if odd:
            log.warning("vivek_run [%s]: %d held position(s) carry a sector this "
                        "market's universe disagrees with, so the per-sector cap "
                        "counts them as separate buckets: %s (REFINEMENTS #112)",
                        market, len(odd), ", ".join(odd))
        # The per-sector cap is per-MARKET; the position and notional ceilings
        # are global. So a real sector can sit at 3-per-market across markets
        # and every check still passes. Reported, never enforced — closing the
        # gap changes which trades get taken (owner's call, REFINEMENTS #113).
        heavy = sectorcache.global_sector_load(
            book["open"], int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0))
        if heavy:
            log.warning("vivek_run [%s]: %d sector(s) exceed the %d-per-sector cap "
                        "once ALL markets are counted together (the cap is enforced "
                        "per market): %s (REFINEMENTS #113)",
                        market, len(heavy),
                        int(getattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 0) or 0),
                        ", ".join(heavy))
    except Exception as e:                                       # noqa: BLE001
        log.warning("vivek_run [%s]: sector merge skipped (%s) - the per-sector "
                    "cap will only bind on rows that already carry one", market, e)
    # NOTIONAL RIDES ALONG TOO (2026-07-28). decide() seeds `open_notional` from
    # this projection, so omitting the field made the $150,000 ceiling count
    # every market's exposure EXCEPT the one it was deciding for — an effective
    # ceiling of $150,000 plus whatever this market already held. Latent while
    # every position is $5,000 and the 30-slot cap binds first at exactly
    # $150,000, but it is a risk cap reading a number it believes is complete.
    # `direction` is READ, not required (2026-07-28, TOP100 #22). It used to be
    # `p["direction"]`, so one row missing the key raised KeyError here and took
    # the WHOLE market run with it — including the mark refresh and the stop
    # checks on every other position, which is a worse failure than the caps
    # miscounting. decide() classifies an unreadable direction as neither side,
    # counts the slot it is really holding, and says so loudly.
    open_book = [{"symbol": p["symbol"], "direction": p.get("direction"),
                  "sector": p.get("sector", ""),
                  "notional": p.get("notional", 0)}
                 for p in book["open"] if p.get("market") == market]
    # Global ceiling across every market (owner, 2026-07-28): the book may hold
    # VIVEK_BOT_MAX_OPEN_TOTAL positions distributed however the setups fall,
    # instead of a fixed slice per market. decide() sees one market, so the
    # cross-market count is supplied here; None = a sibling book is unreadable
    # and decide() will then take nothing.
    gate: dict = {}
    max_total = int(getattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 0) or 0)
    max_notional = float(getattr(config, "VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL", 0) or 0)
    if max_total or max_notional:
        # ONE read of the sibling books feeds BOTH ceilings, so the count and
        # the notional can never disagree about what is open elsewhere.
        seen = _book_elsewhere(market)
        if max_total:
            gate["max_open_total"] = max_total
            gate["open_elsewhere"] = None if seen is None else seen["count"]
        if max_notional:
            gate["max_portfolio_notional"] = max_notional
            gate["notional_elsewhere"] = None if seen is None else seen["notional"]
    # W3-ONLY LEVEL GATE (owner-signed 2026-08-02, cycle "w3-1"). Filters the
    # CANDIDATE rows decide() may consider down to the levels in
    # VIVEK_BOT_LEVEL_TF_ALLOW - the only cohort that passed all three
    # pre-registered confirmation samples. Deliberately OUTSIDE the ringfenced
    # vivek_bot.py: decide() and every skip/cap/guard inside it are untouched;
    # this narrows what it is shown, exactly like VIVEK_BOT_EXCLUDE_FUNDS
    # narrows by instrument type. FAIL-CLOSED: a row with no readable level_tf
    # is dropped and counted - an unlabelled level is precisely the row the
    # evidence cannot vouch for. Held positions, exits, time-stops and guards
    # never pass through here (they run in steps 1-2 above off the book).
    results, level_gate_skipped = _apply_level_gate(results)
    if level_gate_skipped:
        log.info("vivek_run [%s]: level gate (%s) dropped %d candidate row(s) "
                 "before decide()", market,
                 "/".join(getattr(config, "VIVEK_BOT_LEVEL_TF_ALLOW", ()) or ()),
                 level_gate_skipped)
    decision = vivek_bot.decide(results, equity, market=market, open_book=open_book,
                                cooldown_syms=_cooldown_symbols(book, market, day),
                                **gate)

    # 4) fill new entries at the current intraday price (session only, guard clear).
    added, chased, earnings_skipped = 0, 0, 0
    earnings_gate = (market in (getattr(config, "VIVEK_BOT_EARNINGS_MARKETS", ()) or ()))
    earnings_buffer = int(getattr(config, "VIVEK_BOT_EARNINGS_BUFFER_DAYS", 0) or 0)
    opened_events: list[dict] = []          # for the end-of-run alert digest
    # symbol → level_tf from this scan's rows (audit stamp on new tickets).
    level_tf_by_sym = {
        str(r.get("symbol") or "").upper(): r.get("level_tf")
        for r in (results or []) if r.get("symbol")
    }
    if is_open and not guard["breached"]:
        for out in decision["plans"]:
            sym = out["plan"]["symbol"]
            price = _current_price(frames, yf_map.get(sym))
            if price is None:
                continue
            # Earnings gap-avoidance (best-effort, fail-open) — only for the
            # handful of names actually being filled, never the universe.
            if earnings_gate and _earnings_within(yf_map.get(sym), earnings_buffer):
                earnings_skipped += 1
                log.info("SKIP  %-8s [earnings] reports within %dd — gap risk",
                         sym, earnings_buffer)
                continue
            pos = _ticket_to_position(
                out, price, market, day,
                level_tf=level_tf_by_sym.get(str(sym or "").upper()),
            )
            if pos is None:                              # don't chase
                chased += 1
                continue
            # guard against a duplicate already in the persistent book
            if any(p["symbol"] == sym and p.get("market") == market for p in book["open"]):
                continue
            book["open"].append(pos)
            opened_events.append(pos)
            added += 1

    book_open = sum(1 for p in book["open"] if p.get("market") == market)
    book_short = sum(1 for p in book["open"]
                     if p.get("market") == market and p.get("direction") == "short")

    # Book-level snapshot for the UI/header: total open + live unrealised P&L.
    book["summary"] = _summary_of(book, day)

    if dry_run:
        log.info("vivek_run [%s]: DRY-RUN · %s · would add %d, close %d "
                 "(book unchanged: %d open, %d short) · decision: %s",
                 market, "OPEN" if is_open else "closed-session", added, closed_now,
                 book_open, book_short, decision["summary"]["skip_reasons"] or "none")
        # Combined view with THIS market's in-memory (unsaved) slice overlaid.
        return _combined_view(override={market: book})

    _save_market_book(market, book)
    log.info("vivek_run [%s]: %s · %s · +%d new, %d closed (%d open, %d short)",
             market, mode.upper(), "OPEN" if is_open else "closed-session",
             added, closed_now, book_open, book_short)

    _notify_reviews(market, opened_events)
    _stale_probe(market, book, day)

    # Trade-event digest through the shared alert dispatcher. OFF by default:
    # the scan workflow exports SMTP creds and alert_dispatch fires every
    # configured channel, so this would EMAIL each bot trade event. Flip
    # VIVEK_BOT_NOTIFY_TRADES in config when pushes are wanted.
    if getattr(config, "VIVEK_BOT_NOTIFY_TRADES", False) and (opened_events or closed_events):
        try:
            from .alert_dispatch import send as _alert
            lines = [f"OPEN  {p['symbol']} {p.get('direction','?')} @ {p.get('entry')} "
                     f"({p.get('timeframe','?')} {p.get('entry_type','?')})"
                     for p in opened_events]
            lines += [f"CLOSE {p['symbol']} {p.get('exit_reason','?')} @ {p.get('exit')} "
                      f"→ {(p.get('realized_r') or 0):+.2f}R"     # .get default won't catch a stored None
                      for p in closed_events]
            _alert("order_placed",
                   f"VIVEK bot [{market}]: {len(opened_events)} opened, {len(closed_events)} closed",
                   "\n".join(lines))
        except Exception as e:                            # alerts must never break a run
            log.warning("could not send trade-event alert: %s", e)
    # Return the cross-market combined view (same shape callers always saw).
    return _combined_view()


# ── CLI: dry-run smoke test from the latest scan JSON ─────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="VIVEK execution/runner layer (paper book)")
    parser.add_argument("--market", action="append", choices=[*config.MARKETS, "all"],
                        help="market(s) to run; default = all")
    parser.add_argument("--dry-run", action="store_true",
                        help="force dry-run (decide + log only, never write the book)")
    parser.add_argument("--live", action="store_true",
                        help="force-write the paper book (overrides VIVEK_BOT_DRY_RUN); "
                             "still PAPER only — never a real order")
    # Manual close of ONE bot-book position (review C4). Used by the
    # close_position.yml workflow with journal_type=bot.
    parser.add_argument("--close", metavar="SYMBOL",
                        help="close one open bot-book position and exit")
    parser.add_argument("--price", type=float, help="exit price for --close")
    parser.add_argument("--direction", choices=["long", "short"],
                        help="disambiguate --close when both sides exist")
    parser.add_argument("--day", help="exit date YYYY-MM-DD for --close (default: today)")
    parser.add_argument("--close-batch", action="store_true",
                        help="close MANY positions in one process: reads a JSON "
                             "array of {symbol, market, direction?, price, day?} "
                             "from the VIVEK_CLOSE_BATCH env var. One checkout, "
                             "one commit, one deploy for the lot.")
    parser.add_argument("--rebuild-combined", action="store_true",
                        help="regenerate the derived combined book from the "
                             "canonical per-market files and exit")
    parser.add_argument("--verify", action="store_true",
                        help="read-only integrity audit of the book files; "
                             "exit 1 (and list problems) if anything is wrong")
    args = parser.parse_args()

    if args.verify:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        problems = verify_books()
        if problems:
            for pr in problems:
                print(f"BOOK VERIFY FAIL: {pr}")
            raise SystemExit(1)
        v = _combined_view()
        n_files = sum(1 for m in config.MARKETS if _market_book_file(m).exists())
        print(f"book verify OK - {n_files} market file(s), "
              f"{len(v['open'])} open / {len(v['closed'])} closed combined")
        return

    if args.rebuild_combined:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        _write_combined()
        v = _combined_view()
        print(f"combined view rebuilt: {len(v['open'])} open, {len(v['closed'])} closed")
        return

    if args.close_batch:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        raw = os.environ.get("VIVEK_CLOSE_BATCH", "")
        try:
            entries = json.loads(raw)
            assert isinstance(entries, list) and entries
        except (ValueError, AssertionError):
            parser.error("--close-batch needs VIVEK_CLOSE_BATCH set to a "
                         "non-empty JSON array")
        # Same ceiling close.js enforces — belt and braces, since this env var
        # arrives through a workflow input.
        if len(entries) > 30:
            parser.error(f"--close-batch capped at 30 entries, got {len(entries)}")
        closed, failed = close_bot_batch(entries)
        for row in closed:
            print(f"closed {row['symbol']} {row['direction']} [{row['market']}] "
                  f"@ {row['exit_price']} -> {row.get('realized_r', 0):+.2f}R (manual)")
        for e in failed:
            print(f"SKIPPED {e.get('symbol')} [{e.get('market')}]: {e.get('why')}")
        print(f"batch: {len(closed)} closed, {len(failed)} skipped")
        if not closed:
            # Mirrors --close's loud-failure rule: a batch that changed nothing
            # must not commit a no-op "success".
            raise SystemExit(2)
        return

    if args.close:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        if not args.market or len(args.market) != 1 or args.market[0] == "all":
            parser.error("--close needs exactly one --market")
        if args.price is None:
            parser.error("--close needs --price")
        closed = close_bot_position(args.close, args.market[0], args.price,
                                    direction=args.direction, day=args.day or None)
        if closed is None:
            print(f"no open position matched {args.close} [{args.market[0]}] - book untouched")
            raise SystemExit(2)
        print(f"closed {closed['symbol']} {closed['direction']} [{args.market[0]}] "
              f"@ {closed['exit_price']} -> {closed.get('realized_r', 0):+.2f}R (manual)")
        return

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not config.VIVEK_BOT_ENABLED:
        print("VIVEK_BOT_ENABLED is False — runner is a no-op. "
              "Set it True in config.py to exercise the paper book.")
        return

    dry_run = True if args.dry_run else (False if args.live else None)
    markets = list(config.MARKETS) if (not args.market or "all" in args.market) else args.market

    from ..universe import load_universe
    from ..data import download, merge_with_cache

    for market_key in markets:
        pub = ROOT / "public" / "data" / f"{market_key}_vivek.json"
        if not pub.exists():
            print(f"[{market_key}] no scan JSON ({pub.name}) — run the scanner first")
            continue
        results = json.loads(pub.read_text(encoding="utf-8")).get("results", [])
        # v5 payload split (2026-07-31): the published summary carries LITE
        # plans only, and plan_trade builds tickets from row["plans"][tf] —
        # so this STANDALONE path re-joins the detail sidecar to reconstruct
        # exactly the rows the scheduled in-memory path hands run_market.
        # MERGE-ONLY (no decision logic here) and FAIL-CLOSED: without the
        # sidecar the rows keep lite plans and evaluate_setup skips them —
        # the same "run the scanner first" posture as a missing scan file.
        det = pub.with_name(f"{market_key}_vivek_detail.json")
        drows = {}
        if det.exists():
            try:
                drows = (json.loads(det.read_text(encoding="utf-8")) or {}).get("rows") or {}
            except (OSError, ValueError):
                print(f"[{market_key}] detail sidecar unreadable — rows stay lite (fail-closed)")
        elif results and not any("analysis" in r for r in results[:5]):
            print(f"[{market_key}] no detail sidecar ({det.name}) — lite rows, entries will be skipped")
        for r in results:
            extra = drows.get(str(r.get("symbol") or ""))
            if isinstance(extra, dict):
                r.update(extra)
        universe = load_universe(market_key, full=True)
        fresh = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)
        frames, _ = merge_with_cache(market_key, fresh, [u["yf"] for u in universe])
        run_market(market_key, results, frames, universe, dry_run=dry_run)


if __name__ == "__main__":
    main()

"""VIVEK execution/runner layer — Phase 1–2 (dry-run + paper book).

This is the thin orchestration layer that sits between the pure decision engine
(`vivek_bot.decide`) and a broker. In Phase 1–2 there is NO broker: it keeps a
persistent PAPER book per market and resolves it with the same intraday
mark-to-market the journal uses. Live execution is deliberately NOT wired here —
the runner refuses to place a real order regardless of config (see the hard
gates below), so this can run on every scan with zero risk.

What it does each run, per market:

  1. Loads the persistent book (journal/vivek_bot_book.json) — Gap 1. The book
     survives across runs, so the 10-position cap, ≥4-short bias and one-per-
     symbol rules hold over time, not just within a single scan.
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
BOOK_FILE = ROOT / "journal" / "vivek_bot_book.json"
PUBLIC_FILE = ROOT / "public" / "data" / "vivek_bot_book.json"

BOOK_VERSION = 1
TIMEFRAMES = ("1D", "1W")          # server-side intraday timeframes (4H is browser-only)
MAX_CLOSED = 4000


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


def _load_book() -> dict:
    if not BOOK_FILE.exists():
        # An ABSENT book is a legitimate fresh start (first run / deliberate
        # reset). Only an unreadable EXISTING book aborts, below.
        return {"version": BOOK_VERSION, "mode": "paper", "open": [], "closed": []}
    try:
        b = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
        b.setdefault("open", [])
        b.setdefault("closed", [])
        return b
    except Exception as e:
        # THE track record is unreadable. Leave the file EXACTLY as it is (no
        # rename — parking it made the next run silently start empty), alert,
        # and abort the process so nothing downstream can write a blank book.
        log.error("vivek book CORRUPT (%s) — aborting run, book left untouched at %s",
                  e, BOOK_FILE)
        _alert_book_corrupt(e)
        raise BookCorruptError(
            f"vivek_run: corrupt bot book at {BOOK_FILE} ({e}) — run aborted, "
            f"file left untouched; restore from git/backups before re-running"
        ) from e


def _save_book(book: dict) -> None:
    book["version"] = BOOK_VERSION
    book["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if len(book["closed"]) > MAX_CLOSED:
        book["closed"] = book["closed"][-MAX_CLOSED:]
    payload = json.dumps(book, indent=2)
    atomic_write(BOOK_FILE, payload)
    atomic_write(PUBLIC_FILE, payload)


def _ticket_to_position(out: dict, entry_price: float, market: str, day: str) -> dict | None:
    """Build a paper book position from a decide() plan, filling at the current
    intraday price with the journal's don't-chase guard. Carries entry_type +
    label + timeframe + grade + sector end-to-end. Returns None to not-chase."""
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
    snap["source"] = "vivek_bot"
    snap["lens"] = "vivek"     # lens attribution — journal lens tracker reads it
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
    return snap


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
    book = _load_book()                  # corrupt book -> BookCorruptError (C2)
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
    _save_book(book)
    log.info("close_bot_position: CLOSED %s %s [%s] @ %g -> %+.2fR (%s)",
             sym, match.get("direction"), market, price,
             match.get("realized_r") or 0.0, reason)
    return match


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
        return _load_book()

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

    book = _load_book()
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
    guard = vivek_guard.check(book, market, day, equity, price_of)
    book.setdefault("guard", {})[market] = guard
    if guard["breached"]:
        kind = guard.get("breach_kind") or "daily"
        hit_usd = guard["session_usd"] if kind == "daily" else guard.get("week_usd", 0.0)
        hit_lim = guard["limit_usd"] if kind == "daily" else guard.get("week_limit_usd", 0.0)
        log.warning("vivek_run [%s]: %s-LOSS GUARD — P&L $%.2f ≤ -$%.2f "
                    "— halting new entries for %s",
                    market, kind.upper(), hit_usd, hit_lim, day)
        try:
            from .alert_dispatch import send as _alert
            _alert("vivek_guard",
                   f"VIVEK {kind}-loss guard [{market}] — P&L ${hit_usd:.2f}",
                   f"Limit -${hit_lim:.2f}. New entries halted for {day}. "
                   f"{'DRY RUN.' if dry_run else 'Paper book — managing open positions only.'}")
        except Exception as e:
            log.warning("could not send guard alert: %s", e)

    # 3) decide NEW entries against the CURRENT book (caps/short-bias across runs).
    # Sector rides along so decide() can enforce the per-sector correlation cap;
    # ADV is stamped on the rows for the liquidity gates; recently-stopped
    # symbols are handed over for the re-entry cooldown.
    _enrich_adv(results, frames, yf_map)
    open_book = [{"symbol": p["symbol"], "direction": p["direction"],
                  "sector": p.get("sector", "")}
                 for p in book["open"] if p.get("market") == market]
    decision = vivek_bot.decide(results, equity, market=market, open_book=open_book,
                                cooldown_syms=_cooldown_symbols(book, market, day))

    # 4) fill new entries at the current intraday price (session only, guard clear).
    added, chased, earnings_skipped = 0, 0, 0
    earnings_gate = (market in (getattr(config, "VIVEK_BOT_EARNINGS_MARKETS", ()) or ()))
    earnings_buffer = int(getattr(config, "VIVEK_BOT_EARNINGS_BUFFER_DAYS", 0) or 0)
    opened_events: list[dict] = []          # for the end-of-run alert digest
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
            pos = _ticket_to_position(out, price, market, day)
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
    book["summary"] = {
        "open": len(book["open"]),
        "unreal_usd": round(sum(p.get("unreal_usd", 0.0) or 0.0 for p in book["open"]), 2),
        "updated_day": day,
    }

    if dry_run:
        log.info("vivek_run [%s]: DRY-RUN · %s · would add %d, close %d "
                 "(book unchanged: %d open, %d short) · decision: %s",
                 market, "OPEN" if is_open else "closed-session", added, closed_now,
                 book_open, book_short, decision["summary"]["skip_reasons"] or "none")
        return book

    _save_book(book)
    log.info("vivek_run [%s]: %s · %s · +%d new, %d closed (%d open, %d short)",
             market, mode.upper(), "OPEN" if is_open else "closed-session",
             added, closed_now, book_open, book_short)

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
    return book


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
    args = parser.parse_args()

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
        universe = load_universe(market_key, full=True)
        fresh = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)
        frames, _ = merge_with_cache(market_key, fresh, [u["yf"] for u in universe])
        run_market(market_key, results, frames, universe, dry_run=dry_run)


if __name__ == "__main__":
    main()

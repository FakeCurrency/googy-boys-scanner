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
from ..vivek_journal import _current_price, _mark, _snapshot, costs_for, market_open
from ..journal_common import atomic_write

log = logging.getLogger("vivek_run")

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOOK_FILE = ROOT / "journal" / "vivek_bot_book.json"
PUBLIC_FILE = ROOT / "public" / "data" / "vivek_bot_book.json"

BOOK_VERSION = 1
TIMEFRAMES = ("1D", "1W")          # server-side intraday timeframes (4H is browser-only)
MAX_CLOSED = 4000


# ── persistence (separate from the signal journal — Decision §9.2) ────────────

def _load_book() -> dict:
    if BOOK_FILE.exists():
        try:
            b = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
            b.setdefault("open", [])
            b.setdefault("closed", [])
            return b
        except Exception:
            # Never let a corrupt/half-written book crash the run or get silently
            # clobbered — park it for inspection and continue from a clean book.
            try:
                bad = BOOK_FILE.with_suffix(".corrupt.json")
                BOOK_FILE.replace(bad)
                log.warning("vivek book corrupt — parked at %s, starting fresh", bad.name)
            except Exception:
                pass
    return {"version": BOOK_VERSION, "mode": "paper", "open": [], "closed": []}


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
    label + timeframe + grade end-to-end. Returns None to not-chase."""
    plan = out["plan"]
    tf = plan["timeframe"]
    # Reuse the journal's snapshot so the fill model (don't-chase, risk, MAE/MFE,
    # ids) is identical to the forward-test journal — single source of truth.
    row = {
        "symbol": plan["symbol"],
        "name": plan.get("name", plan["symbol"]),
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
    return snap


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

    # 1) manage open positions for THIS market — mark to the observed price.
    closed_now = 0
    still_open = []
    for pos in book["open"]:
        if pos.get("market") != market:
            still_open.append(pos)
            continue
        price = price_of(pos["symbol"])
        if is_open and price is not None:
            _mark(pos, price, day, costs)
        if pos.get("status") == "closed":
            book["closed"].append(pos)
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
        log.warning("vivek_run [%s]: DAILY-LOSS GUARD — session P&L $%.2f ≤ -$%.2f "
                    "(%.1f%% of $%.0f) — halting new entries for %s",
                    market, guard["session_usd"], guard["limit_usd"],
                    guard["limit_pct"], equity, day)
        try:
            from .alert_dispatch import send as _alert
            _alert("vivek_guard",
                   f"VIVEK daily-loss guard [{market}] — session P&L ${guard['session_usd']:.2f}",
                   f"Limit -${guard['limit_usd']:.2f}. New entries halted for {day}. "
                   f"{'DRY RUN.' if dry_run else 'Paper book — managing open positions only.'}")
        except Exception as e:
            log.warning("could not send guard alert: %s", e)

    # 3) decide NEW entries against the CURRENT book (caps/short-bias across runs).
    open_book = [{"symbol": p["symbol"], "direction": p["direction"]}
                 for p in book["open"] if p.get("market") == market]
    decision = vivek_bot.decide(results, equity, market=market, open_book=open_book)

    # 4) fill new entries at the current intraday price (session only, guard clear).
    added, chased = 0, 0
    if is_open and not guard["breached"]:
        for out in decision["plans"]:
            sym = out["plan"]["symbol"]
            price = _current_price(frames, yf_map.get(sym))
            if price is None:
                continue
            pos = _ticket_to_position(out, price, market, day)
            if pos is None:                              # don't chase
                chased += 1
                continue
            # guard against a duplicate already in the persistent book
            if any(p["symbol"] == sym and p.get("market") == market for p in book["open"]):
                continue
            book["open"].append(pos)
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
    args = parser.parse_args()

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

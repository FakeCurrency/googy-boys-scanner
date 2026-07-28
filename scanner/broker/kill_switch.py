"""Daily-loss kill-switch.

Checks the session P&L (realised + unrealised) against SCALP_MAX_DAILY_LOSS.
If the limit is breached, flattens all broker positions and cancels all orders,
then fires an alert via alert_dispatch.

Runs:
  • At the start of bybit_run / paper_run (pre-trade gate)
  • As a standalone hourly workflow to catch moves between scans
    (python -m scanner.broker.kill_switch)
"""

import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

log = logging.getLogger(__name__)


def check_and_kill(j: dict, dry_run: bool = False,
                   limit_usd: float | None = None, label: str = "session") -> bool:
    """Return True if the kill switch fired (caller must abort new orders).

    j          — journal-shaped dict: open[].unreal_pnl + closed[].{session_day,pnl}
    limit_usd  — loss limit; defaults to the legacy SCALP_MAX_DAILY_LOSS so the
                 pre-2026-07-20 call sites/tests behave identically. The bot-book
                 path (run_standalone) passes the VIVEK guard limit instead.
    label      — names the P&L source in logs/alerts (e.g. "bot book [asx]").
    """
    from scanner.config import SCALP_MAX_DAILY_LOSS
    from scanner.scalp_journal import _session_day

    limit = SCALP_MAX_DAILY_LOSS if limit_usd is None else float(limit_usd)
    today        = _session_day()
    today_closed = [c for c in j.get("closed", []) if c.get("session_day") == today]
    today_pnl    = sum(c.get("pnl", 0) for c in today_closed)
    unrealised   = sum(p.get("unreal_pnl") or 0 for p in j.get("open", []))
    total_session = today_pnl + unrealised

    if total_session >= -limit:
        return False

    log.warning("KILL SWITCH TRIGGERED — %s P&L = $%.2f (limit -$%.2f)",
                label, total_session, limit)

    # Dispatch alert to all configured channels
    try:
        from .alert_dispatch import send as _alert
        _alert(
            "kill_switch",
            f"Kill switch triggered — {label} P&L ${total_session:.2f}",
            f"Daily loss limit: -${limit:.2f}. "
            f"{'DRY RUN — not flattening.' if dry_run else 'Flattening all positions now.'}",
        )
    except Exception as e:
        log.warning("could not send kill-switch alert: %s", e)

    if dry_run:
        log.info("kill-switch: dry_run=True — not flattening")
        return True

    if os.environ.get("BYBIT_API_KEY"):
        from scanner.broker import bybit_client as bc
        try:
            bc.cancel_all_orders()
            log.info("kill-switch: Bybit orders cancelled")
        except Exception as e:
            log.error("kill-switch: error cancelling Bybit orders: %s", e)
        try:
            bc.close_all_positions()
            log.info("kill-switch: Bybit positions closed")
        except Exception as e:
            log.error("kill-switch: error closing Bybit positions: %s", e)

    elif os.environ.get("ALPACA_API_KEY"):
        from scanner.broker import alpaca_client as ac
        try:
            resp = ac.close_all_positions()
            log.info("kill-switch: Alpaca positions closed: %s", resp)
        except Exception as e:
            log.error("kill-switch: error closing Alpaca positions: %s", e)
        try:
            resp = ac.cancel_all_orders()
            log.info("kill-switch: Alpaca orders cancelled: %s", resp)
        except Exception as e:
            log.error("kill-switch: error cancelling Alpaca orders: %s", e)

    else:
        log.warning("kill-switch: no broker API keys set — skipping flatten")

    return True


def _live_marks(book: dict) -> dict:
    """(symbol, market) -> latest price for every open book position.

    Best-effort, ONE batched yfinance call (2026-07-20 Phase 4): the standalone
    check runs BETWEEN scans, and pricing open risk off the marks the runner
    stamped last scan meant a fast adverse move could stay invisible for up to
    an hour (crypto overnight/weekend especially). Daily bars: the last close
    IS the running candle for crypto and the delayed session price for stocks —
    exactly the freshness a scan run would have stamped at this moment.

    Returns {} on ANY failure so every caller falls back to the last-scan
    marks per position — the safety net can never end up WORSE than before.
    """
    open_pos = [p for p in book.get("open", []) if p.get("symbol")]
    if not open_pos:
        return {}
    try:
        from scanner import config
        from scanner.data import download
        from scanner.vivek_journal import _current_price
        want = {}                                # yf ticker -> (symbol, market)
        for p in open_pos:
            m = p.get("market")
            if m in config.MARKETS:
                want[p["symbol"] + config.MARKETS[m].suffix] = (p["symbol"], m)
        if not want:
            return {}
        frames = download(sorted(want), period="5d", retries=1)
        by_key = {}
        for p in open_pos:
            m = p.get("market")
            if m in config.MARKETS:
                by_key[(p["symbol"], m)] = p
        quotes = {}
        for yf_t, key in want.items():
            px = _current_price(frames, yf_t)
            if px is None or px <= 0:
                continue
            # Mark-sanity filter (2026-07-21, Phase 6 P1): a split/bad print
            # must not fake-trigger the loss check either. A quote that moved
            # beyond the per-market sanity limit vs the runner's last ACCEPTED
            # mark is dropped -> that position falls back to its stamped mark.
            pos = by_key.get(key)
            ref = (pos or {}).get("last_mark") or 0.0
            limit = (getattr(config, "VIVEK_MARK_SANITY_PCT", {}) or {}).get(
                key[1], 0.0)
            if ref > 0 and limit > 0 and abs(px / ref - 1.0) > limit:
                log.warning("kill-switch: dropping SUSPECT quote for %s [%s]: "
                            "%.6g vs last mark %.6g (limit %.0f%%)",
                            key[0], key[1], px, ref, limit * 100)
                continue
            quotes[key] = px
        return quotes
    except Exception as e:
        log.warning("kill-switch: live quote fetch failed (%s) - falling back "
                    "to last-scan marks", e)
        return {}


def _book_market_journal(book: dict, market: str, market_day: str,
                         quotes: dict | None = None) -> dict:
    """Adapt ONE market's slice of the BOT BOOK to check_and_kill's journal shape.

    Selection is by the market-local day (exit_date), but rows are stamped with
    the AEST _session_day() key because that is what check_and_kill compares
    against. Open positions are re-priced LIVE when `quotes` has a price for
    them (same _unreal_r maths the runner itself stamps with, so the two can
    never disagree on semantics); any position without a live quote falls back
    to the unreal_usd mark from the last scan. Banked partial-exit R
    (realized_r) is added either way.
    """
    from scanner.scalp_journal import _session_day

    from . import vivek_guard
    key = _session_day()
    closed = [{"session_day": key,
               "pnl": (t.get("realized_r") or 0.0) * (t.get("risk_usd") or 0.0)}
              for t in book.get("closed", [])
              if t.get("market") == market and t.get("exit_date") == market_day]
    open_, live_n = [], 0
    for p in book.get("open", []):
        if p.get("market") != market:
            continue
        unreal = p.get("unreal_usd") or 0.0          # last-scan stamp (fallback)
        q = (quotes or {}).get((p.get("symbol"), market))
        if q is not None:
            try:
                unreal = vivek_guard._unreal_r(p, q) * (p.get("risk_usd") or 0.0)
                live_n += 1
            except Exception:                        # malformed row: keep stamp
                unreal = p.get("unreal_usd") or 0.0
        open_.append({"unreal_pnl": unreal
                      + (p.get("realized_r") or 0.0) * (p.get("risk_usd") or 0.0)})
    return {"open": open_, "closed": closed, "live_marks": live_n}


def run_standalone(dry_run: bool = False) -> dict:
    """Check the BOT BOOK — the one-and-only track record — per market.

    Rewritten 2026-07-20 (review C5): the old version read the retired scalp
    journal, whose file no longer exists — session P&L was always $0.00 and
    the switch could never fire. It now reads journal/vivek_bot_book.json and
    applies the same per-market limit the runner's own guard uses
    (VIVEK_BOT_MAX_DAILY_LOSS_PCT of VIVEK_BOT_ACCOUNT_EQUITY).
    Returns {"triggered": [markets], "checked": [markets]} for tests/callers.
    """
    import datetime as dt
    import json
    from zoneinfo import ZoneInfo

    from scanner import config
    from scanner.broker.vivek_run import BOOK_FILE

    book = {"open": [], "closed": []}
    if BOOK_FILE.exists():
        try:
            book = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            # Fail LOUD (C2 spirit): an unreadable track record must alert,
            # not silently report "all clear" on an empty dict.
            log.error("kill-switch: could not read bot book (%s)", e)
            try:
                from .alert_dispatch import send as _alert
                _alert("scan_error", "Kill-switch could not read the bot book",
                       f"{BOOK_FILE}: {e} - loss guard is flying blind until fixed.")
            except Exception:
                pass
    else:
        log.warning("kill-switch: no bot book at %s yet - nothing to guard", BOOK_FILE)

    # Live re-pricing (2026-07-20 Phase 4): between scans the stamped marks can
    # be up to an hour old — exactly the window this standalone check exists to
    # cover. One batched fetch; empty dict on failure = last-scan marks.
    quotes = _live_marks(book)
    if book.get("open"):
        log.info("kill-switch: live quotes for %d/%d open position(s); "
                 "the rest use last-scan marks", len(quotes), len(book["open"]))

    equity = config.VIVEK_BOT_ACCOUNT_EQUITY
    pct = getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0) or 0.0
    limit = equity * pct / 100.0
    out = {"triggered": [], "checked": []}
    for market, mkt in config.MARKETS.items():
        market_day = dt.datetime.now(ZoneInfo(mkt.timezone)).strftime("%Y-%m-%d")
        j = _book_market_journal(book, market, market_day, quotes=quotes)
        out["checked"].append(market)
        if check_and_kill(j, dry_run=dry_run, limit_usd=limit,
                          label=f"bot book [{market}]"):
            out["triggered"].append(market)
        else:
            pnl = (sum(c["pnl"] for c in j["closed"])
                   + sum(p["unreal_pnl"] for p in j["open"]))
            log.info("kill-switch OK [%s] - book P&L $%.2f / limit -$%.2f "
                     "(%d open, %d live-priced)",
                     market, pnl, limit, len(j["open"]), j.get("live_marks", 0))
    return out


def _write_step_summary(result: dict, dry_run: bool) -> None:
    """Put a fired kill switch on the Actions run page, not just in the log.

    THE FIRING LEAVES NO OTHER TRACE (2026-07-28). This workflow holds
    `permissions: contents: read` and has no commit step, so nothing it learns
    reaches the repo; the book is not stamped, no state file is written, and
    `run_standalone` returns to a `__main__` that discarded its result. Until
    today the alert was the ONLY output, and the alert had no secrets exported
    (see the env block in kill_switch.yml), so a fired switch was a green run
    with a warning buried 300 lines into a collapsed step. A green run that
    flattened the account and a green run that found nothing looked identical
    from the Actions list, which is the only place anyone looks.

    Deliberately NOT made to fail the job: firing is the safety net WORKING,
    and a red run here would train the eye to ignore red on the one workflow
    where red must mean something. The summary is the signal.

    Deliberately does NOT halt the next scan either — `vivek_run`'s own
    `vivek_guard` owns that, in the book, per market. Wiring this into entry
    decisions changes which trades get taken and is the owner's call.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    fired = result.get("triggered") or []
    try:
        with open(path, "a", encoding="utf-8") as fh:
            if fired:
                fh.write("## KILL SWITCH TRIGGERED\n\n")
                fh.write(f"Markets: **{', '.join(fired)}**\n\n")
                fh.write(
                    "Dry run - nothing was flattened.\n" if dry_run else
                    "Broker flatten + cancel-all was attempted for any market "
                    "with credentials set. The PAPER BOOK IS UNCHANGED - it "
                    "still shows these positions open, and the next scan is "
                    "governed by `vivek_guard`, not by this run.\n"
                )
                fh.write(f"\nChecked: {', '.join(result.get('checked') or [])}\n")
            else:
                fh.write(
                    f"Kill switch OK - no market breached "
                    f"({', '.join(result.get('checked') or []) or 'none'} checked).\n"
                )
    except Exception as e:      # a summary must never break the safety net
        log.warning("kill-switch: could not write step summary: %s", e)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S UTC",
    )
    p = argparse.ArgumentParser(description="Run the daily-loss kill-switch check")
    p.add_argument("--dry-run", action="store_true", help="Log only, don't flatten")
    args = p.parse_args()
    _result = run_standalone(dry_run=args.dry_run)
    _write_step_summary(_result, args.dry_run)
    if _result.get("triggered"):
        # ::error:: so it surfaces in the Actions UI annotation rail even when
        # the job stays green. See _write_step_summary for why it stays green.
        print("::error::KILL SWITCH TRIGGERED for: "
              + ", ".join(_result["triggered"]))

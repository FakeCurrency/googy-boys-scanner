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


_LEGACY_BROKERS = ("bybit", "alpaca")   # sentinel: try each in order, first-keyed wins


def _flatten_bybit() -> None:
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


def _flatten_alpaca() -> None:
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


# name -> the env var that says "this account is reachable from here". The
# flatten itself is resolved through module globals at call time, not bound
# here, so a test (or a future broker) can replace _flatten_<name> and be seen.
_FLATTEN_KEYS = {"bybit": "BYBIT_API_KEY", "alpaca": "ALPACA_API_KEY"}


def _flatten(name: str) -> None:
    globals()[f"_flatten_{name}"]()


def _armed_brokers(wanted, legacy: bool) -> list[str]:
    """Of the brokers this breach may flatten, the ones that can actually act.

    "Can act" means the account is reachable from this process at all — i.e. its
    API key is in the environment. Under the LEGACY sentinel the first keyed
    broker wins and the rest are dropped, which is exactly the old
    `if BYBIT_API_KEY: ... elif ALPACA_API_KEY: ...`. Under an explicit list
    every keyed broker acts, because the caller has told us they each hold part
    of the book that breached.

    Shared by check_and_kill (which flattens them) and run_standalone (which
    reports them) so the Actions summary cannot claim an account was flattened
    that check_and_kill never had the keys to touch.
    """
    armed = [b for b in wanted if os.environ.get(_FLATTEN_KEYS[b])]
    return armed[:1] if legacy else armed


def check_and_kill(j: dict, dry_run: bool = False,
                   limit_usd: float | None = None, label: str = "session",
                   brokers: tuple[str, ...] | None = None) -> bool:
    """Return True if the kill switch fired (caller must abort new orders).

    j          — journal-shaped dict: open[].unreal_pnl + closed[].{session_day,pnl}
    limit_usd  — loss limit; defaults to the legacy SCALP_MAX_DAILY_LOSS so the
                 pre-2026-07-20 call sites/tests behave identically. The bot-book
                 path (run_standalone) passes the VIVEK guard limit instead.
    label      — names the P&L source in logs/alerts (e.g. "bot book [asx]").
    brokers    — WHICH ACCOUNTS THIS BREACH IS ALLOWED TO FLATTEN. None (the
                 default, and every pre-existing caller) keeps the old
                 behaviour exactly: try Bybit, else Alpaca. An explicit tuple
                 restricts it; an explicit EMPTY tuple flattens nothing.

    THE FLATTEN IS ACCOUNT-WIDE AND THE CHECK IS NOT (2026-07-28). run_standalone
    evaluates the bot book market by market and calls this once per market, but
    `close_all_positions()` does not take a market — it closes everything on the
    account. So an ASX breach used to liquidate the entire Bybit crypto book,
    which held none of the positions that lost the money and was inside its own
    limit. `brokers` is how the caller says which account actually holds the
    losing positions; config.VIVEK_KILL_SWITCH_BROKERS is the map.

    An empty tuple still ALERTS, still logs, still returns True. Not flattening
    is not the same as not firing: the breach is real, the caller must still
    abort new orders, and the operator must still hear about it. What changes is
    only that a paper market stops reaching for a live account.
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

    legacy  = brokers is None
    wanted  = _LEGACY_BROKERS if legacy else tuple(brokers)
    armed   = _armed_brokers(wanted, legacy)

    log.warning("KILL SWITCH TRIGGERED — %s P&L = $%.2f (limit -$%.2f)",
                label, total_session, limit)

    if dry_run:
        plan = "DRY RUN — not flattening."
    elif armed:
        plan = f"Flattening {', '.join(armed)} now."
    elif not wanted:
        plan = "No broker holds this market — nothing to flatten (paper book)."
    else:
        plan = f"No API keys for {', '.join(wanted)} — nothing was flattened."

    # Dispatch alert to all configured channels. Say what will ACTUALLY happen:
    # the old wording promised "Flattening all positions now" even on a paper
    # market with no broker and no keys, so the one message that has to be
    # trustworthy described an action that never occurred.
    try:
        from .alert_dispatch import send as _alert
        _alert(
            "kill_switch",
            f"Kill switch triggered — {label} P&L ${total_session:.2f}",
            f"Daily loss limit: -${limit:.2f}. {plan}",
        )
    except Exception as e:
        log.warning("could not send kill-switch alert: %s", e)

    if dry_run:
        log.info("kill-switch: dry_run=True — not flattening")
        return True

    for name in armed:
        _flatten(name)
    if not armed:
        log.warning("kill-switch: %s", plan)

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

    The closed-row conversion is risk_manager.trade_pnl, which is the same
    `realized_r x risk_usd` this line has always hand-rolled -- it was the only
    place in the repo that knew the bot book records R rather than dollars, and
    that knowledge now lives in one function that every reader shares. Identical
    arithmetic, one owner.
    """
    from scanner.scalp_journal import _session_day

    from . import vivek_guard
    from .risk_manager import trade_pnl
    key = _session_day()
    closed = [{"session_day": key, "pnl": trade_pnl(t)}
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
    Returns {"triggered": [markets], "checked": [markets], "flattened": [brokers]}.

    EACH BROKER IS FLATTENED AT MOST ONCE PER RUN (2026-07-28). The loop calls
    check_and_kill once per market and the flatten is account-wide, so two
    markets mapped to the same broker used to mean two full cancel-all +
    close-all cycles against the same account, the second one racing the first's
    reduce-only orders. `done` makes the second breach alert and count as
    triggered without re-flattening an account that is already flat. Only
    ATTEMPTED brokers are recorded, and never under --dry-run, so a dry pass
    still reports what each market would have reached for.
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
    routing = getattr(config, "VIVEK_KILL_SWITCH_BROKERS", {}) or {}
    out = {"triggered": [], "checked": [], "flattened": []}
    done: set[str] = set()
    for market, mkt in config.MARKETS.items():
        market_day = dt.datetime.now(ZoneInfo(mkt.timezone)).strftime("%Y-%m-%d")
        j = _book_market_journal(book, market, market_day, quotes=quotes)
        out["checked"].append(market)

        if market in routing:
            brokers = tuple(b for b in routing[market] if b not in done)
        else:
            # Unmapped market: keep the old flatten-everything behaviour rather
            # than silently leaving it unguarded, and say so loudly enough that
            # whoever added the market fixes the map.
            log.warning("kill-switch: market %r is not in VIVEK_KILL_SWITCH_BROKERS "
                        "— falling back to the account-wide flatten", market)
            brokers = None

        if check_and_kill(j, dry_run=dry_run, limit_usd=limit,
                          label=f"bot book [{market}]", brokers=brokers):
            out["triggered"].append(market)
            # Record what check_and_kill could ACTUALLY reach, not what the map
            # pointed at: a mapped broker with no API key in this environment
            # was never touched, and the run summary must not say it was.
            if not dry_run:
                hit = _armed_brokers(
                    _LEGACY_BROKERS if brokers is None else brokers,
                    brokers is None)
                done.update(hit)
                out["flattened"].extend(b for b in hit if b not in out["flattened"])
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
                flat = result.get("flattened") or []
                if dry_run:
                    fh.write("Dry run - nothing was flattened.\n")
                else:
                    fh.write(
                        f"Broker flatten + cancel-all attempted on: "
                        f"**{', '.join(flat)}**.\n" if flat else
                        "NO BROKER WAS FLATTENED - the breached market(s) are "
                        "paper-only, or the mapped broker has no API keys set "
                        "here. See `VIVEK_KILL_SWITCH_BROKERS`.\n"
                    )
                    fh.write(
                        "\nThe PAPER BOOK IS UNCHANGED - it still shows these "
                        "positions open, and the next scan is governed by "
                        "`vivek_guard`, not by this run.\n"
                    )
                fh.write(f"\nChecked: {', '.join(result.get('checked') or [])}\n")
            else:
                fh.write(
                    f"Kill switch OK - no market breached "
                    f"({', '.join(result.get('checked') or []) or 'none'} checked).\n"
                )
    except Exception as e:      # a summary must never break the safety net
        log.warning("kill-switch: could not write step summary: %s", e)


def main(argv: list[str] | None = None) -> int:
    """The CLI kill_switch.yml runs. Extracted from the bare ``__main__``
    block 2026-08-20 so the entrypoint the workflow actually invokes can be
    driven by tests (the vivek_run.main / watchdog.main pattern) — the body
    is the old block verbatim, plus an explicit ``return 0``: the run stays
    GREEN even when the switch fires, per _write_step_summary's doctrine
    (firing is the safety net WORKING; the summary + ::error:: annotation
    are the signal, never a red job)."""
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S UTC",
    )
    p = argparse.ArgumentParser(description="Run the daily-loss kill-switch check")
    p.add_argument("--dry-run", action="store_true", help="Log only, don't flatten")
    args = p.parse_args(argv)
    _result = run_standalone(dry_run=args.dry_run)
    _write_step_summary(_result, args.dry_run)
    if _result.get("triggered"):
        # ::error:: so it surfaces in the Actions UI annotation rail even when
        # the job stays green. See _write_step_summary for why it stays green.
        print("::error::KILL SWITCH TRIGGERED for: "
              + ", ".join(_result["triggered"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Sync Bybit position and closed-PnL state into the scalp journal.

Bybit is ground truth. The journal mirrors it, never leads it.

Called at the start of every bybit_run invocation so the journal always
reflects what the broker actually holds before new orders go in.

State transitions handled:
  position exists at Bybit, size > 0  → keep open, update unrealised PnL
  position closed (not in Bybit list)  → look up closed_pnl, mark closed
  order still pending (not filled yet) → keep as open with broker_status="pending"
"""

import datetime as dt
import logging

from . import bybit_client as bc
from .bybit_bracket import to_bybit_symbol

log = logging.getLogger(__name__)


def _now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _positions_by_symbol(positions: list[dict]) -> dict[str, dict]:
    """Index Bybit positions by symbol, ignoring zero-size entries."""
    out = {}
    for p in positions:
        if float(p.get("size", 0)) != 0:
            out[p["symbol"]] = p
    return out


def _rec_ms(rec: dict) -> float | None:
    """When Bybit says this closed-PnL record happened, in epoch ms.

    V5 returns `updatedTime` / `createdTime` as STRINGS of epoch milliseconds.
    Returns None when neither is present or parseable, which the caller treats
    as "cannot date this record" rather than as "old".
    """
    for key in ("updatedTime", "createdTime"):
        raw = rec.get(key)
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _pos_open_ms(pos: dict) -> float | None:
    """When this journal position was created, in epoch ms (None if unknown).

    `opened_ts` is the SCAN's generated_at, i.e. strictly before the order was
    placed, so it is the correct conservative floor: no exit of this position
    can predate the scan that decided to open it. A naive timestamp is read as
    UTC, matching what scan.py writes.
    """
    raw = pos.get("opened_ts")
    if not raw:
        return None
    try:
        ts = dt.datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.timestamp() * 1000.0


def _find_closed_pnl(symbol: str, direction: str, closed_records: list[dict],
                     not_before_ms: float | None = None) -> dict | None:
    """Most recent closed-PnL record matching symbol + direction + TIME.

    THE TIME FILTER IS NOT A REFINEMENT (2026-07-28, TOP100 #20). The match used
    to be symbol + side and nothing else, against the last 50 closed-PnL records
    on the whole account. Re-enter a symbol you have traded before and the
    position vanishing from the live list resolves against the PREVIOUS trade's
    record: the journal books an exit that already happened, at the old trade's
    P&L, with the old trade's exit price deciding stop-vs-target — while the
    real position is still open at Bybit. It then reappears on the next
    reconcile as an ORPHAN, because the journal has just closed the row that
    claimed it. One bad match writes a fabricated trade into the record AND
    strands live exposure that no guard is watching. BTC and ETH are re-entered
    constantly, so this is the common case rather than the exotic one.

    `not_before_ms` is the position's own creation time; records older than that
    cannot be its exit, minus BYBIT_RECONCILE_SKEW_MIN of tolerance for clock
    skew between the runner and the exchange. Records Bybit did not date, and
    positions with no `opened_ts` (pre-2026 rows), fall back to the old
    behaviour rather than silently refusing to close anything.
    """
    wanted_side = "Buy" if direction == "long" else "Sell"
    matches = [
        r for r in closed_records
        if r.get("symbol") == symbol and r.get("side") == wanted_side
    ]
    if not matches:
        return None

    if not_before_ms is not None:
        from scanner import config
        skew  = float(getattr(config, "BYBIT_RECONCILE_SKEW_MIN", 5.0)) * 60_000.0
        floor = not_before_ms - skew
        fresh = []
        for r in matches:
            ms = _rec_ms(r)
            if ms is None or ms >= floor:
                fresh.append(r)
            else:
                log.info("reconcile: ignoring closed-PnL record for %s dated "
                         "before the position was opened (%.0f < %.0f)",
                         symbol, ms, floor)
        if not fresh:
            return None
        matches = fresh

    # Bybit returns records newest-first
    return matches[0]


def _filled_units(pos: dict, size) -> float:
    """The size the BROKER says is on, falling back to the size we asked for.

    A partial fill (thin book, a limit that only half-worked) leaves the journal
    holding the size that was REQUESTED, and every R in the system is then
    divided by risk computed from a quantity that was never on. Bybit's `size`
    is unsigned — direction lives on `side` — so it is used as an absolute.
    """
    try:
        n = abs(float(size))
    except (TypeError, ValueError):
        n = 0.0
    if n > 0:
        return n
    try:
        return abs(float(pos.get("units") or 0)) or 1.0
    except (TypeError, ValueError):
        return 1.0


def _risk_usd(pos: dict, units: float, fill_price: float | None = None) -> float:
    """Dollars actually at risk: (real fill - stop) x real size.

    ONE BASIS FOR OPEN AND CLOSED R (2026-07-28, TOP100 #19). The open branch
    measured risk from the INTENDED entry and the closed branch from the ACTUAL
    fill, so `current_r` stepped at the moment of close even when not a single
    price had moved — the same trade, two different denominators, and the jump
    read as a real move on the journal. `risk_per_trade` is the sizing INPUT and
    is only used when there is no usable fill/stop pair to measure from, because
    it describes the risk that was planned rather than the risk that was taken.
    """
    try:
        stop = float(pos["stop"])
        px   = float(fill_price if fill_price else (pos.get("fill_price") or pos["entry"]))
    except (TypeError, ValueError, KeyError):
        px = stop = 0.0
    risk = abs(px - stop) * units
    if risk > 0:
        return risk
    try:
        return float(pos.get("risk_per_trade") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _exit_reason(rec: dict, pos: dict) -> str:
    """Classify why a position closed.

    Bybit V5 closed-pnl records carry ``execType`` (Trade / BustTrade /
    AdlTrade ...), NOT the ``exitType`` a previous version read — and execType
    can't tell a take-profit from a stop anyway. So: liquidations map from
    execType, and TP-vs-SL is classified by which of the position's own stop /
    target levels the average exit price landed nearer to."""
    exec_type = str(rec.get("execType") or rec.get("exitType") or "").strip()
    if exec_type in ("BustTrade", "AdlTrade", "Liq", "SessionSettlePnl"):
        return "liquidated"
    try:
        exit_px = float(rec.get("avgExitPrice") or 0)
        stop = float(pos.get("stop") or 0)
        target = float(pos.get("target") or 0)
        if exit_px > 0 and stop > 0 and target > 0 and stop != target:
            return "stop" if abs(exit_px - stop) <= abs(exit_px - target) else "target"
    except (TypeError, ValueError):
        pass
    return "unknown"


def _sweep_orphans(j: dict, live_positions: list[dict], known_symbols: set[str],
                   now_ts: str) -> None:
    """AUDIT: positions that exist at Bybit but NOT in the journal (a crash
    between place_order success and save, an adopted timeout order, a manual
    trade). The broker is ground truth — an unknown live position means real
    exposure that no stop-watcher, guard or kill-switch is accounting for.
    Recorded on the journal (j['orphans']) and logged loudly; NOT auto-adopted
    (sizing/stop context is unknowable here — a human must decide)."""
    orphans = []
    for p in live_positions:
        if float(p.get("size", 0)) == 0:
            continue
        if p["symbol"] in known_symbols:
            continue
        orphans.append({
            "symbol": p["symbol"], "side": p.get("side"),
            "size": p.get("size"), "avg_price": p.get("avgPrice"),
            "unrealised": p.get("unrealisedPnl"), "seen_at": now_ts,
        })
        log.error("ORPHAN position at Bybit not in journal: %s %s size=%s "
                  "avg=%s — unmanaged exposure, review immediately",
                  p["symbol"], p.get("side"), p.get("size"), p.get("avgPrice"))
    j["orphans"] = orphans

    # ROUTED, AND DEDUPED ON THE SET OF SYMBOLS (2026-07-28).
    # Two defects fixed at once. (1) It called alert_dispatch.send, the
    # LOW-level path with no severity tier and no rate limit, so
    # "orphan_position" never appeared in ALERT_SEVERITY and could not be
    # routed, silenced or acknowledged like every other event; it also meant
    # `send` fired all three channels unconditionally, which is right for the
    # severity but right by accident. (2) It re-fired on EVERY reconcile for as
    # long as the orphan existed, and an orphan exists until a human adopts or
    # closes it - i.e. the alert that matters most is the one guaranteed to
    # become wallpaper fastest.
    #
    # The fix is not a rate limit. A time window would swallow a genuinely NEW
    # orphan arriving inside it, and a new orphan is the whole point. Dedupe is
    # on the SORTED SET OF SYMBOLS instead, carried on the journal beside the
    # orphan list itself - same shape as vivek_run's guard stamp and
    # sectorbreadth's ping memory, and for the same reason: the memory must be
    # committed by whatever commits the finding, or the two disagree about what
    # has already been said. A changed set (one appears, or one is dealt with
    # and another remains) re-announces; an unchanged set stays quiet.
    seen_key = ",".join(sorted(o["symbol"] for o in orphans))
    if orphans and j.get("orphans_notified") != seen_key:
        try:
            from .alert_router import smart_send as _smart
            _smart("orphan_position",
                   f"Bybit holds {len(orphans)} position(s) the journal doesn't know",
                   "\n".join(f"{o['symbol']} {o['side']} size={o['size']} avg={o['avg_price']}"
                             for o in orphans)
                   + "\nUnmanaged exposure: no stop-watcher, guard or kill-switch "
                     "is accounting for these. Adopt or close them manually.")
            j["orphans_notified"] = seen_key
        except Exception as e:
            log.warning("could not send orphan alert: %s", e)
    elif not orphans:
        # Cleared - the next orphan, even the same symbol, is news again.
        j.pop("orphans_notified", None)


def reconcile_journal(j: dict) -> dict:
    """Mutate the journal in-place: sync every Bybit-tracked open position."""

    # Fetch current state once
    try:
        live_positions = bc.get_positions()
    except Exception as e:
        log.error("could not fetch Bybit positions: %s", e)
        return j

    try:
        closed_pnl_records = bc.get_closed_pnl(limit=50)
    except Exception as e:
        log.warning("could not fetch Bybit closed PnL: %s", e)
        closed_pnl_records = []

    pos_index = _positions_by_symbol(live_positions)
    now_ts    = _now_ts()
    survivors = []

    for pos in j.get("open", []):
        # Journal positions without a Bybit order ID are paper-only — leave untouched
        if not pos.get("broker_order_id"):
            survivors.append(pos)
            continue

        bybit_sym = pos.get("bybit_symbol") or to_bybit_symbol(pos["symbol"])
        direction = pos.get("direction", "long")
        live      = pos_index.get(bybit_sym)

        if live:
            # Position still open at Bybit — update P&L and position-level risk metrics
            unreal     = float(live.get("unrealisedPnl", 0))
            avg_price  = float(live.get("avgPrice", 0))   # actual average fill price
            mark_price = float(live.get("markPrice", 0))  # current mark price

            stop_p   = float(pos["stop"])
            target_p = float(pos["target"])

            # THE SIZE THE BROKER SAYS IS ON, NOT THE ONE WE ASKED FOR
            # (2026-07-28, TOP100 #19). A partial fill used to leave the journal
            # holding the REQUESTED quantity for the life of the trade, and every
            # R in the system was then divided by risk computed from a size that
            # was never on. `risk_usd` is measured on the same basis as the closed
            # branch below — actual fill against the stop, times the real size —
            # because the two used to disagree: open measured from the INTENDED
            # entry, closed from the ACTUAL fill, so `current_r` stepped at the
            # moment of close without a single price having moved.
            requested  = pos.get("units")
            units      = _filled_units(pos, live.get("size"))
            fill_price = avg_price if avg_price > 0 else pos.get("fill_price")
            risk_usd   = _risk_usd(pos, units, avg_price if avg_price > 0 else None)

            stop_dist_pct   = (abs(mark_price - stop_p) / mark_price * 100
                               if mark_price > 0 else 0.0)
            target_dist_pct = (abs(target_p - mark_price) / mark_price * 100
                               if mark_price > 0 else 0.0)
            current_r       = round(unreal / risk_usd, 2) if risk_usd > 0 else 0.0

            row = {
                **pos,
                "unreal_pnl":       round(unreal, 2),
                "broker_status":    "open",
                "units":            units,
                "fill_price":       (round(fill_price, 8) if fill_price else pos.get("fill_price")),
                "mark_price":       (round(mark_price, 6) if mark_price else None),
                "current_r":        current_r,
                "stop_dist_pct":    round(stop_dist_pct, 2),
                "target_dist_pct":  round(target_dist_pct, 2),
            }

            # A partial fill is worth SAYING, not just silently correcting: the
            # size we asked for is recorded once, on the reconcile that first
            # sees the divergence, so the correction leaves an audit trail
            # instead of overwriting what the sizer decided.
            try:
                diverged = abs(float(requested or 0) - units) > 1e-9 * max(1.0, units)
            except (TypeError, ValueError):
                diverged = False
            if diverged:
                if "units_requested" not in pos:
                    row["units_requested"] = requested
                log.warning("%s is open at Bybit for %s units, journal said %s "
                            "- R is now measured against the size actually on",
                            pos["symbol"], units, requested)

            survivors.append(row)
            continue

        # Position is gone from Bybit — find out why via closed_pnl. The time
        # floor is load-bearing, not a refinement: see _find_closed_pnl.
        closed_rec = _find_closed_pnl(bybit_sym, direction, closed_pnl_records,
                                      not_before_ms=_pos_open_ms(pos))

        if closed_rec:
            closed_pnl = float(closed_rec.get("closedPnl", 0))
            reason = _exit_reason(closed_rec, pos)
            # Bybit's closedPnl already NETS exchange trading fees — deducting
            # the $40 ASX-CFD round-turn here double-charged every crypto exit
            # (a taker round-trip on a ~$5k perp position is ~$5.50, not $40).
            pnl    = round(closed_pnl, 2)

            # Same basis as the open branch above (TOP100 #19): dollars actually
            # at risk = (real fill - stop) x the size the broker last confirmed.
            fill_price = float(pos.get("fill_price") or pos["entry"])
            units      = _filled_units(pos, None)
            risk_usd   = _risk_usd(pos, units)
            r_val      = round(closed_pnl / risk_usd, 2) if risk_usd > 0 else 0.0

            # Detect fill-price divergence from intended entry
            intended = float(pos["entry"])
            slip_pct = abs(fill_price - intended) / intended * 100 if intended > 0 else 0.0

            log.info("%s %s → %s  pnl=$%.2f  r=%.2f  slip=%.2f%%",
                     pos["symbol"], direction, reason, pnl, r_val, slip_pct)

            j["closed"].append({
                **pos,
                "status":        "closed",
                "exit_ts":       now_ts,
                "reason":        reason,
                "pnl":           pnl,
                "r":             r_val,
                "fill_price":    pos.get("fill_price"),
                "entry_slip_pct": round(slip_pct, 3),
                "broker_status": "closed",
            })
        else:
            # No closed record found yet — order may not have filled
            log.warning("%s not in live positions and no closed record "
                        "— keeping open (may be pending entry)", pos["symbol"])
            survivors.append({**pos, "broker_status": "pending"})

    j["open"] = survivors

    # Broker-side audit: anything live at Bybit that no journal entry claims.
    known = {p.get("bybit_symbol") or to_bybit_symbol(p["symbol"])
             for p in j.get("open", []) if p.get("broker_order_id")}
    _sweep_orphans(j, live_positions, known, now_ts)
    return j

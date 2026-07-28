"""Order-path integration tests — the ROADMAP's P4 gap.

The bracket-submit → fill → reconcile → kill-switch chain had zero test
coverage: exactly the code that will one day touch real money. These tests
run the REAL bybit_bracket / bybit_reconcile / kill_switch logic against a
fake Bybit client that returns V5-API-shaped payloads (recorded from the
testnet docs), so the whole path is exercised with no network and no keys.
"""

import datetime as dt

import pytest

from scanner import config
from scanner.broker import bybit_bracket as bb
from scanner.broker import bybit_reconcile as br
from scanner.broker import kill_switch as ks


def _pos(**over):
    base = {
        "symbol": "BTC-USD", "direction": "long", "asset_type": "crypto",
        "entry": 60000.0, "stop": 58800.0, "target": 63600.0,
        "units": 0.05, "session_day": "2026-07-09",
    }
    base.update(over)
    return base


# ── bracket submission ────────────────────────────────────────────────────────

pytestmark = pytest.mark.pretrade


def _stub_specs(monkeypatch, qty_step=0.001, min_qty=0.001, tick=0.5):
    """Deterministic instrument spec + no pre-existing order, so submit tests
    never hit the network through get_instrument_spec/find_order_by_link_id."""
    monkeypatch.setattr(bb.bc, "get_instrument_spec",
                        lambda s: {"qty_step": qty_step, "min_qty": min_qty,
                                   "tick_size": tick})
    monkeypatch.setattr(bb.bc, "find_order_by_link_id", lambda s, l: {})


def test_submit_skips_non_crypto():
    out = bb.submit(_pos(asset_type="asx"))
    assert out["skipped"] and "asset_type" in out["reason"]


def test_submit_skips_zero_units():
    out = bb.submit(_pos(units=0))
    assert out["skipped"] and "units" in out["reason"]


def test_submit_places_full_bracket(monkeypatch):
    """The single Bybit order must carry entry + embedded TP + SL — a partial
    bracket (entry without a stop) is the worst live failure mode."""
    calls = []

    def fake_place_order(**kw):
        calls.append(kw)
        return {"orderId": "oid-1", "orderLinkId": kw["orderLinkId"], "orderStatus": "New"}

    _stub_specs(monkeypatch)
    monkeypatch.setattr(bb.bc, "place_order", fake_place_order)
    out = bb.submit(_pos())

    assert out["order_id"] == "oid-1" and out["bybit_symbol"] == "BTCUSDT"
    (kw,) = calls
    assert kw["category"] == "linear" and kw["side"] == "Buy"
    assert kw["symbol"] == "BTCUSDT"
    assert kw["price"] == "60000" and kw["qty"] == "0.05"      # snapped to spec grid
    assert kw["stopLoss"] == "58800" and kw["takeProfit"] == "63600"
    assert kw["tpslMode"] == "Full"


def test_submit_short_maps_to_sell(monkeypatch):
    seen = {}
    _stub_specs(monkeypatch)
    monkeypatch.setattr(bb.bc, "place_order",
                        lambda **kw: seen.update(kw) or {"orderId": "x"})
    bb.submit(_pos(direction="short", entry=60000, stop=61200, target=56400))
    assert seen["side"] == "Sell"


def test_submit_retries_then_succeeds(monkeypatch):
    """Transient API failure → retry with backoff, not a dropped order."""
    attempts = []

    def flaky(**kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("bybit 5xx")
        return {"orderId": "oid-2", "orderLinkId": kw["orderLinkId"]}

    _stub_specs(monkeypatch)
    monkeypatch.setattr(bb.bc, "place_order", flaky)
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    out = bb.submit(_pos())
    assert out["order_id"] == "oid-2" and len(attempts) == 2


def test_submit_gives_up_after_max_attempts(monkeypatch):
    def always_down(**kw):
        raise ConnectionError("bybit down")

    _stub_specs(monkeypatch)
    monkeypatch.setattr(bb.bc, "place_order", always_down)
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    out = bb.submit(_pos())
    assert out["skipped"]
    assert f"after {config.ORDER_RETRY_ATTEMPTS} attempts" in out["reason"]


def test_order_link_id_is_deterministic_and_capped():
    """Same signal on a retried scan must produce the SAME client order id —
    Bybit then rejects the duplicate instead of double-entering."""
    a = bb._order_link_id("BTCUSDT", "long", "2026-07-09")
    b = bb._order_link_id("BTCUSDT", "long", "2026-07-09")
    assert a == b and len(a) <= 36
    assert bb._order_link_id("A" * 60, "long", "2026-07-09") != a


def test_symbol_mapping():
    assert bb.to_bybit_symbol("BTC-USD") == "BTCUSDT"
    assert bb.to_bybit_symbol("sol-usd") == "SOLUSDT"


def test_risk_based_sizing():
    # $50 risk, $1,200 stop distance → 0.041666… units
    qty = bb.calc_qty_risk(60000, 58800, 50)
    assert qty == pytest.approx(50 / 1200)
    assert bb.calc_qty_risk(60000, 60000, 50) == 0.0     # zero stop distance
    assert bb.calc_qty_risk(0, 100, 50) == 0.0


# ── reconcile: broker is ground truth ─────────────────────────────────────────

def _journal_with(open_positions):
    return {"open": list(open_positions), "closed": []}


def _broker_pos(symbol="BTCUSDT", size=0.05, unreal=25.0, avg=60010.0, mark=60510.0):
    """A Bybit V5 /v5/position/list row (the fields reconcile reads)."""
    return {"symbol": symbol, "size": str(size), "unrealisedPnl": str(unreal),
            "avgPrice": str(avg), "markPrice": str(mark)}


def _closed_rec(symbol="BTCUSDT", side="Buy", pnl=170.0, exec_type="Trade",
                avg_exit=None):
    """A Bybit V5 /v5/position/closed-pnl row — the REAL shape: execType
    (Trade/BustTrade/AdlTrade), avgExitPrice. There is no exitType field."""
    return {"symbol": symbol, "side": side, "closedPnl": str(pnl),
            "execType": exec_type,
            "avgExitPrice": str(avg_exit) if avg_exit is not None else ""}


def _open_trade(**over):
    base = {
        "symbol": "BTC-USD", "direction": "long", "broker_order_id": "oid-1",
        "bybit_symbol": "BTCUSDT", "entry": 60000.0, "stop": 58800.0,
        "target": 63600.0, "units": 0.05, "fill_price": 60010.0,
    }
    base.update(over)
    return base


def test_reconcile_leaves_paper_positions_alone(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    paper = _open_trade(broker_order_id=None)
    j = br.reconcile_journal(_journal_with([paper]))
    assert j["open"] == [paper] and j["closed"] == []


def test_reconcile_updates_live_position(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [_broker_pos()])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    (p,) = j["open"]
    assert p["broker_status"] == "open"
    assert p["unreal_pnl"] == 25.0
    assert p["fill_price"] == 60010.0          # broker avgPrice wins
    assert p["mark_price"] == 60510.0
    assert p["current_r"] != 0                 # risk metrics computed


def test_reconcile_marks_target_hit_closed(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])   # gone at broker
    monkeypatch.setattr(br.bc, "get_closed_pnl",
                        lambda limit=50: [_closed_rec(pnl=170.0, avg_exit=63590.0)])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    assert j["open"] == []
    (c,) = j["closed"]
    assert c["reason"] == "target" and c["status"] == "closed"
    # Bybit closedPnl already nets exchange fees — nothing further deducted
    assert c["pnl"] == pytest.approx(170.0)


def test_reconcile_marks_stop_hit_closed(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl",
                        lambda limit=50: [_closed_rec(pnl=-62.0, avg_exit=58810.0)])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    (c,) = j["closed"]
    assert c["reason"] == "stop" and c["r"] < 0


def test_reconcile_short_matches_sell_side_records(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [
        _closed_rec(side="Buy", pnl=999.0, avg_exit=63000.0),  # someone else's long
        _closed_rec(side="Sell", pnl=-30.0, avg_exit=61190.0),
    ])
    short = _open_trade(direction="short", entry=60000, stop=61200, target=56400)
    j = br.reconcile_journal(_journal_with([short]))
    (c,) = j["closed"]
    assert c["pnl"] == pytest.approx(-30.0)                    # matched the Sell record


def test_reconcile_pending_when_gone_but_no_closed_record(monkeypatch):
    """Unfilled limit order: not in positions, no closed PnL → keep it open as
    pending, never invent a close."""
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    (p,) = j["open"]
    assert p["broker_status"] == "pending" and j["closed"] == []


def test_reconcile_survives_broker_outage(monkeypatch):
    def boom():
        raise ConnectionError("bybit unreachable")
    monkeypatch.setattr(br.bc, "get_positions", boom)
    before = _journal_with([_open_trade()])
    j = br.reconcile_journal(before)
    assert len(j["open"]) == 1                                 # untouched, no fake closes


# ── reconcile: a record must be able to BE this position's exit (#20) ─────────
#
# The match used to be symbol + side against the last 50 closed-PnL records on
# the whole account, with no time filter at all. Re-enter a symbol you have
# traded before and the new position resolves against the PREVIOUS trade's
# record: the journal books an exit that already happened, at the old trade's
# P&L, with the old trade's exit price deciding stop-vs-target -- while the real
# position is still open at Bybit and then reappears as an ORPHAN, because the
# journal has just closed the row that claimed it. BTC and ETH are re-entered
# constantly, so this is the common case, not the exotic one.

def _ms(*args) -> str:
    """Epoch milliseconds as a STRING, which is how V5 returns timestamps."""
    return str(int(dt.datetime(*args, tzinfo=dt.timezone.utc).timestamp() * 1000))


def _iso(*args) -> str:
    """The `opened_ts` shape scalp_journal writes (the scan's generated_at)."""
    return dt.datetime(*args, tzinfo=dt.timezone.utc).isoformat(timespec="seconds")


def _dated(when: str, **over):
    rec = _closed_rec(**over)
    rec["updatedTime"] = when
    return rec


def _gone(monkeypatch, records):
    """Nothing live at Bybit; these closed-PnL records on the account."""
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: records)


def test_a_re_entered_symbol_does_not_close_against_the_previous_trades_record(monkeypatch):
    """THE BUG. Yesterday's BTC trade is still in the last-50 window; today's
    BTC position has not filled yet. Nothing may be booked."""
    _gone(monkeypatch, [_dated(_ms(2026, 7, 20, 3, 0), pnl=170.0, avg_exit=63590.0)])
    fresh = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([fresh]))
    assert j["closed"] == []                          # no fabricated trade
    (p,) = j["open"]
    assert p["broker_status"] == "pending"            # correctly still waiting


def test_the_positions_own_exit_is_still_matched(monkeypatch):
    _gone(monkeypatch, [_dated(_ms(2026, 7, 27, 6, 0), pnl=170.0, avg_exit=63590.0)])
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    (c,) = j["closed"]
    assert c["reason"] == "target" and c["pnl"] == pytest.approx(170.0)


def test_a_record_a_few_minutes_early_is_clock_skew_not_a_different_trade(monkeypatch):
    """`opened_ts` is the RUNNER's clock and the record carries the EXCHANGE's.
    Inside BYBIT_RECONCILE_SKEW_MIN they are the same instant."""
    monkeypatch.setattr(config, "BYBIT_RECONCILE_SKEW_MIN", 5.0)
    _gone(monkeypatch, [_dated(_ms(2026, 7, 27, 2, 58), pnl=170.0, avg_exit=63590.0)])
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    assert len(j["closed"]) == 1


def test_a_record_outside_the_skew_window_is_a_different_trade(monkeypatch):
    monkeypatch.setattr(config, "BYBIT_RECONCILE_SKEW_MIN", 5.0)
    _gone(monkeypatch, [_dated(_ms(2026, 7, 27, 2, 30), pnl=170.0, avg_exit=63590.0)])
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    assert j["closed"] == [] and j["open"][0]["broker_status"] == "pending"


def test_the_newest_qualifying_record_wins(monkeypatch):
    """Two exits on the same symbol/side since the position opened -- Bybit
    returns newest-first and the ordering must survive the filter."""
    _gone(monkeypatch, [
        _dated(_ms(2026, 7, 27, 9, 0), pnl=170.0, avg_exit=63590.0),   # newest
        _dated(_ms(2026, 7, 27, 5, 0), pnl=-62.0, avg_exit=58810.0),
        _dated(_ms(2026, 7, 20, 3, 0), pnl=999.0, avg_exit=63000.0),   # last trade
    ])
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    (c,) = j["closed"]
    assert c["pnl"] == pytest.approx(170.0)


def test_an_old_record_cannot_be_reached_past_a_qualifying_one(monkeypatch):
    """The stale record must be DROPPED, not merely outranked -- if the only
    fresh record is second in the list, the filter is what does the work."""
    _gone(monkeypatch, [
        _dated(_ms(2026, 7, 20, 3, 0), pnl=999.0, avg_exit=63000.0),   # stale, first
        _dated(_ms(2026, 7, 27, 5, 0), pnl=-62.0, avg_exit=58810.0),
    ])
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    (c,) = j["closed"]
    assert c["pnl"] == pytest.approx(-62.0) and c["reason"] == "stop"


def test_a_row_with_no_opened_ts_keeps_the_old_behaviour(monkeypatch):
    """Positions written before this field existed must not become uncloseable
    -- the filter degrades to the old match rather than refusing to act."""
    _gone(monkeypatch, [_dated(_ms(2020, 1, 1, 0, 0), pnl=170.0, avg_exit=63590.0)])
    j = br.reconcile_journal(_journal_with([_open_trade()]))     # no opened_ts
    assert len(j["closed"]) == 1


def test_an_undated_record_is_not_assumed_to_be_old(monkeypatch):
    """Same principle from the other side: a record Bybit did not date is
    unknown, not stale, and unknown falls back to the old behaviour."""
    _gone(monkeypatch, [_closed_rec(pnl=170.0, avg_exit=63590.0)])   # no timestamps
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    assert len(j["closed"]) == 1


def test_created_time_is_read_when_updated_time_is_absent(monkeypatch):
    rec = _closed_rec(pnl=170.0, avg_exit=63590.0)
    rec["createdTime"] = _ms(2026, 7, 20, 3, 0)                  # stale, via the fallback key
    _gone(monkeypatch, [rec])
    pos = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([pos]))
    assert j["closed"] == []


def test_a_naive_opened_ts_is_read_as_utc_not_local(monkeypatch):
    """scan.py can write a naive generated_at. Reading it as LOCAL time would
    move the floor by up to a day and silently re-admit the previous trade --
    on a UTC runner that is invisible, so the two forms are compared directly
    rather than through a scenario the CI timezone would make pass anyway."""
    assert (br._pos_open_ms({"opened_ts": "2026-07-27T03:00:00"}) ==
            br._pos_open_ms({"opened_ts": "2026-07-27T03:00:00+00:00"}))

    _gone(monkeypatch, [_dated(_ms(2026, 7, 27, 1, 0), pnl=170.0, avg_exit=63590.0)])
    pos = _open_trade(opened_ts="2026-07-27T03:00:00")           # no tzinfo
    j = br.reconcile_journal(_journal_with([pos]))
    assert j["closed"] == []


def test_an_unparseable_opened_ts_does_not_strand_the_position(monkeypatch):
    _gone(monkeypatch, [_dated(_ms(2026, 7, 20, 3, 0), pnl=170.0, avg_exit=63590.0)])
    j = br.reconcile_journal(_journal_with([_open_trade(opened_ts="whenever")]))
    assert len(j["closed"]) == 1


def test_a_short_is_still_matched_on_side_as_well_as_time(monkeypatch):
    """The time filter narrows the candidates; it must not widen them."""
    _gone(monkeypatch, [
        _dated(_ms(2026, 7, 27, 9, 0), side="Buy", pnl=999.0, avg_exit=63000.0),
        _dated(_ms(2026, 7, 27, 8, 0), side="Sell", pnl=-30.0, avg_exit=61190.0),
    ])
    short = _open_trade(direction="short", entry=60000, stop=61200, target=56400,
                        fill_price=60000.0, opened_ts=_iso(2026, 7, 27, 3, 0))
    j = br.reconcile_journal(_journal_with([short]))
    (c,) = j["closed"]
    assert c["pnl"] == pytest.approx(-30.0)


# ── reconcile: R is measured against the size that was actually on (#19) ──────
#
# Two halves of one defect. The broker's filled `size` was never copied into
# pos["units"], so a partial fill divided every R by a quantity that was never
# on; and the open branch measured risk from the INTENDED entry while the closed
# branch measured it from the ACTUAL fill, so current_r stepped at the moment of
# close even when not a single price had moved.

def test_a_partial_fill_records_the_size_actually_on(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [_broker_pos(size=0.02)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade(units=0.05)]))
    (p,) = j["open"]
    assert p["units"] == pytest.approx(0.02)
    assert p["units_requested"] == pytest.approx(0.05)     # audit trail, written once


def test_a_partial_fill_does_not_overwrite_what_was_first_requested(monkeypatch):
    """The second reconcile sees units=0.02 as the journal value. Re-stamping
    units_requested from it would erase the only record of the real ask."""
    monkeypatch.setattr(br.bc, "get_positions", lambda: [_broker_pos(size=0.02)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    first  = br.reconcile_journal(_journal_with([_open_trade(units=0.05)]))
    second = br.reconcile_journal(_journal_with(first["open"]))
    assert second["open"][0]["units_requested"] == pytest.approx(0.05)


def test_a_full_fill_leaves_no_partial_fill_marker(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [_broker_pos(size=0.05)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade(units=0.05)]))
    (p,) = j["open"]
    assert p["units"] == pytest.approx(0.05) and "units_requested" not in p


def test_r_is_divided_by_the_risk_actually_taken(monkeypatch):
    """0.02 filled of 0.05 asked: $25 unrealised is 1.03R on the size that is on,
    not the 0.41R it reads against the size that was requested."""
    monkeypatch.setattr(br.bc, "get_positions",
                        lambda: [_broker_pos(size=0.02, unreal=25.0, avg=60010.0)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade(units=0.05)]))
    # risk = |60010 - 58800| x 0.02 = $24.20
    assert j["open"][0]["current_r"] == pytest.approx(round(25.0 / 24.20, 2))


def test_open_and_closed_r_share_one_denominator(monkeypatch):
    """The same trade, the same dollars, reconciled live and then closed. R must
    not step on the transition -- it used to, because the two branches measured
    risk from different prices."""
    slipped = _open_trade(opened_ts=_iso(2026, 7, 27, 3, 0))
    monkeypatch.setattr(br.bc, "get_positions",
                        lambda: [_broker_pos(unreal=90.0, avg=60300.0)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    live = br.reconcile_journal(_journal_with([slipped]))
    open_r = live["open"][0]["current_r"]

    _gone(monkeypatch, [_dated(_ms(2026, 7, 27, 9, 0), pnl=90.0, avg_exit=63590.0)])
    closed = br.reconcile_journal(_journal_with(live["open"]))
    assert closed["closed"][0]["r"] == pytest.approx(open_r)


def test_the_planned_risk_no_longer_overrides_the_risk_actually_taken(monkeypatch):
    """`risk_per_trade` is the sizing INPUT. It describes the risk that was
    planned, so it cannot be the denominator once a real fill exists."""
    monkeypatch.setattr(br.bc, "get_positions",
                        lambda: [_broker_pos(size=0.02, unreal=25.0)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade(risk_per_trade=60.0)]))
    assert j["open"][0]["current_r"] == pytest.approx(round(25.0 / 24.20, 2))


def test_risk_falls_back_to_the_planned_number_when_nothing_can_be_measured():
    """A zero-width stop (trailed to breakeven) would divide by zero. The
    planned risk is wrong-but-finite, which beats a silent 0.0R."""
    pos = {"entry": 60000.0, "stop": 60000.0, "fill_price": 60000.0,
           "risk_per_trade": 60.0}
    assert br._risk_usd(pos, 0.05) == pytest.approx(60.0)


def test_a_size_bybit_reports_as_a_string_is_still_a_number():
    assert br._filled_units({"units": 0.05}, "0.02") == pytest.approx(0.02)
    assert br._filled_units({"units": 0.05}, None) == pytest.approx(0.05)
    assert br._filled_units({"units": 0.05}, "junk") == pytest.approx(0.05)
    assert br._filled_units({}, None) == pytest.approx(1.0)      # old default


def test_a_short_size_is_unsigned_at_bybit_and_used_as_such():
    assert br._filled_units({"units": -0.05}, "0.02") == pytest.approx(0.02)
    assert br._filled_units({"units": -0.05}, None) == pytest.approx(0.05)


# ── kill switch ───────────────────────────────────────────────────────────────

def _session_day():
    from scanner.scalp_journal import _session_day as sd
    return sd()


def test_kill_switch_quiet_inside_limit():
    j = {"open": [{"unreal_pnl": -10.0}],
         "closed": [{"session_day": _session_day(), "pnl": -50.0}]}
    assert ks.check_and_kill(j, dry_run=True) is False


def test_kill_switch_fires_past_limit_and_flattens(monkeypatch):
    from scanner.broker import bybit_client as bc
    cancelled, closed = [], []
    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    monkeypatch.setattr(bc, "cancel_all_orders", lambda: cancelled.append(1))
    monkeypatch.setattr(bc, "close_all_positions", lambda: closed.append(1))
    over = -(config.SCALP_MAX_DAILY_LOSS + 1)
    j = {"open": [{"unreal_pnl": over}], "closed": []}
    assert ks.check_and_kill(j, dry_run=False) is True
    assert cancelled and closed                               # actually flattened


def test_kill_switch_dry_run_does_not_flatten(monkeypatch):
    from scanner.broker import bybit_client as bc
    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    monkeypatch.setattr(bc, "cancel_all_orders",
                        lambda: (_ for _ in ()).throw(AssertionError("flattened in dry run")))
    over = -(config.SCALP_MAX_DAILY_LOSS + 1)
    j = {"open": [{"unreal_pnl": over}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True) is True


# -- quantisation, timeout-adoption, exit classification, orphans -------------

def test_submit_quantises_qty_down_and_prices_to_tick(monkeypatch):
    """Sizes floor to qtyStep (never oversize) and prices snap to tickSize --
    Bybit rejects anything off the grid."""
    _stub_specs(monkeypatch, qty_step=0.001, min_qty=0.001, tick=0.5)
    seen = {}
    monkeypatch.setattr(bb.bc, "place_order",
                        lambda **kw: seen.update(kw) or {"orderId": "x"})
    bb.submit(_pos(units=0.0529, entry=60000.26))
    assert seen["qty"] == "0.052"                 # floored, not rounded up
    assert seen["price"] == "60000.5"             # snapped to 0.5 tick


def test_submit_skips_below_min_order_qty(monkeypatch):
    _stub_specs(monkeypatch, qty_step=0.001, min_qty=0.1)
    monkeypatch.setattr(bb.bc, "place_order",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("must not order")))
    out = bb.submit(_pos(units=0.05))
    assert out["skipped"] and "minOrderQty" in out["reason"]


def test_submit_adopts_existing_order_on_ambiguous_timeout(monkeypatch):
    """A timeout AFTER Bybit accepted the order must NOT retry into a double
    entry -- the deterministic orderLinkId is looked up first and adopted."""
    _stub_specs(monkeypatch)
    calls = []
    def timeout(**kw):
        calls.append(1)
        raise TimeoutError("read timed out")
    monkeypatch.setattr(bb.bc, "place_order", timeout)
    monkeypatch.setattr(bb.bc, "find_order_by_link_id",
                        lambda s, l: {"orderId": "already-there", "orderLinkId": l})
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    out = bb.submit(_pos())
    assert len(calls) == 1                        # no blind second submission
    assert out["order_id"] == "already-there"


def test_exit_reason_classified_from_real_v5_fields():
    pos = {"stop": 58800.0, "target": 63600.0}
    assert br._exit_reason(_closed_rec(avg_exit=63550.0), pos) == "target"
    assert br._exit_reason(_closed_rec(avg_exit=58900.0), pos) == "stop"
    assert br._exit_reason(_closed_rec(exec_type="BustTrade"), pos) == "liquidated"
    assert br._exit_reason(_closed_rec(), pos) == "unknown"       # no exit price


def test_reconcile_flags_orphan_broker_positions(monkeypatch):
    """A live position at Bybit that no journal entry claims is unmanaged real
    exposure -- it must be recorded and shouted about, never silently ignored."""
    monkeypatch.setattr(br.bc, "get_positions",
                        lambda: [_broker_pos(symbol="DOGEUSDT", size=500)])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([]))
    (o,) = j["orphans"]
    assert o["symbol"] == "DOGEUSDT" and float(o["size"]) == 500


def test_reconcile_known_positions_are_not_orphans(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [_broker_pos()])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    assert j["orphans"] == []

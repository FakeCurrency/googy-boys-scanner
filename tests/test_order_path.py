"""Order-path integration tests — the ROADMAP's P4 gap.

The bracket-submit → fill → reconcile → kill-switch chain had zero test
coverage: exactly the code that will one day touch real money. These tests
run the REAL bybit_bracket / bybit_reconcile / kill_switch logic against a
fake Bybit client that returns V5-API-shaped payloads (recorded from the
testnet docs), so the whole path is exercised with no network and no keys.
"""

import pytest

from scanner import config
from scanner.broker import bybit_bracket as bb
from scanner.broker import bybit_reconcile as br
from scanner.broker import kill_switch as ks
from scanner.scalp_journal import BROK_RT


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

    monkeypatch.setattr(bb.bc, "place_order", fake_place_order)
    out = bb.submit(_pos())

    assert out["order_id"] == "oid-1" and out["bybit_symbol"] == "BTCUSDT"
    (kw,) = calls
    assert kw["category"] == "linear" and kw["side"] == "Buy"
    assert kw["symbol"] == "BTCUSDT"
    assert kw["price"] == "60000.0" and kw["qty"] == "0.05000"
    assert kw["stopLoss"] == "58800.0" and kw["takeProfit"] == "63600.0"
    assert kw["tpslMode"] == "Full"


def test_submit_short_maps_to_sell(monkeypatch):
    seen = {}
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

    monkeypatch.setattr(bb.bc, "place_order", flaky)
    monkeypatch.setattr(bb.time, "sleep", lambda s: None)
    out = bb.submit(_pos())
    assert out["order_id"] == "oid-2" and len(attempts) == 2


def test_submit_gives_up_after_max_attempts(monkeypatch):
    def always_down(**kw):
        raise ConnectionError("bybit down")

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


def _closed_rec(symbol="BTCUSDT", side="Buy", pnl=170.0, exit_type="takeProfit"):
    """A Bybit V5 /v5/position/closed-pnl row."""
    return {"symbol": symbol, "side": side, "closedPnl": str(pnl), "exitType": exit_type}


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
                        lambda limit=50: [_closed_rec(pnl=170.0, exit_type="takeProfit")])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    assert j["open"] == []
    (c,) = j["closed"]
    assert c["reason"] == "target" and c["status"] == "closed"
    assert c["pnl"] == pytest.approx(170.0 - BROK_RT)          # fees deducted


def test_reconcile_marks_stop_hit_closed(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl",
                        lambda limit=50: [_closed_rec(pnl=-62.0, exit_type="StopLoss")])
    j = br.reconcile_journal(_journal_with([_open_trade()]))
    (c,) = j["closed"]
    assert c["reason"] == "stop" and c["r"] < 0


def test_reconcile_short_matches_sell_side_records(monkeypatch):
    monkeypatch.setattr(br.bc, "get_positions", lambda: [])
    monkeypatch.setattr(br.bc, "get_closed_pnl", lambda limit=50: [
        _closed_rec(side="Buy", pnl=999.0),                    # someone else's long
        _closed_rec(side="Sell", pnl=-30.0, exit_type="StopLoss"),
    ])
    short = _open_trade(direction="short", entry=60000, stop=61200, target=56400)
    j = br.reconcile_journal(_journal_with([short]))
    (c,) = j["closed"]
    assert c["pnl"] == pytest.approx(-30.0 - BROK_RT)          # matched the Sell record


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

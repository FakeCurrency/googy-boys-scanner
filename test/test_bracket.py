"""Tests for Alpaca bracket-order construction (scanner/broker/bracket_order.py).

Pure logic only — no network. Verifies the OCO body, the deterministic
client_order_id (double-submit guard), the stop-limit buffer direction, and the
asset-type allow-list that keeps ASX/commodity/crypto signals off Alpaca.

Run:  python -m pytest test/test_bracket.py
"""

from scanner.broker import bracket_order as bo


def _pos(**kw):
    base = {"symbol": "AAPL", "direction": "long", "entry": 100.0, "stop": 98.0,
            "target": 104.0, "units": 50, "session_day": "2024-06-21",
            "asset_type": "nasdaq"}
    base.update(kw)
    return base


def test_long_bracket_body_shape():
    body = bo.build_bracket(_pos())
    assert body["side"] == "buy"
    assert body["order_class"] == "bracket"
    assert body["qty"] == "50"
    assert body["limit_price"] == "100.0"
    assert body["take_profit"]["limit_price"] == "104.0"
    assert body["stop_loss"]["stop_price"] == "98.0"
    # Long stop-limit sits BELOW the stop so it fills on the way down.
    assert float(body["stop_loss"]["limit_price"]) < 98.0


def test_short_bracket_side_and_stop_limit_direction():
    body = bo.build_bracket(_pos(direction="short", entry=100.0, stop=102.0, target=96.0))
    assert body["side"] == "sell"
    # Short stop-limit sits ABOVE the stop.
    assert float(body["stop_loss"]["limit_price"]) > 102.0


def test_client_order_id_is_deterministic():
    a = bo.build_bracket(_pos())["client_order_id"]
    b = bo.build_bracket(_pos())["client_order_id"]
    assert a == b == "AAPL_long_2024-06-21"


def test_unsupported_asset_types_are_skipped():
    for at in ("asx", "crypto", "commodity", ""):
        res = bo.submit(_pos(asset_type=at))
        assert res.get("skipped") is True
        assert "not supported" in res["reason"]


def test_nasdaq_is_supported_attempts_submit(monkeypatch):
    # Stub the API so we exercise submit() without a real call.
    monkeypatch.setattr(bo.ac, "post", lambda path, body: {"id": "x1", "status": "new"})
    res = bo.submit(_pos(asset_type="nasdaq"))
    assert res.get("skipped") is None
    assert res["order_id"] == "x1"

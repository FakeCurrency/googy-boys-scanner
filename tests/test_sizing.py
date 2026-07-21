"""Unit tests for position sizing — ATR/risk-based and legacy notional."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from scanner.broker.bybit_bracket import calc_qty, calc_qty_risk


class TestCalcQty:
    def test_basic(self):
        assert calc_qty(50000, 5000) == pytest.approx(0.1)

    def test_zero_entry_returns_zero(self):
        assert calc_qty(0, 5000) == 0.0

    def test_negative_entry_returns_zero(self):
        assert calc_qty(-100, 5000) == 0.0


class TestCalcQtyRisk:
    def test_consistent_dollar_risk(self):
        # Entry $50000, stop $49000 → stop_dist=$1000, risk=$100 → qty=0.1 BTC
        qty = calc_qty_risk(50000, 49000, 100)
        assert qty == pytest.approx(0.1)
        # Dollar risk = qty * stop_dist = 0.1 * 1000 = $100
        assert qty * abs(50000 - 49000) == pytest.approx(100)

    def test_larger_atr_gives_smaller_qty(self):
        # Wider stop → smaller position size (same dollar risk)
        qty_tight = calc_qty_risk(100, 98, 100)   # stop_dist=2
        qty_wide  = calc_qty_risk(100, 90, 100)   # stop_dist=10
        assert qty_tight > qty_wide

    def test_zero_stop_dist_returns_zero(self):
        assert calc_qty_risk(100, 100, 100) == 0.0

    def test_zero_entry_returns_zero(self):
        assert calc_qty_risk(0, -5, 100) == 0.0

    def test_short_direction_same_as_long(self):
        # |entry - stop| is the same either way
        qty_long  = calc_qty_risk(100, 95, 50)
        qty_short = calc_qty_risk(100, 105, 50)
        assert qty_long == pytest.approx(qty_short)

    def test_dollar_risk_always_equals_risk_param(self):
        for entry, stop, risk in [(50000, 48500, 100), (100, 97, 50), (0.5, 0.48, 10)]:
            qty = calc_qty_risk(entry, stop, risk)
            if qty > 0:
                actual_risk = qty * abs(entry - stop)
                assert actual_risk == pytest.approx(risk, rel=1e-6)


class TestFillModel:
    """Pessimistic fill: entry = next_open * (1 + slippage) for longs."""

    def _fill_price(self, next_open: float, direction: str, slippage: float = 0.0003) -> float:
        if direction == "long":
            return next_open * (1 + slippage)
        return next_open * (1 - slippage)

    def test_long_fill_above_open(self):
        fill = self._fill_price(100.0, "long")
        assert fill > 100.0

    def test_short_fill_below_open(self):
        fill = self._fill_price(100.0, "short")
        assert fill < 100.0

    def test_slippage_magnitude(self):
        fill = self._fill_price(10000.0, "long", slippage=0.0003)
        assert abs(fill - 10000.0) == pytest.approx(3.0, rel=1e-6)

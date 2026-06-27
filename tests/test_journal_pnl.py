"""Journal P&L calculations and categorization.

Covers the money math and trade-categorization that the paper-trade record is
built on:
  * journal_common.mark_to_market  — unrealised R / PnL (long, short, fees, BE)
  * scalp_journal._close_pos       — slippage-aware fills + round-trip brokerage
  * journal._close                 — swing realised PnL + R
  * _corr_group / summarize        — correlation + regime categorization
"""

import pytest

from scanner import journal as jj
from scanner import scalp_journal as sj
from scanner.journal_common import mark_to_market

pytestmark = pytest.mark.journal


# ── mark_to_market ────────────────────────────────────────────────────────────

class TestMarkToMarket:
    def test_long_in_profit(self):
        # entry 100, stop 90 (risk 10), price 120 (+20) → +2R, +$200 on 10 units
        r, pnl = mark_to_market(100, 120, 90, "long", qty=10)
        assert r == pytest.approx(2.0)
        assert pnl == pytest.approx(200.0)

    def test_short_in_profit(self):
        # short entry 100, stop 110 (risk 10), price 80 (+20 for a short) → +2R
        r, pnl = mark_to_market(100, 80, 110, "short", qty=10)
        assert r == pytest.approx(2.0)
        assert pnl == pytest.approx(200.0)

    def test_fees_reduce_pnl_not_r(self):
        r, pnl = mark_to_market(100, 120, 90, "long", qty=10, fees=40)
        assert r == pytest.approx(2.0)        # R is gross of fees
        assert pnl == pytest.approx(160.0)    # PnL nets the $40 round-trip

    def test_zero_risk_never_divides_by_zero(self):
        r, pnl = mark_to_market(100, 110, 100, "long", qty=5)  # stop == entry
        assert r == 0.0
        assert pnl == pytest.approx(50.0)


# ── scalp _close_pos: slippage + brokerage + categorization ───────────────────

class TestScalpClose:
    def _pos(self, **kw):
        p = {"symbol": "GC", "direction": "long", "entry": 100.0,
             "stop": 95.0, "target": 110.0, "units": 10.0}
        p.update(kw)
        return p

    def test_long_winner_nets_brokerage_and_slippage(self):
        closed = sj._close_pos(self._pos(), price=110.0, ts="t", reason="target", bars=3)
        slip = sj.SLIP
        exit_px = 110.0 * (1 - slip)            # exit slips against a long
        gross = 10.0 * (exit_px - 100.0)
        assert closed["pnl"] == pytest.approx(round(gross - sj.BROK_RT, 2))
        assert closed["reason"] == "target"
        assert closed["status"] == "closed"

    def test_short_winner_mirrors_long(self):
        pos = self._pos(direction="short", stop=105.0, target=90.0)
        closed = sj._close_pos(pos, price=90.0, ts="t", reason="target", bars=2)
        slip = sj.SLIP
        exit_px = 90.0 * (1 + slip)             # exit slips against a short
        gross = 10.0 * (100.0 - exit_px)
        assert closed["pnl"] == pytest.approx(round(gross - sj.BROK_RT, 2))
        assert closed["r"] > 0

    def test_brokerage_is_full_round_trip(self):
        # a scratch trade (exit≈entry) still pays the round-trip cost
        closed = sj._close_pos(self._pos(), price=100.0, ts="t", reason="manual", bars=0)
        assert closed["pnl"] < 0
        assert closed["pnl"] == pytest.approx(round(10.0 * (100 * (1 - sj.SLIP) - 100) - sj.BROK_RT, 2))

    def test_loss_is_negative_r(self):
        closed = sj._close_pos(self._pos(), price=95.0, ts="t", reason="stop", bars=1)
        assert closed["r"] < 0 and closed["pnl"] < 0


# ── swing _close: realised PnL + R ────────────────────────────────────────────

class TestSwingClose:
    def _pos(self, **kw):
        p = {"symbol": "BHP", "direction": "long", "entry": 40.0, "stop": 38.0,
             "target": 46.0, "shares": 25, "brokerage": 5}
        p.update(kw)
        return p

    def test_long_pnl_nets_two_way_brokerage(self):
        closed = jj._close(self._pos(), price=46.0, date="2026-06-27", reason="target", bars=10)
        # 25 * (46-40) = 150 gross, minus 2 * $5 brokerage
        assert closed["pnl"] == pytest.approx(150 - 10)
        assert closed["r"] == pytest.approx((46 - 40) / (40 - 38))   # 3R

    def test_short_pnl_and_r(self):
        pos = self._pos(direction="short", entry=40.0, stop=42.0, target=34.0)
        closed = jj._close(pos, price=34.0, date="2026-06-27", reason="target", bars=8)
        assert closed["pnl"] == pytest.approx(25 * (40 - 34) - 10)
        assert closed["r"] == pytest.approx((40 - 34) / (42 - 40))   # 3R

    def test_invalid_risk_yields_zero_r(self):
        # stop == entry → risk 0 → R defaults to 0 (no divide-by-zero)
        closed = jj._close(self._pos(stop=40.0), price=44.0, date="d", reason="manual", bars=1)
        assert closed["r"] == 0.0


# ── categorization: correlation groups + summarize ────────────────────────────

class TestCategorization:
    def test_corr_group_explicit_mapping(self):
        # GOLD maps to the 'metals' bucket in config.SCALP_CORRELATION_GROUPS
        assert sj._corr_group("GOLD") == "metals"

    def test_corr_group_falls_back_to_type_sector(self):
        assert sj._corr_group("XYZ", asset_type="crypto", sector="defi") == "crypto:defi"

    def test_corr_group_unknown_is_solo(self):
        # no mapping, no type/sector → a per-symbol bucket (treated as uncorrelated)
        assert sj._corr_group("WEIRD") == "solo:weird"

    def test_summarize_splits_long_short_and_groups(self, make_journal, closed_trade):
        j = make_journal(
            open_=[{"symbol": "GC", "direction": "long", "corr_group": "metals",
                    "unreal_pnl": 12.0, "session_day": sj._session_day()}],
            closed=[closed_trade(direction="long", pnl=100, r=1.5, market_regime="trending"),
                    closed_trade(direction="short", pnl=-50, r=-1.0, market_regime="ranging")],
        )
        s = sj.summarize(j)
        assert s["longs"]["closed"] == 1 and s["shorts"]["closed"] == 1
        assert s["group_exposure"]["metals"] == 1
        # regime categorization tallies wins/trades per regime
        assert s["regime_stats"]["trending"]["wins"] == 1
        assert s["regime_stats"]["ranging"]["trades"] == 1

    def test_summarize_win_rate(self, make_journal, closed_trade):
        j = make_journal(closed=[
            closed_trade(direction="long", pnl=100, r=2.0),
            closed_trade(direction="long", pnl=100, r=1.0),
            closed_trade(direction="long", pnl=-50, r=-1.0)])
        s = sj.summarize(j)
        assert s["longs"]["win_rate"] == pytest.approx(66.7, abs=0.1)  # 2 of 3

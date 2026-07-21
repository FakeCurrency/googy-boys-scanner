"""Unit tests for scalp_journal — AEST session-day reset and journal logic."""

import datetime as dt
import sys
import pathlib

# Make scanner importable from repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from scanner.scalp_journal import _session_day, _corr_group, _walk_1h, SLIP


class TestSessionDay:
    """_session_day() must return the calendar date in AEST (Australia/Sydney)."""

    def test_utc_midnight_is_previous_aest_day(self):
        # Midnight UTC on 2025-03-01 is 11:00 AEDT (UTC+11) — still 01 March
        ts = "2025-03-01T00:00:00"
        assert _session_day(ts) == "2025-03-01"

    def test_utc_13_is_midnight_aest_standard(self):
        # 13:00 UTC on 2025-07-01 = midnight AEST (UTC+10, AEST standard time)
        ts = "2025-07-01T13:00:00"
        assert _session_day(ts) == "2025-07-01"

    def test_utc_1359_still_same_aest_day_standard(self):
        # 13:59 UTC on 2025-07-01 = 23:59 AEST (UTC+10, standard) on 2025-07-01 — not rolled over yet
        ts = "2025-07-01T13:59:00"
        assert _session_day(ts) == "2025-07-01"

    def test_utc_1400_rolls_to_next_aest_day_standard(self):
        # 14:00 UTC on 2025-07-01 = 00:00 AEST (UTC+10, standard) on 2025-07-02 — new day
        ts = "2025-07-01T14:00:00"
        assert _session_day(ts) == "2025-07-02"

    def test_utc_12_is_midnight_aedt(self):
        # 13:00 UTC on 2025-01-01 = midnight AEDT (UTC+11, daylight saving)
        # Actually 13:00 UTC = 01:00 AEDT — so this is already Jan 2nd at 01:00 AEDT
        ts = "2025-01-01T13:00:00"
        # UTC+11 → 2025-01-02 00:00 AEDT
        assert _session_day(ts) == "2025-01-02"

    def test_no_arg_returns_today_string(self):
        result = _session_day()
        # Should be a valid date string in YYYY-MM-DD format
        dt.date.fromisoformat(result)  # raises ValueError if malformed

    def test_z_suffix_handled(self):
        ts = "2025-07-15T13:30:00Z"
        result = _session_day(ts)
        assert len(result) == 10
        assert result[4] == "-"

    def test_invalid_ts_falls_back_gracefully(self):
        result = _session_day("not-a-date")
        # Should return today rather than crashing
        dt.date.fromisoformat(result)


class TestCorrGroup:
    def test_known_crypto_falls_to_asset_sector(self):
        # BTC has no explicit entry in SCALP_CORRELATION_GROUPS → falls back to "crypto:crypto"
        g = _corr_group("BTC", "crypto", "crypto")
        assert g == "crypto:crypto"

    def test_unknown_falls_back_to_asset_sector(self):
        g = _corr_group("UNKNOWN123", "nasdaq", "tech")
        assert "nasdaq" in g or "tech" in g

    def test_metals_group(self):
        g = _corr_group("GOLD", "commodity", "metals")
        assert g == "metals"

    def test_us_tech_group(self):
        g = _corr_group("AAPL", "nasdaq", "tech")
        assert g == "us_tech"


class TestWalkExits:
    """_walk_1h exit precedence + long/short mirroring.

    Locks the refactored single-loop exit logic: gap-stop, gap-target,
    intrabar-stop, intrabar-target — checked in that order, mirrored by side.
    """

    @staticmethod
    def _df(bars):
        """bars: list of (open, high, low, close). Hourly index starting 01:00."""
        pd = pytest.importorskip("pandas")
        idx = pd.date_range("2026-01-01 01:00", periods=len(bars), freq="h")
        return pd.DataFrame(
            {"Open":  [b[0] for b in bars],
             "High":  [b[1] for b in bars],
             "Low":   [b[2] for b in bars],
             "Close": [b[3] for b in bars]},
            index=idx,
        )

    @staticmethod
    def _pos(direction, entry, stop, target):
        return {"direction": direction, "entry": entry, "fill_price": entry,
                "stop": stop, "target": target, "units": 10, "filled": True,
                "opened_ts": "2026-01-01T00:00:00"}

    # ── LONG ──────────────────────────────────────────────────────────────────
    def test_long_intrabar_target(self):
        df  = self._df([(100, 101, 99, 100), (100, 111, 100, 105)])
        out = _walk_1h(df, self._pos("long", 100, 95, 110))
        assert out["reason"] == "target"
        assert out["exit"] == pytest.approx(110 * (1 - SLIP), rel=1e-6)

    def test_long_intrabar_stop(self):
        df  = self._df([(100, 101, 99, 100), (100, 101, 94, 96)])
        out = _walk_1h(df, self._pos("long", 100, 95, 110))
        assert out["reason"] == "stop"
        assert out["exit"] == pytest.approx(95 * (1 - SLIP), rel=1e-6)

    def test_long_stop_gap_takes_open(self):
        df  = self._df([(100, 101, 99, 100), (93, 94, 92, 93)])
        out = _walk_1h(df, self._pos("long", 100, 95, 110))
        assert out["reason"] == "stop-gap"
        assert out["exit"] == pytest.approx(93 * (1 - SLIP), rel=1e-6)

    def test_long_target_gap_takes_open(self):
        df  = self._df([(100, 101, 99, 100), (112, 113, 111, 112)])
        out = _walk_1h(df, self._pos("long", 100, 95, 110))
        assert out["reason"] == "target-gap"

    def test_long_stop_checked_before_target_within_bar(self):
        # A bar that touches both stop and target: stop must win (precedence).
        df  = self._df([(100, 101, 99, 100), (100, 111, 94, 100)])
        out = _walk_1h(df, self._pos("long", 100, 95, 110))
        assert out["reason"] == "stop"

    # ── SHORT (mirror) ─────────────────────────────────────────────────────────
    def test_short_intrabar_target(self):
        df  = self._df([(100, 101, 99, 100), (100, 100, 89, 95)])
        out = _walk_1h(df, self._pos("short", 100, 105, 90))
        assert out["reason"] == "target"
        assert out["exit"] == pytest.approx(90 * (1 + SLIP), rel=1e-6)

    def test_short_intrabar_stop(self):
        df  = self._df([(100, 101, 99, 100), (100, 106, 99, 104)])
        out = _walk_1h(df, self._pos("short", 100, 105, 90))
        assert out["reason"] == "stop"
        assert out["exit"] == pytest.approx(105 * (1 + SLIP), rel=1e-6)

    def test_short_stop_gap_takes_open(self):
        df  = self._df([(100, 101, 99, 100), (107, 108, 106, 107)])
        out = _walk_1h(df, self._pos("short", 100, 105, 90))
        assert out["reason"] == "stop-gap"
        assert out["exit"] == pytest.approx(107 * (1 + SLIP), rel=1e-6)

    def test_short_target_gap_takes_open(self):
        df  = self._df([(100, 101, 99, 100), (88, 89, 87, 88)])
        out = _walk_1h(df, self._pos("short", 100, 105, 90))
        assert out["reason"] == "target-gap"

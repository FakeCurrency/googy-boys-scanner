"""Tests for Phase 7 modules: alert_router, expectancy, health_check."""

import datetime as dt
import json
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# ─────────────────────────────────────────────────────────────────────────────
# alert_router
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertRouterSeverity:
    def test_kill_switch_is_critical(self):
        from scanner.broker.alert_router import get_severity
        assert get_severity("kill_switch") == "CRITICAL"

    def test_anomaly_is_warning(self):
        from scanner.broker.alert_router import get_severity
        assert get_severity("anomaly") == "WARNING"

    def test_order_placed_is_info(self):
        from scanner.broker.alert_router import get_severity
        assert get_severity("order_placed") == "INFO"

    def test_unknown_event_defaults_to_warning(self):
        from scanner.broker.alert_router import get_severity
        assert get_severity("totally_unknown_event") == "WARNING"


class TestAlertRouterChannels:
    def test_info_events_get_no_channels(self):
        from scanner.broker.alert_router import get_channels
        assert get_channels("order_placed") == []

    def test_critical_events_get_all_channels(self):
        from scanner.broker.alert_router import get_channels
        channels = get_channels("kill_switch")
        assert "telegram" in channels
        assert "discord"  in channels
        assert "email"    in channels

    def test_warning_events_exclude_email(self):
        from scanner.broker.alert_router import get_channels
        channels = get_channels("anomaly")
        assert "telegram" in channels
        assert "discord"  in channels
        assert "email" not in channels

    def test_explicit_severity_override(self):
        from scanner.broker.alert_router import get_channels
        assert "email" in get_channels("anomaly", severity="CRITICAL")
        assert get_channels("kill_switch", severity="INFO") == []


class TestAlertRouterRateLimit:
    def test_first_send_always_passes(self, tmp_path, monkeypatch):
        from scanner.broker import alert_router
        monkeypatch.setattr(alert_router, "STATE_FILE", tmp_path / "state.json")
        assert alert_router.should_send("order_placed") is True

    def test_second_send_blocked_within_window(self, tmp_path, monkeypatch):
        from scanner.broker import alert_router
        monkeypatch.setattr(alert_router, "STATE_FILE", tmp_path / "state.json")
        assert alert_router.should_send("order_placed") is True   # first: pass
        assert alert_router.should_send("order_placed") is False  # second: rate-limited

    def test_zero_rate_limit_always_sends(self, tmp_path, monkeypatch):
        from scanner.broker import alert_router
        monkeypatch.setattr(alert_router, "STATE_FILE", tmp_path / "state.json")
        assert alert_router.should_send("kill_switch") is True
        assert alert_router.should_send("kill_switch") is True  # no rate limit → always pass

    def test_expired_rate_limit_passes(self, tmp_path, monkeypatch):
        from scanner.broker import alert_router
        monkeypatch.setattr(alert_router, "STATE_FILE", tmp_path / "state.json")
        # Manually write a very old timestamp
        state = {"last_sent": {
            "order_placed": (
                dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
            ).isoformat(timespec="seconds")
        }}
        (tmp_path / "state.json").write_text(json.dumps(state))
        assert alert_router.should_send("order_placed") is True  # expired → pass

    def test_different_event_types_are_independent(self, tmp_path, monkeypatch):
        from scanner.broker import alert_router
        monkeypatch.setattr(alert_router, "STATE_FILE", tmp_path / "state.json")
        assert alert_router.should_send("anomaly")        is True
        assert alert_router.should_send("order_rejected") is True   # different key
        assert alert_router.should_send("anomaly")        is False  # rate-limited


# ─────────────────────────────────────────────────────────────────────────────
# expectancy
# ─────────────────────────────────────────────────────────────────────────────

def _make_trades(r_values: list[float], regime: str = "trending",
                 hour: int = 10) -> list[dict]:
    return [
        {
            "r":             r,
            "pnl":           r * 100,
            "market_regime": regime,
            "opened_ts":     f"2026-06-01T{hour:02d}:00:00+00:00",
        }
        for r in r_values
    ]


class TestCalcExpectancy:
    def test_empty_returns_zeros(self):
        from scanner.broker.expectancy import calc_expectancy
        result = calc_expectancy([])
        assert result["trades"] == 0
        assert result["expectancy_r"] == 0.0
        assert result["edge_ratio"] is None

    def test_positive_expectancy(self):
        from scanner.broker.expectancy import calc_expectancy
        # 60% win rate, avg win 2R, avg loss 1R  → E = 0.6*2 - 0.4*1 = 0.8
        trades = _make_trades([2.0, 2.0, 2.0, -1.0, -1.0] * 4)
        result = calc_expectancy(trades)
        assert result["expectancy_r"] > 0
        assert result["win_rate"] == pytest.approx(60.0)
        assert result["avg_win_r"]  > 0
        assert result["avg_loss_r"] > 0

    def test_negative_expectancy(self):
        from scanner.broker.expectancy import calc_expectancy
        # 40% win rate, avg win 1R, avg loss 2R  → E = 0.4*1 - 0.6*2 = -0.8
        trades = _make_trades([-2.0, -2.0, -2.0, 1.0, 1.0] * 4)
        result = calc_expectancy(trades)
        assert result["expectancy_r"] < 0

    def test_all_winners(self):
        from scanner.broker.expectancy import calc_expectancy
        result = calc_expectancy(_make_trades([1.0, 1.5, 2.0]))
        assert result["win_rate"] == pytest.approx(100.0)
        assert result["avg_loss_r"] == 0.0
        assert result["expectancy_r"] > 0

    def test_all_losers(self):
        from scanner.broker.expectancy import calc_expectancy
        result = calc_expectancy(_make_trades([-1.0, -1.5]))
        assert result["win_rate"] == pytest.approx(0.0)
        assert result["avg_win_r"] == 0.0
        assert result["expectancy_r"] < 0

    def test_edge_ratio(self):
        from scanner.broker.expectancy import calc_expectancy
        # avg_win = 2R, avg_loss = 1R → edge_ratio = 2.0
        trades = _make_trades([2.0, 2.0, -1.0, -1.0])
        result = calc_expectancy(trades)
        assert result["edge_ratio"] == pytest.approx(2.0)

    def test_low_sample_note(self):
        from scanner.broker.expectancy import calc_expectancy
        result = calc_expectancy(_make_trades([1.0, -1.0]))  # 2 trades < 20 min
        assert "low_sample" in result["note"]

    def test_expectancy_usd_scales_with_risk(self):
        from scanner.broker.expectancy import calc_expectancy
        from scanner import config as _cfg
        trades = _make_trades([2.0, 2.0, -1.0, -1.0])
        result = calc_expectancy(trades)
        expected_usd = result["expectancy_r"] * float(getattr(_cfg, "SCALP_RISK_PER_TRADE", 100))
        assert result["expectancy_usd"] == pytest.approx(expected_usd, abs=0.01)


class TestByRegime:
    def test_groups_by_regime(self):
        from scanner.broker.expectancy import by_regime
        trades = (
            _make_trades([1.0, 1.0, 1.0, -0.5], regime="trending") +
            _make_trades([-1.0, -1.0, 0.5],      regime="ranging")
        )
        result = by_regime(trades)
        assert "trending" in result
        assert "ranging"  in result
        assert result["trending"]["trades"] == 4
        assert result["ranging"]["trades"]  == 3

    def test_trending_beats_ranging(self):
        from scanner.broker.expectancy import by_regime
        trades = (
            _make_trades([2.0, 2.0, -1.0], regime="trending") +
            _make_trades([-2.0, -2.0, 1.0], regime="ranging")
        )
        result = by_regime(trades)
        assert result["trending"]["expectancy_r"] > result["ranging"]["expectancy_r"]


class TestBySessionHour:
    def test_groups_by_utc_hour(self):
        from scanner.broker.expectancy import by_session_hour
        trades = [
            {"r": 1.0,  "pnl": 100, "opened_ts": "2026-06-01T08:00:00+00:00"},
            {"r": 1.5,  "pnl": 150, "opened_ts": "2026-06-02T08:30:00+00:00"},
            {"r": -1.0, "pnl": -100, "opened_ts": "2026-06-01T22:00:00+00:00"},
        ]
        result = by_session_hour(trades)
        assert 8  in result
        assert 22 in result
        assert result[8]["trades"] == 2
        assert result[22]["trades"] == 1

    def test_invalid_ts_skipped(self):
        from scanner.broker.expectancy import by_session_hour
        trades = [
            {"r": 1.0, "pnl": 100, "opened_ts": "not-a-date"},
            {"r": 1.0, "pnl": 100, "opened_ts": "2026-06-01T10:00:00+00:00"},
        ]
        result = by_session_hour(trades)
        assert len(result) == 1   # only the valid timestamp included
        assert 10 in result

    def test_missing_ts_skipped(self):
        from scanner.broker.expectancy import by_session_hour
        trades = [{"r": 1.0, "pnl": 100}]  # no opened_ts
        result = by_session_hour(trades)
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# health_check
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_run_all_checks_returns_valid_structure(self):
        import health_check
        result = health_check.run_all_checks()
        assert "status" in result
        assert "code"   in result
        assert result["code"] in (0, 1, 2)
        assert result["status"] in ("OK", "WARNING", "CRITICAL")
        assert "checks" in result
        assert "generated_at" in result

    def test_all_check_keys_present(self):
        import health_check
        result = health_check.run_all_checks()
        expected_keys = {"scan_freshness", "journal", "circuit_breakers",
                         "log_sizes", "fill_analysis"}
        assert expected_keys.issubset(result["checks"].keys())

    def test_check_scan_freshness_missing_file(self, tmp_path, monkeypatch):
        import health_check
        # Point ROOT to a tmp dir with no health.json
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        (tmp_path / "public" / "data").mkdir(parents=True)
        code, msg = health_check._check_scan_freshness()
        assert code == health_check._WARN

    def test_check_scan_freshness_fresh(self, tmp_path, monkeypatch):
        import health_check
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        (tmp_path / "public" / "data").mkdir(parents=True)
        data = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        (tmp_path / "public" / "data" / "health.json").write_text(json.dumps(data))
        code, msg = health_check._check_scan_freshness()
        assert code == health_check._OK

    def test_check_scan_freshness_stale(self, tmp_path, monkeypatch):
        import health_check
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        (tmp_path / "public" / "data").mkdir(parents=True)
        stale_ts = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)
        ).isoformat(timespec="seconds")
        data = {"generated_at": stale_ts}
        (tmp_path / "public" / "data" / "health.json").write_text(json.dumps(data))
        code, msg = health_check._check_scan_freshness()
        assert code == health_check._CRIT

    def test_check_journal_missing(self, tmp_path, monkeypatch):
        import health_check
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        (tmp_path / "journal").mkdir()
        code, msg = health_check._check_journal()
        assert code == health_check._WARN

    def test_check_journal_ok(self, tmp_path, monkeypatch):
        import health_check
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        (tmp_path / "journal").mkdir()
        j = {"open": [{"symbol": "BTC"}], "closed": []}
        (tmp_path / "journal" / "scalp_journal.json").write_text(json.dumps(j))
        code, msg = health_check._check_journal()
        assert code == health_check._OK

    def test_overall_status_worst_wins(self, tmp_path, monkeypatch):
        import health_check
        # Check that if one check is CRITICAL, overall is CRITICAL
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        (tmp_path / "public" / "data").mkdir(parents=True)
        (tmp_path / "journal").mkdir()
        # Stale health.json → CRITICAL
        stale_ts = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)
        ).isoformat(timespec="seconds")
        (tmp_path / "public" / "data" / "health.json").write_text(
            json.dumps({"generated_at": stale_ts})
        )
        result = health_check.run_all_checks()
        assert result["code"] == health_check._CRIT
        assert result["status"] == "CRITICAL"

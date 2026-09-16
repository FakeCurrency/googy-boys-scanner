"""Tests for alert_router (the expectancy + health_check halves went with the
AI BOT page / scalp risk stack on 2026-09-17)."""

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))


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
        assert "email"    in channels
        # discord removed 2026-08-27 (owner ruling)
        assert "discord" not in channels

    def test_warning_events_exclude_email(self):
        from scanner.broker.alert_router import get_channels
        channels = get_channels("anomaly")
        assert "telegram" in channels
        assert "email" not in channels
        assert "discord" not in channels

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

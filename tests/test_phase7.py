"""Tests for Phase 7 modules: alert_router, expectancy, health_check."""

import datetime as dt
import json
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Snapshot of the live circuit-breaker state, taken at IMPORT — before any test
# in this module has had a chance to write it. See the pin in TestHealthCheck.
_LIVE_ALERT_STATE = ROOT / "journal" / "alert_state.json"
_ALERT_STATE_AT_IMPORT = (
    _LIVE_ALERT_STATE.read_bytes() if _LIVE_ALERT_STATE.exists() else None
)
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
    # THESE TWO USED TO WRITE THE LIVE STATE FILE (fixed 2026-08-07).
    #
    # `run_all_checks` → `_check_circuit_breakers` resolves the journal off
    # health_check's OWN module-global ROOT (health_check.py:90), so an
    # unpatched call read the real journal/scalp_journal.json, evaluated the
    # breakers against the real trade history, and wrote the result straight
    # through to journal/alert_state.json — flipping consecutive_losses and
    # drawdown to true on every `pytest -q`. CLAUDE.md's "run
    # `git checkout -- journal/alert_state.json`" rule exists because of this.
    #
    # Worse than the file churn: check_all runs with notify=True by default and
    # these tests took no stub, so on any machine with DISCORD_WEBHOOK_URL
    # exported the suite fired a real circuit-breaker alert into #alerts. Inert
    # in CI only because CI has no credentials — which is luck, not isolation.
    #
    # test_circuit_breaker.py has had a correct `isolated_state` fixture all
    # along; it is module-local to that file and these live in this one.
    # test_overall_status_worst_wins below always patched ROOT and was clean,
    # which is the proof these two simply forgot.
    @pytest.fixture(autouse=True)
    def _isolate_root(self, tmp_path, monkeypatch):
        """Point health_check at an empty tree for every test in this class."""
        import health_check
        monkeypatch.setattr(health_check, "ROOT", tmp_path)
        # Deliberately creates NOTHING. Several tests below build their own
        # tree with a bare mkdir(), which raises if the fixture got there
        # first — and health_check handles a missing tree by design (every
        # _check_* returns early on a file that is not there), which is
        # exactly the state these two want anyway.
        return tmp_path

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

    def test_the_suite_does_not_write_the_live_alert_state(self):
        """The regression pin — and it has to be ORDER-PROOF.

        The obvious version (read the file, run, read it again) is worthless
        here and I proved that by mutation: with the fixture disabled the leak
        came straight back and this test still passed, because an earlier test
        in the class had already flipped both breakers to true and a saturated
        file does not change again. Comparing against a snapshot taken at
        MODULE IMPORT, before any test in this file has run, catches a write by
        any test rather than only the last one.

        Watches the REAL path deliberately: the failure being pinned is that
        the real file gets written, so a test watching tmp_path would pass
        while the bug reoccurred.

        Known limit, stated rather than hidden: if the file is already dirty
        when pytest starts, this compares dirty-to-dirty and cannot fire. CI
        always starts from a clean checkout, and the structural pin below does
        not depend on file state at all.
        """
        import health_check
        from scanner.broker import alert_router

        assert alert_router.STATE_FILE == _LIVE_ALERT_STATE, (
            "alert_router no longer writes journal/alert_state.json — this pin "
            "is watching the wrong path and is now worthless"
        )
        health_check.run_all_checks()
        now = _LIVE_ALERT_STATE.read_bytes() if _LIVE_ALERT_STATE.exists() else None
        assert now == _ALERT_STATE_AT_IMPORT, (
            "pytest has written journal/alert_state.json. A test run is mutating "
            "live circuit-breaker state — and that path also calls alert_dispatch, "
            "so on a machine with DISCORD_WEBHOOK_URL set it fires a real alert."
        )

    def test_health_check_isolation_is_autouse(self):
        """Structural half of the pin — immune to ordering and to saturation.

        This is the assertion the behavioural test above cannot make. Turning
        the fixture off is the exact regression, and it is visible in the
        fixture's own metadata without running anything.
        """
        fx = TestHealthCheck._isolate_root
        # pytest 8 exposes the marker as `_fixture_function_marker` on a
        # FixtureFunctionDefinition; older versions hung `_pytestfixturefunction`
        # on the raw function. Accept either so a pytest bump does not silently
        # turn this pin into a no-op.
        mark = getattr(fx, "_fixture_function_marker", None) or \
            getattr(fx, "_pytestfixturefunction", None)
        assert mark is not None, (
            "_isolate_root is no longer a fixture, or pytest moved the marker "
            "again — this pin cannot see autouse and must be updated"
        )
        assert mark.autouse is True, (
            "TestHealthCheck._isolate_root is no longer autouse — health_check "
            "will resolve ROOT to the real repo and write journal/alert_state.json"
        )
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

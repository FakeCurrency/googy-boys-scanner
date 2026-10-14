"""The alert blackout — Tier 0 of TOP100.md (2026-07-28).

Every test in here pins a case where the system HAD the information and failed
to tell anybody. That is a distinct class of bug from a wrong number, and it
outranks one: a wrong number with a working alarm gets caught, while a right
number with a dead alarm teaches you to trust the silence.

The findings these lock down:
  #4  the rate-limit window was spent before delivery, so a send that reached
      nobody suppressed the NEXT one — the real one — for the full interval
  #5  "nobody was told" was logged at DEBUG, below the default level
  #6  the book's loss guard bypassed the router entirely
  #8  the staleness probe read a file its own pipeline re-stamps
  #10 orphan alerts were unrouted and re-fired every single reconcile
  #11 a corrupt journal was parked silently and the run went green
  #12 two modules did read-modify-write on one state file

Nothing here touches which trades get taken.
"""

import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.risk


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Point the router at a temp alert_state.json. (The circuit-breaker
    co-writer and the orphan-position sweep went with the scalp bot, 2026-09-17.)"""
    from scanner.broker import alert_router as ar
    f = tmp_path / "alert_state.json"
    monkeypatch.setattr(ar, "STATE_FILE", f)
    return f


# ── #4: the window is spent on delivery, not on the attempt ───────────────────

class TestRateLimitWindowIsSpentOnDelivery:
    def test_dry_check_does_not_stamp(self, state):
        from scanner.broker import alert_router as ar
        assert ar.should_send("anomaly", commit=False) is True
        assert not state.exists() or "anomaly" not in json.loads(
            state.read_text()).get("last_sent", {})
        # ...and asking again still says yes, because nothing was spent.
        assert ar.should_send("anomaly", commit=False) is True

    def test_committing_check_stamps_and_then_blocks(self, state):
        from scanner.broker import alert_router as ar
        assert ar.should_send("anomaly") is True
        assert ar.should_send("anomaly") is False

    def test_mark_sent_alone_opens_the_window(self, state):
        from scanner.broker import alert_router as ar
        ar.mark_sent("anomaly")
        assert ar.should_send("anomaly", commit=False) is False

    def test_a_send_that_reaches_nobody_does_not_suppress_the_next_one(
            self, state, monkeypatch):
        """THE failure this split exists for.

        A webhook 500s, or a workflow forgot to export the secret. Under the old
        stamp-first ordering that dead send burned the window, so the retry a
        minute later — carrying the same unheard news — was silently dropped.
        """
        from scanner.broker import alert_router as ar
        monkeypatch.setattr(ar._cfg, "ALERT_RATE_LIMITS", {"anomaly": 3600})
        monkeypatch.setattr("scanner.broker.alert_dispatch._telegram",
                            lambda *_: False)
        monkeypatch.setattr("scanner.broker.alert_dispatch._email",
                            lambda *_: False)
        ar.smart_send("anomaly", "nobody is listening")
        assert ar.should_send("anomaly", commit=False) is True

    def test_a_send_that_lands_does_spend_the_window(self, state, monkeypatch):
        from scanner.broker import alert_router as ar
        monkeypatch.setattr(ar._cfg, "ALERT_RATE_LIMITS", {"anomaly": 3600})
        monkeypatch.setattr("scanner.broker.alert_dispatch._telegram",
                            lambda *_: True)
        monkeypatch.setattr("scanner.broker.alert_dispatch._email",
                            lambda *_: False)
        ar.smart_send("anomaly", "somebody is listening")
        assert ar.should_send("anomaly", commit=False) is False


# ── #5: silence is reported at a level somebody reads ─────────────────────────

class TestSilenceIsLoud:
    def test_router_warns_when_no_channel_accepts(self, state, monkeypatch, caplog):
        from scanner.broker import alert_router as ar
        for ch in ("_telegram", "_email"):
            monkeypatch.setattr(f"scanner.broker.alert_dispatch.{ch}",
                                lambda *_: False)
        with caplog.at_level("WARNING"):
            ar.smart_send("kill_switch", "the account is being flattened")
        assert "NOBODY WAS TOLD" in caplog.text
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_dispatch_warns_when_no_channel_is_configured(self, monkeypatch, caplog):
        from scanner.broker import alert_dispatch as ad
        for ch in ("_telegram", "_email"):
            monkeypatch.setattr(ad, ch, lambda *_: False)
        with caplog.at_level("WARNING"):
            ad.send("kill_switch", "fired")
        assert any(r.levelname == "WARNING" for r in caplog.records)


# ── severity tables: config is the one table, and every key is live ──────────

_EMITTER_CALLS = {"send", "smart_send", "_alert", "_smart"}


def _emitted_event_types() -> set[str]:
    """Every string literal passed as the event type to an alert sender
    anywhere under scanner/ or scripts/ (AST, so comments and docstrings
    cannot count as an emitter)."""
    import ast
    seen: set[str] = set()
    for base in ("scanner", "scripts"):
        for f in (ROOT / base).rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and node.args):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                arg = node.args[0]
                if name in _EMITTER_CALLS and isinstance(arg, ast.Constant) \
                        and isinstance(arg.value, str):
                    seen.add(arg.value)
    return seen


class TestRoutingTablesAreLive:
    """REFINE200 #90 (2026-10-14). The router used to keep hand-mirrored
    "fallback" copies of these tables for a config that failed to import; config
    is imported unconditionally, so the copies were never read and only drifted.
    And nine scalp-era event types (daily_loss, order_failed, circuit_breaker,
    orphan_position, ...) sat in the tables with nothing left to emit them."""

    def test_the_router_reads_config_and_keeps_no_copy(self):
        from scanner.broker import alert_router as ar
        for name in ("_SEV_MAP", "_RATE_MAP", "_CHAN_MAP"):
            assert not hasattr(ar, name), f"alert_router.{name} is back"

    def test_every_routed_event_type_has_an_emitter(self):
        from scanner import config
        from scanner.broker.alert_dispatch import _EMOJI
        emitted = _emitted_event_types()
        assert {"kill_switch", "scan_error", "vivek_guard"} <= emitted  # the scan works
        tables = {"ALERT_SEVERITY": set(config.ALERT_SEVERITY),
                  "ALERT_RATE_LIMITS": set(config.ALERT_RATE_LIMITS) - {"DEFAULT"},
                  "alert_dispatch._EMOJI": set(_EMOJI)}
        for table, keys in tables.items():
            orphans = sorted(keys - emitted)
            assert not orphans, f"{table} routes event types nothing emits: {orphans}"

    def test_an_unknown_severity_routes_like_warning(self):
        from scanner import config
        from scanner.broker import alert_router as ar
        assert ar.get_channels("anomaly", severity="NO_SUCH_TIER") == \
            config.ALERT_CHANNELS["WARNING"]

    def test_the_guard_event_is_registered_everywhere(self):
        from scanner import config
        from scanner.broker import alert_router as ar
        from scanner.broker.alert_dispatch import _EMOJI
        assert config.ALERT_SEVERITY["vivek_guard"] == "CRITICAL"
        assert ar.get_severity("vivek_guard") == "CRITICAL"
        assert config.ALERT_RATE_LIMITS["vivek_guard"] == 0
        assert "vivek_guard" in _EMOJI


# ── #12: one file, one writer ─────────────────────────────────────────────────

class TestBookStalenessReadsCanonicalFiles:
    NOW = dt.datetime(2026, 7, 20, 12, 0, tzinfo=dt.timezone.utc)

    def _iso(self, hours_ago):
        return (self.NOW - dt.timedelta(hours=hours_ago)).isoformat(
            timespec="seconds")

    def _books(self, root, combined_h, canonical_h):
        from scanner import config
        (root / "journal").mkdir(parents=True, exist_ok=True)
        (root / "journal" / "vivek_bot_book.json").write_text(
            json.dumps({"open": [], "closed": [],
                        "updated_at": self._iso(combined_h)}), encoding="utf-8")
        if canonical_h is not None:
            for m in config.MARKETS:
                (root / "journal" / f"vivek_bot_book.{m}.json").write_text(
                    json.dumps({"open": [], "closed": [],
                                "updated_at": self._iso(canonical_h)}),
                    encoding="utf-8")

    def _keys(self, root):
        from scanner import watchdog as wd
        return {f["key"] for f in wd.probe_content(root, self.NOW)}

    def test_a_fresh_rebuild_over_stale_data_no_longer_reads_as_healthy(
            self, tmp_path):
        """`--rebuild-combined` stamps the derived file with the wall clock of
        the rebuild. The old probe read that stamp, so the pipeline satisfied
        its own staleness check — a monitor reporting health it never
        measured."""
        self._books(tmp_path, combined_h=0.1, canonical_h=48.0)
        assert "book_stale" in self._keys(tmp_path)

    def test_it_also_names_the_rebuild_that_was_hiding_it(self, tmp_path):
        self._books(tmp_path, combined_h=0.1, canonical_h=48.0)
        assert "book_combined_ahead" in self._keys(tmp_path)

    def test_a_real_run_is_silent(self, tmp_path):
        self._books(tmp_path, combined_h=1.0, canonical_h=1.0)
        keys = self._keys(tmp_path)
        assert "book_stale" not in keys and "book_combined_ahead" not in keys

    def test_freshest_market_wins_so_a_crypto_only_weekend_is_not_stale(
            self, tmp_path):
        from scanner import config
        (tmp_path / "journal").mkdir(parents=True)
        (tmp_path / "journal" / "vivek_bot_book.json").write_text(
            json.dumps({"updated_at": self._iso(1.0)}), encoding="utf-8")
        for m in config.MARKETS:
            (tmp_path / "journal" / f"vivek_bot_book.{m}.json").write_text(
                json.dumps({"updated_at": self._iso(
                    1.0 if m == "crypto" else 60.0)}), encoding="utf-8")
        assert "book_stale" not in self._keys(tmp_path)

    def test_a_combined_book_with_nothing_behind_it_is_critical(self, tmp_path):
        self._books(tmp_path, combined_h=0.1, canonical_h=None)
        assert "book_canonical_missing" in self._keys(tmp_path)


# ── #10: orphans are routed, and deduped on the set rather than a clock ────────

class TestCorruptJournalAlerts:
    def test_it_alerts_and_still_recovers(self, tmp_path, monkeypatch):
        from scanner import vivek_journal as vj
        f = tmp_path / "vivek_journal.json"
        f.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(vj, "JOURNAL_FILE", f)
        sent = []
        monkeypatch.setattr("scanner.broker.alert_router.smart_send",
                            lambda *a, **k: sent.append(a))
        j = vj._load()
        assert j["open"] == [] and j["closed"] == []          # still recovers
        assert len(sent) == 1 and sent[0][0] == "scan_error"  # and says so
        assert f.with_suffix(".corrupt.json").exists()        # and parks it

    def test_a_healthy_journal_is_quiet(self, tmp_path, monkeypatch):
        from scanner import vivek_journal as vj
        f = tmp_path / "vivek_journal.json"
        f.write_text(json.dumps({"open": [], "closed": []}), encoding="utf-8")
        monkeypatch.setattr(vj, "JOURNAL_FILE", f)
        sent = []
        monkeypatch.setattr("scanner.broker.alert_router.smart_send",
                            lambda *a, **k: sent.append(a))
        vj._load()
        assert sent == []


# ── #7: a fired kill switch leaves a trace outside the log ────────────────────

class TestKillSwitchStepSummary:
    def test_a_trigger_is_written_to_the_run_page(self, tmp_path, monkeypatch):
        from scanner.broker import kill_switch as ks
        f = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
        ks._write_step_summary({"triggered": ["asx"], "checked": ["asx", "crypto"]},
                               dry_run=False)
        text = f.read_text()
        assert "KILL SWITCH TRIGGERED" in text and "asx" in text
        # It must say the paper book was NOT changed — the next scan is governed
        # by vivek_guard, not by this run, and reading it otherwise is worse
        # than reading nothing.
        assert "PAPER BOOK IS UNCHANGED" in text

    def test_a_clean_check_says_so_rather_than_nothing(self, tmp_path, monkeypatch):
        from scanner.broker import kill_switch as ks
        f = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
        ks._write_step_summary({"triggered": [], "checked": ["asx"]}, dry_run=False)
        assert "OK" in f.read_text()

    def test_no_summary_env_is_not_an_error(self, monkeypatch):
        from scanner.broker import kill_switch as ks
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        ks._write_step_summary({"triggered": ["asx"], "checked": ["asx"]}, False)

"""CLI entrypoint coverage for kill_switch.py and watchdog.py (2026-08-20).

Both modules had well-tested internals (run_standalone / run) and ZERO
coverage of the argparse surface the workflows actually invoke — the layer
where a renamed flag, a bad default or a lost exit code ships silently and
is discovered by the half-hourly cron that can flatten a live broker
account. Pattern: tests/test_vivek_run.py's CLI class — drive the REAL
main() with real argv, stub only the boundary underneath it.

kill_switch.main() was extracted from the bare ``__main__`` block for
exactly this purpose (body verbatim; behaviour pinned here).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from scanner import watchdog
from scanner.broker import kill_switch as ks

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── kill_switch CLI ──────────────────────────────────────────────────────────

class TestKillSwitchCLI:
    def _stub(self, monkeypatch, result=None):
        calls = {}

        def fake_standalone(dry_run=False):
            calls["dry_run"] = dry_run
            return result if result is not None else {"triggered": [], "checked": ["asx"]}

        def fake_summary(res, dry):
            calls["summary"] = (res, dry)

        monkeypatch.setattr(ks, "run_standalone", fake_standalone)
        monkeypatch.setattr(ks, "_write_step_summary", fake_summary)
        return calls

    def test_bare_invocation_is_a_LIVE_check(self, monkeypatch):
        calls = self._stub(monkeypatch)
        assert ks.main([]) == 0
        assert calls["dry_run"] is False, "no flag means the real, flattening check"

    def test_dry_run_flag_reaches_run_standalone_and_the_summary(self, monkeypatch):
        calls = self._stub(monkeypatch)
        assert ks.main(["--dry-run"]) == 0
        assert calls["dry_run"] is True
        assert calls["summary"][1] is True, "the summary must say dry so a fired dry-run reads as one"

    def test_an_unknown_flag_exits_2_like_any_argparse_cli(self, monkeypatch):
        self._stub(monkeypatch)
        with pytest.raises(SystemExit) as e:
            ks.main(["--flatten-everything"])
        assert e.value.code == 2

    def test_a_FIRED_switch_stays_a_green_run_with_the_error_annotation(self, monkeypatch, capsys):
        # The doctrine _write_step_summary documents: firing is the safety net
        # WORKING. A red run here would train the eye to ignore red on the one
        # workflow where red must mean something. Exit 0 + ::error:: is the
        # contract kill_switch.yml relies on; this is the pin.
        self._stub(monkeypatch, result={"triggered": ["asx", "crypto"], "checked": ["asx", "crypto"]})
        rc = ks.main([])
        out = capsys.readouterr().out
        assert rc == 0, "a fired switch must NOT turn the job red"
        assert "::error::KILL SWITCH TRIGGERED for: asx, crypto" in out

    def test_a_quiet_check_prints_no_error_annotation(self, monkeypatch, capsys):
        self._stub(monkeypatch)
        ks.main([])
        assert "::error::" not in capsys.readouterr().out

    def test_the_summary_is_written_from_the_result_the_check_returned(self, monkeypatch):
        res = {"triggered": ["nasdaq"], "checked": ["nasdaq"]}
        calls = self._stub(monkeypatch, result=res)
        ks.main(["--dry-run"])
        assert calls["summary"][0] is res, "the summary must describe THIS run's result object"

    def test_step_summary_writes_the_dry_run_wording(self, monkeypatch, tmp_path):
        # One layer deeper, unstubbed: the real _write_step_summary against a
        # real GITHUB_STEP_SUMMARY file, both branches.
        p = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(p))
        ks._write_step_summary({"triggered": ["asx"], "checked": ["asx"], "flattened": []}, dry_run=True)
        text = p.read_text(encoding="utf-8")
        assert "KILL SWITCH TRIGGERED" in text and "Dry run - nothing was flattened." in text
        ks._write_step_summary({"triggered": [], "checked": ["asx"]}, dry_run=False)
        assert "Kill switch OK" in p.read_text(encoding="utf-8")

    def test_module_still_runs_as_python_dash_m(self):
        src = (ROOT / "scanner" / "broker" / "kill_switch.py").read_text(encoding="utf-8")
        assert re.search(r'if __name__ == "__main__":\s*\n\s*raise SystemExit\(main\(\)\)', src), \
            "kill_switch.yml invokes `python -m scanner.broker.kill_switch` - the guard must stay"

    def test_the_workflow_still_invokes_both_forms(self):
        wf = (ROOT / ".github" / "workflows" / "kill_switch.yml").read_text(encoding="utf-8")
        assert "python -m scanner.broker.kill_switch --dry-run" in wf
        assert re.search(r"python -m scanner\.broker\.kill_switch\s*$", wf, re.M), \
            "the live (non-dry) invocation disappeared from the workflow"


# ── watchdog CLI ─────────────────────────────────────────────────────────────

class TestWatchdogCLI:
    def _stub(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(watchdog, "run", lambda dry_run=False: calls.setdefault("run", dry_run))
        monkeypatch.setattr(watchdog, "test_alert", lambda: calls.setdefault("test_alert", True))
        return calls

    def test_bare_invocation_is_the_real_probe(self, monkeypatch):
        calls = self._stub(monkeypatch)
        watchdog.main([])
        assert calls == {"run": False}

    def test_dry_run_probes_without_alerting(self, monkeypatch):
        calls = self._stub(monkeypatch)
        watchdog.main(["--dry-run"])
        assert calls == {"run": True}

    def test_test_alert_routes_to_the_self_test_and_NEVER_to_run(self, monkeypatch):
        # test_alerts.yml's whole point: force one message through every
        # channel WITHOUT running the real probe (which would mix genuine
        # staleness state into a delivery test).
        calls = self._stub(monkeypatch)
        watchdog.main(["--test-alert"])
        assert calls == {"test_alert": True}, f"run() must not fire on a self-test: {calls}"

    def test_an_unknown_flag_exits_2(self, monkeypatch):
        self._stub(monkeypatch)
        with pytest.raises(SystemExit) as e:
            watchdog.main(["--probe-harder"])
        assert e.value.code == 2

    def test_the_workflows_still_invoke_the_cli_they_always_did(self):
        kill = (ROOT / ".github" / "workflows" / "kill_switch.yml").read_text(encoding="utf-8")
        alerts = (ROOT / ".github" / "workflows" / "test_alerts.yml").read_text(encoding="utf-8")
        assert "python -m scanner.watchdog" in kill
        assert "python -m scanner.watchdog --test-alert" in alerts

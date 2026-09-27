"""scanner.vps -- the JOBS table, gates, locks, ledger, spool and runner order.

deploy/DESIGN.md section 8: the JOBS table covers exactly the 14 VPS
workflows; every step's module imports / script exists; every dropped
Actions-only step is recorded with a reason; gates (windows, DST, weekend,
close-slot no-upper-bound, backstop post-close rule, crypto/backup/ledger
backstops, manual bypass, probe fail-open); ``.scan-skipped`` deleted at job
start; operator-only args dropped by the drainer; the spool matrix; ledger
atomicity + multi-field semantics; lock ordering; HALT refusal for book writers.

Every step subprocess is replaced by a fake argv runner, so the suite runs in
seconds and never touches the real journal/ or public/data (VIVEK_HOME points
at a temp dir).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import pytest

from scanner import config
from scanner.vps import __main__ as cli
from scanner.vps import gate as G
from scanner.vps import jobs as J
from scanner.vps import ledger as LG
from scanner.vps import locks as L
from scanner.vps import notify as N
from scanner.vps import spool as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc

EXPECTED_JOBS = {
    "scan.yml", "crypto_bot.yml", "kill_switch.yml", "phasemap.yml", "confluence.yml",
    "reco_note.yml", "backup_book.yml", "alert_returns.yml", "evidence_brief.yml",
    "lens_backtest.yml", "vivek_backtest.yml", "morning_plays.yml", "momentum.yml",
    "close_position.yml",
}


def _at(tz: str, y, mo, d, h, mi) -> dt.datetime:
    """A wall-clock instant in ``tz`` as an aware UTC datetime."""
    return dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).astimezone(UTC)


# ── fixtures ─────────────────────────────────────────────────────────────────

class FakeExec:
    """Records every step invocation; scripted results by argv predicate."""

    def __init__(self):
        self.calls: list[dict] = []
        self.rules: list[tuple] = []           # (predicate, result_or_callable)

    def when(self, pred, result):
        self.rules.append((pred, result))
        return self

    def __call__(self, argv, *, cwd, env, stdin=None, timeout=None, stream=True):
        call = {"argv": list(argv), "cwd": cwd, "env": dict(env), "stdin": stdin, "timeout": timeout}
        self.calls.append(call)
        for pred, result in self.rules:
            if pred(call["argv"]):
                res = result(call) if callable(result) else result
                return res
        return cli.Exec(0, "ok")

    def argvs(self):
        return [c["argv"] for c in self.calls]

    def find(self, *needles):
        return [c for c in self.calls if all(any(n in tok for tok in c["argv"]) for n in needles)]


class FakeRun:
    """A stand-in for subprocess.run used by the gates (git rev-parse etc.)."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.handlers: list[tuple] = []

    def when(self, pred, handler):
        self.handlers.append((pred, handler))
        return self

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        for pred, handler in self.handlers:
            if pred(list(argv)):
                return handler(list(argv), kw)
        return subprocess.CompletedProcess(argv, 0, "", "")


@pytest.fixture
def rt(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "public" / "data").mkdir(parents=True)
    (home / "journal").mkdir()
    (home / "backups").mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("VIVEK_HOME", str(home))
    monkeypatch.setenv("VIVEK_STATE_DIR", str(state))
    monkeypatch.setenv("VIVEK_PUBLISH", str(tmp_path / "publish"))
    monkeypatch.setenv("VIVEK_GIT_PUBLISH", "0")          # no git in these tests
    for k in list(os.environ):
        if k.startswith(cli.SECRET_PREFIXES):
            monkeypatch.delenv(k, raising=False)
    fake = FakeExec()
    run = FakeRun()
    clock = {"t": 1000.0}
    runtime = cli.Runtime(home=home, publish=tmp_path / "publish", state=state, python="PY",
                          ledger_file=state / "runs.json", exec_fn=fake, run=run,
                          now=lambda: dt.datetime(2026, 9, 29, 1, 0, tzinfo=UTC),
                          sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
                          clock=lambda: clock["t"], notify=lambda *a: [], host="test")
    runtime.fake, runtime.fake_run, runtime.clock_state = fake, run, clock
    return runtime


def _write(path: pathlib.Path, doc) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ── the JOBS table ────────────────────────────────────────────────────────────

def test_the_table_covers_exactly_the_14_vps_workflows():
    assert set(J.JOBS) == EXPECTED_JOBS
    for name in EXPECTED_JOBS:
        assert (ROOT / ".github" / "workflows" / name).exists(), name
    assert set(J.book_writers()) == set(config.VPS_BOOK_WRITER_JOBS)
    assert set(config.VPS_WORKFLOWS_TO_DISABLE) - {"dispatch_scan.yml"} == EXPECTED_JOBS


def _argvs_of(job: J.Job):
    for step in job.steps:
        if step.kind in ("cmd", "markets", "brief", "morning_plays", "momentum_screen"):
            yield step.argv
        for c in step.cmds:
            yield c["argv"]


def test_every_module_step_imports_and_every_script_exists():
    seen_modules, seen_scripts = set(), set()
    for job in J.JOBS.values():
        for argv in _argvs_of(job):
            argv = list(argv)
            if "-m" in argv:
                mod = argv[argv.index("-m") + 1]
                assert importlib.util.find_spec(mod) is not None, (job.name, mod)
                seen_modules.add(mod)
            elif len(argv) > 1 and argv[1].startswith("scripts/"):
                assert (ROOT / argv[1]).exists(), (job.name, argv[1])
                seen_scripts.add(argv[1])
    # the kinds that build their argv in code
    for mod in ("scanner.broker.vivek_run", "scanner.journal", "scanner.momentum.run"):
        assert importlib.util.find_spec(mod) is not None
    assert {"scanner.run", "scanner.watchdog", "scanner.broker.kill_switch", "phasemap.run",
            "scanner.spec_run", "scanner.confluence_alert", "phasemap.backtest",
            "scanner.vivek_backtest"} <= seen_modules
    assert {"scripts/reco_note.py", "scripts/backup_journal.py", "scripts/evidence_brief.py",
            "scripts/morning_plays.py"} <= seen_scripts


def test_the_inline_schema_gates_compile():
    for job in J.JOBS.values():
        for step in job.steps:
            if step.stdin:
                compile(step.stdin, f"{job.name}:{step.name}", "exec")
                assert step.argv[-1] == "-", "a stdin script runs as `python -`"


def test_every_dropped_actions_step_carries_a_reason():
    for job in J.JOBS.values():
        assert job.dropped, f"{job.name}: at least checkout is Actions-only"
        for entry in job.dropped:
            assert len(entry) == 2 and entry[0].strip() and len(entry[1].strip()) > 15, (job.name, entry)
        names = " ".join(e[0] for e in job.dropped)
        assert "checkout" in names, job.name
        if job.publish:
            assert "github-actions[bot]" in names, f"{job.name}: the identity swap must be recorded"
    close = J.JOBS["close_position.yml"]
    assert any("redispatch" in e[0] for e in close.dropped)


def test_the_transcription_keeps_the_workflows_shape():
    scan = J.JOBS["scan.yml"]
    kinds = [s.kind for s in scan.steps]
    names = [s.name for s in scan.steps]
    assert kinds == ["cmd", "cmd", "markets", "cmd", "cmd", "cmd", "publish"]
    assert "market-cap" in names[0] and "sector" in names[1]
    assert scan.steps[0].continue_on_error and scan.steps[1].continue_on_error
    assert scan.steps[5].continue_on_error, "confluence_alert never blocks the scan"
    assert scan.steps[2].order_all == ("nasdaq", "crypto", "asx")
    assert scan.steps[2].require_ok == ("asx", "nasdaq")
    assert scan.steps[2].parallel == (), "scan.yml is strictly sequential"
    assert scan.publish.rebuild_combined is True
    assert scan.publish.message == "data: scan {utc} UTC"
    assert len(scan.publish.paths) == 15 and len(scan.publish.paths_per_market) == 6
    assert scan.publish.paths[-1] == "data/history"
    pm = J.JOBS["phasemap.yml"]
    assert pm.steps[0].parallel == ("nasdaq", "crypto") and pm.steps[0].require_ok == ("asx", "nasdaq")
    assert pm.steps[1].sets_flag == "specs_ok" and pm.steps[1].continue_on_error
    assert pm.publish.must_change["policy"] == "collect"
    lb = J.JOBS["lens_backtest.yml"]
    assert [c["tag"] for c in lb.steps[0].cmds] == ["nasdaq", "crypto", "asx"]
    assert lb.steps[1].ignore_rc and lb.steps[2].continue_on_error
    vb = J.JOBS["vivek_backtest.yml"]
    assert [s.leg for s in vb.steps if s.kind == "publish"] == ["nasdaq", "asx", "crypto"]
    assert vb.steps[0].argv[-1] == "partial" and vb.steps[4].argv[-1] == "complete"
    cb = J.JOBS["crypto_bot.yml"]
    assert [s.kind for s in cb.steps] == ["cmd", "cmd", "cmd", "publish", "cmd"], \
        "the watchdog runs AFTER the publish, never after a failed one"
    assert cb.steps[-1].env_set == {"WATCHDOG_HOST": "crypto_bot"}
    ks = J.JOBS["kill_switch.yml"]
    assert set(ks.steps[0].env_pass) >= {"BYBIT_API_KEY", "ALPACA_API_KEY", "TELEGRAM_BOT_TOKEN"}
    assert "BYBIT_API_KEY" not in ks.steps[1].env_pass, "the watchdog step never sees broker keys"
    bb = J.JOBS["backup_book.yml"]
    assert bb.gate_mode == "steps" and not bb.steps[-1].gated, "verify runs even on a skipped backstop"


def test_lock_families_and_waits_match_the_design():
    fam = {n: j.family for n, j in J.JOBS.items()}
    assert {n for n, f in fam.items() if f == "scan"} == {"scan.yml", "crypto_bot.yml",
                                                         "close_position.yml", "confluence.yml"}
    assert {n for n, f in fam.items() if f == "heavy"} == {"phasemap.yml", "lens_backtest.yml",
                                                          "vivek_backtest.yml", "alert_returns.yml",
                                                          "momentum.yml"}
    for n in ("kill_switch.yml", "backup_book.yml", "reco_note.yml", "evidence_brief.yml"):
        assert fam[n] is None and J.JOBS[n].locks == (n[:-4],)
    assert J.JOBS["scan.yml"].locks == ("scan",), "own name == family: one flock, not two"
    assert J.JOBS["crypto_bot.yml"].locks == ("scan", "crypto_bot")
    assert J.JOBS["scan.yml"].lock_wait_s == config.VPS_LOCK_WAIT_S["scan"] == 7200
    assert J.JOBS["kill_switch.yml"].lock_wait_s == config.VPS_LOCK_WAIT_S["default"]
    assert J.JOBS["scan.yml"].timeout_s == 7200 and J.JOBS["lens_backtest.yml"].timeout_s == 350 * 60


def test_operator_only_args_are_dropped_by_the_drainer_and_kept_for_operators():
    scan = J.JOBS["scan.yml"]
    assert scan.operator_only_args == ("extra",)
    op = J.parse_args(scan, {"market": "asx", "extra": "--limit 3", "reason": "manual"})
    assert op["extra"] == "--limit 3"
    api = J.parse_args(scan, {"market": "asx", "extra": "--limit 3", "reason": "manual"}, operator=False)
    assert api["extra"] == ""
    with pytest.raises(J.ArgError):
        J.parse_args(scan, {"market": "asx", "bogus": "1"})
    with pytest.raises(J.ArgError):
        J.parse_args(scan, {"market": "nyse"})
    assert set(J.JOBS["momentum.yml"].operator_only_args) == {"mode", "window", "dry_run", "backtest"}
    assert set(J.JOBS["morning_plays.yml"].operator_only_args) == {"force", "dry_run"}


def test_reason_defaults_from_the_slot_the_timer_passes():
    scan = J.JOBS["scan.yml"]
    assert J.parse_args(scan, {"market": "asx", "slot": "hourly"})["reason"] == "cron"
    assert J.parse_args(scan, {"market": "asx"})["reason"] == "manual"
    assert J.is_scheduled(scan, {"reason": "cron", "slot": "manual"})
    assert not J.is_scheduled(scan, {"reason": "heartbeat", "slot": "manual"}), \
        "a heartbeat heal is a workflow_dispatch on Actions: the manual (soft) branch"
    cb = J.JOBS["crypto_bot.yml"]
    assert J.parse_args(cb, {"slot": "backstop"})["reason"] == "cron"
    assert J.parse_args(cb, {})["reason"] == "manual"
    assert J.is_scheduled(J.JOBS["phasemap.yml"], J.parse_args(J.JOBS["phasemap.yml"], {}))
    assert J.is_scheduled(J.JOBS["reco_note.yml"], {})
    assert not J.is_scheduled(J.JOBS["close_position.yml"], J.parse_args(
        J.JOBS["close_position.yml"], {"symbol": "abc", "market": "asx", "price": "1.5"}))


def test_close_args_are_typed_like_the_function_validator():
    close = J.JOBS["close_position.yml"]
    a = J.parse_args(close, {"symbol": "fph", "market": "asx", "price": "12.34"})
    assert a["symbol"] == "FPH" and a["direction"] == "long" and a["journal_type"] == "bot"
    for bad in ({"symbol": "F PH", "market": "asx", "price": "1"},
                {"symbol": "FPH", "market": "asx", "price": "0"},
                {"symbol": "FPH", "market": "asx", "price": "nan"},
                {"symbol": "FPH", "market": "asx", "price": "1", "exit_date": "26-09-01"},
                {"symbol": "FPH", "market": "lse", "price": "1"}):
        with pytest.raises(J.ArgError):
            J.parse_args(close, bad)


def test_data_roots_are_the_union_of_every_publish_path():
    roots = J.data_roots()
    assert "journal/vivek_bot_book.asx.json" in roots and "data/history" in roots
    assert "backups" in roots and "public/data/momentum/" not in roots
    assert any(r.startswith("public/data/momentum") for r in roots)
    assert "public/data/reco_note.json" in roots


def test_split_extra_word_splits_like_the_unquoted_ARGS():
    assert J.split_extra("--limit 12 --curated") == ["--limit", "12", "--curated"]
    assert J.split_extra("") == [] and J.split_extra(None) == []


# ── fences the new package must respect (mirrors the repo-wide grep tests) ───

def test_no_workflow_literal_leaks_into_the_python_of_scanner_vps():
    needles = ("alert_" + "returns", "alert_forward" + "_returns", "edge_" + "summary", "edge_" + "rosters",
               "book_" + "stress", "alert_edge" + "_report", "funnel_" + "history", "_arriv" + "ing",
               "spec_grad" + "uation", "DISCORD_WEBHOOK" + "_URL", "eod" + "hd", "25" + "y")
    for py in sorted((ROOT / "scanner" / "vps").glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for n in needles:
            assert n not in text, f"{py.name} names {n!r}: keep it in workflows.json"
        assert text.isascii(), f"{py.name}: scanner-side source stays ASCII"


def test_the_transcription_file_is_the_only_home_of_those_names():
    text = (ROOT / "scanner" / "vps" / "workflows.json").read_text(encoding="utf-8")
    assert '"alert_returns.yml"' in text and "data/history" in text and "backups" in text


# ── gates ─────────────────────────────────────────────────────────────────────

class TestScanGate:
    def test_hourly_inside_and_outside_the_window_in_both_dst_regimes(self, tmp_path):
        # AEST (July) and AEDT (December): 11:07 local is inside, 10:30 is not.
        for y, mo, d in ((2026, 7, 7), (2026, 12, 1)):
            assert G.scan_gate("asx", "hourly", now=_at("Australia/Sydney", y, mo, d, 11, 7), home=tmp_path)
            assert G.scan_gate("asx", "hourly", now=_at("Australia/Sydney", y, mo, d, 16, 45), home=tmp_path)
            assert not G.scan_gate("asx", "hourly", now=_at("Australia/Sydney", y, mo, d, 16, 46), home=tmp_path)
            assert not G.scan_gate("asx", "hourly", now=_at("Australia/Sydney", y, mo, d, 10, 30), home=tmp_path)
        for y, mo, d in ((2026, 7, 7), (2026, 12, 1)):      # EDT and EST
            assert G.scan_gate("nasdaq", "hourly", now=_at("America/New_York", y, mo, d, 10, 37), home=tmp_path)
            assert not G.scan_gate("nasdaq", "hourly", now=_at("America/New_York", y, mo, d, 10, 29), home=tmp_path)
        # the two windows never overlap in UTC: an ASX-hour instant is not a NASDAQ session
        assert not G.scan_gate("nasdaq", "hourly", now=_at("Australia/Sydney", 2026, 7, 7, 12, 0), home=tmp_path)

    def test_weekends_in_the_markets_own_calendar(self, tmp_path):
        assert not G.scan_gate("asx", "hourly", now=_at("Australia/Sydney", 2026, 9, 26, 12, 0), home=tmp_path)
        # the weekday is judged in Sydney: Monday 11:07 there is 00:07 UTC under
        # AEDT and 01:07 UTC under AEST -- both due, one UTC hour apart
        aedt = _at("Australia/Sydney", 2026, 12, 7, 11, 7)
        aest = _at("Australia/Sydney", 2026, 7, 6, 11, 7)
        assert (aedt.hour, aest.hour) == (0, 1)
        assert G.scan_gate("asx", "hourly", now=aedt, home=tmp_path)
        assert G.scan_gate("asx", "hourly", now=aest, home=tmp_path)
        # Saturday 00:07 UTC is Friday evening in New York: outside the window either way
        assert not G.scan_gate("nasdaq", "hourly", now=dt.datetime(2026, 12, 12, 0, 7, tzinfo=UTC), home=tmp_path)

    def test_manual_bypasses_everything_and_reaches_all(self, tmp_path):
        r = G.scan_gate("all", "manual", now=_at("Australia/Sydney", 2026, 9, 26, 3, 0), home=tmp_path)
        assert r.due and r.market == "all"
        assert not G.scan_gate("all", "hourly", now=_at("Australia/Sydney", 2026, 9, 29, 12, 0), home=tmp_path)

    def test_probe_failure_fails_open_to_all_with_a_warning(self, tmp_path, monkeypatch):
        def boom(tz, now):
            raise LookupError("no tz database")
        monkeypatch.setattr(G, "_local_now", boom)
        r = G.scan_gate("asx", "hourly", now=dt.datetime(2026, 9, 26, 3, tzinfo=UTC), home=tmp_path)
        assert r.due and r.market == "all" and "fail open" in (r.warning or "")

    @pytest.mark.parametrize("slot", ["close", "backstop"])
    def test_close_slot_runs_only_after_16_00_and_only_until_a_post_close_scan_lands(self, tmp_path, slot):
        home = tmp_path
        prices = home / "public" / "data" / "asx_prices.json"
        tue = (2026, 9, 29)
        assert not G.scan_gate("asx", slot, now=_at("Australia/Sydney", *tue, 15, 59), home=home)
        assert G.scan_gate("asx", slot, now=_at("Australia/Sydney", *tue, 16, 30), home=home), "no file: due"
        _write(prices, {"generated_at": _at("Australia/Sydney", *tue, 16, 7).isoformat()})
        assert G.scan_gate("asx", slot, now=_at("Australia/Sydney", *tue, 16, 30), home=home), \
            "the 16:07 hourly scan is NOT post-close (16:12)"
        _write(prices, {"generated_at": _at("Australia/Sydney", *tue, 16, 31).isoformat()})
        assert not G.scan_gate("asx", slot, now=_at("Australia/Sydney", *tue, 17, 15), home=home), \
            "a post-close scan landed: the backstop skips"
        # no upper bound: a reboot-late fire at 21:00 still runs when nothing landed
        _write(prices, {"generated_at": _at("Australia/Sydney", *tue, 16, 7).isoformat()})
        assert G.scan_gate("asx", slot, now=_at("Australia/Sydney", *tue, 21, 0), home=home)
        assert not G.scan_gate("asx", slot, now=_at("Australia/Sydney", 2026, 10, 3, 16, 30), home=home), "Saturday"
        _write(prices, {"generated_at": "garbage"})
        assert G.scan_gate("asx", slot, now=_at("Australia/Sydney", *tue, 16, 30), home=home), "unreadable: fail open"

    def test_the_close_rule_uses_the_digest_gate_times_from_config(self, tmp_path):
        # NASDAQ's post-close stamp is 16:05 New York (config.MORNING_PLAYS_SLOT_GATE['us'])
        tue = (2026, 9, 29)
        prices = tmp_path / "public" / "data" / "nasdaq_prices.json"
        _write(prices, {"generated_at": _at("America/New_York", *tue, 16, 4).isoformat()})
        assert G.scan_gate("nasdaq", "close", now=_at("America/New_York", *tue, 16, 7), home=tmp_path)
        _write(prices, {"generated_at": _at("America/New_York", *tue, 16, 5).isoformat()})
        assert not G.scan_gate("nasdaq", "close", now=_at("America/New_York", *tue, 16, 7), home=tmp_path)
        assert config.MORNING_PLAYS_SLOT_GATE["us"]["minute"] == 5


class TestOtherGates:
    def test_crypto_backstop_skips_only_when_the_local_scan_is_fresh(self, tmp_path):
        now = dt.datetime(2026, 9, 29, 1, 52, tzinfo=UTC)
        f = tmp_path / "public" / "data" / "crypto_vivek.json"
        assert G.crypto_gate("hourly", now=now, home=tmp_path).due
        assert G.crypto_gate("manual", now=now, home=tmp_path).due
        assert G.crypto_gate("backstop", now=now, home=tmp_path).due, "missing file: unknown -> run"
        _write(f, {"generated_at": (now - dt.timedelta(minutes=30)).isoformat()})
        r = G.crypto_gate("backstop", now=now, home=tmp_path)
        assert not r.due and "Backstop :52" in r.why
        _write(f, {"generated_at": (now - dt.timedelta(seconds=config.VPS_CRYPTO_BACKSTOP_FRESH_S)).isoformat()})
        assert G.crypto_gate("backstop", now=now, home=tmp_path).due, "exactly 3900 s is stale"
        _write(f, {"generated_at": "not a date"})
        assert G.crypto_gate("backstop", now=now, home=tmp_path).due

    def test_backup_backstop_skips_when_todays_snapshot_dir_exists(self, tmp_path):
        now = dt.datetime(2026, 9, 29, 23, 35, tzinfo=UTC)
        (tmp_path / "backups").mkdir()
        assert G.backup_gate("backstop", now=now, home=tmp_path).due
        (tmp_path / "backups" / "2026-09-28T21-35-10").mkdir()
        assert G.backup_gate("backstop", now=now, home=tmp_path).due, "yesterday's does not count"
        (tmp_path / "backups" / "2026-09-29T21-35-10").mkdir()
        assert not G.backup_gate("backstop", now=now, home=tmp_path).due
        assert G.backup_gate("primary", now=now, home=tmp_path).due

    def test_ledger_backstop_skips_only_on_a_scheduled_success_today(self, tmp_path):
        led = tmp_path / "runs.json"
        now = dt.datetime(2026, 9, 29, 23, 50, tzinfo=UTC)
        job = J.JOBS["alert_returns.yml"]
        assert G.ledger_today_gate(job.name, "backstop", job.scheduled_slots, now=now, ledger_file=led).due
        LG.record(job.name, status="failed", exit_code=1, args={"slot": "primary"}, started=now, ended=now, path=led)
        assert G.ledger_today_gate(job.name, "backstop", job.scheduled_slots, now=now, ledger_file=led).due, \
            "a failed 22:20 still needs the backstop"
        LG.record(job.name, status="ok", exit_code=0, args={"slot": "manual"}, started=now, ended=now, path=led)
        assert G.ledger_today_gate(job.name, "backstop", job.scheduled_slots, now=now, ledger_file=led).due, \
            "a manual run today does not suppress the backstop"
        LG.record(job.name, status="ok", exit_code=0, args={"slot": "primary"}, started=now, ended=now, path=led)
        assert not G.ledger_today_gate(job.name, "backstop", job.scheduled_slots, now=now, ledger_file=led).due
        tomorrow = now + dt.timedelta(days=1)
        assert G.ledger_today_gate(job.name, "backstop", job.scheduled_slots, now=tomorrow, ledger_file=led).due
        assert G.ledger_today_gate(job.name, "primary", job.scheduled_slots, now=now, ledger_file=led).due

    def test_momentum_gate_reads_main_via_git_and_lets_momentum_due_pick(self, tmp_path):
        state = tmp_path / "state"
        picks = {"market": "nasdaq"}

        def run(argv, **kw):
            if argv[:2] == ["git", "fetch"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[:2] == ["git", "show"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps({"generated_at": "2026-09-01T00:00:00Z"}), "")
            if argv[1].endswith("momentum_due.py"):
                assert argv[2] == "--dir" and pathlib.Path(argv[3]).exists()
                assert (pathlib.Path(argv[3]) / "asx.json").exists()
                out = kw["env"]["GITHUB_OUTPUT"]
                pathlib.Path(out).write_text(f"market={picks['market']}\n")
                return subprocess.CompletedProcess(argv, 0, f"picked: {picks['market'] or 'nothing due'}", "")
            raise AssertionError(argv)
        r = G.momentum_gate(None, home=tmp_path, state_dir=state, run=run, python="PY")
        assert r.due and r.market == "nasdaq"
        picks["market"] = ""
        assert not G.momentum_gate(None, home=tmp_path, state_dir=state, run=run, python="PY").due
        assert G.momentum_gate("asx", home=tmp_path, state_dir=state, run=run).market == "asx"
        assert not list((state / "tmp").glob("momentum-on-main-*")), "the temp dir is cleaned up"

    def test_a_crashing_momentum_gate_is_a_failure_not_a_skip(self, tmp_path):
        def run(argv, **kw):
            if argv[1:2] and str(argv[1]).endswith("momentum_due.py"):
                return subprocess.CompletedProcess(argv, 1, "", "ImportError")
            return subprocess.CompletedProcess(argv, 0, "{}", "")
        with pytest.raises(G.GateError):
            G.momentum_gate(None, home=tmp_path, state_dir=tmp_path / "s", run=run, python="PY")


# ── locks ─────────────────────────────────────────────────────────────────────

def test_locks_are_taken_in_order_repo_shared_then_family_then_own(tmp_path):
    ls = L.LockSet(tmp_path, J.JOBS["crypto_bot.yml"].locks)
    assert ls.names == ["repo", "scan", "crypto_bot"]
    assert ls.order[0].shared and not ls.order[1].shared
    waited = ls.acquire(5)
    assert waited < 1 and all(lk.held for lk in ls.order)
    # a second job on the same family cannot take it; repo shared is still fine
    other = L.Lock(L.lock_path(tmp_path, "scan"))
    assert not other.try_acquire()
    reader = L.Lock(L.lock_path(tmp_path, "repo"), shared=True)
    assert reader.try_acquire()
    reader.release()
    # update.sh's exclusive repo lock is refused while a job holds it shared
    excl = L.Lock(L.lock_path(tmp_path, "repo"))
    assert not excl.try_acquire()
    ls.release()
    assert excl.try_acquire()
    excl.release()


def test_lock_wait_is_its_own_budget_and_releases_everything_on_timeout(tmp_path):
    holder = L.Lock(L.lock_path(tmp_path, "scan"))
    assert holder.try_acquire()
    t = {"now": 0.0}
    ls = L.LockSet(tmp_path, ("scan", "confluence"))
    with pytest.raises(L.LockTimeout) as ei:
        ls.acquire(30, clock=lambda: t["now"], sleep=lambda s: t.__setitem__("now", t["now"] + s))
    assert ei.value.waited_s >= 30 and ei.value.name == "scan"
    assert not ls.order[0].held, "repo (taken first) was released on the timeout"
    holder.release()
    assert ls.acquire(1, clock=lambda: t["now"], sleep=lambda s: None) == 0
    ls.release()


def test_a_blocked_lock_is_reported_as_waited_seconds(tmp_path):
    holder = L.Lock(L.lock_path(tmp_path, "scan"))
    assert holder.try_acquire()
    threading.Timer(0.3, holder.release).start()
    ls = L.LockSet(tmp_path, ("scan",))
    waited = ls.acquire(10, poll_s=0.05)
    assert 0.2 <= waited < 5
    ls.release()


# ── ledger ────────────────────────────────────────────────────────────────────

def test_ledger_rows_keep_success_failure_and_skip_stamps_apart(tmp_path):
    led = tmp_path / "runs.json"
    t0 = dt.datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    LG.record("scan.yml", status="ok", exit_code=0, args={"market": "asx", "slot": "hourly"},
              started=t0, ended=t0 + dt.timedelta(minutes=40), waited_s=12.4, pushed="abc123",
              last_line="Pushed.", host="vps", path=led)
    row = LG.rows_for("scan.yml", led)
    assert row["last_status"] == "ok" and row["last_success_at"] == "2026-09-29T01:40:00Z"
    assert row["waited_s"] == 12 and row["pushed"] == "abc123" and row["host"] == "vps"
    assert row["last_success_args"] == {"market": "asx", "slot": "hourly"}
    t1 = t0 + dt.timedelta(hours=1)
    LG.record("scan.yml", status="skipped", exit_code=3, args={"market": "nasdaq", "slot": "hourly"},
              started=t1, ended=t1, path=led)
    row = LG.rows_for("scan.yml", led)
    assert row["last_status"] == "skipped" and row["last_skip_at"] == "2026-09-29T02:00:00Z"
    assert row["last_success_at"] == "2026-09-29T01:40:00Z", "a gate skip never clobbers the last success"
    assert row["pushed"] == "abc123" and row["consecutive_failures"] == 0
    t2 = t1 + dt.timedelta(hours=1)
    LG.record("scan.yml", status="failed", exit_code=1, args={}, started=t2, ended=t2,
              last_line="ASSERT-STAGED FAILED", path=led)
    LG.record("scan.yml", status="failed", exit_code=1, args={}, started=t2, ended=t2, path=led)
    row = LG.rows_for("scan.yml", led)
    assert row["last_failure_at"] == "2026-09-29T03:00:00Z" and row["consecutive_failures"] == 2
    assert row["last_failure_at"] > row["last_success_at"], "the watchdog's failed-run condition"
    LG.record("scan.yml", status="halted", exit_code=4, args={}, started=t2, ended=t2, path=led)
    row = LG.rows_for("scan.yml", led)
    assert row["last_halt_at"] and row["consecutive_failures"] == 3
    LG.record("scan.yml", status="ok", exit_code=0, args={}, started=t2, ended=t2, path=led)
    assert LG.rows_for("scan.yml", led)["consecutive_failures"] == 0
    with pytest.raises(ValueError):
        LG.record("scan.yml", status="bogus", exit_code=0, path=led)


def test_ledger_is_atomic_and_tolerant(tmp_path):
    led = tmp_path / "runs.json"
    assert LG.load(led) == {} and LG.rows_for("x", led) == {}
    led.write_text("{not json", encoding="utf-8")
    assert LG.load(led) == {}
    LG.record("update", status="ok", exit_code=0, path=led)
    assert json.loads(led.read_text())["update"]["last_status"] == "ok"
    assert not list(tmp_path.glob("*.tmp")), "temp + os.replace leaves no debris"
    LG.annotate("update", {"note": "x"}, path=led)
    assert LG.rows_for("update", led)["note"] == "x" and LG.rows_for("update", led)["last_status"] == "ok"


def test_ledger_writes_are_serialised_across_threads(tmp_path):
    led = tmp_path / "runs.json"

    def work(i):
        LG.record(f"job{i % 4}.yml", status="ok", exit_code=0, args={"i": i}, path=led)
    ths = [threading.Thread(target=work, args=(i,)) for i in range(16)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    doc = json.loads(led.read_text())
    assert set(doc) == {"job0.yml", "job1.yml", "job2.yml", "job3.yml"}


def test_redaction_strips_credentials_and_last_line_is_the_last_nonblank():
    assert LG.redact("fatal: https://x-token:ghp_abc@github.com/o/r") == "fatal: https://***@github.com/o/r"
    assert LG.redact("Authorization: Bearer abc.def") == "Authorization: Bearer ***"
    assert LG.redact("ssh://git:pw@host/x") == "ssh://***@host/x"
    assert LG.redact("api_key=SECRET rest") == "api_key=*** rest"
    assert LG.last_line_of("a\nb\n\n   \n") == "b"
    assert LG.last_line_of("") == ""


# ── spool ─────────────────────────────────────────────────────────────────────

def _spool(state: pathlib.Path, body, name=None, raw: str | None = None) -> pathlib.Path:
    (state / "spool").mkdir(parents=True, exist_ok=True)
    name = name or S.new_id(dt.datetime(2026, 9, 26, 21, 44, tzinfo=UTC))
    p = state / "spool" / name
    p.write_text(raw if raw is not None else json.dumps(body), encoding="utf-8")
    return p


def test_the_spool_name_regex_and_the_atomic_writer():
    assert S.NAME_RE.match("20260926T214400Z-1a2b3c4d.json")
    assert not S.NAME_RE.match("20260926T214400Z-1a2b3c4d.json.tmp")
    assert not S.NAME_RE.match("junk.json") and not S.NAME_RE.match(".20260926T214400Z-1a2b3c4d.json")


def test_write_spool_lands_atomically_in_the_spool_dir(tmp_path):
    p = S.write_spool("momentum.yml", {}, "chain/morning_plays.yml", state_dir=tmp_path)
    assert p.parent == tmp_path / "spool" and S.NAME_RE.match(p.name)
    body = json.loads(p.read_text())
    assert body["workflow"] == "momentum.yml" and body["inputs"] == {} and body["source"] == "chain/morning_plays.yml"
    assert body["id"] == p.stem and body["received_at"].endswith("Z")
    assert not list((tmp_path / "spool" / ".tmp").iterdir())


def test_validate_dispatch_matrix():
    assert S.validate_dispatch("scan.yml", {"market": "asx", "reason": "heartbeat"}) == \
        ("scan.yml", {"market": "asx", "reason": "heartbeat", "slot": "manual"})
    assert S.validate_dispatch("scan.yml", {"market": "ALL"})[1]["market"] == "all"
    for wf, inputs in (("scan.yml", {"market": "nyse"}), ("scan.yml", {"market": "asx", "reason": "cron"}),
                       ("scan.yml", {"market": "asx", "extra": "--limit 3"}),
                       ("morning_plays.yml", {"slot": "eu"}), ("morning_plays.yml", {"slot": "asx", "force": "true"}),
                       ("momentum.yml", {"market": "asx"}), ("kill_switch.yml", {}), ("nope.yml", {}),
                       ("close_position.yml", {"symbol": "FPH", "market": "asx", "price": "1", "journal_type": "x"}),
                       ("close_position.yml", {"symbol": "FPH", "market": "", "price": "1", "journal_type": "bot"}),
                       ("close_position.yml", {"journal_type": "swing", "closes": [{"symbol": "A", "market": "asx", "price": 1}]}),
                       ("close_position.yml", {"journal_type": "bot", "closes": []}),
                       ("close_position.yml", {"journal_type": "bot", "closes": [{"symbol": "A", "market": "asx", "price": 1}] * 2}),
                       ("close_position.yml", {"journal_type": "bot", "closes": [{"symbol": "A", "market": "asx", "price": "x"}]})):
        with pytest.raises(S.SpoolRefused):
            S.validate_dispatch(wf, inputs)
    assert S.validate_dispatch("morning_plays.yml", {"slot": "us"}) == ("morning_plays.yml", {"slot": "us"})
    assert S.validate_dispatch("momentum.yml", {}) == ("momentum.yml", {})
    single = S.validate_dispatch("close_position.yml", {"symbol": "fph", "market": "ASX", "price": 12.5,
                                                         "direction": "short", "exit_date": "bad",
                                                         "journal_type": "bot"})[1]
    assert single == {"symbol": "FPH", "direction": "short", "market": "asx", "price": "12.5",
                      "exit_date": "", "journal_type": "bot", "batch": ""}
    batch = S.validate_dispatch("close_position.yml", {"journal_type": "bot", "closes": [
        {"symbol": "fph", "market": "asx", "direction": "long", "price": "12.34"},
        {"symbol": "XYZ", "market": "nasdaq", "direction": "short", "price": 3}]})[1]
    assert batch["symbol"] == "FPH+1" and batch["journal_type"] == "bot"
    assert json.loads(batch["batch"]) == [{"symbol": "FPH", "market": "asx", "direction": "long", "price": "12.34"},
                                          {"symbol": "XYZ", "market": "nasdaq", "direction": "short", "price": "3.0"}]
    via_text = S.validate_dispatch("close_position.yml", {"journal_type": "bot",
                                                           "batch": json.dumps([{"symbol": "A", "market": "asx", "price": 1}])})[1]
    assert json.loads(via_text["batch"])[0]["symbol"] == "A", "close.js's batch STRING is accepted too"


def test_drain_matrix(tmp_path):
    state = tmp_path
    ran = []

    def runner(job, args, source):
        ran.append((job, args, source))
        if job == "morning_plays.yml":
            return 3
        return 1 if args.get("market") == "crypto" else 0
    ok = _spool(state, {"workflow": "scan.yml", "inputs": {"market": "asx", "reason": "manual"}, "source": "api/scan"},
                name="20260926T000001Z-aaaaaaaa.json")
    skip = _spool(state, {"workflow": "morning_plays.yml", "inputs": {"slot": "asx"}, "source": "api/mp"},
                  name="20260926T000002Z-bbbbbbbb.json")
    fail = _spool(state, {"workflow": "scan.yml", "inputs": {"market": "crypto"}}, name="20260926T000003Z-cccccccc.json")
    unknown = _spool(state, {"workflow": "test.yml", "inputs": {}}, name="20260926T000004Z-dddddddd.json")
    broken = _spool(state, None, name="20260926T000005Z-eeeeeeee.json", raw='{"workflow": "scan.yml", "inputs": {"market"')
    big = _spool(state, None, name="20260926T000006Z-ffffffff.json", raw='{"x": "' + "a" * (config.VPS_SPOOL_MAX_BYTES + 10) + '"}')
    ignored = _spool(state, {"workflow": "scan.yml", "inputs": {"market": "asx"}}, name="not-a-dispatch.json")
    (state / "spool" / ".tmp").mkdir(parents=True, exist_ok=True)
    partial = state / "spool" / ".tmp" / "20260926T000007Z-99999999.json"
    partial.write_text('{"workflow": "scan.yml", "inp')
    link = state / "spool" / "20260926T000008Z-01234567.json"
    link.symlink_to(ok)
    report = S.drain(runner, state_dir=state)
    assert [j for j, _, _ in ran] == ["scan.yml", "morning_plays.yml", "scan.yml"], "oldest first, only valid files"
    assert ran[0][1] == {"market": "asx", "reason": "manual", "slot": "manual"} and ran[0][2] == "api/scan"
    assert [(n, c) for n, _, c in report.ran] == [(ok.name, 0), (skip.name, 3), (fail.name, 1)]
    assert sorted(report.done) == sorted([ok.name, skip.name]), "exit 0 and 3 -> done/"
    assert (state / "spool" / "done" / ok.name).exists() and (state / "spool" / "done" / skip.name).exists()
    failed = dict(report.failed)
    assert failed[fail.name] == "exit 1"
    assert failed[unknown.name].startswith("unknown workflow")
    assert failed[broken.name] == "JSONDecodeError", "parse errors record the exception TYPE only"
    assert failed[big.name] == "oversize"
    assert (state / "spool" / "failed" / big.name).read_text().startswith('{"x"'), "refused unread, moved intact"
    assert report.skipped == [(link.name, "not a regular file")] and link.is_symlink(), "symlinks are left alone"
    assert ignored.exists() and partial.exists(), "non-matching names and .tmp partials are never touched"
    assert not (state / "spool" / ok.name).exists()


def test_a_file_that_cannot_be_moved_is_renamed_stuck(tmp_path):
    state = tmp_path
    p = _spool(state, {"workflow": "momentum.yml", "inputs": {}}, name="20260926T000001Z-aaaaaaaa.json")
    (state / "spool" / "done" / p.name).mkdir(parents=True)          # a DIRECTORY sits where the file must land
    report = S.drain(lambda *a: 0, state_dir=state)
    assert report.stuck and report.stuck[0][0] == p.name
    assert (state / "spool" / (p.name + ".stuck")).exists() and not p.exists()


def test_a_runner_exception_moves_the_file_to_failed(tmp_path):
    p = _spool(tmp_path, {"workflow": "momentum.yml", "inputs": {}}, name="20260926T000001Z-aaaaaaaa.json")

    def runner(*a):
        raise RuntimeError("boom")
    report = S.drain(runner, state_dir=tmp_path)
    assert dict(report.failed)[p.name] == "exit 1" and (tmp_path / "spool" / "failed" / p.name).exists()


# ── the runner: order, HALT, .scan-skipped, env, exit codes ──────────────────

def _row(rt, job="scan.yml"):
    return LG.rows_for(job, rt.ledger_file)


def test_a_book_writer_refuses_to_run_while_HALT_exists(rt):
    (rt.state).mkdir(parents=True, exist_ok=True)
    (rt.state / "HALT").write_text("{}")
    assert cli.run_job("scan.yml", ["market=asx"], rt) == 4
    assert rt.fake.calls == [] and _row(rt)["last_status"] == "halted" and _row(rt)["last_exit"] == 4
    assert cli.run_job("close_position.yml", ["symbol=FPH", "market=asx", "price=1"], rt) == 4
    assert cli.run_job("evidence_brief.yml", [], rt) == 0, "a read-only job still runs under HALT"
    assert rt.fake.find("evidence_brief.py")


def test_the_scan_skip_marker_is_deleted_before_the_first_scanner_run(rt):
    marker = rt.home / config.SCAN_SKIP_MARKER
    marker.write_text("asx\n")
    seen = {}

    def observe(call):
        seen["marker_present"] = marker.exists()
        return cli.Exec(0, "scan ok")
    rt.fake.when(lambda a: "scanner.run" in a, observe)
    assert cli.run_job("scan.yml", ["market=asx", "reason=manual"], rt) == 0
    assert seen["marker_present"] is False
    assert not marker.exists()
    # a NON scan-family job leaves a marker alone
    marker.write_text("asx\n")
    cli.run_job("reco_note.yml", [], rt)
    assert marker.exists()


def test_scan_single_market_runs_the_transcribed_steps_in_order_with_the_right_env(rt, monkeypatch):
    monkeypatch.setenv("GBS_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    assert cli.run_job("scan.yml", ["market=asx", "slot=manual", "reason=heartbeat"], rt) == 0
    argvs = rt.fake.argvs()
    assert argvs[0] == ["PY", "-m", "scanner.marketcaps"]
    assert argvs[1] == ["PY", "-m", "scanner.sectorcache"]
    assert argvs[2] == ["PY", "-m", "scanner.run", "--market", "asx"]
    assert argvs[3] == ["PY", "-"] and "SCHEMA GATE" in rt.fake.calls[3]["stdin"]
    assert argvs[4] == ["PY", "-m", "scanner.broker.vivek_run", "--verify"]
    assert argvs[5] == ["PY", "-m", "scanner.confluence_alert"]
    assert len(argvs) == 6, "publish is disabled (VIVEK_GIT_PUBLISH=0): no rebuild subprocess"
    scan_env = rt.fake.calls[2]["env"]
    assert scan_env["SCAN_TRIGGER"] == "heartbeat" and scan_env["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    assert scan_env["GBS_SMTP_HOST"] == "smtp.example" and "BYBIT_API_KEY" not in scan_env
    assert "GBS_SMTP_HOST" not in rt.fake.calls[0]["env"], "marketcaps does not list the alert secrets"
    assert rt.fake.calls[3]["env"]["SCANNED_MARKET"] == "asx"
    assert rt.fake.calls[2]["env"]["GITHUB_STEP_SUMMARY"].startswith(str(rt.state / "summaries"))
    for c in rt.fake.calls:
        assert c["cwd"] == str(rt.home), "every step runs from the checkout root"
    row = _row(rt)
    assert row["last_status"] == "ok" and row["last_args"]["market"] == "asx" and row["host"] == "test"


def test_scan_all_runs_nasdaq_crypto_asx_and_gates_on_asx_and_nasdaq(rt):
    rt.fake.when(lambda a: a[-1] == "crypto", cli.Exec(1, "crypto blew up"))
    assert cli.run_job("scan.yml", ["market=all", "extra=--limit 3"], rt) == 0
    scans = [c["argv"] for c in rt.fake.find("scanner.run")]
    assert scans == [["PY", "-m", "scanner.run", "--market", m, "--limit", "3"] for m in ("nasdaq", "crypto", "asx")]
    assert rt.fake.calls[-1]["argv"][2] == "scanner.confluence_alert", "crypto rc is ignored on a full cycle"
    rt.fake.calls.clear()
    rt.fake.rules.clear()
    rt.fake.when(lambda a: a[-1] == "asx" and "scanner.run" in a, cli.Exec(1, "asx blew up"))
    assert cli.run_job("scan.yml", ["market=all"], rt) == 1
    assert not rt.fake.find("--verify"), "fail-fast: nothing after the failed scan step"
    assert _row(rt)["last_status"] == "failed" and "asx" in _row(rt)["last_line"]


def test_scan_hourly_outside_the_window_is_a_skip_with_a_ledger_row_and_no_steps(rt):
    rt.now = lambda: _at("Australia/Sydney", 2026, 9, 29, 9, 0)
    assert cli.run_job("scan.yml", ["market=asx", "slot=hourly", "reason=cron"], rt) == 3
    assert rt.fake.calls == []
    row = _row(rt)
    assert row["last_status"] == "skipped" and row["last_exit"] == 3 and "Outside" in row["last_line"]


def test_the_close_slot_is_rechecked_after_the_lock(rt):
    tue = _at("Australia/Sydney", 2026, 9, 29, 16, 30)
    rt.now = lambda: tue
    prices = rt.home / "public" / "data" / "asx_prices.json"
    real_acquire = L.LockSet.acquire

    def landed_while_waiting(self, *a, **k):
        _write(prices, {"generated_at": tue.isoformat()})     # another writer finished the close scan
        return real_acquire(self, *a, **k)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(L.LockSet, "acquire", landed_while_waiting)
        assert cli.run_job("scan.yml", ["market=asx", "slot=close", "reason=cron"], rt) == 3
    assert rt.fake.calls == [] and _row(rt)["last_status"] == "skipped"


def test_crypto_backstop_skips_on_a_fresh_local_scan_and_the_watchdog_follows_the_publish(rt):
    now = rt.now()
    _write(rt.home / "public" / "data" / "crypto_vivek.json", {"generated_at": (now - dt.timedelta(minutes=5)).isoformat()})
    assert cli.run_job("crypto_bot.yml", ["slot=backstop"], rt) == 3 and rt.fake.calls == []
    assert cli.run_job("crypto_bot.yml", ["slot=hourly"], rt) == 0
    argvs = rt.fake.argvs()
    assert argvs[0] == ["PY", "-m", "scanner.run", "--market", "crypto"]
    assert rt.fake.calls[0]["env"]["SCAN_TRIGGER"] == "cron" and rt.fake.calls[0]["env"]["GITHUB_EVENT_NAME"] == "schedule"
    assert argvs[-1] == ["PY", "-m", "scanner.watchdog"] and rt.fake.calls[-1]["env"]["WATCHDOG_HOST"] == "crypto_bot"
    rt.fake.calls.clear()
    rt.fake.when(lambda a: "--verify" in a, cli.Exec(1, "BOOK VERIFY FAIL: x"))
    assert cli.run_job("crypto_bot.yml", ["slot=hourly"], rt) == 1
    assert not rt.fake.find("scanner.watchdog"), "no watchdog after a failed gate/publish (no always())"


def test_kill_switch_is_armed_on_the_timer_and_dry_only_when_asked(rt, monkeypatch):
    monkeypatch.setenv("BYBIT_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert cli.run_job("kill_switch.yml", [], rt) == 0
    check, wd = rt.fake.calls
    assert check["argv"] == ["PY", "-m", "scanner.broker.kill_switch"]
    assert check["env"]["BYBIT_API_KEY"] == "k" and check["env"]["TELEGRAM_BOT_TOKEN"] == "t"
    assert wd["argv"] == ["PY", "-m", "scanner.watchdog"] and wd["env"]["WATCHDOG_HOST"] == "kill_switch"
    assert "BYBIT_API_KEY" not in wd["env"] and wd["env"]["TELEGRAM_BOT_TOKEN"] == "t"
    rt.fake.calls.clear()
    assert cli.run_job("kill_switch.yml", ["dry_run=true"], rt) == 0
    assert rt.fake.calls[0]["argv"] == ["PY", "-m", "scanner.broker.kill_switch", "--dry-run"]


def test_phasemap_runs_small_markets_in_parallel_and_records_the_specs_outcome(rt):
    order = []
    rt.fake.when(lambda a: "phasemap.run" in a, lambda c: (order.append(c["argv"][-1]), cli.Exec(0, ""))[1])
    rt.fake.when(lambda a: "scanner.spec_run" in a, cli.Exec(1, "specs broke"))
    assert cli.run_job("phasemap.yml", [], rt) == 0
    assert order[-1] == "asx" and set(order[:2]) == {"nasdaq", "crypto"}
    assert rt.fake.find("phasemap.config") or rt.fake.calls[-1]["stdin"].startswith("import json")
    assert cli.run_job("phasemap.yml", ["market=asx", "args=--limit 5"], rt) == 0
    assert rt.fake.calls[-3]["argv"] == ["PY", "-m", "phasemap.run", "--market", "asx", "--limit", "5"]


def test_momentum_rc3_is_a_reported_decision_and_a_named_market_skips_the_due_check(rt):
    rt.fake.when(lambda a: "scanner.momentum.run" in a, cli.Exec(3, "no data"))
    assert cli.run_job("momentum.yml", ["market=nasdaq"], rt) == 0
    assert rt.fake.argvs() == [["PY", "-m", "scanner.momentum.run", "--market", "nasdaq"]]
    assert rt.fake_run.calls == [["git", "rev-parse", "HEAD"]], "manual market: no fetch, no momentum_due"
    assert _row(rt, "momentum.yml")["last_status"] == "ok"
    rt.fake.calls.clear()
    rt.fake.rules.clear()
    rt.fake.when(lambda a: "scanner.momentum.run" in a, cli.Exec(2, "traceback"))
    assert cli.run_job("momentum.yml", ["market=asx", "mode=B", "backtest=true"], rt) == 1
    assert rt.fake.argvs()[0] == ["PY", "-m", "scanner.momentum.run", "--market", "asx", "--mode", "B", "--backtest"]


def test_momentum_from_the_spool_lets_momentum_due_pick_and_skips_when_nothing_is_due(rt):
    def handler(argv, kw):
        if argv[:2] == ["git", "show"]:
            return subprocess.CompletedProcess(argv, 0, "{}", "")
        if str(argv[1]).endswith("momentum_due.py"):
            pathlib.Path(kw["env"]["GITHUB_OUTPUT"]).write_text("market=\n")
            return subprocess.CompletedProcess(argv, 0, "picked: nothing due", "")
        return subprocess.CompletedProcess(argv, 0, "", "")
    rt.fake_run.when(lambda a: True, handler)
    assert cli.run_job("momentum.yml", {}, rt, operator=False, source="spool") == 3
    assert rt.fake.calls == [] and _row(rt, "momentum.yml")["last_status"] == "skipped"


def test_evidence_brief_rc1_is_green_and_a_crash_is_red(rt):
    rt.fake.when(lambda a: a[1].endswith("evidence_brief.py"), cli.Exec(1, "# Evidence brief ISSUE: x", "warn"))
    assert cli.run_job("evidence_brief.yml", [], rt) == 0
    assert rt.fake.calls[0]["timeout"] and rt.fake.calls[0]["cwd"] == str(rt.home)
    briefs = list((rt.state / "summaries").glob("evidence_brief-*-brief.txt"))
    assert briefs and briefs[0].read_text().startswith("# Evidence brief")
    rt.fake.rules.clear()
    rt.fake.when(lambda a: a[1].endswith("evidence_brief.py"), cli.Exec(2, "", "Traceback"))
    assert cli.run_job("evidence_brief.yml", [], rt) == 1


def test_close_position_builds_the_three_branches_and_passes_the_batch_by_env(rt):
    assert cli.run_job("close_position.yml", ["symbol=fph", "market=asx", "price=12.34", "direction=long"], rt) == 0
    assert rt.fake.argvs()[0] == ["PY", "-m", "scanner.broker.vivek_run", "--close", "FPH", "--market", "asx",
                                  "--price", "12.34", "--direction", "long"]
    assert rt.fake.argvs()[1] == ["PY", "-m", "scanner.broker.vivek_run", "--verify"]
    rt.fake.calls.clear()
    batch = json.dumps([{"symbol": "FPH", "market": "asx", "direction": "long", "price": "1"}])
    assert cli.run_job("close_position.yml", ["symbol=FPH", "market=asx", "price=1", "journal_type=bot",
                                              f"batch={batch}"], rt) == 0
    c = rt.fake.calls[0]
    assert c["argv"] == ["PY", "-m", "scanner.broker.vivek_run", "--close-batch"]
    assert c["env"]["VIVEK_CLOSE_BATCH"] == batch and "VIVEK_CLOSE_BATCH" not in rt.fake.calls[1]["env"]
    assert _row(rt, "close_position.yml")["last_args"]["batch"] == "<1 entries>"
    rt.fake.calls.clear()
    assert cli.run_job("close_position.yml", ["symbol=FPH", "market=asx", "price=1", "journal_type=swing",
                                              "exit_date=2026-09-01"], rt) == 0
    assert rt.fake.argvs()[0] == ["PY", "-m", "scanner.journal", "--close-manual", "--symbol", "FPH",
                                  "--direction", "long", "--market", "asx", "--price", "1",
                                  "--date", "2026-09-01", "--journal-type", "swing"]
    rt.fake.calls.clear()
    rt.fake.when(lambda a: "--close" in a, cli.Exec(2, "no open position matched FPH [asx] - book untouched"))
    assert cli.run_job("close_position.yml", ["symbol=FPH", "market=asx", "price=1"], rt) == 1
    assert len(rt.fake.calls) == 1 and "no open position" in _row(rt, "close_position.yml")["last_line"]


def test_morning_plays_maps_the_slot_and_chains_a_momentum_dispatch(rt, monkeypatch):
    monkeypatch.setenv("DISCORD_MORNING_WEBHOOK_URL", "https://discord/x")
    assert cli.run_job("morning_plays.yml", ["slot=asx"], rt) == 0
    c = rt.fake.calls[0]
    assert c["argv"] == ["PY", "scripts/morning_plays.py", "--slot", "asx"]
    assert c["env"]["DISCORD_MORNING_WEBHOOK_URL"] == "https://discord/x"
    spooled = S.pending(rt.state)
    assert len(spooled) == 1 and json.loads(spooled[0].read_text())["workflow"] == "momentum.yml"
    rt.fake.calls.clear()
    assert cli.run_job("morning_plays.yml", ["slot=us", "redeliver=true"], rt) == 0
    assert rt.fake.argvs()[0][-3:] == ["--slot", "us", "--redeliver"]
    assert cli.run_job("morning_plays.yml", [], rt) == 0
    assert rt.fake.argvs()[-1][-1] == "--force"
    assert cli.run_job("morning_plays.yml", ["force=false"], rt) == 0
    assert len(rt.fake.calls) == 2, "slot blank + force=false: nothing runs"
    rt.fake.calls.clear()
    rt.fake.when(lambda a: a[1].endswith("morning_plays.py"), cli.Exec(1, "::error::morning_plays: Discord returned HTTP 500"))
    assert cli.run_job("morning_plays.yml", ["slot=asx"], rt) == 1
    assert len(S.pending(rt.state)) == 5, "the chain fires on every completion, failed ones included"


def test_backup_backstop_skip_still_runs_verify(rt):
    (rt.home / "backups" / (rt.now().strftime("%Y-%m-%d") + "T01-00-00")).mkdir(parents=True)
    assert cli.run_job("backup_book.yml", ["slot=backstop"], rt) == 3
    assert rt.fake.argvs() == [["PY", "scripts/backup_journal.py", "verify"]]
    assert _row(rt, "backup_book.yml")["last_status"] == "skipped"
    rt.fake.calls.clear()
    assert cli.run_job("backup_book.yml", ["slot=primary"], rt) == 0
    assert rt.fake.argvs() == [["PY", "scripts/backup_journal.py", "backup"], ["PY", "scripts/backup_journal.py", "verify"]]


def test_offbox_copy_fails_the_backup_when_the_target_copy_fails(rt, monkeypatch):
    monkeypatch.setenv("VIVEK_BACKUP_TARGET", "host:/srv/backups/")
    rt.fake.when(lambda a: a[0] == "rsync", cli.Exec(23, "rsync: connection refused"))
    assert cli.run_job("backup_book.yml", ["slot=primary"], rt) == 1
    assert rt.fake.argvs()[1] == ["rsync", "-a", "--delete", str(rt.home / "backups") + "/", "host:/srv/backups/"]


def test_lens_backtest_tolerates_specs_and_vivek_but_gates_on_phasemap_asx_and_nasdaq(rt):
    rt.fake.when(lambda a: "scanner.spec_backtest" in a, cli.Exec(1, ""))
    rt.fake.when(lambda a: "scanner.vivek_backtest" in a, cli.Exec(1, ""))
    assert cli.run_job("lens_backtest.yml", ["vivek_limit=10"], rt) == 0
    assert rt.fake.argvs()[-1] == ["PY", "-m", "scanner.vivek_backtest", "--market", "all", "--limit", "10", "--period", "5y"]
    rt.fake.calls.clear()
    rt.fake.when(lambda a: "phasemap.backtest" in a and a[4] == "nasdaq", cli.Exec(1, ""))
    assert cli.run_job("lens_backtest.yml", [], rt) == 1
    assert len(rt.fake.calls) == 3, "all three legs run, then the job stops"


def test_vivek_backtest_streams_three_legs_each_followed_by_a_publish(rt):
    assert cli.run_job("vivek_backtest.yml", ["limit=0", "period=max"], rt) == 0
    legs = [c["argv"][4] for c in rt.fake.find("scanner.vivek_backtest")]
    assert legs == ["nasdaq", "asx", "crypto"]
    assert rt.fake.calls[0]["argv"][5:] == ["--limit", "0", "--period", "max", "--long-only", "--out",
                                            "public/data/vivek_backtest_longonly.json", "--merge", "--status", "partial"]
    rt.fake.calls.clear()
    rt.fake.when(lambda a: a[4] == "asx", cli.Exec(1, "asx crashed"))
    assert cli.run_job("vivek_backtest.yml", [], rt) == 1
    assert [c["argv"][4] for c in rt.fake.calls] == ["nasdaq", "asx"], "the crypto leg never runs"


def test_the_edge_pipeline_captures_each_scripts_output_for_the_sentinels(rt):
    rt.fake.when(lambda a: a[1].endswith("alert_returns.py"), cli.Exec(0, "ALERT_RETURNS_UNCHANGED"))
    assert cli.run_job("alert_returns.yml", ["slot=primary"], rt) == 0
    names = [c["argv"][1] for c in rt.fake.calls]
    assert names == ["scripts/alert_returns.py", "scripts/edge_rosters.py", "scripts/book_stress.py",
                     "scripts/alert_edge_report.py", "scripts/edge_summary.py"]
    summary = pathlib.Path(rt.fake.calls[0]["env"]["GITHUB_STEP_SUMMARY"]).read_text()
    assert "Edge report" in summary, "the report step lands in the per-run summary file"
    rt.fake.calls.clear()
    rt.fake.when(lambda a: a[1].endswith("book_stress.py"), cli.Exec(2, "ERROR book unreadable"))
    assert cli.run_job("alert_returns.yml", ["slot=primary"], rt) == 1
    assert len(rt.fake.calls) == 3, "fail-fast: no report, no summary, no publish"


def test_the_ledger_row_is_written_even_when_the_runner_crashes(rt):
    def boom(call):
        raise RuntimeError("exec exploded")
    rt.fake.when(lambda a: True, boom)
    assert cli.run_job("reco_note.yml", [], rt) == 1
    row = _row(rt, "reco_note.yml")
    assert row["last_status"] == "failed" and "RuntimeError" in row["last_line"]


def test_a_job_timeout_fails_the_run(rt):
    def slow(call):
        rt.clock_state["t"] += 10_000          # longer than reco_note's 600 s
        return cli.Exec(0, "")
    rt.fake.when(lambda a: True, slow)
    assert cli.run_job("reco_note.yml", [], rt) == 1
    assert "timeout" in _row(rt, "reco_note.yml")["last_line"]


def test_lock_wait_is_recorded_separately_from_the_step_timeout(rt):
    holder = L.Lock(L.lock_path(rt.state, "reco_note"))
    (rt.state / "locks").mkdir(parents=True, exist_ok=True)
    assert holder.try_acquire()
    rt.clock, rt.sleep = time.monotonic, time.sleep          # a real wait on a real holder
    threading.Timer(0.6, holder.release).start()
    assert cli.run_job("reco_note.yml", [], rt) == 0
    row = _row(rt, "reco_note.yml")
    assert row["last_status"] == "ok" and row["waited_s"] >= 0
    assert rt.fake.calls, "the step ran AFTER the wait, with its own full timeout budget"
    assert rt.fake.calls[0]["timeout"] > J.JOBS["reco_note.yml"].timeout_s - 5


def test_a_lock_timeout_is_a_failed_row_not_a_hang(rt):
    holder = L.Lock(L.lock_path(rt.state, "scan"))
    (rt.state / "locks").mkdir(parents=True, exist_ok=True)
    assert holder.try_acquire()
    assert cli.run_job("confluence.yml", [], rt) == 1
    assert "lock" in _row(rt, "confluence.yml")["last_line"] and rt.fake.calls == []
    holder.release()


def test_spool_driven_failures_alert_and_operator_runs_do_not(rt):
    alerts = []
    rt.notify = lambda sev, title, details="": alerts.append((sev, title)) or []
    rt.fake.when(lambda a: "scanner.run" in a, cli.Exec(1, "dead"))
    assert cli.run_job("scan.yml", {"market": "asx", "reason": "manual", "slot": "manual"}, rt,
                       operator=False, source="api/scan") == 1
    assert alerts and alerts[0][0] == "CRITICAL" and "scan.yml failed" in alerts[0][1]
    alerts.clear()
    assert cli.run_job("scan.yml", ["market=asx"], rt) == 1
    assert alerts == [], "an operator at the CLI sees the failure; the OnFailure hook alerts for units"


def test_publish_disabled_records_a_green_row_and_a_halt_result_records_halted(rt, monkeypatch):
    from scanner.vps import publish as P
    assert cli.run_job("reco_note.yml", [], rt) == 0 and _row(rt, "reco_note.yml")["last_status"] == "ok"
    monkeypatch.setattr(P, "publish", lambda *a, **k: P.PublishResult("halted", 4, None, "second writer"))
    monkeypatch.setenv("VIVEK_GIT_PUBLISH", "1")
    assert cli.run_job("reco_note.yml", [], rt) == 4
    assert _row(rt, "reco_note.yml")["last_status"] == "halted"
    monkeypatch.setattr(P, "publish", lambda *a, **k: P.PublishResult("pushed", 1, "deadbeef", "data: phasemap"))
    assert cli.run_job("phasemap.yml", [], rt) == 1, "a collected must-change miss is red even though data pushed"
    row = _row(rt, "phasemap.yml")
    assert row["last_status"] == "failed" and row["pushed"] == "deadbeef"


# ── notify ────────────────────────────────────────────────────────────────────

def test_alert_logs_to_alerts_log_and_uses_the_watchdog_channel_path(tmp_path, monkeypatch):
    sent = []

    def fake_dispatch(sev, text):
        sent.append((sev, text))
        return ["telegram"]
    monkeypatch.setenv("WATCHDOG_HOST", "vps-test")
    got = N.alert("CRITICAL", "second writer", "sha abc by x\nBearer secret123", state_dir=tmp_path, dispatch=fake_dispatch)
    assert got == ["telegram"] and sent[0][0] == "CRITICAL"
    assert "[Vivek 5.0] VPS second writer" in sent[0][1] and "Bearer ***" in sent[0][1]
    log = (tmp_path / "alerts.log").read_text()
    assert "CRITICAL second writer | sent=telegram" in log and "(host: vps-test" in sent[0][1]
    N.alert("WARNING", "quiet", state_dir=tmp_path, dispatch=lambda s, t: [])
    assert "sent=NONE" in (tmp_path / "alerts.log").read_text()
    import scanner.watchdog as wd
    assert N._dispatch_default.__module__ == N.__name__ and callable(wd._dispatch)


def test_unit_names_map_to_ledger_keys():
    assert N.unit_to_key("vivek5-scan@asx.service") == "scan.yml"
    assert N.unit_to_key("vivek5-scan-close@nasdaq.service") == "scan.yml"
    assert N.unit_to_key("vivek5-scan-backstop@asx.service") == "scan.yml"
    assert N.unit_to_key("vivek5-crypto-bot-backstop.service") == "crypto_bot.yml"
    assert N.unit_to_key("vivek5-alert-returns-backstop.service") == "alert" + "_returns.yml"
    assert N.unit_to_key("vivek5-morning-plays@us.service") == "morning_plays.yml"
    assert N.unit_to_key("vivek5-kill-switch.service") == "kill_switch.yml"
    assert N.unit_to_key("vivek5-update.service") == "update"
    assert N.unit_to_key("vivek5-api.service") == "api"


def test_notify_failure_writes_a_failed_row_only_when_the_runner_left_none(tmp_path):
    led = tmp_path / "runs.json"
    now = dt.datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    alerts = []
    dispatch = lambda s, t: alerts.append((s, t)) or []                  # noqa: E731
    fake_run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "line1\nline2", "")   # noqa: E731
    assert N.notify_failure("vivek5-kill-switch.service", state_dir=tmp_path, ledger_file=led,
                            dispatch=dispatch, run=fake_run, now=now) == 0
    row = LG.rows_for("kill_switch.yml", led)
    assert row["last_status"] == "failed" and row["last_exit"] == -1 and row["last_unit_failure_at"]
    assert alerts[0][0] == "CRITICAL" and "unit failed: vivek5-kill-switch.service" in alerts[0][1]
    # the runner already wrote a row seconds ago: the hook only annotates it
    LG.record("reco_note.yml", status="failed", exit_code=1, started=now, ended=now, last_line="assert", path=led)
    N.notify_failure("vivek5-reco-note.service", state_dir=tmp_path, ledger_file=led, dispatch=dispatch,
                     run=fake_run, now=now + dt.timedelta(seconds=30))
    row = LG.rows_for("reco_note.yml", led)
    assert row["last_line"] == "assert" and row["last_exit"] == 1 and row["last_unit_failure_at"]
    assert alerts[-1][0] == "WARNING"


# ── the CLI surface ───────────────────────────────────────────────────────────

def test_the_cli_verbs_exist_and_list_runs_in_this_checkout():
    out = subprocess.run([sys.executable, "-m", "scanner.vps", "list"], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for name in EXPECTED_JOBS:
        assert name in out.stdout
    assert "14 jobs" in out.stdout
    helptext = subprocess.run([sys.executable, "-m", "scanner.vps", "--help"], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=60).stdout
    for verb in ("run", "gate", "drain-spool", "notify-failure", "ledger", "list", "accept-upstream", "clear-halt",
                 "data-roots"):
        assert verb in helptext
    roots = subprocess.run([sys.executable, "-m", "scanner.vps", "data-roots"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=60).stdout.split()
    assert roots == list(J.data_roots()) and "journal/vivek_bot_book.json" in roots, \
        "update.sh reads the second-writer scope from this verb"


def test_gate_verb_exit_codes(rt):
    rt.now = lambda: _at("Australia/Sydney", 2026, 9, 29, 12, 0)
    assert cli.cmd_gate("scan.yml", ["market=asx", "slot=hourly"], rt) == 0
    assert cli.cmd_gate("scan.yml", ["market=nasdaq", "slot=hourly"], rt) == 3
    assert cli.main(["run", "scan.yml", "market=lse"]) == 2
    assert cli.main(["run", "nope.yml"]) == 2


def test_default_exec_streams_and_returns_the_exit_code(tmp_path):
    res = cli.default_exec([sys.executable, "-c", "import sys; print('hi'); sys.exit(7)"], cwd=str(tmp_path),
                           env=dict(os.environ))
    assert res.rc == 7 and res.out.strip() == "hi"
    res = cli.default_exec([sys.executable, "-"], cwd=str(tmp_path), env=dict(os.environ), stdin="print(2+2)")
    assert res.rc == 0 and res.out.strip() == "4"
    res = cli.default_exec([sys.executable, "-c", "import time; time.sleep(5)"], cwd=str(tmp_path),
                           env=dict(os.environ), timeout=0.5)
    assert res.rc == 124
    res = cli.default_exec([sys.executable, "-c", "import sys; sys.stderr.write('e'); sys.exit(1)"],
                           cwd=str(tmp_path), env=dict(os.environ), stream=False)
    assert res.rc == 1 and res.err == "e"


def test_step_env_strips_secrets_unless_the_step_lists_them(rt, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "a")
    monkeypatch.setenv("GH_DISPATCH_TOKEN", "g")
    monkeypatch.setenv("SOMETHING_ELSE", "keep")
    job = J.JOBS["reco_note.yml"]
    ctx = {"summary": rt.state / "s.md", "event_name": "schedule", "outputs": {}}
    env = cli.step_env(rt, job, job.steps[0], {}, ctx, rt.state / "o")
    assert "ALPACA_API_KEY" not in env and "GH_DISPATCH_TOKEN" not in env and env["SOMETHING_ELSE"] == "keep"
    assert env["GITHUB_EVENT_NAME"] == "schedule" and env["VIVEK_HOME"] == str(rt.home)
    ks = J.JOBS["kill_switch.yml"]
    env = cli.step_env(rt, ks, ks.steps[0], {}, ctx, rt.state / "o")
    assert env["ALPACA_API_KEY"] == "a" and "GH_DISPATCH_TOKEN" not in env


def test_schedule_table_units_map_to_job_args_the_table_accepts():
    """Every `run ...` invocation in DESIGN section 4 parses against the table."""
    design = (ROOT / "deploy" / "DESIGN.md").read_text(encoding="utf-8")
    invocations = re.findall(r"`run ([a-z_]+\.yml)((?: [a-z_]+=[a-z_]+)*)`", design)
    assert len(invocations) >= 20
    for name, kvs in invocations:
        job = J.get(name)
        J.parse_args(job, J.parse_kv(kvs.split()))

"""Forward returns for confluence alerts (scripts/alert_returns.py, 2026-08-20).

Four families:
  1. Identity — one alignment is ONE ledger row, keyed by the same
     market-local session day confluence itself dedupes on.
  2. Stamping — returns come from real bar arithmetic, mature per horizon,
     and are FROZEN at first measurement (idempotent re-runs).
  3. The fences — this is research infrastructure: the script must never
     write alert_history.json (the scan mutex owns it) and nothing in
     scanner/ or broker/ may read the ledger back.
  4. Workflow shape — the reco_note commit pattern: skip on UNCHANGED,
     surgical staging + assert_staged, outside the scan mutex.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alert_returns", ROOT / "scripts" / "alert_returns.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)

WF = (ROOT / ".github" / "workflows" / "alert_returns.yml").read_text(encoding="utf-8")
SRC = (ROOT / "scripts" / "alert_returns.py").read_text(encoding="utf-8")


def _entry(ticker="BHP", market="asx", side="long", count=2,
           date="2026-08-01T05:18:11+00:00"):
    return {"date": date, "market": market, "ticker": ticker, "side": side,
            "count": count, "lenses": ["PHASEMAP", "VIVEK"]}


def _frames(sym, start="2026-08-01", n=30, base=100.0, step=1.0):
    idx = pd.date_range(start, periods=n, freq="D")
    return {sym: pd.DataFrame({"Close": [base + i * step for i in range(n)]}, index=idx)}


# ── identity ─────────────────────────────────────────────────────────────────

def test_the_key_is_the_market_local_session_day():
    # 2026-08-01T22:00 UTC is already Aug 2 in Melbourne — the ledger must
    # agree with confluence_alert's own dedupe about which session that was.
    e = _entry(date="2026-08-01T22:00:00+00:00", market="asx")
    assert ar.entry_key(e).startswith("2026-08-02|asx|BHP|long|2")


def test_ingest_copies_once_and_a_second_run_adds_nothing():
    led = ar._fresh()
    assert ar.ingest(led, [_entry(), _entry()]) == 1, "duplicate alignments collapse"
    assert ar.ingest(led, [_entry()]) == 0, "a re-run ingests nothing"
    assert len(led["entries"]) == 1
    row = led["entries"][0]
    assert row["fwd"] == {"5": None, "10": None, "20": None}
    assert row["base_close"] is None


def test_a_malformed_history_entry_is_skipped_not_fatal():
    led = ar._fresh()
    assert ar.ingest(led, [{"date": "x"}, _entry()]) == 1


# ── maturity filter ──────────────────────────────────────────────────────────

def test_only_plausibly_matured_horizons_ask_for_prices():
    led = ar._fresh()
    ar.ingest(led, [_entry(date="2026-08-01T05:00:00+00:00")])
    assert ar.wanting_prices(led, dt.date(2026, 8, 3)) == {}, "2 days old - nothing can have matured"
    want = ar.wanting_prices(led, dt.date(2026, 8, 10))
    assert "BHP.AX" in want, "ASX tickers price under their Yahoo suffix"


def test_a_fully_stamped_entry_never_downloads_again():
    led = ar._fresh()
    ar.ingest(led, [_entry()])
    led["entries"][0]["fwd"] = {"5": 0.01, "10": 0.02, "20": 0.03}
    assert ar.wanting_prices(led, dt.date(2027, 1, 1)) == {}


# ── stamping arithmetic ──────────────────────────────────────────────────────

def _stamped_ledger(n_bars):
    led = ar._fresh()
    ar.ingest(led, [_entry(date="2026-08-01T05:00:00+00:00")])
    want = ar.wanting_prices(led, dt.date(2026, 12, 1))
    n = ar.stamp(led, _frames("BHP.AX", n=n_bars), want)
    return led["entries"][0], n


def test_returns_are_close_over_base_close_minus_one():
    e, _ = _stamped_ledger(30)
    # base = first bar on/after Aug 1 = index 0 (close 100); +5 sessions = 105.
    assert e["base_close"] == 100.0
    assert abs(e["fwd"]["5"] - 0.05) < 1e-9
    assert abs(e["fwd"]["10"] - 0.10) < 1e-9
    assert abs(e["fwd"]["20"] - 0.20) < 1e-9


def test_an_immature_horizon_stays_None_and_is_filled_next_run():
    e, _ = _stamped_ledger(12)          # bars for 5 and 10, not 20
    assert e["fwd"]["5"] is not None and e["fwd"]["10"] is not None
    assert e["fwd"]["20"] is None, "never guessed from a shorter window"


def test_a_stamped_return_is_FROZEN_against_later_price_revisions():
    led = ar._fresh()
    ar.ingest(led, [_entry(date="2026-08-01T05:00:00+00:00")])
    want = ar.wanting_prices(led, dt.date(2026, 12, 1))
    ar.stamp(led, _frames("BHP.AX", n=30), want)
    before = json.dumps(led["entries"][0]["fwd"])
    # Yahoo revises the tape: same symbol, wildly different closes.
    n2 = ar.stamp(led, _frames("BHP.AX", n=30, base=500, step=-3), ar.wanting_prices(led, dt.date(2026, 12, 1)))
    assert json.dumps(led["entries"][0]["fwd"]) == before
    assert n2 == 0, "a second run re-stamps nothing"


def test_a_missing_frame_leaves_the_entry_untouched_for_the_next_run():
    led = ar._fresh()
    ar.ingest(led, [_entry()])
    want = ar.wanting_prices(led, dt.date(2026, 12, 1))
    assert ar.stamp(led, {}, want) == 0
    assert led["entries"][0]["fwd"]["5"] is None


# ── trim discipline ──────────────────────────────────────────────────────────

def test_trim_never_drops_an_entry_still_waiting_on_a_horizon(monkeypatch):
    monkeypatch.setattr(ar, "CAP", 2)
    led = ar._fresh()
    for i, day in enumerate(("2026-07-01", "2026-07-02", "2026-07-03")):
        ar.ingest(led, [_entry(ticker=f"T{i}", date=f"{day}T05:00:00+00:00")])
    led["entries"][0]["fwd"] = {"5": 0.1, "10": 0.1, "20": 0.1}   # oldest, done
    dropped = ar.trim(led)
    assert dropped == 1, "only the fully-stamped entry may go"
    assert {e["ticker"] for e in led["entries"]} == {"T1", "T2"}
    led2 = ar._fresh()
    for i in range(4):
        ar.ingest(led2, [_entry(ticker=f"W{i}", date=f"2026-07-0{i+1}T05:00:00+00:00")])
    assert ar.trim(led2) == 0, "all waiting -> nothing trimmed even over cap"


# ── the fences ───────────────────────────────────────────────────────────────

def test_the_script_never_writes_alert_history():
    # The history file is written inside the scan mutex by confluence_alert;
    # a second writer would race it. This script may only READ it.
    writes = re.findall(r"write_json\(([^,]+),", SRC)
    assert writes == ["LEDGER"], f"only the ledger may be written, saw: {writes}"
    assert "HISTORY" not in "".join(writes)


def test_nothing_in_scanner_or_broker_reads_the_ledger_back():
    # config.py is exempt: it DECLARES the constants (rule 3) - declaring a
    # threshold is not reading the artefact. Everything else in the engine
    # must stay blind to the ledger.
    hits = []
    for p in (ROOT / "scanner").rglob("*.py"):
        if p.name == "config.py":
            continue
        if "alert_forward_returns" in p.read_text(encoding="utf-8"):
            hits.append(str(p))
    assert hits == [], f"the ledger leaked into a signal path: {hits}"


def test_the_engine_does_not_import_the_script():
    for p in (ROOT / "scanner").rglob("*.py"):
        if p.name == "config.py":
            continue
        assert "alert_returns" not in p.read_text(encoding="utf-8"), p


# ── workflow shape ───────────────────────────────────────────────────────────

def test_workflow_skips_the_commit_on_UNCHANGED():
    assert "ALERT_RETURNS_UNCHANGED" in WF
    block = WF[WF.index("grep -q ALERT_RETURNS_UNCHANGED"):]
    assert "exit 0" in block.split("git config")[0], "the UNCHANGED branch must exit before any git write"


def test_workflow_stages_one_path_and_asserts_it():
    assert 'git add -- data/alert_forward_returns.json' in WF
    assert 'assert_staged.sh "alert returns ledger" data/alert_forward_returns.json' in WF


def test_workflow_is_outside_the_scan_mutex_and_watchdogged():
    assert "group: scan" not in WF
    assert not re.search(r"^\s*concurrency:", WF, re.M)
    from scanner import config
    assert "alert_returns.yml" in config.WATCHDOG_RUNS, \
        "a workflow that commits data needs a WATCHDOG_RUNS entry (CLAUDE.md)"


def test_workflow_has_pipefail_on_the_tee():
    assert "set -o pipefail" in WF

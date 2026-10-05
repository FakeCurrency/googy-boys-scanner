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
  5. Completed bars only (2026-10-05) — a stamp is frozen, so it may never be
     read off a daily bar that is still forming (the ASX mid-session runs).
  6. The backstop gate, EXECUTED — anchored on the 22:00 UTC slot, satisfied
     only by a pass that landed on main, fail-open.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

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
    assert row["fwd"] == {str(h): None for h in ar.HORIZONS}
    assert row["base_close"] is None


def test_a_malformed_history_entry_is_skipped_not_fatal():
    led = ar._fresh()
    assert ar.ingest(led, [{"date": "x"}, _entry()]) == 1


# ── maturity filter ──────────────────────────────────────────────────────────

def test_only_plausibly_matured_horizons_ask_for_prices():
    led = ar._fresh()
    ar.ingest(led, [_entry(date="2026-08-01T05:00:00+00:00")])
    assert ar.wanting_prices(led, dt.date(2026, 8, 1)) == {}, "same day - not even 1s can have matured"
    want = ar.wanting_prices(led, dt.date(2026, 8, 10))
    assert "BHP.AX" in want, "ASX tickers price under their Yahoo suffix"


def test_a_fully_stamped_entry_never_downloads_again():
    led = ar._fresh()
    ar.ingest(led, [_entry()])
    led["entries"][0]["fwd"] = {str(h): 0.01 for h in ar.HORIZONS}
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
    led["entries"][0]["fwd"] = {str(h): 0.1 for h in ar.HORIZONS}   # oldest, done
    dropped = ar.trim(led)
    assert dropped == 1, "only the fully-stamped entry may go"
    assert {e["ticker"] for e in led["entries"]} == {"T1", "T2"}
    led2 = ar._fresh()
    for i in range(4):
        ar.ingest(led2, [_entry(ticker=f"W{i}", date=f"2026-07-0{i+1}T05:00:00+00:00")])
    assert ar.trim(led2) == 0, "all waiting -> nothing trimmed even over cap"


# ── the 1-session horizon migration (batch-100 WS-A) ─────────────────────────

def test_the_horizons_now_include_1_session():
    assert 1 in ar.HORIZONS and 5 in ar.HORIZONS and 20 in ar.HORIZONS


def test_a_legacy_row_without_the_1s_key_is_padded_not_wiped():
    # Rows written before the 1-session horizon existed carry fwd {5,10,20}.
    # A missing key must read as "unstamped" (filled next run) — and stamping
    # the new horizon must never disturb the frozen old ones.
    led = ar._fresh()
    ar.ingest(led, [_entry(date="2026-08-01T05:00:00+00:00")])
    e = led["entries"][0]
    del e["fwd"]["1"]                              # simulate the legacy shape
    e["fwd"]["5"] = 0.123                          # a frozen old stamp
    want = ar.wanting_prices(led, dt.date(2026, 12, 1))
    assert "BHP.AX" in want, "a missing horizon key means unstamped, so prices are wanted"
    ar.stamp(led, _frames("BHP.AX", n=30), want)
    assert abs(e["fwd"]["1"] - 0.01) < 1e-9        # close 101/100 - 1
    assert e["fwd"]["5"] == 0.123, "the frozen 5s stamp must not move"


def test_crypto_session_day_is_the_UTC_calendar():
    # config.MARKETS crypto tz is UTC; the ledger key must agree (a Melbourne
    # day here would split one crypto session across two identities).
    e = _entry(market="crypto", date="2026-08-01T23:30:00+00:00")
    assert ar.entry_key(e).startswith("2026-08-01|crypto")


# ── context enrichment (batch-100 WS-A) ──────────────────────────────────────

def test_enrich_is_blank_only_and_day_honest(monkeypatch):
    led = ar._fresh()
    ar.ingest(led, [_entry(ticker="BHP", market="asx", date="2026-08-01T05:00:00+00:00"),
                    _entry(ticker="OLD", market="asx", date="2026-07-15T05:00:00+00:00")])
    monkeypatch.setattr(ar, "_load_sectors", lambda: {("asx", "BHP"): "Materials",
                                                      ("asx", "OLD"): "Energy"})
    monkeypatch.setattr(ar, "_breadth_series", lambda: {"asx": {"2026-08-01": 0.4321}})
    # The scan join carries ITS OWN day — only same-day entries may take it.
    monkeypatch.setattr(ar, "_scan_day_rows", lambda: {
        ("asx", "2026-08-01"): {"BHP": {"grade_raw": "A+", "score": 9, "is_product": False}}})
    n = ar.enrich(led)
    bhp, old = led["entries"]
    assert bhp["sector"] == "Materials" and old["sector"] == "Energy"
    assert bhp["breadth200"] == 0.4321
    assert "breadth200" not in old or old.get("breadth200") is None, \
        "no breadth row for 2026-07-15 in the fixture - never guessed"
    assert bhp["grade_raw"] == "A+" and bhp["score"] == 9 and bhp["is_product"] is False
    assert old.get("grade_raw") is None, "a different-day scan must never stamp grades backwards"
    assert n == 6
    # Frozen once written: a second pass with DIFFERENT sources changes nothing.
    monkeypatch.setattr(ar, "_load_sectors", lambda: {("asx", "BHP"): "Tech"})
    monkeypatch.setattr(ar, "_breadth_series", lambda: {"asx": {"2026-08-01": 0.9}})
    monkeypatch.setattr(ar, "_scan_day_rows", lambda: {
        ("asx", "2026-08-01"): {"BHP": {"grade_raw": "B+", "score": 1, "is_product": True}}})
    assert ar.enrich(led) == 0
    assert bhp["sector"] == "Materials" and bhp["breadth200"] == 0.4321 and bhp["grade_raw"] == "A+"


def test_enrichment_counts_as_a_change_for_the_commit_gate():
    src = SRC
    assert "added or enriched or stamped or dropped" in src, \
        "an enrichment-only run must commit, not print UNCHANGED"


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


def test_workflow_stages_one_path_per_call_and_asserts_both_ledgers():
    assert 'git add -- data/alert_forward_returns.json' in WF
    assert 'git add -- data/edge_rosters.json' in WF
    assert 'assert_staged.sh "edge ledgers" data/alert_forward_returns.json data/edge_rosters.json' in WF


def test_workflow_skips_commit_only_when_BOTH_ledgers_are_unchanged():
    # One changed ledger must still commit — the && is the load-bearing bit.
    block = WF[WF.index("grep -q ALERT_RETURNS_UNCHANGED"):]
    head = block.split("git config")[0]
    assert "EDGE_ROSTERS_UNCHANGED" in head and "&&" in head


def test_workflow_is_outside_the_scan_mutex_and_watchdogged():
    assert "group: scan" not in WF
    assert not re.search(r"^\s*concurrency:", WF, re.M)
    from scanner import config
    assert "alert_returns.yml" in config.WATCHDOG_RUNS, \
        "a workflow that commits data needs a WATCHDOG_RUNS entry (CLAUDE.md)"


def test_workflow_has_pipefail_on_the_tee():
    assert "set -o pipefail" in WF


# ── completed bars only (2026-10-05) ─────────────────────────────────────────
# Yahoo's daily series carries the session's still-forming bar, the ledger's
# runs land 00:00-03:00 UTC (inside the ASX session in AEST and AEDT alike),
# and a stamp is frozen at first measurement. So every instant below is built
# from a market-local wall clock through zoneinfo: no offset is typed here.

SYD, NY, UTC = ZoneInfo("Australia/Sydney"), ZoneInfo("America/New_York"), dt.timezone.utc


def _at(tz, *ymdhm):
    """A market-local wall-clock time, as the aware UTC instant a run sees."""
    return dt.datetime(*ymdhm, tzinfo=tz).astimezone(UTC)


def _bars(sym, closes: dict):
    """{sym: frame} from {iso day: close} - a Yahoo daily frame's shape."""
    idx = pd.to_datetime(sorted(closes))
    return {sym: pd.DataFrame({"Close": [closes[d] for d in sorted(closes)]}, index=idx)}


def _one(market, ticker, base_day):
    led = ar._fresh()
    led["entries"].append({"key": f"{base_day}|{market}|{ticker}|long|2", "market": market,
                           "ticker": ticker, "side": "long", "base_day": base_day,
                           "base_close": None, "fwd": {str(h): None for h in ar.HORIZONS}})
    return led, led["entries"][0]


@pytest.mark.parametrize("market,now,cutoff,why", [
    ("asx", _at(SYD, 2026, 9, 30, 11, 21), "2026-09-30", "AEST mid-session: today's bar is forming"),
    ("asx", _at(SYD, 2026, 9, 30, 16, 44), "2026-09-30", "AEST, the auction print not yet on the feed"),
    ("asx", _at(SYD, 2026, 9, 30, 16, 45), "2026-10-01", "AEST, from the finality time today is final"),
    ("asx", _at(SYD, 2026, 10, 5, 10, 50), "2026-10-05", "AEDT: an on-time 23:50 UTC backstop is IN session"),
    ("asx", _at(SYD, 2026, 10, 5, 9, 20), "2026-10-05", "AEDT pre-open: today's bar does not count either"),
    ("nasdaq", _at(NY, 2026, 10, 5, 15, 0), "2026-10-05", "EDT mid-session"),
    ("nasdaq", _at(NY, 2026, 10, 5, 18, 20), "2026-10-06", "EDT: the 22:20 UTC primary is post-close"),
    ("nasdaq", _at(NY, 2026, 11, 2, 16, 29), "2026-11-02", "EST, one minute before finality"),
    ("nasdaq", _at(NY, 2026, 11, 2, 17, 20), "2026-11-03", "EST: the 22:20 UTC primary is post-close"),
    ("crypto", _at(UTC, 2026, 10, 5, 23, 59), "2026-10-05", "24/7: today's UTC bar is never final"),
    ("crypto", _at(UTC, 2026, 10, 6, 0, 1), "2026-10-06", "the new UTC day closed yesterday's bar"),
    ("nowhere", _at(UTC, 2026, 10, 5, 23, 59), "2026-10-05", "an unknown market gets the strict answer"),
])
def test_the_final_bar_cutoff_is_judged_in_each_markets_own_zone(market, now, cutoff, why):
    assert ar.final_bar_cutoff(market, now).isoformat() == cutoff, why


def test_every_session_market_has_a_finality_time_after_its_delayed_close():
    """The finality table lives in config (rule 3) and has two ways to rot:
    a stock market added without an entry would be read as 24/7 (merely
    strict), and an entry before the close + the delayed feed would read the
    forming bar again. 24/7 markets must have NO entry."""
    from scanner import config
    final = config.ALERT_RETURNS_BAR_FINAL
    assert set(final) <= set(config.MARKETS)
    for m, sess in config.VIVEK_JOURNAL_SESSION.items():
        if sess is None:
            assert m not in final, f"{m} trades 24/7 - its today's bar is never final"
            continue
        delayed_close = sess[2] * 60 + sess[3] + config.VIVEK_JOURNAL_FEED_DELAY_MIN
        h, mi = final[m]
        assert h * 60 + mi >= delayed_close, f"{m}: final before the delayed close"


def test_the_audits_ARR_case_is_never_frozen_at_an_intraday_price():
    """The audit's own example: commit 262caf9d stamped ARR base 2026-09-29 at
    Wed 2026-09-30 11:21 Sydney, reading Wednesday's half-formed bar (0.37) as
    its 1-session close - +2.78%, frozen - while Wednesday really closed 0.355
    (-1.39%, the sign flipped)."""
    led = ar._fresh()
    ar.ingest(led, [_entry(ticker="ARR", date="2026-09-29T03:00:00+00:00")])
    e = led["entries"][0]
    assert e["base_day"] == "2026-09-29"
    tape = {"2026-09-25": 0.35, "2026-09-28": 0.355, "2026-09-29": 0.36}
    now = _at(SYD, 2026, 9, 30, 11, 21)
    want = ar.wanting_prices(led, now.date())
    assert "ARR.AX" in want, "the UTC-age prefilter does ask for it - stamp() must refuse"
    ar.stamp(led, _bars("ARR.AX", {**tape, "2026-09-30": 0.37}), want, now)
    assert e["base_close"] == 0.36, "Tuesday's bar is complete - the base may be read"
    assert e["fwd"]["1"] is None, "Wednesday's bar is still forming at 11:21 Sydney"
    # Next morning Wednesday is final; Thursday's forming bar is ignored.
    now2 = _at(SYD, 2026, 10, 1, 11, 21)
    ar.stamp(led, _bars("ARR.AX", {**tape, "2026-09-30": 0.355, "2026-10-01": 0.40}),
             ar.wanting_prices(led, now2.date()), now2)
    assert e["fwd"]["1"] == round(0.355 / 0.36 - 1.0, 6) < 0


def test_a_forming_bar_is_never_read_as_the_BASE_either():
    # A Saturday alert's base is the next session's bar: Monday's, still
    # forming at 12:03 Monday Sydney (AEDT).
    led, e = _one("asx", "BHP", "2026-10-03")
    tape = {"2026-10-02": 40.0, "2026-10-05": 41.0}
    assert ar.stamp(led, _bars("BHP.AX", tape), {"BHP.AX": [e]}, _at(SYD, 2026, 10, 5, 12, 3)) == 0
    assert e["base_close"] is None
    ar.stamp(led, _bars("BHP.AX", tape), {"BHP.AX": [e]}, _at(SYD, 2026, 10, 5, 17, 0))
    assert e["base_close"] == 41.0, "once final, the same bar is the base"


def test_the_long_horizons_share_the_guard():
    # Mon 2026-09-07 + 20 sessions = Mon 2026-10-05 (no ASX holiday between).
    days = pd.bdate_range("2026-09-07", "2026-10-05")
    assert len(days) == 21
    tape = {d.date().isoformat(): 100.0 + i for i, d in enumerate(days)}
    led, e = _one("asx", "BHP", "2026-09-07")
    ar.stamp(led, _bars("BHP.AX", tape), {"BHP.AX": [e]}, _at(SYD, 2026, 10, 5, 12, 3))
    assert e["fwd"]["10"] is not None and e["fwd"]["20"] is None
    ar.stamp(led, _bars("BHP.AX", tape), {"BHP.AX": [e]}, _at(SYD, 2026, 10, 5, 16, 45))
    assert e["fwd"]["20"] == 0.2


def test_a_post_close_nasdaq_run_still_stamps_the_days_own_bar():
    """The guard must not starve the market whose runs land after its close:
    the 22:20 UTC primary is 18:20 EDT, and Monday's bar is final by then."""
    led, e = _one("nasdaq", "AAPL", "2026-10-02")
    tape = {"2026-10-01": 99.0, "2026-10-02": 100.0, "2026-10-05": 103.0}
    ar.stamp(led, _bars("AAPL", tape), {"AAPL": [e]}, _at(UTC, 2026, 10, 5, 22, 20))
    assert e["fwd"]["1"] == 0.03


def test_crypto_never_reads_todays_UTC_bar():
    led, e = _one("crypto", "BTC", "2026-10-04")
    tape = {"2026-10-04": 100.0, "2026-10-05": 104.0}
    ar.stamp(led, _bars("BTC-USD", tape), {"BTC-USD": [e]}, _at(UTC, 2026, 10, 5, 23, 59))
    assert e["base_close"] == 100.0 and e["fwd"]["1"] is None
    ar.stamp(led, _bars("BTC-USD", tape), {"BTC-USD": [e]}, _at(UTC, 2026, 10, 6, 0, 5))
    assert e["fwd"]["1"] == 0.04


def test_main_judges_finality_on_a_clock_taken_BEFORE_the_download(tmp_path, monkeypatch):
    """A bar fetched at 16:44 is not made final by a stamp at 16:46: main()
    hands stamp() the instant it asked for prices, never a later one."""
    import time as _time
    import scanner.data
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"entries": [_entry(date="2026-08-01T05:00:00+00:00")]}), encoding="utf-8")
    monkeypatch.setattr(ar, "HISTORY", str(hist))
    monkeypatch.setattr(ar, "LEDGER", str(tmp_path / "ledger.json"))
    seen = {}

    def download(syms, period=None):
        seen["asked"] = _time.time()
        return {}

    def stamp(led, frames, want, now=None):
        seen["now"] = now
        return 0

    monkeypatch.setattr(scanner.data, "download", download)
    monkeypatch.setattr(ar, "stamp", stamp)
    assert ar.main(["--dry-run"]) == 0
    assert seen["now"] is not None and seen["now"].tzinfo is not None, "stamp() got no clock"
    assert seen["now"].timestamp() <= seen["asked"], "the clock was read after the download"


# ── the backstop gate, EXECUTED (2026-10-05) ─────────────────────────────────
# The old gate counted scheduled successes created since 00:00 UTC. Both crons
# land hours late, so on 2026-10-05 that query already returned the Oct-4
# slot's late primary (01:01Z) and its backstop skip-run (02:25Z): an on-time
# Oct-5 backstop would have skipped a day whose 22:20 never ran. The gate now
# asks whether a pass LANDED ON MAIN since the most recent 22:00 UTC.

BACKSTOP = "50 23 * * *"
LEDGERS = ("data/alert_forward_returns.json", "data/edge_rosters.json")
BASH, GIT, REAL_DATE = shutil.which("bash"), shutil.which("git"), shutil.which("date")


def _gnu_date() -> bool:
    if not REAL_DATE:
        return False
    p = subprocess.run([REAL_DATE, "-u", "-d", "@0", "+%Y"], capture_output=True, text=True)
    return p.returncode == 0 and p.stdout.strip() == "1970"


needs_shell = pytest.mark.skipif(not (BASH and GIT and _gnu_date()),
                                 reason="bash, git and GNU date run the gate")

# What the Actions API really answered on 2026-10-05 for "scheduled successes
# created since 00:00 UTC": the Oct-4 slot's late runs. A stub `curl` serves
# it, so a gate that still trusts that question is caught believing it.
API_ANSWER = {"workflow_runs": [
    {"id": 1, "event": "schedule", "conclusion": "success", "created_at": "2026-10-05T01:01:04Z"},
    {"id": 2, "event": "schedule", "conclusion": "success", "created_at": "2026-10-05T02:25:49Z"}]}


def _gate_body() -> str:
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(WF)["jobs"]["returns"]["steps"]
    gate = [s for s in steps if s.get("id") == "gate"]
    assert len(gate) == 1
    env = {k: v for k, v in (gate[0].get("env") or {}).items() if k != "GH_TOKEN"}
    assert env == {"SCHEDULE": "${{ github.event.schedule }}"}, gate[0].get("env")
    assert "${{" not in gate[0]["run"], "the gate reads env, so it can be executed verbatim"
    return gate[0]["run"]


def _sh(tmp_path, now: dt.datetime, ledgers: dict, origin: bool = True):
    """A bare file:// origin whose main carries `ledgers` ({path: text}), and
    the shape actions/checkout leaves (init + remote): the gate's own fetch
    must bring main in. `date` answers from `now`; `curl` serves API_ANSWER."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("", encoding="utf-8")
    epoch = int(now.timestamp())
    (bin_ / "date").write_text(f'#!/usr/bin/env bash\nexec "{REAL_DATE}" -d "@{epoch}" "$@"\n')
    curl_log = tmp_path / "curl.log"
    (bin_ / "curl").write_text(f"#!/usr/bin/env bash\necho \"$*\" >> \"{curl_log}\"\n"
                               f"echo '{json.dumps(API_ANSWER)}'\n")
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = {"PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(home),
           "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GITHUB_REPOSITORY": "owner/repo",
           "LC_ALL": "C", "TZ": "Australia/Sydney"}     # a runner's TZ must not matter

    def run(*args, cwd):
        p = subprocess.run([GIT, *args], cwd=cwd, env=env, capture_output=True, text=True)
        assert p.returncode == 0, p.stderr

    work = tmp_path / "work"
    run("init", "-q", str(work), cwd=tmp_path)
    if origin:
        bare, seed = tmp_path / "origin.git", tmp_path / "seed"
        run("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
        run("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
        for rel, text in {"README": "x\n", **ledgers}.items():
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_text(text, encoding="utf-8")
        run("add", "-A", cwd=seed)
        run("commit", "-q", "-m", "seed", cwd=seed)
        run("push", "-q", bare.resolve().as_uri(), "main", cwd=seed)
        run("remote", "add", "origin", bare.resolve().as_uri(), cwd=work)
    return env, work, curl_log


def _gate(tmp_path, now, ledgers, schedule=BACKSTOP, origin=True):
    env, work, curl_log = _sh(tmp_path, now, ledgers, origin)
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    script = tmp_path / "gate.sh"
    script.write_text(_gate_body(), encoding="utf-8")
    p = subprocess.run([BASH, "-e", str(script)], cwd=work, capture_output=True, text=True,
                       timeout=60, env=dict(env, GITHUB_OUTPUT=str(out), SCHEDULE=schedule))
    assert p.returncode == 0, p.stdout + p.stderr
    outputs = dict(l.split("=", 1) for l in out.read_text(encoding="utf-8").splitlines() if "=" in l)
    called_api = curl_log.exists() and curl_log.read_text(encoding="utf-8").strip() != ""
    return outputs, p.stdout + p.stderr, called_api


def _ledger(updated_at):
    return json.dumps({"schema_version": 1, "updated_at": updated_at, "entries": []})


def _both(updated_at):
    return {p: _ledger(updated_at) for p in LEDGERS}


@needs_shell
def test_an_on_time_backstop_is_NOT_fooled_by_the_previous_slots_late_runs(tmp_path):
    """The audit's scenario on 2026-10-05: the Oct-4 slot's pass landed at
    01:03Z, the Oct-5 22:20 is dropped, its 23:50 backstop fires on time. The
    API (stubbed with its real answer) says two scheduled runs succeeded
    'today'; the backstop must still run."""
    out, log, called_api = _gate(tmp_path, _at(UTC, 2026, 10, 5, 23, 50),
                                 _both("2026-10-05T01:03:17+00:00"))
    assert out == {"run": "true"}, log
    assert not called_api, "a scheduled 'success' includes skip-runs - the gate must not ask"


@pytest.mark.parametrize("now,stamps,expect,why", [
    (_at(UTC, 2026, 10, 5, 23, 50), ("2026-10-05T22:24:02+00:00",) * 2, "false",
     "on time: the 22:20 pass landed on main"),
    (_at(UTC, 2026, 10, 6, 2, 25), ("2026-10-06T01:01:30+00:00",) * 2, "false",
     "both crons late (the observed norm): this slot's own late pass counts"),
    (_at(UTC, 2026, 10, 6, 2, 25), ("2026-10-05T01:03:17+00:00",) * 2, "true",
     "late backstop, this slot never landed - the calendar date is not the slot"),
    (_at(UTC, 2026, 10, 5, 23, 50), ("2026-10-05T01:03:17+00:00", "2026-10-05T22:31:00+00:00"), "false",
     "the NEWEST ledger write decides"),
    (_at(UTC, 2026, 10, 5, 22, 0), ("2026-10-05T22:00:00+00:00",) * 2, "false",
     "the slot boundary is inclusive"),
    (_at(UTC, 2026, 10, 5, 22, 0), ("2026-10-05T21:59:59+00:00",) * 2, "true",
     "one second before the slot opened is the previous slot"),
])
@needs_shell
def test_the_backstop_is_anchored_on_the_22_00_UTC_slot(tmp_path, now, stamps, expect, why):
    ledgers = dict(zip(LEDGERS, (_ledger(s) for s in stamps)))
    out, log, _ = _gate(tmp_path, now, ledgers)
    assert out == {"run": expect}, (why, log)


@pytest.mark.parametrize("ledgers,origin,why", [
    ({}, True, "no ledger on main at all"),
    ({LEDGERS[0]: "{not json", LEDGERS[1]: "[]"}, True, "corrupt / wrong-shaped ledgers"),
    ({LEDGERS[0]: _ledger(""), LEDGERS[1]: json.dumps({"entries": []})}, True,
     "a blank or missing updated_at"),
    (_both("2026-10-05T22:24:02+00:00"), False, "origin unreachable - nothing can be read"),
])
@needs_shell
def test_the_gate_fails_OPEN(tmp_path, ledgers, origin, why):
    out, log, _ = _gate(tmp_path, _at(UTC, 2026, 10, 5, 23, 50), ledgers, origin=origin)
    assert out == {"run": "true"}, (why, log)


@pytest.mark.parametrize("schedule", ["20 22 * * *", ""])
@needs_shell
def test_every_trigger_but_the_backstop_cron_runs_unconditionally(tmp_path, schedule):
    # The primary cron and a manual dispatch (empty schedule) never consult
    # main - not even with a pass already on it.
    out, log, _ = _gate(tmp_path, _at(UTC, 2026, 10, 5, 22, 20),
                        _both("2026-10-05T22:20:30+00:00"), schedule=schedule)
    assert out == {"run": "true"}, log


def test_the_gates_cron_literal_is_the_backstop_in_the_schedule():
    """The gate recognises the backstop by its cron STRING: edited without
    the schedule, the backstop silently becomes an always-run (or the primary
    gets gated). And the gate needs no Actions API, so no `actions: read`."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WF)
    on = doc.get("on") or doc[True]
    crons = [c["cron"] for c in on["schedule"]]
    assert crons == ["20 22 * * *", BACKSTOP], crons
    assert f'"{BACKSTOP}"' in _gate_body()
    assert doc["permissions"] == {"contents": "write"}, doc["permissions"]

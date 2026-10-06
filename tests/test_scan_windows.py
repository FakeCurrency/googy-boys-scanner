"""THE SCAN SCHEDULE -- market hours only, verified in every DST regime.

Owner, 2026-09-21: "lets turn off NASDAQ and ASX scans after market closing
moving forward"; first scan an hour after the open, last at the close; crypto
hourly, seven days.

The crons in scan.yml are a deliberate superset and the gate job decides, in
each market's own calendar, which markets a run scans. Since 2026-10-05 that
decision is ONE stdlib-only script, scripts/scan_gate.py, which reads config
directly -- so these tests drive the real decision instead of a re-typed copy,
and there is no inline window table left to drift.

Two defects this file now pins, both found checking the schedule after the
2026-10-04 switch to AEDT:
  * the :47 closing backstops could never run. They land at 16:47 local and
    the old gate only scanned inside the 11:00/10:30 .. 16:45 window, so in
    every regime they were skipped as "outside every session".
  * a heartbeat heal rescanned ALL three markets whatever the hour: the old
    gate waved every dispatch through and the scan step read the heal's
    `market=all` input before the gate's answer. 65 of the 83 heal-started ASX
    scans from 28 Sep to 5 Oct ran with the ASX shut.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import re
import subprocess
from zoneinfo import ZoneInfo

import pytest
import yaml

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
SCAN = (WF / "scan.yml").read_text(encoding="utf-8")
GATE_PATH = ROOT / "scripts" / "scan_gate.py"
_spec = importlib.util.spec_from_file_location("scan_gate", GATE_PATH)
GATE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GATE)

UTC = dt.timezone.utc
LAND = dt.timedelta(minutes=10)      # a scan's stamp, minutes after its cron


def _load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _crons(name) -> list[str]:
    on = _load(name)[True]          # PyYAML reads the `on:` key as the bool True
    return [c["cron"] for c in on["schedule"]]


def _hours(field: str) -> list[int]:
    out: list[int] = []
    for part in field.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def _fires(cron: str, day: dt.date) -> list[dt.datetime]:
    """Every UTC instant this cron fires on a given UTC date."""
    minute, hours, _dom, _mon, dow = cron.split()
    lo, hi = (int(x) for x in dow.split("-")) if "-" in dow else (int(dow), int(dow))
    # cron day-of-week: 1=Mon..5=Fri; python weekday(): 0=Mon..4=Fri
    if not (lo - 1 <= day.weekday() <= hi - 1):
        return []
    return [dt.datetime(day.year, day.month, day.day, h, int(minute), tzinfo=UTC)
            for h in _hours(hours)]


def _local(market: str, t: dt.datetime) -> dt.datetime:
    return t.astimezone(ZoneInfo(config.MARKET_SCAN_WINDOWS[market][0]))


def scans_on(day: dt.date, keep=lambda t, cron: True) -> list[tuple[str, str]]:
    """[(market, local HH:MM), ...] the schedule delivers over the UTC day
    `day` if every cron fires on time, except those `keep` rejects (a dropped
    cron). Each scan stamps the market LAND minutes after its cron, and the
    gate sees every earlier stamp -- the backstops depend on exactly that.
    Both markets start the day stamped 00:00 UTC: after New York's previous
    close (so yesterday is covered) and before Sydney's next one."""
    start = dt.datetime(day.year, day.month, day.day, tzinfo=UTC)
    last = {m: start for m in GATE.STOCK}
    fires = sorted((t, cron) for cron in _crons("scan.yml")
                   for t in _fires(cron, day) if keep(t, cron))
    out = []
    for t, cron in fires:
        markets, _why = GATE.decide("schedule", cron, "", "", t, last)
        for m in markets:
            last[m] = t + LAND
            out.append((m, _local(m, t).strftime("%H:%M")))
    return sorted(out)


# Sydney and New York change daylight saving on DIFFERENT dates, so a year
# holds three regimes (AEST + EST never happens: Sydney's winter is New York's
# summer) and the AEDT + EDT overlap happens twice, in October and in March.
# Each one moves a session's UTC hours independently of the other.
DAYS = {
    "AEST + EDT (Sep)":  dt.date(2026, 9, 16),
    "AEDT + EDT (Oct)":  dt.date(2026, 10, 21),
    "AEDT + EST (Dec)":  dt.date(2026, 12, 16),
    "AEDT + EDT (Mar)":  dt.date(2027, 3, 24),
}


# ── the gate is the script, and the script reads config ─────────────────────

def _gate_job() -> dict:
    return _load("scan.yml")["jobs"]["gate"]


def _check_step() -> dict:
    return next(s for s in _gate_job()["steps"] if s.get("id") == "check")


def test_the_gate_job_runs_the_script_and_carries_no_window_table_of_its_own():
    run = _check_step()["run"]
    assert "python3 scripts/scan_gate.py" in run
    assert "ZoneInfo" not in run and "16*60" not in run, \
        "an inline window table is back in scan.yml's gate -- it belongs in config"


def test_the_gate_follows_config_rather_than_a_copy_of_it(monkeypatch):
    """Move both tables and the gate must move with them. (A source-text
    check would pass on the docstring, which names both tables.)"""
    tue_1230_utc = _t("2026-10-06T12:30:00+00:00")       # 23:30 AEDT, 08:30 EDT
    assert not GATE.in_session("asx", tue_1230_utc)
    monkeypatch.setitem(config.MARKET_SCAN_WINDOWS, "asx",
                        ("Australia/Sydney", 23 * 60, 23 * 60 + 45))
    assert GATE.in_session("asx", tue_1230_utc)
    nyc_1710 = _t("2026-10-05T21:10:00+00:00")            # Mon 17:10 EDT
    stamp = {"nasdaq": _t("2026-10-05T21:00:00+00:00")}    # 17:00 EDT
    assert not GATE.missed_close("nasdaq", nyc_1710, stamp["nasdaq"])
    monkeypatch.setitem(config.MORNING_PLAYS_SLOT_GATE, "us",
                        {"market": "nasdaq", "tz": "America/New_York", "hour": 17, "minute": 5})
    assert GATE.missed_close("nasdaq", nyc_1710, stamp["nasdaq"])


@pytest.mark.parametrize("market,before,after,backstop", [
    # A scan stamped 16:32 Sydney is NOT the closing scan: the auction prints
    # ~16:10-16:12 but Yahoo's ASX feed shows it ~20 min late. 16:32:36 is the
    # real 2026-10-05 stamp whose prices were still pre-auction on 19% of names
    # (download from 16:28:52); the digest and the gate wait for 16:40.
    ("asx", "2026-10-06T05:32:36+00:00", "2026-10-06T05:41:00+00:00", "2026-10-06T05:47:00+00:00"),
    # New York's gate is 16:05, not later (the winter 21:07 UTC scan is 16:07).
    ("nasdaq", "2026-10-05T20:02:00+00:00", "2026-10-05T20:06:00+00:00", "2026-10-05T20:47:00+00:00"),
])
def test_the_closing_scan_is_the_digests_close_not_the_bell(market, before, after, backstop):
    cron = "47 5,6 * * 1-5" if market == "asx" else "47 20,21 * * 1-5"
    assert GATE.decide("schedule", cron, "", "", _t(backstop), {market: _t(before)})[0] == [market]
    assert GATE.decide("schedule", cron, "", "", _t(backstop), {market: _t(after)})[0] == []


def test_the_gate_script_imports_only_the_standard_library_and_config():
    """It runs on the runner's own python3, before any pip install."""
    src = GATE_PATH.read_text(encoding="utf-8")
    mods = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert mods <= {"__future__", "argparse", "datetime", "json", "pathlib", "sys",
                    "zoneinfo", "scanner"}, mods
    cfg = (ROOT / "scanner" / "config.py").read_text(encoding="utf-8")
    assert set(re.findall(r"^(?:from|import)\s+([\w.]+)", cfg, re.M)) <= {"dataclasses"}


def test_the_gate_checkout_carries_every_file_the_script_reads_and_cannot_hang():
    """A sparse checkout: a renamed file must fail here, not as a gate that
    silently falls back to fail-open on every run. Its own timeout, because git
    has none: a stalled fetch that ran into the job's would skip the scan
    rather than fail open."""
    co = next(s for s in _gate_job()["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    paths = co["with"]["sparse-checkout"].split()
    assert co["with"]["ref"] == "${{ github.ref }}"
    assert co["continue-on-error"] is True
    assert co["timeout-minutes"] < _gate_job()["timeout-minutes"]
    for rel in paths:
        assert (ROOT / rel).is_file(), f"the gate checks out {rel}, which does not exist"
    for rel in ("scripts/scan_gate.py", "scanner/config.py"):
        assert rel in paths
    for m in GATE.STOCK:
        assert f"public/data/{m}_prices.json" in paths, \
            f"the gate cannot see when {m} was last scanned"


def _run_check_step(tmp_path, env, script=None):
    """Run the SHIPPED check step's shell under bash -e, as Actions does.
    `script` replaces scripts/scan_gate.py (None = absent, i.e. a failed
    checkout). Returns the GITHUB_OUTPUT lines."""
    if script is not None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "scan_gate.py").write_text(script, encoding="utf-8")
    out = tmp_path / "out"
    out.write_text("")
    full = {"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(out), **env}
    p = subprocess.run(["bash", "-e", "-c", _check_step()["run"]], cwd=tmp_path,
                       env=full, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    return out.read_text().splitlines()


def test_the_check_step_hands_the_script_every_input(tmp_path):
    """The heal fix lives in one flag: drop `--reason` and a heal is a manual
    dispatch again, rescanning every market at any hour. So the shipped shell
    is run with a stub that echoes what it was given."""
    env = _check_step()["env"]
    assert env == {"EVENT": "${{ github.event_name }}", "SCHED": "${{ github.event.schedule }}",
                   "REASON": "${{ github.event.inputs.reason }}",
                   "MARKET": "${{ github.event.inputs.market }}"}
    stub = ("import sys\nprint('run=true')\nprint('markets=' + '|'.join(sys.argv[1:]))\n")
    got = _run_check_step(tmp_path, {"EVENT": "workflow_dispatch", "SCHED": "",
                                     "REASON": "heartbeat", "MARKET": "all"}, stub)
    assert got == ["run=true",
                   "markets=--event|workflow_dispatch|--schedule||--reason|heartbeat|--market|all"]


@pytest.mark.parametrize("event,market,want", [
    ("schedule", "", "asx nasdaq"),                        # a schedule never scans crypto
    ("workflow_dispatch", "all", "asx nasdaq crypto"),
    ("workflow_dispatch", "asx", "asx"),
])
def test_a_gate_crash_fails_open_not_shut(tmp_path, event, market, want):
    got = _run_check_step(tmp_path, {"EVENT": event, "SCHED": "", "REASON": "", "MARKET": market})
    assert got == ["run=true", f"markets={want}"]


def test_the_scan_step_scans_what_the_gate_said_not_what_the_dispatch_asked():
    """The heartbeat dispatches market=all. The old scan step read that input
    BEFORE the gate's answer, so a heal scanned every market whatever the
    hour. The input may now reach only the gate."""
    steps = _load("scan.yml")["jobs"]["scan"]["steps"]
    run = next(s for s in steps if str(s.get("name", "")).startswith("Run market scans"))
    assert run["env"]["MARKETS"] == "${{ needs.gate.outputs.markets }}"
    assert _load("scan.yml")["jobs"]["scan"]["if"] == "needs.gate.outputs.run == 'true'"
    scan_job = SCAN.split("\n  scan:\n", 1)[1]
    assert "inputs.market" not in scan_job and "market_override" not in SCAN


def test_the_closing_crons_in_the_script_are_the_ones_in_scan_yml():
    crons = _crons("scan.yml")
    for c in GATE.CLOSING_CRONS:
        assert c in crons, f"scan_gate.CLOSING_CRONS names {c!r}, which scan.yml no longer has"
    assert {c for c in crons if c.split()[0] in ("41", "47")} == set(GATE.CLOSING_CRONS)


def test_the_windows_are_open_plus_one_hour_to_after_the_close():
    asx_tz, asx_lo, asx_hi = config.MARKET_SCAN_WINDOWS["asx"]
    nas_tz, nas_lo, nas_hi = config.MARKET_SCAN_WINDOWS["nasdaq"]
    assert asx_lo == 11 * 60, "ASX opens 10:00; the owner asked for the first scan an hour after"
    assert nas_lo == 9 * 60 + 30 + 60, "NASDAQ opens 09:30; first scan is an hour after"
    # The tails must clear the closing auction, or the Discord digest never sends.
    gate_asx = config.MORNING_PLAYS_SLOT_GATE["asx"]
    gate_us = config.MORNING_PLAYS_SLOT_GATE["us"]
    assert asx_hi > gate_asx["hour"] * 60 + gate_asx["minute"], (
        "the ASX window closes before the auction print the plays digest gates on — "
        "the afternoon Discord ping would never fire again")
    assert nas_hi > gate_us["hour"] * 60 + gate_us["minute"]


def test_the_two_windows_can_never_overlap_in_utc():
    """If they could, one scheduled run would scan two stock markets."""
    for day in DAYS.values():
        for minute in range(0, 24 * 60, 5):
            t = dt.datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=UTC)
            hits = [m for m in GATE.STOCK if GATE.in_session(m, t)]
            assert len(hits) <= 1, f"{t} is inside {hits}"


# ── what the schedule actually delivers ──────────────────────────────────────

@pytest.mark.parametrize("label", sorted(DAYS))
def test_every_weekday_gets_a_full_session_of_scans_in_every_dst_regime(label):
    got = scans_on(DAYS[label])
    asx = sorted(t for m, t in got if m == "asx")
    nas = sorted(t for m, t in got if m == "nasdaq")

    assert asx, f"{label}: no ASX scan at all"
    assert nas, f"{label}: no NASDAQ scan at all"
    # First scan is at/after open+1h, last is at/after the close — that IS the ask.
    assert asx[0] <= "11:40", f"{label}: first ASX scan is {asx[0]}, too far past the open"
    assert asx[-1] >= "16:30", f"{label}: last ASX scan is {asx[-1]}, before the 16:30 close scan"
    assert nas[0] <= "11:10", f"{label}: first NASDAQ scan is {nas[0]}"
    assert nas[-1] >= "16:00", f"{label}: last NASDAQ scan is {nas[-1]}, no post-close scan"
    # ...and with the closing scan landed, nothing outside the window.
    assert all("11:00" <= t <= "16:45" for t in asx), f"{label}: out-of-window ASX scans: {asx}"
    assert all("10:30" <= t <= "16:45" for t in nas), f"{label}: out-of-window NASDAQ scans: {nas}"


@pytest.mark.parametrize("label", sorted(DAYS))
def test_a_full_session_is_covered_roughly_hourly(label):
    """Not a cadence promise -- GitHub's scheduler is best-effort -- but a
    session must not have a multi-hour hole where a trigger could be missed."""
    for market in ("asx", "nasdaq"):
        times = sorted(t for m, t in scans_on(DAYS[label]) if m == market)
        mins = [int(t[:2]) * 60 + int(t[3:]) for t in times]
        gaps = [b - a for a, b in zip(mins, mins[1:])]
        assert not gaps or max(gaps) <= 75, f"{label} {market}: {max(gaps)}min hole in {times}"


@pytest.mark.parametrize("label", sorted(DAYS))
@pytest.mark.parametrize("market", ["asx", "nasdaq"])
def test_a_missed_closing_scan_is_caught_up_exactly_once_by_the_backstop(label, market):
    """The defect: the :47 backstops land at 16:47 local, past the window, and
    the old gate skipped them as out of session in EVERY regime. Drop the
    crons between the bell and the end of the window (the 16:07 hourly and
    the 16:30 closing slot) and the first cron after the close -- the :47
    backstop -- catches the close up; every later cron stays quiet."""
    def keep(t, cron):
        return not 16 * 60 <= _local(market, t).hour * 60 + _local(market, t).minute <= 16 * 60 + 45

    late = [t for m, t in scans_on(DAYS[label], keep) if m == market and t >= "16:00"]
    assert late == ["16:47"], f"{label}: {market} after the close: {late}"


def test_no_stock_market_is_scanned_on_its_own_weekend():
    """Weekday UTC crons do reach local weekends: Friday 14:37 UTC is Saturday
    in Sydney and Monday 00:07 UTC is Sunday in New York. Nothing stamped, so
    every catch-up the gate could want is on offer."""
    for day in (dt.date(2026, 10, 9), dt.date(2026, 10, 12),     # Fri, Mon (AEDT+EDT)
                dt.date(2026, 12, 18), dt.date(2026, 12, 21)):   # Fri, Mon (AEDT+EST)
        for cron in _crons("scan.yml"):
            for t in _fires(cron, day):
                for m in GATE.decide("schedule", cron, "", "", t, {})[0]:
                    assert _local(m, t).weekday() < 5, (cron, t, m)
    assert not any(c.split()[-1].strip("*") in ("0,6", "6,0", "0", "6")
                   for c in _crons("scan.yml")), "a weekend cron is back in scan.yml"


def test_a_scheduled_run_scans_at_most_one_stock_market_and_never_crypto():
    """crypto_bot.yml owns crypto on a schedule. And a catch-up never rides
    with a live market: a failing catch-up leg would discard the live scan.
    Swept with NO stamps -- every catch-up on offer at every instant."""
    days = list(DAYS.values()) + [dt.date(2026, 10, 9), dt.date(2026, 10, 12)]
    for day in days:
        for minute in range(0, 24 * 60, 5):
            t = dt.datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=UTC)
            for cron in _crons("scan.yml"):
                markets, _ = GATE.decide("schedule", cron, "", "", t, {})
                assert "crypto" not in markets and len(markets) <= 1, (cron, t, markets)


def test_a_closing_cron_that_lands_mid_session_is_skipped_not_run():
    """Each closing slot exists twice, one per DST regime. Without the
    after-the-close guard the wrong one is an ordinary extra full scan an hour
    before the close -- two surplus ASX scans a day for half the year."""
    asx = [t for m, t in scans_on(DAYS["AEST + EDT (Sep)"]) if m == "asx"]
    assert "15:30" not in asx and "15:47" not in asx, asx
    nas = [t for m, t in scans_on(DAYS["AEDT + EST (Dec)"]) if m == "nasdaq"]
    assert "15:47" not in nas, nas


# ── who asked: heartbeat heals and manual dispatches ─────────────────────────

def _t(iso):
    return dt.datetime.fromisoformat(iso)


# (now UTC, last ASX scan, last NASDAQ scan, want) -- real calendar instants
HEALS = [
    # Mon 5 Oct 2026, 20:00 AEDT / 05:00 EDT: both shut, both closes covered
    ("2026-10-05T09:00:00+00:00", "2026-10-05T05:45:00+00:00", "2026-10-02T20:20:00+00:00", ["crypto"]),
    # ...but an ASX scan stamped 16:32 (pre-auction on Yahoo) did NOT cover it
    ("2026-10-05T09:00:00+00:00", "2026-10-05T05:32:36+00:00", "2026-10-02T20:20:00+00:00", ["asx", "crypto"]),
    # Sun 11 Oct, midday Sydney (Sat night New York): the weekend is crypto only
    ("2026-10-11T01:00:00+00:00", None, None, ["crypto"]),
    # Sat 10 Oct, midday Sydney = FRIDAY 21:00 New York: Friday's close counts
    ("2026-10-10T01:00:00+00:00", None, "2026-10-09T20:20:00+00:00", ["crypto"]),
    ("2026-10-10T01:00:00+00:00", None, "2026-10-09T19:10:00+00:00", ["nasdaq", "crypto"]),
    # Tue 6 Oct 13:00 AEDT: ASX in session
    ("2026-10-06T02:00:00+00:00", "2026-10-06T00:20:00+00:00", "2026-10-05T20:20:00+00:00", ["asx", "crypto"]),
    # ...and NASDAQ (21:00 Mon New York) still owes Monday's close: the live
    # market goes alone, the catch-up waits for a run with nothing live
    ("2026-10-06T01:00:00+00:00", "2026-10-06T00:20:00+00:00", "2026-10-05T19:10:00+00:00", ["asx", "crypto"]),
    # Mon 5 Oct 12:00 EDT: NASDAQ in session
    ("2026-10-05T16:00:00+00:00", "2026-10-05T05:35:00+00:00", "2026-10-05T14:50:00+00:00", ["nasdaq", "crypto"]),
    # Tue 6 Oct 18:00 AEDT: ASX shut, last scan 15:00 -> the missed closing scan
    ("2026-10-06T07:00:00+00:00", "2026-10-06T04:00:00+00:00", "2026-10-05T20:20:00+00:00", ["asx", "crypto"]),
    # ...also when it has never been scanned at all (no readable stamp)
    ("2026-10-06T07:00:00+00:00", None, "2026-10-05T20:20:00+00:00", ["asx", "crypto"]),
    # ...and once a scan has landed after the close, crypto only again
    ("2026-10-06T07:30:00+00:00", "2026-10-06T07:15:00+00:00", "2026-10-05T20:20:00+00:00", ["crypto"]),
    # Wed 16 Dec 2026 (EST): 17:30 New York, no NASDAQ scan since 15:10
    ("2026-12-16T22:30:00+00:00", "2026-12-16T05:35:00+00:00", "2026-12-16T20:10:00+00:00", ["nasdaq", "crypto"]),
]


@pytest.mark.parametrize("now,asx,nas,want", HEALS)
def test_a_heartbeat_heal_scans_crypto_plus_only_the_due_stock_market(now, asx, nas, want):
    last = {"asx": _t(asx) if asx else None, "nasdaq": _t(nas) if nas else None}
    markets, why = GATE.decide("workflow_dispatch", "", "heartbeat", "all", _t(now), last)
    assert markets == want, why


def test_a_heal_for_one_shut_stock_market_is_a_skip():
    markets, _ = GATE.decide("workflow_dispatch", "", "heartbeat", "asx",
                             _t("2026-10-05T09:00:00+00:00"),
                             {"asx": _t("2026-10-05T05:45:00+00:00")})
    assert markets == []


@pytest.mark.parametrize("market,want", [("all", ["asx", "nasdaq", "crypto"]),
                                         ("", ["asx", "nasdaq", "crypto"]),
                                         ("asx", ["asx"]), ("crypto", ["crypto"])])
def test_a_person_gets_exactly_what_they_asked_for_at_any_hour(market, want):
    sat = _t("2026-10-10T01:00:00+00:00")
    assert GATE.decide("workflow_dispatch", "", "manual", market, sat, {})[0] == want


def test_a_late_closing_cron_still_runs_when_nothing_landed_after_the_close():
    """GitHub delays crons by hours. A closing cron that lands at 17:10 local
    used to be skipped as out of session; it is now the catch-up."""
    t = _t("2026-10-06T06:10:00+00:00")                       # 17:10 AEDT
    before = {"asx": _t("2026-10-06T04:20:00+00:00")}          # 15:20
    after = {"asx": _t("2026-10-06T05:40:00+00:00")}           # 16:40
    assert GATE.decide("schedule", "41 5,6 * * 1-5", "", "", t, before)[0] == ["asx"]
    assert GATE.decide("schedule", "41 5,6 * * 1-5", "", "", t, after)[0] == []


def test_an_unreadable_stamp_counts_as_never_scanned(tmp_path):
    assert GATE.last_scan(tmp_path, "asx") is None
    (tmp_path / "asx_prices.json").write_text('{"generated_at": "2026-10-06T16:40:00"}')
    assert GATE.last_scan(tmp_path, "asx") is None, "a naive stamp is not a time"
    (tmp_path / "asx_prices.json").write_text('{"generated_at": "2026-10-06T16:40:00+11:00"}')
    assert GATE.last_scan(tmp_path, "asx") == _t("2026-10-06T05:40:00+00:00")


def test_the_cli_reads_the_stamps_and_prints_github_output_lines(tmp_path, capsys):
    def cli(*extra):
        assert GATE.main(["--data", str(tmp_path), *extra]) == 0
        return capsys.readouterr().out.splitlines()

    backstop = ["--event", "schedule", "--schedule", "47 5,6 * * 1-5",
                "--now", "2026-10-06T05:47:00+00:00"]                   # Tue 16:47 AEDT
    stamp = tmp_path / "asx_prices.json"
    stamp.write_text('{"generated_at": "2026-10-06T15:20:00+11:00"}')
    assert cli(*backstop) == ["run=true", "markets=asx"]
    stamp.write_text('{"generated_at": "2026-10-06T16:40:00+11:00"}')
    assert cli(*backstop) == ["run=false", "markets="]
    assert cli("--event", "workflow_dispatch", "--market", "all",
               "--now", "2026-10-11T01:00:00+00:00") == ["run=true", "markets=asx nasdaq crypto"]


# ── crypto: every hour, every day, and nobody else's business ────────────────

def test_crypto_runs_hourly_seven_days_and_scan_yml_never_touches_it():
    crypto = _crons("crypto_bot.yml")
    assert "22 * * * *" in crypto and "52 * * * *" in crypto
    for c in crypto:
        assert c.split()[-1] == "*", f"crypto cron {c} is restricted to some days"
    # scan.yml must not be able to pick crypto — the gate's table has no entry
    # for it, which is what retired crypto_bot's window-ownership gate.
    assert "crypto" not in config.MARKET_SCAN_WINDOWS
    assert "market_override=crypto" not in SCAN


def test_crypto_bots_window_ownership_gate_is_gone_not_merely_bypassed():
    """It only ever existed because scan.yml scanned crypto too. Leaving a
    dead UTC hour-table in place is how the next reader re-derives a rule that
    no longer applies."""
    cb = (WF / "crypto_bot.yml").read_text(encoding="utf-8")
    assert "scan.yml owns crypto now" not in cb
    assert "0[0-6]|1[4-9]|2[01]" not in cb, "the weekday hour table is still there"
    assert "$DOW" not in cb and "$HR" not in cb, "dead clock variables left behind"
    # the :52 freshness backstop must SURVIVE — it catches a dropped :22
    assert "Backstop :52" in cb


def test_the_crypto_universe_is_the_top_200():
    assert config.CRYPTO_UNIVERSE_SIZE == 200
    from scanner import universe
    # This test used to pin per_page=260 -- i.e. it pinned the BUG. CoinGecko
    # caps per_page at 250 and answers anything larger with its default 100,
    # which is how "top 200" became 86 names (2026-09-20..28). The fetch now
    # pages at the cap; the behaviour is pinned in tests/test_crypto_universe.py.
    assert "per_page=250" in universe.COINGECKO_URL
    assert universe.COINGECKO_PER_PAGE_MAX == 250

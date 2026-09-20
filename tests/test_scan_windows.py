"""THE SCAN SCHEDULE — market hours only, verified in both DST regimes.

Owner, 2026-09-21: "lets turn off NASDAQ and ASX scans after market closing
moving forward"; first scan an hour after the open, last at the close; crypto
hourly, seven days.

WHAT THIS REPLACED. `tests/test_workflow_dst.py` (TOP100 #41) pinned a pile of
DST special cases: two 23:xx "AEDT open" crons, a weekend crypto-only branch, a
per-market :47 backstop branch, and a matching hour-23 hand-off inside
crypto_bot.yml. Every one of them existed to patch a schedule written in fixed
UTC hours. The schedule is no longer written that way -- the crons are a
deliberate superset and the gate asks the tz database, in the market's own
calendar, whether now is inside that market's window -- so all of it is gone
and this file pins the property those tests were approximating.

It also pins the defect that prompted the change: the weekend cron was
commented "crypto only" and passed NO market, so scheduled runs fell through to
`all` and re-scanned ~2,000 ASX names four times a day on a shut market.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
from zoneinfo import ZoneInfo

import pytest
import yaml

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
SCAN = (WF / "scan.yml").read_text(encoding="utf-8")


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
    return [dt.datetime(day.year, day.month, day.day, h, int(minute), tzinfo=dt.timezone.utc)
            for h in _hours(hours)]


def gate(now_utc: dt.datetime) -> str:
    """The gate job's decision, re-expressed against the CONFIG table.

    The mirror test below is what keeps this honest: scan.yml carries the same
    numbers inline (its gate job checks out nothing and cannot import config),
    and a drift between the two fails.
    """
    for market, (tz, lo, hi) in config.MARKET_SCAN_WINDOWS.items():
        n = now_utc.astimezone(ZoneInfo(tz))
        if n.weekday() < 5 and lo <= n.hour * 60 + n.minute <= hi:
            return market
    return ""


# The closing slots are written twice (one per DST regime); the gate skips
# whichever one lands before the 16:00 close so it is not an extra mid-session
# scan. Mirrors the `case` block in scan.yml's gate.
CLOSING_CRONS = ("30 5,6 * * 1-5", "47 5,6 * * 1-5", "47 20,21 * * 1-5")


def scans_on(day: dt.date) -> list[tuple[str, str]]:
    """[(market, local HH:MM), ...] the schedule actually delivers that day."""
    out = []
    for cron in _crons("scan.yml"):
        for t in _fires(cron, day):
            m = gate(t)
            if not m:
                continue
            tz = ZoneInfo(config.MARKET_SCAN_WINDOWS[m][0])
            local = t.astimezone(tz)
            if cron in CLOSING_CRONS and local.hour * 60 + local.minute < 16 * 60:
                continue
            out.append((m, local.strftime("%H:%M")))
    return sorted(out)


# Four regimes, because Melbourne and New York change daylight saving on
# DIFFERENT dates: every combination has actually occurred and each one moves a
# session's UTC hours independently of the other.
DAYS = {
    "AEST + EDT (Sep)":  dt.date(2026, 9, 16),
    "AEDT + EDT (Oct)":  dt.date(2026, 10, 21),
    "AEDT + EST (Dec)":  dt.date(2026, 12, 16),
    "AEST + EST (Jun)":  dt.date(2026, 6, 17),
}


# ── the mirror: scan.yml's inline numbers vs config ──────────────────────────

def test_the_gate_carries_the_same_window_table_as_config():
    """scan.yml's gate job is deliberately checkout-free (contents: read), so
    it cannot import config and has to inline the numbers. This is the drift
    pin -- the same treatment the offline rules mirror gets."""
    line = next(l for l in SCAN.splitlines() if "MARKET=$(python3 -c" in l)
    for market, (tz, lo, hi) in config.MARKET_SCAN_WINDOWS.items():
        lo_expr = f"{lo // 60}*60" + (f"+{lo % 60}" if lo % 60 else "")
        hi_expr = f"{hi // 60}*60" + (f"+{hi % 60}" if hi % 60 else "")
        assert f"('{market}','{tz}',{lo_expr},{hi_expr})" in line, (
            f"scan.yml's gate disagrees with config.MARKET_SCAN_WINDOWS about {market}")


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
    """If they could, one run would have to scan two markets and the gate's
    single-market answer would be wrong for half of them."""
    for day in DAYS.values():
        for minute in range(0, 24 * 60, 5):
            t = dt.datetime(day.year, day.month, day.day, minute // 60, minute % 60,
                            tzinfo=dt.timezone.utc)
            hits = [m for m, (tz, lo, hi) in config.MARKET_SCAN_WINDOWS.items()
                    if (lambda n: n.weekday() < 5 and lo <= n.hour * 60 + n.minute <= hi)
                    (t.astimezone(ZoneInfo(tz)))]
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
    # ...and nothing outside the window, in either market.
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


def test_the_weekend_is_silent_for_both_stock_markets():
    """The defect that prompted all of this: 2026-09-19/20 took eleven full
    weekend ASX+NASDAQ scans because the 'crypto only' weekend cron passed no
    market and fell through to `all`."""
    for day in (dt.date(2026, 9, 19), dt.date(2026, 9, 20)):     # Sat, Sun
        assert scans_on(day) == [], f"{day} still scans: {scans_on(day)}"
    assert not any(c.split()[-1].strip("*") in ("0,6", "6,0", "0", "6")
                   for c in _crons("scan.yml")), "a weekend cron is back in scan.yml"


def test_a_scheduled_run_can_never_scan_all_markets():
    """`market_override` empty means `all` downstream, which is what made the
    weekend scans so expensive. On a schedule the gate now either names one
    market or refuses to run; only the fail-open probe error and a manual
    dispatch may leave it empty."""
    blocks = SCAN.split('echo "market_override=')
    empties = [b for b in blocks[1:] if b.startswith('"')]
    # Each empty one must be a skip (run=false), a manual dispatch, or the
    # explicitly-labelled fail-open branch.
    for b in blocks[1:]:
        if not b.startswith('"'):
            continue
        ctx = blocks[blocks.index(b) - 1][-600:]
        assert ('run=false' in b[:200] or 'run=false' in ctx
                or "Manual dispatch" in ctx or "fail open" in ctx), \
            f"an unexplained empty market_override (=> scans all markets):\n...{ctx[-300:]}"
    assert empties, "sanity: the parse found nothing to check"


# ── crypto: every hour, every day, and nobody else's business ────────────────

def test_a_closing_cron_that_lands_mid_session_is_skipped_not_run():
    """Each closing slot exists twice, one per DST regime. Without the >=16:00
    guard the wrong one is an ordinary extra full scan an hour before the
    close -- two surplus ASX scans a day for half the year."""
    for cron in CLOSING_CRONS:
        assert f'"{cron}"' in SCAN.split("Closing slot")[0].split("case \"$SCHED\" in")[-1] \
            or f'"{cron}"' in SCAN, f"{cron} is not in the closing-slot guard"
    assert "$LOCAL_MIN" in SCAN and "-lt 960" in SCAN, \
        "the closing crons no longer check they fired after the close"
    # and it really does drop them: AEST days must not carry a 15:30 ASX scan
    for label in ("AEST + EDT (Sep)", "AEST + EST (Jun)"):
        times = [t for m, t in scans_on(DAYS[label]) if m == "asx"]
        assert "15:30" not in times, f"{label}: surplus mid-session closing scan {times}"


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
    assert f"per_page={config.CRYPTO_UNIVERSE_SIZE + 60}" in universe.COINGECKO_URL, \
        "per_page must exceed the target: stablecoins are filtered OUT of the response"

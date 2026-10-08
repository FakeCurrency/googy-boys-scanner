"""Audit #69 and #30 (2026-10-08): the edge ledgers' forward-return stamps.

#69 -- stamp() re-derived the base bar on every run as "the first completed bar
on/after base_day" in a fixed period='3mo' frame and never consulted what it
had stored. Once base_day slid out of that window (a long suspension, a row
that stays unmatured), the base silently became a bar weeks later and the
remaining horizons froze against it. The base bar is now pinned by date
(`base_bar`), a legacy row is only re-found in a frame that reaches base_day
and within ALERT_RETURNS_BASE_MAX_GAP_DAYS of it, and each ticker downloads a
period that covers its oldest wanted base_day.

#30 -- both ledgers priced crypto through Yahoo's `download`, with no identity
check, so a colliding ticker (JUP: Yahoo 0.000327 vs the scanned $0.37) froze
another token's returns. Crypto now goes through scanner.data.fetch with the
identity check armed, and a stored base that is not the instrument now
priced is never extended.

Forward fixes only: no frozen value is rewritten by any of this.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alert_returns", ROOT / "scripts" / "alert_returns.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
er_spec = importlib.util.spec_from_file_location("edge_rosters", ROOT / "scripts" / "edge_rosters.py")
er = importlib.util.module_from_spec(er_spec)
er_spec.loader.exec_module(er)

UTC = dt.timezone.utc


def _row(market, ticker, base_day, base_close=None, fwd=None, **kw):
    r = {"key": f"{base_day}|{market}|{ticker}|long|2", "market": market, "ticker": ticker,
         "side": "long", "base_day": base_day, "base_close": base_close,
         "fwd": fwd or {str(h): None for h in ar.HORIZONS}}
    r.update(kw)
    return r


def _bars(sym, index, closes):
    return {sym: pd.DataFrame({"Close": list(closes)}, index=pd.DatetimeIndex(index))}


# ── #69: the base bar ────────────────────────────────────────────────────────

def test_the_audits_suspension_case_never_reanchors_on_the_resumption_bar(capsys):
    """Alert 2026-06-15, base_close 2.50 stored; suspended until 2026-09-21,
    resumes at 1.00. The next run's 3-month frame starts after the suspension:
    the old code took the resumption bar as the base and froze +5%/+25%/+50%
    where the true move was -60%."""
    led = ar._fresh()
    led["entries"].append(_row("asx", "XYZ", "2026-06-15", base_close=2.5))
    idx = pd.bdate_range("2026-09-21", periods=30)
    frames = _bars("XYZ.AX", idx, [1.0 + 0.05 * i for i in range(30)])
    now = dt.datetime(2026, 11, 20, tzinfo=UTC)
    assert ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now) == 0
    e = led["entries"][0]
    assert e["fwd"] == {str(h): None for h in ar.HORIZONS}, "never measured off the resumption bar"
    assert e["base_close"] == 2.5 and "base_bar" not in e, "the stored row is untouched"
    assert "WARNING stamp: 1 entry left unstamped" in capsys.readouterr().out


def test_a_halt_from_the_alert_session_is_a_gap_not_a_base():
    """The frame DOES reach back to base_day, but the first bar after it is a
    month later (halted from the alert session): no base, retried."""
    led = ar._fresh()
    led["entries"].append(_row("asx", "HLT", "2026-08-03"))
    idx = list(pd.bdate_range("2026-07-20", "2026-07-31")) + list(pd.bdate_range("2026-09-01", periods=25))
    frames = _bars("HLT.AX", idx, [10.0] * len(idx))
    now = dt.datetime(2026, 10, 20, tzinfo=UTC)
    ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now)
    assert led["entries"][0]["base_close"] is None


def test_a_weekend_or_holiday_base_still_finds_the_next_session():
    # Good Friday 2027-03-26 alert -> the Tuesday (Easter Monday shut): +4 days.
    led = ar._fresh()
    led["entries"].append(_row("asx", "BHP", "2027-03-26"))
    idx = pd.to_datetime(["2027-03-24", "2027-03-25", "2027-03-30", "2027-03-31"])
    frames = _bars("BHP.AX", idx, [40.0, 41.0, 42.0, 42.84])
    now = dt.datetime(2027, 4, 2, tzinfo=UTC)
    ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now)
    e = led["entries"][0]
    assert e["base_close"] == 42.0 and e["base_bar"] == "2027-03-30"
    assert e["fwd"]["1"] == 0.02


def test_the_first_stamp_pins_the_base_bar_and_later_runs_measure_from_it():
    led = ar._fresh()
    led["entries"].append(_row("asx", "BHP", "2026-08-03"))
    idx = pd.bdate_range("2026-07-27", periods=12)            # Mon 27 Jul ..
    closes = [100.0 + i for i in range(12)]
    first = dt.datetime(2026, 8, 5, tzinfo=UTC)                # base + 1 session done
    ar.stamp(led, _bars("BHP.AX", idx[:8], closes[:8]), ar.wanting_prices(led, first.date()), first)
    e = led["entries"][0]
    assert e["base_bar"] == "2026-08-03" and e["base_close"] == 105.0
    # A later download LOST the base bar (Yahoo dropped it). The old code took
    # the next bar as the base and measured every new horizon from it.
    later = dt.datetime(2026, 8, 20, tzinfo=UTC)
    keep = [i for i in range(12) if idx[i].date() != dt.date(2026, 8, 3)]
    ar.stamp(led, _bars("BHP.AX", [idx[i] for i in keep], [closes[i] for i in keep]),
             ar.wanting_prices(led, later.date()), later)
    assert e["fwd"]["5"] is None, "never measured from a bar that is not the base"
    # With the base bar back, the horizon is the close 5 bars after IT.
    ar.stamp(led, _bars("BHP.AX", idx, closes), ar.wanting_prices(led, later.date()), later)
    assert e["fwd"]["5"] == round(110.0 / 105.0 - 1.0, 6)


@pytest.mark.parametrize("age,period", [(0, "3mo"), (81, "3mo"), (82, "6mo"),
                                        (173, "6mo"), (300, "1y"), (700, "2y"), (2000, "max")])
def test_the_period_reaches_the_oldest_wanted_base_day(age, period):
    today = dt.date(2026, 10, 8)
    old = (today - dt.timedelta(days=age)).isoformat()
    young = (today - dt.timedelta(days=2)).isoformat()
    assert ar.period_for([_row("asx", "X", young), _row("asx", "X", old)], today) == period


def test_main_downloads_each_ticker_over_the_period_its_oldest_row_needs(tmp_path, monkeypatch):
    import scanner.data
    today = dt.datetime.now(UTC).date()
    led = {"schema_version": 1, "updated_at": "", "entries": [
        _row("asx", "OLD", (today - dt.timedelta(days=120)).isoformat()),
        _row("asx", "NEW", (today - dt.timedelta(days=10)).isoformat())]}
    (tmp_path / "ledger.json").write_text(json.dumps(led), encoding="utf-8")
    (tmp_path / "history.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(ar, "LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(ar, "HISTORY", str(tmp_path / "history.json"))
    asked = []
    monkeypatch.setattr(scanner.data, "download",
                        lambda syms, period=None, **k: asked.append((sorted(syms), period)) or {})
    assert ar.main(["--dry-run"]) == 0
    assert sorted(asked) == [(["NEW.AX"], "3mo"), (["OLD.AX"], "6mo")]

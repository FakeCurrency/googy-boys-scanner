"""IGNITION on NASDAQ (2026-10-08, owner: "build both") -- every per-market
value, pinned. The third market after crypto and the ASX, ported by the ASX
recipe (tests/test_ignition_asx.py):

  * CALENDAR windows rescale x252/365 -- NASDAQ trades ~252 days a year, so
    every one equals the ASX's (504/252/756/252/276/124/126). CHART windows
    stay in bars.
  * Floors US$1M base / US$3M trigger (Close x Volume; base = the VIVEK
    NASDAQ scan's own liquidity floor), 0.5% round-trip cost, a 5-day data
    age, the NASDAQ Composite as the regime line, NO design case (no chart
    informed the port), forward bucket from 2026-10-08.
  * The screen is its own workflow, ignition_nasdaq.yml, a structural twin of
    ignition.yml (the TWINS pins in tests/test_ignition_asx.py hold its steps
    and run blocks); its crons and backstop gate are pinned here.

Network is never touched (tests/conftest.py refuses the venues; the frames
here are synthetic).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
import yaml

from scanner import config
from scanner.ignition import backtest as BT
from scanner.ignition import engine as E
from scanner.ignition import run as RUN

ROOT = pathlib.Path(__file__).resolve().parents[1]
M = "nasdaq"

_spec = importlib.util.spec_from_file_location("_ig_asx_suite_nq",
                                               ROOT / "tests" / "test_ignition_asx.py")
_asx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_asx)
T = _asx.T
nasdaq_frame = _asx.asx_frame     # a weekday calendar; ~1.6M shares at ~$80 clears US$1M/3M


# ---------------------------------------------------------------------------
# the conversion
# ---------------------------------------------------------------------------

def test_the_nasdaq_windows_are_the_crypto_ones_in_trading_days():
    want = {"IGNITION_RANK_WINDOW": 504, "IGNITION_RANK_MIN_PERIODS": 252,
            "IGNITION_DD_LOOKBACK": 756, "IGNITION_DD_MIN_PERIODS": 252,
            "IGNITION_MIN_BARS": 276, "IGNITION_BT_MAX_HOLD": 124,
            "IGNITION_BT_RANDOM_WINDOW": 126}
    assert set(want) == set(E.CALENDAR_WINDOWS)
    for name, n in want.items():
        assert E.bars(M, name) == n == E.bars("asx", name), name
    assert config.IGNITION_BARS_PER_YEAR == {"crypto": 365, "asx": 252, "nasdaq": 252}


def test_the_minimum_history_still_covers_every_input_on_nasdaq():
    need = max(max(config.IGNITION_RIBBON_SMAS),
               E.bars(M, "IGNITION_RANK_MIN_PERIODS") + config.IGNITION_VOL_AVG_LEN,
               E.bars(M, "IGNITION_DD_MIN_PERIODS"))
    assert E.bars(M, "IGNITION_MIN_BARS") >= need


# ---------------------------------------------------------------------------
# per-market settings
# ---------------------------------------------------------------------------

def test_nasdaq_floors_are_us_dollars_on_the_scan_floor():
    pn, pc = E.Params.from_config(M), E.Params.from_config("crypto")
    assert (pn.min_base_turnover, pn.min_trigger_turnover) == (1_000_000, 3_000_000)
    assert pn.min_base_turnover == config.MARKETS[M].liquidity_min
    assert pn.min_trigger_turnover == 3 * pn.min_base_turnover
    for f in ("ribbon_max", "atr_pctl_max", "vol_pctl_max", "min_drawdown", "coil_lookback",
              "rvol_min", "max_ext", "rearm_bars", "stop_atr_mult"):
        assert getattr(pn, f) == getattr(pc, f), f


def test_nasdaq_turnover_is_price_times_shares():
    df = nasdaq_frame()
    np.testing.assert_allclose(E.dollar_volume(df, M), df["Close"] * df["Volume"])


def test_the_nasdaq_overrides():
    assert E.mkt(M, "IGNITION_BT_COST_PCT") == 0.5
    assert E.mkt(M, "IGNITION_BT_REGISTERED_DATE") == "2026-10-08"
    assert E.mkt(M, "IGNITION_BT_CASES") == ()
    assert BT.design_cases(M) == {}
    assert RUN.max_age_days(M) == 5
    assert config.IGNITION_REGIME_INDEX[M] == ("^IXIC", "NASDAQ Composite")
    assert config.IGNITION_MARKETS == ("crypto", "asx", "nasdaq")
    # crypto and the ASX did not move
    assert E.mkt("crypto", "IGNITION_BT_COST_PCT") == 0.30 and E.mkt("asx", "IGNITION_BT_COST_PCT") == 1.0
    assert BT.design_cases("asx") == {"DTR": "2026-09-01"}
    assert BT.design_cases("crypto") == {"QNT": "2026-09-01"}


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------

def _index(n=260, start="2025-10-01"):
    return pd.DataFrame({"Open": 18000.0, "High": 18010.0, "Low": 17990.0,
                         "Close": np.linspace(15000, 19000, n), "Volume": 0.0},
                        index=pd.bdate_range(start, periods=n))


def test_the_fixture_ignites_on_nasdaq_at_its_designed_bar():
    feat = E.compute(nasdaq_frame(), M)
    assert T in np.flatnonzero(feat["trigger"].to_numpy())


def test_a_nasdaq_listing_between_276_and_400_bars_is_screened_not_skipped():
    df = nasdaq_frame().iloc[:300]
    assert E.screen_frame(df, "crypto") is None
    assert E.compute(df, M)["inputs_ready"].iloc[-1]


def test_screen_market_publishes_a_nasdaq_payload_with_the_composite_regime():
    df = nasdaq_frame().iloc[:T + 3]
    now = dt.datetime.combine(df.index[-1].date() + dt.timedelta(days=1),
                              dt.time(15, 0), tzinfo=dt.timezone.utc)
    pay = RUN.screen_market(M, frames={"ZZZ": df},
                            rows=[{"symbol": "ZZZ", "name": "Zed Inc", "yf": "ZZZ"}],
                            now=now, regime=_index())
    assert pay["market"] == M and pay["summary"]["screened"] == 1
    assert pay["results"][0]["symbol"] == "ZZZ"
    assert pay["results"][0]["state"] in ("IGNITING", "RUNNING")
    rg = pay["regime"]
    assert rg["label"] == "NASDAQ Composite" and rg["index"] == "^IXIC"
    assert rg["above_200"] is True
    assert not any(k.startswith("btc_") for k in rg)
    assert pay["rules"]["bars_per_year"] == 252
    assert pay["rules"]["calendar_windows"]["IGNITION_RANK_WINDOW"] == 504
    assert pay["params"]["min_trigger_turnover"] == 3_000_000
    assert pay["params"]["min_base_turnover"] == 1_000_000


def test_a_nasdaq_frame_up_to_five_days_old_is_screened_and_six_is_not():
    df = nasdaq_frame().iloc[:T + 3]
    last = df.index[-1].date()
    for days, screened in ((5, 1), (6, 0)):
        now = dt.datetime.combine(last + dt.timedelta(days=days), dt.time(15, 0),
                                  tzinfo=dt.timezone.utc)
        pay = RUN.screen_market(M, frames={"ZZZ": df}, rows=[], now=now)
        assert (0 if pay is None else pay["summary"]["screened"]) == screened, days


def test_the_nasdaq_bar_forms_until_the_new_york_close():
    ny = ZoneInfo("America/New_York")
    day = pd.Timestamp("2026-10-08")
    assert RUN.bar_is_forming(M, day, dt.datetime(2026, 10, 8, 15, 59, tzinfo=ny))
    assert not RUN.bar_is_forming(M, day, dt.datetime(2026, 10, 8, 16, 0, tzinfo=ny))
    # 02:00 UTC next day is still the 8th in New York, after the close
    assert not RUN.bar_is_forming(M, day, dt.datetime(2026, 10, 9, 2, 0, tzinfo=dt.timezone.utc))
    # a pre-open run the next morning: yesterday's bar is complete
    assert not RUN.bar_is_forming(M, day, dt.datetime(2026, 10, 9, 8, 0, tzinfo=ny))


def test_nasdaq_freshness_has_no_expected_bar():
    df = nasdaq_frame().iloc[:T + 3]
    now = dt.datetime.combine(df.index[-1].date() + dt.timedelta(days=1), dt.time(15, 0),
                              tzinfo=dt.timezone.utc)
    b = RUN.bar_freshness({"ZZZ": df}, {}, M, now)
    assert b["expected_completed"] is None and b["lagging"] == 0


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------

def _frames():
    return {"ZZZ": nasdaq_frame(),
            "THIN": nasdaq_frame(seed=11, vol_scale=1e-4),      # never clears US$3M
            "QNT": nasdaq_frame(seed=3)}                       # a crypto design-case NAME


def test_prepare_drops_a_name_that_never_clears_both_floors_on_nasdaq():
    fr = _frames()
    assert {p.symbol for p in BT.prepare(fr, M, {k: k for k in fr})} == {"ZZZ", "QNT"}


def test_the_nasdaq_prefilter_changes_no_trade():
    fr = _frames()
    p = E.Params.from_config(M)
    kept = BT.prepare(fr, M, {k: k for k in fr})
    every = [BT.Prepared(k, E.clean(v), M) for k, v in sorted(fr.items())]
    strip = lambda ts: sorted((t["symbol"], t.get("_t0")) for t in ts)
    assert strip(BT.run_all(kept, p)) == strip(BT.run_all(every, p))


def test_nasdaq_has_no_design_case():
    for sym in ("QNT", "DTR"):
        assert not BT.is_design_case({"symbol": sym, "trigger_date": "2026-10-08", "_mkt": M})


def test_nasdaq_trades_carry_the_nasdaq_hold_cost_and_index_regime():
    fr = _frames()
    pr = [p for p in BT.prepare(fr, M, {k: k for k in fr}) if p.symbol == "ZZZ"][0]
    tr = [t for t in BT.trades_for(pr, E.apply_rules(pr.bf, E.Params.from_config(M)))
          if not t.get("skipped")]
    assert tr, "the fixture must trade"
    t = tr[0]
    assert t["_mkt"] == M and "index_up" in t and "btc_up" not in t
    assert t["cost_r"] == pytest.approx(0.005 * t["entry"] / (t["entry"] - t["stop"]), abs=1e-4)
    assert t["bars"] <= 124


def test_the_nasdaq_backtest_payload(monkeypatch):
    monkeypatch.setattr(config, "IGNITION_BT_BOOTSTRAP", 50)
    monkeypatch.setattr(BT, "GRID", {k: v[:1] + v[1:2] for k, v in BT.GRID.items()})
    fr = _frames()
    pay = BT.backtest(fr, M, symbols={k: k for k in fr},
                      now=dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc),
                      regime=_index(1200, "2021-01-04"))
    pre = pay["pre_registered"]
    assert pre["cost_pct_round_trip"] == 0.5
    assert pre["max_hold_bars"] == 124
    assert pre["registered"] == "2026-10-08"
    assert pay["scoring"]["design_cases_excluded"] == {}
    assert pay["cases"] == {}
    assert "+/-126 bars" in pay["scoring"]["baseline_rule"]
    assert pay["primary"]["regime_index"] == {"symbol": "^IXIC", "label": "NASDAQ Composite"}
    assert "by_regime" in pay["primary"] and "by_btc_regime" not in pay["primary"]
    assert pay["symbols_replayed"] == 2          # THIN never cleared the floors
    # QNT is a crypto design case, never a NASDAQ one: its trades are scored
    assert not any(t["design_case"] for t in pay["trades"])
    cav = " ".join(pay["caveats"])
    assert "NASDAQ listings" in cav and "252 trading days" in cav
    assert "No design case: no NASDAQ chart informed the port, so every trigger is scored." in cav
    assert "Costs 0.5% round trip (a flat broker fee both ways + the spread;" in cav
    assert "none prompted" not in cav and "ASX" not in cav and "coins" not in cav.lower()


def test_the_port_did_not_move_the_asx_caveats():
    """The caveat sentences that became per-market (the design case, the cost
    parenthesis) still read, on the ASX, EXACTLY as published before the port
    -- a frozen copy, so a reworded ASX payload fails here."""
    cav = BT._caveats("asx", None, {"DTR": "2026-09-01"})
    assert cav[2] == ("The rule is crypto's, thresholds unchanged; calendar windows are "
                      "converted to 252 trading days a year. DTR prompted the port, so it "
                      "is excluded from every scored number and reported only as a case study.")
    assert cav[4] == ("Costs 1.0% round trip (brokerage both ways + the spread; under 10c an "
                      "ASX tick is ~1% of the price). Thin names can move more than that on "
                      "the open.")


# ---------------------------------------------------------------------------
# the workflow (its shape is pinned by the TWINS tests in test_ignition_asx.py)
# ---------------------------------------------------------------------------

WFDIR = ROOT / ".github" / "workflows"
NQ = yaml.safe_load((WFDIR / "ignition_nasdaq.yml").read_text(encoding="utf-8"))
CRONS = ["34 21 * * 1-5", "34 22,23 * * 1-5", "54 14,16,18 * * 1-5"]
_on = lambda d: d.get("on") or d[True]


def test_the_nasdaq_triggers_gate_group_cache_and_timeout():
    on = _on(NQ)
    assert [c["cron"] for c in on["schedule"]] == CRONS
    assert on["push"]["paths"] == [".github/ignition-nasdaq-kick"]
    assert set(on["workflow_dispatch"]["inputs"]) == {"backtest", "dry_run"}
    group = NQ["concurrency"]["group"]
    assert group == "ignition-nasdaq-${{ github.ref_name }}"
    for other in ("ignition.yml", "ignition_asx.yml"):
        assert yaml.safe_load((WFDIR / other).read_text(encoding="utf-8"))["concurrency"]["group"] != group
    assert NQ["concurrency"]["cancel-in-progress"] is False
    job = NQ["jobs"]["ignition"]
    assert job["timeout-minutes"] == 300
    cache = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/cache"))
    assert cache["with"]["key"].startswith("ignition-nasdaq-frames-")
    assert cache["with"]["restore-keys"].strip() == "ignition-nasdaq-frames-"
    gate = next(s for s in job["steps"] if s.get("id") == "due")["run"]
    assert '"%s"' % CRONS[1] in gate             # the backstop cron it recognises
    assert "scripts/ignition_due.py nasdaq" in gate
    assert "public/data/ignition/nasdaq.json" in gate
    assert NQ["permissions"] == {"contents": "write"}


def _ny(day: str, hh: int, mm: int):
    t = dt.datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00+00:00")
    return t.astimezone(ZoneInfo(config.IGNITION_BAR_FINAL[M][0]))


def _crons(i):
    """(hour, minute) UTC of the SHIPPED schedule's i-th cron line."""
    minute, hours = _on(NQ)["schedule"][i]["cron"].split()[:2]
    return [(int(h), int(minute)) for h in hours.split(",")]


@pytest.mark.parametrize("day", ["2026-07-15", "2026-12-15"])     # EDT, EST
def test_every_post_close_cron_is_past_the_bar_final_on_the_same_weekday(day):
    """Primary and backstops all land after 16:30 New York AND before UTC
    midnight, so `1-5` is the close's own weekday (a 00:34 UTC backstop would
    need `2-6` to cover Friday)."""
    final = config.IGNITION_BAR_FINAL[M][1:]
    for hh, mm in _crons(0) + _crons(1):
        local = _ny(day, hh, mm)
        assert (local.hour, local.minute) >= final, (day, hh)
        assert local.date().isoformat() == day, (day, hh)


@pytest.mark.parametrize("day", ["2026-07-15", "2026-12-15"])
def test_every_intraday_cron_is_in_session_an_hour_clear_of_the_close(day):
    """A run that reads its clock after the close would call a not-yet-final
    bar COMPLETED, so every intraday run starts in session with an hour of
    slack for the download."""
    o_h, o_m, c_h, c_m = config.VIVEK_JOURNAL_SESSION[M]
    for hh, mm in _crons(2):
        local = _ny(day, hh, mm)
        t = local.hour * 60 + local.minute
        assert o_h * 60 + o_m <= t <= c_h * 60 + c_m - 60, (day, hh)


def test_the_kick_is_not_dispatched_by_the_scan():
    ds = yaml.safe_load((WFDIR / "dispatch_scan.yml").read_text(encoding="utf-8"))
    assert ".github/ignition-nasdaq-kick" not in str(_on(ds))


# ---------------------------------------------------------------------------
# the backstop gate (scripts/ignition_due.py, shared with the ASX)
# ---------------------------------------------------------------------------

GATE = ROOT / "scripts" / "ignition_due.py"


def _due(market, stamp, now):
    p = subprocess.run([sys.executable, str(GATE), market, stamp, "--now", now],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


def test_the_nasdaq_bar_final_is_derived_not_retyped():
    assert config.IGNITION_BAR_FINAL[M] == \
        (config.MARKETS[M].timezone,) + tuple(config.ALERT_RETURNS_BAR_FINAL[M])
    assert config.IGNITION_BAR_FINAL[M][1:] >= config.VIVEK_JOURNAL_SESSION[M][2:]


@pytest.mark.parametrize("market,stamp,now,want", [
    # EDT (UTC-4): final 16:30 = 20:30 UTC
    ("nasdaq", "2026-07-15T21:36:00+00:00", "2026-07-15T22:34:00+00:00", "run=false"),
    ("nasdaq", "2026-07-15T20:30:00+00:00", "2026-07-15T22:34:00+00:00", "run=false"),
    ("nasdaq", "2026-07-15T19:06:00+00:00", "2026-07-15T22:34:00+00:00", "run=true"),
    ("nasdaq", "2026-07-14T21:36:00+00:00", "2026-07-15T22:34:00+00:00", "run=true"),
    # EST (UTC-5): final 16:30 = 21:30 UTC
    ("nasdaq", "2026-12-15T21:36:00+00:00", "2026-12-15T22:34:00+00:00", "run=false"),
    ("nasdaq", "2026-12-15T21:20:00+00:00", "2026-12-15T22:34:00+00:00", "run=true"),
    # Monday before the close: the last close is FRIDAY's
    ("nasdaq", "2026-10-09T21:40:00+00:00", "2026-10-12T15:00:00+00:00", "run=false"),
    ("nasdaq", "2026-10-09T20:20:00+00:00", "2026-10-12T15:00:00+00:00", "run=true"),
    # Saturday maps to Friday's close too
    ("nasdaq", "2026-10-09T21:40:00+00:00", "2026-10-10T15:00:00+00:00", "run=false"),
    ("nasdaq", "2026-10-09T19:00:00+00:00", "2026-10-10T15:00:00+00:00", "run=true"),
    # unreadable -> fail OPEN
    ("nasdaq", "", "2026-07-15T22:34:00+00:00", "run=true"),
    ("nasdaq", "garbage", "2026-07-15T22:34:00+00:00", "run=true"),
    ("nasdaq", "2026-07-15T21:36:00", "2026-07-15T22:34:00+00:00", "run=true"),
    ("nyse", "2026-07-15T21:36:00+00:00", "2026-07-15T22:34:00+00:00", "run=true"),
    ("crypto", "2026-07-15T21:36:00+00:00", "2026-07-15T22:34:00+00:00", "run=true"),
])
def test_the_gate(market, stamp, now, want):
    assert _due(market, stamp, now) == want


def test_the_same_stamp_reads_differently_per_market():
    """One script, each market's own close: 06:00 UTC on 15 Jul is after the
    previous NASDAQ close but before that day's ASX close (06:40 UTC)."""
    stamp, now = "2026-07-15T06:00:00+00:00", "2026-07-15T07:24:00+00:00"
    assert _due("nasdaq", stamp, now) == "run=false"
    assert _due("asx", stamp, now) == "run=true"

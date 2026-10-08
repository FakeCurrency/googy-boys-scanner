"""IGNITION on the ASX (2026-09-29) -- the trading-day conversion and every
per-market difference, pinned.

Owner ruling after the DTR miss: "Yes and factor in the converting windows
from calendar days to trading days and everything else". What that means in
code, and what each test below holds:

  * CALENDAR windows (2y ranks, 3y drawdown, a year of warm-up, the minimum
    history, the replay's max hold and random-timing window) are written in
    crypto bars and rescaled by engine.bars(): x252/365 on the ASX, and
    EXACTLY x1 on crypto -- ruleset 1.0.0 cannot move there.
  * CHART-CONVENTION windows (SMA 9/26/43/200, ATR 14, 20-bar volume, the
    60-bar base, coil lookback, rearm, keep, the 9-SMA trail) are bars on
    every market and are NOT rescaled.
  * Floors (A$100k / A$300k), costs (1.0% round trip), data age (5 days),
    the forward date, the regime index (the ASX 200) and the design case (DTR)
    are per market.
  * The ASX screen is its own workflow, ignition_asx.yml, held to the crypto
    workflow's exact shape so that suite's EXECUTED shell covers it too.

Network is never touched (tests/conftest.py refuses the venues; the frames
here are synthetic).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import re
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
import yaml

from scanner import config
from scanner.ignition import backtest as BT
from scanner.ignition import engine as E
from scanner.ignition import run as RUN

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("_ig_suite", ROOT / "tests" / "test_ignition.py")
_ig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ig)
build, T = _ig.build, _ig.T


def asx_frame(**kw) -> pd.DataFrame:
    """The crypto suite's decline -> base -> breakout fixture on a WEEKDAY
    calendar (an ASX tape has no weekends). Volume is shares here; at a ~$80
    price the floors are cleared by a wide margin unless `vol_scale` says not."""
    df = build(**kw)
    df.index = pd.bdate_range("2021-01-04", periods=len(df))
    return df


# ---------------------------------------------------------------------------
# the conversion
# ---------------------------------------------------------------------------

def test_every_calendar_window_is_the_identity_on_crypto():
    for name in E.CALENDAR_WINDOWS:
        assert E.bars("crypto", name) == getattr(config, name), name


def test_the_asx_windows_are_the_crypto_ones_in_trading_days():
    want = {"IGNITION_RANK_WINDOW": 504, "IGNITION_RANK_MIN_PERIODS": 252,
            "IGNITION_DD_LOOKBACK": 756, "IGNITION_DD_MIN_PERIODS": 252,
            "IGNITION_MIN_BARS": 276, "IGNITION_BT_MAX_HOLD": 124,
            "IGNITION_BT_RANDOM_WINDOW": 126}
    assert set(want) == set(E.CALENDAR_WINDOWS)
    for name, n in want.items():
        assert E.bars("asx", name) == n, name
    assert config.IGNITION_BARS_PER_YEAR == {"crypto": 365, "asx": 252}


def test_the_minimum_history_still_covers_every_input_on_the_asx():
    """276 bars must hold the 200-SMA AND a full rank warm-up (252 + the 20-bar
    volume average) -- a shorter floor would screen names whose coil can never
    be computed and call them 'nothing coiling'."""
    need = max(max(config.IGNITION_RIBBON_SMAS),
               E.bars("asx", "IGNITION_RANK_MIN_PERIODS") + config.IGNITION_VOL_AVG_LEN,
               E.bars("asx", "IGNITION_DD_MIN_PERIODS"))
    assert E.bars("asx", "IGNITION_MIN_BARS") >= need


def test_a_chart_convention_window_is_not_a_calendar_window():
    for name in ("IGNITION_BASE_BARS", "IGNITION_COIL_LOOKBACK", "IGNITION_REARM_BARS",
                 "IGNITION_KEEP_BARS", "IGNITION_RVOL_LEN", "IGNITION_VOL_AVG_LEN",
                 "IGNITION_ATR_LEN", "IGNITION_TRAIL_SMA", "IGNITION_EXT_SMA"):
        assert name not in E.CALENDAR_WINDOWS
        with pytest.raises(KeyError):
            E.bars("asx", name)


def test_the_conversion_reads_config_at_call_time(monkeypatch):
    monkeypatch.setattr(config, "IGNITION_RANK_WINDOW", 365)
    assert E.bars("crypto", "IGNITION_RANK_WINDOW") == 365
    assert E.bars("asx", "IGNITION_RANK_WINDOW") == 252


def test_base_features_rank_over_the_asx_window_and_the_crypto_one_elsewhere():
    df = asx_frame()
    fa = E.base_features(df, "asx")
    fc = E.base_features(df, "crypto")
    # First computable rank = min_periods - 1 (rolling over the ATR%, itself
    # NaN for the first ATR bar): the ASX one warms up 113 bars sooner.
    first = lambda s: int(np.flatnonzero(s.notna().to_numpy())[0])
    assert first(fc["atr_rank"]) - first(fa["atr_rank"]) == 365 - 252
    assert first(fc["drawdown"]) - first(fa["drawdown"]) == 365 - 252
    # A chart-convention series is identical on both markets.
    pd.testing.assert_series_equal(fa["base_high"], fc["base_high"])
    pd.testing.assert_series_equal(fa["trail"], fc["trail"])
    pd.testing.assert_series_equal(fa["ribbon"], fc["ribbon"])


def test_the_asx_rank_is_the_percentile_inside_504_bars_exactly():
    df = asx_frame()
    fa = E.base_features(df, "asx")
    atr_pct = (E.calc_atr(df, config.IGNITION_ATR_LEN) / df["Close"])
    i = 600
    window = atr_pct.iloc[i - 503:i + 1].dropna()
    expect = (window <= window.iloc[-1]).sum() / len(window)   # rank(pct) with ties avg ~ exact here
    assert fa["atr_rank"].iloc[i] == pytest.approx(expect, abs=1.0 / len(window))


# ---------------------------------------------------------------------------
# per-market settings
# ---------------------------------------------------------------------------

def test_asx_floors_are_in_aud_and_crypto_floors_did_not_move():
    pa, pc = E.Params.from_config("asx"), E.Params.from_config("crypto")
    assert (pa.min_base_turnover, pa.min_trigger_turnover) == (100_000, 300_000)
    assert (pc.min_base_turnover, pc.min_trigger_turnover) == (1_000_000, 3_000_000)
    assert pa.min_base_turnover == config.MARKETS["asx"].liquidity_min
    # every other threshold is the same rule
    for f in ("ribbon_max", "atr_pctl_max", "vol_pctl_max", "min_drawdown", "coil_lookback",
              "rvol_min", "max_ext", "rearm_bars", "stop_atr_mult"):
        assert getattr(pa, f) == getattr(pc, f), f


def test_asx_turnover_is_price_times_shares():
    df = asx_frame()
    np.testing.assert_allclose(E.dollar_volume(df, "asx"), df["Close"] * df["Volume"])
    np.testing.assert_allclose(E.dollar_volume(df, "crypto"), df["Volume"])


def test_mkt_reads_the_override_and_falls_through_for_crypto():
    assert E.mkt("asx", "IGNITION_BT_COST_PCT") == 1.0
    assert E.mkt("crypto", "IGNITION_BT_COST_PCT") == config.IGNITION_BT_COST_PCT == 0.30
    assert E.mkt("asx", "IGNITION_BT_REGISTERED_DATE") == "2026-09-29"
    assert E.mkt("crypto", "IGNITION_BT_REGISTERED_DATE") == "2026-09-28"
    assert E.mkt("asx", "IGNITION_BT_CASES") == ("DTR",)
    assert E.mkt("crypto", "IGNITION_BT_CASES") == ("QNT",)
    assert RUN.max_age_days("asx") == 5 and RUN.max_age_days("crypto") == 3


def test_the_markets_list_and_the_regime_indices():
    assert config.IGNITION_MARKETS == ("crypto", "asx")
    assert config.IGNITION_REGIME_INDEX["asx"] == ("^AXJO", "ASX 200")
    assert config.IGNITION_REGIME_INDEX["crypto"][0] == "BTC-USD"


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------

def test_the_fixture_ignites_on_the_asx_at_its_designed_bar():
    df = asx_frame()
    feat = E.compute(df, "asx")
    trig = np.flatnonzero(feat["trigger"].to_numpy())
    assert T in trig


def test_an_asx_listing_between_276_and_400_bars_is_screened_not_skipped():
    """On crypto 400 bars is ~13 months; on the ASX 276 is the same time. A
    frame of 300 completed bars is screenable on the ASX and short on crypto."""
    df = asx_frame().iloc[:300]
    assert E.screen_frame(df, "crypto") is None
    feat = E.compute(df, "asx")
    assert feat["inputs_ready"].iloc[-1]          # every coil input exists by bar 300


def test_screen_market_publishes_an_asx_payload_with_the_index_regime():
    df = asx_frame().iloc[:T + 3]
    idx = pd.DataFrame({"Open": 8000.0, "High": 8010.0, "Low": 7990.0,
                        "Close": np.linspace(7000, 8800, 260), "Volume": 0.0},
                       index=pd.bdate_range("2025-10-01", periods=260))
    now = dt.datetime.combine(df.index[-1].date() + dt.timedelta(days=1),
                              dt.time(0, 30), tzinfo=dt.timezone.utc)
    pay = RUN.screen_market("asx", frames={"ZZZ.AX": df},
                            rows=[{"symbol": "ZZZ", "name": "Zed Ltd", "yf": "ZZZ.AX"}],
                            now=now, regime=idx)
    assert pay["market"] == "asx"
    assert pay["summary"]["screened"] == 1
    row = pay["results"][0]
    assert row["symbol"] == "ZZZ" and row["state"] in ("IGNITING", "RUNNING")
    rg = pay["regime"]
    assert rg["label"] == "ASX 200" and rg["index"] == "^AXJO" and rg["above_200"] is True
    assert "btc_above_200" not in rg
    assert pay["rules"]["bars_per_year"] == 252
    assert pay["rules"]["calendar_windows"]["IGNITION_RANK_WINDOW"] == 504
    assert pay["params"]["min_trigger_turnover"] == 300_000


def test_an_asx_frame_up_to_five_days_old_is_screened_and_six_is_not():
    df = asx_frame().iloc[:T + 3]
    last = df.index[-1].date()
    for days, screened in ((5, 1), (6, 0)):
        now = dt.datetime.combine(last + dt.timedelta(days=days), dt.time(0, 30),
                                  tzinfo=dt.timezone.utc)
        pay = RUN.screen_market("asx", frames={"ZZZ.AX": df}, rows=[], now=now)
        got = 0 if pay is None else pay["summary"]["screened"]
        assert got == screened, days


def test_the_asx_forming_bar_is_the_session_before_the_close():
    # audit #22: the close is config.DAILY_BAR_FINAL's 16:40 Sydney (Yahoo shows
    # the auction ~20 min late), so 16:30 is still forming; it was the 16:00 bell
    syd = dt.timezone(dt.timedelta(hours=10))
    day = pd.Timestamp("2026-09-29")
    assert RUN.bar_is_forming("asx", day, dt.datetime(2026, 9, 29, 14, 0, tzinfo=syd))
    assert RUN.bar_is_forming("asx", day, dt.datetime(2026, 9, 29, 16, 30, tzinfo=syd))
    assert not RUN.bar_is_forming("asx", day, dt.datetime(2026, 9, 29, 16, 40, tzinfo=syd))


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------

def _frames():
    return {"ZZZ.AX": asx_frame(),
            "THIN.AX": asx_frame(seed=11, vol_scale=1e-4),      # never clears A$300k
            "DTR.AX": asx_frame(seed=3)}


def test_prepare_drops_a_name_that_never_clears_both_floors_on_the_asx_only():
    fr = _frames()
    syms = {k: k.split(".")[0] for k in fr}
    got = {p.symbol for p in BT.prepare(fr, "asx", syms)}
    assert got == {"ZZZ", "DTR"}
    # crypto keeps its old behaviour: no liquidity pre-filter in prepare
    cr = {k.replace(".AX", "-USD"): v for k, v in fr.items()}
    assert {p.symbol for p in BT.prepare(cr, "crypto")} == {"ZZZ", "THIN", "DTR"}


def test_the_prefilter_changes_no_trade():
    """Dropping never-liquid names is a SPEED-UP, not a rule: the same frames
    with the filter bypassed must trade exactly the same list."""
    fr = _frames()
    syms = {k: k.split(".")[0] for k in fr}
    p = E.Params.from_config("asx")
    kept = BT.prepare(fr, "asx", syms)
    every = [BT.Prepared(syms[k], E.clean(v), "asx") for k, v in sorted(fr.items())]
    strip = lambda ts: sorted((t["symbol"], t.get("_t0")) for t in ts)
    assert strip(BT.run_all(kept, p)) == strip(BT.run_all(every, p))


def test_dtr_is_an_asx_design_case_and_qnt_is_not_one_there():
    assert BT.is_design_case({"symbol": "DTR", "trigger_date": "2026-09-29", "_mkt": "asx"})
    assert not BT.is_design_case({"symbol": "DTR", "trigger_date": "2026-08-31", "_mkt": "asx"})
    assert not BT.is_design_case({"symbol": "QNT", "trigger_date": "2026-09-29", "_mkt": "asx"})
    assert BT.is_design_case({"symbol": "QNT", "trigger_date": "2026-09-29"})     # crypto default
    assert not BT.is_design_case({"symbol": "DTR", "trigger_date": "2026-09-29"})


def test_asx_trades_carry_the_asx_hold_cost_and_index_regime():
    fr = _frames()
    syms = {k: k.split(".")[0] for k in fr}
    pr = [p for p in BT.prepare(fr, "asx", syms) if p.symbol == "ZZZ"][0]
    tr = [t for t in BT.trades_for(pr, E.apply_rules(pr.bf, E.Params.from_config("asx")))
          if not t.get("skipped")]
    assert tr, "the fixture must trade"
    t = tr[0]
    assert t["_mkt"] == "asx" and "index_up" in t and "btc_up" not in t
    assert t["cost_r"] == pytest.approx(0.01 * t["entry"] / (t["entry"] - t["stop"]), abs=1e-4)
    assert t["bars"] <= 124


def test_the_asx_backtest_payload(monkeypatch):
    monkeypatch.setattr(config, "IGNITION_BT_BOOTSTRAP", 50)
    monkeypatch.setattr(BT, "GRID", {k: v[:1] + v[1:2] for k, v in BT.GRID.items()})
    fr = _frames()
    idx = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0,
                        "Close": np.linspace(5000, 9000, 1200), "Volume": 0.0},
                       index=pd.bdate_range("2021-01-04", periods=1200))
    pay = BT.backtest(fr, "asx", symbols={k: k.split(".")[0] for k in fr},
                      now=dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc), regime=idx)
    pre = pay["pre_registered"]
    assert pre["cost_pct_round_trip"] == 1.0
    assert pre["max_hold_bars"] == 124
    assert pre["registered"] == "2026-09-29"
    assert pay["scoring"]["design_cases_excluded"] == {"DTR": "2026-09-01"}
    assert "+/-126 bars" in pay["scoring"]["baseline_rule"]
    assert "by_regime" in pay["primary"] and "by_btc_regime" not in pay["primary"]
    assert pay["primary"]["regime_index"] == {"symbol": "^AXJO", "label": "ASX 200"}
    assert set(pay["primary"]["by_regime"]) <= {"index_above_200", "index_below_200", "unknown"}
    cav = " ".join(pay["caveats"])
    assert "ASX listings" in cav and "252 trading days" in cav and "DTR" in cav
    assert "coins" not in cav.lower()
    assert "DTR" in pay["cases"]
    assert pay["symbols_replayed"] == 2          # THIN never cleared the floors
    assert any("symbols" in ln for ln in BT.summary_lines(pay)[:1])


# ---------------------------------------------------------------------------
# the workflow: a structural twin of ignition.yml
# ---------------------------------------------------------------------------

WFDIR = ROOT / ".github" / "workflows"
CRYPTO = yaml.safe_load((WFDIR / "ignition.yml").read_text(encoding="utf-8"))
ASX_SRC = (WFDIR / "ignition_asx.yml").read_text(encoding="utf-8")
ASX = yaml.safe_load(ASX_SRC)
_on = lambda d: d.get("on") or d[True]


def _to_asx(text: str) -> str:
    return (text.replace("--market crypto", "--market asx")
                .replace("public/data/ignition/crypto", "public/data/ignition/asx")
                .replace("ignition crypto", "ignition asx"))


def test_the_asx_workflow_has_the_same_steps_in_the_same_order():
    cs, as_ = CRYPTO["jobs"]["ignition"]["steps"], ASX["jobs"]["ignition"]["steps"]
    shape = lambda st: [(s.get("id"), s.get("uses"), s.get("if")) for s in st]
    assert shape(as_) == shape(cs)
    names = [s.get("name") for s in as_]
    assert names == [(_to_asx(n or "").replace("Screen crypto", "Screen ASX")
                      .replace("Backtest crypto", "Backtest ASX") or None)
                     for n in (s.get("name") for s in cs)]


def test_every_run_block_but_the_gate_is_the_crypto_block_for_the_asx():
    """The crypto suite EXECUTES these blocks (exit-code arms, one-path
    staging, per-path must-change gate, own-branch push); holding the ASX
    copies byte-equal after the market substitution extends that proof."""
    cs, as_ = CRYPTO["jobs"]["ignition"]["steps"], ASX["jobs"]["ignition"]["steps"]
    for c, a in zip(cs, as_):
        if c.get("id") == "due" or "run" not in c:
            continue
        assert a["run"] == _to_asx(c["run"]), c.get("name")


def test_the_asx_triggers_gate_group_cache_and_timeout():
    on = _on(ASX)
    crons = [c["cron"] for c in on["schedule"]]
    assert crons == ["24 6 * * 1-5", "24 7,9 * * 1-5", "54 0,2,4 * * 1-5"]
    assert on["push"]["paths"] == [".github/ignition-asx-kick"]
    assert set(on["workflow_dispatch"]["inputs"]) == {"backtest", "dry_run"}
    assert ASX["concurrency"]["group"] == "ignition-asx-${{ github.ref_name }}"
    assert CRYPTO["concurrency"]["group"] != ASX["concurrency"]["group"]
    job = ASX["jobs"]["ignition"]
    assert job["timeout-minutes"] == 300
    cache = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/cache"))
    assert cache["with"]["key"].startswith("ignition-asx-frames-")
    assert cache["with"]["restore-keys"].strip() == "ignition-asx-frames-"
    gate = next(s for s in job["steps"] if s.get("id") == "due")["run"]
    assert '"24 7,9 * * 1-5"' in gate            # the backstop cron it recognises
    assert "scripts/ignition_asx_due.py" in gate
    assert ASX["permissions"] == {"contents": "write"}


def test_the_post_close_cron_is_after_the_close_in_both_dst_regimes():
    """The close is 16:40 Sydney (Yahoo shows the auction ~20 min late). Under
    AEDT the 06:24 UTC primary is past it; under AEST it is 16:24, so the
    GATED 07:24 UTC backstop is the first run past the close and re-screens
    (the gate sees a file generated before the close)."""
    from zoneinfo import ZoneInfo
    syd = ZoneInfo("Australia/Sydney")
    g = config.MORNING_PLAYS_SLOT_GATE["asx"]
    close = (g["hour"], g["minute"])
    def local(day, hhmm):
        t = dt.datetime.fromisoformat(f"{day}T{hhmm}:00+00:00").astimezone(syd)
        return (t.hour, t.minute)
    assert local("2026-12-15", "06:24") >= close                   # AEDT primary
    assert local("2026-07-15", "06:24") < close <= local("2026-07-15", "07:24")   # AEST
    assert _due("2026-07-15T06:24:00+00:00", "2026-07-15T07:24:00+00:00") == "run=true"


def test_the_asx_kick_is_neither_the_scan_kick_nor_the_crypto_kick():
    kick = ".github/ignition-asx-kick"
    assert kick not in str(_on(CRYPTO)) and ".github/ignition-kick" not in str(_on(ASX))
    ds = yaml.safe_load((WFDIR / "dispatch_scan.yml").read_text(encoding="utf-8"))
    assert kick not in str(_on(ds))


# ---------------------------------------------------------------------------
# the backstop gate script (stdlib only: it runs before pip install)
# ---------------------------------------------------------------------------

GATE = ROOT / "scripts" / "ignition_asx_due.py"


def _due(stamp, now):
    p = subprocess.run([sys.executable, str(GATE), stamp, "--now", now],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.mark.parametrize("stamp,now,want", [
    # AEST (UTC+10): close 16:40 = 06:40 UTC
    ("2026-07-15T06:45:00+00:00", "2026-07-15T07:24:00+00:00", "run=false"),
    ("2026-07-15T06:30:00+00:00", "2026-07-15T07:24:00+00:00", "run=true"),
    ("2026-07-15T04:54:00+00:00", "2026-07-15T07:24:00+00:00", "run=true"),
    ("2026-07-14T06:30:00+00:00", "2026-07-15T07:24:00+00:00", "run=true"),
    # AEDT (UTC+11): close 16:40 = 05:40 UTC
    ("2026-12-15T05:45:00+00:00", "2026-12-15T07:24:00+00:00", "run=false"),
    ("2026-12-15T05:30:00+00:00", "2026-12-15T07:24:00+00:00", "run=true"),
    ("2026-12-15T05:00:00+00:00", "2026-12-15T07:24:00+00:00", "run=true"),
    # Monday before the close: the last close is FRIDAY's
    ("2026-09-25T06:45:00+00:00", "2026-09-28T01:00:00+00:00", "run=false"),
    # unreadable -> fail OPEN
    ("", "2026-07-15T07:24:00+00:00", "run=true"),
    ("garbage", "2026-07-15T07:24:00+00:00", "run=true"),
    ("2026-07-15T06:30:00", "2026-07-15T07:24:00+00:00", "run=true"),
])
def test_the_gate(stamp, now, want):
    assert _due(stamp, now) == want


def test_the_gate_script_imports_only_the_standard_library_and_config():
    src = GATE.read_text(encoding="utf-8")
    mods = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert mods <= {"__future__", "datetime", "pathlib", "sys", "zoneinfo", "scanner"}
    cfg = (ROOT / "scanner" / "config.py").read_text(encoding="utf-8")
    assert set(re.findall(r"^(?:from|import)\s+([\w.]+)", cfg, re.M)) <= {"dataclasses"}

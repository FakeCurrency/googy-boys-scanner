"""Scan pipeline: hysteresis vs grade_raw + traded-plan headline (H1+H2, 2026-07-20).

First integration-level coverage of scan_vivek_market's grading/headline
assembly (the review flagged it as untested). The signal engine is stubbed so
these tests pin the PIPELINE contract, not detection maths:

  * row["grade"]      = hysteresis-held then gated   (display)
  * row["grade_raw"]  = raw then gated               (what the bot may buy)
  * headline entry/stop/TP/R:R = the TRADED plan (gated TF when armed,
    1D fallback when watching), labelled by headline_tf
  * a weekly-armed setup with no usable 1D plan is still published
  * vivek_bot buys off grade_raw, never the smoothed grade
"""

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import scan
from scanner.broker import vivek_bot

pytestmark = pytest.mark.risk


def _frame():
    idx = pd.date_range(end="2024-01-02", periods=30, freq="D")
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1_000_000.0}, index=idx)


def _plan(entry, armed, trigger="reclaim"):
    risk = entry - (entry - 4.0)
    return {"armed": armed, "entry": entry, "stop": entry - 4.0,
            "tp1": entry + 6.0, "tp2": entry + 8.0, "tp3": entry + 12.0,
            "scale": [0.25, 0.50, 0.15], "risk": 4.0,
            "rr": round((entry + 8.0 - entry) / risk, 2),   # 2.0
            "entry_trigger": trigger if armed else None,
            "trigger_bar": "2024-01-02" if armed else None}


_SIG = {"direction": "long", "close": 100.0, "level_tf": "weekly", "level": 99.0,
        "at_level": True, "reaction": "bounce", "structure": 0.8, "confluence": False}


def _stub_engine(monkeypatch, plans, raw=("A+", 8), held=None):
    monkeypatch.setattr(vivek, "evaluate", lambda df: dict(_SIG))
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (raw[1], raw[0], ["CHIP"]))
    if held is not None:  # force a hysteresis hold different from the raw grade
        monkeypatch.setattr(vivek, "apply_grade_hysteresis",
                            lambda *a, **k: (held, 1))
    monkeypatch.setattr(vivek, "build_plans", lambda df, sig: dict(plans))
    monkeypatch.setattr(vivek, "build_markers", lambda plans: {})
    monkeypatch.setattr(vivek, "build_detail", lambda df, sig, lv: {})
    monkeypatch.setattr(vivek, "narrative", lambda *a, **k: "n/a")
    monkeypatch.setattr(vivek, "entry_types", lambda sig: ["reclaim"])


def _run():
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"}]
    out = scan.scan_vivek_market("asx", universe=uni,
                                 frames={"BHP.AX": _frame()},
                                 pulse_data=[], progress=False)
    return out["results"]


def test_headline_follows_the_armed_traded_plan(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False), "1W": _plan(103.0, armed=True)}
    (row,) = _run() if _stub_engine(monkeypatch, plans) is None else ()
    assert row["headline_tf"] == "1W" and row["armed_tf"] == "1W"
    assert row["entry"] == 103.0 and row["stop"] == 99.0     # weekly numbers
    assert row["entry_trigger"] == "reclaim"
    assert row["grade"] == "A+" and row["grade_raw"] == "A+"


def test_watching_setup_keeps_1d_headline_and_caps_at_b_plus(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False), "1W": _plan(103.0, armed=False)}
    (row,) = _run() if _stub_engine(monkeypatch, plans) is None else ()
    assert row["headline_tf"] == "1D" and row["armed_tf"] is None
    assert row["entry"] == 100.0
    assert row["grade"] == "B+" and row["grade_raw"] == "B+"   # gate demotes both


def test_weekly_armed_setup_without_1d_plan_is_still_published(monkeypatch):
    plans = {"1W": _plan(103.0, armed=True)}                   # no 1D plan at all
    (row,) = _run() if _stub_engine(monkeypatch, plans) is None else ()
    assert row["headline_tf"] == "1W" and row["entry"] == 103.0
    # the pre-H1 code `continue`d on a missing/bad 1D plan and hid this row


def test_display_hold_does_not_leak_into_grade_raw(monkeypatch):
    # raw decayed to A, hysteresis holds the DISPLAYED grade at A+:
    plans = {"1D": _plan(100.0, armed=True)}
    _stub_engine(monkeypatch, plans, raw=("A", 7), held="A+")
    (row,) = _run()
    assert row["grade"] == "A+"          # what the user sees (smoothed)
    assert row["grade_raw"] == "A"       # what the bot is allowed to buy


def test_bot_skips_stale_cache_reused_rows(monkeypatch):
    """2026-07-20 (Phase 2): a row built from a cache-reused frame carries
    data_age_days > 0 — its armed trigger describes a market that has since
    moved. The bot must never open on it; fresh rows pass untouched."""
    from scanner import config as _c
    monkeypatch.setattr(_c, "VIVEK_BOT_MAX_DATA_AGE_DAYS", 3, raising=False)
    row = {"symbol": "BHP", "name": "BHP", "sector": "Materials", "dir": "LONG",
           "grade": "A+", "grade_raw": "A+", "entry_types": ["reclaim"],
           "plans": {"1W": _plan(103.0, armed=True)}, "price": 103.0,
           "data_age_days": 5}
    out = vivek_bot.evaluate_setup(row)
    assert out["take"] is False and out["code"] == "stale_data"

    row["data_age_days"] = 0
    assert vivek_bot.evaluate_setup(row)["take"] is True
    del row["data_age_days"]                       # absent field == fresh
    assert vivek_bot.evaluate_setup(row)["take"] is True


def test_bot_buys_off_grade_raw_not_the_smoothed_grade():
    plans = {"1W": _plan(103.0, armed=True)}
    row = {"symbol": "BHP", "name": "BHP", "sector": "Materials", "dir": "LONG",
           "grade": "A+", "grade_raw": "A", "entry_types": ["reclaim"],
           "plans": plans, "price": 103.0}
    out = vivek_bot.evaluate_setup(row)
    assert out["take"] is False and out["code"] == "not_a_plus"

    row["grade_raw"] = "A+"
    out = vivek_bot.evaluate_setup(row)
    assert out["take"] is True and out["timeframe"] == "1W"

    legacy = dict(row)                    # pre-v4 JSON: no grade_raw field
    legacy.pop("grade_raw")
    assert vivek_bot.evaluate_setup(legacy)["take"] is True   # falls back to grade


# ── the pipeline funnel: drop-offs as numbers, not feelings (2026-07-29) ─────
# Published with every scan so "is a filter too restrictive?" is answerable
# from the artefact. Counted at the loop's own `continue` points — pure
# observation; these tests also pin the identity so a future drop point that
# forgets its counter shows up as a hole in the arithmetic.

def _run_full(monkeypatch, frames=None, uni=None):
    uni = uni or [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"}]
    return scan.scan_vivek_market("asx", universe=uni,
                                  frames=frames or {"BHP.AX": _frame()},
                                  pulse_data=[], progress=False)


def test_funnel_counts_a_clean_setup_through_to_grades(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    f = _run_full(monkeypatch)["funnel"]
    assert f["universe"] == 1 and f["with_data"] == 1
    assert f["setups"] == 1 and f["grades"].get("A+") == 1
    assert f["no_setup"] == f["illiquid_setup"] == f["below_score"] == f["no_plan"] == 0


def test_funnel_counts_no_setup(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(vivek, "evaluate", lambda df: None)
    f = _run_full(monkeypatch)["funnel"]
    assert f["no_setup"] == 1 and f["setups"] == 0


def test_funnel_counts_an_illiquid_setup_separately(monkeypatch):
    # The interesting number: a name that HAD a setup and was dropped for
    # turnover — the row a too-tight liquidity floor would be killing.
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 0.0)
    f = _run_full(monkeypatch)["funnel"]
    assert f["illiquid_setup"] == 1 and f["no_setup"] == 0 and f["setups"] == 0


def test_funnel_counts_below_score_and_no_plan(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (0, None, []))
    assert _run_full(monkeypatch)["funnel"]["below_score"] == 1
    _stub_engine(monkeypatch, {})          # no plans at all -> no headline plan
    f = _run_full(monkeypatch)["funnel"]
    assert f["no_plan"] == 1 and f["setups"] == 0


def test_funnel_identity_holds_with_a_thrown_name(monkeypatch):
    # Two names: one clean A+, one whose evaluate throws. The thrown one lands
    # in `errors`, and the identity must still balance exactly.
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    real_frame = _frame()
    calls = {"n": 0}

    def evaluate(df):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("synthetic failure")
        return dict(_SIG)
    monkeypatch.setattr(vivek, "evaluate", evaluate)
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"},
           {"yf": "RIO.AX", "symbol": "RIO", "name": "RIO", "sector": "Materials"}]
    out = _run_full(monkeypatch, frames={"BHP.AX": real_frame, "RIO.AX": real_frame}, uni=uni)
    f = out["funnel"]
    assert f["errors"] == 1 and f["setups"] == 1
    assert (f["with_data"] == f["no_setup"] + f["illiquid_setup"] + f["below_score"]
            + f["no_plan"] + f["errors"] + f["setups"]), f"funnel does not balance: {f}"


def test_funnel_is_additive_not_a_schema_bump(monkeypatch):
    # Same contract as `errors` (TOP100 #60): consumers read named keys and the
    # schema gates read schema_version alone, so this key must ride the
    # CURRENT version rather than forcing every committed scan stale.
    from scanner import config
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    out = _run_full(monkeypatch)
    assert out["schema_version"] == config.VIVEK_SCHEMA_VERSION
    assert isinstance(out["funnel"], dict)


def test_illiquid_sample_carries_volume_context(monkeypatch):
    """The floor's kills publish WHO they were and whether volume is arriving —
    the evidence for the owner's liquidity-exception decision (2026-07-29)."""
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 0.0)
    spiky = _frame()
    spiky.loc[spiky.index[-1], "Volume"] = 5_000_000.0   # 5M vs 19x1M history
    out = scan.scan_vivek_market(
        "asx", universe=[{"yf": "THN.AX", "symbol": "THN", "name": "Thin", "sector": "Energy"}],
        frames={"THN.AX": spiky}, pulse_data=[], progress=False)
    sample = out["funnel"]["illiquid_sample"]
    assert len(sample) == 1
    row = sample[0]
    assert row["symbol"] == "THN" and row["dir"] == "LONG"
    assert row["turnover"] == 0
    # avg20 includes today's bar: (19*1M + 5M)/20 = 1.2M -> 5/1.2 = 4.2x
    assert row["rvol"] == 4.2


def test_illiquid_sample_is_sorted_by_rvol_and_capped(monkeypatch):
    from scanner import config
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 0.0)
    monkeypatch.setattr(config, "SCAN_FUNNEL_ILLIQUID_SAMPLE_MAX", 1, raising=False)
    quiet, spiky = _frame(), _frame()
    spiky.loc[spiky.index[-1], "Volume"] = 5_000_000.0
    out = scan.scan_vivek_market(
        "asx",
        universe=[{"yf": "AAA.AX", "symbol": "AAA", "name": "A", "sector": "Energy"},
                  {"yf": "BBB.AX", "symbol": "BBB", "name": "B", "sector": "Energy"}],
        frames={"AAA.AX": quiet, "BBB.AX": spiky}, pulse_data=[], progress=False)
    sample = out["funnel"]["illiquid_sample"]
    assert [r["symbol"] for r in sample] == ["BBB"], \
        "the cap must keep the HIGHEST-rvol name, not the first-iterated one"
    assert out["funnel"]["illiquid_setup"] == 2, "the count still covers everyone"


def test_illiquid_sample_is_present_and_empty_when_nothing_dropped(monkeypatch):
    # The UI's "none show unusual volume" claim is only allowed off a
    # PRESENT-and-empty array; an absent key means an older payload.
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    out = _run_full(monkeypatch)
    assert out["funnel"]["illiquid_sample"] == []


# ── the "liquidity arriving" list (owner-ruled 2026-07-30) ───────────────────
# Two-leg rule on the floor's kills; its own fenced file; report-only. These
# tests ARE the four fences from the design note — each one pins a boundary
# the ruling made a hard limit.

def _spiky_frame(close=100.0, hist_vol=1_000.0, today_vol=5_000.0):
    f = _frame()
    f["Close"] = close
    f["Volume"] = hist_vol
    f.loc[f.index[-1], "Volume"] = today_vol
    return f


def _run_arriving(monkeypatch, tmp_path, frames, uni=None):
    uni = uni or [{"yf": "THN.AX", "symbol": "THN", "name": "Thin Co", "sector": "Energy"}]
    out = scan.scan_vivek_market("asx", universe=uni, frames=frames,
                                 pulse_data=[], progress=False, out_root=str(tmp_path))
    import json as _json
    arr = _json.loads((tmp_path / "asx_arriving.json").read_text(encoding="utf-8"))
    return out, arr


def test_arriving_two_legs_qualify_together(monkeypatch, tmp_path):
    """Today clears the floor alone AND rvol >= 3: publishes, with the schema
    the design note promised — and the name is STILL dropped from the scan."""
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 50_000.0)   # avg under the floor
    # today: 100.0 x 5,000 = A$500k >= A$100k floor; rvol = 5000/1200 = 4.2
    out, arr = _run_arriving(monkeypatch, tmp_path, {"THN.AX": _spiky_frame()})
    assert [r["symbol"] for r in arr["results"]] == ["THN"]
    row = arr["results"][0]
    assert row["turnover_today"] == 500_000 and row["rvol"] == 4.2
    assert row["turnover_avg20"] == 50_000 and row["adv_usd"] == 50_000.0
    assert row["fund"] is False and row["dir"] == "LONG"
    assert arr["rule"]["floor"] == 100_000 and arr["rule"]["min_rvol"] == 3.0
    # fence: still dropped — not graded, not published, counted as a kill
    assert out["results"] == []
    assert out["funnel"]["illiquid_setup"] == 1
    assert out["funnel"]["arriving"] == 1


def test_arriving_leg_a_excludes_dust_no_matter_the_multiple(monkeypatch, tmp_path):
    """An 18x day on dust stays out — leg A is the load-bearing half."""
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 500.0)
    # today: 0.01 x 90,000 = A$900 << floor, rvol = 90000/5450 = 16.5
    out, arr = _run_arriving(monkeypatch, tmp_path,
                             {"THN.AX": _spiky_frame(close=0.01, hist_vol=1_000, today_vol=90_000)})
    assert arr["results"] == []                      # present AND empty
    assert out["funnel"]["illiquid_setup"] == 1      # still an audited kill
    assert out["funnel"]["arriving"] == 0


def test_arriving_leg_b_excludes_ordinary_volume(monkeypatch, tmp_path):
    """Today clears the floor but volume is ordinary (rvol < 3): not 'arriving'."""
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 90_000.0)
    # today: 100 x 4,400 = A$440k >= floor, rvol = 4400/(19*4000+4400 over 20)=4400/4020=1.1
    out, arr = _run_arriving(monkeypatch, tmp_path,
                             {"THN.AX": _spiky_frame(hist_vol=4_000, today_vol=4_400)})
    assert arr["results"] == []
    assert out["funnel"]["arriving"] == 0


def test_arriving_rows_carry_no_tradeable_fields(monkeypatch, tmp_path):
    """Fence 4: no grade, no grade_raw, no plans, no entry — a mis-wire into a
    bot path fails the bot's own field requirements instead of trading."""
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 50_000.0)
    _out, arr = _run_arriving(monkeypatch, tmp_path, {"THN.AX": _spiky_frame()})
    row = arr["results"][0]
    for banned in ("grade", "grade_raw", "plans", "entry", "stop", "tp1", "score"):
        assert banned not in row, f"arriving row must never carry '{banned}'"


def test_arriving_results_identity_fence(monkeypatch, tmp_path):
    """Fence 2: the published results array is IDENTICAL whether or not a
    qualifying name exists — the list is computed from the drop path."""
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    liq = {"BHP.AX": 10_000_000.0, "THN.AX": 50_000.0}

    def fake_liq(df, m, _map=liq):
        # keyed by frame identity via a column marker set below
        return _map["THN.AX"] if float(df["Volume"].iloc[-1]) == 5_000.0 else _map["BHP.AX"]
    monkeypatch.setattr(scan, "_liquidity", fake_liq)
    uni2 = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"},
            {"yf": "THN.AX", "symbol": "THN", "name": "Thin Co", "sector": "Energy"}]
    out_with, arr_with = _run_arriving(monkeypatch, tmp_path,
                                       {"BHP.AX": _frame(), "THN.AX": _spiky_frame()}, uni=uni2)
    out_without, _ = _run_arriving(monkeypatch, tmp_path, {"BHP.AX": _frame()},
                                   uni=[uni2[0]])
    assert [r["symbol"] for r in arr_with["results"]] == ["THN"]
    strip = lambda rows: [{k: v for k, v in r.items()} for r in rows]  # noqa: E731
    assert strip(out_with["results"]) == strip(out_without["results"]), \
        "a qualifying thin name must not change the published results in ANY way"


def test_arriving_fund_shaped_names_arrive_pre_tagged(monkeypatch, tmp_path):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 50_000.0)
    uni = [{"yf": "IHEB.AX", "symbol": "IHEB", "name": "iShares Core Bond ETF", "sector": ""}]
    _out, arr = _run_arriving(monkeypatch, tmp_path, {"IHEB.AX": _spiky_frame()}, uni=uni)
    assert arr["results"][0]["fund"] is True


def test_fence_1_nothing_in_broker_ever_opens_the_arriving_file():
    """Fence 1, the structural one: the bot's input surface is the scan
    payload; no CODE-shaped reference to the arriving artefact may appear in
    scanner/broker/. (The bare English word 'arriving' exists in two old
    comments there — prose is not a wire, so the probe matches the file stem
    and identifier shapes instead.)"""
    import pathlib as _pl
    broker = _pl.Path(scan.__file__).parent / "broker"
    offenders = [p.name for p in broker.glob("*.py")
                 if any(tok in p.read_text(encoding="utf-8", errors="ignore")
                        for tok in ("_arriving", "arriving.json", "ARRIVING"))]
    assert offenders == [], f"broker code references the arriving artefact: {offenders}"

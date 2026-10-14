"""Sanity tests for scripts/alert_edge_report.py (edge-research batch, 2026-08-20).

A research script whose math is wrong produces confident nonsense, so every
number-producing function is verified against a small fixture computed by
hand. The report's prose is not tested; the arithmetic is.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "alert_edge_report", ROOT / "scripts" / "alert_edge_report.py")
aer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aer)


def test_signed_returns_flip_for_shorts_only():
    # A short alert followed by a -3% move WENT THE ALERT'S WAY: +3% edge.
    assert aer.signed(0.03, "long") == 0.03
    assert aer.signed(-0.03, "short") == 0.03
    assert aer.signed(0.03, "short") == -0.03
    assert aer.signed(None, "long") is None


def test_cohort_stats_by_hand():
    s = aer.cohort_stats([0.10, -0.05, 0.05, None])
    assert s["n"] == 3, "None never counts as an observation"
    assert abs(s["mean"] - (0.10 - 0.05 + 0.05) / 3) < 1e-12
    assert abs(s["median"] - 0.05) < 1e-12
    assert abs(s["win"] - 2 / 3) < 1e-12
    # population sd of [.1,-.05,.05] = sqrt(mean((x-mean)^2)); SE = sd/sqrt(3)
    m = s["mean"]
    sd = math.sqrt(sum((x - m) ** 2 for x in (0.10, -0.05, 0.05)) / 3)
    assert abs(s["se"] - sd / math.sqrt(3)) < 1e-12
    assert aer.cohort_stats([])["n"] == 0


def test_dedup_keeps_the_FIRST_alignment_only():
    rows = [
        {"market": "asx", "ticker": "BHP", "side": "long", "base_day": "2026-08-10", "v": 2},
        {"market": "asx", "ticker": "BHP", "side": "long", "base_day": "2026-08-08", "v": 1},
        {"market": "asx", "ticker": "BHP", "side": "short", "base_day": "2026-08-09", "v": 3},
        {"market": "nasdaq", "ticker": "BHP", "side": "long", "base_day": "2026-08-11", "v": 4},
    ]
    out = aer.dedup_first(rows)
    assert [x["v"] for x in out] == [1, 3, 4], \
        "earliest base_day wins per (market,ticker,side); other identities survive"


def test_forward_return_is_h_sessions_not_h_days():
    days = ["d1", "d2", "d3", "d4", "d5", "d6", "d7"]
    snaps = {d: {"prices": {"XYZ": 100.0 + i}} for i, d in enumerate(days)}
    r = aer.forward_return(days, snaps, "d1", "XYZ", 5)
    assert abs(r - (105.0 / 100.0 - 1)) < 1e-12, "5 sessions forward = index +5"
    assert aer.forward_return(days, snaps, "d3", "XYZ", 5) is None, \
        "right-censored: no session d3+5 yet"
    assert aer.forward_return(days, snaps, "d1", "MISSING", 5) is None
    snaps["d1"]["prices"]["ZERO"] = 0.0
    assert aer.forward_return(days, snaps, "d1", "ZERO", 5) is None, "a zero base is not a return"


def test_too_thin_buckets_are_labelled_not_reported_as_findings():
    line = aer.fmt(aer.cohort_stats([0.01] * (aer.MIN_N - 1)), "x")
    assert "TOO THIN" in line
    line = aer.fmt(aer.cohort_stats([0.01] * aer.MIN_N), "x")
    assert "TOO THIN" not in line


def test_roster_baseline_keeps_the_cohorts_disjoint(capsys):
    # A name that aligned on a day must not also count as that day's plain-A+
    # baseline — double-counting one bet on both sides of the comparison.
    entries = [{"market": "asx", "base_day": "2026-08-01", "ticker": "BHP",
                "side": "long", "fwd": {"5": 0.05}}]
    rosters = [{"market": "asx", "base_day": "2026-08-01", "ticker": "BHP",
                "side": "long", "fwd": {"5": 0.99}},
               {"market": "asx", "base_day": "2026-08-01", "ticker": "CBA",
                "side": "long", "fwd": {"5": 0.02}}]
    aer.roster_report(entries, rosters)
    out = capsys.readouterr().out
    roster_line = next(l for l in out.splitlines() if "roster A+ dedup" in l)
    assert "n=   1" in roster_line, f"BHP must be excluded from the baseline: {roster_line}"
    assert "+2.00%" in roster_line, "only CBA's return may enter"


def test_day_clustered_view_prints_in_the_ledger_report(capsys, monkeypatch):
    entries = []
    for day in ("2026-08-01", "2026-08-02"):
        for i in range(3):
            entries.append({"market": "asx", "base_day": day, "ticker": f"T{day}{i}",
                            "side": "long", "count": 2, "lenses": ["PHASEMAP", "VIVEK"],
                            "fwd": {"5": 0.01 * (i + 1), "10": None, "20": None, "1": None}})
    monkeypatch.setattr(aer, "load_sectors", lambda: {})
    aer.ledger_report(entries)
    out = capsys.readouterr().out
    assert "day-clustered means" in out
    line = next(l for l in out.splitlines() if "day-clustered means" in l and "n=" in l)
    assert "n=   2" in line, f"two base days -> two clustered observations: {line}"


def test_the_script_is_read_only_research():
    src = (ROOT / "scripts" / "alert_edge_report.py").read_text(encoding="utf-8")
    for verb in ("write_json", "os.replace", 'open(', ):
        pass  # open() is used read-only; assert no write modes instead
    assert '"w"' not in src and "'w'" not in src, "the report must never write a file"
    for p in (ROOT / "scanner").rglob("*.py"):
        assert "alert_edge_report" not in p.read_text(encoding="utf-8"), \
            f"the engine must not import the research script: {p}"


# ── REFINE200 (2026-10-14): exclusions, excess, sectors, the hc rule ─────────

def _r(day, market="asx", ticker="NGI", side="long", **kw):
    return {"market": market, "base_day": day, "ticker": ticker, "side": side,
            "fwd": {"5": 0.01}, **kw}


def test_weekend_copies_of_one_base_bar_are_excluded_and_counted():
    """#140: Sat/Sun stock rows were measured from Monday's close - the same
    bar as Monday's own row. One observation, counted once."""
    sat, sun, mon = _r("2026-10-10"), _r("2026-10-11"), _r("2026-10-12")
    kept, n = aer.clean([sat, sun, mon], prices={})
    assert kept == [mon] and n["weekend_duplicates"] == 2
    kept, n = aer.clean([sat, sun], prices={})
    assert kept == [sat] and n["weekend_duplicates"] == 1, "a weekend-only name keeps its first copy"
    other = _r("2026-10-11", ticker="XYZ")
    assert aer.clean([other, mon], prices={})[0] == [other, mon], "different names are never collapsed"
    crypto = [_r("2026-10-10", market="crypto"), _r("2026-10-11", market="crypto")]
    assert aer.clean(crypto, prices={})[0] == crypto, "crypto trades at the weekend"


def test_a_legacy_wrong_token_crypto_row_is_excluded_and_counted():
    jup = _r("2026-09-29", market="crypto", ticker="JUP", base_close=0.000327)
    ok = _r("2026-09-29", market="crypto", ticker="ETH", base_close=2400.0)
    new = _r("2026-10-13", market="crypto", ticker="JUP", base_close=0.000327, price_source="binance_vision")
    kept, n = aer.clean([jup, ok, new], prices={"JUP": 0.3354, "ETH": 2505.5})
    assert kept == [ok, new] and n["crypto_wrong_token"] == 1
    from scanner import config
    f = config.EDGE_CRYPTO_WRONG_TOKEN_FACTOR
    near = _r("2026-09-29", market="crypto", ticker="QNT", base_close=70.0)
    assert aer.clean([near], prices={"QNT": 70.0 * (f - 1)})[0] == [near], "a big real move is not a stranger"


def test_excess_is_the_move_beyond_the_market_in_the_called_direction():
    long_ = {"side": "long", "fwd": {"5": 0.05}, "bench": {"5": 0.02}}
    short = {"side": "short", "fwd": {"5": -0.05}, "bench": {"5": -0.01}}
    assert abs(aer.excess(long_, "5") - 0.03) < 1e-12
    assert abs(aer.excess(short, "5") - 0.04) < 1e-12, "a short that fell 4pp more than the index"
    assert aer.excess({"side": "long", "fwd": {"5": 0.05}}, "5") is None, "no benchmark -> no excess"


def test_sector_labels_fold_to_gics_for_analysis_only():
    assert aer.norm_sector("Financial Services") == "Financials"
    assert aer.norm_sector("Banks") == aer.norm_sector("Insurance") == "Financials"
    assert aer.norm_sector("Healthcare") == "Health Care"
    assert aer.norm_sector("Equity Real Estate Investment Trusts (REITs)") == "Real Estate"
    assert aer.norm_sector("Energy") == "Energy" and aer.norm_sector("") == "(no sector)"
    assert aer.sector_of({"market": "nasdaq", "ticker": "X", "sector": "Technology"}, {}) == \
        "Information Technology", "the row's own frozen sector wins"


def test_the_alias_table_never_reaches_the_bot():
    """#40 is analysis-only: the bot's per-sector cap keeps its own labels
    (overwriting a sector there is a trade change - REFINEMENTS #112)."""
    for p in (ROOT / "scanner").rglob("*.py"):
        if p.name == "config.py":
            continue
        text = p.read_text(encoding="utf-8")
        assert "EDGE_SECTOR_ALIASES" not in text and "EDGE_CRYPTO_WRONG_TOKEN_FACTOR" not in text, p


def test_legacy_roster_rows_are_split_by_the_rule_in_force_when_filed():
    assert aer.hc_rule_of({"base_day": "2026-09-10"}) == aer.HC_RULE_RETIRED
    assert aer.hc_rule_of({"base_day": "2026-09-19"}) == aer.HC_RULE_UNKNOWN
    assert aer.hc_rule_of({"base_day": "2026-10-01"}) == aer.HC_RULE_FOUR_CELL
    assert aer.hc_rule_of({"base_day": "2026-09-10", "hc_rule": "x"}) == "x", "a stamp always wins"


def test_the_legacy_four_cell_label_is_what_the_roster_stamps_today():
    spec2 = importlib.util.spec_from_file_location("edge_rosters", ROOT / "scripts" / "edge_rosters.py")
    er = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(er)
    assert er.hc_rule() == aer.HC_RULE_FOUR_CELL, \
        "HC_CELLS moved: keep HC_RULE_FOUR_CELL as the 2026-09-21..10-14 rule, do not edit it"


def test_the_roster_reader_sees_shards_and_the_unmigrated_file_alike(tmp_path):
    import json
    spec2 = importlib.util.spec_from_file_location("edge_rosters", ROOT / "scripts" / "edge_rosters.py")
    er = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(er)
    path = tmp_path / "edge_rosters.json"
    rows = [dict(_r("2026-08-20"), key="a"), dict(_r("2026-09-02"), key="b")]
    path.write_text(json.dumps({"entries": rows}), encoding="utf-8")
    assert aer.load_rosters(str(path)) == rows
    led = er.load_ledger(str(path))
    er.write_ledger(led, str(path))
    assert aer.load_rosters(str(path)) == rows == er.load_ledger(str(path))["entries"]


def test_the_report_prints_its_exclusions_and_excess(tmp_path, monkeypatch, capsys):
    import json
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"entries": [
        dict(_r("2026-10-12"), count=2, lenses=["PHASEMAP", "VIVEK"], fwd={"5": 0.05}, bench={"5": 0.01}),
        dict(_r("2026-10-11"), count=2, lenses=["PHASEMAP", "VIVEK"])]}), encoding="utf-8")
    monkeypatch.setattr(aer, "LEDGER", str(led))
    monkeypatch.setattr(aer, "ROSTERS", str(tmp_path / "none.json"))
    monkeypatch.setattr(aer, "load_sectors", lambda: {})
    assert aer.main([]) == 0
    out = capsys.readouterr().out
    assert "'weekend_duplicates': 1" in out
    line = next(l for l in out.splitlines() if "EXCESS vs index" in l)
    assert "n=   1" in line and "+4.00%" in line

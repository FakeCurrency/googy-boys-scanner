"""NEXT100 Stage 2 (#15, #20, #18): the replay as a fair judge.

* #15 the books run at the live caps scaled to the sample's share of the
  universe (min 3 slots); total R and the live-mix R sit beside every
  R/slot-month
* #20 blank (NASDAQ) sectors are filled from sector_map -> universe_cache ->
  the live book, so the per-market sector cap binds as live
* #18 a passing variant is re-run on a second sample sharing no name with
  the first and its verdict reads PASS (replicated) / PASS (not replicated)

Simulation only: synthetic series, committed files read through tmp roots.
"""
from __future__ import annotations

import json

import pytest

from scanner import config, replay_replicate as rr, replay_stats as rs
from scanner import vivek_parity as vp
from scanner.vivek_backtest import _sample

from tests.test_decision_replay import W1R, _series

pytestmark = pytest.mark.risk


# ------------------------------------------------- #15 slot scale

def test_a_half_sampled_universe_halves_the_caps(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 60)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 6)
    sc = rs.slot_scale({"asx": {"symbols": 5, "universe": 10}}, mode="universe")
    assert (sc["max_open_total"], sc["max_per_sector"]) == (30, 3)
    assert sc["share"] == 0.5 and sc["by_market"]["asx"]["share"] == 0.5
    assert sc["live"] == {"max_open_total": 60, "max_per_sector": 6}
    assert sc["floors"] == {"max_open_total": 3, "max_per_sector": 1} and sc["floored"] == []


def test_the_share_is_pooled_across_markets_and_floors_at_three_slots(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 60)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 6)
    monkeypatch.setattr(config, "VIVEK_PARITY_SLOT_SCALE_MIN", 3)
    cov = {"asx": {"symbols": 1, "universe": 1000}, "nasdaq": {"symbols": 1, "universe": 1000}}
    sc = rs.slot_scale(cov, mode="universe")
    assert sc["share"] == 0.001
    assert sc["max_open_total"] == 3 and sc["max_per_sector"] == 1
    assert sc["floored"] == ["max_open_total", "max_per_sector"]
    port = {"skipped": {}, "taken": 0, "peak_open": 0}
    line = vp.slot_scale_lines(sc, port, {})[0]
    assert line.isascii() and "floors 3 total / 1 per sector (the total and per-sector floor binds)" in line
    sc = rs.slot_scale({"asx": {"symbols": 24, "universe": 100}}, mode="universe")
    assert (sc["max_open_total"], sc["max_per_sector"]) == (14, 1) and sc["floored"] == []
    assert ("caps 14 total / 1 per sector per market (live 60 / 6); book_full 0, sector_cap 0, "
            "taken 0, peak 0; floors 3 total / 1 per sector") in vp.slot_scale_lines(sc, port, {})[0]
    # the OOS denominator is the universe BEFORE the exclusion
    sc = rs.slot_scale({"asx": {"symbols": 5, "universe": 8, "universe_before_exclude": 10}},
                       mode="universe")
    assert sc["share"] == 0.5 and sc["max_open_total"] == 30 and sc["floored"] == []


def test_mode_none_and_a_whole_universe_keep_the_live_caps(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 60)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 6)
    assert rs.slot_scale({"asx": {"symbols": 5, "universe": 10}}, mode="none")["max_open_total"] == 60
    assert "floors" not in rs.slot_scale({"asx": {"symbols": 5, "universe": 10}}, mode="none")
    full = rs.slot_scale({"asx": {"symbols": 10, "universe": 10}}, mode="universe")
    assert (full["max_open_total"], full["max_per_sector"]) == (60, 6) and "floors" not in full
    assert config.VIVEK_PARITY_SLOT_SCALE in ("universe", "none")


def test_the_scaled_caps_bind_the_baseline_and_every_variant_and_print(monkeypatch):
    """A 6-name universe sampled 3/6 at live caps 4/6 runs the books at 2
    total (min 3 lowered to 2 for the test) and prints both book_full counts."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 4)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 6)
    monkeypatch.setattr(config, "VIVEK_PARITY_SLOT_SCALE", "universe")
    monkeypatch.setattr(config, "VIVEK_PARITY_SLOT_SCALE_MIN", 2)
    monkeypatch.setattr(config, "VIVEK_PARITY_REPLICATE", False)

    def fake_load(mk, limit, period, exclude_symbols=None, workers=1):
        ss = [_series(f"{mk[:1].upper()}{i}", market=mk, signals=[(0, W1R, "A+", "weekly")])
              for i in range(3)]
        return ss, {"symbols": 3, "universe": 6, "sampled_pct": 50.0, "replayed": 3,
                    "signals": 3, "data_sources": {"by_source": {"x": 3}},
                    "sectors": {"named": 3, "total": 3, "filled": {"sector_map": 3}},
                    "sampled_symbols": [s.symbol for s in ss]}

    monkeypatch.setattr(vp, "load_market_series", fake_load)
    monkeypatch.setattr(vp, "fx_rates", lambda: {"audusd": 0.66, "source": "fallback"})
    rep = vp.run_parity(["nasdaq"], 3, "5y", workers=1)
    sc = rep["baseline"]["slot_scale"]
    assert sc["max_open_total"] == 2 and sc["unscaled"]["book_full"] == 0
    port = rep["baseline"]["portfolio"]
    assert port["taken"] == 2 and port["skipped"]["book_full"] == 1
    assert port["params"]["max_open_total"] == 2
    for vr in rep["variants"].values():
        assert vr["portfolio"]["params"]["max_open_total"] == 2
    assert "total_r" in port and "live_mix_r" in port
    md = vp.summary_markdown(rep)
    assert "slot scale `universe`: sample share 50.0%" in md
    assert "caps 2 total / 3 per sector per market (live 4 / 6)" in md
    assert "floors 2 total / 1 per sector" in md
    assert "book_full 1" in md and "at the live caps: book_full 0" in md
    assert "| total R | live-mix R |" in md and "sectors 3/3 named (filled sector_map 3)" in md
    assert "### Replication" in md and "not run: VIVEK_PARITY_REPLICATE is off" in md
    for line in md.splitlines():
        if line.startswith("- slot scale") or line.startswith("- live mix") or "Replication" in line:
            assert line.isascii(), line
    # the JSON carries nothing the markdown does not print
    assert str(rep["live_mix"]["n"]) in md and f"{port['total_r']:+.3f}" in md


# ------------------------------------------------- #15 live-mix R

def test_live_mix_r_is_the_per_market_average_reweighted_by_hand():
    mix = {"weights": {"asx": 0.4, "nasdaq": 0.6}}
    trades = [{"market": "asx", "realized_r": 0.5}, {"market": "asx", "realized_r": 1.5},
              {"market": "nasdaq", "realized_r": -0.5}]
    assert rs.live_mix_r(trades, mix) == pytest.approx(0.4 * 1.0 + 0.6 * -0.5)   # 0.1
    # a market the mix weights but the book never traded drops out, renormalised
    assert rs.live_mix_r(trades[:2], mix) == pytest.approx(1.0)
    assert rs.live_mix_r([{"market": "crypto", "realized_r": 2.0}], mix) is None
    assert rs.live_mix_r([], mix) is None
    assert rs.total_r(trades) == pytest.approx(1.5)


def test_the_live_mix_reads_the_live_cycles_rows_and_falls_back_to_equal_weights(tmp_path):
    jd = tmp_path / "journal"
    jd.mkdir()
    rows = ([{"market": "nasdaq", "cycle": "hc4-1"}] * 6 + [{"market": "asx", "cycle": "hc4-2"}] * 3
            + [{"market": "crypto", "cycle": "hc4-1"}] + [{"market": "asx", "cycle": "w3-1"}] * 20)
    (jd / "vivek_bot_book.json").write_text(json.dumps({"open": rows[:4], "closed": rows[4:]}),
                                            encoding="utf-8")
    mix = rs.live_market_mix(tmp_path, ("hc4-1", "hc4-2"))
    assert mix["n"] == 10 and mix["source"] == "book" and "note" not in mix
    assert mix["weights"] == {"asx": 0.3, "crypto": 0.1, "nasdaq": 0.6}
    gone = rs.live_market_mix(tmp_path / "nowhere")
    assert gone["source"] == "equal" and "unreadable" in gone["note"]
    assert set(gone["weights"]) == set(config.MARKETS)
    assert sum(gone["weights"].values()) == pytest.approx(1.0, abs=0.01)
    assert config.VIVEK_PARITY_LIVE_CYCLES == ("hc4-1", "hc4-2")


# ------------------------------------------------- #20 sectors

def test_blank_sectors_fill_from_sector_map_then_cache_then_book_and_named_stays():
    uni = [{"symbol": "AAA", "sector": ""}, {"symbol": "BBB", "sector": ""},
           {"symbol": "CCC", "sector": ""}, {"symbol": "DDD", "sector": ""},
           {"symbol": "EEE", "sector": "Energy"}]
    cov = rs.fill_sectors(
        "nasdaq", uni,
        sector_map={"nasdaq:AAA": {"sector": "Technology"}, "nasdaq:BBB": {"sector": ""},
                    "asx:CCC": {"sector": "Banks"}},
        cache_items=[{"symbol": "AAA", "sector": "Healthcare"}, {"symbol": "BBB", "sector": "Industrials"}],
        book_rows=[{"market": "nasdaq", "symbol": "CCC", "sector": "Consumer Defensive"},
                   {"market": "asx", "symbol": "DDD", "sector": "Banks"}])
    by = {u["symbol"]: u["sector"] for u in uni}
    assert by == {"AAA": "Technology", "BBB": "Industrials", "CCC": "Consumer Defensive",
                  "DDD": "", "EEE": "Energy"}
    assert cov == {"named": 4, "total": 5,
                   "filled": {"universe": 1, "sector_map": 1, "universe_cache": 1, "book": 1}}


def test_the_fill_reads_the_committed_files_read_only(tmp_path):
    (tmp_path / "data" / "universe_cache").mkdir(parents=True)
    (tmp_path / "journal").mkdir()
    (tmp_path / "data" / "sector_map.json").write_text(
        json.dumps({"nasdaq:AAA": {"sector": "Technology", "ts": "x"}}), encoding="utf-8")
    (tmp_path / "data" / "universe_cache" / "nasdaq.json").write_text(
        json.dumps({"items": [{"symbol": "BBB", "sector": "Industrials"}]}), encoding="utf-8")
    (tmp_path / "journal" / "vivek_bot_book.json").write_text(
        json.dumps({"open": [{"market": "nasdaq", "symbol": "CCC", "sector": "Healthcare"}],
                    "closed": []}), encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    uni = [{"symbol": s, "sector": ""} for s in ("AAA", "BBB", "CCC", "ZZZ")]
    cov = rs.fill_sectors("nasdaq", uni, root=tmp_path)
    assert [u["sector"] for u in uni] == ["Technology", "Industrials", "Healthcare", ""]
    assert cov["named"] == 3 and cov["total"] == 4
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.json")} == before
    # nothing committed is required: an empty root fills nothing and raises nothing
    assert rs.fill_sectors("nasdaq", [{"symbol": "Q", "sector": ""}], root=tmp_path / "none")["named"] == 0


def test_a_filled_nasdaq_sector_binds_the_per_market_cap_and_blank_stays_exempt(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 60)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 6)
    named = [_series(f"N{i}", sector="Technology", signals=[(0, W1R, "A+", "weekly")]) for i in range(7)]
    blank = [_series(f"B{i}", sector="", signals=[(0, W1R, "A+", "weekly")]) for i in range(8)]
    out = vp.run_book(named + blank, vp.baseline_rules())
    assert out["skipped"].get("sector_cap") == 1 and len(out["taken"]) == 14
    # the Yahoo label lands on its GICS bucket through the bot's own key
    assert vp._sector_key("N0", "Technology", "nasdaq") == "information technology"
    assert vp._sector_key("B0", "", "nasdaq") == ""


# ------------------------------------------------- #18 replication

def test_the_second_draw_shares_no_name_with_the_first_and_keeps_the_size():
    uni = [{"symbol": f"S{i:03d}"} for i in range(1000)]
    first = _sample(uni, 300)
    first_syms = {u["symbol"] for u in first}
    second = _sample([u for u in uni if u["symbol"] not in first_syms], 300)
    second_syms = {u["symbol"] for u in second}
    assert len(first) == len(second) == 300 and not (first_syms & second_syms)
    # the second draw sits between the first's picks, spread over the whole list
    assert second[0]["symbol"] != "S000" and second[-1]["symbol"] > "S900"
    # fewer names left than the draw: the complement is every name left, smaller
    small = [{"symbol": f"T{i}"} for i in range(10)]
    f = {u["symbol"] for u in _sample(small, 7)}
    s = _sample([u for u in small if u["symbol"] not in f], 7)
    assert len(s) == 3 and not ({u["symbol"] for u in s} & f)


def test_verdict_wording_and_best_variant_need_the_replication():
    assert rr.verdict_label({"pass": False}) == "fail"
    assert rr.verdict_label({"pass": True}) == "PASS"
    assert rr.verdict_label({"pass": True, "replicated": True}) == "PASS (replicated)"
    assert rr.verdict_label({"pass": True, "replicated": False}) == "PASS (not replicated)"
    chk = {"overall": {"delta": 0.2}}
    res = {"V7_no_asx": {"verdict": {"pass": True, "replicated": False, "checks": chk}},
           "V1_hold_off": {"verdict": {"pass": True, "replicated": True, "checks": {"overall": {"delta": 0.1}}}}}
    assert vp.best_variant(res)["name"] == "V1_hold_off"
    res["V1_hold_off"]["verdict"]["replicated"] = False
    bv = vp.best_variant(res)
    assert bv["name"] is None and "replicated" in bv["reason"]
    assert vp.best_variant({"V1": {"verdict": {"pass": True, "checks": chk}}})["name"] == "V1"


def test_a_pass_is_re_run_on_the_disjoint_sample_only_and_labelled(monkeypatch):
    """The first draw took A0..A2; the loader, asked to exclude them, hands
    back A3..A5. Only the baseline and the passing variant run on it, at the
    first run's caps; the label follows the second sample's verdict."""
    monkeypatch.setattr(config, "VIVEK_PARITY_REPLICATE", True)
    loads: list[tuple] = []

    def fake_load(mk, limit, period, exclude_symbols=None, workers=1):
        loads.append((mk, limit, frozenset(exclude_symbols or ())))
        ss = [_series(f"A{i}", market=mk, signals=[(0, W1R, "A+", "weekly")]) for i in range(3, 6)]
        return ss, {"symbols": 3, "universe": 9, "replayed": 3, "signals": 3,
                    "sampled_symbols": [s.symbol for s in ss]}

    monkeypatch.setattr(vp, "load_market_series", fake_load)
    books: list[tuple] = []
    real_run_book = vp.run_book

    def spy_run_book(series, rules=None, **kw):
        books.append((rules.name if rules else None, kw.get("max_total"), kw.get("max_sector")))
        return real_run_book(series, rules, **kw)

    monkeypatch.setattr(vp, "run_book", spy_run_book)
    second_pass = {"value": True}
    monkeypatch.setattr(vp, "variant_passes", lambda b, v, skip_markets=(): {
        "pass": second_pass["value"],
        "checks": {"overall": {"baseline": 0.1, "variant": 0.3, "delta": 0.2, "pass": True},
                   "market:asx": {"pass": None}, "market:nasdaq": {"pass": True},
                   "half:first": {"pass": True}, "half:second": {"pass": second_pass["value"]}}})
    coverage = {"nasdaq": {"symbols": 3, "universe": 9, "sampled_symbols": ["A0", "A1", "A2"]},
                "crypto": {"symbols": 4, "universe": 4, "sampled_symbols": ["B", "T", "E", "S"]}}

    def results():
        return {"V7_no_asx": {"portfolio": {"taken": 5},
                              "verdict": {"pass": True, "checks": {"overall": {"baseline": 0.1, "variant": 0.2, "delta": 0.1}}}},
                "V1_hold_off": {"portfolio": {"taken": 4},
                                "verdict": {"pass": False, "checks": {"overall": {"delta": -0.1}}}}}

    vr = results()
    block = rr.replicate_passes(["nasdaq", "crypto"], 3, "5y", {"nasdaq": {"ZZ"}}, 1, vr, coverage,
                                {"max_open_total": 7, "max_per_sector": 2})
    assert block["ran"] and block["passing"] == ["V7_no_asx"]
    assert loads == [("nasdaq", 3, frozenset({"ZZ", "A0", "A1", "A2"}))]      # crypto: whole market
    assert block["sample"]["nasdaq"] == {"symbols": 3, "universe": 9, "overlap_dropped": 0,
                                         "replayed": 3, "signals": 3}
    assert "no disjoint names" in block["sample"]["crypto"]["note"]
    assert [b[0] for b in books] == ["baseline", "V7_no_asx"] and all(b[1:] == (7, 2) for b in books)
    assert vr["V7_no_asx"]["verdict"]["replicated"] is True
    assert vr["V7_no_asx"]["verdict"]["label"] == "PASS (replicated)"
    assert vr["V1_hold_off"]["verdict"]["label"] == "fail"
    assert block["variants"]["V7_no_asx"]["second"]["pass"] is True
    chk = block["variants"]["V7_no_asx"]["second"]["checks"]
    assert set(chk["overall"]) == {"baseline", "variant", "delta", "pass"}
    assert chk["market:asx"] == {"pass": None} and chk["half:second"] == {"pass": True}
    assert "thin" not in block                  # nasdaq: 3 replayed against the first draw's 3
    md = "\n".join(vp.replication_lines(block))
    assert md.isascii() and "| V7_no_asx | PASS (replicated) | +0.100 -> +0.200 (5 taken) | +0.100 -> +0.300" in md
    assert "overlap dropped 0" in md and "caps 7 total / 2 per sector per market" in md
    # the second sample refuses: not replicated, and the best variant says so
    second_pass["value"] = False
    vr = results()
    block = rr.replicate_passes(["nasdaq"], 3, "5y", {}, 1, vr, coverage, {"max_open_total": 7, "max_per_sector": 2})
    assert vr["V7_no_asx"]["verdict"]["label"] == "PASS (not replicated)"
    assert block["variants"]["V7_no_asx"]["label"] == "PASS (not replicated)"
    assert vp.best_variant(vr)["name"] is None
    assert "| V7_no_asx | PASS (not replicated) |" in "\n".join(vp.replication_lines(block))
    # nothing passed: nothing is loaded
    loads.clear()
    vr = {"V1_hold_off": {"verdict": {"pass": False}}}
    block = rr.replicate_passes(["nasdaq"], 3, "5y", {}, 1, vr, coverage, {})
    assert not block["ran"] and loads == [] and vr["V1_hold_off"]["verdict"]["label"] == "fail"


def test_a_loader_that_ignores_the_exclusion_is_cut_to_the_disjoint_names(monkeypatch):
    def fake_load(mk, limit, period, exclude_symbols=None, workers=1):
        ss = [_series(f"A{i}", market=mk, signals=[(0, W1R, "A+", "weekly")]) for i in range(4)]
        return ss, {"symbols": 4, "universe": 9, "sampled_symbols": [s.symbol for s in ss]}

    monkeypatch.setattr(vp, "load_market_series", fake_load)
    monkeypatch.setattr(vp, "variant_passes", lambda b, v, skip_markets=(): {"pass": False, "checks": {}})
    cov = {"nasdaq": {"symbols": 3, "universe": 9, "sampled_symbols": ["A0", "A1", "A2"]}}
    vr = {"V1_hold_off": {"portfolio": {"taken": 1}, "verdict": {"pass": True, "checks": {}}}}
    block = rr.replicate_passes(["nasdaq"], 3, "5y", {}, 1, vr, cov, {"max_open_total": 3, "max_per_sector": 1})
    assert block["sample"]["nasdaq"]["overlap_dropped"] == 3
    assert block["sample"]["nasdaq"]["symbols"] == 1 and block["sample"]["nasdaq"]["replayed"] == 1
    # 1 name against the first draw's 3 (under VIVEK_PARITY_REPLICATE_MIN_SHARE): the block
    # says so; the verdict wording does not change
    assert config.VIVEK_PARITY_REPLICATE_MIN_SHARE == 0.5
    assert (block["thin"]["replayed"], block["thin"]["first"]) == (1, 3)
    assert "under 50%" in block["thin"]["note"]
    assert vr["V1_hold_off"]["verdict"]["label"] == "PASS (not replicated)"
    lines = vp.replication_lines(block)
    thin_line = next(ln for ln in lines if ln.startswith("- thin second sample"))
    assert thin_line.isascii()                      # _fmt_r prints an em dash for a missing figure
    assert "the second sample replayed 1 names against the first draw's 3 (under 50%)" in thin_line


def test_a_whole_universe_run_has_no_disjoint_names_and_keeps_the_pass(monkeypatch):
    """--limit 0 samples every market whole: nothing to re-draw, so the
    replication is NOT RUN, the label stays PASS (neither confirmed nor
    refused), best_variant keeps the name and the loader is never called."""
    monkeypatch.setattr(config, "VIVEK_PARITY_REPLICATE", True)
    loads: list = []
    monkeypatch.setattr(vp, "load_market_series", lambda *a, **k: loads.append(a) or ([], {}))
    cov = {"asx": {"symbols": 10, "universe": 10, "replayed": 10,
                   "sampled_symbols": [f"A{i}" for i in range(10)]},
           "nasdaq": {"symbols": 4, "universe": 4, "replayed": 4, "sampled_symbols": list("WXYZ")}}

    def results():
        return {"V7_no_asx": {"portfolio": {"taken": 5},
                              "verdict": {"pass": True, "checks": {"overall": {"baseline": 0.1, "variant": 0.2, "delta": 0.1}}}}}

    vr = results()
    block = rr.replicate_passes(["asx", "nasdaq"], None, "5y", {}, 1, vr, cov,
                                {"max_open_total": 60, "max_per_sector": 6})
    assert block["ran"] is False and "whole-universe" in block["reason"] and loads == []
    assert block["passing"] == ["V7_no_asx"]
    assert all("no disjoint names" in s["note"] for s in block["sample"].values())
    assert "replicated" not in vr["V7_no_asx"]["verdict"]
    assert vr["V7_no_asx"]["verdict"]["label"] == "PASS"
    assert vp.best_variant(vr)["name"] == "V7_no_asx"
    md = "\n".join(vp.replication_lines(block))
    assert md.isascii() and "- not run: no disjoint names to replay (whole-universe run)" in md
    assert "- asx: 0 names of 10, overlap dropped 0; the first draw sampled the whole market" in md
    # a second draw that replays nothing is the same case
    monkeypatch.setattr(vp, "load_market_series",
                        lambda *a, **k: ([], {"symbols": 0, "universe": 9, "sampled_symbols": []}))
    vr = results()
    block = rr.replicate_passes(["nasdaq"], 3, "5y", {}, 1, vr,
                                {"nasdaq": {"symbols": 3, "universe": 9, "sampled_symbols": ["A0", "A1", "A2"]}},
                                {"max_open_total": 3, "max_per_sector": 1})
    assert block["ran"] is False and vr["V7_no_asx"]["verdict"]["label"] == "PASS"
    assert vp.best_variant(vr)["name"] == "V7_no_asx"

"""scripts/r_parity.py -- like-for-like R across the four lenses.

Driven over COMMITTED ASX daily bars (no network). What it pins:
  * every lens is scored on the same rules -- one cost table, the 1% minimum
    stop, the house fill as the headline and the worst print beside it, one
    trade set under both;
  * the 5.0 house column is a RE-SCORE of the evidence engine's own trades,
    and the worst-print re-score reproduces the engine's realized_r exactly;
  * the engine is run unchanged and its `_snapshot` is always restored;
  * the report's headline is long only, shorts live in an appendix and never
    reach a headline win%, every market carries a coverage line, and the
    survivorship sentence is there.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from phasemap.backtest import rmodel as pm_rmodel
from scanner import config, conviction
from scanner import spec_backtest as sbt
from scanner import vivek_backtest as vbt
from scanner import vivek_journal
from scanner.momentum import backtest as mbt

ROOT = pathlib.Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "history" / "asx"
_spec = importlib.util.spec_from_file_location("r_parity", ROOT / "scripts" / "r_parity.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

NAMES = ("CBA", "ELS", "AEV")          # AEV is a sub-$0.50 name, so Specs fires


@pytest.fixture(scope="module")
def doc():
    rows = [{"symbol": s, "yf": f"{s}.AX", "name": f"{s} Limited", "sector": ""} for s in NAMES]
    frames = rp._load_frames(HIST, rows)
    if len(frames) < len(NAMES):
        pytest.skip("committed history missing a test name")
    return rp.replay_frames("asx", frames, {u["yf"]: u for u in rows})


def test_every_lens_trades_on_the_same_bars(doc):
    lenses = {t["lens"] for t in doc["trades"]}
    assert lenses == set(rp.LENSES), lenses
    assert doc["errors"] == {} and doc["replayed"] == len(NAMES)


def test_the_5_0_worst_print_re_score_is_the_evidence_engine(doc):
    assert doc["vivek_check"].get("compared", 0) > 0
    assert doc["vivek_check"].get("mismatch", 0) == 0


def test_one_trade_set_and_the_worst_print_is_never_better(doc):
    for t in doc["trades"]:
        assert t["w"] <= t["r"] + 1e-9, t


def test_the_one_percent_minimum_stop_binds_every_lens(doc):
    for t in doc["trades"]:
        assert t["k"] / t["e"] * 100.0 >= config.VIVEK_BOT_MIN_STOP_PCT - 1e-9, t


def test_the_5_0_headline_replay_is_long_only_and_carries_the_splits(doc):
    v = [t for t in doc["trades"] if t["lens"] == "vivek"]
    assert {t["tf"] for t in v} <= {"1D", "3D", "1W"}
    assert all(t["cohort"] in ("A+", "A") for t in v)
    for t in v:
        want = conviction.trade_cell({"grade": t["cohort"], "timeframe": t["tf"], "entry_type": t["et"]})
        assert t["cell"] == want


def test_the_cost_table_is_one_table():
    for m in ("asx", "nasdaq", "crypto"):
        want = vivek_journal.costs_for(m)
        assert pm_rmodel.costs_for(m) == want
        assert sbt.costs_for(m) == want
        assert mbt._costs(m) == pytest.approx(want)


def test_the_evidence_engine_is_restored_even_when_it_throws(monkeypatch):
    orig = vbt._snapshot

    def boom(*a, **k):
        assert vbt._snapshot is not orig, "the wrapper is in place during the replay"
        raise RuntimeError("x")
    monkeypatch.setattr(vbt, "replay_symbol", boom)
    with pytest.raises(RuntimeError):
        rp.replay_vivek(None, "asx", {"symbol": "X"}, long_only=True,
                        gated=rp.collections.Counter(), check=rp.collections.Counter())
    assert vbt._snapshot is orig


def test_an_open_in_float_noise_of_tp1_is_still_re_scored(monkeypatch):
    """Found on the runners: Yahoo's open 9.9999999999 sits below TP1 10.0, so
    the engine takes the trade, while the 8-dp entry reads 10.0 and a second
    chase guard would refuse it. The engine decides takeability; the re-score
    must reproduce every trade it took."""
    import pandas as pd
    from scanner.vivek_journal import costs_for as cf
    idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    df = pd.DataFrame({"Open": [9.8, 10.0 - 1e-10, 10.1, 10.3], "High": [9.9, 10.2, 10.6, 10.4],
                       "Low": [9.7, 9.95, 10.0, 9.9], "Close": [9.85, 10.1, 10.5, 10.0],
                       "Volume": [1e6] * 4}, index=idx)
    plan = {"stop": 9.0, "tp1": 10.0, "tp2": 11.0, "tp3": 12.0,
            "scale": list(config.VIVEK_TP_SCALE_LONG)}
    row = {"symbol": "X", "dir": "LONG", "grade": "A", "level_tf": "weekly"}

    def fake_replay(frame, market, *a, **k):
        tr = vbt._snapshot(row, "1W", plan, market, float(frame["Open"].iat[1]), "2026-01-06")
        assert tr is not None, "the engine takes it"
        for j in range(1, len(frame)):
            vbt._manage_bar(tr, float(frame["High"].iat[j]), float(frame["Low"].iat[j]),
                            float(frame["Close"].iat[j]), idx[j].date().isoformat(), cf(market),
                            is_last=(j == len(frame) - 1))
            if tr["status"] == "closed":
                break
        return [tr]
    monkeypatch.setattr(vbt, "replay_symbol", fake_replay)
    check = rp.collections.Counter()
    out = rp.replay_vivek(df, "asx", {"symbol": "X"}, long_only=True,
                          gated=rp.collections.Counter(), check=check)
    assert check == {"compared": 1} and len(out) == 1
    assert out[0]["w"] <= out[0]["r"] + 1e-9


def _t(lens, d, r, w=None, m="asx", **kw):
    return dict({"lens": lens, "m": m, "s": "X", "dir": d, "cohort": "A", "d": "2024-01-02",
                 "e": 10.0, "k": 1.0, "r": r, "w": r if w is None else w, "c": r, "cb": "stop"}, **kw)


def _shard(market, trades, shard=0, of=1, universe=100, downloaded=57):
    return {"version": rp.VERSION, "market": market, "shard": shard, "of": of, "period": "5y",
            "universe": universe, "shard_symbols": universe, "downloaded": downloaded,
            "replayed": downloaded, "product_excluded": 0, "errors": {}, "gated": {},
            "vivek_check": {"compared": 1}, "trades": trades}


def test_the_headline_is_long_only_and_shorts_never_reach_it():
    longs = [_t("momentum", "long", 2.0, cohort="Rule A"), _t("momentum", "long", -1.0, cohort="Rule B")]
    base, _ = rp.build_report([_shard("asx", longs)])
    more, res = rp.build_report([_shard("asx", longs + [_t("momentum", "short", 5.0, cohort="Rule A")])])
    head = lambda md: md.split("## Headline")[1].split("\n## ")[0]  # noqa: E731
    assert head(base) == head(more), "a short changed the headline"
    assert res["headline"]["momentum"]["house"]["win_pct"] == 50.0
    assert res["shorts"]["momentum"]["house"]["net_r"] == 5.0
    assert "## Appendix -- shorts" in more


def test_the_table_is_lens_by_fill_with_dollars_at_one_thousand():
    md, res = rp.build_report([_shard("asx", [_t("specs", "long", 2.0, -1.0)])])
    assert "| lens | fill rule | net R | R/trade | win% | n | $ at $1k |" in md
    assert res["headline"]["specs"]["house"]["usd"] == 200.0          # 2R x 1000 x 1/10
    assert res["headline"]["specs"]["worst print"]["usd"] == -100.0
    assert "Median stop distance, longs: " in md and "Specs 10.0%" in md
    assert "| house |" in md and "| worst print |" in md


def test_every_market_has_a_coverage_line_and_a_missing_shard_is_named():
    md, _ = rp.build_report([_shard("asx", [], universe=2046, downloaded=1170),
                             _shard("nasdaq", [], shard=0, of=2, universe=1428, downloaded=700),
                             _shard("crypto", [], universe=86, downloaded=60)])
    assert "**ASX**: 1,170 downloaded / 2,046 in the universe (57.2%)" in md
    assert "**NASDAQ**: 700 downloaded / 1,428" in md and "MISSING shards [1]" in md
    assert "**CRYPTO**: 60 downloaded / 86" in md
    assert md.count(rp.SURVIVORSHIP) == 1 and "TODAY's universe" in rp.SURVIVORSHIP


def test_the_splits_the_owner_asked_to_keep_visible():
    ts = [_t("vivek", "long", 1.0, tf=tf, et="reclaim", cell=None, lvl="weekly")
          for tf in ("1D", "3D", "1W")]
    ts += [_t("momentum", "long", 1.0, m=m, cohort=r) for m in ("asx", "nasdaq", "crypto")
           for r in ("Rule A", "Rule B")]
    md, _ = rp.build_report([_shard("asx", ts), _shard("nasdaq", []), _shard("crypto", [])])
    for tf in ("1D", "3D", "1W"):
        assert f"| 5.0 {tf} | house |" in md
    assert "| 5.0 high-conviction cells (any of the four) | house |" in md
    assert "| 5.0 all A+/A | worst print |" in md
    assert "| 5.0 bot rule, stop <= 25% (as the bot takes it) | house |" in md
    assert "| 5.0 bot rule as taken, ASX | worst print |" in md
    for cell in conviction.cell_names():
        assert f"| 5.0 cell: {cell} | house |" in md
    for r in ("Rule A", "Rule B"):
        for m in ("ASX", "NASDAQ", "CRYPTO"):
            assert f"| Momentum {r} {m} | house |" in md
    assert "live min_signal_score" in md


def test_a_verdict_is_appended_under_its_own_heading():
    md, _ = rp.build_report([_shard("asx", [])], "Keep the 1W reclaim.")
    assert md.rstrip().endswith("Keep the 1W reclaim.")
    assert "## What the paper bot should keep taking" in md


def test_the_script_writes_only_the_paths_it_is_handed():
    """Analysis only: no bot_rules.json, no Discord, no confluence, no book.
    Every write is an atomic_write to a path from the command line, and the
    script imports nothing that publishes or trades."""
    import ast
    src = (ROOT / "scripts" / "r_parity.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert not {m for m in mods if any(b in m for b in ("confluence", "discord", "morning_plays",
                                                         "vivek_run", "output", "requests"))}, mods
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and getattr(n.func, "id", getattr(n.func, "attr", "")) in
              ("atomic_write", "write_text", "write_json", "open")]
    assert len(writes) == 3 and all(ast.unparse(w.args[0]).startswith("pathlib.Path(a.")
                                    for w in writes), [ast.unparse(w) for w in writes]


def test_a_name_the_first_download_pass_missed_gets_one_more_try(monkeypatch, tmp_path):
    """29 shards hit Yahoo at once and a throttled batch comes back empty; one
    more pass after a pause recovers what it can, and the shard's coverage
    counts what actually arrived."""
    import json
    import scanner.data
    import scanner.universe
    row = {"symbol": "CBA", "yf": "CBA.AX", "name": "Commonwealth Bank", "sector": ""}
    frame = rp._load_frames(HIST, [row])
    if not frame:
        pytest.skip("no committed CBA history")
    calls = []

    def fake_download(tickers, period=None, **k):
        calls.append(list(tickers))
        return {} if len(calls) == 1 else dict(frame)
    monkeypatch.setattr(scanner.universe, "load_universe", lambda m, full=True: [row])
    monkeypatch.setattr(scanner.data, "download", fake_download)
    out = tmp_path / "asx-00.json"
    assert rp.main(["shard", "--market", "asx", "--out", str(out), "--retry-wait", "0"]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert calls == [["CBA.AX"], ["CBA.AX"]]
    assert doc["downloaded"] == 1 and doc["universe"] == 1 and doc["version"] == rp.VERSION
    assert doc["vivek_check"].get("mismatch", 0) == 0

"""Live vs replay, trade by trade (scanner/live_vs_replay.py; the owner's
"20 more" #3, 2 Nov). Each live trade of a cycle is lined up with the
replay's trade on the same symbol nearest its entry; the gap splits into
trades the replay never took, the entry fill, and the outcome. No network
here: the replay side is stubbed, and the workflow step is checked as text."""
from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from scanner import live_vs_replay as lvr

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _live(sym, entry_date, r, *, status="closed", reason="stop", market="nasdaq", entry=10.0,
          risk=1.0, cycle="hc4-1"):
    row = {"symbol": sym, "market": market, "cycle": cycle, "status": status,
           "entry_date": entry_date, "entry": entry, "risk": risk, "direction": "long",
           "timeframe": "3D", "entry_type": "reclaim"}
    if status == "closed":
        row.update(realized_r=r, exit_reason=reason, exit_date="2026-10-20")
    else:
        row.update(unreal_r=r)
    return row


def _rep(sym, entry_date, r, *, market="nasdaq", entry=10.2, house=None, reason="stop"):
    return {"symbol": sym, "market": market, "entry_date": entry_date, "entry": entry,
            "realized_r": r, "realized_r_house": r if house is None else house,
            "exit_reason": reason, "exit_date": "2026-10-25"}


def test_each_live_trade_pairs_with_the_nearest_replay_trade_within_the_tolerance():
    live = [_live("AAA", "2026-09-22", -1.1), _live("BBB", "2026-09-22", +0.5, reason="time"),
            _live("CCC", "2026-09-22", -0.4, reason="time")]
    rep = [_rep("AAA", "2026-09-28", 0.3),             # 6 days out: too far
           _rep("AAA", "2026-09-23", -1.2, house=-1.0),
           _rep("BBB", "2026-09-21", 0.8, reason="time"),
           _rep("CCC", "2026-09-22", 0.1, market="asx")]  # another market's CCC
    pairs = lvr.match(live, rep)
    a, b, c = pairs
    assert a["matched"] and a["replay_entry_date"] == "2026-09-23" and a["days_off"] == -1
    assert a["entry_gap_r"] == pytest.approx(-0.2)          # live paid 10.0, replay 10.2
    assert b["matched"] and b["replay_r"] == 0.8
    assert not c["matched"]


def test_a_replay_trade_is_claimed_by_one_live_row_only():
    live = [_live("AAA", "2026-09-22", -1.0), _live("AAA", "2026-09-24", -1.0)]
    pairs = lvr.match(live, [_rep("AAA", "2026-09-24", 0.5)])
    assert [p["matched"] for p in pairs] == [False, True]   # the nearer one claims it


def test_the_summary_splits_matched_unmatched_and_hand_closes():
    live = [_live("AAA", "2026-09-22", -1.1),                       # matched, rules
            _live("BBB", "2026-09-22", -1.0),                       # unmatched, rules
            _live("CCC", "2026-09-22", +2.0, reason="manual"),      # a hand close
            _live("DDD", "2026-09-29", +0.3, status="open")]        # open, matched
    rep = [_rep("AAA", "2026-09-22", +0.4, house=+0.5), _rep("CCC", "2026-09-22", 0.1),
           _rep("DDD", "2026-09-29", 0.2)]
    s = lvr.summarize(lvr.match(live, rep), "hc4-1")
    assert (s["live_rows"], s["rules_closed"], s["matched"], s["unmatched"]) == (4, 2, 3, 1)
    mc = s["matched_closed"]
    assert (mc["n"], mc["live_r"], mc["replay_r"], mc["replay_r_house"]) == (1, -1.1, 0.4, 0.5)
    assert mc["unmatched_closed_live_r"] == -1.0
    assert s["exit_crosstab"] == {"stop -> stop": 1}
    assert s["by_market"]["nasdaq"]["rules_closed"] == 2
    md = lvr.markdown(s, lvr.match(live, rep))
    assert md.isascii() and "| BBB | nasdaq |" in md and "never" in md


def test_live_rows_reads_only_the_cycle_from_the_canonical_books(tmp_path):
    j = tmp_path / "journal"
    j.mkdir()
    (j / "vivek_bot_book.asx.json").write_text(json.dumps({
        "closed": [_live("A", "2026-09-22", -1.0, market="asx"),
                   _live("W", "2026-08-02", -1.0, market="asx", cycle="w3-1")],
        "open": [dict(_live("B", "2026-10-01", 0.2, status="open", market="asx"), status=None)]}))
    rows = lvr.live_rows(tmp_path, "hc4-1")
    assert sorted(r["symbol"] for r in rows) == ["A", "B"]
    assert {r["symbol"]: r["status"] for r in rows}["B"] == "open"


def test_main_prints_and_writes_only_where_it_is_told(monkeypatch, tmp_path, capsys):
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "vivek_bot_book.nasdaq.json").write_text(json.dumps(
        {"closed": [_live("AAA", "2026-09-22", -1.1)], "open": []}))
    monkeypatch.setattr(lvr, "ROOT", tmp_path)
    seen = {}

    def fake(rows, period, start):
        seen.update(period=period, start=start)
        return [_rep("AAA", "2026-09-22", 0.4)], {"nasdaq": {"symbols": 1}}

    monkeypatch.setattr(lvr, "replay_trades", fake)
    out, md = tmp_path / "o.json", tmp_path / "s.md"
    assert lvr.main(["--cycle", "hc4-1", "--out", str(out), "--summary-md", str(md)]) == 0
    assert seen == {"period": "5y", "start": "2026-09-12"}
    assert json.loads(out.read_text())["summary"]["matched"] == 1
    assert "## Live vs replay, trade by trade (hc4-1)" in md.read_text()
    assert "| AAA | nasdaq |" in capsys.readouterr().out


def test_the_decision_replay_runs_it_read_only_after_the_replay():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "decision_replay.yml").read_text())
    steps = wf["jobs"]["replay"]["steps"]
    names = [s.get("name", "") for s in steps]
    i = next(k for k, n in enumerate(names) if n.startswith("Live vs replay"))
    assert names.index("Upload the report") > i > next(k for k, n in enumerate(names)
                                                      if n.startswith("Replay the live rules"))
    run = steps[i]["run"]
    assert "set -o pipefail" in run and "python -m scanner.live_vs_replay --cycle hc4-1" in run
    assert '$RUNNER_TEMP/decision-replay' in run and "public/data" not in run
    assert steps[i].get("if") == "success() || failure()"


def test_the_replay_side_runs_the_parity_engine_end_to_end(monkeypatch):
    """No network: the universe and the fetch are stubbed with a synthetic
    frame; the plumbing (universe -> fetch -> phase 1 -> unconstrained book
    -> window) must run and report coverage, whatever it finds."""
    from scanner import universe, vivek_backtest
    from tests.test_vivek_parity import _ohlc

    df = _ohlc(n=420, seed=5, start="2025-01-01")
    monkeypatch.setattr(universe, "load_universe", lambda mk, full=True: (
        [{"symbol": "AAA", "name": "Aaa Corp", "sector": "", "yf": "AAA"}] if mk == "nasdaq" else []))
    monkeypatch.setattr(vivek_backtest, "fetch_market_frames",
                        lambda mk, uni, period: ({u["yf"]: df for u in uni}, {"mode": "stub"}))
    rows = [_live("AAA", "2026-01-05", -1.0), _live("ZZZ", "2026-01-05", -1.0)]   # ZZZ: not listed
    trades, cov = lvr.replay_trades(rows, "5y", "2025-06-01")
    assert cov["nasdaq"]["symbols"] == 2 and cov["nasdaq"]["priced"] == 2
    assert all(t["market"] == "nasdaq" and t["entry_date"] >= "2025-06-01" for t in trades)

"""scanner/replay_summary.py -- the committed slim summary of a decision
replay and its pinned inputs (NEXT100 #14, 2026-11-03).

What is pinned: the writer's summary.json is EXACTLY the schema-1 document
scripts/decision_pack.py documents and reads (key for key against the
fixture the pack's own tests use), the inputs digest is stable on the same
tape and moves on a re-based one, and the hook is opt-in (no --summary-dir,
nothing written). Synthetic series only; nothing reaches the network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

from scanner import config, output
from scanner import replay_summary as rs
from scanner import vivek_backtest as vb
from scanner import vivek_parity as vp

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "decision_replay_summary.json"
D0 = dt.date(2024, 1, 1)
SCALE = list(config.VIVEK_TP_SCALE_LONG)


def _dp():
    spec = importlib.util.spec_from_file_location("decision_pack_for_summary",
                                                  ROOT / "scripts" / "decision_pack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plan(trigger: str) -> dict:
    return {"stop": 95.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0, "scale": SCALE,
            "entry": 100.0, "rr": 4.0, "entry_trigger": trigger, "trigger_bar": None,
            "structural_tps": 0}


def _series(sym: str, market: str, n: int = 120, signals=(), lows=None) -> vp.SymbolSeries:
    """Flat bars at 100 unless `lows` dips a bar (tests/test_decision_replay.py's shape)."""
    o = np.full(n, 100.0)
    h, l, c = o + 1.0, o - 1.0, o.copy()
    for k, v in (lows or {}).items():
        l[k] = v
    days = np.array([(D0 - vp._EPOCH).days + k for k in range(n)], dtype=np.int64)
    s = vp.SymbolSeries(market=market, symbol=sym, name=sym, sector=f"sec-{sym}",
                        days=days, o=o, h=h, l=l, c=c, adv=np.full(n, 1e8))
    for j, plans, grade, level in signals:
        s.signals.append((j, {"grade": grade, "dir": "LONG", "level_tf": level,
                              "entry_types": list(plans.values()),
                              "plans": {tf: _plan(trig) for tf, trig in plans.items()}}))
    return s


N_NAMES = 8   # over the 6-per-sector cap: the book REFUSES some, the population keeps them


def _fake_load(mk, limit, period, exclude_symbols=None, workers=1):
    ss = [_series(f"{mk[:1].upper()}{i}", mk,
                  signals=[(i, {"3D": "reclaim", "1D": "break"}, "A+" if i % 2 else "A", "3d"),
                           (40 + i, {"1W": "reclaim"}, "A+", "weekly")],
                  lows={i + 4: 90.0} if i % 3 == 0 else None)
          for i in range(N_NAMES)]
    for s in ss:
        s.sector = "Technology"       # one GICS bucket per market, so the sector cap bites
    return ss, {"symbols": N_NAMES, "universe": 60, "sampled_pct": 10.0, "replayed": N_NAMES,
                "priced": N_NAMES, "signals": 2 * N_NAMES, "data_sources": {"by_source": {"x": 6}},
                "sampled_symbols": [s.symbol for s in ss]}


@pytest.fixture
def replayed(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "load_market_series", _fake_load)
    monkeypatch.setattr(vp, "fx_rates", lambda: {"audusd": 0.66, "source": "fallback"})
    monkeypatch.setenv("GITHUB_SHA", "abc123def4567890abc123def4567890abc123de")
    monkeypatch.setenv("GITHUB_RUN_ID", "424242")
    out_dir = tmp_path / "data" / "research" / "decision_replay"
    rep = vp.run_parity(["asx", "nasdaq", "crypto"], 6, "5y", workers=1, summary_dir=out_dir)
    return rep, tmp_path, out_dir


# -- schema round trip: writer -> the pack's reader ---------------------------

def test_the_summary_is_schema_1_key_for_key_and_the_pack_reads_it(replayed):
    rep, root, out_dir = replayed
    dp = _dp()
    doc = dp.load_replay_summary(root=str(root))           # raises if not schema 1
    assert doc["schema"] == 1 == config.VIVEK_PARITY_SUMMARY_SCHEMA
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(fixture) <= set(doc), "every top-level key the pack documents"
    assert set(doc) == {"schema", "generated_at", "run", "trades", "variants"}
    assert dt.datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    taken = [t for t in rep["trades"] if t["taken"]]
    assert 0 < len(taken) < len(rep["trades"]), "the sector cap refused some: the arms differ"
    assert len(doc["trades"]) == len(taken), "the live-rules arm's taken trades only"
    want = list(fixture["trades"][0])
    assert want == list(rs.TRADE_KEYS)
    cells = {"1W reclaim", "1W break", "3D reclaim", "1D break"}
    for row, src in zip(doc["trades"], taken):
        assert list(row) == want, "key for key, in the fixture's order"
        assert row["m"] in ("asx", "nasdaq", "crypto") and row["s"] == src["symbol"]
        assert row["cell"] in cells and row["grade"] in ("A+", "A")
        assert row["entry"] == src["entry_date"] and row["exit"] == src["exit_date"]
        assert row["r"] == round(src["realized_r"], 4) and row["reason"] == src["exit_reason"]
    # the reader's same-weeks figure over the written file
    weeks = sorted({dp.iso_week(t["entry"]) for t in doc["trades"]})
    f = dp.replay_same_weeks(doc, "all", weeks)
    closed = [t for t in doc["trades"] if t["exit"]]
    assert f["n"] == len(closed) and f["open"] == len(doc["trades"]) - len(closed)
    assert f["avg"] == round(sum(t["r"] for t in closed) / len(closed), 3)
    assert dp.replay_same_weeks(doc, "cell:3D reclaim", weeks)["n"] == sum(
        1 for t in closed if t["cell"] == "3D reclaim")
    # a run block the pack and a person can place
    run = doc["run"]
    assert run["sha"] == "abc123def4567890abc123def4567890abc123de" and run["id"] == "424242"
    assert run["period"] == "5y" and run["limit"] == 6
    assert run["markets"] == ["asx", "nasdaq", "crypto"]
    assert run["cycle_tag"] == config.VIVEK_BOT_CYCLE_TAG
    assert run["rules"] == rep["baseline"]["rules"] and run["params"] == rep["params"]
    assert run["coverage"]["asx"]["symbols"] == N_NAMES
    # the variants: each verdict and R per slot-month, beside the baseline's
    v = doc["variants"]
    assert set(v["by_name"]) == set(rep["variants"]) == {r.name for r in vp.variant_grid()}
    for name, vr in v["by_name"].items():
        assert vr["pass"] == rep["variants"][name]["verdict"]["pass"]
        assert vr["r_per_slot_month"] == rs._num(rep["variants"][name]["portfolio"]["r_per_slot_month"])
        assert "overall" in vr["checks"] and vr["kind"] in ("entry_rule", "exit_rule")
    assert v["baseline"]["r_per_slot_month"] == rs._num(rep["baseline"]["portfolio"]["r_per_slot_month"])
    assert v["best"] == rep["best_variant"].get("name")
    assert (out_dir / "summary.json").stat().st_size < 1_000_000
    assert (out_dir / "summary.json").read_text(encoding="utf-8").endswith("\n")


def test_the_inputs_pin_every_sampled_name_with_its_bars_and_digest(replayed):
    rep, root, out_dir = replayed
    doc = json.loads((out_dir / "inputs.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and doc["sha"] == "abc123def4567890abc123def4567890abc123de"
    assert doc["digest"] == {"of": "close series", "dp": config.VIVEK_PARITY_INPUT_DIGEST_DP,
                             "hex": config.VIVEK_PARITY_INPUT_DIGEST_HEX, "algo": "sha1"}
    assert set(doc["markets"]) == {"asx", "nasdaq", "crypto"}
    for mk, blk in doc["markets"].items():
        assert blk["names"] == rep["sampled_symbols"][mk]
        assert set(blk["series"]) == set(blk["names"])
        for sym, s in blk["series"].items():
            assert s == {"first": "2024-01-01", "last": "2024-04-29", "n": 120,
                         "digest": rs.close_digest(np.full(120, 100.0))}, (sym, s)
    assert (out_dir / "inputs.json").stat().st_size < 1_000_000


# -- the digest ----------------------------------------------------------------

def test_the_digest_is_stable_under_float_noise_and_moves_on_a_rebase():
    closes = np.linspace(10.0, 20.0, 50)
    d = rs.close_digest(closes)
    assert len(d) == config.VIVEK_PARITY_INPUT_DIGEST_HEX and int(d, 16) >= 0
    assert rs.close_digest(list(closes)) == d, "a list and an array digest alike"
    assert rs.close_digest(closes + 1e-9) == d, "noise under the rounding does not move it"
    assert rs.close_digest(closes * 0.98) != d, "a re-based (adjusted) tape does"
    assert rs.close_digest(closes[:-1]) != d, "a shorter tape does"
    nan = closes.copy()
    nan[3] = float("nan")
    assert rs.close_digest(nan) != d and rs.close_digest(nan) == rs.close_digest(nan)


def test_series_inputs_accepts_a_flat_list_and_lists_unpriced_sample_names():
    a = _series("AAA", "asx", n=5)
    b = _series("BBB", "nasdaq", n=3)
    out = rs.series_inputs([b, a], {"asx": ["AAA", "ZZZ"], "nasdaq": ["BBB"]})
    assert out["asx"]["names"] == ["AAA", "ZZZ"] and set(out["asx"]["series"]) == {"AAA"}
    assert out["asx"]["series"]["AAA"]["n"] == 5 and out["asx"]["series"]["AAA"]["last"] == "2024-01-05"
    assert out["nasdaq"]["series"]["BBB"]["first"] == "2024-01-01"


# -- the hook is opt-in --------------------------------------------------------

def test_run_parity_writes_nothing_unless_a_summary_dir_is_given(monkeypatch, tmp_path):
    monkeypatch.setattr(vp, "load_market_series", _fake_load)
    monkeypatch.setattr(vp, "fx_rates", lambda: {"audusd": 0.66, "source": "fallback"})
    calls = []
    monkeypatch.setattr(rs, "write_summary", lambda *a: calls.append(a))
    vp.run_parity(["asx"], 6, "5y", run_variants=False, workers=1)
    assert calls == []
    vp.run_parity(["asx"], 6, "5y", run_variants=False, workers=1, summary_dir=tmp_path / "s")
    assert len(calls) == 1 and calls[0][2] == tmp_path / "s"
    assert set(calls[0][1]) == {"asx"} and calls[0][0]["mode"] == "parity"


def test_the_cli_flag_defaults_to_none_and_passes_the_directory_through(monkeypatch, tmp_path):
    seen = []

    def fake_run_parity(markets, limit, period, **kw):
        seen.append(kw.get("summary_dir"))
        return {"generated_at": "x", "coverage": {}, "sampled_symbols": {}, "mode": "parity"}

    monkeypatch.setattr(vp, "run_parity", fake_run_parity)
    monkeypatch.setattr(vp, "print_parity", lambda rep: None)
    monkeypatch.setattr(output, "write_json", lambda *a, **k: None)
    base = ["vivek_backtest", "--parity", "--market", "asx", "--out", str(tmp_path / "r.json")]
    monkeypatch.setattr(sys, "argv", base)
    vb.main()
    monkeypatch.setattr(sys, "argv", base + ["--summary-dir", str(tmp_path / "sum")])
    vb.main()
    assert seen == [None, str(tmp_path / "sum")]
    assert not (tmp_path / "sum").exists(), "the stub wrote nothing: the flag only passes through"

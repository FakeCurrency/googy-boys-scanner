"""phasemap/run.py's publish path — it deletes and replaces committed files
every night and had no tests (REFINE200 folded finding).

Every test drives the real run_market/main with an in-memory FrameProvider
and a temp data root; nothing reaches Yahoo or the live public/data tree.
"""

import argparse
import datetime as dt
import json
import os

import pandas as pd
import pytest

from phasemap import run
from phasemap.config import PUBLISH_MIN_COVERAGE, RULESET_VERSION
from phasemap.data.provider import FrameProvider
from phasemap.data.session import bar_final, drop_unfinal_bar, latest_final_session
from phasemap.output.writer import validate_published
from phasemap.tests import synth

UTC = dt.timezone.utc
FRI = dt.date(2026, 10, 9)                    # a Friday
# 19:30 Sydney on Friday (AEDT) — after the ASX's 16:45 bar-final
FRI_EVENING = dt.datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
SAT = dt.datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
MON_LATE = dt.datetime(2026, 10, 12, 16, 0, tzinfo=UTC)   # Tue 03:00 Sydney


def _ending(df: pd.DataFrame, last: dt.date) -> pd.DataFrame:
    """Re-date a synthetic frame onto consecutive weekdays ending on `last`."""
    days, d = [], last
    while len(days) < len(df):
        if d.isoweekday() <= 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    out = df.copy()
    out["Date"] = pd.to_datetime(list(reversed(days)))
    return out


def _frames(last=FRI, n=3):
    fx = [synth.fixture1, synth.fixture5, synth.fixture_trap_only, synth.fixture2]
    return {f"T{i}": _ending(fx[i % len(fx)](), last) for i in range(n)}


def _args(**kw):
    base = dict(tickers=None, limit=None, period="2y", force=False)
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "STATS_DIR", str(tmp_path / "stats"))
    return tmp_path / "data"


def _load(root, market, name):
    return json.loads((root / market / name).read_text(encoding="utf-8"))


# ── load_stats: the {stats} guardrail ──────────────────────────────────────

def _stats(tmp_path, **over):
    s = {"market": "ASX", "ruleset_version": RULESET_VERSION, "window_sessions": 20,
         "sample": 500, "hit_rate_pct": 41}
    s.update(over)
    (tmp_path / "stats").mkdir(exist_ok=True)
    (tmp_path / "stats" / "asx.json").write_text(json.dumps(s), encoding="utf-8")


def test_load_stats_accepts_a_current_big_enough_artefact(tmp_path, root):
    _stats(tmp_path)
    assert run.load_stats("asx")["hit_rate_pct"] == 41


@pytest.mark.parametrize("over", [{"ruleset_version": "0.9.0"}, {"sample": 5},
                                  {"hit_rate_pct": None}])
def test_load_stats_refuses_an_unmeasured_claim(tmp_path, root, over):
    _stats(tmp_path, **over)
    assert run.load_stats("asx") is None


def test_load_stats_is_none_when_the_file_is_missing_or_broken(tmp_path, root):
    assert run.load_stats("asx") is None
    (tmp_path / "stats").mkdir()
    (tmp_path / "stats" / "asx.json").write_text("{not json", encoding="utf-8")
    assert run.load_stats("asx") is None


# ── pruners ────────────────────────────────────────────────────────────────

def test_prune_dated_keeps_the_newest_and_never_the_published_trio(tmp_path):
    for n in ("2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"):
        (tmp_path / f"{n}.json").write_text("{}")
    for n in ("latest.json", "narrations.json", "confluence.json"):
        (tmp_path / n).write_text("{}")
    assert run.prune_dated_snapshots(str(tmp_path), keep_last=2) == 2
    assert sorted(os.listdir(tmp_path)) == ["2026-10-10.json", "2026-10-11.json",
                                            "confluence.json", "latest.json",
                                            "narrations.json"]


def test_prune_stale_files_removes_only_unkept_tickers(tmp_path):
    for t in ("AAA", "BBB", "CCC"):
        (tmp_path / f"{t}.json").write_text("{}")
    assert run.prune_stale_files(str(tmp_path), {"AAA"}) == 2
    assert os.listdir(tmp_path) == ["AAA.json"]
    assert run.prune_stale_files(str(tmp_path / "missing"), set()) == 0


# ── a fresh publish ────────────────────────────────────────────────────────

def test_a_full_run_publishes_the_trio_confluence_and_charts(root):
    frames = _frames()
    st = run.run_market("asx", _args(), "2026-10-10", str(root),
                        now=FRI_EVENING, provider=FrameProvider(frames))
    assert st == run.PUBLISHED
    latest = _load(root, "asx", "latest.json")
    validate_published(latest, _load(root, "asx", "narrations.json"))
    assert {r["state"] for r in latest["results"]} >= {"RUNNING", "STALLED", "TRAP_SET"}
    assert latest["as_of"] == FRI.isoformat()
    assert latest["fetched"] == latest["universe_size"] == 3
    assert "carried_from" not in latest
    assert (root / "asx" / "2026-10-10.json").exists()
    conf = _load(root, "asx", "confluence.json")
    assert list(conf) == ["schema_version", "run_date", "generated_at", "rows"]
    assert conf["schema_version"] == 1 and conf["run_date"] == latest["run_date"]
    assert conf["rows"] == [{"ticker": r["ticker"], "direction": r["direction"],
                             "state": r["state"]} for r in latest["results"]]
    # every result's ticker has a chart file carrying its record + narration
    narr = _load(root, "asx", "narrations.json")["narrations"]
    for r in latest["results"]:
        chart = json.loads((root / "charts" / "asx" / f"{r['ticker']}.json")
                           .read_text(encoding="utf-8"))
        assert chart["candles"] and chart["ticker"] == r["ticker"]
        rows = chart.get("records") or [{"record": chart["record"],
                                         "narration": chart["narration"]}]
        mine = [x for x in rows if x["record"]["direction"] == r["direction"]]
        assert mine and mine[0]["record"] == r
        assert mine[0]["narration"] == narr[f"{r['ticker']}|{r['direction']}"]


def test_published_latest_is_compact(root):
    run.run_market("asx", _args(), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(_frames()))
    text = (root / "asx" / "latest.json").read_text(encoding="utf-8")
    assert "\n " not in text and text.endswith("}\n")      # REFINE200 #65
    dated = (root / "asx" / "2026-10-10.json").read_text(encoding="utf-8")
    assert "\n  " in dated                                  # archival copy stays readable


def test_an_unchanged_chart_file_is_not_rewritten(root):
    """REFINE200 #59: identical bytes are left alone."""
    frames = _frames()
    run.run_market("asx", _args(force=True), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(frames))
    chart = root / "charts" / "asx" / "T0.json"
    os.utime(chart, (1_000_000, 1_000_000))
    run.run_market("asx", _args(force=True), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(frames))
    assert os.stat(chart).st_mtime == 1_000_000


def test_chart_candles_keep_significant_figures(root, tmp_path):
    df = synth.fixture1()
    for c in ("Open", "High", "Low", "Close"):
        df[c] = df[c] * 3.1234567e-6
    d = tmp_path / "c"
    d.mkdir()
    run.write_chart_json(str(d), "BONK", df)
    candle = json.loads((d / "BONK.json").read_text())["candles"][-1]
    assert candle["c"] == pytest.approx(float(df["Close"].iloc[-1]), rel=1e-7)


# ── #197: an outage keeps the last good files ──────────────────────────────

def test_an_outage_refuses_to_publish_and_keeps_every_file(root):
    run.run_market("asx", _args(), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(_frames()))
    before = {p: p.read_bytes() for p in root.rglob("*.json")}
    dead = FrameProvider({t: None for t in _frames()})
    st = run.run_market("asx", _args(force=True), "2026-10-11", str(root),
                        now=SAT, provider=dead)
    assert st == run.REFUSED
    assert {p: p.read_bytes() for p in root.rglob("*.json")} == before


def test_a_run_below_the_coverage_floor_is_refused(root):
    frames = _frames(n=4)
    keep = max(1, int(len(frames) * PUBLISH_MIN_COVERAGE) - 1)
    thin = {t: (df if i < keep else None) for i, (t, df) in enumerate(frames.items())}
    assert run.run_market("asx", _args(), "2026-10-10", str(root), now=FRI_EVENING,
                          provider=FrameProvider(thin)) == run.REFUSED
    assert not (root / "asx" / "latest.json").exists()


def test_one_raising_ticker_does_not_cost_the_market(root, monkeypatch):
    frames = _frames(n=3)
    real = run.scan_ticker

    def flaky(t, df, **kw):
        if t == "T1":
            raise KeyError("t1_low")
        return real(t, df, **kw)
    monkeypatch.setattr(run, "scan_ticker", flaky)
    assert run.run_market("asx", _args(), "2026-10-10", str(root), now=FRI_EVENING,
                          provider=FrameProvider(frames)) == run.PUBLISHED
    assert "T1" not in {r["ticker"] for r in _load(root, "asx", "latest.json")["results"]}


# ── #45: no new completed bar -> carry, don't rescan ───────────────────────

def test_a_weekend_run_carries_the_friday_scan_forward(root):
    frames = _frames()
    run.run_market("asx", _args(), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(frames))
    first = _load(root, "asx", "latest.json")

    class Boom(FrameProvider):
        def fetch_all(self):
            raise AssertionError("a carry must not download")
    st = run.run_market("asx", _args(), "2026-10-11", str(root), now=SAT,
                        provider=Boom(frames))
    assert st == run.CARRIED
    carried = _load(root, "asx", "latest.json")
    assert carried["run_date"] == "2026-10-11"
    assert carried["as_of"] == first["as_of"] == FRI.isoformat()
    assert carried["carried_from"] == "2026-10-10"
    assert carried["results"] == first["results"]
    validate_published(carried, _load(root, "asx", "narrations.json"))
    assert _load(root, "asx", "confluence.json")["run_date"] == "2026-10-11"
    # Sunday carries from the SCAN, not from Saturday's carry
    run.run_market("asx", _args(), "2026-10-12", str(root),
                   now=SAT + dt.timedelta(days=1), provider=Boom(frames))
    assert _load(root, "asx", "latest.json")["carried_from"] == "2026-10-10"


def test_a_new_session_force_or_a_ruleset_change_rescans(root, monkeypatch):
    frames = _frames()
    run.run_market("asx", _args(), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(frames))
    # Monday's bar is final at Tue 03:00 Sydney -> rescan
    mon = _frames(last=dt.date(2026, 10, 12))
    assert run.run_market("asx", _args(), "2026-10-13", str(root), now=MON_LATE,
                          provider=FrameProvider(mon)) == run.PUBLISHED
    assert _load(root, "asx", "latest.json")["as_of"] == "2026-10-12"
    # --force always rescans
    assert run.run_market("asx", _args(force=True), "2026-10-13", str(root),
                          now=MON_LATE, provider=FrameProvider(mon)) == run.PUBLISHED
    # a ruleset bump must never carry an old-version file past the schema gate
    monkeypatch.setattr(run, "RULESET_VERSION", "9.9.9")
    assert run.run_market("asx", _args(), "2026-10-13", str(root), now=MON_LATE,
                          provider=FrameProvider(mon)) == run.PUBLISHED


def test_crypto_never_carries(root):
    frames = {k: _ending(v, dt.date(2026, 10, 9)) for k, v in _frames().items()}
    for when in (FRI_EVENING, SAT):
        assert run.run_market("crypto", _args(), "2026-10-10", str(root), now=when,
                              provider=FrameProvider(frames)) == run.PUBLISHED


# ── #131: a session bar is not scanned before it is final ──────────────────

def test_nasdaq_mid_session_bar_is_dropped_before_detection(root):
    tue = dt.date(2026, 10, 13)
    frames = _frames(last=tue)
    mid = dt.datetime(2026, 10, 13, 16, 25, tzinfo=UTC)          # 12:25 New York
    run.run_market("nasdaq", _args(), "2026-10-14", str(root), now=mid,
                   provider=FrameProvider(frames))
    assert _load(root, "nasdaq", "latest.json")["as_of"] == "2026-10-12"
    chart = json.loads((root / "charts" / "nasdaq" / "T0.json").read_text())
    assert chart["candles"][-1]["t"] == "2026-10-12"
    final = dt.datetime(2026, 10, 13, 20, 31, tzinfo=UTC)        # 16:31 New York
    run.run_market("nasdaq", _args(force=True), "2026-10-14", str(root), now=final,
                   provider=FrameProvider(frames))
    assert _load(root, "nasdaq", "latest.json")["as_of"] == tue.isoformat()


def test_the_bar_final_table_is_read_from_the_house_config_not_retyped():
    from scanner import config as house
    for m, (hh, mm) in house.ALERT_RETURNS_BAR_FINAL.items():
        tz, h2, m2 = bar_final(m)
        assert (str(tz), h2, m2) == (house.MARKETS[m].timezone, hh, mm)
    assert bar_final("crypto") is None


def test_latest_final_session_walks_back_over_the_weekend_and_pre_final():
    assert latest_final_session("asx", SAT) == FRI
    assert latest_final_session("nasdaq", MON_LATE) == FRI          # Mon 12:00 New York
    assert latest_final_session("asx", MON_LATE) == dt.date(2026, 10, 12)
    assert latest_final_session("crypto", SAT) is None


def test_drop_unfinal_bar_only_drops_bars_after_the_final_session():
    df = _ending(synth.fixture1(), dt.date(2026, 10, 13))
    mid = dt.datetime(2026, 10, 13, 16, 25, tzinfo=UTC)
    assert len(drop_unfinal_bar(df, "nasdaq", mid)) == len(df) - 1
    assert len(drop_unfinal_bar(df, "crypto", mid)) == len(df)
    assert drop_unfinal_bar(None, "nasdaq", mid) is None


# ── #198: a quick test never touches the live data ─────────────────────────

def test_a_partial_run_writes_to_a_scratch_dir_unless_told_to_publish(root, monkeypatch):
    seen = {}

    def fake(market, args, run_date, data_root, now=None, provider=None):
        seen[market] = data_root
        return run.PUBLISHED
    monkeypatch.setattr(run, "run_market", fake)
    monkeypatch.setattr(run, "REPO_ROOT", str(root))
    scratch = root.parent / "scratch"
    monkeypatch.setattr(run.tempfile, "mkdtemp", lambda prefix="": str(scratch))
    assert run.main(["--market", "asx", "--limit", "25"], now=SAT) == 0
    assert seen["asx"] == str(scratch)
    assert run.main(["--market", "asx", "--limit", "25", "--publish"], now=SAT) == 0
    assert seen["asx"].startswith(str(root))


def test_a_partial_publish_does_not_prune_other_tickers_charts(root):
    frames = _frames(n=3)
    run.run_market("asx", _args(), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(frames))
    charts = sorted(os.listdir(root / "charts" / "asx"))
    run.run_market("asx", _args(tickers="T0", force=True), "2026-10-10", str(root),
                   now=FRI_EVENING, provider=FrameProvider(frames))
    assert sorted(os.listdir(root / "charts" / "asx")) == charts


def test_main_exit_codes_name_the_outcome(monkeypatch):
    outcomes = iter([run.PUBLISHED, run.CARRIED, run.REFUSED])
    monkeypatch.setattr(run, "run_market", lambda *a, **k: next(outcomes))
    assert run.main(["--market", "asx,nasdaq,crypto", "--out", "x"], now=SAT) == 4
    monkeypatch.setattr(run, "run_market", lambda *a, **k: run.CARRIED)
    assert run.main(["--market", "asx", "--out", "x"], now=SAT) == 3

    def boom(*a, **k):
        raise RuntimeError("yfinance exploded")
    monkeypatch.setattr(run, "run_market", boom)
    assert run.main(["--market", "asx", "--out", "x"], now=SAT) == 1
    assert run.main(["--market", "lse"], now=SAT) == 2

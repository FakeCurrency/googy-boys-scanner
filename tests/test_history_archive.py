"""$0 forward archive + the EODHD live-path fence (owner order 2026-08-15).

Two jobs: (1) the archive stores exactly what the scan downloaded — adjusted,
completed, sparse-honest, splice-consistent, capped, survivorship-frozen; and
(2) the FENCE — EODHD feeds charts/history/research ONLY. The live grade path
must not touch it in this batch, and that is pinned structurally here, not
promised in prose.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

import pandas as pd
import pytest

from scanner import config, history_archive

REPO = pathlib.Path(__file__).resolve().parents[1]
TODAY = history_archive._today("asx")


def _df(rows):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, *_ in rows])
    return pd.DataFrame(
        {"Open": [r[1] for r in rows], "High": [r[2] for r in rows],
         "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
         "Volume": [r[5] for r in rows]}, index=idx)


def _days(n):
    return [(TODAY - dt.timedelta(days=n - i)).isoformat() for i in range(n)]


def test_writes_schema_and_drops_the_forming_bar(tmp_path):
    d = _days(3) + [TODAY.isoformat()]            # 3 completed + today's forming bar
    df = _df([(x, 1.0, 2.0, 0.5, 1.5, 100) for x in d])
    out = history_archive.update("asx", [{"symbol": "BHP"}], {"BHP.AX": df}, root=tmp_path)
    assert out["written"] == 1
    j = json.loads((tmp_path / "asx" / "BHP.json").read_text())
    assert j["symbol"] == "BHP" and j["market"] == "asx" and j["basis"] == "adj"
    assert len(j["bars"]) == 3, "the forming bar (today) must not be archived"
    assert j["bars"][-1][0] != TODAY.isoformat()
    assert j["splice_suspect"] is False


def test_no_fantasy_fills_a_missing_session_stays_missing(tmp_path):
    d = _days(5)
    rows = [(x, 1, 1, 1, 1, 10) for i, x in enumerate(d) if i != 2]   # day 3 never printed
    out = history_archive.update("asx", [{"symbol": "RML"}], {"RML.AX": _df(rows)}, root=tmp_path)
    j = json.loads((tmp_path / "asx" / "RML.json").read_text())
    assert len(j["bars"]) == 4 and d[2] not in [b[0] for b in j["bars"]], \
        "a no-trade day must stay absent — nothing invents a print"
    assert out["new_bars"] == 4


def test_splice_rescales_the_old_tail_onto_the_new_basis(tmp_path):
    base = tmp_path / "asx"; base.mkdir(parents=True)
    d = _days(6)
    # Stored: days 0-3 at the OLD basis (2.0). New frame: days 2-5 at HALF basis
    # (a dividend re-based history) — old-only days 0-1 must be rescaled by 0.5.
    old = {"symbol": "KAR", "market": "asx", "basis": "adj", "updated": d[3],
           "last_seen": d[3], "splice_suspect": False,
           "bars": [[x, 2.0, 2.0, 2.0, 2.0, 10] for x in d[:4]]}
    (base / "KAR.json").write_text(json.dumps(old))
    frame = _df([(x, 1.0, 1.0, 1.0, 1.0, 10) for x in d[2:]])
    history_archive.update("asx", [{"symbol": "KAR"}], {"KAR.AX": frame}, root=tmp_path)
    j = json.loads((base / "KAR.json").read_text())
    assert [b[0] for b in j["bars"]] == d, "old-only days kept, new window replaces overlap"
    assert j["bars"][0][4] == pytest.approx(1.0), "old tail rescaled by the join ratio (0.5)"
    assert j["splice_suspect"] is True, "a 50% join drift is past the 25% suspicion line"


def test_delisted_name_is_frozen_not_deleted(tmp_path):
    base = tmp_path / "asx"; base.mkdir(parents=True)
    stored = {"symbol": "GONE", "market": "asx", "basis": "adj", "updated": "2026-01-05",
              "last_seen": "2026-01-05", "splice_suspect": False,
              "bars": [["2026-01-02", 1, 1, 1, 1, 5]]}
    (base / "GONE.json").write_text(json.dumps(stored))
    history_archive.update("asx", [{"symbol": "BHP"}],
                           {"BHP.AX": _df([(x, 1, 1, 1, 1, 1) for x in _days(2)])}, root=tmp_path)
    assert json.loads((base / "GONE.json").read_text()) == stored, \
        "a vanished name keeps its frozen file — that IS the survivorship record"


def test_caps_and_same_session_noop(tmp_path):
    df = _df([(x, 1, 1, 1, 1, 1) for x in _days(4)])
    frames = {"BHP.AX": df}
    history_archive.update("asx", [{"symbol": "BHP"}], frames, root=tmp_path)
    p = tmp_path / "asx" / "BHP.json"
    before = p.read_text()
    out2 = history_archive.update("asx", [{"symbol": "BHP"}], frames, root=tmp_path)
    assert out2["written"] == 0 and p.read_text() == before, \
        "second scan of the same session must be a byte-level no-op"
    assert config.HISTORY_ARCHIVE_MAX_BARS >= 1300, "cap must hold >5y of sessions"
    assert config.HISTORY_ARCHIVE_MARKETS == ("asx",)
    assert history_archive.update("crypto", [{"symbol": "BTC"}], {}, root=tmp_path) == {}


# ── THE FENCE — EODHD is charts/history/research ONLY in this batch ──────────

def test_fence_no_scanner_module_references_eodhd():
    hits = []
    for p in list((REPO / "scanner").rglob("*.py")):
        if "eodhd" in p.read_text(encoding="utf-8", errors="ignore").lower():
            hits.append(str(p))
    assert not hits, f"live engine path references EODHD: {hits} — that is a data-regime change " \
                     "the owner has NOT ordered (phase-2 cutover only, explicitly)"


def test_fence_no_workflow_hands_the_key_to_actions():
    for wf in (REPO / ".github" / "workflows").glob("*.yml"):
        assert "EODHD" not in wf.read_text(encoding="utf-8"), \
            f"{wf.name} exposes an EODHD secret to Actions — the key lives in Cloudflare ONLY"


def test_fence_download_is_still_yfinance():
    src = (REPO / "scanner" / "data.py").read_text(encoding="utf-8")
    assert re.search(r"yf\.download\(", src) and "auto_adjust=True" in src, \
        "the live engine's download path moved off yfinance without an owner order"


def test_the_run_hook_is_fail_soft_and_storage_only():
    src = (REPO / "scanner" / "run.py").read_text(encoding="utf-8")
    m = re.search(r"try:\s*\n\s+from \. import history_archive.+?except Exception", src, re.S)
    assert m, "the archive hook lost its try/except — an archive fault could cost a scan"
    assert "history_archive" not in (REPO / "scanner" / "vivek.py").read_text(encoding="utf-8")
    assert "history_archive" not in (REPO / "scanner" / "broker" / "vivek_run.py").read_text(encoding="utf-8"), \
        "nothing in the grade/bot path may READ the archive"


# ── REFINE200 #155 ────────────────────────────────────────────────────────────

def test_a_suspect_splice_stays_flagged_after_a_clean_join(tmp_path, monkeypatch):
    """Day 2 re-bases the frame 40% (suspect); day 3 joins cleanly onto day
    2's basis. The 40%-rescaled tail is still in the file, so the flag that
    warns about it must survive day 3 -- it used to clear itself."""
    d = _days(8)
    base = tmp_path / "asx"
    clock = {"today": dt.date.fromisoformat(d[4])}
    monkeypatch.setattr(history_archive, "_today", lambda m: clock["today"])

    def run(rows):
        history_archive.update("asx", [{"symbol": "KAR"}], {"KAR.AX": _df(rows)}, root=tmp_path)
        return json.loads((base / "KAR.json").read_text())

    j1 = run([(x, 1.0, 1.0, 1.0, 1.0, 10) for x in d[:4]])
    assert j1["splice_suspect"] is False and "suspect_since" not in j1
    clock["today"] = dt.date.fromisoformat(d[5])
    j2 = run([(x, 1.4, 1.4, 1.4, 1.4, 10) for x in d[2:5]])      # re-based 40%
    assert j2["splice_suspect"] is True and j2["suspect_since"] == d[5]
    clock["today"] = dt.date.fromisoformat(d[6])
    j3 = run([(x, 1.4, 1.4, 1.4, 1.4, 10) for x in d[3:6]])      # same basis, +1 bar
    assert j3["splice_suspect"] is True, "the broken join is still in the series"
    assert j3["suspect_since"] == d[5], "dated from the FIRST suspect join"
    assert list(j3).index("suspect_since") < list(j3).index("bars")


def test_the_new_name_cap_is_plainly_the_file_count(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HISTORY_ARCHIVE_MAX_FILES", 2)
    frames = {f"{s}.AX": _df([(x, 1, 1, 1, 1, 1) for x in _days(3)]) for s in "ABC"}
    out = history_archive.update("asx", [{"symbol": s} for s in "ABC"], frames, root=tmp_path)
    assert out["written"] == 2 and out["total_files"] == 2
    assert sorted(p.stem for p in (tmp_path / "asx").glob("*.json")) == ["A", "B"]
    src = (REPO / "scanner" / "history_archive.py").read_text(encoding="utf-8")
    assert "(written and 0)" not in src, "the garbled always-0 term is gone"


def test_root_is_anchored_to_the_repo_not_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    mod = importlib.reload(history_archive)
    assert mod.ROOT == REPO / "data" / "history"
    assert mod.ROOT.is_absolute()


def test_market_dates_come_from_config_timezones():
    src = (REPO / "scanner" / "history_archive.py").read_text(encoding="utf-8")
    assert "_MARKET_TZ" not in src and "Australia/Sydney" not in src
    from zoneinfo import ZoneInfo
    for m in ("asx", "nasdaq", "crypto"):
        want = dt.datetime.now(ZoneInfo(config.MARKETS[m].timezone)).date()
        assert history_archive._today(m) in (want, want + dt.timedelta(days=1))
    utc = dt.datetime.now(dt.timezone.utc).date()
    assert history_archive._today("nowhere") in (utc, utc + dt.timedelta(days=1))


# ── REFINE200 WP16: a cache-reused frame is not today's download ──────────────

def test_a_cache_reused_frame_is_not_archived(tmp_path):
    """merge_with_cache hands back an EARLIER run's frame for a ticker the
    source skipped. Its last bar was forming when it was downloaded, so once
    the market date rolls it would pass the `< today` test as a completed bar
    (14 Oct 2026: 41 ASX files took the 16:45 13-Oct snapshot as the close)."""
    from scanner import data
    d = _days(3)
    good = _df([(x, 1.0, 2.0, 0.5, 1.5, 100) for x in d])
    history_archive.update("asx", [{"symbol": "RIO"}], {"RIO.AX": good}, root=tmp_path)
    path = tmp_path / "asx" / "RIO.json"
    before = path.read_bytes()
    stale = data._as_reused(_df([(x, 9.0, 9.0, 9.0, 9.0, 1) for x in _days(4)]))
    assert stale.attrs.get(data.CACHE_REUSED)
    out = history_archive.update("asx", [{"symbol": "RIO"}, {"symbol": "NEW"}],
                                 {"RIO.AX": stale, "NEW.AX": stale}, root=tmp_path)
    assert out["written"] == 0 and out["skipped_reused"] == 2
    assert path.read_bytes() == before, "the stored file must not take the reused bars"
    assert not (tmp_path / "asx" / "NEW.json").exists()
    # the same frame, fresh (untagged), is archived as before
    out = history_archive.update("asx", [{"symbol": "NEW"}],
                                 {"NEW.AX": _df([(x, 1, 1, 1, 1, 1) for x in d])}, root=tmp_path)
    assert out["written"] == 1 and out["skipped_reused"] == 0

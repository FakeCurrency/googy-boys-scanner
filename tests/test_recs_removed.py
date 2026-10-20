"""The RECS page stays removed (owner 2026-10-20: "It's a waste. I dont use it").

recommendations.html, recs.js, scripts/reco_note.py, reco_note.yml and
public/data/reco_note.json went together. These pins keep the page, its nav
entry, its PWA shortcut, its daily workflow and that workflow's watchdog row
from coming back half-wired (a nav link to a 404, or a WATCHDOG_RUNS row for a
workflow that never runs again, which would warn every day).
"""
import json
import pathlib

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]

GONE = ("public/recommendations.html", "public/js/recs.js", "scripts/reco_note.py",
        ".github/workflows/reco_note.yml", "public/data/reco_note.json")


def test_the_recs_files_are_gone():
    for rel in GONE:
        assert not (ROOT / rel).exists(), f"{rel} was removed 2026-10-20"


def test_no_page_or_script_links_the_recs_page():
    for p in list((ROOT / "public").glob("*.html")) + list((ROOT / "public/js").glob("*.js")):
        src = p.read_text(encoding="utf-8")
        assert "recommendations.html" not in src, f"{p.name} still links the removed RECS page"
        assert "recs.js" not in src, f"{p.name} still loads the removed recs.js"
        assert "reco_note" not in src, f"{p.name} still reads the removed reco note"


def test_no_pwa_shortcut_to_recs():
    m = json.loads((ROOT / "public/manifest.json").read_text(encoding="utf-8"))
    assert not any("recommendations" in s.get("url", "") for s in m.get("shortcuts", []))


def test_no_workflow_or_watchdog_row_for_the_reco_note():
    assert "reco_note.yml" not in config.WATCHDOG_RUNS
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        src = wf.read_text(encoding="utf-8")
        assert "reco_note.py" not in src and "reco_note.json" not in src, wf.name

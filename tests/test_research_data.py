"""Research outputs live in data/research/, not on the site (REFINE200 #63/#64).

The parity / OOS / C3 replays, their symbol samples and gates, the fill
sensitivity and the confluence study were committed under public/data/, so
Cloudflare shipped ~5 MB that no page reads. They moved to data/research/
(still committed, still recomputable), and the parity writer's defaults moved
with them. Four Discord-era files (a webhook preview, an email preview and two
TradingView watchlists), a 2026-08-20 write probe and the retired AI BOT's
event calendar had no writer and no reader and were deleted.

The one trap in the move is the FX rate: `set_fx_path` reads fx.json from the
DIRECTORY of the report, and data/research/ has none, so a default parity run
would have quietly priced its secondary $ columns at the fallback rate. The
default run reads the scan's public/data/fx.json instead (pinned below).
"""

from __future__ import annotations

import pathlib
import sys

from scanner import config
from scanner import vivek_backtest as bt
from scanner import vivek_parity

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_DATA = ROOT / "public" / "data"
RESEARCH = ROOT / "data" / "research"

RESEARCH_FILES = (
    "vivek_backtest_parity.json",
    "vivek_backtest_parity_oos.json",
    "vivek_backtest_parity_c3.json",
    "vivek_fill_sensitivity.json",
    "vivek_confluence_study.json",
    "vivek_parity_c3_symbols.json",
    "vivek_parity_is_symbols.json",
    "vivek_parity_oos_symbols.json",
    "vivek_parity_oos_gates.json",
)
DELETED_ORPHANS = (
    "discord_preview.json",
    "alert_preview.html",
    "watchlist_asx.txt",
    "watchlist_nasdaq.txt",
    ".grok-write-probe.txt",
    # The AI BOT's economic calendar: nothing has read or written it since
    # that page went (2026-09-17); backups dropped it the same day as this.
    "events.json",
)


def test_research_files_live_in_data_research_and_not_on_the_site():
    for name in RESEARCH_FILES:
        assert (RESEARCH / name).is_file(), f"data/research/{name} is missing"
        assert not (PUBLIC_DATA / name).exists(), f"public/data/{name} ships to the site again"


def test_the_discord_era_orphans_stay_deleted():
    for name in DELETED_ORPHANS:
        assert not (PUBLIC_DATA / name).exists(), f"public/data/{name} came back"


def test_the_parity_writer_defaults_to_data_research():
    assert config.VIVEK_PARITY_OUT_FILE == "data/research/vivek_backtest_parity.json"
    assert config.VIVEK_PARITY_OOS_OUT_FILE == "data/research/vivek_backtest_parity_oos.json"


def _run_parity_main(monkeypatch, argv):
    """Drive vivek_backtest.main --parity with the replay stubbed out."""
    written = {}
    monkeypatch.setattr(vivek_parity, "run_parity",
                        lambda *a, **k: {"generated_at": "x", "coverage": {}})
    monkeypatch.setattr(vivek_parity, "print_parity", lambda report: None)
    monkeypatch.setattr(bt.output, "write_json",
                        lambda path, payload, **k: written.setdefault("path", pathlib.Path(path)))
    monkeypatch.setattr(sys, "argv", ["vivek_backtest", "--parity", "--market", "asx",
                                      "--workers", "1", *argv])
    try:
        bt.main()
        return written["path"], bt._FX_PATH
    finally:
        bt.set_fx_path(bt.OUT_FILE)


def test_a_default_parity_run_writes_research_but_reads_the_published_fx(monkeypatch):
    path, fx = _run_parity_main(monkeypatch, [])
    assert path == ROOT / config.VIVEK_PARITY_OUT_FILE
    assert fx == PUBLIC_DATA / "fx.json", "a default run must price $ at the scan's rate"


def test_an_explicit_out_still_reads_fx_beside_it(monkeypatch, tmp_path):
    path, fx = _run_parity_main(monkeypatch, ["--out", str(tmp_path / "r.json")])
    assert path == tmp_path / "r.json"
    assert fx == tmp_path / "fx.json"

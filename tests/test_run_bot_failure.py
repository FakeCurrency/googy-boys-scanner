"""REFINE200 #20 -- a paper-bot crash must not exit 0.

run.py wrapped `vivek_run.run_market` in `except Exception: print("bot book:
skipped")` and never recorded it, so a run whose bot layer threw -- the book
not managed, no stop tested, no entry decided -- read green. The fix records it
in `failed_markets` beside the markets whose SCAN threw, so the process still
publishes everything (the scan pair, the slim prices file, bot_rules.json) and
only then exits 1. These tests drive the real `main()` end to end with the
network and the heavy layers stubbed out.
"""
from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from scanner import config, output, scan
from scanner import run as runmod


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    uni = [{"symbol": "AAA", "name": "Alpha", "yf": "AAA", "sector": ""}]
    monkeypatch.setattr(runmod, "load_universe", lambda m, full=True: list(uni))
    monkeypatch.setattr(runmod, "identity_kwargs", lambda *a, **k: {})
    monkeypatch.setattr(runmod, "fetch", lambda m, t, **k: ({"AAA": pd.DataFrame({"Close": [1.0]})}, {}))
    monkeypatch.setattr(runmod, "merge_with_cache",
                        lambda m, fresh, t, **k: (dict(fresh), {"fresh": 1, "reused": 0}))
    monkeypatch.setattr(runmod, "tag_sources", lambda *a, **k: None)
    monkeypatch.setattr(runmod, "_scan_health", lambda *a, **k: 0)
    monkeypatch.setattr(runmod, "download", lambda *a, **k: {})   # FX leg: no rate

    def fake_scan(market_key, **kw):
        return {"market": market_key, "schema_version": config.VIVEK_SCHEMA_VERSION,
                "generated_at": "2026-10-14T10:00:00+00:00", "scanned": 1,
                "universe_size": 1, "results": [], "prices": {"AAA": 1.0},
                "price_age": {}}
    monkeypatch.setattr(scan, "scan_vivek_market", fake_scan)

    from scanner import funnelhistory, history_archive, sectors
    monkeypatch.setattr(funnelhistory, "append", lambda *a, **k: None)
    monkeypatch.setattr(history_archive, "update", lambda *a, **k: {})
    monkeypatch.setattr(sectors, "fetch", lambda: {"markets": {"asx": {"sectors": []},
                                                              "us": {"sectors": []}}})
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(sys, "argv", ["scanner.run", "--market", "nasdaq",
                                      "--out", str(tmp_path)])
    return tmp_path


def _bot(monkeypatch, fn):
    from scanner.broker import vivek_run
    monkeypatch.setattr(vivek_run, "run_market", fn)


def test_a_bot_crash_exits_non_zero_after_publishing_everything(harness, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("book exploded")
    _bot(monkeypatch, boom)
    with pytest.raises(SystemExit) as exc:
        runmod.main()
    assert exc.value.code == 1, "a bot-layer crash must fail the run, not read green"
    out = capsys.readouterr().out
    assert "bot book: FAILED (RuntimeError: book exploded)" in out
    assert "nasdaq: bot book: RuntimeError: book exploded" in out, \
        "the closing summary must name the market AND say it was the bot layer"
    # ...and still published the scan and every surface after the loop.
    for name in ("nasdaq_vivek.json", "nasdaq_vivek_detail.json",
                 "nasdaq_prices.json", "bot_rules.json", "sectors.json"):
        assert (harness / name).exists(), f"{name} must still publish"
    out.encode("ascii")   # scanner prints stay console-safe (cp1252)


def test_a_healthy_bot_run_still_exits_cleanly(harness, monkeypatch, capsys):
    _bot(monkeypatch, lambda *a, **k: {"open": [{"market": "nasdaq", "direction": "long"}]})
    runmod.main()                                   # no SystemExit
    out = capsys.readouterr().out
    assert "bot book: 1 open | 0 short" in out
    assert "FAILED" not in out
    assert json.loads((harness / "nasdaq_prices.json").read_text())["prices"] == {"AAA": 1.0}


def test_the_bot_failure_is_recorded_not_swallowed():
    """Structural pin beside the behaviour above: the bot handler appends to
    the same list the exit block reads."""
    src = (runmod.REPO_ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    handler = src.split("vivek_run.run_market(", 1)[1].split("except Exception as e:", 1)[1]
    handler = handler.split("except Exception as e:", 1)[0]
    assert "failed_markets.append(" in handler
    assert "bot book: skipped" not in handler
    assert output  # imported for the fixture's side effects

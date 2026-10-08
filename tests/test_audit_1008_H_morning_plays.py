"""Audit #32 (2026-10-08): names hidden behind '+N more' were recorded as SENT.

_market_block names only picks[:MORNING_PLAYS_MAX_ROWS] and folds the rest
into '...+N more (see the app)', but main() recorded the FULL list, so every
over-cap name was stamped as delivered and the 7-day dedup then kept it out of
every digest for a week without it ever appearing in one. Only the names the
messages actually NAME may be recorded.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scripts import morning_plays as mp
from scanner import config

pytestmark = pytest.mark.risk

US_SLOT = dt.datetime(2026, 9, 9, 6, 30, tzinfo=dt.timezone.utc)


def _row(symbol, score):
    return {"symbol": symbol, "name": f"{symbol} Inc", "grade": "A+", "dir": "LONG",
            "score": score,
            "plans": {"1W": {"armed": True, "entry_trigger": "reclaim", "structural_tps": 0}}}


def _data(tmp_path, n_nasdaq):
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = [_row(f"N{i:02d}", 1000 - i) for i in range(n_nasdaq)]   # N00 strongest
    (d / "nasdaq_vivek.json").write_text(json.dumps({"generated_at": now, "results": rows}))
    (d / "crypto_vivek.json").write_text(json.dumps({"generated_at": now, "results": [_row("LINK", 5)]}))
    (d / "asx_vivek.json").write_text(json.dumps({"generated_at": now, "results": []}))
    return str(d)


def _run(tmp_path, monkeypatch, data_dir, now, posts):
    monkeypatch.setattr(config, "MORNING_PLAYS_TZ", "UTC")
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    seen = str(tmp_path / "seen.json")
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen], now=now) == 0
    return mp.load_state(seen)


def test_only_the_named_rows_are_recorded_as_sent(tmp_path, monkeypatch):
    cap = int(config.MORNING_PLAYS_MAX_ROWS)
    posts: list[str] = []
    state = _run(tmp_path, monkeypatch, _data(tmp_path, cap + 5), US_SLOT, posts)
    text = "\n".join(posts)
    assert "+5 more" in text
    named = {f"N{i:02d}" for i in range(cap)}
    hidden = {f"N{i:02d}" for i in range(cap, cap + 5)}
    for s in named:
        assert f"\n{s}\n" in f"\n{text}\n" and state["sent"].get(f"nasdaq:{s}") == "2026-09-09"
    for s in hidden:
        assert s not in text, "sanity: an over-cap name is not in any message"
        assert f"nasdaq:{s}" not in state["sent"], f"{s} was never named - it must not be buried"
    assert state["sent"].get("crypto:LINK") == "2026-09-09"


def test_the_over_cap_names_lead_the_next_slot(tmp_path, monkeypatch):
    cap = int(config.MORNING_PLAYS_MAX_ROWS)
    data_dir = _data(tmp_path, cap + 5)
    posts: list[str] = []
    _run(tmp_path, monkeypatch, data_dir, US_SLOT, posts)
    posts.clear()
    _run(tmp_path, monkeypatch, data_dir, US_SLOT + dt.timedelta(days=1), posts)
    text = "\n".join(posts)
    assert "No new plays" not in text
    for i in range(cap, cap + 5):
        assert f"N{i:02d}" in text, "yesterday's '+N more' names are new to the reader"
    assert "N00" not in text, "a name that WAS named stays inside its 7-day window"


def test_shown_is_the_slice_the_block_renders():
    cap = mp.max_rows()
    picks = {"nasdaq": [_row(f"N{i:02d}", 100 - i) for i in range(cap + 3)], "crypto": []}
    out = mp.shown(picks)
    assert [r["symbol"] for r in out["nasdaq"]] == [f"N{i:02d}" for i in range(cap)]
    assert out["crypto"] == []
    block = "\n".join(mp._market_block("nasdaq", picks["nasdaq"], cap, None, 0))
    assert all(r["symbol"] in block for r in out["nasdaq"])

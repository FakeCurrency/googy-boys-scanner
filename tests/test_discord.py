"""Discord digest — filtering, formatting, chunking, and resilient posting.

Covers scanner/discord.py without ever hitting the network: the webhook POST is
monkeypatched, so these verify the logic that decides WHAT gets posted and HOW
it's shaped, plus the retry/back-off behaviour.
"""

import json

import pytest

from scanner import config
from scanner import discord as dsc

pytestmark = pytest.mark.journal  # reuse a marker; logic-only, no network


def _row(symbol, grade="A", score=9, **kw):
    r = {"symbol": symbol, "grade": grade, "score": score, "score_max": 15,
         "dir": "LONG", "rr": 2.0, "low_rr": False,
         "entry": 10.0, "stop": 9.5, "target": 11.0}
    r.update(kw)
    return r


# ── grade filtering ───────────────────────────────────────────────────────────

def test_grades_to_post_includes_stronger_grades():
    assert dsc.grades_to_post("A") == {"A+", "A"}
    assert dsc.grades_to_post("A+") == {"A+"}
    assert dsc.grades_to_post("B") == {"A+", "A", "B"}


# ── dedup ─────────────────────────────────────────────────────────────────────

def test_dedup_keeps_highest_score_per_symbol():
    rows = [_row("BHP", score=7), _row("BHP", score=11), _row("CBA", score=9)]
    out = dsc.dedup_by_symbol(rows)
    syms = {r["symbol"]: r["score"] for r in out}
    assert syms == {"BHP": 11, "CBA": 9}
    assert len(out) == 2


# ── collect: new vs all (state dedup) ─────────────────────────────────────────

def test_collect_new_vs_all(tmp_path, monkeypatch):
    monkeypatch.setattr(dsc, "ROOT", tmp_path)
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    scan = {"label": "ASX", "currency_symbol": "A$", "market": "asx",
            "results": [_row("BHP", "A"), _row("CBA", "A+"), _row("XYZ", "C")]}
    (d / "asx.json").write_text(json.dumps(scan))

    grades = dsc.grades_to_post("A")
    # First run: nothing seen → both tradeable names are "new"
    state = {}
    _, items = dsc.collect("asx", state, send_all=False, grades=grades)
    assert {r["symbol"] for r in items} == {"BHP", "CBA"}   # C filtered out
    assert set(state["asx"]) == {"BHP", "CBA"}

    # Second run, same data: nothing new
    _, items2 = dsc.collect("asx", state, send_all=False, grades=grades)
    assert items2 == []

    # send_all re-emits everything regardless of state
    _, items3 = dsc.collect("asx", state, send_all=True, grades=grades)
    assert {r["symbol"] for r in items3} == {"BHP", "CBA"}


# ── formatting ────────────────────────────────────────────────────────────────

def test_setup_line_is_consistent_and_complete():
    line = dsc.setup_line(_row("BHP", "A", rr=3.1, entry=28.4, stop=26.9, target=33.1), "A$")
    assert "**BHP**" in line and "A" in line
    assert "R:R 3.1" in line
    assert "entry A$28.4000" in line and "stop A$26.9000" in line and "target A$33.1000" in line


def test_setup_line_flags_low_rr_and_short():
    line = dsc.setup_line(_row("Z", "A", low_rr=True, dir="SHORT"), "$")
    assert "low R:R" in line
    assert "SHORT" in line


def test_build_market_embed_caps_and_colours(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_MAX_PER_MARKET", 2)
    scan = {"label": "ASX", "currency_symbol": "A$"}
    items = [_row("A1", "A"), _row("A2", "A+"), _row("A3", "A")]
    embed = dsc.build_market_embed(scan, items)
    # capped to 2, title notes the total + top-N
    assert "3 setups" in embed["title"] and "top 2" in embed["title"]
    # best grade present in the cap is A+ → its colour
    assert embed["color"] == config.DISCORD_GRADE_COLORS["A+"]
    assert embed["description"].count("\n") >= 2  # two setups, two lines each


# ── payload chunking ──────────────────────────────────────────────────────────

def test_build_payloads_header_and_footer():
    digests = [("asx", {"label": "ASX", "currency_symbol": "A$"}, [_row("BHP")])]
    payloads = dsc.build_payloads(digests, total=1)
    assert len(payloads) == 1
    assert "1 new setup" in payloads[0]["content"]
    assert payloads[0]["username"] == config.DISCORD_USERNAME
    assert "not financial advice" in payloads[0]["embeds"][-1]["footer"]["text"]


def test_build_payloads_chunks_over_ten_markets():
    digests = [(f"m{i}", {"label": f"M{i}", "currency_symbol": "$"}, [_row(f"S{i}")])
               for i in range(13)]
    payloads = dsc.build_payloads(digests, total=13)
    assert len(payloads) == 2                       # 13 embeds → 10 + 3
    assert len(payloads[0]["embeds"]) == 10
    assert len(payloads[1]["embeds"]) == 3
    assert "content" in payloads[0] and "content" not in payloads[1]


# ── posting: retries + status handling ────────────────────────────────────────

class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)
    def json(self):
        return self._body


def test_post_webhook_success(monkeypatch):
    monkeypatch.setattr(dsc.requests, "post", lambda *a, **k: _Resp(204))
    assert dsc.post_webhook("http://x", {"a": 1}) is True


def test_post_webhook_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}
    def fake_post(*a, **k):
        calls["n"] += 1
        return _Resp(204) if calls["n"] >= 2 else _Resp(429, {"retry_after": 0.01})
    monkeypatch.setattr(dsc.requests, "post", fake_post)
    monkeypatch.setattr(dsc.time, "sleep", lambda *_: None)
    assert dsc.post_webhook("http://x", {}, retries=3) is True
    assert calls["n"] == 2


def test_post_webhook_gives_up_on_client_error(monkeypatch):
    monkeypatch.setattr(dsc.requests, "post", lambda *a, **k: _Resp(400, {"error": "bad"}))
    assert dsc.post_webhook("http://x", {}) is False


def test_run_no_webhook_writes_preview_and_advances_state(tmp_path, monkeypatch):
    monkeypatch.setattr(dsc, "ROOT", tmp_path)
    monkeypatch.setattr(dsc, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(dsc, "PREVIEW", tmp_path / "preview.json")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    d = tmp_path / "public" / "data"; d.mkdir(parents=True)
    (d / "asx.json").write_text(json.dumps(
        {"label": "ASX", "currency_symbol": "A$", "results": [_row("BHP", "A")]}))

    posted = dsc.run(["asx"], send_all=False)
    assert posted == 1
    assert (tmp_path / "preview.json").exists()       # preview always written
    assert (tmp_path / "state.json").exists()         # state advanced so we don't re-dump

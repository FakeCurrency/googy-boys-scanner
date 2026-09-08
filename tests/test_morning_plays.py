"""Morning Discord high-conviction digest (scripts/morning_plays.py).

Owner spec (2026-09-08): LONG plays only, no SHORTs, no FUNDS/REITs, clean
text `SYMBOL -> label`. Default = high-conviction longs; an opt-in widens to
every long A+. Pins the definition (identical to app.js isHighConviction),
the filter, the label, the message shape/chunking, and the exit codes.
"""

import datetime as dt
import json

import pytest

from scripts import morning_plays as mp
from scanner import config

pytestmark = pytest.mark.risk


def _row(symbol="AAA", grade="A+", direction="LONG", trigger="reclaim",
         armed=True, structural=0, score=100, **kw):
    r = {"symbol": symbol, "name": f"{symbol} Ltd", "grade": grade,
         "dir": direction, "score": score,
         "plans": {"1W": {"armed": armed, "entry_trigger": trigger,
                          "structural_tps": structural}}}
    r.update(kw)
    return r


# ── the definition, byte-for-byte with app.js isHighConviction ───────────────

def test_high_conviction_is_a_weekly_armed_reclaim_that_is_A_or_strong():
    assert mp.is_high_conviction(_row(grade="A+"))
    assert mp.is_high_conviction(_row(grade="A"))
    assert mp.is_high_conviction(_row(grade="B+", structural=2))     # strong structure
    assert not mp.is_high_conviction(_row(grade="B+", structural=1))
    assert not mp.is_high_conviction(_row(trigger="retest"))
    assert not mp.is_high_conviction(_row(armed=False))
    assert not mp.is_high_conviction({"grade": "A+", "plans": {}})


def test_it_matches_the_shipped_app_js_rule():
    src = (mp.ROOT / "public" / "js" / "app.js").read_text(encoding="utf-8")
    body = src[src.index("function isHighConviction("):]
    body = body[:body.index("}")]
    assert 'entry_trigger !== "reclaim"' in body
    assert '"A+"' in body and '"A"' in body
    assert "structural_tps" in body and ">= 2" in body


# ── the filter: long only, no funds, high-conviction (or opt-in A+) ──────────

def test_qualifies_is_long_high_conviction_and_never_a_short_or_fund():
    assert mp.qualifies(_row("HC", grade="A+"))                       # long, HC
    assert not mp.qualifies(_row("S", grade="A+", direction="SHORT")), "no shorts"
    assert not mp.qualifies(_row("F", grade="A+", is_product=True)), "no funds/REITs"


def test_a_plain_long_A_plus_needs_the_opt_in(monkeypatch):
    plain = _row("PLAIN", grade="A+", trigger="retest")              # A+ but not HC
    monkeypatch.setattr(config, "MORNING_PLAYS_INCLUDE_ALL_APLUS", False)
    assert not mp.qualifies(plain), "focused default excludes plain long A+"
    monkeypatch.setattr(config, "MORNING_PLAYS_INCLUDE_ALL_APLUS", True)
    assert mp.qualifies(plain), "opt-in includes plain long A+"
    # a plain long A+ short is STILL excluded even with the opt-in on
    assert not mp.qualifies(_row(grade="A+", trigger="retest", direction="SHORT"))


def test_the_label_says_why_a_play_made_the_cut():
    assert mp.play_label(_row(grade="A+")) == "A+ High conviction"
    assert mp.play_label(_row(grade="A")) == "High conviction"        # HC but not A+
    assert mp.play_label(_row(grade="A+", trigger="retest")) == "A+"  # A+ but not HC


def test_select_filters_and_sorts_by_score():
    rows = [_row("LOW", score=1), _row("HI", score=99),
            _row("SHORT_HC", direction="SHORT", score=50),           # dropped: short
            _row("FUND", is_product=True, score=50)]                 # dropped: product
    assert [r["symbol"] for r in mp.select(rows)] == ["HI", "LOW"]


# ── the clean text message ───────────────────────────────────────────────────

def test_empty_morning_sends_a_none_message_not_silence():
    msgs = mp.build_messages({"asx": [], "nasdaq": []},
                             {"asx": 1.0, "nasdaq": 1.0}, "Mon 1 Jan")
    assert len(msgs) == 1 and "No long high-conviction" in msgs[0]


def test_the_message_is_clean_symbol_arrow_label_grouped_by_market():
    picks = {"asx": [_row("JHX", grade="A+")],
             "nasdaq": [_row("CRWV", grade="A")]}
    msgs = mp.build_messages(picks, {"asx": 1.0, "nasdaq": 1.0}, "Mon 1 Jan")
    text = "\n".join(msgs)
    assert "**ASX plays**" in text and "**NASDAQ plays**" in text
    assert "JHX → A+ High conviction" in text
    assert "CRWV → High conviction" in text
    # clean: none of the old entry/stop/RR clutter, no company names, no arrows
    assert "entry" not in text and "stop" not in text and "R:R" not in text
    assert "▲" not in text and "▼" not in text and "Ltd" not in text


def test_a_market_with_no_plays_still_shows_a_header():
    msgs = mp.build_messages({"asx": [_row("JHX")], "nasdaq": []},
                             {"asx": 1.0, "nasdaq": 1.0}, "Mon 1 Jan")
    text = "\n".join(msgs)
    assert "**NASDAQ plays**" in text and "(none this morning)" in text


def test_a_long_list_is_chunked_under_the_discord_limit():
    big = {"asx": [_row(f"S{i:03d}", score=i) for i in range(400)], "nasdaq": []}
    # bypass the per-market cap so the chunker is what does the splitting
    orig = config.MORNING_PLAYS_MAX_ROWS
    try:
        config.MORNING_PLAYS_MAX_ROWS = 400
        msgs = mp.build_messages(big, {"asx": None, "nasdaq": None}, "Mon 1 Jan")
    finally:
        config.MORNING_PLAYS_MAX_ROWS = orig
    assert len(msgs) > 1, "a 400-row list must split into several messages"
    assert all(len(m) <= mp.CONTENT_LIMIT for m in msgs)


def test_a_stale_scan_is_noted():
    picks = {"asx": [_row("AAA")]}
    fresh = "\n".join(mp.build_messages(picks, {"asx": 2.0}, "Mon 1 Jan"))
    stale = "\n".join(mp.build_messages(picks, {"asx": 48.0}, "Mon 1 Jan"))
    assert "old" not in fresh and "old" in stale


# ── the hour gate ────────────────────────────────────────────────────────────

def test_only_the_target_hour_sends_unless_forced():
    seven = dt.datetime(2026, 9, 9, 7, 3)
    eight = dt.datetime(2026, 9, 9, 8, 3)
    assert mp.should_send_now(seven, 7, force=False)
    assert not mp.should_send_now(eight, 7, force=False)
    assert mp.should_send_now(eight, 7, force=True)


# ── posting ──────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_post_sends_json_with_a_named_ua_and_returns_status():
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["ua"] = req.get_header("User-agent")
        seen["ct"] = req.get_header("Content-type")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(204)

    status = mp.post("https://discord.test/wh", {"content": "hi"},
                     "vivek5-morning/1.0", urlopen=fake_urlopen)
    assert status == 204
    assert seen["ua"] == "vivek5-morning/1.0" and seen["ct"] == "application/json"
    assert seen["body"] == {"content": "hi"}


# ── main() end to end ────────────────────────────────────────────────────────

def _fixtures(tmp_path):
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    (d / "asx_vivek.json").write_text(json.dumps({"generated_at": now, "results": [
        _row("JHX", grade="A+"),
        _row("SHORTY", grade="A+", direction="SHORT"),     # dropped: short
        _row("FUNDY", grade="A+", is_product=True)]}))     # dropped: product
    (d / "nasdaq_vivek.json").write_text(json.dumps({"generated_at": now, "results": [
        _row("HLIT", grade="A")]}))
    return d


def test_main_missing_webhook_warns_and_exits_zero_without_posting(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(config.MORNING_PLAYS_WEBHOOK_ENV, raising=False)
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(a) or 204)
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path))])
    assert rc == 0 and not called
    assert "::warning::" in capsys.readouterr().out


def test_main_delivers_with_a_cleaned_webhook_and_only_longs(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV,
                       "﻿https://discord.test/wh \n")       # BOM + trailing ws
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: seen.update(url=url, body=payload) or 204)
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path))])
    assert rc == 0
    assert seen["url"] == "https://discord.test/wh", "clean_secret trims BOM + ws"
    content = seen["body"]["content"]
    assert "JHX" in content and "HLIT" in content
    assert "SHORTY" not in content and "FUNDY" not in content, "no shorts, no funds"


def test_main_returns_1_when_the_post_fails_loudly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("reset")))
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path))])
    assert rc == 1 and "::error::" in capsys.readouterr().out


def test_main_returns_1_on_a_non_2xx_status(tmp_path, monkeypatch):
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda *a, **k: 500)
    assert mp.main(["--force", "--data-dir", str(_fixtures(tmp_path))]) == 1


def test_a_dry_run_never_posts(tmp_path, monkeypatch):
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(1) or 204)
    assert mp.main(["--force", "--dry-run", "--data-dir", str(_fixtures(tmp_path))]) == 0
    assert not called

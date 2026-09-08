"""Morning Discord high-conviction digest (scripts/morning_plays.py, 2026-09-08).

Pins the definition (identical to app.js isHighConviction), the payload shape,
the Melbourne hour gate, the BOM-trimmed webhook, and the exit codes -- a dead
send must be loud (exit 1), a missing webhook is a green setup gap (exit 0).
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
         "dir": direction, "entry": 10.0, "stop": 9.0, "tp1": 11, "tp2": 12,
         "tp3": 13, "rr": 2.0, "score": score,
         "plans": {"1W": {"armed": armed, "entry_trigger": trigger,
                          "structural_tps": structural}}}
    r.update(kw)
    return r


# ── the definition, byte-for-byte with app.js isHighConviction ───────────────

def test_high_conviction_is_a_weekly_armed_reclaim_that_is_A_or_strong():
    assert mp.is_high_conviction(_row(grade="A+"))
    assert mp.is_high_conviction(_row(grade="A"))
    # B+ but strong structure (>=2 structural TPs) still qualifies
    assert mp.is_high_conviction(_row(grade="B+", structural=2))
    # B+ with weak structure does not
    assert not mp.is_high_conviction(_row(grade="B+", structural=1))
    # must be a RECLAIM, ARMED, on the WEEKLY plan
    assert not mp.is_high_conviction(_row(trigger="retest"))
    assert not mp.is_high_conviction(_row(armed=False))
    assert not mp.is_high_conviction({"grade": "A+", "plans": {}})
    assert not mp.is_high_conviction({"grade": "A+"})


def test_it_matches_the_shipped_app_js_rule():
    """If app.js isHighConviction changes, this must change with it."""
    src = (mp.ROOT / "public" / "js" / "app.js").read_text(encoding="utf-8")
    body = src[src.index("function isHighConviction("):]
    body = body[:body.index("}")]
    assert 'entry_trigger !== "reclaim"' in body
    assert '"A+"' in body and '"A"' in body
    assert "structural_tps" in body and ">= 2" in body


# ── selection ────────────────────────────────────────────────────────────────

def test_pick_filters_sorts_by_score_and_caps():
    rows = [_row("LOW", score=1), _row("HI", score=99),
            _row("SKIP", trigger="retest", score=50)]        # not high-conviction
    got = mp.pick(rows, cap=10)
    assert [r["symbol"] for r in got] == ["HI", "LOW"], "score desc, retest dropped"
    assert len(mp.pick([_row(f"S{i}", score=i) for i in range(30)], cap=5)) == 5


# ── payload ──────────────────────────────────────────────────────────────────

def test_empty_morning_sends_a_none_message_not_silence():
    p = mp.build_payload({"asx": [], "nasdaq": []}, {"asx": 1.0, "nasdaq": 1.0}, "Mon 1 Jan")
    assert "No high-conviction plays" in p["content"]
    assert "embeds" not in p


def test_payload_lists_both_markets_with_side_grade_and_product_tag():
    picks = {"asx": [_row("JHX", direction="LONG", grade="A+")],
             "nasdaq": [_row("FUN", direction="SHORT", grade="A+", is_product=True)]}
    p = mp.build_payload(picks, {"asx": 1.0, "nasdaq": 1.0}, "Mon 1 Jan")
    assert "2 plays across ASX + NASDAQ" in p["content"]
    titles = {e["title"].split(" ")[0]: e for e in p["embeds"]}
    assert titles["ASX"]["description"].startswith("▲ **JHX** LONG · A+")
    fund = titles["NASDAQ"]["description"]
    assert fund.startswith("▼ **FUN** SHORT")           # down triangle for a short
    assert "FUND/REIT" in fund                                # product tagged, not hidden


def test_a_stale_scan_is_flagged_in_the_title():
    picks = {"asx": [_row("AAA")]}
    fresh = mp.build_payload(picks, {"asx": 2.0}, "Mon 1 Jan")
    stale = mp.build_payload(picks, {"asx": 48.0}, "Mon 1 Jan")
    assert "old" not in fresh["embeds"][0]["title"]
    assert "old" in stale["embeds"][0]["title"]


# ── the hour gate ────────────────────────────────────────────────────────────

def test_only_the_target_hour_sends_unless_forced():
    seven = dt.datetime(2026, 9, 9, 7, 3)
    eight = dt.datetime(2026, 9, 9, 8, 3)
    assert mp.should_send_now(seven, 7, force=False)
    assert not mp.should_send_now(eight, 7, force=False)
    assert mp.should_send_now(eight, 7, force=True)          # manual run always sends


# ── posting ──────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_post_sends_json_with_a_named_ua_and_returns_status():
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["ua"] = req.headers.get("User-agent") or req.get_header("User-agent")
        seen["ct"] = req.get_header("Content-type")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["url"] = req.full_url
        return _Resp(204)

    status = mp.post("https://discord.test/wh", {"content": "hi"},
                     "vivek5-morning/1.0", urlopen=fake_urlopen)
    assert status == 204
    assert seen["ua"] == "vivek5-morning/1.0"        # Discord 403s the default UA
    assert seen["ct"] == "application/json"
    assert seen["body"] == {"content": "hi"}


# ── main() end to end ────────────────────────────────────────────────────────

def _fixtures(tmp_path):
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    (d / "asx_vivek.json").write_text(json.dumps(
        {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
         "results": [_row("JHX"), _row("SKIP", trigger="retest")]}))
    (d / "nasdaq_vivek.json").write_text(json.dumps(
        {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
         "results": [_row("HLIT")]}))
    return d


def test_main_missing_webhook_warns_and_exits_zero_without_posting(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(config.MORNING_PLAYS_WEBHOOK_ENV, raising=False)
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(a) or 204)
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path))])
    assert rc == 0 and not called, "no webhook = green setup gap, nothing sent"
    assert "::warning::" in capsys.readouterr().out


def test_main_delivers_with_a_cleaned_webhook(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV,
                       "﻿https://discord.test/wh \n")       # BOM + trailing ws
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: seen.update(url=url, payload=payload) or 204)
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path))])
    assert rc == 0
    assert seen["url"] == "https://discord.test/wh", "clean_secret trims the BOM + whitespace"
    total = "2 plays" in seen["payload"]["content"]          # JHX + HLIT, SKIP dropped
    assert total


def test_main_returns_1_when_the_post_fails_loudly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")

    def boom(*a, **k):
        raise OSError("connection reset")
    monkeypatch.setattr(mp, "post", boom)
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

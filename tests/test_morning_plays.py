"""Morning Discord high-conviction digest (scripts/morning_plays.py).

Owner spec (2026-09-08): LONG plays only, no SHORTs, no FUNDS/REITs, clean
text `SYMBOL -> label`. Default = high-conviction longs; an opt-in widens to
every long A+. 2026-09-09: added CRYPTO as a third market and a 7-day de-dup
so a ticker shared once is not re-sent inside the window.

Pins the definition (identical to app.js isHighConviction), the filter, the
label, the message shape/chunking, the de-dup memory, and the exit codes.
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
    msgs = mp.build_messages({"asx": [], "nasdaq": [], "crypto": []},
                             {"asx": 1.0, "nasdaq": 1.0, "crypto": 1.0}, "Mon 1 Jan")
    assert len(msgs) == 1 and "No high-conviction" in msgs[0]


def test_all_suppressed_reads_differently_from_no_plays():
    # empty picks, but there WERE qualifying names (all sent inside the window)
    msgs = mp.build_messages({"asx": [], "nasdaq": [], "crypto": []},
                             {"asx": 1.0, "nasdaq": 1.0, "crypto": 1.0},
                             "Mon 1 Jan", had_qualifying=True)
    assert len(msgs) == 1
    assert "No new plays" in msgs[0] and "already shared" in msgs[0]


def test_the_message_is_clean_symbol_arrow_label_grouped_by_market():
    picks = {"asx": [_row("JHX", grade="A+")],
             "nasdaq": [_row("CRWV", grade="A")],
             "crypto": [_row("LINK", grade="A+")]}
    msgs = mp.build_messages(picks, {"asx": 1.0, "nasdaq": 1.0, "crypto": 1.0},
                             "Mon 1 Jan")
    text = "\n".join(msgs)
    assert "**ASX plays**" in text and "**NASDAQ plays**" in text
    assert "**CRYPTO plays**" in text
    assert "JHX → A+ High conviction" in text
    assert "CRWV → High conviction" in text
    assert "LINK → A+ High conviction" in text
    # clean: none of the old entry/stop/RR clutter, no company names, no arrows
    assert "entry" not in text and "stop" not in text and "R:R" not in text
    assert "▲" not in text and "▼" not in text and "Ltd" not in text


def test_a_market_with_no_plays_still_shows_a_header():
    msgs = mp.build_messages({"asx": [_row("JHX")], "nasdaq": [], "crypto": []},
                             {"asx": 1.0, "nasdaq": 1.0, "crypto": 1.0}, "Mon 1 Jan")
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


# ── the de-dup memory ────────────────────────────────────────────────────────

def test_seen_file_roundtrips(tmp_path):
    p = tmp_path / "nested" / "seen.json"                # parent made on save
    mp.save_seen(p, {"asx:JHX": "2026-09-09", "crypto:LINK": "2026-09-06"})
    assert mp.load_seen(p) == {"asx:JHX": "2026-09-09", "crypto:LINK": "2026-09-06"}


def test_load_seen_is_empty_on_a_missing_or_corrupt_file(tmp_path):
    assert mp.load_seen(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert mp.load_seen(bad) == {}


def test_filter_unseen_skips_a_ticker_sent_inside_the_window():
    today = dt.date(2026, 9, 9)
    sent = {"asx:RECENT": (today - dt.timedelta(days=3)).isoformat(),   # inside 7d
            "asx:OLD": (today - dt.timedelta(days=8)).isoformat()}      # outside 7d
    picks = {"asx": [_row("RECENT"), _row("OLD"), _row("FRESH")]}
    out = mp.filter_unseen(picks, sent, today, window=7)
    assert [r["symbol"] for r in out["asx"]] == ["OLD", "FRESH"], \
        "sent 3 days ago is suppressed; 8 days ago and never-sent pass"


def test_filter_unseen_is_market_scoped():
    today = dt.date(2026, 9, 9)
    sent = {"asx:LINK": today.isoformat()}               # an ASX LINK, not the coin
    picks = {"asx": [_row("LINK")], "crypto": [_row("LINK")]}
    out = mp.filter_unseen(picks, sent, today, window=7)
    assert out["asx"] == [] and [r["symbol"] for r in out["crypto"]] == ["LINK"]


def test_a_zero_window_disables_dedup_entirely():
    today = dt.date(2026, 9, 9)
    sent = {"asx:JHX": today.isoformat()}
    picks = {"asx": [_row("JHX")]}
    out = mp.filter_unseen(picks, sent, today, window=0)
    assert [r["symbol"] for r in out["asx"]] == ["JHX"]


def test_record_sent_stamps_today_and_prunes_the_expired():
    today = dt.date(2026, 9, 9)
    sent = {"asx:GONE": (today - dt.timedelta(days=20)).isoformat()}   # will prune
    delivered = {"asx": [_row("JHX")], "crypto": [_row("LINK")]}
    out = mp.record_sent(sent, delivered, today, window=7)
    assert out["asx:JHX"] == today.isoformat()
    assert out["crypto:LINK"] == today.isoformat()
    assert "asx:GONE" not in out, "a stamp past the window can no longer suppress"


# ── the slot gate ────────────────────────────────────────────────────────────

def test_slot_markets_picks_the_live_slot_or_noops(monkeypatch):
    monkeypatch.setattr(config, "MORNING_PLAYS_SCHEDULE",
                        {16: ("asx",), 6: ("nasdaq", "crypto")})
    monkeypatch.setattr(config, "MORNING_PLAYS_MARKETS", ("asx", "nasdaq", "crypto"))
    afternoon = dt.datetime(2026, 9, 9, 16, 33)
    morning = dt.datetime(2026, 9, 9, 6, 33)
    off = dt.datetime(2026, 9, 9, 17, 33)                 # a DST superset off-cron
    # scheduled: only the live slot's markets, else None
    assert mp.slot_markets(afternoon, force=False) == ("asx",)
    assert mp.slot_markets(morning, force=False) == ("nasdaq", "crypto")
    assert mp.slot_markets(off, force=False) is None      # off-crons no-op
    # --force sends the whole union, at any hour
    assert mp.slot_markets(off, force=True) == ("asx", "nasdaq", "crypto")


def test_every_dst_offcron_hour_is_a_noop():
    # the four superset crons land on Melbourne hours 5/6/7 and 15/16/17;
    # only 6 and 16 are slots, so both off-crons of each pair must no-op.
    for off_hour in (5, 7, 15, 17):
        when = dt.datetime(2026, 9, 9, off_hour, 30)
        assert mp.slot_markets(when, force=False) is None, off_hour


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
    (d / "crypto_vivek.json").write_text(json.dumps({"generated_at": now, "results": [
        _row("LINK", grade="A+")]}))
    return d


def _seen(tmp_path):
    """A per-test seen-file so main() never touches the real repo .cache."""
    return str(tmp_path / "seen.json")


# a UTC clock at a slot's :30 -- tests pin TZ to UTC so the hour maps directly.
ASX_SLOT = dt.datetime(2026, 9, 9, 16, 30, tzinfo=dt.timezone.utc)      # ASX
US_SLOT = dt.datetime(2026, 9, 9, 6, 30, tzinfo=dt.timezone.utc)        # NASDAQ+crypto


def _utc_tz(monkeypatch):
    monkeypatch.setattr(config, "MORNING_PLAYS_TZ", "UTC")


def test_main_missing_webhook_warns_and_exits_zero_without_posting(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(config.MORNING_PLAYS_WEBHOOK_ENV, raising=False)
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(a) or 204)
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path)),
                  "--seen-file", _seen(tmp_path)])
    assert rc == 0 and not called
    assert "::warning::" in capsys.readouterr().out


def test_main_delivers_with_a_cleaned_webhook_and_only_longs(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV,
                       "﻿https://discord.test/wh \n")       # BOM + trailing ws
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: seen.update(url=url, body=payload) or 204)
    # --force sends the whole union, so every market's names appear
    rc = mp.main(["--force", "--data-dir", str(_fixtures(tmp_path)),
                  "--seen-file", _seen(tmp_path)])
    assert rc == 0
    assert seen["url"] == "https://discord.test/wh", "clean_secret trims BOM + ws"
    content = seen["body"]["content"]
    assert "JHX" in content and "HLIT" in content and "LINK" in content
    assert "SHORTY" not in content and "FUNDY" not in content, "no shorts, no funds"


def test_a_scheduled_run_sends_only_the_live_slots_market(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    # the ASX slot posts JHX (ASX) and NOT HLIT/LINK (the US slot's markets)
    assert mp.main(["--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", _seen(tmp_path)], now=ASX_SLOT) == 0
    assert posts and "JHX" in posts[0]
    assert "HLIT" not in posts[0] and "LINK" not in posts[0]


def test_a_scheduled_run_off_slot_posts_nothing(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(1) or 204)
    off = dt.datetime(2026, 9, 9, 11, 30, tzinfo=dt.timezone.utc)   # no slot at 11
    assert mp.main(["--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", _seen(tmp_path)], now=off) == 0
    assert not called, "an off-slot cron is a silent no-op"


def test_main_records_delivered_tickers_and_suppresses_them_next_run(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    data_dir = str(_fixtures(tmp_path))
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)

    # the US slot delivers HLIT + LINK and records both (market-scoped keys)
    assert mp.main(["--data-dir", data_dir, "--seen-file", seen_path], now=US_SLOT) == 0
    assert posts and "HLIT" in posts[0] and "LINK" in posts[0]
    recorded = mp.load_seen(seen_path)
    assert recorded.get("nasdaq:HLIT") and recorded.get("crypto:LINK")

    # Second US slot the same day: both were just sent -> the "no new" message.
    posts.clear()
    assert mp.main(["--data-dir", data_dir, "--seen-file", seen_path], now=US_SLOT) == 0
    assert len(posts) == 1 and "No new plays" in posts[0]


def test_a_force_test_never_touches_the_real_dedup_window(tmp_path, monkeypatch):
    # a --force send must not record, so it can't suppress a real scheduled send
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda url, payload, ua, **k: 204)
    assert mp.main(["--force", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", seen_path]) == 0
    assert mp.load_seen(seen_path) == {}, "a forced test records nothing"


def test_main_does_not_record_when_the_post_fails(tmp_path, monkeypatch, capsys):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("reset")))
    rc = mp.main(["--data-dir", str(_fixtures(tmp_path)),
                  "--seen-file", seen_path], now=US_SLOT)
    assert rc == 1 and "::error::" in capsys.readouterr().out
    assert mp.load_seen(seen_path) == {}, "a failed send buries nothing"


def test_main_returns_1_on_a_non_2xx_status(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda *a, **k: 500)
    assert mp.main(["--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", seen_path], now=US_SLOT) == 1
    assert mp.load_seen(seen_path) == {}, "a rejected send buries nothing"


def test_a_dry_run_never_posts_and_records_nothing(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(1) or 204)
    assert mp.main(["--dry-run", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", seen_path], now=US_SLOT) == 0
    assert not called
    assert mp.load_seen(seen_path) == {}, "a dry run buries nothing"

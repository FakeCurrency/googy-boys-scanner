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
import pathlib
from zoneinfo import ZoneInfo

import pytest

from scripts import morning_plays as mp
from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]

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

def test_state_file_roundtrips_sent_and_slots(tmp_path):
    p = tmp_path / "nested" / "seen.json"                # parent made on save
    mp.save_state(p, {"sent": {"asx:JHX": "2026-09-09"}, "slots": {"asx": "2026-09-09"}})
    got = mp.load_state(p)
    assert got["sent"] == {"asx:JHX": "2026-09-09"}
    assert got["slots"] == {"asx": "2026-09-09"}


def test_load_state_is_empty_on_a_missing_or_corrupt_file(tmp_path):
    assert mp.load_state(tmp_path / "nope.json") == {"sent": {}, "slots": {}}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert mp.load_state(bad) == {"sent": {}, "slots": {}}


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


# ── the delay-proof slot gate (slot_due) ─────────────────────────────────────

def _melb(h, m=30):
    return dt.datetime(2026, 9, 9, h, m)                  # a naive Melbourne wall-clock


def test_slot_due_sends_at_or_past_target_however_late():
    # ASX target 16:30. Before it -> skip; at it -> due; HOURS late -> STILL due.
    assert mp.slot_due("asx", _melb(15), {}) == (False, "before")
    assert mp.slot_due("asx", _melb(16), {}) == (True, "due")
    assert mp.slot_due("asx", _melb(21), {})[0] is True, "a 5h-late cron must still send"
    # US target 06:30.
    assert mp.slot_due("us", _melb(5), {}) == (False, "before")
    assert mp.slot_due("us", _melb(7), {})[0] is True, "a 1h-late US cron still sends"


def test_slot_due_marks_once_per_day_so_the_second_dst_cron_cannot_double():
    marks = {"asx": dt.date(2026, 9, 9).isoformat()}
    assert mp.slot_due("asx", _melb(16), marks) == (False, "done")
    assert mp.slot_due("asx", _melb(17), marks) == (False, "done")   # the other DST cron
    # yesterday's marker does not block today
    assert mp.slot_due("asx", _melb(16), {"asx": "2026-09-08"})[0] is True


def test_slot_markets_is_the_legacy_local_fallback(monkeypatch):
    # kept only for a bare `python morning_plays.py` on a laptop.
    monkeypatch.setattr(config, "MORNING_PLAYS_SCHEDULE",
                        {16: ("asx",), 6: ("nasdaq", "crypto")})
    monkeypatch.setattr(config, "MORNING_PLAYS_MARKETS", ("asx", "nasdaq", "crypto"))
    assert mp.slot_markets(dt.datetime(2026, 9, 9, 16, 33), force=False) == ("asx",)
    assert mp.slot_markets(dt.datetime(2026, 9, 9, 11, 0), force=False) is None
    assert mp.slot_markets(dt.datetime(2026, 9, 9, 11, 0), force=True) == \
        ("asx", "nasdaq", "crypto")


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


def test_a_scheduled_slot_sends_only_its_own_markets(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    # --slot asx posts JHX (ASX) and NOT HLIT/LINK (the US slot's markets)
    assert mp.main(["--slot", "asx", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", _seen(tmp_path)], now=ASX_SLOT) == 0
    assert posts and "JHX" in posts[0]
    assert "HLIT" not in posts[0] and "LINK" not in posts[0]


def test_a_slot_delivers_even_when_the_cron_is_hours_late(tmp_path, monkeypatch):
    # THE 2026-09-09 REGRESSION: GitHub delivered the crons 2-5h late and the old
    # hour-exact gate no-op'd them all. A late run must still deliver its slot.
    _utc_tz(monkeypatch)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    late = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)   # US target 06:30, 5.5h late
    assert mp.main(["--slot", "us", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", _seen(tmp_path)], now=late) == 0
    assert posts and "HLIT" in posts[0] and "LINK" in posts[0], "a late cron must still send"


def test_a_slot_before_its_target_posts_nothing(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(1) or 204)
    early = dt.datetime(2026, 9, 9, 5, 0, tzinfo=dt.timezone.utc)   # before US 06:30 target
    assert mp.main(["--slot", "us", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", _seen(tmp_path)], now=early) == 0
    assert not called, "the wrong-DST early cron is a silent no-op"


def test_the_per_day_marker_makes_the_second_dst_cron_a_silent_noop(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path, data_dir = _seen(tmp_path), str(_fixtures(tmp_path))
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    # first US cron of the day delivers and marks the slot done + records tickers
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path],
                   now=US_SLOT) == 0
    assert posts and "HLIT" in posts[0] and "LINK" in posts[0]
    state = mp.load_state(seen_path)
    assert state["slots"].get("us") == "2026-09-09"
    assert state["sent"].get("nasdaq:HLIT") and state["sent"].get("crypto:LINK")
    # the OTHER DST cron fires an hour later, same day -> hard no-op, NOT a "no new" post
    posts.clear()
    later = dt.datetime(2026, 9, 9, 7, 30, tzinfo=dt.timezone.utc)
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path],
                   now=later) == 0
    assert not posts, "the marker suppresses the second cron with no message at all"


def test_tickers_stay_suppressed_on_the_next_days_slot(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path, data_dir = _seen(tmp_path), str(_fixtures(tmp_path))
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path],
                   now=US_SLOT) == 0
    assert "HLIT" in posts[0]
    # next day's US slot (marker is yesterday, so due) -> same names still inside
    # the 7-day window -> "no new plays", never a duplicate ticker for the reader
    posts.clear()
    tomorrow = dt.datetime(2026, 9, 10, 6, 30, tzinfo=dt.timezone.utc)
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path],
                   now=tomorrow) == 0
    assert len(posts) == 1 and "No new plays" in posts[0]


def test_a_force_test_never_touches_the_real_state(tmp_path, monkeypatch):
    # a --force send must not record tickers OR mark a slot done
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda url, payload, ua, **k: 204)
    assert mp.main(["--force", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", seen_path]) == 0
    assert mp.load_state(seen_path) == {"sent": {}, "slots": {}}, "a forced test records nothing"


def test_main_does_not_record_when_the_post_fails(tmp_path, monkeypatch, capsys):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("reset")))
    rc = mp.main(["--slot", "us", "--data-dir", str(_fixtures(tmp_path)),
                  "--seen-file", seen_path], now=US_SLOT)
    assert rc == 1 and "::error::" in capsys.readouterr().out
    state = mp.load_state(seen_path)
    assert state == {"sent": {}, "slots": {}}, "a failed send buries nothing and marks nothing"


def test_main_returns_1_on_a_non_2xx_status(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    monkeypatch.setattr(mp, "post", lambda *a, **k: 500)
    assert mp.main(["--slot", "us", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", seen_path], now=US_SLOT) == 1
    assert mp.load_state(seen_path)["slots"] == {}, "a rejected send marks no slot done"


def test_a_dry_run_never_posts_and_records_nothing(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    called = []
    monkeypatch.setattr(mp, "post", lambda *a, **k: called.append(1) or 204)
    assert mp.main(["--slot", "us", "--dry-run", "--data-dir", str(_fixtures(tmp_path)),
                    "--seen-file", seen_path], now=US_SLOT) == 0
    assert not called
    assert mp.load_state(seen_path) == {"sent": {}, "slots": {}}, "a dry run buries nothing"


# ── the post-close data gate (2026-09-11) ───────────────────────────────────
# On-time was not enough: the first on-time 06:35 US digest read a 1:43pm New
# York MID-SESSION scan and missed MDLZ/ASO/SWKS, which only set up in the last
# hours of trade. A slot now waits for a scan GENERATED after the session close.

NY = dt.timezone(dt.timedelta(hours=-4))          # EDT, the offset the real payload carried


def test_latest_close_is_the_most_recent_weekday_close():
    gate = config.MORNING_PLAYS_SLOT_GATE["us"]
    ny = ZoneInfo(gate["tz"])
    # Thursday 16:35 NY (after the bell) -> Thursday's close
    c = mp.latest_close(gate, dt.datetime(2026, 9, 10, 20, 35, tzinfo=dt.timezone.utc))
    assert (c.astimezone(ny).strftime("%a %H:%M")) == "Thu 16:05"
    # Friday 08:00 NY (before the bell) -> Thursday's close
    c = mp.latest_close(gate, dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.timezone.utc))
    assert c.astimezone(ny).strftime("%a %d %H:%M") == "Thu 10 16:05"
    # Sunday and Monday-before-the-bell both walk back to FRIDAY's close
    for when in (dt.datetime(2026, 9, 13, 12, 0, tzinfo=dt.timezone.utc),
                 dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.timezone.utc)):
        c = mp.latest_close(gate, when)
        assert c.astimezone(ny).strftime("%a %d") == "Fri 11"


def test_the_real_2026_09_10_scans_mid_session_fails_post_close_passes():
    """The actual stamps from the incident: what the 06:35 run read vs what
    landed at 07:06 Melbourne."""
    at_0635 = dt.datetime(2026, 9, 10, 20, 35, tzinfo=dt.timezone.utc)
    ok, why = mp.scan_is_post_close("us", "2026-09-10T13:43:20-04:00", at_0635)
    assert ok is False and "predates" in why
    at_0715 = dt.datetime(2026, 9, 10, 21, 15, tzinfo=dt.timezone.utc)
    ok, why = mp.scan_is_post_close("us", "2026-09-10T17:01:14-04:00", at_0715)
    assert ok is True and "past" in why


def test_the_asx_gate_refuses_a_scan_inside_the_closing_auction():
    """ASX's closing auction prints ~16:10-16:12; a 16:09 scan has no close.
    Both stamps are real ones from the 2026-09-08 / 2026-09-07 sessions."""
    now = dt.datetime(2026, 9, 8, 7, 0, tzinfo=dt.timezone.utc)          # 17:00 AEST Tue
    assert mp.scan_is_post_close("asx", "2026-09-08T16:09:58+10:00", now)[0] is False
    assert mp.scan_is_post_close("asx", "2026-09-08T17:54:01+10:00", now)[0] is True
    now = dt.datetime(2026, 9, 7, 7, 0, tzinfo=dt.timezone.utc)
    assert mp.scan_is_post_close("asx", "2026-09-07T16:14:13+10:00", now)[0] is True


def test_the_us_gate_accepts_the_winter_21_07_scan_or_the_digest_never_sends():
    """Under EST scan.yml's LAST NASDAQ cron (21:07 UTC) is 16:07 New York, and it
    is the only post-close scan of the day. The gate must let it through."""
    now = dt.datetime(2026, 12, 10, 21, 45, tzinfo=dt.timezone.utc)
    assert mp.scan_is_post_close("us", "2026-12-10T16:07:30-05:00", now)[0] is True
    assert mp.scan_is_post_close("us", "2026-12-10T15:07:30-05:00", now)[0] is False
    assert config.MORNING_PLAYS_SLOT_GATE["us"]["hour"] == 16
    assert config.MORNING_PLAYS_SLOT_GATE["us"]["minute"] <= 7, \
        "a gate later than 16:07 NY refuses every winter session's only post-close scan"


def test_a_missing_or_unreadable_stamp_fails_closed():
    now = dt.datetime(2026, 9, 10, 21, 15, tzinfo=dt.timezone.utc)
    assert mp.scan_is_post_close("us", None, now)[0] is False
    assert mp.scan_is_post_close("us", "yesterday-ish", now)[0] is False
    assert mp.scan_is_post_close("nonexistent-slot", None, now) == (True, "ungated")


def _fixtures_stamped(tmp_path, nasdaq_generated_at):
    d = tmp_path / "public" / "data"
    if not d.exists():
        _fixtures(tmp_path)
    (d / "nasdaq_vivek.json").write_text(json.dumps({
        "generated_at": nasdaq_generated_at, "results": [_row("MDLZ", grade="A+")]}))
    return d


def test_the_us_slot_waits_for_a_post_close_scan_and_marks_nothing(tmp_path, monkeypatch):
    """The incident replayed end to end: on time, mid-session data -> silent
    no-op with NO marker; the next attempt after the post-close scan sends."""
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    at_0635 = dt.datetime(2026, 9, 10, 20, 35, tzinfo=dt.timezone.utc)   # past the 06:30 floor
    data_dir = str(_fixtures_stamped(tmp_path, "2026-09-10T13:43:20-04:00"))
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path],
                   now=at_0635) == 0
    assert not posts, "a mid-session scan must not be sent as the morning list"
    assert mp.load_state(seen_path)["slots"].get("us") is None, "nothing marked -> retried"
    # the next attempt in the ladder finds the post-close scan
    data_dir = str(_fixtures_stamped(tmp_path, "2026-09-10T17:01:14-04:00"))
    at_0715 = dt.datetime(2026, 9, 10, 21, 15, tzinfo=dt.timezone.utc)
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path],
                   now=at_0715) == 0
    assert posts and "MDLZ" in posts[0]
    assert mp.load_state(seen_path)["slots"].get("us") == "2026-09-10"


def test_force_and_dry_run_ignore_the_gate(tmp_path, monkeypatch):
    _utc_tz(monkeypatch)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    data_dir = str(_fixtures_stamped(tmp_path, "2026-09-10T13:43:20-04:00"))
    at_0635 = dt.datetime(2026, 9, 10, 20, 35, tzinfo=dt.timezone.utc)
    assert mp.main(["--force", "--data-dir", data_dir, "--seen-file", _seen(tmp_path)],
                   now=at_0635) == 0
    assert posts and "MDLZ" in posts[0], "--force is a manual test and sends what is there"


def test_the_workflow_crons_fire_after_the_close_scans_and_each_maps_to_a_slot():
    """morning_plays.yml's crons are GitHub's late backstop behind the cron-job.org
    ladder; every one must be AFTER scan.yml's close-scan cron for its market
    (ASX 06:37 UTC, NASDAQ 21:07 UTC) and must map to a slot in the run block."""
    import re
    wf = (ROOT / ".github" / "workflows" / "morning_plays.yml").read_text()
    crons = re.findall(r'- cron: "([^"]+)"', wf)
    assert len(crons) == 4
    for c in crons:
        minute, hour = c.split()[:2]
        h = int(hour)
        assert f'"{c}"' in wf.split("case \"$SCHEDULE\" in")[1], f"{c} is not mapped to a slot"
        assert h in (7, 8, 21, 22), c
        if h in (7, 8):
            assert f'"{c}"' in wf.split('ARGS="--slot asx"')[0].split("case")[-1]
        else:
            assert f'"{c}"' in wf.split('ARGS="--slot us"')[0].split("case")[-1]
    assert '"30 5 * * *"' not in wf and '"30 19 * * *"' not in wf, \
        "the pre-close wall-clock crons must not come back"


def test_redeliver_skips_only_the_per_day_marker_and_still_records(tmp_path, monkeypatch):
    """2026-09-11: the 06:35 run marked the US slot done off mid-session data; the
    owner wanted the three post-close names sent the same day. --redeliver ignores
    the marker ONLY -- dedup, the data gate and state recording all still apply."""
    _utc_tz(monkeypatch)
    seen_path = _seen(tmp_path)
    monkeypatch.setenv(config.MORNING_PLAYS_WEBHOOK_ENV, "https://discord.test/wh")
    posts = []
    monkeypatch.setattr(mp, "post",
                        lambda url, payload, ua, **k: posts.append(payload["content"]) or 204)
    data_dir = str(_fixtures_stamped(tmp_path, "2026-09-10T17:01:14-04:00"))
    at = dt.datetime(2026, 9, 10, 21, 15, tzinfo=dt.timezone.utc)
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path], now=at) == 0
    assert len(posts) == 1 and "MDLZ" in posts[0]
    # same day, plain re-run: marker no-ops it
    assert mp.main(["--slot", "us", "--data-dir", data_dir, "--seen-file", seen_path], now=at) == 0
    assert len(posts) == 1
    # a new name lands in the scan; --redeliver sends it, dedup holds MDLZ back
    (pathlib.Path(data_dir) / "nasdaq_vivek.json").write_text(json.dumps({
        "generated_at": "2026-09-10T17:01:14-04:00",
        "results": [_row("MDLZ", grade="A+"), _row("ASO", grade="A")]}))
    assert mp.main(["--slot", "us", "--redeliver", "--data-dir", data_dir,
                    "--seen-file", seen_path], now=at) == 0
    assert len(posts) == 2 and "ASO" in posts[1] and "MDLZ" not in posts[1]
    assert mp.load_state(seen_path)["sent"].get("nasdaq:ASO"), "redelivered names are recorded"
    wf = (ROOT / ".github" / "workflows" / "morning_plays.yml").read_text()
    assert 'REDELIVER: ${{ github.event.inputs.redeliver }}' in wf
    assert '--redeliver' in wf

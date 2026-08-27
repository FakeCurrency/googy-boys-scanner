"""Review flags — the owner's take/skip call, surfaced but never taken for him.

Owner's instruction, 2026-07-28, immediately after declining to resize the seven
wide-stop legacy positions: "Disregard the daily stop for the positions that
have already been taken. Flag this in the future so i can verify whether claude
or I should take the position or not."

Two halves, and this file exists for the second. The first half is a decision
already made and recorded in CLAUDE.md: the open book keeps full size. The second
half is a REQUIREMENT — from now on, a plan whose 1R loss is a big share of the
daily loss guard has to arrive with a mark on it, so the owner can choose to take
it himself instead of letting the bot take it.

THE THING THESE TESTS PROTECT is that a flag stays an annotation. It runs after
every rule has said take, it adds a key, it returns. The moment a flag can
suppress a trade it has become a rule change, and rule changes are the owner's.
test_a_flagged_plan_is_still_taken_because_a_flag_is_not_a_gate pins exactly
that, and it is the one test in here that must never be "fixed" by making it
agree with a future gate.
"""

import pytest

from scanner import config
from scanner.broker import vivek_bot as vb

pytestmark = pytest.mark.risk


def _plan(entry=100.0, stop=96.0, **kw):
    p = {"armed": True, "entry_trigger": "reclaim",
         "entry": entry, "stop": stop,
         "tp1": entry * 1.06, "tp2": entry * 1.12, "tp3": entry * 1.20,
         "rr": 3.0, "scale": [0.25, 0.50, 0.15]}
    p.update(kw)
    return p


def _row(entry=100.0, stop=96.0, symbol="TEST"):
    return {"symbol": symbol, "name": f"{symbol} Ltd", "sector": "Software",
            "dir": "LONG", "grade": "A+", "entry_types": ["reclaim"],
            "price": entry, "plans": {"1W": _plan(entry, stop)}}


def _ticket(entry=100.0, stop=96.0, market="asx"):
    out = vb.plan_trade(_row(entry, stop), config.VIVEK_BOT_ACCOUNT_EQUITY, market)
    assert out["take"] is True, out.get("reason")
    return out["plan"]


# ── the limit the flag measures against ──────────────────────────────────────

def test_the_daily_limit_is_equity_times_the_guard_pct():
    assert vb.daily_loss_limit() == pytest.approx(
        config.VIVEK_BOT_ACCOUNT_EQUITY * config.VIVEK_BOT_MAX_DAILY_LOSS_PCT / 100.0)
    # The live number, spelled out, because every note the owner reads quotes it.
    assert vb.daily_loss_limit() == pytest.approx(4_500.0)


@pytest.mark.parametrize("equity,pct", [(0, 3.0), (150_000, 0), (0, 0), (-1, 3.0)])
def test_a_missing_or_zero_guard_yields_no_limit_and_never_divides_by_it(
        monkeypatch, equity, pct):
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", equity)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", pct)
    assert vb.daily_loss_limit() == 0.0
    # and the flag path must not blow up on it
    assert vb.review_flags({"risk_usd": 999.0, "entry": 100.0, "stop": 76.0}) == []


# ── what fires and what does not ─────────────────────────────────────────────

def test_an_ordinary_plan_is_not_flagged():
    # 4% stop on $5,000 = $200 risk = 4.4% of the $4,500 guard. This is the
    # common case and it has to stay quiet, or the flag means nothing.
    t = _ticket(entry=100.0, stop=96.0)
    assert t["risk_usd"] == pytest.approx(200.0)
    assert t["review"] == []


def test_a_wide_stop_plan_is_flagged():
    # 24% stop — still inside the 25% hard gate, so the bot takes it — but that
    # is $1,200 of a $4,500 day in one name.
    t = _ticket(entry=100.0, stop=76.0)
    assert t["risk_usd"] == pytest.approx(1_200.0)
    assert [f["code"] for f in t["review"]] == ["heavy_risk"]
    f = t["review"][0]
    assert f["share_pct"] == pytest.approx(26.7, abs=0.1)
    assert f["stop_pct"] == pytest.approx(24.0, abs=0.1)
    assert f["limit_usd"] == pytest.approx(4_500.0)


def test_the_threshold_is_inclusive_at_the_boundary():
    # 13.5% stop = $675 = exactly 15.0% of the guard. ">=" not ">", so it fires.
    t = _ticket(entry=100.0, stop=86.5)
    assert t["risk_usd"] == pytest.approx(675.0)
    assert t["review"][0]["share_pct"] == pytest.approx(15.0)
    # a hair under does not
    assert _ticket(entry=100.0, stop=86.6)["review"] == []


def test_a_short_is_measured_on_stop_distance_not_direction():
    # Stop ABOVE entry. |entry - stop| is the risk either way; a short must not
    # slip through with a negative share.
    flags = vb.review_flags({"risk_usd": 1_200.0, "entry": 100.0, "stop": 124.0})
    assert flags and flags[0]["stop_pct"] == pytest.approx(24.0)
    assert flags[0]["share_pct"] > 0


def test_setting_the_threshold_to_zero_turns_flagging_off(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", 0)
    assert _ticket(entry=100.0, stop=76.0)["review"] == []


# ── the guarantee: a flag is not a gate ──────────────────────────────────────

def test_a_flagged_plan_is_still_taken_because_a_flag_is_not_a_gate():
    # THE point of this file. The owner decides take-or-skip; the flag only
    # tells him there is something to decide. If this test ever needs changing
    # to match the code, the code has taken a decision that was not its own.
    out = vb.plan_trade(_row(entry=100.0, stop=76.0),
                        config.VIVEK_BOT_ACCOUNT_EQUITY, "asx")
    assert out["take"] is True
    assert out["plan"] is not None
    assert out["plan"]["review"], "expected this one to be flagged"
    assert out["code"] == "OK"
    # and it is sized exactly as an unflagged one would be — no quiet trimming
    assert out["plan"]["notional"] == pytest.approx(config.VIVEK_BOT_POSITION_NOTIONAL)


def test_flagging_changes_nothing_else_on_the_ticket():
    flagged = _ticket(entry=100.0, stop=76.0)
    assert flagged["review"]
    # Every sizing field is what size_position produced, untouched.
    sized = vb.size_position(config.VIVEK_BOT_ACCOUNT_EQUITY, 100.0, 76.0,
                             None, vb._leverage_for("asx"))
    for k in ("units", "notional", "risk_usd", "risk_pct", "leverage", "sizing_mode"):
        assert flagged[k] == sized[k], k


def test_review_flags_does_not_mutate_the_ticket_it_is_given():
    t = {"risk_usd": 1_200.0, "entry": 100.0, "stop": 76.0}
    before = dict(t)
    vb.review_flags(t)
    assert t == before


def test_every_ticket_carries_the_key_even_when_clean():
    # The front end and the alert path both read plan["review"]; an absent key
    # would make "no flags" and "old build" indistinguishable at the reader.
    assert _ticket(entry=100.0, stop=96.0)["review"] == []
    assert "review" in _ticket(entry=100.0, stop=96.0)


# ── why the threshold is where it is ─────────────────────────────────────────

def test_the_threshold_sits_below_the_ceiling_the_stop_gate_implies():
    # MAX_STOP_PCT caps any NEW position's risk at 25% x $5,000 = $1,250, which
    # is 27.8% of the $4,500 guard. A threshold at or above that could never
    # fire on a plan the bot would actually take — the flag would be dead code
    # and nobody would notice. This is the test that notices.
    ceiling = (config.VIVEK_BOT_MAX_STOP_PCT / 100.0
               * config.VIVEK_BOT_POSITION_NOTIONAL) / vb.daily_loss_limit() * 100.0
    assert ceiling == pytest.approx(27.8, abs=0.1)
    assert 0 < config.VIVEK_BOT_REVIEW_DAILY_LOSS_PCT < ceiling


def test_the_note_reads_as_english_and_carries_the_numbers():
    f = _ticket(entry=100.0, stop=76.0)["review"][0]
    assert "1,200" in f["note"] and "4,500" in f["note"]
    assert "27%" in f["note"] and "24% stop" in f["note"]
    f["note"].encode("cp1252")   # the note reaches logs and Discord


# ── delivery: the flag has to arrive somewhere the owner looks ───────────────
#
# A flag computed on a ticket and then dropped is not a flag. The ticket lives
# for the length of one decide() call; if the mark does not survive onto the
# book row and out through a push, it exists only in a log line inside a
# finished Actions run, which is not a place a decision gets made. These cover
# the two hops between "computed" and "read".


def _opened(symbol="MDB", entry=100.0, stop=76.0, risk=1_200.0, flagged=True):
    """A book row shaped like the ones _ticket_to_position produces."""
    return {"symbol": symbol, "direction": "long", "entry": entry, "stop": stop,
            "risk_usd": risk, "market": "asx",
            "review": ([{"code": "heavy_risk", "share_pct": round(risk / 4500 * 100, 1),
                         "stop_pct": 24.0, "risk_usd": risk, "limit_usd": 4500.0,
                         "note": f"a 1R loss here is ${risk:,.0f} - "
                                 f"{risk / 4500 * 100:.0f}% of the $4,500 daily "
                                 f"loss guard, on a 24% stop"}] if flagged else [])}


def test_the_flag_rides_down_onto_the_book_row():
    from scanner.broker import vivek_run as vr
    out = vb.plan_trade(_row(entry=100.0, stop=76.0),
                        config.VIVEK_BOT_ACCOUNT_EQUITY, "asx")
    pos = vr._ticket_to_position(out, 100.0, "asx", "2026-07-28")
    assert pos is not None, "the fill guard rejected a same-price fill"
    assert [f["code"] for f in pos["review"]] == ["heavy_risk"]
    # and a clean plan lands an EMPTY list, not a missing key -- "checked and
    # clean" and "written before flags existed" must stay distinguishable.
    clean = vb.plan_trade(_row(entry=100.0, stop=96.0),
                          config.VIVEK_BOT_ACCOUNT_EQUITY, "asx")
    assert vr._ticket_to_position(clean, 100.0, "asx", "2026-07-28")["review"] == []


def test_the_book_row_flag_is_a_copy_not_the_tickets_own_list():
    from scanner.broker import vivek_run as vr
    out = vb.plan_trade(_row(entry=100.0, stop=76.0),
                        config.VIVEK_BOT_ACCOUNT_EQUITY, "asx")
    pos = vr._ticket_to_position(out, 100.0, "asx", "2026-07-28")
    pos["review"].append({"code": "scribble"})
    assert len(out["plan"]["review"]) == 1, "book row aliases the ticket's list"


def test_only_flagged_opens_are_pushed():
    from scanner.broker import vivek_run as vr
    sent = []
    n = vr._notify_reviews("asx", [_opened("MDB"), _opened("BHP", flagged=False)],
                           send=lambda *a: sent.append(a))
    assert n == ["MDB"]
    assert len(sent) == 1 and "MDB" in sent[0][2] and "BHP" not in sent[0][2]


def test_a_run_with_nothing_flagged_is_silent():
    from scanner.broker import vivek_run as vr
    sent = []
    assert vr._notify_reviews("asx", [_opened("BHP", flagged=False)],
                              send=lambda *a: sent.append(a)) == []
    assert vr._notify_reviews("asx", [], send=lambda *a: sent.append(a)) == []
    assert sent == []


def test_one_message_per_run_carrying_the_combined_risk():
    # THE number this exists for. Three flagged opens at 27% each is 80% of the
    # day committed in one run, and nobody is summing that by hand across three
    # separate notifications.
    from scanner.broker import vivek_run as vr
    sent = []
    vr._notify_reviews("asx", [_opened("MDB"), _opened("AXON"), _opened("GLBE")],
                       send=lambda *a: sent.append(a))
    assert len(sent) == 1, "one message per run, not one per position"
    body = sent[0][2]
    assert "MDB" in body and "AXON" in body and "GLBE" in body
    assert "80% of the $4,500 daily guard" in body


def test_a_single_flagged_open_does_not_get_a_combined_line():
    # Restating one position's own risk as "together they" reads as a bug.
    from scanner.broker import vivek_run as vr
    sent = []
    vr._notify_reviews("asx", [_opened("MDB")], send=lambda *a: sent.append(a))
    assert "Together" not in sent[0][2]


def test_the_message_says_the_trade_is_already_taken():
    # The owner's choice is not take-or-skip -- the bot has taken it under his
    # own rules. It is whose position it is. A message that reads like a
    # pre-trade approval request would be a lie about what the system does.
    from scanner.broker import vivek_run as vr
    sent = []
    vr._notify_reviews("asx", [_opened("MDB")], send=lambda *a: sent.append(a))
    body = sent[0][2].lower()
    assert "taken" in body and "stay taken" in body
    assert "close" in body and "yourself" in body


def test_the_push_can_be_turned_off_without_losing_the_flag(monkeypatch):
    from scanner.broker import vivek_run as vr
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_PUSH", False)
    sent = []
    assert vr._notify_reviews("asx", [_opened("MDB")],
                              send=lambda *a: sent.append(a)) == []
    assert sent == []


def test_a_failing_channel_never_breaks_the_run():
    # This runs after the book has been saved. An exception escaping here would
    # abort the scan AFTER the positions are on disk -- the alert is the least
    # important thing in the function and must behave like it.
    from scanner.broker import vivek_run as vr

    def boom(*_a):
        raise RuntimeError("discord down")

    assert vr._notify_reviews("asx", [_opened("MDB")], send=boom) == []


def test_the_pushed_event_type_is_routed_and_not_rate_limited():
    # NOTICE is channel-less since 2026-08-27, and a limit here could only ever drop the second
    # market's flagged open in a sequential run.
    from scanner.broker import alert_router as ar
    assert config.ALERT_SEVERITY["trade_review"] == "NOTICE"
    assert config.ALERT_CHANNELS["NOTICE"] == []  # no push channel since the 2026-08-27 Discord removal
    assert config.ALERT_RATE_LIMITS["trade_review"] == 0
    assert ar.get_channels("trade_review") == []  # channel-less until the replacement lands


def test_the_message_is_cp1252_safe():
    from scanner.broker import vivek_run as vr
    sent = []
    vr._notify_reviews("asx", [_opened("MDB"), _opened("AXON")],
                       send=lambda *a: sent.append(a))
    for part in sent[0]:
        str(part).encode("cp1252")

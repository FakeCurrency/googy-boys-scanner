"""MOMENTUM publisher -- the artefact, the gates, and the write-set.

The engine is proved in `test_momentum_screen.py`. This covers everything
around it: what gets screened at all, what the published file looks like, and
-- the property the whole lens rests on -- that a blocked market keeps its last
good file instead of being overwritten with an empty list.

No network anywhere. `screen_market` takes `frames` and `rows` injected, so the
only part not exercised here is the download itself, which is the only part
that cannot be.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from scanner.momentum import config as C
from scanner.momentum import gates as G
from scanner.momentum import run as R

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def frame(close, *, vol=1e6, n=None):
    """A frame whose LAST BAR IS TODAY.

    Anchoring to a fixed past date made every fixture three years stale, and
    the age gate correctly rejected all eight symbols -- the gate working and
    the fixture wrong. Ending at today exercises the age gate for real instead
    of stubbing it out; the dedicated staleness test below patches the age
    explicitly, which is the one place that behaviour is the subject.
    """
    c = np.asarray(close, dtype=float)
    idx = pd.bdate_range(end=pd.Timestamp.now("UTC").tz_localize(None).normalize(),
                         periods=c.size)
    prev = np.concatenate([[c[0]], c[:-1]])
    v = np.full(c.size, vol, dtype=float) if np.isscalar(vol) else np.asarray(vol, float)
    return pd.DataFrame({"Open": prev, "High": np.maximum(c, prev) * 1.004,
                         "Low": np.minimum(c, prev) * 0.996, "Close": c,
                         "Volume": v}, index=idx)


def walk(seed, n=600, s0=50.0):
    r = np.random.default_rng(seed)
    return s0 * np.exp(np.cumsum(r.normal(0, 0.025, n)))


@pytest.fixture
def market_fixture():
    """A small ASX-shaped universe with one of every interesting kind."""
    rows = [
        {"symbol": "AAA", "name": "Alpha Mining Limited", "sector": "Materials", "yf": "AAA.AX"},
        {"symbol": "BBB", "name": "Beta Group Ltd", "sector": "Financials", "yf": "BBB.AX"},
        {"symbol": "CCC", "name": "Gamma Industries", "sector": "Industrials", "yf": "CCC.AX"},
        {"symbol": "ETFX", "name": "Vanguard Australian Shares ETF", "sector": "", "yf": "ETFX.AX"},
        {"symbol": "PENNY", "name": "Penny Co", "sector": "Materials", "yf": "PENNY.AX"},
        {"symbol": "THIN", "name": "Thin Co", "sector": "Materials", "yf": "THIN.AX"},
        {"symbol": "HALT", "name": "Halted Co", "sector": "Materials", "yf": "HALT.AX"},
        {"symbol": "SHORT", "name": "New Listing", "sector": "Materials", "yf": "SHORT.AX"},
    ]
    frames = {
        "AAA.AX": frame(walk(1)),
        "BBB.AX": frame(walk(2)),
        "CCC.AX": frame(walk(3)),
        "ETFX.AX": frame(walk(4)),
        "PENNY.AX": frame(walk(5) * 0.0002),                 # below the A$0.02 floor
        "THIN.AX": frame(walk(6), vol=10.0),                 # far below the turnover floor
        "HALT.AX": frame(np.concatenate([walk(7, 580), np.full(20, 40.0)]),
                         vol=np.concatenate([np.full(580, 1e6), np.zeros(20)])),
        "SHORT.AX": frame(walk(8, 40)),                      # under min_bars
    }
    return rows, frames


# ---------------------------------------------------------------------------
# the parity test that replaces an import
# ---------------------------------------------------------------------------

def test_the_fund_word_lists_still_match_the_bot_the_lens_may_not_import():
    """Spec 5.6 says reuse the owner's existing product classification rather
    than rewrite it. The PATTERNS are imported from `scanner/config.py`; the
    fund word lists cannot be, because they live in
    `scanner/broker/vivek_bot.py` and this lens must not be able to reach the
    bot at all.

    So they are copied, and this reads `vivek_bot.py` AS SOURCE -- parsing a
    file is not importing it -- and fails if the two ever diverge. That is the
    difference between a copy and a fork.
    """
    src = (ROOT / "scanner" / "broker" / "vivek_bot.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("_FUND_NAME_KEYWORDS", "_FUND_SECTOR_HINTS", "_NON_OPERATING_SECTORS"):
                found[name] = ast.literal_eval(node.value)
    assert set(found) == {"_FUND_NAME_KEYWORDS", "_FUND_SECTOR_HINTS", "_NON_OPERATING_SECTORS"}, (
        f"vivek_bot no longer declares all three lists: {sorted(found)}")
    assert set(found["_FUND_NAME_KEYWORDS"]) == set(C.FUND_NAME_KEYWORDS)
    assert set(found["_FUND_SECTOR_HINTS"]) == set(C.FUND_SECTOR_HINTS)
    assert set(found["_NON_OPERATING_SECTORS"]) == set(C.NON_OPERATING_SECTORS)


def test_the_patterns_are_imported_not_retyped():
    from scanner import config as shared
    assert C.PRODUCT_NAME_PATTERNS is shared.PRODUCT_NAME_PATTERNS


def test_the_matcher_uses_word_boundaries_unlike_the_bots():
    """The bot's matcher is SUBSTRING, where `"ETF" in "NETFLIX"` is True -- a
    real bug the front end fixed with `\\b` while the bot's ringfenced copy kept
    it. A display surface takes the corrected discipline."""
    assert G.is_product("NETFLIX INC") is False
    assert G.is_product("NETFLIX ETF") is True
    assert G.is_product("Vanguard Australian Shares ETF") is True
    assert G.is_product("Argo Investments Limited") is True, "an ASX LIC"
    assert G.is_product("Australian Ethical Investment Ltd") is False, (
        "SINGULAR 'Investment Ltd' is an operating fund MANAGER - the plural "
        "pattern is the false-positive fence")
    assert G.is_product("Anything", "Not Applicable") is True, "the ETF/LIC sector tag"
    assert G.is_product("Anything", "  REIT ") is True
    assert G.is_product(None, None) is False, "fails open"


# ---------------------------------------------------------------------------
# turnover
# ---------------------------------------------------------------------------

def test_crypto_turnover_is_volume_itself_not_close_times_volume():
    """Yahoo reports crypto Volume as USD dollar-volume ALREADY. Multiplying by
    the close dollars it twice -- for BTC that is a ~60,000x overstatement, in
    the direction that lets everything through the liquidity gate."""
    f = frame(np.full(40, 60000.0), vol=2e7)
    assert G.dollar_adv(f, "crypto") == pytest.approx(2e7)
    assert G.dollar_adv(f, "nasdaq") == pytest.approx(60000.0 * 2e7)
    meta = C.MARKETS_META
    assert meta["crypto"].volume_is_usd is True
    assert meta["asx"].volume_is_usd is False and meta["nasdaq"].volume_is_usd is False


def test_turnover_is_none_rather_than_zero_when_it_cannot_be_computed():
    """None and 0.0 are different facts: one is "unknown", the other is "no
    trade". A gate that treats them alike silently drops or admits a name."""
    assert G.dollar_adv(pd.DataFrame(), "asx") is None
    assert G.dollar_adv(frame(walk(1, 40)).drop(columns=["Volume"]), "asx") is None


# ---------------------------------------------------------------------------
# the gates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sym,expect", [
    ("AAA.AX", None),
    ("ETFX.AX", "non-operating"),
    ("PENNY.AX", "below the asx floor"),
    ("THIN.AX", "turnover"),
    ("HALT.AX", "no volume"),
    ("SHORT.AX", "short history"),
])
def test_each_gate_fires_on_the_shape_it_is_for(market_fixture, sym, expect):
    rows, frames = market_fixture
    meta = {r["yf"]: r for r in rows}[sym]
    reason = G.gate_frame(frames[sym], "asx", name=meta["name"], sector=meta["sector"])
    if expect is None:
        assert reason is None, f"{sym} should have been screened, got {reason!r}"
    else:
        assert reason and expect in reason, f"{sym}: got {reason!r}"


def test_a_gate_reason_is_a_string_a_human_can_act_on():
    """"1,146 skipped" with no breakdown is a number nobody can do anything
    with, so every gate returns WHY and the summary counts them by reason."""
    r = G.gate_frame(frame(walk(9, 40)), "asx")
    assert isinstance(r, str) and re.search(r"\d", r), r


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

def _row(**kw):
    base = {"ok": True, "passes": True, "symbol": "X", "rule_a": False, "rule_b": False,
            "rule_a_direction": "", "rule_b_direction": "", "rule_b_score": None,
            "rule_a_bars_ago": None, "rule_b_bars_ago": None, "dollar_adv_20": 0.0}
    base.update(kw)
    return base


def test_ranking_follows_the_six_levels_in_order():
    rows = [
        _row(symbol="PLAIN_B", rule_b=True, rule_b_direction="bull", rule_b_score=2, rule_b_bars_ago=0),
        _row(symbol="ALIGNED", rule_a=True, rule_b=True, rule_a_direction="bull",
             rule_b_direction="bull", rule_b_score=2, rule_a_bars_ago=1, rule_b_bars_ago=1),
        _row(symbol="A_ONLY", rule_a=True, rule_a_direction="bull", rule_a_bars_ago=0),
        _row(symbol="CONFLICT", rule_a=True, rule_b=True, rule_a_direction="bull",
             rule_b_direction="bear", rule_b_score=3, rule_a_bars_ago=0, rule_b_bars_ago=0),
    ]
    order = [r["symbol"] for r in G.rank_rows(rows)]
    assert order[0] == "ALIGNED", "confluence outranks everything"
    assert order.index("A_ONLY") < order.index("PLAIN_B"), (
        "divergence is the higher-information signal")
    assert order[-1] == "PLAIN_B"
    for i, r in enumerate(G.rank_rows(rows), 1):
        assert r["rank"] == i


def test_ranking_is_a_TOTAL_order_so_a_rerun_cannot_reorder():
    """Without the alphabetical final tie-break, two identical rows can swap on
    a re-run and diffing yesterday's list against today's stops working."""
    same = [_row(symbol=s, rule_a=True, rule_a_bars_ago=0) for s in ("DDD", "AAA", "CCC", "BBB")]
    assert [r["symbol"] for r in G.rank_rows(same)] == ["AAA", "BBB", "CCC", "DDD"]
    assert [r["symbol"] for r in G.rank_rows(list(reversed(same)))] == ["AAA", "BBB", "CCC", "DDD"]


def test_mode_C_keeps_only_rows_where_both_fired_and_agree():
    rows = [
        _row(symbol="AGREE", rule_a=True, rule_b=True, rule_a_direction="bull", rule_b_direction="bull"),
        _row(symbol="DISAGREE", rule_a=True, rule_b=True, rule_a_direction="bull", rule_b_direction="bear"),
        _row(symbol="A_ONLY", rule_a=True, rule_a_direction="bull"),
        _row(symbol="BOTH_DIRS", rule_a=True, rule_b=True, rule_a_direction="both", rule_b_direction="bull"),
    ]
    assert [r["symbol"] for r in G.select(rows, "C")] == ["AGREE"]
    assert len(G.select(rows, "B")) == 4
    # "both" can never satisfy C, because rule_b_direction is never "both".
    # Reproduced from the reference and flagged rather than smoothed over.
    assert G.directions_agree(rows[3]) is False


def test_select_drops_rows_that_did_not_pass_or_are_not_ok():
    rows = [_row(symbol="OK", rule_a=True), _row(symbol="NOPASS", passes=False),
            _row(symbol="NOTOK", ok=False, rule_a=True)]
    assert [r["symbol"] for r in G.select(rows, "A")] == ["OK"]


# ---------------------------------------------------------------------------
# the payload
# ---------------------------------------------------------------------------

def test_the_payload_carries_the_spec_envelope(market_fixture):
    rows, frames = market_fixture
    p = R.screen_market("asx", cfg=C.DEFAULTS.replace(mode="B", div_fresh_bars=60,
                                                      signal_fresh_bars=60),
                        frames=frames, rows=rows)
    assert p is not None
    for key in ("generated_at", "market", "timeframe", "last_closed_bar",
                "ruleset_version", "mode", "params", "summary", "results", "errors"):
        assert key in p, key
    assert p["market"] == "asx" and p["timeframe"] == "1d" and p["mode"] == "B"
    assert p["ruleset_version"] == C.RULESET_VERSION
    s = p["summary"]
    for key in ("universe", "scanned", "skipped_gates", "skipped_by_reason", "hits",
                "hits_rule_a", "hits_rule_b", "hits_both_aligned", "errors", "elapsed_s"):
        assert key in s, key
    assert s["universe"] == len(rows)
    assert s["skipped_gates"] == 5, "ETF, penny, thin, halted and short are gated"
    assert s["scanned"] == 3
    assert isinstance(p["errors"], list), "errors are first-class, not a log line"


def test_every_published_row_carries_the_evidence_to_open_a_chart(market_fixture):
    rows, frames = market_fixture
    p = R.screen_market("asx", cfg=C.DEFAULTS.replace(mode="B", div_fresh_bars=90,
                                                      signal_fresh_bars=90),
                        frames=frames, rows=rows)
    assert p["results"], "the fixture produced no hits - this test is vacuous"
    for r in p["results"]:
        for key in ("symbol", "name", "sector", "is_product", "dollar_adv_20",
                    "data_age_days", "close", "rsi", "atr", "fast", "mid", "slow",
                    "macd_hist", "slow_ready", "rule_a", "rule_b", "direction", "rank"):
            assert key in r, f"{r['symbol']} missing {key}"
        if r["rule_a"]:
            assert r["rule_a_pivot_bars_ago"] == r["rule_a_bars_ago"] + C.DEFAULTS.piv_right
            for key in ("rule_a_pivot_bar", "rule_a_rsi_at_pivot", "rule_a_price_at_pivot"):
                assert key in r, f"{r['symbol']} missing rule-A evidence {key}"
        if r["rule_b"]:
            for key in ("rule_b_score", "rule_b_label", "rule_b_bar"):
                assert key in r, f"{r['symbol']} missing rule-B evidence {key}"


def test_a_blocked_market_KEEPS_ITS_LAST_GOOD_FILE(tmp_path, monkeypatch):
    """The defect `spec_run.py` has and `run.py` does not.

    With no frames, publishing `"results": []` would make the page say "nothing
    set up today" when the truth is "we could not look" -- and it would do it
    by destroying the last honest answer.
    """
    monkeypatch.setattr(R, "OUT_DIR", tmp_path)
    good = {"market": "asx", "results": [{"symbol": "KEEP"}]}
    R.out_path("asx").write_text(json.dumps(good), encoding="utf-8")
    assert R.screen_market("asx", frames={}, rows=[]) is None
    assert json.loads(R.out_path("asx").read_text(encoding="utf-8")) == good


def test_the_exit_code_distinguishes_no_data_from_failure(tmp_path, monkeypatch):
    """The workflow has to tell three outcomes apart, and a bare 0/1 cannot:
    0 published, 3 deliberately nothing, 1 broken."""
    monkeypatch.setattr(R, "OUT_DIR", tmp_path)
    monkeypatch.setattr(R, "screen_market", lambda *a, **k: None)
    assert R.main(["--market", "asx"]) == 3

    def boom(*a, **k):
        raise RuntimeError("yahoo exploded")
    monkeypatch.setattr(R, "screen_market", boom)
    assert R.main(["--market", "asx"]) == 1


def test_publishing_round_trips_and_is_atomic(tmp_path, monkeypatch, market_fixture):
    """A bare NaN token makes the browser reject the WHOLE file -- one bad bar
    blanks the page -- so the published bytes must parse under a strict reader."""
    rows, frames = market_fixture
    monkeypatch.setattr(R, "OUT_DIR", tmp_path)
    p = R.screen_market("asx", cfg=C.DEFAULTS.replace(mode="B"), frames=frames, rows=rows)
    path = R.publish("asx", p)
    assert path == tmp_path / "asx.json"
    raw = path.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    back = json.loads(raw)                       # strict: rejects NaN/Infinity
    assert back["market"] == "asx"
    assert "\r\n" not in raw, "LF is pinned so a Windows run cannot rewrite every file"


def test_the_runner_writes_exactly_one_path_and_it_is_ours(tmp_path, monkeypatch, market_fixture):
    rows, frames = market_fixture
    monkeypatch.setattr(R, "OUT_DIR", tmp_path)
    p = R.screen_market("asx", cfg=C.DEFAULTS.replace(mode="B"), frames=frames, rows=rows)
    R.publish("asx", p)
    written = sorted(q.name for q in tmp_path.rglob("*") if q.is_file())
    assert written == ["asx.json"]


def test_a_symbol_that_throws_is_recorded_not_fatal(monkeypatch, market_fixture):
    """One bad symbol must not take down the market, and the error is PUBLISHED
    -- a name that throws every night is otherwise indistinguishable from one
    that never sets up."""
    rows, frames = market_fixture
    real = R.screen_symbol
    def flaky(df, cfg=None, symbol="", market=""):
        if symbol == "BBB":
            raise ValueError("planted")
        return real(df, cfg, symbol=symbol, market=market)
    monkeypatch.setattr(R, "screen_symbol", flaky)
    p = R.screen_market("asx", cfg=C.DEFAULTS.replace(mode="B"), frames=frames, rows=rows)
    assert p is not None, "one bad symbol must not lose the market"
    assert p["summary"]["errors"] >= 1
    assert any("BBB" in json.dumps(e) for e in p["errors"]), p["errors"]
    assert p["summary"]["scanned"] == 2, "the other two still screened"


def test_a_stale_frame_is_gated_and_counted(monkeypatch, market_fixture):
    """Computing a fresh signal off a two-week-old last bar is the single most
    dangerous silent failure a screener has."""
    rows, frames = market_fixture
    monkeypatch.setattr(R, "_frame_age_days", lambda f, m: 99)
    p = R.screen_market("asx", cfg=C.DEFAULTS.replace(mode="B"), frames=frames, rows=rows)
    assert p["summary"]["stale_frames"] == 3, "the three that passed the other gates"
    assert p["summary"]["scanned"] == 0
    assert any("stale" in k for k in p["summary"]["skipped_by_reason"])


def test_the_default_run_is_mode_A_and_a_one_bar_window(market_fixture):
    rows, frames = market_fixture
    p = R.screen_market("asx", frames=frames, rows=rows)
    assert p["mode"] == "A"
    assert p["params"]["div_fresh_bars"] == 1 and p["params"]["signal_fresh_bars"] == 1
    assert all(r["rule_a"] for r in p["results"]), "mode A passes on Rule A only"


def test_the_params_block_records_every_tunable_that_produced_the_file(market_fixture):
    """A published artefact must be traceable to the rules that made it."""
    rows, frames = market_fixture
    p = R.screen_market("asx", frames=frames, rows=rows)
    assert p["params"] == C.DEFAULTS.to_dict()
    assert p["params"]["ema_seed"] == "sma" and p["params"]["pivot_strict_left"] is True

"""IGNITION market cap (scanner/ignition/mcap.py) -- a DISPLAY field.

The contract the panel is built on: every published row carries mcap (float or
None), mcap_asof ("YYYY-MM-DD" or None) and mcap_src ("coingecko" | "yahoo" |
"cache" | "previous" | None); payload["summary"]["mcap"] == {"rows", "have"}.
No test here reaches the network or writes the shared cap cache.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import pathlib
from zoneinfo import ZoneInfo

import pytest

from scanner import config, marketcaps, output, universe
from scanner.ignition import mcap
from scanner.ignition import run as RUN

ROOT = pathlib.Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 30, 6, 0, tzinfo=UTC)
TODAY = NOW.date().isoformat()
KEYS = ["mcap", "mcap_asof", "mcap_src"]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ig = _load("_ig_suite_mcap", "test_ignition.py")
_asx = _load("_ig_asx_suite_mcap", "test_ignition_asx.py")
_fences = _load("_ig_fences_suite_mcap", "test_ignition_fences.py")


def _day(days_ago):
    return (NOW - dt.timedelta(days=days_ago)).date().isoformat()


def _prev(tmp_path, *rows):
    """This lens's previous published file, holding `rows`."""
    path = tmp_path / "asx.json"
    path.write_text(json.dumps({"results": list(rows)}), encoding="utf-8")
    return path


class Yahoo:
    """Stands in for marketcaps.fetch_caps: records each ask, answers from
    .table, or raises .raises."""

    def __init__(self, table=None, raises=None):
        self.table, self.raises, self.calls = dict(table or {}), raises, []

    def __call__(self, yf_syms):
        self.calls.append(list(yf_syms))
        if self.raises:
            raise self.raises
        return {y: self.table[y] for y in yf_syms if y in self.table}


@pytest.fixture
def yahoo(monkeypatch):
    """marketcaps.fetch_caps, stubbed: the one seam for Yahoo's cap quote."""
    y = Yahoo()
    monkeypatch.setattr(marketcaps, "fetch_caps", y)
    return y


@pytest.fixture
def shared_cache(monkeypatch):
    """The shared cap cache as a dict the test fills. Writing it fails the test."""
    cache = {}
    monkeypatch.setattr(marketcaps, "load_cache", lambda: cache)
    monkeypatch.setattr(marketcaps, "save_cache", lambda *a, **k: pytest.fail("cache written"))
    monkeypatch.setattr(marketcaps, "refresh", lambda *a, **k: pytest.fail("cache refreshed"))
    return cache


# ---------------------------------------------------------------------------
# crypto: CoinGecko's cap, universe row -> published row
# ---------------------------------------------------------------------------

def test_the_crypto_universe_carries_coingeckos_cap(monkeypatch):
    coins = [{"symbol": "btc", "name": "Bitcoin", "current_price": 65000.5,
              "market_cap": 1_280_000_000_000},
             {"symbol": "arb", "name": "Arbitrum", "current_price": 0.4, "market_cap": None},
             {"symbol": "qnt", "name": "Quant", "current_price": 71.0, "market_cap": 0},
             {"symbol": "sol", "name": "Solana", "current_price": 150.0}]
    monkeypatch.setattr(universe, "_http_get", lambda *a, **k: json.dumps(coins))
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    by = {i["symbol"]: i for i in universe._fetch_crypto("-USD", limit=10)}
    assert by["BTC"]["cg_mcap"] == 1.28e12 and isinstance(by["BTC"]["cg_mcap"], float)
    assert by["ARB"]["cg_mcap"] is None and by["QNT"]["cg_mcap"] is None
    assert by["SOL"]["cg_mcap"] is None
    assert by["BTC"]["cg_price"] == 65000.5        # the identity reference is untouched


def test_a_crypto_cap_flows_from_the_universe_row_to_the_published_row():
    frames, rows = _ig._fresh_frames()
    extra = {"IGN-USD": {"cg_mcap": 2.5e9},
             "RUN-USD": {"cg_mcap": 7.0e7, "cg_stale": True},   # outage-day snapshot
             "CLS-USD": {"cg_mcap": None}}
    for r in rows:
        r.update(extra.get(r["yf"], {}))
    now = dt.datetime.now(UTC)
    pl = RUN.screen_market("crypto", frames=frames, rows=rows, now=now)
    by = {r["symbol"]: [r[k] for k in KEYS] for r in pl["results"]}
    assert by == {"IGNX": [2.5e9, now.date().isoformat(), "coingecko"],
                  "RUNX": [7.0e7, None, "coingecko"],             # a snapshot has no date
                  "CLSX": [None, None, None], "COIX": [None, None, None]}
    assert pl["summary"]["mcap"] == {"rows": 4, "have": 2}


def test_crypto_reads_no_cache_and_asks_no_one(monkeypatch, tmp_path, yahoo):
    monkeypatch.setattr(marketcaps, "load_cache", lambda: pytest.fail("cache read on crypto"))
    assert mcap.known("crypto", _prev(tmp_path, {"symbol": "X", "yf": "X-USD"}), NOW) == {}
    assert yahoo.calls == []


# ---------------------------------------------------------------------------
# ASX: the newest of the shared cache and the previous file, topped up once
# ---------------------------------------------------------------------------

def test_the_asx_takes_the_newest_of_the_cache_and_the_previous_file(
        tmp_path, shared_cache, yahoo):
    shared_cache.update({
        "asx:CCH": {"mcap": 1.0e8, "ts": _day(1) + "T08:00:00+00:00"},   # newer than prev
        "asx:PRV": {"mcap": 2.0e8, "ts": _day(3) + "T08:00:00+00:00"},   # older than prev
        "asx:TIE": {"mcap": 3.0e8, "ts": _day(2) + "T08:00:00+00:00"},
        "nasdaq:CCH": {"mcap": 9.9e9, "ts": _day(0) + "T08:00:00+00:00"},  # another market
    })
    prev = _prev(tmp_path,
                 {"symbol": "CCH", "yf": "CCH.AX", "mcap": 1.5e8, "mcap_asof": _day(2)},
                 {"symbol": "PRV", "yf": "PRV.AX", "mcap": 2.5e8, "mcap_asof": _day(1)},
                 {"symbol": "TIE", "yf": "TIE.AX", "mcap": 3.5e8, "mcap_asof": _day(2)})
    caps = mcap.known("asx", prev, NOW)
    assert caps == {"CCH": {"mcap": 1.0e8, "asof": _day(1), "src": "cache"},
                    "PRV": {"mcap": 2.5e8, "asof": _day(1), "src": "previous"},
                    "TIE": {"mcap": 3.0e8, "asof": _day(2), "src": "cache"}}  # tie: cache
    assert yahoo.calls == []                            # every name is recent: no ask


def test_yahoo_is_asked_once_only_for_previous_names_with_a_missing_or_old_cap(
        tmp_path, shared_cache, yahoo):
    age = marketcaps.MAX_AGE_DAYS
    shared_cache.update({"asx:OLD": {"mcap": 1e8, "ts": _day(age + 5)},
                         "asx:GONE": {"mcap": 4e8, "ts": _day(age + 9)}})   # not in prev
    prev = _prev(tmp_path,
                 {"symbol": "EDGE", "yf": "EDGE.AX", "mcap": 5e6, "mcap_asof": _day(age)},
                 {"symbol": "AGED", "yf": "AGED.AX", "mcap": 6e6, "mcap_asof": _day(age + 1)},
                 {"symbol": "OLD", "yf": "OLD.AX"},
                 {"symbol": "NONE", "yf": "NONE.AX"})
    yahoo.table = {"OLD.AX": 2e8, "NONE.AX": 7e6}
    caps = mcap.known("asx", prev, NOW)
    assert yahoo.calls == [["AGED.AX", "NONE.AX", "OLD.AX"]]
    assert caps["OLD"] == {"mcap": 2e8, "asof": TODAY, "src": "yahoo"}
    assert caps["NONE"] == {"mcap": 7e6, "asof": TODAY, "src": "yahoo"}
    assert caps["AGED"] == {"mcap": 6e6, "asof": _day(age + 1), "src": "previous"}  # real date
    assert caps["EDGE"]["src"] == "previous" and caps["GONE"]["src"] == "cache"


def test_a_fetch_that_raises_keeps_what_is_already_known(tmp_path, shared_cache, yahoo, capsys):
    prev = _prev(tmp_path, {"symbol": "OLD", "yf": "OLD.AX", "mcap": 9e7, "mcap_asof": _day(10)})
    yahoo.raises = RuntimeError("Too Many Requests — 429")
    caps = mcap.known("asx", prev, NOW)
    assert caps == {"OLD": {"mcap": 9e7, "asof": _day(10), "src": "previous"}}
    out = capsys.readouterr().out
    assert "market caps incomplete (RuntimeError" in out and out.isascii()


def test_a_first_run_or_a_bad_previous_file_is_no_previous_file(tmp_path, shared_cache, yahoo):
    assert mcap.known("asx", tmp_path / "missing.json", NOW) == {}
    bad = tmp_path / "asx.json"
    for text in ("{not json", "[1, 2]"):
        bad.write_text(text, encoding="utf-8")
        assert mcap.known("asx", bad, NOW) == {}


def test_bad_values_become_none(tmp_path, shared_cache, yahoo):
    junk = [True, "7", float("nan"), float("inf"), 0, -1.0, None]
    results = [{"symbol": f"S{i}"} for i in range(len(junk))] + [{"symbol": "OK"}]
    caps = {f"S{i}": {"mcap": v, "asof": TODAY, "src": "cache"} for i, v in enumerate(junk)}
    caps["OK"] = {"mcap": 5, "asof": TODAY, "src": "cache"}
    assert mcap.stamp("asx", results, [], caps, TODAY) == {"rows": len(results), "have": 1}
    assert [r["mcap"] for r in results] == [None] * len(junk) + [5.0]
    assert all(r["mcap_asof"] is r["mcap_src"] is None for r in results[:-1])
    # ...and a cached or previous value without a usable date or value is skipped
    shared_cache.update({"asx:A": {"mcap": 5.0}, "asx:B": {"mcap": "x", "ts": TODAY}})
    prev = _prev(tmp_path, {"symbol": "C", "yf": "C.AX", "mcap": 5.0, "mcap_asof": "soon"},
                 {"symbol": "D", "yf": "D.AX", "mcap": False, "mcap_asof": TODAY})
    assert mcap.known("asx", prev, NOW) == {}


# ---------------------------------------------------------------------------
# the screen: where the hook sits, and what it must not do
# ---------------------------------------------------------------------------

def _stub_download(monkeypatch, market):
    """screen_market(market) down the DOWNLOAD path with every edge stubbed.
    `events` proves the Yahoo ask comes before the frame download; the
    previous file is whatever the test puts in `prev` (read path recorded).
    Symbols carry the market's own Yahoo suffix (".AX"; none on NASDAQ)."""
    sfx = config.MARKETS[market].suffix
    local = ZoneInfo(config.MARKETS[market].timezone)
    end = dt.datetime.now(UTC).astimezone(local).date() - dt.timedelta(days=1)
    df = _ig.redate(_asx.asx_frame().iloc[:_asx.T + 3], end)
    state = {"events": [], "read": [], "yahoo": Yahoo({"ZZZ" + sfx: 1.2e8}),
             "prev": [{"symbol": "ZZZ", "yf": "ZZZ" + sfx, "mcap": 9e7,
                       "mcap_asof": "2026-01-02"}]}
    rows = [{"symbol": "ZZZ", "name": "Zed Ltd", "yf": "ZZZ" + sfx},
            {"symbol": "NEW", "name": "New Ltd", "yf": "NEW" + sfx}]

    def download(market, period, limit):
        state["events"].append("download")
        return rows, {"ZZZ" + sfx: df.copy(), "NEW" + sfx: df.copy()}, {}

    def yahoo(yf_syms):
        state["events"].append("yahoo")
        return state["yahoo"](yf_syms)

    monkeypatch.setattr(RUN, "_download", download)
    monkeypatch.setattr(RUN, "regime_frame", lambda market, period: None)
    monkeypatch.setattr(RUN.sdata, "merge_with_cache", lambda key, fresh, t, **k: (dict(fresh), {}))
    monkeypatch.setattr(marketcaps, "fetch_caps", yahoo)
    monkeypatch.setattr(mcap, "_previous_rows",
                        lambda path: state["read"].append(path) or state["prev"])
    return state


@pytest.fixture
def asx_download(monkeypatch, shared_cache):
    return _stub_download(monkeypatch, "asx")


@pytest.fixture
def nasdaq_download(monkeypatch, shared_cache):
    return _stub_download(monkeypatch, "nasdaq")


def test_the_download_path_asks_yahoo_before_the_download(asx_download):
    pl = RUN.screen_market("asx")
    assert asx_download["events"] == ["yahoo", "download"]
    assert asx_download["yahoo"].calls == [["ZZZ.AX"]]              # NEW waits for the next run
    assert asx_download["read"] == [RUN.out_path("asx")]            # the lens's OWN file
    by = {r["symbol"]: [r[k] for k in KEYS] for r in pl["results"]}
    assert by == {"ZZZ": [1.2e8, dt.datetime.now(UTC).date().isoformat(), "yahoo"],
                  "NEW": [None, None, None]}
    assert pl["summary"]["mcap"] == {"rows": 2, "have": 1}


def test_a_fetch_that_raises_never_fails_the_run(asx_download):
    asx_download["yahoo"] = Yahoo(raises=RuntimeError("throttled"))
    pl = RUN.screen_market("asx")
    by = {r["symbol"]: [r[k] for k in KEYS] for r in pl["results"]}
    assert by == {"ZZZ": [9e7, "2026-01-02", "previous"], "NEW": [None, None, None]}


def test_the_injected_path_touches_no_cap_source(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the injected path touched a cap source")
    monkeypatch.setattr(mcap, "known", refuse)
    monkeypatch.setattr(marketcaps, "load_cache", refuse)
    monkeypatch.setattr(marketcaps, "fetch_caps", refuse)
    df = _asx.asx_frame().iloc[:_asx.T + 3]
    now = dt.datetime.combine(df.index[-1].date() + dt.timedelta(days=1), dt.time(0, 30),
                              tzinfo=UTC)
    pl = RUN.screen_market("asx", frames={"ZZZ.AX": df}, now=now,
                           rows=[{"symbol": "ZZZ", "name": "Zed", "yf": "ZZZ.AX"}])
    assert [pl["results"][0][k] for k in KEYS] == [None] * 3


def test_the_cap_moves_no_row_state_or_count(monkeypatch):
    """Same screen with and without the stamp: identical rows, order and
    summary; the three keys are the whole difference and sit last."""
    frames, rows = _ig._fresh_frames()
    rows[0]["cg_mcap"] = 2.5e9
    now = dt.datetime.now(UTC)
    with_caps = RUN.screen_market("crypto", frames=frames, rows=rows, now=now)
    monkeypatch.setattr(mcap, "stamp", lambda *a, **k: {})
    bare = RUN.screen_market("crypto", frames=frames, rows=rows, now=now)
    for a, b in zip(with_caps["results"], bare["results"], strict=True):
        assert list(a)[-3:] == KEYS and {k: a[k] for k in list(a)[:-3]} == b
    drop = ("mcap", "elapsed_s")
    assert {k: v for k, v in with_caps["summary"].items() if k not in drop} \
        == {k: v for k, v in bare["summary"].items() if k not in drop}


# ---------------------------------------------------------------------------
# the shared cache is read, never written
# ---------------------------------------------------------------------------

def test_the_lens_touches_only_the_read_only_surface_of_marketcaps():
    """Parsed, not grepped: save_cache / refresh / the cache paths are writers."""
    used = set()
    for p in sorted((ROOT / "scanner" / "ignition").glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == "marketcaps":
                used.add(node.attr)
    assert used == {"load_cache", "fetch_caps", "MAX_AGE_DAYS"}, used


def test_a_full_asx_cli_run_writes_exactly_its_two_paths(asx_download, monkeypatch):
    """The screen file, then its chart sidecar; published[0] is the screen."""
    published = []
    monkeypatch.setattr(output, "write_json", lambda path, payload, **kw:
                        published.append((pathlib.Path(path), payload)) or pathlib.Path(path))
    raw = _fences.record_writes(monkeypatch)
    assert RUN.main(["--market", "asx"]) == 0
    assert [p.relative_to(ROOT).as_posix() for p, _ in published] \
        == ["public/data/ignition/asx.json", "public/data/ignition/asx_charts.json"]
    assert published[1][1]["generated_at"] == published[0][1]["generated_at"]
    assert raw == []
    assert published[0][1]["summary"]["mcap"] == {"rows": 2, "have": 1}


# ---------------------------------------------------------------------------
# NASDAQ (2026-10-08): the same stock-market path, its own keys and file
# ---------------------------------------------------------------------------

def test_nasdaq_reads_only_its_own_cache_keys(tmp_path, shared_cache, yahoo):
    shared_cache.update({
        "nasdaq:CCH": {"mcap": 9.9e9, "ts": _day(1) + "T08:00:00+00:00"},
        "asx:CCH": {"mcap": 1.0e8, "ts": _day(0) + "T08:00:00+00:00"},   # another market
        "asx:ONLY": {"mcap": 2.0e8, "ts": _day(0) + "T08:00:00+00:00"},
    })
    caps = mcap.known("nasdaq", _prev(tmp_path, {"symbol": "CCH", "yf": "CCH"}), NOW)
    assert caps == {"CCH": {"mcap": 9.9e9, "asof": _day(1), "src": "cache"}}
    assert yahoo.calls == []


def test_the_nasdaq_download_path_asks_yahoo_first_with_bare_symbols(nasdaq_download):
    pl = RUN.screen_market("nasdaq")
    assert nasdaq_download["events"] == ["yahoo", "download"]
    assert nasdaq_download["yahoo"].calls == [["ZZZ"]]               # no suffix on NASDAQ
    assert nasdaq_download["read"] == [RUN.out_path("nasdaq")]       # its OWN file
    by = {r["symbol"]: [r[k] for k in KEYS] for r in pl["results"]}
    assert by == {"ZZZ": [1.2e8, dt.datetime.now(UTC).date().isoformat(), "yahoo"],
                  "NEW": [None, None, None]}


def test_a_full_nasdaq_cli_run_writes_exactly_its_two_paths(nasdaq_download, monkeypatch):
    published = []
    monkeypatch.setattr(output, "write_json", lambda path, payload, **kw:
                        published.append((pathlib.Path(path), payload)) or pathlib.Path(path))
    raw = _fences.record_writes(monkeypatch)
    assert RUN.main(["--market", "nasdaq"]) == 0
    assert [p.relative_to(ROOT).as_posix() for p, _ in published] \
        == ["public/data/ignition/nasdaq.json", "public/data/ignition/nasdaq_charts.json"]
    assert published[0][1]["market"] == published[1][1]["market"] == "nasdaq"
    assert raw == []

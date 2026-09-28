"""The crypto universe fetch pages CoinGecko at its 250-row cap (2026-09-28).

The bug this exists to keep dead: CRYPTO_UNIVERSE_SIZE went 100 -> 200 on
2026-09-20 and the one-page request asked for per_page=260. CoinGecko does not
reject that -- it silently serves its DEFAULT page of 100 rows. The universe
shrank from 101 names to 86 on the very next run, every crypto scan from then
on was a top ~100 wearing a "top 200" label, and nothing anywhere said so.
Found chasing the QNT move of 24-27 Sep 2026: the band being dropped (ranks
100-250) is where most coins of that shape live.

Every test here drives the SHIPPED _fetch_crypto with _http_get stubbed, so
the behaviour -- not a re-typed copy of it -- is what is pinned.
"""
import json
from urllib.parse import parse_qs, urlparse

import pytest

from scanner import config, universe


def _coins(start, n, stable_every=0):
    out = []
    for i in range(start, start + n):
        sym = f"C{i}"
        if stable_every and i % stable_every == 0:
            sym = f"S{i}USD"          # _is_stable: any <X>USD ticker is a peg
        out.append({"symbol": sym.lower(), "name": f"Coin {i}"})
    return out


class _Feed:
    """Stub CoinGecko: answers each page from a pre-built ranked list, and
    reproduces the real service's silent default when per_page > 250."""

    def __init__(self, ranked, fail_pages=()):
        self.ranked = ranked
        self.fail_pages = set(fail_pages)
        self.calls = []

    def __call__(self, url, timeout=30, headers=None, attempts=3):
        q = parse_qs(urlparse(url).query)
        page, per = int(q["page"][0]), int(q["per_page"][0])
        self.calls.append((page, per))
        if page in self.fail_pages:
            raise OSError("boom")
        if per > 250:                  # the real service's silent fallback
            per = 100
        lo = (page - 1) * per
        return json.dumps(self.ranked[lo:lo + per])


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(universe.time, "sleep", lambda s: None)


def test_no_request_ever_asks_for_more_than_the_cap(monkeypatch, no_sleep):
    feed = _Feed(_coins(1, 1200, stable_every=5))
    monkeypatch.setattr(universe, "_http_get", feed)
    universe._fetch_crypto("-USD", limit=400)
    assert feed.calls, "no request was made"
    assert all(per <= 250 for _, per in feed.calls), feed.calls


def test_the_top_200_really_is_200_tradeable_coins(monkeypatch, no_sleep):
    """The regression itself: with 1-in-6 rows a peg, 200 tradeable coins
    need ~240 rows. One capped page covers it; the old 260 request got 100."""
    feed = _Feed(_coins(1, 600, stable_every=6))
    monkeypatch.setattr(universe, "_http_get", feed)
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    items = universe._fetch_crypto("-USD", limit=200)
    assert len(items) == 200
    assert not any(universe._is_stable(i["symbol"]) for i in items)
    # rank order preserved: the first tradeable coin is rank 1
    assert items[0]["symbol"] == "C1" and items[0]["yf"] == "C1-USD"


def test_a_second_page_is_fetched_only_when_the_first_falls_short(monkeypatch, no_sleep):
    feed = _Feed(_coins(1, 600, stable_every=2))    # half are pegs
    monkeypatch.setattr(universe, "_http_get", feed)
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    items = universe._fetch_crypto("-USD", limit=200)
    assert len(items) == 200
    assert [p for p, _ in feed.calls] == [1, 2]

    feed2 = _Feed(_coins(1, 600))
    monkeypatch.setattr(universe, "_http_get", feed2)
    universe._fetch_crypto("-USD", limit=200)
    assert [p for p, _ in feed2.calls] == [1], "page 2 fetched though page 1 sufficed"


def test_a_short_page_is_the_last_page(monkeypatch, no_sleep):
    """CoinGecko ran out of coins: asking again would repeat nothing useful,
    and the page walk must never spin to the hard stop on a short list."""
    feed = _Feed(_coins(1, 120))
    monkeypatch.setattr(universe, "_http_get", feed)
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    items = universe._fetch_crypto("-USD", limit=200)
    assert len(items) == 120
    assert len(feed.calls) == 1


def test_the_page_walk_has_a_hard_stop(monkeypatch, no_sleep):
    feed = _Feed([{"symbol": f"s{i}usd", "name": "peg"} for i in range(5000)])
    monkeypatch.setattr(universe, "_http_get", feed)
    universe._fetch_crypto("-USD", limit=200)
    assert len(feed.calls) == universe.COINGECKO_MAX_PAGES


def test_page_one_failing_is_a_failed_fetch(monkeypatch, no_sleep):
    feed = _Feed(_coins(1, 600), fail_pages={1})
    monkeypatch.setattr(universe, "_http_get", feed)
    assert universe._fetch_crypto("-USD", limit=200) == []


def test_a_later_page_failing_keeps_the_earlier_pages(monkeypatch, no_sleep):
    feed = _Feed(_coins(1, 600, stable_every=2), fail_pages={2})
    monkeypatch.setattr(universe, "_http_get", feed)
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    items = universe._fetch_crypto("-USD", limit=200)
    assert len(items) == 125          # the 125 tradeable rows of page 1


def test_pinned_extras_still_ride_along(monkeypatch, no_sleep):
    feed = _Feed(_coins(1, 600))
    monkeypatch.setattr(universe, "_http_get", feed)
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", ["XMR", "C5"])
    items = universe._fetch_crypto("-USD", limit=10)
    syms = [i["symbol"] for i in items]
    assert syms[-1] == "XMR" and syms.count("C5") == 1


def test_the_url_builder_clamps(monkeypatch):
    assert "per_page=250" in universe.coingecko_url(1, per_page=260)
    assert "page=3" in universe.coingecko_url(3)

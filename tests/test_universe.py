"""Crypto universe filtering — pegged stablecoins must never be scanned/traded."""

from scanner.universe import _is_stable


def test_explicit_stablecoins_and_wrapped_tokens_are_skipped():
    for sym in ["USDT", "USDC", "DAI", "RLUSD", "WBTC", "STETH", "EURC"]:
        assert _is_stable(sym), sym


def test_any_usd_peg_is_skipped_even_if_not_listed():
    # the heuristic catches a newly-listed <X>USD dollar peg automatically
    for sym in ["FDUSD", "CRVUSD", "SOMENEWUSD", "rlusd"]:
        assert _is_stable(sym), sym


def test_real_trending_coins_are_kept():
    for sym in ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "PAXG"]:
        assert not _is_stable(sym), sym

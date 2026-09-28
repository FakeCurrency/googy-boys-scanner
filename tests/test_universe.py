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


# ── 2026-09-28: pegs the <X>USD rule could not see ─────────────────────────
# The pagination fix brought ranks ~100-250 back, and the first dry VIVEK
# crypto scan on exchange data graded EURCV (a euro stablecoin) A+ and U
# ("United Stables") A. The old 86-name cache already held USDF, USYC, USTB,
# EUTBL, EURSAFO and USDGO -- pegs and tokenised cash funds that were being
# scanned as if they could trend.

def test_non_dollar_fiat_pegs_and_tokenised_funds_are_skipped_by_ticker():
    for sym in ["EURCV", "EURR", "EURQ", "USDF", "USDGO", "USDM", "A7A5", "XSGD",
                "JAAA", "JTRSY", "OUSG", "USTB", "USYC", "EUTBL", "USR"]:
        assert _is_stable(sym), sym


def test_a_peg_is_skipped_by_its_NAME_when_the_ticker_gives_nothing_away():
    for sym, name in [("U", "United Stables"),
                      ("ZZZ", "Ondo US Dollar Yield"),
                      ("SAFO", "Spiko Amundi Overnight Swap Fund (EUR)"),
                      ("INV", "Invesco Short Duration US Government Securities Fund"),
                      ("GD", "Global Dollar"),
                      ("SE", "StablR Euro"),
                      ("TB", "Spiko EU T-Bills Money Market Fund"),
                      ("JH", "Janus Henderson Anemoy AAA CLO Fund"),
                      ("TR", "Some Treasury Token")]:
        assert _is_stable(sym, name), (sym, name)


def test_the_name_rule_keeps_coins_that_float():
    """The fence on the other side: gold tokens trend and are scanned on
    purpose; STABLE is a floating chain token whose name is one word short
    of a peg; the rest are real coins whose names sit near a peg word."""
    for sym, name in [("STABLE", "​​Stable"), ("PAXG", "PAX Gold"),
                      ("XAUT", "Tether Gold"), ("ONDO", "Ondo"), ("USUAL", "Usual"),
                      ("EUL", "Euler"), ("MAGIC", "Treasure"), ("SKY", "Sky"),
                      ("ENA", "Ethena"), ("QNT", "Quant"), ("BDX", "Beldex"),
                      ("WLFI", "World Liberty Financial"), ("BCAP", "Blockchain Capital")]:
        assert not _is_stable(sym, name), (sym, name)


def test_the_fetch_drops_a_peg_known_only_by_name(monkeypatch):
    import json
    from scanner import config, universe
    page = [{"symbol": "btc", "name": "Bitcoin", "current_price": 1.0},
            {"symbol": "u", "name": "United Stables", "current_price": 1.0},
            {"symbol": "eth", "name": "Ethereum", "current_price": 1.0}]
    monkeypatch.setattr(universe, "_http_get", lambda *a, **k: json.dumps(page))
    monkeypatch.setattr(config, "CRYPTO_EXTRA_SYMBOLS", [])
    assert [i["symbol"] for i in universe._fetch_crypto("-USD", limit=10)] == ["BTC", "ETH"]


def test_a_cached_universe_saved_under_the_old_rule_is_refiltered(monkeypatch, tmp_path):
    """CoinGecko down + a snapshot written before this rule must not bring
    the pegs back for the day."""
    import json
    from scanner import config, universe
    items = [{"symbol": f"C{i}", "name": f"Coin {i}", "yf": f"C{i}-USD"} for i in range(45)]
    items += [{"symbol": "EURCV", "name": "EUR CoinVertible", "yf": "EURCV-USD"},
              {"symbol": "U", "name": "United Stables", "yf": "U-USD"}]
    monkeypatch.setattr(universe, "UNIVERSE_CACHE_DIR", tmp_path)
    (tmp_path / "crypto.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    monkeypatch.setattr(universe, "_fetch_crypto", lambda suffix: [])
    got = [i["symbol"] for i in universe.load_universe("crypto")]
    assert len(got) == 45 and "EURCV" not in got and "U" not in got

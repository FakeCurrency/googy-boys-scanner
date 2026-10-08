"""2026-10-08 audit, cluster E -- #68: momentum's product gate applied the
STOCK fund words to CoinGecko coin names on every market, so "Trust Wallet"
(TWT, a real wallet/exchange token with a ~$225M cap in the crypto universe)
matched \\bTRUST\\b and was gated out of every crypto screen as a
'non-operating listing'. Spec 5.6 scopes the gate to ASX LICs/ETFs/trusts and
NASDAQ preferred/warrants/rights/notes; crypto pegs and cash funds are
universe._is_stable's job. Crypto now reads its own two words (FUND, ETF), so
a tokenised fund the peg list has not named (SAFO) is still caught.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from scanner.momentum import config as C
from scanner.momentum import gates as G
from scanner.momentum import run as R


@pytest.mark.parametrize("name, product", [
    ("Trust Wallet", False),                               # the audit's case
    ("TrustSwap", False),
    ("Spiko Amundi Overnight Swap Fund", True),            # SAFO: a tokenised fund
    ("SPDR S&P 500 ETF (Ondo Tokenized)", True),
    ("Bitcoin", False),
    ("Kinesis Gold", False),                               # metal tokens stay (owner)
])
def test_crypto_names_are_read_with_crypto_words(name, product):
    assert G.is_product(name, "", "crypto") is product


def test_the_stock_markets_keep_the_stock_lists():
    assert G.is_product("Trust Wallet", "", "asx") is True       # an ASX "... Trust" is a trust
    assert G.is_product("Argo Investments Limited", "", "asx") is True
    assert G.is_product("NETFLIX INC", "", "nasdaq") is False
    assert G.is_product("Anything", "Not Applicable", "asx") is True
    assert G.is_product("Trust Wallet") is True                  # no market = the stock rule


def _coin(n=400, usd_vol=2e7):
    end = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    idx = pd.date_range(end=pd.Timestamp(end), periods=n, freq="D")
    c = 0.5 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.03, n)))
    prev = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"Open": prev, "High": np.maximum(c, prev) * 1.01,
                         "Low": np.minimum(c, prev) * 0.99, "Close": c,
                         "Volume": np.full(n, usd_vol)}, index=idx)


def test_trust_wallet_is_screened_on_crypto_and_safo_is_still_gated():
    f = _coin()
    assert G.gate_frame(f, "crypto", name="Trust Wallet") is None
    assert G.gate_frame(f, "crypto", name="Spiko Amundi Overnight Swap Fund").startswith(
        "non-operating listing")
    rows = [{"yf": "TWT-USD", "symbol": "TWT", "name": "Trust Wallet", "sector": ""},
            {"yf": "SAFO-USD", "symbol": "SAFO", "name": "Spiko Amundi Overnight Swap Fund",
             "sector": ""}]
    p = R.screen_market("crypto", frames={"TWT-USD": f, "SAFO-USD": f.copy()}, rows=rows)
    assert p["summary"]["scanned"] == 1
    assert p["summary"]["skipped_by_reason"] == {"non-operating listing": 1}
    assert p["ruleset_version"] == C.RULESET_VERSION == "1.0.1"

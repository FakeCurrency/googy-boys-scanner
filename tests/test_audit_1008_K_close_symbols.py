"""/api/close accepts every symbol the crypto universe can admit (audit #48, 2026-10-08).

The two validators disagreed. ``universe._fetch_crypto`` keeps any CoinGecko
symbol for which Python's ``str.isalnum()`` is true -- CJK letters included,
and the live scan already prices one such coin -- while ``functions/api/close.js``
accepted only ASCII ``[A-Z0-9.-]`` and returned 400 for a WHOLE batch on the
first entry it refused. The day the bot held a non-ASCII coin, "Close all" and
the stalled strip could close nothing at all.

These tests drive the SHIPPED pieces from both sides: the real ``_fetch_crypto``
against a stubbed CoinGecko page, and the real ``SYMBOL_RE`` literal sliced out
of close.js and run by node (the regex is JavaScript with the ``u`` flag;
re-typing it in Python would test a copy, not the endpoint). The behavioural
JS half -- a batch carrying such a coin dispatches -- lives in
``test/api_guards.test.js``.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scanner import universe

ROOT = Path(__file__).resolve().parents[1]
CLOSE_JS = ROOT / "functions" / "api" / "close.js"
CJK_COIN = "币安人生"      # the coin the audit found in crypto_prices.json

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _symbol_re_literal() -> str:
    m = re.search(r"^const SYMBOL_RE = (/.+/[a-z]*);$", CLOSE_JS.read_text(encoding="utf-8"), re.M)
    assert m, "close.js no longer declares one shared SYMBOL_RE literal"
    return m.group(1)


def _rejected_by_close_js(symbols):
    """Symbols close.js's validator refuses, after the same trim/upper it applies."""
    js = (
        f"const r = {_symbol_re_literal()};"
        "let d = ''; process.stdin.on('data', (x) => (d += x)).on('end', () => {"
        "  const bad = JSON.parse(d).filter((s) => !r.test(String(s).trim().toUpperCase()));"
        "  process.stdout.write(JSON.stringify(bad));"
        "});"
    )
    out = subprocess.run([NODE, "-e", js], input=json.dumps(symbols), capture_output=True,
                         text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def test_both_close_shapes_use_the_one_shared_rule():
    src = CLOSE_JS.read_text(encoding="utf-8")
    assert src.count("SYMBOL_RE.test(") == 2, "the batch and single shapes must share one rule"
    assert "[A-Z0-9" not in src, "an ASCII-only symbol class came back"


def test_the_universe_admits_the_cjk_coin(monkeypatch):
    """The universe side of the contract, from the shipped fetch."""
    page = [{"symbol": CJK_COIN.lower(), "name": "Binance Life", "current_price": 0.48},
            {"symbol": "btc", "name": "Bitcoin", "current_price": 60000.0}]
    monkeypatch.setattr(universe, "_http_get", lambda *a, **k: json.dumps(page))
    monkeypatch.setattr(universe.time, "sleep", lambda s: None)
    syms = [r["symbol"] for r in universe._fetch_crypto("-USD", limit=2)]
    assert CJK_COIN in syms


@needs_node
def test_close_js_accepts_every_symbol_the_universe_can_admit(monkeypatch):
    # Every single character the universe's filter admits (after its own
    # strip().upper()), plus the real coin and the ordinary ticker shapes.
    admitted = []
    for cp in range(0x21, 0x30000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        u = chr(cp).strip().upper()
        if u and u.isalnum() and len(u) <= 15:
            admitted.append(u)
    admitted += [CJK_COIN, "BTC", "PEPE", "1INCH", "BRK-B", "BHP.AX"]
    bad = _rejected_by_close_js(admitted)
    assert bad == [], f"close.js refuses {len(bad)} symbol(s) the universe admits, e.g. {bad[:10]}"


@needs_node
def test_close_js_still_refuses_anything_that_is_not_a_letter_or_number():
    hostile = ["b;rm -rf", "A B", "$X", "X`id`", "币；", "币　安",
               "A‍B", "X́", "", "A" * 16, "../x", "a'b", 'a"b']
    assert sorted(_rejected_by_close_js(hostile)) == sorted(hostile)

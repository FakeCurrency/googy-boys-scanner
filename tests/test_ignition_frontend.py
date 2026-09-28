"""IGNITION deck pill -- the Python half of the front-end parity (2026-09-28).

The deck pill decides which markets it is shown on from a JS literal,
`IGNITION_MARKETS` in public/js/ignition.js. That literal is a hand-typed
mirror of `config.IGNITION_MARKETS`, and a mirror nobody checks drifts
(TOP100 #34 is what that looks like):

  * engine screens a market the literal does not name -> the owner never sees
    that market's ignitions, and nothing anywhere says so;
  * the literal names a market the engine does not screen -> the deck fetches
    a file that can never exist, on every visit to that market.

So the literal is PARSED out of the shipped file here and compared to config.
The same goes for the two data paths: the page must read exactly the files
`scanner.ignition.run` writes, or the pill silently never appears.

It lives in `tests/` because it reads the shipped files as source and executes
nothing; the behaviour is covered by test/ignition.test.js. New `tests/*.py`
need no registration -- pytest collects the directory.
"""

import json
import re
from pathlib import Path

from scanner import config

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
JS = PUB / "js" / "ignition.js"
APP = PUB / "js" / "app.js"
INDEX = PUB / "index.html"


def _js_markets():
    src = JS.read_text(encoding="utf-8")
    m = re.search(r"const\s+IGNITION_MARKETS\s*=\s*(\[[^\]]*\])\s*;", src)
    assert m, "public/js/ignition.js no longer declares `const IGNITION_MARKETS = [...]`"
    return json.loads(m.group(1).replace("'", '"'))


def test_the_js_market_list_is_config_IGNITION_MARKETS():
    assert _js_markets() == list(config.IGNITION_MARKETS), (
        "public/js/ignition.js IGNITION_MARKETS drifted from scanner/config.py "
        "IGNITION_MARKETS -- the deck pill would show on the wrong markets")


def test_the_market_list_is_declared_exactly_once_and_only_in_ignition_js():
    """One mirror, in one place. A second copy in app.js is a second thing to
    drift, and it would be the one nobody remembers to update."""
    src = JS.read_text(encoding="utf-8")
    assert len(re.findall(r"const\s+IGNITION_MARKETS\s*=", src)) == 1
    assert "IGNITION_MARKETS" not in APP.read_text(encoding="utf-8")


def test_the_page_reads_exactly_the_files_the_runner_writes():
    from scanner.ignition import run
    src = JS.read_text(encoding="utf-8")
    for market in config.IGNITION_MARKETS:
        for path in (run.out_path(market), run.backtest_path(market)):
            rel = path.relative_to(PUB).as_posix()          # data/ignition/<m>.json
            folder, name = rel.rsplit("/", 1)
            template = folder + "/" + name.replace(market, "${market}", 1)
            assert f"`{template}`" in src, (
                f"ignition.js does not fetch {rel} (expected the template `{template}`)")


def test_index_html_references_both_assets_with_a_version():
    html = INDEX.read_text(encoding="utf-8")
    assert re.search(r'<script src="js/ignition\.js\?v=\d+"></script>', html), \
        "index.html must load js/ignition.js with a ?v= cache-buster"
    assert re.search(r'<link rel="stylesheet" href="css/ignition\.css\?v=\d+" />', html), \
        "index.html must load css/ignition.css with a ?v= cache-buster"


def test_ignition_js_loads_before_app_js():
    """app.js reads window.Ignition when it renders the pill strip; loading the
    lens after the deck would make the first paint pill-less for no reason."""
    html = INDEX.read_text(encoding="utf-8")
    lens = html.find('src="js/ignition.js?v=')
    deck = html.find('src="js/app.js?v=')
    assert 0 < lens < deck


def test_the_panel_host_ships_hidden_inside_the_deck():
    html = INDEX.read_text(encoding="utf-8")
    deck = html[html.index('<section class="deck" id="deck">'):]
    deck = deck[:deck.index("</section>")]
    assert re.search(r'<div class="ig-panel" id="ignition-panel" hidden\b', deck), \
        "#ignition-panel must ship hidden, inside the deck, so an absent file shows nothing"


def test_the_deck_pill_says_it_is_report_only():
    """The count is not a trade signal. The pill title and the panel sub-line
    both say so in words; a lightning bolt on the deck says the opposite."""
    src = JS.read_text(encoding="utf-8")
    assert "report-only, not traded by the bot" in src
    assert re.search(r"Report-only \S+ not traded by the bot", src), \
        "the panel sub-line must say report-only / not traded"

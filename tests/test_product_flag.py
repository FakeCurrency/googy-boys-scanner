"""The `is_product` display flag (2026-08-19, Session C) — and THE FENCE.

The scanner now publishes `is_product` on every result row so the UI can dim,
mark and de-rank non-operating instruments the fund keyword list structurally
misses — measured on the live scans before writing: four ASX LICs graded A+
(AFI, BTI, HM1, RG8) and four NASDAQ preferred lines (STRF, STRD, STRC, MCHPP)
were dressing as operating-company opportunities on the deck.

Two properties carry the whole design, and both are pinned here:

1.  DISPLAY-ONLY. Nothing under scanner/broker/ may read the field or the
    patterns behind it. The bot's eligibility test is `_is_fund_or_reit` and it
    stays byte-untouched — widening or narrowing what the bot may take while
    w3-1 is mid-sample is a rule change by stealth, whatever the commit message
    says. The fence test greps the broker tree for the field name and the
    config constant and fails on the FIRST reference, in either direction:
    the flag may not reach the bot, and the bot's own names may not leak into
    the flag's config either.

2.  THE MATCHING IS THE FRONT END'S, NOT THE BOT'S. `_is_fund_or_reit` tests
    `kw in name`, and `"ETF" in "NETFLIX"` is True — the substring bug the deck
    fixed with word boundaries on 2026-08-13 while the bot's copy stayed as-is
    (ringfenced). The first draft of `_product_tag` delegated to `_fund_tag`
    and the NFLX case below went red: delegating would have re-dimmed Netflix
    and silently reverted the front-end fix. The flag borrows the bot's WORD
    LIST (imported, never re-typed) under the front end's `\\b` discipline.
"""
from __future__ import annotations

import pathlib
import re

from scanner import config
from scanner.scan import _product_tag

ROOT = pathlib.Path(__file__).resolve().parents[1]
BROKER = ROOT / "scanner" / "broker"


# ── what the flag catches, case by measured case ─────────────────────────────

def _row(name, sector=""):
    return {"name": name, "sector": sector}


def test_asx_lics_are_products_the_afi_class():
    # None of these names contain FUND/TRUST/ETF — the leak this flag closes.
    for name in (
        "Australian Foundation Investment Company Limited",
        "Bailador Technology Investments Limited",
        "Hearts and Minds Investments Limited",
        "Regal Asian Investments Limited",
        "Perpetual Equity Investment Company Limited",
    ):
        assert _product_tag(_row(name, "Financials")), name


def test_preferred_lines_are_products_including_depositary_preferreds():
    for name in (
        "Strategy Inc - 10.00% Series A Perpetual Strife Preferred Stock",
        "Strategy Inc - Variable Rate Series A Perpetual Stretch Preferred Stock",
        "Huntington Bancshares Incorporated - Depositary Shares 4.500% Series H "
        "Non-Cumulative Perpetual Preferred Stock",
        "Microchip Technology Incorporated - Depositary Shares Each Representing "
        "a 1/20th Interest in a Share of Series A Convertible Preferred Stock",
    ):
        assert _product_tag(_row(name)), name


def test_the_fund_classes_still_come_through_word_bounded():
    assert _product_tag(_row("BetaShares Australia 200 ETF", "Not Applic"))
    assert _product_tag(_row("Charter Hall Retail REIT", "Real Estate"))
    assert _product_tag(_row("Vanguard Australian Shares Index ETF"))


def test_adrs_are_operating_companies_not_products():
    """Bare "Depositary Shares" is DELIBERATELY not a pattern.

    Sanofi, JD.com and Ryanair trade as ADS/ADR lines and are real companies;
    the preferred patterns key on the word "Preferred", never on the wrapper.
    This is the test that keeps someone from "completing" the pattern list with
    the obvious-looking substring and flagging half the NASDAQ internationals.
    """
    for name in (
        "Sanofi - American Depositary Shares",
        "JD.com, Inc. - American Depositary Shares",
        "Ryanair Holdings plc - American Depositary Shares, each representing "
        "five Ordinary Shares",
    ):
        assert not _product_tag(_row(name)), name


def test_NETFLIX_is_not_a_product_because_matching_is_word_bounded():
    """The reason _product_tag does NOT delegate to the bot's matcher.

    `_is_fund_or_reit` tests `"ETF" in name` and N-ETF-LIX matches; the deck
    fixed this with word boundaries on 2026-08-13 while the bot's ringfenced
    copy kept the substring test. The first draft of this flag called
    _fund_tag() and THIS test caught the regression — delegating would have
    republished the NFLX bug as a server-side verdict the UI now trusts over
    its own fixed heuristic.
    """
    assert not _product_tag(_row("Netflix, Inc. - Common Stock"))


def test_operating_fund_MANAGERS_are_not_products():
    """The LIC pattern is plural-only, and this is why.

    "Australian Ethical Investment Ltd" manages funds; it IS an operating
    company. The LICs the owner named all read "InvestmentS Limited" (plural)
    or "Investment Company" — the singular-before-Limited form is the manager,
    not the vehicle. Known accepted borderline the plural form does catch:
    NGI (Navigator Global Investments), an asset-management holding co.
    """
    assert not _product_tag(_row("Australian Ethical Investment Ltd", "Financials"))
    assert not _product_tag(_row("Pinnacle Investment Management Group Limited",
                                 "Financials"))


def test_a_broken_row_is_False_never_a_throw():
    assert _product_tag({}) is False
    assert _product_tag({"name": None, "sector": None}) is False


def test_the_flag_is_a_superset_of_the_word_bounded_fund_classes():
    """Everything the sector hints / no-sector rule catches stays caught."""
    assert _product_tag(_row("Anything At All", "REIT"))
    assert _product_tag(_row("Anything At All", "not applicable"))


# ── publication ──────────────────────────────────────────────────────────────

def test_scan_publishes_is_product_on_result_rows_and_arriving_rows():
    src = (ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert src.count('"is_product": _product_tag(info)') == 2, (
        "scan.py must publish the flag on BOTH the result rows and the arriving "
        "sidecar rows — the deck reads the first, the arriving list the second")


def test_the_patterns_live_in_config_first():
    assert isinstance(config.PRODUCT_NAME_PATTERNS, tuple)
    assert len(config.PRODUCT_NAME_PATTERNS) >= 5
    for p in config.PRODUCT_NAME_PATTERNS:
        re.compile(p)   # a bad pattern fails here, not silently per-row


# ── THE FENCE, both directions ───────────────────────────────────────────────

def test_FENCE_nothing_in_broker_reads_the_flag_or_its_patterns():
    """The whole point of the session, enforced.

    scanner/broker/ is the decision path: decide(), plan_trade, the caps, the
    guards. The day any file there mentions `is_product` or
    PRODUCT_NAME_PATTERNS, display honesty has become an eligibility change —
    mid-w3-1, without a sign-off. This test names the file so the diff review
    starts in the right place.
    """
    offenders = []
    for f in sorted(BROKER.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        if "is_product" in src or "PRODUCT_NAME_PATTERNS" in src:
            offenders.append(str(f.relative_to(ROOT)))
    assert offenders == [], (
        f"the display flag leaked into the decision path: {offenders} — "
        "if this is intentional it is a TRADE change and needs the owner, "
        "not a test edit")


def test_FENCE_the_bots_own_fund_test_is_untouched_in_shape():
    """The bot's matcher must still be the substring form it has always been.

    Not because substring matching is good — it has the NFLX bug — but because
    changing it changes which trades the bot takes, and that is the owner's
    call after the w3-1 readout. If this fails, someone 'fixed' the bot's
    heuristic while wiring the display flag; revert that half.
    """
    src = (BROKER / "vivek_bot.py").read_text(encoding="utf-8")
    assert "return any(kw in name for kw in _FUND_NAME_KEYWORDS)" in src, (
        "vivek_bot._is_fund_or_reit's matching changed — that is a trade "
        "change, not a display change")


def test_the_word_list_is_imported_not_retyped():
    """scan.py must build its regex from vivek_bot's keyword tuple.

    A re-typed list drifts in step with the bug it is supposed to catch —
    the standing mirror rule. The MATCHING differs on purpose (word
    boundaries); the WORDS may not.
    """
    src = (ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert "_vb._FUND_NAME_KEYWORDS" in src
    # and no literal copy of the list's distinctive members outside config
    assert '"BETASHARES"' not in src and "'BETASHARES'" not in src

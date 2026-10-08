"""Audit #56 (2026-10-08): the is_product display flag dimmed operating
companies whose names happen to read like a LIC.

`_product_tag` returned True on any PRODUCT_NAME_PATTERNS hit even when the row
carried a real operating GICS sector, so Premier Investments Limited (PMV, an
ASX retailer) and New Zealand King Salmon Investments Limited (NZK, food) were
dimmed and dropped from the deck's real A+/A counts. The patterns now apply only
where a financial listing class can live: a blank, financial, unclassified or
non-operating sector (config.PRODUCT_PATTERN_SECTOR_HINTS).

Deliberately NOT changed (both verifiers): the fund KEYWORD list (TRUST/FUND/
ETF ...) mirrors the bot's own exclusion, which skips the TRUST-named banks too,
so the deck and the bot keep agreeing there. And the bot's matcher is untouched
(tests/test_product_flag.py's fence).
"""
from scanner import config
from scanner.broker import vivek_bot
from scanner.scan import _product_tag


def _row(name, sector=""):
    return {"name": name, "sector": sector}


def test_operating_companies_named_investments_limited_are_not_products():
    pmv = _row("Premier Investments Limited", "Consumer Discretionary Distribution & Retail")
    nzk = _row("New Zealand King Salmon Investments Limited", "Food, Beverage & Tobacco")
    assert _product_tag(pmv) is False
    assert _product_tag(nzk) is False
    # and the bot already treats them as operating companies, so deck and bot agree
    assert not vivek_bot._is_fund_or_reit(pmv)
    assert not vivek_bot._is_fund_or_reit(nzk)


def test_the_real_lics_still_dim_under_every_sector_they_actually_carry():
    for name, sector in (
        ("Bailador Technology Investments Limited", "Financial Services"),
        ("Navigator Global Investments Limited", "Financial Services"),   # accepted borderline
        ("Illuminator Investment Company Limited", "Class Pend"),
        ("Hearts and Minds Investments Limited", "Not Applic"),
        ("Regal Asian Investments Limited", "Financials"),
        ("Australian Foundation Investment Company Limited", ""),
    ):
        assert _product_tag(_row(name, sector)) is True, (name, sector)


def test_nasdaq_preferred_lines_carry_no_sector_and_still_dim():
    assert _product_tag(_row(
        "Strategy Inc - 10.00% Series A Perpetual Strife Preferred Stock")) is True


def test_the_keyword_list_is_not_gated_by_the_sector_mirror_rule():
    """Northern Trust is excluded by the bot itself (word list TRUST), so the
    deck dimming it is the deck and the bot agreeing. Untouched on purpose."""
    ntrs = _row("Northern Trust Corporation - Common Stock")
    assert _product_tag(ntrs) is True and vivek_bot._is_fund_or_reit(ntrs)
    assert _product_tag(_row("Reef Casino Trust", "Consumer Services")) is True


def test_the_sector_hints_live_in_config_and_are_lower_case():
    hints = config.PRODUCT_PATTERN_SECTOR_HINTS
    assert isinstance(hints, tuple) and hints
    assert all(h == h.lower().strip() and h for h in hints)

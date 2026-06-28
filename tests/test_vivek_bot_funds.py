"""The bot must not trade REITs / ETFs / LICs / managed funds."""

import pytest

from scanner.broker import vivek_bot as vb

pytestmark = pytest.mark.risk


def _plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim",
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "rr": 3.0, "scale": [0.25, 0.50, 0.15]}
    p.update(kw)
    return p


def _row(name, sector, **kw):
    r = {"symbol": "XYZ", "name": name, "sector": sector, "dir": "LONG",
         "grade": "A+", "entry_types": ["reclaim"], "plans": {"1W": _plan()}}
    r.update(kw)
    return r


def test_is_fund_or_reit_flags_vehicles_not_operating_companies():
    fund = lambda n, s="": vb._is_fund_or_reit({"name": n, "sector": s})
    assert fund("Charter Hall Long Wale Reit", "Equity Real Estate Investment Trusts (REITs)")
    assert fund("Ma Credit Income Trust", "Not Applicable")
    assert fund("State Street Spdr S&P/Asx 200", "Not Applicable")
    assert fund("Qualitas Real Estate Income Fund", "Financial Services")   # fund under an op sector
    assert fund("Some LIC", "Not Applic")                                   # the real ETF/LIC tag
    # real operating companies must NOT be flagged
    assert not fund("Some Name", "")                  # merely missing sector is not a fund signal
    assert not fund("Ansell Limited", "Health Care Equipment & Services")
    assert not fund("Premier Investments Limited", "Consumer Discretionary Distribution & Retail")
    assert not fund("Credit Corp Group Limited", "Financial Services")


def test_bot_skips_reit_and_fund_rows():
    for row in [
        _row("Scentre Group", "Equity Real Estate Investment Trusts (REITs)"),
        _row("Clime Capital Limited", "Not Applicable", name_kw="LIC"),
        _row("Qualitas Real Estate Income Fund", "Financial Services"),
    ]:
        d = vb.evaluate_setup(row)
        assert d["take"] is False and d["code"] == "fund_reit"


def test_bot_still_takes_a_normal_operating_company():
    d = vb.evaluate_setup(_row("Ansell Limited", "Health Care Equipment & Services"))
    assert d["take"] is True and d["code"] == "OK"


def test_exclusion_can_be_disabled(monkeypatch):
    monkeypatch.setattr(vb._cfg, "VIVEK_BOT_EXCLUDE_FUNDS", False)
    d = vb.evaluate_setup(_row("Scentre Group", "Equity Real Estate Investment Trusts (REITs)"))
    assert d["take"] is True

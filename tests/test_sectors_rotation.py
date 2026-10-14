"""The NEWS page's rotation clause is built from the sectors that led
(REFINE200 #142).

It used to be one fixed sentence per branch: every risk-off day read
"Defensives & gold leading" -- on 2026-10-14 with gold (XGD -3.4%) the
second-worst ASX sector, and in the US column, which has no gold series at all.
"""

from scanner import sectors


def _s(sym, name, pct):
    return {"symbol": sym, "name": name, "chg_pct": pct}


def _rotation(rows, label="ASX"):
    return sectors._read(label, rows, [])[1]


# The live ASX read of 2026-10-14 12:26 AEDT (the finding's evidence).
ASX_RISK_OFF = [
    _s("XEJ", "Energy", 1.8), _s("XUJ", "Utilities", 1.5), _s("XTJ", "Comm. Services", 0.5),
    _s("XHJ", "Health Care", 0.4), _s("XSJ", "Cons. Staples", 0.3), _s("XPJ", "Property", 0.2),
    _s("XFJ", "Financials", -0.5), _s("XDJ", "Cons. Disc.", -1.0), _s("XNJ", "Industrials", -1.2),
    _s("XMJ", "Materials", -2.8), _s("XGD", "Gold", -3.4), _s("XIJ", "Info Tech", -4.2),
]


def test_a_risk_off_day_with_gold_falling_never_says_gold_is_leading():
    rot = _rotation(ASX_RISK_OFF)
    assert "OUT OF XIJ (-4.2%), XGD (-3.4%), XMJ (-2.8%)" in rot
    assert "gold" not in rot.split(". ", 1)[1].lower(), rot
    assert "Defensives leading (Utilities +1.5%)" in rot, rot
    assert rot.endswith("a cautious, risk-off lean.")


def test_gold_is_named_only_when_it_actually_led():
    rows = [_s("XGD", "Gold", 2.0), _s("XUJ", "Utilities", 1.0), _s("XEJ", "Energy", 0.1),
            _s("XMJ", "Materials", -2.0), _s("XIJ", "Info Tech", -3.0), _s("XFJ", "Financials", -1.0)]
    assert "Defensives & gold leading (Gold +2.0%, Utilities +1.0%)" in _rotation(rows)
    only_gold = [_s("XGD", "Gold", 2.0), _s("XEJ", "Energy", 0.5), _s("XFJ", "Financials", 0.1),
                 _s("XMJ", "Materials", -2.0), _s("XIJ", "Info Tech", -3.0), _s("XUJ", "Utilities", -0.1)]
    assert "Gold leading (Gold +2.0%)" in _rotation(only_gold)


def test_the_us_column_never_mentions_gold():
    rows = [_s("XLU", "Utilities", 1.2), _s("XLP", "Cons. Staples", 0.8), _s("XLK", "Technology", -2.0),
            _s("XLY", "Cons. Disc.", -1.5), _s("XLF", "Financials", -0.4), _s("XLV", "Health Care", 0.2)]
    rot = _rotation(rows, "US")
    assert "gold" not in rot.lower(), rot
    assert "Defensives leading (Utilities +1.2%, Cons. Staples +0.8%, Health Care +0.2%)" in rot


def test_a_day_where_nothing_on_the_winning_side_rose_says_less_bad_with_the_averages():
    rows = [_s("XUJ", "Utilities", -0.1), _s("XSJ", "Cons. Staples", -0.2),
            _s("XEJ", "Energy", -1.0), _s("XMJ", "Materials", -2.0)]
    rot = _rotation(rows)
    assert "Defensives held up better than cyclicals (-0.2% vs -1.5%)" in rot, rot


def test_risk_on_names_the_cyclicals_that_led_and_not_a_defensive_leader():
    rows = [_s("XPJ", "Property", 1.0), _s("XTJ", "Comm. Services", 0.8), _s("XEJ", "Energy", 0.8),
            _s("XFJ", "Financials", -1.4), _s("XGD", "Gold", -1.9), _s("XUJ", "Utilities", -0.9)]
    rot = _rotation(rows)
    assert "Cyclicals leading (Comm. Services +0.8%, Energy +0.8%)" in rot, rot
    assert "Property" not in rot.split(". ", 1)[1]
    flat = [_s("XEJ", "Energy", -0.1), _s("XUJ", "Utilities", -0.5)]
    assert "Cyclicals held up better than defensives (-0.1% vs -0.5%)" in _rotation(flat)

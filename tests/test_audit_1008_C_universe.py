"""Audit 2026-10-08 #60: the peg filter missed five $1 pegs / NAV funds in
the live crypto universe -- SOFID ("SoFiUSD": USD glued to a word), USX,
SAFO ("Spiko Amundi Overnight Swap Fund": CoinGecko dropped the "(EUR)" the
name rule used to catch) and the Tradable SSTN notes PC0000031 / PC0000033.
All sit in the committed universe and are requested from every venue each
run; the day a venue serves one, VIVEK grades a peg (the first exchange-data
dry run graded EURCV A+). The same sweep found CASH and the yen coin JPYSC.
"""
import json

from scanner import universe
from scanner.universe import _is_stable

MISSED = [("SOFID", "SoFiUSD"), ("USX", "USX"),
          ("SAFO", "Spiko Amundi Overnight Swap Fund"),
          ("PC0000031", "Tradable NA Rent Financing Platform SSTN"),
          ("PC0000033", "Tradable APAC Diversified Finance Provider SSTN"),
          ("CASH", "CASH"), ("JPYSC", "JPYSC")]


def test_the_missed_pegs_are_skipped():
    for sym, name in MISSED:
        assert _is_stable(sym, name), (sym, name)
        assert _is_stable(sym), sym                    # by ticker, whatever the name


def test_the_name_rule_catches_their_next_siblings_by_name():
    for sym, name in [("PC0000040", "Tradable EU Asset Finance SSTN"),
                      ("SAFX", "Spiko Amundi Overnight Swap Fund")]:
        assert _is_stable(sym, name), (sym, name)


def test_the_widened_name_rule_still_keeps_coins_that_float():
    for sym, name in [("SUSHI", "Sushi"), ("CAKE", "PancakeSwap"), ("UNI", "Uniswap"),
                      ("STABLE", "\u200b\u200bStable"), ("BTSE", "BTSE Token"),
                      ("XAUT", "Tether Gold"), ("KAU", "Kinesis Gold"), ("HTX", "HTX DAO")]:
        assert not _is_stable(sym, name), (sym, name)


def test_a_snapshot_saved_under_the_old_rule_is_refiltered_without_them(monkeypatch, tmp_path):
    """The committed snapshot (saved 2026-10-08 under the old rule) still
    carries all seven; loaded as the CoinGecko-down fallback it must drop
    them. Synthetic rather than the committed file, so the test never reads
    a file the scans rewrite."""
    items = [{"symbol": f"C{i}", "name": f"Coin {i}", "yf": f"C{i}-USD"} for i in range(45)]
    items += [{"symbol": s, "name": n, "yf": f"{s}-USD", "cg_price": 1.0} for s, n in MISSED]
    monkeypatch.setattr(universe, "UNIVERSE_CACHE_DIR", tmp_path)
    (tmp_path / "crypto.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    monkeypatch.setattr(universe, "_fetch_crypto", lambda suffix: [])
    got = [i["symbol"] for i in universe.load_universe("crypto")]
    assert len(got) == 45 and not {s for s, _ in MISSED} & set(got)

"""ONE close writer (REFINE200 #92).

The close accounting -- remaining -> exits -> gross_r -> booked_pct ->
status/exit_* -> costs -> hold_days -- used to be typed out three times: the
stop branch of `vivek_journal._mark`, `vivek_run._close_time_stop` and
`vivek_run.close_bot_position`. It is now `vivek_journal._close_remaining`.

The load-bearing test is BEFORE/AFTER: frozen copies of the three pre-#92
implementations live in this file, and each path is driven over the same
fixtures through both. The serialised rows must match byte for byte, key order
included -- except for the fields later REFINE200 items changed on purpose,
which are named in `ADDED` / `DROPPED` below with the item that moved them, so
a new difference cannot hide among them.
"""

import copy
import datetime as dt
import json

import pytest

from scanner import config
from scanner import vivek_journal as vj
from scanner.broker import vivek_run as vr
from scanner.broker.vivek_bot import manage_position

pytestmark = pytest.mark.risk

# Fields a later REFINE200 item adds to (ADDED) or removes from (DROPPED) a
# closed row on purpose. Everything else must be byte-identical.
ADDED: set = set()
DROPPED: set = set()


# ── the pre-#92 implementations, frozen ──────────────────────────────────────

def _old_mark(trade, price, day, costs=None):
    """vivek_journal._mark as it stood before #92 (verbatim logic)."""
    is_long = trade["direction"] == "long"
    entry, risk = trade["entry"], trade["risk"]
    if risk <= 0:
        return
    trade.setdefault("gross_r", trade.get("realized_r", 0.0))
    trade["mfe"] = max(trade["mfe"], price) if is_long else min(trade["mfe"], price)
    trade["mae"] = min(trade["mae"], price) if is_long else max(trade["mae"], price)
    pos = {"symbol": trade["symbol"], "direction": trade["direction"], "entry": entry,
           "stop": trade["stop"], "tp1": trade["tp1"], "tp2": trade["tp2"],
           "tp3": trade["tp3"], "scale": trade["scale"],
           "tp1_hit": trade["tp1_hit"], "tp2_hit": trade["tp2_hit"], "tp3_hit": trade["tp3_hit"]}
    stop_hit = price <= pos["stop"] if is_long else price >= pos["stop"]
    if stop_hit:
        remaining = round(1.0 - trade["booked_pct"], 6)
        if remaining > 1e-9:
            trade["exits"].append({"reason": "stop", "price": round(price, 8), "pct": remaining, "date": day})
            trade["gross_r"] = round(trade["gross_r"] + remaining * vj._r_of(price, entry, risk, is_long), 4)
            trade["booked_pct"] = 1.0
        trade["status"] = "closed"
        trade["exit_price"] = round(price, 8)
        trade["exit_date"] = day
        trade["exit_reason"] = ("target" if pos["tp3_hit"]
                                else "trail" if pos["tp1_hit"] else "stop")
    else:
        for a in manage_position(pos, price):
            if a["action"] == "scale":
                name = a["tp"].lower()
                pct, px = a["book_pct"], pos[name]
                trade["exits"].append({"reason": name, "price": px, "pct": pct, "date": day})
                trade["gross_r"] = round(trade["gross_r"] + pct * vj._r_of(px, entry, risk, is_long), 4)
                trade["booked_pct"] = round(trade["booked_pct"] + pct, 6)
        trade["tp1_hit"], trade["tp2_hit"], trade["tp3_hit"] = pos["tp1_hit"], pos["tp2_hit"], pos["tp3_hit"]
        trade["stop"] = pos["stop"]
    vj._apply_costs(trade, costs)
    trade["mae_r"] = round(vj._r_of(trade["mae"], entry, risk, is_long), 3)
    trade["mfe_r"] = round(vj._r_of(trade["mfe"], entry, risk, is_long), 3)
    if trade["status"] == "closed":
        try:
            d0 = dt.date.fromisoformat(trade["entry_date"])
            d1 = dt.date.fromisoformat(trade["exit_date"])
            trade["hold_days"] = (d1 - d0).days
        except Exception:
            trade["hold_days"] = None


def _old_close(pos, price, day, costs, record, label):
    """vivek_run._close_time_stop (record="time") and close_bot_position's
    accounting (record="manual") as they stood before #92 -- the two were the
    same lines with different reason strings."""
    is_long = pos.get("direction") == "long"
    remaining = round(1.0 - (pos.get("booked_pct") or 0.0), 6)
    pos.setdefault("gross_r", pos.get("realized_r", 0.0))
    if remaining > 1e-9:
        pos.setdefault("exits", []).append(
            {"reason": record, "price": round(price, 8), "pct": remaining, "date": day})
        pos["gross_r"] = round(
            pos["gross_r"] + remaining * vj._r_of(price, pos["entry"], pos["risk"], is_long), 4)
        pos["booked_pct"] = 1.0
    pos["status"] = "closed"
    pos["exit_price"] = round(price, 8)
    pos["exit_date"] = day
    pos["exit_reason"] = label
    vj._apply_costs(pos, costs)
    try:
        pos["hold_days"] = (dt.date.fromisoformat(day)
                            - dt.date.fromisoformat(pos["entry_date"])).days
    except Exception:
        pos["hold_days"] = None


# ── fixtures ─────────────────────────────────────────────────────────────────

def _r3(px, entry, risk, is_long):
    return round(vj._r_of(px, entry, risk, is_long), 3)


def _long(**kw):
    t = {"id": "AAA:long:1D:2026-09-01", "symbol": "AAA", "market": "asx",
         "direction": "long", "grade": "A+", "entry_type": "reclaim", "timeframe": "1D",
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "scale": [0.25, 0.5, 0.15], "risk": 4.0, "entry_date": "2026-09-01",
         "status": "open", "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
         "booked_pct": 0.0, "realized_r": -0.0031, "gross_r": 0.0, "cost_r": 0.0031,
         "exits": [], "mae": 90.0, "mfe": 125.0,
         "mae_r": _r3(90.0, 100.0, 4.0, True), "mfe_r": _r3(125.0, 100.0, 4.0, True),
         "units": 25.0, "notional": 2500.0, "risk_usd": 100.0, "last_mark": 98.0}
    t.update(kw)
    return t


def _short(**kw):
    t = _long(id="ZZZ:short:1D:2026-09-01", symbol="ZZZ", direction="short",
              stop=104.0, tp1=94.0, tp2=88.0, tp3=80.0, scale=[0.5, 0.25, 0.15],
              mae=110.0, mfe=75.0, mae_r=_r3(110.0, 100.0, 4.0, False),
              mfe_r=_r3(75.0, 100.0, 4.0, False))
    t.update(kw)
    return t


def _scaled(**kw):
    """Past TP1: a quarter banked, the stop trailed to break-even."""
    t = _long(tp1_hit=True, booked_pct=0.25, stop=100.0, gross_r=0.375,
              realized_r=0.37, cost_r=0.005,
              exits=[{"reason": "tp1", "price": 106.0, "pct": 0.25,
                      "date": "2026-09-05"}])
    t.update(kw)
    return t


FIXTURES = {
    "long_flat": _long,
    "long_scaled": _scaled,
    "short_flat": _short,
    "legacy_no_gross": lambda: {k: v for k, v in _long().items() if k != "gross_r"},
    "bad_entry_date": lambda: _long(entry_date="not-a-date"),
    # An odd banked fraction, so the remainder's rounding is exercised too.
    "odd_booked": lambda: _scaled(booked_pct=0.333333),
}
COSTS = {"off": None, "asx": vj.costs_for("asx"), "crypto": vj.costs_for("crypto")}
DAY = "2026-09-20"


def _same(new: dict, old: dict) -> None:
    """Byte-identical once the named intentional changes are set aside."""
    n = {k: v for k, v in new.items() if k not in ADDED}
    o = {k: v for k, v in old.items() if k not in DROPPED}
    assert json.dumps(n) == json.dumps(o)


# ── the three paths, before vs after ─────────────────────────────────────────

@pytest.mark.parametrize("fx", sorted(FIXTURES))
@pytest.mark.parametrize("cost", sorted(COSTS))
@pytest.mark.parametrize("price_kind", ["at_stop", "gapped"])
def test_the_stop_branch_of_mark_is_byte_identical(fx, cost, price_kind):
    base = FIXTURES[fx]()
    is_long = base["direction"] == "long"
    stop = base["stop"]
    price = stop if price_kind == "at_stop" else (stop - 1.5 if is_long else stop + 1.5)
    new, old = copy.deepcopy(base), copy.deepcopy(base)
    vj._mark(new, price, DAY, COSTS[cost])
    _old_mark(old, price, DAY, COSTS[cost])
    assert new["status"] == "closed"
    _same(new, old)


@pytest.mark.parametrize("fx", sorted(FIXTURES))
@pytest.mark.parametrize("cost", sorted(COSTS))
@pytest.mark.parametrize("price", [97.5, 101.25, 104.0])
def test_the_time_stop_is_byte_identical(fx, cost, price):
    base = FIXTURES[fx]()
    new, old = copy.deepcopy(base), copy.deepcopy(base)
    vr._close_time_stop(new, price, DAY, COSTS[cost])
    _old_close(old, price, DAY, COSTS[cost], "time", "time")
    assert new["exit_reason"] == "time" and new["status"] == "closed"
    _same(new, old)


@pytest.mark.parametrize("fx", sorted(FIXTURES))
@pytest.mark.parametrize("cost", sorted(COSTS))
@pytest.mark.parametrize("label", ["manual", "owner_close"])
def test_the_hand_close_core_is_byte_identical(fx, cost, label):
    base = FIXTURES[fx]()
    new, old = copy.deepcopy(base), copy.deepcopy(base)
    vj._close_remaining(new, 102.5, DAY, "manual", COSTS[cost], exit_reason=label)
    _old_close(old, 102.5, DAY, COSTS[cost], "manual", label)
    assert new["exits"][-1]["reason"] == "manual" and new["exit_reason"] == label
    _same(new, old)


@pytest.mark.parametrize("fx", ["long_flat", "long_scaled", "short_flat"])
def test_close_bot_position_end_to_end_matches_the_old_accounting(fx, tmp_path, monkeypatch):
    """The real entry point, through the book file: the closed row it persists
    is the old accounting's row, with the market's own cost model."""
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    base = FIXTURES[fx]()
    (tmp_path / "vivek_bot_book.asx.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": "asx", "open": [base], "closed": []}),
        encoding="utf-8")
    row = vr.close_bot_position(base["symbol"], "asx", 101.0, day=DAY)
    old = copy.deepcopy(base)
    _old_close(old, 101.0, DAY, vj.costs_for("asx"), "manual", "manual")
    _same(row, old)
    saved = json.loads((tmp_path / "vivek_bot_book.asx.json").read_text(encoding="utf-8"))
    assert saved["open"] == [] and len(saved["closed"]) == 1
    _same(saved["closed"][0], old)


def test_there_is_one_close_writer():
    """Structural pin: neither runner path re-types the accounting."""
    import inspect
    for fn in (vr._close_time_stop, vr.close_bot_position):
        src = inspect.getsource(fn)
        assert "_close_remaining(" in src, fn.__name__
        assert "booked_pct\"] = 1.0" not in src, fn.__name__
    mark_src = inspect.getsource(vj._mark)
    assert "_close_remaining(" in mark_src
    assert 'trade["booked_pct"] = 1.0' not in mark_src


def test_the_config_costs_are_on_so_the_cost_cells_mean_something():
    assert config.VIVEK_COSTS_ENABLED is True
    assert COSTS["asx"] is not None and COSTS["crypto"] is not None

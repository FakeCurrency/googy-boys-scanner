"""scripts/decision_pack.py -- the numbers behind docs/DECISIONS_2026-10-14.md.

Three properties make the pack worth trusting later: it is READ-ONLY (it can
be run on any checkout, any day, and change nothing), it counts the same way
the journal does (a rules exit is a MECHANICAL_EXITS reason, everything else
is a hand close), and its pre-registered thresholds cannot drift from the
ones written in the doc. Each has a pin here; the arithmetic is checked on a
small fixture book so a wrong verdict fails here, not in front of the owner.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "decision_pack.py"
DOC = ROOT / "docs" / "DECISIONS_2026-10-14.md"

_spec = importlib.util.spec_from_file_location("decision_pack", SCRIPT)
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


# -- fixtures ----------------------------------------------------------------

def _row(sym, r, reason, *, market="asx", tf="3D", et="reclaim", grade="A+",
         cycle="hc4-1", entry_date="2026-09-28", exit_date="2026-10-20", **kw):
    row = {"symbol": sym, "market": market, "timeframe": tf, "entry_type": et,
           "grade": grade, "cycle": cycle, "entry_date": entry_date,
           "exit_date": exit_date,
           "status": "closed", "realized_r": r, "exit_reason": reason,
           "level_tf": "3d", "mae_r": kw.pop("mae_r", min(r, 0.0)),
           "mfe_r": kw.pop("mfe_r", max(r, 0.0)), "risk_usd": 300.0}
    row.update(kw)
    return row


def _book(tmp_path, closed, opn=()):
    j = tmp_path / "journal"
    j.mkdir(exist_ok=True)
    for m in dp.MARKETS:
        (j / f"vivek_bot_book.{m}.json").write_text(json.dumps({
            "market": m,
            "closed": [r for r in closed if r["market"] == m],
            "open": [r for r in opn if r["market"] == m]}), encoding="utf-8")
    return tmp_path


# -- counting the way the journal counts -------------------------------------

def test_mechanical_exits_are_the_sites_own_list():
    # wherever the site declares it (journal/app/status today, maybe one
    # shared util later), every declaration must be this list
    found = []
    for f in sorted((ROOT / "public" / "js").rglob("*.js")):
        for m in re.finditer(r"MECHANICAL_EXITS\s*[=:]\s*(?:Object\.freeze\()?\[([^\]]*)\]",
                             f.read_text(encoding="utf-8")):
            found.append((f.name, tuple(re.findall(r'["\']([a-z]+)["\']', m.group(1)))))
    assert found, "no MECHANICAL_EXITS declaration left in public/js"
    for name, shipped in found:
        assert shipped == dp.MECHANICAL_EXITS, name


def test_the_frozen_hc41_definition_matches_config_while_the_cycle_runs():
    sys.path.insert(0, str(ROOT))
    from scanner import config
    if config.VIVEK_BOT_CYCLE_TAG != dp.HC41["tag"]:
        return  # hc4-1 has ended: the frozen definition is history now
    assert dict(config.VIVEK_BOT_ENTRY_CELLS) == dp.HC41["cells"]
    assert tuple(config.VIVEK_BOT_GRADES) == dp.HC41["grades"]
    assert tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW) == dp.HC41["levels"]
    assert config.VIVEK_BOT_MAX_HOLD_DAYS == dp.HC41["max_hold_days"]


def test_rules_vs_hand_split_and_a_missing_reason_is_a_hand_close(tmp_path):
    closed = [_row("A", -1.0, "stop"), _row("B", 0.5, "time"),
              _row("C", 0.3, "manual"), _row("D", 0.2, None),
              _row("E", 0.1, "TRAIL ")]
    root = _book(tmp_path, closed)
    h = dp.headline(dp.load_book(str(root))[0])
    assert (h["rules"]["n"], h["rules"]["total"]) == (3, -0.4)
    assert (h["hand"]["n"], h["hand"]["total"]) == (2, 0.5)


# -- the pre-registered checkpoints ------------------------------------------

def _pr(pid):
    return next(p for p in dp.PREREG if p["id"] == pid)


def test_a_checkpoint_is_not_due_below_its_n_however_bad_the_average():
    closed = [_row(f"S{i}", -1.0, "stop") for i in range(19)]
    v = dp.evaluate(_pr("PR-1"), closed)
    assert (v["n"], v["verdict"]) == (19, "NOT DUE")


def test_the_3d_reclaim_line_trips_at_n20_and_holds_or_clears_otherwise():
    bad = [_row(f"S{i}", -1.0, "stop") for i in range(7)] + \
          [_row(f"T{i}", 0.0, "time") for i in range(13)]          # avg -0.35
    assert dp.evaluate(_pr("PR-1"), bad)["verdict"] == "TRIPPED"
    mid = [_row(f"S{i}", -1.0, "stop") for i in range(4)] + \
          [_row(f"T{i}", 0.0, "time") for i in range(16)]          # avg -0.20
    assert dp.evaluate(_pr("PR-1"), mid)["verdict"] == "HOLD"
    ok = [_row(f"T{i}", 0.05, "time") for i in range(20)]
    assert dp.evaluate(_pr("PR-1"), ok)["verdict"] == "CLEAR"
    # the second read: -0.20 at n=40 is past the -0.15 line
    later = dict(exit_date="2026-10-27")
    mid40 = mid + [_row(f"U{i}", -1.0, "stop", **later) for i in range(4)] + \
        [_row(f"V{i}", 0.0, "time", **later) for i in range(16)]
    v = dp.evaluate(_pr("PR-1"), mid40)
    assert (v["verdict"], v["read_on"], v["read_n"]) == ("TRIPPED", "2026-10-27", 40)


def test_a_read_is_pinned_to_the_day_its_n_arrived_not_rolled_forward():
    first = [_row(f"S{i}", -1.0, "stop") for i in range(7)] + \
            [_row(f"T{i}", 0.0, "time") for i in range(13)]        # -0.35 on 20 Oct
    later = [_row(f"W{i}", 1.0, "trail", exit_date="2026-10-27") for i in range(30)]
    v = dp.evaluate(_pr("PR-1"), first + later)
    # 50 closes now average +0.46R, but the read happened on 20 Oct at -0.35R
    assert v["avg"] > 0 and (v["verdict"], v["read_on"]) == ("TRIPPED", "2026-10-20")
    # and closes landing the same day as the 20th all belong to that read
    v = dp.evaluate(_pr("PR-1"), first + [_row("Z", 8.0, "trail")])
    assert v["read_n"] == 21 and v["verdict"] == "CLEAR"


def test_hand_closes_and_other_cells_and_cycles_never_enter_a_cohort():
    rows = [_row(f"S{i}", -1.0, "stop") for i in range(20)]
    noise = ([_row(f"M{i}", -1.0, "manual") for i in range(30)] +
             [_row(f"W{i}", -1.0, "stop", tf="1W") for i in range(30)] +
             [_row(f"X{i}", -1.0, "stop", cycle="w3-1") for i in range(30)])
    v = dp.evaluate(_pr("PR-1"), noise + [_row(f"T{i}", 0.1, "time") for i in range(20)])
    assert (v["n"], v["verdict"]) == (20, "CLEAR")
    assert dp.evaluate(_pr("PR-1"), rows)["n"] == 20


def test_the_asx_line_needs_the_gap_to_nasdaq_not_just_a_bad_asx():
    asx = [_row(f"A{i}", -0.5, "stop") for i in range(15)]
    nas_bad = [_row(f"N{i}", -0.4, "stop", market="nasdaq") for i in range(15)]
    nas_ok = [_row(f"N{i}", 0.1, "time", market="nasdaq") for i in range(15)]
    assert dp.evaluate(_pr("PR-2"), asx + nas_bad)["verdict"] != "TRIPPED"
    assert dp.evaluate(_pr("PR-2"), asx + nas_ok)["verdict"] == "TRIPPED"


def test_grade_cohorts_skip_rows_opened_before_the_grade_label_fix():
    early = [_row(f"E{i}", -1.0, "stop", grade="A", entry_date="2026-09-22") for i in range(20)]
    v = dp.evaluate(_pr("PR-3"), early)
    assert v["n"] == 0


def test_the_doc_register_carries_exactly_the_frozen_numbers():
    doc = DOC.read_text(encoding="utf-8")
    for pr in dp.PREREG:
        lines = [ln for ln in doc.splitlines() if ln.startswith(f"| {pr['id']} ")]
        assert len(lines) == 1, f"{pr['id']} must have exactly one register row"
        row = lines[0]
        if "min_n" in pr:
            assert f"n >= {pr['min_n']}" in row, (pr["id"], row)
        if "line" in pr:
            assert f"{pr['line']:+.2f}R" in row, (pr["id"], row)
        if "then" in pr:
            assert f"n >= {pr['then']['min_n']}" in row and f"{pr['then']['line']:+.2f}R" in row
        if "gap" in pr:
            assert f"{pr['gap']:.2f}R" in row, (pr["id"], row)
        if "min_gain" in pr:
            assert f"+{pr['min_gain']:.2f}R" in row, (pr["id"], row)
        if "gap_pp" in pr:
            assert f"{pr['gap_pp']:.1f}pp" in row, (pr["id"], row)


# -- the evidence helpers ----------------------------------------------------

def test_archive_after_rescales_the_adjusted_bars_and_finds_the_first_touch(tmp_path):
    hist = tmp_path / "data" / "history" / "asx"
    hist.mkdir(parents=True)
    # adjusted archive sits at half the traded price
    bars = [["2026-08-01", 5, 5, 5, 5, 0], ["2026-08-04", 5, 5.1, 4.9, 5, 0],
            ["2026-08-05", 5, 5.0, 4.4, 4.5, 0], ["2026-08-06", 4.5, 6.0, 4.5, 6, 0]]
    (hist / "XYZ.json").write_text(json.dumps({"bars": bars}), encoding="utf-8")
    row = {"market": "asx", "symbol": "XYZ", "exit_date": "2026-08-01",
           "exit_price": 10.0, "entry": 10.0, "risk": 1.0, "tp1": 11.5,
           "tp2": 13.0, "tp1_hit": False}
    a = dp.archive_after(str(tmp_path), row)
    assert a["first"] == ("orig_stop", "2026-08-05")      # 4.4 x 2 = 8.8 <= 9.0
    assert a["last_r"] == 2.0                              # 6 x 2 = 12 -> +2R


def test_the_backtest_replica_applies_cells_grades_and_the_level_gate(tmp_path):
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    base = {"direction": "long", "grade": "A+", "timeframe": "3D",
            "entry_type": "reclaim", "level_tf": "3d", "market": "asx",
            "realized_r": 1.0, "mae_r": -0.1,
            "entry_date": "2020-01-01", "exit_date": "2020-01-10"}
    trades = [base,
              dict(base, level_tf="h4"),            # level gate
              dict(base, grade="B+"),               # grade
              dict(base, entry_type="retest"),      # not a cell
              dict(base, direction="short"),
              dict(base, timeframe="1D", entry_type="break", realized_r=-1.0)]
    (d / "vivek_backtest_longonly.json").write_text(json.dumps({"trades": trades}),
                                                     encoding="utf-8")
    b = dp.backtest_replica(str(tmp_path))
    assert b["n"] == 2 and b["all"]["total"] == 0.0


# -- read-only by construction -----------------------------------------------

def test_it_is_read_only_and_imports_nothing_from_the_trade_path():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                assert not m.startswith(("scanner", "phasemap", "subprocess", "shutil")), m
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            assert name not in {"replace", "remove", "unlink", "rename", "makedirs",
                                "mkdir", "write_text", "write_bytes", "dump", "rmtree",
                                "urlopen", "system"}, name
            if name == "open":
                modes = [a.value for a in node.args[1:] if isinstance(a, ast.Constant)]
                modes += [k.value.value for k in node.keywords
                          if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                assert all(set(m) <= {"r", "b", "t"} for m in modes), modes


def test_it_runs_against_the_real_checkout():
    p = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True,
                       text=True, cwd=ROOT, timeout=120)
    assert p.returncode == 0, p.stderr[-500:]
    out = p.stdout
    assert out.startswith("# Decision pack numbers")
    for token in ("rules closes", "hand closes", "Pre-registered checkpoints",
                  "PR-1", "#34 MAE", "#35 review flags", "#32 time-stop exits",
                  "#33 P12 readout"):
        assert token in out, token
    assert out.isascii(), "prints must stay ASCII (cp1252 consoles)"


def test_main_writes_only_to_the_stream_it_is_given(tmp_path):
    root = _book(tmp_path, [_row("A", -1.0, "stop")])
    before = sorted(p.name for p in tmp_path.rglob("*"))
    buf = io.StringIO()
    assert dp.main([], root=str(root), out=buf) == 0
    assert "rules closes" in buf.getvalue()
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_the_what_if_closes_only_pre_tp1_hc41_rows_on_their_time_stop_day():
    opn = [dict(_row("A", 0.0, None, entry_date="2026-09-22"), status="open", unreal_r=-0.4),
           dict(_row("B", 0.0, None, entry_date="2026-09-22"), status="open", unreal_r=0.9,
                tp1_hit=True),
           dict(_row("C", 0.0, None, cycle="w3-1"), status="open", unreal_r=0.1)]
    proj = dp.projected_closes(opn)
    assert [(r["symbol"], r["exit_date"], r["realized_r"], r["exit_reason"]) for r in proj] == \
        [("A", "2026-10-20", -0.4, "time")]


def test_the_roster_ledger_reads_the_same_single_file_or_sharded(tmp_path):
    rows = [{"key": "a", "market": "asx", "ticker": "A", "side": "long",
             "base_day": "2026-09-22", "hiconv": True, "fwd": {"20": 0.05}},
            {"key": "b", "market": "asx", "ticker": "B", "side": "long",
             "base_day": "2026-10-01", "hiconv": False, "fwd": {"20": -0.05}}]
    single = tmp_path / "single"
    (single / "data").mkdir(parents=True)
    (single / "data" / "edge_rosters.json").write_text(json.dumps({"entries": rows}), encoding="utf-8")
    sharded = tmp_path / "sharded"
    sd = sharded / "data" / "edge_rosters"
    sd.mkdir(parents=True)
    (sharded / "data" / "edge_rosters.json").write_text(json.dumps({"layout": "monthly"}), encoding="utf-8")
    (sd / "2026-09.json").write_text(json.dumps({"entries": rows[:1]}), encoding="utf-8")
    (sd / "2026-10.json").write_text(json.dumps({"entries": rows[1:] + rows[:1]}), encoding="utf-8")
    a, b = dp.hc_checkpoint(str(single)), dp.hc_checkpoint(str(sharded))
    assert a == b and a["20"]["hc"]["n"] == 1 and a["20"]["other"]["n"] == 1


def test_the_hand_close_counterfactual_runs_the_ladder_on_traded_prices(tmp_path):
    hist = tmp_path / "data" / "history" / "asx"
    hist.mkdir(parents=True)
    # the archive sits at half the traded price (dividend-adjusted basis)
    bars = [["2026-08-03", 5, 5, 5, 5, 0],
            ["2026-08-04", 5, 5.8, 5.0, 5.5, 0],     # high 11.6 >= TP1 11.5
            ["2026-08-05", 5, 5.1, 4.9, 5.0, 0]]     # low 9.8 <= stop, now at entry
    (hist / "LAD.json").write_text(json.dumps({"bars": bars}), encoding="utf-8")
    quiet = [bars[0], ["2026-08-04", 5, 5.6, 5.0, 5.5, 0], bars[2]]   # never reaches TP1
    (hist / "OLD.json").write_text(json.dumps({"bars": quiet}), encoding="utf-8")
    base = dict(market="asx", exit_reason="manual", realized_r=-0.1, exit_date="2026-08-03",
                exit_price=10.0, entry=10.0, risk=1.0, stop=9.0, tp1=11.5, tp2=13.0,
                tp3=14.0, scale=[0.25, 0.5, 0.15], exits=[])
    rows = [dict(base, symbol="LAD", entry_date="2026-07-28"),
            dict(base, symbol="OLD", entry_date="2026-07-01"),        # past 28 days
            dict(base, symbol="RUL", entry_date="2026-07-28", exit_reason="stop")]
    got = {x["symbol"]: x for x in dp.hand_close_counterfactual(str(tmp_path), rows)}
    assert set(got) == {"LAD", "OLD"}                  # a rules close is not replayed
    # TP1 books 25% at +1.5R, the stop moves to entry, the rest exits at 0R
    assert (got["LAD"]["rules_r"], got["LAD"]["how"]) == (0.38, "stop")
    # already past 28 days and pre-TP1: out at the next close, 5.5 x 2 = 11 -> +1R
    assert (got["OLD"]["rules_r"], got["OLD"]["how"]) == (1.0, "time")

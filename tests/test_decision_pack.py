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


def test_the_frozen_hc42_definition_matches_config_while_the_cycle_runs():
    """hc4-2 (2026-11-02) is frozen in the pack beside its register (PR-9 ..
    PR-16) for the reason HC41 is: a later rule change must not silently
    redefine the cohort its checkpoints judge."""
    sys.path.insert(0, str(ROOT))
    from scanner import config
    if config.VIVEK_BOT_CYCLE_TAG != dp.HC42["tag"]:
        return  # hc4-2 has ended: the frozen definition is history now
    assert dict(config.VIVEK_BOT_ENTRY_CELLS) == dp.HC42["cells"]
    assert tuple(config.VIVEK_BOT_GRADES) == dp.HC42["grades"]
    assert tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW) == dp.HC42["levels"]
    assert config.VIVEK_BOT_MAX_HOLD_DAYS == dp.HC42["max_hold_days"]
    assert config.VIVEK_BOT_D14_STAMP_DAYS == dp.HC42["d14_days"]
    shadow = next(p for p in dp.PREREG if p["kind"] == "shadow")
    assert (shadow["day"], shadow["floor"]) == (dp.HC42["d14_days"], dp.HC42["d14_mfe_floor"])


def test_every_hc42_checkpoint_judges_hc42_and_the_old_ones_stay_hc41():
    ids = {p["id"]: dp.cycle_of(p) for p in dp.PREREG}
    assert all(ids[f"PR-{i}"] == "hc4-1" for i in range(9))
    assert all(ids[f"PR-{i}"] == "hc4-2" for i in range(9, 17))
    # an hc4-1 close never reaches an hc4-2 checkpoint, and the reverse
    pr10 = next(p for p in dp.PREREG if p["id"] == "PR-10")
    old = [_row(f"S{i}", -1.0, "stop", tf="1W") for i in range(25)]
    assert dp.evaluate(pr10, old)["n"] == 0
    new = [_row(f"S{i}", -1.0, "stop", tf="3D", cycle="hc4-2") for i in range(25)]
    assert dp.evaluate(_pr("PR-1"), new)["n"] == 0


def test_the_day14_whatif_cuts_only_a_pre_tp1_row_still_under_the_floor():
    base = _row("A", -0.9, "time", cycle="hc4-2", cost_r=0.02,
                d14={"day": "2026-11-17", "held": 14, "mfe_r": 0.3, "r": 0.1, "tp1_hit": False})
    assert dp.whatif_d14(base, 0.5) == 0.08                      # the stamp's R less costs
    assert dp.whatif_d14(dict(base, d14=dict(base["d14"], tp1_hit=True)), 0.5) == -0.9
    assert dp.whatif_d14(dict(base, d14=dict(base["d14"], mfe_r=0.5)), 0.5) == -0.9
    assert dp.whatif_d14({k: v for k, v in base.items() if k != "d14"}, 0.5) == -0.9


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


def _bare(pid):
    """A register entry without its 3 Nov veto read: the line logic itself."""
    return {k: v for k, v in _pr(pid).items() if k != "veto"}


def test_a_checkpoint_is_not_due_below_its_n_however_bad_the_average():
    closed = [_row(f"S{i}", -1.0, "stop") for i in range(19)]
    v = dp.evaluate(_pr("PR-1"), closed)
    assert (v["n"], v["verdict"]) == (19, "NOT DUE")


def test_the_3d_reclaim_line_trips_at_n20_and_holds_or_clears_otherwise():
    bad = [_row(f"S{i}", -1.0, "stop") for i in range(7)] + \
          [_row(f"T{i}", 0.0, "time") for i in range(13)]          # avg -0.35
    assert dp.evaluate(_bare("PR-1"), bad)["verdict"] == "TRIPPED"
    mid = [_row(f"S{i}", -1.0, "stop") for i in range(4)] + \
          [_row(f"T{i}", 0.0, "time") for i in range(16)]          # avg -0.20
    assert dp.evaluate(_bare("PR-1"), mid)["verdict"] == "HOLD"
    ok = [_row(f"T{i}", 0.05, "time") for i in range(20)]
    assert dp.evaluate(_bare("PR-1"), ok)["verdict"] == "CLEAR"
    # the second read: -0.20 at n=40 is past the -0.15 line
    later = dict(exit_date="2026-10-27")
    mid40 = mid + [_row(f"U{i}", -1.0, "stop", **later) for i in range(4)] + \
        [_row(f"V{i}", 0.0, "time", **later) for i in range(16)]
    v = dp.evaluate(_bare("PR-1"), mid40)
    assert (v["verdict"], v["read_on"], v["read_n"]) == ("TRIPPED", "2026-10-27", 40)


def test_a_read_is_pinned_to_the_day_its_n_arrived_not_rolled_forward():
    first = [_row(f"S{i}", -1.0, "stop") for i in range(7)] + \
            [_row(f"T{i}", 0.0, "time") for i in range(13)]        # -0.35 on 20 Oct
    later = [_row(f"W{i}", 1.0, "trail", exit_date="2026-10-27") for i in range(30)]
    v = dp.evaluate(_bare("PR-1"), first + later)
    # 50 closes now average +0.46R, but the read happened on 20 Oct at -0.35R
    assert v["avg"] > 0 and (v["verdict"], v["read_on"]) == ("TRIPPED", "2026-10-20")
    # and closes landing the same day as the 20th all belong to that read
    v = dp.evaluate(_bare("PR-1"), first + [_row("Z", 8.0, "trail")])
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
        if "veto" in pr:   # NEXT100 #5: the veto read is in the row, numbers and all
            v = pr["veto"]
            assert (f"{v['replay_avg']:+.3f}R" in row and f"over {v['replay_n']}" in row
                    and "final re-read" in row), (pr["id"], row)
        if pr["kind"] == "live":
            assert ("entry cohort" in row) == (dp.read_mode(pr) == "entry"), (pr["id"], row)


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

# The only scanner modules the pack may import: both standard library only
# (the time stop's one definition, and config's MARKET_HOLIDAYS).
STDLIB_SCANNER = {"scanner.time_stop", "scanner.config"}


def test_it_stays_stdlib_only_at_every_depth():
    """NEXT100 #4: the pack reads scanner.time_stop and scanner.config, so
    their whole import tree must stay standard library (the bare-runner walk
    of tests/test_bare_python_jobs.py)."""
    from tests.test_bare_python_jobs import third_party_imports
    assert third_party_imports(SCRIPT) == []

def test_it_is_read_only_and_imports_nothing_from_the_trade_path():
    # The scanner modules allowed are STDLIB_SCANNER: scanner.config (NEXT100
    # #9, the rules-exit list; #4, the holiday table) and scanner.time_stop
    # (#4, the one time-stop day). Both are stdlib-only (the walk above).
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif node.module == "scanner":
                mods = [f"scanner.{a.name}" for a in node.names]
            else:
                mods = [node.module or ""]
            for m in mods:
                if m in STDLIB_SCANNER:
                    continue
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
    # day 29 (scanner.time_stop.time_stop_due), not day 28: entered Tue 22 Sep
    assert [(r["symbol"], r["exit_date"], r["realized_r"], r["exit_reason"]) for r in proj] == \
        [("A", "2026-10-21", -0.4, "time")]


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


# -- NEXT100 #5 (set 3 Nov 2026): PR-1's replay veto -------------------------

def _first20():
    return ([_row(f"S{i:02d}", -1.0, "stop") for i in range(7)]
            + [_row(f"T{i:02d}", 0.0, "time") for i in range(13)])          # -0.35 on 20 Oct


def test_the_veto_holds_pr1s_trip_until_the_40th_close_then_reads_once_more():
    pr1 = _pr("PR-1")
    for k in (0, 10, 19):        # 20 .. 39 closes: HOLD, naming the veto and the re-read n
        more = [_row(f"U{i:02d}", 0.0, "time", exit_date="2026-10-27") for i in range(k)]
        v = dp.evaluate(pr1, _first20() + more)
        assert (v["verdict"], v["read_on"], v["read_n"], v["read_avg"]) == ("HOLD", "2026-10-20", 20, -0.35)
        assert "replay veto" in v["reason"] and "40 closes" in v["reason"], v["reason"]
    # without the veto the same book is a plain first-read trip
    assert dp.evaluate(_bare("PR-1"), _first20())["verdict"] == "TRIPPED"
    # the 40th close: the FINAL read, at the second line
    bad = [_row(f"U{i:02d}", 0.0, "time", exit_date="2026-10-27") for i in range(20)]   # -0.175
    good = [_row(f"U{i:02d}", 0.25, "trail", exit_date="2026-10-27") for i in range(20)]  # -0.05
    v = dp.evaluate(pr1, _first20() + bad)
    assert (v["verdict"], v["read_on"], v["read_n"], v["read_avg"]) == ("TRIPPED", "2026-10-27", 40, -0.175)
    assert "final re-read" in v["reason"]
    assert dp.evaluate(pr1, _first20() + good)["verdict"] == "CLEAR"


def test_the_veto_re_read_is_final_and_a_veto_needs_its_own_line():
    # a trip at the re-read stays a trip: no second veto, however good the replay
    pr = dict(_pr("PR-1"), veto=dict(_pr("PR-1")["veto"], replay_avg=0.9))
    worse = [_row(f"U{i:02d}", -1.0, "stop", exit_date="2026-10-27") for i in range(20)]
    v, reads = dp._evaluate(pr, _first20() + worse)
    assert v["verdict"] == "TRIPPED" and [r["at"] for r in reads] == [20, 40]
    # a replay under the veto's own line vetoes nothing
    weak = dict(_pr("PR-1"), veto=dict(_pr("PR-1")["veto"], replay_avg=0.049))
    assert not dp.vetoes(weak) and dp.evaluate(weak, _first20())["verdict"] == "TRIPPED"
    # a read between the lines is not the veto's: no reason, the usual second read
    mid = [_row(f"S{i}", -1.0, "stop") for i in range(4)] + [_row(f"T{i}", 0.0, "time") for i in range(16)]
    v = dp.evaluate(_pr("PR-1"), mid)
    assert v["verdict"] == "HOLD" and "reason" not in v


# -- NEXT100 #5: hc4-2's entry-cohort reads ----------------------------------

def _h2(sym, r, reason, entry, exit_, **kw):
    return _row(sym, r, reason, cycle="hc4-2", tf="1W", entry_date=entry, exit_date=exit_, **kw)


def _open(sym, entry, **kw):
    row = dict(_row(sym, 0.0, None, cycle="hc4-2", tf="1W", entry_date=entry, exit_date=None),
               status="open", unreal_r=kw.pop("unreal_r", 0.0))
    row.update(kw)
    return row


def test_an_entry_counts_its_horizon_value_and_a_hand_close_before_it_leaves():
    stamp = {"day": "2026-12-08", "held": 30, "r": 2.5, "booked": 0.4, "tp1_hit": True}
    assert dp.horizon_value(_open("R", "2026-11-04", horizon=stamp), True) == (2.5, "2026-12-08")
    assert dp.horizon_value(_open("W", "2026-11-04"), True) is None            # not there yet
    assert dp.horizon_value(_h2("C", -1.0, "stop", "2026-11-02", "2026-11-09"), False) == (-1.0, "2026-11-09")
    assert dp.horizon_value(_h2("M", 3.0, "manual", "2026-11-02", "2026-11-05"), False) == dp.HAND
    after = _h2("M", 0.2, "manual", "2026-11-02", "2026-12-10", horizon=dict(stamp, r=1.0))
    assert dp.horizon_value(after, False) == (1.0, "2026-12-08")              # hand close AFTER it
    bad = _open("N", "2026-11-04", horizon=dict(stamp, r=float("nan")))
    assert dp.horizon_value(bad, True) is None                                 # NaN-safe: still waiting


def test_entries_go_in_entry_order_then_opened_at_then_symbol():
    rows = [_h2("B", 0.0, "time", "2026-11-03", "2026-12-02", opened_at="2026-11-03T01:00:00+00:00"),
            _h2("A", 0.0, "time", "2026-11-03", "2026-12-02", opened_at="2026-11-03T02:00:00+00:00"),
            _h2("C", 0.0, "time", "2026-11-03", "2026-12-02", opened_at="2026-11-03T01:00:00+00:00"),
            _h2("Z", 0.0, "time", "2026-11-02", "2026-12-01")]
    assert [r["symbol"] for r, _ in dp.horizon_entries("hc4-2", rows)] == ["Z", "B", "C", "A"]


def test_an_entry_cohort_reads_the_first_entries_not_the_first_closes():
    early = [_h2(f"A{i:02d}", 0.1, "time", f"2026-11-0{2 + i // 5}", "2026-12-03") for i in range(20)]
    fast = [_h2(f"Q{i}", -1.0, "stop", "2026-11-09", "2026-11-10") for i in range(5)]
    v = dp.evaluate(_pr("PR-10"), early + fast)
    assert (v["verdict"], v["read_avg"], v["read_n"], v["entries"]) == ("CLEAR", 0.1, 20, 25)
    # read in close order, the five quick losers would have landed first
    close_order = dp.evaluate(dict(_pr("PR-10"), read="close"), early + fast)
    assert close_order["read_avg"] < 0


def test_an_entry_cohort_waits_for_every_entry_and_reads_on_the_last_horizon_day():
    rows = [_h2(f"N{i:02d}", -1.0, "stop", "2026-11-02", "2026-11-12") for i in range(19)]
    waiting = _open("WAIT", "2026-11-03", unreal_r=0.3)
    v = dp.evaluate(_pr("PR-10"), rows, [waiting])
    assert (v["verdict"], v["entries"], v["n"]) == ("NOT DUE", 20, 19)
    stamped = dict(waiting, horizon={"day": "2026-12-07", "held": 30, "r": 1.0, "booked": 0.4,
                                     "tp1_hit": True})
    v = dp.evaluate(_pr("PR-10"), rows, [stamped])
    assert (v["verdict"], v["read_on"], v["read_avg"]) == ("TRIPPED", "2026-12-07", -0.9)


def test_a_versus_entry_cohort_needs_the_versus_entries_up_to_its_last_entry():
    asx = [_row(f"X{i:02d}", -0.5, "stop", cycle="hc4-2", entry_date="2026-11-03",
                exit_date="2026-11-12") for i in range(15)]
    nas = [_row(f"Y{i:02d}", 0.0, "time", market="nasdaq", cycle="hc4-2", entry_date="2026-11-02",
                exit_date="2026-12-02") for i in range(5)]
    pend = dict(_open("YP", "2026-11-03"), market="nasdaq")
    late = dict(_open("YL", "2026-11-10"), market="nasdaq")          # after the cohort: never blocks
    assert dp.evaluate(_pr("PR-14"), asx + nas, [pend, late])["verdict"] == "NOT DUE"
    done = dict(pend, horizon={"day": "2026-12-04", "held": 30, "r": 0.0, "booked": 0.4, "tp1_hit": True})
    v = dp.evaluate(_pr("PR-14"), asx + nas, [done, late])
    assert (v["verdict"], v["read_avg"], v["versus_avg"], v["read_on"]) == ("TRIPPED", -0.5, 0.0, "2026-12-04")


# -- NEXT100 #4: the time stop, the holidays, booked R ------------------------

def test_every_time_stop_day_is_the_engines_day_29_weekend_rolled():
    def o(sym, entry, market="asx", **kw):
        return dict(_row(sym, 0.0, None, market=market, entry_date=entry), status="open", **kw)
    rows = [o("A", "2026-09-22"),                  # day 29 Wed 21 Oct
            o("B", "2026-10-02"),                  # day 29 Sat 31 Oct -> Mon 2 Nov
            o("C", "2026-10-02", market="crypto"),  # crypto has no weekend
            o("D", "2026-10-02", tp1_hit=True)]    # a runner is exempt
    assert dp.time_stop_schedule(rows) == [("2026-10-21", 1), ("2026-10-31", 1), ("2026-11-02", 1)]
    assert [dp.due_day(r) for r in rows] == ["2026-10-21", "2026-11-02", "2026-10-31", None]


def test_a_time_stop_on_a_shut_market_is_flagged_and_past_holiday_marks_are_counted():
    def o(sym, market, entry, **kw):
        return dict(_row(sym, 0.0, None, market=market, entry_date=entry), status="open", **kw)
    # entered Wed 28 Oct: day 29 is Thu 26 Nov, Thanksgiving on NASDAQ, a trading day on the ASX
    rows = [o("US", "nasdaq", "2026-10-28"), o("AU", "asx", "2026-10-28"),
            o("RUN", "nasdaq", "2026-10-28", tp1_hit=True)]
    got = dp.holiday_stops(rows)
    assert [(x["day"], x["market"], x["symbol"], x["holiday"]) for x in got] == \
        [("2026-11-26", "nasdaq", "US", "Thanksgiving Day")]
    marked = [dict(_row("N1", -1.0, "stop", market="nasdaq"), day_marks={"2026-09-04": 1.0, "2026-09-07": 1.0}),
              dict(_row("N2", -1.0, "stop", market="nasdaq"), day_marks={"2026-09-07": 2.0}),
              dict(_row("A1", -1.0, "stop", market="asx"), day_marks={"2026-09-07": 3.0})]   # ASX was open
    assert dp.holiday_marks(marked) == {("nasdaq", "2026-09-07"): ["N1", "N2"]}


def test_an_open_row_is_valued_at_booked_plus_open():
    runner = dict(_row("R", 0.0, None, entry_date="2026-10-01"), status="open", tp1_hit=True,
                  realized_r=0.375, unreal_r=0.9)
    plain = dict(_row("P", 0.0, None, entry_date="2026-10-01"), status="open", realized_r=-0.01,
                 unreal_r=-0.2)
    assert dp.open_r(runner) == 1.275 and round(dp.open_r(plain), 4) == -0.21
    rs = dp.r_per_slot_month([runner, plain], today="2026-10-31")      # 30 days each
    assert rs["r_per_slot_month"] == round((1.275 - 0.21) / (60 / 30.4375), 4)
    assert dp.mae_report([], [dict(runner, mae_r=-0.6, unreal_r=-0.1)])["open_now_positive"] == 1
    proj = dp.projected_closes([plain])
    assert proj[0]["realized_r"] == plain["realized_r"] + plain["unreal_r"]


# -- NEXT100 #6: how sure a read is -------------------------------------------

REPLAY_FIXTURE = ROOT / "tests" / "fixtures" / "decision_replay_summary.json"


def test_a_reads_spread_is_its_standard_error_and_its_iso_entry_weeks():
    rows = [_row("A", 1.0, "trail", entry_date="2026-09-22"), _row("B", -1.0, "stop", entry_date="2026-09-24"),
            _row("C", 0.0, "time", entry_date="2026-09-29")]
    sp = dp.read_spread(rows)
    assert sp == {"n": 3, "se": round(1.0 / 3 ** 0.5, 3), "weeks": ["2026-W39", "2026-W40"]}
    assert dp.read_spread(rows[:1])["se"] is None
    assert dp.iso_week("2027-01-01") == "2026-W53" and dp.iso_week("") is None


def test_the_replay_same_weeks_figure_matches_cohort_and_iso_week_and_year():
    summary = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
    f = dp.replay_same_weeks(summary, "cell:3D reclaim", ["2026-W39", "2026-W40"])
    # IN1 (+1.0) and IN2 (-0.5) only: WK41 is another week, CELL another cell,
    # YEAR the same week number a year earlier, OPEN still open (counted apart)
    assert f == {"n": 2, "avg": 0.25, "se": 0.75, "open": 1}
    assert dp.replay_same_weeks(summary, "market:nasdaq", ["2026-W40"])["n"] == 1
    assert dp.replay_same_weeks(summary, "grade:A", ["2026-W39"])["n"] == 0


def test_the_pack_prints_the_spread_and_says_when_there_is_no_replay_summary(tmp_path):
    closed = [_row(f"S{i:02d}", -1.0, "stop", entry_date="2026-09-22") for i in range(7)] + \
             [_row(f"T{i:02d}", 0.0, "time", entry_date="2026-09-29") for i in range(13)]
    root = _book(tmp_path, closed)
    buf = io.StringIO()
    dp.main([], root=str(root), out=buf)
    text = buf.getvalue()
    assert "replay same weeks: no committed replay summary yet" in text
    assert ("first read 2026-10-20 at 20 closes (line -0.30R): n=20 avg -0.350R | se 0.109R, "
            "2 ISO entry weeks (2026-W39, 2026-W40)") in text, text
    rd = root / "data" / "research" / "decision_replay"
    rd.mkdir(parents=True)
    (rd / "summary.json").write_text(REPLAY_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    buf = io.StringIO()
    dp.main([], root=str(root), out=buf)
    assert ("replay same weeks: n=2 avg +0.250R (se 0.750R), 1 still open in the replay (left out)"
            in buf.getvalue()), buf.getvalue()
    (rd / "summary.json").write_text(json.dumps({"schema": 2, "trades": []}), encoding="utf-8")
    buf = io.StringIO()
    dp.main([], root=str(root), out=buf)
    assert "replay same weeks: unreadable (" in buf.getvalue()

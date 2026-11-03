"""The journal's checkpoint strip is scripts/decision_pack.py, mirrored -- pinned.

Owner item 6 (2026-11-02): the journal states where each of the decision
pack's pre-registered checkpoints stands (PR-0..PR-8: NOT DUE, HOLD, TRIPPED,
CLEAR, or decided off the book). The verdicts are worked out in the browser
from the book the page already loads, by a JS mirror of
decision_pack.evaluate -- no new published file, no workflow change.

A mirror is only worth showing if it cannot drift, so three things are pinned:

  * THE REGISTER. journal.js carries decision_pack.PREREG as a JSON literal
    (between /* PREREG-BEGIN */ and /* PREREG-END */) plus a display `label`.
    Every other key must equal the frozen register exactly; moving a line on
    either side alone fails here, with both values in the message.
  * THE COHORT. PREREG_COHORT's tag and grade-label date are HC41's.
  * THE ARITHMETIC. tests/fixtures/checkpoint_cases.json holds shared cases --
    the live book as of 2026-11-02 and synthetic books built to sit on every
    edge (a read pinned to its day, the second read, the ASX gap, the grade
    label date, padded exit reasons, an average that ROUNDS onto its line).
    This file re-derives every expected verdict with decision_pack.evaluate;
    test/journal_checkpoints.test.js runs journal.js's prEvaluate over the
    same file. Both read one expectation, so the two evaluators agree or one
    of the suites goes red.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "public" / "js" / "journal.js"
CASES = ROOT / "tests" / "fixtures" / "checkpoint_cases.json"

_spec = importlib.util.spec_from_file_location("decision_pack", ROOT / "scripts" / "decision_pack.py")
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


def _js_register():
    src = JOURNAL.read_text(encoding="utf-8")
    m = re.search(r"/\* PREREG-BEGIN \*/\s*const PREREG = (\[.*?\]);\s*/\* PREREG-END \*/", src, re.S)
    assert m, "journal.js lost its PREREG-BEGIN/END block -- re-point this pin"
    return json.loads(m.group(1))


def test_the_journal_register_is_the_frozen_register():
    js = _js_register()
    assert [e["id"] for e in js] == [p["id"] for p in dp.PREREG], "the checkpoints or their order differ"
    for entry, frozen in zip(js, dp.PREREG):
        assert isinstance(entry.get("label"), str) and entry["label"].strip(), entry["id"]
        mirrored = {k: v for k, v in entry.items() if k != "label"}
        assert mirrored == frozen, (
            f"{frozen['id']}: journal.js says {mirrored} but scripts/decision_pack.py PREREG says "
            f"{frozen} -- the register is frozen; moving a line means editing both in plain sight")


def test_the_journal_cohort_is_hc41():
    src = JOURNAL.read_text(encoding="utf-8")
    m = re.search(r'const PREREG_COHORT = \{\s*tag:\s*"([^"]+)",\s*grade_label_fixed:\s*"([^"]+)"\s*\};', src)
    assert m, "journal.js lost PREREG_COHORT -- re-point this pin"
    assert (m.group(1), m.group(2)) == (dp.HC41["tag"], dp.HC41["grade_label_fixed"])


def test_the_mirror_reads_the_journals_own_rules_list():
    """prIsRules is decision_pack.is_rules: the site's MECHANICAL_EXITS after
    strip() and lower() (the list itself is pinned by test_decision_pack)."""
    src = JOURNAL.read_text(encoding="utf-8")
    assert re.search(r'const prIsRules = \(r\) => MECHANICAL_EXITS\.includes\(String\(r\.exit_reason \|\| ""\)'
                     r'\.trim\(\)\.toLowerCase\(\)\);', src), "prIsRules no longer mirrors is_rules()"


def _cases():
    return json.loads(CASES.read_text(encoding="utf-8"))


def test_decision_pack_produces_every_shared_expectation():
    doc = _cases()
    assert len(doc["cases"]) >= 20
    judged = [p for p in dp.PREREG if p["kind"] in ("live", "shadow")]
    assert any(p["kind"] == "shadow" for p in judged), "the day-14 shadow left the register"
    for case in doc["cases"]:
        for pr in judged:
            fn = dp.evaluate_shadow if pr["kind"] == "shadow" else dp.evaluate
            got = fn(pr, case["closed"], case.get("open", []))
            assert got == case["expect"][pr["id"]], (case["name"], pr["id"], got)


def test_the_live_snapshot_is_the_reads_the_owner_was_given():
    """The 2026-11-02 book: PR-0 tripped at its first read; PR-1 tripped at
    its first read too, and since 3 Nov (NEXT100 #5) the replay veto holds
    that trip for the final re-read at 40 closes; PR-2 sits between its lines
    waiting for 30 ASX closes, PR-3 is not due."""
    case = next(c for c in _cases()["cases"] if c["name"].startswith("live book"))
    want = {"PR-0": ("TRIPPED", "2026-10-28", 41, -0.271), "PR-1": ("HOLD", "2026-10-27", 21, -0.433),
            "PR-2": ("HOLD", "2026-10-30", 15, -0.399)}
    for pid, (verdict, day, n, avg) in want.items():
        e = case["expect"][pid]
        assert (e["verdict"], e["read_on"], e["read_n"], e["read_avg"]) == (verdict, day, n, avg), (pid, e)
    assert case["expect"]["PR-3"]["verdict"] == "NOT DUE"
    why = case["expect"]["PR-1"]["reason"]
    assert "replay veto" in why and "+0.054R" in why and "689" in why and "40 closes" in why, why
    assert "reason" not in case["expect"]["PR-2"], "a HOLD between the lines is not the veto's"


def test_the_3_nov_register_changes_are_marked_in_the_register():
    """NEXT100 #5 (owner-approved 3 Nov): PR-1 carries the veto read as data,
    hc4-2's live lines say they read by entry cohort, and nothing else moved
    -- hc4-1's lines and the PR-16 shadow keep the close-order read."""
    reg = {p["id"]: p for p in dp.PREREG}
    assert reg["PR-1"]["veto"] == {"read_on": "2026-11-03", "replay_avg": 0.054, "replay_n": 689,
                                   "min_avg": 0.05, "source": "3 Nov decision replay, hc4-2 code"}
    assert [p["id"] for p in dp.PREREG if "veto" in p] == ["PR-1"]
    for p in dp.PREREG:
        if "veto" in p:
            assert p.get("then") and dp.vetoes(p), p["id"]       # a veto needs its re-read
        want = "entry" if p.get("cycle") == "hc4-2" and p["kind"] == "live" else "close"
        assert dp.read_mode(p) == want, p["id"]
    assert "read" not in reg["PR-16"] and reg["PR-16"]["kind"] == "shadow"


def test_the_new_cases_sit_on_each_new_edge():
    """The shared cases carry the 3 Nov reads, so both evaluators are held to
    them: the veto's hold and both outcomes of its final re-read, a runner's
    horizon stamp, a cohort not due yet, entry order over close order, a hand
    close leaving the cohort, and a versus line before and after its versus
    entries are in."""
    names = {c["name"]: c["expect"] for c in _cases()["cases"]}
    hold = names["PR-1 veto: a first-read trip holds for the final re-read"]["PR-1"]
    assert (hold["verdict"], hold["n"], "40 closes" in hold["reason"]) == ("HOLD", 30, True)
    trip = names["PR-1 veto: the final re-read at 40 trips at -0.15"]["PR-1"]
    clear = names["PR-1 veto: the final re-read at 40 clears"]["PR-1"]
    assert (trip["verdict"], trip["read_n"], trip["read_avg"]) == ("TRIPPED", 40, -0.175)
    assert (clear["verdict"], clear["read_n"], clear["read_avg"]) == ("CLEAR", 40, -0.05)
    assert "final re-read" in trip["reason"] and "no second veto" in clear["reason"]
    runner = names["entry cohort: a runner's horizon stamp counts"]["PR-10"]
    assert (runner["verdict"], runner["read_avg"], runner["read_on"]) == ("HOLD", -0.25, "2026-12-08")
    wait = names["entry cohort: not due while an early entry is short of its horizon"]["PR-10"]
    assert (wait["verdict"], wait["entries"], wait["n"]) == ("NOT DUE", 25, 24)
    order = names["entry cohort: the first entries, not the first closes"]["PR-10"]
    assert (order["verdict"], order["read_avg"]) == ("CLEAR", 0.1)
    hand = names["entry cohort: a hand close before the horizon leaves the cohort"]["PR-10"]
    assert (hand["verdict"], hand["read_avg"], hand["read_on"]) == ("TRIPPED", -0.425, "2026-12-03")
    assert names["entry cohort: a versus line waits for its versus entries"]["PR-14"]["verdict"] == "NOT DUE"
    vs = names["entry cohort: a versus line trips once they are in"]["PR-14"]
    assert (vs["verdict"], vs["read_avg"], vs["versus_avg"], vs["read_on"]) == ("TRIPPED", -0.5, 0.0, "2026-12-07")


def test_the_rounding_cases_are_pythons_round():
    """journal.js pyRound must reproduce round(x, nd) -- exact value, ties to
    even -- because the evaluator compares ROUNDED averages with each line."""
    for x, nd, want in _cases()["round_cases"]:
        assert round(x, nd) == want, (x, nd, want)


def test_an_average_that_rounds_onto_a_line_is_a_case():
    """The edge a toFixed() mirror would get wrong: -0.2996 is above PR-1's
    -0.30 line raw, on it once rounded to three places, so it trips (and the
    replay veto then holds the trip for the re-read)."""
    names = {c["name"]: c for c in _cases()["cases"]}
    on = names["an average that ROUNDS onto the line trips"]["expect"]["PR-1"]
    off = names["an average that rounds off the line holds"]["expect"]["PR-1"]
    # PR-1's trips HOLD under the replay veto since 3 Nov: the trip shows as
    # the veto's reason; a read off the line holds with no reason at all
    assert (on["verdict"], on["read_avg"], "replay veto" in on.get("reason", "")) == ("HOLD", -0.3, True)
    assert (off["verdict"], off["read_avg"], "reason" in off) == ("HOLD", -0.299, False)

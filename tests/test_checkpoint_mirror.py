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
    assert len(doc["cases"]) >= 10
    live = [p for p in dp.PREREG if p["kind"] == "live"]
    for case in doc["cases"]:
        for pr in live:
            got = dp.evaluate(pr, case["closed"])
            assert got == case["expect"][pr["id"]], (case["name"], pr["id"], got)


def test_the_live_snapshot_is_the_reads_the_owner_was_given():
    """The 2026-11-02 book: PR-0 and PR-1 tripped at their first reads, PR-2
    sits between its lines waiting for 30 ASX closes, PR-3 is not due."""
    case = next(c for c in _cases()["cases"] if c["name"].startswith("live book"))
    want = {"PR-0": ("TRIPPED", "2026-10-28", 41, -0.271), "PR-1": ("TRIPPED", "2026-10-27", 21, -0.433),
            "PR-2": ("HOLD", "2026-10-30", 15, -0.399)}
    for pid, (verdict, day, n, avg) in want.items():
        e = case["expect"][pid]
        assert (e["verdict"], e["read_on"], e["read_n"], e["read_avg"]) == (verdict, day, n, avg), (pid, e)
    assert case["expect"]["PR-3"]["verdict"] == "NOT DUE"


def test_the_rounding_cases_are_pythons_round():
    """journal.js pyRound must reproduce round(x, nd) -- exact value, ties to
    even -- because the evaluator compares ROUNDED averages with each line."""
    for x, nd, want in _cases()["round_cases"]:
        assert round(x, nd) == want, (x, nd, want)


def test_an_average_that_rounds_onto_a_line_is_a_case():
    """The edge a toFixed() mirror would get wrong: -0.2996 is above PR-1's
    -0.30 line raw, on it once rounded to three places, so it trips."""
    names = {c["name"]: c for c in _cases()["cases"]}
    on = names["an average that ROUNDS onto the line trips"]["expect"]["PR-1"]
    off = names["an average that rounds off the line holds"]["expect"]["PR-1"]
    assert (on["verdict"], on["read_avg"]) == ("TRIPPED", -0.3)
    assert (off["verdict"], off["read_avg"]) == ("HOLD", -0.299)

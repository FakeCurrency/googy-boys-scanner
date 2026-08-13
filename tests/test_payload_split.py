"""The v5 payload split (owner-ruled payload diet, 2026-07-31).

Four families:

  1. `split_vivek` properties — the summary drops exactly the heavy groups,
     the lite plans are exactly the drift-pin tuple, the detail carries what
     moved, and THE INPUT IS NEVER MUTATED (the bot fence: run_market gets the
     in-memory rows before publish, so mutation here would be a trade change).
  2. The drift-pin itself — the owner's clarification, verbatim: the five
     lite fields are named and pinned so they cannot drift.
  3. The plumbing — run.py publishes the pair, the standalone vivek_run CLI
     re-joins the sidecar, both schema gates carry the pairing check, both
     staging lists carry the detail path.
  4. The fixtures — each e2e fixture summary has a paired detail fixture at
     the same schema_version and generated_at, produced by the same splitter.
"""
from __future__ import annotations

import copy
import json
import pathlib

from scanner import config, output

ROOT = pathlib.Path(__file__).resolve().parents[1]

VK = {
    "market": "asx", "schema_version": 5, "generated_at": "2026-07-31T10:00:00+10:00",
    "scanned": 3, "funnel": {"with_data": 3, "setups": 2},
    "results": [
        {"symbol": "BHP", "grade": "A+", "price": 41.2, "spark": [1, 2, 3],
         "plans": {"1W": {"armed": True, "entry_trigger": "reclaim",
                          "structural_tps": 2, "level_tf": "weekly",
                          "direction": "long", "entry": 41.0, "stop": 39.0,
                          "tp1": 43.0, "why": "long prose"}},
         "detail": {"setup_type": "reclaim"}, "analysis": "words",
         "markers": {"1D": []}},
        {"symbol": "CBA", "grade": "A", "price": 110.0, "plans": None},
    ],
}


def test_summary_drops_exactly_the_heavy_groups_and_keeps_the_rest():
    s, d = output.split_vivek(VK)
    row = s["results"][0]
    for heavy in config.VIVEK_DETAIL_ROW_FIELDS:
        if heavy == "plans":
            continue                       # present but LITE — next test
        assert heavy not in row, heavy
    assert row["spark"] == [1, 2, 3]       # first-paint field stays
    assert row["grade"] == "A+" and row["price"] == 41.2
    assert d["rows"]["BHP"]["analysis"] == "words"
    assert d["rows"]["BHP"]["plans"]["1W"]["entry"] == 41.0


def test_lite_plans_are_exactly_the_drift_pin_tuple():
    s, _ = output.split_vivek(VK)
    p = s["results"][0]["plans"]["1W"]
    assert set(p) <= set(config.VIVEK_SUMMARY_PLAN_FIELDS)
    assert p["armed"] is True and p["entry_trigger"] == "reclaim"
    assert p["structural_tps"] == 2
    assert "entry" not in p and "why" not in p


def test_the_drift_pin_tuple_is_the_five_owner_named_fields():
    assert config.VIVEK_SUMMARY_PLAN_FIELDS == (
        "armed", "entry_trigger", "structural_tps", "level_tf", "direction")
    assert config.VIVEK_DETAIL_ROW_FIELDS == ("plans", "detail", "analysis", "markers")


def test_split_never_mutates_its_input_the_bot_fence():
    before = copy.deepcopy(VK)
    output.split_vivek(VK)
    assert VK == before, "split_vivek mutated the in-memory payload the bot reads"


def test_pairing_stamps_match_and_planless_rows_survive():
    s, d = output.split_vivek(VK)
    assert d["schema_version"] == s["schema_version"] == 5
    assert d["generated_at"] == s["generated_at"]
    assert d["market"] == "asx"
    cba = s["results"][1]
    assert cba["symbol"] == "CBA" and "CBA" not in d["rows"]


def test_run_py_publishes_the_pair_not_the_monolith():
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "output.write_vivek_pair(vk, args.out, market_key)" in src
    assert 'output.write(vk, args.out, name=f"{market_key}_vivek")' not in src


def test_the_standalone_cli_rejoins_the_detail_sidecar():
    src = (ROOT / "scanner" / "broker" / "vivek_run.py").read_text(encoding="utf-8")
    assert '_vivek_detail.json' in src, \
        "the CLI reads the published summary; without the re-join the bot " \
        "would build tickets from LITE plans"


def test_both_schema_gates_carry_the_pairing_check():
    for wf in ("scan.yml", "crypto_bot.yml"):
        src = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        assert "_vivek_detail.json" in src, wf
        assert src.count("generated_at") >= 2, f"{wf}: pairing check must compare stamps"


def test_both_staging_lists_carry_the_detail_path():
    scan = (ROOT / ".github" / "workflows" / "scan.yml").read_text(encoding="utf-8")
    crypto = (ROOT / ".github" / "workflows" / "crypto_bot.yml").read_text(encoding="utf-8")
    assert "public/data/${m}_vivek_detail.json" in scan
    assert "public/data/crypto_vivek_detail.json" in crypto


def test_every_fixture_summary_has_a_paired_detail_fixture():
    fx = ROOT / "test" / "e2e" / "fixtures" / "data"
    for m in ("asx", "nasdaq", "crypto"):
        s = json.loads((fx / f"{m}_vivek.json").read_text(encoding="utf-8"))
        d = json.loads((fx / f"{m}_vivek_detail.json").read_text(encoding="utf-8"))
        assert s.get("schema_version") == config.VIVEK_SCHEMA_VERSION, m
        assert d.get("schema_version") == s.get("schema_version"), m
        assert d.get("generated_at") == s.get("generated_at"), m
        # fixture summaries must be genuinely lite — the e2e walks the real
        # lazy path only if the heavy fields are truly absent
        for r in (s.get("results") or [])[:5]:
            assert "analysis" not in r and "markers" not in r, m
            for p in (r.get("plans") or {}).values():
                assert set(p) <= set(config.VIVEK_SUMMARY_PLAN_FIELDS), m


# ── 5. the pair is published COMPACT (2026-08-13) ────────────────────────────
# The diet's ~0.4 MB summary target had been read against a PRETTY-PRINTED file
# and judged missed: live ASX measured 742.9 KB on disk against 448.5 KB of
# actual content — 39.6% of the deck's first paint was indentation. The split
# had hit its number all along. These pins hold the whitespace out.


def test_the_published_pair_carries_no_pretty_printing(tmp_path):
    output.write_vivek_pair(copy.deepcopy(VK), tmp_path, "asx")
    for name in ("asx_vivek.json", "asx_vivek_detail.json"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "\n" not in text, f"{name} is pretty-printed again"
        assert '", "' not in text and '": ' not in text, f"{name} carries padded separators"


def test_compacting_changed_ONLY_whitespace(tmp_path):
    """The load-bearing half: same bytes of meaning, fewer bytes of file.

    A publisher that silently dropped or reordered a field would also be
    smaller, so size alone proves nothing. This re-publishes the same payload
    pretty and compact and asserts the PARSED results are equal.
    """
    pretty = tmp_path / "pretty"
    compact = tmp_path / "compact"
    pretty.mkdir()
    summary, detail = output.split_vivek(copy.deepcopy(VK))
    output.write_json(pretty / "asx_vivek.json", summary)               # indent=2 default
    output.write_json(pretty / "asx_vivek_detail.json", detail)
    output.write_vivek_pair(copy.deepcopy(VK), compact, "asx")
    for name in ("asx_vivek.json", "asx_vivek_detail.json"):
        a = json.loads((pretty / name).read_text(encoding="utf-8"))
        b = json.loads((compact / name).read_text(encoding="utf-8"))
        assert a == b, f"{name}: compacting changed the content, not just the layout"
        assert (compact / name).stat().st_size < (pretty / name).stat().st_size


def test_there_is_deliberately_NO_byte_BUDGET_on_the_live_payload():
    """A size budget read off public/data/ would be a gate on the TAPE.

    That is the Lighthouse-budget failure exactly (see CLAUDE.md, "The
    Lighthouse budget was measuring the TAPE"): the file grows with how many
    names set up that day, test.yml's path filter excludes public/data/**, and
    the red lands on whoever next pushes CODE. The pins above are properties of
    the WRITER and are size-independent on purpose. Do not "complete" them with
    an assertion about the size of a live file.
    """
    src = (ROOT / "tests" / "test_payload_split.py").read_text(encoding="utf-8")
    body = src.split("def test_there_is_deliberately")[0]
    # Naming the path in a staging-list assertion is fine; OPENING it is not.
    for reader in ('ROOT / "public"', '"public/data/' + '" +', "open(\"public/data"):
        assert reader not in body, (
            f"a test in this file now reads the live payload ({reader}) - "
            "re-read this docstring before adding a size assertion"
        )

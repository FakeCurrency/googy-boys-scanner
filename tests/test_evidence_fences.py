"""Evidence-surface fences, hardened (owner item 2, 2026-07-31).

The four report-only surfaces (arriving list, funnel history, Specs->VIVEK
graduation, HORIZON sector history) each carry their own fence tests beside
their mechanics. THIS suite is the layer above them: one central map of every
evidence artifact and module, swept against the whole scanner/broker tree, so
the isolation guarantees hold as the codebase evolves — an addition ANYWHERE
that points an evidence surface at a decision path goes red here even if the
per-surface suite never sees it.

Calibrated against the tree as it stands, deliberately: the sweeps pin
artifact/module NAMES (``_arriving``, ``funnel_history``, ``specgrad``, ...)
rather than English words — broker prose legitimately says "arriving" twice
and the bot's own trend/range "regime filter" shares a word with regime.py,
and a fence that cries wolf gets deleted, which is worse than no fence.

Also here: the contracts the per-surface suites left unpinned — the funnel's
append-only property under interleaved appends, specgrad's single-write and
read-only-input behaviour, the arriving writer's structural row contract, and
the v5 split/re-join round trip (nothing the split moves is ever lost).
"""
from __future__ import annotations

import copy
import json
import pathlib
import re

import pytest

from scanner import config, funnelhistory as fh, output, specgrad

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _scanner_files():
    return [p for p in sorted(ROOT.glob("scanner/**/*.py")) if "__pycache__" not in str(p)]


def _broker_files():
    return [p for p in sorted(ROOT.glob("scanner/broker/**/*.py")) if "__pycache__" not in str(p)]


def _rel(p):
    return str(p.relative_to(ROOT)).replace("\\", "/")


# ── THE MAP — every evidence artifact, its allowed scanner-side mentions ─────
# ⊆ semantics: files may stop mentioning a name, but a NEW mention anywhere
# outside the allowed set is a leak toward a decision path and fails here.

ARTIFACT_MAP = {
    "_arriving":       {"scanner/config.py", "scanner/scan.py"},
    "arriving.json":   {"scanner/config.py", "scanner/scan.py"},
    "funnel_history":  {"scanner/config.py", "scanner/funnelhistory.py"},
    "spec_graduation": {"scanner/config.py", "scanner/specgrad.py"},
    "sector_history":  {"scanner/config.py", "scanner/sectorbreadth.py"},
}

MODULE_MAP = {  # module name -> the ONE file allowed to import it
    "funnelhistory": "scanner/run.py",
    "specgrad":      "scanner/spec_run.py",
    "sectorbreadth": "scanner/run.py",
    "regime":        "scanner/run.py",
}


@pytest.mark.parametrize("needle,allowed", sorted(ARTIFACT_MAP.items()))
def test_the_artifact_name_never_leaves_its_allowed_files(needle, allowed):
    hits = [_rel(p) for p in _scanner_files()
            if needle in p.read_text(encoding="utf-8") and _rel(p) not in allowed]
    assert hits == [], (
        f"evidence artifact '{needle}' leaked toward a decision path: {hits} — "
        f"report-only files may be read by their writer and displayed by the "
        f"front end, never consumed inside scanner/broker")


@pytest.mark.parametrize("mod,importer", sorted(MODULE_MAP.items()))
def test_the_module_is_imported_by_its_one_publish_file_alone(mod, importer):
    # Catches every real form: `from . import specgrad`, `import regime as _r`,
    # `from scanner import funnelhistory`. \b stops `regime` matching the
    # bot's unrelated trend/range "regime filter" prose.
    pat = re.compile(rf"import\s+{mod}\b")
    importers = [_rel(p) for p in _scanner_files()
                 if p.name != f"{mod}.py" and pat.search(p.read_text(encoding="utf-8"))]
    assert importers == [importer], (
        f"{mod} must be reachable from {importer} alone, found: {importers}")


def test_broker_never_names_any_evidence_artifact():
    # The bot must not know these FILES exist. Artifact names only: module
    # names are policed by the import fence above (whose glob includes
    # broker/**), and broker prose legitimately cross-references a module's
    # DESIGN twice today ("same reason as sectorbreadth's ping memory") — a
    # fence that fails on rationale comments gets deleted, which is worse.
    needles = ("_arriving", "arriving.json", "funnel_history",
               "spec_graduation", "sector_breadth", "sector_history",
               "regime.json")
    hits = []
    for p in _broker_files():
        text = p.read_text(encoding="utf-8")
        hits += [f"{p.name}: {n}" for n in needles if n in text]
    assert hits == [], f"the bot has learned an evidence artifact exists: {hits}"


def test_the_only_cross_module_calls_are_the_two_publish_hooks():
    # Attribute-level fence: the WRITER modules expose one entry point each to
    # the rest of the tree. Someone importing funnelhistory to READ the file
    # via a helper would pass the import fence (run.py is allowed) — this is
    # the pin that catches the second function creeping into use.
    # (?!py\b) skips prose naming the FILE, "funnelhistory.py".
    uses = {"funnelhistory": set(), "specgrad": set()}
    for p in _scanner_files():
        if p.name in ("funnelhistory.py", "specgrad.py"):
            continue
        text = p.read_text(encoding="utf-8")
        for mod in uses:
            uses[mod] |= set(re.findall(rf"\b{mod}\.(?!py\b)(\w+)", text))
    assert uses["funnelhistory"] <= {"append"}, uses["funnelhistory"]
    assert uses["specgrad"] <= {"update"}, uses["specgrad"]


# ── arriving list: the decision-path exclusion, structurally ─────────────────

def _arriving_append_block():
    src = (ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    at = src.index("arriving.append({")
    end = src.index("})", at)
    return src[at:end]


def test_arriving_rows_are_built_without_any_plan_or_grade_field():
    # The fence is structural: the rows CANNOT carry what the ruling excluded,
    # because the writer never puts it there. Pinned at the source so a field
    # added to the append block fails before it ever ships.
    block = _arriving_append_block()
    for banned in ('"grade"', '"plans"', '"entry"', '"stop"', '"target"',
                   '"score"', '"tp1"', '"analysis"'):
        assert banned not in block, (
            f"{banned} in the arriving row would turn evidence into a setup — "
            "the ruling excluded grade/plan/entry fields by construction")
    for required in ('"symbol"', '"rvol"', '"turnover_today"', '"turnover_avg20"'):
        assert required in block, f"arriving row lost {required}"


@pytest.mark.parametrize("market", ["asx", "nasdaq", "crypto"])
def test_the_committed_arriving_artifacts_honour_the_row_contract(market):
    p = ROOT / "public" / "data" / f"{market}_arriving.json"
    if not p.exists():
        pytest.skip(f"no committed {market} arriving artifact")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert "rule" in d and "results" in d
    for r in d["results"]:
        assert not ({"grade", "plans", "entry", "stop", "target"} & set(r)), (
            f"{market} arriving row {r.get('symbol')} carries plan/grade fields")


def test_the_funnel_payload_carries_only_the_arriving_count():
    # The rows live in the fenced file; the scan payload gets a NUMBER. If the
    # rows themselves ever rode into <m>_vivek.json they would be one
    # r.get() away from every consumer of the scan.
    src = (ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    m = re.search(r'"arriving":\s*([^,\n]+)', src)
    assert m and "len(arriving)" in m.group(1), (
        f'the funnel must publish len(arriving), found: {m.group(1) if m else None}')


# ── funnel history: append-only under interleaved writers ────────────────────

def _vk(published, ts):
    return {"scanned": 100, "generated_at": ts,
            "funnel": {"with_data": 90, "setups": published,
                       "illiquid_setup": 5, "arriving": 1}}


def test_interleaved_appends_never_disturb_any_earlier_cell(tmp_path):
    """The strong form of append-only: six appends across two markets, and
    after every one of them each previously-observed column is a strict
    PREFIX of the new state — no rewrite, no reorder, no cross-market bleed."""
    snapshots = []
    for i in range(6):
        market = ("asx", "crypto")[i % 2]
        fh.append(market, _vk(100 + i, f"2026-07-{20 + i:02d}T01:00:00+00:00"), tmp_path)
        snapshots.append(copy.deepcopy(
            json.loads((tmp_path / "funnel_history.json").read_text())["markets"]))
    final = snapshots[-1]
    for step, snap in enumerate(snapshots[:-1]):
        for market, cols in snap.items():
            for col, values in cols.items():
                assert final[market][col][:len(values)] == values, (
                    f"append rewrote history: step {step} {market}.{col}")


def test_the_history_is_published_through_the_integrity_writer():
    src = (ROOT / "scanner" / "funnelhistory.py").read_text(encoding="utf-8")
    assert "output.write_json(" in src
    assert "json.dump(" not in src and ".write_text(" not in src, (
        "a hand-rolled writer here loses atomicity + NaN-nulling (project rule 7)")


# ── spec graduation: report-only, behaviourally ──────────────────────────────

def test_update_writes_exactly_one_file_and_it_is_the_registry(tmp_path, monkeypatch):
    written = []
    real = output.write_json

    def spy(path, payload, **kw):
        written.append(pathlib.Path(path).name)
        return real(path, payload, **kw)

    monkeypatch.setattr(specgrad.output, "write_json", spy)
    specgrad.update("asx", tmp_path, {"generated_at": "2026-07-31T20:00:00+10:00",
                                      "results": [{"symbol": "RHT", "price": 0.058}]})
    assert written == [config.SPEC_GRAD_FILE], (
        f"specgrad wrote {written} — the registry is its ONLY output")


def test_update_reads_the_vivek_artifact_without_touching_it(tmp_path):
    vp = tmp_path / "asx_vivek.json"
    output.write_json(vp, {"schema_version": 5, "market": "asx",
                           "generated_at": "2026-07-31T12:00:00+10:00",
                           "results": [{"symbol": "RHT", "price": 0.61, "grade": "B+"}]})
    before = vp.read_bytes()
    specgrad.update("asx", tmp_path, {"generated_at": "2026-07-31T20:00:00+10:00",
                                      "results": []})
    assert vp.read_bytes() == before, "the graduation check must be a pure read"


# ── v5 pairing: the split loses nothing, ever ────────────────────────────────

def _rich_vk():
    return {
        "schema_version": 5, "market": "asx",
        "generated_at": "2026-07-31T12:40:24+10:00", "scanned": 4,
        "results": [
            {"symbol": "FULL", "price": 1.0, "grade": "A+",
             "plans": {"1D": {"armed": True, "entry_trigger": 1.01,
                              "structural_tps": [1.1], "level_tf": "1W",
                              "direction": "long", "sl": 0.95, "notes": "heavy"}},
             "detail": {"deep": [1, 2]}, "analysis": "words",
             "markers": [{"t": "x"}]},
            {"symbol": "QUIET", "price": 2.0, "grade": "WATCH",
             "plans": None, "detail": None, "analysis": None, "markers": None},
            {"symbol": "FALSY", "price": 3.0, "grade": "A",
             "plans": {}, "detail": [], "analysis": "", "markers": 0},
            "not-a-dict-row",
        ],
    }


def test_the_split_rejoin_round_trip_restores_every_non_none_field():
    """The contract the bot-parity CLI re-join stands on: summary row updated
    with its detail-sidecar row must restore the ORIGINAL row exactly for
    every non-None field — the split relocates, it never discards."""
    vk = _rich_vk()
    summary, detail = output.split_vivek(vk)
    heavy = set(config.VIVEK_DETAIL_ROW_FIELDS)
    originals = [r for r in vk["results"] if isinstance(r, dict)]
    for orig, srow in zip(originals, summary["results"]):
        rejoined = dict(srow)
        rejoined.update(detail["rows"].get(orig["symbol"], {}))
        for k, v in orig.items():
            if v is None and k in heavy:
                continue          # None-valued heavy keys are dropped, by design
            assert k in rejoined and rejoined[k] == v, (
                f"{orig['symbol']}.{k} lost or altered by the split round trip")


def test_falsy_but_not_none_heavy_values_travel_to_the_sidecar_not_the_void():
    # r.get(k) is not None is the guard — {} / [] / "" / 0 are real content
    # and must survive. A truthiness guard here would silently discard them.
    _, detail = output.split_vivek(_rich_vk())
    assert detail["rows"]["FALSY"] == {"plans": {}, "detail": [],
                                       "analysis": "", "markers": 0}


def test_summary_rows_never_carry_a_heavy_key():
    summary, _ = output.split_vivek(_rich_vk())
    heavy = set(config.VIVEK_DETAIL_ROW_FIELDS) - {"plans"}   # plans is re-added LITE
    for r in summary["results"]:
        assert not (heavy & set(r)), f"heavy key leaked into summary row {r.get('symbol')}"
        if "plans" in r:
            for tf, plan in r["plans"].items():
                assert set(plan) <= set(config.VIVEK_SUMMARY_PLAN_FIELDS), (
                    f"summary plan {tf} carries non-lite fields: {set(plan)}")


def test_plans_is_pinned_inside_the_heavy_tuple():
    # The split's lite-pruning special case hangs off "plans" being a heavy
    # row field. Remove it from the tuple and summaries silently ship FULL
    # plans — the diet undone with every test above still green.
    assert "plans" in config.VIVEK_DETAIL_ROW_FIELDS


def test_the_pair_always_shares_its_stamps(tmp_path):
    vk = _rich_vk()
    output.write_vivek_pair(vk, tmp_path, "asx")
    s = json.loads((tmp_path / "asx_vivek.json").read_text(encoding="utf-8"))
    d = json.loads((tmp_path / "asx_vivek_detail.json").read_text(encoding="utf-8"))
    assert (s["schema_version"], s["generated_at"]) == \
           (d["schema_version"], d["generated_at"]), (
        "the pairing stamps are what the CI gates verify — they must be written equal")

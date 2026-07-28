"""Publish integrity — TOP100 #62 and #64 (2026-07-28).

Two defects that shared one line, `path.write_text(json.dumps(payload, ...))`:

**#62.** `json.dumps` defaults to `allow_nan=True` and emits a bare `NaN` token
for a non-finite float. That is not JSON. `response.json()` rejects the WHOLE
file, so one thin sector with no median, or one symbol whose ATR came back NaN,
blanked an entire market page instead of showing one empty cell. The fix nulls
non-finite floats on the way out and keeps `allow_nan=False` behind that as a
backstop — sanitise-then-assert, because flipping the flag alone would have
turned a quietly-broken page into a hard scan failure.

**#64.** `write_text` truncates first and writes second. A crash, a runner
timeout or a full disk mid-write publishes a fragment that parses as nothing.
Eleven publishers were doing this; four more had already hand-rolled the
temp+`os.replace` fix locally, in four near-identical copies. `output.write_json`
is now the single publisher and the copies delegate to it.

The last test in this file is the one that matters in a year: it re-derives
every committed artefact through the helper and demands the bytes match, so a
future formatting change to the publisher shows up here rather than as a 5 MB
whole-file diff on the next scan commit.
"""

import ast
import json
import math
import pathlib

import numpy as np
import pytest

from scanner import journal_common, output

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── #62 · non-finite floats never reach the browser ──────────────────────────

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_publish_as_null(bad):
    text = output.dumps({"atr": bad, "close": 1.5})
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text) == {"atr": None, "close": 1.5}


def test_a_single_nan_does_not_take_the_rest_of_the_payload_down():
    """The actual production shape: one bad row among many good ones.

    Under the old writer this file failed JSON.parse in full, so every row on
    the page vanished because of one. The point of nulling rather than raising
    is that the other 2,211 names still render.
    """
    payload = {"market": "asx", "results": [
        {"symbol": "BHP", "grade": "A+", "atr": 1.23},
        {"symbol": "XYZ", "grade": "A", "atr": float("nan")},
        {"symbol": "CBA", "grade": "B", "atr": 4.56},
    ]}
    back = json.loads(output.dumps(payload))
    assert [r["symbol"] for r in back["results"]] == ["BHP", "XYZ", "CBA"]
    assert back["results"][1]["atr"] is None
    assert back["results"][2]["atr"] == 4.56


def test_sanitising_reaches_every_nesting_level_including_tuples():
    payload = {"a": [{"b": (1.0, float("nan"))}], "c": {"d": {"e": [float("inf")]}}}
    assert json.loads(output.dumps(payload)) == {
        "a": [{"b": [1.0, None]}], "c": {"d": {"e": [None]}}}


def test_numpy_float64_nan_is_caught_by_the_walk():
    """np.float64 IS a float subclass, so `_finite` sees it directly."""
    assert isinstance(np.float64(1.0), float)
    assert json.loads(output.dumps({"v": np.float64("nan")})) == {"v": None}


def test_numpy_float32_nan_is_caught_by_the_default_hook():
    """np.float32 is NOT a float subclass — it reaches json as un-encodable and
    is handled by `_default`. This is the gap a sanitising walk alone leaves."""
    assert not isinstance(np.float32(1.0), float)
    assert json.loads(output.dumps({"v": np.float32("nan")})) == {"v": None}
    assert json.loads(output.dumps({"v": np.float32(2.5)})) == {"v": 2.5}


def test_numpy_ints_stay_ints_rather_than_becoming_floats():
    """`_default` goes through `.item()`, not `float()`. Casting everything
    through float would republish every count in every file as `3.0`."""
    text = output.dumps({"n": np.int64(3), "ok": np.bool_(True)}, indent=None)
    assert text == '{"n": 3, "ok": true}'


def test_an_object_json_cannot_encode_still_raises():
    """The backstop must stay loud. Coercing the unknown to str() would ship
    something that reads like data — an ndarray in a payload is a producer bug
    and this is where it gets found."""
    with pytest.raises(TypeError):
        output.dumps({"frame": np.array([1.0, 2.0])})
    with pytest.raises(TypeError):
        output.dumps({"when": object()})


def test_a_one_element_array_raises_rather_than_flattening_to_a_scalar():
    """Regression, found by the atomicity test below failing to raise.

    `.item()` succeeds on a one-element ndarray as happily as on a scalar, so
    the first cut of `_default` published `{"prices": np.array([1.0])}` as
    `1.0` — a list quietly turned into a number. A publisher whose job is
    stopping corrupt output must not introduce a subtler kind of it.
    """
    with pytest.raises(TypeError):
        output.dumps({"prices": np.array([1.0])})
    # ...while a genuine 0-d value still converts, which is the case the hook exists for.
    assert json.loads(output.dumps({"v": np.array(1.5)})) == {"v": 1.5}


def test_allow_nan_is_never_left_on():
    """Guards the sanitise-then-assert contract from the inside: if a future
    edit drops `_finite` but keeps `allow_nan=False`, the tests above still
    pass by raising. This pins the flag itself, so the pair is checked from
    both ends.

    Read with `ast` rather than by grepping the source, because the module
    docstring necessarily says the words "allow_nan=True" while explaining the
    default it is protecting against — a substring check reads that prose as
    code and fails.
    """
    tree = ast.parse((_ROOT / "scanner" / "output.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and ast.unparse(n.func) == "json.dumps"]
    assert len(calls) == 1, "output.py should build published text in exactly one place"
    flags = {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords
             if k.arg == "allow_nan"}
    assert flags == {"allow_nan": False}


def test_the_callers_payload_is_not_mutated():
    """run.py keeps using `vk` after publishing the slim price file from it."""
    inner = {"atr": float("nan")}
    payload = {"rows": [inner]}
    output.dumps(payload)
    assert math.isnan(inner["atr"])
    assert payload["rows"][0] is inner


# ── #64 · a half-written file is never published ─────────────────────────────

def test_the_swap_is_atomic_not_a_truncate_and_rewrite(tmp_path):
    """The end-to-end property, not a proxy for it.

    A reader holding the file open across a publish must still see the OLD
    contents in full — that is what `os.replace` guarantees and what
    `write_text` cannot, because it truncates the existing inode. On the old
    writer the handle below reads a mangled file.
    """
    path = tmp_path / "market.json"
    output.write_json(path, {"generation": 1})
    with path.open(encoding="utf-8") as reader_holding_it_open:
        output.write_json(path, {"generation": 2, "padding": "x" * 10_000})
        assert json.load(reader_holding_it_open) == {"generation": 1}
    assert json.loads(path.read_text(encoding="utf-8"))["generation"] == 2


def test_a_failed_serialisation_leaves_the_previous_file_intact(tmp_path):
    """`allow_nan=False` made a raise reachable, so this has to hold: the dump
    completes before anything touches the destination."""
    path = tmp_path / "market.json"
    output.write_json(path, {"generation": 1})
    with pytest.raises(TypeError):
        output.write_json(path, {"frame": np.array([1.0])})
    assert json.loads(path.read_text(encoding="utf-8")) == {"generation": 1}


def test_no_temp_file_is_left_behind(tmp_path):
    output.write_json(tmp_path / "market.json", {"ok": True})
    assert [p.name for p in tmp_path.iterdir()] == ["market.json"]


def test_parent_directories_are_created(tmp_path):
    path = tmp_path / "deep" / "deeper" / "market.json"
    assert output.write_json(path, {"ok": True}) == path
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_published_json_is_lf_pinned_on_every_platform(tmp_path, monkeypatch):
    """Cross-platform behaviour, asserted from Linux.

    The published files are committed by the scan workflow. Python text mode
    translates "\\n" to os.linesep unless told otherwise, so a local Windows run
    of the scanner would rewrite every artefact with CRLF and diff all 5 MB of
    them. `write_json` pins newline="\\n"; this is the only way to check that
    from a runner where the default happens to be LF anyway.
    """
    seen = {}
    real = journal_common.atomic_write

    def spy(path, payload, **kw):
        seen.update(kw)
        return real(path, payload, **kw)

    monkeypatch.setattr(output, "atomic_write", spy)
    output.write_json(tmp_path / "lf_probe.json", {"ok": True})
    assert seen.get("newline") == "\n"


def test_atomic_write_default_newline_is_unchanged(tmp_path):
    """The journals were not part of this change and must not have moved."""
    path = tmp_path / "j.json"
    journal_common.atomic_write(path, "a\nb")
    assert path.read_bytes() == b"a\nb"          # identity on POSIX, as before


# ── the invariant: one publisher, repo-wide ──────────────────────────────────

def test_no_module_publishes_json_without_going_through_output():
    """The construct sweep. `write_text(json.dumps(...))` and
    `fh.write(json.dumps(...))` are both non-atomic publishes; after this change
    neither shape should exist anywhere under scanner/.

    Bans the SHAPE rather than a spelling: any new module that hand-rolls a
    publish trips this, which is the point — four modules had already
    hand-rolled the same five-line fix independently before anyone noticed.
    """
    offenders = []
    for py in sorted((_ROOT / "scanner").rglob("*.py")):
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue                          # a comment quoting the old form
            if "write_text(json.dumps" in line or ".write(json.dumps" in line:
                offenders.append(f"{py.relative_to(_ROOT)}:{n}: {stripped}")
    assert not offenders, (
        "non-atomic JSON publish — use scanner.output.write_json:\n  "
        + "\n  ".join(offenders))


def test_output_is_the_only_module_that_calls_json_dumps_to_publish():
    """Companion to the sweep above: nothing else should be *building* the
    published text either, because that is where allow_nan creeps back in."""
    src = (_ROOT / "scanner" / "output.py").read_text(encoding="utf-8")
    assert src.count("json.dumps(") == 1, "output.py should have exactly one dumps call"


# The two-step form the sweep above cannot see: `payload = json.dumps(...)` on
# one line and `tmp.write_text(payload)` on another. Exactly two survive, both
# argued for in output.py's docstring — already atomic (#64 n/a) and carrying no
# float at all (#62 n/a). Anything else is a new hand-rolled publisher.
_EXEMPT_HAND_ROLLED = {
    ("scanner/universe.py", "_save_universe_cache"),
    ("scanner/sectorcache.py", "save_cache"),
}


def _functions_that_hand_roll_a_write(py: pathlib.Path):
    """Names of functions in `py` that call BOTH `.write_text(` and `os.replace(`.

    Matched on the pair rather than on either half: `write_text` alone is a
    perfectly ordinary write (a markdown report, a temp scratch file) and
    `os.replace` alone is a rename. Together, in one function, they are the
    five-line atomic-publish pattern this module exists to centralise.
    """
    tree = ast.parse(py.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.dump(node)
        if "attr='write_text'" in body and "attr='replace'" in body:
            out.append(node.name)
    return out


def test_only_the_two_argued_writers_still_hand_roll_an_atomic_publish():
    """The exemption is a DECISION and this is where it is recorded.

    Both survivors write a payload of strings and ints only — a ticker list and
    a `{SYMBOL: sector}` map — so #62's NaN hazard cannot arise in them, and both
    already do the temp+`os.replace` swap, so #64 does not either. Converting
    them would be churn on the one part of the tree where the old pattern is
    harmless.

    `spec_run` is the reason this test exists rather than a comment. It was
    waved through on exactly the "already atomic" half of that argument and kept
    `allow_nan=True` over rounded OHLC floats, so one NaN bar would have blanked
    a whole chart page. A third writer must be argued for on BOTH halves, out
    loud, rather than inheriting an exemption by resembling one.
    """
    found = set()
    for py in sorted((_ROOT / "scanner").rglob("*.py")):
        rel = py.relative_to(_ROOT).as_posix()
        for name in _functions_that_hand_roll_a_write(py):
            found.add((rel, name))
    assert found == _EXEMPT_HAND_ROLLED, (
        "hand-rolled atomic publishers changed — use scanner.output.write_json "
        f"unless BOTH #62 and #64 are inapplicable:\n  new: {sorted(found - _EXEMPT_HAND_ROLLED)}"
        f"\n  gone: {sorted(_EXEMPT_HAND_ROLLED - found)}")


@pytest.mark.parametrize("rel,fn", sorted(_EXEMPT_HAND_ROLLED))
def test_an_exempt_writer_loses_its_exemption_if_it_stops_being_atomic(rel, fn):
    """Half the exemption is "#64 does not apply because it is already atomic".

    That half is a property of the code, not a promise, so it is checked here:
    drop the `os.replace` and this fails rather than leaving a non-atomic writer
    sitting on a grandfathered pass.
    """
    assert fn in _functions_that_hand_roll_a_write(_ROOT / rel)


# ── the formatting guard ─────────────────────────────────────────────────────

# (repo-relative path, dumps kwargs used by its call site, trailing newline)
_ARTEFACTS = [
    ("public/data/asx_vivek.json",              {}, False),
    ("public/data/nasdaq_vivek.json",           {}, False),
    ("public/data/crypto_vivek.json",           {}, False),
    ("public/data/asx_prices.json",             {"indent": None, "separators": (",", ":")}, True),
    ("public/data/nasdaq_prices.json",          {"indent": None, "separators": (",", ":")}, True),
    ("public/data/crypto_prices.json",          {"indent": None, "separators": (",", ":")}, True),
    ("public/data/sectors.json",                {}, False),
    ("public/data/fx.json",                     {}, True),
    ("public/data/bot_rules.json",              {}, True),
    ("public/data/vivek_backtest.json",         {}, False),
    ("public/data/phasemap/alert_history.json", {"indent": 1}, True),
    ("public/data/regime.json",                 {"indent": None, "separators": (",", ":")}, True),
    ("public/data/sector_breadth.json",         {"indent": None, "separators": (",", ":")}, True),
    ("journal/confluence_state.json",           {"sort_keys": True}, True),
    # spec_run's two writes — converted after the first pass had classified them
    # as "already atomic, leave alone". Atomic was only #64's half; both kept
    # allow_nan over float payloads. Listed here because they are committed by
    # phasemap.yml, so a formatting drift would land as a whole-file diff.
    ("public/data/asx_spec.json",               {"indent": 1, "ensure_ascii": False}, True),
    ("public/data/nasdaq_spec.json",            {"indent": 1, "ensure_ascii": False}, True),
]


@pytest.mark.parametrize("rel,kwargs,newline", _ARTEFACTS,
                         ids=[a[0].rsplit("/", 1)[-1] for a in _ARTEFACTS])
def test_committed_artefact_round_trips_byte_for_byte(rel, kwargs, newline):
    """Every published file, re-derived through the new publisher with the
    kwargs its call site passes, must come back byte-identical.

    This is the guard that lets the change be reviewed as a behaviour fix: the
    scan workflow commits these files, so any formatting drift in `write_json`
    would land as a whole-file diff burying whatever the run actually found.
    """
    path = _ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present in this checkout")
    original = path.read_text(encoding="utf-8")
    rebuilt = output.dumps(json.loads(original), **kwargs) + ("\n" if newline else "")
    assert rebuilt == original, f"{rel} would be rewritten by write_json"

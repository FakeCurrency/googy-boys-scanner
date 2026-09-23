"""THE MOMENTUM FENCES -- what makes a fourth lens non-breaking.

The governing principle (HANDOFF_2026-09-22 Part 17.0) is that the lens must
be deletable tomorrow in one commit, because removability and
non-breakingness are the same property.  TURTLE proved it: a whole lens came
out in one commit and nothing in `broker/`, the bot book or the confluence
machinery changed, because its fences were test-pinned from day one.

WHY THESE ARE AST-BASED AND NOT SUBSTRING-BASED, which is the whole design:

HANDOFF 17.4's template is `assert "<lens>" not in src.lower()`, and for this
lens's name that fence is RED ON A PRISTINE TREE.  The word "momentum" already
appears twice in the files the fences must keep clean, as ordinary English
prose about price behaviour written long before this lens existed:

    scanner/broker/vivek_bot.py   "a real momentum/trend trade"
    scanner/vivek.py              "a break of small structure / momentum entry"

HANDOFF 17.1 anticipated exactly this ("avoid a name that collides with an
existing field or state string").  The owner chose MOMENTUM, so the name
stands and the fences move to the thing actually worth forbidding: a
REACHABILITY relationship, not an English noun.  So the import fences parse
the module and walk its import nodes, which is immune to comments, docstrings
and prose by construction -- and `test_the_bare_word_stays_confined_to_those_two_comments`
below is a TRIPWIRE that fails if a THIRD bare mention appears, so a real leak
still gets looked at.

The house precedent for fencing on imports rather than text is
`tests/test_conviction.py::test_nothing_under_broker_imports_the_conviction_rule`.

Fenced in BOTH directions, mirroring the `is_product` precedent: the lens
cannot reach the bot, AND the bot cannot reach the lens.  One direction is
half a fence -- it is the pair that makes "this cannot change which trades get
taken" a structural fact instead of a claim.

New `tests/*.py` need no registration; pytest collects the directory.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BROKER = ROOT / "scanner" / "broker"
LENS = ROOT / "scanner" / "momentum"

# The files the lens must never appear in. Every one is on the build's
# absolute kill list: they decide which trades get taken, or they are the
# confluence machinery whose meaning a fourth voice would silently change.
PROTECTED = (
    ROOT / "scanner" / "vivek.py",
    ROOT / "scanner" / "scan.py",
    ROOT / "scanner" / "conviction.py",
    ROOT / "scanner" / "confluence_alert.py",
    ROOT / "scripts" / "morning_plays.py",
)

# PhaseMap is on the kill list too, so it gets the TOKEN fence -- but
# deliberately NOT the bare-word tripwire below. "momentum" is a pre-existing
# PhaseMap DOMAIN TERM: `INVALIDATION_MOMENTUM` is one of its zone types and
# `momentum_touched` is a state flag on its setup engine, both years older
# than this lens. Enumerating those in KNOWN_PROSE would make the tripwire
# about PhaseMap's vocabulary instead of about this lens.
PHASEMAP = ROOT / "phasemap"

# THE ONLY shared modules the lens may import. An ALLOWLIST, not a denylist,
# so a new coupling has to be added here deliberately with a reason rather
# than arriving unnoticed. Each entry is here because something requires it:
#   scanner.config      spec 5.6 says to REUSE the product-name patterns
#                       rather than retype them
#   scanner.data        HANDOFF 17.3: reuse the shared downloader and inherit
#                       the frame cache, the fossil ceiling and the
#                       market-calendar age measurement. Never a second
#                       yfinance path.
#   scanner.output      HANDOFF 17.3: publish through write_json -- atomic and
#                       NaN-safe. A bare NaN token kills the whole file in the
#                       browser.
#   scanner.universe    the ticker lists
#   scanner.scanerrors  the shared per-symbol error reporter, so a name that
#                       throws every night is visible rather than silent
#   scanner.rmodel      (2026-09-23) the shared R ledger the backtest scores
#                       trades with, so a momentum R is the same currency as a
#                       5.0 R. It is PURE and imports nothing from the repo --
#                       tests/test_rmodel.py pins that -- so it cannot reach
#                       the bot, a grade table or a published file.
ALLOWED_SCANNER_IMPORTS = frozenset({
    "scanner.config", "scanner.data", "scanner.output",
    "scanner.universe", "scanner.scanerrors", "scanner.rmodel",
})

# The lens's own module path / config prefix / artefact names -- the tokens
# that would mean a real reference, as opposed to the English word.
_CLOCK_ATTRS = frozenset({"now", "utcnow", "today"})
_CLOCK_PATHS = frozenset({"time.time", "time.monotonic", "time.perf_counter"})

_LENS_TOKEN = re.compile(
    r"scanner[./]momentum|from\s+\.\s*import|MOMENTUM_|momentum\.json|data/momentum")

# The two pre-existing prose mentions, as (path relative to root, the phrase).
# Pinned so the tolerance is a recorded decision rather than a hole, and so a
# third mention anywhere in the fenced tree gets a human look.
KNOWN_PROSE = {
    "scanner/broker/vivek_bot.py": "a real momentum/trend trade",
    "scanner/vivek.py": "a break of small structure / momentum entry",
}


def _py(path: pathlib.Path):
    """Every .py file under a directory. `.glob`, matching the house
    precedent, and `*.py` also sidesteps the `__pycache__/*.pyc` that sit in
    `scanner/broker/`."""
    return sorted(path.glob("*.py"))


def _imports(path: pathlib.Path) -> list[str]:
    """Every module this file imports, as dotted names.

    Parsed, not grepped: a regex over source cannot tell an import from the
    same word in a comment, which for this lens's name is the difference
    between a fence and a false alarm.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = ("." * (node.level or 0)) + (node.module or "")
            out.append(base)
            out += [f"{base}.{a.name}" for a in node.names]
    return out


# Excluded from the engine, each for its own reason:
#   config.py   is WHERE the numbers are supposed to live, so the
#               no-magic-numbers gate must not point at it
#   run.py      a RUNNER legitimately needs a clock (generated_at), the
#               network (the downloader) and the filesystem (the publish);
#               the engine must need none of them, which is what makes it
#               replayable and the causality proof meaningful
#   __init__.py re-exports only
_NOT_ENGINE = ("config.py", "run.py", "__init__.py")


def _engine_modules() -> list[pathlib.Path]:
    """The pure-computation half of the lens."""
    return [p for p in _py(LENS) if p.name not in _NOT_ENGINE]


def _require_engine() -> list[pathlib.Path]:
    """The engine modules, or a visible SKIP if there are none yet.

    Phase 1 ships the package stub before the maths, so the two gates below
    have nothing to inspect and would pass vacuously -- "green for ever,
    checking nothing", which is the failure mode this repo has paid for more
    than once (the screenshot sentinel's reset loop, the refs regex that could
    match nothing). A skip is visible in the run output where a pass is not,
    so the emptiness announces itself and stops announcing itself the moment
    Phase 2 lands a module.
    """
    mods = _engine_modules()
    if not mods:
        pytest.skip("no engine modules yet (Phase 1 stub) - this gate is "
                    "vacuous until scanner/momentum/ has maths in it")
    return mods


# ---------------------------------------------------------------------------
# direction 1 -- the bot cannot reach the lens
# ---------------------------------------------------------------------------

def test_nothing_under_broker_imports_the_lens():
    """If the bot cannot import it, the lens cannot change what gets traded.

    This is the fence the whole report-only claim rests on. Everything else
    here defends it from a different angle.
    """
    hits = [p.name for p in _py(BROKER)
            if any("momentum" in m for m in _imports(p))]
    assert hits == [], f"scanner/broker now imports the momentum lens: {hits}"


def test_nothing_under_broker_names_the_lens_module_or_its_artefacts():
    """Reaching the lens without importing it -- reading its JSON off disk,
    or naming a MOMENTUM_ constant -- would be the same coupling wearing a
    different hat, and an import-only fence would not see it."""
    offenders = []
    for p in _py(BROKER):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if _LENS_TOKEN.search(code) and "momentum" in code:
                offenders.append(f"{p.name}:{i}: {line.strip()}")
    assert offenders == [], "\n  ".join(offenders)


def test_the_protected_files_do_not_reference_the_lens():
    """vivek.py / scan.py / conviction.py / confluence_alert.py /
    morning_plays.py are the files that decide what is traded and what the
    5.0 surfaces say. v1 is display-only, so none of them may know the lens
    exists -- in particular confluence_alert.py, because a fourth voice would
    change what every existing confluence surface SHOWS (the pill counts, the
    Eyes strip, the ALERTS log, and the edge pipeline that ingests
    alert_history.json)."""
    offenders = []
    for path in PROTECTED:
        assert path.exists(), f"protected file moved: {path}"
        if any("momentum" in m for m in _imports(path)):
            offenders.append(f"{path.name}: imports the lens")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if _LENS_TOKEN.search(code) and "momentum" in code:
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert offenders == [], "\n  ".join(offenders)


def test_the_bare_word_stays_confined_to_those_two_comments():
    """A TRIPWIRE, not a style rule -- the shape of
    test_the_first_party_actions_are_the_five_we_reviewed.

    The import fences above are deliberately blind to the English word, which
    is right: `vivek_bot.py` describing "a real momentum/trend trade" is not a
    leak. But that blindness would also hide a genuine reference written as a
    comment or a string. So the bare word is ENUMERATED instead of banned: if
    a third one appears, this fails and somebody decides which kind it is.

    Do NOT "fix" a failure here by widening KNOWN_PROSE without reading the
    line. And do not replace this with a bare substring ban -- that is the
    fence that is red on a pristine tree, which is a fence that gets deleted.
    """
    found = {}
    for path in (*_py(BROKER), *PROTECTED):
        rel = path.relative_to(ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if "momentum" in line.lower():
                found.setdefault(rel, []).append(line.strip())
    assert sorted(found) == sorted(KNOWN_PROSE), (
        "the set of files mentioning the bare word 'momentum' changed.\n"
        f"expected: {sorted(KNOWN_PROSE)}\n"
        f"found:    {sorted(found)}\n"
        "Read the new line: a comment about price behaviour is fine (add it to "
        "KNOWN_PROSE); a reference to the lens is a fence breach.")
    for rel, phrase in KNOWN_PROSE.items():
        assert any(phrase in ln for ln in found[rel]), (
            f"{rel} no longer contains the known prose {phrase!r} -- if the "
            "comment was reworded, update KNOWN_PROSE; if it was removed, "
            "drop the entry.")


# ---------------------------------------------------------------------------
# direction 2 -- the lens cannot reach the bot
# ---------------------------------------------------------------------------

def test_phasemap_does_not_reach_the_lens():
    """The other lens is on the kill list as well, and its RULESET_VERSION is
    owner-signed. Token fence only -- see the PHASEMAP note above for why the
    bare word is not checked there."""
    offenders = []
    for p in sorted(PHASEMAP.rglob("*.py")):
        if any("momentum" in m for m in _imports(p)):
            offenders.append(f"{p.relative_to(ROOT)}: imports the lens")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if _LENS_TOKEN.search(code) and "momentum" in code:
                offenders.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
    assert offenders == [], "\n  ".join(offenders)


def test_the_lens_publishes_only_through_output_write_json():
    """`tests/test_publish_integrity.py` sweeps `scanner/` RECURSIVELY, so this
    package is already enrolled in it -- a hand-rolled
    `write_text(json.dumps(...))` here trips a gate that is not ours. Asserted
    locally too, because the reference implementation this lens is ported from
    hand-rolls exactly that publish (`os.fdopen` + `json.dump` + `os.replace`)
    and would slip past BOTH of that suite's construct sweeps if it were copied
    in wholesale. Its NaN handling is also not equivalent: it raises on a
    native NaN where `output.write_json` maps non-finite floats to null."""
    for p in _py(LENS):
        src = p.read_text(encoding="utf-8")
        for bad in ("write_text(json.dumps", ".write(json.dumps",
                    "json.dump(", "os.fdopen"):
            assert bad not in src, (
                f"{p.name} hand-rolls a publish ({bad}) - use output.write_json")


def test_the_lens_imports_nothing_that_could_change_a_trade():
    """The allowlist. Anything under `scanner/broker/`, the bot's ruleset, the
    HIGH-CONVICTION table or another lens's engine is out.

    `conviction.py` is specifically out even though it is a DISPLAY module:
    the bot was aligned to its four cells on the owner's word, so importing it
    here would couple this lens to the table the bot trades. If a later
    version genuinely needs it, that is an owner decision, not a refactor.
    """
    offenders = []
    for p in _py(LENS):
        for mod in _imports(p):
            if mod.startswith("."):          # intra-package, always fine
                continue
            parts = mod.split(".")
            root = parts[0]
            if root == "phasemap":
                offenders.append(f"{p.name}: imports another lens ({mod})")
            elif root == "scanner":
                if len(parts) == 1:
                    # `from scanner import data` yields BOTH "scanner" and
                    # "scanner.data"; the bare package name carries no
                    # information and the submodule entry is what gets checked.
                    continue
                top2 = ".".join(parts[:2])
                if top2 not in ALLOWED_SCANNER_IMPORTS:
                    offenders.append(f"{p.name}: imports {mod} (not on the allowlist)")
    assert offenders == [], "\n  ".join(offenders)


def test_the_allowlist_does_not_quietly_include_the_bot():
    """Guards the gate above. The allowlist is the fence's whole strength, so
    a future edit that adds `scanner.broker.vivek_bot` to it -- which would
    make every assertion above pass while the coupling exists -- fails here
    instead."""
    for name in ALLOWED_SCANNER_IMPORTS:
        assert "broker" not in name and "conviction" not in name, name
        assert not name.endswith((".vivek", ".scan", ".spec")), name


# ---------------------------------------------------------------------------
# the engine itself
# ---------------------------------------------------------------------------

def test_the_engine_is_offline_and_has_no_clock():
    """Deterministic: same bars in, same dict out.

    Not tidiness. The causality proof truncates a frame at each bar and
    re-derives the verdict; if the engine could read a clock or the network,
    that proof would be testing the weather. A screener that consults the wall
    clock also cannot be replayed, which is how a backtest quietly stops
    describing the live system.
    """
    banned = ("requests", "urllib", "yfinance", "http", "socket")
    # Any spelling of "what time is it" -- `.now()`, `.utcnow()`, `.today()`
    # on anything. None has a legitimate use in a pure screen, so matching the
    # final attribute rather than a receiver catches `datetime.now`,
    # `datetime.datetime.now`, `dt.datetime.utcnow` and `pd.Timestamp.now`
    # alike. The module-level `datetime` import is deliberately NOT banned:
    # a row legitimately formats pivot dates off the frame's own index.
    offenders = []
    for p in _require_engine():
        for mod in _imports(p):
            if mod.split(".")[0] in banned:
                offenders.append(f"{p.name}: imports {mod}")
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            # UNPARSE the whole attribute chain rather than reading the
            # receiver's `.id`. A mutation pass caught this: the first version
            # matched `datetime.now` but MISSED `datetime.datetime.now()`,
            # because there the receiver is itself an Attribute and has no
            # `.id` at all -- so the commonest spelling of the thing being
            # banned walked straight through the fence.
            path = ast.unparse(node)
            if node.attr in _CLOCK_ATTRS or path in _CLOCK_PATHS:
                offenders.append(f"{p.name}:{node.lineno}: reads the clock via {path}")
    assert offenders == [], "\n  ".join(offenders)


def test_every_tunable_lives_in_config():
    """No magic numbers in the engine.

    The forbidden set is DERIVED from the config's own defaults rather than
    typed out, so it follows a retune automatically instead of going stale.
    Only values >= 10 are checked: 1, 2 and 5 have legitimate uses in ordinary
    arithmetic, whereas a bare 200 or 26 in this engine is a hardcoded
    parameter every time.
    """
    from scanner.momentum import config as cfg

    tunables = {v for v in cfg.DEFAULTS.to_dict().values()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 10}
    tunables |= {float(cfg.ADV_WINDOW), float(cfg.FLAT_RANGE_BARS)}
    tunables = {float(v) for v in tunables}
    assert tunables, "the tunable set came back empty - this gate would check nothing"

    offenders = []
    for p in _require_engine():
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        # A FUNCTION SIGNATURE DEFAULT is not a hardcoded threshold, and the
        # distinction is the whole difference between a useful gate and a
        # noisy one. `def rsi_wilder(close, period=14)` is a pure indicator
        # stating the Pine default it mirrors; what would actually be a defect
        # is a CALL SITE that omits the argument and silently inherits it, and
        # that is what the companion test below checks. Exempting these by
        # NODE IDENTITY rather than by value keeps a bare 14 in a function
        # BODY caught.
        exempt = set()
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in list(fn.args.defaults) + [k for k in fn.args.kw_defaults if k]:
                    exempt.update(id(x) for x in ast.walk(d))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool)
                    and float(node.value) in tunables
                    and id(node) not in exempt):
                offenders.append(f"{p.name}:{node.lineno}: bare literal "
                                 f"{node.value} is a config value")
    assert offenders == [], (
        "read the threshold from config instead:\n  " + "\n  ".join(offenders))


def test_no_indicator_is_called_without_its_config_length():
    """The other half of the gate above, and the half that would actually bite.

    The indicator signatures carry Pine's defaults so they can be used
    directly, which means an omitted argument at a CALL SITE is silent: the
    screen would compute a 14-period RSI because that is the default, not
    because config said so, and a retune of `rsi_len` would change nothing.
    Every length-taking call in the screen must therefore pass one explicitly.
    """
    src = (LENS / "screen.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # (callee, how many positional args must be present beyond the series)
    needs = {"rsi_wilder": 1, "atr_wilder": 1, "sma_pine": 1, "ema_pine": 1,
             "ma_pine": 1, "macd_pine": 3}
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in needs:
            continue
        supplied = ast.unparse(node)
        given = len(node.args) - 1 + len(node.keywords)
        if given < needs[name] or "cfg." not in supplied:
            bad.append(f"{name} at line {node.lineno}: {supplied[:90]}")
    assert bad == [], (
        "an indicator called without an explicit config length silently uses "
        "its signature default:\n  " + "\n  ".join(bad))


def test_the_config_is_versioned_and_self_checking():
    """`ruleset_version` is how a published file is traced to the rules that
    made it, and `validate()` is what stops a meaningless config producing a
    complete, plausible, wrong answer."""
    from scanner.momentum import config as cfg

    assert re.fullmatch(r"\d+\.\d+\.\d+", cfg.RULESET_VERSION), cfg.RULESET_VERSION
    assert cfg.DEFAULTS.mode == "A", (
        "v1 ships mode A (divergence only). Mode B is a UNION (A or B) and "
        "mode C is an owner decision, not a default.")
    assert cfg.DEFAULTS.div_fresh_bars == cfg.DEFAULTS.signal_fresh_bars == 1, (
        "v1 freshness is 1 bar; 3 is a firehose (~105 A + ~125 B per ASX day)")
    assert cfg.DEFAULTS.ema_seed == "sma" and cfg.DEFAULTS.rma_seed == "sma", (
        "Pine seeds with the SMA of the first `length` values; ewm(adjust=False) "
        "leaves the EMA200 0.247 price units adrift at bar 600, enough to flip "
        "`close > slow`")
    assert cfg.DEFAULTS.pivot_strict_left and cfg.DEFAULTS.pivot_strict_right, (
        "strict is the only convention that cannot fire on a flat series")
    assert cfg.DEFAULTS.max_score == 3, "1 + macd + beyond-slow, with use_rsi off"
    with pytest.raises(ValueError):
        cfg.MomentumConfig(mode="B-only").validate()


# ---------------------------------------------------------------------------
# the write set
# ---------------------------------------------------------------------------

def test_the_lens_publishes_only_into_its_own_directory():
    """It owns `public/data/momentum/` and nothing else.

    Read off the module rather than asserted about it: `out_path` is the single
    declaration of where output goes, so this is the real write set and not a
    second opinion about it.
    """
    from scanner.momentum import run

    assert run.OUT_DIR == ROOT / "public" / "data" / "momentum"
    for market in ("asx", "nasdaq", "crypto"):
        p = run.out_path(market)
        assert p.parent == run.OUT_DIR, p
        assert p.relative_to(ROOT).as_posix() == f"public/data/momentum/{market}.json"
        # the backtest (2026-09-23) is the second and last target, same dir
        b = run.backtest_path(market)
        assert b.parent == run.OUT_DIR, b
        assert b.relative_to(ROOT).as_posix() == f"public/data/momentum/{market}_backtest.json"
    writers = {n for n in dir(run) if n.endswith("_path") and callable(getattr(run, n))}
    assert writers == {"out_path", "backtest_path"}, writers


def test_the_runner_names_no_other_published_artefact():
    """The forbidden list from HANDOFF 17.4, plus the two the lens sits
    nearest. `latest.json` is on it and stays on it: the lens publishes
    per-market files ONLY, so there is no momentum latest.json to confuse with
    PhaseMap's, and keeping the fence absolute keeps it readable."""
    src = (LENS / "run.py").read_text(encoding="utf-8")
    for forbidden in ("_vivek.json", "_spec.json", "latest.json",
                      "vivek_bot_book", "bot_rules.json", "alert_history.json",
                      "funnel_history.json", "sector_map.json",
                      "reco_note.json", "edge_summary.json"):
        assert forbidden not in src, (
            f"run.py names {forbidden} - the lens writes only its own files")


def test_the_lens_owns_no_path_under_journal_or_data():
    """`journal/` is the only track record and `data/` holds signal-path
    state (sector_map.json is read by the bot's correlation cap). A
    report-only lens has no business naming either."""
    for p in _py(LENS):
        src = p.read_text(encoding="utf-8")
        for bad in ('"journal', "'journal", '"data/', "'data/"):
            assert bad not in src, f"{p.name} names {bad}"


def test_the_engine_set_is_what_the_gates_above_actually_inspect():
    """Names the files the two gates cover, so a Phase 2 module cannot land
    somewhere they do not look.

    `_NOT_ENGINE` is the only escape hatch and it holds exactly three files,
    each for a stated reason. Adding a fourth name to it would silently
    exempt a real engine module from the offline and no-magic-numbers gates,
    which is the one edit here worth making noisy.
    """
    assert _NOT_ENGINE == ("config.py", "run.py", "__init__.py")
    present = {p.name for p in _py(LENS)}
    assert {"__init__.py", "config.py", "run.py"} <= present, sorted(present)
    covered = {p.name for p in _engine_modules()}
    assert covered == present - set(_NOT_ENGINE), (
        f"engine coverage disagrees with the tree: {sorted(covered)}")

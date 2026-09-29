"""THE IGNITION FENCES -- what makes the coil -> ignition lens non-breaking.

Same governing principle as the momentum lens (HANDOFF_2026-09-22 Part 17.0):
the lens must be deletable tomorrow in one commit, because removability and
non-breakingness are the same property. TURTLE proved it; MOMENTUM pinned it;
this file pins it for IGNITION from day one.

WHY THE IMPORT FENCES ARE AST-BASED, even though the word is clean today.
Unlike "momentum", the word "ignition" does not appear anywhere in the files
the fences keep clean (checked at authoring time: zero hits across
`scanner/broker/`, the protected files and `phasemap/`). So a bare-word ban is
green on a pristine tree HERE, and `test_the_bare_word_is_absent_from_the_fenced_files`
uses one as a TRIPWIRE. But the load-bearing fences are still about
REACHABILITY, not English: they parse each module and walk its import nodes
(immune to comments, docstrings and prose by construction), resolve relative
imports to absolute names (so `from .. import ignition` inside the broker is
caught, which a substring check on `node.module` would miss), and then follow
the imports TRANSITIVELY through `scanner/` -- a bot module that imports a
helper that imports the lens reaches the lens just as surely as a direct
import does, and a one-hop fence cannot see it.

Fenced in BOTH directions, mirroring the `is_product` and momentum
precedents: the lens cannot reach the bot, AND the bot cannot reach the lens.
One direction is half a fence -- it is the pair that makes "this cannot change
which trades get taken" a structural fact instead of a claim.

Also pinned here, because each is a way a report-only lens stops being one:
  * the engine is OFFLINE and CLOCKLESS (the causality proof in
    tests/test_ignition.py truncates a frame at every bar; an engine that read
    the wall clock or the network would make that proof test the weather);
  * every threshold is a `config.IGNITION_*` constant, threaded through the
    frozen `Params` -- no bare numeric literal in the rule functions beyond
    0/1, no config value re-typed anywhere in the engine;
  * the write set is EXACTLY `public/data/ignition/<market>.json` and
    `<market>_backtest.json`, proven by reading the declarations AND by
    running the real CLI with the writer stubbed;
  * the lens's frame cache has its own key, so it can never overwrite the
    VIVEK scan's last-good cache for the same market;
  * the bot_rules.json publisher (scanner/run.py) does not know the lens.

New `tests/*.py` need no registration; pytest collects the directory.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import datetime as dt
import os
import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scanner"
BROKER = SCANNER / "broker"
LENS = SCANNER / "ignition"
PHASEMAP = ROOT / "phasemap"
MOMENTUM = SCANNER / "momentum"
LENS_PKG = "scanner.ignition"

# The files the lens must never appear in. Every one either decides which
# trades get taken, is the confluence machinery whose meaning a new voice
# would silently change, or publishes the bot's rules (scanner/run.py writes
# public/data/bot_rules.json, which status.js and journal.js read).
PROTECTED = (
    SCANNER / "vivek.py",
    SCANNER / "scan.py",
    SCANNER / "conviction.py",
    SCANNER / "confluence_alert.py",
    ROOT / "scripts" / "morning_plays.py",
    SCANNER / "run.py",
)

# Modules the lens may NEVER reach, directly or transitively. Each is a
# dotted-name PREFIX matched on whole components (so "scanner.vivek" forbids
# scanner.vivek and scanner.vivek.x, but the allowlist below is what keeps
# scanner.vivek_backtest & co out).
FORBIDDEN_FOR_LENS = (
    "scanner.broker",
    "scanner.conviction",
    "scanner.confluence_alert",
    "scanner.scan",
    "scanner.vivek",
    "scripts.morning_plays",
    "scanner.momentum",        # another lens: lenses do not lean on each other
    "phasemap",                # the owner-signed lens; its RULESET_VERSION is law
)

# THE ONLY shared scanner modules the lens may import. An ALLOWLIST, not a
# denylist, so a new coupling has to be added here deliberately, with a
# reason, rather than arriving unnoticed:
#   scanner.config      every IGNITION_* threshold lives there (project rule 3)
#   scanner.data        the shared downloader: frame cache, fossil ceiling and
#                       market-calendar age come with it -- never a second
#                       yfinance path
#   scanner.output      publish through write_json: atomic and NaN-safe
#   scanner.universe    the ticker lists
#   scanner.scanerrors  the shared per-symbol error reporter
#   scanner.indicators  sma / atr. Pure numpy/pandas and imports nothing from
#                       the repo (checked transitively below), so it cannot
#                       reach the bot, a grade table or a published file
#   scanner.exchange_data  public exchange daily klines (2026-09-28, owner:
#                       "Can't we use binance/bybit?"). Imports only stdlib,
#                       pandas and config (checked transitively below), holds
#                       no credentials and places nothing
ALLOWED_SCANNER_IMPORTS = frozenset({
    "scanner.config", "scanner.data", "scanner.output",
    "scanner.universe", "scanner.scanerrors", "scanner.indicators",
    "scanner.exchange_data",
})

# The tokens that would mean a real reference to the lens, as opposed to the
# English word: its module path, its config prefix, its artefact directory,
# its workflow, its kick file, its cache namespace.
_LENS_TOKEN = re.compile(
    r"scanner[./]ignition|IGNITION_|data/ignition|ignition\.yml|"
    r"ignition-kick|ignition-frames|ignition\.json")

# Pre-existing prose mentions of the bare word in the fenced files, as
# {path relative to root: phrase}. EMPTY at authoring time -- see the
# tripwire test for what to do when that changes.
KNOWN_PROSE: dict = {}


# ---------------------------------------------------------------------------
# import resolution
# ---------------------------------------------------------------------------

def _py(path: pathlib.Path):
    """Every .py file directly under a directory (`*.py` sidesteps the
    `__pycache__/*.pyc` beside them)."""
    return sorted(path.glob("*.py"))


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(path: pathlib.Path) -> str:
    """The package a module's relative imports resolve against."""
    name = _module_name(path)
    return name if path.name == "__init__.py" else name.rpartition(".")[0]


def _imports(path: pathlib.Path, pkg: str | None = None) -> list[str]:
    """Every module this file imports, as ABSOLUTE dotted names.

    Parsed, not grepped, and RELATIVE IMPORTS ARE RESOLVED: `from .. import
    ignition` inside scanner/broker/ yields `scanner.ignition`, which a
    fence that only looked at `node.module` (None there) would never see.
    `from a import b` yields both `a` and `a.b`, because `b` may be a
    submodule and there is no way to tell from the syntax alone. Walks the
    WHOLE tree, so a function-level (lazy) import is caught too. `pkg`
    overrides the package relative imports resolve against (tests only).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg = _package_of(path) if pkg is None else pkg
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = pkg.split(".") if pkg else []
                if node.level > 1:
                    base_parts = base_parts[: len(base_parts) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if base:
                out.append(base)
            out += [f"{base}.{a.name}" if base else a.name for a in node.names]
    return out


def _file_for(module: str):
    """The repo file that defines `module`, or None (third-party, or an
    attribute such as `scanner.config.IGNITION_MARKETS`)."""
    parts = module.split(".")
    if parts[0] not in ("scanner", "scripts", "phasemap"):
        return None
    as_file = ROOT.joinpath(*parts).with_suffix(".py")
    if as_file.is_file():
        return as_file
    as_pkg = ROOT.joinpath(*parts) / "__init__.py"
    if as_pkg.is_file():
        return as_pkg
    return None


def _closure(start: list[pathlib.Path]) -> set[str]:
    """Every repo module reachable from `start` by imports, transitively.

    Importing `a.b.c` also imports the packages `a` and `a.b`, so each
    prefix is followed as well -- a package `__init__` that pulled in the bot
    would be a real path.
    """
    seen: set[str] = set()
    todo = list(start)
    visited_files: set[pathlib.Path] = set()
    while todo:
        f = todo.pop()
        if f in visited_files:
            continue
        visited_files.add(f)
        seen.add(_module_name(f))
        for mod in _imports(f):
            parts = mod.split(".")
            for i in range(1, len(parts) + 1):
                target = _file_for(".".join(parts[:i]))
                if target is not None and target not in visited_files:
                    todo.append(target)
    return seen


def _is_under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _reaches_lens(mods) -> list[str]:
    return sorted(m for m in mods if _is_under(m, LENS_PKG))


def _code_lines(path: pathlib.Path):
    """(lineno, code) with trailing `#` comments stripped. Crude on purpose
    (a `#` inside a string is cut too) -- only ever used to look for tokens,
    where cutting too much can only miss prose, never invent a hit."""
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        yield i, line.split("#", 1)[0]


def _token_hits(path: pathlib.Path) -> list[str]:
    return [f"{path.relative_to(ROOT)}:{i}: {code.strip()}"
            for i, code in _code_lines(path) if _LENS_TOKEN.search(code)]


def test_the_resolver_actually_resolves_relative_imports(tmp_path):
    """Guards the gates below. Every fence in this file is only as good as
    `_imports`, and a resolver that returned a bare `ignition` for
    `from .. import ignition` would let the broker import the lens with every
    fence green. Checked twice: on a throwaway module in tmp_path told it
    lives in `scanner.broker` (NOT written into the shared tree -- other
    sessions run these fences concurrently), and on the real
    `scanner/broker/vivek_run.py`, whose relative and lazy imports are known."""
    probe = tmp_path / "mod.py"
    probe.write_text(
        "from .. import ignition\n"
        "from ..ignition import engine as E\n"
        "from . import vivek_bot\n"
        "import scanner.ignition.run\n"
        "def lazy():\n"
        "    from scanner.ignition import backtest\n",
        encoding="utf-8")
    mods = set(_imports(probe, pkg="scanner.broker"))
    assert "scanner.ignition" in mods
    assert "scanner.ignition.engine" in mods
    assert "scanner.broker.vivek_bot" in mods
    assert "scanner.ignition.run" in mods
    assert "scanner.ignition.backtest" in mods, "a lazy import must be seen"
    assert _reaches_lens(mods)

    real = set(_imports(BROKER / "vivek_run.py"))
    for expected in ("scanner.config",                   # from .. import config
                     "scanner.broker.vivek_bot",         # from . import vivek_bot
                     "scanner.broker.alert_dispatch"):   # lazy, inside a function
        assert expected in real, (expected, sorted(real)[:40])
    reach = _closure([BROKER / "vivek_run.py"])
    assert "scanner.broker.vivek_bot" in reach and "scanner.config" in reach
    lens_reach = _closure([LENS / "run.py"])
    assert {"scanner.ignition.engine", "scanner.ignition.backtest",
            "scanner.indicators", "scanner.journal_common"} <= lens_reach, (
        "the closure no longer follows imports transitively")


def test_the_lens_package_exists_where_the_fences_look():
    """A fence over an empty directory is green for ever, checking nothing."""
    names = {p.name for p in _py(LENS)}
    assert {"__init__.py", "engine.py", "backtest.py", "run.py"} <= names, sorted(names)
    assert _module_name(LENS / "engine.py") == "scanner.ignition.engine"
    assert _py(BROKER), "scanner/broker/ has no modules - the bot fence would be vacuous"


# ---------------------------------------------------------------------------
# direction 1 -- the bot (and the protected files) cannot reach the lens
# ---------------------------------------------------------------------------

def test_nothing_under_broker_imports_the_lens():
    """If the bot cannot import it, the lens cannot change what gets traded.
    This is the fence the whole report-only claim rests on."""
    hits = {p.name: _reaches_lens(_imports(p)) for p in _py(BROKER)}
    hits = {k: v for k, v in hits.items() if v}
    assert hits == {}, f"scanner/broker now imports the ignition lens: {hits}"


def test_nothing_under_broker_reaches_the_lens_even_transitively():
    """A broker module importing a helper that imports the lens reaches it
    just as surely as a direct import; the one-hop fence above cannot see
    that, this one can."""
    offenders = {}
    for p in _py(BROKER):
        reach = _reaches_lens(_closure([p]))
        if reach:
            offenders[p.name] = reach
    assert offenders == {}, offenders


def test_nothing_under_broker_names_the_lens_module_or_its_artefacts():
    """Reaching the lens without importing it -- reading its JSON off disk,
    naming an IGNITION_ constant, `importlib.import_module("scanner.ignition")`
    -- is the same coupling wearing a different hat."""
    offenders = [hit for p in _py(BROKER) for hit in _token_hits(p)]
    assert offenders == [], "\n  ".join(offenders)


def test_the_protected_files_do_not_reference_the_lens():
    """vivek.py / scan.py / conviction.py / confluence_alert.py /
    morning_plays.py decide what is traded and what the 5.0 surfaces say, and
    scanner/run.py publishes bot_rules.json. None of them may know the lens
    exists -- in particular confluence_alert.py: the lens is NOT part of
    confluence, and a new voice there would change what every existing
    confluence surface shows."""
    offenders = []
    for path in PROTECTED:
        assert path.exists(), f"protected file moved: {path}"
        reach = _reaches_lens(_closure([path]))
        if reach:
            offenders.append(f"{path.relative_to(ROOT)}: reaches {reach}")
        offenders += _token_hits(path)
    assert offenders == [], "\n  ".join(offenders)


def test_the_bare_word_is_absent_from_the_fenced_files():
    """A TRIPWIRE, not a style rule. The fences above are about reachability
    and deliberately blind to English; this one catches a genuine reference
    written as a comment or a string, which they would miss.

    The word was absent from every one of these files when the lens landed,
    so KNOWN_PROSE starts EMPTY. If a line about price behaviour ("an
    ignition candle") ever legitimately appears here, read it, and if it is
    prose add it to KNOWN_PROSE -- do NOT replace this with a looser check,
    and do not widen KNOWN_PROSE without reading the line.
    """
    found = {}
    for path in (*_py(BROKER), *PROTECTED):
        rel = path.relative_to(ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if "ignit" in line.lower():
                found.setdefault(rel, []).append(line.strip())
    assert sorted(found) == sorted(KNOWN_PROSE), (
        "the set of fenced files mentioning 'ignit...' changed.\n"
        f"expected: {sorted(KNOWN_PROSE)}\nfound: {found}\n"
        "A comment about price behaviour is fine (add it to KNOWN_PROSE); a "
        "reference to the lens is a fence breach.")
    for rel, phrase in KNOWN_PROSE.items():
        assert any(phrase in ln for ln in found[rel]), (rel, phrase)


def test_the_bot_rules_publisher_does_not_know_the_lens():
    """`public/data/bot_rules.json` is the bot's published ruleset -- status.js
    and journal.js read it as the rules the bot trades. An IGNITION_* value
    leaking into it would dress a report-only threshold as a trading rule.

    Checked on the AST of the publisher (no `config.IGNITION_*` attribute, no
    key in any dict literal naming the lens) and, when present, on the
    published file itself."""
    src = (SCANNER / "run.py").read_text(encoding="utf-8")
    assert '"bot_rules.json"' in src, "the bot_rules publisher moved - re-point this fence"
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("IGNITION_"):
            bad.append(f"line {node.lineno}: {ast.unparse(node)}")
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and "ignit" in k.value.lower():
                    bad.append(f"line {k.lineno}: key {k.value!r}")
    assert bad == [], bad
    published = ROOT / "public" / "data" / "bot_rules.json"
    if published.exists():
        assert "ignit" not in published.read_text(encoding="utf-8").lower()


def test_phasemap_and_momentum_do_not_reach_the_lens():
    """The other lenses are on the kill list too (PhaseMap's RULESET_VERSION
    is owner-signed). Token + transitive-import fence."""
    offenders = []
    for p in (*sorted(PHASEMAP.rglob("*.py")), *_py(MOMENTUM)):
        if "__pycache__" in p.parts:
            continue
        if _reaches_lens(_imports(p)):
            offenders.append(f"{p.relative_to(ROOT)}: imports the lens")
        offenders += _token_hits(p)
    assert offenders == [], "\n  ".join(offenders)


# ---------------------------------------------------------------------------
# direction 2 -- the lens cannot reach the bot
# ---------------------------------------------------------------------------

def test_the_lens_imports_only_the_allowlist():
    """Anything under `scanner/broker/`, the bot's ruleset, the
    HIGH-CONVICTION table, the confluence engine or another lens is out.

    `conviction.py` is out even though it is a DISPLAY module: the bot was
    aligned to its four cells on the owner's word, so importing it here would
    couple this lens to the table the bot trades.
    """
    offenders = []
    for p in _py(LENS):
        for mod in _imports(p):
            root = mod.split(".")[0]
            if root in ("phasemap", "scripts"):
                offenders.append(f"{p.name}: imports {mod}")
            elif root == "scanner":
                parts = mod.split(".")
                if len(parts) == 1:
                    continue      # `from scanner import x` -> checked as scanner.x
                top2 = ".".join(parts[:2])
                if top2 == LENS_PKG:
                    continue      # intra-package, resolved from a relative import
                if top2 not in ALLOWED_SCANNER_IMPORTS:
                    offenders.append(f"{p.name}: imports {mod} (not on the allowlist)")
    assert offenders == [], "\n  ".join(offenders)


@pytest.mark.parametrize("forbidden", FORBIDDEN_FOR_LENS)
def test_the_lens_cannot_reach_a_trade_deciding_module_even_transitively(forbidden):
    """The allowlist above checks one hop. This follows every import through
    the repo -- the lens, the allowlisted modules, whatever THEY import -- and
    fails if any path arrives at the bot, the conviction table, the
    confluence engine, the VIVEK scan/engine, the plays digest or another
    lens. `scanner.data` or `scanner.output` growing an import of the bot
    would breach the lens's fence without touching a lens file; only a
    transitive check sees that."""
    reach = _closure(_py(LENS))
    hits = sorted(m for m in reach if _is_under(m, forbidden))
    assert hits == [], f"scanner/ignition reaches {forbidden}: {hits}"


def test_the_allowlist_does_not_quietly_include_the_bot():
    """Guards the gate above: an allowlist edit that added
    `scanner.broker.vivek_bot` would make every assertion pass while the
    coupling exists."""
    for name in ALLOWED_SCANNER_IMPORTS:
        for forbidden in FORBIDDEN_FOR_LENS:
            assert not _is_under(name, forbidden), (name, forbidden)
        assert not name.endswith((".vivek", ".scan", ".spec", ".conviction")), name


_FS_WRITERS = frozenset({
    "os.replace", "os.rename", "os.remove", "os.unlink", "os.makedirs",
    "os.mkdir", "os.open", "os.fdopen", "io.open", "gzip.open", "shutil.move",
    "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.rmtree",
    "json.dump", "pickle.dump", "np.save", "np.savez", "numpy.save"})
_METHOD_WRITERS = frozenset({
    "write_text", "write_bytes", "to_csv", "to_json", "to_pickle", "to_parquet",
    "to_feather", "to_excel", "to_hdf", "mkdir", "unlink", "rmdir", "touch"})


def test_the_lens_publishes_only_through_output_write_json():
    """`output.write_json` is atomic and maps non-finite floats to null; a
    bare NaN token kills the whole file in the browser (Tier 4 #62). So the
    lens may not open a file for writing, or call any other writer, anywhere
    -- the ONLY write-shaped call in the package is `output.write_json`, once,
    in run.py."""
    offenders = []
    write_json_calls = []
    for p in _py(LENS):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            text = ast.unparse(f)
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name == "write_json":
                write_json_calls.append((p.name, text))
            elif name == "open" or text in _FS_WRITERS or (
                    isinstance(f, ast.Attribute) and f.attr in _METHOD_WRITERS):
                offenders.append(f"{p.name}:{node.lineno}: {text}(...)")
    assert offenders == [], "\n  ".join(offenders)
    assert write_json_calls == [("run.py", "output.write_json")], write_json_calls


# ---------------------------------------------------------------------------
# the engine itself -- offline, clockless, config-driven
# ---------------------------------------------------------------------------

# run.py is the RUNNER: it legitimately needs a clock (generated_at, the
# forming-bar split), the network (the shared downloader) and the filesystem
# (the publish). backtest.py is the REPLAY: offline, but it stamps its own
# payload's generated_at when the runner did not inject a `now` -- a single,
# pinned exception (see below). Everything else in the package is ENGINE and
# must need none of those three.
_NOT_ENGINE = ("run.py", "__init__.py", "backtest.py")
_NETWORK = ("requests", "urllib", "urllib3", "http", "socket", "yfinance",
            "aiohttp", "httpx", "ccxt", "websocket")
_CLOCK_ATTRS = frozenset({"now", "utcnow", "today"})
_CLOCK_PATHS = frozenset({"time.time", "time.time_ns", "time.monotonic",
                          "time.perf_counter", "time.localtime", "time.gmtime"})


def _engine_modules() -> list[pathlib.Path]:
    mods = [p for p in _py(LENS) if p.name not in _NOT_ENGINE]
    assert mods, "no engine modules - the offline and no-magic-number gates are vacuous"
    return mods


def _clock_reads(tree: ast.AST) -> list[tuple[int, str, ast.AST]]:
    """Every spelling of "what time is it": `.now()/.utcnow()/.today()` on
    anything (so `datetime.now`, `datetime.datetime.now`, `pd.Timestamp.now`
    alike -- the whole chain is UNPARSED, because `datetime.datetime.now` has
    an Attribute as its receiver and no `.id`), `time.time()` & co, and the
    string forms `pd.Timestamp("now")` / `np.datetime64("today")`."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            path = ast.unparse(node)
            if node.attr in _CLOCK_ATTRS or path in _CLOCK_PATHS:
                out.append((node.lineno, path, node))
        elif isinstance(node, ast.Call):
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and a.value.strip().lower() in ("now", "today"):
                    out.append((node.lineno, ast.unparse(node), node))
    return out


def test_the_engine_is_offline_clockless_and_does_no_io():
    """Deterministic: same bars in, same dict out.

    Not tidiness. The causality proof truncates a frame at each bar and
    re-derives the verdict; if the engine could read a clock or the network
    that proof would be testing the weather, and a screen that consults the
    wall clock cannot be replayed -- which is how a backtest quietly stops
    describing the live system. `time` and `datetime` are banned OUTRIGHT in
    the engine (it needs neither: dates are formatted off the frame's own
    index), and so are `random` / `np.random` (an unseeded draw is a clock by
    another name).
    """
    offenders = []
    for p in _engine_modules():
        for mod in _imports(p):
            root = mod.split(".")[0]
            if root in _NETWORK + ("time", "datetime", "random", "os",
                                   "pathlib", "io", "shutil", "pickle",
                                   "json", "subprocess"):
                offenders.append(f"{p.name}: imports {mod}")
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for lineno, path, _ in _clock_reads(tree):
            offenders.append(f"{p.name}:{lineno}: reads the clock via {path}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "random":
                offenders.append(f"{p.name}:{node.lineno}: {ast.unparse(node)}")
            if isinstance(node, ast.Attribute) and node.attr.startswith("read_"):
                offenders.append(f"{p.name}:{node.lineno}: file read {ast.unparse(node)}")
    assert offenders == [], "\n  ".join(offenders)


def test_the_replay_is_offline_and_its_one_clock_read_is_the_now_fallback():
    """backtest.py may not touch the network or the filesystem, and it reads
    the clock in exactly ONE place: `now = now or dt.datetime.now(...)`, the
    default for `generated_at` when the caller injected nothing. The runner
    always injects it (and the replay's random draws are seeded, never
    clocked), so the evidence file is a function of the bars alone. A second
    clock read -- a "bars since today", an age filter -- would make the replay
    irreproducible, and fails here."""
    p = LENS / "backtest.py"
    for mod in _imports(p):
        assert mod.split(".")[0] not in _NETWORK + ("time", "random", "os",
                                                     "pathlib", "shutil", "pickle",
                                                     "subprocess"), mod
    tree = ast.parse(p.read_text(encoding="utf-8"))
    reads = _clock_reads(tree)
    fallback_calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) \
                and isinstance(node.values[0], ast.Name) and node.values[0].id == "now":
            fallback_calls |= {id(x) for x in ast.walk(node)}
    stray = [f"line {ln}: {path}" for ln, path, n in reads if id(n) not in fallback_calls]
    assert stray == [], "backtest.py reads the clock outside the `now or ...` default: " + str(stray)
    assert len(reads) <= 1, reads
    # every RNG is seeded
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("default_rng"):
            assert node.args or node.keywords, f"line {node.lineno}: unseeded RNG"
    src = p.read_text(encoding="utf-8")
    assert "np.random.seed" not in src and "random.random(" not in src


# The functions that ARE the rule. A literal other than 0/1 inside one of them
# is a threshold that did not come from config.
RULE_FUNCS = ("base_features", "apply_rules", "_any_prior", "_run_length", "compute")


def _functions(path: pathlib.Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
    return out


def test_the_rule_functions_carry_no_bare_numeric_literal_beyond_0_and_1():
    """No magic numbers in the rule.

    `shift(1)`, `- 1.0`, `min_periods=1`, `> 0` are structure; anything else --
    a `rolling(20)`, a `>= 3.0`, a `0.12` -- is a threshold typed into the
    rule instead of read from `config.IGNITION_*`, and a retune of config
    would then silently change nothing. Named functions are asserted to
    EXIST, so a rename cannot make this gate vacuous.
    """
    fns = _functions(LENS / "engine.py")
    missing = [n for n in RULE_FUNCS if n not in fns]
    assert missing == [], f"rule functions renamed/moved: {missing}"
    offenders = []
    for name in RULE_FUNCS:
        for node in ast.walk(fns[name]):
            if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool)
                    and float(node.value) not in (0.0, 1.0)):
                offenders.append(f"{name}:{node.lineno}: bare literal {node.value!r}")
    assert offenders == [], "read it from config.IGNITION_*:\n  " + "\n  ".join(offenders)


def test_every_comparison_in_apply_rules_is_against_a_Params_threshold():
    """The other half of the gate above. `apply_rules` must compare a feature
    against `p.<threshold>` -- the frozen Params the backtest varies one field
    at a time. A comparison against anything else (a module constant, a
    config value read directly, a literal) is a threshold the sensitivity grid
    cannot move, i.e. a rule the robustness read silently does not cover.
    The only exemption is a comparison against the literal 0 (`> 0` on a
    rolling-max flag), which is structure, not a threshold."""
    fn = _functions(LENS / "engine.py")["apply_rules"]
    p_arg = fn.args.args[1].arg
    bad = []
    n_compare = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        n_compare += 1
        uses_p = any(isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                     and x.value.id == p_arg for x in ast.walk(node))
        zero_only = all(isinstance(c, ast.Constant) and c.value == 0 for c in node.comparators)
        if not (uses_p or zero_only):
            bad.append(f"line {node.lineno}: {ast.unparse(node)}")
    assert n_compare >= 6, "apply_rules has fewer comparisons than the rule - gate misaimed?"
    assert bad == [], bad


def test_Params_is_built_from_config_IGNITION_constants_field_by_field():
    """Every threshold field of the frozen Params is assigned from a
    `config.IGNITION_*` expression in `from_config` -- the ONE place the rule
    meets the config. The two ablation switches (require_coil / require_rvol)
    are the only fields with a default, and must default ON: a Params built
    from config is the pre-registered rule, never an ablation."""
    from scanner.ignition import engine as E

    fields = {f.name: f for f in dataclasses.fields(E.Params)}
    ablations = {n for n, f in fields.items() if f.default is not dataclasses.MISSING}
    assert ablations == {"require_coil", "require_rvol"}, ablations
    assert all(fields[n].default is True for n in ablations)
    assert E.Params.__dataclass_params__.frozen, "a grid cell must not leak into the next"

    fn = _functions(LENS / "engine.py")["from_config"]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "cls"]
    assert len(calls) == 1, "from_config should build exactly one Params"
    kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    thresholds = set(fields) - ablations
    assert set(kw) == thresholds, (sorted(set(kw) ^ thresholds))
    not_config = {k: v for k, v in kw.items() if "config.IGNITION_" not in v}
    assert not_config == {}, not_config

    # And the values really are config's, for the one market v1 screens.
    for market in config.IGNITION_MARKETS:
        p = E.Params.from_config(market)
        assert p.rvol_min == config.IGNITION_RVOL_MIN
        assert p.ribbon_max == config.IGNITION_RIBBON_MAX
        assert p.min_drawdown == config.IGNITION_MIN_DRAWDOWN
        assert p.min_trigger_turnover == config.IGNITION_MIN_TRIGGER_TURNOVER[market]
        assert p.require_coil and p.require_rvol


def _ignition_numbers() -> set:
    """Every numeric value in the IGNITION_* config block, flattened through
    tuples and dicts. DERIVED, so the forbidden set follows a retune."""
    out = set()

    def add(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.add(float(v))
        elif isinstance(v, (tuple, list)):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
    for name in dir(config):
        if name.startswith("IGNITION_"):
            add(getattr(config, name))
    return out


def test_no_config_value_is_retyped_anywhere_in_the_engine():
    """The whole-module sweep. Values >= 10 only (2, 3 and 5 have honest
    arithmetic uses; a bare 60, 730 or 1095 in this engine is a re-typed
    parameter every time), and 100 is exempt because it is the percent unit
    the display rounds through, not a threshold. Function-signature defaults
    are exempt BY NODE IDENTITY, so a bare value in a body is still caught."""
    tunables = {v for v in _ignition_numbers() if v >= 10 and v != 100.0}
    assert {60.0, 730.0, 1095.0, 400.0} <= tunables, "the derived set lost the obvious ones"
    offenders = []
    for p in _engine_modules():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        exempt = set()
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in list(fn.args.defaults) + [k for k in fn.args.kw_defaults if k]:
                    exempt.update(id(x) for x in ast.walk(d))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool)
                    and float(node.value) in tunables and id(node) not in exempt):
                offenders.append(f"{p.name}:{node.lineno}: bare {node.value} is a config value")
    assert offenders == [], "\n  ".join(offenders)


def test_every_config_name_the_lens_reads_exists_and_is_the_lens_own():
    """Two properties. (1) Every `config.X` the ENGINE reads is `IGNITION_*`
    or the shared market registry (`MARKETS`, for the liquidity floor and
    `volume_is_usd`) -- the engine does not borrow the bot's or the VIVEK
    scan's thresholds, which would couple a report-only rule to a trading
    one. (2) Every `IGNITION_*` name referenced anywhere in the package
    exists: attribute access is resolved at CALL time, so a typo on a rarely
    taken path (the backtest's case studies, the CLI's choices) would only
    fail on the day it ran."""
    borrowed = []
    missing = []
    for p in _py(LENS):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "config":
                if node.attr.startswith("IGNITION_") and not hasattr(config, node.attr):
                    missing.append(f"{p.name}:{node.lineno}: config.{node.attr}")
                if p.name not in _NOT_ENGINE and not (
                        node.attr.startswith("IGNITION_") or node.attr == "MARKETS"):
                    borrowed.append(f"{p.name}:{node.lineno}: config.{node.attr}")
            if isinstance(node, ast.ImportFrom) and node.module == "scanner.config":
                for a in node.names:
                    if not hasattr(config, a.name):
                        missing.append(f"{p.name}:{node.lineno}: {a.name}")
    assert missing == [], missing
    assert borrowed == [], borrowed


def test_every_indicator_call_passes_its_config_length():
    """`indicators.atr(df, period=14)` carries a signature default, so a call
    that omitted the length would compute a 14-bar ATR because that is the
    default, not because config said so, and a retune of IGNITION_ATR_LEN
    would change nothing. Every sma/atr call in the engine must pass an
    explicit length read from config (or a local bound from it)."""
    tree = ast.parse((LENS / "engine.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) in ("sma", "calc_atr")]
    assert len(calls) >= 3, "sma/atr calls vanished - is the gate still aimed?"
    bad = []
    for n in calls:
        if len(n.args) + len(n.keywords) < 2:
            bad.append(f"line {n.lineno}: {ast.unparse(n)} omits its length")
            continue
        length = n.args[1] if len(n.args) >= 2 else n.keywords[0].value
        if isinstance(length, ast.Constant):
            bad.append(f"line {n.lineno}: {ast.unparse(n)} passes a literal length")
    assert bad == [], bad


def test_the_robustness_grid_brackets_the_pre_registered_rule():
    """The backtest's 3^5 grid is a ROBUSTNESS read around the pre-registered
    values, not a menu. Each dimension must be a real Params field and its
    MIDDLE value must be today's config value -- otherwise a config retune
    leaves the grid describing a neighbourhood of a rule that no longer
    exists, and "the rule sits in the middle of a stable plateau" stops being
    a claim the payload can support."""
    from scanner.ignition import backtest as bt
    from scanner.ignition import engine as E

    fields = {f.name for f in dataclasses.fields(E.Params)}
    live = E.Params.from_config(config.IGNITION_MARKETS[0])
    for dim, values in bt.GRID.items():
        assert dim in fields, dim
        assert len(values) % 2 == 1 and list(values) == sorted(values), (dim, values)
        assert values[len(values) // 2] == getattr(live, dim), (
            f"GRID[{dim!r}] is centred on {values[len(values) // 2]}, config says "
            f"{getattr(live, dim)}")


def test_the_ruleset_is_versioned():
    from scanner import ignition

    assert re.fullmatch(r"\d+\.\d+\.\d+", config.IGNITION_RULESET_VERSION)
    assert ignition.RULESET_VERSION == config.IGNITION_RULESET_VERSION
    assert tuple(config.IGNITION_MARKETS) == ("crypto", "asx"), (
        "crypto + the ASX (owner, 2026-09-29); widening the market set further is "
        "an owner decision, and each market needs its own workflow "
        "(ignition.yml, ignition_asx.yml) and page support")


# ---------------------------------------------------------------------------
# the write set
# ---------------------------------------------------------------------------

def test_the_lens_publishes_only_into_its_own_directory():
    """It owns `public/data/ignition/` and nothing else. Read off the module:
    `out_path` / `backtest_path` are the single declaration of where output
    goes, so this is the real write set and not a second opinion about it."""
    from scanner.ignition import run

    assert run.OUT_DIR == ROOT / "public" / "data" / "ignition"
    for market in ("asx", "nasdaq", "crypto"):
        assert run.out_path(market).relative_to(ROOT).as_posix() \
            == f"public/data/ignition/{market}.json"
        assert run.backtest_path(market).relative_to(ROOT).as_posix() \
            == f"public/data/ignition/{market}_backtest.json"
    writers = {n for n in dir(run) if n.endswith("_path") and callable(getattr(run, n))}
    assert writers == {"out_path", "backtest_path"}, writers


def test_the_runner_names_no_other_published_artefact():
    """HANDOFF 17.4's forbidden list plus the lens's neighbours. Checked on
    STRING CONSTANTS in the AST, so the module docstring explaining what the
    lens does NOT write cannot trip it, while a path spelled in code can."""
    tree = ast.parse((LENS / "run.py").read_text(encoding="utf-8"))
    doc_ids = {id(n.body[0].value) for n in ast.walk(tree)
               if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
               and n.body and isinstance(n.body[0], ast.Expr)
               and isinstance(n.body[0].value, ast.Constant)}
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and id(n) not in doc_ids]
    code = " ".join(strings)
    for forbidden in ("_vivek.json", "_spec.json", "latest.json", "vivek_bot_book",
                      "bot_rules.json", "alert_history.json", "funnel_history.json",
                      "sector_map.json", "reco_note.json", "edge_summary.json",
                      "journal/", "phasemap", "momentum", "backups/"):
        assert forbidden not in code, f"run.py names {forbidden}"
    for p in _py(LENS):
        src = p.read_text(encoding="utf-8")
        for bad in ('"journal', "'journal", '"data/', "'data/"):
            assert bad not in src, f"{p.name} names {bad}"


def _frame(seed: int, n: int = 520, days_old: int = 1) -> pd.DataFrame:
    """A plain random walk ending `days_old` days ago (UTC). Long enough to
    clear IGNITION_MIN_BARS, fresh enough to clear the staleness skip."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(dt.datetime.now(dt.timezone.utc).date()) - pd.Timedelta(days=days_old)
    idx = pd.date_range(end=end, periods=n, freq="D")
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Volume": rng.uniform(4e6, 8e6, n)}, index=idx)


@pytest.fixture
def cli(monkeypatch):
    """The real CLI with only its two edges stubbed: the downloader (the
    network is not reachable from CI's test job, nor from here) and the
    publisher (so nothing lands in the tree). Every write-mode `open`, every
    `os.replace`/`Path.write_*` during the call is ALSO recorded -- the
    write set is proven by running the code, not only by reading it."""
    from scanner import output
    from scanner.ignition import run

    rows = [{"yf": "AAA-USD", "symbol": "AAA", "name": "Aaa"},
            {"yf": "BBB-USD", "symbol": "BBB", "name": "Bbb"},
            {"yf": "CCC-USD", "symbol": "CCC", "name": "Ccc"}]
    # CCC's last bar is TODAY (UTC): the forming bar, which must be split off
    # before anything persists it.
    frames = {"AAA-USD": _frame(1), "BBB-USD": _frame(2), "CCC-USD": _frame(3, days_old=0)}
    state = {"published": [], "raw_writes": [], "load_calls": [], "load": None,
             "cache_calls": []}

    def fake_download(market, period, limit):
        state["load_calls"].append((market, period, limit))
        if state["load"] is not None:
            return state["load"](market, period, limit)
        return rows, frames, {"source_of": {yf: "binance_vision" for yf in frames}}

    def fake_merge(key, fresh, tickers, refused=(), rejected_venues=None):
        # The real merge LOADS and SAVES .cache/frames/<key>.pkl.gz; recorded
        # here (key + exactly what it was handed) instead of touching disk.
        state["cache_calls"].append((key, {k: v.copy() for k, v in fresh.items()}, list(tickers)))
        return dict(fresh), {"fresh": len(fresh), "reused": 0}

    def fake_write_json(path, payload, **kw):
        state["published"].append((pathlib.Path(path), payload))
        return pathlib.Path(path)

    real_open = builtins.open

    def spy_open(file, mode="r", *a, **k):
        if any(c in str(mode) for c in "wax+"):
            state["raw_writes"].append(("open", str(file), mode))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(run, "_download", fake_download)
    monkeypatch.setattr(run.sdata, "merge_with_cache", fake_merge)
    monkeypatch.setattr(output, "write_json", fake_write_json)
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(os, "replace", lambda *a, **k: state["raw_writes"].append(("replace", a)))
    monkeypatch.setattr(pathlib.Path, "write_text",
                        lambda self, *a, **k: state["raw_writes"].append(("write_text", str(self))))
    monkeypatch.setattr(pathlib.Path, "write_bytes",
                        lambda self, *a, **k: state["raw_writes"].append(("write_bytes", str(self))))
    state["run"] = run
    return state


def test_running_the_cli_writes_exactly_the_two_ignition_paths_and_nothing_else(cli):
    """Screen, then backtest, through `main()` exactly as ignition.yml calls
    it. Exactly one publish each, to the canonical path, through
    `output.write_json`; zero other writes of any kind. And the exit codes
    ignition.yml's case statement is built on: 0 published."""
    run = cli["run"]
    assert run.main(["--market", "crypto"]) == 0
    assert run.main(["--market", "crypto", "--backtest"]) == 0
    got = [p.relative_to(ROOT).as_posix() for p, _ in cli["published"]]
    assert got == ["public/data/ignition/crypto.json",
                   "public/data/ignition/crypto_backtest.json"], got
    assert cli["raw_writes"] == [], cli["raw_writes"]
    screen, replay = (payload for _, payload in cli["published"])
    for payload in (screen, replay):
        assert payload["ruleset_version"] == config.IGNITION_RULESET_VERSION
    assert screen["lens"] == "ignition" and screen["report_only"] is True
    assert screen["market"] == "crypto"
    assert not (ROOT / "public" / "data" / "ignition" / "_never").exists()


def test_a_dry_run_writes_nothing_at_all(cli):
    run = cli["run"]
    assert run.main(["--market", "crypto", "--dry-run"]) == 0
    assert run.main(["--market", "crypto", "--backtest", "--dry-run"]) == 0
    assert cli["published"] == [] and cli["raw_writes"] == []


def test_no_data_is_exit_3_and_keeps_the_previous_file(cli):
    """Exit 3 is what ignition.yml's `3)` arm turns into published=false and a
    ::warning:: -- the previous file stands, because an empty list over it
    would say "nothing is coiling" when the truth is "we could not look"."""
    run = cli["run"]
    cli["load"] = lambda *a: ([], {}, {})
    assert run.main(["--market", "crypto"]) == 3
    assert run.main(["--market", "crypto", "--backtest"]) == 3
    assert cli["published"] == [] and cli["raw_writes"] == []


def test_a_crash_is_exit_1_and_writes_nothing(cli):
    """Any other code is ignition.yml's `*)` arm: a red run, no commit."""
    run = cli["run"]

    def boom(*a):
        raise RuntimeError("download exploded")
    cli["load"] = boom
    assert run.main(["--market", "crypto"]) == 1
    assert run.main(["--market", "crypto", "--backtest"]) == 1
    assert cli["published"] == [] and cli["raw_writes"] == []


def test_the_lens_frame_cache_can_never_overwrite_the_scan_cache(cli):
    """`scanner.data.merge_with_cache(key, ...)` LOADS and then SAVES
    `.cache/frames/<key>.pkl.gz`. Were the lens to pass the plain market key
    ("crypto") it would overwrite the VIVEK scan's last-good crypto cache
    with its own universe and window -- the frame the bot's marks fall back
    to. So the screen's key is namespaced, and the replay (period "max")
    uses no cache at all, so a full-history download can never be saved over
    anything."""
    run = cli["run"]
    run.main(["--market", "crypto", "--dry-run"])
    run.main(["--market", "crypto", "--backtest", "--dry-run"])
    (screen_call, replay_call) = cli["load_calls"]
    assert screen_call[1] == config.IGNITION_DATA_PERIOD
    assert replay_call[1] == config.IGNITION_BT_PERIOD
    assert len(cli["cache_calls"]) == 1, "the replay must not read or write the frame cache"
    key = cli["cache_calls"][0][0]
    assert key and key.startswith("ignition-"), key
    assert key not in config.MARKETS, key


def test_the_frame_cache_is_only_ever_handed_completed_bars(cli):
    """Audit 2026-09-28: the cache used to be handed the RAW download, forming
    bar included. If Yahoo then dropped that ticker the next day, the cached
    mid-day snapshot was re-used and screened as a FINISHED daily bar --
    partial volume and a mid-day close feeding rvol, the breakout and the
    stop. The forming bar is now split off before anything can persist it."""
    run = cli["run"]
    run.main(["--market", "crypto", "--dry-run"])
    (_, handed, _), = cli["cache_calls"]
    today = dt.datetime.now(dt.timezone.utc).date()
    assert set(handed) == {"AAA-USD", "BBB-USD", "CCC-USD"}
    for yf, df in handed.items():
        assert pd.Timestamp(df.index[-1]).date() < today, (yf, df.index[-1])
    # ...and the forming bar was still USED (as `forming`), not thrown away:
    # CCC's cached frame is exactly one bar shorter than the download.
    assert len(handed["CCC-USD"]) == len(_frame(3, days_old=0)) - 1


def test_the_engine_set_is_what_the_gates_above_actually_inspect():
    """Names the files the engine gates cover, so a new module cannot land
    somewhere they do not look. `_NOT_ENGINE` is the only escape hatch and
    holds exactly three files, each for a stated reason; a fourth name would
    silently exempt a real engine module from the offline, no-clock and
    no-magic-number gates, which is the one edit here worth making noisy."""
    assert _NOT_ENGINE == ("run.py", "__init__.py", "backtest.py")
    present = {p.name for p in _py(LENS)}
    covered = {p.name for p in _engine_modules()}
    assert "engine.py" in covered
    assert covered == present - set(_NOT_ENGINE), sorted(covered)

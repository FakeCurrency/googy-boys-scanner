"""Scripts that run on a bare Python stay stdlib-only, imports inside
functions included.

3 Nov 2026: the digest's "book full" line imported the time-stop day through
scanner.vivek_journal, whose imports reach numpy. morning_plays.yml installs no
packages, so the ASX slot crashed (ModuleNotFoundError: numpy) before it
posted, on every rung of the ladder. The import sat inside a function and only
ran with the book full, so neither importing the module nor the unit tests (on
a runner WITH numpy) could see it.

Two guards:
* every workflow job that runs Python without installing packages is found
  from the workflows themselves, and each script's whole import tree (every
  `import` at any depth, followed through scanner/, scripts/, phasemap/) must
  name only the standard library;
* the digest runs end to end, book full, with numpy and pandas blocked.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

from tests.test_morning_plays import _row

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCAL = {"scanner", "scripts", "phasemap"}
STDLIB = set(sys.stdlib_module_names) | {"__future__"}
_INSTALL = re.compile(r"pip3?\s+install|requirements[\w.-]*\.txt")
_PY = re.compile(r"\bpython3?\s+(?:-[A-Za-z]+\s+)*(?:-m\s+([\w.]+)|([\w./-]+\.py))")


def _code(run: str) -> str:
    """A run: block without its shell comments."""
    return "\n".join(line.split("#", 1)[0] for line in run.splitlines())


def bare_python_scripts() -> dict[str, str]:
    """{script path: "workflow::job"} for every job that runs Python and never
    installs a package."""
    found: dict[str, str] = {}
    for wf_path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8")) or {}
        for name, job in (wf.get("jobs") or {}).items():
            runs = [_code(s.get("run") or "") for s in job.get("steps") or []]
            if any(_INSTALL.search(r) for r in runs):
                continue
            for r in runs:
                for mod, path in _PY.findall(r):
                    script = path or (mod.replace(".", "/") + ".py")
                    found.setdefault(script, f"{wf_path.name}::{name}")
    return found


def _module_file(name: str) -> pathlib.Path | None:
    p = ROOT.joinpath(*name.split("."))
    if (p / "__init__.py").exists():
        return p / "__init__.py"
    if p.with_suffix(".py").exists():
        return p.with_suffix(".py")
    return None


def _imports(path: pathlib.Path):
    pkg = list(path.relative_to(ROOT).with_suffix("").parts)[:-1]   # a package's __init__ too
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[: len(pkg) - (node.level - 1)]
                full = ".".join(base + ([node.module] if node.module else []))
            else:
                full = node.module or ""
            yield full, node.lineno
            for a in node.names:                 # `from pkg import submodule`
                yield f"{full}.{a.name}", node.lineno


def third_party_imports(entry: pathlib.Path) -> list[str]:
    """Every non-stdlib import reachable from `entry`, as "name <- file:line"."""
    seen: set[pathlib.Path] = set()
    todo, bad = [entry], []
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for name, line in _imports(f):
            top = name.split(".")[0]
            if top in LOCAL:
                bits = name.split(".")
                todo += [m for i in range(1, len(bits) + 1) if (m := _module_file(".".join(bits[:i])))]
            elif top and top not in STDLIB:
                bad.append(f"{top} <- {f.relative_to(ROOT).as_posix()}:{line}")
    return sorted(set(bad))


def test_the_bare_python_jobs_are_found_from_the_workflows():
    jobs = bare_python_scripts()
    assert jobs.get("scripts/morning_plays.py") == "morning_plays.yml::digest"
    assert "scripts/scan_gate.py" in jobs            # the scan gate runs before any install
    for script in jobs:
        assert (ROOT / script).exists(), script


def test_every_bare_python_script_imports_only_the_standard_library():
    bad = {s: third_party_imports(ROOT / s) for s in bare_python_scripts()}
    assert not {s: b for s, b in bad.items() if b}, bad


def test_the_walk_sees_an_import_inside_a_function(tmp_path, monkeypatch):
    """The 3 Nov shape: a function-level import of a module that reaches numpy."""
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    (tmp_path / "scanner").mkdir()
    (tmp_path / "scanner" / "__init__.py").write_text("")
    (tmp_path / "scanner" / "heavy.py").write_text("from . import light\nimport numpy as np\n")
    (tmp_path / "scanner" / "light.py").write_text("import json\n")
    entry = tmp_path / "entry.py"
    entry.write_text("import os\n\ndef f():\n    from scanner.heavy import x\n    return x\n")
    assert third_party_imports(entry) == ["numpy <- scanner/heavy.py:2"]


_BLOCK = """
import sys
class _Bare:
    BLOCKED = {"numpy", "pandas", "yfinance", "requests", "scipy"}
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r} (a bare runner)")
        return None
sys.meta_path.insert(0, _Bare())
import runpy
sys.argv = ["scripts/morning_plays.py"] + sys.argv[1:]
runpy.run_path("scripts/morning_plays.py", run_name="__main__")
"""


def test_the_digest_runs_with_the_book_full_on_a_bare_python(tmp_path):
    """The crash replayed: a full book sends the digest down the time-stop
    path. With numpy and pandas unimportable it must still print the line."""
    d = tmp_path / "data"
    d.mkdir()
    now = dt.datetime.now(dt.timezone.utc)
    for m, sym in (("asx", "JHX"), ("nasdaq", "HLIT"), ("crypto", "LINK")):
        (d / f"{m}_vivek.json").write_text(json.dumps(
            {"generated_at": now.isoformat(), "results": [_row(sym, grade="A+")]}))
    (d / "bot_rules.json").write_text(json.dumps(
        {"open_total": 60, "max_open_total": 60, "max_hold_days": 28}))
    entry = (now.date() - dt.timedelta(days=5)).isoformat()
    (d / "vivek_bot_book.json").write_text(json.dumps(
        {"open": [{"entry_date": entry, "market": "crypto", "tp1_hit": False}]}))
    env = {k: v for k, v in os.environ.items() if not k.startswith("DISCORD")}
    out = subprocess.run(
        [sys.executable, "-c", _BLOCK, "--force", "--dry-run", "--data-dir", str(d),
         "--seen-file", str(tmp_path / "seen.json")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    due = now.date() - dt.timedelta(days=5) + dt.timedelta(days=29)
    assert "Bot book full (60/60)" in out.stdout and f"{due:%a} {due.day} {due:%b}" in out.stdout, out.stdout

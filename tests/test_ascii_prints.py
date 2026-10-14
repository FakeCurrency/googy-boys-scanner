"""Scanner prints and log lines are ASCII (project rule 9; REFINE200 #97).

Windows consoles and redirected output are cp1252, which has no arrow, no
warning sign and no Greek: a print carrying one raises UnicodeEncodeError and
a logging call prints "--- Logging error ---" instead of the message. 47 such
strings had crept into scanner/. This walks every print() / logger call under
scanner/ and fails on a non-ASCII character in any string literal it passes.
Docstrings, comments and the UI text the scan PUBLISHES are not checked here:
they never reach a console.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
_LOGGERS = {"log", "logger", "logging", "_log", "LOG"}


def _is_console_call(node: ast.Call) -> bool:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id == "print"
    if isinstance(f, ast.Attribute) and f.attr in _LOG:
        owner = getattr(f.value, "id", "") or getattr(f.value, "attr", "")
        return owner in _LOGGERS
    return False


def offenders(root: pathlib.Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_console_call(node)):
                continue
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                        and not sub.value.isascii()):
                    bad = "".join(sorted({c for c in sub.value if ord(c) > 127}))
                    out.append(f"{p.relative_to(ROOT)}:{sub.lineno} {bad!r}")
    return out


def test_every_scanner_print_and_log_string_is_ascii():
    bad = offenders(ROOT / "scanner")
    assert not bad, "non-ASCII in a console string (cp1252 consoles):\n" + "\n".join(bad)


def test_the_walker_actually_finds_one(tmp_path):
    """The guard must not pass by never matching anything."""
    pkg = tmp_path / "scanner"
    pkg.mkdir()
    (pkg / "m.py").write_text(
        'import logging\nlog = logging.getLogger(__name__)\n'
        'print(f"a \\u2192 b {1}")\nlog.info("x \\u2014 y")\n'
        '"""docstring \\u2014 fine"""\n# comment \\u2192 fine\n', encoding="utf-8")
    global ROOT
    old, ROOT = ROOT, tmp_path
    try:
        assert len(offenders(pkg)) == 2
    finally:
        ROOT = old

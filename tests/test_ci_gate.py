"""The CI gate's own shape (REFINE200, 2026-10-14).

Pins the decisions made about HOW the tests run, each of which used to be a
convention that nothing checked:

  * production installs carry no test tooling (#82/#83) -- requirements.txt is
    what every scheduled workflow installs, so it holds only what the scanner
    imports; requirements-dev.txt adds the test pins and only test.yml reads it;
  * the pytest step prints its totals (`-qq` hid "N passed, M skipped");
  * one red step does not hide the gates after it;
  * the e2e toolchain is pinned, and the Playwright pin is in the screenshot
    baseline key, so a browser upgrade re-cuts baselines instead of diffing a
    new Chromium against an old one's pixels;
  * every path a suite reads is in the push filter (TOP100 #48; #86 reviews/).
"""

import ast
import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
TEST_YML = WF / "test.yml"
DOC = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))
TEST_ONLY = ("pytest", "pyyaml", "pytest-xdist", "execnet", "pyflakes")
INDEPENDENT = "success() || failure()"


def _reqs(name):
    out = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-r"):
            pkg, _, ver = line.partition("==")
            out[pkg.strip().lower()] = ver.strip()
    return out


def _steps(job):
    return DOC["jobs"][job]["steps"]


def _step(job, name_prefix):
    found = [s for s in _steps(job) if str(s.get("name", "")).startswith(name_prefix)]
    assert len(found) == 1, f"{job}: expected one step named {name_prefix!r}, got {len(found)}"
    return found[0]


# -- requirements: production vs the test gate ----------------------------------

def test_production_requirements_carry_no_test_tooling_and_no_anthropic():
    prod = _reqs("requirements.txt")
    leaked = sorted(set(prod) & set(TEST_ONLY + ("anthropic",)))
    assert not leaked, (
        f"requirements.txt carries {leaked}: every scheduled workflow installs it, so a "
        "test-only package belongs in requirements-dev.txt")
    assert all(prod.values()), f"requirements.txt must pin exactly (==): {prod}"


def test_the_dev_file_extends_production_and_pins_every_test_package():
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^-r requirements\.txt\s*$", text, re.M), (
        "requirements-dev.txt must include requirements.txt, or CI tests a different "
        "dependency set from the one production runs")
    dev = _reqs("requirements-dev.txt")
    for pkg in TEST_ONLY:
        assert dev.get(pkg), f"requirements-dev.txt must pin {pkg} exactly (==)"


def test_nothing_shipped_imports_a_test_only_package():
    """The split is only safe while no production module imports these."""
    banned = {"yaml", "pytest", "xdist", "pyflakes", "anthropic"}
    hits = []
    for top in ("scanner", "phasemap", "scripts"):
        for p in (ROOT / top).rglob("*.py"):
            if "tests" in p.relative_to(ROOT).parts:
                continue
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                hits += [f"{p.relative_to(ROOT)}: {n}" for n in names
                         if n.split(".")[0] in banned]
    assert not hits, f"production code imports a package only requirements-dev.txt installs: {hits}"


def test_only_the_test_gate_installs_the_dev_file():
    install = _step("python", "Install dependencies")["run"]
    assert "requirements-dev.txt" in install
    for wf in sorted(WF.glob("*.yml")):
        if wf.name == "test.yml":
            continue
        assert "requirements-dev.txt" not in wf.read_text(encoding="utf-8"), (
            f"{wf.name} installs the test tooling; production workflows install requirements.txt")


# -- the pytest step -----------------------------------------------------------

def test_pytest_prints_its_totals_and_runs_in_parallel():
    run = _step("python", "pytest")["run"]
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert re.search(r"^addopts\s*=.*-q\b", ini, re.M), "re-read this test: pytest.ini dropped -q"
    assert not re.search(r"(^|\s)-q+(\s|$)", run), (
        "pytest.ini already passes -q; another one makes -qq, which drops the "
        "'N passed, M skipped' line the workflow header calls its smell test")
    assert "-rs" in run, "every skip should name its reason in the log"
    assert "-n auto" in run and "--dist loadfile" in run


def test_pyflakes_lints_the_tests():
    assert "pyflakes tests phasemap/tests" in _step("python", "pyflakes")["run"]


# -- one red step must not hide the rest -----------------------------------------

def test_every_javascript_gate_runs_after_an_earlier_one_failed():
    gates = [s for s in _steps("javascript") if "run" in s]
    assert gates, "the javascript job has no run steps -- re-point this test"
    missing = [s["name"] for s in gates if INDEPENDENT not in str(s.get("if", ""))]
    assert not missing, (
        f"these javascript steps are skipped once any earlier step fails: {missing}. "
        f"Give each `if: {INDEPENDENT}`.")


def test_every_e2e_gate_runs_after_an_earlier_one_failed():
    steps = _steps("e2e")
    install = _step("e2e", "Install Playwright")
    assert install.get("id") == "toolchain"
    after = steps[steps.index(install) + 1:]
    gates = [s for s in after if not str(s.get("name", "")).startswith("Upload")]
    assert len(gates) >= 6, [s.get("name") for s in gates]
    for s in gates:
        cond = str(s.get("if", ""))
        assert INDEPENDENT in cond and "steps.toolchain.outcome == 'success'" in cond, (
            f"e2e step {s.get('name')!r} is skipped after an earlier gate fails (or runs "
            f"without a toolchain): `if: {cond or '(none)'}`")


# -- the pinned e2e toolchain -------------------------------------------------------

def test_the_e2e_tools_are_pinned_and_playwright_keys_the_baselines():
    env = DOC["jobs"]["e2e"]["env"]
    pkgs = {"playwright": "PLAYWRIGHT_VERSION", "lighthouse": "LIGHTHOUSE_VERSION",
            "chrome-launcher": "CHROME_LAUNCHER_VERSION", "pixelmatch": "PIXELMATCH_VERSION",
            "pngjs": "PNGJS_VERSION"}
    install = _step("e2e", "Install Playwright")["run"]
    for pkg, var in pkgs.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", str(env.get(var, ""))), f"{var} must be an exact version"
        assert f'"{pkg}@${{{var}}}"' in install, f"the install line does not pin {pkg} to ${var}"
    key = _step("e2e", "Restore screenshot baselines")["with"]["key"]
    assert "${{ env.PLAYWRIGHT_VERSION }}" in key, (
        "the baseline key must carry the Playwright pin: a new Chromium rasterises differently")
    assert "hashFiles('test/e2e/fixtures/data/**')" in key, (
        "the key must digest every fixture, subdirectories included")


# -- the push filter covers what the suites read ----------------------------------

@pytest.mark.parametrize("path", ["requirements-dev.txt", "reviews/**"])
def test_the_push_filter_covers(path):
    assert path in DOC[True]["push"]["paths"], (
        f"{path} is read by the gate but missing from test.yml's push filter -- an edit to "
        "it alone would ship with every check skipped (TOP100 #48)")

"""The deep-chart-history change (2026-09-19) must not reach the scanner.

Owner, shipping it: "I don't want to lose the edge of the scanner rules etc
otherwise this defeats the purpose."

Deep history was added to the CHART path only -- functions/api/_prices.js,
functions/api/price.js and public/js/chart.js. The engine that decides which
names appear, what grade they get and where the levels sit still downloads
exactly what it always did. That is a structural claim, so it is tested rather
than promised: these are the assertions that fail if the change ever leaks into
the signal path.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENGINE_DIRS = ("scanner", "phasemap")
DEEP_MARKERS = ("fetchYahooDeep", "deepYears", "DAILY_RANGE",
                "CHART_MAX_YEARS", "yahoo-deep", "25y")


def _engine_files():
    for d in ENGINE_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if "test" in p.parts:
                continue
            yield p


def test_the_scan_still_downloads_exactly_five_years():
    """The number the engine feeds its levels from. If deep history ever gets
    wired into the scan, THIS is the line that moves, and moving it changes
    which trades are taken -- an owner decision, not a chart change."""
    cfg = (ROOT / "scanner" / "config.py").read_text(encoding="utf-8")
    assert 'VIVEK_DATA_PERIOD      = "5y"' in cfg or 'VIVEK_DATA_PERIOD = "5y"' in cfg, (
        "VIVEK_DATA_PERIOD moved off 5y — the scan's history changed, which changes "
        "grades and levels. That is a trade decision and needs the owner's sign-off."
    )


def test_no_engine_file_mentions_the_deep_chart_machinery():
    offenders = []
    for p in _engine_files():
        src = p.read_text(encoding="utf-8", errors="ignore")
        for marker in DEEP_MARKERS:
            if marker in src:
                offenders.append(f"{p.relative_to(ROOT)} mentions {marker!r}")
    assert not offenders, (
        "the chart-depth change leaked into the engine:\n  " + "\n  ".join(offenders))


def test_the_deep_path_lives_only_in_the_three_chart_files():
    """Whitelist, so a fourth consumer has to be a deliberate act."""
    allowed = {
        "functions/api/_prices.js", "functions/api/price.js", "public/js/chart.js",
        "test/deep_history.test.js", "scripts/data_depth.py",
        "tests/test_scanner_untouched_by_chart_depth.py",
        ".github/workflows/test.yml", ".github/workflows/data_depth.yml",
    }
    found = set()
    for pat in ("*.js", "*.py"):
        for p in ROOT.rglob(pat):
            rel = p.relative_to(ROOT).as_posix()
            if rel.startswith((".git/", "node_modules/", "backups/")):
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "fetchYahooDeep" in src or "CHART_MAX_YEARS" in src:
                found.add(rel)
    extra = found - allowed
    assert not extra, f"deep-history code appeared somewhere new: {sorted(extra)}"


def test_the_broker_never_sees_it():
    """The bot book is the one real track record; nothing about how it picks or
    sizes may move because a chart got longer."""
    for p in (ROOT / "scanner" / "broker").rglob("*.py"):
        src = p.read_text(encoding="utf-8", errors="ignore")
        for marker in DEEP_MARKERS:
            assert marker not in src, f"{p.name} references {marker!r}"

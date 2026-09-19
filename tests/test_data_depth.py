"""scripts/data_depth.py — the probe is read-only, so these tests cover the two
things that could make it LIE: the coarse-interval detector and the stitcher."""
import datetime as dt
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("data_depth", ROOT / "scripts" / "data_depth.py")
dd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dd)

DAY = 86400


def _result(ts, closes=None, opens=None, highs=None, lows=None):
    n = len(ts)
    closes = closes if closes is not None else [10.0] * n
    return {"timestamp": list(ts), "indicators": {"quote": [{
        "close": closes,
        "open": opens if opens is not None else [9.0] * n,
        "high": highs if highs is not None else [11.0] * n,
        "low": lows if lows is not None else [8.0] * n,
    }]}}


# ---------------------------------------------------------------- the detector
def test_true_daily_bars_are_not_called_degraded_even_with_weekends():
    """The whole probe turns on this call. Daily data has 3-day weekend gaps in
    it, so a MEAN would drift over the 1.8x line and report every healthy series
    as coarse; the median stays at one day. That is why it is a median."""
    ts, t = [], 0
    for week in range(12):                      # Mon..Fri then a weekend jump
        for d in range(5):
            ts.append(t); t += DAY
        t += 2 * DAY
    out = dd.describe(_result(ts))
    assert out["gap_days"] == 1.0
    assert out["degraded"] is False


def test_weekly_candles_returned_for_a_daily_request_are_caught():
    ts = [i * 7 * DAY for i in range(40)]
    out = dd.describe(_result(ts))
    assert out["degraded"] is True
    assert out["gap_days"] == 7.0


def test_monthly_candles_are_caught_too():
    # The exact failure this repo measured on 2026-08-15: max/1d came back monthly.
    ts = [i * 30 * DAY for i in range(30)]
    assert dd.describe(_result(ts))["degraded"] is True


def test_the_threshold_matches_the_shipped_js_rule():
    """_prices.js intervalDegraded() uses got > want * 1.8. If that number moves
    there and not here the probe and production disagree about the same tape."""
    js = (ROOT / "functions" / "api" / "_prices.js").read_text(encoding="utf-8")
    assert "want * 1.8" in js, "the JS threshold moved — update data_depth.describe()"
    src = (ROOT / "scripts" / "data_depth.py").read_text(encoding="utf-8")
    assert "want_interval_sec * 1.8" in src


# ------------------------------------------------------------- dead-tape share
def test_null_and_single_print_sessions_both_count_as_dead():
    """An ASX thin name arrives padded: some sessions null, some a single print
    where o==h==l==c. Both are 'no usable trade' for structure TA, and counting
    only nulls would under-report the ASX problem the owner is asking about."""
    ts = [i * DAY for i in range(4)]
    out = dd.describe(_result(ts,
                              closes=[10.0, None, 12.0, 13.0],
                              opens=[10.0, None, 12.0, 9.0],
                              highs=[10.0, None, 12.0, 14.0],
                              lows=[10.0, None, 12.0, 8.0]))
    assert out["nulls"] == 1
    assert out["flat"] == 2            # bar 0 and bar 2 are single prints
    assert out["dead_share"] == 0.75


def test_a_clean_tape_reports_no_dead_sessions():
    out = dd.describe(_result([i * DAY for i in range(10)]))
    assert out["dead_share"] == 0.0


# ------------------------------------------------------------------ describe()
def test_span_is_measured_in_years_between_first_and_last_bar():
    ts = [int(dt.datetime(2020, 1, 2, tzinfo=dt.timezone.utc).timestamp()),
          int(dt.datetime(2025, 1, 2, tzinfo=dt.timezone.utc).timestamp())]
    out = dd.describe(_result(ts))
    assert out["years"] == pytest.approx(5.0, abs=0.02)
    assert out["first"] == dt.date(2020, 1, 2)


def test_a_failed_or_empty_fetch_reports_not_ok_rather_than_zero():
    # A zeroed row would read as "this source has no history", which is a
    # different claim from "the probe could not ask".
    assert dd.describe(None) == {"ok": False}
    assert dd.describe({"timestamp": [], "indicators": {"quote": [{}]}}) == {"ok": False}


# ------------------------------------------------------------------ stitching
def test_stitched_windows_are_deduped_and_sorted(monkeypatch):
    """Adjacent windows overlap at their shared boundary, so a naive concat
    double-counts bars and overstates depth — the one way this probe could
    flatter the answer it exists to measure."""
    base = int(dt.datetime(2000, 1, 3, tzinfo=dt.timezone.utc).timestamp())
    calls = []

    def fake(symbol, *, interval="1d", rng=None, p1=None, p2=None):
        calls.append((p1, p2))
        start = len(calls) * 100
        # deliberately hand back an overlapping, DESCENDING chunk
        ts = [base + (start + i) * DAY for i in range(120)][::-1]
        return _result(ts)

    monkeypatch.setattr(dd, "yahoo_chart", fake)
    out = dd.stitch_windows("BHP.AX", chunk_years=5, back_years=20)
    assert out["ok"] and out["chunks_ok"] == 4
    # Four chunks of 120 bars starting at day 100/200/300/400 overlap by 100 each,
    # so the UNION is days 100..519 = 420 bars. A naive concat would say 480.
    assert out["bars"] == 420, "overlapping windows must be deduped, not concatenated"
    assert out["first"] < out["last"], "stitched series must come back in ascending order"
    assert out["degraded_chunks"] == 0


def test_stitching_walks_back_in_chunk_sized_windows(monkeypatch):
    seen = []

    def fake(symbol, *, interval="1d", rng=None, p1=None, p2=None):
        seen.append(round((p2 - p1) / (365 * DAY)))
        return _result([i * DAY for i in range(10)])

    monkeypatch.setattr(dd, "yahoo_chart", fake)
    dd.stitch_windows("AAPL", chunk_years=5, back_years=20)
    assert seen == [5, 5, 5, 5], f"expected four 5-year windows, got {seen}"


def test_no_usable_chunk_is_reported_as_not_ok(monkeypatch):
    monkeypatch.setattr(dd, "yahoo_chart", lambda *a, **k: None)
    assert dd.stitch_windows("NOPE.AX", 5, 10) == {"ok": False}


# --------------------------------------------------------------------- stooq
def test_stooq_maps_asx_to_the_au_suffix_and_us_otherwise(monkeypatch):
    seen = {}

    def fake_get(url, timeout=25):
        seen["url"] = url
        return b"Date,Open,High,Low,Close,Volume\n2005-01-03,1,1,1,1,10\n2026-09-18,2,2,2,2,20\n"

    monkeypatch.setattr(dd, "_get", fake_get)
    out = dd.stooq("BHP.AX")
    assert "s=bhp.au" in seen["url"]
    assert out["ok"] and out["bars"] == 2 and out["years"] > 21
    dd.stooq("AAPL")
    assert "s=aapl.us" in seen["url"]


def test_stooq_failure_and_empty_body_never_raise(monkeypatch):
    monkeypatch.setattr(dd, "_get", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    assert dd.stooq("BHP.AX")["ok"] is False
    monkeypatch.setattr(dd, "_get", lambda *a, **k: b"Exceeded the daily hits limit")
    out = dd.stooq("BHP.AX")
    assert out["ok"] is False and "Exceeded" in out["why"]


# ------------------------------------------------------------------- read-only
def test_the_probe_writes_nothing():
    """Checked on the AST, not on the text: the first version of this test
    grepped for the word "commit" and tripped over the docstring that PROMISES
    the probe never commits. A prose match is not a property."""
    import ast
    tree = ast.parse((ROOT / "scripts" / "data_depth.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                assert not str(n).startswith(("subprocess", "shutil", "os.path")), f"probe imports {n}"
        if isinstance(node, ast.Call):
            fn = node.func
            # bare open() would be a file write or read; urlopen is the only one allowed
            if isinstance(fn, ast.Name):
                assert fn.id != "open", "the probe must not open files"
                assert fn.id != "exec", "no exec"
            if isinstance(fn, ast.Attribute):
                assert fn.attr not in ("write", "write_text", "replace", "remove", "mkdir", "unlink"), \
                    f"probe calls {fn.attr}() — it must stay read-only"


def test_the_workflow_is_manual_read_only_and_never_touches_git():
    wf = (ROOT / ".github" / "workflows" / "data_depth.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in wf
    body = wf.split("jobs:")[1]
    assert "git " not in body, "data_depth.yml must never touch git"
    assert "assert_staged" not in body, "it commits nothing, so it must not gate on staging"
    assert "workflow_dispatch" in wf
    assert "\n  schedule:" not in wf, "manual only — the answer changes only when a source does"


def test_free_text_inputs_travel_through_env_not_interpolation():
    """The 2026-07-20 security pass rule: a ${{ }} value must never be expanded
    inside a run: block, where a crafted input would be shell."""
    wf = (ROOT / ".github" / "workflows" / "data_depth.yml").read_text(encoding="utf-8")
    run_blocks = wf.split("run: |")[1:]
    for blk in run_blocks:
        assert "${{" not in blk.split("- name:")[0], "interpolated input inside a run block"
    for var in ("SYMBOLS", "CHUNK", "BACK"):
        assert f"{var}: ${{{{ github.event.inputs." in wf

"""Failures that printed nothing — TOP100 #60, #66 and #67 (2026-07-28).

Three swallow sites, one shape of bug: the scan caught a per-ticker exception ON
PURPOSE (one malformed frame out of 2,212 must not take a market down) and then
threw the fact away, so a name that failed EVERY session was byte-identical in
the output to a name that simply never set up.

* **#60** `scan.py` printed behind ``if progress:`` and the only production
  caller passes ``progress=False``.
* **#66** `spec_run.py` used a bare ``continue`` and, worse, a bare ``pass``.
* **#67** `run.py` caught a whole market's failure, printed one line, and let
  the process exit **0** — so a scan that scanned nothing looked to CI exactly
  like a scan that found nothing.

The tests below are weighted towards what the accounting REFUSES to do, because
that is where its safety lives: it never re-raises inside a scan loop, never
drops a name, never moves a threshold, and never bumps a schema. The one place
it does change behaviour is #67's exit code, and the last section pins both the
placement of that exit and the one path it deliberately does NOT count.
"""

import ast
import pathlib

import pytest

from scanner import config, scanerrors

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _boom(msg="kaboom", cls=ValueError):
    return cls(msg)


# ── _clean · a message has to survive a Windows console and a JSON field ─────

def test_a_multiline_message_is_collapsed_to_one_line():
    """These go into a single summary line; an embedded pandas traceback would
    wreck it, and wreck the JSON field a human skims just as badly."""
    out = scanerrors._clean("first line\nsecond line\n\tindented", 500)
    assert "\n" not in out and "\t" not in out
    assert out == "first line second line indented"


def test_a_non_ascii_message_is_folded_because_windows_consoles_are_cp1252():
    """Project rule 9 applies to whatever an arbitrary third-party exception
    decided to put in its message — we do not control that string."""
    out = scanerrors._clean("bad tick — price €1.50 → nan", 500)
    out.encode("cp1252")            # the actual requirement; raises if broken
    assert out.isascii()


def test_a_long_message_is_truncated_with_an_ellipsis_not_silently_cut():
    out = scanerrors._clean("x" * 400, 40)
    assert len(out) == 40 and out.endswith("...")


def test_a_zero_limit_means_no_truncation_rather_than_an_empty_string():
    """0 has to read as 'unlimited' — the alternative is a config typo silently
    erasing every message in the file."""
    assert scanerrors._clean("y" * 300, 0) == "y" * 300


# ── collection ───────────────────────────────────────────────────────────────

def test_an_empty_log_is_falsey_and_zero_length():
    log = scanerrors.ErrorLog("vivek [asx]")
    assert not log and len(log) == 0


def test_record_never_raises_on_a_hostile_exception():
    """An exception whose __str__ itself throws must not take down the scan loop
    that is CATCHING it — that would convert a swallowed error into a fatal one,
    which is the exact opposite of the point."""
    class Hostile(Exception):
        def __str__(self):
            raise RuntimeError("nope")

    log = scanerrors.ErrorLog("vivek [asx]")
    log.record("BHP", Hostile())
    assert len(log) == 1
    assert log.kinds()["Hostile"] == 1
    log.summary(10).encode("cp1252")


def test_a_non_exception_is_recorded_as_unknown_rather_than_dropped():
    log = scanerrors.ErrorLog("vivek [asx]")
    log.record("BHP", "not an exception")
    assert log.kinds() == {"unknown": 1}


def test_kinds_counts_by_exception_class():
    log = scanerrors.ErrorLog("vivek [asx]")
    for sym in ("A", "B", "C"):
        log.record(sym, _boom(cls=KeyError))
    log.record("D", _boom(cls=ValueError))
    assert log.kinds() == {"KeyError": 3, "ValueError": 1}


# ── sample · diversity first, because a systemic break floods one kind ───────

def test_the_sample_is_capped():
    log = scanerrors.ErrorLog("vivek [asx]", sample_max=3)
    for i in range(50):
        log.record(f"T{i}", _boom())
    assert len(log.sample()) == 3
    assert len(log) == 50, "the COUNT is never capped, only the sample"


def test_the_sample_keeps_one_of_every_kind_before_repeating_a_kind():
    """The whole reason this is not a head-of-list slice. A column rename throws
    the same KeyError on 2,000 names; a plain head sample would be twelve copies
    of it and would cut the ONE rare failure, which is the interesting row."""
    log = scanerrors.ErrorLog("vivek [asx]", sample_max=3)
    for i in range(20):
        log.record(f"COMMON{i}", _boom(cls=KeyError))
    log.record("RARE", _boom(cls=ZeroDivisionError))
    kinds = {row["error"].split(":")[0] for row in log.sample()}
    assert "ZeroDivisionError" in kinds


def test_the_sample_is_deterministic_for_a_given_run():
    def build():
        log = scanerrors.ErrorLog("vivek [asx]", sample_max=5)
        for i, cls in enumerate((KeyError, ValueError, KeyError, TypeError, KeyError)):
            log.record(f"T{i}", _boom(cls=cls))
        return log.sample()

    assert build() == build()


def test_a_zero_cap_publishes_the_count_alone():
    """SCAN_ERROR_SAMPLE_MAX = 0 is the documented 'count only' setting."""
    log = scanerrors.ErrorLog("vivek [asx]", sample_max=0)
    log.record("BHP", _boom())
    assert log.sample() == [] and log.payload()["errors"] == 1


def test_every_sample_row_carries_the_symbol_and_the_kind():
    log = scanerrors.ErrorLog("vivek [asx]")
    log.record("BHP.AX", _boom("no column 'Close'", cls=KeyError))
    row = log.sample()[0]
    assert row["symbol"] == "BHP.AX"
    assert row["error"].startswith("KeyError:") and "Close" in row["error"]


# ── summary · the line that gets read at a glance ────────────────────────────

def test_a_clean_run_still_prints_a_line(capsys):
    """'No line' and 'the accounting never ran' are the same thing in a log. A
    standing `0 failed of 2212` is what makes a jump to 41 legible."""
    line = scanerrors.ErrorLog("vivek [asx]").report(2212)
    assert "0 failed of 2212" in line
    assert line in capsys.readouterr().out


def test_the_label_names_the_lens_AND_the_market():
    """A full cycle prints several of these back to back, so a bare
    'errors: 41' does not tell you which market to go and look at."""
    log = scanerrors.ErrorLog("specs [nasdaq]")
    log.record("AAPL", _boom())
    assert "specs [nasdaq]" in log.summary(100)


def test_a_high_failure_rate_is_marked_loud():
    log = scanerrors.ErrorLog("vivek [asx]", loud_pct=5.0)
    for i in range(10):
        log.record(f"T{i}", _boom())
    assert log.summary(100).lstrip().startswith("!!")


def test_a_low_failure_rate_is_not_marked_loud():
    log = scanerrors.ErrorLog("vivek [asx]", loud_pct=5.0)
    log.record("T", _boom())
    assert "!!" not in log.summary(1000)


def test_the_loud_marker_leads_so_it_survives_a_long_tail_of_kinds():
    """A trailing marker is the first thing lost when the kind list is long,
    which is exactly the run where it matters most."""
    log = scanerrors.ErrorLog("vivek [asx]", loud_pct=1.0, kinds_max=8)
    for i, cls in enumerate((KeyError, ValueError, TypeError, IndexError,
                             ZeroDivisionError, AttributeError)):
        log.record(f"T{i}", _boom("a" * 100, cls=cls))
    assert log.summary(10).lstrip().startswith("!!")


def test_a_zero_loud_pct_turns_the_marker_off_entirely():
    log = scanerrors.ErrorLog("vivek [asx]", loud_pct=0)
    for i in range(99):
        log.record(f"T{i}", _boom())
    assert "!!" not in log.summary(100)


def test_extra_kinds_are_counted_rather_than_silently_dropped():
    log = scanerrors.ErrorLog("vivek [asx]", kinds_max=2)
    for i, cls in enumerate((KeyError, ValueError, TypeError, IndexError)):
        log.record(f"T{i}", _boom(cls=cls))
    assert "+2 more" in log.summary(10)


def test_the_summary_is_always_cp1252_encodable():
    """Rule 9: a scanner print that a Windows console cannot encode is a crash,
    not a cosmetic problem."""
    log = scanerrors.ErrorLog("vivek [asx]")
    log.record("TÉST", _boom("— € →"))
    log.summary(10).encode("cp1252")


def test_a_summary_with_no_denominator_does_not_divide_by_zero():
    log = scanerrors.ErrorLog("vivek [asx]")
    log.record("T", _boom())
    assert "1 failed" in log.summary(0)


# ── payload · additive, and published even at zero ───────────────────────────

def test_the_payload_is_published_even_when_nothing_failed():
    """'Present and 0' is what distinguishes 'accounted for, none failed' from
    'this file predates the accounting'."""
    assert scanerrors.ErrorLog("vivek [asx]").payload() == {"errors": 0, "error_sample": []}


def test_the_payload_keys_are_the_same_two_words_in_both_scan_loops():
    """scan.py and spec_run.py mean the same thing by 'a name that failed to
    produce a row', so a reader must not have to learn two vocabularies."""
    src = (_ROOT / "scanner" / "spec_run.py").read_text(encoding="utf-8")
    assert "**errors.payload()" in src
    assert "chart_errors" in src, "the second, different failure mode stays separate"


def test_a_prefix_is_how_one_payload_carries_two_failure_modes():
    """Summing them is the thing to avoid: '41 failed' that could mean either
    '41 names are missing from the page' or '41 names are on the page with an
    empty chart' is a number you cannot act on."""
    log = scanerrors.ErrorLog("spec charts [asx]")
    log.record("ABC", _boom())
    assert log.payload("chart_") == {"chart_errors": 1,
                                     "chart_error_sample": log.sample()}
    assert set(log.payload()) & set(log.payload("chart_")) == set(), \
        "a prefixed payload must never collide with the unprefixed one"


def test_the_price_snapshot_failure_is_counted_apart_from_the_setup_failure():
    """Different blast radius, so a shared count would hide it. A throw in the
    price snapshot does not cost a SETUP — the name is still scored — it costs
    the published MARK, and the journal then prices a held position off a stale
    one without saying so."""
    src = (_ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert 'ErrorLog(f"vivek prices [{market_key}]")' in src
    assert 'price_errors.payload("price_")' in src
    assert "price_errors.record(symbol, e)" in src


def test_the_schema_version_is_deliberately_not_bumped():
    """Additive fields need no bump, and bumping is actively HARMFUL here: it
    marks every already-committed scan file as a build behind and shows a
    stale-data warning on the site until all three markets have rescanned."""
    assert config.VIVEK_SCHEMA_VERSION == 4


@pytest.mark.parametrize("name", ["SCAN_ERROR_SAMPLE_MAX", "SCAN_ERROR_MSG_MAX",
                                  "SCAN_ERROR_KINDS_MAX", "SCAN_ERROR_LOUD_PCT"])
def test_every_cap_lives_in_config(name):
    """Project rule 3 — a threshold used anywhere is declared here first."""
    assert isinstance(getattr(config, name), (int, float))


def test_the_caps_are_read_at_construction_not_at_import():
    """So a test (or a future CLI flag) can move one without reloading the
    module, which is how the caps became untestable in the first place."""
    log = scanerrors.ErrorLog("vivek [asx]", sample_max=1, msg_max=10,
                              kinds_max=1, loud_pct=99.0)
    assert (log.sample_max, log.msg_max, log.kinds_max, log.loud_pct) == (1, 10, 1, 99.0)


# ── #60 / #66 · the loops still swallow, they just stopped being silent ──────

def _fn(path, name):
    tree = ast.parse((_ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


@pytest.mark.parametrize("path,name", [("scanner/scan.py", "scan_vivek_market"),
                                       ("scanner/spec_run.py", "scan_market")])
def test_no_scan_loop_handler_re_raises(path, name):
    """The accounting must never convert a swallowed per-ticker error into a
    fatal one: one bad frame out of 2,212 still must not kill a market."""
    for node in ast.walk(_fn(path, name)):
        if isinstance(node, ast.ExceptHandler):
            for inner in ast.walk(node):
                assert not isinstance(inner, ast.Raise), \
                    f"{path}:{name} re-raises inside an except handler"


def test_scan_py_still_prints_the_interactive_warning():
    """The `if progress:` line was the ONLY reason a manual run was debuggable;
    the count is an addition to it, not a replacement."""
    src = (_ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert "if progress:" in src and "warning: VIVEK" in src
    assert "errors.record(symbol, e)" in src


def test_the_two_spec_failure_modes_are_counted_separately():
    """A build_row throw means the name is ABSENT from the page. A chart throw
    means the row IS published and its chart page is empty. Summing them would
    destroy the only distinction that makes either number actionable."""
    src = (_ROOT / "scanner" / "spec_run.py").read_text(encoding="utf-8")
    assert 'ErrorLog(f"specs [{market_key}]")' in src
    assert 'ErrorLog(f"spec charts [{market_key}]")' in src
    assert 'chart_errors.payload("chart_")' in src


def test_no_broad_handler_in_a_scan_loop_swallows_into_a_bare_pass():
    """`except Exception: pass` on the chart write was the worst of the three
    sites — it discarded an unknown failure and said nothing at all.

    Scoped to BROAD handlers on purpose. The prune's `except FileNotFoundError:
    pass` further down stays legal: it names one expected condition ("no chart
    directory yet") and passing on it is a decision, not a swallow. Banning
    every `pass` would push that one into a meaningless log line and teach the
    next reader that the rule is noise."""
    for path, name in (("scanner/scan.py", "scan_vivek_market"),
                       ("scanner/spec_run.py", "scan_market")):
        for node in ast.walk(_fn(path, name)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or getattr(node.type, "id", "") == "Exception"
            if broad:
                assert not all(isinstance(b, ast.Pass) for b in node.body), \
                    f"{path}:{name} still swallows an unknown failure silently"


# ── #67 · a market that threw must not exit 0 ────────────────────────────────

def test_run_main_exits_non_zero_when_a_market_throws():
    src = (_ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "failed_markets.append" in src
    assert "raise SystemExit(1)" in src


def test_the_exit_is_the_last_thing_main_does():
    """Placement is the whole design. Raising at the throw site would skip the
    sectors / breadth / HORIZON / REGIME / FX / bot_rules publishes that follow
    the loop, so ONE market's bad frame would stop the OTHER markets' surfaces
    from updating — a fix that costs more than the defect."""
    main = _fn("scanner/run.py", "main")
    raises = [n for n in ast.walk(main)
              if isinstance(n, ast.Raise) and "SystemExit" in ast.dump(n)]
    assert len(raises) == 1, "exactly one exit path"
    writes = [n.lineno for n in ast.walk(main)
              if isinstance(n, ast.Call) and "bot_rules.json" in ast.dump(n)]
    assert writes and raises[0].lineno > max(writes), \
        "bot_rules.json must still publish before the process gives up"


def test_the_deliberate_no_data_skip_is_not_counted_as_a_failure():
    """`no data for <market> (download blocked/empty) - keeping existing JSON`
    is a REPORTED decision, not a fault: it is already caught on scheduled runs
    by scan.yml's per-market assert_staged, and failing on it would turn every
    Yahoo-blocked crypto run red under crypto_bot.yml's plain `bash -e` step."""
    src = (_ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    head, _, tail = src.partition("keeping existing JSON")
    assert tail, "the deliberate skip message is gone — re-check this decision"
    nxt = tail.split("continue", 1)
    assert len(nxt) == 2, "the skip still uses `continue`, not a failure record"
    assert "failed_markets" not in nxt[0], \
        "the no-data skip must not be recorded as a scan failure"


def test_the_failure_summary_names_every_market_that_threw():
    """A count alone sends you to a 90-day-expiring Actions log to find out
    WHICH one; the summary has to carry the names and the exception types."""
    src = (_ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "for market_key, why in failed_markets:" in src
    assert 'f"{type(e).__name__}: {e}"' in src


def test_the_failure_summary_goes_to_stdout():
    """Actions interleaves stdout and stderr unreliably, so a summary written to
    stderr can surface ABOVE the very lines it is summarising."""
    src = (_ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    block = src.split("if failed_markets:", 1)[1].split("raise SystemExit", 1)[0]
    assert "sys.stderr" not in block and "file=" not in block
    assert "print(" in block

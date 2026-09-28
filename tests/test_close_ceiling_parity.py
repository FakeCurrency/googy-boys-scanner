"""The close-batch ceiling is ONE number in four places (owner, 2026-09-27).

The owner's 60 x $2,500 resize doubled the book cap from 30 to 60. A close-all
of a full book travels through four gates, and three of them cannot import
scanner/config.py (Workers runtime, browser, YAML prose), so each carries the
number as a literal:

    public/js/journal.js     CLOSE_ALL_MAX     -- refuses before any dispatch
    functions/api/close.js   batch length gate -- 400 before any dispatch
    scanner/broker/vivek_run CLOSE_BATCH_MAX   -- argparse cap in the workflow
    close_position.yml       "Max N." in the batch input description

A SPLIT CEILING LOSES CLOSES SILENTLY, which is the whole reason this file
exists. If the page and close.js say 60 while vivek_run says 30, a 31..60
close-all is ACCEPTED (the page reads "queued"), dispatched, and then dies in
the workflow with argparse's exit 2. That is not a push contention, so
push_exhausted is never set and the redispatch job does not retry it: the
positions stay open behind one red run the owner may never open. The reverse
split (page lower than the workflow) is merely a refusal, but it is still a
full book that cannot be closed in one run, the thing the ceiling exists for.

vivek_run DERIVES its cap from config rather than repeating it, so the Python
leg is tested behaviourally (its assignment is executed against a stand-in
config) and the three literals are pinned to it.

The second half pins the two OFFLINE FALLBACKS that state the same book shape
(status.js FALLBACK_CAP, journal.js POSITION_NOTIONAL) plus system.html's
static rulebook cells. None of them is a gate, but each is exactly what the
page shows when bot_rules.json cannot be fetched -- the moment the reader is
least able to check it (TOP100 #34, the mirror that drifted for months).
"""

import ast
import pathlib
import re
import types

from scanner import config
from scanner.broker import vivek_run as vr

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLOSE_JS = ROOT / "functions" / "api" / "close.js"
JOURNAL_JS = ROOT / "public" / "js" / "journal.js"
STATUS_JS = ROOT / "public" / "js" / "status.js"
SYSTEM_HTML = ROOT / "public" / "system.html"
VIVEK_RUN = ROOT / "scanner" / "broker" / "vivek_run.py"
CLOSE_YML = ROOT / ".github" / "workflows" / "close_position.yml"


def _one(pattern, text, where):
    found = re.findall(pattern, text)
    assert len(found) == 1, f"{where}: expected exactly one match for {pattern!r}, got {found}"
    return int(found[0])


def _expected():
    """The ceiling every leg must carry: the Python gate, itself = the book cap."""
    return vr.CLOSE_BATCH_MAX


# -- the ceiling ------------------------------------------------------------------

def test_the_python_cap_is_the_book_cap():
    total = int(config.VIVEK_BOT_MAX_OPEN_TOTAL)
    assert total > 0, "the global cap is off; the parity below still holds, re-read this test"
    assert vr.CLOSE_BATCH_MAX == total


def test_close_js_gate_and_its_message_carry_the_ceiling():
    src = CLOSE_JS.read_text(encoding="utf-8")
    gate = _one(r"body\.closes\.length > (\d+)", src, "close.js gate")
    msg = _one(r"Batch must contain 1-(\d+) closes", src, "close.js message")
    assert gate == msg, "close.js refuses at one number and tells the caller another"
    assert gate == _expected(), (
        f"close.js refuses batches over {gate} but the workflow's cap is {_expected()} -- "
        "a split ceiling loses closes silently (see module docstring)")


def test_journal_close_all_carries_the_ceiling():
    src = JOURNAL_JS.read_text(encoding="utf-8")
    n = _one(r"const CLOSE_ALL_MAX = (\d+);", src, "journal.js")
    assert n == _expected(), f"journal.js CLOSE_ALL_MAX {n} != workflow cap {_expected()}"


def test_the_workflow_description_states_the_ceiling():
    src = CLOSE_YML.read_text(encoding="utf-8")
    block = src[src.index("      batch:"):]
    block = block[:block.index("required:")]
    n = _one(r"Max (\d+)\.", block, "close_position.yml batch description")
    assert n == _expected(), (
        f"close_position.yml tells the operator 'Max {n}.' while vivek_run caps at {_expected()}")


def test_vivek_run_refuses_on_the_derived_constant_not_a_literal():
    src = VIVEK_RUN.read_text(encoding="utf-8")
    assert re.search(r"if len\(entries\) > CLOSE_BATCH_MAX:", src), (
        "the --close-batch gate no longer compares against CLOSE_BATCH_MAX")
    assert not re.search(r"len\(entries\) > \d+", src), (
        "a literal --close-batch cap is back; it will not follow the next book-cap change")


def _close_batch_max_under(**cfg):
    """Execute vivek_run's OWN CLOSE_BATCH_MAX assignment against a stand-in config.

    Behavioural rather than a regex: whatever expression ships is what runs.
    Isolated on purpose -- reloading the real module mid-suite would rebind
    functions other tests already hold.
    """
    tree = ast.parse(VIVEK_RUN.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body
             if isinstance(n, (ast.Assign, ast.AnnAssign))
             and any(isinstance(t, ast.Name) and t.id == "CLOSE_BATCH_MAX"
                     for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    assert len(nodes) == 1, "vivek_run.py should assign CLOSE_BATCH_MAX exactly once at module level"
    mod = ast.Module(body=nodes, type_ignores=[])
    ns = {"config": types.SimpleNamespace(**cfg)}
    exec(compile(mod, str(VIVEK_RUN), "exec"), ns)
    return ns["CLOSE_BATCH_MAX"]


def test_the_python_cap_is_derived_from_config_and_follows_it():
    markets = {"asx": {}, "nasdaq": {}, "crypto": {}}
    assert _close_batch_max_under(VIVEK_BOT_MAX_OPEN_TOTAL=77, VIVEK_BOT_MAX_POSITIONS=5,
                                  MARKETS=markets) == 77, "the cap does not follow the book cap"
    # Global cap OFF: the largest possible book is the per-market cap everywhere.
    assert _close_batch_max_under(VIVEK_BOT_MAX_OPEN_TOTAL=0, VIVEK_BOT_MAX_POSITIONS=5,
                                  MARKETS=markets) == 15


# -- the offline fallbacks ----------------------------------------------------------

def test_status_fallback_cap_is_the_book_cap():
    src = STATUS_JS.read_text(encoding="utf-8")
    n = _one(r"const FALLBACK_CAP = (\d+);", src, "status.js")
    assert n == int(config.VIVEK_BOT_MAX_OPEN_TOTAL), (
        f"status.js would read 'Open N / {n}' offline on a {config.VIVEK_BOT_MAX_OPEN_TOTAL}-slot book")


def test_journal_fallback_notional_is_the_config_notional():
    src = JOURNAL_JS.read_text(encoding="utf-8")
    n = _one(r"let POSITION_NOTIONAL = (\d+);", src, "journal.js")
    assert n == int(config.VIVEK_BOT_POSITION_NOTIONAL)


def test_system_rulebook_static_cells_match_config():
    src = SYSTEM_HTML.read_text(encoding="utf-8")
    cell = lambda key: re.findall(r'data-r="%s">([^<]*)<' % key, src)  # noqa: E731
    assert cell("max_open_total") == [str(config.VIVEK_BOT_MAX_OPEN_TOTAL)]
    assert cell("max_positions") == [str(config.VIVEK_BOT_MAX_POSITIONS)]
    assert cell("max_per_sector") == [str(config.VIVEK_BOT_MAX_PER_SECTOR)]
    assert cell("position_notional") == ["${:,}".format(int(config.VIVEK_BOT_POSITION_NOTIONAL))]
    stop = float(config.VIVEK_BOT_MAX_STOP_PCT)
    assert cell("max_stop_pct") == ["{:g}% of entry".format(stop)]

"""deploy/api -- the numbers the VPS adapter enforces are config.py's, not a re-typing.

The adapter is JavaScript and cannot import scanner/config.py, so
deploy/api/dispatch.mjs carries six JSON literals (the mark-sanity band, the
per-workflow dispatch cooldown, the per-workflow daily caps, the spool pending
cap, the body cap and the token-length floor) and this file parses them OUT OF THE SHIPPED FILE and compares them
to config -- the conviction.py pattern (tests/test_conviction.py), so a retune
in config that is not mirrored fails the push instead of drifting silently.

Also pinned here: the spool-name regex agrees with the drainer's, the spool
body the adapter writes is what the drainer accepts, the ESM enablers
(functions/package.json + its .gitignore negation) stay exactly as shipped,
_dispatch.js keeps the sandbox-safe surface the vm loaders rely on, and the
adapter never carries the chart-depth markers the engine fence greps for.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "deploy" / "api"
DISPATCH = API / "dispatch.mjs"
SERVER = API / "server.mjs"
SHIMS = API / "shims.mjs"
FUNCTIONS = ROOT / "functions" / "api"


def _literal(name: str):
    src = DISPATCH.read_text(encoding="utf-8")
    m = re.search(rf"^export const {re.escape(name)} = (.+?);\s*$", src, re.M)
    assert m, f"dispatch.mjs no longer carries `export const {name} = <json>;` on one line"
    return json.loads(m.group(1))


# -- the six parity literals --------------------------------------------------

def test_the_mark_sanity_band_is_configs():
    assert _literal("MARK_SANITY_PCT") == config.VIVEK_MARK_SANITY_PCT


def test_the_dispatch_cooldown_is_configs_per_workflow_and_matches_each_functions_ttl():
    """M2: the adapter's cooldown mirrors the Functions EXACTLY, per workflow:
    scan.js 300 s, close.js 60 s, morning_plays.js 300 s (one 300 s value made
    the VPS refuse a deliberate second close-all the Function would allow)."""
    cd = _literal("DISPATCH_COOLDOWN_S")
    assert cd == config.VPS_DISPATCH_COOLDOWN_S
    assert cd == {"scan.yml": 300, "close_position.yml": 60, "morning_plays.yml": 300}
    assert set(cd) == set(_literal("DISPATCH_DAILY_CAPS")), "every dispatchable workflow has a cooldown"
    for fn, wf in (("scan.js", "scan.yml"), ("close.js", "close_position.yml"), ("morning_plays.js", "morning_plays.yml")):
        m = re.search(r'put\(cdKey, "1", \{ expirationTtl: (\d+) \}\)', (FUNCTIONS / fn).read_text(encoding="utf-8"))
        assert m and int(m.group(1)) == cd[wf], (fn, m and m.group(1), cd[wf])
    src = DISPATCH.read_text(encoding="utf-8")
    assert "expirationTtl: cooldown" in src and "DISPATCH_COOLDOWN_S[v.workflow]" in src


def test_the_token_floor_is_configs():
    assert _literal("DISPATCH_TOKEN_MIN_CHARS") == config.VPS_DISPATCH_TOKEN_MIN_CHARS == 32


def test_the_daily_caps_are_configs():
    assert _literal("DISPATCH_DAILY_CAPS") == config.VPS_DISPATCH_DAILY_CAPS


def test_the_spool_pending_cap_is_configs():
    assert _literal("SPOOL_MAX_PENDING") == config.VPS_SPOOL_MAX_PENDING


def test_the_body_cap_is_the_spool_byte_cap():
    assert _literal("SPOOL_MAX_BYTES") == config.VPS_SPOOL_MAX_BYTES


def test_every_dispatchable_workflow_has_a_daily_cap_and_is_a_real_workflow():
    caps = _literal("DISPATCH_DAILY_CAPS")
    for wf in caps:
        assert (ROOT / ".github" / "workflows" / wf).exists(), wf
    # the adapter's allowlist is exactly the capped set (validateDispatch branches)
    src = DISPATCH.read_text(encoding="utf-8")
    branches = set(re.findall(r'if \(workflow === "([a-z_]+\.yml)"\)', src))
    assert branches == set(caps), (branches, set(caps))


# -- the spool contract with the drainer (C1) ----------------------------------

def test_the_spool_name_regex_matches_the_drainer():
    from scanner.vps import spool  # C1's module; the contract is DESIGN section 3.5
    src = DISPATCH.read_text(encoding="utf-8")
    m = re.search(r"^export const SPOOL_NAME_RE = /(.+?)/;", src, re.M)
    assert m
    assert m.group(1) == spool.NAME_RE.pattern


@pytest.mark.parametrize("workflow,inputs", [
    ("scan.yml", {"market": "asx", "reason": "manual"}),
    ("scan.yml", {"market": "all", "reason": "heartbeat"}),
    ("morning_plays.yml", {"slot": "us"}),
    ("close_position.yml", {"symbol": "NIC", "direction": "long", "market": "asx", "price": "0.8",
                            "exit_date": "", "journal_type": "bot"}),
    ("close_position.yml", {"symbol": "NIC+1", "direction": "long", "market": "asx", "price": "0.8",
                            "exit_date": "", "journal_type": "bot",
                            "batch": json.dumps([{"symbol": "NIC", "market": "asx", "direction": "long", "price": "0.8"},
                                                 {"symbol": "BTC", "market": "crypto", "direction": "long", "price": "61000"}])}),
])
def test_the_canonical_spool_inputs_the_adapter_writes_are_accepted_by_the_drainer(workflow, inputs):
    from scanner.vps import spool
    job, args = spool.validate_dispatch(workflow, inputs)
    assert job == workflow
    if workflow == "close_position.yml":
        assert args["symbol"] == inputs["symbol"] and args["journal_type"] == "bot"
        if inputs.get("batch"):
            # the drainer prints Python str(float) ("61000.0") where the adapter wrote String(61000);
            # vivek_run parses the float either way, so compare the numbers, not the spelling
            got, sent = json.loads(args["batch"]), json.loads(inputs["batch"])
            assert [(e["symbol"], e["market"], e["direction"], float(e["price"])) for e in got] == \
                   [(e["symbol"], e["market"], e["direction"], float(e["price"])) for e in sent]


def test_the_adapter_never_settles_operator_only_keys():
    """extra/args/force/dry_run/attempt are operator-only (DESIGN 3.1): the
    adapter's per-workflow key allowlists must not name them."""
    src = DISPATCH.read_text(encoding="utf-8")
    allow = re.findall(r'onlyKeys\(inputs, \[([^\]]*)\]', src)
    assert len(allow) == 3
    named = {k.strip().strip('"') for group in allow for k in group.split(",")}
    assert not named & {"extra", "args", "force", "dry_run", "attempt", "redeliver"}, named


# -- ESM enablers ---------------------------------------------------------------

def test_functions_package_json_is_exactly_type_module_and_there_is_no_root_one():
    assert json.loads((ROOT / "functions" / "package.json").read_text(encoding="utf-8")) == {"type": "module"}
    assert not (ROOT / "package.json").exists(), "a root package.json would flip test/*.test.js to ESM"


def test_gitignore_unignores_it_right_after_the_package_json_rule():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    i = lines.index("package.json")
    assert lines[i + 1] == "!functions/package.json"


# -- _dispatch.js stays loadable by the vm suites --------------------------------

def test_dispatch_js_keeps_the_sandbox_safe_surface():
    src = (FUNCTIONS / "_dispatch.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert not re.search(r"^\s*import\b", code, re.M), "nobody strips an import from this file"
    exports = re.findall(r"^\s*export\s+(\S+(?:\s+function)?)", code, re.M)
    assert exports and set(exports) <= {"const", "async function"}, exports
    assert not re.search(r"\b(console|process|require|TextEncoder|crypto)\b", code), \
        "heartbeat.test.js's sandbox has none of these"


def test_the_four_endpoints_key_configured_on_either_transport():
    for name in ("scan.js", "close.js", "heartbeat.js", "morning_plays.js"):
        src = (FUNCTIONS / name).read_text(encoding="utf-8")
        assert "!dispatchUrl && !token" in src, name
        assert re.search(r"dispatchUrl,\s*dispatchToken", src), name


# -- hygiene fences the adapter must clear -------------------------------------

def test_the_adapter_carries_no_chart_depth_marker_and_no_removed_secret_name():
    # built by concatenation: tests/test_scanner_untouched_by_chart_depth.py greps every *.py for the literals
    markers = ("fetchYahoo" + "Deep", "deep" + "Years", "DAILY_" + "RANGE", "CHART_MAX_" + "YEARS", "yahoo-" + "deep")
    for p in (SERVER, SHIMS, DISPATCH, ROOT / "test" / "vps_api.test.js"):
        src = p.read_text(encoding="utf-8")
        for m in markers:
            assert m not in src, (p.name, m)
        assert "DISCORD_" + "WEBHOOK_URL" not in src, p.name


def test_the_critical_set_is_the_designs_and_names_real_watchdog_keys():
    crit = _literal("CRITICAL_JOBS")
    assert set(crit) == {"kill_switch.yml", "backup_book.yml", "scan.yml", "crypto_bot.yml"}
    assert set(crit) <= set(config.WATCHDOG_RUNS)


def test_the_suite_is_registered_in_the_workflow():
    yml = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "node test/vps_api.test.js" in yml

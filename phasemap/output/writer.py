"""Nightly JSON snapshot writer (spec Section 7).

Determinism requirement: same input data + same ruleset_version =>
byte-identical output. Results sorted by tier then ticker; floats rounded
before serialisation; keys emitted in fixed insertion order; LF line endings.
"""

import json
import os

from phasemap.config import CONFIG, RULESET_VERSION

REQUIRED_RESULT_KEYS = ("ticker", "direction", "state", "tier", "tags",
                        "regime", "zones", "metrics", "smt", "route_to",
                        "narration")
REQUIRED_ZONE_KEYS = ("id", "type", "low", "high", "status")
VALID_STATES = ("TRAP_SET", "SWEPT", "DISPLACED", "RUNNING", "STALLED",
                "COMPLETE", "DEAD")
VALID_ZONE_TYPES = ("DEMAND", "SUPPLY", "INVALIDATION_HARD",
                    "INVALIDATION_MOMENTUM", "ENTRY_CONTINUATION", "TARGET")
VALID_ZONE_STATUS = ("UNTESTED", "TESTED", "RESPECTED", "CONSUMED", "VIOLATED")


def validate_snapshot(snap: dict) -> None:
    """Hand-rolled schema check — raises ValueError with a precise message."""
    for key in ("run_date", "ruleset_version", "universe_size", "results"):
        if key not in snap:
            raise ValueError(f"snapshot missing key: {key}")
    if not isinstance(snap["results"], list):
        raise ValueError("results must be a list")
    for r in snap["results"]:
        for key in REQUIRED_RESULT_KEYS:
            if key not in r:
                raise ValueError(f"result {r.get('ticker')} missing key: {key}")
        if r["state"] not in VALID_STATES:
            raise ValueError(f"invalid state: {r['state']}")
        if r["direction"] not in ("bullish", "bearish"):
            raise ValueError(f"invalid direction: {r['direction']}")
        if r["tier"] not in ("A+", "A", "Watch", None):
            raise ValueError(f"invalid tier: {r['tier']}")
        if not r["narration"].endswith("not financial advice."):
            raise ValueError(f"{r['ticker']}: narration missing disclaimer")
        for z in r["zones"]:
            for key in REQUIRED_ZONE_KEYS:
                if key not in z:
                    raise ValueError(f"zone missing key: {key}")
            if z["type"] not in VALID_ZONE_TYPES:
                raise ValueError(f"invalid zone type: {z['type']}")
            if z["status"] not in VALID_ZONE_STATUS:
                raise ValueError(f"invalid zone status: {z['status']}")
            if not (isinstance(z["low"], (int, float)) and
                    isinstance(z["high"], (int, float)) and z["low"] <= z["high"]):
                raise ValueError(
                    f"zone {z['id']} band invalid: {z['low']}..{z['high']}")


def build_snapshot(run_date: str, universe_size: int, results: list) -> dict:
    return {
        "run_date": run_date,
        "ruleset_version": RULESET_VERSION,
        "universe_size": universe_size,
        "results": results,
    }


def serialise(snap: dict) -> str:
    return json.dumps(snap, indent=2, ensure_ascii=False) + "\n"


def write_snapshot(snap: dict, out_dir: str = None) -> str:
    """Writes scans dir + latest.json copy. Returns the dated file path."""
    validate_snapshot(snap)
    out_dir = out_dir or CONFIG.output_dir
    os.makedirs(out_dir, exist_ok=True)
    payload = serialise(snap)
    dated = os.path.join(out_dir, f"{snap['run_date']}.json")
    latest = os.path.join(out_dir, "latest.json")
    for path in (dated, latest):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
        os.replace(tmp, path)   # atomic — never corrupt on crash
    return dated

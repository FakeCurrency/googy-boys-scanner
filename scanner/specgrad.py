"""Specs -> VIVEK graduation watch (owner-ruled, 2026-07-31).

Report-only evidence surface, third of its family (arriving list, funnel
history): a per-market tally of names the Specs lens surfaced FIRST — the
sub-$0.50 volume-spike discoveries — that LATER appeared in the published
VIVEK scan, i.e. crossed the 50-cent line and/or the liquidity floor into
VIVEK eligibility and set up there. It answers one question with a number:
does the discovery lens actually feed the core lens, and how often?

The rules, the same fencing standard as its siblings:

  * READS published artifacts only — the spec payload it is handed (already
    written to disk by ``scan_market``) and the committed
    ``public/data/<m>_vivek.json``. No data downloads, no engine calls.
  * FEEDS nothing — imported by ``spec_run.py`` alone, called AFTER the specs
    publish under a narrow try, and nothing in scanner/ or broker/ reads
    ``spec_graduation.json`` back. The display is ``public/js/specs.js``,
    full stop. ``tests/test_specgrad.py`` pins both directions.

Mechanics. Per market the registry keeps ``seen`` — names Specs surfaced
that were NOT in that day's published VIVEK results (a name VIVEK already
publishes has nothing to graduate into, so it is never watched) — and
``graduates``, the crossing events. A watched name graduates when it appears
in a VIVEK payload dated STRICTLY after its ``first_seen``: strictness is
what makes "previously surfaced" true, and it is also what makes a same-night
re-run idempotent. Graduation removes the name from the watch, so the tally
counts crossing EVENTS, not appearances; a graduate that falls back under
50 cents re-enters the watch the next time Specs surfaces it — and can
honestly graduate again. ``graduated_total`` is the lifetime tally and
survives the list cap. Every date comes from the payloads' own
``generated_at`` stamps, never the wall clock, so a replay writes exactly
what the live run wrote.

Single-writer by construction: only phasemap.yml's nightly spec_run touches
this file (mutex ``group: phasemap``), which is what makes the workflow's
reset-and-reapply push retry safe for a read-modify-write artefact — there is
no sibling copy to clobber.
"""
from __future__ import annotations

import datetime
import json
import os

from . import config, output


def _date(stamp) -> str:
    """YYYY-MM-DD off a payload's own ``generated_at``; '' when unusable."""
    s = str(stamp or "")[:10]
    try:
        datetime.date.fromisoformat(s)
        return s
    except ValueError:
        return ""


def _days_between(a: str, b: str):
    try:
        return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days
    except ValueError:
        return None


def _load(path: str) -> dict:
    """The registry, or a fresh one. A corrupt or absent REPORT file starts
    over; it never raises into the scan."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("markets"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"schema_version": 1, "updated_at": "", "markets": {}}


def _slot(reg: dict, market: str) -> dict:
    """The market's block, shape-repaired — a hand-edited or truncated file
    degrades to empty structures, never to a TypeError mid-scan."""
    mk = reg["markets"].get(market)
    mk = mk if isinstance(mk, dict) else {}
    seen = mk.get("seen")
    grads = mk.get("graduates")
    total = mk.get("graduated_total")
    mk = {"seen": seen if isinstance(seen, dict) else {},
          "graduates": grads if isinstance(grads, list) else [],
          "graduated_total": total if isinstance(total, int) and total >= 0 else 0}
    reg["markets"][market] = mk
    return mk


def _vivek_rows(out_dir: str, market: str) -> tuple[dict, str]:
    """({SYMBOL: summary row}, payload date) from the committed
    ``<m>_vivek.json``. Missing or unreadable -> ``({}, "")`` — no artifact
    means no graduations tonight, never a crash. The v5 SUMMARY carries
    everything needed (symbol / price / grade); the detail sidecar is not
    consulted."""
    try:
        with open(os.path.join(out_dir, f"{market}_vivek.json"), encoding="utf-8") as f:
            vk = json.load(f)
        rows = {}
        for r in vk.get("results") or []:
            if isinstance(r, dict) and r.get("symbol"):
                rows[str(r["symbol"])] = r
        return rows, _date(vk.get("generated_at"))
    except (OSError, ValueError, AttributeError):
        return {}, ""


def update(market: str, out_dir: str, spec_payload: dict) -> None:
    """Fold tonight's published Specs results into the graduation registry.

    Never mutates ``spec_payload`` (it is read-only evidence), and every
    failure mode a report file can have — corrupt registry, absent vivek
    artifact, malformed rows — degrades to doing less, never to raising.
    """
    path = os.path.join(out_dir, config.SPEC_GRAD_FILE)
    reg = _load(path)
    mk = _slot(reg, market)
    seen, grads = mk["seen"], mk["graduates"]

    today = _date(spec_payload.get("generated_at"))
    vrows, vdate = _vivek_rows(out_dir, market)

    # 1. Watch tonight's Specs names. A name ALREADY in the published VIVEK
    #    results has nothing to graduate into and is not watched; a name
    #    already watched keeps its first_seen — that date IS the record.
    for r in spec_payload.get("results") or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "")
        if not sym or sym in vrows:
            continue
        entry = seen.get(sym)
        if not isinstance(entry, dict) or not _date(entry.get("first_seen")):
            entry = {"first_seen": today, "price": r.get("price")}
        entry["name"] = r.get("name") or entry.get("name") or sym
        entry["last_seen"] = today
        seen[sym] = entry

    # 2. Graduations: a watched name inside a VIVEK payload dated STRICTLY
    #    after its first_seen has crossed over. Recording it removes it from
    #    the watch — the tally counts crossing events, and a fallen angel
    #    re-enters via step 1 the next time Specs surfaces it.
    if vrows and vdate:
        for sym in [s for s in list(seen) if s in vrows]:
            entry = seen[sym] if isinstance(seen[sym], dict) else {}
            first = _date(entry.get("first_seen"))
            if not first or first >= vdate:
                continue
            vr = vrows[sym]
            if not any(isinstance(g, dict) and g.get("symbol") == sym
                       and g.get("graduated") == vdate for g in grads):
                grads.append({
                    "symbol": sym,
                    "name": entry.get("name") or sym,
                    "first_seen": first,
                    "spec_price": entry.get("price"),
                    "graduated": vdate,
                    "vivek_price": vr.get("price"),
                    "grade": vr.get("grade"),
                    "days": _days_between(first, vdate),
                })
                mk["graduated_total"] += 1
            del seen[sym]

    # 3. Caps — a report file must stay small. The watch trims its OLDEST
    #    first_seen entries; the graduates list keeps its NEWEST tail (the
    #    lifetime tally lives on in graduated_total).
    cap = int(getattr(config, "SPEC_GRAD_SEEN_MAX", 0) or 0)
    if cap > 0 and len(seen) > cap:
        oldest = sorted(seen.items(),
                        key=lambda kv: (str((kv[1] or {}).get("first_seen") or ""), kv[0]))
        for sym, _ in oldest[:len(seen) - cap]:
            del seen[sym]
    gcap = int(getattr(config, "SPEC_GRAD_MAX", 0) or 0)
    if gcap > 0 and len(grads) > gcap:
        mk["graduates"] = grads[len(grads) - gcap:]

    reg["updated_at"] = str(spec_payload.get("generated_at") or reg.get("updated_at") or "")
    # Same formatting family as the spec files this rides beside.
    output.write_json(path, reg, indent=1, ensure_ascii=False, newline=True)

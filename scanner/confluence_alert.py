"""Multi-lens confluence alert engine.

When the same name has ACTIVE, direction-aligned setups on more than one
lens (VIVEK 200-SMA reaction · PhaseMap trap/displacement · Specs volume
breakout), record it: the ALERTS page log is the durable record, and the
delivery state tracks what a push channel owes the owner. Mirrors the
frontend's PM.loadConfluence exactly.

    python -m scanner.confluence_alert            # all markets
    python -m scanner.confluence_alert --dry-run  # preview, write nothing new

DELIVERY REMOVED 2026-08-27 (owner ruling: "get rid of the discord aspect,
I will work on implementing something new in the future"). The Discord
webhook post is gone; everything below it survives on purpose:
  * State-deduped (journal/confluence_state.json): an alignment is owed one
    ping, when it first appears — and again only if it UPGRADES (2-lens ->
    3-lens) or fully lapses and later re-forms. Undelivered alignments are
    recorded with NEGATIVE counts (see build_state), exactly as the old
    "webhook not configured" branch did — so the first run after the next
    channel lands pings everything still current, with nothing burned.
  * The lens threshold (config.CONF_ALERT_MIN_LENSES) is the only gate on
    what counts as push-worthy. A WATCHLIST-AWARE bypass let starred names
    and open manual positions ping below it; both the stars and the synced
    journal they lived in were removed 2026-09-21, and it went with them.
  * The ALERTS page log (append_history) is written for EVERY new alignment
    regardless of the push threshold — and the daily edge pipeline ingests
    it, so it must keep being written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
from zoneinfo import ZoneInfo

from . import config, output

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
STATE_FILE = ROOT / "journal" / "confluence_state.json"
HISTORY_FILE = DATA / "phasemap" / "alert_history.json"
HISTORY_CAP = 800

MARKETS = ("asx", "nasdaq", "crypto")
PM_ACTIVE = {"SWEPT", "DISPLACED", "RUNNING"}
SITE = getattr(config, "SITE_URL", "https://googy-boys-scanner.pages.dev")


def _read(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def compute_alignments(market: str) -> list[dict]:
    """Direction-aware 2+ lens alignments for one market (frontend mirror)."""
    vivek = _read(DATA / f"{market}_vivek.json")
    pm = _read(DATA / "phasemap" / market / "latest.json")
    spec = _read(DATA / f"{market}_spec.json")

    entries: dict[str, dict] = {}

    def ent(t):
        return entries.setdefault(t, {"long": {}, "short": {}})

    for r in (vivek or {}).get("results", []):
        side = "short" if str(r.get("dir", "LONG")).upper() == "SHORT" else "long"
        ent(r["symbol"])[side]["VIVEK"] = f"VIVEK {r.get('grade', '')}".strip()
    for r in (pm or {}).get("results", []):
        if r.get("state") not in PM_ACTIVE:
            continue
        side = "short" if r.get("direction") == "bearish" else "long"
        label = f"PHASEMAP {r['state']}" + (f" {r['tier']}" if r.get("tier") else "")
        ent(r["ticker"])[side]["PHASEMAP"] = label
    for r in (spec or {}).get("results", []):
        ent(r["symbol"])["long"]["SPECS"] = f"SPECS {r.get('grade', '')}".strip()

    out = []
    for ticker, e in entries.items():
        side = "long" if len(e["long"]) >= len(e["short"]) else "short"
        lenses = e[side]
        if len(lenses) < 2:
            continue
        out.append({
            "market": market, "ticker": ticker, "side": side,
            "count": len(lenses),
            "lenses": sorted(lenses),                 # e.g. ["PHASEMAP", "VIVEK"]
            "labels": [lenses[k] for k in sorted(lenses)],
        })
    out.sort(key=lambda x: (-x["count"], x["ticker"]))
    return out


def _state_key(a: dict) -> str:
    return f"{a['market']}:{a['ticker']}:{a['side']}"


def diff_new(alignments: list[dict], state: dict) -> list[dict]:
    """New or upgraded alignments vs the saved state (for the ALERTS-page log).

    State values are SIGNED (see build_state): the magnitude is the last count
    this layer has SEEN, so history compares against abs(prev) — an alignment
    persisting at the same count is not news, whether or not it was posted.
    """
    return [a for a in alignments if a["count"] > abs(state.get(_state_key(a), 0))]


def build_state(alignments: list[dict], state: dict, posted_keys: set[str]) -> dict:
    """Next state. Lapsed keys are pruned so a re-formed alignment pings again.

    SIGNED COUNTS (2026-07-29): +count means "this count was actually POSTED",
    -count means "seen for the history log, but never delivered". The old state
    recorded a bare +count for EVERYTHING current — including 2-lens alignments
    that were below the push threshold (CONF_ALERT_MIN_LENSES) and not
    watchlisted.
    That burned the count: star the name a day later and `count > prev` is
    `2 > 2` — the ping the watchlist bypass exists for can never fire. The
    webhook secret already had exactly this protection ("don't mark as seen").
    (The watchlist bypass itself was removed with the manual journal on
    2026-09-21; the signed state stays, because a logged-but-undelivered
    alignment must still ping when it upgrades.)

    Pre-fix state files hold bare positive counts, which read as "posted" —
    correct for everything at/above the threshold, conservative (no
    retroactive ping) for the sub-threshold entries burned before the fix.
    """
    out = {}
    for a in alignments:
        key = _state_key(a)
        prev = state.get(key, 0)
        if key in posted_keys:
            out[key] = a["count"]                    # delivered at this count
        elif abs(prev) == a["count"]:
            out[key] = prev                          # unchanged — keep its sign
        else:
            out[key] = -a["count"]                   # seen, not delivered
    return out


def _market_tz(market: str):
    m = config.MARKETS.get(market)
    return ZoneInfo(m.timezone) if m else dt.timezone.utc


def _entry_session_day(e: dict) -> str:
    """A stored history entry's date in ITS market's calendar, for dedup.

    Dedup runs on the MARKET's calendar date, not UTC's: one AEDT ASX session
    runs 23:00–05:00 UTC — two UTC dates — so a UTC day key can log the same
    alignment twice per session (one session-day per market-local calendar day).
    The stored `date` field stays a UTC timestamp; BOTH sides of the comparison
    convert to the market's day, or the boundary hour would just move instead
    of closing."""
    try:
        stamp = dt.datetime.fromisoformat(str(e.get("date", "")))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return stamp.astimezone(_market_tz(str(e.get("market", "")))).strftime("%Y-%m-%d")
    except ValueError:
        return str(e.get("date", ""))[:10]         # unparseable → old behaviour


def append_history(fresh: list[dict]) -> None:
    """Site-side alert log (public/data/phasemap/alert_history.json) — push
    pings scroll away; the ALERTS page doesn't. Written for EVERY new
    alignment regardless of the push threshold, deduped per market-day.
    The edge pipeline ingests this file daily — it must keep being written."""
    if not fresh:
        return
    try:
        hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        hist = {}
    entries = hist.get("entries", [])
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    seen = {(_entry_session_day(e), e.get("market"), e.get("ticker"),
             e.get("side"), e.get("count")) for e in entries}
    for a in fresh:
        key = (dt.datetime.now(_market_tz(a["market"])).strftime("%Y-%m-%d"),
               a["market"], a["ticker"], a["side"], a["count"])
        if key in seen:
            continue
        entries.insert(0, {"date": now, "market": a["market"], "ticker": a["ticker"],
                           "side": a["side"], "count": a["count"],
                           "lenses": a["lenses"]})
    # TOP100 #64 — atomic + NaN-safe
    output.write_json(HISTORY_FILE, {"entries": entries[:HISTORY_CAP]},
                      indent=1, newline=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="confluence alert")
    ap.add_argument("--market", default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    markets = MARKETS if args.market == "all" else tuple(args.market.split(","))

    alignments = []
    for m in markets:
        alignments.extend(compute_alignments(m))
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    fresh = diff_new(alignments, state)
    # Only alignments at/above the lens threshold are push-worthy (default:
    # triples only). The site still shows every 2-lens alignment visually —
    # state tracks them all (signed, see build_state), so a 2->3 upgrade
    # always earns a ping.
    min_lenses = getattr(config, "CONF_ALERT_MIN_LENSES", 2)
    # THE WATCHLIST BYPASS IS GONE (2026-09-21). Starred names and open manual
    # positions used to ping at 2 lenses even while the channel was
    # triples-only, read from the synced journal via GBS_SYNC_CODE. Both the
    # stars and that journal were removed with the manual side, so the
    # threshold is now the only gate. The SIGNED state below is untouched and
    # still matters: a 2-lens alignment logged but never delivered keeps a
    # negative count, so a later upgrade to 3 still pings.
    to_post = [a for a in alignments
               if a["count"] >= min_lenses
               and a["count"] > state.get(_state_key(a), 0)]
    print(f"confluence: {len(alignments)} active, {len(fresh)} new/upgraded, "
          f"{len(to_post)} to post (>= {min_lenses} lenses)")
    if not args.dry_run:
        append_history(fresh)   # the ALERTS page log — independent of any push
    # DELIVERY REMOVED 2026-08-27 (owner ruling). No payload is built and no
    # webhook is read; push-worthy alignments are printed for the run log and
    # the state is saved with NO posted keys, so build_state records each one
    # as seen-but-undelivered (negative count). That is deliberately the same
    # path the old "webhook not configured" branch took: the first run after
    # the replacement channel lands finds `count > signed prev` true for
    # everything still current and pings the lot, with nothing burned.
    for a in to_post:
        print(f"confluence: push-worthy (undelivered) {a['market']}:"
              f"{a['ticker']} {a['side'].upper()} {a['count']}-lens - "
              f"{' + '.join(a['labels'])}")
    if args.dry_run and to_post:
        return 0
    _save_state_if_changed(state, build_state(alignments, state, set()))
    return 0


def _save_state_if_changed(old: dict, new: dict) -> None:
    if old != new:
        output.write_json(STATE_FILE, new, sort_keys=True, newline=True)


if __name__ == "__main__":
    raise SystemExit(main())

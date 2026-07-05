"""Multi-lens confluence Discord alert.

When the same name has ACTIVE, direction-aligned setups on more than one
lens (VIVEK 200-SMA reaction · PhaseMap trap/displacement · Specs volume
breakout), post it to Discord — the site shows it visually, this makes sure
the owner gets PINGED. Mirrors the frontend's PM.loadConfluence exactly.

    python -m scanner.confluence_alert            # all markets, post new only
    python -m scanner.confluence_alert --dry-run  # preview, post nothing

Behaviour:
  * State-deduped (journal/confluence_state.json): an alignment pings once,
    when it first appears — and again only if it UPGRADES (2-lens -> 3-lens)
    or if it fully lapses and later re-forms.
  * 3-lens alignments carry a mention (config.DISCORD_CONF_MENTION, default
    @here) — the rare full-house event. 2-lens posts are silent embeds.
  * Without DISCORD_WEBHOOK_URL it previews and exits 0 — never fails CI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib

from . import config
from .discord import post_webhook

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


def diff_new(alignments: list[dict], state: dict) -> tuple[list[dict], dict]:
    """New or upgraded alignments vs the saved state. Lapsed keys are pruned so
    a re-formed alignment pings again."""
    new_state, fresh = {}, []
    for a in alignments:
        key = f"{a['market']}:{a['ticker']}:{a['side']}"
        prev = state.get(key, 0)
        new_state[key] = a["count"]
        if a["count"] > prev:
            fresh.append(a)
    return fresh, new_state


def append_history(fresh: list[dict]) -> None:
    """Site-side alert log (public/data/phasemap/alert_history.json) — Discord
    pings scroll away; the ALERTS page doesn't. Written for EVERY new
    alignment regardless of the Discord lens threshold, deduped per day."""
    if not fresh:
        return
    try:
        hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        hist = {}
    entries = hist.get("entries", [])
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    day = now[:10]
    seen = {(str(e.get("date", ""))[:10], e.get("market"), e.get("ticker"),
             e.get("side"), e.get("count")) for e in entries}
    for a in fresh:
        key = (day, a["market"], a["ticker"], a["side"], a["count"])
        if key in seen:
            continue
        entries.insert(0, {"date": now, "market": a["market"], "ticker": a["ticker"],
                           "side": a["side"], "count": a["count"],
                           "lenses": a["lenses"]})
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps({"entries": entries[:HISTORY_CAP]}, indent=1) + "\n",
        encoding="utf-8")


def build_payloads(fresh: list[dict]) -> list[dict]:
    triples = [a for a in fresh if a["count"] >= 3]
    lines = []
    for a in fresh[:20]:
        arrow = "🔻 SHORT" if a["side"] == "short" else "🔼 LONG"
        icon = "🎯" if a["count"] >= 3 else "⨂"
        d = "&dir=bearish" if a["side"] == "short" else "&dir=bullish"
        url = f"{SITE}/chart.html?m={a['market']}&s={a['ticker']}&pm=1{d}"
        lines.append(
            f"{icon} **[{a['ticker']}]({url})** {arrow} · {a['market'].upper()} · "
            f"{a['count']}-LENS — {' + '.join(a['labels'])}")
    if len(fresh) > 20:
        lines.append(f"… +{len(fresh) - 20} more on the site")
    embed = {
        "title": "⨂ Multi-lens alignment" + (" — 🎯 TRIPLE" if triples else ""),
        "description": "\n".join(lines)[:4000] +
            "\n\n*Independent lenses agreeing on one name at one time. "
            "Analysis only — not financial advice.*",
        "color": 0xFFB224 if triples else 0x37D0C4,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    payload = {
        "username": getattr(config, "DISCORD_USERNAME", "Vivek 5.0"),
        "embeds": [embed],
    }
    mention = getattr(config, "DISCORD_CONF_MENTION", "@here")
    if triples and mention:
        payload["content"] = (f"{mention} 🎯 **TRIPLE-LENS ALIGNMENT** — "
                              + ", ".join(a["ticker"] for a in triples))
    return [payload]


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
    fresh, new_state = diff_new(alignments, state)
    # Discord only carries alignments at/above the lens threshold (default:
    # triples only). The site still shows every 2-lens alignment visually —
    # state tracks them all, so a 2->3 upgrade always pings.
    min_lenses = getattr(config, "DISCORD_CONF_MIN_LENSES", 2)
    to_post = [a for a in fresh if a["count"] >= min_lenses]
    print(f"confluence: {len(alignments)} active, {len(fresh)} new/upgraded, "
          f"{len(to_post)} at >= {min_lenses} lenses")
    if not args.dry_run:
        append_history(fresh)   # the ALERTS page log — independent of Discord
    if not to_post:
        _save_state_if_changed(state, new_state)
        return 0

    payloads = build_payloads(to_post)
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if args.dry_run:
        print(json.dumps(payloads, indent=2)[:2500])
        return 0
    if not url:
        # No webhook configured: preview only and DON'T mark anything as seen,
        # so the first run after the secret is added pings everything current.
        print(json.dumps(payloads, indent=2)[:1200])
        print("confluence: DISCORD_WEBHOOK_URL not set — preview only, state untouched")
        return 0
    for p in payloads:
        if not post_webhook(url, p):
            print("confluence: post failed — state NOT saved (will retry next run)")
            return 0
    print(f"confluence: posted {len(fresh)} alignment(s) to Discord")
    _save_state_if_changed(state, new_state)
    return 0


def _save_state_if_changed(old: dict, new: dict) -> None:
    if old != new:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

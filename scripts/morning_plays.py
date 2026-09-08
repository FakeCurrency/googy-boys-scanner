"""Morning Discord digest of HIGH-CONVICTION VIVEK 5.0 plays (2026-09-08).

Every Melbourne morning, collect the high-conviction setups across ASX and
NASDAQ and post them to a Discord channel. READ-ONLY: it reads the COMMITTED
scan JSON (public/data/<market>_vivek.json) and posts -- it never scans, never
touches Yahoo, never commits, and is not in the scan concurrency group. The
pattern is reco_note.py / evidence_brief.py, not the alert router.

HIGH CONVICTION is defined EXACTLY as the dashboard's app.js isHighConviction:
a WEEKLY (1W) reclaim that is armed and is either A/A+ grade OR has strong
structure (>= 2 structural take-profits). Reproduced here from the same lite
plan fields the summary keeps (config.VIVEK_SUMMARY_PLAN_FIELDS). If that rule
ever changes in app.js, change it here too -- test_morning_plays.py pins the
shared shape.

THE CHANNEL. Discord as an ALERT channel was removed 2026-08-27; this is the
"something new" the owner foreshadowed, on its OWN secret
(config.MORNING_PLAYS_WEBHOOK_ENV = DISCORD_MORNING_WEBHOOK_URL) so it never
revives the removed alert webhook the credential pins guard. The webhook is
run through config.clean_secret (the 2026-08-01 BOM lesson) and posted with a
named User-Agent (Discord 403s Python's default UA).

Exit codes: 0 on a clean send / a "not my hour" skip / a missing webhook
(setup gap, warned loudly, like the tick 503 branch); 1 on a genuine delivery
failure, so the run reddens and GitHub emails -- a dead send must be loud.

    python scripts/morning_plays.py                 # gated to Melbourne 07:00
    python scripts/morning_plays.py --force         # send now regardless of hour
    python scripts/morning_plays.py --force --dry-run   # print payload, post nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                # runnable as `python scripts/morning_plays.py`
    sys.path.insert(0, str(ROOT))

from scanner import config                   # noqa: E402

DATA_DIR = ROOT / "public" / "data"


# ── the definition, identical to app.js isHighConviction ─────────────────────

def is_high_conviction(row: dict) -> bool:
    """A WEEKLY reclaim that's armed and A/A+ or has strong structure.

    Mirrors public/js/app.js isHighConviction exactly:
        p = row.plans["1W"]; p.armed && p.entry_trigger === "reclaim"
        && (grade in {A+, A} || (p.structural_tps || 0) >= 2)
    """
    p = (row.get("plans") or {}).get("1W")
    if not p or not p.get("armed") or p.get("entry_trigger") != "reclaim":
        return False
    good_grade = row.get("grade") in ("A+", "A")
    strong_structure = (p.get("structural_tps") or 0) >= 2
    return bool(good_grade or strong_structure)


# ── loading + selecting ──────────────────────────────────────────────────────

def load_market(market: str, data_dir: pathlib.Path = DATA_DIR) -> dict:
    """Read one market's committed scan JSON, or an empty stand-in if absent."""
    path = data_dir / f"{market}_vivek.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _scan_age_hours(generated_at: str | None, now_utc: dt.datetime) -> float | None:
    if not generated_at:
        return None
    try:
        t = dt.datetime.fromisoformat(generated_at)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (now_utc - t.astimezone(dt.timezone.utc)).total_seconds() / 3600.0
    except Exception:
        return None


def pick(rows: list[dict], cap: int) -> list[dict]:
    """High-conviction rows, strongest first (score desc), capped."""
    hc = [r for r in rows if is_high_conviction(r)]
    hc.sort(key=lambda r: (-(r.get("score") or 0), str(r.get("symbol") or "")))
    return hc[:cap]


# ── formatting the Discord payload (pure) ────────────────────────────────────

def _num(x) -> str:
    if x is None:
        return "-"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    return f"{v:g}"


def _play_line(r: dict) -> str:
    is_short = str(r.get("dir", "LONG")).upper() == "SHORT"
    arrow = "▼" if is_short else "▲"          # down/up triangle
    side = "SHORT" if is_short else "LONG"
    name = str(r.get("name") or "").strip()
    bits = [f"{arrow} **{r.get('symbol', '?')}** {side} · {r.get('grade', '?')}"]
    if name and name.upper() != str(r.get("symbol") or "").upper():
        bits.append(name[:40])
    lv = f"entry {_num(r.get('entry'))} · stop {_num(r.get('stop'))}"
    rr = r.get("rr")
    if rr not in (None, 0):
        lv += f" · R:R {_num(rr)}"
    bits.append(lv)
    if r.get("is_product"):
        bits.append("⚠ FUND/REIT")            # not bot-tradeable / rarely on CFDs
    return " · ".join(bits)


def build_payload(picks_by_market: dict[str, list[dict]],
                  ages: dict[str, float | None],
                  when_label: str) -> dict:
    """The Discord webhook JSON. `picks_by_market` is market -> [rows]."""
    total = sum(len(v) for v in picks_by_market.values())
    stale_h = float(getattr(config, "MORNING_PLAYS_STALE_H", 20.0) or 0)
    if not total:
        return {"content": (f"\U0001f3af **High conviction — {when_label}**\n"
                            "No high-conviction plays across ASX or NASDAQ this "
                            "morning.")}

    embeds = []
    for market, picks in picks_by_market.items():
        if not picks:
            continue
        title = f"{market.upper()} — {len(picks)}"
        age = ages.get(market)
        if age is not None and stale_h and age > stale_h:
            title += f"  (scan {age:.0f}h old)"
        desc = "\n".join(_play_line(r) for r in picks)
        embeds.append({"title": title, "description": desc[:4000],
                       "color": 0x2FD07F})
    plural = "play" if total == 1 else "plays"
    content = (f"\U0001f3af **High conviction — {when_label}**\n"
               f"{total} {plural} across ASX + NASDAQ "
               "(weekly reclaim, A/A+ or strong structure).")
    url = str(getattr(config, "MORNING_PLAYS_APP_URL", "") or "").strip()
    if url:
        content += f"\n{url}"
    return {"content": content, "embeds": embeds[:10]}


# ── posting ──────────────────────────────────────────────────────────────────

def post(webhook: str, payload: dict, ua: str, urlopen=urllib.request.urlopen) -> int:
    """POST the payload; return the HTTP status. Raises on transport failure."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": ua})
    with urlopen(req, timeout=20) as resp:
        return int(getattr(resp, "status", None) or resp.getcode())


# ── the run ──────────────────────────────────────────────────────────────────

def should_send_now(now_local: dt.datetime, hour: int, force: bool) -> bool:
    """One of the two superset crons is the target hour in Melbourne; only it
    sends. A manual --force run always sends."""
    return bool(force or now_local.hour == hour)


def gather(data_dir: pathlib.Path, now_utc: dt.datetime) -> tuple[dict, dict]:
    picks_by_market: dict[str, list[dict]] = {}
    ages: dict[str, float | None] = {}
    cap = int(getattr(config, "MORNING_PLAYS_MAX_ROWS", 20) or 20)
    for market in config.MORNING_PLAYS_MARKETS:
        payload = load_market(market, data_dir)
        picks_by_market[market] = pick(payload.get("results", []), cap)
        ages[market] = _scan_age_hours(payload.get("generated_at"), now_utc)
    return picks_by_market, ages


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="morning_plays")
    ap.add_argument("--force", action="store_true",
                    help="send regardless of the Melbourne hour (manual test)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the payload, post nothing")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)

    tz = ZoneInfo(config.MORNING_PLAYS_TZ)
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_local = now_utc.astimezone(tz)
    hour = int(config.MORNING_PLAYS_HOUR)

    if not should_send_now(now_local, hour, args.force):
        print(f"morning_plays: {now_local:%H:%M} {config.MORNING_PLAYS_TZ} is not "
              f"the {hour:02d}:00 send hour - this cron is a no-op today.")
        return 0

    when_label = f"{now_local:%a %-d %b}, {hour:02d}:00 Melbourne"
    picks_by_market, ages = gather(pathlib.Path(args.data_dir), now_utc)
    payload = build_payload(picks_by_market, ages, when_label)
    total = sum(len(v) for v in picks_by_market.values())
    per = ", ".join(f"{m} {len(v)}" for m, v in picks_by_market.items())
    print(f"morning_plays: {total} high-conviction plays ({per})")

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    webhook = config.clean_secret(os.environ.get(config.MORNING_PLAYS_WEBHOOK_ENV))
    if not webhook:
        # Setup gap, not a fault: the owner has not created the webhook yet.
        # Loud on the run page (like the tick 503 branch), green run.
        print(f"::warning::{config.MORNING_PLAYS_WEBHOOK_ENV} is not set - "
              "nothing was sent. Create a Discord webhook for the channel you "
              "want and add it as that Actions secret to switch this on.")
        return 0

    try:
        status = post(webhook, payload, config.MORNING_PLAYS_UA)
    except Exception as e:                                   # noqa: BLE001
        print(f"::error::morning_plays: Discord POST failed: "
              f"{e.__class__.__name__}: {e}")
        return 1
    if 200 <= status < 300:
        print(f"morning_plays: delivered ({status}).")
        return 0
    print(f"::error::morning_plays: Discord returned HTTP {status} - not delivered.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

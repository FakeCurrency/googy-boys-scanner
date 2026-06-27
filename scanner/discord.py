"""Discord digest — posts new tradeable setups to a Discord channel webhook.

A clean, consistent, daily-friendly feed of the scanner's best ideas:

    python -m scanner.discord                  # new A+/A across all markets
    python -m scanner.discord --all            # repost every current A+/A
    python -m scanner.discord --market asx      # one market
    python -m scanner.discord --min-grade A+    # only the very best
    python -m scanner.discord --dry-run         # build + preview, post nothing

Set DISCORD_WEBHOOK_URL (env var / GitHub secret) to enable posting. Without it
the module writes a JSON preview and exits cleanly — it never fails a workflow.

Design for reliability + a calm daily cadence:
  * State-deduped: only setups that are NEW since the last run are posted, so
    an hourly scan doesn't repeat the same names. `--all` overrides this.
  * One tidy embed per market (capped, grade-sorted), colour-coded by best grade.
  * Discord limits respected: ≤10 embeds/message, description ≤4096 chars.
  * Retries with back-off and 429 Retry-After handling.
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import time

import requests

from . import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "journal" / "discord_state.json"
PREVIEW = ROOT / "public" / "data" / "discord_preview.json"

DISCORD_DESC_LIMIT = 4096
DISCORD_MAX_EMBEDS = 10


# ── state (dedup so we only post NEW setups) ──────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── filtering / sorting ───────────────────────────────────────────────────────

def grades_to_post(min_grade: str) -> set[str]:
    """The set of grades at or above `min_grade` (e.g. 'A' → {'A+', 'A'})."""
    order = config.GRADE_PRECEDENCE
    if min_grade not in order:
        return set(config.TRADEABLE_GRADES)
    cutoff = order.index(min_grade)
    return {g for i, g in enumerate(order) if i <= cutoff}


def dedup_by_symbol(items: list) -> list:
    """Keep the highest-scoring row per symbol, preserving input order."""
    best: dict[str, dict] = {}
    for r in items:
        sym = r["symbol"]
        cur = best.get(sym)
        if cur is None or r.get("score", 0) > cur.get("score", 0):
            best[sym] = r
    seen, out = set(), []
    for r in items:
        sym = r["symbol"]
        if sym not in seen and best[sym] is r:
            seen.add(sym)
            out.append(r)
    return out


def collect(market_key: str, state: dict, send_all: bool, grades: set[str]) -> tuple[dict, list]:
    """Return (scan, items_to_post) for one market.

    items_to_post is the deduped tradeable set (when send_all) or only the
    symbols not seen on the previous run. State is updated to the current set.
    """
    data_file = ROOT / "public" / "data" / f"{market_key}.json"
    if not data_file.exists():
        return {}, []
    try:
        scan = json.loads(data_file.read_text(encoding="utf-8"))
    except Exception:
        return {}, []
    tradeable = dedup_by_symbol([r for r in scan.get("results", []) if r.get("grade") in grades])
    prev = set(state.get(market_key, []))
    new = [r for r in tradeable if r["symbol"] not in prev]
    state[market_key] = [r["symbol"] for r in tradeable]
    return scan, (tradeable if send_all else new)


# ── formatting ────────────────────────────────────────────────────────────────

def _fmt_price(cur: str, v) -> str:
    if v is None:
        return "—"
    v = float(v)
    s = f"{v:,.4f}" if abs(v) < 100 else f"{v:,.2f}"
    return f"{cur}{s}"


def setup_line(r: dict, cur: str) -> str:
    """One clean, consistent block for a single setup (Discord markdown)."""
    emoji = config.DISCORD_GRADE_EMOJI.get(r.get("grade", ""), "•")
    rr = r.get("rr")
    rr_txt = "—" if rr is None else f"{rr:.1f}"
    warn = "  ⚠️ low R:R" if r.get("low_rr") else ""
    score = f"{r.get('score', '?')}/{r.get('score_max', '?')}"
    dir_txt = f" {r['dir']}" if r.get("dir") and r["dir"] != "LONG" else ""
    head = f"{emoji} **{r['symbol']}**{dir_txt} · {r.get('grade', '?')} · {score} · R:R {rr_txt}{warn}"
    levels = (f"   `entry {_fmt_price(cur, r.get('entry'))} · "
              f"stop {_fmt_price(cur, r.get('stop'))} · "
              f"target {_fmt_price(cur, r.get('target'))}`")
    return head + "\n" + levels


def build_market_embed(scan: dict, items: list) -> dict:
    """One embed per market: title, best-grade colour, capped setup list."""
    cur = scan.get("currency_symbol", "$")
    capped = items[: config.DISCORD_MAX_PER_MARKET]
    best_grade = min((r.get("grade", "C") for r in capped),
                     key=lambda g: config.GRADE_PRECEDENCE.index(g) if g in config.GRADE_PRECEDENCE else 99,
                     default="A")
    color = config.DISCORD_GRADE_COLORS.get(best_grade, config.DISCORD_BRAND_COLOR)

    lines = [setup_line(r, cur) for r in capped]
    desc = "\n".join(lines)
    if len(desc) > DISCORD_DESC_LIMIT:
        desc = desc[: DISCORD_DESC_LIMIT - 1].rsplit("\n", 1)[0] + "\n…"
    extra = len(items) - len(capped)
    title = f"{scan.get('label', scan.get('market', '?'))} — {len(items)} setup{'s' if len(items) != 1 else ''}"
    if extra > 0:
        title += f" (top {len(capped)})"

    return {"title": title, "color": color, "description": desc}


def build_payloads(digests: list, total: int) -> list[dict]:
    """Build one or more webhook payloads (chunked to ≤10 embeds each)."""
    today = dt.date.today().isoformat()
    embeds = [build_market_embed(scan, items) for _, scan, items in digests if items]
    if not embeds:
        return []
    # Header line on the first embed's content; disclaimer footer on the last.
    embeds[-1]["footer"] = {"text": "General information only — not financial advice. Markets carry risk."}
    embeds[-1]["timestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()

    payloads = []
    for i in range(0, len(embeds), DISCORD_MAX_EMBEDS):
        chunk = embeds[i: i + DISCORD_MAX_EMBEDS]
        payload = {
            "username": config.DISCORD_USERNAME,
            "embeds": chunk,
        }
        if config.DISCORD_AVATAR_URL:
            payload["avatar_url"] = config.DISCORD_AVATAR_URL
        if i == 0:
            payload["content"] = f"📈 **{total} new setup{'s' if total != 1 else ''}** · {today}"
        payloads.append(payload)
    return payloads


# ── posting ───────────────────────────────────────────────────────────────────

def post_webhook(url: str, payload: dict, retries: int | None = None) -> bool:
    """POST one payload with retry + 429 Retry-After handling. Returns success."""
    retries = config.DISCORD_POST_RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code in (200, 204):
                return True
            if resp.status_code == 429:  # rate limited — honour Retry-After
                wait = 1.0
                try:
                    wait = float(resp.json().get("retry_after", 1.0))
                except Exception:
                    wait = float(resp.headers.get("Retry-After", "1") or 1)
                time.sleep(min(wait + 0.25, 10))
                continue
            if 500 <= resp.status_code < 600:  # transient server error — back off
                time.sleep(2 * (attempt + 1))
                continue
            # 4xx other than 429 won't fix themselves — stop.
            print(f"discord: webhook rejected ({resp.status_code}): {resp.text[:200]}")
            return False
        except requests.RequestException as e:
            print(f"discord: attempt {attempt + 1}/{retries + 1} failed: {e}")
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    return False


# ── orchestration ─────────────────────────────────────────────────────────────

def run(market_keys: list[str], send_all: bool = False, min_grade: str | None = None,
        dry_run: bool = False) -> int:
    """Collect, format and post. Returns the number of setups posted."""
    grades = grades_to_post(min_grade or config.DISCORD_MIN_GRADE)
    state = _load_state()
    digests = []
    for mk in market_keys:
        scan, items = collect(mk, state, send_all, grades)
        if items:
            digests.append((mk, scan, items))

    total = sum(len(i) for _, _, i in digests)
    if not total:
        print("discord: no new setups to post.")
        if not dry_run:
            _save_state(state)
        return 0

    payloads = build_payloads(digests, total)

    # Always write a preview so you can see exactly what would post.
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.write_text(json.dumps(payloads, indent=2, ensure_ascii=False), encoding="utf-8")

    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if dry_run or not webhook:
        why = "dry-run" if dry_run else "DISCORD_WEBHOOK_URL not set"
        print(f"discord: {total} setup(s) — {why}; preview written to {PREVIEW}.")
        # On a real (non-dry) run with no webhook, still advance state so a later
        # configured run doesn't dump the whole backlog at once.
        if not dry_run:
            _save_state(state)
        return total

    ok_all = True
    for payload in payloads:
        if not post_webhook(webhook, payload):
            ok_all = False
            break
        time.sleep(0.4)  # gentle pacing between chunked messages

    if ok_all:
        _save_state(state)  # only mark as posted once delivery succeeded
        print(f"discord: posted {total} setup(s) across {len(digests)} market(s).")
    else:
        print("discord: delivery failed — state NOT advanced, will retry next run.")
    return total if ok_all else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Post new tradeable setups to Discord")
    ap.add_argument("--market", action="append", choices=list(config.MARKETS),
                    help="restrict to one or more markets (default: all)")
    ap.add_argument("--all", action="store_true",
                    help="post all current A+/A, not just new since last run")
    ap.add_argument("--min-grade", default=config.DISCORD_MIN_GRADE,
                    choices=config.GRADE_PRECEDENCE, help="minimum grade to post")
    ap.add_argument("--dry-run", action="store_true", help="build + preview, post nothing")
    args = ap.parse_args()
    run(args.market or list(config.MARKETS), send_all=args.all,
        min_grade=args.min_grade, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

"""Telegram swing trade digest for ASX and NASDAQ.

Sends TWO digests per market per trading day (open + mid-session) so you get
an early heads-up at the open AND a mid-day refresh of new setups that formed
during the session.  Only A+ signals are included to keep the list tight.

    python -m scanner.notify            # live send
    python -m scanner.notify --dry-run  # print without sending
    python -m scanner.notify --reset    # clear today's sent state (re-sends)

Session windows (UTC):
  ASX   open  00:00–02:59   mid  03:00–05:59
  NASDAQ open 13:00–16:59   mid  17:00–21:59
"""

import argparse
import datetime as dt
import html as _html
import json
import os
import pathlib
import urllib.error
import urllib.request

ROOT       = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR   = ROOT / "data"
_SEEN_FILE = DATA_DIR / "notified_signals.json"

# Sources: (market_key, setup_label, relative_path, currency_symbol, TV_prefix)
_SOURCES = [
    ("asx",    "Pullback", "public/data/asx.json",             "A$", "ASX"),
    ("asx",    "Reversal", "public/data/asx_reversal.json",    "A$", "ASX"),
    ("nasdaq", "Pullback", "public/data/nasdaq.json",          "$",  "NASDAQ"),
    ("nasdaq", "Reversal", "public/data/nasdaq_reversal.json", "$",  "NASDAQ"),
]

_ALERT_GRADES   = {"A+"}    # A+ only keeps the list tight (~20 or fewer)
_MAX_PER_DIGEST = 20        # max signals shown per market per session
_TG_MAX_CHARS   = 4000      # Telegram hard limit is 4096; leave headroom

# Session split: which UTC hour marks the start of the "mid" window.
_MID_HOUR = {"asx": 3, "nasdaq": 17}


# ── Telegram ──────────────────────────────────────────────────────────────────

def _tg_send(text: str) -> bool:
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  notify: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set — skipping")
        return False

    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        print(f"  notify: Telegram HTTP {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"  notify: Telegram request failed: {e}")
        return False


# ── Deduplication ─────────────────────────────────────────────────────────────

def _load_seen() -> dict:
    if _SEEN_FILE.exists():
        try:
            return json.loads(_SEEN_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_seen(seen: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SEEN_FILE.write_text(json.dumps(seen, indent=2))


# ── Signal loading ────────────────────────────────────────────────────────────

def _load_signals() -> dict[str, list[dict]]:
    """Return {market: [enriched_signal, ...]} for all A+/A setups, sorted."""
    by_market: dict[str, list[dict]] = {"asx": [], "nasdaq": []}

    for market, setup_type, rel_path, currency, tv_prefix in _SOURCES:
        path = ROOT / rel_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue

        for sig in data.get("results", []):
            if sig.get("grade") not in _ALERT_GRADES:
                continue
            sig["_setup_type"] = setup_type
            sig["_currency"]   = currency
            sig["_tv_prefix"]  = tv_prefix
            by_market[market].append(sig)

    grade_order = {"A+": 0, "A": 1}
    for market in by_market:
        by_market[market].sort(
            key=lambda s: (
                grade_order.get(s.get("grade", "A"), 9),
                -float(s.get("rr", 0) or 0),
                s.get("symbol", ""),          # stable tiebreaker — never compares dicts
            )
        )

    return by_market


# ── Message formatting ────────────────────────────────────────────────────────

def _decimals(price: float) -> int:
    if price < 0.10:  return 4
    if price < 10:    return 3
    if price < 1000:  return 2
    return 0


def _h(text: str) -> str:
    """HTML-escape a string for Telegram's HTML parse mode."""
    return _html.escape(str(text))


def _format_digest(market: str, signals: list[dict], today: str, session: str) -> str:
    """Build a single digest message for one market, capped at _TG_MAX_CHARS."""
    mkt_label     = "🇦🇺 ASX" if market == "asx" else "🇺🇸 NASDAQ"
    session_label = "OPEN" if session == "open" else "MID-SESSION"
    total         = len(signals)

    header = [
        f"<b>{mkt_label} SWING SETUPS — {today} {session_label}</b>",
        f"<i>{total} A+ signal{'s' if total != 1 else ''} found</i>",
        "",
    ]
    footer = "\n⚠️ <i>Check your own chart before entering. This is not financial advice.</i>"

    body_lines: list[str] = []
    shown = 0

    for sig in signals[:_MAX_PER_DIGEST]:
        symbol     = sig.get("symbol", "")
        grade      = sig.get("grade", "")
        direction  = sig.get("dir", "LONG")
        rr_text    = sig.get("rr_text", "")
        entry      = float(sig.get("entry") or 0)
        stop_pct   = float(sig.get("stop_pct") or 0)
        p2_pct     = float(sig.get("p2_pct") or 0)
        weekly     = sig.get("weekly", False)
        chips      = sig.get("chips", [])[:3]
        setup_type = sig.get("_setup_type", "")
        currency   = sig.get("_currency", "$")
        tv_prefix  = sig.get("_tv_prefix", "")

        dec        = _decimals(entry)
        dir_icon   = "🟢" if direction == "LONG" else "🔴"
        grade_icon = "⭐" if grade == "A+" else "✅"
        weekly_str = " W✓" if weekly else ""
        reason     = _h(" · ".join(chips))
        tv_url     = f"https://www.tradingview.com/chart/?symbol={tv_prefix}:{symbol}"
        sym_safe   = _h(symbol)

        sig_lines = [
            f"{dir_icon}{grade_icon} <b><a href=\"{tv_url}\">{sym_safe}</a></b>  {grade}  ·  {_h(setup_type)}{weekly_str}",
            f"   Entry {currency}{entry:.{dec}f}  ·  Stop −{stop_pct:.1f}%  ·  Target +{p2_pct:.1f}%  ·  R:R {rr_text}",
            f"   <i>{reason}</i>",
            "",
        ]

        candidate = "\n".join(header + body_lines + sig_lines) + footer
        if len(candidate) > _TG_MAX_CHARS:
            break

        body_lines += sig_lines
        shown += 1

    more = total - shown
    if more > 0:
        body_lines.append(f"<i>…and {more} more signal{'s' if more != 1 else ''}</i>")
        body_lines.append("")

    return "\n".join(header + body_lines) + footer


# ── Main ──────────────────────────────────────────────────────────────────────

def _session(market: str, now: dt.datetime) -> str:
    """Return 'open' or 'mid' based on current UTC hour."""
    return "mid" if now.hour >= _MID_HOUR[market] else "open"


def run(dry_run: bool = False, reset: bool = False) -> None:
    now    = dt.datetime.now(dt.timezone.utc)
    today  = now.date().isoformat()
    seen   = {} if reset else _load_seen()
    sent   = 0
    skipped = 0

    by_market = _load_signals()

    for market, signals in by_market.items():
        if not signals:
            continue

        session = _session(market, now)
        key = f"{market}_{today}_{session}"
        if seen.get(key):
            skipped += 1
            continue

        msg = _format_digest(market, signals, today, session)

        if dry_run:
            print(f"\n{'═'*62}")
            print(msg)
            print(f"{'═'*62}\n")
            seen[key] = now.isoformat(timespec="seconds")
            sent += 1
        else:
            ok = _tg_send(msg)
            if ok:
                seen[key] = now.isoformat(timespec="seconds")
                sent += 1
                print(f"  notify: ✓ {market.upper()} {session} digest sent ({len(signals)} signals)")
            else:
                print(f"  notify: ✗ {market.upper()} {session} digest failed — will retry next scan")

    _save_seen(seen)

    total_markets = sum(1 for v in by_market.values() if v)
    if total_markets == 0:
        print("  notify: no A+ swing signals in current scan")
    elif skipped == total_markets:
        print(f"  notify: digest already sent today for all {skipped} market(s) — skipping")
    else:
        print(f"  notify: {sent} digest(s) sent, {skipped} already sent today")


def main() -> None:
    ap = argparse.ArgumentParser(description="Send Telegram swing trade digest")
    ap.add_argument("--dry-run", action="store_true",
                    help="print digest without sending to Telegram")
    ap.add_argument("--reset", action="store_true",
                    help="clear today's sent state (re-sends the digest)")
    args = ap.parse_args()
    run(dry_run=args.dry_run, reset=args.reset)


if __name__ == "__main__":
    main()

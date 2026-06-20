"""Telegram swing trade digest for ASX and NASDAQ.

Sends three digests per market per trading day at fixed AEST times.
Only A+ signals are included to keep the list tight (~20 or fewer).
Each slot sends two messages back-to-back:
  1. All A+ signals (all market caps)
  2. Sub-750M small cap A+ signals only

    python -m scanner.notify            # live send
    python -m scanner.notify --dry-run  # print without sending
    python -m scanner.notify --reset    # clear today's sent state (re-sends)

Alert slots (AEST -> UTC):
  ASX    11:00 AM -> 01:00 UTC   2:00 PM -> 04:00 UTC   4:30 PM -> 06:30 UTC
  NASDAQ 12:00 AM -> 14:00 UTC   3:00 AM -> 17:00 UTC   7:00 AM -> 21:00 UTC
"""

import argparse
import datetime as dt
import html as _html
import json
import os
import pathlib
import urllib.error
import urllib.request

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

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

_ALERT_GRADES       = {"A+"}    # A+ only keeps the list tight
_MAX_PER_DIGEST     = 50        # hard cap per slot (paginated across multiple messages)
_TG_MAX_CHARS       = 3800      # safe limit per message (Telegram hard cap is 4096)
_SMALLCAP_THRESHOLD = 750_000_000  # sub-750M market cap filter
_HOT_SMALLCAP       = 500_000_000  # 🔥 marker: micro/small cap spec sweet spot

# Alert slots: (slot_key, utc_hour_min, utc_hour_max_exclusive, display_label)
_SLOTS: dict[str, list[tuple[str, int, int, str]]] = {
    "asx": [
        ("s1",  1,  4, "11 AM AEST"),
        ("s2",  4,  6,  "2 PM AEST"),
        ("s3",  6, 24, "4:30 PM AEST"),
    ],
    "nasdaq": [
        ("s1", 14, 17, "12 AM AEST"),
        ("s2", 17, 21,  "3 AM AEST"),
        ("s3", 21, 24,  "7 AM AEST"),
    ],
}


# -- Market cap helpers --------------------------------------------------------

def _yf_sym(market: str, symbol: str) -> str:
    return symbol + ".AX" if market == "asx" else symbol


def _fmt_mcap(v: float) -> str:
    if not v or v <= 0:
        return ""
    if v >= 1e12: return f"{v/1e12:.1f}T"
    if v >= 1e9:  return f"{v/1e9:.1f}B"
    if v >= 1e6:  return f"{v/1e6:.0f}M"
    return f"{v/1e3:.0f}K"


def _fetch_market_caps(market: str, signals: list[dict]) -> dict[str, float]:
    """Return {symbol: raw_market_cap} for the passed signals.

    Reads from the persistent market-cap cache (data/market_caps.json), which is
    refreshed by `scanner.marketcaps` from a fresh IP BEFORE the scan. Yahoo
    throttles its fundamentals endpoint from cloud IPs right after a heavy scan,
    so fetching live at alert time returns nothing — the cache is the reliable
    source. Symbols missing from the cache simply show no cap (and won't appear
    in the sub-750M digest until the cache picks them up on a later refresh).
    """
    caps: dict[str, float] = {}
    try:
        from . import marketcaps
        cache = marketcaps.load_cache()
        for s in signals:
            sym = s.get("symbol", "")
            mc = marketcaps.mcap_for(cache, market, sym)
            if mc > 0:
                caps[sym] = mc
    except Exception:
        pass
    return caps


# -- Telegram ------------------------------------------------------------------

def _tg_send(text: str) -> bool:
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  notify: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set -- skipping")
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


# -- Deduplication -------------------------------------------------------------

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


# -- Signal loading ------------------------------------------------------------

def _load_signals() -> dict[str, list[dict]]:
    """Return {market: [enriched_signal, ...]} for all A+ setups, sorted by R:R."""
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

    for market in by_market:
        by_market[market].sort(key=lambda s: -float(s.get("rr", 0) or 0))

    return by_market


# -- Message formatting --------------------------------------------------------

def _decimals(price: float) -> int:
    if price < 0.10:  return 4
    if price < 10:    return 3
    if price < 1000:  return 2
    return 0


def _h(text: str) -> str:
    return _html.escape(str(text))


def _sig_block(sig: dict, caps: dict[str, float]) -> str:
    """Format one signal as a 3-line text block (no trailing newline)."""
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
    sector     = sig.get("sector", "")
    raw_mcap   = caps.get(symbol, 0.0)
    mcap       = _fmt_mcap(raw_mcap)
    # 🔥 flags a micro/small cap under 500M — the spec-play sweet spot where a
    # clean chart can precede an outsized breakout.
    if 0 < raw_mcap < _HOT_SMALLCAP and mcap:
        mcap = "🔥" + mcap

    dec        = _decimals(entry)
    dir_icon   = "🟢" if direction == "LONG" else "🔴"
    grade_icon = "⭐" if grade == "A+" else "✅"
    weekly_str = " W✓" if weekly else ""
    meta_parts = [p for p in [sector, mcap] if p]
    meta_str   = ("  ·  " + "  ·  ".join(_h(p) for p in meta_parts)) if meta_parts else ""
    reason     = _h(" · ".join(chips))
    tv_url     = f"https://www.tradingview.com/chart/?symbol={tv_prefix}:{symbol}"

    return (
        f"{dir_icon}{grade_icon} <b><a href=\"{tv_url}\">{_h(symbol)}</a></b>"
        f"{meta_str}  ·  {grade}  ·  {_h(setup_type)}{weekly_str}\n"
        f"   Entry {currency}{entry:.{dec}f}  ·  Stop -{stop_pct:.1f}%"
        f"  ·  Target +{p2_pct:.1f}%  ·  R:R {rr_text}\n"
        f"   <i>{reason}</i>"
    )


def _build_pages(market: str, signals: list[dict], today: str, slot_label: str,
                 caps: dict[str, float] | None = None,
                 title: str = "SWING SETUPS") -> list[str]:
    """Return 1+ Telegram messages covering all signals, each under _TG_MAX_CHARS."""
    mkt_label = "🇦🇺 ASX" if market == "asx" else "🇺🇸 NASDAQ"
    total     = len(signals)
    caps      = caps or {}
    footer    = "\n⚠️ <i>Check your own chart before entering. This is not financial advice.</i>"

    blocks = [_sig_block(s, caps) for s in signals[:_MAX_PER_DIGEST]]

    pages: list[str] = []
    i = 0
    while i < len(blocks):
        page_n = len(pages) + 1
        if page_n == 1:
            hdr = (f"<b>{mkt_label} {title} — {slot_label}</b>\n"
                   f"<i>{today}  ·  {total} A+ signal{'s' if total != 1 else ''}</i>\n\n")
        else:
            hdr = f"<b>{mkt_label} {title} — {slot_label} (cont.)</b>\n\n"

        body = ""
        while i < len(blocks):
            candidate = hdr + body + blocks[i] + "\n\n" + footer
            if len(candidate) > _TG_MAX_CHARS and body:
                break
            body += blocks[i] + "\n\n"
            i += 1

        pages.append(hdr + body.rstrip() + footer)

    return pages or [f"<b>{mkt_label} {title} — {slot_label}</b>\n<i>No A+ signals.</i>"]


# -- Send helper ---------------------------------------------------------------

def _notice_msg(market: str, slot_label: str, today: str, note: str) -> str:
    """A single short message for the small-cap slot when there's no list to show."""
    mkt_label = "🇦🇺 ASX" if market == "asx" else "🇺🇸 NASDAQ"
    return (f"<b>{mkt_label} SMALL CAPS &lt;750M — {slot_label}</b>\n"
            f"<i>{today}</i>\n\n{note}")


def _send_digest(pages: list[str], label: str, dry_run: bool) -> bool:
    """Send all pages for one digest. Returns True if all sent (or dry-run)."""
    if dry_run:
        for pg in pages:
            print(f"\n{'='*62}")
            print(pg)
            print(f"{'='*62}\n")
        return True

    for pg in pages:
        if not _tg_send(pg):
            return False
    return True


# -- Main ----------------------------------------------------------------------

def _slot(market: str, now: dt.datetime) -> tuple[str, str] | None:
    """Return (slot_key, display_label) for the current UTC hour, or None."""
    h = now.hour
    for key, h_min, h_max, label in _SLOTS.get(market, []):
        if h_min <= h < h_max:
            return key, label
    return None


def run(dry_run: bool = False, reset: bool = False) -> None:
    now     = dt.datetime.now(dt.timezone.utc)
    today   = now.date().isoformat()
    seen    = {} if reset else _load_seen()
    sent    = 0
    skipped = 0

    by_market = _load_signals()

    for market, signals in by_market.items():
        slot_info = _slot(market, now)
        if slot_info is None:
            continue

        slot_key, slot_label = slot_info

        if not signals:
            continue

        reg_key = f"{market}_{today}_{slot_key}"
        sc_key  = f"{market}_{today}_{slot_key}_sc750"

        if seen.get(reg_key) and seen.get(sc_key):
            skipped += 1
            continue

        # Fetch raw market caps for ALL signals — used for display and sub-750M filter
        caps = _fetch_market_caps(market, signals)

        # Regular digest (all market caps) ────────────────────────────────────
        if not seen.get(reg_key):
            pages = _build_pages(market, signals, today, slot_label, caps)
            ok = _send_digest(pages, f"{market.upper()} {slot_label}", dry_run)
            if ok:
                seen[reg_key] = now.isoformat(timespec="seconds")
                sent += 1
                if not dry_run:
                    n = len(pages)
                    print(f"  notify: ✓ {market.upper()} {slot_label} sent "
                          f"({len(signals)} signals, {n} message{'s' if n > 1 else ''})")
            else:
                print(f"  notify: ✗ {market.upper()} {slot_label} failed — will retry next scan")

        # Sub-750M small cap digest ────────────────────────────────────────────
        # Always sends a message alongside the regular digest so the small-cap
        # scan is never silently absent: the filtered list, or an explicit note.
        if not seen.get(sc_key):
            small_sigs = [
                s for s in signals
                if 0 < caps.get(s.get("symbol", ""), 0.0) < _SMALLCAP_THRESHOLD
            ]
            if small_sigs:
                sc_pages = _build_pages(market, small_sigs, today, slot_label, caps,
                                        title="SMALL CAPS &lt;750M")
            elif caps:
                # Cap data is good, just nothing under the threshold this slot.
                sc_pages = [_notice_msg(market, slot_label, today,
                                        "No A+ setups under 750M market cap this slot.")]
            else:
                # Couldn't get market caps at all — say so rather than imply none exist.
                sc_pages = [_notice_msg(market, slot_label, today,
                                        "Market-cap data was unavailable this slot, so the "
                                        "&lt;750M filter couldn't run. It'll retry next alert.")]

            ok = _send_digest(sc_pages, f"{market.upper()} {slot_label} <750M", dry_run)
            if ok:
                # Only lock in the dedup key when caps worked; if they didn't, leave
                # it open so the next slot retries the fetch.
                if small_sigs or caps:
                    seen[sc_key] = now.isoformat(timespec="seconds")
                sent += 1
                if not dry_run:
                    n = len(sc_pages)
                    print(f"  notify: ✓ {market.upper()} {slot_label} <750M sent "
                          f"({len(small_sigs)} signals, {n} message{'s' if n > 1 else ''})")
            else:
                print(f"  notify: ✗ {market.upper()} {slot_label} <750M failed — will retry")

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

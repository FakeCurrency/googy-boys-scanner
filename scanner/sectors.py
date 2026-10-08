"""Sector & index dashboard (ASX + US) with an auto, data-derived market read.

Fetches the major indices and the 11 GICS sectors for each market, then writes a
plain-English "what happened" summary and a "money rotation" read — purely from
the moves (no social/AI). Written to public/data/sectors.json.
"""

import datetime as dt
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import yfinance as yf

# ForexFactory weekly economic-calendar feeds (free, times in UTC).
FF_URLS = ["https://nfs.faireconomy.media/ff_calendar_thisweek.xml",
           "https://nfs.faireconomy.media/ff_calendar_nextweek.xml"]
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GoogyBoys/1.0)"}

# (display symbol, name, yfinance ticker, divide_by)
ASX_INDICES = [("XJO", "S&P/ASX 200", "^AXJO", 1), ("XKO", "ASX 300", "^AXKO", 1),
               ("XSO", "Small Ords", "^AXSO", 1), ("XVI", "ASX VIX", "^AXVI", 1)]
ASX_SECTORS = [("XMJ", "Materials", "^AXMJ", 1), ("XEJ", "Energy", "^AXEJ", 1),
               ("XFJ", "Financials", "^AXFJ", 1), ("XHJ", "Health Care", "^AXHJ", 1),
               ("XDJ", "Cons. Disc.", "^AXDJ", 1), ("XSJ", "Cons. Staples", "^AXSJ", 1),
               ("XIJ", "Info Tech", "^AXIJ", 1), ("XUJ", "Utilities", "^AXUJ", 1),
               ("XNJ", "Industrials", "^AXNJ", 1), ("XTJ", "Comm. Services", "^AXTJ", 1),
               ("XPJ", "Property", "^AXPJ", 1), ("XGD", "Gold", "^AXGD", 1)]
US_INDICES = [("SPX", "S&P 500", "^GSPC", 1), ("COMP", "Nasdaq", "^IXIC", 1),
              ("DJI", "Dow Jones", "^DJI", 1), ("RUT", "Russell 2000", "^RUT", 1),
              ("VIX", "VIX", "^VIX", 1), ("US10Y", "10Y Yield", "^TNX", 1)]
US_SECTORS = [("XLK", "Technology", "XLK", 1), ("XLF", "Financials", "XLF", 1),
              ("XLE", "Energy", "XLE", 1), ("XLV", "Health Care", "XLV", 1),
              ("XLI", "Industrials", "XLI", 1), ("XLY", "Cons. Disc.", "XLY", 1),
              ("XLP", "Cons. Staples", "XLP", 1), ("XLU", "Utilities", "XLU", 1),
              ("XLB", "Materials", "XLB", 1), ("XLRE", "Real Estate", "XLRE", 1),
              ("XLC", "Comm. Services", "XLC", 1)]

CYCLICAL = {"XMJ", "XEJ", "XFJ", "XDJ", "XIJ", "XNJ", "XTJ",
            "XLK", "XLY", "XLF", "XLI", "XLE", "XLB", "XLC"}
DEFENSIVE = {"XUJ", "XSJ", "XHJ", "XPJ", "XGD", "XLU", "XLP", "XLV", "XLRE"}


def _fetch(rows):
    tickers = [r[2] for r in rows]
    try:
        data = yf.download(tickers, period="7d", interval="1d", group_by="ticker",
                           auto_adjust=False, threads=True, progress=False)
    except Exception:
        return []
    out = []
    for disp, name, yft, div in rows:
        try:
            close = (data if len(tickers) == 1 else data[yft])["Close"].dropna()
            if len(close) < 2:
                continue
            last = float(close.iloc[-1]) / div
            prev = float(close.iloc[-2]) / div
            if yft == "^TNX" and last > 15:   # Yahoo sometimes quotes the 10Y as yield×10
                last, prev = last / 10, prev / 10
            chg = last - prev
            pct = chg / prev * 100 if prev else 0.0
            out.append({"symbol": disp, "name": name,
                        "last": round(last, 1 if last >= 1000 else 2),
                        "chg": round(chg, 2), "chg_pct": round(pct, 2)})
        except Exception:
            continue
    return out


def _read(label, sectors, indices):
    """Plain-English market summary + rotation read from the day's moves."""
    if not sectors:
        return "", ""
    idx = {i["symbol"]: i for i in indices}

    def mv(sym):
        i = idx.get(sym)
        return f"{i['name']} {i['chg_pct']:+.1f}%" if i else None

    # headline index line per market
    keys = ["SPX", "COMP", "DJI", "RUT"] if label == "US" else ["XJO", "XKO", "XSO"]
    head = "; ".join(m for m in (mv(k) for k in keys) if m)
    extras = []
    if "VIX" in idx:
        extras.append(f"VIX {idx['VIX']['last']:g} ({idx['VIX']['chg_pct']:+.1f}%)")
    if "US10Y" in idx:
        extras.append(f"10Y {idx['US10Y']['last']:.2f}% ({idx['US10Y']['chg_pct']:+.1f}%)")
    if "XVI" in idx:
        extras.append(f"ASX VIX {idx['XVI']['last']:g}")
    extra = (" " + " · ".join(extras) + ".") if extras else ""

    ranked = sorted(sectors, key=lambda s: s["chg_pct"], reverse=True)
    up = [s for s in ranked if s["chg_pct"] > 0]
    down = [s for s in ranked if s["chg_pct"] < 0]
    best, worst = ranked[0], ranked[-1]

    cyc = [s["chg_pct"] for s in sectors if s["symbol"] in CYCLICAL]
    dfn = [s["chg_pct"] for s in sectors if s["symbol"] in DEFENSIVE]
    cyc_avg = sum(cyc) / len(cyc) if cyc else 0.0
    dfn_avg = sum(dfn) / len(dfn) if dfn else 0.0
    risk_on = cyc_avg > dfn_avg

    summary = (f"{head}.{extra} Breadth {len(up)} up / {len(down)} down across sectors — "
               f"{best['name']} led ({best['chg_pct']:+.1f}%), {worst['name']} lagged "
               f"({worst['chg_pct']:+.1f}%). Tone reads "
               f"{'risk-on (cyclicals leading)' if risk_on else 'risk-off / defensive'} "
               f"— cyclicals {cyc_avg:+.1f}% vs defensives {dfn_avg:+.1f}%. "
               "See the calendar below for the events behind it.")
    leaders = ", ".join(f"{s['symbol']} ({s['chg_pct']:+.1f}%)" for s in ranked[:3])
    laggards = ", ".join(f"{s['symbol']} ({s['chg_pct']:+.1f}%)" for s in ranked[-3:][::-1])
    rotation = (f"Money rotated INTO {leaders} and OUT OF {laggards}. "
                + ("Cyclicals/growth leading — appetite for risk."
                   if risk_on else "Defensives & gold leading — a cautious, risk-off lean."))
    return summary, rotation


def _split_movers(rows, market_key):
    """Pick each side's biggest movers split into MEGA vs SMALL companies.

    Up to ``MOVER_PER_TIER`` mega + ``MOVER_PER_TIER`` small per side, so the
    reader sees big-money rotation (mega) and small-cap discovery side by side.
    Company size comes from the pre-scan market-cap cache; when a name isn't
    cached we fall back to its 20-day average dollar volume (mega names trade
    vastly more $ than small caps) so the split always works without an extra,
    throttle-prone Yahoo call at scan time.
    """
    from . import config as _cfg
    from . import marketcaps as _mc

    cap_market = "nasdaq" if market_key in ("us", "nasdaq") else "asx"
    dvol_key   = "us" if cap_market == "nasdaq" else "asx"
    mega_dvol  = _cfg.MOVER_MEGA_DVOL.get(dvol_key, 30_000_000)
    try:
        cap_cache = _mc.load_cache()
    except Exception:
        cap_cache = {}

    def tier_of(r):
        cap = _mc.mcap_for(cap_cache, cap_market, r["symbol"]) if cap_cache else 0.0
        if cap > 0:
            return ("mega" if cap >= _cfg.MOVER_MEGA_CAP_USD else "small"), cap
        return ("mega" if r.get("dvol", 0) >= mega_dvol else "small"), 0.0

    def pick(ordered):
        per = _cfg.MOVER_PER_TIER
        mega, small = [], []
        for r in ordered:
            if len(mega) >= per and len(small) >= per:
                break
            tier, cap = tier_of(r)
            bucket = mega if tier == "mega" else small
            if len(bucket) >= per:
                continue
            bucket.append({"symbol": r["symbol"], "name": r["name"],
                           "sector": r["sector"], "last": r["last"],
                           "pct": r["pct"], "mcap": round(cap), "tier": tier})
        return mega + small

    if not rows:
        return {"winners": [], "losers": []}
    return {"winners": pick(rows), "losers": pick(rows[::-1])}


def enrich(m, frames, universe, min_dollar_vol, market_key=None):
    """Add stock-level depth to a market read: biggest winners/losers and a
    deeper sector-rotation line (which stocks drove it). (The 'explain like I'm
    5' note and the biggest-volume list were removed 2026-09-27 with their
    boxes on the NEWS page; ``indices`` stays because ``_read`` builds the
    "what happened" summary from it.)

    Computed from the scan's already-downloaded daily frames so it costs no extra
    network. ``frames`` is {yf_ticker: OHLCV DataFrame}; ``universe`` carries the
    per-stock GICS sector (ASX) used for the rotation breakdown. ``market_key``
    ('asx' / 'us') selects the market-cap cache used to split movers into mega
    vs small companies.
    """
    rows = []
    for u in universe:
        df = frames.get(u["yf"])
        if df is None or len(df) < 2:
            continue
        try:
            close, vol = df["Close"], df["Volume"]
            last, prev = float(close.iloc[-1]), float(close.iloc[-2])
            if prev <= 0:
                continue
            pct = (last / prev - 1) * 100
            dvol = float((close * vol).tail(20).mean())
        except Exception:
            continue
        # keep it to real, liquid names and drop obvious data glitches
        if dvol < min_dollar_vol or last < 0.05 or abs(pct) > 60:
            continue
        rows.append({"symbol": u["symbol"], "name": u["name"],
                     "sector": (u.get("sector") or "").strip(),
                     "last": round(last, 2 if last >= 1 else 4),
                     "pct": round(pct, 2),
                     "dvol": round(dvol)})

    rows.sort(key=lambda r: r["pct"], reverse=True)
    m["top_movers"] = _split_movers(rows, market_key)
    winners = m["top_movers"]["winners"]
    losers  = m["top_movers"]["losers"]

    # deeper rotation: group the liquid names by GICS sector (ASX has it), find
    # the leading & lagging sector and name the actual stocks driving each.
    by_sec = {}
    for r in rows:
        if r["sector"]:
            by_sec.setdefault(r["sector"], []).append(r)
    detail = ""
    sec_avg = []
    for name, items in by_sec.items():
        if len(items) < 3:
            continue
        avg = sum(i["pct"] for i in items) / len(items)
        sec_avg.append((name, avg, sorted(items, key=lambda i: i["pct"], reverse=True)))
    if sec_avg:
        sec_avg.sort(key=lambda x: x[1], reverse=True)
        best, worst = sec_avg[0], sec_avg[-1]

        def names(items, up=True, n=3):
            picks = items[:n] if up else items[::-1][:n]
            return ", ".join(f"{p['symbol']} {p['pct']:+.1f}%" for p in picks)

        detail = (f"{best[0]} led the session (avg {best[1]:+.1f}% across its big names): "
                  f"{names(best[2])}. {worst[0]} was the weakest (avg {worst[1]:+.1f}%): "
                  f"{names(worst[2], up=False)}.")
    if not detail and winners:
        detail = "Standout names: " + ", ".join(
            f"{w['symbol']} {w['pct']:+.1f}%" for w in winners[:4])
        if losers:
            detail += ". Weakest: " + ", ".join(
                f"{l['symbol']} {l['pct']:+.1f}%" for l in losers[:3])
        detail += "."
    if detail:
        m["rotation_detail"] = detail

    m["enriched_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return m


# Everything enrich() computes from a scan's downloaded frames. A run that did
# not scan a market CANNOT recompute these, so it must carry the last published
# values forward instead of publishing the market without them.
ENRICHED_KEYS = ("top_movers", "rotation_detail", "enriched_at")

# The market READ fetch() builds from its own sector/index downloads, moved as
# ONE unit (summary/rotation are computed from the two lists, and read_at says
# when they were fetched). See carry_forward for why it can need carrying.
READ_KEYS = ("indices", "sectors", "summary", "rotation", "read_at")


def _read_rank(m: dict) -> tuple:
    """How complete a market's read is: the sector board first (it is what the
    NEWS page draws and what the summary needs), then the index list (which
    only feeds the summary's headline)."""
    return (bool(m.get("sectors")), bool(m.get("indices")))


def carry_forward(sec: dict, prev: dict) -> int:
    """Copy ENRICHED_KEYS from the previously published sectors.json into any
    market of ``sec`` that this run did not enrich, and carry the previous
    READ (READ_KEYS) over a fresh one that came back emptier. Returns how many
    fields were moved.

    fetch() rebuilds the whole dict from scratch every run, so a crypto-only run
    (crypto_bot.yml, hourly 24/7) used to publish ASX and US with these keys
    simply GONE - the sectors page lost its movers and rotation detail until
    the next equity scan rebuilt them, which is most of the day.
    Carrying the last values forward is not a fudge: outside market hours the
    previous session's movers ARE the current answer, and enriched_at rides
    along so the age is always auditable.

    The read (audit #54, 2026-10-08): _fetch returns [] when Yahoo raises or
    throttles a batch to an empty frame, so one throttled run published the
    sector board, index list and summary BLANK under a fresh generated_at.
    A fresh read that is missing its sectors or indices is now replaced by the
    previous file's read when that one is more complete (``_read_rank``; a tie
    keeps the fresh one), whole, so the summary always matches the lists shown.
    ``read_at`` rides along (falling back to the previous file's generated_at
    only for a file published before the stamp existed; a carried null stays
    null), so a carried read is never presented as fresher than it is.
    """
    moved = 0
    prev_at = prev.get("generated_at")
    for key, m in (sec.get("markets") or {}).items():
        old = ((prev.get("markets") or {}).get(key) or {})
        for k in ENRICHED_KEYS:
            if k not in m and k in old:
                m[k] = old[k]
                moved += 1
        if _read_rank(old) > _read_rank(m):
            for k in READ_KEYS:
                if k in old:
                    m[k] = old[k]
                    moved += 1
            if "read_at" not in old:
                # A file from before the stamp fetched its read with the file.
                # An explicit null (age unknown) stays null on every later
                # carry: a later file's generated_at would date it falsely.
                m["read_at"] = prev_at   # None = age unknown, never "now"
    return moved


def _num(s):
    """Pull a float out of a ForexFactory value like '3.2%', '-0.1%', '187K', '5.50%'."""
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    mult = 1.0
    if s[-1:] in "KkMmBb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1].lower()]
        s = s[:-1]
    s = s.rstrip("%")
    try:
        return float(s) * mult
    except ValueError:
        return None


# Events where a HOTTER number (actual > forecast) means a hawkish / higher-for-longer
# read for rates, and a COOLER number means dovish. (Growth/jobs are read the same way:
# hotter data => the Fed can stay tighter.)
_HAWKISH_IF_HOT = ("CPI", "PPI", "INFLATION", "PRICE INDEX", "RATE DECISION", "FUNDS RATE",
                   "CASH RATE", "EMPLOYMENT", "PAYROLL", "NONFARM", "WAGE", "EARNINGS", "GDP",
                   "RETAIL SALES", "PMI", "ISM")


def _tone(title, actual, forecast):
    """Plain, data-derived hawkish/dovish read from actual vs forecast (no sentiment)."""
    if actual is None or forecast is None:
        return None, None
    t = title.upper()
    hot_is_hawk = any(k in t for k in _HAWKISH_IF_HOT)
    # unemployment rate is inverted (higher = weaker labour market = dovish)
    if "UNEMPLOYMENT" in t:
        hot_is_hawk = False
    diff = actual - forecast
    if abs(diff) < 1e-9:
        return "in line with forecast", "neutral"
    higher = diff > 0
    surprise = "higher than expected" if higher else "lower than expected"
    tone = ("hawkish" if higher else "dovish") if hot_is_hawk else ("dovish" if higher else "hawkish")
    return surprise, tone


def _calendar():
    """High/medium-impact events per market: upcoming, plus the latest released
    high-impact result with a data-derived hawkish/dovish read."""
    upcoming = {"us": [], "asx": []}
    recent = {"us": [], "asx": []}
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now - dt.timedelta(days=4)
    syd = ZoneInfo("Australia/Sydney")
    seen = set()
    for url in FF_URLS:
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            root = ET.fromstring(urllib.request.urlopen(req, timeout=25).read())
        except Exception:
            continue
        for e in root.findall("event"):
            impact = (e.findtext("impact") or "").strip()
            country = (e.findtext("country") or "").strip()
            if impact not in ("High", "Medium"):
                continue
            mkey = "us" if country == "USD" else "asx" if country == "AUD" else None
            if not mkey:
                continue
            title = (e.findtext("title") or "").strip()
            ds = (e.findtext("date") or "").strip()
            ts = (e.findtext("time") or "").strip()
            try:
                day = dt.datetime.strptime(ds, "%m-%d-%Y").date()
                if ts[:1].isdigit():
                    t = dt.datetime.strptime(ts, "%I:%M%p").time()
                    when = dt.datetime.combine(day, t, tzinfo=dt.timezone.utc)
                    timed = True
                else:
                    when = dt.datetime.combine(day, dt.time(23, 59), tzinfo=dt.timezone.utc)
                    timed = False
            except Exception:
                continue
            key = (mkey, title, ds, ts)
            if key in seen:
                continue
            seen.add(key)
            forecast = (e.findtext("forecast") or "").strip()
            previous = (e.findtext("previous") or "").strip()
            actual = (e.findtext("actual") or "").strip()

            if when >= now:
                loc = when.astimezone(syd)
                date_lbl = f"{loc.strftime('%a')} {loc.day} {loc.strftime('%b')}"
                hr = loc.hour % 12 or 12
                time_lbl = f"{hr}:{loc.minute:02d}{'am' if loc.hour < 12 else 'pm'}" if timed else ""
                upcoming[mkey].append({"date": date_lbl, "time": time_lbl, "title": title,
                                       "impact": impact, "forecast": forecast,
                                       "previous": previous, "when": when.isoformat(),
                                       "_s": when.isoformat()})
            elif impact == "High" and when >= horizon and actual:
                surprise, tone = _tone(title, _num(actual), _num(forecast))
                loc = when.astimezone(syd)
                recent[mkey].append({"title": title, "actual": actual, "forecast": forecast,
                                     "previous": previous, "surprise": surprise, "tone": tone,
                                     "when_lbl": f"{loc.strftime('%a')} {loc.day} {loc.strftime('%b')}",
                                     "_s": when.isoformat()})
    for k in upcoming:
        upcoming[k].sort(key=lambda x: x["_s"])
        upcoming[k] = upcoming[k][:7]
        for ev in upcoming[k]:
            ev.pop("_s", None)
    latest = {}
    for k in recent:
        recent[k].sort(key=lambda x: x["_s"], reverse=True)
        latest[k] = recent[k][0] if recent[k] else None
        if latest[k]:
            latest[k].pop("_s", None)
    return {"upcoming": upcoming, "latest": latest}


def fetch() -> dict:
    cal = _calendar()
    markets = {}
    for key, label, idx_rows, sec_rows in [
        ("asx", "ASX", ASX_INDICES, ASX_SECTORS),
        ("us", "US", US_INDICES, US_SECTORS),
    ]:
        indices = _fetch(idx_rows)
        sectors = _fetch(sec_rows)
        summary, rotation = _read(label, sectors, indices)
        markets[key] = {"label": label, "indices": indices, "sectors": sectors,
                        "summary": summary, "rotation": rotation,
                        # when THIS read was fetched; carry_forward keeps the
                        # previous read's stamp if it replaces an empty one
                        "read_at": dt.datetime.now(dt.timezone.utc).isoformat(
                            timespec="seconds"),
                        "upcoming": cal["upcoming"].get(key, []),
                        "latest_event": cal["latest"].get(key)}

    now = dt.datetime.now(ZoneInfo("Australia/Sydney"))
    # The abbreviation at THIS instant: AEDT in summer, AEST in winter (it was
    # a literal "AEST" all year until 2026-10-05).
    return {"generated_at": now.isoformat(timespec="seconds"), "tz_label": now.tzname(),
            "markets": markets}

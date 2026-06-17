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
               "See the calendar & news below for the events behind it.")
    leaders = ", ".join(f"{s['symbol']} ({s['chg_pct']:+.1f}%)" for s in ranked[:3])
    laggards = ", ".join(f"{s['symbol']} ({s['chg_pct']:+.1f}%)" for s in ranked[-3:][::-1])
    rotation = (f"Money rotated INTO {leaders} and OUT OF {laggards}. "
                + ("Cyclicals/growth leading — appetite for risk."
                   if risk_on else "Defensives & gold leading — a cautious, risk-off lean."))
    return summary, rotation


def _calendar():
    """Upcoming high/medium-impact events per market from the ForexFactory feed."""
    out = {"us": [], "asx": []}
    now = dt.datetime.now(dt.timezone.utc)
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
            if when < now:
                continue
            key = (mkey, title, ds, ts)
            if key in seen:
                continue
            seen.add(key)
            loc = when.astimezone(syd)
            date_lbl = f"{loc.strftime('%a')} {loc.day} {loc.strftime('%b')}"
            hr = loc.hour % 12 or 12
            time_lbl = f"{hr}:{loc.minute:02d}{'am' if loc.hour < 12 else 'pm'}" if timed else ""
            out[mkey].append({"date": date_lbl, "time": time_lbl, "title": title,
                              "impact": impact, "forecast": (e.findtext("forecast") or "").strip(),
                              "previous": (e.findtext("previous") or "").strip(),
                              "_s": when.isoformat()})
    for k in out:
        out[k].sort(key=lambda x: x["_s"])
        out[k] = out[k][:7]
        for ev in out[k]:
            ev.pop("_s", None)
    return out


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
                        "upcoming": cal.get(key, [])}

    now = dt.datetime.now(ZoneInfo("Australia/Sydney"))
    return {"generated_at": now.isoformat(timespec="seconds"), "tz_label": "AEST",
            "markets": markets}

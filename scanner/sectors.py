"""Sector & index dashboard (ASX + US) with an auto, data-derived market read.

Fetches the major indices and the 11 GICS sectors for each market, then writes a
plain-English "what happened" summary and a "money rotation" read — purely from
the moves (no social/AI). Written to public/data/sectors.json.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import yfinance as yf

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


def fetch() -> dict:
    markets = {}
    for key, label, idx_rows, sec_rows in [
        ("asx", "ASX", ASX_INDICES, ASX_SECTORS),
        ("us", "US", US_INDICES, US_SECTORS),
    ]:
        indices = _fetch(idx_rows)
        sectors = _fetch(sec_rows)
        summary, rotation = _read(label, sectors, indices)
        markets[key] = {"label": label, "indices": indices, "sectors": sectors,
                        "summary": summary, "rotation": rotation}

    now = dt.datetime.now(ZoneInfo("Australia/Sydney"))
    return {"generated_at": now.isoformat(timespec="seconds"), "tz_label": "AEST",
            "markets": markets}

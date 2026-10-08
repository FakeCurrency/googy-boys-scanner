"""Market cap on every IGNITION row -- DISPLAY only (owner, 2026-09-30: "I need
a MARKET cap on each box"). Stamped after the screen sorts, so a cap can never
move a row, a state or a count; nothing in the engine or the replay reads it.

Row keys: mcap (the market's own currency: A$ asx, US$ nasdaq and crypto), mcap_asof
("YYYY-MM-DD") and mcap_src ("coingecko" | "yahoo" | "cache" | "previous"), each
None when unknown. The shared cap cache is READ only: scan.yml's marketcaps step
is its one writer.
"""

import datetime as dt
import json
import math

from scanner import marketcaps


def _positive(x):
    """x as a float when it is a real positive number, else None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 < x < math.inf:
        return None
    return float(x)


def _add(caps, symbol, value, asof, src):
    """File a usable, dated cap under `symbol` unless a newer one is there."""
    value = _positive(value)
    try:
        asof = dt.date.fromisoformat(str(asof)[:10]).isoformat()
    except ValueError:
        return
    if symbol and value and (symbol not in caps or asof > caps[symbol]["asof"]):
        caps[symbol] = {"mcap": value, "asof": asof, "src": src}


def _is_old(entry, now):
    """Missing, or past the age at which the shared cache itself re-fetches."""
    return entry is None or (
        (now.date() - dt.date.fromisoformat(entry["asof"])).days > marketcaps.MAX_AGE_DAYS)


def _previous_rows(path):
    """The lens's last published rows; [] on a first run or an unreadable file."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("results") or []
    except Exception:                                     # noqa: BLE001
        return []


def known(market, prev_path, now):
    """{symbol: entry} for a stock market (crypto: {}): the newest of the shared cache
    and the previous file. Yahoo is asked once, for previous-file names with no
    recent cap -- today's rows are nearly all there, as a trigger needs a recent
    coil. Call it BEFORE the frame download: Yahoo throttles after it."""
    caps = {}
    if market == "crypto":
        return caps
    try:
        for key, e in marketcaps.load_cache().items():
            if key.startswith(market + ":"):
                _add(caps, key.split(":", 1)[1], e.get("mcap"), e.get("ts"), "cache")
        rows = _previous_rows(prev_path)
        for r in rows:
            _add(caps, r.get("symbol"), r.get("mcap"), r.get("mcap_asof"), "previous")
        want = {r["yf"]: r["symbol"] for r in rows if _is_old(caps.get(r["symbol"]), now)}
        if want:
            got = marketcaps.fetch_caps(sorted(want))
            print(f"ignition: market caps - Yahoo asked {len(want)}, got {len(got)}", flush=True)
            for yf, cap in got.items():
                _add(caps, want.get(yf), cap, now.date(), "yahoo")
    except Exception as exc:                  # noqa: BLE001 - a cap is never worth a failed run
        msg = str(exc).encode("ascii", "replace").decode("ascii")[:120]
        print(f"ignition: market caps incomplete ({type(exc).__name__}: {msg})", flush=True)
    return caps


def stamp(market, results, rows, caps, today):
    """Write the three keys on every result row, in place; return the summary
    block. Crypto reads the universe rows' cg_mcap (undated when the universe is
    an outage-day snapshot, cg_stale); a stock market reads `caps` from known()."""
    if market == "crypto":
        caps = {r.get("symbol"): {"mcap": r.get("cg_mcap"), "src": "coingecko",
                                  "asof": None if r.get("cg_stale") else today} for r in rows}
    for r in results:
        cap = caps.get(r["symbol"]) or {}
        value = _positive(cap.get("mcap"))
        r["mcap"] = value
        r["mcap_asof"] = cap.get("asof") if value else None
        r["mcap_src"] = cap.get("src") if value else None
    have = sum(1 for r in results if r["mcap"])
    print(f"ignition: market cap on {have}/{len(results)} rows", flush=True)
    return {"rows": len(results), "have": have}

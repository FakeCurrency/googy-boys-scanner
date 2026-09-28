"""Yahoo vs exchange klines, side by side, for the crypto universe (2026-09-28).

The owner asked to move the VIVEK crypto scan and the paper bot off Yahoo
onto Binance/Bybit "so it's all in SYNC". This measures, FROM A GITHUB RUNNER,
everything that switch changes, before it is trusted:

  * which venues answer at all (Binance and Bybit geo-block US IPs, and
    GitHub's hosted runners are US-based -- measured, not assumed)
  * the last COMPLETED bar each source has right now (Yahoo was a day behind
    at 02:00 UTC on 28 Sep)
  * how far each coin's last close sits from Yahoo's (the jump the bot's
    marks take on the day of the switch)
  * how many coins clear the $3M 20-day liquidity floor on each source's
    volume (one exchange's volume is smaller than Yahoo's aggregate)

Read-only: prints a report (Markdown-friendly) and writes nothing.
    python scripts/crypto_source_compare.py [--limit N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanner import config, exchange_data, universe  # noqa: E402
from scanner import data as sdata  # noqa: E402


def _completed(df, today):
    df = df[df.index.normalize() < np.datetime64(today)] if len(df) else df
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    rows = universe.load_universe("crypto")
    if args.limit:
        rows = rows[:args.limit]
    today = dt.datetime.now(dt.timezone.utc).date()
    print(f"## Crypto source comparison - {len(rows)} coins - {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC\n")

    print("### Venue reachability (BTC, first page only)\n")
    for src in config.EXCHANGE_KLINE_SOURCES:
        try:
            df = exchange_data._fetch_one(src, "BTC", 5, float(config.EXCHANGE_HTTP_TIMEOUT))
            last = df.index[-1].date() if df is not None and len(df) else None
            print(f"- {src}: OK ({0 if df is None else len(df)} bars, last {last})")
        except exchange_data.SourceDead as e:
            print(f"- {src}: REFUSED ({e})")
        except Exception as e:  # noqa: BLE001 - a report, not a gate
            print(f"- {src}: ERROR {type(e).__name__}: {str(e)[:100]}")

    ex, rep = exchange_data.download_klines([r["symbol"] for r in rows], days=60)
    yf = sdata.download([r["yf"] for r in rows], period="3mo")
    print(f"\n### Coverage\n\n- exchange: {len(ex)} coins {rep['by_source']}; dead {rep['dead']}")
    print(f"- yahoo: {len(yf)} coins")
    both = [r for r in rows if str(r["symbol"]).upper() in ex and r["yf"] in yf]
    print(f"- on both: {len(both)}; exchange only: "
          f"{sum(1 for r in rows if str(r['symbol']).upper() in ex and r['yf'] not in yf)}; "
          f"yahoo only: {sum(1 for r in rows if str(r['symbol']).upper() not in ex and r['yf'] in yf)}")

    def last_done(d):
        c = _completed(d, today)
        return str(c.index[-1].date()) if len(c) else None

    ex_last = [last_done(ex[str(r["symbol"]).upper()]) for r in both]
    yf_last = [last_done(yf[r["yf"]]) for r in both]
    y = str(today - dt.timedelta(days=1))
    print(f"\n### Freshness (expected last completed bar: {y})\n")
    print(f"- exchange: {sum(1 for d in ex_last if d == y)}/{len(both)} have it")
    print(f"- yahoo:    {sum(1 for d in yf_last if d == y)}/{len(both)} have it")

    diffs, floor_ex, floor_yf = [], 0, 0
    floor = float(config.MARKETS["crypto"].liquidity_min)
    worst = []
    for r in both:
        e = _completed(ex[str(r["symbol"]).upper()], today)
        f = _completed(yf[r["yf"]], today)
        if not len(e) or not len(f):
            continue
        common = e.index.intersection(f.index)
        if len(common):
            d = common[-1]
            pct = (float(e.loc[d, "Close"]) / float(f.loc[d, "Close"]) - 1) * 100
            diffs.append(pct)
            worst.append((abs(pct), r["symbol"], round(pct, 2), str(d.date())))
        if float(e["Volume"].tail(20).mean()) >= floor:
            floor_ex += 1
        if float(f["Volume"].tail(20).mean()) >= floor:
            floor_yf += 1
    if diffs:
        a = np.abs(np.array(diffs))
        print("\n### Close vs Yahoo on the same completed day (exchange / yahoo - 1)\n")
        print(f"- median |diff| {np.median(a):.2f}%, 90th pct {np.percentile(a, 90):.2f}%, "
              f"max {a.max():.2f}% over {len(a)} coins")
        print("- largest: " + ", ".join(f"{s} {p:+}% ({d})" for _, s, p, d in sorted(worst, reverse=True)[:8]))
    print(f"\n### 20-day turnover >= ${floor:,.0f} (the crypto liquidity floor)\n")
    print(f"- exchange volume: {floor_ex}/{len(both)} coins")
    print(f"- yahoo volume:    {floor_yf}/{len(both)} coins")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

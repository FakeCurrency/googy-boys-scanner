"""A DRY VIVEK crypto scan on exchange klines, compared with the published one.

The owner switched the VIVEK crypto scan and the paper bot from Yahoo to
exchange data (2026-09-28: "so it's all in SYNC"). crypto_bot.yml cannot be
dispatched from a feature branch safely -- its commit step pushes to main --
so this runs the REAL scan (data.fetch -> scan.scan_vivek_market, including
the exchange 4h candles for the 4H plans) on a runner and writes NOTHING:
prev-grade hysteresis reads a temp COPY of the committed crypto_vivek.json and
the scan's side file lands in that temp dir. No bot, no book, no publish.

It prints what the switch changes: where the bars came from, which coins the
identity check refused, how fresh the bars are, which setups appear /
disappear / change grade versus the published Yahoo scan, the HIGH
CONVICTION and bot-considerable counts, and the open book's marks on the new
source.

    python scripts/crypto_scan_dryrun.py
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanner import config, conviction, data, scan, universe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public" / "data"


def _rows(payload):
    return {r["symbol"]: r for r in (payload or {}).get("results") or []}


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    uni = universe.load_universe("crypto")
    print(f"## Dry VIVEK crypto scan on exchange klines - {len(uni)} coins - {now:%Y-%m-%d %H:%M} UTC\n")
    frames, rep = data.fetch("crypto", [u["yf"] for u in uni], period=config.VIVEK_DATA_PERIOD,
                             ref_prices={u["yf"]: u.get("cg_price") for u in uni})
    s = data.source_summary(rep)
    print(f"- sources: {s['by_source']}")
    print(f"- refused the runner: {s['dead']}")
    print(f"- identity check rejected (source -> not this coin): {s['identity_rejected']}")
    print(f"- no exchange lists: {len(s['no_exchange'])}; Yahoo fallback: {s['yahoo_fallback']}")
    done = {}
    for yf, f in frames.items():
        if len(f):
            last = f.index[-1].date()
            done[yf] = str(last if last < now.date() else f.index[-2].date() if len(f) > 1 else last)
    y = str(now.date() - dt.timedelta(days=1))
    print(f"- last completed bar = {y}: {sum(1 for d in done.values() if d == y)}/{len(done)}")

    committed = PUB / "crypto_vivek.json"
    before = json.loads(committed.read_text(encoding="utf-8")) if committed.exists() else {}
    with tempfile.TemporaryDirectory() as tmp:
        if committed.exists():
            shutil.copy(committed, Path(tmp) / "crypto_vivek.json")
        vk = scan.scan_vivek_market("crypto", universe=uni, frames=frames,
                                    out_root=tmp, progress=False)
    after = vk
    b, a = _rows(before), _rows(after)

    def summary(rows):
        grades = {}
        for r in rows.values():
            grades[r.get("grade")] = grades.get(r.get("grade"), 0) + 1
        hc = sum(1 for r in rows.values() if conviction.is_high_conviction(r))
        allow = tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW or ())
        bot = sum(1 for r in rows.values()
                  if r.get("grade_raw") in config.VIVEK_BOT_GRADES
                  and (not allow or r.get("level_tf") in allow)
                  and str(r.get("dir", "")).upper() == "LONG")
        return grades, hc, bot

    gb, hb, bb = summary(b)
    ga, ha, ba = summary(a)
    print("\n### Setups: published (Yahoo) vs dry (exchange)\n")
    print(f"- rows {len(b)} -> {len(a)}; grades {gb} -> {ga}")
    print(f"- HIGH CONVICTION {hb} -> {ha}; bot-considerable (A/A+ long at a weekly/3d level) {bb} -> {ba}")
    new = sorted(set(a) - set(b))
    gone = sorted(set(b) - set(a))
    moved = sorted(s for s in set(a) & set(b) if a[s].get("grade") != b[s].get("grade"))

    def g(rows, sym):
        return rows[sym].get("grade")

    print("- new: " + (", ".join(f"{x} {g(a, x)}" for x in new) or "-"))
    print("- gone: " + (", ".join(f"{x} {g(b, x)}" for x in gone) or "-"))
    print("- regraded: " + (", ".join(f"{x} {g(b, x)}->{g(a, x)}" for x in moved) or "-"))
    h4 = sum(1 for r in a.values() if (r.get("plans") or {}).get("4H"))
    print(f"- rows with a real 4H plan (exchange 4h candles): {h4}/{len(a)}")
    print(f"- funnel: {json.dumps(after.get('funnel', {}))[:400]}")

    book = ROOT / "journal" / "vivek_bot_book.crypto.json"
    if book.exists():
        bk = json.loads(book.read_text(encoding="utf-8"))
        print("\n### Open crypto book marked on the new source\n")
        for p in bk.get("open") or []:
            f = frames.get(p["symbol"] + config.MARKETS["crypto"].suffix)
            px = float(f["Close"].iloc[-1]) if f is not None and len(f) else None
            lm = p.get("last_mark")
            gap = (px / lm - 1) * 100 if px and lm else None
            print(f"- {p['symbol']}: last mark {lm} -> exchange {px} "
                  f"({'n/a' if gap is None else f'{gap:+.2f}%'}), stop {p.get('stop')}, "
                  f"source {rep['source_of'].get(p['symbol'] + config.MARKETS['crypto'].suffix, 'none')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

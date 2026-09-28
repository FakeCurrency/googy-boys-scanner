"""DRY momentum + PhaseMap crypto runs: exchange klines vs the old Yahoo path.

Both lenses moved their crypto bars onto `scanner.data.fetch` on 2026-09-28
(exchange daily klines first, every source held to CoinGecko's price for the
coin -- Yahoo's AERO/JUP/ARB/PRL/SKY/XCN/EDGE/MET were different tokens;
PhaseMap's move is the owner's "Move to exchange"). Their workflows commit to
main, so they cannot be dispatched from a feature branch. This runs each
lens's REAL code on a runner TWICE, at the same moment, on the same universe:

  * NEW -- the shipped path (data.fetch with cg_price / phasemap.run's
    make_provider -> FetchProvider)
  * OLD -- the pre-switch path (data.download / YFinanceProvider without the
    identity check), recomputed NOW so the comparison is like-for-like (the
    published momentum crypto file was screened on the old 86-coin universe,
    so it is not a fair baseline)

and prints what changes: where the bars came from, which coins the identity
check refused, how many Yahoo-path results were a DIFFERENT TOKEN, which
results appear / disappear, and -- the number the owner asked for -- how many
coins clear momentum's crypto turnover floor on one exchange's volume versus
Yahoo's aggregate.

WRITES NOTHING to the repo: momentum's screen is handed its frames (so no
frame cache is read or saved), PhaseMap writes into temp dirs, and the
universe is fetched ONCE and shared (CoinGecko's free tier rate-limits).

    python scripts/crypto_lens_dryrun.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import statistics
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanner import config, data, exchange_data, universe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = config.MARKETS["crypto"].suffix


def _base(yf: str) -> str:
    return yf[:-len(SUFFIX)] if SUFFIX and yf.endswith(SUFFIX) else yf


def _list(xs, n=40) -> str:
    xs = list(xs)
    return (", ".join(xs[:n]) + (f" ... (+{len(xs) - n})" if len(xs) > n else "")) or "-"


def _bucket(reason: str) -> str:
    """Gate reasons carry per-coin numbers ("turnover 3622139 below ...");
    strip them so the counts group."""
    return re.sub(r"\s+", " ", re.sub(r"[-+]?\d[\d.,]*", "N", reason.split(" (")[0])).strip()


def _share_universe():
    """Fetch the crypto universe ONCE and hand the same rows to every caller
    (momentum, and PhaseMap's load_symbols twice) -- three CoinGecko walks in
    a minute is how a free-tier 429 turns into a cached, older universe."""
    real = universe.load_universe
    memo = {}

    def load(market_key, full=True):
        if market_key not in memo:
            memo[market_key] = real(market_key, full=full)
        return [dict(r) for r in memo[market_key]]

    universe.load_universe = load
    return load


def momentum_section(rows, strangers) -> None:
    from scanner.momentum import config as MC
    from scanner.momentum import gates as MG
    from scanner.momentum import run as MR

    yfs = [r["yf"] for r in rows]
    refs = {r["yf"]: r.get("cg_price") for r in rows}
    floor = float(MC.MIN_DOLLAR_ADV.get("crypto", 0.0))
    print(f"\n## MOMENTUM crypto - {len(rows)} coins, {MC.DATA_PERIOD} daily\n")

    ex, rep = data.fetch("crypto", yfs, period=MC.DATA_PERIOD, interval="1d", ref_prices=refs)
    yh = data.download(yfs, period=MC.DATA_PERIOD)
    new = MR.screen_market("crypto", rows=[dict(r) for r in rows], frames=dict(ex))
    old = MR.screen_market("crypto", rows=[dict(r) for r in rows], frames=dict(yh))
    if new is None or old is None:
        print(f"- a path returned NO DATA (exchange frames {len(ex)}, Yahoo frames {len(yh)})")
        return
    MR.tag_sources(new, "crypto", rep)
    ds = new["data_sources"]
    print(f"- NEW sources: {ds['by_source']}; refused the runner: {ds['dead']}; "
          f"Yahoo fallback {ds['yahoo_fallback']}")
    left_out = [k + " (" + "/".join(v) + ")" for k, v in ds["identity_rejected"].items()]
    print(f"- NEW identity check left out {len(left_out)}: {_list(left_out)}")
    print(f"- coverage (frames): OLD {len(yh)} -> NEW {len(ex)} of {len(rows)}")

    # --- the turnover floor: one venue's volume vs Yahoo's aggregate --------
    def adv(frames):
        return {yf: MG.dollar_adv(f, "crypto") for yf, f in frames.items()}

    ae, ay = adv(ex), adv(yh)
    same = [yf for yf in ae if yf in ay and _base(yf) not in strangers
            and ae[yf] and ay[yf]]
    clear_e = {yf for yf, v in ae.items() if v is not None and v >= floor}
    clear_y = {yf for yf, v in ay.items() if v is not None and v >= floor and _base(yf) not in strangers}
    print(f"\n### Turnover floor ${floor:,.0f} (20d average)\n")
    print(f"- clear the floor: OLD (Yahoo aggregate, real coins only) {len(clear_y)} -> "
          f"NEW (exchange) {len(clear_e)}")
    lost = sorted(_base(y) for y in clear_y - clear_e if y in ae)
    gained = sorted(_base(y) for y in clear_e - clear_y)
    print(f"- lose the floor on exchange volume ({len(lost)}): {_list(lost)}")
    print(f"- newly clear it ({len(gained)}): {_list(gained)}")
    if same:
        ratios = sorted(ae[y] / ay[y] for y in same)
        print(f"- exchange/Yahoo turnover, same coin (n={len(ratios)}): median "
              f"{statistics.median(ratios):.2f}x, 25th pct {ratios[len(ratios) // 4]:.2f}x, "
              f"75th pct {ratios[(3 * len(ratios)) // 4]:.2f}x")
    for pct in (0.6, 0.4):
        alt = floor * pct
        n = sum(1 for v in ae.values() if v is not None and v >= alt)
        print(f"- for scale only (NOT a proposal): {n} clear ${alt:,.0f} on exchange volume")

    # --- gates + results ------------------------------------------------------
    def gate_counts(frames):
        out = {}
        for yf, f in frames.items():
            meta = next((r for r in rows if r["yf"] == yf), {})
            reason = MG.gate_frame(f, "crypto", name=meta.get("name"), sector=meta.get("sector"))
            key = _bucket(reason) if reason else "passes the gates"
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    print("\n### Gates\n")
    print(f"- OLD: {gate_counts(yh)}")
    print(f"- NEW: {gate_counts(ex)}")
    so, sn = old["summary"], new["summary"]
    print(f"- screened {so['scanned']} -> {sn['scanned']}; stale frames {so['stale_frames']} -> "
          f"{sn['stale_frames']}; hits {so['hits']} -> {sn['hits']}")

    def hits(p):
        return {r["symbol"]: ("A" if r.get("rule_a") else "") + ("B" if r.get("rule_b") else "")
                for r in p["results"]}

    ho, hn = hits(old), hits(new)
    wrong = sorted(s for s in ho if s in strangers)
    print(f"- OLD hits that were a DIFFERENT TOKEN: {_list(wrong)}")
    new_hits = [f"{r['symbol']} [{hn[r['symbol']]}] via {r.get('data_source')}"
                for r in new["results"]]
    print(f"- NEW hits ({len(hn)}): {_list(new_hits)}")
    print(f"- appear: {_list(sorted(set(hn) - set(ho)))}")
    print(f"- disappear: {_list(sorted(set(ho) - set(hn)))}")


def phasemap_section(strangers) -> None:
    from phasemap import run as PMR
    from phasemap.data.provider import YFinanceProvider

    run_date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    args = types.SimpleNamespace(tickers=None, limit=None, period="2y")
    print("\n## PHASEMAP crypto - 2y daily\n")
    with tempfile.TemporaryDirectory() as t_new, tempfile.TemporaryDirectory() as t_old:
        PMR.run_market("crypto", args, run_date, t_new)
        shipped = PMR.make_provider
        # the pre-switch path exactly: Yahoo, no identity check
        PMR.make_provider = lambda m, s, p: YFinanceProvider(
            {t: i["yf"] for t, i in s.items()}, period=p)
        try:
            PMR.run_market("crypto", args, run_date, t_old)
        finally:
            PMR.make_provider = shipped
        new = json.loads((Path(t_new) / "crypto" / "latest.json").read_text(encoding="utf-8"))
        old = json.loads((Path(t_old) / "crypto" / "latest.json").read_text(encoding="utf-8"))

    ds = new.get("data_sources") or {}
    print(f"- NEW sources: {ds.get('by_source')}; refused the runner: {ds.get('dead')}; "
          f"Yahoo fallback {ds.get('yahoo_fallback')}")
    left_out = [k + " (" + "/".join(v) + ")" for k, v in (new.get("identity_rejected") or {}).items()]
    print(f"- NEW identity check left out {len(left_out)}: {_list(left_out)}")

    def keyed(p):
        return {(r["ticker"], r["direction"]): r for r in p["results"]}

    ko, kn = keyed(old), keyed(new)

    def tally(rows, field):
        out = {}
        for r in rows.values():
            out[r.get(field)] = out.get(r.get(field), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: str(kv[0])))

    print(f"- results {len(ko)} -> {len(kn)}; tiers {tally(ko, 'tier')} -> {tally(kn, 'tier')}")
    print(f"- states {tally(ko, 'state')} -> {tally(kn, 'state')}")
    ill_o = sum(1 for r in ko.values() if "ILLIQUID" in (r.get("tags") or []))
    ill_n = sum(1 for r in kn.values() if "ILLIQUID" in (r.get("tags") or []))
    print(f"- ILLIQUID tag (a warning, never a filter): {ill_o} -> {ill_n}")
    wrong = sorted(f"{t} {d} {ko[(t, d)].get('tier')}" for (t, d) in ko if t in strangers)
    print(f"- OLD results on a DIFFERENT TOKEN: {_list(wrong)}")
    fmt = lambda rows, k: f"{k[0]} {k[1]} {rows[k].get('tier')}/{rows[k].get('state')}"  # noqa: E731
    print(f"- appear: {_list(sorted(fmt(kn, k) for k in set(kn) - set(ko)))}")
    print(f"- disappear: {_list(sorted(fmt(ko, k) for k in set(ko) - set(kn)))}")
    moved = sorted(k for k in set(kn) & set(ko)
                   if (kn[k].get("tier"), kn[k].get("state")) != (ko[k].get("tier"), ko[k].get("state")))
    changed = [f"{k[0]} {k[1]} {fmt(ko, k).split(' ', 2)[2]} -> {fmt(kn, k).split(' ', 2)[2]}"
               for k in moved]
    print(f"- changed tier/state: {_list(changed)}")
    graded = lambda rows: sorted(f"{k[0]} {k[1]}" for k, r in rows.items() if r.get("tier") in ("A+", "A"))  # noqa: E731
    print(f"- A+/A OLD: {_list(graded(ko))}")
    print(f"- A+/A NEW: {_list(graded(kn))}")
    src = {}
    for r in kn.values():
        src[r.get("data_source")] = src.get(r.get("data_source"), 0) + 1
    print(f"- NEW rows by data_source: {src}")


def main() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    load = _share_universe()
    rows = load("crypto")
    print(f"# Dry momentum + PhaseMap crypto: exchange vs Yahoo - {len(rows)} coins - "
          f"{now:%Y-%m-%d %H:%M} UTC")
    missing_ref = sorted(r["symbol"] for r in rows if not r.get("cg_price"))
    print(f"\n- coins with no CoinGecko reference price (unchecked everywhere): {_list(missing_ref)}")

    # Which Yahoo <SYM>-USD series are a different token, measured once and
    # used to label the OLD path's results in both sections.
    yh = data.download([r["yf"] for r in rows], period="1mo")
    refs = {r["yf"]: r.get("cg_price") for r in rows}
    strangers = {_base(yf) for yf, f in yh.items() if not exchange_data.same_coin(f, refs.get(yf))}
    print(f"- Yahoo series that are a DIFFERENT TOKEN from the CoinGecko coin "
          f"({len(strangers)}): {_list(sorted(strangers))}")

    for name, section in (("momentum", lambda: momentum_section(rows, strangers)),
                          ("phasemap", lambda: phasemap_section(strangers))):
        try:
            section()
        except Exception as e:  # noqa: BLE001 - one section failing must not hide the other
            print(f"\n- {name} section FAILED: {type(e).__name__}: {str(e)[:300]}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

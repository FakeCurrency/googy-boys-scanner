"""TURTLE lens runner — publishes public/data/<market>_turtle.json.

    python -m scanner.turtle_run                  # asx + nasdaq + crypto
    python -m scanner.turtle_run --market asx
    python -m scanner.turtle_run --limit 200      # quick local pass

Runs nightly (turtle.yml), OFF the 30-minute hot path and outside the `scan`
concurrency group: it writes only its own files and reads nothing the scan
writes. Crypto IS included here, unlike the Specs lens — Specs excludes it
because SPEC_MAX_PRICE is a cents filter with no meaning for coins, whereas
every Turtle parameter is expressed in N and is unit-free by construction.

Five years of daily bars by default. The System 1 filter needs enough history
to have seen prior breakouts resolve, and the per-name record the page ranks
on is only worth reading over a span that contains more than one regime.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import zoneinfo

from . import (config, data, output, scanerrors, turtle, turtle_book,
               turtle_portfolio, universe)

MARKETS = ("asx", "nasdaq", "crypto", "futures")
PERIOD = "5y"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "public", "data")


def _with_date_column(df):
    """data.download frames carry the date in a DatetimeIndex — normalise to a
    'Date' column so the engine can label trades uniformly. Same helper as
    spec_run's, kept local rather than shared: the two lenses are deliberately
    independent and a shared private helper is how a coupling starts."""
    if "Date" in df.columns:
        return df
    out = df.reset_index()
    if "Date" not in out.columns:
        out = out.rename(columns={out.columns[0]: "Date"})
    return out


def params_block() -> dict:
    """Every parameter the engine ran with, published beside the results.

    Not decoration. The page states rule numbers in prose and a reader has no
    way to tell whether the prose describes the code — so the code publishes
    its own constants and the page renders THOSE, which makes a drift between
    the two impossible rather than merely unlikely.
    """
    c = config
    return {
        "n_period": c.TURTLE_N_PERIOD,
        "s1_entry": c.TURTLE_S1_ENTRY, "s1_exit": c.TURTLE_S1_EXIT,
        "s2_entry": c.TURTLE_S2_ENTRY, "s2_exit": c.TURTLE_S2_EXIT,
        "stop_n": c.TURTLE_STOP_N,
        "pyramid_step_n": c.TURTLE_PYRAMID_STEP_N,
        "max_units": c.TURTLE_MAX_UNITS,
        "risk_pct": c.TURTLE_RISK_PCT,
        "max_units_close_corr": c.TURTLE_MAX_UNITS_CLOSE_CORR,
        "max_units_loose_corr": c.TURTLE_MAX_UNITS_LOOSE_CORR,
        "max_units_direction": c.TURTLE_MAX_UNITS_DIRECTION,
        "drawdown_step_pct": c.TURTLE_DRAWDOWN_STEP_PCT,
        "drawdown_cut_pct": c.TURTLE_DRAWDOWN_CUT_PCT,
        "whipsaw_risk_pct": c.TURTLE_WHIPSAW_RISK_PCT,
        "whipsaw_stop_n": c.TURTLE_WHIPSAW_STOP_N,
        "account_equity": c.TURTLE_ACCOUNT_EQUITY,
        "allow_shorts": c.TURTLE_ALLOW_SHORTS,
        "min_bars": c.TURTLE_MIN_BARS,
        "approach_pct": c.TURTLE_APPROACH_PCT,
        "min_coverage_pct": c.TURTLE_MIN_COVERAGE_PCT,
        "small_universe_max": c.TURTLE_SMALL_UNIVERSE_MAX,
        "small_universe_max_missing": c.TURTLE_SMALL_UNIVERSE_MAX_MISSING,
        "period": PERIOD,
    }


def override_frames(items: list[dict], period: str = PERIOD) -> dict:
    """Frames for the collision-corrected crypto names, keyed by the PLAIN
    symbol. One small fetch (five tickers at most); a failure returns {} and
    is logged rather than raised -- the 5x surfaces degrade to the corrected
    names being absent, never to a dead run."""
    over = config.TURTLE_5X_YF_OVERRIDES
    in_univ = {it["symbol"]: it for it in items if it["symbol"] in over}
    if not in_univ:
        return {}
    fetch = {over[sym]: info for sym, info in in_univ.items()}
    try:
        frames = data.download(list(fetch), period=period, interval="1d")
    except Exception as e:                                       # noqa: BLE001
        print(f"[crypto5x] WARNING override fetch failed: "
              f"{e.__class__.__name__}: {e}")
        return {}
    out = {}
    for yf_sym, info in fetch.items():
        df = frames.get(yf_sym)
        if df is None or df.empty or len(df) < config.TURTLE_MIN_BARS:
            continue
        out[info["symbol"]] = _with_date_column(df)
    return out


def five_x_rows(rows: list[dict], items: list[dict],
                period: str = PERIOD, ov_frames: dict | None = None
                ) -> list[dict]:
    """The crypto 5x sleeve's rows: the SAME universe, Yahoo collisions
    corrected, junk prices rejected.

    config.TURTLE_5X_YF_OVERRIDES names the CoinGecko tickers whose naive
    "<SYM>-USD" mapping lands on a DIFFERENT, dead Yahoo token (bare APT-USD
    is Apricot, not Aptos). Those names are dropped from the cash scan's rows
    and re-fetched under their real Yahoo ids; the row still displays the
    plain symbol. THE CASH UNIVERSE IS DELIBERATELY UNTOUCHED -- the cash
    crypto book is a running experiment and editing its universe mid-flight
    changes which trades it takes. Any row whose last close is not a positive
    number is rejected outright.
    """
    over = config.TURTLE_5X_YF_OVERRIDES
    out = [r for r in rows
           if r["symbol"] not in over and (r.get("price") or 0) > 0]
    if ov_frames is None:
        ov_frames = override_frames(items, period=period)
    infos = {it["symbol"]: it for it in items}
    for sym, df in ov_frames.items():
        info = infos.get(sym, {"symbol": sym, "name": sym, "sector": ""})
        try:
            r = turtle.build_row(sym, dict(info, yf=over.get(sym, "")),
                                 df, "crypto")
        except Exception as e:                                   # noqa: BLE001
            print(f"[crypto5x] WARNING {sym}: {e.__class__.__name__}: {e}")
            continue
        if r is not None and (r.get("price") or 0) > 0:
            out.append(r)
    return out


def fit_table(rows: list[dict], equity: float | None = None) -> list[dict]:
    """The futures sleeve's sizing verdicts, one row per contract, at the
    book's own equity -- the table that answers "what can $5,000 actually
    hold" without anyone doing the division by hand.

    Fits-first ordering so the tradeable micros (MES/MNQ-class) lead and the
    full-size contracts that CANNOT fit a $5k unit sit below them wearing
    their refusal. Nothing here rounds up: 0.4 of a contract is a refusal,
    not "1". `two_n_risk_smallest` is what one contract of the smallest
    available size loses at its own 2N stop, in dollars -- the number that
    explains WHY the refusal protects the account.
    """
    # TURTLE_ACCOUNT_EQUITY because that is the equity contract_sizing()
    # computed the per-row verdicts against -- the stamped equity must name
    # the number the verdicts actually used, not a sibling constant.
    eq = config.TURTLE_ACCOUNT_EQUITY if equity is None else equity
    out = []
    for r in rows:
        c = r.get("contracts") or {}
        n = r.get("n")
        small_dpp = c.get("micro_dpp") or c.get("dpp") or 0
        out.append({
            "symbol": r["symbol"], "name": r.get("name", ""),
            "group": r.get("group", ""),
            "n": n,
            "dpp": c.get("dpp"),
            "micro": c.get("micro") or "",
            "micro_dpp": c.get("micro_dpp") or 0,
            "full_contracts": c.get("full_contracts"),
            "micro_contracts": c.get("micro_contracts"),
            "unit_fits": bool(c.get("unit_fits")),
            "two_n_risk_smallest": (round(2.0 * n * small_dpp, 2)
                                    if (n and small_dpp) else None),
            "one_contract_risk_pct": c.get("one_contract_risk_pct"),
            "roll_in_n_window": bool((r.get("rolls") or {}).get("in_n_window")),
            "equity": eq,
        })
    out.sort(key=lambda x: (not x["unit_fits"], not x["micro"], x["symbol"]))
    return out


def aggregate(rows: list[dict]) -> dict:
    """What the whole market did under these rules, and the cohort counts.

    The aggregate record is the honest headline: one flattering name proves
    nothing, and the page's per-name table invites exactly that error. Summed
    across the market it is a wide, in-sample, survivor-biased number — the
    payload says so and the page repeats it.
    """
    trades = sum((r["record"]["n"] for r in rows), 0)
    total_r = sum((r["record"]["total_r"] for r in rows), 0.0)
    gross_r = sum((r["record"].get("gross_r", 0.0) for r in rows), 0.0)
    cost_r = sum((r["record"].get("cost_r", 0.0) for r in rows), 0.0)
    wins = sum((r["record"]["wins"] for r in rows), 0)
    with_trades = [r for r in rows if r["record"]["n"]]
    return {
        "names": len(rows),
        "names_with_trades": len(with_trades),
        "trades": trades,
        "wins": wins,
        "win_pct": round(100.0 * wins / trades, 1) if trades else None,
        "total_r": round(total_r, 2),
        "gross_r": round(gross_r, 2),
        "cost_r": round(cost_r, 2),
        "avg_r": round(total_r / trades, 4) if trades else None,
        "avg_gross_r": round(gross_r / trades, 4) if trades else None,
        "long": sum(1 for r in rows if r["state"] == "long"),
        "short": sum(1 for r in rows if r["state"] == "short"),
        "flat": sum(1 for r in rows if r["state"] == "flat"),
        "fired_today": sum(1 for r in rows if r.get("signal")),
        "added_today": sum(1 for r in rows if r.get("added_today")),
        "approaching": sum(1 for r in rows if r.get("approaching")),
        "s1_blocked": sum(1 for r in rows if r.get("s1_blocked")),
    }


def scan_market(market_key: str, limit: int | None = None,
                period: str = PERIOD, equity: float | None = None,
                portfolio: bool = False) -> dict:
    if market_key == "futures":
        # The sleeve is a declared list, not a directory fetch: these are the
        # markets the Turtles actually traded, and the point of the sleeve is
        # that it is FIXED and uncorrelated rather than whatever a screen
        # returns today. No survivorship, because nothing was selected.
        cur = "$"
        items = [dict(f) for f in config.TURTLE_FUTURES]
    else:
        mk = config.MARKETS[market_key]
        cur = getattr(mk, "currency_symbol", "$")
        items = universe.load_universe(market_key, full=True)
    if limit:
        items = items[:limit]
    yf_map = {it["yf"]: it for it in items}
    frames = data.download(list(yf_map), period=period, interval="1d")

    rows: list[dict] = []
    errors = scanerrors.ErrorLog(f"turtle [{market_key}]")
    skipped_short = skipped_illiquid = skipped_no_data = 0
    no_data_syms: list[str] = []
    # ITERATE THE UNIVERSE, NOT THE DOWNLOAD (2026-08-21 incident). Walking
    # `frames` made every name Yahoo failed to return INVISIBLE BY
    # CONSTRUCTION: it was never in the dict, so the loop never saw it, no
    # counter moved and no error was recorded. On 2026-08-21 a scheduled run
    # got 5 of 101 crypto names back, evaluated ONE of them, and published
    # `errors: 0`. Walking yf_map means a name that did not come back is
    # counted rather than absent.
    for yf_sym, info in yf_map.items():
        df = frames.get(yf_sym)
        if df is None or df.empty:
            skipped_no_data += 1
            no_data_syms.append(info.get("symbol", yf_sym))
            continue
        if len(df) < config.TURTLE_MIN_BARS:
            skipped_short += 1
            continue
        df = _with_date_column(df)
        sym = info.get("symbol", yf_sym)
        try:
            row = turtle.build_row(sym, info, df, market_key, equity=equity)
        except Exception as e:
            # One bad frame never kills the scan, and never does it silently:
            # a name that throws every night is otherwise indistinguishable
            # from a name that simply never breaks out (TOP100 #66).
            errors.record(sym, e)
            continue
        if row is None:
            skipped_illiquid += 1
            continue
        rows.append(row)

    rows.sort(key=turtle.rank_key)
    published = rows[:config.TURTLE_MAX_ROWS]
    # Report against the UNIVERSE. Reporting against len(frames) meant a run
    # that got 5 names back and threw on none of them printed a flawless 0/5.
    errors.report(len(yf_map))

    # THE COVERAGE FLOOR. A fresh file holding one name is indistinguishable
    # from a fresh file holding forty-seven to anything that only checks age,
    # which is every watchdog this repo has. So the run refuses to publish
    # over a good file with a gutted one: same discipline as assert_staged.sh,
    # applied to content instead of to staging.
    covered = len(yf_map) - skipped_no_data
    cover_pct = 100.0 * covered / len(yf_map) if yf_map else 0.0
    # A SMALL universe (the 21-contract futures sleeve) gets an ABSOLUTE
    # ceiling on missing names, because a 60% share was chosen for 2,000-name
    # directories and passes 13-of-21 (62%) — a sleeve missing whole asset
    # groups published as if it were whole. The share floor still applies
    # underneath; the tighter rule wins. Missing names are NAMED, not merely
    # counted: on a fixed table each absence is a market group.
    small = 0 < len(yf_map) <= config.TURTLE_SMALL_UNIVERSE_MAX
    if small and skipped_no_data > config.TURTLE_SMALL_UNIVERSE_MAX_MISSING:
        raise RuntimeError(
            f"[{market_key}] turtle: {skipped_no_data} of {len(yf_map)} names "
            f"returned no usable bars ({', '.join(sorted(no_data_syms))}) - a "
            f"universe this small allows at most "
            f"{config.TURTLE_SMALL_UNIVERSE_MAX_MISSING} missing, REFUSING to "
            f"publish. Yesterday's file is better than a gutted one; re-run "
            f"rather than lowering the floor."
        )
    if yf_map and cover_pct < config.TURTLE_MIN_COVERAGE_PCT:
        raise RuntimeError(
            f"[{market_key}] turtle: data coverage {cover_pct:.1f}% "
            f"({covered} of {len(yf_map)} names returned usable bars) is below "
            f"the {config.TURTLE_MIN_COVERAGE_PCT}% floor - REFUSING to publish. "
            f"Yesterday's file is better than a gutted one. This is almost "
            f"always upstream throttling; re-run rather than lowering the floor."
        )

    tz = zoneinfo.ZoneInfo("Australia/Melbourne")
    payload = {
        "generated_at": datetime.datetime.now(tz).isoformat(timespec="seconds"),
        "market": market_key,
        "lens": "turtle",
        "currency_symbol": cur,
        "universe_size": len(items),
        "evaluated": len(rows),
        "skipped_no_data": skipped_no_data,
        # Named only for small universes: on the 21-contract sleeve each
        # missing name is an asset group; on a 2,000-name directory the list
        # would be hundreds of lines of Yahoo throttle noise.
        "skipped_no_data_symbols": sorted(no_data_syms) if small else [],
        "data_coverage_pct": round(cover_pct, 1),
        "skipped_short_history": skipped_short,
        "skipped_illiquid": skipped_illiquid,
        "truncated": max(0, len(rows) - len(published)),
        "params": params_block(),
        "aggregate": aggregate(rows),
        "results": published,
        **errors.payload(),
    }
    if market_key == "futures":
        # The sizing verdicts as one table, so "what can $5k actually hold"
        # is a payload fact rather than a hand computation. The page renders
        # THIS -- fits first, refusals wearing their reasons.
        payload["fit_table"] = fit_table(rows, equity=equity)
    path = os.path.join(OUT_DIR, f"{market_key}_turtle.json")
    output.write_json(path, payload, indent=1, ensure_ascii=False, newline=True)
    agg = payload["aggregate"]
    print(f"[{market_key}] turtle: coverage {cover_pct:.1f}% "
          f"({covered}/{len(yf_map)} priced, {skipped_no_data} no data)")
    if small and no_data_syms:
        print(f"[{market_key}] turtle: unpriced this run: "
              f"{', '.join(sorted(no_data_syms))}")
    print(f"[{market_key}] turtle: {len(rows)} names "
          f"({agg['long']}L/{agg['short']}S/{agg['flat']}F, "
          f"{agg['fired_today']} fired, {agg['approaching']} approaching) "
          f"from {len(items)} in universe -> {path}")
    print(f"[{market_key}] turtle record (in-sample, {period}): "
          f"{agg['trades']} trades, {agg['win_pct']}% win, "
          f"{agg['total_r']}R total, {agg['avg_r']}R average")

    # THE FORWARD BOOK. Advanced from the rows we just published, on the same
    # download, because the honest test of this thesis is the one that starts
    # today and cannot have chosen its universe on outcomes it does not know.
    # It never blocks the publish: a book failure must not cost the scan.
    try:
        b = turtle_book.update(market_key, rows)
        bs = b["summary"]
        print(f"[{market_key}] turtle BOOK (forward, since {bs['started']}): "
              f"{bs['open_positions']} open / {bs['open_units']} units, "
              f"{bs['closed']} closed, {bs['total_r']}R, "
              f"equity {bs['equity']} of {bs['equity_start']}")
    except Exception as e:                                       # noqa: BLE001
        print(f"[{market_key}] WARNING turtle book update failed: "
              f"{e.__class__.__name__}: {e}")

    # THE 5x SLEEVE rides the crypto scan: same universe with the Yahoo
    # collisions corrected, same frozen rules, posted margin instead of full
    # cash. A NEW series beside the cash book, never a restatement of it --
    # and its failure must not cost the cash publish, same as above.
    ov = override_frames(items, period=period) if market_key == "crypto" else {}
    if market_key == "crypto":
        try:
            rows5x = five_x_rows(rows, items, period=period, ov_frames=ov)
            b5 = turtle_book.update(config.TURTLE_5X["market"], rows5x)
            bs5 = b5["summary"]
            print(f"[crypto5x] turtle BOOK (forward 5x, since "
                  f"{bs5['started']}): {bs5['open_positions']} open / "
                  f"{bs5['open_units']} units, {bs5['closed']} closed, "
                  f"{bs5['total_r']}R, equity {bs5['equity']} of "
                  f"{bs5['equity_start']}, posted {bs5.get('posted_margin')} "
                  f"free {bs5.get('free_margin')}")
        except Exception as e:                                   # noqa: BLE001
            print(f"[crypto5x] WARNING turtle 5x book update failed: "
                  f"{e.__class__.__name__}: {e}")

    # THE PORTFOLIO REPLAY -- the shared-equity context surface, computed on
    # the nightly all-markets pass only (--portfolio) because it is a full
    # second walk of every frame. Report-only, merge-per-sleeve, and a
    # failure must never cost the scan or the books.
    if portfolio:
        try:
            sym_frames = {}
            for yf_sym2, info2 in yf_map.items():
                df2 = frames.get(yf_sym2)
                if df2 is not None and not df2.empty \
                        and len(df2) >= config.TURTLE_MIN_BARS:
                    sym_frames[info2.get("symbol", yf_sym2)] = \
                        _with_date_column(df2)
            sleeves: dict[str, dict] = {}
            # ASX retired from the TURTLE replay (owner, 2026-08-23): it was the
            # single-factor control sleeve, dropped along with ASX everywhere in
            # this lens. The stale asx_5k_cash was also removed from the published
            # payload by hand (write_sleeves merges and never drops a sibling on
            # its own, so stopping generation here is not enough on its own).
            if market_key == "nasdaq":
                # NDX proxy, DECLARED as such: top 100 by trailing 20-day
                # dollar volume as of this run -- survivor-selected like
                # everything Yahoo ships. Two equities, one truth: $5k
                # cash-skips its way through what $100k can actually hold.
                def _dv(df3):
                    s = (df3["Close"] * df3["Volume"]).iloc[-20:]
                    return float(s.mean()) if len(s) else 0.0
                top = dict(sorted(sym_frames.items(),
                                  key=lambda kv: -_dv(kv[1]))[:100])
                sleeves["nasdaq100_5k_cash"] = turtle_portfolio.replay_sleeve(
                    top, market="nasdaq", equity_start=5000.0)
                sleeves["nasdaq100_100k_cash"] = \
                    turtle_portfolio.replay_sleeve(
                        top, market="nasdaq", equity_start=100_000.0)
            elif market_key == "crypto":
                c5 = {s: f for s, f in sym_frames.items()
                      if s not in config.TURTLE_5X_YF_OVERRIDES}
                c5.update(ov)
                sleeves["crypto_5x_5k"] = turtle_portfolio.replay_sleeve(
                    c5, market="crypto", equity_start=5000.0,
                    leverage=float(config.TURTLE_5X["leverage"]))
            elif market_key == "futures":
                contracts = {f["symbol"]: f for f in config.TURTLE_FUTURES}
                sleeves["futures21_5k"] = turtle_portfolio.replay_sleeve(
                    sym_frames, market="futures", equity_start=5000.0,
                    contracts=contracts,
                    margins=turtle_book._load_margin_file())
            if sleeves:
                turtle_portfolio.write_sleeves(sleeves)
                for k, v in sleeves.items():
                    print(f"[{k}] portfolio: {v['trades']} trades, "
                          f"marked {v['equity_marked']} "
                          f"({v['return_pct_marked']}%), "
                          f"maxDD {v['max_dd_pct_marked']}%, "
                          f"refused {v['refused_units']}")
        except Exception as e:                                   # noqa: BLE001
            print(f"[{market_key}] WARNING portfolio replay failed: "
                  f"{e.__class__.__name__}: {e}")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="turtle scanner")
    ap.add_argument("--market", default="all", help="asx | nasdaq | crypto | all")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--period", default=PERIOD)
    ap.add_argument("--equity", type=float,
                    help="account size the published unit sizes are computed "
                         "against (default config.TURTLE_ACCOUNT_EQUITY)")
    ap.add_argument("--portfolio", action="store_true",
                    help="also run the shared-equity portfolio replay per "
                         "sleeve (the nightly all-markets pass sets this)")
    args = ap.parse_args(argv)
    markets = MARKETS if args.market == "all" else tuple(args.market.split(","))
    for m in markets:
        if m not in MARKETS:
            print(f"unknown/unsupported market: {m}")
            return 2
    failed = []
    for m in markets:
        try:
            scan_market(m, limit=args.limit, period=args.period,
                        equity=args.equity, portfolio=args.portfolio)
        except Exception as e:                                   # noqa: BLE001
            # TOP100 #67: a market that fails ENTIRELY used to print one line
            # and exit 0, so a night with no ASX file at all looked like a
            # night with no ASX breakouts.
            failed.append(m)
            print(f"[{m}] turtle scan FAILED: {e.__class__.__name__}: {e}")
    # ONE SECOND CHANCE, after a real cooldown (2026-09-01 -- runs #64/#88).
    # The dominant failure here is Yahoo throttling one market's batch under
    # the coverage floor, and a throttle window clears in minutes; the
    # per-batch retries above it are seconds apart, inside the same window.
    # Only the failed market(s) are re-scanned, once. A retry that still
    # fails keeps the red run -- the floor's alarm is untouched, only its
    # false-positive rate on transients.
    cooldown = float(getattr(config, "TURTLE_THROTTLE_RETRY_COOLDOWN_S", 0) or 0)
    if failed and cooldown > 0:
        print(f"turtle: retrying {len(failed)} failed market(s) once after "
              f"{cooldown:.0f}s cooldown: {', '.join(failed)}")
        time.sleep(cooldown)
        still_failed = []
        for m in failed:
            try:
                scan_market(m, limit=args.limit, period=args.period,
                            equity=args.equity, portfolio=args.portfolio)
                print(f"[{m}] turtle retry OK - the first failure was a transient")
            except Exception as e:                               # noqa: BLE001
                still_failed.append(m)
                print(f"[{m}] turtle retry FAILED: {e.__class__.__name__}: {e}")
        failed = still_failed
    # The derived combined book, regenerated from whatever per-market files
    # exist. Report-only, and it must never take the scan down with it.
    try:
        turtle_book.write_combined()
    except Exception as e:                                       # noqa: BLE001
        print(f"turtle: WARNING combined book failed: {e.__class__.__name__}: {e}")
    if failed:
        print(f"turtle: {len(failed)} market(s) failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

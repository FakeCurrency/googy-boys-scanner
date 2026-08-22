# Turtle money-UI pass — Phase A verification

Read-only phase except the rebase itself. Nothing below is trusted from the incoming brief without an independent check against the actual repo.

## origin/main — one correction to the brief

The brief named `origin/main = 116bb4f`. At fetch time the true tip was **one commit further**, `80ef86b6a657acc26d28fd8c520f88e911d31e2e` ("journal: manual close x1 - ZUMZ"). Diffstat confirms it's unrelated to Turtle — `journal/vivek_bot_book.json`, `journal/vivek_bot_book.nasdaq.json`, `public/data/vivek_bot_book.json` only, bot-authored, a different scanner's paper book entirely. `116bb4f` itself (`data: turtle 2026-08-22`, 12:55 UTC) touches only `journal/turtle_book.{crypto,crypto5x,}.json` and `public/data/{crypto_turtle,turtle_book}.json`. Neither commit touches any file this branch has ever touched, so the rebase was a clean fast-forward-style replay with **zero conflicts** — no journal/ "take theirs" decision was actually needed, no turtle.js conflict either.

Rebased onto `80ef86b` (the true tip, not the brief's `116bb4f` — rebasing onto the older SHA would have left the ZUMZ commit unmerged for no reason). Post-rebase: `git merge-base HEAD origin/main` == `origin/main` == `80ef86b`, confirmed ancestor, working tree clean. All 9 commits replayed with new SHAs; `git diff <old-tip> HEAD -- public/js/turtle.js public/css/turtle.css public/turtle.html test/turtle.test.js public/version.json` is empty — byte-identical content, pure history rewrite.

## Live payload — every claim in the brief checked against the actual JSON, not assumed

| Claim | Checked | Result |
|---|---|---|
| crypto5x: 6 opens/6 units, all long | `journal/turtle_book.crypto5x.json` | Exact match: ZEC/BCH/DASH/UNI/NEAR/WLD, 1 fill each |
| posted_margin 1159.76 / free_margin 3840.24 | same file, `summary` | Exact match |
| Systems: ZEC S2, BCH S2, DASH S2, UNI S1, NEAR S2, WLD S2 | same file, `open[]` | Exact match |
| 12 skips, all close_corr_cap, cap=6, bucket=crypto | same file, `skips[]`/`skip_counts` | Exact match — 6 "add" (on held names), 6 "entry" (DOT/FIL/ATOM/ONDO/XLM/APT) |
| params.leverage=5, margin_mode=isolated | same file, `params` | Exact match, plus `cost_bps: 15.0`, `fractional: true` |
| UNI is the Yahoo-override path | `scanner/config.py` `TURTLE_5X_YF_OVERRIDES` | Confirmed: `"UNI": "UNI7083-USD"` (bare UNI-USD is UNICORN) |
| NEAR is real, not the NRBY fixture | `journal/turtle_book.crypto5x.json` | Confirmed — literal `NEAR` in `open[]` |
| by_market keys: asx/nasdaq/crypto/crypto5x/futures (5) | `journal/turtle_book.json` | Exact match |
| equity_start 25000 / equity 24186.1 | same file, `summary` | Exact match |
| skip_counts: cash 70, close_corr_cap 12, per_market_cap 1, total 83 | same file | Exact match |
| Cash crypto 2026-08-21 closed rows byte-stable vs `af7c795` | `journal/turtle_book.crypto.json`, dict-equality vs the `9adda79` blob | 5/5 identical (BCH, AAVE, XRP, ETC, ADA) — still true after rebase |
| Futures still 0/0 | `journal/turtle_book.futures.json` | Confirmed, unchanged |

Nothing in the brief's description of the live state was wrong. The only miss was the stale `origin/main` SHA, corrected above.

## Code claims — file:line, post-rebase (line numbers unchanged; file is byte-identical)

- `parseTurtleURL` / `serialiseTurtleURL` — `turtle.js:1308`, `:1337`
- `onPopState` never calls push/replace — `turtle.js:1401-1406`, confirmed by re-read
- `data-view` scoped to `#tt-views`, not document-wide — `turtle.js:1466`: `e.target.closest("#tt-views [data-view]")`
- `FILTER` default fired, fallthrough held→all — `URL_DEFAULTS.f = "fired"` (`:1296`), fallthrough logic `:148-151`
- Deck pills are `<button data-filter>` — `turtle.js:204`, `:211`
- `chartHref`: null for futures, real link otherwise — `turtle.js:467-470`
- BOOK opens-first, `#tt-skips` present, N from `by_market` — `:985` (`id="tt-skips"`), `:933`/`:1034` (`mk.length`)
- No fetch of `crypto5x_turtle.json` — grep clean
- No hardcoded "5×"/sleeve count — grep clean, confirmed again this phase

## Live click-path check (real Chromium, local static serve, this session)

Ran fresh against the post-rebase file (not reused from last night), since a live render can catch what static analysis can't:

- Empty URL → FIRED pill `is-active: true`; first paint replaces URL to `?m=asx&v=signals&f=fired&sort=fired`.
- Deep link `?m=crypto&v=book` → active market button is `crypto`, page renders `Open positions / Closed, most recent first / By market` in that order.
- Click ASX→CRYPTO, then browser Back → URL and active button both revert to `asx`. Real history, not a re-implementation risk.
- Futures SIGNALS row expanded → no `chart.html` link in the detail; note reads "no chart for this contract." No 404 risk.

All four live and correct.

## Display-honesty item (brief's DO 5) — checked, not assumed broken

The brief warned: if BOOK/SIGNALS labels a coin quantity as Turtle units ("1.27u" for ZEC meaning units, when it's really coin quantity), that's a lie. Traced every `.units` reference in `turtle.js` against both source schemas:

- `scanner/turtle.py` (SIGNALS payload, `r.position`): `units` is a literal unit **counter**, `1` on first fill, `+= 1` per add, capped at `max_units` (`turtle.py:362`, `:429`, `:501`). `stateChip()` (`turtle.js:449`, "2u · S2") and the held-row detail (`turtle.js:691`, "Units held: 2 of 4") read `r.position.units` — correct, because in this schema `units` genuinely means unit count.
- `scanner/turtle_book.py` (BOOK payload, `BOOK.open[]`): `units` is real coin/contract quantity (UNI: 213.66, ZEC: 1.27). The two places `turtle.js` renders a BOOK position's unit count — `posRow()` (`turtle.js:880`, `(p.fills || []).length + "u"`) and `bookOpenHTML()` (`turtle.js:544`, `kv("Units", (p.fills || []).length)`) — **already use `fills.length`, not `p.units`**. Neither currently mislabels a coin quantity as a unit count.

**Conclusion: the specific failure mode described in the brief does not exist in the shipped code.** What's actually missing is not a fix but a *feature*: BOOK's open-positions table has no visible coin-quantity column at all today — the correct `fills.length` "u" is shown, but the actual position size (1.27 ZEC, 213.66 UNI) is nowhere on that table, only recoverable by dividing `cost_basis` by an unlabelled number in the expanded SIGNALS detail. Phase C's job here is therefore: add an explicit, clearly-labelled quantity column, keep the existing (already correct) unit count, and add a regression test pinning both — not a bugfix.

## Gate

```
node --check public/js/turtle.js                                    OK
node test/turtle.test.js                                             134 passed, 0 failed
python -m pytest tests/test_turtle.py tests/test_turtle_book.py \
  tests/test_turtle_portfolio.py tests/test_version_stamp.py -q      exit 0, clean
sha256sum journal/turtle_book*.json == /tmp/JOURNAL_SHA_AFTER_REBASE  match (see file)
```

No false claim found in the brief (beyond the stale origin/main SHA, which is a staleness artefact of when Grok looked, not an error). **No fix commit needed this phase.** Proceeding to Phase B.

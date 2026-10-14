# Design note — the "liquidity arriving" list

*2026-07-29. Design only — no code exists for this. Implements the rule you
approved in principle, inside the boundaries you set: report-only, fenced,
floor untouched, no promotion into any lens, no bot visibility, no sizing.*

## Output location and schema

**A separate file per market** — `public/data/<market>_arriving.json` — not a
key inside the scan payload. This is the load-bearing isolation choice: the
paper bot's entire input surface is the `results` array of
`<market>_vivek.json` (handed to it by `vivek_run`), so a list that lives in
a file nothing in `scanner/broker/` ever opens cannot reach the bot by
construction rather than by discipline. Secondary benefits: the main payload
(already on a diet plan) gains zero bytes, and the deck fetches it lazily
only when the funnel disclosure is opened.

```json
{
  "schema_version": 1,
  "market": "asx",
  "generated_at": "2026-07-29T16:47:57+10:00",
  "rule": {
    "floor": 100000,
    "min_rvol": 3.0,
    "note": "today's turnover alone >= floor AND today's volume >= min_rvol x own 20d avg; report-only, never traded"
  },
  "results": [
    {
      "symbol": "DUN",
      "name": "…",
      "sector": "…",
      "dir": "LONG",
      "price": 0.0,
      "turnover_avg20": 19945,
      "turnover_today": 191472,
      "rvol": 9.6,
      "adv_usd": 19945,
      "fund": false
    }
  ]
}
```

Field notes: `turnover_today` is exact `Close × Volume` of the last completed
bar (the sample's version approximates it as `avg × rvol`; the real
implementation computes it directly, and the entry test uses the exact
value). `adv_usd` is carried even though the bot never sees the file — the
brief's fail-open note made it a standing rule that any thin row anywhere
carries it. `fund` uses the same scanner-side FUND/REIT detection the bot's
`EXCLUDE_FUNDS` rule uses, so notes/ETF-shaped tickers (28BB, IHEB) arrive
pre-tagged. List capped at a config constant (`SCAN_ARRIVING_MAX = 12`,
rule-3 placed), sorted by `turnover_today` descending — the participation
number, not the multiple, because the multiple alone is the pump signature.

Constants `min_rvol` (3.0) and the floor are **echoed from the existing
config values, never redefined** — the floor constant stays the single
source; this file cannot drift from it.

## How it stays invisible to the bot — four fences, each testable

1. **Different file.** `vivek_bot`/`vivek_run` read rows only from the scan
   payload's `results`. Nothing in `scanner/broker/` opens `*_arriving.json`
   — pinned by a test that walks `scanner/broker/` sources and fails if the
   string `arriving` appears.
2. **`results` byte-identity.** A pipeline test runs the scan with and
   without arriving-qualified names present and asserts the published
   `results` array is identical either way — the list is computed *from the
   drop path*, after the `continue`, so a qualifying name is still dropped
   from the scan exactly as today.
3. **Funnel accounting unchanged.** Qualifying names still count in
   `illiquid_setup` (they were killed; the list just says who), so the
   funnel's identity arithmetic — already test-pinned — would catch any
   accidental re-routing of a thin name into the graded path.
4. **No grades, no plans.** The rows carry no `grade`, `grade_raw`, `plans`,
   or `entry` fields at all, so even a hypothetical future mis-wire into a
   bot path fails the bot's own field requirements (`grade_raw`/plan gates)
   rather than trading.

The UI surface is the existing funnel disclosure on the deck: the line gains
"· N with liquidity arriving" and the expanded body lists the rows as the
same tap-to-chart chips the sample uses today — chart links only, no plan,
no star-into-bot pathway.

## The 16:48 scan through this rule — actual output

Of the 299 floor-kills, the 12-name sample resolves to exactly **4 entries**
(everything below the sample shows ≤5.8× and none of the eight dust names
clears the floor on the day):

| symbol | dir | turnover_avg20 | turnover_today | rvol | would publish? |
|---|---|---|---|---|---|
| BFL | LONG | A$62,866 | ~A$421,202 | 6.7 | yes |
| IHEB | LONG | A$55,082 | ~A$319,476 | 5.8 | yes |
| DUN | LONG | A$19,945 | ~A$191,472 | 9.6 | yes |
| ALPH | LONG | A$27,997 | ~A$176,381 | 6.3 | yes |
| OCA | SHORT | A$2,749 | ~A$51,681 | 18.8 | **no — today still under floor** |
| TRA | SHORT | A$511 | ~A$9,402 | 18.4 | **no — 18× of dust** |

OCA and TRA are shown deliberately: they are the pump-signature rows the
two-leg test exists to exclude, and they are what an rvol-only rule would
have published.

## What this does NOT do (restating your boundaries as commitments)

The existing floor value and its 20-day-average test are byte-untouched.
Nothing is promoted into Specs, VIVEK results, or PhaseMap. No bot code, no
sizing, no grades, no gates change. If the list is ever empty, the file
publishes with `results: []` (present-and-empty, per the house rule that
absent and empty are different claims). Estimated shape when green-lit:
~40 lines in scan.py at the existing drop point, one config constant, one
scan.yml staging path per market, ~15 lines of funnel-UI extension, and the
four fence tests above. Awaiting your review — no code until then.

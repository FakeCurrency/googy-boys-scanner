---
name: port-ignition
description: Port the IGNITION coil -> breakout lens to another stock market (a market the scanner already covers, or a brand-new one like NYSE, TSX or LSE) and ship it end to end - per-market settings with reasons, the workflow twin, tests, the deck or Ignition page, the first replay, PR and merge. Use this whenever someone asks for Ignition on a market that doesn't have it ("why isn't there an IGNITION for X?", "add TSX to ignition", "can we screen NYSE for coils", "port the coil lens to LSE", "get ignition running on <market>"), even if they never say "port".
---

# Port IGNITION to another market

IGNITION (`scanner/ignition/`, CLAUDE.md "IGNITION") screens a market for a
months-long quiet base (the coil) followed by a close out of it on heavy
volume (the trigger). It is REPORT-ONLY: never traded, never in confluence,
fenced away from `scanner/broker/`. It runs on crypto, the ASX (ported
2026-09-29, commit `aad51559`) and NASDAQ (2026-10-08, commits `6898d686` +
`f1e3e04f`). A port is the same rule with the same thresholds on another
market. That means only per-market values change, `IGNITION_RULESET_VERSION`
stays put, and the existing markets' output stays byte-identical.

The owner's standing rules for a port:

- **You pick the per-market settings and ship.** Choose each value by the
  reasoning the ASX and NASDAQ ports used, write that reasoning into the
  config comment and the PR, and merge when CI is green (CLAUDE.md rule 8:
  rebase-merge, no need to ask). Do not stop to ask for numbers.
- **If the scanner doesn't cover the market yet, add it.** That means the
  stock list, timezone, currency, session and data feed, as an
  IGNITION-ONLY market (see "New market" below). Stop only if no free,
  official stock list exists; then report why and ship nothing.
- **Report the replay honestly.** The lens ships whatever the replay says.
  NASDAQ showed no edge over random timing and still shipped, labelled as
  such. Never round a borderline result into a good one.

## Decide the case first

```bash
python3 -c "from scanner import config; print('MARKETS', list(config.MARKETS)); print('IGNITION', config.IGNITION_MARKETS)"
```

- **Already in `IGNITION_MARKETS`:** nothing to port. Say so, and point at
  the panel.
- **In `config.MARKETS` but not `IGNITION_MARKETS`:** a plain port. Follow
  `references/recipe.md` from Part 1.
- **In neither:** a NEW market. Do `references/new-market.md` first (stock
  list and stop rule, the Ignition-only registry, the Ignition page, chart
  links). Then do the recipe.

Never add a new market to `config.MARKETS`. That dict is the registry for
the VIVEK scan and the paper bot. `scanner/run.py --market all`,
`vivek_run`, `kill_switch`, `watchdog` and `vivek_backtest` all loop over
it. A new key there would start scanning, and could start trading, a market
nobody approved. Putting a market on VIVEK or the bot changes trades, so it
is the owner's decision, not a port step.

## The work, in order

1. **Branch.** Use the session's designated branch. Run CLAUDE.md rule 1's
   `git stash -u; git pull --rebase origin main; git stash pop` first.
2. **Settings.** Choose every per-market value with `references/settings.md`.
   Each value gets a one-line reason in the config comment. Define them all
   BEFORE the first replay: they are pre-registered, and changing them after
   seeing results is curve-fitting.
3. **Code.** Work through `references/recipe.md` Parts 1–7: config, lens
   code (mostly generic already), the backstop gate, the workflow twin and
   kick file, the frontend, tests, CLAUDE.md. The recipe is the
   checklist. Missing one item is how the past ports went wrong.
4. **Verify locally.** Run recipe "Verify locally". The full pytest takes
   about 6 minutes, so give it `timeout: 600000`. Load the
   `run-googy-boys-scanner` skill to look at the panel in a browser. This
   container cannot reach Yahoo, so the real screen only runs on GitHub.
5. **Review before pushing.** The NASDAQ port's adversarial review found 7
   real defects after its tests were green, including the 16:00 bell vs
   bar-final gap. Run `/code-review` (or a reviewer agent) on the diff and
   fix what holds up.
6. **Push with the kick file.** The push runs the first screen and the full
   replay on the branch, and the bot commits `<m>.json`, `<m>_charts.json`
   and `<m>_backtest.json` back to it (20–45 min). Open the PR.
7. **Read the replay** (recipe "First replay"). Pull the bot commit with
   `git pull --rebase`. Never force-push over it: that drops the data AND
   re-fires the kick. Look at the panel with the real file, and write the
   verdict into CLAUDE.md and the PR.
8. **Merge when green.** "Green" means the checks on YOUR last commit. The
   bot's data commit shows CI "action_required" because GitHub runs no CI
   on bot pushes; that is not a failure. Rebase-merge. The merge carries the
   kick file to main, which runs the replay once more there; that is
   expected.
9. **Confirm on main.** Check that the three files land on main and that
   the panel or page shows the market.

## What to tell the owner

Put this summary in your FINAL reply, not only in a file: a report file
may not be writable, and the reply is what he reads. He reads it on his
phone. Plain words, no jargon, no file paths in the first lines. Every
number in it comes from a run you made: real test counts from the pytest
and node output, real screened counts from the workflow log. Never leave a
template placeholder (`<n>`, `TBD`, "~N tests") in the reply, the PR body
or CLAUDE.md; if a number isn't known yet (the replay hasn't run), say so
in words.

- What is now live and where to see it ("NYSE now has an Ignition page:
  MORE → IGNITION → NYSE").
- How many names were screened, and what is coiling or igniting right now.
- The replay verdict in one honest sentence, set against crypto (+1.15R
  over random timing) and the other ports. Example: "On NYSE history the
  rule did no better than random timing (+0.03R, P 0.4), so treat it as a
  watch-list, not a signal."
- Anything you chose that he might want to change: the universe scope, the
  turnover floors, and the market cap gap on the first run.

## Pitfalls the past ports actually hit

- **Silent fall-through to crypto's values.** Every per-market lookup falls
  back to crypto when a key is missing. NASDAQ ran end to end on crypto's
  3-day age, 0.30 cost, $1M trigger, QNT design case and BTC regime, with no
  error. The fences test `test_every_market_has_an_explicit_entry_in_every_per_market_setting`
  catches the config dicts. It does NOT catch `COST_WHY` / `UNIVERSE_WHY`
  text, JS `CAP_CCY` / `WF_NAME`, or the session, so check those by hand.
- **Caveat text leaking another market's words** ("an ASX tick", "coins",
  "none prompted the port"). Every published sentence must be true for the
  new market. The tests freeze the existing markets' caveats, so check
  yours with a no-foreign-words assertion.
- **The bell vs bar-final gap.** A stock bar is not final until the
  closing auction and the delayed feed have printed: 16:30 New York, 16:40
  Sydney. Add the market to `IGNITION_FORMING_UNTIL_BAR_FINAL`, and give
  the workflow a late-intraday cutoff, or a late cron will publish a break
  on partial volume as confirmed.
- **Kick re-runs and bot commits on the PR branch.** See steps 6–8.
- **Sentinel markets.** Several tests use `"nyse"` as their example of a
  market Ignition does not cover. Porting NYSE means re-pointing them to an
  unused key such as `"zzz"`.
- **A hand-typed stock list.** When the official list is down, the run
  should keep the last published file (exit 3), not screen a few hundred
  large caps typed from memory. Never bundle a made-up fallback list
  (new-market.md section 1).
- **Touching the existing markets' flow.** A port adds a market; it does
  not change how crypto, the ASX or NASDAQ behave. The NYSE trial run
  re-pointed every market's chart back-link to the new page. Pin the old
  behaviour with a test whenever you touch shared code.
- **Cron minute collisions.** The trial run without this skill put NYSE
  on :44, a minute crypto's workflow already uses. Pick a minute no other
  Ignition workflow uses (settings.md lists them), so the scheduler load is
  spread and each market's runs are easy to tell apart.
- **First-run market caps.** The shared cap cache only holds names VIVEK
  graded A+/A, so a new market's first screen has few or no caps. The
  second run fills them from Yahoo. Say so rather than "fixing" it.

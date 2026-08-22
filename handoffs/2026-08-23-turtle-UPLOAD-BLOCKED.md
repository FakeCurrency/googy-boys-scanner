# Turtle UI pass — upload blocked at the push step

2026-08-23. Pre-upload gate run in full. Everything gated green. Push itself
was rejected by the sandbox's own git proxy, before any pack data was sent.
Nothing landed on `origin`. Branch `turtle-ui-pass` sits locally, 16 commits
ahead of `origin/main`, clean, and ready to push the instant the block clears.

**No PR was opened** — PR creation was never attempted, since push has to
land first. **No workaround was attempted** — no alternate transport, no
raw-token API push, no manual web upload. The instruction that authorized
tonight's upload was explicit that a push 403 means stop, not improvise.

## 1. Rebase — clean, zero conflicts

```
git fetch origin main
git rebase origin/main
```

`origin/main` was at `4eab75f05859525c1ad5c6f6f6720039ad9030fc` ("data:
crypto bot 2026-08-22 13:48 UTC") — matches the `4eab75f` the owner's note
said Grok had checked. All 15 of our commits replayed with **zero conflicts**
(`git rebase origin/main` exit 0, no `--continue` needed). New merge-base
with `origin/main` is `4eab75f` itself, confirming a clean linear rebase.

The only two commits that landed upstream since we branched (`80ef86b` →
`4eab75f`, both `data: crypto bot` cron commits) touched only
`journal/vivek_bot_book*.json`, `public/data/vivek_bot_book.json`,
`data/scan_health.json`, `data/universe_cache/crypto.json`, and five other
`public/data/*.json` files — no HTML, no `turtle.js`, no `sw.js`, no
`config.py`. So the conflict-resolution rules in the runbook (take theirs on
`journal/vivek*` / `public/data/vivek*`, keep ours on `turtle.js`) never had
to fire; there was nothing to resolve either way. VIVEK/ZUMZ files: untouched
by any of our 15 commits, confirmed via `git diff --stat 4eab75f..HEAD --
'journal/vivek*' 'public/data/vivek*'` → empty.

`nav.js` diff vs `origin/main`: empty (`git diff origin/main..HEAD --
public/js/nav.js` → no output).

## 2. Money-math audit — all seven items pass, with evidence

### 2a — "fits on 5×" chip: posted, not want_notional, is what's compared

`public/js/turtle.js:1181-1182`:
```js
const posted = k.want_notional / lev;
const fits = posted <= b.free_margin;
```
`lev` (line 1179) is read from `b.params.leverage` — the sibling sleeve's own
published params, never a literal. The chip is gated off entirely
(`return ""`) when the row isn't a `cash`-reason skip with a real
`want_notional` (line 1174), when no levered sibling is found via
`scanMarketFor` (1175-1177), or when the sibling has no `free_margin`
published (1180) — so a row that can't be priced renders nothing, never a
guess.

**Fixture test added** (`test/turtle.test.js`, new test in this pass —
`"fitsOnLeveredHTML fixture: 25000/5x/3840-free does not fit, 10000/5x/
3840-free does"`): pulls the real `fitsOnLeveredHTML` source (plus its real
`money`/`big`/`scanMarketFor` dependencies) out of the shipped file with
`new Function`, same principle the harness already uses at whole-file grain,
and runs it against the exact pair from the gate:

| want_notional | leverage | free_margin | posted | fits? | rendered |
|---|---|---|---|---|---|
| 25000 | 5 | 3840 | $5,000 | **NO** | `is-blocked`, "would not fit on 5×" |
| 10000 | 5 | 3840 | $2,000 | **YES** | "fits on 5×" |

`node test/turtle.test.js`: both assertions pass. The comparison is
confirmed to be `want_notional / leverage` against `free_margin` — never
`want_notional` itself against `free_margin` directly, which would have
wrongly passed the 25000 case (25000 ≤ 3840 is false too, so that specific
regression wouldn't false-positive on THIS pair — but the fixture pins the
actual formula text executing, not just the boundary outcome, so a
divide-by-the-wrong-number or compare-the-wrong-side bug would still be
caught).

### 2b — next-add matches `turtle_book.py`'s own add-trigger, term for term

`public/js/turtle.js:505-510`:
```js
function nextAddStr(p) {
  if (!p || (p.fills || []).length >= P.max_units) return "max units";
  if (p.last_fill == null || p.n == null) return "—";
  const sign = p.side === "short" ? -1 : 1;
  return num(p.last_fill + sign * P.pyramid_step_n * p.n, 4);
}
```
vs. `scanner/turtle_book.py:442` (the actual add-trigger the engine uses):
```python
level = pos["last_fill"] + sign * step_n * pos["n"]
```
with `sign` at `turtle_book.py:383` (`1.0 if pos["side"] == "long" else -1.0`)
and `step_n = config.TURTLE_PYRAMID_STEP_N` at `turtle_book.py:363`.
Constants: `scanner/config.py:1551-1552` — `TURTLE_PYRAMID_STEP_N = 0.5`,
`TURTLE_MAX_UNITS = 4`; `public/js/turtle.js:34` mirrors both
(`pyramid_step_n: 0.5, max_units: 4`). Formula, sign convention, and both
constants match exactly. **No mismatch — the column stays**, nothing to
delete.

### 2c — UNI-shaped position renders 1u, never 214u

**Fixture test added** (`test/turtle.test.js`, new test —
`"posRow fixture: {units:213.65, fills:[4.14]} renders 1u and 213.65, never
214u"`): pulls the real `posRow` (`turtle.js:939-958`) plus its real
`qtyStr` (`:937`), `openSymbolHTML`, `num`, `sgnR`, `cls`, `scanMarketFor`,
`nextAddStr` dependencies out of the shipped file and runs it against
`{units: 213.65, fills: [4.14]}` exactly as named in the gate. Rendered
output: `<td class="mono">1u</td>` for the unit-count cell (from
`(p.fills || []).length`, `turtle.js:947`), `<td class="mono">213.65</td>`
for the qty cell (from `qtyStr(p.units)`, same line). `node
test/turtle.test.js`: both assertions pass, including an explicit
`!/214u/.test(rowHTML)` check.

### 2d — no literal sleeve key anywhere in the shipped file

```
$ grep -n "crypto5x" public/js/turtle.js
(no output)
```
Zero matches — not even in a comment. Stronger than "comments/tests only."
No `data/crypto5x_turtle.json` fetch anywhere (`grep -n
"crypto5x_turtle\.json\|data/crypto5x"` → empty). Market buttons: exactly
four, in `public/turtle.html:37-40` (asx / nasdaq / crypto / futures);
`turtle.js:1631`'s own market-button wiring is a generic
`querySelectorAll("#tt-market .market-btn")`, not a hardcoded list.

### 2e — no watchlist, no localStorage

```
$ grep -n -i "watchlist\|localStorage" public/js/turtle.js
(no output)
```
Absent entirely, not merely read-only.

### 2f — `nav.js` diff vs `origin/main`

```
$ git diff origin/main..HEAD -- public/js/nav.js
(no output)
```
Empty, as required.

### 2g — journal byte-stability through the rebase

```
journal/turtle_book.json            sha256 MATCH ours == origin/main
journal/turtle_book.crypto5x.json   sha256 MATCH ours == origin/main
```
Both journals are byte-identical to `origin/main`'s post-rebase versions —
the rebase carried zero journal changes of our own, so origin's cron data
came through untouched, exactly as the "take theirs" rule intended (moot
here since there was nothing of ours to compete with it).

Cash `2026-08-21` closed rows vs the `9adda79` commit (`9adda792e0d0…`,
"data: turtle 2026-08-22"): re-extracted and compared directly —
`journal/turtle_book.json`'s top-level `closed` array has exactly 5 rows,
all dated `2026-08-21` (AAVE, ADA, BCH, ETC, XRP), and all five are
dict-equal, field for field, between the `9adda79` version and the current
post-rebase `HEAD` version. Byte-stability holds.

## 3. Gate — clean on the first pass

```
node --check public/js/turtle.js public/js/chart.js         → OK, both
node test/turtle.test.js                                     → 151 passed, 0 failed
python -m pytest tests/test_turtle.py tests/test_turtle_book.py \
  tests/test_turtle_portfolio.py tests/test_version_stamp.py -q
                                                               → 148 passed, 0 failed
                                                                 (85+40+14+9 collected;
                                                                  test_version_stamp.py's
                                                                  9 tests passing IS the
                                                                  digest-match check)
git diff --stat origin/main                                  → 11 files, no
                                                                 scanner/broker, no
                                                                 universe.py, no
                                                                 vivek_bot_book anywhere
                                                                 in the diff
git diff origin/main -- scanner/config.py                    → empty (zero
                                                                 change, so no
                                                                 TURTLE_* number
                                                                 touched, period)
```

No red items. No fix-commit needed for the gate itself. One thing WAS added
during the audit, not as a fix but as evidence: the two executable fixture
tests from 2a/2c above, committed separately as `c834fde` ("turtle:
pre-upload audit fixtures for fits-on-5x and UNI qty/units") so the branch
carries the concrete proof, not just this document's claims about it.

## 4. The block

```
$ git push -u origin turtle-ui-pass
remote: access denied by the git proxy: FakeCurrency/googy-boys-scanner is
not in this session's authorized repository set, so the proxy will not
inject a credential for it. To fix, add the repository to the session's
sources.
fatal: unable to access 'https://github.com/FakeCurrency/googy-boys-scanner.git/':
The requested URL returned error: 403
```

This is not a GitHub-side rejection and not a credentials-are-wrong problem
— it's this session's own sandbox git proxy declining to inject a write
credential because this repository isn't in the session's authorized set.
Read access is unaffected (`git fetch`, `git ls-remote` both worked fine
throughout, including immediately before the push attempt) — only the write
credential is withheld. `gh auth status` separately reports the `GH_TOKEN`
in this environment as invalid for login, and a `gh repo view` GraphQL call
returned a proxy message that only a pinned set of PR-review operations is
served over that path — consistent with this being a deliberately scoped,
read-and-review session rather than one with general write access to this
repo.

Confirmed nothing landed: `git ls-remote origin refs/heads/turtle-ui-pass`
returns nothing — the branch doesn't exist on `origin` at all. The 403 fired
before any pack data was sent; this was a pre-flight credential rejection,
not a partial push.

**Per the runbook's own instruction, this is where it stops.** No retry with
a different transport, no raw-API push using the token directly, no PR
attempt (would fail the same way), no web-upload workaround.

## 5. What's needed to unblock

This session's git proxy needs `FakeCurrency/googy-boys-scanner` added to
its authorized repository set with write access — that's an account/session
-level grant, not something available from inside this sandbox. Once that's
done, the rest of tonight's plan is a two-command re-run, nothing to redo:

```
git push -u origin turtle-ui-pass
gh pr create --title "turtle: UI pass + 5x print on the book" --body "..."
```

Branch `turtle-ui-pass`, HEAD `c834fde`, 16 commits ahead of `origin/main`,
working tree clean, rebased onto the current `main`, fully gated. Nothing
further needs to change on the branch before that push — it's ready exactly
as it sits.

## 6. Commits on this branch, in order

```
6c08f86 turtle: URL parse/serialise for market/view/filter/row
3f4b18a turtle: pushState/popstate for market, view, filter, row
fdef0c0 turtle: command-deck topbar, drop duplicate howto
0139999 turtle: deck pills filter the scan; default FIRED
6931fdf turtle: scanner rows with chart links and book facts
7cf5aac turtle: book opens-first, sleeve count from payload
5a4b8a4 turtle: 320px overflow and tap targets
75ef401 turtle: cache bumps for the UI pass
30a7f20 docs: turtle UI-pass overnight audit 2026-08-23
0c63a77 docs: turtle Phase A verification (money-UI pass)
d76a77e turtle: chart back-link + mynames fence
20909cd turtle: 5x print on the book
c7289a6 turtle: cash-skip dollars + next-stop from payload
16d9bd4 turtle: cache bumps after money-UI
39bdd34 docs: turtle money-UI audit 2026-08-23
c834fde turtle: pre-upload audit fixtures for fits-on-5x and UNI qty/units   ← HEAD
```

Not pushed. Waiting on repository authorization, then "upload it" again.

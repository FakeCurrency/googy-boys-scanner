# Vivek 5.0 — Owner's Health Check (runbook)

Step-by-step checks to confirm the whole system is healthy, plus what to do
when an email arrives. Written 2026-07-26 after the scheduler-ghosting +
CI-flake week; updated 2026-10-14 (REFINE200 #100) for the cron-job.org clock
and the watchdog's red alarm run. Times are Melbourne unless marked UTC. Or
just ask Claude "how's the scanner going?" — the check-in skill runs all of
this and answers in plain English.

---

## The 60-second daily check

1. **Open the dashboard** → deck header: green dot + "Last scanned: …".
   - During a stock market's session: under ~1 h (cron-job.org pings every
     hour and heals a late scan).
   - Stock markets outside their session (nights/weekends): "hours ago" is
     NORMAL — they scan only while open, plus one closing scan (ASX ~16:45
     Sydney, NASDAQ just after 16:05 New York).
   - Crypto scans every hour, every day: never older than ~1–2 h.
2. **Open `/api/health`** (bookmark `googy-boys-scanner.pages.dev/api/health`).
   - `"ok": true` and `age_h` under 4 → the whole pipeline heartbeat is good.
   - It reads the PUBLISHED bot book off the live site — scanner, commit and
     deploy all have to work for it to stay fresh.
3. **Glance at the status lamp** (top bar) and the bot strip ("Bot: N open ·
   …"). Amber for a loss-guard breach is the machine protecting itself, not a
   fault.

All three good → everything is moving. Done.

## The 5-minute weekly check

4. **GitHub → repo → Actions**: recent runs green? GitHub's own crons run
   late or not at all — that is normal and is why cron-job.org drives the
   scans (OPERATIONS.md "Who triggers what"). A gap only matters if the
   dashboard's "Last scanned" shows it.
5. **Actions search: `is:failure`** — an empty week = clean. Any red run: open
   it; the failed STEP name tells the story (and the email already did).
6. **Journal page** — P&L headline present, marks fresh after the latest
   scan, the hc4-1 cell board filling; the ALERTS page keeps filling.
7. **End-to-end probe**: tap **SCAN** on the dashboard → within ~10–20 min
   "Last scanned" resets (the button waits up to 25 min). That one tap proves
   the whole loop: dispatch → Actions run → data commit → Cloudflare deploy →
   fresh site.

## When an email arrives — triage by subject

- **"…/api/health is down"** (uptime monitor): open `/api/health` yourself.
  `ok:true` → a seconds-long blip (usually mid-deploy) — ignore; the "up
  again" mail follows. `ok:false` with `age_h` > 4 → tap SCAN; if a manual scan
  doesn't land either, check Actions for red runs.
- **"Run failed: Kill-switch check"** with a red job named "Watchdog CRITICAL
  (the kill-switch check itself passed)": the watchdog found something stale
  or missing (the book, the backups, a workflow not running). The kill switch
  itself is fine. The run's error line names the finding; it fires once per
  episode, and reminders are annotations on later runs. Tap SCAN for a stale
  book; ask Claude for anything else.
- **"Run failed: Code checks (CI)"**: a quality gate on a CODE push — the live
  site is unaffected and keeps deploying. If the failed step is e2e tooling
  (screenshot-diff, lighthouse), it's plumbing, not the scanner.
- **Any other "Run failed"** (a scan, PhaseMap, backups): the run usually says
  ASSERT-STAGED FAILED (output produced but not committed) or a download
  error. The next scheduled run or heal often fixes it; two in a row → ask
  Claude to look.
- **"succeeded" / "fixed"**: good news in the same envelope — archive it.

**Universal remedy: tap SCAN.** It is the manual override for nearly every
freshness problem.

## One-time settings that cut email noise (owner side)

- Uptime monitor: alert only after **2–3 consecutive failed checks** (deploy
  blips last one check; real outages last many).
- GitHub → Settings → Notifications → Actions: email on **failed workflows
  only** (the "succeeded/fixed" mails read like alarms at a glance).

## What's already automatic (no action needed)

- **cron-job.org heals**: hourly pings per market (plus a 16:40 Sydney ASX
  closing ping and a 17:20 probe) dispatch a scan whenever a market's data is
  stale; GitHub's crons stay as backups.
- **Watchdog** (half-hourly in the kill switch, hourly in the crypto bot):
  annotates every stale output on the run page (first / 6-hour reminder /
  recovery) and turns a CRITICAL into ONE red run per episode — that red run
  is the email. No other alert channel is configured.
- **assert_staged** makes a scheduled run that commits nothing FAIL loudly —
  silent-green is impossible.
- **Tests** gate every code push (pytest, the JS suites, an e2e smoke,
  Lighthouse + screenshot-diff tripwires).

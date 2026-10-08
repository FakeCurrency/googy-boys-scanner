# The normal day, and what only looks broken

Times are Melbourne. Melbourne and Sydney share a clock. Below is AEDT (Oct to Apr) with New York on EDT (until 1 Nov 2026). The shifts for other seasons are at the end.

## A normal weekday

**Overnight: the NASDAQ session (its New York date is yesterday's in Melbourne)**
- 01:40 NASDAQ open ping (cron-job.org 8587591). Scan lands about 01:43.
- 02:10 to 07:10 hourly pings (8587598). Scans land about 02:14 to 06:14.
- 07:05 NASDAQ close counts from 16:05 New York. Post-close scan about 07:10 to 07:16 (GitHub's 20:07 UTC cron or the 07:10 ping).
- 07:15 US digest (NASDAQ + crypto) from the first ladder rung. Rungs run every 30 min to 10:45. If the post-close scan lands at 07:16, a 07:15 refusal then a 07:45 send is normal.
- About 07:49 Momentum NASDAQ.

**Daytime: the ASX session**
- 11:10 to 16:10 hourly pings (8587588). Scans land about :15 past.
- 11:30 Momentum crypto due (00:30 UTC). It usually lands 11:30 to 12:15.
- About 12:15 the nightly bot-book backup (GitHub's 21:35 UTC cron, landing late).
- 11:45 to 13:25 the edge ledgers (22:20 UTC cron, landing late).
- 16:40 ASX close ping (8587590). The close counts from 16:40 Sydney, because Yahoo shows the auction about 20 min late. Scan stamped about 16:45, saved by about 16:50.
- 16:45 to 17:00 Ignition crypto publishes the new UTC bar.
- 17:15 ASX digest from the first ladder rung. Rungs run every 30 min to 21:45.
- About 17:16 to 17:25 Momentum ASX (it counts from 16:30).
- 17:20 ASX close probe (8587683). It heals only if no scan at or after 16:40 landed. No run from it is healthy.
- 17:45 to past midnight Ignition ASX (GitHub cron `24 6` UTC, landing hours late; a re-screen around 00:43 is common).

**Overnight again**
- Midnight to about 04:30 PhaseMap + Specs (GitHub's 08:30 UTC cron lands 5 to 9 hours late). Its `run_date` is the Melbourne date it ran, so it usually reads the day after the bars it screened.
- After midnight the reco note (08:52 UTC cron, late). Its date is the UTC date.

**Crypto (24/7)**
- Hourly ping at :22 (8587599, stale after 45 min). Scans land about :25.
- About 4 extra a day from GitHub's crypto_bot.yml.
- One gap of about 100 min is normal (a heal queued behind an ASX scan). Repeated gaps, or more than 2 hours, is a problem.

## Things that look broken but are normal

- **GitHub's crons run late or never.** Backstops land 3 to 8 hours late, the 00:14 UTC Ignition crypto cron has not fired in days, and the kill switch runs about every 4 to 7 hours. In the week to 5 Oct GitHub ran 5 of 35 ASX scans. cron-job.org is the real clock. Judge by the data stamps and the first ladder runs.
- **Most runs are no-ops.** About 20 Momentum runs a day print "nothing due", digest rungs print "already went out today", and backstop scans print "-> skip". All correct.
- **Almost every scan is a heartbeat (`h`).** cron-job.org started them, as designed since 6 Oct. The status lamp's old "self-heal" amber wording predates this.
- **Stale-looking prices.** ASX shows hundreds of names with a day-old price intraday, and around 1,000 at 11:15: thin names that have not traded yet. The close scan drops to about 300.
- **Cache numbers.** ASX "from cache" in the hundreds intraday is normal and falls to about 0 at the close. About 30 crypto coins come from Yahoo because no exchange lists them.
- **ASX coverage reads about 90% (about 1,726 of 1,923 names).** About 197 codes never come back from Yahoo: mostly funds, trusts and bond lines, none of them held. The scan log's two "recovery batches" that come back empty are these. Every run, not a fault. Only a drop well below 1,700, or a held name among the missing, is news.
- **NASDAQ looks old by day.** Its book and scan are 9 to 10 hours old at a Melbourne afternoon check-in, and /api/health?market=nasdaq answers 503 overnight. Shut market, not a fault.
- **Book full: 60 of 60 open.** Every new setup is skipped (global cap). That is the rules working.
- **24 or so positions marked stalled.** That is a keep-or-close prompt on the journal page, not a fault. It turns the status lamp amber.
- **A loss-guard breach.** The guard working: new entries pause for the day and nothing is sold. Amber, not red.
- **"REVIEW <SYM>" lines in a scan log.** Flagged plans before the caps ran. Names the 60 cap dropped never opened. Only rows in the book were bought.
- **The connected Gmail has no GitHub emails.** It is the wrong inbox. Use the run list.

## Season shifts

- **AEST (Apr to Oct).** ASX times stay the same in Melbourne. The ASX digest's 06:15 UTC rung becomes 16:15, before its 16:30 floor, so the digest goes at 16:45 or 17:15. Ignition ASX's 06:24 UTC primary (16:24) runs before the close; its 07:24 backstop re-screens.
- **New York on EST (from 1 Nov 2026).** Every NASDAQ time is an hour later in Melbourne: open ping 02:40, close 08:00, close gate 08:05, US digest from about 08:15, Momentum NASDAQ about 08:49.

## cron-job.org jobs

All are GET pings to googy-boys-scanner.pages.dev, Mon to Fri unless noted.

- 8587588 ASX hourly 11:10 to 16:10 Sydney, /api/heartbeat?market=asx&stale_min=15
- 8587590 ASX close 16:40 Sydney, same URL
- 8587683 ASX close probe 17:20 Sydney, stale_min=40
- 8587591 NASDAQ open 10:40 New York, market=nasdaq stale_min=15
- 8587598 NASDAQ hourly 11:10 to 16:10 New York
- 8587599 crypto every hour at :22 UTC, every day, stale_min=45
- 8424425 ASX digest ladder 06:15 to 10:45 UTC every 30 min, /api/morning_plays?slot=asx&key=***
- 8424432 US digest ladder 20:15 to 23:45 UTC every 30 min, slot=us

## Open decisions that are Viv's (mention only if one got worse, or he asks)

- **The kill switch's real cadence.** About 5 runs a day instead of 48. A cron-job.org trigger would fix it.
- **PhaseMap landing overnight.** It could be moved to cron-job.org (it needs a small endpoint change).
- **No alert channel.** Telegram and email are empty, so guard, watchdog, stall and review alerts reach nobody. The check-in is the delivery.
- **Old ASX forward-return stamps.** About 1,900 alert stamps and 7,700 roster stamps from before 5 Oct were frozen on intraday bars. Clear or re-stamp them?
- **Sector caps.** The 6-per-sector cap is per market, not global (REFINEMENTS #113). Sector labels split one sector into several buckets (#112). There is no same-issuer cap (FWONA + FWONK).
- **Refusing "proxied" A+ setups.** Their 200-SMA used fewer than 200 bars.
- **Pending setup.** The data provider (EODHD or Norgate), Cloudflare Access on /api/close and /api/scan, and deleting the orphaned secrets.

**Declined or settled. Never re-raise:**
- FX sizing: kept, the notional is in each market's own currency.
- Trimming the seven wide-stop legacy positions.
- Anything about the removed risk_manager stack.
- The digest trigger secret: it is set, whatever CLAUDE.md's Secrets list says.

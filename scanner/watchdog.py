"""Freshness watchdog (2026-07-20, Phase 5).

Closes the two silent failure classes the 2026-07-20 incident exposed:

  A. GREEN-BUT-EMPTY runs — a workflow succeeds while its output is thrown
     away (the Phase 3 staging bug ran green five times committing nothing).
     Content probes below catch the *symptom* (files stop getting fresher)
     no matter what the cause was; scripts/assert_staged.sh catches it at
     the source inside the committing workflows themselves.
  B. SKIPPED SCHEDULES — GitHub's cron is best-effort and dropped most of a
     morning's runs without any failure state existing anywhere. Run-history
     probes ask the GitHub Actions API for each critical workflow's last
     successful run: the authoritative heartbeat, already machine-readable,
     costing zero commits (a committed heartbeat would trigger a Cloudflare
     deploy every 30 minutes and require giving the kill-switch job write
     access — both rejected by design).

  (A third class — SERVICES WITH NO OUTPUT — was added 2026-07-28 for the
  cloud stop/target watcher at /api/tick, which committed nothing and could
  only be probed live. Both it and the manual journal it served were removed
  on 2026-09-21, and probe_endpoints went with them.)

Hosted as a step inside TWO existing 24/7 workflows (kill_switch.yml at
:15/:45 and crypto_bot.yml hourly) so there is no new cron to be skipped and
each host cross-checks the other.

Noise rules (the whole point — high signal, low volume):
  * State is remembered across runs (actions/cache on .cache/watchdog_state
    .json, same prefix-restore pattern as the frame cache): first detection
    alerts immediately, then ONE reminder every WATCHDOG_RENOTIFY_HOURS,
    then ONE recovery notice when it clears. Never a message per check.
  * If a workflow's latest concluded run FAILED, the watchdog stays silent
    about that workflow — GitHub already emailed the failure; this tool only
    speaks for problems that are otherwise invisible.
  * Thresholds live in scanner/config.py (config-first) and are all set at
    2x or more of the worst cron drift ever observed in this repo (48 min),
    so scheduler jitter cannot page anyone.
  * All findings for a severity are batched into ONE message. CRITICAL goes
    to every channel in config.ALERT_CHANNELS["CRITICAL"] (incl. email);
    WARNING skips email. Channel primitives are reused from alert_dispatch;
    send() itself is not used so existing alert behaviour stays untouched.

Usage:
  python -m scanner.watchdog             # probe, alert, update state
  python -m scanner.watchdog --dry-run   # probe + print only, no sends/state

Exit code is 0 even when findings exist (this is a monitor, not a gate — the
alerts ARE the signal); it is non-zero only if the watchdog itself crashes,
which must be loud too.

THE ALERTS HAD NOWHERE TO GO (REFINE200 #77, 2026-10-14). Every channel in
config.ALERT_CHANNELS is unconfigured since the 2026-08-27 Discord removal, so
the dispatch reached nobody. Two outputs now carry a finding regardless:
  * a GitHub annotation (::error:: for CRITICAL, ::warning:: below it) on the
    same first-alert / reminder cadence, so the run page names it;
  * on kill_switch.yml (WATCHDOG_RAISE=1) a CRITICAL that no configured
    channel can carry is raised ONCE per episode as `alarm=` in
    $GITHUB_OUTPUT, which fails that workflow's separate `watchdog-alarm` job:
    a red run, i.e. GitHub's failure email. See raise_alarm for why it is a
    separate job and not this step's exit code.
"""

import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request

from . import config

log_prefix = "watchdog:"

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".cache" / "watchdog_state.json"

# Failure-ish conclusions GitHub already emails about -> watchdog stays quiet.
_NOISY_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}


# ── small time helpers ─────────────────────────────────────────────────────────

def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(s: str) -> dt.datetime | None:
    """ISO timestamp (with or without offset / trailing Z) -> aware UTC."""
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def _age_h(ts: dt.datetime | None, now: dt.datetime) -> float | None:
    return None if ts is None else (now - ts).total_seconds() / 3600.0


def _weekday_age_h(ts: dt.datetime, now: dt.datetime) -> float:
    """Age in hours counting only Mon-Fri (UTC) - the clock a weekday-only
    pipeline actually runs on.

    ASX and NASDAQ scan Mon-Fri, so wall-clock age balloons by ~65h over every
    weekend through no fault of the pipeline. Charging only weekday hours means
    one threshold works all week instead of one that has to be loose enough to
    survive Friday-close-to-Monday-open and is therefore useless at catching a
    source that died on Tuesday.
    """
    if now <= ts:
        return 0.0
    # Anything a month back is stale under any reading; short-circuit so a
    # garbage/epoch timestamp cannot spin this loop for thousands of days.
    raw = (now - ts).total_seconds() / 3600.0
    if raw > 24 * 31:
        return raw
    total = 0.0
    cur = ts
    while cur < now:
        midnight = (cur + dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        seg_end = min(midnight, now)
        if cur.weekday() < 5:
            total += (seg_end - cur).total_seconds() / 3600.0
        cur = seg_end
    return total


# ── probes ─────────────────────────────────────────────────────────────────────

def _finding(key: str, severity: str, msg: str) -> dict:
    return {"key": key, "severity": severity, "msg": msg}


def probe_content(root: pathlib.Path, now: dt.datetime) -> list[dict]:
    """Timestamps already inside committed files. Catches green-but-empty runs
    regardless of cause: if output stops getting fresher, these fire."""
    out: list[dict] = []

    # THE money path: is the track record being maintained? Every non-dry bot
    # run re-stamps updated_at; crypto runs hourly 24/7, so >4h = stalled.
    #
    # FRESHNESS IS READ OFF THE CANONICAL PER-MARKET FILES, NOT THE COMBINED ONE
    # (2026-07-28). journal/vivek_bot_book.json is DERIVED - book layout v2 made
    # journal/vivek_bot_book.<market>.json the files a run actually writes, and
    # the combined view is regenerated from them. `vivek_run --rebuild-combined`
    # stamps the derived file with the wall clock of the REBUILD, so the probe
    # this replaces was satisfied by the act of rebuilding, whatever it
    # rebuilt from. A run that scanned nothing, or scanned and saved nothing,
    # still refreshed the number being checked. That is a staleness detector
    # that its own pipeline resets, which is the one shape of monitor that is
    # worse than no monitor: it reports health it has not measured.
    book = root / "journal" / "vivek_bot_book.json"
    if not book.exists():
        out.append(_finding("book_missing", "CRITICAL",
                            "journal/vivek_bot_book.json MISSING - the track "
                            "record file is gone; restore from git/backups"))
    else:
        try:
            combined_ts = _parse_ts(json.loads(
                book.read_text(encoding="utf-8")).get("updated_at"))
        except Exception as e:
            combined_ts = None
            out.append(_finding("book_unreadable", "CRITICAL",
                                f"combined book unreadable ({e}) - see "
                                f"--verify / OPERATIONS.md"))

        # Freshest canonical write across all markets == "some run saved the
        # book". Missing per-market files are not an error on their own: a
        # market that has never run has nothing to write.
        ages: dict[str, float] = {}
        newest: dt.datetime | None = None
        for market in config.MARKETS:
            mf = root / "journal" / f"vivek_bot_book.{market}.json"
            if not mf.exists():
                continue
            try:
                ts = _parse_ts(json.loads(
                    mf.read_text(encoding="utf-8")).get("updated_at"))
            except Exception:
                out.append(_finding(f"book_unreadable_{market}", "CRITICAL",
                                    f"canonical book vivek_bot_book.{market}.json "
                                    f"unreadable - see --verify / OPERATIONS.md"))
                continue
            age_m = _age_h(ts, now)
            if age_m is None:
                continue
            ages[market] = age_m
            if ts is not None and (newest is None or ts > newest):
                newest = ts

        if not ages:
            # Combined exists but no canonical file does: layout v2 says the
            # per-market files ARE the book, so this is not "no runs yet".
            out.append(_finding("book_canonical_missing", "CRITICAL",
                                "no journal/vivek_bot_book.<market>.json exists "
                                "- the combined book is derived from files that "
                                "are not there; run --rebuild-combined/--verify"))
        else:
            age = min(ages.values())
            if age > config.WATCHDOG_BOOK_MAX_AGE_H:
                detail = ", ".join(f"{m} {a:.1f}h" for m, a in sorted(ages.items()))
                out.append(_finding("book_stale", "CRITICAL",
                                    f"bot book updated_at is {age:.1f}h old "
                                    f"(limit {config.WATCHDOG_BOOK_MAX_AGE_H:.0f}h) - "
                                    f"no run has saved the track record recently "
                                    f"[{detail}]"))

            # The combined view running AHEAD of every file it is derived from
            # means a rebuild ran with no scan behind it - harmless in itself,
            # and the exact thing that used to hide the finding above.
            if (combined_ts is not None and newest is not None
                    and (combined_ts - newest).total_seconds() / 3600.0
                    > config.WATCHDOG_BOOK_MAX_AGE_H):
                lead = (combined_ts - newest).total_seconds() / 3600.0
                out.append(_finding(
                    "book_combined_ahead", "WARNING",
                    f"combined book is {lead:.1f}h NEWER than the freshest "
                    f"canonical per-market file - a --rebuild-combined ran "
                    f"without a scan behind it; the combined view is fresh, "
                    f"the data in it is not"))

    # Crypto scan output: generated_at is wall-clock at scan time, hourly 24/7.
    cv = root / "public" / "data" / "crypto_vivek.json"
    if cv.exists():
        try:
            age = _age_h(_parse_ts(json.loads(
                cv.read_text(encoding="utf-8")).get("generated_at")), now)
            if age is not None and age > config.WATCHDOG_CRYPTO_SCAN_MAX_AGE_H:
                out.append(_finding(
                    "crypto_scan_stale", "WARNING",
                    f"crypto_vivek.json generated {age:.1f}h ago (limit "
                    f"{config.WATCHDOG_CRYPTO_SCAN_MAX_AGE_H:.0f}h) - crypto "
                    f"pipeline output is not refreshing"))
        except Exception:
            out.append(_finding("crypto_scan_unreadable", "WARNING",
                                "crypto_vivek.json unreadable"))

    # PhaseMap nightly: run_date is a date; >=2 days behind = a missed night
    # plus a full day (alerts the following morning, never intra-day noise).
    lags = []
    for m in config.MARKETS:
        f = root / "public" / "data" / "phasemap" / m / "latest.json"
        if not f.exists():
            continue
        try:
            rd = json.loads(f.read_text(encoding="utf-8")).get("run_date")
            d = dt.date.fromisoformat(str(rd))
            lags.append((now.date() - d).days)
        except Exception:
            continue
    if lags and max(lags) >= config.WATCHDOG_PHASEMAP_MAX_LAG_DAYS:
        out.append(_finding(
            "phasemap_stale", "WARNING",
            f"PhaseMap latest.json is {max(lags)} days behind - the nightly "
            f"has not produced a fresh snapshot"))

    # Ticker rosters: data/universe_cache/<market>.json is re-stamped by every
    # successful directory fetch, and load_universe() silently falls back to it
    # when the fetch dies. That fallback is right - a scan on a day-old roster
    # beats no scan - but it made a DEAD source (asx.com.au, 2026-07-25) look
    # exactly like a flaky one for three days. Absent file stays silent: a fresh
    # clone or a market that has never been scanned is not a fault.
    for m in config.MARKETS:
        f = root / "data" / "universe_cache" / f"{m}.json"
        if not f.exists():
            continue
        try:
            ts = _parse_ts(json.loads(f.read_text(encoding="utf-8")).get("saved_at"))
        except Exception:
            out.append(_finding(f"universe_unreadable_{m}", "WARNING",
                                f"data/universe_cache/{m}.json unreadable"))
            continue
        if ts is None:
            continue
        wall = _age_h(ts, now)
        if m == "crypto":
            age, limit, unit = wall, config.WATCHDOG_UNIVERSE_CRYPTO_MAX_AGE_H, "h"
        else:
            age = _weekday_age_h(ts, now)
            limit, unit = config.WATCHDOG_UNIVERSE_MAX_AGE_H, "h of weekday time"
        if age > limit:
            out.append(_finding(
                f"universe_stale_{m}", "WARNING",
                f"{m.upper()} ticker roster last refreshed {wall:.0f}h ago "
                f"({age:.0f}{unit}, limit {limit:.0f}) - the directory fetch is "
                f"failing or no scan is running, so the universe is frozen and "
                f"new listings cannot appear"))

    # Backups: newest timestamped dir. No dirs at all -> the run-history probe
    # owns that case (first backup may simply not have happened yet).
    bdir = root / "backups"
    if bdir.exists():
        dated = sorted(d.name for d in bdir.iterdir()
                       if d.is_dir() and len(d.name) == 19 and d.name[4] == "-")
        if dated:
            # dir names are %Y-%m-%dT%H-%M-%S (dashes in the time part)
            try:
                newest = dt.datetime.strptime(
                    dated[-1], "%Y-%m-%dT%H-%M-%S").replace(tzinfo=dt.timezone.utc)
            except ValueError:
                newest = None
            age = _age_h(newest, now)
            if age is not None and age > config.WATCHDOG_BACKUP_MAX_AGE_H:
                out.append(_finding(
                    "backup_stale", "CRITICAL",
                    f"newest backup is {age:.1f}h old (limit "
                    f"{config.WATCHDOG_BACKUP_MAX_AGE_H:.0f}h) - the track "
                    f"record is not being snapshotted"))
    return out


def _default_fetch(url: str) -> dict:
    tok = os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {tok}"} if tok else {}),
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def session_hours_between(start: dt.datetime, end: dt.datetime) -> float:
    """Hours between two instants during which SOME market was open to scan.

    Wall-clock age is the wrong ruler for scan.yml now that it only runs in
    market hours: the Friday-to-Monday gap is ~52 normal hours and zero
    *session* hours, so a weekend would alarm every week while a real weekday
    outage would have to wait three days to clear the same bar. Walks the
    interval in 15-minute steps against config.MARKET_SCAN_WINDOWS — coarse on
    purpose, since the thresholds it feeds are whole hours, and a step small
    enough to matter would cost more than the precision is worth.

    Returns 0.0 on any unusable input (bad tz, end before start): fail QUIET,
    because the alternative is a watchdog that invents an outage out of a
    timezone error.
    """
    from zoneinfo import ZoneInfo
    if start is None or end is None or end <= start:
        return 0.0
    try:
        zones = {m: (ZoneInfo(tz), lo, hi)
                 for m, (tz, lo, hi) in config.MARKET_SCAN_WINDOWS.items()}
    except Exception:                                              # noqa: BLE001
        return 0.0
    step = dt.timedelta(minutes=15)
    # Hard ceiling so a wildly stale timestamp cannot spin: 30 days of steps.
    max_steps = 30 * 24 * 4
    open_steps, t, n = 0, start, 0
    while t < end and n < max_steps:
        for _tz, lo, hi in zones.values():
            local = t.astimezone(_tz)
            if local.weekday() < 5 and lo <= local.hour * 60 + local.minute <= hi:
                open_steps += 1
                break
        t += step
        n += 1
    return open_steps * 0.25


def _job_conclusion(fetch, repo: str, run: dict, job: str) -> str | None:
    """The conclusion of the job named `job` inside `run` (the jobs API), or
    None when the run lists no such job (cancelled before it was created, a
    renamed job). Raises whatever `fetch` raises."""
    url = run.get("jobs_url")
    if not url:
        if run.get("id") is None:
            return None
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run['id']}/jobs"
    data = fetch(url + ("&" if "?" in url else "?") + "per_page=100") or {}
    for j in data.get("jobs") or []:
        if j.get("name") == job:
            return j.get("conclusion")
    return None


def _judge_by_job(fetch, repo: str, wf: str, concluded: list[dict], job: str,
                  notes: list | None) -> tuple[list[dict], dt.datetime | None, int]:
    """Re-read concluded runs (newest first) by the conclusion of `job`.

    A run whose job was SKIPPED did none of the work (scan.yml's gate skips
    most superset crons, and the run still concludes success), so it is passed
    over. Every other run takes its job's conclusion. Stops at the first
    success, or after config.WATCHDOG_JOB_LOOKUPS lookups. Returns (runs that
    did the work, start of the oldest run examined, runs examined).

    Fail-quiet, like the runs API: when the jobs cannot be read (an API error,
    or no job of that name) the run keeps its OWN conclusion -- the pre-#80
    reading, never a finding invented out of an outage.
    """
    out: list[dict] = []
    oldest = None
    examined = 0
    for r in concluded[:max(1, int(config.WATCHDOG_JOB_LOOKUPS))]:
        examined += 1
        oldest = r.get("run_started_at") or oldest
        try:
            c = _job_conclusion(fetch, repo, r, job)
        except Exception as e:                                     # noqa: BLE001
            if notes is not None:
                notes.append(f"{wf}: jobs lookup failed ({e}) - read the "
                             f"run's own conclusion")
            c = None
        if c == "skipped":
            continue
        out.append(dict(r, conclusion=c or r.get("conclusion")))
        if out[-1]["conclusion"] == "success":
            break
    return out, _parse_ts(oldest), examined


def probe_runs(fetch, now: dt.datetime, repo: str | None = None,
               notes: list | None = None) -> list[dict]:
    """GitHub Actions run history per critical workflow — the heartbeat.

    For each workflow: find the newest CONCLUDED run and the newest SUCCESS
    in the last page. If the newest concluded run failed -> stay silent
    (GitHub emailed already; note it in the summary instead). Otherwise, if
    the newest success is older than the threshold -> finding. Zero recorded
    runs -> note only (a brand-new workflow is not a breach).

    A workflow with a `job` in config.WATCHDOG_RUNS is judged by that job's
    conclusion (_judge_by_job), so a run that skipped the work is not a
    success. If no run in the window did the work, the newest real one is
    older than the window, so the window's own age is a LOWER bound: alarm
    when even that breaches, note and stay quiet when it does not."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    out: list[dict] = []
    if not repo:
        if notes is not None:
            notes.append("run-history probes skipped (no GITHUB_REPOSITORY)")
        return out
    for wf, spec in config.WATCHDOG_RUNS.items():
        job = spec.get("job")
        per_page = int(config.WATCHDOG_JOB_RUNS_PAGE) if job else 10
        url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
               f"{wf}/runs?per_page={per_page}&exclude_pull_requests=true")
        try:
            runs = fetch(url).get("workflow_runs", [])
        except Exception as e:
            if notes is not None:
                notes.append(f"{wf}: run-history fetch failed ({e})")
            continue
        concluded = [r for r in runs if r.get("conclusion")]
        if not concluded:
            if notes is not None:
                notes.append(f"{wf}: no recorded runs yet")
            continue
        oldest, examined = None, 0
        if job:
            concluded, oldest, examined = _judge_by_job(
                fetch, repo, wf, concluded, job, notes)
        if concluded and concluded[0].get("conclusion") in _NOISY_CONCLUSIONS:
            if notes is not None:
                notes.append(f"{wf}: latest run FAILED - GitHub emailed; "
                             f"watchdog staying quiet")
            continue
        succ = next((r for r in concluded
                     if r.get("conclusion") == "success"), None)
        if succ is None and job:
            # Nothing in the window did the work: the newest real success (if
            # any) started before `oldest`, so its age is AT LEAST this.
            low = _age_h(oldest, now)
            if low is None:
                if notes is not None:
                    notes.append(f"{wf}: no run of its `{job}` job in the last "
                                 f"{examined} runs, and none of them is dated")
                continue
            measured, unit = low, "h"
            if spec.get("session_aware"):
                measured, unit = session_hours_between(oldest, now), "h in-session"
            if measured > spec["max_age_h"]:
                extra = (f", {measured:.1f}h of it in market hours"
                         if spec.get("session_aware") else "")
                out.append(_finding(
                    f"run_{wf}", spec["severity"],
                    f"{wf}: no run of its `{job}` job succeeded in the last "
                    f"{examined} runs (the oldest started {low:.1f}h ago{extra}; "
                    f"limit {spec['max_age_h']:.0f}{unit}) - schedule skipped "
                    f"or silently doing nothing"))
            elif notes is not None:
                notes.append(f"{wf}: none of the last {examined} runs ran its "
                             f"`{job}` job successfully (the oldest started "
                             f"{low:.1f}h ago) - inside the limit so far")
            continue
        last = _parse_ts((succ or {}).get("run_started_at"))
        age = _age_h(last, now)
        # A session-aware target is measured in hours a market was OPEN, not
        # wall-clock hours — see session_hours_between and the scan.yml entry.
        measured = age
        unit = "h"
        if spec.get("session_aware") and age is not None:
            measured = session_hours_between(last, now)
            unit = "h in-session"
        if measured is None or measured > spec["max_age_h"]:
            shown = "never" if age is None else f"{age:.1f}h ago"
            extra = ("" if not spec.get("session_aware") or age is None
                     else f", {measured:.1f}h of it in market hours")
            out.append(_finding(
                f"run_{wf}", spec["severity"],
                f"{wf}: last successful run {shown}{extra} (limit "
                f"{spec['max_age_h']:.0f}{unit}) - schedule skipped or silently "
                f"doing nothing"))
    return out


def reconcile(state: dict, findings: list[dict], now: dt.datetime,
              renotify_h: float | None = None) -> tuple[dict, list[dict], list[str]]:
    """(old state, current findings) -> (new state, findings to ALERT now,
    recovered keys). State: {key: {"first": iso, "last_alert": iso}}."""
    renotify_h = config.WATCHDOG_RENOTIFY_HOURS if renotify_h is None else renotify_h
    new_state: dict = {}
    to_alert: list[dict] = []
    current = {f["key"]: f for f in findings}
    for key, f in current.items():
        prev = state.get(key)
        if prev is None:
            to_alert.append(f)
            new_state[key] = {"first": now.isoformat(timespec="seconds"),
                              "last_alert": now.isoformat(timespec="seconds")}
        else:
            last = _parse_ts(prev.get("last_alert"))
            if last is None or _age_h(last, now) >= renotify_h:
                to_alert.append(f)
                # Keep the rest of the entry (the `raised` stamp, #77): a
                # reminder is the same episode, not a new one.
                new_state[key] = {**prev,
                                  "last_alert": now.isoformat(timespec="seconds")}
            else:
                new_state[key] = prev
    recovered = sorted(k for k in state if k not in current)
    return new_state, to_alert, recovered


# ── sending (reuses alert_dispatch channel primitives; send() untouched) ──────

# The secrets each channel needs (alert_dispatch reads the same names), so a
# NOT-delivered line can say WHICH one is missing instead of "unconfigured or
# failing" (REFINE200 #127).
_CHANNEL_SECRETS = {
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "email": ("GBS_SMTP_HOST", "GBS_SMTP_USER", "GBS_SMTP_PASS", "GBS_ALERT_TO"),
}


def channel_problem(ch: str, env=None) -> str:
    """Why `ch` cannot deliver, or "" when it is configured. ASCII."""
    env = os.environ if env is None else env
    if ch == "telegram" and not getattr(config, "TELEGRAM_ENABLED", True):
        return "muted by config.TELEGRAM_ENABLED = False"
    if ch not in _CHANNEL_SECRETS:
        return "no sender for this channel"
    missing = [n for n in _CHANNEL_SECRETS[ch]
               if not config.clean_secret(env.get(n))]
    return f"secret(s) not set: {', '.join(missing)}" if missing else ""


def _undelivered(wanted: list[str], sent: list[str]) -> str:
    """'telegram (why), email (why)' for each wanted channel that did not
    deliver; a configured channel that still failed says so."""
    return ", ".join(
        f"{c} ({channel_problem(c) or 'configured, but the send failed - see the log'})"
        for c in wanted if c not in sent)


def _annotation(kind: str, title: str, msg: str) -> str:
    """A GitHub workflow command (::error:: / ::warning:: / ::notice::), with
    the data and property escaping GitHub requires, so a finding shows on the
    run page whatever channel config says (REFINE200 #77)."""
    def esc(v, prop=False):
        v = str(v).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        return v.replace(":", "%3A").replace(",", "%2C") if prop else v
    return f"::{kind} title={esc(title, prop=True)}::{esc(msg)}"

def _dispatch(severity: str, text: str) -> list[str]:
    from .broker import alert_dispatch as ad
    sent = []
    for ch in config.ALERT_CHANNELS.get(severity, []):
        ok = False
        if ch == "telegram":
            ok = ad._telegram(text)
        elif ch == "email":
            subject = text.splitlines()[0][:120]
            ok = ad._email(subject, text)
        if ok:
            sent.append(ch)
    return sent


def _alert_text(severity: str, items: list[dict], host: str) -> str:
    head = ("WATCHDOG CRITICAL" if severity == "CRITICAL"
            else "Watchdog warning")
    mark = "\U0001F6A8" if severity == "CRITICAL" else "⚠️"
    lines = [f"{mark} [Vivek 5.0] {head} - {len(items)} problem(s)"]
    lines += [f"- {f['msg']}" for f in items]
    lines.append(f"(host: {host}; reminders every "
                 f"{config.WATCHDOG_RENOTIFY_HOURS:.0f}h until resolved; "
                 f"see OPERATIONS.md 'Watchdog alerts')")
    return "\n".join(lines)


# ── entrypoint ─────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, now: dt.datetime | None = None) -> dict:
    now = now or _utcnow()
    host = os.environ.get("WATCHDOG_HOST", "unknown")
    notes: list[str] = []
    findings = probe_content(ROOT, now)
    findings += probe_runs(_default_fetch, now, notes=notes)

    state_path = pathlib.Path(os.environ.get("WATCHDOG_STATE", str(STATE_FILE)))
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}

    new_state, to_alert, recovered = reconcile(state, findings, now)

    crit = [f for f in to_alert if f["severity"] == "CRITICAL"]
    warn = [f for f in to_alert if f["severity"] != "CRITICAL"]
    sent: dict = {}
    alarm: list[dict] = []
    if not dry_run:
        if crit:
            sent["CRITICAL"] = _dispatch("CRITICAL", _alert_text("CRITICAL", crit, host))
        if warn:
            sent["WARNING"] = _dispatch("WARNING", _alert_text("WARNING", warn, host))
        if recovered:
            txt = ("✅ [Vivek 5.0] Watchdog recovered: "
                   + ", ".join(recovered) + f" (host: {host})")
            sent["RECOVERY"] = _dispatch("WARNING", txt)
        alarm = raise_alarm(new_state, findings, now)
        from .output import write_json      # TOP100 #64 — atomic + NaN-safe
        write_json(state_path, new_state)

    # ASCII-only stdout (repo rule); markdown summary for the Actions page.
    print(f"{log_prefix} {len(findings)} finding(s), "
          f"{len(to_alert)} alerted, {len(recovered)} recovered "
          f"({'dry-run' if dry_run else 'live'}, host={host})")
    for f in findings:
        print(f"{log_prefix}   [{f['severity']}] {f['msg']}")
    for n in notes:
        print(f"{log_prefix}   (note) {n}")

    # THE RUN PAGE CARRIES IT (REFINE200 #77). Every channel in ALERT_CHANNELS
    # is unconfigured, so the dispatch above tells nobody; the annotation puts
    # the finding on the run page on the same first-alert / reminder cadence
    # (to_alert), whatever channels say. A finding raised as an alarm this run
    # is annotated too, even when it is not due a reminder here.
    if not dry_run:
        for f in to_alert + [a for a in alarm if a not in to_alert]:
            kind = "error" if f["severity"] == "CRITICAL" else "warning"
            print(_annotation(kind, f"Watchdog {f['severity']}", f["msg"]))
        if recovered:
            print(_annotation("notice", "Watchdog recovered", ", ".join(recovered)))
        for sev in ("CRITICAL", "WARNING"):
            if sev in sent:
                miss = _undelivered(config.ALERT_CHANNELS.get(sev, []), sent[sev])
                if miss:
                    print(f"{log_prefix}   (note) {sev} alert NOT delivered: {miss}")
                    notes.append(f"{sev} alert NOT delivered: {miss}")
        _write_alarm_output(alarm)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and not dry_run:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Watchdog ({host})\n\n")
            if findings:
                fh.write("| Severity | Problem |\n|---|---|\n")
                for f in findings:
                    fh.write(f"| {f['severity']} | {f['msg']} |\n")
            else:
                fh.write("All monitored pipelines fresh.\n")
            for n in notes:
                fh.write(f"\n- note: {n}")
            fh.write("\n")
    return {"findings": findings, "alerted": to_alert,
            "recovered": recovered, "sent": sent, "notes": notes,
            "alarm": alarm}


def raise_alarm(new_state: dict, findings: list[dict], now: dt.datetime,
                env=None) -> list[dict]:
    """The CRITICAL findings this run must raise as a RED RUN (REFINE200 #77).

    Only on the host that can (WATCHDOG_RAISE=1: kill_switch.yml, whose
    `watchdog-alarm` job fails on this output while the kill-switch `check`
    job stays green and keeps its cache), only while NO CRITICAL channel is
    configured (a configured one carries the alert itself), and ONCE per
    episode: the finding's state entry is stamped `raised`, the stamp rides
    the shared watchdog state, and recovery drops the entry, so the next
    episode raises again. A CRITICAL first seen by the other host (crypto_bot,
    which never raises) is raised by this one on its next run.

    The red run is GitHub's own failure email -- the one alarm that reaches
    the owner today. Failing the watchdog STEP instead was rejected: a red job
    skips actions/cache's post-save (post-if: success()), so the state that
    makes it once-per-episode would never persist and every run would go red.
    """
    env = os.environ if env is None else env
    if env.get("WATCHDOG_RAISE", "") != "1":
        return []
    if any(not channel_problem(c, env) for c in config.ALERT_CHANNELS.get("CRITICAL", [])):
        return []
    out = []
    for f in findings:
        entry = new_state.get(f["key"])
        if f["severity"] != "CRITICAL" or entry is None or entry.get("raised"):
            continue
        new_state[f["key"]] = {**entry, "raised": now.isoformat(timespec="seconds")}
        out.append(f)
    return out


def _write_alarm_output(alarm: list[dict]) -> None:
    """Hand the alarm to the workflow as one `alarm=` line in $GITHUB_OUTPUT
    (empty = no alarm). Single line by construction: messages are joined."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    text = " | ".join(f["msg"] for f in alarm).replace("\r", " ").replace("\n", " ")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"alarm={text}\n")


def test_alert() -> None:
    """Force ONE test message through every configured channel and print the
    per-channel delivery result (2026-07-21, Phase 6 P2). This is how the
    owner PROVES the alert paths actually deliver — before Phase 6 the email
    leg (GBS_SMTP_*) had never once been exercised, so a CRITICAL could have
    silently degraded to a single channel. Run locally with the secrets
    exported, or via a manual workflow dispatch. (Since the 2026-08-27
    Discord removal no push channel is configured, so this prints NOT
    delivered for every tier — it becomes the proof harness again the day
    the replacement channel lands.)"""
    host = os.environ.get("WATCHDOG_HOST", "manual")
    text = (f"[Vivek 5.0] Watchdog TEST ALERT (host: {host}) - if you can "
            f"read this, this channel delivers. No action needed.")
    for severity in ("WARNING", "CRITICAL"):
        wanted = config.ALERT_CHANNELS.get(severity, [])
        sent = _dispatch(severity, f"{text} [severity route: {severity}]")
        missing = _undelivered(wanted, sent)
        # The REAL reason per channel (REFINE200 #127): a missing secret by
        # name, the TELEGRAM_ENABLED mute, or a configured channel that failed.
        print(f"{log_prefix} test-alert {severity}: sent via "
              f"{','.join(sent) or 'NONE'}"
              + (f" - NOT delivered: {missing}" if missing else ""))


def main(argv: list[str] | None = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Vivek 5.0 freshness watchdog")
    p.add_argument("--dry-run", action="store_true",
                   help="probe and print only - no alerts, no state update")
    p.add_argument("--test-alert", action="store_true",
                   help="send one TEST message through every configured "
                        "channel and report per-channel delivery")
    args = p.parse_args(argv)
    if args.test_alert:
        test_alert()
        return
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

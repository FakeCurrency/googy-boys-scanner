# Phase 7 — Operational Automation: Grok Code Review

Vivek's Beta Scanner — prepared 2026-06-22

This document covers the genuinely **new** work added in the Phase 7 Operational
Automation pass.  Phases 5, 6, 8, 9, and 10 were implemented in prior sessions and
are **not** duplicated here (see `PHASE6_GROK_REVIEW.md` for that material).

---

## Summary of Changes

### A — API Retry / Auto-Recovery (`scanner/broker/bybit_client.py`)

`ORDER_RETRY_ATTEMPTS` and `ORDER_RETRY_BACKOFF_BASE` were already in `config.py`
but unused.  This change wires them into every Bybit API call:

- Added `_retry(fn, *args, **kwargs)` helper with exponential backoff
  (`base^attempt` seconds: 2 s, 4 s, 8 s for base=2, attempts=3)
- Wrapped every public function: `place_order`, `cancel_order`, `cancel_all_orders`,
  `get_positions`, `close_position`, `close_all_positions`, `get_order_status`,
  `get_closed_pnl`, `wallet_balance`
- Replaced `print()` in `close_all_positions` with `log.info/log.error`
- Removed duplicate `_testnet()` and `_session()` definitions that existed in the
  old file

### B — Self-Healing Circuit Breakers (`scanner/broker/circuit_breaker.py`)

Previously, a fired circuit breaker would only log/alert when it **fired**.
When the condition naturally resolved (e.g. a losing streak ended), nothing was
emitted.  This change adds:

- `_load_cb_state()` / `_save_cb_state()` — persist per-breaker fired state under
  `journal/alert_state.json["cb_state"]` so state survives across Actions runs
- In `check_all()`: after computing all checks, compare vs saved state.  For any
  breaker where `was_fired=True` and `now_ok=True`, emit `log.info` + call
  `smart_send("info", ...)` so the operator receives a clearance notification
- State is always written at the end of `check_all()` to track current condition

### C — Operational Auto-Recovery Script (`scripts/auto_recover.py`)

New CLI script for operational housekeeping:

- `expire_acks` — purge alert acknowledgments whose window has passed from
  `journal/alert_state.json`
- `ensure_dirs` — create any missing runtime directories (`journal/`, `public/data/`)
- `validate_journals` — warn if journal JSON files are absent or malformed
- `rotate_logs` — optional (requires `--rotate-logs`): truncate log files that exceed
  `HEALTH_LOG_SIZE_CRIT_MB`, keeping the last 25% of content
- Supports `--dry-run` flag: reports actions without modifying any file
- Exit code 0 = all clean; 1 = warnings present

---

## Key Design Decisions

### 1. Retry strategy: lambda wrapper vs partial

`_retry` accepts a zero-argument callable and extra `*args/**kwargs`.  Callers that
need to close over session state use `lambda:` wrappers (e.g.
`_retry(lambda: _session().place_order(**kwargs))`).

**Why not `functools.partial`?** The `_session()` call itself is expensive (creates a
new HTTPS session object) and should happen inside the retry loop so reconnection is
attempted on each try.  A `partial` would capture the session at call-site, outside
the loop.  The lambda ensures `_session()` is re-evaluated on every attempt.

### 2. CB state co-located in `alert_state.json`

Circuit breaker state is persisted under `alert_state.json["cb_state"]` alongside the
alert router's own `last_sent` and `acknowledged` keys.  A separate file would work
equally well but adds filesystem overhead.  The key is namespaced (`"cb_state"`) so
the two sets of data don't collide.

**Risk:** `circuit_breaker.py` now both reads *and* writes `alert_state.json`,
which is also read/written by `alert_router.py`.  Both use `_atomic_write()` (temp +
`os.replace()`) so concurrent writes from two processes would race safely, but a
write from one module could overwrite a concurrent write from the other.  In practice
GitHub Actions runs are sequential, so this is acceptable.

### 3. `smart_send("info", ...)` for CB clearance

CB-cleared events use event type `"info"` which maps to `INFO` severity → zero
delivery channels.  The net effect is: the clearance appears in the log (where the
operator reviews) but does not generate a Telegram/Discord push.

**Rationale:** A breaker clearing is positive news, not urgent.  Pushing a
notification for every auto-resolved condition would create alert fatigue.  The
log entry is sufficient for post-run review.

If the operator wants push notifications for clearances, they can add
`"circuit_breaker_cleared": "INFO"` (or `"WARNING"`) to `ALERT_SEVERITY` in
`config.py`.

### 4. `auto_recover.py` — rotate vs truncate

Log rotation keeps the **last 25%** of the file (configurable by changing the
`keep_frac` constant) and prepends a marker line.  This is destructive but
intentional — the script is meant to be run when logs are critically large.

An alternative (rename + compress) would be safer but requires running a background
process or cron.  GitHub Actions ephemeral runners don't persist renamed log files
between runs anyway, so in-place truncation is the practical choice.

---

## Important Code Sections

### `_retry()` in `bybit_client.py`

```python
def _retry(fn, *args, **kwargs):
    attempts = int(getattr(_cfg, "ORDER_RETRY_ATTEMPTS", 3))
    base     = float(getattr(_cfg, "ORDER_RETRY_BACKOFF_BASE", 2.0))

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == attempts:
                log.error("Bybit API failed after %d attempt(s): %s", attempts, exc)
                raise
            wait = base ** attempt
            log.warning(
                "Bybit API error (attempt %d/%d): %s — retrying in %.0fs",
                attempt, attempts, exc, wait,
            )
            time.sleep(wait)

    raise last_exc  # unreachable; satisfies type checkers
```

### Self-healing detection in `check_all()`

```python
prev_state = _load_cb_state()

# ... run all checks ...

for name, result in checks.items():
    was_fired = prev_state.get(name, False)
    now_ok    = result.get("ok", True)
    if was_fired and now_ok:
        log.info("CIRCUIT BREAKER CLEARED: %s — trading may resume", name)
        try:
            from .alert_router import smart_send
            smart_send("info", f"Circuit breaker cleared: {name}", ...)
        except Exception:
            pass

_save_cb_state({name: not r.get("ok", True) for name, r in checks.items()})
```

### `expire_acks()` in `auto_recover.py`

```python
now   = dt.datetime.now(dt.timezone.utc)
stale = []
for event_type, ack_until_raw in list(acks.items()):
    try:
        ack_until = dt.datetime.fromisoformat(ack_until_raw)
        if now >= ack_until:
            stale.append(event_type)
    except Exception:
        stale.append(event_type)  # malformed timestamp → treat as expired
```

---

## Potential Issues / Review Points

### P1 — `_save_cb_state` reads + writes alert_state.json (no file lock)

`_save_cb_state` does a read-modify-write of `alert_state.json`.  If `alert_router`
writes the same file concurrently (same bybit_run cycle, different code path), one
write will overwrite the other.  The current usage pattern (sequential execution
within a single bybit_run call) makes this safe, but it is an implicit ordering
assumption.

**Suggestion:** consolidate all reads/writes to `alert_state.json` through
`alert_router`'s `_load_state`/`_save_state` helpers.

### P2 — Retry on non-transient errors

`_retry` catches all `Exception` subclasses.  A `KeyError` or `TypeError` from a
malformed API response would be retried up to `ORDER_RETRY_ATTEMPTS` times before
raising.  This adds unnecessary latency when the error is not network-related.

**Suggestion:** inspect exception type or the Bybit API error code (available in
`pybit` exceptions via `e.status_code`) and skip retries for 4xx client errors.

### P3 — `auto_recover.py` always runs circuit_breaker checks in `health_check.py`

`_check_circuit_breakers()` in `health_check.py` calls `check_all()`, which now
*writes* to `alert_state.json` as a side effect (persisting the CB state snapshot).
Running `health_check.py` therefore mutates state, which may be unexpected for an
operator running a read-only health check.

**Suggestion:** add a `persist=False` parameter to `check_all()` to skip the
`_save_cb_state()` call when called from diagnostic tools.

### P4 — Log rotation is destructive without backup

`rotate_logs` truncates in-place.  If the operator needs the rotated-away section
for post-incident analysis, it is gone.  The current design is intentional for the
ephemeral Actions environment but should be documented.

### P5 — `ORDER_RETRY_BACKOFF_BASE` of 2.0 gives long total wait

3 attempts with base=2: waits 2 s then 4 s before the 3rd (and final) attempt.
Total worst-case blocking time = 6 s per API call.  For a fill loop that iterates
over multiple positions this could add up.  Consider whether `ORDER_RETRY_ATTEMPTS=2`
is more appropriate for time-sensitive scalp execution.

---

## Testing & Validation

### Unit tests

```
python -m pytest tests/ -q
# 74 passed in 0.89s
```

All 74 existing tests pass unchanged.  Phase 7 additions are integration-style
(they touch the Bybit HTTP session and filesystem) and do not have dedicated unit
tests yet.

### Manual validation checklist

- [ ] `BYBIT_TESTNET=true` (default) — `mode()` returns `"TESTNET"` before any live order
- [ ] Disconnect Bybit (or use invalid key) → `place_order` retries 3× and raises
- [ ] Set `ORDER_RETRY_ATTEMPTS=1` in `.env.test` → only 1 attempt, no sleep
- [ ] Manually fire a circuit breaker (set `CONSEC_LOSS_PAUSE=1`), run once, then
      clear it → second run should log `CIRCUIT BREAKER CLEARED: consecutive_losses`
- [ ] `python scripts/auto_recover.py --dry-run` → prints actions, no file modified
- [ ] `python scripts/auto_recover.py` → missing dirs created, expired acks removed
- [ ] `python scripts/auto_recover.py --rotate-logs` with a >200 MB log → truncates,
      prepends marker line

### Security checks

- **API keys never logged** — `_session()` reads from env vars; they are not passed
  through `_retry` or logged anywhere
- **Withdrawal permission must NOT be granted** on the Bybit API key
- **`BYBIT_TESTNET` defaults to `true`** — live mode requires explicit
  `BYBIT_TESTNET=false` AND `BYBIT_LIVE_CONFIRMED=true`
- `auto_recover.py` only reads/writes files under `ROOT` (the repo directory) —
  no path traversal, no external network calls

---

## File Manifest

| File | Change | Lines |
|------|--------|-------|
| `scanner/broker/bybit_client.py` | MODIFIED — added `_retry()`, wrapped all API calls | ~210 |
| `scanner/broker/circuit_breaker.py` | MODIFIED — self-healing CB state + clear notifications | ~160 |
| `scripts/auto_recover.py` | NEW — operational housekeeping script | ~165 |

---

*Document generated for Grok review — Vivek's Beta Scanner Phase 7 Operational Automation*

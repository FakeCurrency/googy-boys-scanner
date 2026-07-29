/* =========================================================================
   GBS Sync — shared "My Trades" store + optional cross-device cloud sync.

   Single source of truth for the localStorage journal (gbs:manual_journal),
   used by BOTH the journal page and the chart page so a simulated buy/sell and
   the journal always agree on schema.

   Cloud sync is OPTIONAL: if the user sets a private sync code, the journal is
   mirrored to a tiny Cloudflare KV store (functions/api/journal.js) so the same
   trades appear on phone and desktop. With no code (or no KV configured) every-
   thing still works fully offline.

   Conflict handling is "close enough": trades are unioned by id (newest mtime
   wins on a clash), deletions are tracked as tombstones so they propagate, and
   capital/brokerage follow the most recently-updated copy. No trade that exists
   on either device is ever silently dropped.
   ========================================================================= */
(function () {
  "use strict";

  const KEY = "gbs:manual_journal";
  const CODE_KEY = "gbs:sync_code";
  const API = "/api/journal";

  // ── tombstone ceiling (TOP100 #83) ─────────────────────────────────────────
  // `deleted` is an append-only list of trade ids and NOTHING had ever removed
  // an entry from it. It is unioned on every merge and round-trips through
  // localStorage AND the KV store on every sync, so it only ever grows — for
  // the life of the journal, across every device, permanently. That is a slow
  // leak with a sharp edge on the end of it: `saveLocal` writes the whole
  // journal as ONE localStorage value, so the failure at the end of the road is
  // a QuotaExceeded on a save — i.e. the trade you just typed not persisting.
  // `cache.js` refuses to store anything over 500 KB rather than risk the same
  // outcome, and its comment names it: "a silently lost trade".
  //
  // 500 ids is ~15 KB of JSON and is far past any plausible use of a manual
  // journal that holds 30 positions — this is a backstop against unbounded
  // growth, not a working limit anyone should reach.
  const TOMBSTONE_MAX = 500;

  function normalize(d) {
    d = d && typeof d === "object" ? d : {};
    if (!Array.isArray(d.trades)) d.trades = [];
    if (!Array.isArray(d.deleted)) d.deleted = [];
    // Keep the NEWEST ids, drop from the front. Age is the right axis: an old
    // tombstone has had the longest time to reach every device, so it is the
    // one whose loss is least likely to resurrect anything.
    //
    // The order is only APPROXIMATELY chronological and the approximation is
    // worth stating. Locally it is exact (journal.js appends on delete). After
    // a merge it is `[...local.deleted, ...remote.deleted]` through a Set — so
    // local's list in local order, then whatever ids only the remote had, in
    // the remote's order. No comparison against a clock happens anywhere.
    // Consequence at the extreme: two journals BOTH at the cap with no ids in
    // common resolve entirely in favour of the remote. That needs 1000
    // disjoint deletions to reach, and it is named here rather than defended
    // against, because every defence for it (a {id, ts} schema, a smarter
    // victim policy) costs the thing below.
    //
    // The elements stay BARE ID STRINGS. Older clients that have not reloaded
    // still run `data.deleted.includes(id)` and `new Set([...a.deleted])`
    // against this array, and a device mid-flight on the previous build is the
    // normal case for a store whose entire job is to be read by both.
    //
    // THE TRADE-OFF, stated rather than buried: a device offline across more
    // than TOMBSTONE_MAX deletions could re-introduce one deleted trade on its
    // next merge. That is strictly better than the failure it replaces — the
    // whole journal failing to save — and unlike that one it is visible and
    // recoverable, by deleting the row again.
    if (d.deleted.length > TOMBSTONE_MAX) d.deleted = d.deleted.slice(-TOMBSTONE_MAX);
    if (typeof d.capital !== "number") d.capital = 10000;
    if (typeof d.brokerage !== "number") d.brokerage = 10;
    // Per-asset defaults — canonical here so every caller gets consistent values.
    if (typeof d.stock_capital !== "number") d.stock_capital = 10000;
    if (typeof d.stock_brokerage !== "number") d.stock_brokerage = 10;
    if (typeof d.crypto_capital !== "number") d.crypto_capital = 10000;
    if (typeof d.crypto_brokerage !== "number") d.crypto_brokerage = 5;
    // Unified watchlists (2026-07-03): flat map "<lens>:<market>:<TICKER>" ->
    // { snap, date, mtime } for live stars, { del: mtime } for un-stars
    // (tombstones so removals propagate across devices, same as trades).
    if (!d.watchlists || typeof d.watchlists !== "object" || Array.isArray(d.watchlists)) d.watchlists = {};
    if (typeof d.updated_at !== "number") d.updated_at = 0;
    return d;
  }

  function load() {
    try { const r = localStorage.getItem(KEY); if (r) return normalize(JSON.parse(r)); } catch (_) {}
    return normalize({});
  }

  // Persist locally, stamping the journal's updated_at. Returns the saved object.
  function saveLocal(d) {
    d = normalize(d);
    d.updated_at = Date.now();
    try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {
      // Most likely QuotaExceeded — surface rather than silently losing the trade.
      try { window.dispatchEvent(new CustomEvent("gbs:save-error", { detail: String(e) })); } catch (_) {}
    }
    return d;
  }

  const getCode = () => { try { return localStorage.getItem(CODE_KEY) || ""; } catch (_) { return ""; } };
  const setCode = (c) => { try { c ? localStorage.setItem(CODE_KEY, c) : localStorage.removeItem(CODE_KEY); } catch (_) {} };

  // Union two journals by trade id; tombstoned ids are dropped from both.
  function merge(a, b) {
    // Capture raw inputs before normalizing so we can distinguish an explicitly
    // set value (present in raw) from a normalize()-filled default (absent in raw).
    const rawA = a && typeof a === "object" ? { ...a } : {};
    const rawB = b && typeof b === "object" ? { ...b } : {};
    a = normalize(a); b = normalize(b);
    const deleted = new Set([...(a.deleted || []), ...(b.deleted || [])]);
    const byId = new Map();
    for (const t of [...a.trades, ...b.trades]) {
      if (!t || !t.id || deleted.has(t.id)) continue;
      const ex = byId.get(t.id);
      // ON A TIE, THE FIRST ARGUMENT WINS (TOP100 #32). Every caller passes
      // merge(LOCAL, remote), so the first argument is the copy the user is
      // sitting in front of and can see on screen. `>=` handed the tie to
      // whichever journal came second — the remote one, always — and a tie is
      // not the rare same-millisecond race it looks like: any pair of rows
      // where NEITHER side carries an mtime ties at `0 >= 0`, which is every
      // legacy row and was every row touched by a rule-computed scale-out
      // before that path started stamping mtime. The visible copy losing to an
      // invisible one is the failure that teaches you not to trust the journal.
      // A genuine edit from another device bumps mtime, so it still wins on `>`.
      if (!ex || (t.mtime || 0) > (ex.mtime || 0)) byId.set(t.id, t);
    }
    const newer = (b.updated_at || 0) >= (a.updated_at || 0) ? b : a;
    const rNewer = newer === b ? rawB : rawA;
    const rOlder = newer === b ? rawA : rawB;
    // Explicit user setting (present as a number in raw) beats a normalize()
    // default. Prefer newer's explicit value, then older's, then normalized default.
    const pick = (f) => typeof rNewer[f] === "number" ? rNewer[f]
                      : typeof rOlder[f] === "number" ? rOlder[f]
                      : newer[f];
    // Watchlists: per-key newest mtime wins; a newer tombstone ({del}) removes,
    // a newer live star resurrects. No star set on either device is dropped.
    const wl = {};
    for (const src of [a.watchlists || {}, b.watchlists || {}]) {
      for (const [k, v] of Object.entries(src)) {
        if (!v) continue;
        const ex = wl[k];
        const vm = v.del || v.mtime || 0;
        const em = ex ? (ex.del || ex.mtime || 0) : -1;
        if (vm >= em) wl[k] = v;
      }
    }
    return normalize({
      capital:          pick("capital"),
      brokerage:        pick("brokerage"),
      stock_capital:    pick("stock_capital"),
      stock_brokerage:  pick("stock_brokerage"),
      crypto_capital:   pick("crypto_capital"),
      crypto_brokerage: pick("crypto_brokerage"),
      trades: [...byId.values()],
      deleted: [...deleted],
      watchlists: wl,
      updated_at: Math.max(a.updated_at || 0, b.updated_at || 0),
    });
  }

  // ── remote (Cloudflare KV via /api/journal) ────────────────────────────────
  async function pull() {
    const code = getCode();
    if (!code) return { ok: false, configured: null, data: null };
    try {
      // Code travels in a HEADER, not the query string (2026-07-20 security
      // pass): URLs leak via Referer, proxy logs and browser history, and the
      // code is this journal's only credential. Server still accepts ?code=
      // as a fallback for older cached clients.
      const res = await fetch(API, { cache: "no-store", headers: { "X-Sync-Code": code } });
      const j = await res.json().catch(() => null);
      if (!res.ok || !j) return { ok: false, configured: j ? j.configured : null, data: null };
      return { ok: true, configured: true, data: j.data || null };
    } catch (_) {
      return { ok: false, configured: null, data: null };
    }
  }

  // Hard daily budget for cloud writes so the free Workers KV tier (1000 puts/
  // day) can NEVER be exceeded — even if something tries to write in a loop.
  // Local storage always saves; only the cloud push is skipped once the budget
  // is spent. Counter is per-device and resets at UTC midnight.
  // TOP100 #83 — CHECKING THE BUDGET AND SPENDING IT ARE SEPARATE, and that
  // split IS the fix. The old `_putBudgetOk()` incremented the counter and THEN
  // the caller attempted the PUT, so a request that never reached the server
  // still burned a slot. Backwards, and not by a rounding error:
  // `syncOutDebounced` fires on every journal edit, so a phone editing trades
  // in a tunnel spends the whole day's budget on fetches that threw — and comes
  // back onto the network with nothing left to sync with until UTC midnight.
  // The offline stretch consumed the quota it was meant to protect and bought
  // no writes at all, which is the exact inversion of what a budget is for.
  const PUT_BUDGET = 400;
  const BUDGET_KEY = "gbs:put_budget";

  function _budgetState() {
    const day = new Date().toISOString().slice(0, 10);   // UTC date
    try {
      const raw = JSON.parse(localStorage.getItem(BUDGET_KEY) || "{}");
      return { day, used: raw.day === day ? (raw.n || 0) : 0 };
    } catch (_) {
      // An unreadable or corrupt counter reads as UNUSED, exactly as the old
      // `catch (_) { return true; }` did. This budget guards a COST, not a
      // correctness property, so a device whose storage is broken must still be
      // able to sync — failing closed here would silently un-sync it instead.
      return { day, used: 0 };
    }
  }

  // Read-only. Never writes, so it is safe to call before an attempt that may
  // not happen.
  function _putBudgetCheck() { return _budgetState().used < PUT_BUDGET; }

  // Called ONLY once the server has actually answered, because that is the
  // moment a KV write can have happened. `functions/api/journal.js` writes KV
  // inside the request — the journal itself, plus the rate-limit counters that
  // run before it — so a NON-OK response can still have cost quota and is
  // charged too: a ceiling is only a ceiling if it counts conservatively. The
  // one case charged nothing is a fetch that REJECTED. A connection dropped
  // after the server had already written is undercounted by one, which the 600
  // slots between PUT_BUDGET and the real 1000/day limit exist to absorb.
  function _putBudgetSpend() {
    try {
      const { day, used } = _budgetState();
      localStorage.setItem(BUDGET_KEY, JSON.stringify({ day, n: used + 1 }));
    } catch (_) { /* a counter we cannot write is a counter we cannot enforce */ }
  }

  async function put(d) {
    const code = getCode();
    if (!code) return { ok: false };
    if (!_putBudgetCheck()) return { ok: false, skipped: "budget" };   // stay inside the free tier
    try {
      const res = await fetch(API, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-Sync-Code": code },
        body: JSON.stringify(normalize(d)),
      });
      _putBudgetSpend();          // the server answered — quota may have moved
      const j = await res.json().catch(() => null);
      return { ok: res.ok, configured: j ? j.configured : null };
    } catch (_) {
      return { ok: false };
    }
  }

  // Pull remote → merge into local → save.
  //
  // RETURN SHAPE (2026-07-29): {ok, journal, reason?} — not the bare journal.
  // `ok` answers "did the cloud round-trip actually work", because the journal
  // page's status pill used to print "Synced at HH:MM" off the mere RETURN of
  // this function — and pull() reports failure by VALUE ({ok:false}), never by
  // throw, so a rate-limited or offline pull still "returned" and the pill lied
  // about the exact state (silent sync loss) it exists to surface. Every page
  // caller ignores the return or only fires side effects, so widening the shape
  // breaks nobody; journal.js now checks `.ok` before claiming success.
  // `ok:true` with no remote data yet is a SUCCESS (first sync of a new code).
  async function syncIn() {
    const local = load();
    if (!getCode()) return { ok: false, journal: local, reason: "no-code" };
    const r = await pull();
    if (!r.ok) return { ok: false, journal: local, reason: "pull-failed" };
    if (!r.data) return { ok: true, journal: local };
    return { ok: true, journal: saveLocal(merge(local, r.data)) };
  }

  // Merge remote first (so we never clobber remote-only trades), save, then
  // push. Same {ok, journal, reason?} shape as syncIn; `ok` requires BOTH legs
  // (a push that lands after a failed pull is only half a sync — the other
  // device's edits are still not here, so "Synced" would still be a lie).
  async function syncOut() {
    const local = load();
    if (!getCode()) return { ok: false, journal: local, reason: "no-code" };
    const r = await pull();
    const merged = r.ok && r.data ? merge(local, r.data) : local;
    saveLocal(merged);
    const pushed = await put(merged);
    const ok = !!(r.ok && pushed && pushed.ok);
    const reason = !r.ok ? "pull-failed"
      : pushed && pushed.skipped === "budget" ? "budget"
      : pushed && pushed.ok ? undefined : "push-failed";
    return reason === undefined ? { ok, journal: merged } : { ok, journal: merged, reason };
  }

  let pushT = null;
  function syncOutDebounced(ms) {
    if (!getCode()) return;
    clearTimeout(pushT);
    pushT = setTimeout(() => { syncOut().catch(() => {}); }, ms || 900);
  }

  window.GBSSync = {
    load, saveLocal, normalize, merge,
    getCode, setCode, pull, put,
    syncIn, syncOut, syncOutDebounced,
    enabled: () => !!getCode(),
  };
})();

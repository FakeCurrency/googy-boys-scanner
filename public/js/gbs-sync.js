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

  function normalize(d) {
    d = d && typeof d === "object" ? d : {};
    if (!Array.isArray(d.trades)) d.trades = [];
    if (!Array.isArray(d.deleted)) d.deleted = [];
    if (typeof d.capital !== "number") d.capital = 10000;
    if (typeof d.brokerage !== "number") d.brokerage = 10;
    // Per-asset defaults — canonical here so every caller gets consistent values.
    if (typeof d.stock_capital !== "number") d.stock_capital = 10000;
    if (typeof d.stock_brokerage !== "number") d.stock_brokerage = 10;
    if (typeof d.crypto_capital !== "number") d.crypto_capital = 10000;
    if (typeof d.crypto_brokerage !== "number") d.crypto_brokerage = 5;
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
    a = normalize(a); b = normalize(b);
    const deleted = new Set([...(a.deleted || []), ...(b.deleted || [])]);
    const byId = new Map();
    for (const t of [...a.trades, ...b.trades]) {
      if (!t || !t.id || deleted.has(t.id)) continue;
      const ex = byId.get(t.id);
      if (!ex || (t.mtime || 0) >= (ex.mtime || 0)) byId.set(t.id, t);
    }
    const newer = (b.updated_at || 0) >= (a.updated_at || 0) ? b : a;
    return normalize({
      capital: newer.capital,
      brokerage: newer.brokerage,
      // Per-asset settings: take from whichever side has them (prefer newer).
      stock_capital:    newer.stock_capital    ?? (a.stock_capital    ?? b.stock_capital),
      stock_brokerage:  newer.stock_brokerage  ?? (a.stock_brokerage  ?? b.stock_brokerage),
      crypto_capital:   newer.crypto_capital   ?? (a.crypto_capital   ?? b.crypto_capital),
      crypto_brokerage: newer.crypto_brokerage ?? (a.crypto_brokerage ?? b.crypto_brokerage),
      trades: [...byId.values()],
      deleted: [...deleted],
      updated_at: Math.max(a.updated_at || 0, b.updated_at || 0),
    });
  }

  // ── remote (Cloudflare KV via /api/journal) ────────────────────────────────
  async function pull() {
    const code = getCode();
    if (!code) return { ok: false, configured: null, data: null };
    try {
      const res = await fetch(`${API}?code=${encodeURIComponent(code)}`, { cache: "no-store" });
      const j = await res.json().catch(() => null);
      if (!res.ok || !j) return { ok: false, configured: j ? j.configured : null, data: null };
      return { ok: true, configured: true, data: j.data || null };
    } catch (_) {
      return { ok: false, configured: null, data: null };
    }
  }

  async function put(d) {
    const code = getCode();
    if (!code) return { ok: false };
    try {
      const res = await fetch(`${API}?code=${encodeURIComponent(code)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(normalize(d)),
      });
      const j = await res.json().catch(() => null);
      return { ok: res.ok, configured: j ? j.configured : null };
    } catch (_) {
      return { ok: false };
    }
  }

  // Pull remote → merge into local → save. Returns the (possibly merged) journal.
  async function syncIn() {
    const local = load();
    const r = await pull();
    if (!r.ok || !r.data) return local;
    return saveLocal(merge(local, r.data));
  }

  // Merge remote first (so we never clobber remote-only trades), save, then push.
  async function syncOut() {
    const local = load();
    const r = await pull();
    const merged = r.ok && r.data ? merge(local, r.data) : local;
    saveLocal(merged);
    await put(merged);
    return merged;
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

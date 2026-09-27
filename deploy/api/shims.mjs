/* Workers-runtime shims for running the Cloudflare Pages Functions under Node
 * (deploy/DESIGN.md D3 / section 5). The Functions are imported UNCHANGED; this
 * file supplies the four things the Workers runtime gave them for free:
 *
 *   env.JOURNAL_KV        get / put(value, {expirationTtl}) / delete (+ list),
 *                         file-backed at <state>/kv.json with per-key expiry.
 *   env.ASSETS.fetch()    the static site under VIVEK_PUBLIC_DIR, by pathname,
 *                         with traversal refused (health.js / heartbeat.js read
 *                         /data/*.json through it).
 *   globalThis.caches     .default {match, put, delete}: an in-memory LRU
 *                         honouring s-maxage (fallback max-age), capped ~50 MB.
 *                         _relay_guard.js degrades to "no cache" without it.
 *   ctx.waitUntil         collects the deferred promises (access log, cache
 *                         puts) so a graceful stop can drain them.
 *
 * Shapes follow what the Functions and their tests actually use (see
 * test/api_guards.test.js fakeKV, test/access_log.test.js). Nothing here reads
 * request bodies or logs URLs.
 */
import fs from "node:fs";
import path from "node:path";

const ZW = /^[\s﻿​-‍]+|[\s﻿​-‍]+$/g;
/* config.clean_secret's rule: trim whitespace + BOM/zero-width chars from the
 * ENDS of a pasted credential (the 2026-08-01 U+FEFF lesson). */
export function cleanSecret(v) {
  return String(v == null ? "" : v).replace(ZW, "");
}

// ── KV ───────────────────────────────────────────────────────────────────────
/* A JSON object store `{ key: { v: string, exp: epochMs|null } }` persisted
 * whole on every write. Writes are temp+rename when the directory allows it;
 * where the adapter may write ONLY the pre-created kv.json (the box's state/
 * is not writable by vivek5-api) it falls back to an in-place rewrite -- a
 * torn file costs rate-limit state and access-log rows, never the book, and
 * the loader treats unreadable JSON as empty. Expiry is lazy on read and
 * pruned on every flush. */
export function makeKV({ file, clock = () => Date.now() } = {}) {
  const store = new Map();
  let inPlace = false;
  if (file) {
    try {
      const raw = JSON.parse(fs.readFileSync(file, "utf8"));
      if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        for (const [k, rec] of Object.entries(raw)) {
          if (rec && typeof rec.v === "string") {
            store.set(k, { v: rec.v, exp: Number.isFinite(rec.exp) ? rec.exp : null });
          }
        }
      }
    } catch (_) { /* missing or unreadable -> start empty */ }
  }
  const expired = (rec) => rec.exp != null && rec.exp <= clock();
  function prune() {
    for (const [k, rec] of store) if (expired(rec)) store.delete(k);
  }
  function flush() {
    if (!file) return;
    prune();
    const obj = {};
    for (const [k, rec] of store) obj[k] = rec;
    const text = JSON.stringify(obj);
    if (!inPlace) {
      const tmp = `${file}.${process.pid}.tmp`;
      try {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(tmp, text, { mode: 0o660 });
        fs.renameSync(tmp, file);
        return;
      } catch (e) {
        if (!e || (e.code !== "EACCES" && e.code !== "EPERM")) throw e;
        try { fs.unlinkSync(tmp); } catch (_) { /* never created */ }
        inPlace = true;
        console.error(`[kv] ${path.dirname(file)} is not writable by this user; falling back to in-place writes of ${path.basename(file)}`);
      }
    }
    fs.writeFileSync(file, text, { mode: 0o660 });
  }
  function valueOf(value) {
    if (typeof value === "string") return value;
    if (value instanceof ArrayBuffer) return Buffer.from(value).toString("utf8");
    if (ArrayBuffer.isView(value)) return Buffer.from(value.buffer, value.byteOffset, value.byteLength).toString("utf8");
    return String(value);
  }
  return {
    async get(key, opts) {
      const k = String(key);
      const rec = store.get(k);
      if (!rec) return null;
      if (expired(rec)) { store.delete(k); return null; }
      const type = typeof opts === "string" ? opts : (opts && opts.type);
      if (type === "json") { try { return JSON.parse(rec.v); } catch (_) { return null; } }
      return rec.v;
    },
    async put(key, value, opts = {}) {
      const now = clock();
      let exp = null;
      if (opts && Number.isFinite(Number(opts.expirationTtl)) && Number(opts.expirationTtl) > 0) {
        exp = now + Number(opts.expirationTtl) * 1000;
      } else if (opts && Number.isFinite(Number(opts.expiration)) && Number(opts.expiration) > 0) {
        exp = Number(opts.expiration) * 1000;
      }
      store.set(String(key), { v: valueOf(value), exp });
      flush();
    },
    async delete(key) {
      if (store.delete(String(key))) flush();
    },
    async list({ prefix = "", limit = 1000 } = {}) {
      prune();
      const keys = [...store.keys()].filter((k) => k.startsWith(prefix)).sort().slice(0, limit)
        .map((name) => ({ name, expiration: store.get(name).exp == null ? undefined : Math.floor(store.get(name).exp / 1000) }));
      return { keys, list_complete: true, cursor: null };
    },
    // adapter-only helpers (not part of the Workers surface)
    _size() { prune(); return store.size; },
    _file: file,
  };
}

// ── ASSETS ───────────────────────────────────────────────────────────────────
const MIME = {
  ".json": "application/json; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".webmanifest": "application/manifest+json",
  ".map": "application/json",
  ".xml": "application/xml",
  ".csv": "text/csv; charset=utf-8",
};
export const mimeOf = (file) => MIME[path.extname(file).toLowerCase()] || "application/octet-stream";

/* `env.ASSETS.fetch(Request|URL|string)` -> Response. Serves files under
 * `publicDir` by URL pathname only (query ignored). Refuses a `..` segment
 * (403) before any filesystem call and re-checks the REAL path stays inside
 * the real public dir (symlinks), 404 for anything missing, a directory
 * serves its index.html. Method is ignored (callers only GET). */
export function makeAssets({ publicDir } = {}) {
  const root = fs.realpathSync(path.resolve(publicDir));
  const text = (status, body) => new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  return {
    async fetch(input) {
      let pathname;
      try {
        const raw = typeof input === "string" ? input : (input && input.url) || String(input);
        pathname = decodeURIComponent(new URL(raw, "http://assets.local").pathname);
      } catch (_) {
        return text(400, "bad request");
      }
      if (pathname.includes("\0") || pathname.split("/").includes("..")) return text(403, "forbidden");
      const rel = path.posix.normalize(pathname).replace(/^\/+/, "");
      let abs = path.join(root, rel);
      let real;
      try { real = fs.realpathSync(abs); } catch (_) { return text(404, "not found"); }
      if (real !== root && !real.startsWith(root + path.sep)) return text(403, "forbidden");
      let st;
      try { st = fs.statSync(real); } catch (_) { return text(404, "not found"); }
      if (st.isDirectory()) {
        real = path.join(real, "index.html");
        try { st = fs.statSync(real); } catch (_) { return text(404, "not found"); }
      }
      if (!st.isFile()) return text(404, "not found");
      let buf;
      try { buf = fs.readFileSync(real); } catch (_) { return text(404, "not found"); }
      return new Response(buf, {
        status: 200,
        headers: { "Content-Type": mimeOf(real), "Content-Length": String(buf.length) },
      });
    },
  };
}

// ── caches.default ───────────────────────────────────────────────────────────
/* In-memory LRU keyed on the full URL. Only 200s with a positive s-maxage (or
 * max-age) are stored; `no-store`/`private` never are. A match returns a FRESH
 * Response every time (a Response body reads once). Total bytes are capped;
 * the least recently used entry goes first. */
export function installCaches({ maxBytes = 50 * 1024 * 1024, clock = () => Date.now() } = {}) {
  const entries = new Map();
  let total = 0;
  const keyOf = (x) => (typeof x === "string" ? x : (x && x.url) || String(x));
  function ttlOf(headers) {
    const cc = (headers.get("cache-control") || "").toLowerCase();
    if (/\bno-store\b|\bprivate\b/.test(cc)) return 0;
    const m = /\bs-maxage=(\d+)/.exec(cc) || /\bmax-age=(\d+)/.exec(cc);
    return m ? Number(m[1]) : 0;
  }
  function drop(k) {
    const e = entries.get(k);
    if (e) { entries.delete(k); total -= e.size; }
  }
  const cache = {
    async match(req) {
      const k = keyOf(req);
      const e = entries.get(k);
      if (!e) return undefined;
      if (e.expires <= clock()) { drop(k); return undefined; }
      entries.delete(k); entries.set(k, e);            // LRU touch
      const h = new Headers(e.headers);
      h.set("Age", String(Math.max(0, Math.floor((clock() - e.stored) / 1000))));
      return new Response(e.body, { status: e.status, headers: h });
    },
    async put(req, res) {
      if (!res || res.status !== 200) return;
      const ttl = ttlOf(res.headers);
      if (ttl <= 0) return;
      const body = Buffer.from(await res.arrayBuffer());
      if (body.length > maxBytes) return;
      const k = keyOf(req);
      drop(k);
      const now = clock();
      const e = { status: res.status, headers: [...res.headers], body, size: body.length, expires: now + ttl * 1000, stored: now };
      entries.set(k, e);
      total += e.size;
      while (total > maxBytes && entries.size) drop(entries.keys().next().value);
    },
    async delete(req) { const k = keyOf(req); const had = entries.has(k); drop(k); return had; },
    _stats() { return { entries: entries.size, bytes: total, maxBytes }; },
  };
  globalThis.caches = { default: cache, open: async () => cache, _vivek: true };
  return cache;
}

// ── ctx.waitUntil ────────────────────────────────────────────────────────────
export function makeWaitUntil() {
  const pending = new Set();
  return {
    waitUntil(p) {
      const q = Promise.resolve(p).catch(() => {});
      pending.add(q);
      q.finally(() => pending.delete(q));
    },
    size() { return pending.size; },
    drain(timeoutMs = 5000) {
      let t;
      const timer = new Promise((r) => { t = setTimeout(r, timeoutMs); if (t.unref) t.unref(); });
      return Promise.race([Promise.all([...pending]), timer]).finally(() => clearTimeout(t));
    },
  };
}

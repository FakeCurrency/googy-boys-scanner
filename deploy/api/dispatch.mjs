/* /api/dispatch and /api/vps -- the two routes that are NOT Pages Functions
 * (deploy/DESIGN.md section 3.5 / section 5, security review BLOCKER 1).
 *
 * /api/dispatch is a TYPED API, not a relay. A bearer token-holder can queue
 * exactly the four (workflow, inputs) shapes the Cloudflare Functions send,
 * validated with the Functions' OWN regexes and sets (cited inline), and a
 * bot-book close is additionally checked against the book itself: the symbol
 * must be OPEN and the price inside config.VIVEK_MARK_SANITY_PCT of the row's
 * last_mark -- so a leaked token cannot book a close at 0.01 on every long.
 * Operator-only knobs (extra/args/force/dry_run) are not settable here at all;
 * the operator override is the CLI on the box. Cooldown + daily caps live in
 * the kv shim because a direct caller bypasses the Functions' KV rules, and a
 * spool-depth cap stops a flood from wedging the .path unit.
 *
 * Status matrix (test/vps_api.test.js): 503 no DISPATCH_TOKEN (never open) ·
 * 401 bad/missing bearer · 413 body over the cap · 400 unknown workflow/key/
 * bad value (nothing written) · 422 close sanity (names the mark) · 429
 * cooldown / daily cap / spool depth · 202 {ok:true,id}.
 *
 * PARITY LITERALS. The five constants below are JSON literals that
 * tests/test_vps_api_parity.py parses OUT OF THIS FILE and compares to
 * scanner/config.py (the conviction.py pattern) -- keep them on one line each,
 * valid JSON on the right-hand side, and change config first.
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

import { cleanSecret } from "./shims.mjs";

// config.VIVEK_MARK_SANITY_PCT -- the per-market band a close price may sit from last_mark
export const MARK_SANITY_PCT = {"asx": 0.35, "nasdaq": 0.35, "crypto": 0.60};
// config.VPS_DISPATCH_COOLDOWN_S -- seconds between two dispatches of one workflow+scope
export const DISPATCH_COOLDOWN_S = 300;
// config.VPS_DISPATCH_DAILY_CAPS -- dispatches per workflow per UTC day
export const DISPATCH_DAILY_CAPS = {"scan.yml": 40, "close_position.yml": 60, "morning_plays.yml": 12};
// config.VPS_SPOOL_MAX_PENDING -- more pending spool files than this answers 429
export const SPOOL_MAX_PENDING = 20;
// config.VPS_SPOOL_MAX_BYTES -- request body cap here, file size cap in the drainer
export const SPOOL_MAX_BYTES = 16384;

/* /api/vps answers 503 when one of these has last_status "failed" -- the
 * design's CRITICAL set (section 3.6): the loss guard, the backup, and the two
 * book writers. Deliberately the DESIGN's list, not config.WATCHDOG_RUNS
 * severities (there scan/crypto are WARNING because of session-aware ageing;
 * a FAILED run of a book writer is a different question from a stale one). */
export const CRITICAL_JOBS = ["kill_switch.yml", "backup_book.yml", "scan.yml", "crypto_bot.yml"];

export const SPOOL_NAME_RE = /^\d{8}T\d{6}Z-[0-9a-f]{8}\.json$/;   // scanner/vps/spool.py NAME_RE
export const DAY_TTL_S = 172800;                                    // scan.js / close.js day-counter TTL

// -- the Functions' own validators, copied not paraphrased ----------------------
const SYMBOL_RE = /^[A-Z0-9.\-]{1,15}$/;              // close.js:71 (batch) and :109 (single)
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;                // close.js:129
const MARKETS = ["asx", "nasdaq", "crypto"];          // close.js:74 / :120 (bot close markets)
const SCAN_MARKETS = ["asx", "nasdaq", "crypto", "all"]; // scan.js:44, heartbeat.js:118
const REASONS = ["manual", "heartbeat"];              // scan.yml workflow_dispatch `reason` choices
const SLOTS = ["asx", "us"];                          // morning_plays.js:45 VALID_SLOTS
const JOURNAL_TYPES = ["bot", "swing", "scalp"];      // close.js:118 (bot / scalp / else swing)
const DIRECTIONS = ["long", "short"];                 // close.js:85 / :126
const BATCH_MIN = 1, BATCH_MAX = 30;                  // close.js:62

export class DispatchRefused extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const refuse = (status, message) => { throw new DispatchRefused(status, message); };

/* A scalar the Functions would have String()-ed: strings and finite numbers
 * only. Objects, arrays, booleans and null are refused -- the spool must stay
 * canonical and the drainer re-validates the same shapes. */
function scalar(v, name) {
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return refuse(400, `${name} must be a string`);
}
function oneOf(v, allowed, name, { lower = true } = {}) {
  let s = scalar(v, name).trim();
  if (lower) s = s.toLowerCase();
  if (!allowed.includes(s)) refuse(400, `${name} must be one of ${allowed.join("|")}`);
  return s;
}
function onlyKeys(obj, allowed, workflow) {
  const extra = Object.keys(obj).filter((k) => !allowed.includes(k));
  if (extra.length) refuse(400, `${workflow}: unknown input(s) ${extra.sort().join(", ")}`);
}
function positivePrice(v, name) {
  const px = typeof v === "number" ? v : parseFloat(scalar(v, name));
  if (!Number.isFinite(px) || px <= 0) refuse(400, `${name} must be a positive number`);
  return px;
}

/* One batch entry, re-serialised exactly as close.js does (four keys, that
 * order of validation, price as a string). */
function closeEntry(c) {
  if (!c || typeof c !== "object" || Array.isArray(c)) refuse(400, "batch entry is not an object");
  const sym = String(c.symbol == null ? "" : c.symbol).trim().toUpperCase();
  const mkt = String(c.market == null ? "" : c.market).trim().toLowerCase();
  const px = parseFloat(c.price);
  if (!SYMBOL_RE.test(sym) || !Number.isFinite(px) || px <= 0) {
    refuse(400, `Batch entry ${sym || "?"}: symbol and a positive price are required.`);
  }
  if (!MARKETS.includes(mkt)) refuse(400, `Batch entry ${sym}: market must be asx|nasdaq|crypto.`);
  return { symbol: sym, market: mkt, direction: c.direction === "short" ? "short" : "long", price: String(px) };
}

/* Validate a wire body `{workflow, inputs}`. Returns the CANONICAL spool
 * fields `{workflow, inputs, source, scope}` or throws DispatchRefused(400). */
export function validateDispatch(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) refuse(400, "body must be a JSON object");
  onlyKeys(body, ["workflow", "inputs"], "dispatch");
  const workflow = typeof body.workflow === "string" ? body.workflow : refuse(400, "workflow must be a string");
  const inputs = body.inputs == null ? {} : body.inputs;
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) refuse(400, "inputs must be an object");

  if (workflow === "scan.yml") {
    onlyKeys(inputs, ["market", "reason"], workflow);
    const market = oneOf(inputs.market, SCAN_MARKETS, "market");
    const reason = inputs.reason === undefined ? "manual" : oneOf(inputs.reason, REASONS, "reason");
    return { workflow, inputs: { market, reason }, scope: market,
             source: reason === "heartbeat" ? "api/heartbeat" : "api/scan" };
  }

  if (workflow === "close_position.yml") {
    onlyKeys(inputs, ["symbol", "market", "direction", "price", "exit_date", "journal_type", "batch", "closes"], workflow);
    const journalType = oneOf(inputs.journal_type, JOURNAL_TYPES, "journal_type", { lower: false });
    let raw = inputs.closes;
    if (raw === undefined && inputs.batch !== undefined) {
      try { raw = JSON.parse(scalar(inputs.batch, "batch")); } catch (_) { refuse(400, "batch is not a JSON array"); }
    }
    if (raw !== undefined) {
      if (journalType !== "bot") refuse(400, "Batch close is bot-book only.");
      if (!Array.isArray(raw) || raw.length < BATCH_MIN || raw.length > BATCH_MAX) refuse(400, "Batch must contain 1-30 closes.");
      const entries = [];
      const seen = new Set();
      for (const c of raw) {
        const e = closeEntry(c);
        const key = e.market + ":" + e.symbol;
        if (seen.has(key)) refuse(400, `Batch lists ${e.symbol} twice.`);
        seen.add(key);
        entries.push(e);
      }
      return {
        workflow, scope: "batch", source: "api/close",
        inputs: {
          symbol: entries[0].symbol + (entries.length > 1 ? `+${entries.length - 1}` : ""),
          direction: "long", market: entries[0].market, price: entries[0].price,
          exit_date: "", journal_type: "bot", batch: JSON.stringify(entries),
        },
      };
    }
    const symbol = scalar(inputs.symbol, "symbol").trim().toUpperCase();
    if (!SYMBOL_RE.test(symbol)) refuse(400, "symbol and a positive price are required.");
    const price = positivePrice(inputs.price, "price");
    const market = oneOf(inputs.market, MARKETS, "market");
    const direction = inputs.direction === undefined ? "long" : oneOf(inputs.direction, DIRECTIONS, "direction");
    const exitDate = inputs.exit_date === undefined ? "" : scalar(inputs.exit_date, "exit_date").trim();
    if (exitDate && !DATE_RE.test(exitDate)) refuse(400, "exit_date must be YYYY-MM-DD or empty");
    return {
      workflow, scope: symbol, source: "api/close",
      inputs: { symbol, direction, market, price: String(price), exit_date: exitDate, journal_type: journalType },
    };
  }

  if (workflow === "morning_plays.yml") {
    onlyKeys(inputs, ["slot"], workflow);
    const slot = oneOf(inputs.slot, SLOTS, "slot");
    return { workflow, inputs: { slot }, scope: slot, source: "api/morning_plays" };
  }

  // momentum.yml is the runner's INTERNAL chain (morning_plays spools it) and
  // every other workflow is operator-only: nothing else is reachable here.
  return refuse(400, `unknown workflow ${JSON.stringify(String(workflow).slice(0, 40))}`);
}

// -- close sanity against the book -------------------------------------------
export function loadBook(bookPath) {
  try {
    const doc = JSON.parse(fs.readFileSync(bookPath, "utf8"));
    if (!doc || typeof doc !== "object" || !Array.isArray(doc.open)) throw new Error("no open[]");
    return doc;
  } catch (_) {
    return refuse(503, "The bot book is unreadable on the box - closes are refused until it is.");
  }
}

/* Every close in `inputs` (single or batch) must name an OPEN row of the book
 * and quote a price inside MARK_SANITY_PCT[market] of that row's last_mark.
 * Throws DispatchRefused(422) naming the symbol and the mark. */
export function checkCloseSanity(inputs, book) {
  const closes = inputs.batch ? JSON.parse(inputs.batch) : [{ symbol: inputs.symbol, market: inputs.market, price: inputs.price }];
  for (const c of closes) {
    const row = book.open.find((r) => r && r.symbol === c.symbol && r.market === c.market
      && String(r.status || "open") === "open");
    if (!row) refuse(422, `${c.symbol} (${c.market}) is not an open position in the bot book.`);
    const mark = Number(row.last_mark);
    if (!Number.isFinite(mark) || mark <= 0) refuse(422, `${c.symbol} has no last_mark in the book to check the price against.`);
    const px = Number(c.price);
    const band = MARK_SANITY_PCT[c.market];
    const dev = Math.abs(px / mark - 1);
    if (!(dev <= band)) {
      refuse(422, `${c.symbol} price ${px} is ${(dev * 100).toFixed(1)}% from the book's last mark ${mark} (band +-${Math.round(band * 100)}%).`);
    }
  }
}

// -- the spool ---------------------------------------------------------------
export function spoolDirs(stateDir) {
  const spool = path.join(stateDir, "spool");
  return { spool, tmp: path.join(spool, ".tmp") };
}
export function pendingCount(stateDir) {
  const { spool } = spoolDirs(stateDir);
  try {
    return fs.readdirSync(spool, { withFileTypes: true })
      .filter((d) => d.isFile() && SPOOL_NAME_RE.test(d.name)).length;
  } catch (_) {
    return 0;
  }
}
export function spoolId(now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";   // YYYYMMDDTHHMMSSZ
  return `${stamp}-${crypto.randomBytes(4).toString("hex")}`;
}
/* Body, and nothing else: {id, received_at, workflow, inputs, source}.
 * Written to spool/.tmp/<id>.json then rename()d into spool/ (atomic; the
 * .path unit's DirectoryNotEmpty= only ever sees complete files). */
export function writeSpool(stateDir, { workflow, inputs, source }, now = new Date()) {
  const { spool, tmp } = spoolDirs(stateDir);
  fs.mkdirSync(tmp, { recursive: true });
  const id = spoolId(now);
  const body = {
    id,
    received_at: now.toISOString().replace(/\.\d{3}Z$/, "Z"),
    workflow,
    inputs,
    source,
  };
  const tmpPath = path.join(tmp, `${id}.json`);
  fs.writeFileSync(tmpPath, JSON.stringify(body) + "\n", { mode: 0o660 });
  fs.renameSync(tmpPath, path.join(spool, `${id}.json`));
  return id;
}

// -- auth ----------------------------------------------------------------------
/* Bearer from the Authorization header ONLY (never a query string -- Caddy and
 * journald would keep it); constant-time compare on equal-length buffers. */
export function bearerMatches(header, expected) {
  const h = String(header || "");
  if (!h.startsWith("Bearer ")) return false;
  const a = Buffer.from(h.slice(7), "utf8");
  const b = Buffer.from(expected, "utf8");
  return a.length === b.length && a.length > 0 && crypto.timingSafeEqual(a, b);
}

const json = (status, body) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
});

/* POST /api/dispatch. `ctx` = { env, kv, stateDir, bookPath, clock }. */
export async function handleDispatch(request, ctx) {
  if (request.method !== "POST") return json(404, { ok: false, error: "Not Found" });
  const expected = cleanSecret(ctx.env && ctx.env.DISPATCH_TOKEN);
  if (!expected) {
    return json(503, { ok: false, configured: false, message: "DISPATCH_TOKEN is not set on the VPS - /api/dispatch is disabled." });
  }
  if (!bearerMatches(request.headers.get("Authorization"), expected)) {
    return json(401, { ok: false, message: "Unauthorized." });
  }
  let text;
  try { text = await request.text(); } catch (_) { return json(400, { ok: false, message: "Unreadable body." }); }
  if (Buffer.byteLength(text, "utf8") > SPOOL_MAX_BYTES) {
    return json(413, { ok: false, message: `Body exceeds ${SPOOL_MAX_BYTES} bytes.` });
  }
  let body;
  try { body = JSON.parse(text); } catch (_) { return json(400, { ok: false, message: "Invalid JSON body." }); }

  let v;
  try {
    v = validateDispatch(body);
    if (v.workflow === "close_position.yml" && v.inputs.journal_type === "bot") {
      checkCloseSanity(v.inputs, loadBook(ctx.bookPath));
    }
  } catch (e) {
    if (e instanceof DispatchRefused) return json(e.status, { ok: false, message: e.message });
    throw e;
  }

  // Abuse guard, the Functions' pattern: written BEFORE the spool write (closes
  // the double-click race), refunded if the write fails. Separate key space
  // from the Functions' own ratelimit:* keys so Phase 2 (adapter -> itself)
  // never double-blocks a legitimate first request.
  const kv = ctx.kv;
  const now = new Date(ctx.clock ? ctx.clock() : Date.now());
  const cdKey = `vps:dispatch:cooldown:${v.workflow}:${v.scope}`;
  const dayKey = `vps:dispatch:day:${v.workflow}:${now.toISOString().slice(0, 10)}`;
  if (await kv.get(cdKey)) {
    return json(429, { ok: false, message: `${v.workflow} for ${v.scope} was dispatched in the last ${Math.round(DISPATCH_COOLDOWN_S / 60)} minutes - it is queued or running.` });
  }
  const used = parseInt((await kv.get(dayKey)) || "0", 10) || 0;
  const cap = DISPATCH_DAILY_CAPS[v.workflow];
  if (used >= cap) {
    return json(429, { ok: false, message: `Daily ${v.workflow} dispatch cap (${cap}) reached on the VPS.` });
  }
  const depth = pendingCount(ctx.stateDir);
  if (depth > SPOOL_MAX_PENDING) {
    return json(429, { ok: false, message: `${depth} dispatches are already waiting on the VPS (cap ${SPOOL_MAX_PENDING}) - the runner is behind; try later.` });
  }
  await kv.put(cdKey, "1", { expirationTtl: DISPATCH_COOLDOWN_S });
  await kv.put(dayKey, String(used + 1), { expirationTtl: DAY_TTL_S });
  let id;
  try {
    id = writeSpool(ctx.stateDir, v, now);
  } catch (e) {
    try { await kv.delete(cdKey); await kv.put(dayKey, String(used), { expirationTtl: DAY_TTL_S }); } catch (_) { /* best-effort */ }
    throw e;
  }
  return json(202, { ok: true, id });
}

// -- /api/vps ------------------------------------------------------------------
const VPS_ROW_FIELDS = ["last_status", "last_start", "last_end", "last_exit", "last_success_at",
                        "last_failure_at", "last_skip_at", "last_halt_at", "consecutive_failures",
                        "waited_s", "pushed", "host"];

/* GET /api/vps -> {ok, halted, failed, jobs, checked_at} from runs.json; 503
 * when state/HALT exists or a CRITICAL job's last run failed. Rows are
 * projected to status/timestamps only (no last_line, no args): this route is
 * open in Phase 1. */
export async function handleVps(request, ctx) {
  if (request.method !== "GET" && request.method !== "HEAD") return json(404, { ok: false, error: "Not Found" });
  const ledgerPath = ctx.ledgerPath || path.join(ctx.stateDir, "runs.json");
  let ledger = {};
  try {
    const doc = JSON.parse(fs.readFileSync(ledgerPath, "utf8"));
    if (doc && typeof doc === "object" && !Array.isArray(doc)) ledger = doc;
  } catch (_) { /* no ledger yet -> no jobs */ }
  const jobs = {};
  for (const [k, row] of Object.entries(ledger)) {
    if (!row || typeof row !== "object") continue;
    const out = {};
    for (const f of VPS_ROW_FIELDS) if (row[f] !== undefined) out[f] = row[f];
    jobs[k] = out;
  }
  const halted = fs.existsSync(path.join(ctx.stateDir, "HALT"));
  const failed = CRITICAL_JOBS.filter((j) => jobs[j] && jobs[j].last_status === "failed");
  const ok = !halted && failed.length === 0;
  const checked = new Date(ctx.clock ? ctx.clock() : Date.now()).toISOString().replace(/\.\d{3}Z$/, "Z");
  return json(ok ? 200 : 503, { ok, halted, failed, jobs, checked_at: checked });
}

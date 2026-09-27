#!/usr/bin/env node
/* The VPS API adapter (deploy/DESIGN.md section 5): the Cloudflare Pages
 * Functions under Node 22, unchanged, behind Caddy.
 *
 *   node deploy/api/server.mjs          (vivek5-api.service; env from api.env)
 *
 * Binds 127.0.0.1:PORT only. Routes /api/<name> to functions/api/<name>.js,
 * imported ONCE at startup from the directory listing (never from the URL):
 * onRequest<Method> first, then onRequest, else 404 -- Pages' own semantics,
 * where a method with no handler falls through to static assets and 404s
 * rather than 405. Each request becomes a WHATWG Request (full URL from the
 * Host header, headers, body bytes) with CF-Connecting-IP set by the XFF rule:
 * TRUST_PROXY=1 AND the TCP peer is loopback -> the LAST X-Forwarded-For hop
 * (the one Caddy appended); otherwise the socket address. A client-sent
 * CF-Connecting-IP is always dropped.
 *
 * VIVEK_PHASE=1 exposes ONLY /api/dispatch and /api/vps (Cloudflare still
 * serves the site and its Functions); VIVEK_PHASE=2 exposes every Function
 * too. Anything else 404s. Unset/invalid reads as phase 1 -- the least
 * exposure. The request log is method + path + status, never the query
 * string (morning_plays' ?key= would otherwise land in journald). An unhandled
 * error answers 500 JSON with no stack.
 *
 * `createServer(options)` is exported so tests start the real thing on an
 * ephemeral port with temp state/public dirs and a fixture book.
 */
import http from "node:http";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { makeKV, makeAssets, installCaches, makeWaitUntil } from "./shims.mjs";
import { handleDispatch, handleVps } from "./dispatch.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
export const DEFAULT_FUNCTIONS_DIR = path.join(REPO, "functions", "api");
export const ADAPTER_ROUTES = ["/api/dispatch", "/api/vps"];
export const MAX_BODY_BYTES = 1024 * 1024;

// Hop-by-hop and framing headers that must not be copied onto the inner
// Request (undici recomputes framing; Host is the URL), plus the two
// Cloudflare identity headers a client must never be allowed to supply.
const DROP_HEADERS = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
  "trailer", "transfer-encoding", "upgrade", "host", "content-length", "expect",
  "cf-connecting-ip", "cf-ipcountry",
]);

// ── client address rules (pure; unit-tested directly) ───────────────────────
export function normaliseIp(addr) {
  let s = String(addr == null ? "" : addr).trim();
  if (s.startsWith("[") && s.includes("]")) s = s.slice(1, s.indexOf("]"));
  if (/^::ffff:\d{1,3}(\.\d{1,3}){3}$/i.test(s)) s = s.slice(7);
  return s;
}
export function isLoopback(addr) {
  const s = normaliseIp(addr);
  return s === "::1" || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(s);
}
/* CF-Connecting-IP for the inner Request. `xff` is honoured only when the
 * proxy is trusted AND the peer is loopback, and then only its LAST hop. */
export function clientIp({ peer, xff, trustProxy }) {
  const p = normaliseIp(peer);
  if (trustProxy && isLoopback(p) && xff) {
    const hops = String(Array.isArray(xff) ? xff[xff.length - 1] : xff).split(",").map((h) => h.trim()).filter(Boolean);
    const last = hops.length ? normaliseIp(hops[hops.length - 1]) : "";
    if (last && net.isIP(last)) return last;
  }
  return p || "unknown";
}

// ── Functions loader ────────────────────────────────────────────────────────
/* Map "/api/<name>" -> { GET: fn, POST: fn, HEAD: fn, "*": onRequest }.
 * Helpers (leading underscore) are not routable; a module with no handler
 * export is not routable either. */
export async function loadFunctions(dir) {
  const routes = new Map();
  for (const name of fs.readdirSync(dir).sort()) {
    if (!name.endsWith(".js") || name.startsWith("_")) continue;
    const mod = await import(pathToFileURL(path.join(dir, name)).href);
    const table = {};
    for (const [k, v] of Object.entries(mod)) {
      if (typeof v !== "function") continue;
      if (k === "onRequest") table["*"] = v;
      else if (k.startsWith("onRequest")) table[k.slice("onRequest".length).toUpperCase()] = v;
    }
    if (Object.keys(table).length) routes.set(`/api/${name.slice(0, -3)}`, table);
  }
  return routes;
}

const HOST_RE = /^([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])(:\d{1,5})?$/;

const jsonResponse = (status, body) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const notFound = () => jsonResponse(404, { ok: false, error: "Not Found" });

function readBody(req, max) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let n = 0;
    req.on("data", (c) => {
      n += c.length;
      if (n > max) {
        req.pause();
        reject(Object.assign(new Error("payload too large"), { httpStatus: 413 }));
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function sendResponse(res, response, isHead) {
  res.statusCode = response.status;
  for (const [k, v] of response.headers) {
    if (k === "set-cookie") continue;
    res.setHeader(k, v);
  }
  const cookies = typeof response.headers.getSetCookie === "function" ? response.headers.getSetCookie() : [];
  if (cookies.length) res.setHeader("set-cookie", cookies);
  if (isHead || !response.body) { res.end(); return; }
  for await (const chunk of response.body) {
    if (!res.write(chunk)) await new Promise((r) => res.once("drain", r));
  }
  res.end();
}

// ── the server ──────────────────────────────────────────────────────────────
export async function createServer(options = {}) {
  const env = { ...(options.env || process.env) };
  const phase = String(options.phase ?? env.VIVEK_PHASE ?? "1").trim() === "2" ? 2 : 1;
  const trustProxy = String(options.trustProxy ?? env.TRUST_PROXY ?? "0").trim() === "1";
  const stateDir = path.resolve(options.stateDir || env.VIVEK_STATE_DIR || path.join(REPO, ".vps-state"));
  const publicDir = path.resolve(options.publicDir || env.VIVEK_PUBLIC_DIR || path.join(REPO, "public"));
  const bookPath = path.resolve(options.bookPath || env.VIVEK_BOOK || path.join(REPO, "journal", "vivek_bot_book.json"));
  const ledgerPath = path.resolve(options.ledgerPath || env.VIVEK_RUNS_LEDGER || path.join(stateDir, "runs.json"));
  const functionsDir = path.resolve(options.functionsDir || DEFAULT_FUNCTIONS_DIR);
  const clock = options.clock || (() => Date.now());
  const log = options.log || ((line) => console.log(line));

  const kv = makeKV({ file: path.join(stateDir, "kv.json"), clock });
  const assets = makeAssets({ publicDir });
  const caches = (globalThis.caches && globalThis.caches._vivek) ? globalThis.caches.default : installCaches({ clock });
  const waits = makeWaitUntil();
  const routes = phase === 2 ? await loadFunctions(functionsDir) : new Map();
  const fnEnv = { ...env, JOURNAL_KV: kv, ASSETS: assets };
  const dispatchCtx = { env, kv, stateDir, bookPath, ledgerPath, clock };

  // PORT unset/blank -> 8787; an explicit PORT=0 means an ephemeral port (tests).
  let boundPort = env.PORT === undefined || String(env.PORT).trim() === "" ? 8787 : Number(env.PORT);
  if (!Number.isInteger(boundPort) || boundPort < 0 || boundPort > 65535) throw new Error(`PORT=${env.PORT} is not a port`);

  async function route(request, method, pathname) {
    if (pathname === "/api/dispatch") {
      return method === "POST" ? handleDispatch(request, dispatchCtx) : notFound();
    }
    if (pathname === "/api/vps") {
      return (method === "GET" || method === "HEAD") ? handleVps(request, dispatchCtx) : notFound();
    }
    const table = routes.get(pathname);
    if (!table) return notFound();
    const fn = table[method] || table["*"];
    if (!fn) return notFound();
    const ctx = {
      request, env: fnEnv, waitUntil: waits.waitUntil, passThroughOnException() {},
      params: {}, data: {}, functionPath: pathname, next: async () => notFound(),
    };
    const out = await fn(ctx);
    if (!(out instanceof Response)) throw new Error("handler returned a non-Response");
    return out;
  }

  async function handle(req, res) {
    res.on("error", () => {});
    const method = String(req.method || "GET").toUpperCase();
    const rawUrl = String(req.url || "/");
    let pathname = "/";
    try { pathname = new URL(rawUrl, "http://placeholder").pathname; } catch (_) { /* logged as "/" */ }
    let status = 500;
    try {
      if (!rawUrl.startsWith("/")) throw Object.assign(new Error("bad request-target"), { httpStatus: 400 });
      const body = await readBody(req, MAX_BODY_BYTES);
      const peer = req.socket && req.socket.remoteAddress;
      const ip = clientIp({ peer, xff: req.headers["x-forwarded-for"], trustProxy });
      const headers = new Headers();
      for (const [k, v] of Object.entries(req.headers)) {
        if (DROP_HEADERS.has(k) || v == null) continue;
        if (Array.isArray(v)) for (const x of v) headers.append(k, x);
        else headers.set(k, v);
      }
      headers.set("CF-Connecting-IP", ip);
      const trusted = trustProxy && isLoopback(peer);
      const proto = trusted && String(req.headers["x-forwarded-proto"] || "").toLowerCase() === "https" ? "https" : "http";
      const hostHdr = String(req.headers.host || "").trim();
      const host = HOST_RE.test(hostHdr) ? hostHdr : `127.0.0.1:${boundPort}`;
      const request = new Request(`${proto}://${host}${rawUrl}`, {
        method, headers, body: (method === "GET" || method === "HEAD") ? undefined : body,
      });
      const response = await route(request, method, pathname);
      status = response.status;
      await sendResponse(res, response, method === "HEAD");
    } catch (err) {
      status = (err && err.httpStatus) || 500;
      if (status === 500) console.error(`[api] ${method} ${pathname} 500 ${(err && err.name) || "Error"}: ${(err && err.message) || err}`);
      if (res.headersSent) { res.destroy(); }
      else {
        res.statusCode = status;
        res.setHeader("Content-Type", "application/json");
        if (status === 413) res.setHeader("Connection", "close");
        res.end(JSON.stringify({ ok: false, error: status === 413 ? "Payload too large" : status === 400 ? "Bad request" : "Internal error" }));
        if (status === 413) res.once("finish", () => req.destroy());
      }
    } finally {
      log(`${method} ${pathname} ${status}`);
    }
  }

  const server = http.createServer((req, res) => { handle(req, res).catch(() => { try { res.destroy(); } catch (_) {} }); });
  server.keepAliveTimeout = 5000;
  server.headersTimeout = 30000;
  server.requestTimeout = 60000;

  const api = {
    server, phase, routes, kv, caches, waits, stateDir, publicDir, bookPath, ledgerPath,
    url: null,
    listen(port = boundPort) {
      return new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, "127.0.0.1", () => {
          server.off("error", reject);
          boundPort = server.address().port;
          api.url = `http://127.0.0.1:${boundPort}`;
          resolve(api.url);
        });
      });
    },
    async close() {
      await new Promise((resolve) => server.close(() => resolve()));
      if (typeof server.closeAllConnections === "function") server.closeAllConnections();
      await waits.drain();
    },
  };
  return api;
}

// ── entrypoint ──────────────────────────────────────────────────────────────
const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  const api = await createServer();
  const url = await api.listen();
  console.log(`vivek5-api listening on ${url} (phase ${api.phase}, ${api.routes.size} functions routed, state ${api.stateDir})`);
  const stop = (sig) => {
    console.log(`vivek5-api: ${sig}, draining`);
    api.close().then(() => process.exit(0), () => process.exit(0));
    setTimeout(() => process.exit(0), 8000).unref();
  };
  process.on("SIGTERM", () => stop("SIGTERM"));
  process.on("SIGINT", () => stop("SIGINT"));
}

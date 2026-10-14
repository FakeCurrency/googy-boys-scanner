#!/usr/bin/env node
/* public/_headers — what Cloudflare Pages actually sends (REFINE200 #56 / #75,
 * 2026-10-14).
 *
 * WHY THIS FILE EXISTS: the file claimed "more-specific paths below win on
 * Cloudflare Pages". They do not. Pages applies EVERY matching rule in file
 * order and JOINS a header two rules both set with a comma, so /js/* went out
 * as "public, max-age=0, must-revalidate, public, max-age=86400" and caches
 * read the first max-age: the scripts were never cached at all. A rule that
 * replaces a header must first detach the inherited one ("! Header"), which
 * Pages applies before that rule's own values.
 *
 * This suite resolves the file with those rules (combine() below) and pins the
 * headers each kind of path ends up with, plus the precondition the year-long
 * immutable cache stands on: every /js/ and /css/ reference carries a ?v=.
 */
"use strict";
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const PUB = path.join(__dirname, "..", "public");
const HEADERS = fs.readFileSync(path.join(PUB, "_headers"), "utf8");

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log(`  ✓  ${name}`); passed++; }
  catch (e) { console.error(`  ✗  ${name}\n     ${e.message}`); failed++; }
}

/* Parse into [{path, regex, set: [[name, value]], unset: [name]}], file order. */
function parse(text) {
  const rules = [];
  for (const raw of text.split("\n")) {
    if (!raw.trim() || raw.trim().startsWith("#")) continue;
    if (!/^\s/.test(raw)) {
      const p = raw.trim();
      const re = new RegExp("^" + p.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
      rules.push({ path: p, re, set: [], unset: [] });
      continue;
    }
    const line = raw.trim();
    assert.ok(rules.length, "a header line before any path: " + line);
    const rule = rules[rules.length - 1];
    if (line.startsWith("!")) { rule.unset.push(line.slice(1).trim().toLowerCase()); continue; }
    const i = line.indexOf(":");
    assert.ok(i > 0, "not a header line: " + line);
    rule.set.push([line.slice(0, i).trim().toLowerCase(), line.slice(i + 1).trim()]);
  }
  return rules;
}
const RULES = parse(HEADERS);

/* The headers Pages sends for `pathname`, by the documented combination rules. */
function combine(pathname) {
  const out = new Map();
  for (const r of RULES.filter((x) => x.re.test(pathname))) {
    for (const name of r.unset) out.delete(name);
    for (const [name, value] of r.set) out.set(name, out.has(name) ? out.get(name) + ", " + value : value);
  }
  return out;
}

const REVALIDATE = "public, max-age=0, must-revalidate";
const IMMUTABLE = "public, max-age=31536000, immutable";
const PAGES = ["/", "/index.html", "/journal", "/chart.html", "/sw.js", "/manifest.json", "/version.json", "/offline.html"];
const DATA = ["/data/asx_vivek.json", "/data/ignition/crypto.json", "/data/vivek_bot_book.json"];
const VERSIONED = ["/js/app.js", "/css/styles.css", "/vendor/lightweight-charts-4.1.3.js", "/fonts/inter-400.woff2"];

console.log("\n── caching: one value per path, never a joined pair ──");

test("HTML, sw.js and the root files revalidate on every load", () => {
  for (const p of PAGES) assert.equal(combine(p).get("cache-control"), REVALIDATE, p);
});

test("scan data revalidates on every load (rewritten every scan)", () => {
  for (const p of DATA) assert.equal(combine(p).get("cache-control"), REVALIDATE, p);
});

test("versioned assets are cached for a year, immutable, with no revalidate directive joined in", () => {
  for (const p of VERSIONED) assert.equal(combine(p).get("cache-control"), IMMUTABLE, p);
});

test("no path ends up with two values joined into one Cache-Control", () => {
  for (const p of [...PAGES, ...DATA, ...VERSIONED]) {
    const cc = combine(p).get("cache-control");
    assert.equal((cc.match(/max-age=/g) || []).length, 1, `${p}: ${cc}`);
  }
});

test("every rule that sets Cache-Control after /* detaches the inherited one first", () => {
  const all = RULES.findIndex((r) => r.path === "/*");
  assert.equal(all, 0, "/* must come first: rules apply in file order");
  for (const r of RULES.slice(1)) {
    if (r.set.some(([n]) => n === "cache-control")) {
      assert.ok(r.unset.includes("cache-control"), `${r.path} would JOIN its Cache-Control onto /*'s`);
    }
  }
});

console.log("\n── security headers on every page (REFINE200 #56) ──");

test("frame-ancestors 'self', SAMEORIGIN, strict-origin-when-cross-origin, nosniff — everywhere", () => {
  for (const p of [...PAGES, ...DATA, ...VERSIONED]) {
    const h = combine(p);
    assert.equal(h.get("content-security-policy"), "frame-ancestors 'self'", p);
    assert.equal(h.get("x-frame-options"), "SAMEORIGIN", p);
    assert.equal(h.get("referrer-policy"), "strict-origin-when-cross-origin", p);
    assert.equal(h.get("x-content-type-options"), "nosniff", p);
  }
});

test("the CSP is frame-ancestors ONLY — a full policy is a separate, deliberate change", () => {
  // A script-src/default-src here would break the inline scripts and the
  // TradingView/Binance fetches the pages make; nothing has audited that.
  for (const r of RULES) {
    for (const [n, v] of r.set) {
      if (n === "content-security-policy") assert.equal(v, "frame-ancestors 'self'", r.path);
    }
  }
});

console.log("\n── the precondition for immutable caching ──");

test("every /js/ and /css/ reference in a page carries a ?v=", () => {
  const bare = [];
  for (const f of fs.readdirSync(PUB).filter((x) => x.endsWith(".html"))) {
    const html = fs.readFileSync(path.join(PUB, f), "utf8");
    for (const m of html.matchAll(/(?:src|href)\s*=\s*["']([^"']*\b(?:js|css)\/[^"']+)["']/g)) {
      if (!/\?v=\d+$/.test(m[1])) bare.push(`${f}: ${m[1]}`);
    }
  }
  assert.deepEqual(bare, [], "an unversioned asset would be pinned for a year:\n" + bare.join("\n"));
});

test("no script or stylesheet loads a /js/ or /css/ file by a string without ?v=", () => {
  const bare = [];
  const files = [...fs.readdirSync(path.join(PUB, "js")).map((f) => path.join(PUB, "js", f)),
                 ...fs.readdirSync(path.join(PUB, "css")).map((f) => path.join(PUB, "css", f)),
                 path.join(PUB, "sw.js")];
  for (const f of files) {
    const code = fs.readFileSync(f, "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:])\/\/.*$/gm, "$1");
    for (const m of code.matchAll(/["'`(]\/?(?:js|css)\/[\w.-]+\.(?:js|css)(\?v=\d+)?/g)) {
      if (!m[1]) bare.push(`${path.relative(PUB, f)}: ${m[0]}`);
    }
  }
  assert.deepEqual(bare, [], bare.join("\n"));
});

test("vendor files carry their version in the file name", () => {
  for (const f of fs.readdirSync(path.join(PUB, "vendor"))) {
    assert.match(f, /\d+\.\d+\.\d+/, `vendor/${f} has no version in its name`);
  }
});

test("every font a page preloads or a stylesheet names exists (fonts are never edited in place)", () => {
  // Pages preload fonts by bare name, so a font is cached a year under that
  // name: change a font by adding a NEW file name, never by overwriting one.
  const have = new Set(fs.readdirSync(path.join(PUB, "fonts")));
  const named = new Set();
  for (const f of fs.readdirSync(PUB).filter((x) => x.endsWith(".html"))) {
    for (const m of fs.readFileSync(path.join(PUB, f), "utf8").matchAll(/fonts\/([\w.-]+\.woff2)/g)) named.add(m[1]);
  }
  for (const m of fs.readFileSync(path.join(PUB, "css", "fonts.css"), "utf8").matchAll(/fonts\/([\w.-]+\.woff2)/g)) named.add(m[1]);
  assert.ok(named.size >= 4, "found too few font references to mean anything");
  for (const n of named) assert.ok(have.has(n), `fonts/${n} is referenced but missing`);
});

console.log(`\nsite_headers.test.js: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);

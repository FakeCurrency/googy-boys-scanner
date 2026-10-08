/* Drive the Vivek 5.0 site in headless Chromium. Agent tooling, not product.
 *
 *   node .claude/skills/run-googy-boys-scanner/driver.js [--fixtures] <<'CMDS'
 *   nav /index.html
 *   wait .row-wrap
 *   shot deck
 *   errors
 *   CMDS
 *
 * Starts its own `python3 serve.py` (public/, or a root whose data/ is the
 * e2e fixtures with --fixtures), runs the commands from stdin one per line,
 * then stops the server. --stub-price answers /api/price (daily) and
 * /api/quote from the committed PhaseMap chart files, so stock charts draw
 * without the Cloudflare Functions (serve.py has none). Commands:
 *   nav <path>             goto, wait for DOMContentLoaded
 *   wait <selector>        wait up to 30s for it
 *   click <selector>
 *   fill <selector> <text>
 *   press <key>            e.g. Escape, Enter
 *   eval <js expression>   prints the JSON result
 *   text <selector>        prints textContent of every match (first 20)
 *   count <selector>       prints how many match
 *   viewport <w> <h>       fresh page at that size (default 1500x950)
 *   sleep <ms>
 *   scroll <selector>      scroll the first match into view
 *   shot <name>            viewport PNG -> $SHOTS (default /tmp/vivek-shots)
 *   fullshot <name>        whole-page PNG (the deck/journal run to 5-8k px,
 *                          too tall to read once an image viewer shrinks it)
 *   errors                 page errors, console errors, HTTP >= 400 so far
 * A failing command prints FAIL and exits 1 after cleanup. `#` = comment.
 */
const { spawn, execSync } = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");

function loadPlaywright() {
  try { return require("playwright"); } catch (_) {}
  const g = execSync("npm root -g").toString().trim();
  return require(path.join(g, "playwright"));
}
const { chromium } = loadPlaywright();

const REPO = path.resolve(__dirname, "..", "..", "..");
const PORT = Number(process.env.PORT || 8765);
const BASE = `http://localhost:${PORT}`;
const SHOTS = process.env.SHOTS || "/tmp/vivek-shots";
const FIXTURES = process.argv.includes("--fixtures");
const STUB_PRICE = process.argv.includes("--stub-price");

// --stub-price: the Pages Functions do not run under serve.py, and this
// container cannot reach Yahoo/Binance anyway. Serve the scan's saved daily
// candles (data/phasemap/charts/<market>/<SYM>.json, ~220 bars) in the
// /api/price shape. Daily only; intraday and unknown names stay 404.
async function stubPrice(route) {
  const u = new URL(route.request().url());
  const raw = (u.searchParams.get("symbol") || u.searchParams.get("sym") || "").toUpperCase();
  const [market, sym] = raw.endsWith(".AX") ? ["asx", raw.slice(0, -3)]
    : raw.endsWith("-USD") ? ["crypto", raw.slice(0, -4)] : ["nasdaq", raw];
  const file = path.join(REPO, "public", "data", "phasemap", "charts", market, `${sym}.json`);
  const quote = u.pathname.endsWith("/quote");
  if (!fs.existsSync(file) || (!quote && u.searchParams.get("interval") !== "1d")) {
    return route.fulfill({ status: 404, body: "no stub" });
  }
  // Stocks at 12:00Z: the same exchange date in Sydney and New York, so
  // chart.js's toExchangeDates keeps the date. Crypto days are UTC.
  const hh = market === "crypto" ? "T00:00:00Z" : "T12:00:00Z";
  const candles = JSON.parse(fs.readFileSync(file, "utf8")).candles.map((c) => ({
    time: Date.parse(c.t + hh) / 1000, open: c.o, high: c.h, low: c.l, close: c.c, volume: c.v || 0,
  }));
  const last = candles[candles.length - 1].close;
  const body = quote
    ? { price: last, currency: market === "asx" ? "AUD" : "USD", time: Date.now(), source: "stub" }
    : { ok: true, symbol: raw, price: last, source: "stub", delayed: true, bars: candles.length, candles };
  console.log(`stub ${u.pathname}${u.search} -> ${quote ? `price ${last}` : `${candles.length} bars`}`);
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

// --fixtures: the lighthouse gate's trick -- symlink every public/ entry
// except data/, and point data/ at the deterministic e2e fixture set.
function stageRoot() {
  if (!FIXTURES) return path.join(REPO, "public");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "vivek-root-"));
  for (const e of fs.readdirSync(path.join(REPO, "public"))) {
    if (e !== "data") fs.symlinkSync(path.join(REPO, "public", e), path.join(dir, e));
  }
  fs.symlinkSync(path.join(REPO, "test", "e2e", "fixtures", "data"), path.join(dir, "data"));
  return dir;
}

const portUp = () => new Promise((res) => {
  const s = net.connect(PORT, "127.0.0.1");
  s.once("connect", () => { s.destroy(); res(true); });
  s.once("error", () => { s.destroy(); res(false); });
});

async function main() {
  if (await portUp()) throw new Error(`port ${PORT} already in use -- stop it or set PORT=`);
  const root = stageRoot();
  const srv = spawn("python3", ["serve.py", String(PORT), root], { cwd: REPO, stdio: "ignore" });
  let browser, failed = false;
  try {
    for (let i = 0; !(await portUp()); i++) {
      if (i > 50) throw new Error("serve.py never came up");
      await new Promise((r) => setTimeout(r, 200));
    }
    const exe = process.env.PW_CHROMIUM
      || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);
    browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox", "--disable-background-networking", "--disable-component-update"] });
    fs.mkdirSync(SHOTS, { recursive: true });
    const seen = [];
    let page;
    const newPage = async (w, h) => {
      if (page) await page.context().close();
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, serviceWorkers: "block" });
      // Skip the first-visit tour scrim; it swallows clicks.
      await ctx.addInitScript(() => { try { localStorage.setItem("gbs:onboarded", "1"); } catch (_) {} });
      if (STUB_PRICE) await ctx.route(/\/api\/(price|quote)\b/, stubPrice);
      page = await ctx.newPage();
      page.on("pageerror", (e) => seen.push(`pageerror: ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") seen.push(`console: ${m.text()}`); });
      page.on("response", (r) => { if (r.status() >= 400) seen.push(`http ${r.status()}: ${r.url().replace(BASE, "")}`); });
    };
    await newPage(1500, 950);

    const lines = fs.readFileSync(0, "utf8").split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("#"));
    for (const line of lines) {
      const [cmd, ...rest] = line.split(/\s+/);
      const arg = line.slice(cmd.length).trim();
      try {
        if (cmd === "nav") await page.goto(BASE + arg, { waitUntil: "domcontentloaded", timeout: 30000 });
        else if (cmd === "wait") await page.waitForSelector(arg, { timeout: 30000 });
        else if (cmd === "click") await page.click(arg, { timeout: 10000 });
        else if (cmd === "fill") await page.fill(rest[0], rest.slice(1).join(" "));
        else if (cmd === "press") await page.keyboard.press(arg);
        else if (cmd === "eval") console.log(JSON.stringify(await page.evaluate(arg)));
        else if (cmd === "text") console.log(JSON.stringify(await page.$$eval(arg, (n) => n.slice(0, 20).map((e) => e.textContent.trim().replace(/\s+/g, " ")))));
        else if (cmd === "count") console.log(await page.$$eval(arg, (n) => n.length));
        else if (cmd === "viewport") await newPage(Number(rest[0]), Number(rest[1]));
        else if (cmd === "sleep") await page.waitForTimeout(Number(arg));
        else if (cmd === "scroll") await page.locator(arg).first().scrollIntoViewIfNeeded();
        else if (cmd === "shot" || cmd === "fullshot") {
          const f = path.join(SHOTS, `${arg}.png`);
          await page.screenshot({ path: f, fullPage: cmd === "fullshot" });
          console.log(`shot ${f}`);
        } else if (cmd === "errors") console.log(seen.length ? seen.join("\n") : "no errors");
        else throw new Error(`unknown command "${cmd}"`);
        if (!["eval", "text", "count", "shot", "fullshot", "errors"].includes(cmd)) console.log(`ok   ${line}`);
      } catch (e) {
        console.log(`FAIL ${line}\n     ${e.message.split("\n")[0]}`);
        failed = true;
        break;
      }
    }
  } finally {
    if (browser) await browser.close();
    srv.kill();
    // unlink the symlinks one by one: never recurse into what they point at
    if (FIXTURES) { for (const e of fs.readdirSync(root)) fs.unlinkSync(path.join(root, e)); fs.rmdirSync(root); }
  }
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e.message); process.exit(1); });

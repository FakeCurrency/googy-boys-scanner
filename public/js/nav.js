/* Shared site navigation — one nav, every page.
 *
 * The app grew to 13 pages but navigation stayed hub-and-spoke (everything via
 * the dashboard) with a different link set on every page. This renders ONE
 * consistent nav into the `#site-nav` mount on each page:
 *
 *   • Desktop: pill row — SCAN · PHASEMAP · SPECS · JOURNAL · AI BOT · MORE ▾
 *     (NEWS / TRACK / HOW IT WORKS live in the MORE menu; DEBUG appears there
 *     only when debug mode is on — localStorage gbs:debug or ?debug).
 *   • Mobile (≤680px): the pill row hides and a fixed bottom TAB BAR appears
 *     with the five primary destinations — one-thumb navigation.
 *
 * The current page is highlighted in both. Pages opt in by including this
 * script + an element with id="site-nav"; the chart page deliberately stays
 * minimal (focused view, has its own back-link context).
 */
(() => {
  "use strict";

  const PRIMARY = [
    { href: "index.html",           label: "SCAN",       tab: "📡", key: "index" },
    { href: "recommendations.html", label: "RECS",       tab: "🧭", key: "recommendations" },
    { href: "phasemap.html",        label: "PHASEMAP",   tab: "🗺️", key: "phasemap" },
    { href: "specs.html",           label: "SPECS ⚡",   tab: "⚡", key: "specs" },
    { href: "mynames.html",         label: "★ MY NAMES", tab: "★", key: "mynames" },
    { href: "alerts.html",          label: "ALERTS",     tab: "🔔", key: "alerts" },
    { href: "journal.html",         label: "JOURNAL",    tab: "📒", key: "journal" },
  ];
  // Bottom tab bar fits 5 — SPECS + ALERTS live in the top pills / MORE on
  // mobile (RECS took a slot, owner 2026-07-22).
  const TABS = PRIMARY.filter((x) => x.key !== "specs" && x.key !== "alerts");
  const MORE = [
    { href: "sectors.html", label: "NEWS",         key: "sectors" },
    { href: "bot.html",     label: "AI BOT",       key: "bot", bot: true },
    { href: "system.html",  label: "SYSTEM",       key: "system" },
    { href: "about.html",   label: "HOW IT WORKS", key: "about" },
  ];

  // (debug.html retired 2026-07-21 with the scalp-era data surfaces it read —
  //  system.html + /api/health are the live diagnostics now.)

  // Current page key from the path ("/" and "/index.html" are both the scanner;
  // the phasemap sub-pages highlight the PHASEMAP destination).
  function pageKey() {
    const f = (location.pathname.split("/").pop() || "index.html").toLowerCase();
    const base = f.replace(/\.html$/, "") || "index";
    if (base.startsWith("phasemap")) return "phasemap";
    return base;
  }

  function render() {
    const mount = document.getElementById("site-nav");
    const here = pageKey();
    const more = MORE;

    if (mount) {
      const pill = (it) =>
        `<a class="howto-link${it.bot ? " bot-nav-link" : ""}${it.key === here ? " is-here" : ""}" href="${it.href}">` +
        `${it.bot ? '<span class="bot-nav-dot"></span>' : ""}${it.label}</a>`;
      const moreActive = more.some((it) => it.key === here);
      // BACK (owner 2026-07-22): one click to the previous page from anywhere
      // but the dashboard. Falls back to SCAN when there's no in-site history.
      const backPill = here === "index" ? "" :
        `<button class="howto-link nav-back" type="button" title="Back to the previous page">← BACK</button>`;
      mount.innerHTML =
        backPill +
        PRIMARY.map(pill).join("") +
        `<span class="nav-more">` +
          `<button class="howto-link nav-more-btn${moreActive ? " is-here" : ""}" type="button" aria-haspopup="true" aria-expanded="false">MORE ▾</button>` +
          `<span class="nav-more-menu" hidden>` +
            more.map((it) => `<a class="nav-more-item${it.key === here ? " is-here" : ""}" href="${it.href}">${it.bot ? '<span class="bot-nav-dot"></span> ' : ""}${it.label}</a>`).join("") +
          `</span>` +
        `</span>`;

      const backBtn = mount.querySelector(".nav-back");
      if (backBtn) backBtn.addEventListener("click", () => {
        let sameSite = false;
        try { sameSite = document.referrer && new URL(document.referrer).origin === location.origin; } catch (_) {}
        if (history.length > 1 && sameSite) history.back();
        else location.href = "index.html";
      });

      const btn = mount.querySelector(".nav-more-btn");
      const menu = mount.querySelector(".nav-more-menu");
      if (btn && menu) {
        const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const open = !menu.hidden;
          if (open) { close(); return; }
          // Fixed positioning (2026-07-22): the deck topbar's nav strip is a
          // scroll container, which CLIPS absolutely-positioned children — the
          // menu opened invisibly. Anchor it to the button in viewport space.
          const r = btn.getBoundingClientRect();
          menu.style.position = "fixed";
          menu.style.top = `${Math.round(r.bottom + 6)}px`;
          menu.style.left = "auto";
          menu.style.right = `${Math.max(8, Math.round(window.innerWidth - r.right))}px`;
          menu.hidden = false;
          btn.setAttribute("aria-expanded", "true");
          window.addEventListener("scroll", close, { once: true, passive: true });
        });
        document.addEventListener("click", close);
        document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
      }
    }

    // Bottom tab bar (mobile only via CSS). Appended once per page.
    if (!document.querySelector(".site-tabs")) {
      const bar = document.createElement("nav");
      bar.className = "site-tabs";
      bar.setAttribute("aria-label", "Primary");
      bar.innerHTML = TABS.map((it) =>
        `<a class="site-tab${it.key === here ? " is-here" : ""}" href="${it.href}" data-tabkey="${it.key}">` +
        `<span class="site-tab-ico" aria-hidden="true">${it.tab}<span class="site-tab-badge" data-badge="${it.key}" hidden></span></span>` +
        `<span class="site-tab-lbl">${it.label.replace(" ⚡", "").replace("AI ", "")}</span></a>`
      ).join("");
      document.body.appendChild(bar);
      document.body.classList.add("has-site-tabs");
      decorateTabBadges();
    }
  }

  // Live badge counts on the bottom tabs (backlog #29): the tradeable A+ count
  // on SCAN and the bot's open-position count on JOURNAL — a glance-value the
  // owner asked for. Lightweight: reads the same slim published files the rest
  // of the site uses, fails silent (no badge) if anything is unreachable, and
  // never blocks nav render.
  function setBadge(key, n) {
    const el = document.querySelector(`.site-tab-badge[data-badge="${key}"]`);
    if (!el) return;
    if (n > 0) { el.textContent = n > 99 ? "99+" : String(n); el.hidden = false; }
    else { el.hidden = true; }
  }
  function decorateTabBadges() {
    const grab = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    // SCAN: A+ count for the market the dashboard will open (saved pref).
    let market = "asx";
    try { market = JSON.parse(localStorage.getItem("gbs:prefs") || "{}").market || "asx"; } catch (_) {}
    if (!["asx", "nasdaq", "crypto"].includes(market)) market = "asx";
    grab(`data/${market}_prices.json`).then((d) => {
      const rows = (d && d.rows) || {};
      const aplus = Object.values(rows).filter((r) => r && r.grade === "A+").length;
      setBadge("index", aplus);
    });
    // JOURNAL: bot open positions (the one track record).
    grab("data/vivek_bot_book.json").then((d) => {
      setBadge("journal", ((d && d.open) || []).length);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();

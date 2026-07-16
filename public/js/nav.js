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
    { href: "index.html",    label: "SCAN",       tab: "📡", key: "index" },
    { href: "phasemap.html", label: "PHASEMAP",   tab: "🗺️", key: "phasemap" },
    { href: "specs.html",    label: "SPECS ⚡",   tab: "⚡", key: "specs" },
    { href: "mynames.html",  label: "★ MY NAMES", tab: "★", key: "mynames" },
    { href: "alerts.html",   label: "ALERTS",     tab: "🔔", key: "alerts" },
    { href: "journal.html",  label: "JOURNAL",    tab: "📒", key: "journal" },
  ];
  // Bottom tab bar fits 5 — SPECS lives in the top pills / MORE on mobile.
  const TABS = PRIMARY.filter((x) => x.key !== "specs");
  const MORE = [
    { href: "sectors.html", label: "NEWS",         key: "sectors" },
    { href: "bot.html",     label: "AI BOT",       key: "bot", bot: true },
    { href: "system.html",  label: "SYSTEM",       key: "system" },
    { href: "about.html",   label: "HOW IT WORKS", key: "about" },
  ];

  const isDebug = () => {
    try {
      return new URLSearchParams(location.search).has("debug") ||
        localStorage.getItem("gbs:debug") === "1";
    } catch (_) { return false; }
  };

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
    const more = MORE.concat(isDebug() ? [{ href: "debug.html", label: "DEBUG", key: "debug" }] : []);

    if (mount) {
      const pill = (it) =>
        `<a class="howto-link${it.bot ? " bot-nav-link" : ""}${it.key === here ? " is-here" : ""}" href="${it.href}">` +
        `${it.bot ? '<span class="bot-nav-dot"></span>' : ""}${it.label}</a>`;
      const moreActive = more.some((it) => it.key === here);
      mount.innerHTML =
        PRIMARY.map(pill).join("") +
        `<span class="nav-more">` +
          `<button class="howto-link nav-more-btn${moreActive ? " is-here" : ""}" type="button" aria-haspopup="true" aria-expanded="false">MORE ▾</button>` +
          `<span class="nav-more-menu" hidden>` +
            more.map((it) => `<a class="nav-more-item${it.key === here ? " is-here" : ""}" href="${it.href}">${it.bot ? '<span class="bot-nav-dot"></span> ' : ""}${it.label}</a>`).join("") +
          `</span>` +
        `</span>`;

      const btn = mount.querySelector(".nav-more-btn");
      const menu = mount.querySelector(".nav-more-menu");
      if (btn && menu) {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const open = !menu.hidden;
          menu.hidden = open;
          btn.setAttribute("aria-expanded", String(!open));
        });
        document.addEventListener("click", () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); });
        document.addEventListener("keydown", (e) => { if (e.key === "Escape") { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
      }
    }

    // Bottom tab bar (mobile only via CSS). Appended once per page.
    if (!document.querySelector(".site-tabs")) {
      const bar = document.createElement("nav");
      bar.className = "site-tabs";
      bar.setAttribute("aria-label", "Primary");
      bar.innerHTML = TABS.map((it) =>
        `<a class="site-tab${it.key === here ? " is-here" : ""}" href="${it.href}">` +
        `<span class="site-tab-ico" aria-hidden="true">${it.tab}</span>` +
        `<span class="site-tab-lbl">${it.label.replace(" ⚡", "").replace("AI ", "")}</span></a>`
      ).join("");
      document.body.appendChild(bar);
      document.body.classList.add("has-site-tabs");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();

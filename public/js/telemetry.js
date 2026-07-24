/* Vivek 5.0 — client telemetry (#99). Loaded FIRST in <head> so it catches
 * errors from every later script.
 *
 *   1. window.onerror + unhandledrejection beacon — uncaught errors are logged
 *      (tagged) and kept in a small sessionStorage ring buffer + window.__gbsErrors()
 *      so a glitch is inspectable after the fact instead of vanishing.
 *   2. version.json deploy stamp + skew detection — reads the stamp at load,
 *      re-checks on focus; if it changed, a new deploy landed while the tab sat
 *      open and we offer a refresh (a stale bundle talking to a fresh API is a
 *      classic source of phantom errors). A new service worker taking control
 *      is the same signal and also nudges. No endpoint required; zero network
 *      beyond the tiny version.json poll.
 */
(function () {
  "use strict";

  // ---- 1. uncaught-error beacon ----------------------------------------------
  var RING = [];
  function record(kind, msg, at) {
    var e = { t: new Date().toISOString(), kind: kind, msg: String(msg == null ? "" : msg).slice(0, 500) };
    if (at) e.at = String(at).slice(0, 300);
    RING.push(e); if (RING.length > 20) RING.shift();
    try { sessionStorage.setItem("gbs:errors", JSON.stringify(RING)); } catch (_) {}
    try { console.error("[gbs:" + kind + "]", msg, at || ""); } catch (_) {}
  }
  window.addEventListener("error", function (ev) {
    // resource load errors (img/script) have no message — skip those, keep JS errors.
    if (ev && ev.message) record("error", ev.message, (ev.filename || "") + ":" + (ev.lineno || 0));
  });
  window.addEventListener("unhandledrejection", function (ev) {
    var r = ev && ev.reason;
    record("promise", (r && (r.message || r)) || "unhandledrejection");
  });
  // inspect from the console: window.__gbsErrors()
  window.__gbsErrors = function () { return RING.slice(); };

  // ---- 2. deploy stamp + skew detection --------------------------------------
  var loaded = null;
  var hadController = !!(navigator.serviceWorker && navigator.serviceWorker.controller);

  function fetchVersion() {
    return fetch("version.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function nudge() {
    if (document.getElementById("gbs-update-nudge") || !document.body) return;
    var el = document.createElement("div");
    el.id = "gbs-update-nudge";
    el.setAttribute("role", "status");
    el.style.cssText = "position:fixed;bottom:14px;left:50%;transform:translateX(-50%);" +
      "z-index:9999;background:#0a84ff;color:#fff;padding:9px 15px;border-radius:10px;" +
      "font:600 12.5px system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.4);cursor:pointer";
    el.textContent = "A new version is available — tap to refresh";
    el.addEventListener("click", function () { location.reload(); });
    document.body.appendChild(el);
  }

  fetchVersion().then(function (v) {
    loaded = (v && v.version) || null;
    if (!loaded) return;
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) return;
      fetchVersion().then(function (v2) {
        if (v2 && v2.version && v2.version !== loaded) nudge();
      });
    });
  });

  // A NEW service worker taking control == a new deploy is live. Only nudge if
  // the page was already controlled at load (skip the first-install swap).
  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (hadController) nudge();
    });
  }
})();

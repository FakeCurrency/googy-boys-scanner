/* Registers the PWA service worker (sw.js) — one line per page keeps the
   registration identical everywhere. Silently skipped where unsupported. */
if ("serviceWorker" in navigator) {
  addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

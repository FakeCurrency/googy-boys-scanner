/* Registers the PWA service worker (sw.js) — one line per page keeps the
   registration identical everywhere. Silently skipped where unsupported.

   Update toast: when a NEW service worker takes over (a deploy landed while
   the app was open/cached), show a small "update ready" pill instead of
   leaving the user on stale assets until a hard refresh. */
if ("serviceWorker" in navigator) {
  addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").then((reg) => {
      reg.addEventListener("updatefound", () => {
        const sw = reg.installing;
        if (!sw) return;
        sw.addEventListener("statechange", () => {
          // Only when an OLD worker was controlling — first-ever install is silent.
          if (sw.state === "activated" && navigator.serviceWorker.controller) showUpdateToast();
        });
      });
    }).catch(() => {});
  });

  function showUpdateToast() {
    if (document.getElementById("sw-toast")) return;
    const el = document.createElement("button");
    el.id = "sw-toast";
    el.type = "button";
    el.textContent = "⬆ Update ready — tap to refresh";
    el.style.cssText =
      "position:fixed;left:50%;transform:translateX(-50%);z-index:9999;" +
      "bottom:calc(72px + env(safe-area-inset-bottom, 0px));cursor:pointer;" +
      "font:700 13px/1 -apple-system,'Inter',sans-serif;color:#fff;" +
      "background:#0a84ff;border:none;border-radius:999px;padding:11px 18px;" +
      "box-shadow:0 6px 24px rgba(0,0,0,.45)";
    el.addEventListener("click", () => location.reload());
    document.body.appendChild(el);
    setTimeout(() => { if (el.isConnected) el.remove(); }, 60000);   // don't nag forever
  }
}

/* Registers the PWA service worker (sw.js) — one line per page keeps the
   registration identical everywhere. Silently skipped where unsupported.

   Update flow (v3, 2026-07-22 — owner: "the times haven't even updated"):
   long-lived tabs used to discover a deploy only on navigation, then wait
   for a manual toast tap. Now:
     • the page re-checks for a new worker every 30 minutes, and
     • when a new worker takes control: a BACKGROUND tab reloads itself
       silently; a foreground tab shows the one-tap toast (never yank the
       page out from under an active user on a trading dashboard). */
if ("serviceWorker" in navigator) {
  let refreshing = false;
  const applyUpdate = () => {
    if (refreshing) return;
    refreshing = true;
    location.reload();
  };

  addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").then((reg) => {
      // Long-open tabs (the overnight dashboard) re-check for deploys.
      setInterval(() => { reg.update().catch(() => {}); }, 30 * 60 * 1000);
      reg.addEventListener("updatefound", () => {
        const sw = reg.installing;
        if (!sw) return;
        sw.addEventListener("statechange", () => {
          // Only when an OLD worker was controlling — first-ever install is silent.
          if (sw.state === "activated" && navigator.serviceWorker.controller) {
            if (document.hidden) applyUpdate();   // background tab: self-heal silently
            else showUpdateToast();
          }
        });
      });
    }).catch(() => {});

    // If an update activates while this tab is hidden (e.g. overnight),
    // refresh the moment it happens rather than serving stale assets.
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (document.hidden) applyUpdate();
    });
    // And when the user returns to a tab that has an update pending, apply it
    // before they read stale numbers.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden || !navigator.serviceWorker.controller) return;
      navigator.serviceWorker.getRegistration().then((reg) => {
        if (reg && reg.waiting) applyUpdate();
      }).catch(() => {});
    });
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
    el.addEventListener("click", applyUpdate);
    document.body.appendChild(el);
    setTimeout(() => { if (el.isConnected) el.remove(); }, 60000);   // don't nag forever
  }
}

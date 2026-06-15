/* =========================================================================
   Password gate — a lightweight lock screen shown until the correct password
   is entered (remembered per device). The password is stored only as a SHA-256
   hash, never in plain text. This is a "soft" client-side lock; the hosting
   layer (Cloudflare Pages Basic Auth, see functions/_middleware.js) is the
   real server-side protection once deployed.
   ========================================================================= */
(() => {
  "use strict";
  const HASH = "f6798ee8bd024bd5159c62e189cd127720c39bd9b52763ca7e875a0629d5caab";
  const KEY = "gbs:unlocked";

  if (localStorage.getItem(KEY) === HASH) return;   // already unlocked on this device

  // Hide the page (but keep the overlay visible) until unlocked — no content flash.
  const hide = document.createElement("style");
  hide.id = "gate-hide";
  hide.textContent =
    "body{visibility:hidden!important}#gate-overlay,#gate-overlay *{visibility:visible!important}" +
    "#gate-overlay{position:fixed;inset:0;z-index:99999;display:grid;place-items:center;" +
    "background:#0b0f16;font-family:-apple-system,Inter,system-ui,sans-serif}" +
    ".gate-card{width:min(360px,88vw);background:#161d2c;border:1px solid #243047;" +
    "border-radius:18px;padding:28px 26px;box-shadow:0 20px 60px rgba(0,0,0,.5);text-align:center}" +
    ".gate-mark{width:46px;height:46px;border-radius:12px;margin:0 auto 14px;display:grid;" +
    "place-items:center;color:#06120a;background:linear-gradient(145deg,#34c759,#30b0c7)}" +
    ".gate-card h1{margin:0 0 4px;font-size:18px;font-weight:800;color:#e8edf5;letter-spacing:.4px}" +
    ".gate-card p{margin:0 0 18px;font-size:13px;color:#8a98ab}" +
    ".gate-card input{width:100%;box-sizing:border-box;padding:13px 14px;border-radius:11px;" +
    "border:1px solid #2a3550;background:#0e1219;color:#e8edf5;font-size:16px;text-align:center;" +
    "letter-spacing:3px;outline:none}.gate-card input:focus{border-color:#4d9fff}" +
    ".gate-card button{width:100%;margin-top:12px;padding:13px;border:0;border-radius:11px;cursor:pointer;" +
    "background:linear-gradient(145deg,#34c759,#30b0c7);color:#06120a;font-size:15px;font-weight:700}" +
    ".gate-err{min-height:16px;margin-top:10px;font-size:12.5px;color:#ff6b6b}";
  document.head.appendChild(hide);

  async function sha256(text) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  function mount() {
    const ov = document.createElement("div");
    ov.id = "gate-overlay";
    ov.innerHTML =
      '<form class="gate-card">' +
      '<div class="gate-mark"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></div>' +
      "<h1>GOOGY BOYS SCANNER</h1><p>Enter your password to continue</p>" +
      '<input type="password" inputmode="numeric" autocomplete="off" aria-label="Password" />' +
      "<button type=\"submit\">Unlock</button>" +
      '<div class="gate-err"></div></form>';
    document.body.appendChild(ov);
    const form = ov.querySelector("form"), inp = ov.querySelector("input"), err = ov.querySelector(".gate-err");
    inp.focus();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if ((await sha256(inp.value)) === HASH) {
        localStorage.setItem(KEY, HASH);
        ov.remove();
        document.getElementById("gate-hide")?.remove();
      } else {
        err.textContent = "Incorrect password";
        inp.value = ""; inp.focus();
      }
    });
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();

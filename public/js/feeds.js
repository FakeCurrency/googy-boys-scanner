/* feeds.js — YouTube + AI narrative feeds page renderer */
"use strict";

const FEEDS_JSON = "data/feeds.json";

// ── Helpers ──────────────────────────────────────────────────────────────────

function $(sel, ctx) { return (ctx || document).querySelector(sel); }

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-AU", {
      day: "numeric", month: "short", year: "numeric",
    });
  } catch { return iso.slice(0, 10); }
}

function fmtUpdated(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("en-AU", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
      timeZone: "UTC", timeZoneName: "short",
    });
  } catch { return iso; }
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Narrative card ────────────────────────────────────────────────────────────

function renderNarrative(narrative) {
  const card = $("#narrative-card");
  const text = $("#narrative-text");
  const meta = $("#narrative-meta");
  if (!card) return;

  if (!narrative || !narrative.summary) {
    card.style.display = "none";
    return;
  }

  text.classList.remove("loading");
  text.textContent = narrative.summary;
  if (narrative.generated_at) {
    meta.innerHTML = `Updated <span>${fmtUpdated(narrative.generated_at)}</span>`;
  }
}

// ── Video grid ────────────────────────────────────────────────────────────────

function videoCard(v) {
  const a = document.createElement("a");
  a.className  = "video-card";
  a.href       = escHtml(v.url);
  a.target     = "_blank";
  a.rel        = "noopener";
  a.setAttribute("aria-label", v.title);
  a.innerHTML = `
    <img class="video-thumb" src="${escHtml(v.thumbnail)}"
         alt="" loading="lazy" onerror="this.style.display='none'">
    <div class="video-info">
      <p class="video-title">${escHtml(v.title)}</p>
      <span class="video-date">${fmtDate(v.published)}</span>
      ${v.description ? `<p class="video-desc">${escHtml(v.description)}</p>` : ""}
    </div>`;
  return a;
}

function renderVideos(channels) {
  const section = $("#videos-section");
  if (!section) return;
  section.innerHTML = "";

  let anyVideos = false;

  for (const ch of channels) {
    const block = document.createElement("div");
    block.className = "channel-block";

    block.innerHTML = `
      <div class="channel-heading">
        <span class="channel-name">${escHtml(ch.name)}</span>
        <a class="channel-link" href="${escHtml(ch.url)}" target="_blank" rel="noopener">
          @${escHtml(ch.handle)} ↗
        </a>
      </div>`;

    if (!ch.videos || ch.videos.length === 0) {
      const empty = document.createElement("p");
      empty.className = "videos-empty";
      empty.textContent = "No videos fetched yet — run a feeds update.";
      block.appendChild(empty);
    } else {
      const grid = document.createElement("div");
      grid.className = "videos-grid";
      for (const v of ch.videos) grid.appendChild(videoCard(v));
      block.appendChild(grid);
      anyVideos = true;
    }

    section.appendChild(block);
  }

  // Update section badge
  const badge = $("#videos-badge");
  if (badge) {
    const total = channels.reduce((s, c) => s + (c.videos || []).length, 0);
    badge.textContent = `${total} video${total !== 1 ? "s" : ""}`;
  }

  return anyVideos;
}

// ── X / Twitter section ───────────────────────────────────────────────────────

function xCard(a) {
  const url = `https://twitter.com/${a.handle}`;
  const el = document.createElement("div");
  el.className    = "x-card";
  el.dataset.search = (a.name + " @" + a.handle).toLowerCase();
  el.innerHTML = `
    <div class="x-card-head">
      <div class="x-card-id">
        <span class="x-card-name">${escHtml(a.name)}</span>
        <a class="x-card-handle" href="${escHtml(url)}" target="_blank" rel="noopener">@${escHtml(a.handle)}</a>
      </div>
      <a class="x-card-open" href="${escHtml(url)}" target="_blank" rel="noopener">Open ↗</a>
    </div>
    <div class="x-card-body">
      <a class="twitter-timeline" data-theme="dark" data-height="520"
         data-chrome="noheader nofooter transparent"
         href="${escHtml(url)}">Posts by @${escHtml(a.handle)}</a>
    </div>`;
  return el;
}

function renderX(accounts) {
  const grid   = $("#x-grid");
  const search = $("#x-search");
  const countEl = $("#x-count");
  if (!grid) return;

  grid.innerHTML = "";
  for (const a of accounts) grid.appendChild(xCard(a));

  const total = accounts.length;
  if (countEl) countEl.textContent = `${total} accounts`;

  function applyFilter() {
    const q = search ? search.value.trim().toLowerCase() : "";
    let shown = 0;
    grid.querySelectorAll(".x-card").forEach((c) => {
      const hit = !q || c.dataset.search.includes(q);
      c.classList.toggle("is-hidden", !hit);
      if (hit) shown++;
    });
    if (countEl) countEl.textContent = q ? `${shown} of ${total}` : `${total} accounts`;
  }

  if (search) search.addEventListener("input", applyFilter);

  // Load X widgets.js after cards are in the DOM
  if (!document.querySelector('script[src*="platform.twitter.com"]')) {
    const s = document.createElement("script");
    s.src = "https://platform.twitter.com/widgets.js";
    s.async = true;
    s.charset = "utf-8";
    document.body.appendChild(s);
  }
}

// ── Updated timestamp ─────────────────────────────────────────────────────────

function renderUpdated(iso) {
  const el = $("#feeds-updated");
  if (el && iso) el.textContent = `Updated ${fmtUpdated(iso)}`;
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function init() {
  try {
    const resp = await fetch(FEEDS_JSON + "?v=" + Date.now());
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    renderNarrative(data.narrative);
    renderVideos(data.channels || []);
    renderX(data.x_accounts || []);
    renderUpdated(data.updated);

    const loading = $("#feeds-loading");
    if (loading) loading.remove();
  } catch (err) {
    const loading = $("#feeds-loading");
    if (loading) loading.remove();
    const errEl = $("#feeds-error");
    if (errEl) {
      errEl.style.display = "";
      errEl.textContent = `Could not load feeds data: ${err.message}. Run a feeds update workflow.`;
    }
    // Still try to render X accounts from the hardcoded fallback
    const xFallback = window.__X_ACCOUNTS_FALLBACK;
    if (xFallback) renderX(xFallback);
  }
}

document.addEventListener("DOMContentLoaded", init);

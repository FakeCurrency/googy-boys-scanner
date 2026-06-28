/* =========================================================================
   VIVEK 3D chart — Time × Price × Timeframe "stack" view (Option A).

   A READ-ONLY companion to the 2D LightweightCharts view. It consumes the
   EXACT same per-timeframe data the 2D chart and the bot use — the normalised
   Python plans on `d.timeframes[key]` (candles, the 10/20/43/200 SMAs, and the
   levels block: 200-SMA level / Entry / SL / TP1-3 / armed / entry_trigger).
   It never recomputes a level or a candle; it just re-projects the same numbers
   into 3D so timeframe *confluence* becomes a spatial fact: each timeframe is a
   parallel plane (4H front → Daily → Weekly back), price is the shared vertical
   axis across all planes, so when the Weekly entry, Daily entry and the 200-SMA
   line up at the same height you can literally look down the stack and see it.

   No drawing tools, no trading — that all stays on the 2D view (this is a
   visualisation). three.js + OrbitControls are lazy-loaded from a CDN only when
   the user first opens the 3D view, so the 2D page pays nothing for it.

   Public API (window.VivekChart3D):
     isSupported()            → boolean (WebGL available?)
     mount(hostEl, model)     → Promise<controller>
   model = { timeframes, order, activeTF, currency, symbol, dir }
   controller = { setActiveTF(key), dispose() }
   ========================================================================= */
(() => {
  "use strict";

  // three r128 classic global builds (define window.THREE + THREE.OrbitControls)
  // — same "global <script>" style the page already uses for LightweightCharts,
  // so no ES-module/bundler step is needed.
  const THREE_SRC = "https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js";
  const ORBIT_SRC = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js";

  // World box the stack is drawn into (arbitrary units; the camera frames it).
  const W = 120;     // X — time (oldest left → newest right)
  const H = 72;      // Y — price (shared across every plane)
  const DZ = 48;     // Z — spacing between timeframe planes
  const NBARS = 64;  // candles drawn per plane (most-recent slice) — perf budget

  // Plane backdrop tints, distinct from the level colours below.
  const TF_TINT = { "4H": 0x3a7bd5, "1D": 0x8a7dff, "1W": 0xd98a3a, "1M": 0x46c2a8, "3M": 0xc25a8a };
  const TF_NAME = { "4H": "4H", "1D": "Daily", "1W": "Weekly", "1M": "Monthly", "3M": "Quarterly" };
  // Level colours — identical to the 2D chart so the two views read the same.
  const LEVELS = [
    { key: "level", color: 0xffb020, label: "200 SMA" },
    { key: "stop",  color: 0xff5b5b, label: "SL" },
    { key: "entry", color: 0xe5e9f0, label: "Entry" },
    { key: "tp1",   color: 0x2fd07f, label: "TP1" },
    { key: "tp2",   color: 0x36b06b, label: "TP2" },
    { key: "tp3",   color: 0x2a8f57, label: "TP3" },
  ];
  const SMA200_COLOR = 0xffb020, CLOSE_COLOR = 0xc8d2e0, WICK_COLOR = 0x6b7585;
  const UP = 0x2fd07f, DOWN = 0xff5b5b;
  const hex = (n) => "#" + n.toString(16).padStart(6, "0");

  // ── lazy CDN loader (once) ──────────────────────────────────────────────────
  let threeReady = null;
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = [...document.scripts].find((s) => s.src === src);
      if (existing) {
        if (existing.dataset.loaded) return resolve();
        existing.addEventListener("load", () => resolve());
        existing.addEventListener("error", () => reject(new Error("load " + src)));
        return;
      }
      const s = document.createElement("script");
      s.src = src; s.async = true;
      s.addEventListener("load", () => { s.dataset.loaded = "1"; resolve(); });
      s.addEventListener("error", () => reject(new Error("load " + src)));
      document.head.appendChild(s);
    });
  }
  function ensureThree() {
    if (window.THREE && window.THREE.OrbitControls) return Promise.resolve();
    if (!threeReady) {
      threeReady = loadScript(THREE_SRC)
        .then(() => loadScript(ORBIT_SRC))
        .catch((e) => { threeReady = null; throw e; });
    }
    return threeReady;
  }

  function isSupported() {
    try {
      const c = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
        (c.getContext("webgl") || c.getContext("experimental-webgl")));
    } catch (_) { return false; }
  }

  // ── pure layout: project the shared data into world coordinates ─────────────
  // Exposed on the namespace so it can be reasoned about / tested in isolation
  // (no three.js needed): given the model it returns each plane's z, an x()
  // mapping per bar index, an xAtTime() for aligning the SMA polyline, and a
  // single priceToY() shared by ALL planes (that shared mapping is what makes
  // levels stack vertically). No DOM, no WebGL, no side effects.
  function buildLayout(model) {
    const tfs = model.timeframes || {};
    const order = (model.order || []).filter((k) => tfs[k] && (tfs[k].candles || []).length);
    let lo = Infinity, hi = -Infinity;
    const planes = order.map((key) => {
      const tf = tfs[key];
      const candles = (tf.candles || []).slice(-NBARS);
      for (const c of candles) { if (c.low < lo) lo = c.low; if (c.high > hi) hi = c.high; }
      const lv = tf.levels || {};
      for (const L of LEVELS) {
        const p = lv[L.key];
        if (p != null && isFinite(p)) { if (p < lo) lo = p; if (p > hi) hi = p; }
      }
      return { key, tf, candles, levels: lv };
    });
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) { lo = (lo || 0); hi = lo + 1; }
    const pad = (hi - lo) * 0.05 || 1;
    lo -= pad; hi += pad;
    const span = hi - lo;
    const priceToY = (p) => ((p - lo) / span - 0.5) * H;

    const count = planes.length;
    planes.forEach((pl, i) => {
      pl.z = count > 1 ? (i - (count - 1) / 2) * DZ : 0;
      const n = pl.candles.length;
      pl.n = n;
      pl.xOf = (j) => (n <= 1 ? 0 : (j / (n - 1) - 0.5) * W);
      const tmap = new Map();
      pl.candles.forEach((c, j) => tmap.set(c.time, pl.xOf(j)));
      pl.xAtTime = (t) => (tmap.has(t) ? tmap.get(t) : null);
    });
    return { planes, priceToY, lo, hi };
  }

  // ── three.js scene construction ─────────────────────────────────────────────
  async function mount(host, model) {
    await ensureThree();
    const THREE = window.THREE;
    if (!THREE || !THREE.OrbitControls) throw new Error("three.js unavailable");

    const layout = buildLayout(model);
    if (!layout.planes.length) throw new Error("no timeframe data to render in 3D");

    const width = host.clientWidth || 800;
    const height = host.clientHeight || 480;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));   // clamp for perf
    renderer.setSize(width, height);
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 6000);
    const homePos = new THREE.Vector3(W * 0.85, H * 0.62, DZ * layout.planes.length * 0.9 + 150);
    camera.position.copy(homePos);

    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 0, 0);
    controls.maxDistance = 4000;

    scene.add(new THREE.AmbientLight(0xffffff, 1));     // MeshBasic ignores lights; harmless

    // faint ground grid for spatial reference under the stack
    const grid = new THREE.GridHelper(Math.max(W, DZ * layout.planes.length) * 1.4, 18,
      0x2a3340, 0x1c232e);
    grid.position.y = -H / 2 - 4;
    scene.add(grid);

    const disposables = [];        // {geometry?, material?} to free on dispose
    const track = (obj) => { if (obj.geometry) disposables.push(obj.geometry); if (obj.material) disposables.push(obj.material); return obj; };
    const planeGroups = [];        // {key, group, sheet, bodies, sheetMat, lineMats[]}

    const dummy = new THREE.Object3D();

    layout.planes.forEach((pl) => {
      const group = new THREE.Group();
      group.position.z = pl.z;
      const tint = TF_TINT[pl.key] != null ? TF_TINT[pl.key] : 0x5566aa;
      const lineMats = [];

      // backdrop sheet (the timeframe's "page")
      const sheetMat = new THREE.MeshBasicMaterial({
        color: tint, transparent: true, opacity: 0.06, side: THREE.DoubleSide,
        depthWrite: false,
      });
      const sheet = track(new THREE.Mesh(new THREE.PlaneGeometry(W * 1.04, H * 1.04), sheetMat));
      group.add(sheet);

      // candle wicks (one LineSegments: high→low per bar)
      if (pl.n >= 1) {
        const wickPos = [];
        pl.candles.forEach((c, j) => {
          const x = pl.xOf(j);
          wickPos.push(x, layout.priceToY(c.high), 0, x, layout.priceToY(c.low), 0);
        });
        const wg = new THREE.BufferGeometry();
        wg.setAttribute("position", new THREE.Float32BufferAttribute(wickPos, 3));
        const wm = new THREE.LineBasicMaterial({ color: WICK_COLOR, transparent: true, opacity: 0.7 });
        lineMats.push(wm);
        group.add(track(new THREE.LineSegments(wg, wm)));
      }

      // candle bodies (instanced boxes, coloured per bar)
      let bodies = null;
      if (pl.n >= 1) {
        const bodyW = (W / Math.max(pl.n, 1)) * 0.6;
        const bodyD = DZ * 0.16;
        const bodyMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.95 });
        bodies = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), bodyMat, pl.n);
        disposables.push(bodies.geometry, bodyMat);
        const col = new THREE.Color();
        pl.candles.forEach((c, j) => {
          const yO = layout.priceToY(c.open), yC = layout.priceToY(c.close);
          const mid = (yO + yC) / 2;
          const h = Math.max(Math.abs(yC - yO), 0.25);
          dummy.position.set(pl.xOf(j), mid, 0);
          dummy.scale.set(bodyW, h, bodyD);
          dummy.updateMatrix();
          bodies.setMatrixAt(j, dummy.matrix);
          col.setHex(c.close >= c.open ? UP : DOWN);
          bodies.setColorAt(j, col);
        });
        bodies.instanceMatrix.needsUpdate = true;
        if (bodies.instanceColor) bodies.instanceColor.needsUpdate = true;
        group.add(bodies);
      }

      // close-price polyline
      if (pl.n >= 2) {
        const pos = [];
        pl.candles.forEach((c, j) => pos.push(pl.xOf(j), layout.priceToY(c.close), 0));
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
        const m = new THREE.LineBasicMaterial({ color: CLOSE_COLOR, transparent: true, opacity: 0.55 });
        lineMats.push(m);
        group.add(track(new THREE.Line(g, m)));
      }

      // 200-SMA polyline (the level the whole system reacts to)
      const sma = (pl.tf.lines || []).find((l) => l.name === "SMA 200");
      if (sma && sma.data && sma.data.length >= 2) {
        const pos = [];
        for (const pt of sma.data) {
          const x = pl.xAtTime(pt.time);
          if (x == null) continue;
          pos.push(x, layout.priceToY(pt.value), 0);
        }
        if (pos.length >= 6) {
          const g = new THREE.BufferGeometry();
          g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
          const m = new THREE.LineBasicMaterial({ color: SMA200_COLOR, transparent: true, opacity: 0.85 });
          lineMats.push(m);
          group.add(track(new THREE.Line(g, m)));
        }
      }

      // trade-level planes (Entry / SL / TP1-3 / 200-SMA level) — horizontal
      // translucent quads at the level's shared price height, so they line up
      // across timeframes when there's confluence.
      for (const L of LEVELS) {
        const p = pl.levels[L.key];
        if (p == null || !isFinite(p)) continue;
        const y = layout.priceToY(p);
        const mat = new THREE.MeshBasicMaterial({
          color: L.color, transparent: true,
          opacity: (L.key === "entry" || L.key === "stop" || L.key === "tp1") ? 0.26 : 0.16,
          side: THREE.DoubleSide, depthWrite: false,
        });
        const quad = new THREE.Mesh(new THREE.PlaneGeometry(W, DZ * 0.74), mat);
        quad.rotation.x = -Math.PI / 2;     // lie flat (spans X across, Z deep)
        quad.position.set(0, y, 0);
        disposables.push(quad.geometry, mat);
        group.add(quad);
      }

      scene.add(group);
      planeGroups.push({ key: pl.key, group, sheet, sheetMat, bodies, lineMats });
    });

    // ── DOM overlay: legends, reset, read-only hint ─────────────────────────────
    const overlay = document.createElement("div");
    overlay.className = "c3d-overlay";
    const tfLegend = layout.planes.map((pl) =>
      `<span class="c3d-chip"><i style="background:${hex(TF_TINT[pl.key] || 0x5566aa)}"></i>${TF_NAME[pl.key] || pl.key}` +
      `${pl.levels && pl.levels.armed ? " · ARMED" : ""}</span>`).join("");
    const lvLegend = LEVELS.map((L) =>
      `<span class="c3d-chip"><i style="background:${hex(L.color)}"></i>${L.label}</span>`).join("");
    overlay.innerHTML =
      `<div class="c3d-row c3d-note" hidden></div>` +
      `<div class="c3d-row c3d-tfs">${tfLegend}</div>` +
      `<div class="c3d-row c3d-lvls">${lvLegend}</div>` +
      `<div class="c3d-row c3d-foot">` +
        `<button type="button" class="c3d-reset">Reset view</button>` +
        `<span class="c3d-hint">Read-only 3D view · drag to orbit, scroll to zoom — switch to 2D to measure or simulate.</span>` +
      `</div>`;
    host.appendChild(overlay);
    const noteEl = overlay.querySelector(".c3d-note");
    overlay.querySelector(".c3d-reset").addEventListener("click", () => {
      camera.position.copy(homePos);
      controls.target.set(0, 0, 0);
      controls.update();
    });

    // ── highlight the active timeframe (brighten it, dim the rest) ──────────────
    function setActiveTF(key) {
      planeGroups.forEach((pg) => {
        const active = pg.key === key;
        pg.sheetMat.opacity = active ? 0.14 : 0.05;
        if (pg.bodies) pg.bodies.material.opacity = active ? 1.0 : 0.4;
        pg.lineMats.forEach((m) => { m.opacity = active ? 0.9 : 0.35; });
      });
      // 4H has no plan of its own — its level planes are the Daily reference.
      if (noteEl) {
        if (key === "4H") {
          noteEl.textContent = "4H plane — trade levels are the Daily plan (no separate 4H plan yet).";
          noteEl.hidden = false;
        } else {
          noteEl.hidden = true;
        }
      }
    }
    setActiveTF(model.activeTF || (layout.planes[0] && layout.planes[0].key));

    // ── render loop + resize ────────────────────────────────────────────────────
    let raf = 0, alive = true;
    function tick() {
      if (!alive) return;
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    }
    tick();

    const ro = new ResizeObserver(() => {
      const w = host.clientWidth || width, h = host.clientHeight || height;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    });
    ro.observe(host);

    function dispose() {
      alive = false;
      cancelAnimationFrame(raf);
      try { ro.disconnect(); } catch (_) {}
      try { controls.dispose(); } catch (_) {}
      disposables.forEach((d) => { try { d.dispose(); } catch (_) {} });
      planeGroups.forEach((pg) => { if (pg.bodies) { try { pg.bodies.dispose(); } catch (_) {} } });
      try { renderer.dispose(); } catch (_) {}
      if (renderer.domElement && renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }

    return { setActiveTF, dispose };
  }

  window.VivekChart3D = { isSupported, mount, buildLayout };
})();

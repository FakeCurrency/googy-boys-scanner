/* =========================================================================
   Chart indicator maths — split out of chart.js (REFINE200 #96, 2026-10-14).

   PURE functions only: arrays and bars in, arrays and numbers out. No DOM, no
   network, no page state, so this file can be read (and executed by the test
   suites) on its own. chart.html loads it BEFORE js/chart.js, which takes
   what it needs from window.ChartIndicators. Two families:

     * the scalp overlay maths (BB / KC / EMA / TTM momentum), mirroring
       scanner/scalp.py;
     * the MOMENTUM lens's Pine-seeded stack and the Final_Top_Script.pine
       Auto plan, mirroring scanner/momentum/ (test/momentum.test.js pins the
       ELS numbers to TradingView's).

   Moved verbatim; the comments travel with the code they explain.
   ========================================================================= */
window.ChartIndicators = (() => {
  "use strict";

  // Indicator math mirroring scanner/scalp.py exactly (BB20/2, KC20/1.5×ATR,
  // EMA9/21, TTM momentum = linreg(12) of close−midline, Wilder ATR).
  const SQ_P = 20, SQ_MOM = 12, BB_MULT = 2.0, KC_MULT = 1.5;
  const emaArr = (s, span) => { const k = 2 / (span + 1), o = []; let p;
    for (let i = 0; i < s.length; i++) { p = i === 0 ? s[i] : s[i] * k + p * (1 - k); o[i] = p; } return o; };
  const smaArr = (s, p) => { const o = new Array(s.length).fill(NaN); let sum = 0;
    for (let i = 0; i < s.length; i++) { sum += s[i]; if (i >= p) sum -= s[i - p]; if (i >= p - 1) o[i] = sum / p; } return o; };
  const stdArr = (s, p) => { const o = new Array(s.length).fill(NaN);
    for (let i = p - 1; i < s.length; i++) { let m = 0; for (let k = i - p + 1; k <= i; k++) m += s[k]; m /= p;
      let v = 0; for (let k = i - p + 1; k <= i; k++) { const d = s[k] - m; v += d * d; } o[i] = Math.sqrt(v / p); } return o; };
  const atrArr = (hi, lo, cl, p) => { const tr = [];
    for (let i = 0; i < cl.length; i++) tr[i] = i === 0 ? hi[i] - lo[i]
      : Math.max(hi[i] - lo[i], Math.abs(hi[i] - cl[i - 1]), Math.abs(lo[i] - cl[i - 1]));
    const a = 1 / p, o = []; let pv;
    for (let i = 0; i < tr.length; i++) { pv = i === 0 ? tr[i] : tr[i] * a + pv * (1 - a); o[i] = pv; } return o; };
  const rollMax = (s, p) => { const o = new Array(s.length).fill(NaN);
    for (let i = p - 1; i < s.length; i++) { let m = -Infinity; for (let k = i - p + 1; k <= i; k++) if (s[k] > m) m = s[k]; o[i] = m; } return o; };
  const rollMin = (s, p) => { const o = new Array(s.length).fill(NaN);
    for (let i = p - 1; i < s.length; i++) { let m = Infinity; for (let k = i - p + 1; k <= i; k++) if (s[k] < m) m = s[k]; o[i] = m; } return o; };
  const linregArr = (s, n) => { const o = new Array(s.length).fill(NaN);
    let st = 0, stt = 0; for (let i = 0; i < n; i++) { st += i; stt += i * i; }
    const denom = n * stt - st * st;
    for (let i = n - 1; i < s.length; i++) { let sy = 0, sty = 0;
      for (let j = 0; j < n; j++) { const y = s[i - n + 1 + j]; sy += y; sty += j * y; }
      const slope = (n * sty - st * sy) / denom, intercept = (sy - slope * st) / n;
      o[i] = slope * (n - 1) + intercept; } return o; };

  // Compute the 7 overlay lines + momentum histogram + squeeze markers from bars.
  function computeScalp(bars, nDisp) {
    const hi = bars.map((b) => b.high), lo = bars.map((b) => b.low), cl = bars.map((b) => b.close);
    const mid = smaArr(cl, SQ_P), std = stdArr(cl, SQ_P), kcR = atrArr(hi, lo, cl, SQ_P);
    const bbU = mid.map((m, i) => m + BB_MULT * std[i]), bbL = mid.map((m, i) => m - BB_MULT * std[i]);
    const kcU = mid.map((m, i) => m + KC_MULT * kcR[i]), kcL = mid.map((m, i) => m - KC_MULT * kcR[i]);
    const ema9 = emaArr(cl, 9), ema21 = emaArr(cl, 21);
    const hh = rollMax(hi, SQ_P), ll = rollMin(lo, SQ_P);
    const val = cl.map((c, i) => c - (((hh[i] + ll[i]) / 2 + mid[i]) / 2));
    const mom = linregArr(val, SQ_MOM);

    const start = Math.max(0, bars.length - nDisp);
    const t = (i) => bars[i].time;
    const pack = (arr) => { const out = []; for (let i = start; i < bars.length; i++)
      if (isFinite(arr[i])) out.push({ time: t(i), value: arr[i] }); return out; };
    // order must match the static JSON: BB U/M/L, KC U/L, EMA9, EMA21
    const lineData = [pack(bbU), pack(mid), pack(bbL), pack(kcU), pack(kcL), pack(ema9), pack(ema21)];

    const hist = [];
    for (let i = start; i < bars.length; i++) { const v = mom[i]; if (!isFinite(v)) continue;
      const prev = isFinite(mom[i - 1]) ? mom[i - 1] : v;
      const color = v >= 0 ? (v >= prev ? "#00e6cc" : "#127d70") : (v <= prev ? "#ff3b3b" : "#7d1f1f");
      hist.push({ time: t(i), value: v, color }); }

    const markers = []; let prevOn = null;
    for (let i = start; i < bars.length; i++) {
      const on = isFinite(bbU[i]) && bbU[i] < kcU[i] && bbL[i] > kcL[i];
      if (prevOn !== null && on !== prevOn)
        markers.push(on
          ? { time: t(i), position: "belowBar", color: "#ff5b5b", shape: "circle", size: 1 }
          : { time: t(i), position: "belowBar", color: "#2fd07f", shape: "arrowUp", size: 1, text: "fire" });
      prevOn = on;
    }
    return { lineData, hist, markers };
  }

  // ── MOMENTUM display stack (2026-09-22) ────────────────────────────────────
  // The Momentum lens does NOT use 5.0's 10/20/43/200 SMAs. It screens a
  // 20/50 cross (Rule B) under a 200 trend filter, and the 200 is the one the
  // score reads — so drawing 5.0's stack on a Momentum row would show a reader
  // averages no rule in that lens has ever consulted.
  //
  // THE SEEDING IS THE WHOLE POINT, and it is why this is not `emaArr` above.
  // `emaArr` is pandas' ewm(adjust=false): it seeds on the FIRST value and
  // emits from bar 0. Pine — and therefore scanner/momentum/ema.py — seeds with
  // the SMA of the first `length` values and is `na` before that. The seed
  // error decays as (1-alpha)^n, so it matters in inverse proportion to alpha:
  // negligible on the 20, measurable on the 200, which is exactly the line the
  // trend filter tests `close > slow` against. A chart drawn with the wrong
  // seed can therefore show price on the opposite side of the 200 from the
  // side the scanner scored. This is a direct port of `_recursive_ma(..., seed
  // = "sma")`; keep the two in step.
  function emaPine(vals, period) {
    const n = vals.length;
    const out = new Array(n).fill(NaN);
    const len = Math.floor(period);
    if (!(len >= 1) || !n) return out;
    let f = -1;
    for (let i = 0; i < n; i++) if (isFinite(vals[i])) { f = i; break; }
    if (f < 0 || n - f < len) return out;            // Pine returns na, not a guess
    const alpha = 2 / (len + 1);
    // A NaN inside the seed window: walk forward to the first clean one, exactly
    // as the Python does, rather than seeding off a mean that carries a hole.
    let start = -1, seed = NaN;
    for (let st = f; st <= n - len; st++) {
      let sum = 0, bad = false;
      for (let k = st; k < st + len; k++) { if (!isFinite(vals[k])) { bad = true; break; } sum += vals[k]; }
      if (!bad) { start = st + len - 1; seed = sum / len; break; }
    }
    if (start < 0) return out;
    let prev = seed;
    out[start] = prev;
    for (let i = start + 1; i < n; i++) {
      const x = vals[i];
      if (!isFinite(x)) { prev = NaN; out[i] = NaN; continue; }
      if (!isFinite(prev)) { prev = x; out[i] = x; continue; }
      prev = alpha * x + (1 - alpha) * prev;
      out[i] = prev;
    }
    return out;
  }

  // The lengths and the average TYPE are read from the payload's own `params`,
  // never hardcoded here: the scanner publishes the config it actually ran
  // (ma_type/fast_len/mid_len/slow_len), so retuning the screen moves the chart
  // with it instead of leaving a second copy to drift. Falls back to the
  // shipped defaults when an old payload has no params block.
  const MOM_MA_DEFAULTS = { ma_type: "EMA", fast_len: 20, mid_len: 50, slow_len: 200 };
  function momentumMAs(cl, mp) {
    const P = Object.assign({}, MOM_MA_DEFAULTS, mp || {});
    const sma = (span) => {
      const o = new Array(cl.length).fill(NaN);
      let sum = 0;
      for (let i = 0; i < cl.length; i++) {
        sum += cl[i];
        if (i >= span) sum -= cl[i - span];
        if (i >= span - 1) o[i] = sum / span;
      }
      return o;
    };
    const ma = (span) => (String(P.ma_type).toUpperCase() === "SMA" ? sma(span) : emaPine(cl, span));
    const t = String(P.ma_type).toUpperCase() === "SMA" ? "SMA" : "EMA";
    // TV palette, NOT the 5.0 one. Final_Top_Script plots fast/mid/slow as
    // blue / orange / green and the owner's screenshot reads that way at a
    // glance: a blue fast line over a green 200. The 5.0 chart's
    // white/yellow/purple/amber belongs to a different system and using it
    // here is most of why this page still looked like 5.0.
    return [
      { span: +P.fast_len, name: `${t} ${P.fast_len}`, color: "#2196f3", vals: ma(+P.fast_len) },
      { span: +P.mid_len,  name: `${t} ${P.mid_len}`,  color: "#ff9800", vals: ma(+P.mid_len) },
      { span: +P.slow_len, name: `${t} ${P.slow_len}`, color: "#26a69a", vals: ma(+P.slow_len) },
    ];
  }

  // Wilder's RMA (ta.rma): alpha = 1/length, seeded with the SMA of the first
  // `length` values -- the same seeding discipline as emaPine, and what
  // scanner/momentum/ema.py::wilder_rma does. RSI and ATR both ride on it.
  function rmaPine(vals, period) {
    const n = vals.length, out = new Array(n).fill(NaN), len = Math.floor(period);
    if (!(len >= 1) || !n) return out;
    let f = -1;
    for (let i = 0; i < n; i++) if (isFinite(vals[i])) { f = i; break; }
    if (f < 0 || n - f < len) return out;
    const alpha = 1 / len;
    let start = -1, seed = NaN;
    for (let st = f; st <= n - len; st++) {
      let sum = 0, bad = false;
      for (let k = st; k < st + len; k++) { if (!isFinite(vals[k])) { bad = true; break; } sum += vals[k]; }
      if (!bad) { start = st + len - 1; seed = sum / len; break; }
    }
    if (start < 0) return out;
    let prev = seed; out[start] = prev;
    for (let i = start + 1; i < n; i++) {
      const x = vals[i];
      if (!isFinite(x)) { prev = NaN; out[i] = NaN; continue; }
      if (!isFinite(prev)) { prev = x; out[i] = x; continue; }
      prev = alpha * x + (1 - alpha) * prev;
      out[i] = prev;
    }
    return out;
  }

  function rsiPine(cl, period) {
    const n = cl.length, up = new Array(n).fill(NaN), dn = new Array(n).fill(NaN);
    for (let i = 1; i < n; i++) {
      const ch = cl[i] - cl[i - 1];
      up[i] = Math.max(ch, 0); dn[i] = Math.max(-ch, 0);
    }
    const ru = rmaPine(up, period), rd = rmaPine(dn, period), out = new Array(n).fill(NaN);
    for (let i = 0; i < n; i++) {
      if (!isFinite(ru[i]) || !isFinite(rd[i])) continue;
      out[i] = rd[i] === 0 ? (ru[i] > 0 ? 100 : 50) : 100 - 100 / (1 + ru[i] / rd[i]);
    }
    return out;
  }

  function macdPine(cl, f, sl, sg) {
    const ef = emaPine(cl, f), es = emaPine(cl, sl);
    const line = cl.map((_, i) => (isFinite(ef[i]) && isFinite(es[i]) ? ef[i] - es[i] : NaN));
    const sig = emaPine(line, sg);
    return { line, signal: sig, hist: line.map((v, i) => (isFinite(v) && isFinite(sig[i]) ? v - sig[i] : NaN)) };
  }

  function atrPine(bars, period) {
    const tr = bars.map((b, i) => (i === 0 ? b.high - b.low : Math.max(
      b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close))));
    return rmaPine(tr, period);
  }

  // ── THE AUTO TRADE BOX, from tradingview/Final_Top_Script.pine ─────────────
  // Recovered 2026-09-22 and ported line-for-line. It is NOT vivek.py's plan and
  // shares no code with it: it anchors to the last SCORED CROSS (the 20/50 cross
  // that is Rule B) within `autoMaxAge` bars, stops at the 5-bar swing plus an
  // ATR pad, caps that distance at `maxStopPct` of entry, and lays TP1/2/3 at
  // 1R/2R/3R -- `math.max(..., entRaw * 0.05)` and all.
  //
  // Verified against the owner's TradingView ELS 1D screenshot on the committed
  // daily series: Entry 5.88 / SL 6.76 / TP1 5.00 / TP2 4.12 / TP3 3.23, worst
  // absolute error $0.0040, which is TradingView printing 6.76 for 6.7620.
  const TV_PLAN = {
    swingLen: 5, atrPad: 0.25, atrMult: 1.5, slMode: "Swing",
    maxStopPct: 15, r: [1, 2, 3], autoMaxAge: 60, minScore: 1,
    macd: [12, 26, 9], rsiLen: 14, atrLen: 14,
    useMacd: true, useSlow: true, useRsi: false,
  };
  function momentumPlan(bars, mp) {
    const P = Object.assign({}, MOM_MA_DEFAULTS, mp || {});
    const n = bars.length;
    if (n < 2) return null;
    const cl = bars.map((b) => b.close);
    const fast = emaPine(cl, +P.fast_len), mid = emaPine(cl, +P.mid_len), slow = emaPine(cl, +P.slow_len);
    const { hist } = macdPine(cl, TV_PLAN.macd[0], TV_PLAN.macd[1], TV_PLAN.macd[2]);
    const rsi = rsiPine(cl, TV_PLAN.rsiLen);
    const atr = atrPine(bars, TV_PLAN.atrLen);
    const L = TV_PLAN.swingLen;
    let sigBar = -1, sigDir = 0, sigScore = 0, sigEntry = NaN, sigStop = NaN;
    for (let i = 1; i < n; i++) {
      if (!(isFinite(fast[i]) && isFinite(mid[i]) && isFinite(fast[i - 1]) && isFinite(mid[i - 1]))) continue;
      const bullX = fast[i - 1] <= mid[i - 1] && fast[i] > mid[i];
      const bearX = fast[i - 1] >= mid[i - 1] && fast[i] < mid[i];
      if (!bullX && !bearX) continue;
      const above = isFinite(slow[i]) && cl[i] > slow[i], below = isFinite(slow[i]) && cl[i] < slow[i];
      const bullScore = 1 + (TV_PLAN.useMacd && hist[i] > 0 ? 1 : 0) + (TV_PLAN.useSlow && above ? 1 : 0)
                          + (TV_PLAN.useRsi && rsi[i] > 50 ? 1 : 0);
      const bearScore = 1 + (TV_PLAN.useMacd && hist[i] < 0 ? 1 : 0) + (TV_PLAN.useSlow && below ? 1 : 0)
                          + (TV_PLAN.useRsi && rsi[i] < 50 ? 1 : 0);
      let dir = 0, score = 0;
      if (bullX && bullScore >= TV_PLAN.minScore) { dir = 1; score = bullScore; }
      else if (bearX && bearScore >= TV_PLAN.minScore) { dir = -1; score = bearScore; }
      else continue;
      // 5-bar swing at the signal bar, ATR-padded — ta.lowest/highest(len).
      let lo = Infinity, hi = -Infinity;
      for (let k = Math.max(0, i - L + 1); k <= i; k++) { lo = Math.min(lo, bars[k].low); hi = Math.max(hi, bars[k].high); }
      const a = isFinite(atr[i]) ? atr[i] : 0;
      sigBar = i; sigDir = dir; sigScore = score; sigEntry = cl[i];
      sigStop = TV_PLAN.slMode === "ATR"
        ? (dir === 1 ? cl[i] - a * TV_PLAN.atrMult : cl[i] + a * TV_PLAN.atrMult)
        : (dir === 1 ? lo - a * TV_PLAN.atrPad : hi + a * TV_PLAN.atrPad);
    }
    if (sigBar < 0 || !isFinite(sigEntry)) return null;
    const age = (n - 1) - sigBar;
    if (age > TV_PLAN.autoMaxAge) return null;          // stale signal draws nothing
    const capD = sigEntry * TV_PLAN.maxStopPct / 100;
    const stop = TV_PLAN.maxStopPct <= 0 ? sigStop
      : sigDir === 1 ? Math.max(sigStop, sigEntry - capD) : Math.min(sigStop, sigEntry + capD);
    const risk = Math.abs(sigEntry - stop);
    const tp = TV_PLAN.r.map((r) => Math.max(sigEntry + sigDir * risk * r, sigEntry * 0.05));
    return {
      dir: sigDir, score: sigScore, age, capped: Math.abs(stop - sigStop) > 1e-12,
      bar: bars[sigBar], entry: sigEntry, stop, risk,
      tp1: tp[0], tp2: tp[1], tp3: tp[2], rawStop: sigStop,
    };
  }

  // Strict both-sides pivots ON THE RSI SERIES, returning CONFIRMATION indices
  // (a pivot at i-right is only knowable at i). Strict on both sides means a
  // tie is not a pivot -- scanner/momentum/config.py's pivot_strict_* default.
  function pivotIdx(vals, left, right, low) {
    const out = [], n = vals.length;
    for (let i = left; i + right < n; i++) {
      const v = vals[i];
      if (!isFinite(v)) continue;
      let ok = true;
      for (let k = i - left; k <= i + right && ok; k++) {
        if (k === i || !isFinite(vals[k])) { if (!isFinite(vals[k])) ok = false; continue; }
        ok = low ? v < vals[k] : v > vals[k];
      }
      if (ok) out.push({ pivot: i, confirm: i + right });
    }
    return out;
  }

  // Regular bull/bear divergence, Final_RSI_Plus.pine's rule exactly.
  //
  // THE GAP IS 6..61, NOT 5..60, and it is inherited from TradingView's own
  // Divergence Indicator: f_inRange is called with plFound[1], so
  // ta.barssince() reads (i - previous_confirm - 1). scanner/momentum/screen.py
  // carries the same note; the two must not drift.
  function momentumDivs(bars, rsi, mp) {
    const P = mp || {};
    const L = +(P.piv_left ?? 5), R = +(P.piv_right ?? 5);
    const LO = +(P.range_lower ?? 5), UP = +(P.range_upper ?? 60);
    const lows = pivotIdx(rsi, L, R, true), highs = pivotIdx(rsi, L, R, false);
    const out = [];
    const scan = (piv, bull) => {
      for (let k = 1; k < piv.length; k++) {
        const cur = piv[k], prev = piv[k - 1];
        const gap = cur.confirm - prev.confirm - 1;          // ta.barssince(cond[1])
        if (!(gap >= LO && gap <= UP)) continue;
        const rNow = rsi[cur.pivot], rPrev = rsi[prev.pivot];
        if (!isFinite(rNow) || !isFinite(rPrev)) continue;
        const pNow = bull ? bars[cur.pivot].low : bars[cur.pivot].high;
        const pPrev = bull ? bars[prev.pivot].low : bars[prev.pivot].high;
        const hit = bull ? (pNow < pPrev && rNow > rPrev) : (pNow > pPrev && rNow < rPrev);
        if (hit) out.push({ bull, pivot: cur.pivot, confirm: cur.confirm, rsi: rNow });
      }
    };
    scan(lows, true); scan(highs, false);
    out.sort((a, b) => a.pivot - b.pivot);
    return out;
  }

  // Every scored cross in the series, for the on-price labels the template
  // draws ("+3 Bullish" / "-2 Bearish"). Same scoring as momentumPlan -- both
  // read TV_PLAN, so a retune moves the labels and the box together.
  function momentumCrosses(bars, mp) {
    const P = Object.assign({}, MOM_MA_DEFAULTS, mp || {});
    const cl = bars.map((b) => b.close);
    const fast = emaPine(cl, +P.fast_len), mid = emaPine(cl, +P.mid_len), slow = emaPine(cl, +P.slow_len);
    const { hist } = macdPine(cl, TV_PLAN.macd[0], TV_PLAN.macd[1], TV_PLAN.macd[2]);
    const rsi = rsiPine(cl, TV_PLAN.rsiLen);
    const out = [];
    for (let i = 1; i < bars.length; i++) {
      if (!(isFinite(fast[i]) && isFinite(mid[i]) && isFinite(fast[i - 1]) && isFinite(mid[i - 1]))) continue;
      const bullX = fast[i - 1] <= mid[i - 1] && fast[i] > mid[i];
      const bearX = fast[i - 1] >= mid[i - 1] && fast[i] < mid[i];
      if (!bullX && !bearX) continue;
      const above = isFinite(slow[i]) && cl[i] > slow[i], below = isFinite(slow[i]) && cl[i] < slow[i];
      const bs = 1 + (TV_PLAN.useMacd && hist[i] > 0 ? 1 : 0) + (TV_PLAN.useSlow && above ? 1 : 0)
                   + (TV_PLAN.useRsi && rsi[i] > 50 ? 1 : 0);
      const rs = 1 + (TV_PLAN.useMacd && hist[i] < 0 ? 1 : 0) + (TV_PLAN.useSlow && below ? 1 : 0)
                   + (TV_PLAN.useRsi && rsi[i] < 50 ? 1 : 0);
      if (bullX && bs >= TV_PLAN.minScore) out.push({ i, bull: true, score: bs });
      else if (bearX && rs >= TV_PLAN.minScore) out.push({ i, bull: false, score: rs });
    }
    return out;
  }

  // MACD + RSI pane series for a timeframe, Pine-seeded throughout.
  //
  // ONE POINT PER BAR, ALWAYS (2026-10-13). The panes are separate charts kept
  // in step with the price chart by LOGICAL index (bar number), so pane bar i
  // must be price bar i. Warm-up bars used to be dropped, which made the MACD
  // pane's bar 0 the price chart's bar ~25 and the RSI pane's bar ~14: both
  // panes were drawn that many bars early against the candles. A warm-up bar
  // is now a whitespace point ({ time } with no value): nothing is drawn, but
  // it still counts as a bar. No value is changed.
  function momentumPanes(bars) {
    const cl = bars.map((b) => b.close);
    const m = macdPine(cl, TV_PLAN.macd[0], TV_PLAN.macd[1], TV_PLAN.macd[2]);
    const rsi = rsiPine(cl, TV_PLAN.rsiLen);
    const at = (arr) => bars.map((b, i) => (isFinite(arr[i]) ? { time: b.time, value: arr[i] } : { time: b.time }));
    return {
      macd: at(m.line), macdSignal: at(m.signal),
      macdHist: bars.map((b, i) => (isFinite(m.hist[i])
        ? { time: b.time, value: m.hist[i],
            color: m.hist[i] >= 0 ? "rgba(47,208,127,0.7)" : "rgba(255,91,91,0.7)" } : { time: b.time })),
      rsi: at(rsi),
      // RSI+ draws the RSI and its MA together with a fill between them; the
      // MA is an SMA(14) of the RSI by default (maType "SMA").
      rsiSignal: at((() => {
        const out = new Array(rsi.length).fill(NaN);
        let sum = 0, n = 0;
        for (let i = 0; i < rsi.length; i++) {
          if (!isFinite(rsi[i])) { sum = 0; n = 0; continue; }
          sum += rsi[i]; n++;
          if (n > 14) { sum -= rsi[i - 14]; n = 14; }
          if (n === 14) out[i] = sum / 14;
        }
        return out;
      })()),
    };
  }

  return Object.freeze({
    // scalp overlays
    emaArr, smaArr, stdArr, atrArr, rollMax, rollMin, linregArr, computeScalp,
    // momentum stack + the Auto plan
    MOM_MA_DEFAULTS, emaPine, momentumMAs, rmaPine, rsiPine, macdPine, atrPine,
    TV_PLAN, momentumPlan, pivotIdx, momentumDivs, momentumCrosses, momentumPanes,
  });
})();

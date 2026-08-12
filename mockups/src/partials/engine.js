/* ===========================================================================
   Steinmetz Lab mockups — shared rendering engine.

   Everything here runs on real recordings exported from the lab server:
     · raster    141 simultaneously recorded neurons, 90 s, Neuropixels + Kilosort
     · widefield 8 SVD components of dorsal-cortex calcium imaging, 900 frames @ 35 Hz

   Frames are rebuilt in the browser (dF/F = U · dV) rather than shipped as video,
   which is why a whole cortical movie costs ~150 KB.
   =========================================================================== */
const SL = (() => {
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------------------------------------------------------------- decoding */
  const b64 = (s, Type) => {
    const bin = atob(s);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Type(bytes.buffer);
  };

  function decodeRaster(json) {
    const t = b64(json.t, Uint16Array); // time, in bin_ms units, ascending
    const row = b64(json.r, Uint8Array); // neuron index, ordered by depth
    const depth = Float32Array.from(json.depth);
    const binMs = json.meta.bin_ms;
    const durMs = json.meta.duration_s * 1000;

    // Population rate, computed once: spikes/s averaged over the population.
    const BIN = 50; // ms
    const nb = Math.ceil(durMs / BIN);
    const counts = new Float32Array(nb);
    for (let i = 0; i < t.length; i++) counts[Math.min(nb - 1, (t[i] * binMs / BIN) | 0)]++;
    const rate = new Float32Array(nb);
    const perBin = 1000 / BIN / json.meta.n_neurons;
    for (let i = 0; i < nb; i++) rate[i] = counts[i] * perBin;
    // light smoothing so the trace reads as a rate, not a histogram
    const smooth = new Float32Array(nb);
    for (let i = 0; i < nb; i++) {
      let s = 0, n = 0;
      for (let k = -2; k <= 2; k++) { const j = i + k; if (j >= 0 && j < nb) { s += rate[j]; n++; } }
      smooth[i] = s / n;
    }

    return {
      meta: json.meta, t, row, depth, binMs, durMs,
      nNeurons: json.meta.n_neurons,
      rate: smooth, rateBinMs: BIN,
      // first spike index at or after time `ms` (t is sorted)
      seek(ms) {
        const target = ms / binMs;
        let lo = 0, hi = t.length;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (t[mid] < target) lo = mid + 1; else hi = mid; }
        return lo;
      },
    };
  }

  function decodeWidefield(json) {
    const [H, W] = json.meta.px;
    const K = json.meta.n_components;
    const T = json.meta.n_frames;
    const Uq = b64(json.U, Int8Array);   // idx = k*H*W + row*W + col (row-major per component)
    const Vq = b64(json.V, Int16Array);  // idx = t*K + k

    const HW = H * W;
    const U = new Float32Array(HW * K);
    for (let k = 0; k < K; k++) {
      const s = json.u_scale[k] / 127;
      for (let i = 0; i < HW; i++) U[i + k * HW] = Uq[i + k * HW] * s;
    }
    const V = new Float32Array(T * K);
    for (let t = 0; t < T; t++) {
      for (let k = 0; k < K; k++) V[t * K + k] = Vq[t * K + k] * (json.v_scale[k] / 32000);
    }

    return { meta: json.meta, H, W, K, T, U, V, limit: json.meta.limit, fps: json.meta.fps,
             rectified: !!json.meta.rectified };
  }

  /* ------------------------------------------------------------- color ramp */
  const hex = (s) => {
    s = s.trim().replace('#', '');
    if (s.length === 3) s = s.split('').map((c) => c + c).join('');
    const n = parseInt(s, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };

  function rampStops() {
    const cs = getComputedStyle(document.documentElement);
    return [0, 1, 2, 3, 4].map((i) => hex(cs.getPropertyValue('--d' + i) || '#888'));
  }

  /** 256-entry lookup table across the current palette's data ramp. */
  function rampLUT(n = 256) {
    const stops = rampStops();
    const lut = new Uint8ClampedArray(n * 3);
    const seg = stops.length - 1;
    for (let i = 0; i < n; i++) {
      const x = (i / (n - 1)) * seg;
      const j = Math.min(seg - 1, x | 0);
      const f = x - j;
      for (let c = 0; c < 3; c++) lut[i * 3 + c] = stops[j][c] + (stops[j + 1][c] - stops[j][c]) * f;
    }
    return lut;
  }

  const lutCSS = (lut, i, alpha = 1) => {
    const k = (Math.max(0, Math.min(255, i | 0)) * 3);
    return `rgb(${lut[k]} ${lut[k + 1]} ${lut[k + 2]} / ${alpha})`;
  };

  /* --------------------------------------------------- palette change plumbing */
  const listeners = new Set();
  const onPalette = (fn) => { listeners.add(fn); return fn; };
  const firePalette = () => listeners.forEach((f) => { try { f(); } catch (e) { console.error(e); } });

  function initPaletteSwitch(root = document) {
    const btns = [...root.querySelectorAll('.pal__btn')];
    const set = (name) => {
      document.documentElement.dataset.palette = name;
      btns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.pal === name)));
      firePalette();
    };
    btns.forEach((b) => b.addEventListener('click', () => set(b.dataset.pal)));
    return set;
  }

  /* -------------------------------------------------------- canvas sizing helper */
  function fitCanvas(cv) {
    const dpr = Math.min(2, devicePixelRatio || 1);
    const r = cv.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width * dpr));
    const h = Math.max(1, Math.round(r.height * dpr));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    return { w, h, dpr };
  }

  /** Redraw whenever the element's box changes — covers webfont swap, image loads,
   *  container resize, and the case where no animation frame ever runs. */
  function observeSize(cv, redraw) {
    if (typeof ResizeObserver === 'function') {
      let first = true;
      new ResizeObserver(() => {
        if (first) { first = false; redraw(); return; }
        redraw();
      }).observe(cv);
    }
    addEventListener('resize', redraw, { passive: true });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(redraw).catch(() => {});
  }

  /* ============================================================ raster ==
     Two ways of showing the same real recording moving in time:

       mode 'scroll'  the whole raster slides leftward past a fixed frame, the way a
                      scrolling oscilloscope trace does. No sweep bar -- the motion
                      IS the time axis.
       mode 'sweep'   the raster stands still and a bar travels left to right, laying
                      down new spikes behind it and wiping the old ones just ahead,
                      the way a chart recorder or a clinical monitor does.

     Mixing the two (scrolling AND a sweep bar) reads as two clocks at once, so a page
     should pick one.

     Other opts:
       spanS     seconds across the full width
       speed     seconds of data per second of wall clock
       dotAlpha  opacity of a single spike
       padTop/padBottom  fraction of height left clear
       vertical  draw time downward instead of rightward (scroll mode only)
  */
  function raster(cv, data, opts = {}) {
    const o = Object.assign(
      {
        mode: 'scroll', spanS: 8, speed: 1, dotAlpha: 1, dotW: 1.6,
        padTop: 0, padBottom: 0, vertical: false, fade: true,
        // where along the palette ramp the shallowest and deepest units sit; a higher
        // floor keeps the dim end of the ramp off the spikes so they stay legible
        shadeLo: 118, shadeHi: 255,
        // sweep mode only: an element the page positions as the glowing bar. Drawing the
        // bar onto the canvas itself leaves a pale residue behind every frame.
        barEl: null,
      },
      opts
    );
    const ctx = cv.getContext('2d', { alpha: true });
    let lut = rampLUT();
    let t0 = 0, raf = 0, last = 0, running = false;
    let swept = 0;   // sweep mode: total data time laid down so far, in ms

    onPalette(() => { lut = rampLUT(); repaint(); });

    /** Geometry shared by both modes. */
    function geom(w, h) {
      const top = h * o.padTop;
      const usable = h * (1 - o.padTop - o.padBottom);
      return {
        top,
        rowH: usable / data.nNeurons,
        dotH: Math.max(1, (usable / data.nNeurons) * 0.82),
      };
    }

    const shadeOf = (r) =>
      o.shadeLo + (((r / data.nNeurons) * (o.shadeHi - o.shadeLo)) | 0);

    /* ---- scroll mode: repaint the whole visible window every frame ---- */
    function drawScroll(startMs) {
      const { w, h } = fitCanvas(cv);
      ctx.clearRect(0, 0, w, h);
      const spanMs = o.spanS * 1000;
      const g = geom(w, h);
      const along = o.vertical ? h : w;
      const rowSpan = o.vertical ? w / data.nNeurons : g.rowH;
      const dotAcross = Math.max(1, rowSpan * 0.82);
      const scale = along / spanMs;

      let i = data.seek(startMs);
      const endBin = (startMs + spanMs) / data.binMs;
      for (; i < data.t.length && data.t[i] < endBin; i++) {
        const tm = data.t[i] * data.binMs - startMs;
        const r = data.row[i];
        let alpha = o.dotAlpha;
        if (o.fade) {
          const f = tm / spanMs;               // soften both edges of the frame
          alpha *= f < 0.08 ? f / 0.08 : f > 0.92 ? (1 - f) / 0.08 : 1;
        }
        ctx.fillStyle = lutCSS(lut, shadeOf(r), alpha);
        if (o.vertical) ctx.fillRect(r * rowSpan, tm * scale, dotAcross, o.dotW);
        else ctx.fillRect(tm * scale, g.top + r * g.rowH, o.dotW, g.dotH);
      }
    }

    /* ---- sweep mode ------------------------------------------------------------
       The canvas persists and only the columns the bar has just crossed are redrawn.
       Work in whole pixel columns: clearing and redrawing the *same* integer range each
       time is what stops fractional edges leaving pale vertical residue behind the bar.
       Nothing is wiped ahead of the bar -- the previous cycle stays visible right up to
       it, the way a chart recorder looks.                                            */
    let lastX = 0;

    function paintColumns(xa, xb) {
      const w = cv.width, h = cv.height;
      const spanMs = o.spanS * 1000;
      const g = geom(w, h);
      xa = Math.max(0, Math.min(w, Math.floor(xa)));
      xb = Math.max(0, Math.min(w, Math.ceil(xb)));
      if (xb <= xa) return;

      ctx.clearRect(xa, 0, xb - xa, h);

      // the recording time that maps onto this band of columns, within the current cycle
      const cycle = Math.floor(swept / spanMs);
      const t0ms = (cycle * spanMs + (xa / w) * spanMs) % data.durMs;
      const durMs = ((xb - xa) / w) * spanMs;

      let i = data.seek(t0ms);
      const endBin = (t0ms + durMs) / data.binMs;
      for (; i < data.t.length && data.t[i] < endBin; i++) {
        const tm = data.t[i] * data.binMs - t0ms;
        const r = data.row[i];
        ctx.fillStyle = lutCSS(lut, shadeOf(r), o.dotAlpha);
        ctx.fillRect(xa + (tm / spanMs) * w, g.top + r * g.rowH, o.dotW, g.dotH);
      }
    }

    function placeBar(xFrac) {
      if (!o.barEl) return;
      o.barEl.style.left = (xFrac * 100).toFixed(3) + '%';
    }

    function repaintSweep() {
      const { w, h } = fitCanvas(cv);
      ctx.clearRect(0, 0, w, h);
      lastX = 0;
      paintColumns(0, (((swept % (o.spanS * 1000)) / (o.spanS * 1000)) * w) || 0);
      lastX = ((swept % (o.spanS * 1000)) / (o.spanS * 1000)) * w;
      placeBar(lastX / w);
    }

    const repaint = () => (o.mode === 'sweep' ? repaintSweep() : drawScroll(t0));

    function tick(ts) {
      if (!running) return;
      if (!last) last = ts;
      const dt = Math.min(80, ts - last);
      last = ts;
      if (o.mode === 'sweep') {
        const w = cv.width;
        const spanMs = o.spanS * 1000;
        swept += dt * o.speed;
        const x = ((swept % spanMs) / spanMs) * w;
        if (x >= lastX) {
          paintColumns(lastX, x);
        } else {              // wrapped past the right edge
          paintColumns(lastX, w);
          paintColumns(0, x);
        }
        lastX = x;
        placeBar(x / w);
      } else {
        t0 = (t0 + dt * o.speed) % Math.max(1, data.durMs - o.spanS * 1000);
        drawScroll(t0);
      }
      raf = requestAnimationFrame(tick);
    }

    const api = {
      start() {
        if (running || reduceMotion) { repaint(); return api; }
        running = true; last = 0; raf = requestAnimationFrame(tick); return api;
      },
      stop() { running = false; cancelAnimationFrame(raf); return api; },
      /** Pin the view to a specific start time (used by the scrubbers). */
      showAt(ms) { api.stop(); t0 = ms; drawScroll(ms); return api; },
      redraw() { repaint(); return api; },
      get time() { return o.mode === 'sweep' ? Math.max(0, swept - o.spanS * 1000) % data.durMs : t0; },
      get mode() { return o.mode; },
      set mode(m) {
        o.mode = m;
        swept = 0;
        lastX = 0;
        const { w, h } = fitCanvas(cv);
        ctx.clearRect(0, 0, w, h);
        if (o.barEl) o.barEl.hidden = m !== 'sweep';
        repaint();
      },
      set span(s) { o.spanS = s; repaint(); },
    };

    observeSize(cv, repaint);
    // only animate while on screen
    new IntersectionObserver((es) => es.forEach((e) => (e.isIntersecting ? api.start() : api.stop())), {
      rootMargin: '80px',
    }).observe(cv);
    if (o.barEl) o.barEl.hidden = o.mode !== 'sweep';   // honour the mode we started in
    repaint();
    return api;
  }

  /* ================================================== widefield calcium movie ==
     Rebuilds each frame as dF/F = U · dV and paints it through the palette ramp.
  */
  function widefield(cv, wf, opts = {}) {
    // `gain` divides the color limit, so >1 saturates sooner and pushes real activation
    // into the warm end of the ramp instead of leaving the whole frame mid-scale. Prefer
    // tuning this over `gamma`: a power curve drags the highlights down along with the
    // baseline, and past about 1.2 the activation peaks stop reaching the warm colors.
    const o = Object.assign({ speed: 1, gain: 1.35, alpha: 1, fit: 'contain', gamma: 1 }, opts);
    const ctx = cv.getContext('2d');
    const { H, W, K, T, U, V } = wf;
    const off = document.createElement('canvas');
    off.width = W; off.height = H;
    const octx = off.getContext('2d');
    const img = octx.createImageData(W, H);
    const px = new Float32Array(H * W);
    let lut = rampLUT();
    let frame = 0, raf = 0, last = 0, running = false;

    onPalette(() => { lut = rampLUT(); render(frame); });

    function render(f) {
      f = Math.max(0, Math.min(T - 1, f | 0));
      px.fill(0);
      for (let k = 0; k < K; k++) {
        const v = V[f * K + k];
        if (v === 0) continue;
        const base = k * H * W;
        for (let i = 0; i < px.length; i++) px[i] += U[base + i] * v;
      }
      const lim = wf.limit / o.gain;
      const d = img.data;
      // A rectified asset has already had each pixel's own baseline removed, so zero is a
      // real floor and belongs at the dark end of the ramp. An unrectified one is signed
      // and needs the symmetric mapping, where zero lands mid-ramp.
      const rect = !!wf.rectified;
      for (let i = 0; i < px.length; i++) {
        const p = i * 4;
        let x = rect ? px[i] / lim               // 0..lim   -> 0..1
                     : (px[i] / lim + 1) / 2;    // -lim..lim -> 0..1
        x = x < 0 ? 0 : x > 1 ? 1 : x;
        if (o.gamma !== 1) x = Math.pow(x, o.gamma);
        const c = ((x * 255) | 0) * 3;
        d[p] = lut[c]; d[p + 1] = lut[c + 1]; d[p + 2] = lut[c + 2];
        d[p + 3] = 255 * o.alpha;
      }
      octx.putImageData(img, 0, 0);

      const { w, h } = fitCanvas(cv);
      ctx.clearRect(0, 0, w, h);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      const s = o.fit === 'cover' ? Math.max(w / W, h / H) : Math.min(w / W, h / H);
      const dw = W * s, dh = H * s;
      ctx.drawImage(off, (w - dw) / 2, (h - dh) / 2, dw, dh);
    }

    function tick(ts) {
      if (!running) return;
      if (!last) last = ts;
      const dt = Math.min(120, ts - last);
      last = ts;
      frame = (frame + (dt / 1000) * wf.fps * o.speed) % T;
      render(frame);
      raf = requestAnimationFrame(tick);
    }

    const api = {
      start() {
        if (running || reduceMotion) { render(frame); return api; }
        running = true; last = 0; raf = requestAnimationFrame(tick); return api;
      },
      stop() { running = false; cancelAnimationFrame(raf); return api; },
      showFrame(f) { frame = f; render(f); return api; },
      get frame() { return frame; },
      get nFrames() { return T; },
    };

    observeSize(cv, () => render(frame));
    new IntersectionObserver((es) => es.forEach((e) => (e.isIntersecting ? api.start() : api.stop())), {
      rootMargin: '80px',
    }).observe(cv);
    render(0);
    return api;
  }

  /* ============================================ line trace (population rate) == */
  function trace(cv, values, opts = {}) {
    const o = Object.assign(
      { lineWidth: 1.5, fill: true, cursor: null, color: null, window: null, onSeek: null },
      opts
    );
    const ctx = cv.getContext('2d');
    let lut = rampLUT();
    onPalette(() => { lut = rampLUT(); draw(o.cursor); });

    function draw(cursorFrac) {
      const { w, h, dpr } = fitCanvas(cv);
      ctx.clearRect(0, 0, w, h);
      let lo = Infinity, hi = -Infinity;
      for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
      const pad = (hi - lo) * 0.12 || 1;
      lo -= pad; hi += pad;
      const X = (i) => (i / (values.length - 1)) * w;
      const Y = (v) => h - ((v - lo) / (hi - lo)) * h;
      const stroke = o.color || lutCSS(lut, 210, 1);

      // the slice currently shown in the raster above, if any
      if (o.window) {
        const [a, b] = o.window;
        ctx.fillStyle = lutCSS(lut, 235, 0.16);
        ctx.fillRect(a * w, 0, Math.max(1, (b - a) * w), h);
        ctx.strokeStyle = lutCSS(lut, 245, 0.75);
        ctx.lineWidth = 1 * dpr;
        ctx.strokeRect(a * w + 0.5, 0.5, Math.max(1, (b - a) * w) - 1, h - 1);
      }

      if (o.fill) {
        const g = ctx.createLinearGradient(0, 0, 0, h);
        g.addColorStop(0, lutCSS(lut, 200, 0.32));
        g.addColorStop(1, lutCSS(lut, 200, 0));
        ctx.beginPath();
        ctx.moveTo(0, h);
        for (let i = 0; i < values.length; i++) ctx.lineTo(X(i), Y(values[i]));
        ctx.lineTo(w, h);
        ctx.closePath();
        ctx.fillStyle = g;
        ctx.fill();
      }
      ctx.beginPath();
      for (let i = 0; i < values.length; i++) i ? ctx.lineTo(X(i), Y(values[i])) : ctx.moveTo(X(i), Y(values[i]));
      ctx.strokeStyle = stroke;
      ctx.lineWidth = o.lineWidth * dpr;
      ctx.lineJoin = 'round';
      ctx.stroke();

      if (cursorFrac != null) {
        const x = cursorFrac * w;
        ctx.beginPath();
        ctx.moveTo(x, 0); ctx.lineTo(x, h);
        ctx.strokeStyle = lutCSS(lut, 250, 0.9);
        ctx.lineWidth = 1 * dpr;
        ctx.stroke();
      }
      return { lo, hi };
    }

    observeSize(cv, () => draw(o.cursor));
    const api = {
      draw,
      get cursor() { return o.cursor; },
      set cursor(f) { o.cursor = f; draw(f); },
      /** Highlight a slice of the trace, as [startFrac, endFrac]. */
      set window(wnd) { o.window = wnd; draw(o.cursor); },
    };

    /** Click or drag anywhere on the trace to jump the movie there. */
    if (o.onSeek) {
      const frac = (e) => {
        const r = cv.getBoundingClientRect();
        return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      };
      cv.style.cursor = 'ew-resize';
      cv.style.touchAction = 'none';           // let a horizontal drag scrub, not scroll
      cv.addEventListener('pointerdown', (e) => {
        cv.setPointerCapture(e.pointerId);
        o.onSeek(frac(e));
      });
      cv.addEventListener('pointermove', (e) => { if (e.buttons) o.onSeek(frac(e)); });
      // keyboard equivalent, so seeking is not mouse-only
      if (!cv.hasAttribute('tabindex')) cv.tabIndex = 0;
      cv.addEventListener('keydown', (e) => {
        const step = e.shiftKey ? 0.1 : 0.02;
        if (e.key === 'ArrowLeft') o.onSeek(Math.max(0, (o.cursor || 0) - step));
        else if (e.key === 'ArrowRight') o.onSeek(Math.min(1, (o.cursor || 0) + step));
        else if (e.key === 'Home') o.onSeek(0);
        else if (e.key === 'End') o.onSeek(1);
        else return;
        e.preventDefault();
      });
    }

    draw(null);
    return api;
  }

  /* ========================================================== PCB trace motif ==
     The lab logo is a brain drawn as a printed-circuit board, and the department-retreat
     poster frames every panel with the same language: a trace runs along an edge, turns a
     corner at 45 degrees, and terminates in a small open pad.

     These are generated as SVG at the element's real pixel size (so the pads stay circular
     at any aspect ratio) and re-generated on resize. They draw themselves in when revealed.
  */
  const PCB_NS = 'http://www.w3.org/2000/svg';

  function pcbSvg(el, build) {
    let svg = el.querySelector(':scope > .pcb');
    if (!svg) {
      svg = document.createElementNS(PCB_NS, 'svg');
      svg.setAttribute('class', 'pcb');
      svg.setAttribute('aria-hidden', 'true');
      svg.setAttribute('fill', 'none');
      el.appendChild(svg);
    }
    const draw = () => {
      const r = el.getBoundingClientRect();
      const w = Math.max(1, Math.round(r.width));
      const h = Math.max(1, Math.round(r.height));
      svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
      svg.setAttribute('width', w);
      svg.setAttribute('height', h);
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      build(svg, w, h);
      // measure the path so the draw-in animation is length-correct
      svg.querySelectorAll('path').forEach((p) => {
        const len = p.getTotalLength();
        p.style.setProperty('--len', len);
      });
    };
    draw();
    if (typeof ResizeObserver === 'function') {
      let skip = true;
      new ResizeObserver(() => { if (skip) { skip = false; return; } draw(); }).observe(el);
    }
    addEventListener('resize', draw, { passive: true });
    return svg;
  }

  const pad = (svg, x, y, r = 3.5) => {
    const c = document.createElementNS(PCB_NS, 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', r);
    c.setAttribute('class', 'pcb__pad');
    svg.appendChild(c);
    return c;
  };
  const wire = (svg, d) => {
    const p = document.createElementNS(PCB_NS, 'path');
    p.setAttribute('d', d);
    p.setAttribute('class', 'pcb__wire');
    svg.appendChild(p);
    return p;
  };

  /** A rule that runs right from the label, steps up at 45 degrees, and ends in a pad. */
  function pcbRule(el) {
    return pcbSvg(el, (svg, w, h) => {
      const y = h - 1.5, up = Math.min(10, h - 8), endX = w - 10;
      wire(svg, `M0 ${y} H${endX - up - 14} L${endX - 14} ${y - up} H${endX}`);
      pad(svg, endX + 4.5, y - up);
    });
  }

  /** An L-shaped trace tucked into a panel corner, with a pad on the free end.
   *  `m` insets it from the edge so it reads as a detail inside the panel rather than
   *  doubling the panel's own border (and so it survives `overflow: hidden`). */
  function pcbCorner(el, corner = 'bl', arm = 46, m = 10) {
    return pcbSvg(el, (svg, w, h) => {
      const ch = 9;
      if (corner === 'bl') {
        wire(svg, `M${m} ${h - m - arm} V${h - m - ch} L${m + ch} ${h - m} H${m + arm}`);
        pad(svg, m + arm + 5.5, h - m);
      } else {
        wire(svg, `M${w - m} ${m + arm} V${m + ch} L${w - m - ch} ${m} H${w - m - arm}`);
        pad(svg, w - m - arm - 5.5, m);
      }
    });
  }

  /** A full bracket around a block, as on the retreat poster. */
  function pcbBracket(el, armFrac = 0.34) {
    return pcbSvg(el, (svg, w, h) => {
      const ch = 10, a = Math.max(30, w * armFrac);
      wire(svg, `M0 ${h} V${ch} L${ch} 0 H${a}`);
      pad(svg, a + 5.5, 0);
      wire(svg, `M${w} 0 V${h - ch} L${w - ch} ${h} H${w - a}`);
      pad(svg, w - a - 5.5, h);
    });
  }

  /* ============================================================== psychometric */
  /** Three-choice psychometric: measured proportions with 95% binomial intervals, and
   *  the Burgess et al. 2017 observer model regenerated from its six fitted parameters.
   *  Drawn rather than filmed, so it stays sharp at any size and follows the palette.
   *
   *  data = { params: {bL,bR,sL,sR,c50,n}, points: [{dc, n, p:[L,R,0], ci:[[lo,hi]x3]}] } */
  function psychometric(cv, data, opts = {}) {
    const o = Object.assign({ pad: { l: 46, r: 14, t: 14, b: 40 }, dur: 1500, hold: 5000, loop: true, dot: 3.4 }, opts);
    const ctx = cv.getContext('2d');
    let lut = rampLUT();
    let t0 = null, done = reduceMotion, raf = 0, running = false;

    // model probabilities along the pedestal-0 slice: one side carries the contrast
    const P = data.params;
    const f = (c) => (c <= 0 ? 0 : Math.pow(c, P.n) / (Math.pow(P.c50, P.n) + Math.pow(c, P.n)));
    function probs(dc) {
      const zL = P.bL + P.sL * f(Math.max(0, -dc) / 100);
      const zR = P.bR + P.sR * f(Math.max(0, dc) / 100);
      const m = Math.max(0, zL, zR);
      const eL = Math.exp(zL - m), eR = Math.exp(zR - m), e0 = Math.exp(-m);
      const s = eL + eR + e0;
      return [eL / s, eR / s, e0 / s];
    }
    const N = 160;
    const grid = Array.from({ length: N }, (_, i) => -100 + (200 * i) / (N - 1));
    const curve = grid.map(probs);

    // left cool, right warm, NoGo neutral ink -- the same assignment as the review clip.
    // NoGo must NOT come off the ramp: mid-ramp is green in every palette, so it would
    // read as a second "left" curve.
    const LABELS = ['Left', 'Right', 'NoGo'];    // the order of data.points[].p
    const colOf = (k, a = 1) => {
      if (k === 2) {
        const ink = getComputedStyle(document.documentElement)
          .getPropertyValue('--di-2').trim() || '#9aa';
        return a === 1 ? ink : `color-mix(in srgb, ${ink} ${a * 100}%, transparent)`;
      }
      return lutCSS(lut, k === 0 ? 70 : 238, a);
    };

    function draw(frac) {
      const { w, h, dpr } = fitCanvas(cv);
      const p = { l: o.pad.l * dpr, r: o.pad.r * dpr, t: o.pad.t * dpr, b: o.pad.b * dpr };
      ctx.clearRect(0, 0, w, h);
      const x0 = p.l, x1 = w - p.r, y0 = p.t, y1 = h - p.b;
      if (x1 <= x0 || y1 <= y0) return;
      const X = (dc) => x0 + ((dc + 100) / 200) * (x1 - x0);
      const Y = (v) => y1 - v * (y1 - y0);

      // canvas cannot parse var() in a font string or a color, so resolve them here
      const cs = getComputedStyle(document.documentElement);
      const mono = cs.getPropertyValue('--mono').trim() || 'monospace';
      ctx.lineWidth = Math.max(1, dpr);
      ctx.strokeStyle = cs.getPropertyValue('--drule').trim() || '#333';
      ctx.beginPath();
      ctx.moveTo(x0, y0); ctx.lineTo(x0, y1); ctx.lineTo(x1, y1);
      ctx.stroke();

      ctx.font = `${11 * dpr}px ${mono}`;
      ctx.fillStyle = cs.getPropertyValue('--di-3').trim() || '#888';
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText('1', x0 - 6 * dpr, Y(1));
      ctx.fillText('0', x0 - 6 * dpr, Y(0));
      ctx.textBaseline = 'top';
      const ty = y1 + 5 * dpr;
      ctx.textAlign = 'left'; ctx.fillText('-100', x0, ty);
      ctx.textAlign = 'center'; ctx.fillText('0', X(0), ty);
      ctx.textAlign = 'right'; ctx.fillText('+100', x1, ty);
      ctx.textAlign = 'center';
      ctx.fillText('Contrast difference (%)', (x0 + x1) / 2, ty + 14 * dpr);

      // y-axis title, rotated up the left edge
      ctx.save();
      ctx.translate(x0 - 20 * dpr, (y0 + y1) / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
      ctx.fillText('Proportion choices', 0, 0);
      ctx.restore();

      // legend, parked at the far left where all three curves are flat
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      LABELS.forEach((name, k) => {
        const ly = Y(0.66 - 0.13 * k);
        ctx.strokeStyle = colOf(k);
        ctx.lineWidth = 2 * dpr;
        ctx.beginPath();
        ctx.moveTo(x0 + 8 * dpr, ly); ctx.lineTo(x0 + 22 * dpr, ly);
        ctx.stroke();
        ctx.fillStyle = colOf(k);
        ctx.fillText(name, x0 + 27 * dpr, ly);
      });
      ctx.fillStyle = cs.getPropertyValue('--di-3').trim() || '#888';

      const m = Math.max(2, Math.round(N * frac));
      for (let k = 0; k < 3; k++) {
        ctx.strokeStyle = colOf(k);
        ctx.lineWidth = 2 * dpr;
        ctx.beginPath();
        for (let i = 0; i < m; i++) {
          const x = X(grid[i]), y = Y(curve[i][k]);
          i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        }
        ctx.stroke();
      }

      const shown = -100 + 200 * frac;
      for (const pt of data.points) {
        if (pt.dc > shown + 1e-6) continue;
        for (let k = 0; k < 3; k++) {
          const x = X(pt.dc);
          ctx.strokeStyle = colOf(k, 0.85);
          ctx.lineWidth = Math.max(1, 1.2 * dpr);
          ctx.beginPath();
          ctx.moveTo(x, Y(pt.ci[k][0])); ctx.lineTo(x, Y(pt.ci[k][1]));
          ctx.stroke();
          ctx.fillStyle = colOf(k);
          ctx.beginPath();
          ctx.arc(x, Y(pt.p[k]), o.dot * dpr, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // Sweep the curves in, hold the finished plot, then sweep again. One cycle is
    // dur + hold; within a cycle the fraction runs 0 -> 1 and then sits at 1.
    const cycle = () => o.dur + o.hold;
    const tick = (now) => {
      if (t0 === null) t0 = now;
      const into = o.loop ? (now - t0) % cycle() : now - t0;
      const frac = Math.min(1, into / o.dur);
      draw(frac);
      if (o.loop || frac < 1) raf = requestAnimationFrame(tick);
      else { done = true; running = false; }
    };

    const api = {
      draw: () => draw(done ? 1 : 0),
      /** Sweep the curves in; with `loop` set, keep doing so on a cycle. */
      start() {
        if (reduceMotion) { draw(1); return api; }
        if (running) return api;
        running = true;
        cancelAnimationFrame(raf);
        t0 = null;
        raf = requestAnimationFrame(tick);
        return api;
      },
      stop() { running = false; cancelAnimationFrame(raf); return api; },
    };
    onPalette(() => { lut = rampLUT(); draw(done || running ? 1 : 0); });
    observeSize(cv, () => draw(done || running ? 1 : 0));
    draw(reduceMotion ? 1 : 0);
    // only animate while on screen, like the raster and widefield panels
    new IntersectionObserver((es) => es.forEach((e) => (e.isIntersecting ? api.start() : api.stop())), {
      rootMargin: '80px',
    }).observe(cv);
    return api;
  }

  /* ================================================== scroll reveal + counters */
  function reveal(sel = '[data-reveal]') {
    const els = [...document.querySelectorAll(sel)];
    if (reduceMotion) { els.forEach((e) => e.classList.add('is-in')); return; }
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => {
        if (!e.isIntersecting) return;
        const el = e.target;
        const d = parseFloat(el.dataset.revealDelay || 0);
        setTimeout(() => el.classList.add('is-in'), d * 1000);
        if (el.dataset.count) countUp(el.querySelector('[data-count-target]') || el);
        io.unobserve(el);
      }),
      // Threshold 0, not a fraction: an element taller than the viewport can never reach
      // a fractional ratio, and would sit at opacity 0 for ever. The negative bottom
      // margin is what delays the reveal until the element is properly on screen.
      { threshold: 0, rootMargin: '0px 0px -12% 0px' }
    );
    els.forEach((e) => io.observe(e));
  }

  function countUp(el) {
    const to = parseFloat(el.dataset.countTarget ?? el.textContent.replace(/[^\d.]/g, ''));
    if (!isFinite(to)) return;
    const dec = (el.dataset.countDecimals | 0) || 0;
    const suffix = el.dataset.countSuffix || '';
    const dur = 900;
    const t0 = performance.now();
    const fmt = (v) => v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + suffix;
    if (reduceMotion) { el.textContent = fmt(to); return; }
    (function step(now) {
      const p = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(to * e);
      if (p < 1) requestAnimationFrame(step);
    })(t0);
  }

  return {
    reduceMotion, decodeRaster, decodeWidefield, rampLUT, lutCSS, onPalette, firePalette,
    initPaletteSwitch, fitCanvas, raster, widefield, trace, psychometric, reveal, countUp,
    pcbRule, pcbCorner, pcbBracket, observeSize,
  };
})();

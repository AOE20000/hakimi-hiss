// 共享动画工具：一切都是时间 t 的纯函数，保证逐帧渲染可复现。
// 镜头页面协议（render.py 依赖）：
//   window.SHOT = { start, end }       全片时间（秒），渲染区间 [start, end)
//   window.__ready  : Promise          资源（图片、字体、数据）全部就绪
//   window.__seek(t): Promise<void>    把画面定位到全片时间 t 并同步绘制完
(function () {
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, p) => a + (b - a) * p;

  const ease = {
    linear: (p) => p,
    inQuad: (p) => p * p,
    outQuad: (p) => 1 - (1 - p) * (1 - p),
    inCubic: (p) => p * p * p,
    outCubic: (p) => 1 - Math.pow(1 - p, 3),
    inOutCubic: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    inOutSine: (p) => -(Math.cos(Math.PI * p) - 1) / 2,
    outBack: (p, s = 1.70158) => 1 + (s + 1) * Math.pow(p - 1, 3) + s * Math.pow(p - 1, 2),
    outElastic: (p) =>
      p === 0 ? 0 : p === 1 ? 1 : Math.pow(2, -10 * p) * Math.sin((p * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1,
    outExpo: (p) => (p === 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  };

  const tw = (t, t0, dur, e = ease.linear) => e(clamp((t - t0) / Math.max(dur, 1e-6)));

  function kf(t, keys) {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const [t1, v1, e = ease.inOutCubic] = keys[i];
      const [t0, v0] = keys[i - 1];
      if (t <= t1) return lerp(v0, v1, e(clamp((t - t0) / (t1 - t0))));
    }
    return keys[keys.length - 1][1];
  }

  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let x = Math.imul(a ^ (a >>> 15), 1 | a);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }
  const hash = (n) => {
    const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return s - Math.floor(s);
  };

  function shake(t, t0, dur, amp, fps = 24) {
    if (t < t0 || t > t0 + dur) return [0, 0];
    const k = Math.floor((t - t0) * fps);
    const decay = 1 - (t - t0) / dur;
    return [(hash(k * 2 + 1) - 0.5) * 2 * amp * decay, (hash(k * 2 + 7) - 0.5) * 2 * amp * decay];
  }

  const onTwos = (t, fps = 24) => Math.floor(t * (fps / 2)) / (fps / 2);

  function loadImages(map) {
    const out = {};
    return Promise.all(
      Object.entries(map).map(
        ([k, src]) =>
          new Promise((res, rej) => {
            const im = new Image();
            im.onload = () => im.decode().then(() => res((out[k] = im)));
            im.onerror = () => rej(new Error("image load failed: " + src));
            im.src = src;
          })
      )
    ).then(() => out);
  }

  function focusLines(ctx, W, H, cx, cy, r0, n, t, { color = "#000", alpha = 1, seed = 1, fps = 12 } = {}) {
    const k = Math.floor(t * fps);
    const R = Math.hypot(W, H);
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + (hash(i * 13 + seed) - 0.5) * 0.08;
      const w = 0.004 + hash(i * 7 + k * 31 + seed) * 0.012;
      const rin = r0 * (0.85 + hash(i * 3 + k * 17 + seed) * 0.5);
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * rin, cy + Math.sin(a) * rin);
      ctx.lineTo(cx + Math.cos(a - w) * R, cy + Math.sin(a - w) * R);
      ctx.lineTo(cx + Math.cos(a + w) * R, cy + Math.sin(a + w) * R);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }

  function rays(ctx, W, H, cx, cy, n, rot, colorA, colorB) {
    const R = Math.hypot(W, H);
    ctx.save();
    ctx.fillStyle = colorB;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = colorA;
    for (let i = 0; i < n; i++) {
      const a0 = rot + (i / n) * Math.PI * 2;
      const a1 = a0 + Math.PI / n;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(a0) * R, cy + Math.sin(a0) * R);
      ctx.lineTo(cx + Math.cos(a1) * R, cy + Math.sin(a1) * R);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }

  function halftone(ctx, x, y, w, h, step, rmax, color, falloff) {
    ctx.save();
    ctx.fillStyle = color;
    for (let yy = y; yy < y + h; yy += step) {
      for (let xx = x + ((yy / step) % 2 ? step / 2 : 0); xx < x + w; xx += step) {
        const r = rmax * falloff((xx - x) / w, (yy - y) / h);
        if (r <= 0.3) continue;
        ctx.beginPath();
        ctx.arc(xx, yy, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();
  }

  function boltPath(x0, y0, x1, y1, segs, jitter, seed) {
    const r = rng(seed);
    const pts = [[x0, y0]];
    for (let i = 1; i < segs; i++) {
      const p = i / segs;
      const nx = -(y1 - y0), ny = x1 - x0;
      const L = Math.hypot(nx, ny);
      const off = (r() - 0.5) * 2 * jitter;
      pts.push([lerp(x0, x1, p) + (nx / L) * off, lerp(y0, y1, p) + (ny / L) * off]);
    }
    pts.push([x1, y1]);
    return pts;
  }
  function drawBolt(ctx, pts, width, fill, stroke) {
    const left = [], right = [];
    for (let i = 0; i < pts.length; i++) {
      const w = width * (1 - i / pts.length) + 2;
      const [x, y] = pts[i];
      const [xa, ya] = pts[Math.max(0, i - 1)];
      const [xb, yb] = pts[Math.min(pts.length - 1, i + 1)];
      let nx = -(yb - ya), ny = xb - xa;
      const L = Math.hypot(nx, ny) || 1;
      nx /= L; ny /= L;
      left.push([x + nx * w, y + ny * w]);
      right.push([x - nx * w, y - ny * w]);
    }
    ctx.save();
    ctx.beginPath();
    left.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    right.reverse().forEach(([x, y]) => ctx.lineTo(x, y));
    ctx.closePath();
    ctx.lineJoin = "miter";
    ctx.lineWidth = 6;
    ctx.strokeStyle = stroke;
    ctx.stroke();
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.restore();
  }

  function sparkle(ctx, x, y, r, rot, fill, stroke) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rot);
    ctx.beginPath();
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;
      const rr = i % 2 ? r * 0.22 : r;
      ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
    }
    ctx.closePath();
    if (stroke) {
      ctx.lineWidth = Math.max(2, r * 0.08);
      ctx.strokeStyle = stroke;
      ctx.stroke();
    }
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.restore();
  }

  function angerMark(ctx, x, y, s, rot) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rot);
    ctx.strokeStyle = "#d42a2a";
    ctx.lineCap = "round";
    ctx.lineWidth = s * 0.16;
    for (let i = 0; i < 4; i++) {
      ctx.save();
      ctx.rotate((i * Math.PI) / 2);
      ctx.beginPath();
      ctx.moveTo(s * 0.12, s * 0.5);
      ctx.quadraticCurveTo(s * 0.12, s * 0.12, s * 0.5, s * 0.12);
      ctx.stroke();
      ctx.restore();
    }
    ctx.restore();
  }

  // 烟尘团：先全画黑边，再全填白心，使整团只留外轮廓线
  function puff(ctx, x, y, r, p, seed, fill = "#fff", stroke = "#14101f") {
    if (p <= 0 || p >= 1) return;
    const R = rng(seed);
    const n = 9;
    const circles = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + R() * 0.5;
      const d = r * ease.outCubic(p) * (0.35 + R() * 0.5);
      const rr = r * (0.28 + R() * 0.2) * (1 - p * 0.55);
      circles.push([x + Math.cos(a) * d, y + Math.sin(a) * d * 0.5, rr]);
    }
    ctx.save();
    ctx.globalAlpha = 1 - ease.inQuad(p);
    ctx.fillStyle = stroke;
    for (const [cx, cy, rr] of circles) {
      ctx.beginPath(); ctx.arc(cx, cy, rr + 5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = fill;
    for (const [cx, cy, rr] of circles) {
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.fill();
    }
    ctx.restore();
  }

  const seg = (id) => {
    const s = (window.VOICE && window.VOICE.segs.find((x) => x.id === id)) || null;
    if (!s) throw new Error("segment not found: " + id);
    return s;
  };

  window.K = {
    clamp, lerp, ease, tw, kf, rng, hash, shake, onTwos, loadImages,
    focusLines, rays, halftone, boltPath, drawBolt, sparkle, angerMark, puff, seg,
  };
})();

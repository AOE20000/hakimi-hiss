// 漫画 DOM 组件：气泡、标题框、拟声字、角色。全部返回元素，由镜头 render(t) 控制变换。
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function el(tag, cls, parent, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }

  // 椭圆气泡 + 尖尾。tail 为相对气泡左上角的尖端坐标。
  function bubble(parent, { x, y, w, h, zh, en, tail, shape = "ellipse" }) {
    const b = el("div", "bubble", parent);
    Object.assign(b.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", w); svg.setAttribute("height", h);
    const cx = w / 2, cy = h / 2;
    // 尾巴根部：朝尖端方向，在椭圆边上取两个点
    const ang = Math.atan2(tail[1] - cy, tail[0] - cx);
    const spread = 0.22;
    const pt = (a, k = 0.92) => [cx + Math.cos(a) * (w / 2) * k, cy + Math.sin(a) * (h / 2) * k];
    const [ax, ay] = pt(ang - spread), [bx, by] = pt(ang + spread);
    const tailD = `M${ax},${ay} L${tail[0]},${tail[1]} L${bx},${by} Z`;
    let bodyD;
    if (shape === "spiky") {
      // 爆炸形（喊叫）
      const n = 18; let d = "";
      for (let i = 0; i <= n * 2; i++) {
        const a = (i / (n * 2)) * Math.PI * 2;
        const k = i % 2 ? 0.82 : 1.06;
        d += (i ? "L" : "M") + (cx + Math.cos(a) * (w / 2) * k) + "," + (cy + Math.sin(a) * (h / 2) * k);
      }
      bodyD = d + "Z";
    } else {
      bodyD = `M${cx - w / 2},${cy} a${w / 2},${h / 2} 0 1,0 ${w},0 a${w / 2},${h / 2} 0 1,0 ${-w},0 Z`;
    }
    svg.innerHTML =
      `<path d="${tailD}" fill="#fff" stroke="#14101f" stroke-width="6" stroke-linejoin="round"/>` +
      `<path d="${bodyD}" fill="#fff" stroke="#14101f" stroke-width="6" stroke-linejoin="round"/>` +
      `<path d="${tailD}" fill="#fff" stroke="none" transform="translate(${-Math.cos(ang) * 6},${-Math.sin(ang) * 6})"/>`;
    b.appendChild(svg);
    el("div", "txt", b, `<div class="zh">${zh}</div>` + (en ? `<div class="en">${en}</div>` : ""));
    b.style.transformOrigin = `${tail[0]}px ${tail[1]}px`;
    return b;
  }

  function caption(parent, { x, y, zh, en, cls = "" }) {
    const c = el("div", "caption " + cls, parent, `<div class="zh">${zh}</div><div class="en">${en}</div>`);
    Object.assign(c.style, { left: x + "px", top: y + "px" });
    return c;
  }

  function sfx(parent, { x, y, zh, en, size = 220, color = "#1a1030", glow = "#ff6fae" }) {
    const s = el("div", "sfx", parent, `${zh}<span class="en" style="font-size:${size * 0.34}px">${en}</span>`);
    Object.assign(s.style, {
      left: x + "px", top: y + "px", fontSize: size + "px", color,
      filter: `drop-shadow(0 0 0 ${glow}) drop-shadow(10px 10px 0 ${glow})`,
    });
    return s;
  }

  // 角色：按高度缩放；x 为脚底中心，y 为脚底
  function char(parent, img, { x, y, h }) {
    const w = (img.naturalWidth / img.naturalHeight) * h;
    const c = el("img", "char", parent);
    c.src = img.src;
    Object.assign(c.style, { left: x - w / 2 + "px", top: y - h + "px", width: w + "px", height: h + "px" });
    c._w = w; c._h = h;
    return c;
  }

  // 统一设置变换
  function put(e, { x = 0, y = 0, s = 1, sx = 1, sy = 1, r = 0, o = 1 } = {}) {
    e.style.transform = `translate(${x}px,${y}px) rotate(${r}deg) scale(${s * sx},${s * sy})`;
    e.style.opacity = o;
    e.style.visibility = o <= 0.001 ? "hidden" : "visible";
  }

  window.UI = { el, bubble, caption, sfx, char, put };
})();

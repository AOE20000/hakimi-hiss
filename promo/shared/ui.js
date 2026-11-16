// 暗黑机能风 UI 组件：B 风格的折角多边形气泡（A 风格霓虹毛玻璃材质）+ 系统规则通知弹窗。
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function el(tag, cls, parent, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }

  function hud(parent, { left = "AGENT_A · 橘座 // POV: 1ST-PERSON", mid = "HAKIMI-HISS-CHANNEL · STDIO MCP", right = "AGENT_B · 狸花" } = {}) {
    return el("div", "hud-top", parent,
      `<div><span class="pill a">${left}</span></div>` +
      `<div>${mid}</div>` +
      `<div><span class="pill b">${right}</span></div>`
    );
  }

  // B 风格折角多边形气泡，使用 A 风格深色机能描边与微光
  // tailDir: "left" | "right" | "bottom-left" | "bottom-right" | "none"
  // theme: "a" (粉) | "b" (蓝) | "v" (紫)
  function polyBubble(parent, { x, y, w, h, who = "", zh, en = "", theme = "a", tailDir = "left", spiky = false }) {
    const b = el("div", "poly-bub", parent);
    Object.assign(b.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
    const stroke = theme === "a" ? "#ff7ab8" : theme === "b" ? "#6eb8ff" : "#a78bfa";
    const glow = theme === "a" ? "rgba(255,122,184,0.28)" : theme === "b" ? "rgba(110,184,255,0.28)" : "rgba(167,139,250,0.28)";

    // 构造不对称折角多边形顶点 + 尖尾
    let pts;
    if (spiky) {
      pts = [
        [14, 18], [w * 0.28, 4], [w * 0.55, 12], [w * 0.84, 3], [w - 8, 22],
        [w - 4, h * 0.52], [w - 14, h - 16], [w * 0.68, h - 6], [w * 0.34, h - 10], [18, h - 14], [4, h * 0.56],
      ];
    } else {
      pts = [
        [18, 14], [w * 0.46, 5], [w - 14, 16],
        [w - 5, h * 0.62], [w - 20, h - 12],
        [w * 0.52, h - 6], [14, h - 14], [5, h * 0.48],
      ];
    }
    // 插入尾巴尖点
    let origin = [w / 2, h / 2];
    if (tailDir === "left") {
      pts.splice(7, 0, [10, h * 0.72], [-28, h * 0.86], [22, h - 12]);
      origin = [-28, h * 0.86];
    } else if (tailDir === "right") {
      pts.splice(4, 0, [w - 12, h * 0.72], [w + 28, h * 0.86], [w - 24, h - 12]);
      origin = [w + 28, h * 0.86];
    } else if (tailDir === "bottom-left") {
      pts.splice(6, 0, [w * 0.28, h - 10], [w * 0.16, h + 28], [w * 0.18, h - 12]);
      origin = [w * 0.16, h + 28];
    } else if (tailDir === "bottom-right") {
      pts.splice(5, 0, [w * 0.82, h - 10], [w * 0.84, h + 28], [w * 0.70, h - 8]);
      origin = [w * 0.84, h + 28];
    }

    const ptStr = pts.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
    // 内层细线多边形（机能双层边框感）
    const inStr = pts
      .filter((_, i) => !tailDir || tailDir === "none" || Math.hypot(pts[i][0] - origin[0], pts[i][1] - origin[1]) > 6)
      .map(([px, py]) => `${(w / 2 + (px - w / 2) * 0.93).toFixed(1)},${(h / 2 + (py - h / 2) * 0.90).toFixed(1)}`)
      .join(" ");

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", w); svg.setAttribute("height", h);
    svg.style.filter = `drop-shadow(0 16px 36px rgba(0,0,0,0.72)) drop-shadow(0 0 18px ${glow})`;
    svg.innerHTML =
      `<polygon points="${ptStr}" fill="rgba(12, 14, 26, 0.90)" stroke="${stroke}" stroke-width="2.6" stroke-linejoin="miter"/>` +
      `<polygon points="${inStr}" fill="none" stroke="rgba(255,255,255,0.10)" stroke-width="1"/>`;
    b.appendChild(svg);

    const whoColor = theme === "a" ? "#ff9ed2" : theme === "b" ? "#93ccff" : "#d8b4fe";
    el("div", "txt", b,
      (who ? `<div class="who" style="color:${whoColor}">${who}</div>` : "") +
      `<div class="zh">${zh}</div>` +
      (en ? `<div class="en">${en}</div>` : "")
    );
    b.style.transformOrigin = `${origin[0]}px ${origin[1]}px`;
    return b;
  }

  // 系统规则通知弹窗
  // kind: "" (紫/常规规则) | "warn" (红/拦截或打回) | "ok" (绿/通过) | "gold" (金/胜负裁决)
  function sysNotice(parent, { x, y, w = 680, code = "SYSTEM RULE // ACTIVE", badge = "ENFORCED", zh, en, kind = "" }) {
    const n = el("div", "sys-notice " + kind, parent,
      `<div class="hdr"><span><i class="dot"></i>${code}</span><span class="badge">${badge}</span></div>` +
      `<div class="rule-zh">${zh}</div>` +
      (en ? `<div class="rule-en">${en}</div>` : "")
    );
    Object.assign(n.style, { left: x + "px", top: y + "px", width: w + "px" });
    return n;
  }

  function sfxSerif(parent, { x, y, zh, sub, size = 148, subColor = "#ff8ec7", align = "left" }) {
    const s = el("div", "sfx-serif", parent,
      `${zh}<span class="sub" style="color:${subColor};text-align:${align}">${sub}</span>`
    );
    Object.assign(s.style, { left: x + "px", top: y + "px", fontSize: size + "px" });
    return s;
  }

  function char(parent, img, { x, y, h, cls = "" }) {
    const w = (img.naturalWidth / img.naturalHeight) * h;
    const c = el("img", "char " + cls, parent);
    c.src = img.src;
    Object.assign(c.style, { left: x - w / 2 + "px", top: y - h + "px", width: w + "px", height: h + "px" });
    return c;
  }

  function put(e, { x = 0, y = 0, s = 1, sx = 1, sy = 1, r = 0, o = 1 } = {}) {
    e.style.transform = `translate(${x}px,${y}px) rotate(${r}deg) scale(${s * sx},${s * sy})`;
    e.style.opacity = o;
    e.style.visibility = o <= 0.001 ? "hidden" : "visible";
  }

  window.UI = { el, hud, polyBubble, sysNotice, sfxSerif, char, put };
})();

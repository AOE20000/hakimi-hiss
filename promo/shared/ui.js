// 暗黑机能风 UI 组件 v3：折角气泡 + 强存在感系统规则弹窗（带入场扫光与脉冲冲击）+ 啥子符纸。
(function () {
  const NS = "http://www.w3.org/2000/svg";

  function el(tag, cls, parent, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  }

  function hud(parent, { left = "哈基米A (橘座 · 逻辑并发)", mid = "HAKIMI-HISS-CHANNEL · STDIO MCP", right = "哈基米B (狸花 · 边界安全)" } = {}) {
    return el("div", "hud-top", parent,
      `<div><span class="pill a">${left}</span></div>` +
      `<div>${mid}</div>` +
      `<div><span class="pill b">${right}</span></div>`
    );
  }

  // B 风格折角多边形气泡（A 风格深色机能描边与微光）
  function polyBubble(parent, { x, y, w, h, who = "", zh, en = "", theme = "a", tailDir = "left", spiky = false }) {
    const b = el("div", "poly-bub", parent);
    Object.assign(b.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
    const stroke = theme === "a" ? "#ff9e6e" : theme === "b" ? "#6eb8ff" : "#a78bfa";
    const glow = theme === "a" ? "rgba(255,158,110,0.28)" : theme === "b" ? "rgba(110,184,255,0.28)" : "rgba(167,139,250,0.28)";

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
    const inStr = pts
      .filter((_, i) => !tailDir || tailDir === "none" || Math.hypot(pts[i][0] - origin[0], pts[i][1] - origin[1]) > 6)
      .map(([px, py]) => `${(w / 2 + (px - w / 2) * 0.93).toFixed(1)},${(h / 2 + (py - h / 2) * 0.90).toFixed(1)}`)
      .join(" ");

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", w); svg.setAttribute("height", h);
    svg.style.filter = `drop-shadow(0 16px 36px rgba(0,0,0,0.75)) drop-shadow(0 0 18px ${glow})`;
    svg.innerHTML =
      `<polygon points="${ptStr}" fill="rgba(12, 14, 26, 0.92)" stroke="${stroke}" stroke-width="2.6" stroke-linejoin="miter"/>` +
      `<polygon points="${inStr}" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="1"/>`;
    b.appendChild(svg);

    const whoColor = theme === "a" ? "#ffb088" : theme === "b" ? "#93ccff" : "#d8b4fe";
    el("div", "txt", b,
      (who ? `<div class="who" style="color:${whoColor}">${who}</div>` : "") +
      `<div class="zh">${zh}</div>` +
      (en ? `<div class="en">${en}</div>` : "")
    );
    b.style.transformOrigin = `${origin[0]}px ${origin[1]}px`;
    return b;
  }

  // 强存在感【系统规则通知】弹窗
  function sysNotice(parent, { x, y, w = 860, code = "SYSTEM NOTICE // ACTIVE RULE", badge = "ENFORCED", tag = "", zh, en = "", kind = "" }) {
    const n = el("div", "sys-notice " + kind, parent,
      `<div class="hdr"><span class="left"><i class="pulse-dot"></i>${code}</span><span class="badge">${badge}</span></div>` +
      `<div class="hazard"></div>` +
      `<div class="body">` +
        (tag ? `<div class="rule-tag">${tag}</div>` : "") +
        `<div class="rule-zh">${zh}</div>` +
        (en ? `<div class="rule-en">${en}</div>` : "") +
        `<div class="scan-flash"></div>` +
      `</div>`
    );
    Object.assign(n.style, { left: x + "px", top: y + "px", width: w + "px" });
    n._scan = n.querySelector(".scan-flash");
    return n;
  }

  // 弹窗专属入场更新：带 1.28x → 1.0x 砸下弹性缩放 + 扫光条扫过 + 呼吸微动
  function putNotice(n, t, t0, { outT = 1e9, yFrom = -36 } = {}) {
    const pIn = K.tw(t, t0, 0.26, K.ease.outBack);
    const pOut = K.tw(t, outT, 0.22, K.ease.inQuad);
    const o = K.clamp(pIn * 3.5) * (1 - pOut);
    const s = K.lerp(1.26, 1.0, pIn) * (1 - pOut * 0.12);
    const y = (1 - pIn) * yFrom;
    n.style.transform = `translate(0px,${y}px) scale(${s})`;
    n.style.opacity = o;
    n.style.visibility = o <= 0.001 ? "hidden" : "visible";
    if (n._scan) {
      const sp = K.clamp((t - t0) / 0.38);
      n._scan.style.transform = `translateX(${(sp * 220 - 110)}%)`;
      n._scan.style.opacity = sp < 1 ? (1 - sp) : 0;
    }
  }

  // 黄色【啥子】符纸
  function talisman(parent, { x, y }) {
    const d = el("div", "talisman", parent, `<div class="t-zh">啥子</div><div class="t-seal">重修</div>`);
    Object.assign(d.style, { left: x + "px", top: y + "px" });
    return d;
  }

  function sfxSerif(parent, { x, y, zh, sub, size = 148, subColor = "#ffb088", align = "left" }) {
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

  window.UI = { el, hud, polyBubble, sysNotice, putNotice, talisman, sfxSerif, char, put };
})();

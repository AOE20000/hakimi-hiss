"""逐帧渲染镜头页面。

页面协议见 shared/kit.js 开头：window.SHOT={start,end}、window.__ready、window.__seek(t)。

用法：
  python render.py shots/01-hook video            # → out/01-hook.silent.mp4
  python render.py shots/01-hook stills --n 12    # → out/01-hook.sheet.jpg 联系表
  python render.py shots/01-hook frame --t 5.2    # → out/01-hook.t5.20.png 单帧
可选：--fps 30  --from <t>  --to <t>（全片时间）
"""
import argparse
import os
import pathlib
import subprocess
import sys
import time

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out"
W, H = 1920, 1080
CHROME = os.environ.get("CHROME_PATH", "/usr/bin/chromium")


def open_page(pw, shot_dir):
    browser = pw.chromium.launch(
        executable_path=CHROME,
        args=["--allow-file-access-from-files", "--disable-web-security", "--font-render-hinting=none",
              "--force-color-profile=srgb", "--hide-scrollbars"],
    )
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto((shot_dir / "shot.html").resolve().as_uri())
    page.evaluate("() => window.__ready")
    if errors:
        sys.exit("page errors:\n" + "\n".join(errors))
    shot = page.evaluate("() => window.SHOT")
    return browser, page, shot, errors


def grab(page, t, fmt="jpeg"):
    page.evaluate("t => window.__seek(t)", t)
    if fmt == "png":
        return page.screenshot(type="png")
    return page.screenshot(type="jpeg", quality=94)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shot")
    ap.add_argument("mode", choices=["video", "stills", "frame"])
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--t", type=float, default=0.0)
    ap.add_argument("--from", dest="t_from", type=float)
    ap.add_argument("--to", dest="t_to", type=float)
    a = ap.parse_args()

    shot_dir = (ROOT / a.shot) if not os.path.isabs(a.shot) else pathlib.Path(a.shot)
    name = shot_dir.name
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser, page, shot, errors = open_page(pw, shot_dir)
        t0 = a.t_from if a.t_from is not None else shot["start"]
        t1 = a.t_to if a.t_to is not None else shot["end"]

        if a.mode == "frame":
            p = OUT / f"{name}.t{a.t:.2f}.png"
            p.write_bytes(grab(page, a.t, "png"))
            print(p)

        elif a.mode == "stills":
            import io
            ts = [t0 + (t1 - t0) * (i + 0.5) / a.n for i in range(a.n)]
            cols = 4
            tw_, th_ = 480, 270
            rows = (len(ts) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * tw_, rows * (th_ + 22)), (16, 16, 16))
            d = ImageDraw.Draw(sheet)
            for i, t in enumerate(ts):
                im = Image.open(io.BytesIO(grab(page, t))).resize((tw_, th_), Image.LANCZOS)
                x, y = (i % cols) * tw_, (i // cols) * (th_ + 22)
                sheet.paste(im, (x, y))
                d.text((x + 6, y + th_ + 4), f"t={t:.2f}s", fill=(230, 230, 230))
            p = OUT / f"{name}.sheet.jpg"
            sheet.save(p, quality=90)
            print(p)

        else:
            n = int(round((t1 - t0) * a.fps))
            p = OUT / f"{name}.silent.mp4"
            ff = subprocess.Popen(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(a.fps),
                 "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(p)],
                stdin=subprocess.PIPE,
            )
            st = time.time()
            for i in range(n):
                ff.stdin.write(grab(page, t0 + i / a.fps))
                if i % 60 == 0:
                    el = time.time() - st
                    print(f"  frame {i}/{n}  {el:.0f}s elapsed", flush=True)
            ff.stdin.close()
            ff.wait()
            print(p, f"{n} frames in {time.time()-st:.0f}s")

        if errors:
            print("page errors during render:\n" + "\n".join(errors), file=sys.stderr)
        browser.close()


if __name__ == "__main__":
    main()

"""一键总装脚本：渲染缺失镜头 → 拼接干净母版 → 混音 → 叠加独立 ASS 中英字幕 → 输出成片。

用法：
  python build.py           # 只跑还没有 .silent.mp4 的镜头，然后合成 out/hakimi-hiss-promo.mp4
  python build.py --all     # 强制重渲全部四个镜头
"""
import pathlib
import subprocess
import sys

from sound.mix import build_mix
from subs import mux, write_ass

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "out"
SHOTS = ["01-hook", "02-round1", "03-round2", "04-cta"]


def main():
    force = "--all" in sys.argv
    OUT.mkdir(exist_ok=True)
    parts = []
    for name in SHOTS:
        mp4 = OUT / f"{name}.silent.mp4"
        if force or not mp4.exists():
            print(f"=== rendering {name} ===", flush=True)
            subprocess.run([sys.executable, str(ROOT / "render.py"), f"shots/{name}", "video", "--fps", "30"], check=True)
        parts.append(mp4)

    lst = OUT / "_concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    full_silent = OUT / "full.silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(full_silent)], check=True)

    full_wav = OUT / "full.mix.wav"
    build_mix(full_wav, None)

    full_ass = OUT / "full.ass"
    write_ass(full_ass, max_t=None)

    final_mp4 = OUT / "hakimi-hiss-promo.mp4"
    mux(full_silent, full_wav, full_ass, final_mp4)


if __name__ == "__main__":
    main()

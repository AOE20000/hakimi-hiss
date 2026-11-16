"""生成独立 ASS 中英双语字幕层，并与无声画面 + 混音合成为成片。

用单条 Dialogue + \\N + {\\rEN}：中文在上、英文在下，间距固定，不会被 libass 碰撞重排。
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent

ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZH,Noto Sans SC,52,&H00FFFFFF,&H000000FF,&H001F1014,&H801F1014,-1,0,0,0,100,100,1,0,1,5,2,2,80,80,26,1
Style: GEM,Noto Sans SC,54,&H00E2B8FF,&H000000FF,&H001F1014,&H801F1014,-1,0,0,0,100,100,1,0,1,5,2,2,80,80,26,1
Style: EN,Noto Sans SC,30,&H0078E8FF,&H000000FF,&H001F1014,&H801F1014,-1,0,0,0,100,100,0.5,0,1,3.5,1.5,2,80,80,26,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def tc(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(ass_path, max_t=None):
    v = json.loads((ROOT / "data" / "voice.json").read_text(encoding="utf-8"))
    lines = [ASS_HEAD]
    for s in v["segs"]:
        if max_t and s["start"] >= max_t:
            break
        st = "GEM" if s["who"] in ("gem", "duo") else "ZH"
        t0, t1 = tc(s["start"]), tc(s["end"] + 0.12)
        lines.append(f"Dialogue: 0,{t0},{t1},{st},,0,0,0,,{{\\fad(80,80)}}{s['zh']}\\N{{\\rEN}}{s['en']}")
    ass_path.write_text("\n".join(lines), encoding="utf-8")


def mux(silent_mp4, wav, ass_path, out_mp4):
    fontsdir = ROOT / "assets" / "fonts"
    vf = f"ass={ass_path}:fontsdir={fontsdir}"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent_mp4), "-i", str(wav),
         "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-maxrate", "2M", "-bufsize", "4M",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_mp4)],
        check=True,
    )
    print(out_mp4)


if __name__ == "__main__":
    ass = ROOT / "out" / "01-hook.ass"
    write_ass(ass, max_t=15.0)
    if len(sys.argv) > 1 and sys.argv[1] == "mux":
        mux(ROOT / "out" / "01-hook.silent.mp4", ROOT / "out" / "01-hook.mix.wav", ass, ROOT / "out" / "01-hook.mp4")

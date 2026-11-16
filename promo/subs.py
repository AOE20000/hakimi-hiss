"""生成独立 ASS 中英双语字幕层（按说话人区分颜色：A 樱粉白、B 冰蓝白、AB 双猫亮紫）。"""
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
Style: A,Noto Sans SC,44,&H00EA9EFF,&H000000FF,&H00120908,&H90120908,-1,0,0,0,100,100,0.8,0,1,4.0,1.5,2,80,80,26,1
Style: B,Noto Sans SC,44,&H00FFD293,&H000000FF,&H00120908,&H90120908,-1,0,0,0,100,100,0.8,0,1,4.0,1.5,2,80,80,26,1
Style: AB,Noto Sans SC,50,&H00FFFFFF,&H000000FF,&H00120908,&H90120908,-1,0,0,0,100,100,1.2,0,1,4.5,2.0,2,80,80,26,1
Style: EN,Noto Sans SC,26,&H00D8C4B8,&H000000FF,&H00120908,&H90120908,-1,0,0,0,100,100,0.5,0,1,3.0,1.0,2,80,80,26,1

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
        st = s["who"] if s["who"] in ("A", "B", "AB") else "A"
        tag = "[哈基米A] " if st == "A" else "[哈基米B] " if st == "B" else ""
        t0, t1 = tc(s["start"]), tc(s["end"] + 0.12)
        lines.append(f"Dialogue: 0,{t0},{t1},{st},,0,0,0,,{{\\fad(80,80)}}{tag}{s['zh']}\\N{{\\rEN}}{s['en']}")
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
    ass = ROOT / "out" / "full.ass"
    write_ass(ass, max_t=None)

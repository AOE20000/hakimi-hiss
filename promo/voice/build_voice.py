"""合成全部旁白/对白，排出时间轴。

  python voice/build_voice.py [--only S01,S02]   # 只重做指定段（其余用缓存）

输出：
  voice/segs/<id>.wav        每段（48 kHz 立体声，已修剪首尾静音）
  voice/narration.wav        全片长度的人声轨
  data/voice.json, data/voice.js   时间轴（镜头页面用 window.VOICE）
"""
import json
import pathlib
import subprocess
import sys

import numpy as np
import soundfile as sf

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from script import SEGS, LEAD, TAIL  # noqa: E402

SR_TTS, SR = 24000, 48000
SEGD = ROOT / "voice" / "segs"
SEGD.mkdir(parents=True, exist_ok=True)

# 角色 → (模型, 音色, 语速, 升调倍率)
VOICES = {
    "nar": ("hexgrad/Kokoro-82M", "zf_xiaoxiao", 1.0, 1.00),
    "gem": ("hexgrad/Kokoro-82M", "zf_xiaoyi", 1.08, 1.12),
}


def tts_all(todo):
    import torch
    from kokoro import KModel, KPipeline
    torch.set_num_threads(2)
    pipes = {}

    def pipe(repo):
        if repo not in pipes:
            en = KPipeline(lang_code="a", repo_id=repo, model=False)
            model = KModel(repo_id=repo).eval()
            pipes[repo] = KPipeline(lang_code="z", repo_id=repo, model=model,
                                    en_callable=lambda s: next(en(s)).phonemes)
        return pipes[repo]

    for s in todo:
        who = "gem" if s["who"] in ("gem", "duo") else "nar"
        repo, voice, speed, pitch = VOICES[who]
        text = s["tts"] or s["zh"]
        wav = np.concatenate([r.audio.numpy() for r in pipe(repo)(text, voice=voice, speed=speed)])
        raw = SEGD / f"{s['id']}.raw.wav"
        sf.write(raw, wav, SR_TTS)
        # 升调不变速：asetrate 抬音高 + atempo 拉回时长；再重采样到 48k
        af = f"asetrate={int(SR_TTS*pitch)},atempo={1/pitch:.5f},aresample={SR}" if pitch != 1 else f"aresample={SR}"
        tmp = SEGD / f"{s['id']}.mono.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", af, "-ac", "1", str(tmp)], check=True)
        m, _ = sf.read(tmp, dtype="float32")
        m = trim(m)
        if s["who"] == "duo":
            # 两只同时哈：一左一右，第二只略微错开、略高
            d = int(0.035 * SR)
            b = np.interp(np.arange(0, len(m), 1.03), np.arange(len(m)), m).astype(np.float32)
            L = np.zeros(len(m) + d, np.float32); R = np.zeros_like(L)
            L[:len(m)] += m; R[d:d + len(b)] += b[: len(L) - d]
            st = np.stack([L * 0.85 + R * 0.25, R * 0.85 + L * 0.25], 1)
        else:
            st = np.stack([m, m], 1)
        sf.write(SEGD / f"{s['id']}.wav", st, SR)
        raw.unlink(); tmp.unlink()
        print(s["id"], s["who"], f"{len(st)/SR:.2f}s", text, flush=True)


def trim(m, thr=0.01, pad=0.03):
    idx = np.where(np.abs(m) > thr)[0]
    if len(idx) == 0:
        return m
    a = max(0, idx[0] - int(pad * SR)); b = min(len(m), idx[-1] + int(pad * SR))
    out = m[a:b].copy()
    f = int(0.01 * SR)
    out[:f] *= np.linspace(0, 1, f); out[-f:] *= np.linspace(1, 0, f)
    return out


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    todo = [s for s in SEGS if (only and s["id"] in only) or (not only and not (SEGD / f"{s['id']}.wav").exists())]
    if todo:
        tts_all(todo)

    t = LEAD
    segs, clips = [], []
    for s in SEGS:
        w, sr = sf.read(SEGD / f"{s['id']}.wav", dtype="float32")
        dur = len(w) / SR
        segs.append(dict(id=s["id"], who=s["who"], zh=s["zh"], en=s["en"],
                         start=round(t, 3), end=round(t + dur, 3)))
        clips.append((t, w))
        t += dur + s["gap"]
    total = round(t + TAIL, 3)
    full = np.zeros((int(total * SR) + 1, 2), np.float32)
    for t0, w in clips:
        i = int(round(t0 * SR)); full[i:i + len(w)] += w
    sf.write(ROOT / "voice" / "narration.wav", full, SR)

    data = dict(fps=30, total=total, segs=segs)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "voice.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data" / "voice.js").write_text("window.VOICE = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    for s in segs:
        print(f"{s['id']} {s['start']:6.2f}–{s['end']:6.2f}  {s['zh']}")
    print("total", total)


if __name__ == "__main__":
    main()

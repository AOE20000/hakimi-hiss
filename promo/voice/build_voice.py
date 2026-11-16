"""合成双猫对白，排出时间轴。

A 与 B 使用不同音色与音高：
  A（第一人称主视角，高傲利落）：zf_xiaoxiao, speed=1.05, pitch=1.03
  B（死对头，元气炸毛）        ：zf_xiaoyi,   speed=1.08, pitch=1.13
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

VOICES = {
    "A": ("hexgrad/Kokoro-82M", "zf_xiaoxiao", 1.05, 1.03),
    "B": ("hexgrad/Kokoro-82M", "zf_xiaoyi", 1.08, 1.13),
}


def trim(m, thr=0.01, pad=0.03):
    idx = np.where(np.abs(m) > thr)[0]
    if len(idx) == 0:
        return m
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(m), idx[-1] + int(pad * SR))
    out = m[a:b].copy()
    f = int(0.01 * SR)
    out[:f] *= np.linspace(0, 1, f)
    out[-f:] *= np.linspace(1, 0, f)
    return out


def synth_one(pipe, voice, speed, pitch, text):
    wav = np.concatenate([r.audio.numpy() for r in pipe(text, voice=voice, speed=speed)])
    raw = SEGD / "_tmp.raw.wav"
    tmp = SEGD / "_tmp.mono.wav"
    sf.write(raw, wav, SR_TTS)
    af = f"asetrate={int(SR_TTS*pitch)},atempo={1/pitch:.5f},aresample={SR}" if pitch != 1 else f"aresample={SR}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", af, "-ac", "1", str(tmp)], check=True)
    m, _ = sf.read(tmp, dtype="float32")
    raw.unlink(); tmp.unlink()
    return trim(m)


def tts_all(todo):
    import torch
    from kokoro import KModel, KPipeline
    torch.set_num_threads(2)
    repo = "hexgrad/Kokoro-82M"
    en = KPipeline(lang_code="a", repo_id=repo, model=False)
    model = KModel(repo_id=repo).eval()
    pipe = KPipeline(lang_code="z", repo_id=repo, model=model, en_callable=lambda s: next(en(s)).phonemes)

    for s in todo:
        text = s["tts"] or s["zh"]
        if s["who"] == "AB":
            _, vA, spA, pA = VOICES["A"]
            _, vB, spB, pB = VOICES["B"]
            mA = synth_one(pipe, vA, spA, pA, text)
            mB = synth_one(pipe, vB, spB, pB, text)
            d = int(0.03 * SR)
            L_len = max(len(mA), len(mB) + d)
            L = np.zeros(L_len, np.float32); R = np.zeros(L_len, np.float32)
            L[:len(mA)] += mA
            R[d:d + len(mB)] += mB
            st = np.stack([L * 0.85 + R * 0.25, R * 0.85 + L * 0.25], 1)
        else:
            _, v, sp, p = VOICES[s["who"]]
            m = synth_one(pipe, v, sp, p, text)
            # 轻微声像区分：A 偏左 58/42，B 偏右 42/58
            panL, panR = (1.06, 0.92) if s["who"] == "A" else (0.92, 1.06)
            st = np.stack([m * panL, m * panR], 1)
        sf.write(SEGD / f"{s['id']}.wav", st, SR)
        print(s["id"], s["who"], f"{len(st)/SR:.2f}s", text, flush=True)


def main():
    force = "--force" in sys.argv
    todo = [s for s in SEGS if force or not (SEGD / f"{s['id']}.wav").exists()]
    if todo:
        tts_all(todo)

    t = LEAD
    segs, clips = [], []
    for s in SEGS:
        w, _ = sf.read(SEGD / f"{s['id']}.wav", dtype="float32")
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
        print(f"{s['id']} [{s['who']}] {s['start']:6.2f}–{s['end']:6.2f}  {s['zh']}")
    print("total", total)


if __name__ == "__main__":
    main()

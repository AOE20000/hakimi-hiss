"""全片混音 v2：无旁白双猫对白 + 系统通知提示音（sfx_sys_chime）+ 稀疏视觉事件音效 + MusicGen BGM 自动侧链让路 + −16 LUFS 母带。"""
import json
import pathlib
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SR = 48000


def env_ad(n, a=0.005, p=2.0):
    t = np.linspace(0, 1, n)
    na = max(1, int(a * SR))
    e = (1 - t) ** p
    e[:na] = np.linspace(0, 1, na)
    return e


def sfx_sys_chime(f0=987.77, f1=1479.98, dur=0.36, amp=0.24):
    """系统规则通知弹出提示音：清脆双音玻璃提示（B5 → F#6）。"""
    n = int(dur * SR); out = np.zeros((n, 2))
    for t0, f, d in [(0.0, f0, 0.14), (0.065, f1, dur - 0.065)]:
        i0 = int(t0 * SR); m = min(int(d * SR), n - i0)
        t = np.arange(m) / SR
        w = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 14)) * np.exp(-t * 6.5)
        w[:int(0.003 * SR)] *= np.linspace(0, 1, int(0.003 * SR))
        out[i0:i0 + m, 0] += w; out[i0:i0 + m, 1] += w
    return out * amp


def sfx_pop(f0=520, f1=880, dur=0.08, amp=0.22):
    n = int(dur * SR)
    ph = 2 * np.pi * np.cumsum(np.linspace(f0, f1, n)) / SR
    w = np.sin(ph) * env_ad(n, 0.003, 2.5) * amp
    return np.stack([w, w], 1)


def sfx_hiss_clash(dur=0.65, amp=0.45):
    n = int(dur * SR)
    rng = np.random.default_rng(19)
    b, a = butter(3, [2600 / (SR / 2), 9500 / (SR / 2)], btype="band")
    t = np.arange(n) / SR
    mod = 0.75 + 0.25 * np.sin(2 * np.pi * 28 * t)
    hL = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.015, 1.4) * mod
    hR = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.03, 1.4) * mod
    boom = np.sin(2 * np.pi * np.cumsum(np.linspace(140, 36, n)) / SR) * env_ad(n, 0.002, 2.8) * 1.1
    m = int(0.08 * SR)
    zap = np.sign(np.sin(2 * np.pi * np.cumsum(np.linspace(2200, 420, m)) / SR)) * env_ad(m, 0.001, 2.0) * 0.45
    zpad = np.zeros(n); zpad[:m] = zap
    L = (hL * 0.65 + boom * 0.7 + zpad) * amp
    R = (hR * 0.65 + boom * 0.7 + zpad) * amp
    return np.stack([L, R], 1)


def sfx_stamp(dur=0.28, amp=0.42):
    n = int(dur * SR)
    rng = np.random.default_rng(31)
    thud = np.sin(2 * np.pi * np.cumsum(np.linspace(165, 42, n)) / SR) * env_ad(n, 0.002, 3.2)
    b, a = butter(2, 1200 / (SR / 2), btype="high")
    slap = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.001, 8.0) * 0.6
    w = (thud + slap) * amp
    return np.stack([w, w], 1)


def sfx_buzzer(dur=0.34, amp=0.30):
    n = int(dur * SR); t = np.arange(n) / SR
    tone = (np.tanh(2.5 * np.sin(2 * np.pi * 185 * t)) + np.tanh(2.5 * np.sin(2 * np.pi * 262 * t))) * 0.4
    w = tone * env_ad(n, 0.004, 2.2) * amp
    return np.stack([w, w], 1) + sfx_stamp(dur, amp * 0.85)


def sfx_fanfare(dur=1.0, amp=0.26):
    n = int(dur * SR); out = np.zeros((n, 2))
    seq = [(0.0, 587.33, 0.14), (0.13, 783.99, 0.14), (0.26, 1174.66, 0.70)]
    for t0, f, d in seq:
        i0 = int(t0 * SR); m = min(int(d * SR), n - i0)
        t = np.arange(m) / SR
        w = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2 * t)) * env_ad(m, 0.005, 1.8)
        out[i0:i0 + m, 0] += w; out[i0:i0 + m, 1] += w
    return out * amp


def sfx_wah(dur=0.6, amp=0.32):
    n = int(dur * SR)
    ph = 2 * np.pi * np.cumsum(np.linspace(480, 145, n)) / SR
    w = (np.sin(ph) + 0.4 * np.sin(2 * ph)) * env_ad(n, 0.004, 1.6) * amp
    st = np.stack([w, w], 1)
    s = sfx_stamp(0.28, amp)
    st[:len(s)] += s
    return st


def place(buf, t0, clip, gain_db=0.0):
    i = int(round(t0 * SR))
    if i < 0:
        clip = clip[-i:]; i = 0
    g = 10 ** (gain_db / 20)
    m = min(len(clip), len(buf) - i)
    if m > 0:
        buf[i:i + m] += clip[:m] * g


def build_mix(out_wav, end_t=None):
    voice_data = json.loads((ROOT / "data" / "voice.json").read_text(encoding="utf-8"))
    S = {s["id"]: s for s in voice_data["segs"]}
    if end_t is None:
        end_t = voice_data["total"]
    N = int(round(end_t * SR))

    nar, _ = sf.read(ROOT / "voice" / "narration.wav", dtype="float32")
    nar = nar[:N] if len(nar) >= N else np.pad(nar, ((0, N - len(nar)), (0, 0)))

    sfx = np.zeros((N, 2), np.float32)
    hiss = S["S04"]["start"]
    shazi = S["S10"]["start"] + 2.2

    # ── 01-hook ──
    place(sfx, S["S01"]["start"] + 0.2, sfx_pop(520, 880), -4)          # 自吹气泡 1
    place(sfx, S["S01"]["start"] + 2.7, sfx_pop(600, 980), -4)          # 自吹气泡 2
    place(sfx, S["S02"]["start"] - 0.35, sfx_sys_chime(988, 1480), 0)   # 系统通知 01：开启双子哈气对抗审查
    place(sfx, S["S02"]["start"] + 1.5, sfx_stamp(0.24, 0.32), -2)      # 斜切分屏 & B 进场
    place(sfx, hiss, sfx_hiss_clash(), +1)                              # 哈——!!
    place(sfx, S["S04"]["end"] + 0.12, sfx_sys_chime(784, 1568), -1)    # 片名条弹出

    if end_t > 24:
        # ── 02-round1 ──
        place(sfx, S["S05"]["start"] + 1.2, sfx_pop(540, 840), -4)      # BUG-001 登记
        place(sfx, S["S06"]["start"] + 1.8, sfx_buzzer(), 0)            # 系统通知 02：防重拦截（红）
        place(sfx, S["S07"]["start"] + 1.0, sfx_fanfare(), -1)          # 系统通知：第一局【一胜】

        # ── 03-round2 ──
        place(sfx, S["S08"]["start"] - 0.05, sfx_sys_chime(880, 1318), 0)   # 系统通知 03：隔离工作树交叉修复
        place(sfx, S["S09"]["start"] - 0.2, sfx_sys_chime(1046, 784), 0)    # 系统通知 04：互哈互验打回
        place(sfx, S["S09"]["start"] + 4.4, sfx_buzzer(), 0)                # 点驳回
        place(sfx, S["S10"]["start"] - 0.25, sfx_fanfare(), -1)             # 系统通知 05：终审【二胜】
        place(sfx, shazi, sfx_wah(), +1)                                    # 【啥子】贴标

        # ── 04-cta ──
        place(sfx, S["S11"]["start"] + 0.1, sfx_sys_chime(988, 1480), -1)   # 系统通知 06：长期上下文保持
        place(sfx, S["S12"]["end"] - 0.4, sfx_hiss_clash(0.45, 0.35), -1)   # 结尾再哈一声

    bgm_file = ROOT / "sound" / "music" / "m1_test.wav"
    bgm = np.zeros((N, 2), np.float32)
    if bgm_file.exists():
        tmp = ROOT / "out" / "_bgm48.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bgm_file), "-ar", str(SR), "-ac", "2", str(tmp)], check=True)
        m, _ = sf.read(tmp, dtype="float32"); tmp.unlink()
        xf = int(1.2 * SR)
        loop = m.copy()
        while len(loop) < N + xf:
            a = loop[-xf:] * np.linspace(1, 0, xf)[:, None] + m[:xf] * np.linspace(0, 1, xf)[:, None]
            loop = np.concatenate([loop[:-xf], a, m[xf:]], 0)
        bgm = loop[:N] / (np.max(np.abs(loop[:N])) + 1e-6) * 0.15

        silences = [(hiss - 0.25, hiss + 0.55)]
        if end_t > 24:
            silences.append((shazi - 0.2, shazi + 0.5))
        f = int(0.08 * SR)
        for t0, t1 in silences:
            a, b = int(t0 * SR), min(N - f - 1, int(t1 * SR))
            bgm[a - f:a] *= np.linspace(1, 0, f)[:, None]
            bgm[a:b] = 0
            bgm[b:b + f] *= np.linspace(0, 1, f)[:, None]

        fi, fo = int(0.4 * SR), int(1.2 * SR)
        bgm[:fi] *= np.linspace(0, 1, fi)[:, None]
        bgm[-fo:] *= np.linspace(1, 0, fo)[:, None]

    env = np.abs(nar[:, 0]) + np.abs(nar[:, 1])
    win = int(0.06 * SR)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    speaking = np.clip(env / 0.04, 0, 1)
    rel = int(0.18 * SR)
    speaking = np.convolve(speaking, np.ones(rel) / rel, mode="same")
    duck_bgm = 1.0 - speaking * (1 - 10 ** (-7 / 20))
    duck_sfx = 1.0 - speaking * (1 - 10 ** (-3 / 20))

    mix = nar + bgm * duck_bgm[:, None] + sfx * duck_sfx[:, None]

    import pyloudnorm as pyln
    meter = pyln.Meter(SR)
    lufs = meter.integrated_loudness(mix)
    mix = pyln.normalize.loudness(mix, lufs, -16.0)
    lim = 10 ** (-1.5 / 20)
    if np.max(np.abs(mix)) > lim:
        mix = np.tanh(mix / lim) * lim
    sf.write(out_wav, mix.astype(np.float32), SR)
    print(f"{out_wav}  in={lufs:.1f} LUFS → out={meter.integrated_loudness(mix):.1f} LUFS  peak={20*np.log10(np.max(np.abs(mix))):.1f} dBFS")


if __name__ == "__main__":
    build_mix(ROOT / "out" / "full.mix.wav", None)

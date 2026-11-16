"""全片混音 v3：精准对齐 12 镜台词时间轴 + 强存在感系统弹窗提示音 + 双声道猫哈气金属交击 + 防重护盾反弹音 + 搞笑敲锣声 + MusicGen BGM 自动侧链让路 + −16 LUFS 母带。"""
import json
import pathlib
import subprocess

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


def sfx_sys_chime(f0=987.77, f1=1479.98, dur=0.36, amp=0.28):
    """强存在感系统规则弹窗音效：机械冲击底鼓 + 双音战术高频脉冲。"""
    n = int(dur * SR); out = np.zeros((n, 2))
    for t0, f, d in [(0.0, f0, 0.14), (0.065, f1, dur - 0.065)]:
        i0 = int(t0 * SR); m = min(int(d * SR), n - i0)
        t = np.arange(m) / SR
        w = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 12)) * np.exp(-t * 6.0)
        w[:int(0.003 * SR)] *= np.linspace(0, 1, int(0.003 * SR))
        out[i0:i0 + m, 0] += w; out[i0:i0 + m, 1] += w
    thud = np.sin(2 * np.pi * np.cumsum(np.linspace(150, 45, n)) / SR) * env_ad(n, 0.002, 4.0) * 0.55
    out[:, 0] += thud; out[:, 1] += thud
    return out * amp


def sfx_pop(f0=520, f1=880, dur=0.08, amp=0.22):
    n = int(dur * SR)
    ph = 2 * np.pi * np.cumsum(np.linspace(f0, f1, n)) / SR
    w = np.sin(ph) * env_ad(n, 0.003, 2.5) * amp
    return np.stack([w, w], 1)


def sfx_hiss_clash(dur=0.72, amp=0.48):
    """双声道立体声猫哈气 + 金属利爪交击声（S04 & S12）。"""
    n = int(dur * SR)
    rng = np.random.default_rng(19)
    b, a = butter(3, [2600 / (SR / 2), 9500 / (SR / 2)], btype="band")
    t = np.arange(n) / SR
    mod = 0.75 + 0.25 * np.sin(2 * np.pi * 28 * t)
    hL = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.015, 1.4) * mod
    hR = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.03, 1.4) * mod
    boom = np.sin(2 * np.pi * np.cumsum(np.linspace(140, 36, n)) / SR) * env_ad(n, 0.002, 2.8) * 1.0
    # 金属交击泛音簇（非谐波高频铃音）
    metal = np.zeros(n)
    for mf, md in [(1840, 9.0), (2790, 11.0), (4120, 14.0), (5680, 18.0)]:
        metal += np.sin(2 * np.pi * mf * t) * np.exp(-t * md) * 0.32
    metal[:int(0.002 * SR)] *= np.linspace(0, 1, int(0.002 * SR))
    L = (hL * 0.72 + boom * 0.65 + metal * 0.85) * amp
    R = (hR * 0.72 + boom * 0.65 + metal * 0.85) * amp
    return np.stack([L, R], 1)


def sfx_stamp(dur=0.28, amp=0.42):
    n = int(dur * SR)
    rng = np.random.default_rng(31)
    thud = np.sin(2 * np.pi * np.cumsum(np.linspace(165, 42, n)) / SR) * env_ad(n, 0.002, 3.2)
    b, a = butter(2, 1200 / (SR / 2), btype="high")
    slap = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.001, 8.0) * 0.6
    w = (thud + slap) * amp
    return np.stack([w, w], 1)


def sfx_shield_bounce(dur=0.42, amp=0.38):
    """清脆防重护盾拦截音 DUPLICATE!（S06）。"""
    n = int(dur * SR); t = np.arange(n) / SR
    ping = (np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 1980 * t)) * np.exp(-t * 8.5)
    boing = np.sin(2 * np.pi * np.cumsum(np.linspace(680, 260, n)) / SR) * env_ad(n, 0.003, 2.2) * 0.7
    w = (ping * 0.75 + boing) * amp
    st = np.stack([w, w], 1)
    s = sfx_stamp(0.22, amp * 0.6)
    st[:len(s)] += s
    return st


def sfx_buzzer(dur=0.34, amp=0.34):
    n = int(dur * SR); t = np.arange(n) / SR
    tone = (np.tanh(2.5 * np.sin(2 * np.pi * 185 * t)) + np.tanh(2.5 * np.sin(2 * np.pi * 262 * t))) * 0.4
    w = tone * env_ad(n, 0.004, 2.2) * amp
    return np.stack([w, w], 1) + sfx_stamp(dur, amp * 0.85)


def sfx_fanfare(dur=1.0, amp=0.28):
    n = int(dur * SR); out = np.zeros((n, 2))
    seq = [(0.0, 587.33, 0.14), (0.13, 783.99, 0.14), (0.26, 1174.66, 0.70)]
    for t0, f, d in seq:
        i0 = int(t0 * SR); m = min(int(d * SR), n - i0)
        t = np.arange(m) / SR
        w = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * f * 2 * t)) * env_ad(m, 0.005, 1.8)
        out[i0:i0 + m, 0] += w; out[i0:i0 + m, 1] += w
    return out * amp


def sfx_gong(dur=1.15, amp=0.44):
    """搞笑戏曲敲锣 + 符纸啪贴音效（S10 【啥子】符纸贴脑门）。"""
    n = int(dur * SR); t = np.arange(n) / SR
    rng = np.random.default_rng(77)
    # 铜锣上滑音与非谐波金属泛音
    glide = np.cumsum(np.linspace(195, 235, n)) / SR
    gong = np.sin(2 * np.pi * glide) * 0.55
    for ratio, dec in [(1.41, 3.2), (1.73, 4.0), (2.28, 5.2), (2.93, 6.5), (3.65, 8.0)]:
        gong += np.sin(2 * np.pi * glide * ratio + 0.4 * np.sin(2 * np.pi * 18 * t)) * np.exp(-t * dec) * 0.25
    b, a = butter(2, [800 / (SR / 2), 6500 / (SR / 2)], btype="band")
    shimmer = lfilter(b, a, rng.standard_normal(n)) * env_ad(n, 0.008, 2.8) * 0.35
    w = (gong * env_ad(n, 0.003, 1.5) + shimmer) * amp
    st = np.stack([w, w], 1)
    slap = sfx_stamp(0.24, amp * 0.85)
    st[:len(slap)] += slap
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
    talisman_hit = S["S10"]["start"] + 1.1

    # ── 01-hook (S01 - S04) ──
    place(sfx, S["S01"]["start"] + 0.15, sfx_pop(520, 880), -3)           # S01 橘座出场气泡
    place(sfx, S["S01"]["start"] + 1.10, sfx_pop(900, 1400), -3)          # 爪尖划过代码行
    place(sfx, S["S02"]["start"] - 0.25, sfx_sys_chime(988, 1480), +1)    # S02 警报红光 + 同模分裂系统弹窗
    place(sfx, S["S02"]["start"] + 0.05, sfx_stamp(0.24, 0.34), -1)       # 镜像裂缝炸毛跃出
    place(sfx, S["S03"]["start"] + 0.10, sfx_sys_chime(1174, 1568), -2)   # S03 边界安全雷达展开
    place(sfx, hiss - 0.10, sfx_sys_chime(880, 1760), -1)                 # S04 ROUND1_HUNTING 弹窗
    place(sfx, hiss, sfx_hiss_clash(), +1.5)                              # S04 双声道猫哈气 + 金属交击

    if end_t > 24:
        # ── 02-round1 (S05 - S07) ──
        place(sfx, S["S05"]["start"] + 0.20, sfx_sys_chime(1046, 1568), 0)  # S05 BUG-001 抢注成功弹窗
        place(sfx, S["S06"]["start"] + 1.15, sfx_shield_bounce(), +1)       # S06 红色防重护盾反弹 DUPLICATE!
        place(sfx, S["S07"]["start"] - 0.20, sfx_fanfare(), 0)              # S07 第一局结算【一胜】金光

        # ── 03-round2 (S08 - S10) ──
        place(sfx, S["S08"]["start"] - 0.05, sfx_sys_chime(880, 1318), 0)   # S08 双 Worktree 交叉修复弹窗
        place(sfx, S["S08"]["start"] + 0.50, sfx_pop(640, 1120), -2)        # Bug 胶囊交叉飞向对方沙盒
        place(sfx, S["S09"]["start"] - 0.15, sfx_sys_chime(1046, 784), 0)   # S09 Worktree 合入与铲屎官亲测弹窗
        place(sfx, S["S09"]["start"] + 5.20, sfx_buzzer(), +1)              # 铲屎官复跑并发测试当场抓包死锁印章
        place(sfx, S["S10"]["start"] - 0.20, sfx_fanfare(), -1)             # S10 铲屎官终审金光 PERFECT
        place(sfx, talisman_hit, sfx_gong(), +1.5)                          # S10 搞笑敲锣声 + 【啥子】符纸贴脑门

        # ── 04-cta (S11 - S12) ──
        place(sfx, S["S11"]["start"] + 0.02, sfx_sys_chime(988, 1480), 0)   # S11 持久化 conv_id 灵魂锁链弹窗
        place(sfx, S["S12"]["start"] + 0.95, sfx_pop(880, 440), -1)         # S12 撕起半截符纸啪地弹回
        place(sfx, S["S12"]["start"] + 1.35, sfx_sys_chime(784, 1568), -1)  # S12 定格项目 Logo 与 Slogan 卡
        place(sfx, S["S12"]["end"] - 0.85, sfx_hiss_clash(0.55, 0.42), +1)  # S12 结尾「嘶哈——！！」

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

        silences = [(hiss - 0.20, hiss + 0.55)]
        if end_t > 24:
            silences.append((talisman_hit - 0.15, talisman_hit + 0.55))
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

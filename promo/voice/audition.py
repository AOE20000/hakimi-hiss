"""Voice audition: render one line with several Kokoro zh voices so the user can pick by ear.

Usage: python voice/audition.py
Output: voice/audition/<model>_<voice>.wav  +  voice/audition_all.wav (concatenated, 0.6s gaps)
"""
import pathlib
import numpy as np
import soundfile as sf
import torch
from kokoro import KModel, KPipeline

torch.set_num_threads(2)
SR = 24000
here = pathlib.Path(__file__).resolve().parent
outd = here / "audition"
outd.mkdir(exist_ok=True)

LINE = "Gemini 过度自信怎么办？我的观察力太敏锐了！直接把病根切出来了！"

CANDIDATES = {
    "hexgrad/Kokoro-82M-v1.1-zh": ["zf_001", "zf_003", "zf_017", "zf_022", "zf_039", "zf_048", "zf_079", "zf_088"],
    "hexgrad/Kokoro-82M": ["zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi"],
}

allwav = []
for repo, voices in CANDIDATES.items():
    en = KPipeline(lang_code="a", repo_id=repo, model=False)

    def en_callable(text):
        return next(en(text)).phonemes

    model = KModel(repo_id=repo).eval()
    zh = KPipeline(lang_code="z", repo_id=repo, model=model, en_callable=en_callable)
    for v in voices:
        chunks = [r.audio.numpy() for r in zh(LINE, voice=v, speed=1.0)]
        wav = np.concatenate(chunks)
        tag = repo.split("/")[-1] + "_" + v
        sf.write(outd / f"{tag}.wav", wav, SR)
        print(tag, f"{len(wav)/SR:.2f}s", flush=True)
        allwav += [wav, np.zeros(int(SR * 0.6), dtype=np.float32)]

sf.write(here / "audition_all.wav", np.concatenate(allwav), SR)

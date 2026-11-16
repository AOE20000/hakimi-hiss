"""AI 背景音乐：MusicGen-small 本地生成（CPU）。

注意：facebook/musicgen-small 权重为 CC-BY-NC 4.0，仅限非商用。

用法：python sound/gen_music.py <tag> "<prompt>" <seconds> [seed]
输出：sound/music/<tag>.wav（32 kHz 单声道）
"""
import pathlib
import sys
import time

import numpy as np
import soundfile as sf
import torch
from transformers import AutoProcessor, MusicgenForConditionalGeneration

torch.set_num_threads(2)
here = pathlib.Path(__file__).resolve().parent
(here / "music").mkdir(exist_ok=True)

tag, prompt, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
torch.manual_seed(seed)

proc = AutoProcessor.from_pretrained("facebook/musicgen-small")
model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small").eval()
sr = model.config.audio_encoder.sampling_rate
tokens = int(secs * model.config.audio_encoder.frame_rate)

inputs = proc(text=[prompt], padding=True, return_tensors="pt")
st = time.time()
with torch.inference_mode():
    audio = model.generate(**inputs, do_sample=True, guidance_scale=3.0, max_new_tokens=tokens)
wav = audio[0, 0].cpu().numpy().astype(np.float32)
out = here / "music" / f"{tag}.wav"
sf.write(out, wav, sr)
print(out, f"{len(wav)/sr:.1f}s audio in {time.time()-st:.0f}s")

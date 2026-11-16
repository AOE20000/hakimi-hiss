# 哈基米哈气审查 · 无头浏览器宣传视频（`promo/`）

横版 `1920×1080 @ 30fps` 动态漫画宣传片（约 58.6 秒），画面全部由网页（Canvas + CSS/DOM）按时间纯函数渲染，由无头 Chromium 逐帧 seek 截图送入 ffmpeg；配音、背景音乐、音效均在本地生成；中英双语字幕作为独立 ASS 层在合成阶段叠加，无字幕母版与带字幕成片分离。

管线设计参考了 [null0526/dario-genesis](https://github.com/null0526/dario-genesis)，并针对其《遗憾与待改进》做了两项改动：
1. **字幕独立成层**：镜头母版 `out/*.silent.mp4` 不含字幕，最后由 `subs.py` 通过 libass 统一压制双语字幕。
2. **声音做减法 + 自动侧链让路**：音效只挂在画面看得见的强视觉事件上（气泡弹出、翻格、召唤、哈气雷击、防重红章、【一胜】/【二胜】、【啥子】印章），人声出现时 BGM 自动压低 7 dB，关键包袱前抽空静音，最终按 `−16 LUFS / −1.5 dBTP` 做母带归一。

## 目录结构

| 路径 | 说明 |
|---|---|
| `script.py` | 16 段中英旁白/对白文稿（显示层与 TTS 层分离） |
| `voice/build_voice.py` | 本地 Kokoro-82M 中文 TTS 合成，输出 `data/voice.json` 与 `data/voice.js` 时间轴 |
| `voice/audition.py` | 12 种本地中文音色试听脚本 |
| `sound/gen_music.py` | 本地 `facebook/musicgen-small` 背景音乐生成（注：权重为 CC-BY-NC 4.0，仅限非商用） |
| `sound/mix.py` | 稀疏音效合成 + BGM 循环与包袱前抽空 + 人声侧链让路 + `−16 LUFS` 响度标准化 |
| `shared/kit.js` & `shared/ui.js` & `shared/style.css` | 确定性缓动、固定种子 PRNG、集中线/网点/闪电/烟尘团/星芒、漫画分格与气泡组件 |
| `shots/01-hook/shot.html` | 镜头 1（0–14.5s）：Gemini 过度自信 → 翻格 → 两只 Gemini 站立对峙哈气 → 片名卡 |
| `shots/02-round1/shot.html` | 镜头 2（14.5–30.3s）：第一局并行找 Bug、通道计分、“哈——！慢了一爪！”防重拦截、【一胜】 |
| `shots/03-round2/shot.html` | 镜头 3（30.3–46.7s）：第二局双 Worktree 交叉修复、`REJECT_WITH_HISS` 打回、铲屎官裁决、【二胜】与【啥子】印章 |
| `shots/04-cta/shot.html` | 镜头 4（46.7–58.6s）：四大特性速览 + 片尾金句与仓库地址 |
| `render.py` | 单镜头渲染器（支持 `video` / `stills` 联系表 / `frame` 单帧） |
| `subs.py` | 双语 ASS 字幕生成与成片混流 |
| `build.py` | 一键总装脚本（输出 `out/hakimi-hiss-promo.mp4`） |

## 复现方式

```bash
source /home/antigravity/.venvs/promo/bin/activate
cd promo

# 1. 生成旁白与时间轴（已附带 data/voice.json，可直接跳到第 3 步）
python voice/build_voice.py

# 2. 生成本地 AI 背景音乐
python sound/gen_music.py m1_test "playful kawaii anime comedy theme, bright plucky synths, bouncy bass, light drums, cheerful and mischievous, 120 bpm, game soundtrack" 20 1

# 3. 抽帧联系表快速预览任意镜头
python render.py shots/01-hook stills --n 12

# 4. 一键渲染并合成全片（out/hakimi-hiss-promo.mp4）
python build.py
```

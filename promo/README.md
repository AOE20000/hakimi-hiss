# 哈基米哈气审查 · 无头浏览器宣传视频（`promo/`）

横版 `1920×1080 @ 30fps` 高清暗黑机能风宣传片（约 78 秒），画面全部由网页（Canvas + CSS/DOM）按时间纯函数渲染，由无头 Chromium 无损 PNG 逐帧 `seek` 截图送入 `ffmpeg`（`yuv444p` 高保真中间层，成片 `-crf 16 -preset slow -tune animation` 无码率压缩）；配音、背景音乐、音效均在本地生成；中英双语字幕作为独立 ASS 层在合成阶段叠加，无字幕母版与带字幕成片分离。

## 核心设计特点
1. **无旁白 · 双猫第一人称博弈**：A（橘座）与 B（狸花）全程第一人称互呛，不复读弹窗文字。
2. **强存在感前景系统规则弹窗**：高饱和战术顶栏 + 斜纹警戒带 + 扫光砸落动画，完整呈现 `Model: inherit` 同模分裂、`hakimi-hiss-channel` 实时防重、双 Git Worktree 交叉修复、`hakimi_integrate_worktrees` 原子合入与铲屎官复测裁决、`conversationId` 持久上下文及 `【啥子】` 机制（已同步主线最新精简第二局流程，移除自动互哈互验步骤）。
3. **字幕独立成层 + 侧链母带混音**：ASS 字幕层单独压制；人声出现时 BGM 自动压低 7 dB，关键包袱前抽空静音，按 `−16 LUFS / −1.5 dBTP` 输出。

## 目录结构

| 路径 | 说明 |
|---|---|
| `script.py` | 12 镜（`S01`–`S12`）双猫第一人称中英对白文稿（显示层与 TTS 层分离） |
| `voice/build_voice.py` | 本地 Kokoro-82M 双音色 TTS 合成，输出 `data/voice.json` 与 `data/voice.js` 时间轴 |
| `voice/audition.py` | 12 种本地中文音色试听脚本 |
| `sound/gen_music.py` | 本地 `facebook/musicgen-small` 背景音乐生成（注：权重为 CC-BY-NC 4.0，仅限非商用） |
| `sound/mix.py` | 视觉卡点音效（系统通知提示音、金属交击猫哈气、防重护盾反弹、搞笑敲锣贴符纸）+ BGM 侧链让路 + `−16 LUFS` 标准化 |
| `shared/kit.js` & `shared/ui.js` & `shared/style.css` | 确定性缓动、PRNG、折角气泡自适应字号组件、高存在感系统通知弹窗与【啥子】符纸组件 |
| `shots/01-hook/shot.html` | 镜头 1（`S01`–`S04`）：橘座扫代码 → 同模分裂警报弹窗 → 狸花边界雷达对峙 → 双声道嘶哈对撞 |
| `shots/02-round1/shot.html` | 镜头 2（`S05`–`S07`）：`BUG-001` 抢注、±5 行 `DUPLICATE!` 防重护盾反弹、3:2 结算【一胜】 |
| `shots/03-round2/shot.html` | 镜头 3（`S08`–`S10`）：双 Worktree 并行交叉修复、`hakimi_integrate_worktrees` 原子合入、铲屎官亲测抓死锁、【二胜】与【啥子】符纸 |
| `shots/04-cta/shot.html` | 镜头 4（`S11`–`S12`）：持久 `conv_id` 灵魂锁链、撕符纸回弹开启专项重修、Logo 与 Slogan 定格 |
| `render.py` | 单镜头无损渲染器（支持 `video` / `stills` 联系表 / `frame` 单帧） |
| `subs.py` | 双语 ASS 字幕生成与高清成片混流 |
| `build.py` | 一键总装脚本（输出 `out/hakimi-hiss-promo.mp4`） |

## 复现方式

```bash
source /home/antigravity/.venvs/promo/bin/activate
cd promo

# 1. 生成/更新双猫对白与时间轴（已附带 data/voice.json，仅改单句后可删 voice/segs/S09.wav 重跑）
python voice/build_voice.py

# 2. 抽帧/联系表快速预览任意镜头
python render.py shots/03-round2 stills --n 8

# 3. 逐镜头无损渲染（建议逐镜执行避免多实例争抢 CPU）并合成全片
python render.py shots/01-hook video
python render.py shots/02-round1 video
python render.py shots/03-round2 video
python render.py shots/04-cta video
python build.py
```

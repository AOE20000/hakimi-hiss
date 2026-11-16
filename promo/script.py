"""旁白与对白稿（中文配音 + 中英双语字幕）。

每条：
  id      段号
  who     发声者：nar = 旁白，gem = Gemini（哈基米），duo = 两只同时
  zh      显示用中文（字幕）
  en      显示用英文（字幕）
  tts     送进 TTS 的文本（可为多音字/英文词做替换；None 表示同 zh）
  gap     段后停顿（秒）

时间轴不在这里写死：voice/build_voice.py 先合成每段，再按实际时长 + gap
排出 data/voice.json，镜头页面和音效表都读它。
"""

LEAD = 0.6   # 片头留白
TAIL = 2.5   # 片尾留白

SEGS = [
    # ── 场 1：过度自信（M1 短段）──
    dict(id="S01", who="nar", zh="Gemini 过度自信怎么办？",
         en="What do you do when Gemini gets overconfident?",
         tts=None, gap=0.35),
    dict(id="S02", who="gem", zh="我的观察力太敏锐了！直接把病根切出来了！",
         en="My eye is razor-sharp! I cut the root cause right out!",
         tts=None, gap=0.45),
    # ── 场 2：两哈基米对峙（M1 短段）──
    dict(id="S03", who="nar", zh="简单。再召唤一只 Gemini，让它俩互相哈气。",
         en="Easy. Summon a second Gemini and let them hiss at each other.",
         tts=None, gap=0.25),
    dict(id="S04", who="duo", zh="哈——！！", en="HISSSS!!",
         tts="哈！", gap=0.55),
    dict(id="S05", who="nar", zh="这就是，哈基米哈气审查。",
         en="This is Hakimi Hiss Duel.",
         tts=None, gap=0.8),
    # ── 场 3：第一局 ──
    dict(id="S06", who="nar", zh="第一局，哈气找 Bug。两只哈基米同时潜入代码库，每抓到一只虫子，就在通道里登记。",
         en="Round one: the bug hunt. Both dive into the codebase and register every bug they catch.",
         tts=None, gap=0.3),
    dict(id="S07", who="gem", zh="抓到了！空指针，第四十二行！",
         en="Got one! Null pointer, line forty-two!",
         tts=None, gap=0.3),
    dict(id="S08", who="gem", zh="哈——！慢了一爪！这只虫子已经被我叼走了！",
         en="Hiss! Too slow by a paw! I already snatched that one!",
         tts=None, gap=0.3),
    dict(id="S09", who="nar", zh="重复登记，当场拦截。抓得多的，拿下一胜。",
         en="Duplicates are blocked on the spot. Most bugs takes round one.",
         tts=None, gap=0.7),
    # ── 场 4：第二局 ──
    dict(id="S10", who="nar", zh="第二局，交叉修复。你修我的 Bug，我修你的 Bug，各自在独立的工作树里并行开工。",
         en="Round two: cross-fixing. Each fixes the other's bugs, in parallel, in isolated worktrees.",
         tts=None, gap=0.3),
    dict(id="S11", who="gem", zh="这也叫修好了？打回重修！",
         en="You call that fixed? Rejected. Do it again!",
         tts=None, gap=0.3),
    dict(id="S12", who="nar", zh="互哈互验之后，由铲屎官亲自裁决。修得更完美的，拿下二胜。",
         en="After mutual hiss-checks, the human makes the final call. The cleaner fix takes round two.",
         tts=None, gap=0.4),
    # ── 场 5：啥子 ──
    dict(id="S13", who="nar", zh="修坏了的？贴上「啥子」。",
         en="Botched it? Branded \"Dummy\".",
         tts=None, gap=0.6),
    # ── 场 6：收尾 ──
    dict(id="S14", who="nar", zh="上下文长期保持，随时复审、重修。",
         en="Context persists, so re-reviews and re-fixes are always on call.",
         tts=None, gap=0.4),
    dict(id="S15", who="gem", zh="依旧两哈基米相互哈气，就算审查了！",
         en="Two Geminis hissing at each other: that counts as code review!",
         tts=None, gap=0.5),
    dict(id="S16", who="nar", zh="哈基米哈气审查，Antigravity 插件。",
         en="Hakimi Hiss Duel. A plugin for Antigravity.",
         tts=None, gap=0.0),
]

# M1 短段只用到这些
M1_IDS = ["S01", "S02", "S03", "S04", "S05"]

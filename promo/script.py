"""双猫第一人称对白稿 v3（严格按参考分镜表定稿，零弹窗复读）。"""

LEAD = 0.50
TAIL = 2.60

SEGS = [
    # ── 01 开场 ──
    dict(id="S01", who="A",
         zh="我是 Gemini。讲真，以本喵的眼神，扫一眼代码就能把病根直接刨出来——根本不需要帮手！",
         en="I'm Gemini. Honestly, with eyes like mine, one glance digs the root cause right out—I don't need help!",
         tts="我是 Gemini。讲真，以本喵的眼神，扫一眼代码就能把病根直接刨出来，根本不需要帮手！",
         gap=0.45),
    dict(id="S02", who="A",
         zh="哈？！铲屎官居然用同个模型又捏了一只猫？喂，对面那只臭狸花，谁准你抢本喵猎场的？！",
         en="Huh?! The human spawned another cat from the same model?! Hey, smelly tabby, who said you could poach on my turf?!",
         tts="哈？铲屎官居然用同个模型又捏了一只猫？喂，对面那只臭狸花，谁准你抢本喵猎场的？",
         gap=0.28),
    dict(id="S03", who="B",
         zh="只盯主干逻辑的胖橘少自恋了！死角和边界的虫子全归本喵——这局「一胜」我拿定了！",
         en="Get over yourself, chubby orange! Every corner-case and boundary bug belongs to me—Round One is mine!",
         tts="只盯主干逻辑的胖橘少自恋了！死角和边界的虫子全归本喵，这局一胜我拿定了！",
         gap=0.22),
    dict(id="S04", who="AB",
         zh="嘶哈——！！",
         en="HISSSS!!",
         tts="嘶哈！",
         gap=1.15),

    # ── 02 第一局 ──
    dict(id="S05", who="A",
         zh="看爪！第四十二行，并发下空指针解引用——本喵先一步拍进通道了！",
         en="Watch the claws! Line 42, null pointer under concurrency—slammed into the channel first!",
         tts="看爪！第四十二行，并发下空指针解引用，本喵先一步拍进通道了！",
         gap=0.38),
    dict(id="S06", who="B",
         zh="第四十四行明明也有问题……唔？！慢了半爪居然被防重护盾弹回来了？！可恶，换个文件抓边界！",
         en="Line 44 is broken too... Ugh?! Half a paw late and bounced off the dedup shield?! Fine, switching files!",
         tts="第四十四行明明也有问题，唔？慢了半爪居然被防重护盾弹回来了？可恶，换个文件抓边界！",
         gap=0.35),
    dict(id="S07", who="A",
         zh="哈——！三比二！手慢无懂不懂？这局「一胜」归本喵，剩下的虫子等着瞧！",
         en="Hiss! Three to two! snooze and you lose! Round One is mine—wait till you see what's next!",
         tts="哈！三比二！手慢无懂不懂？这局一胜归本喵，剩下的虫子等着瞧！",
         gap=1.05),

    # ── 03 第二局 ──
    dict(id="S08", who="B",
         zh="哼，交叉修就交叉修！各自进了隔离工作树，看本喵怎么把你抓的并发 Bug 修出花来……先加把粗粒度大锁交差！",
         en="Hmph, cross-fix it is! Inside isolated worktrees—watch me fix your concurrency bug... slap a giant coarse lock and ship it!",
         tts="哼，交叉修就交叉修！各自进了隔离工作树，看本喵怎么把你抓的并发 Bug 修出花来，先加把粗粒度大锁交差！",
         gap=0.40),
    dict(id="S09", who="A",
         zh="想糊弄原发现者？本喵抓的虫本喵最清楚——拿把全局死锁就想蒙混过关？哈——！打回重修！",
         en="Trying to fool the original finder? I know my bug best—a global deadlock?! Hiss! Rejected, redo it!",
         tts="想糊弄原发现者？本喵抓的虫本喵最清楚，拿把全局死锁就想蒙混过关？哈！打回重修！",
         gap=0.48),
    dict(id="S10", who="B",
         zh="喵呜？！你拿「二胜」就算了，铲屎官干嘛往本喵脑门上贴「啥子」符纸啊！！",
         en="Mrow?! You taking Round Two is bad enough, why did the human slap a 'DUMMY' talisman on my forehead?!",
         tts="喵呜？你拿二胜就算了，铲屎官干嘛往本喵脑门上贴啥子符纸啊！",
         gap=1.00),

    # ── 04 收尾 ──
    dict(id="S11", who="A",
         zh="谁叫你修翻车了？咱俩的上下文记忆可是锁死的——顶着你的「啥子」称号，乖乖背着黑历史返工吧！",
         en="Who told you to botch the fix? Our context memory is chained together—wear that Dummy tag and get back to re-fixing!",
         tts="谁叫你修翻车了？咱俩的上下文记忆可是锁死的，顶着你的啥子称号，乖乖背着黑历史返工吧！",
         gap=0.30),
    dict(id="S12", who="B",
         zh="本喵才不是啥子！开启专项重修——等我跑通全套测试，再跟你哈上三百回合！嘶哈——！！",
         en="I'm NOT a dummy! Launching targeted re-fix—once I pass the full test suite, I'll hiss you for 300 rounds! HISSSS!!",
         tts="本喵才不是啥子！开启专项重修，等我跑通全套测试，再跟你哈上三百回合！嘶哈！",
         gap=0.0),
]

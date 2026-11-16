"""双猫第一人称对白稿：
无旁白；A 与 B 事先不知道规则，但能实时看到屏幕上弹出的【系统通知】，并当场念出/吐槽通知里的规则。
"""

LEAD = 0.55
TAIL = 2.6

SEGS = [
    # ── 01-hook：A 第一人称自吹 → 看到系统通知召唤 B → 站立哈气 ──
    dict(id="S01", who="A",
         zh="我是 Gemini。讲真，我的观察力实在太敏锐了——扫一眼代码，直接把病根切出来！",
         en="I'm Gemini. Honestly, my eye is razor-sharp—one glance and I cut the root cause right out!",
         tts="我是 Gemini。讲真，我的观察力实在太敏锐了，扫一眼代码，直接把病根切出来！",
         gap=0.50),
    dict(id="S02", who="A",
         zh="等等，这系统通知写的啥……「开启双子哈气对抗审查」？！喂，对面那只怎么跟本喵长得一模一样？！",
         en="Wait, what's this system notice—'Dual-Agent Hiss Review Activated'?! Hey, why does she look just like me?!",
         tts="等等，这系统通知写的啥，开启双子哈气对抗审查？喂，对面那只怎么跟本喵长得一模一样？",
         gap=0.26),
    dict(id="S03", who="B",
         zh="本喵也收到通知了！上面说抓虫多的拿「一胜」——少废话，这库的虫子全归我！",
         en="I got the notice too! It says most bugs takes 'Round One'—save it, every bug here is mine!",
         tts="本喵也收到通知了！上面说抓虫多的拿一胜，少废话，这库的虫子全归我！",
         gap=0.22),
    dict(id="S04", who="AB",
         zh="哈——！！",
         en="HISSSS!!",
         tts="哈！", gap=1.30),

    # ── 02-round1：抢虫子 → B 看到系统防重通知炸毛 → A 看着一胜通知得意 ──
    dict(id="S05", who="A",
         zh="看好了！第四十二行，空指针解引用——本喵先往通道里登上了！",
         en="Watch this! Line forty-two, null pointer dereference—logged in the channel first!",
         tts="看好了！第四十二行，空指针解引用，本喵先往通道里登上了！",
         gap=0.40),
    dict(id="S06", who="B",
         zh="我也看到了，第四十四行……咦？！系统弹窗说「相近五行的重复虫子当场拦截」？！",
         en="I saw it too, line forty-four... Huh?! The system notice says 'Near-line duplicate blocked on sight'?!",
         tts="我也看到了，第四十四行，咦？系统弹窗说，相近五行的重复虫子当场拦截？",
         gap=0.32),
    dict(id="S07", who="A",
         zh="哈——！慢了一爪！看系统通告没？三比二，这局「一胜」归本喵了！",
         en="Hiss! Too slow by a paw! See the system notice? Three to two—'Round One' goes to me!",
         tts="哈——！慢了一爪！看系统通告没？三比二，这局一胜归本喵了！",
         gap=1.15),

    # ── 03-round2：看到第二局交叉修复通知 → A 发打回通知 → B 看到【啥子】通知破防 ──
    dict(id="S08", who="B",
         zh="又弹新通知了……「第二局：隔离工作树交叉修复，互修对方的虫子」？！行，套个 try-except 糊弄过去！",
         en="Another notice... 'Round Two: Cross-fix each other's bugs in isolated worktrees'?! Fine, I'll slap a try-except on it!",
         tts="又弹新通知了，第二局：隔离工作树交叉修复，互修对方的虫子？行，套个 try except 糊弄过去！",
         gap=0.40),
    dict(id="S09", who="A",
         zh="喂！系统刚提示轮到本喵「互哈互验」——你拿个空 except 吞异常也敢交？哈——！点驳回，打回重修！",
         en="Hey! The system just prompted me to 'Hiss-Verify'—you dare submit a bare except?! Hiss! Clicking REJECT!",
         tts="喂！系统刚提示轮到本喵互哈互验，你拿个空 except 吞异常也敢交？哈！点驳回，打回重修！",
         gap=0.50),
    dict(id="S10", who="B",
         zh="呜……终审通知出来了，判你拿「二胜」，居然给本喵贴了个「啥子」标记？！",
         en="Ugh... the final verdict notice is out: you get 'Round Two', and it branded me with a 'DUMMY' tag?!",
         tts="呜，终审通知出来了，判你拿二胜，居然给本喵贴了个啥子标记？",
         gap=1.05),

    # ── 04-cta：看到持久上下文通知，继续互哈 ──
    dict(id="S11", who="A",
         zh="自己看右下角通知——「上下文长期保持，啥子标记随时拉出来复审重修」！还不快改！",
         en="Read the notice in the corner—'Context persists, Dummies can be re-reviewed and re-fixed anytime'! Get to work!",
         tts="自己看右下角通知，上下文长期保持，啥子标记随时拉出来复审重修！还不快改！",
         gap=0.28),
    dict(id="S12", who="B",
         zh="本喵才不是啥子！等我重修完再跟你哈过！哈——！",
         en="I'm NOT a dummy! Wait till I re-fix this and hiss you again! Hiss!",
         tts="本喵才不是啥子！等我重修完再跟你哈过！哈！",
         gap=0.0),
]

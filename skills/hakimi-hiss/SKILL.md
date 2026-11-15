---
name: hakimi-hiss
description: 哈基米哈气审查（Hakimi Hiss Duel）编排技能：使用当前模型创建/复用长期子代理 A 与 B，通过插件防重通道进行第一局找 Bug 赛（一胜，支持全项目或仅限 @ 文件）与第二局交叉修 Bug 赛（二胜，A 修 B 的 Bug、B 修 A 的 Bug），支持「啥子」标记、挂起移交、长期上下文与手动重置。
---

# 哈基米哈气审查 (Hakimi Hiss Duel) 编排指南

> 灵感来源：**“依旧两哈基米（Gemini）相互哈气就算审查了”**

当用户触发哈基米哈气审查（找 Bug、交叉修 Bug、查战况、贴「啥子」标记、复审或手动重置）时，严格按本流程编排 **哈基米A（橘座）** 与 **哈基米B（狸花）**。

## 通道访问方式

优先使用插件内置的 MCP 工具（前缀 `hakimi_`：`hakimi_status`、`hakimi_bind_agents`、`hakimi_start_hunt`、`hakimi_report_bug`、`hakimi_list_bugs`、`hakimi_settle_round1`、`hakimi_start_cross_fix`、`hakimi_claim_files`、`hakimi_report_fix`、`hakimi_report_verify`、`hakimi_integrate_worktrees`、`hakimi_judge_round2`、`hakimi_mark_shazi`、`hakimi_reset`）；若当前会话尚未加载该 MCP 工具，等价使用 `run_command` 调用当前环境可用的 Python 3.10+ 解释器（Windows 需避开 `WindowsApps` 占位别名）执行插件目录下的通道脚本：

```powershell
<python3> "<PLUGIN_ROOT>/skills/hakimi-hiss/scripts/hakimi_channel.py" --workspace "<工作区标识>" <子命令> ...
```

（若传递含 `$`、反引号或双引号的自由文本参数，务必使用变量/单引号或参数数组，避免 Shell 注入与截断；如需跨平台切换 `mcp_config.json` 启动器，可运行 `<python3> "<PLUGIN_ROOT>/skills/hakimi-hiss/scripts/setup_mcp.py"`。）

---

## 核心铁律：长期上下文 & 当前模型

1. **必须使用当前模型**：调用 `invoke_subagent` 创建子代理 A 和 B 时，`Model` 一律传 `"inherit"`（严禁私自切换模型）。
2. **统一 `workspace` 标识（严防状态分裂）**：
   - 有活跃工作区时，将项目根目录规范化为统一格式（正斜杠、去除末尾 `/`）作为唯一 `workspace`；无活跃工作区时统一使用 `"default"`。
   - 铲屎官必须在唤醒 A 与 B 的消息中显式下发同一 `workspace` 值（及插件实际路径），并要求双方每次调用 MCP 或 CLI 时原样携带 `--workspace <ws>`，不可混用省略与绝对路径。
3. **长期上下文保持**：
   - 每次行动前先调用 `hakimi_status`（传入上述统一 `workspace`）。
   - 检查返回的 `agents.A.conv_id` 与 `agents.B.conv_id`：
     - **已存在时**：优先通过 `send_message` 唤醒原 `conversationId`，绝不新建覆盖，使两只哈基米在整个项目生命周期中保持长期上下文记忆！
     - **为 `null`（首次运行或已重置）或原代理已失效时**（含跨主会话导致 `send_message` 报错不可达，或 `manage_subagents` 中不存在且无法唤醒的情况）：**无需请示用户、亦不可擅自 `hakimi_reset` 清空战绩**，直接并行调用 `invoke_subagent`（`Model="inherit"`）创建 A 与 B（优先使用 `TypeName: "hakimi-a"` 与 `TypeName: "hakimi-b"`；若尚未热加载出这两个类型，则降级为 `TypeName: "self"` 并在 `Prompt` 中完整附带其人设及通道命令），随后立即调用 `hakimi_bind_agents` 持久化更新双方的 `conversationId`。
4. **裸触发直通规则（禁止无谓弹窗确认）**：
   - 当用户仅输入 `/hakimi-hiss` 或泛指“开始哈气审查 / 找 Bug”（且未明确指示“查看战况 / 交叉修复 / 重修啥子 / 手动重置”）时：
     - 若当前 `phase` 为 `IDLE`、`SUSPENDED_ROUND1` 或 `SUSPENDED_ROUND2`，**不要弹窗或反问确认**，直接保留既有累计战绩与历史归档，立即调用 `hakimi_start_hunt` 开启新一轮第一局找 Bug 赛并派发 A/B 并行审查。
     - 仅当 `phase` 处于未结算的进行中阶段（`ROUND1_HUNTING` 或 `ROUND2_CROSS_FIXING`）时，才按当前进行中进度续接、汇报当前任务，或在必要时确认是否传 `force=true` 强行重开。

---

## 阶段一：第一局 · 哈气找 Bug 赛（决出【一胜】）

1. **判定审查范围**：
   - 检查用户消息中是否 `@` 了具体文件（或明确指定了文件路径）。
   - 若 `@` 了文件：调用 `hakimi_start_hunt(workspace=..., scope="files", files=[...])`。
   - 若未 `@` 文件：默认全项目审查，调用 `hakimi_start_hunt(workspace=..., scope="project")`。
   - 若用户明确要求“追加审查/复审旧问题”，可传 `keep_bugs=true`。
2. **双猫并行出击**：
   - 通过 `send_message`（复用已有上下文）或 `invoke_subagent(Model="inherit")`（首次创建）**并行**通知哈基米A与哈基米B：
     - 明确下发统一的 `workspace` 标识、通道命令前缀（或 MCP 工具名）、`scope_mode` 与 `target_files`（若是全项目则告知项目根目录）。
     - 明确要求：第一局 **只找真实 Bug 并通过插件通道提交（`--workspace <ws> report-bug --reporter A/B`），不可重复，不要擅自改代码**。
     - 提醒它们先看 `list-bugs` 避开对方已登记的问题；若被通道以 `DUPLICATE` 拒收，立刻换找别的真 Bug。
3. **等待汇总并挂起**：
   - 发出派单后结束当前工具调用，等待 A、B 各自回复（禁止轮询）。
   - 两者均回复后，调用 `hakimi_settle_round1` 结算第一局：
     - 统计唯一有效 Bug 数量，决出 **【一胜】**（或平局）。
     - **插件自动进入 `SUSPENDED_ROUND1` 挂起状态**。
   - 向铲屎官（用户与主调度视图）完整呈现：
     1. 一胜战报（A vs B 找到的 Bug 数、严重程度分布、重复撞车/被拒次数）。
     2. 全部去重后的 Bug 清单（`BUG-001` ...，含文件、行号、发现者、严重程度与根因）。
     3. 明确询问/等待下一步选择：
        - **选项 1**：由铲屎官直接动手修复；
        - **选项 2**：通过插件发起第二局 **交叉修 Bug 赛（二胜）** —— 让 A 修 B 找到的 Bug，B 修 A 找到的 Bug。

---

## 阶段二：第二局 · 交叉修 Bug 赛（决出【二胜】）

当用户选择通过插件发起修复（或重修带有 `【啥子】` 标记的 Bug）时：

1. **启动交叉任务分配与模式自动探测**：
   - 调用 `hakimi_start_cross_fix(workspace=..., only_shazi=..., mode="auto")`（支持 `mode="auto" | "worktree" | "wave"`）。
   - 通道会自动把 **B 找到的 Bug 分配给 A**，把 **A 找到的 Bug 分配给 B**，并自动决定 `execution_mode`：
     - **`GIT_WORKTREE_PARALLEL`（首选真并行）**：当工作区为干净 Git 仓库根目录且双猫均存在任务时，自动派生隔离工作目录 `worktrees.A.path` 与 `worktrees.B.path` 及独立临时分支。若本地已安装 `git` 且工作区尚不存在 Git 仓库，会**自动执行 `git init` 并创建基线提交**（通过 `.git/info/exclude` 排除 `__pycache__` 与通道运行期状态文件）后直接启用该模式。
     - **`WAVE_PING_PONG`（自动优雅降级）**：当系统未安装 `git`、`git init` 失败、已有 Git 仓库尚无提交（unborn HEAD）、存在未提交改动、仅为仓库子目录或显式 `mode="wave"` 时自动降级（返回清晰 `fallback_reason`），将任务拆分为 **Wave 0 无冲突并行波次** + **先手均衡的 `PING_PONG_TURN` 重叠文件交替波次**。
     - **`SINGLE_FIXER_DIRECT`**：仅单侧存在待修任务时，直接在原工作区串行修完即可。
2. **按执行模式调度修复（防覆盖 & 强验证）**：
   - **若 `execution_mode == "GIT_WORKTREE_PARALLEL"`**：
     - 立即通过 `send_message` **真并行** 唤醒 A 和 B：在消息中明确下发各自的 `worktrees.A.path` / `worktrees.B.path`，**严禁双猫直接改动主工作区或互相修改对方 worktree**。
   - **若 `execution_mode == "WAVE_PING_PONG"`**：
     - 严格按 `waves` 顺序分波次通过 `send_message` 调度（Wave 0 若主文件及关联测试完全隔离可并行；进入每轮 `PING_PONG_TURN` 前等待上一波完成，并提醒双猫编辑重叠/共享文件前先调用 `hakimi_claim_files` 抢占软锁、换边后先 `read_file` 最新文件内容）。
   - 若某一方本轮没有待修任务，只唤醒有任务的一方即可。
   - 叮嘱双猫修完后必须实跑验证命令，并在调用 `hakimi_report_fix` 时附带 `verify_cmd` 与 `verify_passed` 证据（完成同文件最后一项任务时软锁会自动释放）。
3. **互哈互验（Cross-Verify）**：
   - 双猫汇报修复后，铲屎官可唤醒原 Bug 发现者调用 `hakimi_report_verify(verifier=..., bug_id=..., verdict="VERIFIED"|"REJECT_WITH_HISS", note=...)` 进行互验（`GIT_WORKTREE_PARALLEL` 下既可让原发现者检查对方 worktree，也可先用 `cleanup=false` 合入后互验再清理）：
     - 若原发现者哈气打回（`REJECT_WITH_HISS`），该 Bug 会直接退回 `IN_CROSS_FIX` 状态，通知原修复者返工重修。
4. **Worktree 合入、铲屎官终验与【二胜】裁决**：
   - 若本轮启用了 `GIT_WORKTREE_PARALLEL`，在终验合并阶段调用 `hakimi_integrate_worktrees(workspace=..., action="merge", cleanup=true)`：
     - 通道会自动暂存提交双猫 worktree 改动并依次并入主仓库；成功且 `cleanup=true` 时自动清理临时 worktree 与分支；若发生 `MERGE_CONFLICT`（默认 `abort_on_conflict=true`）则原子回滚主仓库并保留双 worktree 供排查。
   - 铲屎官 **必须亲自核查最终主工作区代码并运行验证命令**（不可轻信子代理自夸）。
   - 逐条给出客观评判并调用 `hakimi_judge_round2`：
     - `PERFECT`（+2 分）：修得干净彻底、边界无遗漏、测试通过、未引入新问题。
     - `PASS`（+1 分）：核心问题解决但有小瑕疵。
     - `FAILED`（-1 分）：未修好、漏改、测试失败或引入新 Bug —— **通道会自动给该 Bug 和对应修复者贴上 `【啥子】` 标记！**
   - 向用户公布 **【二胜】** 得主、双方完美率对比、互验概况以及被贴上 **`【啥子】`** 标记的翻车榜单。

---

## 阶段三：「啥子」标记、复审/重修与手动重置

- **手动贴/撕「啥子」标记**：
  - 用户或铲屎官认为某次审查或修复犯蠢时，调用 `hakimi_mark_shazi(target_type="bug"|"agent", target_id=..., reason=...)`（加 `--clear` / `clear=true` 可撤销）。
- **对「啥子」Bug 再次发起审查或更改**：
  - **重新交叉修复**：调用 `hakimi_start_cross_fix(only_shazi=true, mode="auto")`，再用 `send_message` 唤醒原 A/B（保留上下文！）盯着刚才犯蠢的原因重修。
  - **再次复审（复查是否还有隐藏 Bug）**：调用 `hakimi_start_hunt(scope=..., files=..., keep_bugs=true)`，再用 `send_message` 让原 A/B 继续相互哈气找茬。
- **手动重置上下文与战绩**：
  - 仅当用户明确要求重置时，调用 `hakimi_reset`（会自动清理残留的 Git worktree 与临时分支），并在返回 `previous_conv_ids` 后，若原后台子代理仍在列表中，可调用 `manage_subagents(Action="kill", ConversationIds=[...])` 彻底清理旧上下文，下次将全新创建 A 与 B。

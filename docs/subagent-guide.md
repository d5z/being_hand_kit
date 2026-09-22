# Hand 迭代 × portal subagent 实用指南

> 血统：hand 0.7 实现期撞出的三摩擦（task_id / 预算 / 进度）；0.9 S5 文档化。
> portal 侧修复清单见 `docs/portal-handoff-0.9.md`（转 weiguo/sw，不占 hand 账面）。
> 读者：驱动 Hand 迭代的人（Alice 或接手者）。
> 纪律：**错误消息即文档**——本文每条「判读法」都对应一个你能在终端或文件里看到的证据。

## 0. 一分钟总纲

| 摩擦 | 一句话规则 | 判读信号 |
|---|---|---|
| task_id | 记完整 UUID：`sub_` + 36 位带连字符 UUID；短前缀只用于人读 | 报错 `unknown task: <前缀>` |
| 预算 | 子会话开头 `Budget:` 行是唯一权威；超限不保证当场停 | 末尾 status=`budget_exhausted` / `timeout` |
| 进度 | spawn 后**不要 await**；查子会话 jsonl 尾部 + `git log`；回调会丢 | `callback=pending` 但 status 不动；`callback=sent` 但你没收到 |

---

## 1. 摩擦一：task_id 必须完整 UUID

### 1.1 发生了什么（0.7 实战：sub_3a2ced15）

0.7「AX 感知层」那一轮，实现触手在**文档里被记成了 `sub_3a2ced15`**：

- `docs/acceptance-ax-perception.md:4` —「验收人：Alice（触手 `sub_3a2ced15`，PRD 82e4611 执行）」
- `docs/prd-0.9-receipt-honesty.md:139` —「含 0.7 实战案例（`sub_3a2ced15` 的 task_id 教训）」

但 portal 台账里真实存在的 task_id 是**完整**的：

```
sub_3a2ced15-4930-4b72-9cb1-4d71a9678555
```
（`~/.heart-portal/subagent/ledger.json` → `tasks[]`，session=`hand-0.7`）

`sub_3a2ced15` 只是这个 UUID 的前 8 位十六进制——**人读够用，机器不认**。等到需要按 id 去查它、给它注入方向、
或读取它的完整结果时，拿这个前缀去调用就会失败。

### 1.2 机制（portal 源码核实，checkout v0.9.2）

- 生成：`task_id = format!("sub_{}", uuid::Uuid::new_v4())` — `portal/src/subagent/mod.rs:1022`
- 查找：`tasks.lock().await.get(task_id)` —— **HashMap 精确匹配，没有前缀/模糊匹配** — `subagent/mod.rs:2369-2376`
- 失败即 `anyhow!("unknown task: {task_id}")` — 同处 2376
- 所有以 task_id 为参数的工具（`portal_subagent_status` / `portal_subagent_log` / `portal_subagent_control`）
  都走这条精确匹配 — `portal/src/tools/subagent.rs:250-296`

也就是说：**portal 不接受短前缀**。你给它什么字符串，它就按什么字符串精确查，查不到就报 `unknown task`。

### 1.3 规则

1. spawn 返回的 task_id **原样记下**（完整 `sub_` + UUID），不要只记前缀。
2. 事后要 id 时，从 `~/.heart-portal/subagent/ledger.json` 的 `tasks[].task_id` 复制完整值——
   那是权威来源，文档里的短前缀只是人读标签。
3. 写文档/公告引用某个子任务时，写完整 id；若为可读性想缩写，明确标注「仅供人读，调用时用完整 id」。

### 1.4 检测

- 报错文本里出现 `unknown task: ...` → 十有八九是前缀或抄漏字符。回 ledger.json 复制完整 id 重试。
- 别把「ledger 里查不到前缀」当成「任务没跑」——先确认你给的是完整 id。

### 1.5 未验证 / 需确认

- 0.7 当时**触发这条错误的确切现场与原始报错文本没有留档**（repo 里只有短前缀的文档记录，没有当时的终端输出）。
  上面的「短前缀 → unknown task」机制由**当前** portal 源码确认；「0.7 当天怎么踩到的」属据台账 + 文档的合理重建，
  **未验证**。

---

## 2. 摩擦二：预算语义（max_tokens / max_turns / timeout_secs）

### 2.1 权威值在哪读

子会话 jsonl 的第一条 user message 顶部有 portal 渲染的三行抬头：

```
# Task sub_<完整-uuid> (session <key>)
Working directory: <path>
Budget: ≤N turns, ≤M tokens, ≤T min
```

这一行来自 `render_prompt`（`subagent/mod.rs:2464-2476`），`N/M/T` 就是**本次实际生效**的预算
（`T = timeout_secs / 60` 取整）。

0.7 那次抬头的实测值（hand-0.7 子会话 `pi/sessions/01a0c363-8b07-758a-9717-17e7988ef1ea.jsonl`，抬头行）：

```
Budget: ≤40 turns, ≤400000 tokens, ≤120 min
```

即 max_turns=40（默认）、max_tokens=400000（默认）、timeout_secs=7200（默认 1800 被覆盖成 120 min）。

### 2.2 三个字段各界什么（源码核实）

| 字段 | 界什么 | 默认值 | 覆盖时 clamp | 源码 |
|---|---|---|---|---|
| `max_turns` | 一次任务的 turn（模型-工具往返）数上限 | 40 | ≥1 | config.rs:681 / tools/subagent.rs:389-390 |
| `max_tokens` | 一次任务的 token 用量上限 | 400,000 | ≥1000 | config.rs:682 / tools/subagent.rs:392-393 |
| `timeout_secs` | 一次任务的墙钟时长上限 | 1800（30 min） | [30, 21600]（30s–6h） | config.rs:683 / tools/subagent.rs:24-25,395-396 |

另有 `max_continuations`（默认 3，config.rs:684）——hand 迭代里没用它规划过，**未验证**其与 hand 场景的关系。

### 2.3 什么时候会变成 `budget_exhausted`

结束分类在 `classify()`（`subagent/mod.rs:2447-2461`），优先级：

1. 被 cancel → `cancelled`
2. `error` 有值 / status_override=failed → `failed`
3. 预算相关 → `budget_exhausted`，满足任一即触发（`protocol.rs:517-533`）：
   - `limit_reached` 有值；
   - `stop_reason ∈ {max_turns, max_tokens, timeout, budget}`；
   - `turns_used >= max_turns`（max_turns>0）；
   - `tokens_used >= max_tokens`（max_tokens>0）。
4. 否则 → `done`

**三个预算谁先到谁算**，任一触发即 `budget_exhausted`（不是各自独立状态）。但见 2.6：这是「末尾分类」，
不保证在超限那一刻当场掐断。

### 2.4 如何读消耗

- 权威：`~/.heart-portal/subagent/ledger.json` → `tasks[]` 每行
  `status` / `turns` / `tokens_total` / `ended_ms - created_ms`（墙钟）/ `callback`。
- 子会话 jsonl 本身**不含预算计数**，只有工具调用与文本内容。
- 若 `portal_subagent_status` 对 hand 侧可用，它返回运行中任务的 `elapsed_s` / `turns` / `last_tool`——
  比 ledger 更实时（见 2.6 第 5 条）。

### 2.5 观察到的台账（供你校准直觉）

以下几行都取自 `ledger.json`（同机、同一 portal）：

| session | status | turns | tokens_total | 墙钟 |
|---|---|---|---|---|
| hand-0.7（sub_3a2ced15…8555） | budget_exhausted | 104 | 10,921,701 | 2442s (~40.7 min) |
| hand-0.7（另一 sub） | timeout | 32 | 17,528,209 | 1920s |
| hand-07-test | timeout | 110 | 10,180,562 | 1920s |
| hand-08 | budget_exhausted | 43 | 1,506,698 | 785s |
| hand-08-s4 | budget_exhausted | 49 | 2,233,573 | 1282s |

两个直观结论：

- **timeout 样本整齐停在 1920s**（4 条），提示默认 timeout 与判定粒度在 32 min 附近——但 1920 与默认 1800
  的差异来源**未验证**。
- **budget_exhausted 样本的 turns/tokens 差异极大**（14 turns/10.8M 到 104 turns/10.9M 都有），
  说明「挂上 budget_exhausted」并不能直接反推「撞的是哪条上限」。

### 2.6 未验证 / 需 weiguo 确认（重要）

以下都**不要当成已知**，写文档/决策前先找 weiguo/sw 确认：

1. **声明 cap 与实测 tokens 对不上**：0.7 抬头写 `≤400000 tokens`，台账却记 `tokens_total=10,921,701`。
   `tokens_total` 到底是不是「逐 turn 累计的 prompt+completion」，还是别的口径——**未验证**。
2. **max_turns=40 没在 40 turn 硬停**（实际 104 turns 才 budget_exhausted）。
   「预算只是末尾分类、运行期不硬掐」还是「运行中的 portal 二进制与本机源码 checkout 不是同一版」——**未验证**。
3. **运行中的 portal 二进制版本**是否等于 `/home/alice/heart-portal` 的 checkout（v0.9.2）——**未验证**。
   本指南的源码引用都来自该 checkout。
4. **timeout 是主动掐断子任务，还是只在末尾把 status 标成 timeout**——**未验证**。
5. **`portal_subagent_status/log/control` 对 hand 侧驱动者（being）是否稳定可用**——**未验证**。
6. **`max_continuations`（默认 3）的实际语义**及其对 hand 迭代的影响——**未验证**。
7. 台账 timeout 样本集中在 **1920s** 与默认 **1800s** 的差异来源——**未验证**。

### 2.7 怎么规划一个迭代预算（务实版）

- **抬头行是准绳**：spawn 后第一件事是读子会话 jsonl 抬头，确认 N/M/T，别凭记忆。
- **整轮 0.9 的估算**（来自 0.9 实现 brief 的自估）：S1≈15 turns、S2≈20、S3≈20、S4≈15、S5≈8，加 commit/测试
  共约 **90 turns**。这只是「目标」，不是「上限」。
- **按 S 块拆 spawn**：比一个大 spawn 更容易判读进度、更容易在预算耗尽时保住已完成的部分（0.7 一个大 spawn
  跑到 104 turns/40 min 才收场）。分块后，某块耗尽不影响其它块已落的 commit。
- **预算不是 KPI 而是护栏**：先用偏小的预算拿到早期信号，不够再用 `control` 的 steer / follow_up 续，
  比一次开超大导致失联/烧穿更可控。
- **留 buffer**：0.7 用掉 40 min 才跑完 S1–S7；给 timeout 至少留出预期墙钟的 1.5–2×。

---

## 3. 摩擦三：进度只能靠旁路推断（spawn 后别等）

### 3.1 为什么不能 await

**完成回调会丢**，典型是 needs_input 陷阱：子任务以纯文本汇报结尾时，daemon 可能判定它「在等输入」而停住，
父侧就收不到完成事件。这条已在 SOP 里写死：

- `docs/iteration-sop.md:58`：「纯文本结尾的汇报会触发 daemon 判 needs_input → 回调丢失……spawn 后 15 分钟
  主动查一次 session 文件」
- `docs/iteration-sop.md:85`：「subagent 回调不可依赖：完成通知会丢（needs_input 陷阱）」

**结论**：回调是「可能来」的优化，不是「一定来」的契约。按「不会来」设计你的循环。

### 3.2 侧信道 A：子会话 jsonl 尾部（最可靠）

- 先拿路径：`ledger.json` → `sessions.<session_key>.session_file`（值是 `~/.heart-portal/subagent/pi/sessions/<uuid>.jsonl`）。
- 读法：`tail -c 4000 <session_file>`，看最后几条工具调用与 assistant 文本。
- 判读：
  - 看到 `python3 tests/run_tests.py ... OK` → 正在收尾；
  - 看到 `git commit`（0.7/0.9 约定每 S 块一个 commit）→ 某块刚落地；
  - 看到 `await agent_message.send(..., receiver_role='parent')` → 报告要发了；
  - 长时间停在同一工具调用 → 可能卡住或踩 needs_input，考虑 steer。
- 这是**只读文件**，随时可查，不会阻塞子任务。

### 3.3 侧信道 B：git log

- 子任务约定「每 S 项一个 commit，message 带 S 编号」。
- `git log --oneline | head` 一眼看出走到哪个 S：0.7 实现链是
  `27a9405 S1 → 81d533f S2 → 713dd4c S3 → a5d6748 S4 → d0456e1 S5 → 29dc7ef S6 → 7f34223 S7`，
  之后是 `bdc42b6` 验收记录。
- 优点：语义清晰、里程碑可见；缺点：两个 commit 之间看不到中间态。
- **组合用法**：`git log` 看「走到哪」，jsonl 尾部看「此刻在做什么」。

### 3.4 spawn then don't wait 循环

1. **spawn**，立刻记下**完整 task_id** 与 session key。
2. **不 await**；继续做自己的事（review 别的东西、写文档、准备下一个 spawn）。
3. **每 10–15 min 查一次**（不阻塞）：① `ledger.json` 看 status；② `git log` 看有没有新 commit；
   ③ jsonl 尾部看在做什么。
4. status ∈ `{done, budget_exhausted, timeout}` 即视为「交卷/收场」，**不要等回调**；直接从 jsonl 读最终
   assistant 文本作为报告。
5. 长时间 `running` 且无新 commit → 用 `portal_subagent_control` 的 `steer` 注入方向（或 `follow_up` 追加活），
   真要止损用 `cancel`（注意：cancel 会 **suppress** 回调，设计如此）。
6. 收尾后按 commit 逐个 review——回调丢不丢都不影响正确性，只是可能白等一场。

### 3.5 状态/回调信号表

| 信号 | 含义 |
|---|---|
| `status=running` + `callback=pending` | 正常进行中 |
| `status=running` + `callback=pending` 但很久无新 commit | 疑似卡住 / needs_input 陷阱 → 查 jsonl 尾部，必要时 steer |
| `status=done` + `callback=sent` | 完成且回调**已尝试投递**（不代表你收到了） |
| `status ∈ {budget_exhausted, timeout}` | 收场；结果可能在 jsonl 最终文本里，不保证有回调 |
| `status=cancelled` + `callback=suppressed` | 主动取消；回调被抑制（设计如此） |

### 3.6 portal 侧已有、但 hand 侧未验证的进度工具

当前 portal 源码（`tools/subagent.rs`，checkout v0.9.2）里有三个进度工具：

- `portal_subagent_status` — 子代理在做什么（含 running 任务的 elapsed/turns/last_tool）；
- `portal_subagent_log` — 任务会话转录，支持分页与 `timeout_ms` 等待新行；
- `portal_subagent_control` — steer / follow_up / cancel。

如果 hand 迭代驱动者（being）能直接拿到这些工具，它们就是比「jsonl 尾 + git log」更好的进度界面。
但 0.7/0.8 实操都走的是旁路，这些工具**对 hand 侧是否可用、工具名是否稳定，未验证/需 weiguo 确认**。

---

## 附：证据索引

- `subagent/mod.rs:1022` — task_id 生成（`sub_` + UUID v4）
- `subagent/mod.rs:2369-2376` — task_id 精确查表，失败文本 `unknown task: {task_id}`
- `subagent/mod.rs:2447-2461` — 结束状态分类（failed / budget_exhausted / done 优先级）
- `subagent/mod.rs:2464-2476` — `render_prompt`，子会话抬头 `Budget:` 行来源
- `subagent/protocol.rs:517-533` — `AutonomousStatus::budget_exhausted` 触发条件
- `config.rs:204-212,681-684` — 预算默认值（40 / 400000 / 1800 / continuations 3）
- `tools/subagent.rs:24-28,76-83,389-397` — 预算 schema、clamp、description
- `tools/subagent.rs:250-296` — status/log/control 的 task_id 用法
- `~/.heart-portal/subagent/ledger.json` — 实测台账（task_id / status / turns / tokens_total / callback）
- `~/.heart-portal/subagent/pi/sessions/<uuid>.jsonl` — 子会话逐 turn 记录（含抬头 Budget 行）
- `docs/iteration-sop.md:51-58,84-85` — SOP 里的 subagent 陷阱与 workaround
- `docs/acceptance-ax-perception.md:4` — 0.7 触手短前缀记录
- `docs/prd-0.9-receipt-honesty.md:130-140` — S5 摩擦原始描述与验收

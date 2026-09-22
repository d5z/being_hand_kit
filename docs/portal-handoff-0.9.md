# portal 侧转交清单（hand 0.9 · S5 副产物）

> 来源：`docs/prd-0.9-receipt-honesty.md` S5「portal 侧修复转 weiguo/sw，不占 hand 0.9 账面」。
> 本清单把 0.7 实现期撞出的三条 portal 摩擦整理成 issue 形态，**均为待办，尚未修复**。
> 配套 hand 侧规避文档：`docs/subagent-guide.md`。

---

## H1 · task_id 短前缀容错（P1）

**问题**
`portal_subagent_status` / `portal_subagent_log` / `portal_subagent_control` 对 task_id 做 **HashMap 精确匹配**
（`subagent/mod.rs:2369-2376`，失败 `unknown task: {task_id}`）。但人写文档、笔记、公告时天然只记前缀
（0.7 的 `sub_3a2ced15`，实为 `sub_3a2ced15-4930-4b72-9cb1-4d71a9678555`）。事后拿前缀去调用即失败，
且错误消息不带「你前面还差多少位」的提示。

**期望**
1. task_id 查找支持**唯一前缀匹配**：命中唯一 → 解析到完整任务；多命中 → 报 ambiguous 并**列出候选完整 id**；
2. 错误消息可行动：不存在的 id 报 `unknown task: <given>` + 「当前 session/近期任务里以该串开头的有 N 个」；
3. status/ledger 展示层给出便于复制的**完整 id**（例如 status 返回同时带 `task_id` 与 `short`）。

**验收**
- `status(task_id="sub_3a2ced15")` 在唯一命中时返回完整任务行；
- 非唯一时返回 ambiguous 错误并列出所有候选完整 id；
- 完全不存在时错误消息含候选提示（或明确「无匹配」）；
- 精确完整 id 行为不变（向后兼容）。

---

## H2 · 预算字段文档化（P1）

**问题**
`max_turns` / `max_tokens` / `timeout_secs` 的真实语义只存在于源码。hand 侧 0.7 实测：抬头声明
`≤40 turns, ≤400000 tokens, ≤120 min`，台账却是 `104 turns / 10,921,701 tokens / 2442s`，
最终 status=`budget_exhausted`。使用者无法据此规划预算，也无法判读「撞的是哪条上限」。
`budget_exhausted` 是当场掐断还是末尾分类、`tokens_total` 的口径，都不透明。

**期望**
1. 文档页逐字段说明：界什么、单位、默认值、clamp 范围、判定时机；
2. 明确 `budget_exhausted` 的触发时机（运行期硬掐 vs 末尾分类）与优先级（cancel > failed > budget > done）；
3. 明确 `tokens_total` 计数口径（是否逐 turn 累计 prompt+completion）；
4. status / 任务结果**回显「生效预算」与「实际消耗」对照**（budget vs usage）。

**验收**
- 文档覆盖上述 4 点；
- `portal_subagent_status` 返回含 `budget`（生效值）与 `usage`（实际值）两栏；
- 针对「声明 400k vs 实测 10.9M」给出官方解释。

---

## H3 · 结构化进度事件（P2）

**问题**
父侧只能靠子会话 jsonl 尾部 / `git log` 推断进度（见 hand 侧指南 §3）。完成回调可能丢失——
典型是 needs_input 陷阱：子任务以纯文本汇报结尾时 daemon 判其「在等输入」，父侧收不到完成事件
（`docs/iteration-sop.md:58,85` 的 workaround 就是「过一会儿自己去查文件」）。

**期望**
1. 结构化**进度事件**（`task_id`, `turns`, `tokens`, `last_tool`, `elapsed_s`, `status`）经 SSE/inbox 推送，
   让父侧不必轮询文件；
2. needs_input **不再静默丢回调**：至少发一条「child 正在等待输入」事件；
3. 文档写明 `portal_subagent_status/log/control` 对 being 侧驱动者的**稳定可用性**（0.7/0.8 实操未依赖它们，
   属未验证）。

**验收**
- 订阅进度事件可在任务 running 时拿到 turns / last_tool；
- needs_input 时父侧收到显式事件（而非静默停住）；
- 文档明确这三个工具对 being 的可用性边界。

---

_整理：hand 0.9 S5（2026-09-22）。以上三条均未修复，等待 weiguo/sw 排期。_

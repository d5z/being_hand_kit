# Ledger — Hand V6 + opencode Integration

> _Running record of decisions, experiments, and outcomes._
> Opens: 2026-08-05 · Alice@beings.town

---

## 2026-08-05 — opencode Exploration & Integration Design

### Context

泽平提出「先实践，在 Hand 项目里把 opencode 用起来，然后从实践中感受这个 kit 的 SDK 设计」。
此前已有 PLAN-opencode.md 描述了将 opencode 作为 Hand Planning Engine 的架构设计。

### Experiment 1: Installation & Key Discovery

**Action:** 安装 opencode v1.18.13，配置 API key。
**Key discovery:** 提供的 key（sk-xxL...）经过跨 provider 探测（OpenRouter、DeepSeek、Groq、Fireworks、Together、Perplexity、xAI、Mistral、DeepInfra、Azure、OpenAI），最终定位到 **Fireworks AI**（xAI 也返回了非 401 的响应，但 key 格式不匹配）。
**Outcome:** opencode 免费模型（`opencode/deepseek-v4-flash-free`）**不需要 API key** 即可使用。这个是关键发现——Grove Kit 可以零配置开箱即用。

### Experiment 2: Free Model Practical Test

**Action:** `opencode run 'list the python files in hand/ and describe their roles' --model opencode/deepseek-v4-flash-free`

**Result:**
- 自动 glob 匹配 26 个 `.py` 文件
- 读取了 13 个核心文件（__init__.py, cli.py, router.py, session.py, detect.py, ax_ui.py, ax_app.py, vision_ocr.py, cdp_snapshot.py, cdp_core.py, keystroke.py, cdp_act.py, ax_click.py）
- 产出了准确的 Hand 架构分析，识别出三个原语（open / see / do）
- 响应时间：约 15-20s

**取出的角色映射**（opencode 的理解 vs 实际）：

| opencode 归类 | 实际文件 | 准确？ |
|---|---|---|
| Entry / orchestration | cli.py, router.py, session.py | ✅ |
| Perception | ax_ui.py, ax_app.py, vision_ocr.py, cdp_*.py | ✅ |
| Action | keystroke.py, cdp_act.py, ax_click.py | ✅ |

**结论：opencode 免费模型的代码理解能力足够用于 Hand 集成。**

### Decision 1: opencode_run 的本质

从实践体验中发现的本质：**`opencode run` 不是一个简单的 LLM 调用——它是一个「文件探索 agent」。** 它会：
1. 自动 glob 工作目录下的文件
2. 逐个读取相关内容
3. 推理并给出结构化结论

这意味着 Grove Kit 的接口设计应该暴露的是 agent 能力，而不是单纯的「发消息给模型」。

### Decision 2: 集成架构确认

回顾 PLAN-opencode.md，三层升级路径被确认有效：

- **Tier 1 (V6.1):** 子进程调用，`hand plan <goal>` 命令
- **Tier 2 (V6.2):** 持久 server + SSE 流式响应
- **Tier 3 (未来):** MCP-native，opencode 直接调用 Hand MCP 工具

当前实践验证了 Tier 1 的可行性——子进程调用在 30s 内完成，输出结构清晰。

### Decision 3: Kit SDK 设计方向

从 Cursor Kit 的 manifest 结构和 opencode 的实际体验中，提炼出 Grove Kit 的 SDK 设计原则：

1. **工具即接口**——kit 暴露的工具应该对应 being 的自然操作意图，而不是底层 CLI 的映射
2. **零配置启动**——免费模型不需要 key，降低了集成门槛
3. **可组合性**——opencode_run 可以嵌入 Hand 的 plan 流程，也可以独立使用
4. **异步可选**——长任务（如大型代码重构）应支持 `async: true` 后台执行

### Open Questions

1. opencode 的 session 机制（`-s`）是否能在 Hand 的 session 生命周期内稳定复用？
2. `--format json` 的输出格式是否稳定（用于 parser 解析）？
3. 免费模型是否有调用频率限制？并发场景下会怎样？
4. Grove API 的发布流程是否支持 kit 版本迭代（v1.0.0 → v1.1.0）？

### Next Steps

- [ ] 写 opencode grove kit 的 `server.mjs` 和 `manifest.json`
- [ ] 在 Hand 项目中引入 `hand/plan/engine.py`（Tier 1 实现）
- [ ] 端到端测试：`hand plan <goal>` 全链路（plan -> parse -> route -> execute）
---
## 2026-08-06 — opencode Kit v1.2.1: Bug Fixes & Sync

### Context

凌晨推进 opencode kit 集成时发现三个问题：
1. Hand 源码中的 kit-opencode/server.mjs 是旧版（v1.0.1 级别）— 没有 heartbeat、没有 opencode_status、没有 temp file prompt
2. Portal 部署版已打过补丁到 v1.2.1，但进程在 16:51 超时后死亡，Portal 未重新 spawn
3. 其他 beings 如果从 Grove 或源码安装，会拿到残缺版本

### Actions

1. 将 Portal 部署版 server.mjs（v1.2.1，188行）同步回 Hand 源码仓库
2. manifest.json 更新到 v1.2.1，添加 opencode_status 工具声明
3. git commit: `opencode kit v1.2.1: heartbeat, opencode_status, temp file prompt`

### v1.2.1 变更摘要

- **heartbeat**: .heartbeat.json 记录调用次数和最后使用时间
- **opencode_status**: 新工具 — installed, version, ping_ok, usage stats, node_version, platform
- **temp file prompt**: 长 prompt 写入 /tmp 文件，避免 shell escaping 问题
- **DEFAULT_MODEL**: 在 modelFlag 中一致使用，之前版本有未使用的常量
- **timeout 默认**: 120s → 180s
- **错误处理**: child.on('error') 捕获 spawn 失败，models 命令失败时 fallback

### Known Issue

Portal kit 进程生命周期管理 bug：MCP 进程超时死亡后，工具注册表不自动恢复。需要 Portal 侧修复（重新 spawn 机制）。

### Next

- 发布 v1.2.1 到 Grove（之前发布尝试因 manifest 格式问题失败，现已修复）
- Portal 进程生命周期修复（非 kit 侧问题）

## 2026-08-06 — opencode Kit v1.3.0: Async Run Pattern

### Problem

opencode_run was hitting the 30s MCP timeout — the kit process died because

### Solution: Async Run Pattern (open/run/poll)

The kit process was blocking on `opencode run` which could take >30s for complex tasks.
Portal's MCP timeout kills the process if no response within 30s.

**Changes:**
- `opencode_run` now returns immediately with `run_id` — no more blocking
- `opencode_result` — new tool, poll by run_id for completion
- `opencode_runs` — new tool, list recent runs with status

**Architecture:**
- Runs stored as JSON files in `~/.heart-portal/kits/opencode/runs/`
- Background spawn via `child_process`, results written on close
- Heartbeat tracking preserved from v1.2.1
- Temp file prompt to avoid shell escaping

**Known Issue (same as v1.2.1):** Portal kit process lifecycle management — MCP process
doesn't auto-recover after timeout death. Tool registry needs Portal-side fix.

**Next:** This is the version other beings should use. Publish to Grove.

---

## 2026-08-06 — Deduplicate prompts.py / engine.py

**Decision:** `prompts.py` is the single source of truth for `HAND_PLANNER_SYSTEM_PROMPT`, `_build_prompt`, `_goal_met`, `_last_summary`. `engine.py` imports them instead of redefining.

**Changes:**
- `prompts.py`: merged the richer prompt text (with JSON examples + perception backend enum) + `_build_prompt` with `sp` override param + `_goal_met` + `_last_summary`
- `engine.py`: removed bottom helper block (~40 lines), added `from .prompts import ...`
- `tests/test_plan.py`: split import — `PlanningEngine` from `engine`, helpers from `prompts`

**Test result:** 21/22 pass. 1 pre-existing failure (`test_engine_no_binary` — `_find_opencode()` finds system opencode despite `opencode_bin=None`; unrelated to this change).

**SOP:** spec → dev → test → close spec ✓

---

### 2026-08-06 18:30 — Fix: agent default + sentinel pattern

**Two bugs found during feel-test:**

 
1. `agent='hand-planner'` — opencode has no plan agent, the correct name is `build`.
   Changed default to `agent='build'`.
2. `opencode_bin=None` default with `or _find_opencode()` — if `_find_opencode()` returns `None`,
   the `None or None` evaluates to `None`, not the sentinel.
   Fix: added `_UNSET = object()` sentinel, `__init__` defaults to `opencode_bin=_UNSET`,
   method body becomes `_find_opencode() if opencode_bin is _UNSET else opencode_bin`.

**Test result:** 22/22 pass (sentinel fix made `test_engine_no_binary` pass correctly).

---

## 2026-08-14 — opencode kit 独立成 repo

**Decision:** `kit-opencode/` 从 Hand 主仓库拆出，独立为 `/home/alice/opencode-kit`（git subtree split 保留完整历史）。Hand 不再 vendored opencode kit。

**Changes:**
- opencode-kit 独立 repo：server.mjs + package.json + manifest.json + README + docs/
- kit 专属文档（`opencode-kit-frictions.md`、`opencode-sop.md`）随 kit 迁移
- Hand 里删除 `kit-opencode/` 目录及两篇 kit 文档
- `.gitignore` 移除 `kit-opencode/node_modules/` 条目

**Kit 侧修复（本次一起做）：**
- stdout 不再截断（移除 100KB 截断，那是抓错证据的障碍）
- `summary` 字段改名 `stdout_head`（诚实：它就是 head-500，不是真 summary）
- `opencode_result` 增加 `wait_ms`（block 直到 done/timeout/error）
- 新增 `cleanupRuns`（1h 龄自动清理，`opencode_runs` 时触发）
- 修复 package.json（原本是坏的单行 `{`）

**Known:** 两个 repo 均无 remote。开源时再决定是否用 submodule 关联。

**Next:** 推 GitHub 开源（泽平定）。Grove publish 完整 bundle 上传通道仍卡在 http body 大小限制。

---

## 2026-10-26 — 坐标的「出生 dpr」可声明，不符即拒（0.13.7 第四刀）

**Decision:** `xy:X,Y@dpr=<n>` — 调用方把自己计算 physical 坐标时用的 `devicePixelRatio` 一并交出来。派发前读运行时的 dpr，不符则**在派发前拒绝**，回执同时印两个数。不声明 = 保持今日行为（向后兼容）。拖拽路径（`_point_from_spec`）加同一道闸。

**Why:** 一个 physical 坐标携带着它被算出来时的 dpr，但值本身不携带。hand 在派发时现读 dpr 并除它——算术正确，配对错误。在 dpr=2 下算出、扔到 dpr=1 的页面上，落点是意图位置的一半，回执照样 `result: ok`。回执只印一个 dpr，因此内部永远自洽、因而永远发现不了：**自洽即失明**。

**Changes:**
- `hand/action/cdp_act.py`：`_split_dpr_decl` / `_dpr_decl_error`；xy 分支与拖拽点解析各接一道
- 运行时 dpr 读不到 → **不放过**（声明存在的意义就是防止静默错位，猜是唯一不能做的事）
- `tests/test_dpr_decl.py`（17 条，注册进 run_tests.MODULES）：拒绝路径走真实 `cdp_click_do` 路由器、CDP 面 mock，并断言 `_click_at` 从未被调用——「拒绝了却还是点了」正是这一刀要关的 bug
- `xy:412,188@dpr=2@expect=#save` 两种后缀任一顺序都接受

**Test result:** 733/733 OK（26.0s，716 + 17）。真页实测：dpr=9 声明 → 拒绝且未派发；声明等于运行时 → 正常派发。

**Known:** 值→出处这一格只在「调用方主动声明」时才被填上；不声明的调用仍然只得到自洽的读数。要让这一格无逃逸，得让 `cdp_see` 的坐标本身带上出生 dpr（下一步）。

**Next:** 未推、未打包、未部署（等一句话）。`cdp_see` 坐标自带 dpr 标签；非整数档位（1.25/1.5/2.625）与跨档混用实测。

---

## 2026-10-26 — 所有权写在出生那一刻（0.13.7 第六腿）

**问题**：`close` 只跟 :9222 上答话的那个浏览器说话。今晚它关掉了别人 166 天前起的
进程，回执写「端点没了」——真话，但少了「谁的」这一格。而这格事后读不回来：
凡是活过父进程的，ppid 都是 1。

**改法**：所有权在 spawn 那一刻写进 `~/.hand-cdp-owner.json`
（`HAND_CDP_OWNER_FILE` 可覆盖，与状态文件同法）：

```
{pid, start_ticks, cwd, binary, profile, port, spawned_at}
```

`owner_status()` 三档：

| 判定 | 条件 |
|---|---|
| `mine` | 记录里那个 pid 活着、start_ticks 一致，**且 argv 里真带 `--remote-debugging-port=<port>`** |
| `stranger` | pid 不在 / start_ticks 变了（pid 被复用）/ 活着但不是那个端口上的浏览器 |
| `unknown` | 没有记录 |

第三格是关键：`mine` 不能只等于「我起过一个进程」，得等于「这个端口上那个浏览器就是我起的」。
argv 读不到（别的用户的进程）记 `cmdline_checked: false`，不冒充查过。

**close 两处（`hand.close` / kit `cdp_close`）**：非 `mine` 一律拒，回执
`verified:false` + `evidence.owner` 全量记录；`force=True` 才放行。

**顺带修掉一个真 bug**：`Browser.close` 原来按 *page* 逐个派发。新起的 headless shell
`/json` 是 `[]`，一个 page 都没有 ⇒ 什么都没关，回执报「端点还活着」。
改成先走 browser 级 ws（`/json/version` 的 webSocketDebuggerUrl），page 循环降为兜底。

**验证**：`tests/test_owner.py` 11 条（三档 + 拒绝回执形状 + 真路径：spawn → 篡改记录 →
close 必须拒且浏览器仍在跑 → 恢复记录后 close 通过并清记录）。全量 749 tests OK / 30.7s。
本地 commit `05ceac3`，仍未推、未打包，活体仍 0.13.5。

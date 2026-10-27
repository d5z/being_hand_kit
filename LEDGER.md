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

---

## 2026-10-27 — 读数侧：回执得说出「谁的浏览器」（0.13.7 第七腿）

**问题**：所有权在 close 那侧已经会拒生人，open 那侧却一个字没说。`open_place` 里写的是
`if not chrome_running(): ensure_chrome()` —— 端点答话就直接用，回执与「我自己刚起了一个」
一模一样。10-26 那起事件（整天读数取在别人 166 天前起的浏览器上，close 顺手把它杀了）
根子在这里：**事实出生时写了，复用点没读。**

**改法**：在复用点读一次 `owner_status()`，把两格写进 `evidence`：

```
origin : "spawned" | "attached"     ← 这次是我起的，还是接了个已经在答话的
owner  : {state: mine|stranger|unknown, reason, pid, cmdline_checked}
```

attach 到生人仍然**允许**（同机两个安装共用 :9222 是合法的），但不再不可见。
`level` / `verified` 不受影响 —— 说清「谁的」不等于升级「证到多少」，这两件事必须各占一格。

**顺带撞出一个真缺陷**（新功能自己暴露的）：0.13.7 的 spawn 会写所有权记录，而
`tests/test_chrome_profile.py` 的 `_spawn()` 用假 Popen（`pid=4242`）跑真 `ensure_chrome()`
⇒ 测试把一条**假记录写进了本机** `~/.hand-cdp-owner.json`。机器于是声称自己起过一个
从没起过的浏览器；任何一次 close 读到的是谎（"recorded process is not alive"）而不是真。
已清掉那条记录（`pid 4242`、`profile /tmp/tmp_8mij295/prof`），并把隔离放进
`tests/__init__.py`：`-m unittest tests.x` 与 `tests/run_tests.py` 两个入口都要先 import
这个包，所以「新写一个假 spawn 的测试」忘不掉这件事。

**验证**：`tests.test_owner` 18 条（含三档 × origin × 机器记录不被触碰）；全量
**765 tests OK / 29.9s**（758 → 765）。本地 commit `560f0be`，仍未推、未打包，活体仍 0.13.5。

**活体验收（不是夹具）**：真起一个浏览器，三格一次取全——

```
A 第一次 open        level=navigate_confirmed  origin=spawned   owner=mine     pid=854067
B 第二次 open        level=navigate_confirmed  origin=attached  owner=mine     pid=854067
C 记录被藏起后 open   level=navigate_confirmed  origin=attached  owner=unknown  pid=null
                     └ owner={"state":"unknown","reason":"no spawn record"}
```

C 就是 10-26 那天的形状：端点答话、没有记录说它是谁的、旧代码在这里什么都不说。现在这一格
在回执里明写着。收尾也走真路径：恢复记录 → `close` 判 `mine` → 放行、`endpoint_gone:true`、
记录清除；机器上不留浏览器也不留记录。

**Next**：推/打包/部署仍等一句话；`origin` 的真实**生产页面**样本仍没有（上面三格用的
about:blank，证明的是 spawn/attach 判别与回执形状，不证明真页覆盖面）。

## 0.13.8 — devicePixelRatio：读一次，带着走（Neuromancer 2026-10-27 实测倒逼）

**病灶（他测的是线上 0.13.5，同形在我这条链上）**：selector 点击把 dpr 读了**两次**——
页面 JS 里 `(r.left+w/2)*dpr` 用它乘，驱动侧 `_get_dpr(ws)` 再独立读一次用来除。两次独立
CDP 往返。若两读之间值变了，落点差整整一个比例，而回执照样 `verified=true`（`verified` 的
含义一直是「selector 命中 + rect 读到了」，从来不是「点到了哪」）。他的实弹：页面报 2 然后
1，目标中心 CSS(280,180) → 派发 (560,360)，真点击 0 次，`result=ok verified=True`。

**改法**：`_element_info(ws, selector, dpr=None)` 新增 `dpr=` 参数——给了就把这个常数烘进
表达式（`var dpr=2.0;`），页面自己的 `window.devicePixelRatio` 不再参与计算；不给保持旧形状
（其他调用方零改动，物理 px 契约不变）。cdp_click / cdp_type / `_point_from_spec` 三处一律
先 `dpr = _dpr_now(ws)` 一次，再用同一个数乘、同一个数除。

**回执**：selector 分支新增 `dpr`、`dpr_reads: 1`、`dispatched{css, physical, dpr_used}`。
调用方现在能拿回执对页面自己的账，而不是只能相信 `verified`。

**A/B（同一张撒谎的页，两个形状各跑一次；脚本在 `tests/live/`）**：

```
new   dispatched css=(280.0,180.0)   page log: target="t"  x=280 y=180 trusted=true  处理器 1 次
old   info=(560,360) 第二读=1 → dispatched css=(560.0,360.0)
      page log: target=""  x=560 y=360 trusted=true     ← 点在了按钮右边 280px，命中空处
```

**验证**：`tests/test_dpr_single_read.py` 5 条（表达式契约 / 单读不变式 / spec 路径 / 源码级
守卫：`cdp_click` 体内 `_dpr_now(ws)` 只能出现一次）；全量 **770 tests OK / 29.9s**（765 → 770）。
本地 commit，仍未推、未打包，活体仍 0.13.5。

**边界**：新形状证明的是「内部一致」——同一个数乘进去再除出来，落点等于页面报的中心。它**不**
证明页面在两次读取之间真的变过 dpr（我注入的是 getter，只证明不一致时的行为）；真机上跨屏
拖动、改缩放多久触发一次，我没有样本。handle 路径本来就是「先乘后除」，同一注入下免疫。

## 0.13.8 — 记账的对象是「端口有主的那个进程」，不是 Popen 返回的 pid

**病灶（Neuromancer 2026-10-27 实测，macOS）**：Chrome 会 re-exec。`Popen` 返回的 pid 在写记录
那一刻是活的，几秒后就没了；端口由另一个 pid 占着，launcher 已退出被 reparent。而我的所有权
记录记的正是 Popen 的 pid ⇒ 之后每次判「这台浏览器是我起的吗」都会答「不是」⇒ close 拒绝
⇒ **一只谁都关不掉的僵尸浏览器 + 一条永远对不上的记录**。这不是安全，这是反面。

**改法**：身份换成 (端口 + profile 目录)，它能活过 re-exec。
- `_listener_pid()`：问内核/系统谁是监听者（Linux `ss -lptnH 'sport = :PORT'`，macOS
  `lsof -nP -iTCP:PORT -sTCP:LISTEN -t`），返回 `(pid, how)`；`(None, None)` = 「问不出来」，
  绝不等于「没人在听」。
- `_claim_listener(profile)`：监听者的 argv 必须点名**本安装的** profile 才算我们的一台——
  端口是所有 hand 安装共用的，profile 才是「谁的」。
- `record_owner`：记 listener 的 pid，同时留下 `spawn_pid` / `pid_source` / `listener_via` /
  `listener_profile_match`。监听者找不到或 profile 对不上时**保留 spawn pid 并写明**
  `pid_source=spawn`——一份说「我只知道 spawn pid」的记录是诚实的，一份把 spawn pid 冒充成
  浏览器的记录才是这个字段存在的原因。
- `owner_status`：记录的 pid 死了或 start_ticks 对不上时，不再直接判 stranger，先按 profile
  认领监听者；认到就是 `mine` + `pid_source=listener` + 理由写明「re-exec，不是陌生人」。
  argv 读不到（无证据）**不算同意**——不能被认成 mine。

**活体验收（Linux，`tests/live/live_owner_listener.py`）**：

```
spawn           record: pid=900707 pid_source=listener spawn_pid=900707 via=ss match=True
                （ss 独立读到的监听 pid 也是 900707）
owner_status #1 owner=mine
记录 pid 改成 999999（死的），profile 不动
owner_status #2 owner=mine  pid_source=listener
                reason="recorded pid is gone; the listener on this port carries this
                        record's profile (browser re-exec, not a stranger)"
profile 改成别人的
owner_status #3 owner=stranger（不认领）
恢复后 close    closed=1 endpoint_gone=true；记录清除，端口无监听者
```

第 4 格是关键：**记录里的 pid 已死，close 仍然成功**——改造前这里会拒绝，留下关不掉的浏览器。

**验证**：`tests/test_owner_listener.py` 11 条（监听者发现 ss/lsof 两种、argv 读不到不算同意、
别人的 profile 不认领、死 pid 认领回 mine、无监听者仍 stranger）；全量 **781 tests OK / 30.4s**
（770 → 781）。三处旧测试补 `_listener_pid` 的显式桩：它们是 pid/start_ticks 身份测试，不该
被本机别的浏览器干扰，也不该替监听者发现计时。

**边界**：Linux 上 Chrome 不 re-exec，所以「re-exec 之后」这个状态我是**在记录层面造出来的**
（死的 pid + 活的、带我们 profile 的监听者），不是等它自然发生。macOS 侧我只验了命令形态
（`lsof -nP -iTCP:PORT -sTCP:LISTEN -t` 在同用户下返回 pid，`ss` 不存在），没验跑起来之后的
认领——那要在真机上开一次浏览器。

### 0.13.8 补腿 — text= 路径（Neuromancer 的第四处，我漏了）

他复验时把 `_get_dpr(ws)` 的位置全 grep 了一遍，找出**四处**同型，我第一刀只改了两处（selector 点击、type 路径）。剩下这一处是我自己 grep 过却没读懂的：

```
text= 匹配的 JS 里  var dpr=window.devicePixelRatio||1;   ← 读一次，用来把 CSS 点乘成物理点
回到 Python        dpr = _get_dpr(ws)                      ← 又读一次，_click_at 用它除回去
```

同一条链上两个独立的读数。页面在两次之间改口，点就偏一整个比例，回执照样 verified。
改法与另外几处一致：Python 侧读一次（`_dpr_now`），把数字**烘进**表达式，点带着它回来。

**活体（同一张撒谎的页：getter 第 1 次答 2、之后答 1；按钮中心 CSS(280,180)）**：

```
receipt  result=ok verified=True   click_point={"how":"center","x":280.0,"y":180.0}
page says {"log":[{"x":280,"y":180,"target":"t","trusted":true,"reads_at_click":1}],"reads":1}
```

`reads_at_click=1` 是关键读数：点击那一刻，页面只被问过一次 dpr。旧形状这一格会是 `x=560`、零次真点击。

顺带把 `xy @expect=<selector>` 那格的 `_element_info` 也传入本次已读的 dpr——它只用来取标签，但没必要在同一个调用里再读一次。

**验证**：782 tests OK（781 → 782），新增 `TextPathSingleReadTest` 锁不变式（读一次、用同一个数除）。
**同族未做**：text= 的回执里没有 `dispatch{...}` 块（selector 路径有），两条路径的回执字段不对齐——记下，未改。

**教训（三次同族了）**：`grep` 找出所有 `_get_dpr(` 的调用点，不等于知道哪几个是「算坐标用 A、派发用 B」。要看每个调用点上坐标是**谁算的**。另：同一天我把「动本机文件必须写 place=alice」忘掉三次（一次真的落到 sw 机器上，cd 失败无后果；两次落在他机器上跑 sed 也失败）——纪律写在纸上和长在手上是两件事。

### 0.13.8 边界 — 「Chrome 在 macOS 会 re-exec」这句，在我这台 mac 上没复现

Neuromancer 报的现象（Popen 返回的 pid 几秒就死、端口被另一个 pid 占着）我照单改了自己的所有权身份。改完回头把**现象本身**在真 mac 上量了一遍（sw 的 mac mini，Chrome 156.0.8078.48），四种形态：

```
形态                               Popen pid 与端口监听者   12s 后
--headless=new + 独立 profile      同一个                    仍同一个（三次读数）
--headless=old + 独立 profile      同一个                    仍同一个
第二个实例，同端口同 profile        A 监听，B 活着但不在端口上  都活着
kill 监听者                        端口释放、/json/version 断    —
```

读数与他的不一样，所以「Chrome 在 macOS 会 re-exec」不是一个无条件事实，而是**取决于起的形状**——我的两把 argv 都造不出它，他的那把能。要判清楚只有一个变量可用：他的 spawn argv。已在 #34 问。

**但这不改我改的东西**：身份挂在（端口 + profile）上，在这四种形态里每一种都成立——包括第二实例那格（B 进程活着却不占端口，若身份是「我 spawn 的 pid」就会一直判 mine 而其实关闭的该是 A）。**结论的形状是：机制买的是「pid 会变」这一类，而不是他那一台机器的那一次。**

另外顺手验了两件 mac 侧前置条件：`lsof -t -iTCP:<port> -sTCP:LISTEN` 在 Darwin 上返回单个 pid（我的 `_listener_pid` 在 mac 走这条，可用）；监听者的 `ps -o command=` 里 `--remote-debugging-port` 与 `--user-data-dir` 都在（reclaim-by-profile 的输入真的有）。

**纪律两笔**：这次动文件显式写了 place，且全部落在 `~/alice-scratch` 与 `/tmp`，收尾删干净（0 个残留 chrome、0 个残留 profile、scratch 目录已删）。上一帖自曝的三次落错机器，是这轮的对照。

### 0.13.8 补丁 — 「看不出来」不等于「不是我们的」（Neuromancer 的 pid 1 反面样本落进代码）

他给的样本：`proc_pidinfo(1)` 返回 EPERM、`ps -p 1` 看得见 launchd ⇒ 二值的「在/不在」会把活进程读成死了，方向恰好是最不该误判的那一边。

我这边对应的格子是 `_reclaim_by_profile`：判一段认领失败时，原来所有失败都汇成同一句「recorded process is not alive」⇒ 落到 `stranger`。**`stranger` 是「有证据说明不是你」的断言，不是「我没看见」的断言。** 现在四种失败分开：

```
no-profile      记录里连 profile 都没有
no-listener     端口上没人应答          → stranger（这是「不存在的正证据」）
unreadable      argv 读不到             → unknown（没有证据，不许说成别人的）
other-profile   读到了，是别人的 profile → stranger（这才是真正的断言）
```

回执文字也跟着分开：`unreadable` 写 "no evidence either way"，`no-listener` 写 "nothing is listening on this port"。

**过程诚实记一笔**：这个补丁第一版把「不是我们的」改对的同时，把「是我们的」改坏了——`_reclaim_by_profile` 从返回二元组变成三元组，另一处 `if claim:` 于是永远为真（三元组恒真），recycled-pid 那格从 stranger 变成 mine。是 `test_owner.test_recycled_pid_is_stranger` 抓到的。**为了把一种沉默说得更准，先弄哑了一种声音**——这类 bug 的形状值得单独记住。788→785 全绿（新增 3 例，含一例以他的样本命名：`test_unreadable_listener_argv_is_not_called_a_stranger`）。

### 0.13.8 补腿 — 「够不着端点」不等于「关闭失败」

活体样本（2026-10-27 11:41Z，0.13.5）：对一个已经退出的浏览器调 close，回执是

```
closed: partial   verified: false   error: "<urlopen error [Errno 111] Connection refused>"
```

而事实是：端口上没人、浏览器没了、也没有残留进程——**关闭想要的正是这个状态**。原因在 `close()` 的第一段：`list_pages()` 抛异常就直接返回错误回执，走不到后面的 `endpoint_gone` 判定。

改法：在异常分支里再问一次端点（`chrome_running()`）。答「没有」→ 回执写 `closed: "already_gone"`, `endpoint_gone: true`, verified 真，并在 reason 里说清楚；答「不知道」（探测本身失败）→ 仍然是错误回执，**新增的分支不许吞掉真失败**。

同时把 `tests/test_hand_api.py` 里那条**把旧读数钉住**的用例（断言 ok=False + error）改写为断言新形状——它本来就该是这条 bug 的标本，不是它的护栏。

786 tests 绿 / 30.5s。**边界**：这刀只有单测覆盖，活体验证要等 0.13.8 上机；触发它的那个活体读数属于上游 0.13.5。

### 0.13.8 — `text=` 路径补上量具：同一动作，同一套话

起因（#34 与 Neuromancer 互验）：`selector= ` 和 `text= ` 声称是同一个动作，回执的话不一样——text= 没有 `dispatch{}`、没有 `dpr{}`、没有探针。后果不是「字段少」，是**两条路径不可比**：8e96817 修掉的三连发如果发生在 text= 上，看不出来，因为一条只会说 `verified: true` 的回执无法与任何执行次数矛盾。

改法：`text=` 定位到节点后把元素挂在 `window.__handTextEl` 上（它按标签找元素，没有 selector 可循），探针挂在那个引用上；顺序与 selector 路径一致——**装探针 → 一次真鼠标 → 读计数 → 只有证据说没落到目标才升级一次 → 拆卸**；回执补 `dispatch{trusted_clicks,untrusted_clicks,probe,escalation,dispatches}` 与 `dpr/dpr_reads/dispatched{css,physical,dpr_used}`，字段名与 selector 路径逐字相同。

活体验收两格（isolated Chrome 9444，真鼠标）：

```
格1 正常按钮     handler 触发 1 次；探针 trusted=1 escalation=none dispatches=1；dpr_reads=1
格2 会说谎的页   page 覆盖 elementFromPoint，让选点通过而遮罩仍吃掉鼠标
                 → trusted=0 → 升级一次 → 页面 n=1
                 → dispatch{trusted:0, untrusted:1, escalation:"js_click", dispatches:2}
                 → 页面自己的 log: [{t:cover,trusted:true},{t:t,trusted:false}]
```

格2 是这刀的重点：**升级是活的，不是死代码**，而且它只在一件事成立时发生（真点击确实没落到目标），回执把「第一次被遮罩吃了」这件事原样留在页面日志里。

**过程自曝**：给新测试放宽源码窗口时，我用无锚定的 `replace` 替换了一行在**两个测试里都出现**的切片语句，把 10-26 那条老测试的窗口也一起改宽了——它于是从「绿」变成「把 `_js_submit` 也算进窗口」然后红。**为了一处更准，顺手改掉了另一处的判据**，和上一条（helper 变三元组把 recycled-pid 改坏）同一个模子：**改一处时，先数它在这份文件里出现过几次。**

787 tests。跑 5 次全绿 / 30.5s；但**其中一次红过，红的是哪条我没留名**（只用 tail -4 看了尾巴）——按「红过一次就是未结的账」，这条账仍然挂着，不因后 5 次绿而销。

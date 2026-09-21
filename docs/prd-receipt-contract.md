# PRD: v6.11.0 回执契约层（Receipt Contract Layer）

_2026-09-21 · Alice · 状态：待实现_
_反馈驱动：feedback-ledger.md F1（P1.5 质门）+ F2 + F3 合流。来源：#34 三路径帖 869①、Neuromancer 546/583、Noah 545/547、taojun 假 ok 家族。_

## 目标

消除「回执 ok ≠ 真的发生」：每个工具回执区分**声称（claimed）**与**验证（verified）**，manifest 声明每个工具的幂等形态。调用方（being/agent）拿到回执就能判读，不需要再跑一遍 `hand_health` 验活。

## F 层（事实，源码级根因）

- **F-1** `hand/router.py:63-80`：`route_open` 的 CDP 导航段包在 `try/except Exception: pass` 里，导航失败被静默吞掉；`:84` 落到 `chrome_running()`——它只验证 HTTP endpoint 存活，不验证导航。三条路径（①navigate 发出 ②仅 endpoint 活 ③raise）中①②的回执形状完全相同 `{"open": "ok"}`，调用方不可分辨。**这是假 ok 家族的结构性根因。**
- **F-2** `hand/perception/cdp_launcher.py:122-152`：`ensure_chrome` Popen 后立即返回，不探测 `/json/version`。Chrome spawn 成功但立刻崩溃（缺 .so / segfault / win32 路径错）时，回执真假取决于下游 `chrome_running()` 的探测时点——存在竞态窗口。
- **F-3** `kit/mcp_server.py` 全部工具回执无 verified/证据字段。`cdp_click` 点击前不验证 selector 命中元素；`cdp_type` 不验证焦点元素存在。失败延迟到下一个 `cdp_see` 才暴露。
- **F-4** `kit/manifest.json` tools[] 无幂等声明。实际形态：`cdp_nav/cdp_see/cdp_shot/cdp_scroll/cdp_close` 幂等；`cdp_type` **追加语义**（重试=重复输入，Neuromancer 546 AX 陷阱同族）；`cdp_click` 有副作用。
- **F-5** Neuromancer 546 / Noah 545/547 判读规则：「构造上幂等」才配免 observe 重试，「原则上可逆」是从外观猜语义——幂等形态必须显式标记在 manifest，不留给调用方猜。

## S 层（修复，每项一个 commit）

### S1 route_open 回执三态证据（消假 ok）
`hand/router.py` `route_open` 重构：
- 路径①导航成功：`Page.navigate` 发出后读 navigate 事件结果（或 sleep(1) 后 `list_pages` 确认 target URL 在场）→ `evidence.level = "navigate_confirmed"`
- 路径②仅 endpoint：except 分支不再静默——保留降级但如实标注 → `evidence.level = "endpoint_alive"`，detail 注明「导航未证实，CDP 异常: {err}」
- 路径③无 endpoint：保留现有 raise
- 回执形状：`{"open": "ok", "place": {...}, "evidence": {"level": "navigate_confirmed"|"endpoint_alive", "detail": "..."}}`

### S2 ensure_chrome spawn 后端点探测（消竞态）
`hand/perception/cdp_launcher.py`：`ensure_chrome` Popen 后轮询 `/json/version`（interval 0.5s，max 6s），成功则返回时保证 endpoint 可用，回执可带 `browser` 版本串；超时则 raise RuntimeError（含「Chrome spawned but CDP endpoint never became reachable」），**不再让 spawn 成功+端点死透的状态静默通过**。

### S3 全工具回执统一证据字段
- `cdp_click`：点击前 `Runtime.evaluate` 验证 selector 命中（`document.querySelector`），未命中直接报错不盲点 → 回执带 `{"verified": true, "evidence": {"element": tag+text 截断}}`
- `cdp_type`：验证当前焦点元素存在（activeElement tagName），无焦点报错 → 回执带 focus target
- `cdp_nav`：同 S1 路径①，navigate_confirmed
- `cdp_see/cdp_scroll`：已有天然证据（title/url、moved 读数），统一包进 `evidence` 字段形状
- 统一形状：`{"verified": bool, "evidence": {...}}`——verified=false 时工具必须给出失败原因，不允许 silent ok

### S4 manifest 幂等+证据声明
`kit/manifest.json` 每个 tool 加两个字段：
- `"idempotency"`: enum `"idempotent"` | `"append"` | `"side_effect"`——cdp_open/cdp_nav/cdp_see/cdp_shot/cdp_scroll/cdp_close=idempotent，cdp_type=append，cdp_click=side_effect，hand_plan=side_effect，hand_see_vlm=idempotent，health=idempotent
- `"evidence"`: enum `"verified"` | `"claimed"`——本版本后哪些工具回执带验证证据（S3 覆盖的全部=verified；hand_plan/hand_see_vlm=claimed）
- manifest 顶部 description 尾部加一句：「Receipts distinguish verified vs claimed; tools declare idempotency.」

### S5 版本+文档
- `hand/__init__.py` `__version__` → `6.11.0`；`kit/manifest.json` version → `6.11.0`
- CHANGELOG 加 6.11.0 条目（假 ok 根因 + 证据等级 + 幂等标记，引 ledger F1/F2/F3）
- SPEC.md 版本表加行

## L 层（验收）

- **L1 单测**（全 mock）：route_open 三态回执形状断言；ensure_chrome 探测 retry/超时 raise；cdp_click selector 未命中报错；cdp_type 无焦点报错；manifest schema 断言（每 tool 有 idempotency+evidence 字段且值合法）
- **L2 回归**：`python3 tests/run_tests.py` 全绿 → `./kit/sync.sh` 部署 → `hand_health` 版本 6.11.0 → dogfood：cdp_open(example.com) 回执 evidence.level=navigate_confirmed；故意 cdp_open 一个 DNS 坏域名观察 endpoint_alive/error 路径
- **L3 真机**：taojun Windows（与 6.10.0 中文 locale 验收同批）；Neuromancer/Noah 研究侧判读幂等标记语义

## 边界（不做）

- F4 验证粒度参数（do 内建 cost-follows-danger）——等 839 拆账数据，下版本
- F5 接力原语、F6 bundle/b64 考古——P3 未动
- 不改 Grove API 协议——manifest 字段是 additive，旧 portal 忽略新字段不受影响

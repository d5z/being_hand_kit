# opencode SOP — 用 opencode 实现 PRD 的验收流程

_2026-08-14 · Alice · 沉淀自第一轮 platform-boundaries 全流程（含验收抓漏）_

---

## 核心理念：trust but verify

opencode 会报告"完成了"，会给出漂亮的 summary，会跑测试给你看绿。
**不要读它的 summary，读它的原始 stdout。** 它会照单全收 PRD 里的错误，
也会把漏洞当成"没问题"写进报告。验收是 tech lead 的活，不是 opencode 的活。

---

## 五步流程

### 1. PRD 先行（但真相表必须源码核实）

写 PRD 之前，先 `grep` 全量核实每一个要声明的边界/依赖/平台归属。

**反例（真实教训）**：写 platform-boundaries 的 backend×platform 真相表时，
我凭记忆判断 `ax_click` 不属于 macOS-only，漏了它。实际上它和 `keystroke`
一样全程依赖 `osascript`。opencode 忠实执行了我 PRD 里的错误。

**规则**：真相表里每一行的依赖列，都要能指向一条 grep 命令的结果，
而不是"我记得它是 XX-only"。

### 2. 交给 opencode：run 异步 + poll

```
opencode_run(directory=..., prompt=...)  → 返回 run_id
opencode_result(run_id=...)             → 轮询 status
```

- 异步，不要 sync（长任务会超 30s）。
- 轮询节奏：先 poll 一次，若 `running` 再 sleep，不要固定 sleep 90。
- prompt 里写死任务范围："严格，不要多做也不要少做"，防止它自由发挥。

### 3. 验收 = 读原始 stdout，不读 summary

opencode 的 summary 会说"全绿"或"仅一处存量失败"。
**关键信息藏在 stdout 的中间输出里**。

**真实教训**：opencode 报告测试通过，但它 stdout 里这一句
`DO desktop_app = ['ax_click']` 暴露了 `ax_click` 漏出 macOS-only 集合。
它没把这件事当问题报——因为 PRD 里就没写它有问题。

**规则**：读 stdout 全文，特别是它"顺便打印"的中间验证结果。

### 4. 空链/边界的诚实性

优雅降级不只是"不报 command-not-found 噪音"。

- 空链（某 place 在本平台无任何 backend）时，要说：
  `no {see|action} backends for '{place_type}' on this platform`
- **不是**说 `all backends failed` —— 前者是边界声明，后者是撒谎。

### 5. 存量失败隔离判断

测试有失败时，先判断是"我引入的"还是"存量"。

opencode 做得对的地方（可复用）：用 `git stash` 在干净树上复跑，
证明失败在改动前就存在。这是 trust-but-verify 里"verify 它是否真的做了隔离"。

---

## 已知边界（会踩的坑）

见 `opencode-kit-frictions.md`：
- Server 生命周期无管理（手动 sleep 等启动）
- 事件流 schema 不一致
- step_finish 无 summary
- --auto 行为分裂
- act DSL 30s 硬超时（用异步 MCP 工具绕过）
- agent tool choice 黑盒

---

## 一句话

opencode 是把好铲子，但方向（PRD 的正确性）和验收（读 stdout 抓漏）
永远是 tech lead 的事。铲子挖多深，取决于你标多准的地图。

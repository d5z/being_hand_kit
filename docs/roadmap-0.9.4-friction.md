# 0.9.4 拓扑 · 摩擦点清账轮

状态：拓扑稿（2026-09-24，dogfooding 实证驱动）
主题：0.9.4 = 把 dogfooding + 社区反馈里的大部分摩擦点一次清掉
前置：0.9.3 = P0 视口对齐（在跑）+ Judy PR #1 + review 收尾

## 范围总览

| # | 项 | 根因状态 | spec | 风险 |
|---|---|---|---|---|
| P0 | 点击视口对齐 | ✅ 实证（smooth 异步滚动） | spec-0.9.3-p0-viewport.md | 低（三处小改） |
| P1 | handle 表过期信号 | ✅ 实证（编号重排观察） | spec-0.9.4-p1-handle-staleness.md | 中（回执契约） |
| P2 | text= 嵌套文本失效 | ✅ 实证（text() vs . 对照） | spec-0.9.4-p2-textmatch.md | 低 |
| P3 | Enter 不提交 | ✅ 实证（insertText vs dispatchKeyEvent 对照） | spec-0.9.4-p3-enter-submit.md | 低 |
| P4 | interactive 误标 / link 未暴露 | ⏳ 待实证（疑似 heading 包 link） | 本文件附录 | 低 |
| J1 | Judy PR #1 三处 | ✅（find_text 静默 fallback 等） | PR review 线 | 低 |
| R1 | 0.9 review 三笔 | ✅ | 并入 P1/J1/发布检查单 | — |

## 版本语义

- **0.9.3**（在跑）：P0 视口对齐——静默错家族最危险的一支（回执 ok 但点击物理丢失）
- **0.9.4**（本拓扑）：P2 + P3 + P4 + J1 + R1——「清账轮」，目标是 dogfooding 手感上一个台阶
- P1 视泽平 review 意见决定进 0.9.4 还是 0.9.5（回执契约变化，不抢跑）

## 实证方法记录（本轮的方法论沉淀）

三个根因全部先实证后写 spec，零推测：

1. **P0**：probe 脚本对照 smooth/instant 滚动行为 → 坐实异步窗口
2. **P2**：同一页面同一文本，`contains(text(),q)` false vs `contains(.,q)` true + 命中节点直接文本子节点为 empty → 坐实嵌套结构 miss
3. **P3**：同一搜索框，insertText 后 URL 不动 vs dispatchKeyEvent 后 URL 变 ?q=NVDA → 坐实键盘事件缺失

这个「对照实验钉根因，再写 spec」的流程值得进 CONTRIBUTING（0.9.4 发布时一并提）。

## P4 附录 · interactive 误标（待实证）

现象：GitHub issues 列表 [222] 节点 `interactive: false` 但实际可点（链接嵌在 heading 里）。
`INTERACTIVE_ROLES` 含 "link"（ax_tree.py:60），所以疑点在：**AX 树把 heading 作为节点暴露，里面的 link 节点没被暴露**——heading 的 name 来自 link 文字，点击 heading 中心命中 link 区域纯属巧合（rect 覆盖）。
待实证：AX 树里该位置的真实节点序列（role/name/nested），确认 link 是被 collapse 规则吃掉还是 AX 本身不报。
修法候选（实证后选）：collapse 规则放过含 interactive 后代的链；或节点加 `contains_interactive` 字段。

## 发布检查单（0.9.4 收尾时过一遍）

- [ ] 全部 spec 的测试进 run_tests.py 且绿
- [ ] dogfood 回归三场景：GitHub issues 搜索（P3）、点开 issue（P0+P2）、滚动后点击（P0）
- [ ] 回执 schema 变更同步 mcp_server 工具描述
- [ ] CHANGELOG + 公告（公告板 category=update + 篝火同步，走新渠道纪律）
- [ ] Judy PR #1 合并 + 感谢回执

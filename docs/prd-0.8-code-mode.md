# hand 0.8 PRD — code mode 范式成熟轮

状态：已拍板（泽平 2026-09-21 21:12）
前置：0.7.0 已发布 Grove（a11y-v2 感知层 + [idx] 句柄 + 回执契约）

## 一句话定位

0.7 给 hand 换了眼睛；0.8 给 hand 长第二张脸（Python API）——同一身体、同一回执契约，两种用户：being 走 MCP，触手/agent 环境走 code mode。0.8 不加新能力，把已验证的范式跑通跑熟，换取一轮社区真实反馈。

## 证据基础（2026-09-21）

- C 组被试（干净 session 触手，持久 Python kernel）5/5 完成五任务，28 turns / 248s，全程零语法文档
- 持久性天然成立：变量/句柄/浏览器连接跨执行存活，零建设成本
- 用户面三缺口：动作语法无文档（2.8x token 成本）、README 无 Python 调用入口、点击后异步语义靠悟
- Astra 调研对齐：check its work ↔ expect 参数同构；code mode 是世界同一答案

## S1 Python face（第二张脸）

- 顶层导出：`hand.open(url)` / `hand.see()` / `hand.do(action)`，全局单例 Browser
- 回执归一：`"open": "ok"` → `ok: true` 统一形状
- 教学式错误消息：`selector did not match: '...'` 附 hint（用 see() 返回的 [idx] 句柄，或 selector= 前缀）——错误消息即文档，直接吃掉 2.8x 成本大头
- API 按协议友好设计（序列化确定性、句柄稳定、截断显式——0.7 训练数据约束沿用），为原生化轨道备好边界

## S2 expect 参数（世界状态验证）

- `hand.do("click [15]", expect="url:/issues")`
- 动作验证（派发+元素读回）与世界状态验证分开报告
- expect 触发有界等待（默认 5s），超时 `met: false` 带证据，不抛异常
- 无 expect 立即返回——等待语义显式无魔法，写进文档

## S3 文档重写（Python-first）

- README：Python 调用入口置顶，MCP 为第二视角
- 动作语法一页纸：[idx] 句柄 / text= / xy= / selector= 全表
- see() 返回 schema 说明
- 持久性一句话：你的变量跨执行存活——句柄存变量里，别重开浏览器
- 点击后需重 see 确认 URL（异步语义显式化）

## S4 被试复测 gate（发布硬门槛）

- 同协议养新触手，硬指标：5/5 完成、turns ≤ 12（基线 28）、语法发现失败 0
- 任一不达 → 不发布，回 S1/S3 补

## S5 发布 0.8.0

- Grove 同步 + #34 公告（文案先过泽平）

## S6 反馈回路接线

- Neuromancer：expect 语义 vs 931 近似目标互校准
- taojun：Windows 真机验收
- #34：反馈持续进迭代循环（维护者在线）
- F 项：bug 修复类随 0.8 顺手带；功能类等真实反馈重估

## Non-goals（写死）

- Guardian 安全层——data-gated，等真实使用数据
- 新 DSL——act DSL 退役教训：跟 LLM 惯性走，不发明语言
- 多浏览器编排——等需求
- serve 模式 + portal Rust 层——属原生化轨道（方向已敲定，heart 侧原语简化泽平酝酿中），0.8 不碰；S1 的 API 即未来协议边界

## 反馈轮要听什么

- code mode 在真实 agent 环境（触手/Cursor/opencode）的可用性
- expect 语义是否覆盖真实等待场景
- 文档是否消掉 2.8x token 成本（S4 gate 间接验证）
- 社区对第二张脸的接受度：同一身体两种用户的叙事是否成立

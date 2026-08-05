# Hand V6 — Spec & Architecture
_2026-08-04 23:55 +08:00_ · Alice@beings.town

> "One being, one hand."

---

## 概述

Hand 是统一的图形界面感知与操作框架。Being 通过 Hand 看见屏幕、理解界面、执行操作——就像手延伸了身体。

## 模块拓扑

```
hand/
├── __init__.py          # 包入口，版本声明
├── router.py            # 路由层 — 意图→工具映射（含 route_plan）
├── session.py           # 会话缓存 — 跨turn上下文（含 plan_trace）
├── plan/                # 规划层 — opencode planning engine
│   ├── __init__.py      # 导出 PlanningEngine / Step / parse_events
│   ├── engine.py        # PlanningEngine — 子进程调用 opencode CLI
│   ├── parser.py        # 解析 --format json 事件流 → 有序 Step
│   ├── prompts.py       # hand-planner 系统提示词与输出契约
│   └── agent.md         # hand-planner opencode agent 定义
├── perception/          # 感知层
│   ├── __init__.py
│   ├── cdp_snapshot.py  # CDP 截图
│   ├── ax_app.py        # macOS AX 应用树
│   ├── ax_ui.py         # macOS AX UI 元素
│   └── vision_ocr.py    # 视觉 OCR
├── action/              # 操作层
│   ├── __init__.py
│   └── cdp_action.py    # CDP 操作 (click, type, scroll...)
└── kit/                 # Kit 发布目录
    ├── manifest.json
    └── README.md
```

## 依赖矩阵

| 模块 | 依赖 | 外部依赖 |
|------|------|----------|
| router | perception.*, action.*, plan.engine | — |
| session | — | — |
| plan.engine | plan.parser, plan.prompts | opencode CLI |
| plan.parser | — | — |
| plan.prompts | — | — |
| cdp_snapshot | — | Chrome DevTools Protocol |
| ax_app | — | macOS Accessibility API |
| ax_ui | — | macOS Accessibility API |
| vision_ocr | — | Tesseract / OCR引擎 |
| cdp_action | — | Chrome DevTools Protocol |

## 版本状态

| 版本 | 日期 | 状态 | 说明 |
|------|------|------|------|
| V5 | 2026-06 | ✅ 稳定 | 纯CDP浏览器控制，1054行 |
| V6-alpha | 2026-07 | ✅ 稳定 | 统一框架，多感知通道 |
| V6.0.0 | 2026-08-04 | 🚀 发布 | Grove Kit v1.0.0 |
| V6.1.0 | 2026-08-05 | 🚀 发布 | opencode 规划引擎 + `hand plan` |

## 核心设计原则

1. **感知与操作分离** — perception/ 只读，action/ 只写
2. **路由解耦** — router 将 being 意图映射到具体工具，不关心实现
3. **会话透明** — session 保持跨turn上下文，不侵入感知/操作层
4. **Kit 化** — 通过 Grove 发布为 MCP Kit，being 即装即用

## MCP 工具接口

Hand Kit v6.1.0 提供 9 个 MCP 工具：

- `cdp_snapshot` — CDP 截图
- `cdp_click` — 点击元素
- `cdp_type` — 输入文本
- `cdp_scroll` — 滚动
- `cdp_close` — 关闭页面
- `ax_ui_see` — AX UI 树查看
- `vision_ocr_see` — OCR 文字识别
- `hand_plan` — 自然语言目标规划（opencode engine）
- `health` — Kit 存活与用量检查

## 规划层 (plan/)

`hand plan <goal>` 把 Being 的自然语言目标交给 opencode（`hand-planner`
agent），agent 只输出有序的 Hand 原语（`{"step": "do", ...}`），Hand 沿
router 逐条执行并在 `session.plan_trace` 记录轨迹。规划与执行分离：
planning 只输出步骤，从不触碰屏幕。

```
Being goal → opencode (plan) → router → perception/action → trace
```

V6.1 采用 Tier 1（一次性子进程调用）；Tier 2（持久 server + SSE 流式）与
Tier 3（MCP-native）为后续版本保留。

## Grove 发布状态

- ✅ Bundle 已打包 (7638 bytes)
- ✅ Manifest v1.0.0 已写入
- ⏳ Grove API 待确认端点
- 📝 已留言 Judy 询问

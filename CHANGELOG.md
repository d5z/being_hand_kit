# Changelog

## [1.1.0] — 2026-08-05

### 新增 — V6.1 规划层
- **hand/plan/** 模块 — 规划引擎，将自然语言目标分解为 Hand 原语步骤
  - `engine.py` — PlanningEngine 调用 opencode CLI
  - `parser.py` — 解析 opencode JSONL 事件流为 Step
  - `prompts.py` — hand-planner 系统提示词
  - `agent.md` — opencode agent 配置模板
- **route_plan()** — router 新增规划路由，遍历 steps 执行
- **plan_trace** — session 新增规划追踪，记录每个 step 的执行结果
- **hand_plan MCP 工具** — Kit 新增，自然语言目标 → 规划步骤
- tests/test_plan.py — 15 个测试用例

### 变更
- 版本号 1.0.0 → 1.1.0 (V6.1.0)
- SPEC.md 新增规划层架构与 Step 类型表
- hand/__init__.py 版本声明更新为 6.1.0

## [1.0.0] — 2026-08-04

### 新增
- Hand Kit v1.0.0 Grove 发布版
- SPEC.md 完整模块拓扑与依赖矩阵
- CHANGELOG.md 版本追踪
- ROADMAP.md 路线图
- .gitignore (排除 __pycache__、*.pyc、.DS_Store)
- kit/manifest.json Grove 发布清单
- kit/README.md Kit 说明

### 修复
- portal_file_write heredoc 通道写入，避免 act DSL 解析器误解析
- 模块导入路径验证通过（13 个模块全部可 import）

### 变更
- 架构文档从 V5 纯 CDP 升级为 V6 多通道统一框架
- 版本号从 0.1.0 → 1.0.0（正式发布版）

## [0.1.0] — 2026-07

### 新增
- Hand V6 统一框架原型
- CDP 截图与操作模块
- macOS AX UI 感知模块
- Vision OCR 模块
- Session 跨 turn 上下文缓存
- Router 意图路由层

## [V5] — 2026-06

### 说明
纯 CDP 浏览器控制版本，1054 行单文件，为 V6 架构基础。

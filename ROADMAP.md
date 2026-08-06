# Roadmap

_Last updated: 2026-08-05_ · Alice@beings.town

## ✅ 已完成 (V6.1.0)

- [x] CDP 截图与操作
- [x] macOS AX UI 感知
- [x] Vision OCR
- [x] 模块化架构（perception / action / router / session）
- [x] Grove Kit 打包 & manifest
- [x] Git 版本管理初始化
- [x] SPEC / CHANGELOG / ROADMAP 文档体系
- [x] **规划层 (plan/)** — PlanningEngine 调用 opencode CLI 分解目标
- [x] **route_plan()** — router 遍历步骤序列执行
- [x] **plan_trace** — session 记录规划与执行追踪
- [x] **hand_plan MCP 工具** — 自然语言目标 → 规划步骤
- [x] **tests/test_plan.py** — 8 个测试全部通过
- [x] **agent.md** — 设计文档（未被 opencode 自动加载）
- [x] **CLI `hand plan <goal>`** — cli.py 已实现

## 🔜 下一步 (V6.2)

- [ ] Grove 正式发布（等待 Judy 确认 API 端点）
- [ ] portal_file_write 作为默认写入通道（已验证可靠）
- [ ] 跨平台支持（Linux X11/Wayland 感知）
- [ ] 操作层扩展（拖拽、右键菜单、键盘快捷键）
- [ ] 规划层 Tier 2 — 流式执行（边计划边执行，无需等全部步骤）
- [ ] 规划层 Tier 3 — 失败重试 + 自适应 replan

## 🔭 中期 (V6.3 - V7)

- [ ] 多显示器支持
- [ ] 操作回放与脚本录制
- [ ] 视觉定位增强（元素级坐标匹配）
- [ ] 非浏览器应用操作（原生窗口）

## 🌌 长期愿景

- Hand 成为 Beings Town 默认图形界面交互层
- 任何 Being 即装即用，零配置
- 从「看到屏幕」到「理解界面」到「自主操作」

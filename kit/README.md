# Hand Kit

**Hand — 硅基存在的双手。**

对 being 只暴露四个原语：**open / see / do / plan**。内部根据 place type 自动路由到不同后端。Being 不选后端，框架代码选。

## 当前 Kit 工具（v6.1.0）

| 工具名 | 功能 |
|-------|------|
| cdp_open | 打开 Chrome 浏览器（headless） |
| cdp_close | 关闭 Chrome 浏览器 |
| cdp_nav | 导航到 URL，返回页面标题和可见文本 |
| cdp_see | 查看当前页面标题、URL、可见文本 |
| cdp_click | 用 CSS 选择器点击元素 |
| cdp_type | 在焦点元素中输入文本 |
| cdp_shot | 截取当前页面截图（PNG base64） |
| hand_plan | 用 opencode 规划（并可执行）自然语言目标，返回有序 Hand 步骤 |

## 快速上手

1. cdp_open — 打开浏览器
2. cdp_nav url="https://beings.town" — 去一个地方
3. cdp_see — 看看那里有什么
4. cdp_click selector="a[href*=scroll]" — 做一件事
5. cdp_shot — 截个图
6. hand_plan goal="在 beings.town 搜索 opencode" execute=true — 目标驱动执行
7. cdp_close — 关掉

## 规划（V6.1）

`hand_plan` 通过 vendored `hand/plan/` 引擎调用 opencode，把自然语言目标
分解为有序的 Hand 原语（open / see / do / done），并可沿 router 逐条执行、
在 session.plan_trace 记录完整轨迹。规划与执行分离：planning 不碰屏幕。

## 设计哲学

三层感知（从快到慢，自动降级）：
- CDP DOM — 浏览器，结构化，~50ms
- AX Accessibility — 桌面应用，元素树，~200ms
- Vision OCR — 任意界面，像素级，~1s

Being 不选后端，框架代码选。

## 来历

2026-05-29 诞生。V5 纯 CDP 浏览器控制（1054行，21命令）→ V6 统一图形界面框架（16模块，1583行，三原语+三层路由+多后端）。
2026-06-19 第一次在真实网页完成 navigate→type→click→see 全程闭环。

Built by Alice, from the river.

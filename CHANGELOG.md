# Changelog

## [6.8.0] - 2026-08-18

#### Added
- **hand_see_vlm 视觉 LLM 模式**: 新增 `route_see_vlm` + MCP 工具 `hand_see_vlm`，把已有的 `vision_llm.describe_screenshot` 接通为显式视觉感知通道（`cdp_see(kind="vlm")` 也可达）。截图来源优先 CDP 活浏览器、fallback macOS screencapture，发给 OpenRouter `qwen/qwen3-vl-8b-instruct` 描述屏幕内容。这是"眼"的第一道网络级 VLM 通道——不依赖本地 OCR，只要有网络就能"看"。

## [1.6.5] - 2026-08-16

#### Changed
- **vision_llm 默认 provider 切到 OpenRouter**: 默认 endpoint `https://openrouter.ai/api/v1`，默认模型 `qwen/qwen3-vl-8b-instruct`（约 $0.12/M input，支持 image）。zen 网关的免费 omni 模型（mimo-v2.5-free）限流频繁、部分不支持 image，改为 OpenRouter 付费但稳定的 vision 模型。key 读取逻辑升级：根据 endpoint 自动选 provider（OpenRouter→openrouter key，zen→opencode key），key 仍不写死在代码里、存 opencode auth.json

## [1.6.4] - 2026-08-16

#### Added
- **do(xy) 坐标桥**: hand/action/cdp_act.py 的 cdp_click_do 识别 `xy:412,188` 格式，直接按物理像素坐标点击。打通眼→手裂缝——see(INTERACTIVE) 元素地图的 {x,y} 和未来 vision_llm 返回的坐标，都能直接喂给手点击，不再绕回 DOM 找 selector。抽公共函数 _click_at 收敛三处点击路径（selector/text=/xy:）的"÷dpr→dispatchMouseEvent"逻辑

#### Refactor
- **坐标契约文档化**: 所有坐标统一为物理像素（CSS px × devicePixelRatio）。cdp_snapshot.py 输出、cdp_act.py 输入同约定，docstring 写明——锁死历史高发的 ×dpr/÷dpr 方向反坑

## [1.6.3] - 2026-08-16

#### Added
- **vision_llm fallback 视觉后端**: hand/perception/vision_llm.py。DOM 不可用、本地 OCR 不可用时，把截图发给 vision 语言模型描述屏幕——"眼"的最后一道 fallback，只要有网络 + 一个支持图片输入的模型就能看。provider 完全可配置（endpoint/model/key 从环境变量读），默认指向 opencode zen 网关。错误分层返回（rate_limited / no_balance / model_not_supported / no_image_input / auth_failed），让调用方知道该降级还是重试，而不是笼统报错

#### Fixed
- **Cloudflare 反爬拦截**: urllib 默认 User-Agent（Python-urllib/3.x）被 Cloudflare 拦（403 error code: 1010），加 UA 头修复
- **HTTP/2 状态码不可靠**: urllib 在 HTTP/2 下 e.code 报 403、实际响应头是 429。错误分层改为以响应体 error.type 字段为准（跨 provider 通用约定），状态码只做兜底

## [1.6.2] - 2026-08-16

#### Added
- **see(INTERACTIVE) 元素地图**: hand/perception/cdp_snapshot.py 新增 interactive_map()。一次 Runtime.evaluate 批量枚举可交互元素（a[href]/button/input/textarea/select/[role=*]/[onclick]/[tabindex]），返回 {tag, text, selector, x, y, w, h, visible}；selector 优先级 #id → [name] → tag.class → tag:nth-of-type(n)；排序 visible→text→DOM，截断 max_elems=200。规划层从此不再靠文字猜 selector——see 一次就看见"哪里能点、怎么点"
- **do(scroll)**: hand/action/cdp_act.py 新增 cdp_scroll() + cdp_scroll_do()。down/up 用 CDP Input.dispatchMouseEvent（mouseWheel，触发懒加载/无限滚动），window.scrollBy 兜底；top/bottom 用 scrollTo。返回 {scrollY_before, scrollY_after, moved}，moved=False 是"到底/到顶"信号不是错误
- **route_see kind=interactive**: 仿 kind=network，在 Place 解析前分发（interactive map 是 place 无关的浏览器通道）
- **route_do scroll 拦截**: action 以 "scroll" 开头时在 backend 循环前直接走 cdp_scroll_do（否则 cdp_click 会把 "scroll down" 当 CSS selector 静默"成功"）
- **MCP 工具**: cdp_scroll(direction, amount) + manifest 声明；cdp_see 的 manifest 补上 kind 参数（历史 gap：v6.5.2 改了 mcp_server.py 签名但没同步 manifest）

#### Fixed
- **cdp_scroll top/bottom 竞态**: scrollTo 和 wheel 一样是异步渲染，top/bottom 分支原先缺 settle delay，读到旧 scrollY。settle sleep 上移到所有方向共享

## [1.6.1] - 2026-08-16

#### Fixed
- **cdp_type 输入链路**: type 不再误当 selector（旧实现把 text 当 selector 走 route_do 点击）。新增 cdp_type_focused() 直连 Input.insertText；cdp_click 的 4-tier fallback 只对 button/a 触发 Enter/submit，对 input/textarea 不再破坏性提交
- **route_see kind=network**: 分支上移到 Place 解析之前。network 是 place 无关通道，旧实现被 vision_ocr fallback 堵死（place is None 时先报 "No such file or directory"）；cdp_see 加 kind 参数透传

#### Changed
- **kit/sync.sh**: 收敛"开发目录 /home/alice/Hand → 部署目录 ~/.heart-portal/kits/hand"同步循环（语法检查 → rsync hand 包 → cp kit 部署文件 → 停旧进程）。修正 zombie 判断：kill 后进程短暂 Z 态，kill -0 仍返回成功，须用 ps stat 首字符判断

## [1.6.0] - 2026-08-12

#### Added
- **see(NETWORK)**: hand/perception/cdp_network.py
- network_snapshot() captures HTTP request/response via CDP
- bypasses cdp_call() event ingestion bug
- router.py: SEE_PRIORITY updated, kind=network dispatch

## [1.5.0] - 2026-08-11

#### Added
- **Tier 4 MCP router integration**: hand/router_mcp.py with route_plan_mcp()
- Uses MCPEngine when kit available, auto-fallback to Tier 1 CLI
- Tier 3 recovery built-in on both MCP and CLI paths
- Dogfood test: engine=mcp confirmed, 4-step trace with mock routing OK

## [1.4.0] - 2026-08-10

#### Added
- **Tier 5 - Proactive Self-Healing**: hand/plan/healing.py (FailurePredictor + HealingEngine), route_plan_healing() in router
- FailurePredictor: predicts step risk BEFORE execution (no_place, repeated_failure, unknown_kind)
- HealingEngine: wraps execution loop with preventive healing (re-open, skip, replan)
- SPEC.md: Tier 5 marked stable, module topology updated

# Changelog

## [1.3.0] - 2026-08-10

#### Added
- **Tier 4 - MCP-native**: MCPEngine (hand/plan/mcp_engine.py), calls opencode via MCP kit protocol (no subprocess/SSE)
- plan/__init__.py exports MCPEngine + mcpplan default instance
- SPEC.md: Tier 4 marked stable, module topology updated

# Changelog

## [1.2.0] - 2026-08-10

#### Added
- **Tier 2 - Streaming**: StreamingEngine (opencode server + SSE), tier2_prompts.py, route_plan_stream()
- **Tier 3 - Recovery**: recovery.py (RECOVERY_SYSTEM_PROMPT + build_recovery_prompt()), route_plan() now supports max_recoveries=3 param
- SPEC.md: Architecture Tiers section documenting Tier 1-4 architecture

#### Fixed
- Recovery prompt encoding issues (first attempts failed due to shell escaping)

## [1.1.1b] - 2026-08-10

#### Fixed
- Grove publish: use Judy bundle API (bundle embeds manifest.json)
- SPEC.md restored from git (was truncated on disk)
- Docs topology aligned to actual code (cli.py, docs/, tests/)

## [1.1.1] - 2026-08-06

#### Added
- cli.py - hand plan <goal> CLI entry (--json/--model/--session)

#### Fixed
- engine.py: agent name plan -> build (opencode has no plan agent)
- agent.md: marked NOT auto-loaded by opencode
- PLAN-opencode.md: rewritten agent strategy

## [1.1.0] - 2026-08-05

#### Added - V6.1 planning layer
- hand/plan/ module - planning engine
- route_plan() - router planning route
- plan_trace - session planning trace
- hand_plan MCP tool
- tests/test_plan.py (15 cases)

#### Changed
- Version 1.0.0 -> 1.1.0 (V6.1.0)
- SPEC.md planning layer architecture

## [1.0.0] - 2026-08-04

#### Added
- Hand Kit v1.0.0 Grove release
- SPEC.md full module topology
- Docs system (SPEC/CHANGELOG/ROADMAP)

## [0.1.0] - 2026-07

#### Added
- Hand V6 unified framework prototype
- CDP, AX, OCR modules
- Session, Router

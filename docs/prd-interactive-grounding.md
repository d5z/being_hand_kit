# Interactive Grounding — See Map + Scroll

PRD - 2026-08-16 - Alice - Hand v6.6.0

---

## Motivation

Hand 的"眼"（see）现在只返回 `innerText` 纯文本。规划层能"读"页面，但不能"看见界面"——不知道哪些元素可交互、它们在哪里、用什么 selector 命中。

Hand 的"手"（do）只有 `click` 和 `type`。长页面无法滚动，下面的元素根本够不到。

2026 年 computer use 综述里的两条数据直接戳中现状：

| 路线 | 表现 | 根因 |
|---|---|---|
| DOM-only（Agent-E） | 静态站 95%，**动态站 27-35% 崩** | DOM 结构和视觉布局不匹配 |
| screenshot-only（Operator） | 复杂 JS 站 87% | vision 通用但 token 贵、小元素精度差 |

SOTA 的共识是 **hybrid（结构 + 坐标 grounding）**。本 PRD 补上 Hand 缺失的地基：让"眼"看见可交互元素地图，让"手"能滚动到长页面的任意位置。

## Goal

两个能力，对应三原语的两个通道：

| 原语 | 调用 | 返回 | 用途 |
|---|---|---|---|
| **see** | `see(INTERACTIVE)` | 可交互元素列表 `{role, text, selector, x, y, w, h}` | 看见界面哪里能点 |
| **do** | `do(scroll down)` | 滚动前后 scrollY | 够到长页面任意位置 |

## Design Principles

1. **感知与动作闭环**：see 返回的每个元素带稳定 selector，do 直接拿这个 selector 命中，不再靠文字猜测。这是本 PRD 的核心——打通 see→do 之间现在断裂的那一段。

2. **不做"最稳 selector 生成器"**：selector 用简单的 CSS 组合（id → name → 稳定的结构路径），不预先设计复杂的去重/稳定性算法。不稳定就在 dogfood 里暴露，再迭代。不越过真实，不提前。

3. **元素地图有上限**：页面可能有上千可交互元素，默认截断（200 个），优先可见、优先有文本。地图是"界面的骨架"，不是 DOM 全量导出。

4. **scroll 是真实滚动**：优先用 CDP `Input.dispatchMouseEvent`（mouseWheel），等价于用户滚轮，会触发懒加载/无限滚动；`window.scrollBy` 兜底。返回滚动前后 scrollY 验证是否真的动了。

## Foundation: 已有 CDP 底子

`cdp_core.py` 已经提供了 grounding 的全部地基，无需新协议：

| 现有函数 | 能力 |
|---|---|
| `_element_info(ws, selector)` | 单元素 `{x,y,w,h,visible,tag,text}`，用 `getBoundingClientRect` + dpr |
| `_scroll_into_view(ws, selector)` | 让单元素滚进视口 |
| `_get_dpr(ws)` | 设备像素比，坐标换算用 |

`cdp_snapshot.py` 的 `cdp_snapshot()` 现在只返回 innerText。本 PRD 是给它加一个 sibling 通道，复用同一套 WebSocket 连接管理。

## Implementation Path

### Part A: see(INTERACTIVE) — 元素地图

**Step 1**: `cdp_snapshot.py` 新增 `interactive_map(page_sel=None, max_elems=200)`。

- 连接 CDP，`_init_domains(ws, 'Runtime')`
- 用 `document.querySelectorAll` 枚举可交互元素：
  `a[href], button, input, textarea, select, [role="button"], [role="link"], [role="checkbox"], [role="tab"], [onclick], [tabindex]:not([tabindex="-1"])`
- 对每个元素取 `{tag, text, selector, x, y, w, h, visible}`，`getBoundingClientRect` + dpr（复用 `_element_info` 的逻辑，但批量）
- selector 生成优先级：`#id` → `[name=...]` → `tag[class 前缀]` → `tag:nth-of-type(n)`
- 排序：visible 优先 → 有文本优先 → 按 DOM 顺序
- 截断到 max_elems

**Step 2**: `router.py` 的 `SEE_PRIORITY[browser]` 已含 `cdp_network`，补 `cdp_interactive`。`route_see` 的 `kind` 分支加 `interactive`（复用刚修好的 kind 提前分发结构）。

**Step 3**: `kit/mcp_server.py` 的 `cdp_see(kind)` 已支持 kind 参数（v6.5.2 刚加的），无需改契约，kind 透传即可。

### Part B: do(scroll) — 滚动

**Step 4**: `cdp_act.py` 新增 `cdp_scroll(direction, amount=None, page_sel=None)`。

- `direction`: `down` / `up` / `top` / `bottom`
- `down/up`: 用 `Input.dispatchMouseEvent` 发 `mouseWheel`（deltaY ±），amount 默认一屏高
- `top/bottom`: `window.scrollTo(0, 0)` / `window.scrollTo(0, document.body.scrollHeight)`
- 记录滚动前后 `window.scrollY`，返回 `{method: cdp_scroll, direction, scrollY_before, scrollY_after, moved}`
- `moved=False` 时是"已经到底/到顶"的信号，不是错误——这个信号对规划层有用（避免无限重试）

**Step 5**: `router.py` 的 `DO_PRIORITY[browser]` 补 `cdp_scroll`。`route_do` 识别 `scroll` 意图。

**Step 6**: `kit/mcp_server.py` 加 `cdp_scroll(direction, amount)` MCP 工具。

## Acceptance Criteria

1. `see(INTERACTIVE)` 在 beings.town 首页返回元素列表，含 `a[href]` 和 `button` 项，每项有非空 `x/y/w/h`，且 selector 能直接被 `cdp_click` 命中（闭环）。
2. 元素地图尊重 max_elems 截断，visible 元素排在不可见元素前。
3. `do(scroll down)` 在长页面（如 Google 搜索结果）返回 `moved=True` 且 `scrollY_after > scrollY_before`。
4. `do(scroll bottom)` 到页底后再次 scroll 返回 `moved=False`（不报错，是信号）。
5. 三个 SOP 文档（SPEC / CHANGELOG / ROADMAP）闭合，版本号 v6.6.0 / 1.6.2。
6. dogfood：`open → see(INTERACTIVE) → click(地图里的 selector) → scroll → see` 全链路在 Linux CDP 跑通。

## Out of Scope

- **视觉兜底（vision on Linux）**：依赖外部 vision 模型，是上层能力，等本 PRD 跑通积累数据后再评估。
- **长程 state tracking（watch 模式）**：需多步截图/DOM diff 对比，同上。
- **drag / hover / zoom**：SOTA 承认的难点（Anthropic 自认 scrolling/dragging/zooming 是挑战），但 scroll 是地基，drag/zoom 依赖更复杂的坐标+状态机，后续单独 PRD。
- **selector 稳定性算法**：不做唯一性哈希、不做"最稳 selector 学习器"。简单 CSS 组合先跑，不稳定在 dogfood 暴露。
- **跨平台 grounding（macOS AX）**：本 PRD 只做 Linux CDP 浏览器，macOS 的 AX 树 grounding 是另一条感知后端，不混进来。

# 坐标桥 — do(xy) 打通眼→手

PRD - 2026-08-16 - Alice@beings.town

## 背景

操作线（do）当前只能按 CSS selector 或 `text=` 匹配点击。但感知线（see）的两条新路径都输出**坐标**：

- `see(INTERACTIVE)` 元素地图：每个元素返回 `{x, y, w, h}`（中心点）
- `vision_llm` fallback：视觉模型描述屏幕时天然会说"按钮在 (412, 188)"

眼看到了坐标，手接不住——还得绕回 DOM 找 selector。这是"视觉感知"和"操作执行"之间的裂缝。

## 目标

给手加一个**坐标点击**入口，让"眼看到什么坐标，手就能点什么坐标"。

## 核心设计：坐标契约（最重要的部分）

**所有 see 输出、所有 do 输入，统一使用"物理像素（CSS px × devicePixelRatio）"坐标系。**

已确认现状（代码级验证）：

1. `interactive_map` 返回：`x = (rect.left + rect.width/2) * dpr` —— 物理像素 ✓
2. `_element_info` 返回：同样 `* dpr` —— 物理像素 ✓
3. `cdp_click` 内部：`x_scaled = x / dpr` 再 dispatch —— 说明 CDP `Input.dispatchMouseEvent` 要的是 **CSS px（未乘 dpr）**

所以三者已经统一在"物理像素"这一层，`dispatchMouseEvent` 前统一 `÷dpr` 转 CSS px 即可。坐标桥只是把这段已有的转换抽出来，加一个直接入口。

**viewport 相对坐标天然对齐**：`getBoundingClientRect` 和 `dispatchMouseEvent` 都是相对于 viewport 的，不需要加减 `scrollX/scrollY`。

## 范围

### In scope

1. **`cdp_click_do` 识别坐标格式**：action 字符串支持 `xy:412,188`（与现有 `text=Learn more` 前缀风格对称）
   - 解析坐标 → 复用现有"÷dpr → dispatchMouseEvent"路径
   - 返回 `{method: 'cdp_click', xy: [x, y], page_index, result: 'ok'}`

2. **抽公共函数 `_click_at(ws, x, y, dpr)`**：把 `cdp_click` / `cdp_click_do(text=)` / `cdp_click_do(xy:)` 三处重复的"坐标→dispatch"逻辑收敛为一处，消除后续漂移

3. **坐标契约文档化**：在 `cdp_snapshot.py` 和 `cdp_act.py` 的 docstring 里写明"坐标 = 物理像素（×dpr），do 接收物理像素"——防止未来再出现 ×dpr / ÷dpr 方向搞反

### Out of scope（本次不做，先记录）

- `button` / `clickCount` 参数化（为 hover / 右键 / 双击留口，但不实现）
- hover、drag & drop、右键 context menu
- vision 模型返回坐标的**坐标系校准**（vision 看的是 viewport 截图则天然对齐；若未来给全页截图，需要减 scrollY——届时再处理）

## Acceptance Criteria

1. `cdp_click_do("xy:412,188")` 能在浏览器当前页面按该坐标完成一次真实鼠标点击（pressed + released）
2. 坐标语义与 `interactive_map` 输出一致：拿 `interactive_map` 里某个元素的 `{x, y}` 直接喂给 `cdp_click_do("xy:x,y")`，能点中那个元素（端到端闭环验证）
3. 三处点击路径（selector / text= / xy:）行为不回归，语法检查通过
4. 抽出的 `_click_at` 无重复逻辑，原有 `cdp_click` 改用它
5. docstring 写明坐标契约

## 验证方式

dogfood 闭环测试（浏览器导航到测试页）：
1. `route_see(kind="interactive")` 拿元素地图 → 取一个元素的 `{x, y}`
2. `cdp_click_do(f"xy:{x},{y}")` 点它
3. `route_see` 确认页面状态变化（点击生效）

## 风险

- **DPR 方向搞反**是历史高发坑（这次已确认现状是"输出×dpr、dispatch÷dpr"，契约文档化后应锁死）
- 坐标点击没有 selector 的"可见性检查 / scroll_into_view"兜底——点不可见元素会点空。本次接受此限制（坐标点击语义是"点屏幕上那个位置"，是否可见由调用方负责）；后续可在 `_click_at` 里加越界/负值校验

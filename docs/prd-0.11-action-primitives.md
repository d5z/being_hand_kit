# PRD — hand 0.11.0「动作原语与变化可判定」

_2026-10-20 · 触发：泽平要求用当前 substrate 深测 hand 与 computer use 能力，目标含「操作 Blender」_

## 为什么是这一版

Blender 是纯视觉域：3D 视口没有 DOM、没有 a11y、没有可查元素。hand 现有的三件武器（a11y 元数据 / selector 寻址 / 轮询重试）在那里**全部失效**，能用的只剩像素 + 坐标。而 0.10.0 的坐标路径只支持「点」——**点不了、拖不动、按不了组合键**，等于在纯视觉域里只有一根手指，没有手腕。

本版不追 Astra 的「更聪明」，只补三件地基：**能拖、能按组合键、动作结果能判定**。这是 Blender 目标的第一个可测子问题。

## F 层：事实（2026-10-20 实测，HeadlessChrome 151 / dpr 1 / 800×600）

| # | 事实 | 证据 |
|---|---|---|
| F1 | **无拖拽原语** | kit 13 工具无 drag；`cdp_act._click_at` 只发 pressed+released，无 moved。Excalidraw 选矩形工具后单击画布**不产生图形**；绕过 hand 直发 down→10×move→up，矩形立即画出（`/home/alice/hand-calib/drag_test.py`）。归因：页面支持，hand 缺 |
| F2 | **无修饰键** | 只能 `Input.insertText`。`Ctrl+Z`/`Shift+Click`/`Meta+箭头` 无一可达。Blender 的核心操作是 `G`/`R`/`S` + `X/Y/Z` + 数字，快捷键即语言 |
| F3 | **`box` 的 x/y 是中心，字段名暗示左上角** | geom.html：元素 BCR=(100,100,200,100)、中心 (200,150)；回执 `box:{x:200,y:150,w:200,h:100}`。同拍 `click_point:{how:"center",x:200,y:150}` 数值正确——**歧义在 box 的字段名，不在算术** |
| F4 | **三条寻址路径三种回执** | selector：只 `read_back:querySelector hit`，无 box/无 dispatched；handle：box+dispatched+click_point+in_viewport；xy：`verified:false,"dispatch-only"`。同一动作，三种可观测性 |
| F5 | **坐标无帧锚** | `cdp_shot` 回执只有 `img:<sha8>`+尺寸，无 scrollX/scrollY/zoom。实测踩中：拿滚动前的坐标点在滚动后的页面上 → 落空，回执 `ok`。跨拍坐标不可复现 |
| F6 | **`effected` 不可判** | 标定台点 `left:-9999px` 的按钮：`result:ok, verified:true`，世界未变（`OUT` 不变）。`verified` 验的是「元素找到 + 命中链」，不是「动作落地」 |
| F7 | **canvas 内容 a11y 覆盖率 0** | Excalidraw 有 27 个可访问节点（工具栏全可达），但画布本身只是一个 `Canvas ""`。形状画没画出来，元数据一概不知；DOM 侧漏只有 `Selected shape actions`（知道「有个东西被选中」，不知道是什么、在哪） |
| F8 | **a11y 坐标覆盖率 21%** | 标定台 19 节点，`coords_resolved:4`。div 假按钮、无 label 图标、canvas 全是 `x:null`。「元数据够用就不用截图」的前提必须先量覆盖率，不能假定 |

## S 层：修复（每项一个 commit，可独立回滚）

### S1 `cdp_drag(from, to, steps=10, interval_ms=16)`
- `from`/`to` 各支持 `xy:X,Y` 与 selector/`[idx]`（后者走 `_clickable_point` 求中心）
- 序列：`mousePressed(from)` → `steps` 次 `mouseMoved(buttons=1)` → `mouseReleased(to)`
- 回执：`from`/`to` 解析结果、`steps`、`dispatched_events`、`elapsed_ms`、**`landed`**（起点 `elementFromPoint` 是否命中 from 目标）、`element_at_end`（终点是谁）、帧锚
- **不报 verified=true**——拖拽无法从回执侧验证效果，`effected: unknown` + reason
- 失败模式必须显式：`from` 解析失败 / 起点不在视口 / 起点被遮挡（landed=false，仍派发但如实标注）

### S2 `cdp_key(keys)` 
- 语法：`"Control+z"`、`"Meta+Shift+t"`、`"Enter"`、`"Escape"`、`"ArrowLeft"`（`+` 连接修饰键，最后一个是主键）
- 修饰位掩码：Alt=1 / Ctrl=2 / Meta=4 / Shift=8（CDP `Input.dispatchKeyEvent` 约定）
- 序列：modifier keyDown → 主键 keyDown → 主键 keyUp → modifier keyUp（**修饰键不松手的语义**由 `cdp_key_hold`/`cdp_key_release` 另开销，本版只做组合键单发）
- 回执：`parsed{modifiers,key,code,vk}`、`dispatched_events`、`focused_before/after`（`document.activeElement` 标签）、`landed` 判定
- 同样不报 verified=true

### S3 回执三态（click / drag / key 统一）
在三个动作的回执里加**并列**的三段，取代单一 `verified`：

| 字段 | 含义 | 判定方式 | 成本 |
|---|---|---|---|
| `resolved` | 找到目标了吗 | selector 命中 / handle 有效 / 坐标在视口内 | 零（元数据） |
| `landed` | 动作送到它身上了吗 | `elementFromPoint(点)` 是目标或其后代 | 零（`Runtime.evaluate`） |
| `effected` | 世界变了吗 | **本版一律 `unknown`** + reason（`no_readback`） | — |

- `verified` 保留但**降级为 `resolved and landed`**，并在回执里写明这等价式（旧调用方不炸，新调用方能读真语义）
- `effected` 留到 0.12（需要帧 diff，属 data-gated）；**本版绝不假装**

### S4 帧锚（实现比原计划保守 — 偏差在此标注）
- `cdp_shot` 回执加 `frame: {scrollX, scrollY, viewport{w,h}, dpr}`（`img` 已在 `emitted` 里）
- `xy` 语法接受 `xy@img:<sha8>:X,Y`，`@` 前的帧引用解析后如实写进回执 `frame_ref`
- **未做跨帧校验**：本版不存历史帧台账，无法回查某张旧图拍摄时的 scroll 位置。回执显式写 `frame_verified: false` + `frame_reason: no_frame_ledger`，**不假装验证过**。"不一致就不派发"需要台账，推到 0.12
- 裸 `xy:X,Y` 行为不变（向后兼容），回执加 `frame`，让「我点的是哪一帧」可核

**S3 补充（实现时收紧）**：`landed` 只在"有目标可核对"时给 `true`。裸 `xy:` 源不声称任何元素，因此 **`landed` 永远为 `null`**，落点事实走 `element_at_start` / `element_at_point`。宁可说"判不了"，不给一个宽松的 `true`。

### S5 `box` 语义修正
- `box` 改为 `bounds: {left, top, right, bottom, width, height}`（真 BCR），新增 `center: {x, y}`（当前 box.x/y 的值）
- `box` 字段保留一版并标注 deprecated（同值，避免破坏调用方）

## L 层：验收

- **L1 单测**：drag 事件序列形状（pressed → N×moved → released，坐标单调收敛）、steps=0/1 边界、from 解析失败、key 解析（修饰键顺序无关、非法组合显式报错）、modifiers 位掩码、frame_stale 不派发、三态字段互斥性（`effected!=unknown` 必须带 evidence）
- **L2 回归**：`python3 tests/run_tests.py` 全绿（0.10.0 基线 497）
- **L3 真机**（我自己的机器，HeadlessChrome 151）：
  1. Excalidraw：`cdp_drag` 画出一个矩形（像素可见，尺寸与坐标一致）
  2. Excalidraw：`cdp_key("Control+z")` 撤销该矩形（像素可见消失）
  3. 标定台：屏幕外按钮 → `landed:false`（不再报绿）
  4. 帧锚：滚动前后用过期 `xy@img` → `frame_stale`，不派发
  5. geom.html：`bounds.left=100, center.x=200`（F3 修正可证）

## 不做什么（明确 out of scope）

- 帧 diff / `effected` 自动判定（0.12，data-gated）
- Astra / VLM 接入（substrate 的视觉定位能力由 substrate 自己做，hand 只负责「把坐标变成动作、把结果变成可判定的回执」）
- Blender 本体安装与操作验证（需要真显示器机器，下一轮）
- `cdp_key_hold`/`release`（长按语义，0.12）
- 多键序列 / 宏录制

## 一句话

**0.10 让 hand 不说自己不知道的事；0.11 让 hand 能做出更多事、并且说清每件事做到了哪一步。**

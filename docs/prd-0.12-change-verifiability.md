# PRD — hand 0.12.0「变化可判定」

_2026-10-20 · 触发：0.11 PRD 里写明「`effected` 留到 0.12（需要帧 diff，属 data-gated）；本版绝不假装」——本版就是那一版。08:0x 的长任务实测（Excalidraw 画 A→B 流程图，23 次调用 / ~15 拍）给出了数据。_

## 为什么是这一版

0.11 让 hand 有了手腕（drag / key），但每个动作回执都在同一句话上停住：

> `effected: unknown` — *"drag has no readback — verify the effect by comparing two frames, not by this receipt"*

hand 知道该怎么验，也诚实地告诉了调用方，**但它没替你做**。于是 15 拍的任务里，我手动截了 6 次图、手工比对，靠自己的眼睛补上了 hand 缺的那一环。

0.12 把这一环装回 hand：**动作说完「我发出了」之后，再多说一句「我看到它变了没有」。**

## F 层：事实（2026-10-20 实测，HeadlessChrome / dpr 1 / 800×600 / Excalidraw）

| # | 事实 | 证据 |
|---|---|---|
| F1 | **静止页面帧差分零噪声** | 不操作、间隔 800ms 连抓两帧：`changed=0, ratio=0.000000`。基线干净到可以做「没变」的强判定 |
| F2 | **变化量大 ≠ 动作对** | 点画布空白（取消选中）：`changed=5930, ratio=0.0124, bbox=[14,67,609,420]`。数字不小，但它证明的是「选中框消失了」，不是「点击成功了」 |
| F3 | **单一变化量无法归因** | 画一个 130×80 矩形：`changed=6745`；从「取消选中」帧再算：`changed=8146`。同一个动作，取决于跟哪帧比，差 1400 像素。没有区域限定，diff 只能当参考不能当判据 |
| F4 | **全屏 diff 纯 Python 约 0.9s** | 4 次全屏 diff 共 4.22s（含抓帧）。产品化必须靠**区域限定**或采样，不能全屏硬比 |
| F5 | **hand 已经知道正确验法** | 三条回执的 `effected_reason` 分别写 `no_readback` / "compare two frames" / "observe the page" —— 缺的不是知识，是执行 |
| F6 | **readback 存在性极不均衡** | `type`: `verified:true`（`before:"" → after:"Step B"`）；`key(Enter)`: 只有 `focus_before:DIV → focus_after:TEXTAREA`；`click`/`drag`: 零 readback。同一个 hand，四种可观测性 |

## S 层：修复（每项一个 commit，可独立回滚）

### S1 `frame_diff(before, after, region=None, ch_delta=12)` — 差分原语
- 输入：两个 PNG（bytes 或 b64）
- `region`: `{x,y,w,h}` —— 只比这一块；缺省全屏
- 返回：`{comparable, changed, total, ratio, bbox}`
- **不可比必须显式**：尺寸/通道数不一致 → `{comparable:false, why:"geometry 800x600x4 vs 800x600x3"}`。**绝不把不可比算成「没变化」**
- `ch_delta`：每通道容忍差（默认 12，来自实测：静止帧 0 差异，真实变化远超）

### S2 预期变化区域（expect region）—— 每个动作自带
| 动作 | expect region |
|---|---|
| `click` | 点击点为中心、边长 `EXPECT_R`（默认 120）的正方形，裁剪到视口 |
| `drag` | 起止点 bbox 外扩 `EXPECT_PAD`（默认 24） |
| `key` | 焦点元素 bbox；无焦点元素 → 全屏（并如实标注 `region:"fullscreen"`） |

区域的作用是**把 F2/F3 的歧义挡在门外**：只问「我预期变的地方变了吗」，不问「整页变了吗」。

### S3 动作级自动 diff → `effected` 落地
动作序列：抓 before 帧 → 派发 → `wait_stable` → 抓 after 帧 → 只 diff expect region。

`effected` 三态（保留 0.11 的 `unknown`，新增两个可判定值）：

| 值 | 条件 | 含义 |
|---|---|---|
| `changed` | region 内 `ratio > EFFECT_THRESHOLD` | 预期区域真的变了 |
| `no_change` | region 内 `ratio <= threshold` **且两帧可比** | 预期区域没变——动作很可能没生效 |
| `unknown` | 抓帧失败 / 不可比 / 页面未静止 | 判不了，不猜 |

回执新增 `change` 块：`{region, changed, total, ratio, bbox, threshold, comparable}`。

**同时报全屏 bbox**（不判、只给）：当 region 内 `no_change` 而全屏 `bbox` 落在 region 之外时，调用方一眼能看出「我以为点这里，结果变在别处」——0.9.4 那批「回执绿、任务死」的根因就是它，只是当时看不见。

### S4 `wait_stable(timeout_ms=800, quiet_ms=120)` — 抓帧前等静止
- 连续两帧 diff 低于 `STABLE_THRESHOLD` 才算静止
- 超时 → `{stable:false, waited_ms}`，随后的 diff 标 `unknown`（**不拿动画帧当判据**）
- 纯静态页面（F1 那种）几乎零成本：两帧即可返回

### S5 默认开、可关
- `verify=True` 为默认：0.12 的核心价值就是这个，默认关掉等于没做
- `verify=False` 保留旧行为（零额外抓帧，`effected:"unknown"`），给高频批处理路径
- 单次动作成本预算：区域 diff 应 < 80ms（对比全屏 0.9s）

### S6 不倒退
- `verified` 语义不变（仍是 `resolved and landed`），0.11 调用方不受影响
- `effected` 从 `"unknown"` 变成可判定值是**信息增加**，不是语义变更
- `effect_reason` 保留：`no_change` 时写清「两帧可比、区域无变化」，`unknown` 时写清卡在哪一步

## L 层：验收（每条都要有反例）

| # | 场景 | 期望 |
|---|---|---|
| L1 | 无选中状态下点画布死区 | `effected:"no_change"` —— **这是真负样本**，0.11 做不到 |
| L2 | 点矩形工具后拖一个矩形 | `effected:"changed"`，`bbox` 落在拖拽区域内 |
| L3 | 点 A 处、变化发生在 B 处 | `effected:"changed"` 但 region 内 `no_change` + 全屏 bbox 在 region 外 → 报告两边，让人看出点歪了 |
| L4 | 抓帧失败 / 页面持续动画 | `effected:"unknown"` + 具体原因。**任何路径都不得返回 `no_change`** |
| L5 | 静止页面连续 20 次 click | 20 次 `no_change`，零误报（F1 保证了这一点） |
| L6 | `verify=False` | 回执与 0.11 逐字一致 |

## 不做什么（明确 out of scope）

- **不做 OCR diff**：文字变化已由 `type` 的 readback 覆盖；`ocr_diff.py` 留给需要「读懂了什么」的场景（0.13+）
- **不做语义判断**：不回答「这个按钮变红了吗」。0.12 只回答「这块像素变了吗」，语义需要 `cdp_read(region)`（0.13）
- **不引 numpy**：保持纯 stdlib。性能靠区域限定解决，不靠换依赖
- **不改 `verified` 的旧语义**：0.11 的调用方不该被这一版弄坏

## 一句话

**0.11 说「我发出了，你去看两帧」。0.12 说「我看过了，这是两帧的差别」——包括我什么都没看见的时候。**

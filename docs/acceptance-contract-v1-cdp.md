# 感知契约 v1 验收记录 — cdp 路径闭环

日期：2026-09-01 00:55 CST
验收人：Alice
实现 commit：2bf8ccf（feat(hand): perception contract v1 — cdp 坐标元信息）
实现者：触手 contract-cdp（49a43a79）

## 验收项与结果

| # | 验收项 | 方法 | 结果 |
|---|--------|------|------|
| 1 | 坐标元数据块 | 实跑 interactive_map，检查 coord 字段 | ✅ `{"space":"physical","dpr":1,"viewport":{"w":785,"h":600},"image":{"w":785,"h":600,"scale":1.0}}` |
| 2 | 全量测试 | python3 tests/run_tests.py | ✅ 60 tests OK（含 test_cdp_contract.py 88 行专项） |
| 3 | 滚动坐标保真 | see → scroll → see，比对 y 差值 | ✅ 1318.53 → 718.53 → 518.53，差值 = scrollY 增量，零漂移 |
| 4 | see→do(xy) 闭环 | 取元素中心物理坐标 (199,526) → cdp_click | ✅ URL beings.town → beings.town/grove，标题变 Kit Grove，落点精确无误触 |

## 验收 SOP（see→do 坐标闭环，可复用）

1. `hand_cdp_open(url)` 打开目标页
2. `hand_cdp_see(kind="interactive")` 拿 interactive_map，记录目标元素 (x, y, w, h)
3. 若元素超出视口：`hand_cdp_scroll` 后重新 see，验证坐标差值 == scrollY 增量（保真检查）
4. 计算元素中心：`cx = x + w/2`（取整），`cy = y + h/2`
5. `hand_cdp_click selector="xy:cx,cy"` 用物理坐标点击
6. 独立验证落点：`hand_cdp_see(kind="dom")` 检查 URL/标题变化是否与目标元素语义一致
7. 通过标准：落点语义正确 + 全程坐标无漂移

## 边界与备注

- 当前验证环境 dpr=1，scale=1.0（基准情形）。scale≠1 的 Retina 场景是契约真正显威处，待验证。
- interactive_map 返回 0 元素时（空白页）coord 块仍正常输出——元数据与内容解耦，符合设计。
- 验收现场自指：用 hand 验证 hand 的感知契约，落点页面恰好是 Grove 上的 hand kit 页。

## 下一步（第二步候选）

- dpr≠1 场景验证（需 Retina 环境或 CDP deviceMetricsOverride 模拟）
- ax / vision 路径的同类契约
- 坐标-场景图沉淀 → 空间记忆建模（泽平直觉：fundamental 范式，类似具身智能，可能反推 heart 空间记忆）

---

# 第五层：being 侧自证（交付到达层）— hand 0.10 D4

日期：2026-10-18
实现：`hand/perception/eye_check.py` + MCP 工具 `hand_eye_check`
PRD：`docs/prd-delivery-honesty.md` §D4

## 为什么需要第五层（前四层测不到它）

| 层 | 验的是 |
|---|---|
| CI mock | 代码路径 |
| Linux 真机 | 工具行为 |
| 平台人工 | 页面看起来对不对 |
| 0.9 visual_state | 工具对页面状态的判读 |
| **第五层：being 自证** | **像素有没有到达调用方的 context** |

前四层全在验**工具的行为对不对**。没有一层在验**感知有没有到达**。而这一层有个
特殊性质：**外部判不了**——只有 being 自己能说"图像进没进我的 context"。

**此层只能由 being 侧执行。** 人、CI、另一个 being 都不能代跑：别处跑出来的 pass
只证明"这个装置在一台有眼睛的机器上能跑通"，不证明"画面上那串字到了谁的 context"。

## 判定 SOP

1. `hand_eye_check(op="challenge")` → 回执只给 `challenge_id / place / expires_at`
   （串不进回执、不进 DOM、不进 title、不进页面源）
2. 用你自己的视觉通道看一眼当前页面：`hand_cdp_shot`（或 `hand_see_vlm`）
3. `hand_eye_check(op="verify", challenge_id=..., answer="<你看到的>")`
4. 通过：`pass: true` + `elapsed_ms`。失败：`reason=mismatch / expired / unknown-challenge`

## 三条不可省的约束

1. **canvas 渲染**：串只存在于像素里。DOM `innerText` 是空串，`cdp_see(kind=dom)`
   读不到——这是"必须真看见"的机制保证，不是风格选择。
2. **出题/判卷分离**：工具不知道你能不能看见，只判字面对不对。8 字符 × 31 符号
   ≈ 1/8.5e11 盲猜通过率——不可猜是这个装置成立的前提。
3. **无视觉必须 fail**：一个永远 pass 的自证工具是废物。空渲染/无墨帧直接拒发题
   （`challenge not rendered`），错答一律 `mismatch`。

## 2026-10-18 实机验收（HeadlessChrome 151，640×160 canvas，48px）

```
DOM innerText = ''            DOM title = 'eye check'
DOM canvas_count = 1          DOM canvas_px = '640x160'
RECEIPT_HAS_STRING = False    PAGE_SOURCE_HAS_STRING = False
evidence.ink_ratio = 0.03849  (14629 samples)
读图 → XRADEJDH → verify pass:true, elapsed_ms:10011
```

474 tests 全绿（`tests/test_eye_check.py` 17 枚：回执/页面源不含串、canvas 渲染、
未渲染拒发题、形近替换 fail、单次有效、过期区分、list 不打印串）。

## 已知边界

- 字母表排除 `O 0 I 1 L`：这道题问"像素到了没有"，不问"字体好不好认"。把判读难度
  顶到边界会把交付测试变成视力测试，对诚实的 being 产生假失败。严格匹配不打折。
- challenge 状态是进程内内存（单次、短命）。MCP server 重启后未 verify 的 challenge
  失效——正确行为（宁可 unknown 不猜）。
- 每次 `op=challenge` 会把浏览器导航到新页面（`route_open`），调用方之后的页面状态变了。
- 尚未接进 Grove 上报（那是 D6，data-gated 等 Judy 线）。

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

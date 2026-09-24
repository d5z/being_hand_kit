# Spec 0.9.3-P0 · 点击视口对齐（viewport alignment）

状态：待实现
来源：2026-09-24 dogfooding 实测（GitHub issues 多步任务），根因已实证复现
优先级：P0（静默错家族——回执 ok 但点击物理丢失）

## 根因（实证链，非推测）

1. GitHub 等站点 CSS `html { scroll-behavior: smooth }`（实测确认）
2. `scrollIntoView({block:'center'})` 不带 `behavior` → 继承 smooth → **异步动画**
3. `_handle_rect` 在同一 JS 表达式里紧跟 `getBoundingClientRect()` → **读到动画开始前的坐标**（元素可能仍在视口外）
4. `_click_at` 把点击派发到视口外物理坐标 → `Input.dispatchMouseEvent` 事件无目标 → **静默丢失**
5. 回执 `verified=true`——元素存在、rect 读取、派发完成都是事实，但「点击命中元素」这个隐含断言是假的

实测数据（GitHub issues 页，2026-09-24）：
- click [222] 回执 box y=687 > 视口高 600，dispatched (520, 688)，页面无反应
- probe: `scrollIntoView` 调用后同步读 scrollY 不变（动画未开始）；`behavior:'instant'` 后立即滚动到位（800→388）
- `Element.prototype.scrollIntoView` 是 native code（未被页面重写）

## 修法（三处，全部精确到函数）

### M1 — instant 滚动（主修，一行）

文件：`hand/action/cdp_act.py`，函数 `_handle_rect`：

```python
# 现在
scroll_js = "this.scrollIntoView({block:'center',inline:'center'});"
# 改为
scroll_js = "this.scrollIntoView({block:'center',inline:'center',behavior:'instant'});"
```

理由：消除 smooth 异步窗口，滚动在 JS 表达式返回前完成，后续 rect 读取即真实落点。

### M2 — 落点视口检查 + 回执新字段（防滚动锁定）

文件：`hand/action/cdp_act.py`，函数 `cdp_click_handle`。

在 `rect = _handle_rect(ws, oid)` 之后、`_click_at` 之前，读视口尺寸并检查落点（rect 的 x/y 是中心点 CSS px）：

```python
vp = cdp_call(ws, "Runtime.evaluate",
              {"expression": "JSON.stringify({w: window.innerWidth, h: window.innerHeight})"},
              msg_id=33, timeout=5)
viewport = json.loads((vp or {}).get("result", {}).get("value") or "{}")
vw, vh = viewport.get("w", 0), viewport.get("h", 0)
in_viewport = (0 <= rect["x"] < vw) and (0 <= rect["y"] < vh)
if not in_viewport:
    return _handle_fail(
        f'handle [{entry["idx"]}] click point ({rect["x"]:.0f},{rect["y"]:.0f}) '
        f'is outside viewport ({vw}x{vh}) — scroll did not take effect',
        entry=entry, handle=str(handle))
```

成功回执 evidence 增加两个字段（与既有 box/space/dpr 平级）：

```python
"viewport": {"w": vw, "h": vh},   # CSS px
"in_viewport": True,
```

注意：**只改 click 路径**。`cdp_type_handle` 同用 `_handle_rect` 但 focus 不依赖物理位置，不加检查（M1 的 instant 对它自动生效，有益无害）。

### M3 — CSS tier 同修

文件：`hand/perception/cdp_core.py`，函数 `_scroll_into_view`：

```python
# 现在
.scrollIntoView({block:"center"})
# 改为
.scrollIntoView({block:"center",behavior:"instant"})
```

理由：CSS tier 靠 `time.sleep(0.2)` + `_js_click` 兜底掩盖了同一问题，但物理点击那一下同样会落空。sleep(0.2) 与 JS click 兜底**保留不动**（懒加载页面需要缓冲），只修滚动语义。

## 测试

### T1 — 新文件 `tests/test_viewport_alignment.py`

两个本地 HTML fixture（内联字符串或 tests/fixtures/ 下文件）：

- **fixture A（plain）**：高列表页（视口 600，元素在 ~1500px 处），目标元素带 `onclick` 计数器
- **fixture B（smooth）**：同 A，但 `html { scroll-behavior: smooth }`——复现 GitHub 条件

用例：
1. `test_click_handle_outside_viewport_plain`：元素在视口外，click handle → 计数器=1，回执 `evidence.in_viewport == True`
2. `test_click_handle_outside_viewport_smooth`：**核心回归**——同 1 但 smooth 页面
3. `test_click_receipt_has_viewport_fields`：成功回执含 `evidence.viewport = {"w": …, "h": …}`
4. `test_click_viewport_locked_fails_loudly`：滚动锁定场景（如 `html { overflow: hidden }` + 元素在视口外）→ 返回 verified=false，reason 含 "outside viewport"，计数器=0

fixture 通过本地 HTTP 服务或 `file://` 加载（headless Chrome 打开），复用 tests/ 里现有的 CDP 测试基建（参考 test_ax_see.py / test_receipt_contract.py 的做法）。

### T2 — 回执契约

`tests/test_receipt_contract.py` 增补：cdp_click_handle 成功回执必须含 in_viewport/viewport 字段（若该文件按方法枚举契约，把新字段加进 handle 路径的契约清单）。

## 验收（外部证据，非口头）

1. `python3 tests/run_tests.py` 全绿（含 T1 四个新用例）
2. 手动 dogfood 回归（我来做，不派触手）：GitHub issues 页滚动到列表中部，click handle 视口外元素 → 一次命中，页面导航成功
3. 回执示例贴回：in_viewport/viewport 字段在场

## 边界（明确不做）

- 不动 4-tier 的 `_js_click`/`_js_focus_enter`/`_js_submit` 兜底链
- 不动 cdp_type 输入路径的回执
- 不做交集 clamp（box∩viewport 中心）——留待真实场景证明需要后再加
- dpr 语义不变：rect 是 CSS px，dispatched 是物理 px，检查用 CSS px 对 innerWidth/innerHeight

## 关联

- P1 handle 漂移（backendNodeId 失效后 [idx] 重排）→ 另立 spec
- P2 text= 匹配失败 → 另立 spec
- P3 Enter 不提交 → 另立 spec

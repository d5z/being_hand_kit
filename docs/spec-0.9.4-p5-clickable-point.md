# Spec 0.9.4-P5 · clickable point 预检（elementFromPoint 命中链）

状态：已实现（bcc672d，随 0.9.4 发布）——三条路径全接入（text= 内联命中链 / handle `_clickable_point` / P4 重定向 verified point），陷阱 fixture `tests/test_clickable_point.py`（415 全绿含多行 link 行为断言）。本文件保留设计依据，状态行 2026-09-24 补记。
来源：2026-09-24 P4 现场回归在 GitHub 真实页面失败（重定向回执 ok 但导航没发生）

## 现象

GitHub issues 列表，heading 包 link（P4 重定向场景）：
- `cdp_click [257]`（heading handle）→ 回执 `redirected: true`，`redirect_target_href: /microsoft/vscode/issues/337206`，`nav_id_at_action: 1`——一切看起来对
- 但 URL 不变，导航没发生

## 根因（实证钉死）

标题 link 是 `display: inline` 的 3-4 行文本。`getBoundingClientRect` 返回 224×137 的**包围盒**，但 inline 元素跨行时，行间隙不属于元素本身——中心点 (425, 300) 的 `elementsFromPoint` 堆栈是 `[DIV.Title-module__container, LI, DIV.IssueRow, ...]`，**没有 link**（link 的 pointerEvents 是 auto，display 是 inline）。

坐标派发 `Input.dispatchMouseEvent` 走浏览器 hit-test：点击落在容器 DIV 上，click 事件 target 链没有 `<a>`，浏览器不做默认导航。

对照组：CSS selector 点击（`a[href*="337206"]`）走 `_js_click` → `el.click()`——JS 直接在元素上派发 click，**不经过 hit-test**，所以能导航。

**结论：`getBoundingClientRect` 的包围盒中心 ≠ 元素的 hit-test 区域。对 inline 多行元素，中心点可能落在行间隙。**

受影响路径（全部是坐标派发）：
1. `text=` 点击——XPath 找到元素后取 box 中心
2. handle 点击——handle map 的 box 中心
3. P4 重定向——候选 link 的 box 中心

## 修法

派发前用 `elementFromPoint` 验证命中链，不中则网格扫描：

```js
function findClickablePoint(el) {
  var r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  function hits(x, y) {
    var e = document.elementFromPoint(x, y);
    return !!(e && (e === el || el.contains(e)));
  }
  var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  if (hits(cx, cy)) return [cx, cy, "center"];
  for (var yi = 1; yi <= 15; yi++) {
    for (var xi = 1; xi <= 5; xi++) {
      var x = r.left + r.width * xi / 6;
      var y = r.top + r.height * yi / 16;
      if (hits(x, y)) return [x, y, "grid_scan"];
    }
  }
  return null;  // 完全被覆盖或不可命中
}
```

命中链条件：`e === el || el.contains(e)`（命中元素自己或其后代）。命中**祖先不算**——那正是现在的 bug。

### 三条路径接入

1. **text= 分支**：XPath 命中后跑 findClickablePoint；返回 null → 失败回执 `element has no clickable point (covered or zero-size)`
2. **handle 点击**：`_handle_rect` 取到 box 后，对目标元素跑 findClickablePoint；null → 响亮失败
3. **P4 重定向**：候选 link 的点击点用 findClickablePoint 的结果

### 回执

`evidence.click_point = {how: "center" | "grid_scan"}`——声明用的哪个点。grid_scan 意味着元素是 inline 多行或部分覆盖，这个信息对使用者有价值。

## 测试

fixture 造陷阱：外层容器比内层 inline link 大很多，link 中心落在间隙（复刻 GitHub 结构）。断言：
1. 危险条件存在：elementFromPoint(link 中心) 不是 link（控制实验，证明旧路径必输）
2. 新路径：text= / handle / 重定向点击后 linkClicks == 1（行为真的发生）
3. 完全覆盖 case：findClickablePoint 返回 null → 失败回执诚实

## 边界

- 网格扫描 75 点 × elementFromPoint，JS 内执行，微秒级/点，无性能顾虑
- elementFromPoint 需要 CSS px（viewport 坐标）；返回点转 physical px（× dpr）再进 `_click_at`（它内部除回 CSS px——保持现有接口）

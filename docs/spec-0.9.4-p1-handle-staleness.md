# Spec 0.9.4-P1 · handle 表过期信号（stale detection）

状态：**定稿——待实现**（2026-09-24 泽平授权「有把握的都进 0.9.4」；三个设计悬点已由 alice 拍定，见下）
来源：2026-09-24 dogfooding 观察 + 0.9 review 悬账「stale 检测」
优先级：P1（可靠性——0.9 已有失效兜底，缺的是前置信号）

## 现状（已有的保护，先说清楚）

`cdp_click_handle` / `cdp_type_handle` 对失效 handle 已有两层检测（0.9 已落）：

1. `DOM.resolveNode` 失败 → 回执 "element is gone (backendNodeId … does not resolve) — call cdp_see again"
2. rect 为 None（display:none / zero-size / detached）→ 回执 "element has no box"

backendNodeId 是 DOM 节点身份：节点被替换后 id 失效，**不会误指向新节点**。所以「点了错的元素」不会发生——这是可靠底线。

## 缺口（今天实测的摩擦）

1. **过期信号只在失败时出现**：handle 表是 see 时刻的快照。页面重渲染后旧表作废，但用户（being）不知道——每次用 handle 都在赌，输了浪费一轮点击 + 一次来回
2. **跨 see 编号不稳定**：同页重渲染后重新 see，[idx] 编号重排（今天实测：text= 失败后重新 see，[221]→[223]）。用户无法区分「页面变了」和「我记错了」
3. **navigation 后无提示**：整页导航后旧表全灭，但没有任何信号说「你手里的表是上个页面的」

## 修法（提案，三件事）

### M1 — see 回执带导航锚

`cdp_see(kind=a11y)` 回执顶层加：

```json
"nav_id": <Page.getNavigationHistory 的 currentEntry index>
```

同时 handle map 文件（/tmp/hand_ax_handles.json）记录 see 时刻的 nav_id——它是浏览器侧状态，跨 MCP 进程稳定，是唯一可靠的比对锚。

### M2 — click/type handle 回执带动作时锚 + 偏离警告

`cdp_click_handle` / `cdp_type_handle` 回执 evidence 加 `nav_id_at_action`。与 handle map 里存的 see 时刻 nav_id 不一致时，evidence 加：

```json
"warnings": ["navigation occurred since last cdp_see — handle table may be stale"]
```

（warning 进返回值 = 0.9 review 悬账之一，此处一并落。）

### M3 — 文档化边界（不做的部分）

同页局部重渲染**不做预检**（成本：每次 handle 操作前全树对比）。靠已有 resolveNode 失败兜底。README/CHANGELOG 明说：handle 的可靠性合同 = 「要么点对，要么显式失败」，不是「永远不失败」。

## 设计定夺记录（2026-09-24，alice 拍）

1. **warning 放 evidence 层**，不进回执顶层——与 0.9.3 的 in_viewport/viewport 字段一致（evidence 是回执的「检查声明区」，warning 是检查产出）；顶层加字段对下游 schema 破坏更大。Judy 反哺的「warning 进返回值」验收项由 evidence.warnings 满足（evidence 是返回值子结构）。
2. **tree_epoch 砍掉**——MCP server 每次工具调用可能是新进程（lazy spawn），进程内自增 epoch 跨进程无意义，反而引入「epoch 不匹配但表其实有效」的误报。nav_id 是浏览器侧状态，跨进程稳定，单独承担锚定职责。
3. **expect 断言语法不加**——nav_id 是被动信号（回执自动带），不是主动断言目标；用户不需要写 expect="nav_id:…"，偏离时 warning 自动出现。

## 测试（实现后）

1. `test_see_receipt_has_nav_anchor`：a11y see 回执含 nav_id/tree_epoch
2. `test_click_after_navigation_warns`：see → nav 到新页 → click 旧 handle → 回执含 stale warning（且失败，不是误点）
3. `test_click_same_page_no_warning`：see → click（无导航）→ 无 warning

## 验收

run_tests.py 全绿 + dogfood：GitHub issues 页 see → 点开 issue（navigation）→ 回头点旧 handle → 收到 warning 而非静默。

## 关联

- 0.9 review 三笔悬账：warning 进返回值（M2 一并落）、stale 检测（本 spec 主体）、fallback 不静默（Judy PR #1 同族，另线）

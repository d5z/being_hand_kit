# Spec 0.9.4-P4 · heading 包 link 的点击重定向（interactive 后代）

状态：待实现
来源：2026-09-24 dogfooding 实测（GitHub issues 列表），根因已实证
优先级：P4（可用性——常见「标题包链接」结构下，点标题靠巧合命中）

## 根因（实证链）

GitHub issues 列表结构（2026-09-24 probe 确认）：

```html
<h3><a href="/microsoft/vscode/issues/33760…">标题文字</a></h3>
```

- AX 树暴露**两个节点**：heading [222]（interactive: false）+ link [223]（interactive: true）
- heading 有 name，不满足 collapse 条件（collapse 只吃 nameless generic），link 是 interactive 不会被吃——两个都独立成行
- 用户（being）看 a11y 树时，heading 是视觉上最显眼的标题行，自然点它
- 实测：点 [222]（heading）成功——**纯属巧合**：link 是 heading 的唯一内容，heading rect 覆盖 link rect，中心点落在 link 上
- 巧合不保证：heading 有多个子元素（如带 meta 前缀）时，heading 中心可能落在非 link 区域 → 静默丢失（同 P0 家族）

## 修法（两层）

### M1 — meta 加 `contains_interactive`（树层面声明）

`ax_tree.py` `_traverse`：遍历时记录每个节点的子树是否含 interactive 后代。实现：后序传播——子节点 meta 生成后，向上传播 interactive 标记到所有祖先。meta 加：

```json
"contains_interactive": true
```

（仅 true 时带，false 省略——减噪。）

### M2 — click 非 interactive handle 时重定向（行为层接住意图）

`cdp_click_handle`（cdp_act.py）：拿到 handle 的 backend_node_id 后，若 AX meta 显示该节点非 interactive 且 `contains_interactive: true`：

1. DOM 查询该节点的 interactive 后代：`querySelectorAll('a, button, [role], input, select, textarea')` 中取 AX interactive 的（简化：a/button/input/select/textarea + role 属性非空）
2. **唯一后代** → 点击重定向到它。回执 evidence 加：

```json
"redirected": true,
"original": "heading \"标题…\"",
"redirect_target": "link \"标题…\""
```

3. **多个后代** → 不猜。失败回执列 candidates（tag + text 前 80 字符 + href 若有，前 3 个）——同 P2 的诊断模式
4. **零后代**（contains_interactive 过期）→ 走现有失败路径

### 不做的部分

- 不改 a11y 树的行格式（heading/link 双行保留——树如实反映 AX 结构，行为层负责接住意图）
- 不重定向 type（输入目标歧义更大：点 heading 想输入的场景不存在）

## 测试（tests/test_click_redirect.py）

fixture：`<h3><a>Nested Heading Link</a></h3>`、`<div><a>One</a><a>Two</a></div>`、`<h3>Plain Heading</h3>`

1. `test_click_heading_redirects_to_link`：点 heading handle → 点击落在 link 上（link 的 click 计数器 +1），回执 redirected: true
2. `test_click_container_multiple_interactive_fails_with_candidates`：点含两个 link 的容器 → 失败，candidates 列出两个
3. `test_click_plain_heading_no_redirect`：点无 interactive 后代的 heading → 正常点击（无 redirected 字段）
4. `test_meta_contains_interactive_flag`：serialize 后 heading 的 meta contains_interactive: true，普通文本节点无此字段

## 验收

1. run_tests.py 全绿
2. dogfood 回归：GitHub issues 页点 heading [222] → 回执 redirected: true，issue 打开

## 边界

- 重定向只认 AX interactive 后代，不认「任意可点元素」（onclick 内联不在范围）
- redirected 回执不静默：original + target 都写明，用户可核对意图是否被正确接住

# Spec 0.9.4-P2 · text= 匹配修复（嵌套文本）

状态：待实现
来源：2026-09-24 dogfooding 实测（GitHub issues 页），根因已实证复现
优先级：P2（可用性缺陷——常见站点结构下 text= 完全失效，把用户逼到 CSS 选择器）

## 根因（实证链）

`cdp_click_do` 的 text= 路径（cdp_act.py:432-457）XPath：

```
//a[contains(text(),"q")]|//button[contains(text(),"q")]|//*[text()="q"]
```

1. `text()` 只匹配**直接文本子节点**。GitHub 等站点链接文字在嵌套子元素里（`<a><span>标题</span></a>`），`<a>` 的直接文本子节点为空 → contains 永远 miss
2. 第三支 `//*[text()="q"]` 是精确匹配，前缀查询 miss
3. 实测（2026-09-24，GitHub issues 搜索结果页）：
   - `//a[contains(text(),"Screen reader announces the same table name")]` → **false**
   - `//a[contains(.,"…")]` → **true**，命中 `/microsoft/vscode/issues/337206`
   - 命中节点的直接文本子节点实测为 **empty**——文字全在嵌套子元素

当天后果：text= 点击失败 → 被迫重新 see a11y + python 解析 handle 表 + 换 CSS 选择器，四步才点开一个 issue。

## 修法

文件：`hand/action/cdp_act.py`，函数 `cdp_click_do` 的 text= 分支。

XPath 三支改为：

```
//a[contains(normalize-space(.),"q")]|//button[contains(normalize-space(.),"q")]|//*[normalize-space(.)="q"]
```

- `.` = 节点完整字符串值（含所有后代文本），嵌套结构命中
- `normalize-space()` 折叠空白差异
- 第三支保留精确语义（`=`），作为「全文本精确匹配」的兜底

### 失败回执增强（诊断性）

找不到时，追加一次宽松扫描：遍历 `//a|//button`，取 `innerText` 包含 q 的前 3 个，作为 `candidates` 返回（tag + text 前 80 字符 + href 若有）。空列表则 candidates: []。这让「为什么 not found」从猜测变成可诊断。

## 测试（tests/test_text_match.py）

fixture：`<a><span>Nested Target</span></a>`、`<button><em>Deep Button</em></button>`、`<a href="#">Plain Link</a>`

1. `test_text_match_nested_span`：text=Nested Target → 命中（旧实现 miss——核心回归）
2. `test_text_match_prefix`：text=Plain → 命中（contains 语义）
3. `test_text_match_exact_branch`：text=Plain Link → 命中（第三支）
4. `test_text_match_not_found_returns_candidates`：text=不存在 → verified=false，candidates 列出页面上相近链接
5. `test_text_match_case_sensitive`：text=plain link（小写）→ 不命中（XPath contains 大小写敏感，保持）

## 验收

1. run_tests.py 全绿
2. dogfood 回归：GitHub issues 页 text=Screen reader announces → 一次命中 337206

## 边界

- 不改 text= 的大小写语义（敏感）
- 不加 text~= 正则变体——真实需求出现再说
- candidates 只做 a/button 两类（click 的语义域）

## 关联

- Judy PR #1 的 find_text 静默 fallback 同属「静默错家族」——P2 修的是「找不到」，Judy 修的是「找到了但不是那个」，0.9.4 一并收

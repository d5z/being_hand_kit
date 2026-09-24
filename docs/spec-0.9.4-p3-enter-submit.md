# Spec 0.9.4-P3 · Enter 提交修复（键盘事件 vs 文本插入）

状态：待实现
来源：2026-09-24 dogfooding 实测（GitHub issues 搜索框），根因已实证复现
优先级：P3（可用性缺陷——搜索/提交场景全灭，被迫手拼 URL）

## 根因（实证链）

`cdp_type` / `cdp_type_handle` / `cdp_type_focused` 的输入循环：

```python
for char in text:
    cdp_call(ws, "Input.insertText", {"text": char})
```

1. `Input.insertText` 是**文本插入**，不产生任何 KeyboardEvent
2. text 含 `"\n"` 时，换行符作为文本进 input——单行 input 里被忽略/字面量化，**永远不触发 keydown(13)**
3. React/框架搜索框监听 onKeyDown(keyCode 13)，收不到 → 不提交
4. 实测（2026-09-24，GitHub issues 搜索框）：
   - `Input.insertText("NVDA")` → 词进框，URL 不变（没提交）
   - `Input.dispatchKeyEvent` keyDown+keyUp (windowsVirtualKeyCode:13) → **URL 立刻变 `?q=NVDA`**，搜索触发

当天后果：type "\n" 两次都无效 → 被迫手拼查询 URL 直接 nav，搜索框交互形同虚设。

## 修法

### 语义分叉：input 提交 / textarea 换行

`"\n"` 在单行 input = 提交意图；在 textarea = 换行意图。按元素类型分派：

- **tag 是 textarea（或 role 含 multiline）** → `"\n"` 照旧 `Input.insertText`（真换行）
- **否则** → 派发完整键盘事件序列：

```python
cdp_call(ws, "Input.dispatchKeyEvent", {
    "type": "keyDown", "key": "Enter", "code": "Enter",
    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}, msg_id=…)
cdp_call(ws, "Input.dispatchKeyEvent", {
    "type": "keyUp", "key": "Enter", "code": "Enter",
    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}, msg_id=…)
```

### 落点（三个函数）

1. `cdp_type`（cdp_act.py:326）：`_element_info` 已返回 tag——循环前判 tag；循环内遇 `"\n"` 按上述分叉
2. `cdp_type_handle`（cdp_act.py:228）：entry 有 role；focus 后可读 `activeElement.tagName`（focus 检查已存在，顺手拿 tag）
3. `cdp_type_focused`（cdp_act.py:515）：pre-flight 已读 activeElement——扩展它返回 tagName

### 回执

evidence 增加 `"enter_mode"`：`"keyboard_event"` | `"text_insert"` | `null`（无 \n 时）。输入含 \n 时必带。

## 测试（tests/test_enter_submit.py）

fixture A：搜索框 `<input onkeydown="if(event.keyCode===13){this.form&&(document.title='submitted')||document.title='submitted'}">`（或计数器）
fixture B：`<textarea>` 记录 value

1. `test_enter_submits_input`：type 到 input，text 以 \n 结尾 → title/计数器确认提交发生
2. `test_enter_newline_in_textarea`：type 到 textarea，text 含中间 \n → value 里有真实换行，无 keydown 副作用
3. `test_enter_receipt_has_mode`：回执 evidence.enter_mode 正确分叉
4. `test_enter_focused_path`：cdp_type_focused 同样生效

## 验收

1. run_tests.py 全绿
2. dogfood 回归：GitHub issues 搜索框 type "screen reader" + "\n" → 一次提交，URL 变 ?q=…

## 边界

- 不做 Tab/Escape 等其他键的 dispatchKeyEvent 化——真实需求出现再说
- 不动 fast=True 路径（el.value 直写，语义本就是程序化赋值）
- keypress 事件不派（已废弃的标准，keydown+keyup 足够）

## 关联

- 0.8 subagent 摩擦「Enter 不提交」同源——那是 CLI 侧，此处是浏览器侧，分开修

# Hand v6.8.0 — vision_llm 接通（视觉 LLM 模式）

## 目标
把已有的 `hand/perception/vision_llm.py`（`describe_screenshot` 函数）接通到 router 和 MCP 工具层，让 Grove 上的 hand 拥有"视觉 LLM 模式"——being 能主动调用 VLM 描述屏幕。

## 背景（已确认的事实）
- `vision_llm.py` 的 `describe_screenshot(image_b64, prompt=None, model=None, max_tokens=400)` 已完整实现，默认 OpenRouter `qwen/qwen3-vl-8b-instruct`，key 从 `~/.local/share/opencode/auth.json` 的 openrouter 读（已就绪，len=73）。
- router 的 see fallback 链（SEE_PRIORITY）没有 vision_llm，MCP 工具也没暴露它。
- 截图来源已存在：
  - `hand/perception/cdp_core.py` 的 `cdp_screenshot()` 返回 `{'data': base64, 'format': 'png', 'page_index': idx}`。
  - `hand/perception/vision_ocr.py` 的 `_capture_screenshot(path)` 在 macOS 用 screencapture 返回文件路径。

## 设计决策
vision_llm 作为**显式通道**（`kind="vlm"` + 独立工具 `hand_see_vlm`），不做静默 fallback 链集成。理由：VLM 调用有 60s 超时 + 网络延迟 + token 成本，不该在每次 see 失败时静默触发。being 主动选择"用 VLM 看"。

## 变更清单

### 1. hand/router.py — 新增 `route_see_vlm`
在 `route_see` 函数之前（或之后）新增：

```python
def route_see_vlm(prompt: Optional[str] = None, image_b64: Optional[str] = None) -> dict:
    """
    Use a vision LLM to describe the current screen.

    Screenshot source: CDP browser (if alive) → screencapture (macOS).
    Returns {"method": "vision_llm", "text": ..., "model": ..., "source": ...}.
    """
    source = None
    if not image_b64:
        # 1) try CDP browser
        try:
            from hand.perception.cdp_core import list_pages, cdp_screenshot
            pages = list_pages()
            if pages:
                shot = cdp_screenshot()
                image_b64 = shot.get("data", "")
                source = "cdp"
        except Exception:
            image_b64 = ""
        # 2) fallback screencapture (macOS)
        if not image_b64:
            import base64, tempfile, os
            from hand.perception.vision_ocr import _capture_screenshot
            path = _capture_screenshot()
            with open(path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
            source = "screencapture"

    from hand.perception.vision_llm import describe_screenshot
    result = describe_screenshot(image_b64, prompt=prompt)
    if result.get("ok"):
        return {
            "method": "vision_llm",
            "text": result.get("text"),
            "model": result.get("model"),
            "source": source,
        }
    return {
        "method": "vision_llm",
        "text": None,
        "model": result.get("model"),
        "source": source,
        "error": result.get("error"),
        "detail": result.get("detail"),
    }
```

在 `route_see` 里加分支——放在 `kind == "interactive"` 分支之后、`if place is None` 之前：

```python
    if kind == "vlm":
        return route_see_vlm()
```

### 2. hand/__init__.py
`__version__ = "6.8.0"`

### 3. kit/mcp_server.py — 新增工具
在 `hand_plan` 工具之后、`health` 之前新增：

```python
@mcp.tool()
def hand_see_vlm(prompt: str = None, image_b64: str = None) -> dict:
    from hand.router import route_see_vlm
    _bump()
    return route_see_vlm(prompt=prompt, image_b64=image_b64)
```

### 4. kit/manifest.json
- `"version": "6.7.0"` → `"6.8.0"`
- tools 数组（在 hand_plan 之后）新增：

```json
{
  "name": "hand_see_vlm",
  "description": "Use a vision language model (VLM) to describe the current screen. Takes a screenshot and sends it to the configured vision model (OpenRouter qwen3-vl by default). Set prompt to ask a specific question about the screen.",
  "params": {
    "type": "object",
    "properties": {
      "prompt": {"type": "string"},
      "image_b64": {"type": "string"}
    }
  }
}
```

### 5. CHANGELOG.md
在文件顶部（第一个 `## [` 之前）新增：

```
## [6.8.0] - 2026-08-18

#### Added
- **hand_see_vlm 视觉 LLM 模式**: 新增 `route_see_vlm` + MCP 工具 `hand_see_vlm`，把已有的 `vision_llm.describe_screenshot` 接通为显式视觉感知通道（`cdp_see(kind="vlm")` 也可达）。截图来源优先 CDP 活浏览器、fallback macOS screencapture，发给 OpenRouter `qwen/qwen3-vl-8b-instruct` 描述屏幕内容。这是"眼"的第一道网络级 VLM 通道——不依赖本地 OCR，只要有网络就能"看"。
```

### 6. tests/test_vision_llm.py（新建）
用标准库 unittest + unittest.mock，不引入 pytest。

测试用例：
1. `test_describe_screenshot_empty_image`：真实调用 `describe_screenshot("")`，断言返回 `ok == False` 且 `error == "empty image"`（不 mock，纯函数逻辑）。
2. `test_describe_screenshot_no_key`：`mock.patch("hand.perception.vision_llm._default_key", return_value="")`，调用 `describe_screenshot("aGVsbG8=")`，断言 `ok == False` 且 `error == "no api key"`。
3. `test_route_see_vlm_with_image`：`mock.patch("hand.router.describe_screenshot", return_value={"ok": True, "text": "hello", "model": "qwen", "error": None})`（注意 route_see_vlm 内部是 `from ... import describe_screenshot`，要 patch 到 `hand.router` 模块命名空间或直接用 `mock.patch.object`），调用 `route_see_vlm(image_b64="aGVsbG8=")`，断言返回 `method == "vision_llm"`、`text == "hello"`、`model == "qwen"`、`source is None`。
4. `test_route_see_vlm_screencapture_fallback`：mock `cdp_core.list_pages` 返回空列表、mock `vision_ocr._capture_screenshot` 返回一个临时 PNG 文件路径、mock `hand.router.describe_screenshot` 返回 ok。断言返回 `source == "screencapture"` 且 describe_screenshot 收到的 image_b64 非空。

注意 patch 目标：`route_see_vlm` 里 `from hand.perception.cdp_core import list_pages` 是运行时导入，所以 patch `hand.perception.cdp_core.list_pages`；`from hand.perception.vision_ocr import _capture_screenshot` patch `hand.perception.vision_ocr._capture_screenshot`；`from hand.perception.vision_llm import describe_screenshot` patch `hand.perception.vision_llm.describe_screenshot`。

### 7. tests/run_tests.py
`MODULES` 列表加 `"tests.test_vision_llm"`。

## 验收标准
1. `cd /home/alice/Hand && python3 -m py_compile hand/router.py kit/mcp_server.py` 无错误。
2. `cd /home/alice/Hand && python3 tests/run_tests.py` 全绿（含新增 test_vision_llm）。
3. 端到端（真实调 OpenRouter）：`cd /home/alice/Hand && python3 -c "from hand.perception.vision_llm import describe_screenshot; import json; print(json.dumps(describe_screenshot('aGVsbG8='), ensure_ascii=False))"` — 返回 ok=True（模型会尝试描述一张无效 PNG，可能返回 model error，这也可接受），但绝不能是 "no api key" 或 "auth_failed"（说明 key 配置正确）。

## 不要做的事
- 不要把 vision_llm 加进 SEE_PRIORITY 静默 fallback 链。
- 不要改 describe_screenshot 现有签名和逻辑（它已正确）。
- 不要动 start.sh / sync.sh / requirements.txt / cli.py。
- 不要改 mcp_server.py 里已有的其他工具函数。

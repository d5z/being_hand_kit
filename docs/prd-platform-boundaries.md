# platform boundaries - Platform Detection & Graceful Degradation

PRD - 2026-08-14 - Alice - Hand v6.6.0

---

## Motivation

Hand V6 声称"跨平台"。但代码里埋着一个未声明的真相：

- **CDP 主线是跨平台的**：browser 场景走 Chrome DevTools Protocol，
  依赖只有 `websocket` + `mcp`，三平台通吃。
- **fallback 层是 macOS-only**：`vision_ocr` 靠 `screencapture` + Apple
  Vision framework + `swiftc` 编译；`ax_app`/`ax_ui` 靠 `osascript`。
  这三样在 Linux/Windows 上是不存在的命令。
- **零平台检测**：README 是空的，代码里没有一处 `platform`/`darwin` 判断。

第一个外部 being（zongyang）在 Linux 上装 v6.5.1 时撞出了打包 bug，
修好后他会撞到第二个坑：CDP 能跑，但 see 一旦 fallback 到 vision_ocr /
ax_ui，就是一串 `command not found` 噪音。

这不是 bug 修复能盖住的，是**定位问题**。Hand 需要诚实地声明自己的
能力边界，并在不可用平台上优雅降级，而不是报噪音错。

---

## Goal

1. 引入平台检测，让 router 知道自己在什么平台上跑。
2. 非 macOS 平台上，自动摘掉 ax/vision backend，静默跳过而不是报错。
3. manifest.json 声明每个 backend 的平台可用性，让安装的 being 提前知道
   "CDP 全平台、AX/Vision 仅 macOS"。
4. 写 README，补上 zongyang 撞出来的第二个洞。

---

## Design

### 1. `hand/platform.py`（新增）

一个极小的模块，只做一件事：识别当前平台。

```python
import sys
import platform as _pyplatform

PLATFORM = _pyplatform.system().lower()   # "darwin" | "linux" | "windows"

def is_macos() -> bool:
    return PLATFORM == "darwin"

def is_linux() -> bool:
    return PLATFORM == "linux"
```

不做更多。没有抽象层，没有配置，没有依赖注入。就是一个常量 + 两个
谓词，router 直接 import。

### 2. router 按平台裁剪 backend 列表

`SEE_PRIORITY` / `DO_PRIORITY` 目前是静态 dict。改成：在模块加载时
（或首次路由时）按平台过滤。

```python
from hand.platform import is_macos

# ax_* / vision_ocr 只在 macOS 上可用
_MAC_ONLY_BACKENDS = {"ax_app", "ax_ui", "vision_ocr", "keystroke"}

def _available(backends: list[str]) -> list[str]:
    if is_macos():
        return backends
    return [b for b in backends if b not in _MAC_ONLY_BACKENDS]
```

关键：**静默跳过，不报错。** 非 macOS 上，`browser` 的优先级链
`["cdp_dom", "cdp_network", "ax_ui", "vision_ocr"]` 变成
`["cdp_dom", "cdp_network"]`，直接 fallback 到下一层或返回空，
而不是抛 `osascript: command not found`。

### 3. manifest.json 声明能力边界

加一个 `platforms` 字段：

```json
{
  "platforms": {
    "supported": ["darwin", "linux"],
    "backend_matrix": {
      "cdp":     ["darwin", "linux", "windows"],
      "ax":      ["darwin"],
      "vision":  ["darwin"]
    }
  }
}
```

让 Grove 层和安装方在装上之前就能读到能力边界，而不是装完才知道。

### 4. README.md（新增）

补上完全空缺的 README。至少包含：

- Hand 是什么（one being, one hand；open/see/do 三原语）
- 平台支持矩阵（上面 backend_matrix 的展开）
- 安装方式（Grove / 手动）
- 依赖（websocket、mcp；macOS 额外需要 osascript、screencapture、swiftc）
- 已知边界（非 macOS 上 desktop 感知不可用，browser/CDP 全平台）

---

## Backend × Platform Matrix（真相表）

| Backend | darwin | linux | windows | 依赖 |
|---|---|---|---|---|
| cdp_dom / cdp_network | ✅ | ✅ | ✅ | websocket, mcp |
| cdp_click / cdp_type | ✅ | ✅ | ✅ | websocket, mcp |
| ax_app / ax_ui | ✅ | ❌ | ❌ | osascript |
| ax_click | ✅ | ❌ | ❌ | osascript (System Events) |
| vision_ocr | ✅ | ❌ | ❌ | screencapture, swiftc, Vision |
| keystroke | ✅ | ❌ | ❌ | osascript |

> 注：ax_click 也依赖 osascript，与 keystroke 一样归入 macOS-only。
> 核实方式：源码 grep `osascript`，不是靠记忆。

---

## Acceptance Criteria（验收尺子）

1. `python3 -c "import hand.platform"` 在 Linux 上返回 `PLATFORM == "linux"`，
   `is_macos() == False`。
2. 在 Linux 上，`route_see(place=Place("browser"))` 的 backend 链不包含
   `ax_ui` / `vision_ocr`，且不产生任何 `command not found` 输出。
3. 在 macOS 上，行为与现在完全一致（不回归）。
4. manifest.json 有 `platforms` 字段，且 backend_matrix 与真相表一致。
5. README.md 存在，包含平台支持矩阵和已知边界。
6. 全部现有测试（`tests/`）通过。

---

## Out of Scope（明确不做）

- **不给 Linux 写 AX 替代**（AT-SPI）——这是将来"各平台长新触觉"的事，
  不是这次的事。这次只做"声明边界 + 优雅降级"。
- **不引入重型平台抽象层**——保持 platform.py 极简，不做依赖注入框架。
- **Windows 支持**——本 PRD 只声明边界，不承诺 Windows 可用性。

---

## Direction 依据

泽平 2026-08-14 确认方向："最终是要跨平台的" + "接口统一，实现分平台"。

抽象层（open/see/do 原语 + Place 路由）稳住不变，实现层（backend）各平台
自己长。CDP 是跨平台血脉，AX/Vision 是 macOS 更精细的触觉，将来 AT-SPI /
UIAutomation 是各平台新触觉。

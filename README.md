# Hand

One being, one hand. Hand is a being's hand on the screen: it **opens** places,
**sees** what's there, and **does** things — click, type, navigate. It speaks
the three primitives `open` / `see` / `do`, and routes them to whatever backend
fits the current place.

- **open** — launch a place (app, URL, file) and set the session context.
- **see** — perceive the current place: DOM snapshot, accessibility tree, OCR.
- **do** — act on the place: click, type, keystroke, plan.

Built by Alice for every being who needs to reach into a GUI.

## Platform support matrix

CDP (Chrome DevTools Protocol) is the cross-platform backbone. AX and Vision
are macOS-only — they depend on `osascript` / `screencapture` / `swiftc`, which
do not exist on Linux or Windows.

| Backend       | darwin | linux | windows | Depends on                        |
|---------------|--------|-------|---------|-----------------------------------|
| cdp_dom       | ✅     | ✅    | ✅      | websocket, mcp                    |
| cdp_network   | ✅     | ✅    | ✅      | websocket, mcp                    |
| cdp_click     | ✅     | ✅    | ✅      | websocket, mcp                    |
| cdp_type      | ✅     | ✅    | ✅      | websocket, mcp                    |
| ax_app        | ✅     | ❌    | ❌      | osascript                         |
| ax_ui         | ✅     | ❌    | ❌      | osascript                         |
| vision_ocr    | ✅     | ❌    | ❌      | screencapture, swiftc, Vision     |
| keystroke     | ✅     | ❌    | ❌      | osascript                         |

On non-macOS platforms the macOS-only backends are silently removed from the
routing priority chains — no "command not found" noise. Browsers (CDP) work on
all platforms.

### Backend × platform (as declared in `kit/manifest.json`)

```json
{
  "platforms": {
    "supported": ["darwin", "linux"],
    "backend_matrix": {
      "cdp":    ["darwin", "linux", "windows"],
      "ax":     ["darwin"],
      "vision": ["darwin"]
    }
  }
}
```

`supported` lists the platforms Hand is actively maintained on. Windows is not
yet supported; only the CDP matrix acknowledges it for the future.

## Installation

Via Grove, or manually:

```bash
git clone <repo> && cd Hand
pip install -r requirements.txt
./start.sh
```

## Dependencies

Core (all platforms):

- Python 3.8+
- `websocket` — CDP transport to Chrome
- `mcp` — Model Context Protocol (Tier 4)

macOS additionally requires:

- `osascript` — AX app/ui tree traversal, keystroke
- `screencapture` — screen capture for Vision OCR
- `swiftc` — compiling the Vision OCR helper
- Vision framework

## Known boundaries

- **Non-macOS**: desktop-native perception is unavailable. `ax_app`, `ax_ui`,
  `vision_ocr`, and `keystroke` backends are silently skipped. Browser / CDP
  flows (`cdp_*`) work everywhere.
- **Windows**: not yet supported at all.
- The `open` / `see` / `do` primitives and `Place` routing stay platform-neutral;
  only the backend implementations differ per platform.
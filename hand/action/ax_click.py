"""
AX Click — System Events click action backend.

Called by router.route_do() as a fallback when keystroke doesn't
handle the action. Uses ax_ui.ax_click() for raw AX path clicks,
with semantic mapping for common actions.

Design principles (learned from keystroke.py):
  - AppleScript app commands > toolbar click > menu bar click
  - Toolbar buttons exist but click result depends on window context
  - Menu bar items can be disabled (enabled=false) depending on UI state
  - When in doubt, fall back to AppleScript app layer

For Notes specifically: "新建笔记" / "Create a note" uses AppleScript
`make new note` — same bulletproof path as keystroke.py.
"""

import subprocess
import time
from typing import Optional


# ── Semantic action map ──────────────────────────────────────────────

def _notes_new_note(app_name: str = "Notes") -> dict:
    """
    Create a new note via AppleScript make.
    Bulletproof — bypasses UI state, same as keystroke.py.
    """
    try:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "{app_name}" to activate',
             "-e", "delay 0.2",
             "-e", f'tell application "{app_name}" to make new note'],
            capture_output=True, text=True, timeout=10
        )
        time.sleep(0.3)
        return {"method": "ax_click", "sub_method": "applescript_make",
                "success": True, "action": "新建笔记"}
    except Exception as e:
        return {"method": "ax_click", "success": False,
                "error": str(e), "action": "新建笔记"}


def _toolbar_click(app_name: str, button_index: int) -> dict:
    """
    Click a toolbar button by index. Requires app to be frontmost.
    Single -e script for coherent execution context.
    """
    script = f'''
tell application "{app_name}" to activate
delay 0.3
tell application "System Events"
  tell process "{app_name}"
    tell window 1
      click button {button_index} of toolbar 1
    end tell
  end tell
end tell
delay 0.2
'''
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return {"method": "ax_click", "sub_method": "toolbar_button",
                    "success": False, "button": button_index,
                    "error": r.stderr.strip()}
        return {"method": "ax_click", "sub_method": "toolbar_button",
                "success": True, "button": button_index,
                "result": r.stdout.strip()}
    except Exception as e:
        return {"method": "ax_click", "success": False,
                "error": str(e), "button": button_index}


def _menu_click(app_name: str, menu_name: str, item_name: str) -> dict:
    """
    Click a menu bar item. Checks enabled state first.
    """
    # Check if enabled
    check = f'''
tell application "System Events"
  tell process "{app_name}"
    tell menu 1 of menu bar item "{menu_name}" of menu bar 1
      return enabled of menu item "{item_name}"
    end tell
  end tell
end tell
'''
    try:
        r = subprocess.run(
            ["osascript", "-e", check],
            capture_output=True, text=True, timeout=5
        )
        if r.stdout.strip() == "false":
            return {"method": "ax_click", "sub_method": "menu_bar",
                    "success": False, "menu": f"{menu_name} → {item_name}",
                    "error": "menu item is disabled"}
    except Exception:
        pass

    # Click
    script = f'''
tell application "{app_name}" to activate
delay 0.2
tell application "System Events"
  tell process "{app_name}"
    tell menu bar 1
      tell menu bar item "{menu_name}"
        click menu item "{item_name}" of menu 1
      end tell
    end tell
  end tell
end tell
delay 0.2
'''
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return {"method": "ax_click", "sub_method": "menu_bar",
                    "success": False,
                    "menu": f"{menu_name} → {item_name}",
                    "error": r.stderr.strip()}
        return {"method": "ax_click", "sub_method": "menu_bar",
                "success": True,
                "menu": f"{menu_name} → {item_name}"}
    except Exception as e:
        return {"method": "ax_click", "success": False,
                "error": str(e)}


# ── CLICK_MAP: semantic action → strategy ────────────────────────────
# Priority: AppleScript app > toolbar button > menu bar

CLICK_MAP = {
    # Notes
    "新建笔记":      _notes_new_note,
    "Create a note": _notes_new_note,
    "新建文件夹":    lambda app: _toolbar_click(app, 1),
    "Add folder":    lambda app: _toolbar_click(app, 1),
    "折叠列表":      lambda app: _toolbar_click(app, 2),
    "Hide folders":  lambda app: _toolbar_click(app, 2),
    "画廊视图":      lambda app: _toolbar_click(app, 3),
    "Gallery view":  lambda app: _toolbar_click(app, 3),
    "清单":          lambda app: _toolbar_click(app, 6),
    "Checklist":     lambda app: _toolbar_click(app, 6),
    "表格":          lambda app: _toolbar_click(app, 7),
    "Add table":     lambda app: _toolbar_click(app, 7),
    "附件":          lambda app: _menu_click(app, "File", "Import to Notes…"),
}


# ── Main entry point — called by router ──────────────────────────────

def ax_click_do(action: str, app_name: str = "Notes") -> dict:
    """
    Execute a click action.

    Called by router.route_do() as backend="ax_click".
    Looks up semantic action in CLICK_MAP first.
    Falls back to raw AX path click via ax_ui.ax_click().
    """
    # 1. Semantic map
    if action in CLICK_MAP:
        try:
            return CLICK_MAP[action](app_name)
        except Exception as e:
            return {"method": "ax_click", "success": False,
                    "error": str(e), "action": action}

    # 2. Try as raw AX path (e.g. "button 4 of toolbar 1")
    try:
        from hand.perception.ax_ui import ax_click as _ax_click_raw
        result = _ax_click_raw(app_name, action)
        return {
            "method": "ax_click",
            "sub_method": "raw_path",
            **result
        }
    except ImportError:
        pass
    except Exception as e:
        return {"method": "ax_click", "success": False,
                "error": str(e), "action": action}

    return {"method": "ax_click", "success": False,
            "error": f"unknown action: {action}", "action": action}
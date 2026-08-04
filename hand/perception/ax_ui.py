"""
AX UI Layer — System Events accessibility tree traversal.

This is the "touch extension": fast but the tree paths are fragile.
Keystroke bypass is more reliable than click for UI actions.

Validated patterns (2026-06-19):
  - Process list: 'tell application "System Events" to get name of every process'
  - Window contents: 'tell process "{app}" to get entire contents of window 1'
  - Keystroke: 'tell process "{app}" to keystroke "n" using command down'
  - Toolbar help: elements have empty name but help attributes work

Design: follow ax_app.py pattern — _osascript() helper, typed functions.
"""

import subprocess
from typing import Optional


def _osascript(script: str, timeout: int = 10) -> tuple[str, str, int]:
    """Run AppleScript, return (stdout, stderr, exit_code)."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


# ── Process discovery ───────────────────────────────────────────────

def list_processes() -> list[str]:
    """Get names of all GUI processes."""
    out, err, code = _osascript(
        'tell application "System Events" to get name of every process'
    )
    if code != 0:
        raise RuntimeError(f"list_processes failed: {err}")
    return [p.strip() for p in out.split(",")]


def process_exists(app_name: str) -> bool:
    """Check if a GUI process is running."""
    names = list_processes()
    return app_name.lower() in {n.lower() for n in names}


# ── Window discovery ─────────────────────────────────────────────────

def list_windows(app_name: str) -> list[str]:
    """Get titles of all windows for an app."""
    out, err, code = _osascript(
        f'tell application "System Events" to tell process "{app_name}" '
        'to get name of every window'
    )
    if code != 0:
        raise RuntimeError(f"list_windows({app_name}) failed: {err}")
    return [w.strip() for w in out.split(",")]


def window_count(app_name: str) -> int:
    """Number of windows for an app."""
    out, err, code = _osascript(
        f'tell application "System Events" to tell process "{app_name}" '
        'to get count of windows'
    )
    if code != 0:
        raise RuntimeError(f"window_count({app_name}) failed: {err}")
    return int(out)


# ── AX tree traversal ────────────────────────────────────────────────

def get_ax_tree(app_name: str, window_index: int = 1) -> str:
    """Get entire AX tree of a window as raw text.

    Returns the full accessibility tree from 'entire contents'.
    This is the broadest AX query — sees everything System Events can reach.
    """
    out, err, code = _osascript(
        f'tell application "System Events" to tell process "{app_name}" '
        f'to get entire contents of window {window_index}'
    )
    if code != 0:
        raise RuntimeError(f"get_ax_tree({app_name}) failed: {err}")
    return out


def get_element(path: str, attribute: str, app_name: str, window_index: int = 1) -> str:
    """Get an attribute of an AX element by its path.

    path: like 'toolbar 1' or 'splitter group 1'
    attribute: 'value', 'help', 'name', 'description', 'count of buttons', etc.
    """
    out, err, code = _osascript(
        f'tell application "System Events" to tell process "{app_name}"\n'
        f'  tell window {window_index}\n'
        f'    get {attribute} of {path}\n'
        f'  end tell\n'
        f'end tell'
    )
    if code != 0:
        raise RuntimeError(f"get_element({path}.{attribute}) failed: {err}")
    return out


def get_toolbar_buttons(app_name: str, window_index: int = 1) -> list[dict]:
    """List all toolbar buttons with their help text.

    macOS toolbar buttons often have empty 'name' but populated 'help'.
    Returns list of {index, help, description}.
    """
    # Get button count
    count_out, count_err, count_code = _osascript(
        f'tell application "System Events" to tell process "{app_name}"\n'
        f'  tell window {window_index}\n'
        f'    get count of buttons of toolbar 1\n'
        f'  end tell\n'
        f'end tell'
    )
    if count_code != 0:
        raise RuntimeError(f"get_toolbar_buttons count failed: {count_err}")
    button_count = int(count_out)

    buttons = []
    for i in range(1, button_count + 1):
        # Try 'help' first (more reliable for macOS toolbars)
        help_out, _, _ = _osascript(
            f'tell application "System Events" to tell process "{app_name}"\n'
            f'  tell window {window_index}\n'
            f'    get help of button {i} of toolbar 1\n'
            f'  end tell\n'
            f'end tell'
        )
        # Also try 'description' as fallback
        desc_out, _, _ = _osascript(
            f'tell application "System Events" to tell process "{app_name}"\n'
            f'  tell window {window_index}\n'
            f'    get description of button {i} of toolbar 1\n'
            f'  end tell\n'
            f'end tell'
        )
        buttons.append({
            "index": i,
            "help": help_out if help_out else None,
            "description": desc_out if desc_out else None,
        })

    return buttons


# ── Keystroke (AX UI layer) ──────────────────────────────────────────

def ax_keystroke(key: str, modifiers: Optional[list[str]] = None,
                 app_name: Optional[str] = None) -> dict:
    """Send keystroke via System Events. More reliable than click.

    key: the key to press ('return', 'n', 'escape', 'tab')
    modifiers: list of modifiers ('command', 'shift', 'option', 'control')
    app_name: target process (activates to front first)
    """
    modifier_str = ""
    if modifiers:
        for mod in modifiers:
            modifier_str += f" using {mod} down"

    script = ""
    if app_name:
        script += f'tell application "System Events" to tell process "{app_name}"\n'
        script += f'  set frontmost to true\n'
        script += f'end tell\n'
        # Small delay for focus
        import time
        time.sleep(0.2)

    script += 'tell application "System Events"\n'
    script += f'  keystroke "{key}"{modifier_str}\n'
    script += 'end tell'

    out, err, code = _osascript(script, timeout=5)
    if code != 0:
        return {"success": False, "error": err, "key": key, "modifiers": modifiers}
    return {"success": True, "key": key, "modifiers": modifiers}


def ax_click(app_name: str, path: str, window_index: int = 1) -> dict:
    """Click an AX element by path. Fragile — prefer ax_keystroke.

    path: 'button 4 of toolbar 1' or 'menu item "File" of menu bar 1'
    """
    out, err, code = _osascript(
        f'tell application "System Events" to tell process "{app_name}"\n'
        f'  tell window {window_index}\n'
        f'    click {path}\n'
        f'  end tell\n'
        f'end tell'
    )
    if code != 0:
        return {"success": False, "error": err, "path": path}
    return {"success": True, "path": path, "result": out}


# ── High-level see() — router entry point ────────────────────────────

def see(app_name: str) -> dict:
    """Full AX perception of an app. Returns structured view.

    This is the entry point called by router.route_see().
    Returns process info + windows + toolbar + tree.
    """
    result = {
        "method": "ax_ui",
        "app": app_name,
        "running": False,
        "windows": [],
        "window_count": 0,
        "toolbar": None,
        "ax_tree": None,
        "error": None,
    }

    try:
        result["running"] = process_exists(app_name)
        if not result["running"]:
            result["error"] = f"Process '{app_name}' not found"
            return result

        # Windows
        result["windows"] = list_windows(app_name)
        result["window_count"] = window_count(app_name)

        # Toolbar (if exists)
        try:
            result["toolbar"] = get_toolbar_buttons(app_name)
        except RuntimeError:
            pass  # No toolbar or not accessible

        # AX tree (full)
        try:
            result["ax_tree"] = get_ax_tree(app_name)
        except RuntimeError as e:
            result["error"] = str(e)

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Quick checks ─────────────────────────────────────────────────────

#
# -- Quick checks --
 
def is_frontmost(app_name: str) -> bool:
    """Check if app is frontmost."""
    out, _, code = _osascript(
        f'tell application "System Events"\n'
        f'  get name of first process whose frontmost is true\n'
        f'end tell'
    )
    if code != 0:
        return False
    return code == 0

# Alias for router
ax_ui_see = see

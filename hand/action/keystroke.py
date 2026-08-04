"""
Keystroke — the most reliable desktop action backend.

Keystroke bypasses AX tree fragility. Instead of finding a button
and clicking it (which can fail with -1719 Invalid Index), we just
press the keyboard shortcut for the same action.

For Notes specifically: Cmd+N and menu click are unreliable because
the "New Note" menu item is often disabled (enabled=false) depending
on Notes UI state. The bulletproof path is AppleScript `make new note`,
which bypasses UI state entirely.
"""

import subprocess
import time
from typing import Optional


# ── Keystroke shortcuts we know ────────────────────────────────────

KEYSTROKE_MAP = {
    # Notes — use AppleScript make (bypasses UI state)
    "新建笔记": lambda app: _notes_new_note(app),
    "Cmd+N":    lambda app: _notes_new_note(app),
    "cmd+n":    lambda app: _notes_new_note(app),
    "列表模式": ("command", "2"),
    "Cmd+2": ("command", "2"),
    "Cmd+0": ("command", "0"),
    
    # General
    "Cmd+C": ("command", "c"),
    "Cmd+V": ("command", "v"),
    "Cmd+A": ("command", "a"),
    "Cmd+W": ("command", "w"),
    "Cmd+Q": ("command", "q"),
    "return": (None, "return"),
    "escape": (None, "escape"),
    "tab": (None, "tab"),
}


def _notes_new_note(app_name: str = "Notes") -> dict:
    """
    Create a new note in Notes via AppleScript make.
    This is the bulletproof path — bypasses UI state where
    File → New Note is often disabled.
    
    1. Cmd+0 to switch to list view (so new note is visible)
    2. AppleScript make new note in default account
    """
    # Step 1: go to list view
    subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to activate',
         "-e", "delay 0.3",
         "-e", f'tell application "System Events" to tell process "{app_name}" to keystroke "0" using command down'],
        capture_output=True, timeout=8
    )
    time.sleep(0.15)
    
    # Step 2: AppleScript make (always works)
    result = subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to make new note with properties {{name:"Untitled", body:""}}'],
        capture_output=True, text=True, timeout=8
    )
    
    return {
        "method": "applescript_make",
        "action": "新建笔记",
        "resolved": "make new note (AppleScript)",
        "exit_code": result.returncode,
        "stderr": result.stderr.strip() if result.stderr else None,
        "stdout": result.stdout.strip() if result.stdout else None,
    }


def keystroke_do(action: str, app_name: Optional[str] = None) -> dict:
    """
    Execute an action via keystroke.
    
    action can be:
    - A known semantic intent: "新建笔记"
    - A direct shortcut: "Cmd+N"
    - A raw key: "return"
    """
    try:
        # Activate target app if specified
        if app_name:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to activate'],
                capture_output=True, timeout=5
            )
            time.sleep(0.3)
        
        # Resolve action — may be a lambda for complex actions
        resolved = KEYSTROKE_MAP.get(action)
        if resolved is None:
            # Generic Cmd+X / Ctrl+X
            if action.startswith("Cmd+"):
                key = action.split("+", 1)[1].lower()
                mod, key = "command", key
            elif action.startswith("Ctrl+"):
                key = action.split("+", 1)[1].lower()
                mod, key = "control", key
            else:
                mod, key = None, action
            return _execute_keystroke(mod, key, action)
        
        if callable(resolved):
            return resolved(app_name if app_name else "Notes")
        else:
            mod, key = resolved
            return _execute_keystroke(mod, key, action)

    except Exception as e:
        return {"method": "keystroke", "error": str(e)}


def _execute_keystroke(mod: Optional[str], key: str, action_label: str) -> dict:
    """Build and run AppleScript keystroke."""
    if mod:
        script = f'tell application "System Events" to keystroke "{key}" using {mod} down'
    else:
        script = f'tell application "System Events" to keystroke "{key}"'
    
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=5
    )
    
    return {
        "method": "keystroke",
        "action": action_label,
        "resolved": f"{mod or ''}+{key}" if mod else key,
        "exit_code": result.returncode,
        "stderr": result.stderr.strip() if result.stderr else None,
    }
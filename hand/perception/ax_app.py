"""
AX Application Layer — AppleScript application-level interface.

This is proprioception: 0-latency, structured, no pixel inference.
Like knowing where your fingers are with your eyes closed.

Examples:
  - Notes: count notes, list names, read body, create note
  - Finder: list files, get selection
  - Calendar: list events

Pattern: tell {app} to {verb} {noun}
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


# ── Notes app ──────────────────────────────────────────────────────

def notes_count() -> int:
    """Number of notes in default account."""
    out, err, code = _osascript(
        'tell application "Notes" to get count of notes'
    )
    if code != 0:
        raise RuntimeError(f"notes_count failed: {err}")
    return int(out)


def notes_list() -> list[str]:
    """List all note names."""
    out, err, code = _osascript(
        'tell application "Notes" to get name of every note'
    )
    if code != 0:
        raise RuntimeError(f"notes_list failed: {err}")
    # Returns comma-separated names
    return [n.strip() for n in out.split(",")]


def notes_read(name: str) -> str:
    """Read body of a note by name."""
    out, err, code = _osascript(
        f'tell application "Notes" to get body of note "{name}"'
    )
    if code != 0:
        raise RuntimeError(f"notes_read failed: {err}")
    return out


def notes_create(name: str, body: str = "") -> str:
    """Create a new note. Returns the note's CoreData URI."""
    script = f'tell application "Notes" to make new note with properties {{name:"{name}", body:"{body}"}}'
    out, err, code = _osascript(script)
    if code != 0:
        raise RuntimeError(f"notes_create failed: {err}")
    return out


# ── Unified see interface ──────────────────────────────────────────

def ax_app_see(app_name: Optional[str] = None) -> dict:
    """Unified perception for supported apps."""
    if app_name is None:
        return {"method": "ax_app", "error": "no app specified"}

    try:
        if app_name.lower() == "notes":
            count = notes_count()
            names = notes_list()
            return {
                "method": "ax_app",
                "app": "Notes",
                "note_count": count,
                "note_names": names,
                "timestamp": __import__("time").time(),
            }
        else:
            return {"method": "ax_app", "error": f"app '{app_name}' not yet supported"}
    except Exception as e:
        return {"method": "ax_app", "error": str(e)}

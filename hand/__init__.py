"""
Hand — 图形界面统一框架（0.8.0：Python face / code mode）

Hand is a unified framework for beings to perceive and act on graphical interfaces.
Three primitives: open, see, do.
One being, one hand — whether it's a browser or a desktop app.

Two faces, one body (0.8.0):

    # Python face — for 触手 / agents in a persistent kernel (code mode)
    from hand import hand
    hand.open("https://beings.town")
    page = hand.see()                 # a11y tree + [idx] handles
    hand.do("click [15]", expect="url:/issues")

    # MCP face — for beings on Beings Town (kit/, unchanged)
    #   cdp_open / cdp_see / cdp_click / ... (see kit/manifest.json)

The Python face is a thin adapter over the same router and the same receipt
contract; it adds no capability, only a Python-shaped surface. See hand/hand.py
for the field-order contract (it is the boundary of a future native protocol).

V5 → V6: browser CDP code reborn as perception/action backends,
same primitives translated to desktop via accessibility tree + keystroke + Vision OCR.
0.7.0: a11y-v2 perception layer ([idx] handles) + receipt contract.
0.8.0: code mode — the Python face, and expect= world-state verification.
0.8.1: start.sh venv-first (grove installs get their .venv respected).
0.8.2: CDP port overridable via HAND_CDP_PORT (default 9222 unchanged).
0.8.3: vision-ocr bounds output + receipt contract fixes (PR #1, Judy).
"""

__version__ = "0.8.3"
__author__ = "Alice, from the river"

# Top-level Python face (lazy singleton behind these names).
from hand.hand import (          # noqa: E402
    browser, reset, open, see, do, shot, close, handles, resolve, history, help,
)

__all__ = [
    "__version__", "__author__",
    "browser", "reset", "open", "see", "do", "shot", "close", "handles",
    "resolve", "history", "help",
]

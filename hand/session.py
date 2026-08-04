"""
Session — cross-turn context cache.

A Session keeps the place and perception cache alive across turns.
Being's breath is turn-granular; the hand doesn't need to re-sense
the world from scratch every turn.
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Place:
    """Where I am right now."""
    type: str          # "browser" | "desktop_app" | "unknown"
    identifier: str    # URL / app name / None
    session_cache: dict = field(default_factory=dict)


@dataclass
class Session:
    """Context from one 'open' to the next."""
    place: Optional[Place] = None
    ax_tree: Optional[dict] = None         # AX tree cache
    screenshot_path: Optional[str] = None   # last screenshot path
    ocr_result: Optional[dict] = None       # last OCR result
    dom_ref: Optional[str] = None           # CDP node reference
    created_at: float = field(default_factory=time.time)

    def clear(self):
        """Invalidate all caches (e.g. after a 'do' action)."""
        self.ax_tree = None
        self.screenshot_path = None
        self.ocr_result = None
        self.dom_ref = None

    def touch(self):
        """Update heartbeat timestamp."""
        self.created_at = time.time()


# Global session — lives across turns in the same process
_current_session: Optional[Session] = None


def get_session() -> Session:
    global _current_session
    if _current_session is None:
        _current_session = Session()
    return _current_session


def reset_session():
    global _current_session
    _current_session = Session()

"""Minimal platform detection.

A single constant + two predicates. Router imports this directly.
No abstraction layer, no config, no dependency injection.
"""

import sys
import platform as _pyplatform

PLATFORM = _pyplatform.system().lower()   # "darwin" | "linux" | "windows"


def is_macos() -> bool:
    return PLATFORM == "darwin"


def is_linux() -> bool:
    return PLATFORM == "linux"
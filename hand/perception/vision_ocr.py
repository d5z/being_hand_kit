"""
Vision OCR — screencapture + Apple Vision framework recognition.

Layered confidence:
  1.0 = structured, parseable text
  0.5 = semantic clue (partial match, likely correct)
  0.3 = noise (recognized but low confidence)

Strengths: sees what you don't know to look for (Terminal, Feishu,
Cursor, browser tabs all at once).
Weaknesses: ~500ms latency, not as precise as AX for counting.
"""

import subprocess
import json
import os
import time
from typing import Optional

# Path to compiled Vision OCR binary — relative to this file so the
# kit works regardless of where it's installed. Compile on the fly if missing.
VISION_OCR_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_ocr_bin")


def _capture_screenshot(path: str = "/tmp/hand_screenshot.png") -> str:
    """Take a screenshot, return path."""
    result = subprocess.run(
        ["screencapture", "-x", path],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        raise RuntimeError(f"screencapture failed: {result.stderr}")
    return path


def _vision_recognize(image_path: str) -> dict:
    """
    Run Vision OCR on an image.
    Returns {"lines": [...], "warnings": [...]} — lines carry
    {text, confidence, bounds} when the binary is current.
    Warnings are returned (not just stderr): in kit scenarios stderr
    lands in logs the caller never sees; the return value is the main
    channel (Judy 1172, 0.9 receipt-honesty).
    """
    warnings = []
    if not os.path.exists(VISION_OCR_BIN):
        # Fallback: compile on the fly
        _compile_vision_bin()

    # Stale-binary detection (0.9): a bin older than its swift source
    # predates the bounds output — old-format lines silently lose
    # coordinates. Declare it instead of swallowing it.
    swift_src = os.path.join(os.path.dirname(__file__), "vision_ocr.swift")
    if os.path.exists(VISION_OCR_BIN) and os.path.exists(swift_src):
        try:
            if os.path.getmtime(VISION_OCR_BIN) < os.path.getmtime(swift_src):
                warnings.append(
                    "stale vision_ocr_bin: binary older than vision_ocr.swift — "
                    "bounds output may be missing; recompile with swiftc "
                    "-o vision_ocr_bin vision_ocr.swift")
        except OSError:
            pass

    result = subprocess.run(
        [VISION_OCR_BIN, image_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"vision_ocr failed: {result.stderr}")

    # New format: confidence\tx\ty\tw\th\ttext  (tab-separated, 6 fields)
    # Old format fallback: "confidence: text"
    lines = []
    old_format_count = 0
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        segments = line.split("\t", 5)
        if len(segments) >= 6:
            try:
                confidence = float(segments[0])
                x = int(float(segments[1]))
                y = int(float(segments[2]))
                w = int(float(segments[3]))
                h = int(float(segments[4]))
                text = segments[5]
                lines.append({
                    "text": text,
                    "confidence": confidence,
                    "x": x, "y": y, "w": w, "h": h,
                    "center_x": x + w // 2,
                    "center_y": y + h // 2,
                })
                continue
            except (ValueError, IndexError):
                pass
        try:
            parts = line.split(": ", 1)
            if len(parts) == 2:
                confidence = float(parts[0])
                text = parts[1]
                lines.append({"confidence": confidence, "text": text})
                old_format_count += 1
        except (ValueError, IndexError):
            continue
    if old_format_count:
        warnings.append(
            f"{old_format_count} line(s) parsed in old format (no bounds) — "
            "binary predates bounds output; coordinates unavailable for them")
    return {"lines": lines, "warnings": warnings}


def _compile_vision_bin():
    """Compile the Swift Vision OCR binary."""
    swift_source = os.path.join(os.path.dirname(__file__), "vision_ocr.swift")
    subprocess.run(
        ["swiftc", "-o", VISION_OCR_BIN, swift_source],
        capture_output=True, text=True, timeout=60
    )


def vision_ocr_see() -> dict:
    """Take screenshot + OCR, return structured perception."""
    start = time.time()
    try:
        path = _capture_screenshot()
        capture_time = time.time() - start

        recognized = _vision_recognize(path)
        lines = recognized["lines"]
        ocr_time = time.time() - start - capture_time

        # Organize by confidence tiers
        high_conf = [l for l in lines if l["confidence"] >= 0.9]
        mid_conf = [l for l in lines if 0.5 <= l["confidence"] < 0.9]
        low_conf = [l for l in lines if l["confidence"] < 0.5]

        return {
            "method": "vision_ocr",
            "screenshot": path,
            "capture_ms": int(capture_time * 1000),
            "ocr_ms": int(ocr_time * 1000),
            "all_text": "\n".join(l["text"] for l in lines),
            "by_confidence": {
                "high": [l["text"] for l in high_conf],
                "mid": [l["text"] for l in mid_conf],
                "low": [l["text"] for l in low_conf],
            },
            "total_lines": len(lines),
            "warnings": recognized["warnings"],
            "timestamp": time.time(),
        }
    except Exception as e:
        return {"method": "vision_ocr", "error": str(e)}


def find_text(query: str, image_path=None) -> dict:
    """Locate query on screen via Vision OCR; return matching lines with pixel coords.

    Case-insensitive substring match. Screenshot path: use image_path if given
    (must exist — explicit intent is not silently overridden with a fresh screen
    capture), otherwise _capture_screenshot() (osascript screencapture).
    """
    if image_path is not None:
        if not os.path.isfile(image_path):
            return {
                "method": "vision_ocr_find",
                "query": query,
                "error": f"image_path not found: {image_path}",
            }
        path = image_path
    else:
        path = _capture_screenshot()
    recognized = _vision_recognize(path)
    lines = recognized["lines"]
    needle = (query or "").lower()
    matches = [l for l in lines if needle in (l.get("text") or "").lower()]
    matches.sort(key=lambda m: m.get("confidence", 0), reverse=True)
    return {
        "method": "vision_ocr_find",
        "query": query,
        "matches": matches,
        "count": len(matches),
        "screenshot": path,
        "warnings": recognized["warnings"],
    }

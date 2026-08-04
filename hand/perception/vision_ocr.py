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

# Path to compiled Vision OCR binary
VISION_OCR_BIN = "/Users/alice/Hand/hand/perception/vision_ocr_bin"


def _capture_screenshot(path: str = "/tmp/hand_screenshot.png") -> str:
    """Take a screenshot, return path."""
    result = subprocess.run(
        ["screencapture", "-x", path],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode != 0:
        raise RuntimeError(f"screencapture failed: {result.stderr}")
    return path


def _vision_recognize(image_path: str) -> list[dict]:
    """
    Run Vision OCR on an image.
    Returns list of {text, confidence, bounds}.
    Requires the compiled Swift binary.
    """
    if not os.path.exists(VISION_OCR_BIN):
        # Fallback: compile on the fly
        _compile_vision_bin()

    result = subprocess.run(
        [VISION_OCR_BIN, image_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"vision_ocr failed: {result.stderr}")

    # Parse JSON lines output
    lines = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            parts = line.split(": ", 1)
            if len(parts) == 2:
                confidence = float(parts[0])
                text = parts[1]
                lines.append({"confidence": confidence, "text": text})
        except (ValueError, IndexError):
            continue
    return lines


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

        lines = _vision_recognize(path)
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
            "timestamp": time.time(),
        }
    except Exception as e:
        return {"method": "vision_ocr", "error": str(e)}

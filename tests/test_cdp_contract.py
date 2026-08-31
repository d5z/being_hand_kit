"""Pure-logic tests for CDP perception contract v1 (no real browser needed).

Run with: python3 tests/run_tests.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hand.perception.cdp_core import _build_coord, _decode_image_size
import base64


class TestBuildCoord(unittest.TestCase):
    """Validate scale math with mock layout metrics."""

    def test_1x_dpr_unsampled(self):
        """CSS 1440×900, DPR=1, image 1440×900 → scale 1.0."""
        coord = _build_coord(1440, 900, 1.0, 1440, 900)
        self.assertEqual(coord['space'], 'physical')
        self.assertEqual(coord['dpr'], 1.0)
        self.assertEqual(coord['viewport'], {'w': 1440, 'h': 900})
        self.assertEqual(coord['image']['w'], 1440)
        self.assertEqual(coord['image']['h'], 900)
        self.assertEqual(coord['image']['scale'], 1.0)

    def test_2x_dpr_unsampled(self):
        """CSS 1440×900, DPR=2, image 2880×1800 → scale 1.0."""
        coord = _build_coord(1440, 900, 2.0, 2880, 1800)
        self.assertEqual(coord['image']['scale'], 1.0)

    def test_2x_dpr_downsampled(self):
        """CSS 1440×900, DPR=2, image 1440×900 (downsampled 0.5x) → scale 0.5."""
        coord = _build_coord(1440, 900, 2.0, 1440, 900)
        self.assertEqual(coord['image']['scale'], 0.5)

    def test_no_image_infers_physical(self):
        """Without explicit image size, infer physical size and scale=1.0."""
        coord = _build_coord(1440, 900, 2.0)
        self.assertEqual(coord['image']['w'], 2880)
        self.assertEqual(coord['image']['h'], 1800)
        self.assertEqual(coord['image']['scale'], 1.0)

    def test_zero_viewport_fallback(self):
        """Zero viewport yields scale 1.0 fallback."""
        coord = _build_coord(0, 0, 2.0, 0, 0)
        self.assertEqual(coord['image']['scale'], 1.0)


class TestDecodeImageSize(unittest.TestCase):
    """Validate PNG/JPEG header decoding."""

    def test_decode_png(self):
        # Minimal 1×1 PNG in base64
        png = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\x0dIHDR'
            b'\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        b64 = base64.b64encode(png).decode('ascii')
        w, h = _decode_image_size(b64, 'png')
        self.assertEqual(w, 1)
        self.assertEqual(h, 1)

    def test_decode_jpeg(self):
        # Minimal JPEG with SOF0
        jpeg = bytes([
            0xFF, 0xD8,  # SOI
            0xFF, 0xC0,  # SOF0
            0x00, 0x0B,  # length
            0x08,        # precision
            0x00, 0x01,  # height
            0x00, 0x01,  # width
            0x01,        # components
            0x01, 0x11, 0x00,  # component
            0xFF, 0xD9,  # EOI
        ])
        b64 = base64.b64encode(jpeg).decode('ascii')
        w, h = _decode_image_size(b64, 'jpeg')
        self.assertEqual(w, 1)
        self.assertEqual(h, 1)


if __name__ == "__main__":
    unittest.main()

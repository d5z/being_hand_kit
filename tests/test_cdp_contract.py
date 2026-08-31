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


class TestClickAtContract(unittest.TestCase):
    """Verify _click_at dispatches CSS px = physical / dpr."""

    def test_click_at_divides_by_dpr(self):
        from unittest import mock
        from hand.action.cdp_act import _click_at

        calls = []
        def fake_cdp(ws, method, params=None, msg_id=1, timeout=10):
            calls.append((method, params, msg_id))
            return {}

        with mock.patch('hand.action.cdp_act.cdp_call', side_effect=fake_cdp):
            _click_at(mock.Mock(), 400, 600, 2.0)

        self.assertEqual(len(calls), 2)  # pressed + released
        for _, params, _ in calls:
            self.assertEqual(params['x'], 200.0)  # 400 / 2
            self.assertEqual(params['y'], 300.0)  # 600 / 2

    def test_click_at_1x_identity(self):
        from unittest import mock
        from hand.action.cdp_act import _click_at

        calls = []
        def fake_cdp(ws, method, params=None, msg_id=1, timeout=10):
            calls.append((method, params, msg_id))
            return {}

        with mock.patch('hand.action.cdp_act.cdp_call', side_effect=fake_cdp):
            _click_at(mock.Mock(), 150, 250, 1.0)

        for _, params, _ in calls:
            self.assertEqual(params['x'], 150.0)
            self.assertEqual(params['y'], 250.0)


class TestElementInfoContract(unittest.TestCase):
    """Verify _element_info returns physical w/h at dpr≠1."""

    def test_element_info_physical_pixels_at_dpr2(self):
        from unittest import mock
        from hand.perception.cdp_core import _element_info

        # Simulate CDP returning JS result for an element at CSS (100,50) size 200×40, dpr=2
        def fake_cdp(ws, method, params=None, msg_id=1, timeout=10):
            if method == 'Runtime.evaluate':
                return {'result': {'value': '{"x":300,"y":150,"w":400,"h":80,"visible":true,"tag":"BUTTON","text":"OK"}'}}
            return {}

        with mock.patch('hand.perception.cdp_core.cdp_call', side_effect=fake_cdp):
            info = _element_info(mock.Mock(), '#btn')

        self.assertEqual(info['x'], 300)
        self.assertEqual(info['y'], 150)
        self.assertEqual(info['w'], 400)  # 200 CSS * 2
        self.assertEqual(info['h'], 80)   # 40 CSS * 2
        self.assertTrue(info['visible'])

    def test_element_info_js_expr_contains_dpr_for_wh(self):
        """Sanity-check that the JS expression multiplies w/h by dpr."""
        import json as jm
        from hand.perception.cdp_core import _element_info

        # The JS expr is constructed inside _element_info; we inspect it indirectly
        # by ensuring a mocked response is parsed correctly.
        from unittest import mock
        def fake_cdp(ws, method, params=None, msg_id=1, timeout=10):
            expr = params.get('expression', '')
            # Assert the expression contains *dpr for width and height
            self.assertIn('r.width*dpr', expr)
            self.assertIn('r.height*dpr', expr)
            return {'result': {'value': '{"x":0,"y":0,"w":0,"h":0,"visible":false,"tag":"DIV","text":""}'}}

        with mock.patch('hand.perception.cdp_core.cdp_call', side_effect=fake_cdp):
            _element_info(mock.Mock(), 'body')


if __name__ == "__main__":
    unittest.main()

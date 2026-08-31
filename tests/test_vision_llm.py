"""Tests for vision_llm route and describe_screenshot."""

import base64
import os
import tempfile
import unittest
from unittest import mock

from hand.perception.vision_llm import describe_screenshot
from hand.router import route_see_vlm


class TestVisionLLM(unittest.TestCase):

    def test_describe_screenshot_empty_image(self):
        result = describe_screenshot("")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "empty image")

    @mock.patch("hand.perception.vision_llm._default_key", return_value="")
    def test_describe_screenshot_no_key(self, _mock_key):
        result = describe_screenshot("aGVsbG8=")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error"), "no api key")

    @mock.patch(
        "hand.perception.vision_llm.describe_screenshot",
        return_value={"ok": True, "text": "hello", "model": "qwen", "error": None},
    )
    def test_route_see_vlm_with_image(self, mock_describe):
        result = route_see_vlm(image_b64="aGVsbG8=")
        self.assertEqual(result.get("method"), "vision_llm")
        self.assertEqual(result.get("text"), "hello")
        self.assertEqual(result.get("model"), "qwen")
        self.assertIsNone(result.get("source"))
        mock_describe.assert_called_once_with("aGVsbG8=", prompt=None)

    @mock.patch("hand.perception.cdp_core.list_pages", return_value=[])
    @mock.patch("hand.perception.vision_ocr._capture_screenshot")
    @mock.patch(
        "hand.perception.vision_llm.describe_screenshot",
        return_value={"ok": True, "text": "screen", "model": "qwen", "error": None},
    )
    def test_route_see_vlm_screencapture_fallback(
        self, mock_describe, mock_capture, mock_list_pages
    ):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            tmp_path = f.name
        try:
            mock_capture.return_value = tmp_path
            result = route_see_vlm()
            self.assertEqual(result.get("method"), "vision_llm")
            self.assertEqual(result.get("source"), "screencapture")
            # describe_screenshot received a non-empty base64 string
            call_args = mock_describe.call_args
            received_b64 = call_args[0][0] if call_args[0] else call_args[1].get("image_b64")
            self.assertTrue(received_b64)
            self.assertIsInstance(received_b64, str)
            # verify it decodes back to the PNG header
            decoded = base64.b64decode(received_b64)
            self.assertTrue(decoded.startswith(b"\x89PNG"))
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()

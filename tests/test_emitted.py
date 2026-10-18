"""L1 tests for hand 0.10 D1 — the `emitted` half of the two-part signature.

PRD: docs/prd-delivery-honesty.md D1.

What these tests are actually guarding
--------------------------------------
The whole point of `emitted` is that hand says ONLY what hand did: it put a
payload into THIS receipt. The two failure modes this file exists to catch:

  1. hand claiming `delivered` / `attached` — that is portal/heart's signature,
     and a hand-side claim would be a new `claimed` masquerading as `verified`
     (the exact sin 0.9 S1 was written to stop).
  2. hand staying silent about a payload it captured but did not return — the
     S2 bug shape: absence read as completeness. Captured-but-not-sent must be
     `emitted: false` + a reason, never an absent block.

No browser needed: the CDP layer is patched.
"""

import base64
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand import router  # noqa: E402
from hand.receipt import (_b64_decoded_len, emitted_block,  # noqa: E402
                          image_channel, text_channel,
                          EMITTED_BY, EMITTED_IMAGE_REASONS)
from hand.session import Place  # noqa: E402

# A tiny but real PNG header + payload — enough to exercise byte accounting.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f5e0000000049454e44ae42"
    "6082")
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")


class TestEmittedBlockShape(unittest.TestCase):
    def test_by_is_hand(self):
        blk = emitted_block({"image": image_channel(b64=_PNG_B64, fmt="png")})
        self.assertEqual(blk["by"], EMITTED_BY)
        self.assertEqual(blk["by"], "hand")

    def test_never_speaks_for_the_caller(self):
        """The block must not carry delivery/attached/received — ever."""
        blk = emitted_block({"image": image_channel(b64=_PNG_B64, fmt="png")})
        flat = repr(blk)
        for forbidden in ("delivered", "attached", "received", "delivery"):
            self.assertNotIn(forbidden, flat,
                             f"emitted block leaked the caller's side: {forbidden}")

    def test_false_always_carries_a_reason(self):
        for reason in EMITTED_IMAGE_REASONS:
            ch = image_channel(b64=None, fmt=None, path=None)
            self.assertFalse(ch["emitted"])
            self.assertIn(ch["reason"], EMITTED_IMAGE_REASONS)
        ch = image_channel(path="/tmp/shot.png")
        self.assertEqual(ch["reason"], "file_path")
        self.assertEqual(ch["path"], "/tmp/shot.png")
        ch = image_channel()
        self.assertEqual(ch["reason"], "not_requested")


class TestBase64ByteAccounting(unittest.TestCase):
    def test_length_matches_real_decode(self):
        for raw in (b"", b"a", b"ab", b"abc", _PNG_BYTES, b"x" * 4097):
            b64 = base64.b64encode(raw).decode("ascii")
            self.assertEqual(_b64_decoded_len(b64), len(raw),
                             f"byte accounting wrong for {len(raw)} bytes")

    def test_image_channel_reports_wire_bytes_not_base64_chars(self):
        ch = image_channel(b64=_PNG_B64, fmt="png")
        self.assertTrue(ch["emitted"])
        self.assertEqual(ch["bytes"], len(_PNG_BYTES))
        self.assertEqual(ch["data_chars"], len(_PNG_B64))
        self.assertEqual(ch["encoding"], "base64")
        self.assertEqual(ch["format"], "png")


class TestShotEmits(unittest.TestCase):
    """route_screenshot is where 0.9's `verified` and 0.10's `emitted` diverge."""

    def _patched_shot(self, with_data):
        fake = {"data": _PNG_B64, "format": "png"}
        with mock.patch("hand.perception.cdp_core.cdp_screenshot", return_value=fake):
            return router.route_screenshot(
                place=Place(type="browser", identifier="https://x/"),
                with_data=with_data)

    def test_with_data_true_declares_the_image(self):
        out = self._patched_shot(with_data=True)
        self.assertTrue(out["verified"])
        image = out["emitted"]["channels"]["image"]
        self.assertTrue(image["emitted"])
        self.assertEqual(image["bytes"], len(_PNG_BYTES))
        self.assertEqual(image["format"], "png")
        self.assertEqual(out["emitted"]["by"], "hand")
        # The payload is really there — emitted must track reality.
        self.assertEqual(out["data"], _PNG_B64)

    def test_with_data_false_declares_a_gap_not_silence(self):
        out = self._patched_shot(with_data=False)
        self.assertTrue(out["verified"])          # the action DID happen
        self.assertNotIn("data", out)             # the payload did NOT travel
        image = out["emitted"]["channels"]["image"]
        self.assertFalse(image["emitted"])        # ...and hand says so
        self.assertEqual(image["reason"], "not_requested")

    def test_verified_and_emitted_are_independent_axes(self):
        """0.10's core claim: verified says the action happened, emitted says
        the evidence travelled. A receipt can be verified-and-not-emitted."""
        out = self._patched_shot(with_data=False)
        self.assertIs(out["verified"], True)
        self.assertIs(out["emitted"]["channels"]["image"]["emitted"], False)


class TestSeeChannelsEmit(unittest.TestCase):
    def _see_with(self, payload, **kwargs):
        with mock.patch("hand.perception.ax_tree.ax_snapshot", return_value=payload):
            return router.route_see(place=Place(type="browser", identifier="https://x/"),
                                    kind=kwargs.get("kind", "a11y"))

    def test_a11y_declares_tree_nodes(self):
        payload = {
            "method": "cdp_a11y", "tree": "- root\n  - link 'a'",
            "node_count": 2, "raw_node_count": 2, "serialized_bytes": 20,
            "truncated": False, "nodes_omitted": 0, "text_truncated_count": 0,
            "format": "a11y-v2", "ax_version": 2, "sha256": "x" * 64,
            "root_role": "RootWebArea", "url": "https://x/", "page_title": "X",
            "nav_id": "nav_1",
        }
        out = self._see_with(payload)
        a11y = out["emitted"]["channels"]["a11y"]
        self.assertTrue(a11y["emitted"])
        self.assertEqual(a11y["count"], 2)
        self.assertEqual(a11y["unit"], "nodes")
        self.assertEqual(a11y["key"], "tree")

    def test_unknown_backend_stays_absent_not_false(self):
        """Absent != false. A backend with no media channel declares nothing."""
        wrapped = router._with_receipt({"method": "some_future_backend"})
        self.assertNotIn("emitted", wrapped)
        self.assertIn("verified", wrapped)

    def test_interactive_zero_elements_is_a_declared_gap(self):
        wrapped = router._with_receipt({"method": "cdp_interactive", "count": 0,
                                        "total": 0})
        elements = wrapped["emitted"]["channels"]["elements"]
        self.assertFalse(elements["emitted"])
        self.assertEqual(elements["reason"], "no_elements")
        self.assertEqual(elements["count"], 0)


class TestVisionOcrEmitsFilePath(unittest.TestCase):
    def test_file_path_is_a_gap_with_its_reason(self):
        fake = {"method": "screenshot", "source": "vision_ocr",
                "path": "/tmp/shot.png", "verified": True}
        with mock.patch("hand.perception.vision_ocr._capture_screenshot",
                        return_value="/tmp/shot.png"), \
             mock.patch.object(router, "cdp_screenshot", create=True), \
             mock.patch("hand.perception.cdp_core.list_pages", return_value=[]):
            out = router.route_screenshot(place=Place(type="desktop_app",
                                                      identifier="Notes"))
        self.assertEqual(out["source"], "vision_ocr")
        image = out["emitted"]["channels"]["image"]
        self.assertFalse(image["emitted"])
        self.assertEqual(image["reason"], "file_path")
        self.assertEqual(image["path"], "/tmp/shot.png")
        self.assertNotIn("data", out)


if __name__ == "__main__":
    unittest.main()

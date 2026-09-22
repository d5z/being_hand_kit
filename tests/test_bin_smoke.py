"""Release guardrail: vision_ocr_bin runtime smoke (Judy PR #3, #34 1233).

The mtime SOP is blind to stale-checkout compiles: a bin compiled today
from an old checkout passes "bin newer than swift source" yet outputs the
pre-bounds single-colon format. The structural guard is running the bin
on a fixture image and asserting the tab-separated bounds format.

Platform contract (0.9 receipt-honesty): the binary is Mach-O arm64 —
runs on macOS only. On other platforms this test SKIPS with an explicit
declaration (not a silent pass): the guard is enforced wherever Mach-O
can execute (macOS contributors, sw-mac-mini release preflight), and the
skip is visible in every run so a Linux-only green suite never implies
the bin was checked.
"""

import os
import platform
import subprocess
import unittest

BIN = os.path.join(os.path.dirname(__file__), "..", "hand", "perception", "vision_ocr_bin")
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ocr", "smoke.png")


class TestVisionOcrBinSmoke(unittest.TestCase):
    def setUp(self):
        if platform.system() != "Darwin":
            self.skipTest(
                "vision_ocr_bin is Mach-O arm64 — runtime smoke only runs on macOS; "
                "bin format NOT verified on this platform (declared skip, 0.9 principle)")
        if not os.path.exists(BIN):
            self.skipTest("vision_ocr_bin not present")

    def _run(self):
        return subprocess.run(
            [BIN, FIXTURE], capture_output=True, text=True, timeout=30)

    def test_bin_outputs_tab_format_with_bounds(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, f"bin exited {result.returncode}: {result.stderr}")
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        self.assertTrue(lines, "no text recognized on fixture image — smoke cannot verify format")
        for line in lines:
            segments = line.split("\t")
            self.assertGreaterEqual(
                len(segments), 6,
                f"line not in tab-separated bounds format (got {line!r}) — "
                f"bin is stale-compiled or predates bounds output; recompile: "
                f"swiftc -o hand/perception/vision_ocr_bin hand/perception/vision_ocr.swift")

    def test_bin_not_old_single_colon_format(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, f"bin exited {result.returncode}: {result.stderr}")
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            self.assertNotIn(
                ": ", line,
                f"old single-colon format detected ({line!r}) — bin compiled from "
                f"stale checkout or pre-bounds source; mtime check cannot catch this; recompile")


if __name__ == "__main__":
    unittest.main()

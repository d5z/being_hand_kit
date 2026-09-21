"""L6 stability — boundaries and recovery.

PRD L6: Chrome crash -> re-open brings it back; a heavy tree truncates instead of
hanging; a slow page stays bounded and honest; 20 consecutive calls leak no
processes; the same page state serializes byte-identically across repeats.
"""

import hashlib
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, "/home/alice/Hand")

from hand import router

from tests.harness import judge as J
from tests.harness import runner
from tests.harness.scenarios import FixtureServer

_FX = None
_CHROME = runner.chrome_available()


def setUpModule():
    global _FX
    if _CHROME:
        _FX = FixtureServer()


def tearDownModule():
    if _FX:
        _FX.close()


def _kill_chrome():
    """SIGKILL every chrome process — a genuine crash, not a graceful close."""
    for pat in ("chrome-headless-shell", "chrome", "chromium"):
        subprocess.run(["pkill", "-9", "-f", pat],
                       capture_output=True, text=True)
    deadline = time.time() + 10
    while time.time() < deadline and runner.chrome_available(timeout=1):
        time.sleep(0.4)


def _ensure_chrome():
    if not runner.chrome_available():
        router.route_open("https://example.com")


@unittest.skipIf(not _CHROME, "Chrome unavailable")
class L6Stability(unittest.TestCase):

    def test_a_crash_recovery_reopen(self):
        """Kill Chrome mid-session; the next open must spawn a fresh one."""
        router.route_open(_FX.url("/basic"))
        _kill_chrome()
        self.assertFalse(runner.chrome_available(timeout=1),
                         "chrome survived SIGKILL (kill failed)")
        t0 = time.time()
        r = router.route_open(_FX.url("/form"))
        elapsed = time.time() - t0
        J.assert_verdict(self, J.judge_open(r, task="recover-after-crash"))
        self.assertTrue(runner.chrome_available(), "endpoint not back after recovery")
        self.assertLess(elapsed, 20, f"recovery took {elapsed:.1f}s")
        after = router.route_see(kind="a11y")
        J.assert_verdict(self, J.judge_a11y(after, task="see-after-crash"))

    def test_b_close_is_verified_and_recoverable(self):
        router.route_open(_FX.url("/basic"))
        r = runner.close_browser()
        J.assert_verdict(self, J.judge_close(r, task="close(verified)"))
        self.assertTrue(r.get("endpoint_gone"))
        # restore for any later test
        router.route_open(_FX.url("/basic"))
        self.assertTrue(runner.chrome_available())

    def test_c_heavy_tree_truncates(self):
        router.route_open(_FX.url("/big"))
        r = router.route_see(kind="a11y")
        J.assert_verdict(self, J.judge_a11y(r, task="see(heavy)"))
        self.assertTrue(r["truncated"], "900-paragraph page did not trigger truncation")
        self.assertGreater(r["nodes_omitted"], 0)
        self.assertEqual(r["node_count"], r["max_lines"])
        # no [idx] is emitted past the cut: handle map must not exceed node_count
        self.assertLessEqual(len(r["handles"]), r["node_count"])

    def test_d_slow_page_stays_bounded(self):
        router.route_open(_FX.url("/big"))
        t0 = time.time()
        r = router.route_see(kind="a11y")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 15, f"see on a heavy page took {elapsed:.1f}s")
        self.assertTrue(r.get("verified"))

    def test_e_20_calls_no_process_leak(self):
        router.route_open(_FX.url("/basic"))
        time.sleep(0.5)
        base = runner.chrome_proc_count()
        self.assertGreater(base, 0, "no chrome processes to measure")
        for i in range(20):
            router.route_see(kind="a11y")
            if i % 4 == 0:
                router.route_screenshot()
            if i % 5 == 0:
                router.route_do("scroll down")
        time.sleep(1.0)
        after = runner.chrome_proc_count()
        self.assertLessEqual(after, base + 2,
                             f"process leak over 20 calls: {base} -> {after}")
        self.assertTrue(runner.chrome_available(), "CDP died during the 20-call loop")

    def test_f_repeat_determinism_three_times(self):
        """PRD discipline: same scenario 3x must give the same result."""
        router.route_open(_FX.url("/big"))
        shas = []
        for _ in range(3):
            r = router.route_see(kind="a11y")
            J.assert_verdict(self, J.judge_a11y(r, task="see(repeat)"))
            shas.append(r["sha256"])
        self.assertEqual(len(set(shas)), 1,
                         f"a11y serialization not reproducible across repeats: {shas}")


if __name__ == "__main__":
    unittest.main()

"""L1 tests for hand 0.7.0 S5 — macOS Chrome discovery layer (F8).

PRD docs/prd-ax-perception.md S5. No browser and no Mac needed: platform and
filesystem are mocked.

Cotton 935: the old wrapper hard-coded /Applications/Google Chrome.app; the path
was real, the wire was not connected. These tests pin it into the regular chain.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.perception.cdp_launcher as cdp_launcher


class TestMacOSDiscovery(unittest.TestCase):
    """F8: non-Windows discovery was all Linux-shaped."""

    CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    def _find(self, platform, existing, which=None):
        def isfile(p):
            return p in existing

        with mock.patch("sys.platform", platform), \
             mock.patch.object(os.path, "isfile", side_effect=isfile), \
             mock.patch.object(os.path, "isdir", return_value=False), \
             mock.patch.object(cdp_launcher.shutil, "which",
                               side_effect=lambda name: (which or {}).get(name)), \
             mock.patch.dict(os.environ, {"HOME": "/Users/tester"}, clear=False):
            os.environ.pop("CHROME", None)
            return cdp_launcher._find_chrome()

    def test_macos_chrome_app_path(self):
        self.assertEqual(self._find("darwin", {self.CHROME}), self.CHROME)

    def test_macos_ignores_paths_that_do_not_exist(self):
        self.assertIsNone(self._find("darwin", set()))

    def test_macos_prefers_chrome_over_chromium(self):
        chromium = "/Applications/Chromium.app/Contents/MacOS/Chromium"
        self.assertEqual(self._find("darwin", {self.CHROME, chromium}), self.CHROME)

    def test_macos_falls_through_to_chromium_then_path(self):
        chromium = "/Applications/Chromium.app/Contents/MacOS/Chromium"
        self.assertEqual(self._find("darwin", {chromium}), chromium)
        self.assertEqual(self._find("darwin", set(), which={"google-chrome": "/usr/local/bin/google-chrome"}),
                         "/usr/local/bin/google-chrome")

    def test_env_override_still_wins_on_macos(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            env_chrome = f.name
        try:
            with mock.patch("sys.platform", "darwin"), \
                 mock.patch.dict(os.environ, {"CHROME": env_chrome}):
                self.assertEqual(cdp_launcher._find_chrome(), env_chrome)
        finally:
            os.unlink(env_chrome)

    def test_windows_chain_is_unchanged(self):
        win = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        self.assertEqual(self._find("win32", {win}), win)


if __name__ == "__main__":
    unittest.main()

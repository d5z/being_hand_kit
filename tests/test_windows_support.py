"""L1 unit tests for Hand v6.10.0 Windows support.

All tests mock the platform (sys.platform) and the CDP/PowerShell touch
points; nothing here needs a real Windows machine or a live browser.
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.perception.cdp_launcher as cdp_launcher
import hand.router as router
from hand.session import Place, get_session, reset_session
from hand.place import detect as place_detect


class TestWindowsSupport(unittest.TestCase):

    def test_find_chrome_windows(self):
        # 1) $CHROME wins even on Windows
        with tempfile.NamedTemporaryFile(delete=False) as f:
            chrome_env = f.name
        try:
            with mock.patch.dict(os.environ, {"CHROME": chrome_env}):
                with mock.patch("sys.platform", "win32"):
                    self.assertEqual(cdp_launcher._find_chrome(), chrome_env)
        finally:
            os.unlink(chrome_env)

        # 2) Install paths are probed before PATH, Chrome install before Edge install
        existing = {
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        }
        with mock.patch.dict(os.environ, {"CHROME": "", "LOCALAPPDATA": "C:\\Users\\alice\\AppData\\Local"}):
            with mock.patch("sys.platform", "win32"):
                with mock.patch.object(os.path, "isfile", side_effect=lambda p: p in existing):
                    with mock.patch("shutil.which", return_value=r"C:\Temp\fake_chrome.exe") as mock_which:
                        found = cdp_launcher._find_chrome()
                        self.assertEqual(found, r"C:\Program Files\Google\Chrome\Application\chrome.exe")
                        mock_which.assert_not_called()

        # 3) PATH fallback finds msedge.exe when chrome.exe is absent
        with mock.patch.dict(os.environ, {"CHROME": "", "LOCALAPPDATA": ""}):
            with mock.patch("sys.platform", "win32"):
                with mock.patch.object(os.path, "isfile", return_value=False):
                    with mock.patch(
                        "shutil.which",
                        side_effect=lambda name: r"C:\Windows\SystemApps\msedge.exe" if name == "msedge.exe" else None,
                    ) as mock_which:
                        found = cdp_launcher._find_chrome()
                        self.assertEqual(found, r"C:\Windows\SystemApps\msedge.exe")
                        self.assertEqual([c.args[0] for c in mock_which.call_args_list], ["chrome.exe", "msedge.exe"])

    def test_see_priority_unknown(self):
        # win32 (same filtering as this Linux runner): CDP backends present, mac-only dropped
        try:
            with mock.patch.object(__import__("hand.platform", fromlist=["PLATFORM"]), "PLATFORM", "win32"):
                router_win = importlib.reload(router)
                self.assertEqual(
                    router_win.SEE_PRIORITY["unknown"],
                    ["cdp_dom", "cdp_interactive"],
                )
                self.assertIn("cdp_dom", router_win.SEE_PRIORITY["unknown"])
            # darwin: mac-only tail preserved (vision_ocr before ax_ui)
            with mock.patch.object(__import__("hand.platform", fromlist=["PLATFORM"]), "PLATFORM", "darwin"):
                router_darwin = importlib.reload(router)
                self.assertEqual(
                    router_darwin.SEE_PRIORITY["unknown"],
                    ["cdp_dom", "cdp_interactive", "vision_ocr", "ax_ui"],
                )
                self.assertLess(
                    router_darwin.SEE_PRIORITY["unknown"].index("vision_ocr"),
                    router_darwin.SEE_PRIORITY["unknown"].index("ax_ui"),
                )
        finally:
            importlib.reload(router)

    @mock.patch(
        "hand.perception.cdp_snapshot.cdp_snapshot_see",
        return_value={"method": "cdp_snapshot", "text": "window text"},
    )
    @mock.patch(
        "hand.perception.cdp_core.list_pages",
        return_value=[{"id": "1", "type": "page", "webSocketDebuggerUrl": "ws://localhost/1"}],
    )
    def test_route_see_unknown_probes_cdp(self, mock_list_pages, mock_cdp_snapshot_see):
        reset_session()
        result = router.route_see(place=Place(type="unknown", identifier="stale"))
        self.assertEqual(result.get("method"), "cdp_snapshot")
        self.assertEqual(result.get("text"), "window text")
        self.assertEqual(get_session().place.type, "browser")
        self.assertEqual(get_session().place.identifier, "cdp-detected")
        mock_list_pages.assert_called_once()
        mock_cdp_snapshot_see.assert_called_once()

    def test_open_place_honest_failure(self):
        # 1) No browser binary: ensure_chrome's RuntimeError must propagate.
        with mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=False) as mock_chrome_running, \
             mock.patch(
                 "hand.perception.cdp_launcher.ensure_chrome",
                 side_effect=RuntimeError("no chrome binary found — set $CHROME or install Chrome/Edge"),
             ) as mock_ensure_chrome:
            with self.assertRaises(RuntimeError) as ctx:
                place_detect.open_place("https://example.com")
            self.assertIn("$CHROME", str(ctx.exception))
            mock_chrome_running.assert_called_once()
            mock_ensure_chrome.assert_called_once()

        # 2) ensure_chrome did not raise, but navigation failed and no live
        #    CDP endpoint survived → the new last-resort gate must raise.
        with mock.patch(
            "hand.perception.cdp_launcher.chrome_running",
            side_effect=[False, False],
        ) as mock_chrome_running, \
             mock.patch("hand.perception.cdp_launcher.ensure_chrome", return_value=None) as mock_ensure_chrome, \
             mock.patch(
                 "hand.perception.cdp_core.list_pages",
                 side_effect=RuntimeError("CDP unreachable"),
             ):
            with self.assertRaises(RuntimeError) as ctx:
                place_detect.open_place("https://example.com")
            self.assertIn("cannot open ", str(ctx.exception))
            self.assertIn("$CHROME", str(ctx.exception))

    @mock.patch(
        "hand.perception.cdp_core.list_pages",
        side_effect=RuntimeError("CDP unreachable"),
    )
    @mock.patch("hand.perception.cdp_launcher.chrome_running", return_value=True)
    def test_open_place_fallback_when_alive(self, mock_chrome_running, mock_list_pages):
        place = place_detect.open_place("https://example.com")
        self.assertEqual(place.type, "browser")
        self.assertEqual(place.identifier, "https://example.com")
        mock_chrome_running.assert_called()

    def test_detect_place_windows(self):
        def run_with_output(output):
            return mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=output
            ))

        with mock.patch("sys.platform", "win32"):
            with run_with_output("chrome\r\n"):
                place = place_detect.detect_place()
                self.assertEqual(place.type, "browser")
                self.assertEqual(place.identifier, "chrome")

            with run_with_output("Notepad\r\n"):
                place = place_detect.detect_place()
                self.assertEqual(place.type, "desktop_app")
                self.assertEqual(place.identifier, "notepad")

            with run_with_output(""):
                place = place_detect.detect_place()
                self.assertEqual(place.type, "unknown")
                self.assertIsNone(place.identifier)

            with mock.patch("subprocess.run", side_effect=FileNotFoundError("no powershell")):
                place = place_detect.detect_place()
                self.assertEqual(place.type, "unknown")
                self.assertIsNone(place.identifier)

    def test_manifest_platforms(self):
        manifest_path = os.path.join(os.path.dirname(__file__), "..", "kit", "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        self.assertEqual(manifest.get("version"), "6.11.0")
        supported = manifest["platforms"]["supported"]
        backend = manifest["platforms"]["backend_matrix"]
        self.assertIn("windows", supported)
        self.assertIn("windows", backend["cdp"])
        # supported platforms must all be covered by at least one backend
        covered = set()
        for platforms in backend.values():
            covered.update(platforms)
        self.assertTrue(set(supported).issubset(covered))


if __name__ == "__main__":
    unittest.main()

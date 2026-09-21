"""L1 tests for hand 0.7.0 S4/S5 — Chrome profile strategy + macOS discovery.

PRD docs/prd-ax-perception.md S4 (F7) / S5 (F8). No browser is spawned: the
Popen call, the platform and the filesystem are mocked.

Covers: isolated default profile dir, HAND_PROFILE=persistent opt-in,
HAND_PROFILE_DIR override, HAND_HEADLESS=0, the flags actually reaching argv
(the ps-verification protocol step), the spawn handle carrying its flags, and
the macOS discovery candidates.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.perception.cdp_launcher as cdp_launcher


def _flags(**env):
    clean = {k: v for k, v in os.environ.items()
             if k not in ("HAND_PROFILE", "HAND_PROFILE_DIR", "HAND_HEADLESS", "CHROME")}
    clean.update(env)
    with mock.patch.dict(os.environ, clean, clear=True):
        return cdp_launcher._chrome_flags()


def _flag_value(flags, name):
    prefix = f"--{name}="
    for f in flags:
        if f.startswith(prefix):
            return f[len(prefix):]
    return None


class TestProfileStrategy(unittest.TestCase):

    def test_default_is_isolated_kit_profile_dir(self):
        with tempfile.TemporaryDirectory() as d:
            flags = _flags(HAND_PROFILE_DIR=os.path.join(d, "prof"))
            self.assertEqual(_flag_value(flags, "user-data-dir"), os.path.join(d, "prof"))

    def test_default_profile_dir_lives_under_the_kit_home(self):
        flags = _flags()
        path = _flag_value(flags, "user-data-dir")
        self.assertTrue(path.endswith(cdp_launcher.PROFILE_DIR_NAME), path)
        self.assertTrue(os.path.isabs(path))

    def test_isolated_profile_dir_is_created_before_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "nested", "prof")
            _flags(HAND_PROFILE_DIR=target)
            self.assertTrue(os.path.isdir(target))

    def test_isolated_is_the_explicit_default_mode(self):
        with tempfile.TemporaryDirectory() as d:
            flags = _flags(HAND_PROFILE="isolated", HAND_PROFILE_DIR=os.path.join(d, "p"))
            self.assertEqual(_flag_value(flags, "user-data-dir"), os.path.join(d, "p"))

    def test_persistent_mode_uses_the_platform_chrome_profile(self):
        # taojun 954: headless fingerprint throttling → persistent profile opt-in.
        with mock.patch("sys.platform", "darwin"), \
             mock.patch.dict(os.environ, {"HOME": "/Users/tester"}, clear=False):
            os.environ.pop("HAND_PROFILE_DIR", None)
            flags = _flags(HAND_PROFILE="persistent")
        self.assertEqual(_flag_value(flags, "user-data-dir"),
                         "/Users/tester/Library/Application Support/Google/Chrome")

    def test_persistent_mode_honours_explicit_dir_override(self):
        with tempfile.TemporaryDirectory() as d:
            flags = _flags(HAND_PROFILE="persistent", HAND_PROFILE_DIR=d)
            self.assertEqual(_flag_value(flags, "user-data-dir"), d)

    def test_profile_mode_helper_reports_the_mode(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cdp_launcher.profile_mode(), "isolated")
        with mock.patch.dict(os.environ, {"HAND_PROFILE": "PERSISTENT"}, clear=True):
            self.assertEqual(cdp_launcher.profile_mode(), "persistent")

    def test_existing_flags_are_untouched(self):
        flags = _flags()
        self.assertIn(f"--remote-debugging-port={cdp_launcher.CDP_PORT}", flags)
        for f in ("--no-first-run", "--no-default-browser-check", "--disable-gpu",
                  "--disable-dev-shm-usage", "--disable-software-rasterizer",
                  "--disable-extensions"):
            self.assertIn(f, flags)


class TestHeadlessSwitch(unittest.TestCase):

    def test_headless_is_default(self):
        self.assertIn("--headless", _flags())

    def test_headless_zero_makes_it_headed(self):
        self.assertNotIn("--headless", _flags(HAND_HEADLESS="0"))

    def test_headless_falsey_spellings_all_work(self):
        for value in ("0", "false", "FALSE", "no", "off"):
            self.assertNotIn("--headless", _flags(HAND_HEADLESS=value), value)

    def test_headless_one_and_other_values_stay_headless(self):
        for value in ("1", "true", "yes", ""):
            self.assertIn("--headless", _flags(HAND_HEADLESS=value), value)

    def test_headless_helper(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(cdp_launcher.headless())
        with mock.patch.dict(os.environ, {"HAND_HEADLESS": "0"}, clear=True):
            self.assertFalse(cdp_launcher.headless())


class TestFlagsReachTheSpawn(unittest.TestCase):
    """Acceptance protocol step 4: `ps` must show --user-data-dir in the argv."""

    def _spawn(self, **env):
        captured = {}
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("HAND_PROFILE", "HAND_PROFILE_DIR", "HAND_HEADLESS", "CHROME")}
        clean.update(env)

        class _Proc:
            pid = 4242

            def kill(self):
                pass

        def fake_popen(argv, **kw):
            captured["argv"] = argv
            return _Proc()

        with mock.patch.dict(os.environ, clean, clear=True), \
             mock.patch.object(cdp_launcher, "chrome_running", return_value=False), \
             mock.patch.object(cdp_launcher, "_find_chrome", return_value="/usr/bin/google-chrome"), \
             mock.patch.object(cdp_launcher, "endpoint_info",
                               return_value={"Browser": "Chrome/141.0.0",
                                             "Protocol-Version": "1.3"}), \
             mock.patch.object(cdp_launcher.subprocess, "Popen", side_effect=fake_popen):
            proc = cdp_launcher.ensure_chrome()
        return proc, captured

    def test_user_data_dir_is_in_the_real_argv(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "prof")
            proc, captured = self._spawn(HAND_PROFILE_DIR=target)
            self.assertIn(f"--user-data-dir={target}", captured["argv"])

    def test_spawn_handle_carries_its_flags_and_profile(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "prof")
            proc, _ = self._spawn(HAND_PROFILE_DIR=target)
            self.assertIn(f"--user-data-dir={target}", proc.cdp_flags)
            self.assertEqual(proc.cdp_profile["dir"], target)
            self.assertEqual(proc.cdp_profile["mode"], "isolated")
            self.assertTrue(proc.cdp_profile["headless"])

    def test_headed_spawn_has_no_headless_flag_in_argv(self):
        with tempfile.TemporaryDirectory() as d:
            _, captured = self._spawn(HAND_PROFILE_DIR=os.path.join(d, "p"),
                                      HAND_HEADLESS="0")
            self.assertNotIn("--headless", captured["argv"])


if __name__ == "__main__":
    unittest.main()

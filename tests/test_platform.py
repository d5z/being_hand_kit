"""Unit tests for hand.platform: constant + predicates.

Run with: python3 tests/run_tests.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hand.platform import PLATFORM, is_macos, is_linux


class TestPlatform(unittest.TestCase):

    def test_platform_is_known(self):
        self.assertIn(PLATFORM, ("darwin", "linux", "windows"))

    def test_macos_predicate_matches_constant(self):
        self.assertEqual(is_macos(), PLATFORM == "darwin")

    def test_linux_predicate_matches_constant(self):
        self.assertEqual(is_linux(), PLATFORM == "linux")

    def test_predicates_are_mutually_exclusive(self):
        self.assertFalse(is_macos() and is_linux())

    def test_platform_is_detected_from_system(self):
        import platform as _pyplatform
        self.assertEqual(PLATFORM, _pyplatform.system().lower())


if __name__ == "__main__":
    unittest.main()

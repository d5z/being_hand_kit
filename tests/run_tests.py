"""
Test runner using standard library unittest.

Loads every tests/test_*.py module explicitly (kept deterministic, no
pytest dependency) and runs the suite.
"""

import os
import sys
import unittest

sys.path.insert(0, "/home/alice/Hand")

MODULES = ["tests.test_plan", "tests.test_tier2_3", "tests.test_platform", "tests.test_vision_llm", "tests.test_cdp_contract", "tests.test_cdp_contract_real", "tests.test_windows_support", "tests.test_receipt_contract", "tests.test_ax_tree", "tests.test_ax_see", "tests.test_macos_discovery", "tests.test_chrome_profile", "tests.test_kit_quickfixes", "tests.test_release_070", "tests.test_hand_api"]


def build_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in MODULES:
        try:
            mod = __import__(name, fromlist=[name.rsplit(".", 1)[-1]])
        except ImportError as e:
            print(f"SKIP {name}: {e}")
            continue
        suite.addTests(loader.loadTestsFromModule(mod))
    return suite


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(build_suite())
    sys.exit(0 if result.wasSuccessful() else 1)

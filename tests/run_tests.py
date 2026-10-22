"""
Test runner using standard library unittest.

Loads every tests/test_*.py module explicitly (kept deterministic, no
pytest dependency) and runs the suite.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hermetic session state: a test run must not read or overwrite the CDP
# session-page record the operator's browser is actually using. See
# tests/harness/__init__.py for the same rule on the package-import path.
os.environ.setdefault(
    "HAND_CDP_STATE_FILE",
    os.path.join(tempfile.gettempdir(), "hand_cdp_last_idx_tests"),
)


MODULES = ["tests.test_plan", "tests.test_tier2_3", "tests.test_platform", "tests.test_vision_llm", "tests.test_cdp_contract", "tests.test_cdp_contract_real", "tests.test_page_identity", "tests.test_windows_support", "tests.test_receipt_contract", "tests.test_truncation", "tests.test_ax_tree", "tests.test_ax_see", "tests.test_macos_discovery", "tests.test_chrome_profile", "tests.test_kit_quickfixes", "tests.test_release_070", "tests.test_release_080", "tests.test_release_097", "tests.test_release_098", "tests.test_release_0100", "tests.test_release_chain", "tests.test_hand_api", "tests.test_visual_state", "tests.test_ocr_diff", "tests.test_expect_spec", "tests.test_viewport_alignment", "tests.test_text_match", "tests.test_enter_submit", "tests.test_handle_staleness", "tests.test_heading_redirect", "tests.test_clickable_point", "tests.test_eye_check", "tests.test_emitted", "tests.test_action_primitives", "tests.test_release_0110", "tests.test_frame_diff", "tests.test_effect", "tests.test_release_0120", "tests.test_release_0130", "tests.test_iframe_coords", "tests.test_release_0131", "tests.test_iframe_transform", "tests.test_release_0132"]


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

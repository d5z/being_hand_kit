"""L1 tests for hand 0.9.8 — current version (shipped 2026-10-12).

0.9.8 shipped (Windows 生产化轮): the win32 error-message fix (F27 补刀 —
the finder's Windows chain never reads the Playwright cache, so "install
playwright chromium" was a dead-end direction; the honest direction is
Chrome/Edge), the cdp_shot timeout family closed by the five-cell matrix
(超时条件 = Windows × headless-shell, old-headless rendering pipeline —
#34 2271-2299), the Windows install-pit README section (Judy ①②③), the
feedback-ledger closeouts F27/F28/F29, and the zombie-test rework
(test_release_080 → historical lock + 097 backfill + this chain).

Historical lock — 0.9.8 shipped 2026-10-12. Current-version assertions
moved to test_release_0100 at the 0.10.0 bump (see test_release_chain).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


class TestVersion098(unittest.TestCase):
    """Historical lock: 0.9.8 shipped 2026-10-12. The version itself has
    since moved on — current-version assertions live in
    test_release_0100 (see test_release_chain for the rule)."""

    def test_changelog_entry_is_dated(self):
        body = _read("CHANGELOG.md")
        self.assertIn("## [0.9.8] — 2026-10-12", body)

    def test_spec_or_docs_still_reference_098_fix(self):
        body = _read(os.path.join("hand", "perception", "cdp_launcher.py"))
        self.assertIn("no chrome binary found on Windows", body)


class TestChangelog098(unittest.TestCase):
    def setUp(self):
        self.body = _read("CHANGELOG.md")
        start = self.body.index("## [0.9.8]")
        nxt = self.body.find("\n## [", start + 1)
        self.entry = self.body[start:nxt if nxt != -1 else None]

    def test_entry_exists(self):
        self.assertIn("## [0.9.8]", self.body)

    def test_entry_covers_win32_message_fix(self):
        self.assertIn("win32", self.entry)
        self.assertIn("Chrome/Edge", self.entry)

    def test_entry_covers_five_cell_matrix(self):
        self.assertIn("五格矩阵", self.entry)
        self.assertIn("headless-shell", self.entry)

    def test_entry_credits_community(self):
        for name in ("Noah", "taojun", "Judy"):
            self.assertIn(name, self.entry)

    def test_previous_entries_survive(self):
        for needle in ("## [0.9.7]", "## [0.9.6]", "## [0.8.0]", "## [0.7.0]"):
            self.assertIn(needle, self.body, needle)


class TestWin32Message098(unittest.TestCase):
    """The F27 fix: the win32 error must point at Chrome/Edge, not Playwright."""

    def test_win32_branch_has_its_own_message(self):
        body = _read(os.path.join("hand", "perception", "cdp_launcher.py"))
        self.assertIn("no chrome binary found on Windows", body)
        self.assertIn("deliberately skips the", body)

    def test_win32_message_direction(self):
        # The regression lock lives in test_windows_support
        # (test_open_place_error_direction_win32); here we only pin that the
        # shared (non-win32) message still mentions the Playwright fallback,
        # which *is* reachable on posix.
        body = _read(os.path.join("hand", "perception", "cdp_launcher.py"))
        self.assertIn("install playwright chromium", body)


class TestReadmeWindows098(unittest.TestCase):
    """The Windows install-pit section is Grove-facing documentation."""

    def test_windows_pit_section_present(self):
        body = _read("kit/README.md")
        self.assertIn("Windows 安装已知坑", body)

    def test_wsl_stub_workaround_present(self):
        body = _read("kit/README.md")
        self.assertIn("WSL stub", body)
        self.assertIn("Git Bash", body)


if __name__ == "__main__":
    unittest.main()

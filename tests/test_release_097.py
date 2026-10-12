"""L1 tests for hand 0.9.7 — historical lock (shipped 2026-09-28, 9f622f7).

0.9.7 shipped: F22 cdp_type post-flight read-back (pre-flight editability
refusal + read-back + pre-Enter re-read; Judy's diff applied as d80cde0),
the Judy-authored setup_guide backup wording (kits/ backup trap, double
experiment attribution), Grove 77-file scrubbed bundle, 415 tests green.

This file locks what shipped. Current-version assertions follow the bump
(test_release_chain enforces the file exists for the current version).

Backfilled 2026-10-12 during 0.9.8: 0.9.7 shipped without its own release
test file (0.9.0-0.9.7 all shipped without one — the chain was broken
after 0.8.0's file turned zombie). This backfill closes the gap for the
current version; older gaps (0.9.0-0.9.6) stay covered by CHANGELOG only.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


class TestChangelog097(unittest.TestCase):
    def setUp(self):
        self.body = _read("CHANGELOG.md")
        start = self.body.index("## [0.9.7]")
        nxt = self.body.find("\n## [", start + 1)
        self.entry = self.body[start:nxt if nxt != -1 else None]

    def test_entry_exists(self):
        self.assertIn("## [0.9.7]", self.body)

    def test_entry_covers_f22_read_back(self):
        self.assertIn("read-back", self.entry)
        self.assertIn("F22", self.entry)

    def test_entry_covers_setup_guide_backup_wording(self):
        self.assertIn("备份", self.entry)
        self.assertIn("Judy", self.entry)

    def test_previous_entries_survive(self):
        for needle in ("## [0.9.6]", "## [0.8.0]", "## [0.7.0]"):
            self.assertIn(needle, self.body, needle)


class TestManifest097(unittest.TestCase):
    """The F22 read-back contract is declared in the manifest tool surface."""

    def test_cdp_type_declares_read_back(self):
        import json
        with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        tools = {t["name"]: t for t in manifest["tools"]}
        self.assertIn("read-back", tools["cdp_type"]["description"])
        self.assertEqual(tools["cdp_type"]["evidence"], "verified")


class TestSetupGuide097(unittest.TestCase):
    """The Judy-authored upgrade section lives in the Grove-facing guide."""

    def test_upgrade_section_present(self):
        body = _read("kit/README.md")
        self.assertIn("## 升级影响（0.9.6 → 0.9.7）", body)

    def test_backup_rule_present(self):
        body = _read("kit/README.md")
        self.assertIn("kits/", body)
        self.assertIn("bak", body)


if __name__ == "__main__":
    unittest.main()

"""L1 tests for hand 0.8.0 S5 — version + manifest + release note + S4 gate.

PRD docs/prd-0.8-code-mode.md S5: the release commit bumps package version to
0.8.0 (dev suffix dropped), manifest to 0.8.0, SPEC version table row flips to
released; the changelog entry covers code mode (S1-S3), the a11y-v2.1 contract
fix (S4 subject-1 finding #2) and the README documentation holes (findings
#1/#3-#8).
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANIFEST = os.path.join(ROOT, "kit", "manifest.json")


def _manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


class TestVersion(unittest.TestCase):
    def test_package_version_is_released(self):
        import hand
        self.assertEqual(hand.__version__, "0.8.0")

    def test_manifest_version_is_released(self):
        self.assertEqual(_manifest()["version"], "0.8.0")

    def test_spec_version_table_row(self):
        with open(os.path.join(ROOT, "SPEC.md"), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("| V0.8.0 |", body)
        self.assertIn("released", body.split("| V0.8.0 |")[1].split("\n")[0])


class TestReleaseNote(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            self.body = f.read()

    def test_changelog_has_the_entry(self):
        self.assertIn("## [0.8.0]", self.body)

    def test_entry_covers_the_blocks(self):
        entry = self.body[self.body.index("## [0.8.0]"):]
        entry = entry[:entry.index("\n## [")] if "\n## [" in entry else entry
        for needle in ("code mode", "Python face", "expect=", "a11y-v2.1",
                       "text_truncated_count", "MAX_NAME", "README"):
            self.assertIn(needle, entry, needle)

    def test_a11y_v21_contract_fix_is_described(self):
        entry = self.body[self.body.index("## [0.8.0]"):]
        entry = entry[:entry.index("\n## [")] if "\n## [" in entry else entry
        self.assertIn("60", entry)          # the old silent cut
        self.assertIn("200", entry)         # the new declared limit

    def test_previous_entry_survives(self):
        self.assertIn("## [0.7.0]", self.body)


class TestS4GateEvidence(unittest.TestCase):
    """The S4 subject reports are the release gate's raw material — they stay
    in the repo (S4-subject-1-report.md caught the v2 contract hole)."""

    def test_subject1_report_is_committed(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "S4-subject-1-report.md")))

    def test_ax_format_version_is_v21(self):
        from hand.perception.ax_tree import AX_FORMAT_VERSION
        self.assertEqual(AX_FORMAT_VERSION, "a11y-v2.1")


if __name__ == "__main__":
    unittest.main()

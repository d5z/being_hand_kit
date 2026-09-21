"""L1 tests for hand 0.7.0 S7 — manifest + version + release note + F15 review.

PRD docs/prd-ax-perception.md S7: manifest.json version 0.7.0; the tool surface
declares what actually shipped (a11y default, [idx] handles); F15 (cdp_type fast
path is replace, not append) re-checked; release note says out loud that this is
a version-line reset.
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


def _tools():
    return {t["name"]: t for t in _manifest()["tools"]}


class TestVersion(unittest.TestCase):
    def test_package_version(self):
        import hand
        self.assertEqual(hand.__version__, "0.7.0")

    def test_manifest_version_matches_the_package(self):
        import hand
        self.assertEqual(_manifest()["version"], hand.__version__)

    def test_spec_version_table_row(self):
        with open(os.path.join(ROOT, "SPEC.md"), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("| V0.7.0 |", body)
        self.assertIn("AX 感知层", body)


class TestManifestSurface(unittest.TestCase):
    """The manifest must describe the 0.7.0 tool surface, not the 6.11.0 one."""

    def setUp(self):
        self.tools = _tools()

    def test_see_declares_a11y_as_the_default_kind(self):
        see = self.tools["cdp_see"]
        enum = see["params"]["properties"]["kind"]["enum"]
        self.assertIn("a11y", enum)
        self.assertIn("interactive", enum)
        self.assertIn("dom", enum)
        self.assertIn("network", enum)
        self.assertIn("a11y", see["description"])
        self.assertIn("default", see["description"].lower())
        self.assertIn("idx", see["description"])

    def test_click_declares_idx_handles(self):
        click = self.tools["cdp_click"]
        self.assertIn("[idx]", click["description"])
        self.assertEqual(click["idempotency"], "side_effect")

    def test_type_declares_the_handle_flow(self):
        typ = self.tools["cdp_type"]
        self.assertIn("focus", typ["description"].lower())
        self.assertIn("[idx]", typ["description"])

    def test_f15_idempotency_note_for_type(self):
        """F15: the flat `append` label would go stale because the internal fast
        path replaces the whole value. The label is now path-split in writing."""
        note = self.tools["cdp_type"]["idempotency_note"]
        self.assertIn("append", note)
        self.assertIn("replace", note)
        self.assertIn("fast", note)
        self.assertEqual(self.tools["cdp_type"]["idempotency"], "append")

    def test_manifest_still_declares_idempotency_and_evidence_for_every_tool(self):
        for name, tool in self.tools.items():
            self.assertIn("idempotency", tool, name)
            self.assertIn("evidence", tool, name)

    def test_see_is_still_declared_idempotent_verified(self):
        self.assertEqual(self.tools["cdp_see"]["idempotency"], "idempotent")
        self.assertEqual(self.tools["cdp_see"]["evidence"], "verified")

    def test_description_keeps_the_receipt_contract_sentence(self):
        self.assertIn("Receipts distinguish verified vs claimed",
                      _manifest()["description"])


class TestReleaseNote(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            self.body = f.read()

    def test_changelog_has_the_entry(self):
        self.assertIn("## [0.7.0]", self.body)

    def test_version_line_reset_is_the_first_thing_it_says(self):
        """PRD risk note: a version-line reset changes Grove ordering, so the
        release note has to say it up front."""
        head = self.body[self.body.index("## [0.7.0]"):]
        head = head[:head.index("####")]
        self.assertIn("版本线重置", head)
        self.assertIn("6.11.0", head)

    def test_entry_covers_the_blocks(self):
        entry = self.body[self.body.index("## [0.7.0]"):]
        entry = entry[:entry.index("\n## [")]
        for needle in ("a11y", "AX", "[idx]", "F7", "F8", "F9", "F15",
                       "chrome-wrapper.sh", ".chrome-profile", "确定性"):
            self.assertIn(needle, entry, needle)

    def test_previous_entry_survives(self):
        self.assertIn("## [6.11.0]", self.body)


class TestFeedbackLedgerUpdated(unittest.TestCase):
    """A release that closes F7-F13/F15 should say so in the ledger."""

    def setUp(self):
        with open(os.path.join(ROOT, "docs", "feedback-ledger.md"), encoding="utf-8") as f:
            self.body = f.read()

    def test_closed_items_are_marked_for_070(self):
        for fid in ("F7", "F8", "F9", "F10", "F11", "F12", "F13", "F15"):
            row = [l for l in self.body.splitlines() if l.startswith(f"| {fid} |")]
            self.assertTrue(row, fid)
            self.assertIn("0.7.0", row[0], f"{fid} not marked as closed in 0.7.0")


if __name__ == "__main__":
    unittest.main()

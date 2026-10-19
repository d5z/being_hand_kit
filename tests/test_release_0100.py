"""L1 tests for hand 0.10.0 — current version (shipped 2026-10-19).

0.10 ships 交付诚实 (docs/prd-delivery-honesty.md): the fourth axis of
perception — did the evidence reach the caller?

  D1  emitted — the receipt's first paragraph is a signature of what hand put
      INTO the receipt (image / tree / text). hand speaks only for itself:
      `hand 只声明 emitted`, `delivery` is the portal/heart's to add.
  D3  blank 判据要求视觉证据 — DOM only nominates "blank", a pixel vote
      settles it; no vote -> `unknown` + `pixel-unavailable`, never blank.
  D4  hand_eye_check — a being-side self-proof that rendered pixels actually
      reached the caller's context (canvas-rendered random string, never in
      the receipt / DOM / title / page source).
  D5/D6 data-gated (not in this release).

This file holds the current-version assertions.
test_release_chain enforces this file exists while hand.__version__ == 0.10.0.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def _manifest():
    with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


class TestVersion0100(unittest.TestCase):
    """Historical lock (0.11.0 turned this from a current-version assertion
    into a chain link): 0.10.0 must stay a released version in the chain."""

    def test_version_is_at_least_0100(self):
        import hand
        parts = [int(x) for x in hand.__version__.split(".")]
        self.assertGreaterEqual(parts, [0, 10, 0])

    def test_manifest_version_matches_package(self):
        import hand
        self.assertEqual(_manifest()["version"], hand.__version__)


class TestChangelog0100(unittest.TestCase):
    def setUp(self):
        self.body = _read("CHANGELOG.md")
        start = self.body.index("## [0.10.0]")
        nxt = self.body.find("\n## [", start + 1)
        self.entry = self.body[start:nxt if nxt != -1 else None]

    def test_entry_exists(self):
        self.assertIn("## [0.10.0]", self.body)

    def test_entry_covers_emitted(self):
        self.assertIn("emitted", self.entry)
        # the boundary must be stated in the release note, not just in code
        self.assertIn("delivery", self.entry)

    def test_entry_covers_pixel_vote_and_eye_check(self):
        for needle in ("hand_eye_check", "像素票", "blank"):
            self.assertIn(needle, self.entry, needle)

    def test_entry_covers_delivery_honesty_prd(self):
        self.assertIn("prd-delivery-honesty", self.entry)

    def test_previous_entries_survive(self):
        for needle in ("## [0.9.8]", "## [0.9.7]", "## [0.9.6]",
                       "## [0.8.0]", "## [0.7.0]"):
            self.assertIn(needle, self.body, needle)


class TestManifestTools0100(unittest.TestCase):
    """D4 is a Grove-declared tool, not a private helper."""

    def test_eye_check_declared(self):
        tools = {t["name"]: t for t in _manifest()["tools"]}
        self.assertIn("hand_eye_check", tools)
        self.assertEqual(tools["hand_eye_check"]["evidence"], "verified")

    def test_eye_check_params_are_ops(self):
        tools = {t["name"]: t for t in _manifest()["tools"]}
        props = tools["hand_eye_check"]["params"]["properties"]
        for key in ("op", "challenge_id", "answer"):
            self.assertIn(key, props, key)


class TestDeliveryHonestyDocs(unittest.TestCase):
    """The PRD is the contract this release is accountable to."""

    def test_prd_present(self):
        body = _read(os.path.join("docs", "prd-delivery-honesty.md"))
        self.assertIn("D1", body)
        self.assertIn("D4", body)

    def test_emitted_boundary_is_documented(self):
        body = _read(os.path.join("docs", "prd-delivery-honesty.md"))
        self.assertIn("emitted", body)
        self.assertIn("delivered", body)


if __name__ == "__main__":
    unittest.main()

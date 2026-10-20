"""Release test for 0.11.0 — 动作原语与变化可判定.

Spec: docs/prd-0.11-action-primitives.md

This file is the ONLY place allowed to assert the current version number
(tests/test_release_chain.py enforces that a bump without this file goes red).

What 0.11.0 must keep true:
  * two new primitives exist and are declared in the manifest — and both are
    declared `claimed`, never `verified`, because a drag or a key press has no
    read-back in this version;
  * the three-state receipt never claims a change it did not observe:
    `effected` is always 'unknown', and `landed: null` is a distinct answer
    from `landed: false`;
  * malformed key combos are refused outright instead of dispatching a guess.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import cdp_act as A

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _manifest():
    with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestVersion0110(unittest.TestCase):
    """Historical lock (0.12.0 turned this from a current-version assertion
    into a chain link): 0.11.0 must stay a released version in the chain."""

    def test_version_is_at_least_0110(self):
        import hand
        parts = [int(x) for x in hand.__version__.split(".")]
        self.assertGreaterEqual(parts, [0, 11, 0])

    def test_manifest_version_matches_package(self):
        import hand
        self.assertEqual(_manifest()["version"], hand.__version__)


class TestManifestDeclaresPrimitives(unittest.TestCase):
    def setUp(self):
        self.tools = {t["name"]: t for t in _manifest()["tools"]}

    def test_both_primitives_are_declared(self):
        for name in ("cdp_drag", "cdp_key"):
            self.assertIn(name, self.tools)

    def test_primitives_declare_side_effect_and_claimed(self):
        for name in ("cdp_drag", "cdp_key"):
            self.assertEqual(self.tools[name]["idempotency"], "side_effect", name)
            # 'verified' here would be a lie: effected is unknown in 0.11.
            self.assertEqual(self.tools[name]["evidence"], "claimed", name)


class TestThreeStateContract(unittest.TestCase):
    def test_effected_is_never_a_claimed_change(self):
        for resolved, landed in ((True, True), (True, False), (False, None)):
            state = A._three_state(resolved, landed)
            self.assertEqual(state["effected"], "unknown")
            self.assertTrue(state["effected_reason"])

    def test_landed_none_is_not_false(self):
        state = A._three_state(True, None)
        self.assertIsNone(state["landed"])
        self.assertIsNot(state["landed"], False)


class TestPrimitivesExist(unittest.TestCase):
    def test_drag_and_key_are_callable(self):
        self.assertTrue(callable(A.cdp_drag))
        self.assertTrue(callable(A.cdp_key))

    def test_frame_anchor_is_exposed_for_shot_receipts(self):
        self.assertTrue(callable(A.frame_anchor))

    def test_key_parse_roundtrip(self):
        info, err = A._parse_key_combo("Meta+Shift+t")
        self.assertIsNone(err)
        self.assertEqual(info["modifiers"], 12)   # Meta 4 | Shift 8
        self.assertEqual(info["key"], "t")

    def test_malformed_combo_is_refused(self):
        info, err = A._parse_key_combo("Control+")
        self.assertIsNone(info)
        self.assertIn("empty key", err)


class TestChangelog0110(unittest.TestCase):
    def setUp(self):
        body = _read("CHANGELOG.md")
        start = body.index("## [0.11.0]")
        nxt = body.find("\n## [", start + 1)
        self.entry = body[start:nxt if nxt != -1 else None]

    def test_entry_covers_both_primitives(self):
        for needle in ("cdp_drag", "cdp_key"):
            self.assertIn(needle, self.entry)

    def test_entry_states_the_honesty_boundary(self):
        self.assertIn("effected", self.entry)
        self.assertIn("unknown", self.entry)

    def test_entry_states_known_limits(self):
        self.assertIn("Known limits", self.entry)


class TestPRDLanded(unittest.TestCase):
    def test_prd_carries_facts_and_repairs(self):
        body = _read("docs/prd-0.11-action-primitives.md")
        for needle in ("F1", "F3", "cdp_drag", "cdp_key"):
            self.assertIn(needle, body)

    def test_prd_records_the_s4_deviation(self):
        """The implementation is more conservative than S4 planned; the PRD
        must say so rather than silently disagree with the code."""
        body = _read("docs/prd-0.11-action-primitives.md")
        self.assertIn("no_frame_ledger", body)


if __name__ == "__main__":
    unittest.main()

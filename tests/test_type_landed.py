"""Typing receipts must speak the same vocabulary as click / drag / key.

2026-10-27 — the sweep behind intent #36192 ("receipts report what I looked at,
not the fact"). The table came out mostly healthy: click / drag / key / scroll
already say what the world did. Typing was the odd one out — it reported
`verified: True` and buried the read-back verdict inside `evidence.read_back`,
so a caller doing `r.get("landed")` across tools got **None** from every typing
path. Absence is not False: it reads as "this tool has no such concept".

These tests call the receipt builder itself (no browser), so they fail if the
top-level word ever drifts back into the evidence block.
"""

import unittest

from hand.action.cdp_act import _typed_out


class TestTypedOut(unittest.TestCase):
    def test_landed_is_a_top_level_word(self):
        out = _typed_out("cdp_type", 0, "hi", {"tag": "INPUT"},
                         {"before": "", "after": "hi", "landed": True})
        self.assertTrue(out["resolved"])
        self.assertTrue(out["landed"])
        self.assertEqual(out["landed_source"], "readback")
        self.assertTrue(out["verified"])
        # the same word click/drag/key use, not a typing-only dialect
        self.assertIn("landed", out)

    def test_landed_false_when_readback_says_so(self):
        out = _typed_out("cdp_type", 0, "hi", {},
                         {"before": "", "after": "", "landed": False})
        self.assertFalse(out["landed"])
        self.assertEqual(out["landed_source"], "readback")

    def test_no_readback_means_not_landed_not_unknown_true(self):
        # no read-back must never be reported as a landed keystroke
        out = _typed_out("cdp_type", 0, "hi", {}, None)
        self.assertFalse(out["landed"])
        self.assertFalse(out["evidence"]["read_back"]["landed"])

    def test_failure_keeps_the_key_and_the_reason(self):
        out = _typed_out("cdp_type", 0, "hi", {"tag": "INPUT"},
                         {"before": "", "after": "", "landed": False},
                         fail="text did not land (zero-landing)")
        self.assertFalse(out["verified"])
        self.assertFalse(out["landed"])          # key present on the failure path too
        self.assertEqual(out["landed_source"], "readback")
        self.assertIn("zero-landing", out["error"])
        self.assertEqual(out["evidence"].get("tag"), "INPUT")  # caller's evidence survives
        self.assertEqual(out["evidence"]["read_back"]["landed"], False)

    def test_extra_fields_land_at_top_level(self):
        out = _typed_out("cdp_type", 2, "hi", {}, None, handle="[93]")
        self.assertEqual(out["handle"], "[93]")
        self.assertEqual(out["page_index"], 2)


if __name__ == "__main__":
    unittest.main()

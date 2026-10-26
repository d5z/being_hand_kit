"""0.13.7 — the coordinate's birth dpr can be declared, and a mismatch refuses.

Why this exists: a physical-pixel coordinate carries the devicePixelRatio it was
*computed* under, but nothing in the value says which one. hand re-reads dpr at
dispatch time and divides by *that* — correct arithmetic, wrong pair. The
receipt then prints a single `dpr`, so it is internally consistent and
therefore blind: a click computed at dpr=2 and dispatched on a dpr=1 page lands
at half the intended x,y and reports success.

`xy:X,Y@dpr=<n>` lets the caller hand over its assumption. If the page
disagrees, hand refuses *before* dispatching and says both numbers. No
declaration → today's behaviour, unchanged (backward compatible).

Hermetic: no browser. The refusal path is exercised through the real
`cdp_click_do` router with the CDP surface mocked, and the dispatch is asserted
absent — a refusal that still clicks would be the exact bug this closes.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import cdp_act as mod


class SplitDeclTest(unittest.TestCase):
    def test_no_declaration_is_untouched(self):
        self.assertEqual(mod._split_dpr_decl("412,188"), ("412,188", None))

    def test_declaration_at_the_end(self):
        self.assertEqual(mod._split_dpr_decl("412,188@dpr=2"), ("412,188", 2.0))

    def test_fractional_ratio_survives(self):
        self.assertEqual(mod._split_dpr_decl("10,20@dpr=1.25"), ("10,20", 1.25))

    def test_declaration_before_expect(self):
        self.assertEqual(mod._split_dpr_decl("412,188@dpr=2@expect=#save"),
                         ("412,188@expect=#save", 2.0))

    def test_declaration_after_expect(self):
        self.assertEqual(mod._split_dpr_decl("412,188@expect=#save@dpr=2"),
                         ("412,188@expect=#save", 2.0))

    def test_zero_is_not_a_declaration(self):
        # dpr=0 is not a ratio any page reports; treat the text as opaque
        # rather than dividing by zero downstream.
        self.assertEqual(mod._split_dpr_decl("412,188@dpr=0"),
                         ("412,188@dpr=0", None))

    def test_non_numeric_is_not_a_declaration(self):
        self.assertEqual(mod._split_dpr_decl("412,188@dpr=retina"),
                         ("412,188@dpr=retina", None))


class DeclErrorTest(unittest.TestCase):
    def test_no_claim_no_error(self):
        self.assertIsNone(mod._dpr_decl_error(None, 2))

    def test_match_is_silent(self):
        self.assertIsNone(mod._dpr_decl_error(2, 2))
        self.assertIsNone(mod._dpr_decl_error(1.25, 1.25))

    def test_mismatch_names_both_numbers(self):
        err = mod._dpr_decl_error(2, 1)
        self.assertIn("dpr=2", err)
        self.assertIn("dpr=1", err)
        self.assertIn("before dispatch", err)

    def test_unreadable_runtime_is_not_a_pass(self):
        for runtime in (None, 0, 0.0, "?"):
            err = mod._dpr_decl_error(2, runtime)
            self.assertIsNotNone(err, "runtime=%r must not pass" % (runtime,))
            self.assertIn("refusing", err)


class RefusalBeforeDispatchTest(unittest.TestCase):
    """The whole point: a mismatch must not reach Input.dispatchMouseEvent."""

    def _run(self, action, runtime_dpr, click_side_effect=None):
        page = {"webSocketDebuggerUrl": "ws://stub", "id": "stub"}
        with mock.patch.object(mod, "list_pages", return_value=[page]), \
             mock.patch.object(mod, "resolve_page", return_value=(0, page)), \
             mock.patch.object(mod, "cdp_connect", return_value=mock.MagicMock()), \
             mock.patch.object(mod, "_init_domains", return_value=None), \
             mock.patch.object(mod, "_get_dpr", return_value=runtime_dpr), \
             mock.patch.object(mod, "_frame_at", return_value=None), \
             mock.patch.object(mod, "_viewport_size",
                               return_value=({"w": 800, "h": 600}, True)), \
             mock.patch.object(mod, "_element_at", return_value="DIV#other"), \
             mock.patch.object(mod, "_doc_identity",
                               return_value={"ok": True, "href": "u",
                                             "timeOrigin": 1}), \
             mock.patch.object(mod, "_element_at_checked",
                               return_value=("hit", "DIV#other")), \
             mock.patch.object(mod, "_write_last", return_value=None), \
             mock.patch.object(mod, "_click_at",
                               side_effect=click_side_effect) as click:
            receipt = mod.cdp_click_do(action)
        return receipt, click

    def test_mismatch_refuses_and_never_dispatches(self):
        receipt, click = self._run("xy:400,200@dpr=1", runtime_dpr=2)
        click.assert_not_called()
        # failure-receipt contract (same shape as every other refused click):
        # verified=False + error names why. There is no `result` key on failures.
        self.assertFalse(receipt.get("verified", True), receipt)
        joined = repr(receipt)
        self.assertIn("dpr mismatch", joined)
        self.assertIn("dpr=1", joined)
        self.assertIn("dpr=2", joined)

    def test_matching_declaration_dispatches(self):
        receipt, click = self._run("xy:400,200@dpr=2", runtime_dpr=2)
        click.assert_called_once()
        self.assertNotEqual(receipt.get("result"), "error")
        self.assertEqual(receipt.get("evidence", {}).get("dpr_declared"), 2.0)

    def test_undeclared_coordinate_still_dispatches(self):
        # backward compatible: silence is not a claim
        receipt, click = self._run("xy:400,200", runtime_dpr=3)
        click.assert_called_once()
        self.assertIsNone(receipt.get("evidence", {}).get("dpr_declared"))


class DragPathTest(unittest.TestCase):
    def test_drag_point_refuses_on_mismatch(self):
        with mock.patch.object(mod, "_dpr_now", return_value=1.0):
            point, err = mod._point_from_spec(mock.MagicMock(), "xy:400,200@dpr=2")
        self.assertIsNone(point)
        self.assertIn("dpr mismatch", err)

    def test_drag_point_accepts_matching_ratio(self):
        with mock.patch.object(mod, "_dpr_now", return_value=2.0):
            point, err = mod._point_from_spec(mock.MagicMock(), "xy:400,200@dpr=2")
        self.assertIsNone(err)
        self.assertEqual((point["x"], point["y"]), (200.0, 100.0))
        self.assertEqual(point["dpr_declared"], 2.0)

    def test_selector_ending_in_a_decl_like_text_is_not_rewritten(self):
        # `_point_from_spec` must only treat `@dpr=` as a declaration for xy:
        # specs; a CSS selector is a different grammar that we don't own.
        with mock.patch.object(mod, "_dpr_now", return_value=1.0), \
             mock.patch.object(mod, "_element_info",
                               return_value={"x": 1, "y": 2}), \
             mock.patch.object(mod, "_split_dpr_decl",
                               side_effect=AssertionError("must not be called")):
            point, err = mod._point_from_spec(mock.MagicMock(), "a@dpr=2")
        self.assertIsNone(err)
        self.assertEqual(point["x"], 1.0)


if __name__ == "__main__":
    unittest.main()

"""0.13.8 — devicePixelRatio is read ONCE and carried, not read twice and crossed.

Why this exists: the selector click read `window.devicePixelRatio` twice — once
inside the page expression that multiplied the rect centre (physical px), and
again from the driver to divide the point back down before dispatch. Two
independent CDP round trips of the same quantity. If the value changes between
them, the dispatch point is off by that ratio while the receipt still says
verified=true (verified only ever meant "selector matched, rect read").

Measured 2026-10-27 by Neuromancer on 0.13.5 (macOS, injected getter reporting
2 then 1): target centred at CSS(280,180) → dispatched (560,360), zero real
clicks reached the page, receipt result=ok verified=True. His reading was on the
deployed build; the same two-read shape was present in this tree, in the click
path, the type path and the spec→point path.

These tests lock the *invariant* rather than the fix's shape: whatever the page
would report later, the number that multiplies the rect is the number that
divides the dispatch. Hermetic — cdp_call is mocked.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import cdp_act as mod
from hand.perception import cdp_core as core


class ElementInfoDprContractTest(unittest.TestCase):
    """`dpr=` removes the page-side read from the expression entirely."""

    def _expr(self, **kwargs):
        sent = []

        def fake(ws, method, params, msg_id=None, **kw):
            sent.append(params.get("expression", ""))
            return {"result": {"value": '{"x":560,"y":360,"w":10,"h":10,'
                                        '"css":{"x":280,"y":180},'
                                        '"visible":true,"tag":"BUTTON","text":""}'}}

        with mock.patch.object(core, "cdp_call", side_effect=fake):
            out = core._element_info(None, "#btn", **kwargs)
        return sent[0], out

    def test_declared_dpr_is_baked_in_and_page_is_not_asked(self):
        expr, out = self._expr(dpr=2.0)
        self.assertIn("var dpr=2.0;", expr)
        self.assertNotIn("window.devicePixelRatio", expr)
        self.assertEqual(out["x"], 560)

    def test_no_declaration_keeps_the_legacy_shape(self):
        expr, out = self._expr()
        self.assertIn("window.devicePixelRatio", expr)
        self.assertEqual(out["x"], 560)          # whatever the page said


class TextPathSingleReadTest(unittest.TestCase):
    """Neuromancer's fourth site: the text= path read dpr inside the JS to make
    the point and again from the driver to divide it."""

    def test_text_path_reads_dpr_once_and_divides_by_that_number(self):
        reads = []
        dispatched = []

        def dpr_now(ws):
            reads.append(1)
            return 2.0

        def fake_call(ws, method, params, msg_id=None, **kw):
            if method == "Runtime.evaluate":
                expr = params.get("expression", "")
                if "fold(" in expr:                      # the text matcher
                    self.assertIn("var dpr=2.0;", expr)
                    self.assertNotIn("window.devicePixelRatio", expr)
                    return {"result": {"value": '{"x":560,"y":360,"how":"center",'
                                                '"tag":"A","text":"Go"}'}}
                return {"result": {"value": "{}"}}
            if method == "Input.dispatchMouseEvent":
                dispatched.append((params.get("x"), params.get("y")))
            return {}

        with mock.patch.object(mod, "_dpr_now", side_effect=dpr_now), \
             mock.patch.object(mod, "cdp_call", side_effect=fake_call), \
             mock.patch.object(mod, "list_pages", return_value=[]), \
             mock.patch.object(mod, "resolve_page", return_value=(0, {"webSocketDebuggerUrl": "ws://x"})), \
             mock.patch.object(mod, "cdp_connect", return_value=mock.MagicMock()), \
             mock.patch.object(mod, "_init_domains"), \
             mock.patch.object(mod, "_write_last"):
            out = mod.cdp_click_do("text=Go")

        self.assertEqual(len(reads), 1, "dpr must be read exactly once")
        self.assertEqual(out.get("result"), "ok")
        self.assertEqual(dispatched[0], (280.0, 180.0),
                         "physical 560/360 divided by the SAME dpr that made it")


class OneNumberBothWaysTest(unittest.TestCase):
    """The click path: the dpr multiplying the rect == the dpr dividing dispatch."""

    def test_selector_click_uses_the_same_read_for_info_and_dispatch(self):
        seen = {}

        def fake_info(ws, selector, dpr=None):
            seen["info_dpr"] = dpr
            return {"x": 560.0, "y": 360.0, "w": 100, "h": 40,
                    "css": {"x": 280.0, "y": 180.0},
                    "visible": True, "tag": "BUTTON", "text": "go"}

        def fake_click(ws, x, y, dpr):
            seen["dispatch"] = (x, y, dpr)

        sent = []

        with mock.patch.object(mod, "_dpr_now", return_value=2.0) as dpr_now, \
             mock.patch.object(mod, "_element_info", side_effect=fake_info), \
             mock.patch.object(mod, "_click_at", side_effect=fake_click), \
             mock.patch.object(mod, "_selector_hit", return_value={"found": True}), \
             mock.patch.object(mod, "_install_click_probe"), \
             mock.patch.object(mod, "_read_click_probe",
                               return_value={"trusted": 1, "untrusted": 0,
                                             "has_form": False}), \
             mock.patch.object(mod, "_clear_click_probe"), \
             mock.patch.object(mod, "_js_focus_enter"), \
             mock.patch.object(mod, "_write_last"), \
             mock.patch.object(core, "cdp_call", return_value={}), \
             mock.patch.object(mod, "list_pages", return_value=[{"webSocketDebuggerUrl": "ws://x"}]), \
             mock.patch.object(mod, "resolve_page", return_value=(0, {"webSocketDebuggerUrl": "ws://x"})), \
             mock.patch.object(mod, "cdp_connect", return_value=mock.MagicMock(close=lambda: None)):
            out = mod.cdp_click("#btn")

        self.assertEqual(dpr_now.call_count, 1, "dpr must be read exactly once")
        self.assertEqual(seen["info_dpr"], 2.0, "info must be computed under that read")
        self.assertEqual(seen["dispatch"][2], 2.0, "dispatch must divide by that same read")
        # the landing point in CSS px equals the centre the page reported
        self.assertEqual((seen["dispatch"][0] / seen["dispatch"][2],
                          seen["dispatch"][1] / seen["dispatch"][2]), (280.0, 180.0))
        # the receipt now states both sides, so a caller can check it
        self.assertEqual(out["evidence"]["dpr"], 2.0)
        self.assertEqual(out["evidence"]["dpr_reads"], 1)
        self.assertEqual(out["evidence"]["dispatched"]["css"], {"x": 280.0, "y": 180.0})
        self.assertEqual(out["evidence"]["dispatched"]["physical"], {"x": 560.0, "y": 360.0})

    def test_spec_point_passes_its_single_read_into_the_rect(self):
        seen = {}

        def fake_info(ws, selector, dpr=None):
            seen["dpr"] = dpr
            return {"x": 560.0, "y": 360.0, "visible": True, "tag": "A", "text": ""}

        with mock.patch.object(mod, "_dpr_now", return_value=2.0), \
             mock.patch.object(mod, "_element_info", side_effect=fake_info):
            pt, err = mod._point_from_spec(None, "#a")

        self.assertIsNone(err)
        self.assertEqual(seen["dpr"], 2.0)
        self.assertEqual((pt["x"], pt["y"]), (280.0, 180.0))

    def test_click_path_has_no_second_dpr_read_before_dispatch(self):
        """Source-level guard: the crossed pair (info under page dpr, dispatch
        under a fresh read) must not come back."""
        path = os.path.join(os.path.dirname(__file__), "..", "hand",
                            "action", "cdp_act.py")
        with open(path) as fh:
            src = fh.read()
        start = src.index("def cdp_click(selector")
        body = src[start:src.index("def cdp_type(", start)]
        self.assertEqual(body.count("_dpr_now(ws)"), 1)
        self.assertNotIn("_click_at(ws, x, y, _get_dpr(ws))", body)
        self.assertIn("_element_info(ws, selector, dpr=dpr)", body)


if __name__ == "__main__":
    unittest.main()

"""L1 tests for hand 0.7.0 S2 — see() wiring + [idx] handles in click/type.

PRD docs/prd-ax-perception.md S2. All CDP/backend surfaces mocked; no browser.

Covers: kind=a11y as the default browser snapshot (place-independent),
interactive/dom/network escape hatches still reachable, desktop_app unaffected,
handle resolution into click/type (fresh box re-read, honest unverified receipts
when the element is gone), and the receipt contract shape for a11y snapshots.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.router as router
import hand.perception.ax_tree as ax
from hand.action import cdp_act
from hand.session import get_session, reset_session


PAGE = {"id": "1", "type": "page", "url": "https://beings.town/", "title": "Beings",
        "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}


class _FakeWS:
    def close(self):
        pass


def _snapshot(method="cdp_a11y", **over):
    out = {"method": method, "page_index": 0, "url": "https://beings.town/",
           "page_title": "Beings", "tree": '- RootWebArea "Beings"\n  - link "Sign in" [2]',
           "nodes": [{"idx": 2, "role": "link", "name": "Sign in",
                      "backend_node_id": 105, "interactive": True}],
           "handles": {"2": {"role": "link", "name": "Sign in", "backend_node_id": 105}},
           "coords": {"2": {"x": 10, "y": 20}}, "hint": None,
           "root_role": "RootWebArea", "format": "a11y-v2",
           "node_count": 2, "raw_node_count": 15, "curated_node_count": 13,
           "line_count": 2, "serialized_bytes": 45, "max_lines": 600,
           "truncated": False, "nodes_omitted": 0, "sha256": "abc",
           "ax_version": {"product": "Chrome/141.0.0", "protocol": "1.3"}}
    out.update(over)
    return out


class TestRouteSeeKinds(unittest.TestCase):
    def setUp(self):
        reset_session()

    def tearDown(self):
        reset_session()

    def test_kind_a11y_is_place_independent(self):
        with mock.patch("hand.perception.ax_tree.ax_snapshot",
                        return_value=_snapshot()) as m:
            r = router.route_see(kind="a11y")
        self.assertTrue(m.called)
        self.assertEqual(r["method"], "cdp_a11y")
        self.assertTrue(r["verified"])

    def test_default_browser_see_is_a11y(self):
        session = get_session()
        session.place = router.Place(type="browser", identifier="https://beings.town/")
        with mock.patch("hand.perception.ax_tree.ax_snapshot",
                        return_value=_snapshot()):
            r = router.route_see()
        self.assertEqual(r["method"], "cdp_a11y")

    def test_kind_interactive_still_works(self):
        with mock.patch("hand.perception.cdp_snapshot.interactive_map",
                        return_value={"method": "cdp_interactive", "count": 3, "total": 3,
                                      "elems": [], "coord": {}}):
            r = router.route_see(kind="interactive")
        self.assertEqual(r["method"], "cdp_interactive")

    def test_kind_dom_is_not_shadowed_by_a11y(self):
        with mock.patch("hand.perception.ax_tree.ax_snapshot",
                        return_value=_snapshot()) as ax_m, \
             mock.patch("hand.perception.cdp_snapshot.cdp_snapshot_see",
                        return_value={"method": "cdp_snapshot", "url": "u",
                                      "page_title": "t", "chars": 5}) as dom_m:
            r = router.route_see(kind="dom")
        self.assertEqual(r["method"], "cdp_snapshot")
        self.assertTrue(dom_m.called)
        self.assertFalse(ax_m.called)

    def test_kind_network_unchanged(self):
        with mock.patch("hand.perception.cdp_network.network_snapshot",
                        return_value={"method": "cdp_network", "total_requests": 2,
                                      "duration": 0.1}):
            r = router.route_see(kind="network")
        self.assertEqual(r["method"], "cdp_network")

    def test_desktop_app_place_does_not_get_hijacked_by_a11y(self):
        session = get_session()
        session.place = router.Place(type="desktop_app", identifier="Notes")
        # SEE_PRIORITY is computed at import time (mac-only backends are filtered
        # by platform), so the chain is patched directly.
        with mock.patch.dict(router.SEE_PRIORITY, {"desktop_app": ["ax_app"]}), \
             mock.patch("hand.perception.ax_tree.ax_snapshot",
                        return_value=_snapshot()) as ax_m, \
             mock.patch("hand.perception.ax_app.ax_app_see",
                        return_value={"method": "ax_app", "app": "Notes"}):
            r = router.route_see()
        self.assertEqual(r["method"], "ax_app")
        self.assertFalse(ax_m.called)

    def test_a11y_failure_is_an_error_receipt_with_reason(self):
        with mock.patch("hand.perception.ax_tree.ax_snapshot",
                        side_effect=RuntimeError("endpoint down")):
            r = router.route_see(kind="a11y")
        self.assertIn("error", r)
        self.assertFalse(r["verified"])
        self.assertIn("endpoint down", r["evidence"]["reason"])

    def test_a11y_snapshot_sets_browser_place_for_followup_do(self):
        with mock.patch("hand.perception.ax_tree.ax_snapshot", return_value=_snapshot()):
            router.route_see(kind="a11y")
        self.assertEqual(get_session().place.type, "browser")


class TestA11yReceiptContract(unittest.TestCase):
    """S3: the a11y snapshot goes through the same receipt ruler."""

    def test_receipt_fields_from_evidence(self):
        r = router._with_receipt(_snapshot())
        self.assertTrue(r["verified"])
        ev = r["evidence"]
        for key in ("node_count", "serialized_bytes", "truncated", "nodes_omitted",
                    "ax_version", "format"):
            self.assertIn(key, ev)
        self.assertEqual(ev["backend"], "cdp_a11y")

    def test_empty_tree_receipt_is_unverified_with_reason(self):
        snap = _snapshot(node_count=0, line_count=0, tree="")
        r = router._with_receipt(snap)
        self.assertFalse(r["verified"])
        self.assertIn("reason", r["evidence"])

    def test_truncated_tree_is_still_verified_but_flagged(self):
        snap = _snapshot(truncated=True, nodes_omitted=12)
        r = router._with_receipt(snap)
        self.assertTrue(r["verified"])
        self.assertTrue(r["evidence"]["truncated"])
        self.assertEqual(r["evidence"]["nodes_omitted"], 12)


# ── [idx] handles in click/type ──────────────────────────────────────

class TestHandleClick(unittest.TestCase):
    def _run_click(self, action, handle_entry=None, box_ok=True):
        calls = []
        entry = handle_entry if handle_entry is not None else {
            "role": "link", "name": "Sign in", "backend_node_id": 105,
            "interactive": True, "x": 10, "y": 20, "idx": 2}

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            calls.append((method, params))
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.resolveNode":
                if not box_ok:
                    raise RuntimeError("CDP error: node with given id does not belong to the document")
                return {"object": {"objectId": "obj-1"}}
            if method == "Runtime.callFunctionOn":
                if not box_ok:
                    return {"result": {"value": json.dumps({"x": 0, "y": 0, "w": 0, "h": 0})}}
                return {"result": {"value": json.dumps({"x": 60, "y": 40, "w": 100, "h": 40})}}
            if method == "Runtime.evaluate":
                if params.get("expression") == "window.devicePixelRatio":
                    return {"result": {"value": 2}}
                return {"result": {"value": json.dumps({"tag": "A", "id": "", "type": ""})}}
            return {}

        with mock.patch.object(cdp_act, "list_pages", return_value=[PAGE]), \
             mock.patch.object(cdp_act, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(cdp_act, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(cdp_act, "cdp_call", side_effect=fake_call), \
             mock.patch.object(cdp_act, "_init_domains", return_value=None), \
             mock.patch.object(cdp_act, "_write_last", return_value=None), \
             mock.patch.object(ax, "load_handle_map",
                               return_value={} if handle_entry is False else {"2": entry}):
            out = cdp_act.cdp_click_do(action)
        return out, calls

    def test_idx_click_dispatches_at_fresh_box_center(self):
        out, calls = self._run_click("[2]")
        self.assertTrue(out["verified"], out)
        self.assertEqual(out["handle"], "[2]")
        self.assertIn('link "Sign in"', out["evidence"]["element"])
        presses = [p for m, p in calls if m == "Input.dispatchMouseEvent"]
        self.assertEqual(len(presses), 2)
        # box center is viewport CSS px (60,40); hand dispatches CSS px = physical/dpr
        self.assertEqual(presses[0]["x"], 60.0)
        self.assertEqual(presses[0]["y"], 40.0)
        self.assertEqual(out["evidence"]["space"], "physical")
        self.assertEqual(out["evidence"]["dispatched"], [120, 80])  # physical

    def test_idx_click_uses_fresh_geometry_not_stale_snapshot_coords(self):
        """Snapshot x,y are informational; the click re-reads the element box."""
        out, calls = self._run_click("[2]")
        self.assertIn("Runtime.callFunctionOn", [m for m, _ in calls])
        self.assertIn("DOM.resolveNode", [m for m, _ in calls])
        self.assertNotEqual(out["evidence"]["dispatched"], [10, 20])

    def test_idx_click_unknown_handle_is_unverified_with_hint(self):
        out, _ = self._run_click("[9]", handle_entry=False)
        self.assertFalse(out["verified"])
        self.assertIn("cdp_see", out["evidence"]["reason"])

    def test_idx_click_on_removed_element_is_unverified(self):
        out, _ = self._run_click("[2]", box_ok=False)
        self.assertFalse(out["verified"])
        self.assertIn("cdp_see", out["evidence"]["reason"])

    def test_selector_path_is_untouched(self):
        with mock.patch.object(cdp_act, "cdp_click",
                               return_value={"method": "cdp_click", "selector": "a.x",
                                             "verified": True, "evidence": {}}) as m:
            out = cdp_act.cdp_click_do("a.x")
        self.assertTrue(m.called)
        self.assertEqual(out["selector"], "a.x")

    def test_text_and_xy_paths_still_route(self):
        with mock.patch.object(cdp_act, "cdp_click",
                               return_value={"method": "cdp_click"}) as m:
            cdp_act.cdp_click_do("text=Learn more")
            cdp_act.cdp_click_do("xy:10,20")
        self.assertFalse(m.called)  # neither goes through the selector path


class TestHandleType(unittest.TestCase):
    def _run_type(self, action, active="INPUT"):
        calls = []
        entry = {"role": "textbox", "name": "Search", "backend_node_id": 115,
                 "interactive": True, "x": 1, "y": 2, "idx": 5}

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            calls.append((method, params))
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.resolveNode":
                return {"object": {"objectId": "obj-2"}}
            if method == "Runtime.callFunctionOn":
                return {"result": {"value": json.dumps({"focused": True})}}
            if method == "Runtime.evaluate":
                return {"result": {"value": json.dumps(
                    {"tag": active, "id": "q", "type": "search"})}}
            return {}

        with mock.patch.object(cdp_act, "list_pages", return_value=[PAGE]), \
             mock.patch.object(cdp_act, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(cdp_act, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(cdp_act, "cdp_call", side_effect=fake_call), \
             mock.patch.object(cdp_act, "_init_domains", return_value=None), \
             mock.patch.object(cdp_act, "_write_last", return_value=None), \
             mock.patch.object(ax, "load_handle_map", return_value={"5": entry}):
            out = cdp_act.cdp_type_do(action)
        return out, calls

    def test_idx_type_focuses_handle_then_inserts_text(self):
        out, calls = self._run_type("[5]|hello")
        self.assertTrue(out["verified"], out)
        self.assertEqual(out["text"], "hello")
        self.assertIn("DOM.resolveNode", [m for m, _ in calls])
        self.assertEqual([p["text"] for m, p in calls if m == "Input.insertText"],
                         list("hello"))
        self.assertIn("textbox \"Search\"", out["evidence"]["element"])

    def test_idx_type_without_focus_is_unverified(self):
        out, _ = self._run_type("[5]|hi", active="BODY")
        self.assertFalse(out["verified"])
        self.assertIn("focus", out["evidence"]["reason"])

    def test_type_without_handle_needs_pipe_format(self):
        out = cdp_act.cdp_type_do("just-text")
        self.assertFalse(out["verified"])
        self.assertIn("selector|text", out["evidence"]["reason"])


class TestRouteDoHandle(unittest.TestCase):
    def setUp(self):
        reset_session()

    def tearDown(self):
        reset_session()

    def test_route_do_recovers_browser_place_for_handle_action(self):
        with mock.patch("hand.perception.cdp_core.list_pages", return_value=[PAGE]), \
             mock.patch("hand.action.cdp_act.cdp_click_do",
                        return_value={"method": "cdp_click", "verified": True,
                                      "evidence": {}}) as m:
            r = router.route_do("[2]")
        self.assertTrue(m.called)
        self.assertEqual(r["method"], "cdp_click")

    def test_route_do_without_place_and_without_browser_still_errors(self):
        with mock.patch("hand.perception.cdp_core.list_pages", return_value=[]):
            r = router.route_do("[2]")
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()

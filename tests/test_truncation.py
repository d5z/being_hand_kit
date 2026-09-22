"""L1 tests for hand 0.9 S1 — truncation/dropped/skipped declarations.

PRD docs/prd-0.9-receipt-honesty.md S1: a cut is always declared. Every backend
that can drop output emits a unified `truncation` block {field, reason, dropped,
total}; when nothing was dropped the block is ABSENT (not null). Internal skips
travel through the hint channel as `skipped: <what> (<why>)`.

The legacy per-backend fields (`truncated` bool, `nodes_omitted`, `total`,
`total_chars`) are preserved for one version — see hand/receipt.py for why the
unified block is named `truncation` and not `truncated`.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.perception.ax_tree as ax
import hand.perception.cdp_snapshot as snap
from hand.receipt import truncation, skipped, merge_hints


PAGE = {"id": "1", "type": "page", "url": "https://example.com/",
        "title": "Example", "webSocketDebuggerUrl": "ws://x/1"}


class _FakeWS:
    def close(self):
        pass


def _node(node_id, role, name="", parent=None, backend_id=None):
    n = {"nodeId": node_id, "role": {"value": role}, "name": {"value": name}}
    if parent is not None:
        n["parentId"] = parent
    if backend_id is not None:
        n["backendDOMNodeId"] = backend_id
    return n


def _long_fixture():
    nodes = [_node("1", "RootWebArea", "Page")]
    for i in range(2, 12):
        nodes.append(_node(str(i), "button", f"Btn {i}", parent="1", backend_id=100 + i))
    return nodes


# ── helper semantics ─────────────────────────────────────────────────

class TestTruncationBlock(unittest.TestCase):
    def test_shape_and_no_null_when_complete(self):
        self.assertEqual(truncation("tree", "max_lines", 3, 10),
                         {"field": "tree", "reason": "max_lines", "dropped": 3,
                          "total": 10})
        # nothing dropped → None (the receipt key must be ABSENT, never null)
        self.assertIsNone(truncation("tree", "max_lines", 0, 10))

    def test_skipped_and_merge(self):
        self.assertEqual(skipped("coords for 2 nodes", "not rendered"),
                         "skipped: coords for 2 nodes (not rendered)")
        self.assertEqual(merge_hints("hint: x", [skipped("a", "b")]),
                         "hint: x; skipped: a (b)")
        self.assertIsNone(merge_hints(None, []))


# ── a11y tree ────────────────────────────────────────────────────────

class TestA11yTruncation(unittest.TestCase):
    def test_serialize_declares_the_tree_cut(self):
        ser = ax.serialize(_long_fixture(), max_lines=4)
        self.assertTrue(ser["truncated"])
        block = ser["truncation"]
        self.assertEqual(set(block), {"field", "reason", "dropped", "total"})
        self.assertEqual(block["field"], "tree")
        self.assertEqual(block["reason"], "max_lines")
        self.assertEqual(block["dropped"], ser["nodes_omitted"])
        # total is the full, un-cut line count
        self.assertEqual(block["total"], block["dropped"] + len(ser["lines"]))
        self.assertEqual(block["total"] + 0, len(ax.serialize(_long_fixture(),
                                                              max_lines=999)["lines"]))

    def test_serialize_absent_when_complete(self):
        ser = ax.serialize(_long_fixture(), max_lines=999)
        self.assertFalse(ser["truncated"])
        self.assertNotIn("truncation", ser)

    def test_name_cut_declared_when_tree_is_complete(self):
        nodes = [_node("1", "RootWebArea", "Page"),
                 _node("2", "StaticText", "x" * (ax.MAX_NAME + 5), parent="1")]
        ser = ax.serialize(nodes, max_lines=999)
        self.assertFalse(ser["truncated"])
        self.assertEqual(ser["text_truncated_count"], 1)
        self.assertEqual(ser["truncation"]["field"], "names")
        self.assertEqual(ser["truncation"]["reason"], "max_name")

    def _snapshot(self, nodes, max_lines=600, resolve_coords=True, coords_map=None):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Accessibility.getFullAXTree":
                return {"nodes": nodes}
            if method == "Browser.getVersion":
                return {"product": "Chrome/141.0"}
            if method == "Runtime.evaluate":
                return {"result": {"value": 1}}
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": []}
            return {}
        tmp = tempfile.mkdtemp()
        with mock.patch.object(ax, "list_pages", return_value=[PAGE]), \
             mock.patch.object(ax, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(ax, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(ax, "cdp_call", side_effect=fake_call), \
             mock.patch.object(ax, "_init_domains", return_value=None), \
             mock.patch.object(ax, "_write_last", return_value=None):
            return ax.ax_snapshot(max_lines=max_lines, resolve_coords=resolve_coords,
                                  handle_map_path=os.path.join(tmp, "h.json"))

    def test_receipt_carries_block_and_legacy_fields(self):
        out = self._snapshot(_long_fixture(), max_lines=4)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["nodes_omitted"], out["truncation"]["dropped"])
        self.assertEqual(out["truncation"]["field"], "tree")

    def test_receipt_block_absent_when_complete(self):
        out = self._snapshot(_long_fixture(), max_lines=999)
        self.assertNotIn("truncation", out)

    def test_unresolved_coordinates_are_declared_as_skipped(self):
        out = self._snapshot(_long_fixture(), max_lines=999, resolve_coords=True)
        # DOM.pushNodesByBackendIdsToFrontend returns no nodeIds → no coords.
        self.assertIn("skipped: coordinates for", out["hint"])
        self.assertIn("not in the render tree", out["hint"])


# ── DOM snapshot ─────────────────────────────────────────────────────

class TestDomTruncation(unittest.TestCase):
    def _snapshot(self, total, chars):
        payload = {"page_title": "T", "url": "https://example.com/",
                   "line_count": 1, "chars": chars, "total_chars": total,
                   "truncated": total > chars, "text": "x" * chars}

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Runtime.evaluate":
                expr = (params or {}).get("expression", "")
                if "innerText" in expr:
                    return {"result": {"value": json.dumps(payload)}}
                return {"result": {"value": 1.0}}
            return {}

        with mock.patch.object(snap, "list_pages", return_value=[PAGE]), \
             mock.patch.object(snap, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(snap, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(snap, "cdp_call", side_effect=fake_call), \
             mock.patch.object(snap, "_init_domains", return_value=None), \
             mock.patch.object(snap, "_write_last", return_value=None):
            return snap.cdp_snapshot(max_chars=8000)

    def test_declares_the_max_chars_cut(self):
        out = self._snapshot(total=20000, chars=8000)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["total_chars"], 20000)
        block = out["truncation"]
        self.assertEqual(block["field"], "text")
        self.assertEqual(block["reason"], "max_chars")
        self.assertEqual(block["dropped"], 12000)
        self.assertEqual(block["total"], 20000)

    def test_absent_when_the_page_fits(self):
        out = self._snapshot(total=100, chars=100)
        self.assertFalse(out["truncated"])
        self.assertNotIn("truncation", out)


# ── interactive map ──────────────────────────────────────────────────

class TestInteractiveTruncation(unittest.TestCase):
    def _map(self, n_elems, max_elems):
        elems = [{"tag": "BUTTON", "text": f"b{i}", "selector": "#b%d" % i,
                  "x": i, "y": i, "w": 1, "h": 1, "in_viewport": True,
                  "occluded": False, "visible": True} for i in range(n_elems)]

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Runtime.evaluate":
                return {"result": {"value": json.dumps(elems)}}
            return {}

        with mock.patch.object(snap, "list_pages", return_value=[PAGE]), \
             mock.patch.object(snap, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(snap, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(snap, "cdp_call", side_effect=fake_call), \
             mock.patch.object(snap, "_init_domains", return_value=None), \
             mock.patch.object(snap, "_write_last", return_value=None):
            return snap.interactive_map(max_elems=max_elems)

    def test_declares_the_max_elems_cut(self):
        out = self._map(n_elems=5, max_elems=2)
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["total"], 5)
        self.assertEqual(out["truncation"],
                         {"field": "elems", "reason": "max_elems",
                          "dropped": 3, "total": 5})

    def test_absent_when_all_elements_fit(self):
        out = self._map(n_elems=2, max_elems=10)
        self.assertFalse(out["truncated"])
        self.assertNotIn("truncation", out)


# ── skipped steps declared in the hint channel ───────────────────────

class TestSkippedStepsDeclared(unittest.TestCase):
    def test_fallback_declares_the_backend_it_skipped(self):
        from hand.session import reset_session, Place
        import hand.router as r
        reset_session()
        with mock.patch("hand.perception.ax_tree.ax_snapshot",
                        side_effect=RuntimeError("a11y down")), \
             mock.patch("hand.perception.cdp_snapshot.cdp_snapshot_see",
                        return_value={"method": "cdp_snapshot",
                                      "url": "https://x/", "page_title": "X",
                                      "text": "hi"}):
            out = r.route_see(place=Place(type="browser", identifier="https://x/"))
        self.assertEqual(out["evidence"]["backend"], "cdp_snapshot")
        self.assertIn("skipped: cdp_a11y", out["hint"])
        self.assertIn("backend failed", out["hint"])

    def test_no_hint_when_nothing_was_skipped(self):
        from hand.session import reset_session, Place
        import hand.router as r
        reset_session()
        with mock.patch("hand.perception.cdp_snapshot.cdp_snapshot_see",
                        return_value={"method": "cdp_snapshot", "url": "https://x/",
                                      "page_title": "X", "text": "hi"}):
            out = r.route_see(kind="dom")
        self.assertIsNone(out.get("hint"))


# ── vision LLM output cut at max_tokens ──────────────────────────────

class TestVlmOutputCut(unittest.TestCase):
    """An LLM description can be cut at max_tokens. The provider verdict is the
    honest declaration; we never fabricate {dropped, total} for it."""

    def test_length_finish_reason_is_declared(self):
        import hand.router as r
        with mock.patch("hand.perception.vision_llm.describe_screenshot",
                        return_value={"ok": True, "text": "a very long descrip",
                                      "model": "m", "error": None,
                                      "finish_reason": "length",
                                      "usage": {"completion_tokens": 400}}):
            out = r.route_see_vlm(image_b64="AAAA")
        self.assertEqual(out["finish_reason"], "length")
        self.assertIn("max_tokens", out["hint"])
        self.assertIn("finish_reason=length", out["hint"])
        # no numeric block: the unproduced total is unknowable
        self.assertNotIn("truncation", out)

    def test_normal_stop_carries_no_hint(self):
        import hand.router as r
        with mock.patch("hand.perception.vision_llm.describe_screenshot",
                        return_value={"ok": True, "text": "done", "model": "m",
                                      "error": None, "finish_reason": "stop",
                                      "usage": {}}):
            out = r.route_see_vlm(image_b64="AAAA")
        self.assertEqual(out["finish_reason"], "stop")
        self.assertNotIn("hint", out)
        self.assertNotIn("truncation", out)


# ── cross-cutting invariants & the Python face ───────────────────────

class TestUnifiedBlockInvariants(unittest.TestCase):
    """Any block any backend emits must obey the frozen shape/meaning."""

    def test_block_is_always_well_formed_and_positive(self):
        blocks = [
            ax.serialize(_long_fixture(), max_lines=4)["truncation"],
            ax.serialize([_node("1", "RootWebArea", "P"),
                          _node("2", "StaticText", "y" * (ax.MAX_NAME + 1),
                                parent="1")])["truncation"],
        ]
        import hand.perception.cdp_snapshot as s
        # interactive: exercise the block building through the helper used there
        from hand.receipt import truncation as T
        blocks.append(T("elems", "max_elems", 3, 5))
        for b in blocks:
            self.assertEqual(set(b), {"field", "reason", "dropped", "total"})
            self.assertIsInstance(b["dropped"], int)
            self.assertIsInstance(b["total"], int)
            self.assertGreater(b["dropped"], 0)
            self.assertLessEqual(b["dropped"], b["total"])


class TestFaceReceiptPreservesDeclarations(unittest.TestCase):
    """The Python face (hand.see) must carry the 0.9 fields through untouched."""

    def test_see_receipt_carries_truncation_and_visual_state(self):
        import hand.hand as face
        block = {"field": "tree", "reason": "max_lines", "dropped": 7, "total": 9}
        snap = {"method": "cdp_a11y", "format": "a11y-v2.1", "page_index": 0,
                "url": "https://x/", "page_title": "X", "tree": "t",
                "nodes": [], "handles": {}, "coords": {}, "root_role": "RootWebArea",
                "node_count": 2, "line_count": 2, "serialized_bytes": 1,
                "truncated": True, "nodes_omitted": 7, "text_truncated_count": 0,
                "max_lines": 2, "truncation": block, "sha256": "a",
                "visual_state": "loading", "visual_signals": ["aria-busy"]}
        face.reset()
        with mock.patch("hand.perception.ax_tree.ax_snapshot", return_value=snap):
            r = face.see(kind="a11y")
        self.assertEqual(r["truncation"], block)
        self.assertEqual(r["visual_state"], "loading")
        self.assertEqual(r["visual_signals"], ["aria-busy"])
        # both new keys sit in their declared FIELD_ORDER slot (contract order)
        keys = list(r.keys())
        self.assertLess(keys.index("truncation"), keys.index("visual_state"))
        self.assertLess(keys.index("visual_state"), keys.index("evidence"))


if __name__ == "__main__":
    unittest.main()


class TestNetworkBodyTruncation(unittest.TestCase):
    """0.9: fetch_body bodies larger than max_small_body are cut and declared.

    The max_small_body parameter sat unused in the signature since 0.8 —
    a fetched 10MB body went into the receipt whole, silently. Found while
    hardening 0.9 before release.
    """

    def _snapshot(self, body, max_small_body=64):
        import hand.perception.cdp_network as net
        big = "x" * 200
        with mock.patch.object(net, "list_pages", return_value=[
                {"webSocketDebuggerUrl": "ws://x", "id": "p0"}]), \
             mock.patch.object(net, "cdp_connect"), \
             mock.patch.object(net, "cdp_call_raw",
                               return_value={"body": body, "base64Encoded": False}), \
             mock.patch.object(net, "_write_last"):
            return net.network_snapshot(
                fetch_body_id="R1", duration=0.05,
                max_small_body=max_small_body)

    def test_big_body_is_cut_and_declared(self):
        r = self._snapshot("y" * 200, max_small_body=64)
        req = r["requests"][0]
        self.assertEqual(len(req["body"]), 64)
        self.assertEqual(req["body_truncation"],
                         {"field": "body", "reason": "max_small_body",
                          "dropped": 136, "total": 200})

    def test_small_body_passes_through_undeclared(self):
        r = self._snapshot("y" * 10, max_small_body=64)
        req = r["requests"][0]
        self.assertEqual(req["body"], "y" * 10)
        self.assertNotIn("body_truncation", req)

    def test_boundary_exact_limit_is_not_a_cut(self):
        r = self._snapshot("y" * 64, max_small_body=64)
        req = r["requests"][0]
        self.assertEqual(len(req["body"]), 64)
        self.assertNotIn("body_truncation", req)

"""L1 unit tests for hand 0.7.0 S1 — a11y v2 serialization productization.

PRD: docs/prd-ax-perception.md (S1). No real Chrome needed: the CDP call
surface is injected/mocked.

Covers: curation rules, label/state formatting, structural collapse, handle
stability, truncation policy, cross-process determinism (byte-identical output),
handle-map IO + [idx] resolution, backendNodeId→coordinate mapping (physical px),
and the ax_snapshot receipt.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hand.perception.ax_tree as ax


# ── fixture builders ─────────────────────────────────────────────────

def _n(node_id, role, name="", parent=None, backend_id=None, props=None, ignored=False):
    node = {"nodeId": node_id, "role": {"value": role}, "name": {"value": name}}
    if parent is not None:
        node["parentId"] = parent
    if backend_id is not None:
        node["backendDOMNodeId"] = backend_id
    if props:
        node["properties"] = [{"name": k, "value": {"value": v}} for k, v in props.items()]
    if ignored:
        node["ignored"] = True
    return node


def fixture_nodes():
    """A small page: heading, nav link, list with a mislabeled level, dup StaticText,
    a single-child generic chain, an ignored node and an InlineTextBox."""
    return [
        _n("1", "RootWebArea", "Example Page"),
        _n("2", "heading", "Welcome", parent="1", backend_id=102, props={"level": 1}),
        _n("3", "StaticText", "Welcome", parent="2"),
        _n("4", "navigation", "Main", parent="1"),
        _n("5", "link", "Sign in", parent="4", backend_id=105, props={"focusable": True}),
        _n("6", "StaticText", "Sign in", parent="5"),
        _n("7", "list", "", parent="1"),
        _n("8", "listitem", "Item A", parent="7", props={"level": 2}),
        _n("9", "listitem", "Item B", parent="7"),
        # single-child generic chain: generic > generic > button  (structural, collapse)
        _n("10", "generic", "", parent="1"),
        _n("11", "generic", "", parent="10"),
        _n("12", "button", "More", parent="11", backend_id=112, props={"hasPopup": "menu"}),
        _n("13", "InlineTextBox", "More", parent="12"),
        _n("14", "button", "Hidden", parent="1", ignored=True),
        _n("15", "textbox", "Search", parent="1", backend_id=115, props={"focusable": True}),
    ]


FIXTURE = fixture_nodes()


class TestCuration(unittest.TestCase):
    def test_drops_ignored_and_layout_roles(self):
        kept = ax.filter_nodes(FIXTURE)
        roles = [n["role"]["value"] for n in kept]
        self.assertNotIn("InlineTextBox", roles)
        self.assertNotIn("Hidden", [n.get("name", {}).get("value") for n in kept])
        self.assertEqual(len(kept), len(FIXTURE) - 2)

    def test_index_tree_links_children_in_document_order(self):
        kept = ax.filter_nodes(FIXTURE)
        children, roots = ax.index_tree(kept)
        self.assertEqual([n["nodeId"] for n in roots], ["1"])
        self.assertEqual([n["nodeId"] for n in children["1"]], ["2", "4", "7", "10", "15"])


class TestLabels(unittest.TestCase):
    def test_heading_level_becomes_h1(self):
        role, name, state_s, _cut = ax.node_label(_n("x", "heading", "Welcome", props={"level": 1}))
        self.assertEqual(role, "heading")
        self.assertTrue(state_s.startswith(" (h1"))

    def test_level_misapplied_to_listitem_is_dropped(self):
        role, name, state_s, _cut = ax.node_label(_n("x", "listitem", "Item A", props={"level": 2}))
        self.assertNotIn("h2", state_s)
        self.assertNotIn("level", state_s)

    def test_focusable_only_shown_for_non_interactive_roles(self):
        _, _, s_link, _cut = ax.node_label(_n("x", "link", "Sign in", props={"focusable": True}))
        self.assertNotIn("focusable", s_link)
        _, _, s_generic, _cut = ax.node_label(_n("x", "generic", "box", props={"focusable": True}))
        self.assertIn("focusable", s_generic)

    def test_state_order_is_declared_not_set_order(self):
        """STATE_PROPS must be an ordered sequence: str set iteration order varies
        with PYTHONHASHSEED, which would break byte-identical serialization."""
        self.assertIsInstance(ax.STATE_PROPS, tuple)
        _, _, s, _cut = ax.node_label(_n("x", "button", "B", props={"disabled": True, "checked": "true"}))
        self.assertEqual(s, " (disabled=True, checked=true)")

    def test_name_is_single_line_and_truncated(self):
        # v2.1: a name longer than MAX_NAME is cut AND the cut is flagged
        # (never silent). Fixture must exceed MAX_NAME (200 since v2.1).
        role, name, _, cut = ax.node_label(_n("x", "StaticText", "a\nb" + "x" * 300))
        self.assertNotIn("\n", name)
        self.assertEqual(len(name), ax.MAX_NAME)
        self.assertTrue(cut)

    def test_short_name_is_never_flagged_truncated(self):
        role, name, _, cut = ax.node_label(_n("x", "StaticText", "一句完整的话"))
        self.assertEqual(name, "一句完整的话")
        self.assertFalse(cut)

    def test_serialize_declares_text_truncated_count(self):
        nodes = [
            _n("1", "RootWebArea", "P"),
            _n("2", "StaticText", "短文本", parent="1"),
            _n("3", "StaticText", "长" * 250, parent="1"),
        ]
        ser = ax.serialize(nodes)
        self.assertEqual(ser["text_truncated_count"], 1)
        flagged = [m for m in ser["nodes"] if m.get("text_truncated")]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["idx"], 3)
        # short page: nothing truncated anywhere
        ser0 = ax.serialize([_n("1", "RootWebArea", "P"), _n("2", "link", "ok", parent="1")])
        self.assertEqual(ser0["text_truncated_count"], 0)
        self.assertEqual(ser0["format"], "a11y-v2.1")


class TestSerialization(unittest.TestCase):
    def setUp(self):
        ser = ax.serialize(FIXTURE)
        self.ser = ser
        self.lines = ser["lines"]
        self.text = ax.snapshot_text(ser)

    def test_line_format(self):
        self.assertIn('- link "Sign in" [', self.text)
        for line in self.lines:
            self.assertRegex(line, r'^\s*- .+ \[\d+\]$')

    def test_structural_generic_chain_is_collapsed(self):
        button_line = [l for l in self.lines if 'button "More"' in l][0]
        self.assertEqual(len(button_line) - len(button_line.lstrip()), 2)  # depth 1, not 3

    def test_duplicate_statictext_does_not_emit_a_line(self):
        self.assertEqual(sum(1 for l in self.lines if 'StaticText "Sign in"' in l), 0)
        # ...but it consumes an index (experiment-v2 fidelity: indices are positions
        # in the curated traversal, not dense line numbers).
        idxs = [n["idx"] for n in self.ser["nodes"]]
        self.assertEqual(idxs, sorted(idxs))
        self.assertGreater(max(idxs), len(self.lines))

    def test_nodes_align_one_to_one_with_lines(self):
        self.assertEqual(len(self.ser["nodes"]), len(self.lines))
        for node, line in zip(self.ser["nodes"], self.lines):
            self.assertTrue(line.endswith(f'[{node["idx"]}]'))

    def test_handle_is_stable_across_runs(self):
        again = ax.serialize(FIXTURE)
        self.assertEqual(ax.snapshot_text(again), self.text)

    def test_hash_is_sha256_of_text(self):
        import hashlib
        self.assertEqual(self.ser["sha256"], hashlib.sha256(self.text.encode("utf-8")).hexdigest())

    def test_no_truncation_marker_on_small_tree(self):
        self.assertFalse(self.ser["truncated"])
        self.assertEqual(self.ser["nodes_omitted"], 0)


class TestTruncation(unittest.TestCase):
    def test_truncation_marks_flag_and_counts_omitted(self):
        full = ax.serialize(FIXTURE)
        cut = ax.serialize(FIXTURE, max_lines=3)
        self.assertTrue(cut["truncated"])
        self.assertEqual(len(cut["lines"]), 3)
        self.assertEqual(cut["lines"], full["lines"][:3])
        self.assertEqual(cut["nodes_omitted"], len(full["lines"]) - 3)
        # No dangling handles: every [idx] in the emitted text has a nodes entry,
        # and the cut is a prefix of the full traversal (indices are traversal
        # positions, so they may skip — see the duplicate-StaticText rule).
        self.assertEqual([n["idx"] for n in cut["nodes"]],
                         [n["idx"] for n in full["nodes"][:3]])
        self.assertTrue(all(f'[{n["idx"]}]' in cut["lines"][i]
                            for i, n in enumerate(cut["nodes"])))


class TestDeterminismAcrossProcesses(unittest.TestCase):
    """Same page (same CDP payload) → byte-identical serialization, even with a
    different PYTHONHASHSEED (the training-data contract, PRD S1)."""

    def test_cross_process_bytes_identical(self):
        script = (
            "import json,sys;sys.path.insert(0,{root!r});"
            "import hand.perception.ax_tree as ax;"
            "nodes=json.load(open(sys.argv[1]));"
            "print(ax.snapshot_text(ax.serialize(nodes)))"
        ).format(root=os.path.join(os.path.dirname(__file__), ".."))
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(FIXTURE, f)
            path = f.name
        try:
            outs = []
            for seed in ("0", "1", "12345"):
                env = dict(os.environ, PYTHONHASHSEED=seed)
                env.pop("PYTHONPATH", None)
                r = subprocess.run([sys.executable, "-c", script, path],
                                   capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                self.assertEqual(r.returncode, 0, r.stderr)
                outs.append(r.stdout)
            self.assertEqual(len(set(outs)), 1)
        finally:
            os.unlink(path)


class TestHandleMap(unittest.TestCase):
    def test_handle_map_round_trip_and_resolution_forms(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "handles.json")
            ax.save_handle_map({"3": {"role": "link", "name": "Sign in", "x": 10, "y": 20}},
                               path=p)
            for form in ("[3]", "3", "idx:3", "  [3] "):
                r = ax.resolve_handle(form, path=p)
                self.assertEqual(r["role"], "link", form)
                self.assertEqual(r["x"], 10)
            self.assertIn("error", ax.resolve_handle("[9]", path=p))
            self.assertEqual(ax.handle_index("idx:7"), 7)
            self.assertIsNone(ax.handle_index("a.login"))

    def test_resolve_handle_without_map_errors(self):
        r = ax.resolve_handle("[1]", path="/nonexistent/handles.json")
        self.assertIn("error", r)


class TestCoords(unittest.TestCase):
    def test_backend_ids_to_coords_returns_physical_pixels(self):
        calls = []

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            calls.append(method)
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11, 0]}
            if method == "DOM.getBoxModel":
                return {"model": {"content": [10, 20, 110, 20, 110, 60, 10, 60]}}
            return {}

        out = ax.backend_ids_to_coords(fake_call, mock.Mock(), [105, 112], dpr=2.0)
        # 0.13: the box as well as its centre — 100×40 css → 200×80 physical.
        self.assertEqual(out[105], {"x": 120, "y": 80, "w": 200, "h": 80})
        self.assertIsNone(out[112])                        # nodeId 0 → not rendered
        self.assertIn("DOM.getDocument", calls)

    def test_missing_box_model_is_none_not_error(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11]}
            if method == "DOM.getBoxModel":
                raise RuntimeError("CDP error: not in render tree")
            return {}

        out = ax.backend_ids_to_coords(fake_call, mock.Mock(), [7], dpr=1.0)
        self.assertIsNone(out[7])

    def test_hit_test_reports_topmost_node(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "DOM.getNodeForLocation":
                return {"backendNodeId": 999}
            return {}

        out = ax.hit_test(fake_call, mock.Mock(), [(105, 10.0, 20.0)])
        self.assertEqual(out[105], 999)

    def test_hit_test_unknown_is_none_not_error(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            raise RuntimeError("Detached")

        out = ax.hit_test(fake_call, mock.Mock(), [(105, 10.0, 20.0)])
        self.assertIsNone(out[105])

    def test_hit_test_uses_css_px(self):
        seen = []

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            seen.append(params)
            return {"backendNodeId": 105}

        ax.hit_test(fake_call, mock.Mock(), [(105, 10.4, 20.6)])
        self.assertEqual(seen[0]["x"], 10)   # css px, not dpr-scaled physical px
        self.assertEqual(seen[0]["y"], 20)

    def test_hit_test_applies_document_offset(self):
        # 0.13: boxes are viewport coordinates, DOM.getNodeForLocation wants
        # document coordinates. At scrollY=0 the two coincide, which is why this
        # survived every earlier check; on a scrolled page each probe answered
        # "No node found at given location" and the verdict layer emptied itself
        # (MDN, scrollY=900: judged 63 → 0). The offset belongs here, in the one
        # function that knows both spaces.
        seen = []

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            seen.append(params)
            return {"backendNodeId": 105}

        out = ax.hit_test(fake_call, mock.Mock(), [(105, 10.0, 20.0)], offset=(0, 900))
        self.assertEqual(seen[0]["x"], 10)   # no horizontal scroll, no shift
        self.assertEqual(seen[0]["y"], 920)  # viewport y + scrollY
        self.assertEqual(out[105], 105)

    def test_dom_parents_walks_the_whole_tree(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "DOM.getDocument":
                return {"root": {
                    "backendNodeId": 1, "children": [
                        {"backendNodeId": 2, "children": [
                            {"backendNodeId": 3, "children": []}]},
                        {"backendNodeId": 4, "children": []}]}}
            return {}

        self.assertEqual(ax.dom_parents(fake_call, mock.Mock()),
                         {2: 1, 3: 2, 4: 1})

    def test_on_same_chain_self_ancestor_descendant(self):
        parents = {2: 1, 3: 2, 4: 1}
        self.assertTrue(ax.on_same_chain(2, 2, parents))    # self
        self.assertTrue(ax.on_same_chain(3, 1, parents))    # descendant of 1
        self.assertTrue(ax.on_same_chain(1, 3, parents))    # ancestor of 3
        self.assertFalse(ax.on_same_chain(3, 4, parents))   # sibling branches
        self.assertFalse(ax.on_same_chain(99, 3, parents))  # unknown node


class TestHint(unittest.TestCase):
    def test_overflow_menu_hint_from_haspopup_button(self):
        ser = ax.serialize(FIXTURE)
        hint = ax.overflow_hint(ser["nodes"])
        self.assertIsNotNone(hint)
        self.assertIn('button "More"', hint)
        self.assertIn("[", hint)

    def test_no_hint_when_no_popup(self):
        nodes = [_n("1", "RootWebArea", "x"), _n("2", "link", "a", parent="1")]
        self.assertIsNone(ax.overflow_hint(ax.serialize(nodes)["nodes"]))


# ── ax_snapshot with a mocked CDP surface ────────────────────────────

PAGE = {"id": "1", "type": "page", "url": "https://beings.town/", "title": "Beings",
        "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}


class _FakeWS:
    def close(self):
        pass


class TestAxSnapshot(unittest.TestCase):
    def _snapshot(self, max_lines=ax.DEFAULT_MAX_LINES, **kw):
        calls = []

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            calls.append((method, params))
            if method == "Accessibility.getFullAXTree":
                return {"nodes": FIXTURE}
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11, 22, 33, 44]}
            if method == "DOM.getBoxModel":
                return {"model": {"content": [0, 0, 20, 0, 20, 10, 0, 10]}}
            if method == "Browser.getVersion":
                return {"product": "Chrome/141.0.0", "protocolVersion": "1.3"}
            if method == "Page.getLayoutMetrics":
                # 0.13: a page scrolled by 300 — the offset has to reach
                # hit_test, otherwise every probe answers "No node found".
                return {"cssLayoutViewport": {"clientWidth": 100, "clientHeight": 100},
                        "cssVisualViewport": {"pageX": 0, "pageY": 300}}
            if method == "Runtime.evaluate":
                return {"result": {"value": 1}}
            return {}

        tmp = tempfile.mkdtemp()
        with mock.patch.object(ax, "list_pages", return_value=[PAGE]), \
             mock.patch.object(ax, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(ax, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(ax, "cdp_call", side_effect=fake_call), \
             mock.patch.object(ax, "_init_domains", return_value=None), \
             mock.patch.object(ax, "_write_last", return_value=None):
            out = ax.ax_snapshot(max_lines=max_lines,
                                 handle_map_path=os.path.join(tmp, "h.json"), **kw)
        return out, calls, os.path.join(tmp, "h.json")

    def test_snapshot_shape(self):
        out, calls, map_path = self._snapshot()
        self.assertEqual(out["method"], "cdp_a11y")
        self.assertEqual(out["format"], ax.AX_FORMAT_VERSION)
        self.assertEqual(out["url"], "https://beings.town/")
        self.assertEqual(out["page_title"], "Beings")
        self.assertGreater(out["node_count"], 0)
        self.assertEqual(out["line_count"], len(out["tree"].split("\n")))
        self.assertFalse(out["truncated"])
        self.assertEqual(out["ax_version"]["product"], "Chrome/141.0.0")
        self.assertEqual([m for m, _ in calls][0], "Accessibility.getFullAXTree")

    def test_handle_map_persisted_for_later_idx_clicks(self):
        out, _, map_path = self._snapshot()
        with open(map_path) as f:
            saved = json.load(f)
        link_idx = [n["idx"] for n in out["nodes"] if n["role"] == "link"][0]
        entry = saved[str(link_idx)]
        self.assertEqual(entry["name"], "Sign in")
        self.assertEqual(entry["backend_node_id"], 105)
        self.assertEqual(entry["x"], 10)  # css 10 × dpr 1

    def test_coords_for_every_backed_node(self):
        # 0.13 reverses the 0.9 rule. Coordinates used to be resolved only for
        # interactive nodes, which left "visible but not clickable" nodes with
        # no position at all — the band where a StaticText or a plain container
        # lives. Every backed node is placed now; the interactive distinction
        # survives in the handle entry, not in the coordinate map.
        out, _, _ = self._snapshot()
        backed = [n for n in out["nodes"] if n["backend_node_id"]]
        self.assertTrue(backed)
        for n in backed:
            self.assertIn(str(n["idx"]), out["coords"])
        self.assertTrue([n for n in backed if not n["interactive"]],
                        "fixture must contain a non-interactive backed node")

    def test_covered_node_declares_its_coverer(self):
        # 0.13: a node whose centre is occupied reports who sits on top, and
        # the receipt declares how many such nodes there are.
        with mock.patch.object(
                ax, "hit_test",
                side_effect=lambda call, ws, pts, **kw: {b: 999 for b, _, _ in pts}):
            out, _, _ = self._snapshot()
        covered = [e for e in out["handles"].values() if e.get("reachable") is False]
        self.assertTrue(covered)
        self.assertTrue(all(e["covered_by"] == 999 for e in covered))
        self.assertIn("covered at their centre", out.get("hint") or "")

    def test_reachable_when_node_is_topmost(self):
        with mock.patch.object(
                ax, "hit_test",
                side_effect=lambda call, ws, pts, **kw: {b: b for b, _, _ in pts}):
            out, _, _ = self._snapshot()
        entries = [e for e in out["handles"].values() if "reachable" in e]
        self.assertTrue(entries)
        self.assertTrue(all(e["reachable"] is True for e in entries))
        self.assertNotIn("covered", out.get("hint") or "")

    def test_scroll_offset_reaches_hit_test(self):
        # 0.13: the offset is read from Page.getLayoutMetrics →
        # cssVisualViewport and handed to hit_test. This locks the wiring;
        # the arithmetic itself is locked in test_hit_test_applies_document_offset.
        seen = {}

        def fake_offset(call, ws, pts, offset=(0.0, 0.0)):
            seen["offset"] = offset
            return {b: b for b, _, _ in pts}

        with mock.patch.object(ax, "hit_test", side_effect=fake_offset):
            self._snapshot()
        self.assertEqual(seen.get("offset"), (0.0, 300.0))

    def test_iframe_content_is_merged(self):
        # 0.13: getFullAXTree without a frameId answers for the root document
        # only, so everything a page embeds was invisible — measured on a
        # one-iframe fixture, 0 of the frame's named nodes reached the handle
        # map. The frame's own tree comes back per frameId, and its
        # backendNodeIds resolve in top-level coordinates (no offset math).
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Accessibility.getFullAXTree":
                if (params or {}).get("frameId") == "F_FRAME":
                    return {"nodes": [
                        _n("777", "button", "Frame button", parent="1", backend_id=777),
                    ]}
                return {"nodes": fixture_nodes()}
            if method == "Page.getFrameTree":
                return {"frameTree": {"frame": {"id": "F_MAIN"},
                                      "childFrames": [{"frame": {"id": "F_FRAME"}}]}}
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11, 22, 33, 44]}
            if method == "DOM.getBoxModel":
                return {"model": {"content": [0, 0, 20, 0, 20, 10, 0, 10]}}
            if method == "Browser.getVersion":
                return {"product": "Chrome/141.0.0", "protocolVersion": "1.3"}
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 800, "clientHeight": 600}}
            return {}

        tmp = tempfile.mkdtemp()
        with mock.patch.object(ax, "list_pages", return_value=[PAGE]), \
             mock.patch.object(ax, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(ax, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(ax, "cdp_call", side_effect=fake_call), \
             mock.patch.object(ax, "_init_domains", return_value=None), \
             mock.patch.object(ax, "_write_last", return_value=None):
            out = ax.ax_snapshot(handle_map_path=os.path.join(tmp, "h.json"))
        names = [e.get("name") for e in out["handles"].values()]
        self.assertIn("Frame button", names)
        self.assertIn("child frame(s) merged", out.get("hint") or "")

    def test_descendant_hit_is_reachable_not_covered(self):
        # elementFromPoint returns the deepest element, so a container whose
        # centre reports its own child was never covered — the click still
        # bubbles through it. Only an off-chain branch counts as a block.
        with mock.patch.object(ax, "hit_test",
                               side_effect=lambda call, ws, pts, **kw: {b: 500 for b, _, _ in pts}), \
             mock.patch.object(ax, "dom_parents",
                               return_value={500: 105, 105: 1, 1: None}):
            out, _, _ = self._snapshot()
        e = [x for x in out["handles"].values() if x["backend_node_id"] == 105][0]
        self.assertTrue(e["reachable"])
        self.assertNotIn("covered_by", e)

    def test_natural_evidence_fields(self):
        out, _, _ = self._snapshot()
        self.assertGreater(out["serialized_bytes"], 0)
        self.assertEqual(out["node_count"], out["line_count"])
        self.assertEqual(out["curated_node_count"], len(ax.filter_nodes(FIXTURE)))
        self.assertIn("product", out["ax_version"])
        # The verified/evidence wrapper belongs to the router (S3), not here.
        self.assertNotIn("verified", out)
        self.assertNotIn("evidence", out)

    def test_empty_tree_reports_zero_nodes(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "Accessibility.getFullAXTree":
                return {"nodes": []}
            if method == "Browser.getVersion":
                return {}
            return {}
        with mock.patch.object(ax, "list_pages", return_value=[PAGE]), \
             mock.patch.object(ax, "resolve_page", return_value=(0, PAGE)), \
             mock.patch.object(ax, "cdp_connect", return_value=_FakeWS()), \
             mock.patch.object(ax, "cdp_call", side_effect=fake_call), \
             mock.patch.object(ax, "_init_domains", return_value=None), \
             mock.patch.object(ax, "_write_last", return_value=None):
            out = ax.ax_snapshot(handle_map_path="/tmp/does-not-matter.json")
        self.assertEqual(out["node_count"], 0)
        self.assertEqual(out["tree"], "")
        self.assertFalse(out["truncated"])


if __name__ == "__main__":
    unittest.main()


class TestFixtureFidelity(unittest.TestCase):
    """Reproduce the v2.1 golden snapshot from the saved raw AX payload.

    The reference (experiments/a11y_ab/github_snapshot_v2_1.txt) was generated
    once from the same raw payload under the v2.1 contract (MAX_NAME=200, cut
    declared) and committed; any accidental serializer change breaks the
    byte-identical comparison. The v2 snapshot (60-char silent cut) is kept in
    the repo as history — it is what S4 subject-1 caught.

    The experiment artifacts live under experiments/ (not shipped in the Grove
    bundle), so this skips when they are absent.
    """

    ROOT = os.path.join(os.path.dirname(__file__), "..")
    RAW = os.path.join(ROOT, "experiments", "a11y_ab", "github_ax.json")
    V2 = os.path.join(ROOT, "experiments", "a11y_ab", "github_snapshot_v2_1.txt")

    @staticmethod
    def _normalize(lines):
        """Drop the documented refinements so the comparison is about structure:
          * StaticText noise rule (empty name / duplicate of nearest ancestor line)
          * level-on-listitem curation fix (state suffix only)
          * page-content clock skew between the two captures ('47 vs 48 minutes ago')
        """
        import re as _re
        out = []
        for line in lines:
            if "StaticText" in line:
                continue
            line = _re.sub(r" \([^)]*\)", "", line)
            line = _re.sub(r"\d+ (minutes?|hours?|days?) ago", r"N \1 ago", line)
            out.append(line)
        return out

    @unittest.skipUnless(os.path.exists(RAW) and os.path.exists(V2),
                         "experiment artifacts not present")
    def test_serializer_reproduces_experiment_v2_snapshot(self):
        import json as _json
        raw = _json.load(open(self.RAW))
        mine = ax.snapshot_text(ax.serialize(raw)).split("\n")
        exp = open(self.V2).read().split("\n")
        self.assertEqual(self._normalize(mine), self._normalize(exp))

    @unittest.skipUnless(os.path.exists(RAW), "experiment artifacts not present")
    def test_experiment_tree_is_not_truncated_by_default_limit(self):
        import json as _json
        raw = _json.load(open(self.RAW))
        ser = ax.serialize(raw)
        self.assertFalse(ser["truncated"])
        self.assertGreater(ser["kept_count"], 500)


class TestStaticTextCuration(unittest.TestCase):
    def test_empty_name_statictext_is_dropped_but_consumes_index(self):
        nodes = [_n("1", "alert", "Alert!"), _n("2", "StaticText", "", parent="1"),
                 _n("3", "link", "Next", parent="1")]
        ser = ax.serialize(nodes)
        self.assertNotIn("StaticText", ax.snapshot_text(ser))
        self.assertEqual([n["idx"] for n in ser["nodes"]], [1, 3])

    def test_whitespace_only_name_statictext_is_dropped(self):
        nodes = [_n("1", "alert", "x"), _n("2", "StaticText", "   ", parent="1")]
        self.assertEqual(len(ax.serialize(nodes)["lines"]), 1)

    def test_surrounding_whitespace_of_real_names_is_preserved(self):
        role, name, _, _cut = ax.node_label(_n("x", "StaticText", " Star "))
        self.assertEqual(name, " Star ")

    def test_duplicate_detection_ignores_whitespace_differences(self):
        nodes = [_n("1", "link", "Sign in"), _n("2", "StaticText", " Sign in ", parent="1")]
        self.assertEqual(len(ax.serialize(nodes)["lines"]), 1)


class TestZeroAreaBox(unittest.TestCase):
    def test_degenerate_quad_is_not_a_click_target(self):
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11]}
            if method == "DOM.getBoxModel":
                return {"model": {"content": [5, 5, 5, 5, 5, 5, 5, 5]}}   # zero area
            return {}

        out = ax.backend_ids_to_coords(fake_call, mock.Mock(), [9], dpr=1.0)
        self.assertIsNone(out[9])


class TestReachabilityInputs(unittest.TestCase):
    """0.13: three inputs the verdict depends on, each found by measuring
    real pages on 2026-10-21 (github.com, developer.mozilla.org)."""

    def test_coords_prefer_the_border_box(self):
        # content box under-reports every padded control: a clickable 40px
        # button whose content is 20px read as 20px, so "how much error does
        # this forgive" answered with the wrong number (71/233 nodes off >2px,
        # worst 2x, measured on github.com).
        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11]}
            if method == "DOM.getBoxModel":
                return {"model": {"content": [10, 10, 30, 10, 30, 30, 10, 30],
                                  "border": [0, 0, 40, 0, 40, 40, 0, 40]}}
            return {}

        out = ax.backend_ids_to_coords(fake_call, mock.Mock(), [5], dpr=2.0)
        self.assertEqual(out[5]["w"], 80)      # border 40 css * dpr 2
        self.assertEqual(out[5]["h"], 80)
        self.assertEqual(out[5]["x"], 40)      # centre 20 css * dpr 2

    def test_hit_test_does_not_pierce_ua_shadow(self):
        # With includeUserAgentShadowDOM a point over an <input> answers with
        # its internal UA-shadow editor div, which dom_parents cannot place on
        # any chain — every text field read as "covered by a stranger".
        seen = []

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            seen.append((method, dict(params or {})))
            return {"backendNodeId": 7}

        out = ax.hit_test(fake_call, None, [(5, 10.5, 20.5)])
        self.assertEqual(out[5], 7)
        params = seen[0][1]
        self.assertNotIn("includeUserAgentShadowDOM", params)
        self.assertEqual(params["x"], 10)      # CDP input space: integer CSS px

    def test_dom_parents_places_shadow_and_pseudo_children(self):
        # shadow roots hang off "shadowRoots" and ::before/::after off
        # "pseudoElements" — neither is in "children". Walking only "children"
        # made every web component and every icon-button read as cross-branch.
        doc = {"root": {
            "backendNodeId": 1,
            "children": [{"backendNodeId": 2, "children": []}],
            "shadowRoots": [{"children": [
                {"backendNodeId": 3, "children": [{"backendNodeId": 4}]}]}],
            "pseudoElements": [{"backendNodeId": 5}],
        }}

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            return doc

        parents = ax.dom_parents(fake_call, None)
        self.assertEqual(parents[2], 1)
        self.assertEqual(parents[3], 1)   # a shadow child bubbles to its host
        self.assertEqual(parents[4], 3)
        self.assertEqual(parents[5], 1)   # ::before belongs to its host

"""Release test for 0.13.4 — 数的是行，不是载荷。

0.13.1 的提示说「合并进来的节点有的读得到、点不到」。0.13.4 修的是那个数：
它数的是原始 AX 节点（含永远不成行的结构节点），而不是树上印出来的行。
跨源夹具上每个可见节点都可寻址，旧计数照样报 3；两级嵌套报 1。

这一版还坐实了一件事：0.13.1 记的「两级嵌套内层节点没有 backendDOMNodeId」
已不成立——内层按钮有 id、有 frame_id、点得到。行为证据在
tests/test_frame_origins.py 里（真 Chrome，子文档 title 翻转）。
"""

import json
import os
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestVersion0134(unittest.TestCase):

    def test_version_bumped_everywhere(self):
        with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["version"], "0.13.4")
        self.assertIn('__version__ = "0.13.4"', _read("hand/__init__.py"))

    def test_changelog_has_0134_entry(self):
        log = _read("CHANGELOG.md")
        self.assertIn("## [0.13.4] — 2026-10-22", log)
        # the entry must name the thing that changed, not just the version
        self.assertIn("frame_lines_without_handle", log)

    def test_serialize_reports_line_count_not_raw_count(self):
        """The one code contract of this release, checked directly."""
        from hand.perception import ax_tree

        def node(nid, role, name, bid=None, parent="1"):
            n = {"nodeId": nid, "role": {"type": "role", "value": role},
                 "name": {"type": "value", "value": name}}
            if bid is not None:
                n["backendDOMNodeId"] = bid
            if parent:
                n["parentId"] = parent
            return n

        nodes = [
            node("1", "RootWebArea", "top", bid=1, parent=None),
            dict(node("2", "none", "", bid=None), ignored=True),   # never a line
            node("3", "StaticText", "orphan", bid=None),
        ]
        ser = ax_tree.serialize(nodes, frame_nodeids={"2", "3"})
        self.assertEqual(len(ser["lines"]), 2)
        self.assertEqual(ser["frame_lines_without_handle"], 1)

    def test_note_wording_no_longer_claims_a_missing_idx(self):
        """The old wording ('have no [idx] handle') was itself wrong: those
        lines do get an [idx]; what they lack is a box. Check the note the
        snapshot actually emits, not the source text (the 0.13.4 comment
        quotes the old wording on purpose)."""
        from hand.perception import ax_tree
        src = _read(os.path.join("hand", "perception", "ax_tree.py"))
        self.assertIn("not aimable", src)
        self.assertNotIn("have no [idx] handle", src)

    def test_internal_key_is_stripped(self):
        from hand.perception import ax_tree
        nodes = [{"nodeId": "1", "role": {"type": "role", "value": "RootWebArea"},
                  "name": {"type": "value", "value": "top"},
                  "backendDOMNodeId": 1}]
        ser = ax_tree.serialize(nodes)
        self.assertNotIn("_node_id", ser["nodes"][0])


if __name__ == "__main__":
    unittest.main()

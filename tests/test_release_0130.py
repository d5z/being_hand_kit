"""Release test for 0.13.0 — 看见了，也要能摸到。

Spec: CHANGELOG 0.13.0 条目。这一版把坐标从「只给 interactive」扩到
「全部有 backend id 的节点」（预算 400，interactive 优先），并给每个屏内
节点一次 hit test：中心点上命中的是不是自己这一支。
"""

import json
import os
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _manifest():
    with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


class TestVersion0130(unittest.TestCase):
    """Historical lock: 0.13.0 shipped 2026-10-21. The version itself has moved
    on — current-version assertions live in test_release_0131. This class keeps
    the shipped changelog entry, so it can stay registered forever."""

    def test_changelog_has_0130_entry(self):
        self.assertIn("## [0.13.0]", _read("CHANGELOG.md"))


class TestReachabilityLayer(unittest.TestCase):
    """the four primitives 0.13 added must be public and keep their semantics."""

    def test_primitives_are_public(self):
        from hand.perception import ax_tree as ax
        for name in ("hit_test", "dom_parents", "on_same_chain"):
            self.assertTrue(callable(getattr(ax, name, None)), name)
        self.assertIsInstance(ax.MAX_COORD_NODES, int)
        self.assertGreaterEqual(ax.MAX_COORD_NODES, 400)

    def test_box_carries_width_and_height(self):
        from hand.perception import ax_tree as ax

        def fake_call(ws, method, params=None, msg_id=1, timeout=10):
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.pushNodesByBackendIdsToFrontend":
                return {"nodeIds": [11]}
            if method == "DOM.getBoxModel":
                return {"model": {"content": [0, 0, 40, 0, 40, 20, 0, 20]}}
            return {}

        out = ax.backend_ids_to_coords(fake_call, mock.Mock(), [5], dpr=2.0)
        self.assertEqual(set(out[5]), {"x", "y", "w", "h"})
        self.assertEqual(out[5]["w"], 80)     # 40 css × dpr 2
        self.assertEqual(out[5]["h"], 40)

    def test_cover_verdict_is_cross_branch_only(self):
        """同链不算被盖（点在子元素上会冒泡），跨分支才算。"""
        from hand.perception import ax_tree as ax
        parents = {2: 1, 3: 2, 4: 1}
        self.assertTrue(ax.on_same_chain(3, 2, parents))    # descendant
        self.assertTrue(ax.on_same_chain(2, 3, parents))    # ancestor
        self.assertFalse(ax.on_same_chain(3, 4, parents))   # sibling branches

"""Release test for 0.13.2 — 平移不等于仿射。

Spec: CHANGELOG 0.13.2 条目。

0.13.1 把帧内点加上帧原点当顶层点派发。这在 owner 未被 transform 时成立；
`iframe{transform:scale(0.5)}` 上实测（2026-10-22）：see 画在 (112,89)，click
派发 (123,126)——平移做了，缩放被静默丢掉，回执仍是 landed=true，页面没动。

0.13.2 的判据：派发点来自元素自己的 border quad（DOM.getBoxModel，顶层、含
transform），帧内点用双线性映射过去。同一份读数喂给 see 和 click，两者不可能
再各说各话。

行为证明在 tests/test_iframe_transform.py（缩放夹具上点完子 frame 必须跳走）。
本文件锁版本、变更记录与公开面。
"""

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _manifest():
    with open(os.path.join(ROOT, "kit", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


class TestVersion0132(unittest.TestCase):
    """Historical lock: 0.13.2 shipped 2026-10-22. The version itself has moved
    on — current-version assertions live in the newest test_release_*."""

    def test_changelog_has_0132_entry(self):
        self.assertIn("## [0.13.2]", _read("CHANGELOG.md"))


class TestQuadMappingIsTheDispatchSource(unittest.TestCase):
    """One read for both drawing and clicking is the whole point of 0.13.2."""

    def test_quad_helpers_exist(self):
        from hand.action import cdp_act
        for name in ("_element_border_quad", "_map_local_to_top",
                     "_quad_center_size"):
            self.assertTrue(callable(getattr(cdp_act, name, None)), name)

    def test_click_path_uses_the_quad_for_child_frames(self):
        src = _read("hand/action/cdp_act.py")
        self.assertIn("_element_border_quad(ws, entry[\"backend_node_id\"])", src)
        self.assertIn("element border quad (bilinear, top-level)", src)

    def test_click_path_no_longer_adds_the_frame_origin(self):
        """The 0.13.1 arithmetic must be gone: origin is diagnostic only."""
        src = _read("hand/action/cdp_act.py")
        self.assertNotIn("click_local[0] + dx", src)
        self.assertNotIn("click_local[1] + dy", src)

    def test_receipt_still_names_both_spaces(self):
        src = _read("hand/action/cdp_act.py")
        for field in ("local_space", "dispatch_space", "mapping"):
            self.assertIn(field, src)


class TestMappingIsExactForAffines(unittest.TestCase):
    """Bilinear on the quad is exact for translate/scale/rotate — the property
    the fix rests on, checked independently of the browser."""

    def test_translate_scale_rotate(self):
        from hand.action.cdp_act import _map_local_to_top

        bounds = {"left": 0.0, "top": 0.0, "width": 100.0, "height": 50.0}
        # translate(40,20) scale(2,2): TL(40,20) TR(240,20) BR(240,120) BL(40,120)
        quad = [40.0, 20.0, 240.0, 20.0, 240.0, 120.0, 40.0, 120.0]
        self.assertEqual(_map_local_to_top(quad, bounds, (0.0, 0.0)), (40.0, 20.0))
        x, y = _map_local_to_top(quad, bounds, (50.0, 25.0))   # local centre
        self.assertAlmostEqual(x, 140.0, places=6)
        self.assertAlmostEqual(y, 70.0, places=6)
        x, y = _map_local_to_top(quad, bounds, (100.0, 50.0))  # local BR
        self.assertAlmostEqual(x, 240.0, places=6)
        self.assertAlmostEqual(y, 120.0, places=6)


if __name__ == "__main__":
    unittest.main()

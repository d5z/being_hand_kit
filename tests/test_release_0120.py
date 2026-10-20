"""Release test for 0.12.0 — 变化可判定（effected 从 unknown 变成可判定）。

Spec: docs/prd-0.12-change-verifiability.md
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


class TestVersion0120(unittest.TestCase):
    def test_version_is_0120(self):
        import hand
        self.assertEqual(hand.__version__, "0.12.0")

    def test_manifest_version_is_0120(self):
        self.assertEqual(_manifest()["version"], "0.12.0")


class TestDiffPrimitive(unittest.TestCase):
    def test_frame_diff_is_exposed(self):
        from hand.perception.pixels import frame_diff
        self.assertTrue(callable(frame_diff))

    def test_effect_module_imports(self):
        from hand.action import effect
        self.assertTrue(callable(effect.probe_action))
        self.assertTrue(callable(effect.wait_stable))
        self.assertTrue(callable(effect.grab_png))

    def test_thresholds_are_named_constants(self):
        """阈值不许散落在代码里——它是 PRD 的可调旋钮。"""
        from hand.action import effect
        for name in ('EXPECT_R', 'EXPECT_PAD', 'EFFECT_THRESHOLD',
                     'STABLE_QUIET_MS', 'STABLE_TIMEOUT_MS'):
            self.assertTrue(hasattr(effect, name), name)


class TestToolsAcceptVerify(unittest.TestCase):
    def test_cdp_click_takes_verify(self):
        import inspect
        from hand.action import effect
        sig = inspect.signature(effect.probe_action)
        self.assertIn('verify', sig.parameters)
        self.assertTrue(sig.parameters['verify'].default)

    def test_mcp_server_declares_verify_on_three_tools(self):
        manifest = _manifest()
        tools = {t['name']: t for t in manifest['tools']}
        for name in ('cdp_click', 'cdp_drag', 'cdp_key'):
            self.assertIn('verify', tools[name]['params']['properties'], name)
            self.assertTrue(
                tools[name]['params']['properties']['verify'].get('default'),
                name)


class TestHonestyBoundary(unittest.TestCase):
    """0.12 的三条不许破的边界，写在 CHANGELOG 里就要能被找到。"""

    def setUp(self):
        body = _read("CHANGELOG.md")
        start = body.index("## [0.12.0]")
        nxt = body.find("\n## [", start + 1)
        self.entry = body[start:nxt if nxt != -1 else None]

    def test_entry_states_the_three_states(self):
        for word in ('changed', 'no_change', 'unknown'):
            self.assertIn(word, self.entry)

    def test_entry_states_undispatched_is_not_no_change(self):
        self.assertIn('did not dispatch', self.entry)

    def test_entry_states_known_limits(self):
        self.assertIn('Known limits', self.entry)
        self.assertIn('不是「动作失败了」', self.entry)


class TestPRDLanded(unittest.TestCase):
    def setUp(self):
        self.prd = _read("docs/prd-0.12-change-verifiability.md")

    def test_prd_carries_facts_and_repairs(self):
        self.assertIn("## F 层：事实", self.prd)
        self.assertIn("## S 层：修复", self.prd)

    def test_prd_carries_acceptance_with_negatives(self):
        self.assertIn("## L 层：验收", self.prd)
        self.assertIn("真负样本", self.prd)

    def test_prd_states_what_it_refuses_to_do(self):
        self.assertIn("不做什么", self.prd)
        self.assertIn("不做语义判断", self.prd)


if __name__ == '__main__':
    unittest.main()

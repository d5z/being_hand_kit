"""Release test for 0.13.6 — `landed` 由谁代答。

0.13.5 及以前，handle 路径的 `landed` 来自派发**前**的探针（0.9.4-P5 的
`_clickable_point`）。探针回答的是「这个点属于目标吗」，从来没有回答过
「事件实际落到了谁身上」。两者在真页上可以分开：探针通过、派发之后接收
者是祖先容器——回执仍写 `landed=true`，因为没人回读过。

本版派发之后在目标节点自己的执行上下文里回读一次 elementFromPoint，用
节点身份（self/descendant/ancestor/other/none）判 landed。

这里守的是机制形状：
  * 回读原语存在，且走 callFunctionOn（节点自己的上下文）而不是顶层
    Runtime.evaluate——后者在子帧里会读错文档，那是 0.13.4 踩过的坑
  * 回读发生在派发之后（源码顺序可查）
  * 读不出来时不许把它写成 false：退回探针值，并用 landed_source 署名
  * xy 路径把「点上有谁」提到回执顶层，且不假装有 hit/miss

行为由真页那组（有浏览器时跑）和 2026-10-23 的真页标定读数守。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import cdp_act

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _click_handle_body():
    src = _read("hand", "action", "cdp_act.py")
    body = src[src.index("def cdp_click_handle"):]
    return body[:body.index("\ndef ", 10)]


class TestVersion0136(unittest.TestCase):

    def test_version_bumped_everywhere(self):
        self.assertIn('__version__ = "0.13.6"',
                      _read("hand", "__init__.py"))
        self.assertIn('"version": "0.13.6"', _read("kit", "manifest.json"))

    def test_changelog_has_0136_entry(self):
        body = _read("CHANGELOG.md")
        self.assertIn("## [0.13.6]", body)
        self.assertIn("0.13.6", body.split("## [")[1])


class TestReceiverReadback(unittest.TestCase):

    def test_hit_relation_primitive_exists(self):
        self.assertTrue(callable(cdp_act._hit_relation))
        self.assertIn("elementFromPoint", cdp_act._HIT_REL_FN)
        for relation in ("self", "descendant", "ancestor", "other", "none"):
            self.assertIn("'%s'" % relation, cdp_act._HIT_REL_FN)

    def test_read_runs_in_the_nodes_own_context(self):
        """子帧里的点必须在目标节点的上下文里读——顶层 evaluate 读到的是
        另一个文档，0.13.4 的 document 通道第一版就死在这里。"""
        src = _read("hand", "action", "cdp_act.py")
        body = src[src.index("def _hit_relation"):]
        body = body[:body.index("\ndef ", 10)]
        self.assertIn("Runtime.callFunctionOn", body)
        self.assertNotIn("Runtime.evaluate", body)

    def test_receiver_is_read_after_the_dispatch(self):
        """顺序可查：先派发，再问谁接到。反过来就是拿承诺当结果。"""
        body = _click_handle_body()
        i_dispatch = body.index("_click_at(ws, dispatched[0]")
        i_readback = body.index("_hit_relation(ws, oid")
        self.assertLess(i_dispatch, i_readback)

    def test_unreadable_is_not_a_negative(self):
        """导航导致节点脱离时读不回来：那是「不知道」，不是「没点到」。"""
        body = _click_handle_body()
        self.assertIn("landed_probe", body)
        self.assertIn("pre-dispatch probe only", body)
        tail = body[body.index("hit = _hit_relation"):]
        self.assertIn("landed = landed_probe", tail)

    def test_relation_maps_to_landed(self):
        """self/descendant 算到了；ancestor/other/none 算没到。"""
        body = _click_handle_body()
        self.assertIn("in ('self', 'descendant')", body)

    def test_parse_and_failure_are_honest(self):
        original = cdp_act.cdp_call
        try:
            cdp_act.cdp_call = lambda *a, **k: {
                "result": {"value": '{"relation":"ancestor","tag":"P","'
                                    'id":"","text":"genai"}'}}
            got = cdp_act._hit_relation(object(), object(), 1.0, 2.0)
            self.assertEqual(got["relation"], "ancestor")
            self.assertEqual(got["tag"], "P")

            def boom(*a, **k):
                raise RuntimeError("context destroyed")
            cdp_act.cdp_call = boom
            self.assertIsNone(cdp_act._hit_relation(object(), object(), 1.0, 2.0))

            cdp_act.cdp_call = lambda *a, **k: {"result": {"value": "null"}}
            self.assertIsNone(cdp_act._hit_relation(object(), object(), 1.0, 2.0))
        finally:
            cdp_act.cdp_call = original


class TestXYReceipt(unittest.TestCase):

    def test_point_owner_is_a_top_level_fact(self):
        src = _read("hand", "action", "cdp_act.py")
        body = src[src.index("if action.startswith('xy:')"):]
        body = body[:body.index("\n    return cdp_click(sel)")]
        self.assertIn("'element_at_point': at_point", body)

    def test_no_fake_hit_verdict_without_a_declared_target(self):
        """裸坐标不声明目标，就没有 hit/miss 可言——回执里要写明原因，
        而不是给一个看起来权威的布尔值。"""
        src = _read("hand", "action", "cdp_act.py")
        body = src[src.index("if action.startswith('xy:')"):]
        body = body[:body.index("\n    return cdp_click(sel)")]
        self.assertIn("declares no target", body)


if __name__ == "__main__":
    unittest.main()

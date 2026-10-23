"""Release test for 0.13.7 — 坐标和文本都要先被判，再被报。

0.13.6 把 handle 路径的 `landed` 从「派发前的承诺」换成「派发后的回读」。
同一条标定线上还剩两处同形状的东西：

  * xy 的 `landed` 仍来自派发**前**读到的「点上有谁」。文档在派发中换了
    之后，同一个坐标在新文档里指别的东西——那时给 hit/miss 是编的。
  * `text=` 用 normalize-space() 匹配，只折叠 ASCII 空白。标签里带
    U+00A0 的元素永远匹配不上，回执却写「text element not found」，
    读起来像「没有这个标签」，实际只差一个词的字节。

这里守机制形状（不需要浏览器）：
  * `@expect` 在派发**前**解析（过期的 handle 是它自己的问题）
  * 文档身份在派发前后各读一次，变了就不给 hit/miss
  * 视口外的点在派发前被拒
  * 「派发前读到的点在不在」不再代答 landed
  * text 匹配折叠 Unicode 空白，成功回执带 matched_raw_bytes

行为由 tests/test_xy_expect.py 与 tests/test_text_match.py 的真页组守。
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import cdp_act

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _xy_body():
    src = _read("hand", "action", "cdp_act.py")
    body = src[src.index("if action.startswith('xy:')"):]
    return body[:body.index("\n    return cdp_click(sel)")]


def _text_body():
    src = _read("hand", "action", "cdp_act.py")
    body = src[src.index("if action.startswith('text=')"):]
    return body[:body.index("if action.startswith('xy:')")]


class TestVersion0137(unittest.TestCase):

    def test_version_is_current(self):
        """Newest release test owns the exact current version."""
        self.assertIn('__version__ = "0.13.7"', _read("hand", "__init__.py"))
        self.assertIn('"version": "0.13.7"', _read("kit", "manifest.json"))

    def test_changelog_entry_names_the_changes(self):
        body = _read("CHANGELOG.md")
        self.assertIn("## [0.13.7]", body)
        section = body.split("## [0.13.7]")[1].split("## [")[0]
        for needle in ("@expect", "U+00A0", "landed", "matched_raw_bytes"):
            self.assertIn(needle, section)


class TestXYVerdict(unittest.TestCase):

    def test_expect_is_parsed_before_the_dispatch(self):
        body = _xy_body()
        self.assertIn("@expect=", body)
        self.assertLess(body.index("@expect="),
                        body.index("_click_at(ws, x, y, dpr)"))

    def test_no_pre_dispatch_answer_for_landed(self):
        """派发前读到的「点上有谁」不许直接写成 landed=True。"""
        body = _xy_body()
        self.assertNotIn("landed = True if at_point is not None", body)
        self.assertIn("landed_source", body)

    def test_document_identity_is_read_on_both_sides(self):
        body = _xy_body()
        i_before = body.index("before_doc = _doc_identity")
        i_dispatch = body.index("_click_at(ws, x, y, dpr)")
        i_after = body.index("after_doc = _doc_identity")
        self.assertLess(i_before, i_dispatch)
        self.assertLess(i_dispatch, i_after)

    def test_navigation_yields_no_verdict(self):
        body = _xy_body()
        self.assertIn("navigated", body)
        self.assertIn("no hit/miss verdict", body)

    def test_out_of_viewport_is_refused_before_dispatch(self):
        body = _xy_body()
        i_refuse = body.index("is outside viewport")
        self.assertLess(i_refuse, body.index("_click_at(ws, x, y, dpr)"))
        self.assertIn("refused", body)

    def test_both_relation_vocabularies(self):
        body = _xy_body()
        self.assertIn("in ('self', 'descendant')", body)
        self.assertIn("in ('ancestor', 'other', 'none')", body)

    def test_xy_at_prefix_is_reachable(self):
        """0.11.0 文档写过 'xy@img:<sha8>:X,Y'，但解析只认 'xy:'。"""
        self.assertIn("action.startswith('xy@')", _read("hand", "action",
                                                        "cdp_act.py"))

    def test_selector_relation_primitive_marks_missing(self):
        self.assertIn("'missing'", cdp_act._HIT_REL_SEL_FN)
        original = cdp_act.cdp_call
        try:
            cdp_act.cdp_call = lambda *a, **k: {
                "result": {"value": '{"relation":"missing"}'}}
            self.assertEqual(cdp_act._hit_relation_selector(object(), "#gone", 1, 2),
                             {"relation": "missing"})

            def boom(*a, **k):
                raise RuntimeError("context gone")
            cdp_act.cdp_call = boom
            self.assertIsNone(cdp_act._hit_relation_selector(object(), "#x", 1, 2))
        finally:
            cdp_act.cdp_call = original


class TestDocIdentity(unittest.TestCase):

    def test_unreadable_is_not_the_same_document(self):
        original = cdp_act.cdp_call

        def boom(*a, **k):
            raise RuntimeError("context gone")
        try:
            cdp_act.cdp_call = boom
            self.assertEqual(cdp_act._doc_identity(object()), {"ok": False})

            cdp_act.cdp_call = lambda *a, **k: {
                "result": {"value": '{"href":"https://x/","timeOrigin":12.5}'}}
            got = cdp_act._doc_identity(object())
            self.assertTrue(got["ok"])
            self.assertEqual(got["href"], "https://x/")

            cdp_act.cdp_call = lambda *a, **k: {"result": {"value": "null"}}
            self.assertEqual(cdp_act._doc_identity(object()), {"ok": False})
        finally:
            cdp_act.cdp_call = original


class TestElementAtChecked(unittest.TestCase):

    def test_three_answers_are_distinct(self):
        original = cdp_act.cdp_call
        try:
            cdp_act.cdp_call = lambda *a, **k: {"result": {"value": "null"}}
            self.assertEqual(cdp_act._element_at_checked(object(), 1, 2),
                             ("none", None))

            def boom(*a, **k):
                raise RuntimeError("no context")
            cdp_act.cdp_call = boom
            self.assertEqual(cdp_act._element_at_checked(object(), 1, 2),
                             ("unknown", None))

            cdp_act.cdp_call = lambda *a, **k: {
                "result": {"value": json.dumps({"tag": "A", "text": "hi"})}}
            state, data = cdp_act._element_at_checked(object(), 1, 2)
            self.assertEqual(state, "hit")
            self.assertEqual(data["tag"], "A")
        finally:
            cdp_act.cdp_call = original


class TestTextFold(unittest.TestCase):

    def test_unicode_spaces_are_folded(self):
        body = _text_body()
        for needle in (r"\\u00a0", r"\\u2000-\\u200a", r"\\u202f", r"\\u205f",
                       r"\\u3000", r"\\ufeff"):
            self.assertIn(needle, body)

    def test_success_names_whether_raw_bytes_matched(self):
        body = _text_body()
        self.assertIn("matched_raw_bytes", body)
        self.assertIn("unicode-space-folded contains", body)

    def test_failure_separates_whitespace_from_case(self):
        body = _text_body()
        self.assertIn("whitespace_mismatch_only", body)
        self.assertIn("case_mismatch_only", body)
        self.assertIn("raw_contains", body)

    def test_matching_stays_case_sensitive(self):
        """折叠空白不许顺手把大小写也折了。"""
        body = _text_body()
        self.assertIn("fold(t).indexOf(q)>=0", body)
        self.assertNotIn("fold(t).toLowerCase().indexOf(q)>=", body)

    def test_node_is_scrolled_into_view_before_measuring(self):
        """视口外的标签曾报成「no clickable point (covered)」——那是把
        「elementFromPoint 在视口外答 null」说成「被遮住了」。"""
        self.assertIn("scrollIntoView", _text_body())

    def test_empty_text_query_is_refused_without_a_browser(self):
        """空查询包含所有标签，会顺手点到文档里第一个元素。"""
        r = cdp_act.cdp_click_do("text=   ")
        self.assertFalse(r["verified"])
        self.assertIn("empty text=", r["error"])


if __name__ == "__main__":
    unittest.main()

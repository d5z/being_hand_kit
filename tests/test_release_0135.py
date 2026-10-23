"""Release test for 0.13.5 — 一条通道的空不是世界的空。

0.13.5 只有一处改动，但它属于回执诚实这一族：`effected` 从单通道（像素）
改成双通道（pixel + document），并且每个通道在回执里声明自己看不见什么。

判据（机制层，不需要浏览器）：
  * effect.py 里有 document 通道的两个入口（读数 + 判定），且它走的是
    会合并子帧的 a11y 通道，不是只读顶层文档的表达式
  * 两条通道各自带 blind_to
  * 「一条可用、另一条不可用」不许落到 no_change

行为由 tests/test_effect_channels.py（真页 L2）和 tests/test_effect.py
（四象限）守；这里守的是这几条机制还在，以及版本号/变更记录对齐。
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.action import effect

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class TestVersion0135(unittest.TestCase):

    def test_version_bumped_everywhere(self):
        """Historical lock: 0.13.5 shipped. The *current* version is checked by
        the newest release test — pinning "the version is 0.13.5 forever" would
        go red on every later bump and teach nothing."""
        init = _read("hand", "__init__.py")
        self.assertRegex(init, r'__version__ = "\d+\.\d+\.\d+"')
        manifest = _read("kit", "manifest.json")
        m = re.search(r'"version": "(\d+)\.(\d+)\.(\d+)"', manifest)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(tuple(int(x) for x in m.groups()), (0, 13, 5))

    def test_changelog_has_0135_entry(self):
        body = _read("CHANGELOG.md")
        self.assertIn("## [0.13.5] — 2026-10-22", body)
        # the entry must name the thing that changed, not just the version
        section = body.split("## [0.13.5]")[1].split("## [")[0]
        self.assertIn("effected", section)

    def test_two_channels_exist(self):
        self.assertTrue(callable(effect.grab_png))
        self.assertTrue(callable(effect.grab_document))
        self.assertTrue(callable(effect._document_verdict))

    def test_document_channel_reads_the_frame_merged_tree(self):
        """只读顶层 document 的通道看不见子帧里的标题变化——那正是这一版
        要修的样本。document 通道必须走会合并子帧的 a11y 读数。"""
        src = _read("hand", "action", "effect.py")
        body = src[src.index("def grab_document"):]
        body = body[:body.index("\ndef ", 10)]
        self.assertIn("ax_snapshot", body)
        self.assertNotIn("Runtime.evaluate", body)

    def test_each_channel_declares_its_blindness(self):
        self.assertIn("title", effect.PIXEL_BLIND_TO)
        self.assertIn("ink", effect.DOC_BLIND_TO)

    def test_document_fingerprint_reports_which_fact_moved(self):
        before = {"title": "a", "url": "http://x/1", "tree_sha": "s1"}
        after_title = {"title": "b", "url": "http://x/1", "tree_sha": "s1"}
        after_url = {"title": "a", "url": "http://x/2", "tree_sha": "s1"}
        after_tree = {"title": "a", "url": "http://x/1", "tree_sha": "s2"}
        self.assertEqual(effect._document_verdict(before, after_title),
                         ("changed", ["title"]))
        self.assertEqual(effect._document_verdict(before, after_url),
                         ("changed", ["url"]))
        self.assertEqual(effect._document_verdict(before, after_tree),
                         ("changed", ["content"]))
        self.assertEqual(effect._document_verdict(before, dict(before)),
                         ("no_change", []))

    def test_module_docstring_states_the_rule(self):
        doc = effect.__doc__ or ""
        self.assertIn("一条通道的空不是世界的空", doc)


if __name__ == "__main__":
    unittest.main()

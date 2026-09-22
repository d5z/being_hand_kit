"""S3 OCR diff 测试（PRD 0.9 S3，纯标准库 unittest）。

运行：python3 -m unittest tests.test_ocr_diff -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hand.perception.ocr_diff import ocr_diff, parse_bounds

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "ocr")


def _read(name):
    with open(os.path.join(FIXDIR, name), "r", encoding="utf-8") as f:
        return f.read()


class TestFixtures(unittest.TestCase):
    def test_added(self):
        result = ocr_diff(_read("added_before.txt"), _read("added_after.txt"))
        blocks = result["blocks"]
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual(b["change"], "added")
        self.assertEqual(b["text"], "登录成功")
        self.assertTrue(b["bounds"])
        for key in ("x", "y", "w", "h", "center_x", "center_y"):
            self.assertIn(key, b["bounds"])
        self.assertEqual(b["near"], [4])

    def test_removed(self):
        result = ocr_diff(_read("removed_before.txt"), _read("removed_after.txt"))
        blocks = result["blocks"]
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual(b["change"], "removed")
        self.assertEqual(b["text"], "正在加载...")
        for key in ("x", "y", "w", "h", "center_x", "center_y"):
            self.assertIn(key, b["bounds"])
        self.assertEqual(b["near"], [4])

    def test_moved(self):
        result = ocr_diff(_read("moved_before.txt"), _read("moved_after.txt"))
        blocks = result["blocks"]
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual(b["change"], "moved")
        self.assertEqual(b["text"], "提交")
        self.assertEqual(b["from"]["y"], 172)
        self.assertEqual(b["to"]["y"], 300)

    def test_no_change(self):
        result = ocr_diff(_read("no_change_before.txt"), _read("no_change_after.txt"))
        self.assertEqual(result["blocks"], [])


class TestTolerance(unittest.TestCase):
    def test_moved_less_than_half_line_height_not_reported(self):
        # 行高 24，半高 12；位移 6 < 12 -> 同块，不报 moved
        before = "0.98\t40\t100\t120\t24\t用户名\n0.97\t40\t172\t90\t24\t提交\n"
        after = "0.98\t40\t100\t120\t24\t用户名\n0.97\t40\t178\t90\t24\t提交\n"
        self.assertEqual(ocr_diff(before, after)["blocks"], [])

    def test_moved_more_than_half_line_height_reported(self):
        before = "0.98\t40\t100\t120\t24\t用户名\n0.97\t40\t172\t90\t24\t提交\n"
        after = "0.98\t40\t100\t120\t24\t用户名\n0.97\t40\t200\t90\t24\t提交\n"
        blocks = ocr_diff(before, after)["blocks"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["change"], "moved")

    def test_lines_within_half_line_height_group_into_one_block(self):
        # 两行中心相差 10 < 12，属于同块；块文本合并
        before = "0.9\t40\t100\t120\t24\t第一行\n0.9\t40\t110\t120\t24\t第二行\n"
        after = "0.9\t40\t100\t120\t24\t第一行\n0.9\t40\t110\t120\t24\t第二行\n"
        self.assertEqual(ocr_diff(before, after)["blocks"], [])


class TestReplaceWordDiff(unittest.TestCase):
    def test_replace_emits_word_fragments(self):
        before = "0.98\t40\t100\t120\t24\t欢迎登录\n0.97\t40\t124\t200\t24\tSubmit Button\n"
        after = "0.98\t40\t100\t120\t24\t欢迎登录\n0.97\t40\t124\t200\t24\tSubmit Now\n"
        blocks = ocr_diff(before, after)["blocks"]
        changes = sorted((b["change"], b["text"]) for b in blocks)
        self.assertEqual(changes, [("added", "Now"), ("removed", "Button")])
        for b in blocks:
            self.assertIn("bounds", b)
            self.assertEqual(b["near"], [1])


class TestDeterminism(unittest.TestCase):
    def test_two_runs_identical(self):
        a = json.dumps(ocr_diff(_read("removed_before.txt"), _read("removed_after.txt")),
                       ensure_ascii=False, sort_keys=True)
        b = json.dumps(ocr_diff(_read("removed_before.txt"), _read("removed_after.txt")),
                       ensure_ascii=False, sort_keys=True)
        self.assertEqual(a, b)

    def test_ordering_by_top_y_then_x(self):
        before = "0.9\t40\t100\t120\t24\tA\n0.9\t40\t148\t120\t24\tC\n"
        after = "0.9\t40\t100\t120\t24\tA\n0.9\t40\t124\t120\t24\tB\n0.9\t40\t148\t120\t24\tC\n"
        blocks = ocr_diff(before, after)["blocks"]
        ys = [b["bounds"]["y"] for b in blocks]
        self.assertEqual(ys, sorted(ys))


class TestParseBounds(unittest.TestCase):
    def test_tab_format(self):
        lines = parse_bounds("0.98\t40\t100\t120\t24\t欢迎登录\n\n0.5\t0\t0\t10\t10\t低置信\n")
        self.assertEqual(len(lines), 2)
        first = lines[0]
        self.assertEqual(first["text"], "欢迎登录")
        self.assertAlmostEqual(first["confidence"], 0.98)
        self.assertEqual((first["x"], first["y"], first["w"], first["h"]),
                         (40, 100, 120, 24))
        self.assertEqual(first["center_x"], 40 + 120 // 2)
        self.assertEqual(first["center_y"], 100 + 24 // 2)

    def test_old_confidence_text_fallback(self):
        lines = parse_bounds("0.95: 登录成功\n0.5: 加载中\n")
        self.assertEqual([l["text"] for l in lines], ["登录成功", "加载中"])
        self.assertAlmostEqual(lines[0]["confidence"], 0.95)

    def test_accepts_dict_list_and_str_list(self):
        as_dicts = parse_bounds([{"text": "A", "confidence": 0.9, "x": 0, "y": 0, "w": 10, "h": 10}])
        self.assertEqual(as_dicts[0]["center_x"], 5)
        as_strs = parse_bounds(["0.9\t0\t0\t10\t10\tA"])
        self.assertEqual(as_strs[0]["text"], "A")

    def test_permissive_confidence(self):
        lines = parse_bounds("notafloat\t40\t100\t120\t24\t文本\n")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "文本")

    def test_bad_lines_skipped(self):
        self.assertEqual(parse_bounds("\n   \nnot a valid line\n"), [])


if __name__ == "__main__":
    unittest.main()

"""0.12.0 帧差分 — pixels.frame_diff 的行为锁。

Spec: docs/prd-0.12-change-verifiability.md §S1

最要紧的一条不是「能算出差异」，是**不可比不得被读成没变化**。
"""

import struct
import unittest
import zlib

from hand.perception.pixels import frame_diff


def _chunk(tag, data):
    return (struct.pack('!I', len(data)) + tag + data
            + struct.pack('!I', zlib.crc32(tag + data) & 0xffffffff))


def make_png(width, height, color=(255, 255, 255)):
    """Solid RGB PNG. Filter byte 0 on every row."""
    row = bytes(color) * width
    raw = b''.join(b'\x00' + row for _ in range(height))
    ihdr = struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(raw))
            + _chunk(b'IEND', b''))


def with_rect(width, height, x, y, w, h, fg=(0, 0, 0), bg=(255, 255, 255)):
    """White canvas with one solid black rectangle."""
    rows = []
    for yy in range(height):
        if y <= yy < y + h:
            rows.append(b'\x00'
                        + bytes(bg) * x
                        + bytes(fg) * w
                        + bytes(bg) * (width - x - w))
        else:
            rows.append(b'\x00' + bytes(bg) * width)
    ihdr = struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(b''.join(rows)))
            + _chunk(b'IEND', b''))


class TestFrameDiff(unittest.TestCase):

    def test_identical_frames_report_zero_change(self):
        """F1：静止页面零噪声 —— 「没变」必须是可判定的强结论。"""
        a = make_png(40, 30)
        b = make_png(40, 30)
        r = frame_diff(a, b)
        self.assertTrue(r['comparable'])
        self.assertEqual(r['changed'], 0)
        self.assertEqual(r['ratio'], 0.0)
        self.assertIsNone(r['bbox'])

    def test_rectangle_is_detected_with_exact_bbox(self):
        a = make_png(40, 30)
        b = with_rect(40, 30, 10, 5, 8, 6)
        r = frame_diff(a, b)
        self.assertTrue(r['comparable'])
        self.assertEqual(r['changed'], 8 * 6)
        self.assertEqual(r['bbox'], {'x': 10, 'y': 5, 'w': 8, 'h': 6})

    def test_region_limits_the_question(self):
        """区域限定：变化在区域外时，区域内就是没变。"""
        a = make_png(40, 30)
        b = with_rect(40, 30, 30, 20, 5, 5)          # 变化在右下
        r = frame_diff(a, b, region={'x': 0, 'y': 0, 'w': 20, 'h': 15})
        self.assertTrue(r['comparable'])
        self.assertEqual(r['changed'], 0)
        self.assertEqual(r['total'], 20 * 15)

    def test_region_catches_change_inside(self):
        a = make_png(40, 30)
        b = with_rect(40, 30, 10, 5, 8, 6)
        r = frame_diff(a, b, region={'x': 5, 'y': 0, 'w': 20, 'h': 15})
        self.assertTrue(r['comparable'])
        self.assertEqual(r['changed'], 48)

    def test_geometry_mismatch_is_not_comparable(self):
        """两帧尺寸不同 → comparable:false，绝不能返回 changed=0。"""
        r = frame_diff(make_png(40, 30), make_png(41, 30))
        self.assertFalse(r['comparable'])
        self.assertIn('geometry', r['why'])
        self.assertNotIn('changed', r)

    def test_not_a_png_is_not_comparable(self):
        r = frame_diff(b'not a png at all', make_png(4, 4))
        self.assertFalse(r['comparable'])
        self.assertIn('unsupported png', r['why'])

    def test_empty_region_is_not_comparable(self):
        r = frame_diff(make_png(40, 30), make_png(40, 30),
                       region={'x': 100, 'y': 100, 'w': 10, 'h': 10})
        self.assertFalse(r['comparable'])
        self.assertIn('empty region', r['why'])

    def test_region_is_clipped_to_image(self):
        a = make_png(40, 30)
        b = with_rect(40, 30, 38, 28, 2, 2)
        r = frame_diff(a, b, region={'x': 30, 'y': 20, 'w': 100, 'h': 100})
        self.assertTrue(r['comparable'])
        self.assertEqual(r['region'], {'x': 30, 'y': 20, 'w': 10, 'h': 10})
        self.assertEqual(r['changed'], 4)

    def test_region_starting_off_image_keeps_its_width(self):
        """区域起点为负（点在页面边缘）——必须保住宽度，不能放大到全图。

        回归：先 `max(0, x)` 再 `x + w` 会把 [−55,65) 变成 [0,120)，
        区域悄悄铺满整帧，正是 region 参数要防的那种过宽。
        """
        a = make_png(100, 100)
        b = with_rect(100, 100, 80, 80, 5, 5)          # 变化在右下角
        r = frame_diff(a, b, region={'x': -55, 'y': -55, 'w': 120, 'h': 120})
        self.assertTrue(r['comparable'])
        self.assertEqual(r['region'], {'x': 0, 'y': 0, 'w': 65, 'h': 65})
        self.assertEqual(r['changed'], 0)

    def test_channel_delta_tolerance(self):
        """ch_delta 是三通道绝对差之和的容忍值。"""
        a = make_png(4, 4, (255, 255, 255))
        close = make_png(4, 4, (251, 251, 251))      # 4+4+4 = 12, 不大于 12
        self.assertEqual(frame_diff(a, close, ch_delta=12)['changed'], 0)
        off = make_png(4, 4, (250, 250, 250))        # 5+5+5 = 15 > 12
        self.assertEqual(frame_diff(a, off, ch_delta=12)['changed'], 16)
        self.assertEqual(frame_diff(a, off, ch_delta=20)['changed'], 0)


if __name__ == '__main__':
    unittest.main()

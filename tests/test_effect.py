"""0.12.0 — effect.probe_action 的行为锁。

Spec: docs/prd-0.12-change-verifiability.md §S3 / §L

最要紧的一条（实测撞出来的）：**动作没派发出去，不是「没变化」。**
一个报错的 click 和一个什么都没做的 click，在帧上长得一模一样；
把前者记成 no_change，等于用诚实的外观掩盖一次失败。
"""

import unittest
from unittest import mock

from hand.action import effect
from tests.test_frame_diff import make_png, with_rect


def _receipt(dispatched=(10, 10), **extra):
    r = {
        'method': 'cdp_click',
        'result': 'ok',
        'evidence': {'space': 'physical', 'dpr': 1,
                     'dispatched': list(dispatched),
                     'three_state': {'resolved': True, 'landed': True,
                                     'effected': 'unknown'}},
    }
    r.update(extra)
    return r


class TestProbeAction(unittest.TestCase):

    def _run(self, before, after, receipt, verify=True):
        def action():
            return dict(receipt)

        with mock.patch.object(effect, 'grab_png',
                               lambda: (before, None)), \
             mock.patch.object(effect, 'wait_stable',
                               lambda **kw: {'stable': True, 'png': after,
                                             'waited_ms': 5}):
            return effect.probe_action('click', action, verify=verify)

    def test_no_verify_leaves_receipt_alone(self):
        """verify=False 必须逐字复现 0.11 的回执。"""
        out = self._run(make_png(40, 30), make_png(40, 30),
                        _receipt(), verify=False)
        self.assertNotIn('change', out)
        self.assertEqual(out, _receipt())

    def test_undispatched_action_is_unknown_not_no_change(self):
        """动作报错且没有派发证据 → unknown，不是 no_change。"""
        out = self._run(make_png(40, 30), make_png(40, 30),
                        _receipt(error='no place — call route_open first',
                                 evidence={'dpr': 1}))
        self.assertEqual(out['effected'], 'unknown')
        self.assertIn('did not dispatch', out['change']['reason'])
        self.assertIn('no place', out['change']['reason'])

    def test_identical_frames_are_no_change(self):
        out = self._run(make_png(40, 30), make_png(40, 30), _receipt())
        self.assertEqual(out['effected'], 'no_change')
        self.assertEqual(out['change']['changed'], 0)
        self.assertTrue(out['change']['verifiable'])
        self.assertEqual(out['evidence']['three_state']['effected'], 'no_change')

    def test_change_inside_region_is_changed(self):
        after = with_rect(40, 30, 10, 10, 6, 6)
        out = self._run(make_png(40, 30), after, _receipt(dispatched=(10, 10)))
        self.assertEqual(out['effected'], 'changed')
        self.assertEqual(out['change']['changed'], 36)
        self.assertIsNotNone(out['change']['bbox'])

    def test_change_outside_region_is_flagged_not_judged(self):
        """区域外变了：仍报 no_change，但把「别处动了」标出来。"""
        after = with_rect(100, 100, 80, 80, 5, 5)
        out = self._run(make_png(100, 100), after, _receipt(dispatched=(5, 5)))
        self.assertEqual(out['effected'], 'no_change')
        self.assertTrue(out['change']['changed_outside_region'])
        self.assertEqual(out['change']['whole_frame']['changed'], 25)

    def test_uncomparable_frames_are_unknown(self):
        out = self._run(make_png(40, 30), make_png(41, 30), _receipt())
        self.assertEqual(out['effected'], 'unknown')
        self.assertIn('geometry', out['change']['reason'])

    def test_unsettled_page_is_unknown(self):
        with mock.patch.object(effect, 'grab_png',
                               lambda: (make_png(40, 30), None)), \
             mock.patch.object(effect, 'wait_stable',
                               lambda **kw: {'stable': False,
                                             'reason': 'page did not settle'}):
            out = effect.probe_action('click', lambda: _receipt(), verify=True)
        self.assertEqual(out['effected'], 'unknown')
        self.assertEqual(out['change']['reason'], 'page did not settle')

    def test_grab_failure_still_runs_the_action(self):
        """验不了不等于不做：动作必须照发，只是如实标 unknown。"""
        ran = []

        def action():
            ran.append(True)
            return _receipt()

        with mock.patch.object(effect, 'grab_png',
                               lambda: (None, 'screenshot failed: boom')):
            out = effect.probe_action('click', action, verify=True)

        self.assertEqual(ran, [True])
        self.assertEqual(out['effected'], 'unknown')
        self.assertIn('boom', out['change']['reason'])

    def test_drag_region_spans_both_endpoints(self):
        receipt = {
            'method': 'cdp_drag',
            'from': {'x': 100, 'y': 100},
            'to': {'x': 300, 'y': 200},
            'evidence': {'space': 'css_px', 'dpr': 1},
        }
        region = effect._expect_region(receipt, 'drag')
        self.assertEqual(region['x'], 100 - effect.EXPECT_PAD)
        self.assertEqual(region['y'], 100 - effect.EXPECT_PAD)
        self.assertEqual(region['w'], 200 + 2 * effect.EXPECT_PAD)
        self.assertEqual(region['h'], 100 + 2 * effect.EXPECT_PAD)

    def test_reason_is_rewritten_once_judged(self):
        """动作层写「你自己去比两帧」，判定之后这句话必须改成事实。

        留着不改，回执就是在建议一件已经做完的事。
        """
        r = _receipt()
        r['evidence']['reason'] = ('drag has no readback — verify the effect by '
                                   'comparing two frames, not by this receipt')
        out = self._run(make_png(40, 30), make_png(40, 30), r)
        self.assertIn('frame diff', out['evidence']['reason'])
        self.assertNotIn('verify the effect by', out['evidence']['reason'])

    def test_key_has_no_scope(self):
        self.assertIsNone(effect._expect_region({'evidence': {}}, 'key'))


if __name__ == '__main__':
    unittest.main()

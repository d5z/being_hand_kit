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


def _doc(title='page', url='http://x/', body='sha-a'):
    return {'title': title, 'url': url, 'tree_sha': body,
            'lines': ['- RootWebArea "%s"' % title], 'truncated': False}


class TestProbeAction(unittest.TestCase):

    def _run(self, before, after, receipt, verify=True,
             doc_before=None, doc_after=None):
        def action():
            return dict(receipt)

        db = _doc() if doc_before is None else doc_before
        da = (_doc() if doc_after is None else doc_after)
        readings = [db, da]

        with mock.patch.object(effect, 'grab_png',
                               lambda: (before, None)), \
             mock.patch.object(effect, 'wait_stable',
                               lambda **kw: {'stable': True, 'png': after,
                                             'waited_ms': 5}), \
             mock.patch.object(effect, 'grab_document',
                               lambda: (readings.pop(0), None)
                               if readings else (None, 'spent')):
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
        readings = [_doc(), _doc()]
        with mock.patch.object(effect, 'grab_png',
                               lambda: (make_png(40, 30), None)), \
             mock.patch.object(effect, 'grab_document',
                               lambda: (readings.pop(0), None)), \
             mock.patch.object(effect, 'wait_stable',
                               lambda **kw: {'stable': False,
                                             'reason': 'page did not settle'}):
            out = effect.probe_action('click', lambda: _receipt(), verify=True)
        self.assertEqual(out['effected'], 'unknown')
        self.assertIn('did not settle', out['change']['reason'])
        self.assertEqual(out['change']['channels']['pixel']['verdict'],
                         'unavailable')

    def test_grab_failure_still_runs_the_action(self):
        """验不了不等于不做：动作必须照发，只是如实标 unknown。"""
        ran = []

        def action():
            ran.append(True)
            return _receipt()

        readings = [_doc(), _doc()]
        with mock.patch.object(effect, 'grab_png',
                               lambda: (None, 'screenshot failed: boom')), \
             mock.patch.object(effect, 'grab_document',
                               lambda: (readings.pop(0), None)):
            out = effect.probe_action('click', action, verify=True)

        self.assertEqual(ran, [True])
        self.assertEqual(out['effected'], 'unknown')
        self.assertIn('boom', out['change']['reason'])
        self.assertEqual(out['change']['channels']['pixel']['verdict'],
                         'unavailable')

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
        self.assertIn('channel verdicts', out['evidence']['reason'])
        self.assertNotIn('verify the effect by', out['evidence']['reason'])

    def test_key_has_no_scope(self):
        self.assertIsNone(effect._expect_region({'evidence': {}}, 'key'))


class TestTwoChannels(unittest.TestCase):
    """0.13.5 — 一条通道的空不是世界的空。

    四个象限，每个都得说实话：
      pixel 变 / document 变 → changed（两条都看见）
      pixel 变 / document 静 → changed（像素看见，文档本来就瞎）
      pixel 静 / document 变 → changed（2026-10-22 那个真实样本：
                               点击改了 document.title，像素 0 变化）
      pixel 静 / document 静 → no_change（都看了、都没看见）
      pixel 静 / document 瞎 → unknown（盲区的阴性不能当阴性用）
    """

    def _run(self, px_before, px_after, doc_before, doc_after):
        readings = [doc_before, doc_after]

        with mock.patch.object(effect, 'grab_png',
                               lambda: (px_before, None)), \
             mock.patch.object(effect, 'wait_stable',
                               lambda **kw: {'stable': True, 'png': px_after,
                                             'waited_ms': 3}), \
             mock.patch.object(effect, 'grab_document',
                               lambda: (readings.pop(0), None)):
            return effect.probe_action('click', lambda: _receipt(), verify=True)

    def test_pixels_and_document_both_move(self):
        after = with_rect(40, 30, 10, 10, 6, 6)
        out = self._run(make_png(40, 30), after, _doc(), _doc(title='now'))
        self.assertEqual(out['effected'], 'changed')
        self.assertEqual(out['change']['channels']['pixel']['verdict'], 'changed')
        self.assertEqual(out['change']['channels']['document']['verdict'],
                         'changed')

    def test_ink_only_change_is_changed(self):
        """纯视觉位移：像素看见，文档本来就瞎——照样 changed。"""
        after = with_rect(40, 30, 10, 10, 6, 6)
        out = self._run(make_png(40, 30), after, _doc(), _doc())
        self.assertEqual(out['effected'], 'changed')
        self.assertEqual(out['change']['channels']['pixel']['verdict'], 'changed')
        self.assertEqual(out['change']['channels']['document']['verdict'],
                         'no_change')

    def test_title_only_change_is_not_no_change(self):
        """2026-10-22 的真样本：点击真的发生了，只有标题变了。

        0.12 在这里报 no_change，整帧变化率 0.000。
        """
        out = self._run(make_png(40, 30), make_png(40, 30),
                        _doc(title='nest inner'),
                        _doc(title='INNER CLICKED'))
        self.assertEqual(out['effected'], 'changed')
        self.assertEqual(out['change']['channels']['pixel']['verdict'],
                         'no_change')
        self.assertEqual(out['change']['channels']['document']['moved'],
                         ['title'])
        self.assertIn('document', out['change']['reason'])
        self.assertIn('title', out['change']['reason'])

    def test_url_change_is_seen(self):
        out = self._run(make_png(40, 30), make_png(40, 30),
                        _doc(url='http://x/a'), _doc(url='http://x/b'))
        self.assertEqual(out['effected'], 'changed')
        self.assertEqual(out['change']['channels']['document']['moved'], ['url'])

    def test_both_quiet_is_no_change(self):
        out = self._run(make_png(40, 30), make_png(40, 30), _doc(), _doc())
        self.assertEqual(out['effected'], 'no_change')
        self.assertIn('both channels looked', out['change']['reason'])

    def test_blind_document_is_not_a_negative(self):
        readings = [_doc(), None]
        with mock.patch.object(effect, 'grab_png',
                               lambda: (make_png(40, 30), None)), \
             mock.patch.object(effect, 'wait_stable',
                               lambda **kw: {'stable': True,
                                             'png': make_png(40, 30),
                                             'waited_ms': 3}), \
             mock.patch.object(effect, 'grab_document',
                               lambda: (readings.pop(0), None)
                               if readings[0] else (None, 'eval blocked')):
            out = effect.probe_action('click', lambda: _receipt(), verify=True)
        self.assertEqual(out['effected'], 'unknown')
        self.assertIn('blind channel', out['change']['reason'])
        self.assertIn('eval blocked', out['change']['reason'])

    def test_each_channel_declares_its_blindness(self):
        out = self._run(make_png(40, 30), make_png(40, 30), _doc(), _doc())
        ch = out['change']['channels']
        self.assertIn('title', ch['pixel']['blind_to'])
        self.assertIn('ink', ch['document']['blind_to'])


if __name__ == '__main__':
    unittest.main()

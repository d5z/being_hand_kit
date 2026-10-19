"""0.11.0 action primitives — key parsing, three-state receipts, drag shape.

Spec: docs/prd-0.11-action-primitives.md

What these lock down:
  * a key combo parses to a modifier bitmask + main key, and every malformed
    combo fails loudly instead of dispatching a partial guess;
  * the dispatched event sequence is modifiers-down → main-down → main-up →
    modifiers-up (the order an application actually sees);
  * a drag emits exactly one pressed, N moved, one released, and its points
    converge on the target;
  * the receipt never claims more than it observed: `effected` is always
    'unknown' in 0.11, and a bare xy source cannot claim `landed`.
"""

import unittest
from unittest import mock

from hand.action import cdp_act as A


class FakeWS:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


PAGE = {'webSocketDebuggerUrl': 'ws://fake'}


def _patched(target, calls, **extra):
    """Patch the CDP surface of cdp_act so a primitive can run offline."""
    def fake_call(_ws, method, params=None, msg_id=1, timeout=None):
        calls.append((method, params))
        return {}

    stack = [
        mock.patch.object(A, 'list_pages', return_value=[PAGE]),
        mock.patch.object(A, 'resolve_page', return_value=(0, PAGE)),
        mock.patch.object(A, 'cdp_connect', return_value=FakeWS()),
        mock.patch.object(A, '_init_domains', return_value=None),
        mock.patch.object(A, '_write_last', return_value=None),
        mock.patch.object(A, 'cdp_call', side_effect=fake_call),
    ]
    for key, value in extra.items():
        stack.append(mock.patch.object(A, key, return_value=value))
    return stack


class _Patched(object):
    def __init__(self, calls, **extra):
        self.calls = calls
        self.stack = _patched(None, calls, **extra)

    def __enter__(self):
        for p in self.stack:
            p.start()
        return self.calls

    def __exit__(self, *exc):
        for p in reversed(self.stack):
            p.stop()
        return False


class TestKeyParsing(unittest.TestCase):
    def test_plain_letter(self):
        info, err = A._parse_key_combo('r')
        self.assertIsNone(err)
        self.assertEqual(info['key'], 'r')
        self.assertEqual(info['code'], 'KeyR')
        self.assertEqual(info['vk'], ord('R'))
        self.assertEqual(info['modifiers'], 0)

    def test_ctrl_combo_bitmask(self):
        info, err = A._parse_key_combo('Control+z')
        self.assertIsNone(err)
        self.assertEqual(info['modifiers'], 2)
        self.assertEqual(info['key'], 'z')
        self.assertEqual(info['code'], 'KeyZ')

    def test_modifier_order_does_not_matter(self):
        a, _ = A._parse_key_combo('Meta+Shift+t')
        b, _ = A._parse_key_combo('Shift+Meta+t')
        self.assertEqual(a['modifiers'], b['modifiers'])
        self.assertEqual(a['modifiers'], 12)   # Meta 4 | Shift 8

    def test_named_keys(self):
        for spec, key, vk in [('Enter', 'Enter', 13), ('Escape', 'Escape', 27),
                              ('ArrowLeft', 'ArrowLeft', 37), ('Space', ' ', 32)]:
            info, err = A._parse_key_combo(spec)
            self.assertIsNone(err, spec)
            self.assertEqual(info['key'], key, spec)
            self.assertEqual(info['vk'], vk, spec)

    def test_all_modifier_aliases(self):
        for alias in ('ctrl', 'control', 'CTRL'):
            info, err = A._parse_key_combo(alias + '+a')
            self.assertIsNone(err, alias)
            self.assertEqual(info['modifiers'], 2, alias)
        for alias in ('meta', 'cmd', 'command'):
            info, err = A._parse_key_combo(alias + '+a')
            self.assertEqual(info['modifiers'], 4, alias)

    def test_unknown_modifier_fails_loudly(self):
        info, err = A._parse_key_combo('Blah+x')
        self.assertIsNone(info)
        self.assertIn('unknown modifier', err)

    def test_empty_key_fails_loudly(self):
        info, err = A._parse_key_combo('Control+')
        self.assertIsNone(info)
        self.assertIn('empty key', err)

    def test_empty_modifier_fails_loudly(self):
        info, err = A._parse_key_combo('+z')
        self.assertIsNone(info)
        self.assertIn('empty modifier', err)

    def test_unknown_named_key_fails_loudly(self):
        info, err = A._parse_key_combo('Control+NotAKey')
        self.assertIsNone(info)
        self.assertIn('unknown key', err)

    def test_digit_key(self):
        info, err = A._parse_key_combo('Meta+3')
        self.assertIsNone(err)
        self.assertEqual(info['vk'], ord('3'))


class TestThreeState(unittest.TestCase):
    def test_unknown_landed_is_none_not_false(self):
        st = A._three_state(True, None)
        self.assertIsNone(st['landed'])
        self.assertIsNot(st['landed'], False)
        self.assertEqual(st['effected'], 'unknown')

    def test_effected_never_claims_a_change(self):
        for resolved, landed in [(True, True), (True, False), (False, None)]:
            st = A._three_state(resolved, landed)
            self.assertEqual(st['effected'], 'unknown')
            self.assertTrue(st.get('effected_reason'))


class TestKeyDispatch(unittest.TestCase):
    def test_modifier_wraps_main_key(self):
        with _Patched([]) as calls:
            r = A.cdp_key('Control+z')
        events = [(p['type'], p['key']) for m, p in calls
                  if m == 'Input.dispatchKeyEvent']
        self.assertEqual(events, [('rawKeyDown', 'Control'), ('rawKeyDown', 'z'),
                                  ('keyUp', 'z'), ('keyUp', 'Control')])
        self.assertEqual(r['parsed']['modifiers'], 2)
        self.assertEqual(r['effected'], 'unknown')
        self.assertIsNone(r['landed'])            # focus unchanged → could not tell
        self.assertFalse(r['verified'])

    def test_two_modifiers_down_in_bit_order_up_reversed(self):
        with _Patched([]) as calls:
            A.cdp_key('Shift+Meta+t')
        events = [(p['type'], p['key']) for m, p in calls
                  if m == 'Input.dispatchKeyEvent']
        self.assertEqual(events[0], ('rawKeyDown', 'Meta'))    # bit 4
        self.assertEqual(events[1], ('rawKeyDown', 'Shift'))   # bit 8
        self.assertEqual(events[2][1], 't')
        self.assertEqual(events[-2], ('keyUp', 'Shift'))
        self.assertEqual(events[-1], ('keyUp', 'Meta'))

    def test_release_of_modifiers_carries_zero_mask(self):
        with _Patched([]) as calls:
            A.cdp_key('Control+a')
        ups = [p for m, p in calls
               if m == 'Input.dispatchKeyEvent' and p['type'] == 'keyUp'
               and p['key'] == 'Control']
        self.assertEqual(ups[0]['modifiers'], 0)

    def test_bad_combo_does_not_dispatch(self):
        with _Patched([]) as calls:
            r = A.cdp_key('Blah+x')
        self.assertEqual([c for c in calls if c[0] == 'Input.dispatchKeyEvent'], [])
        self.assertFalse(r['verified'])
        self.assertEqual(r['effected'], 'unknown')
        self.assertIn('unknown modifier', r['evidence']['reason'])

    def test_focus_change_is_the_only_landed_signal(self):
        with _Patched([], _active_element={'tag': 'INPUT', 'id': 'inp'}):
            r = A.cdp_key('Enter')
        self.assertIsNone(r['landed'])
        self.assertIn('focus change', r['evidence']['reason'])


class TestDragDispatch(unittest.TestCase):
    def _drag(self, from_spec='xy:100,100', to_spec='xy:200,200', steps=4,
              at_start=None, at_end=None, claim=None):
        point = {'x': 100.0, 'y': 100.0, 'how': 'xy', 'input': from_spec,
                 'dpr': 1.0, 'element': claim}
        point2 = {'x': 200.0, 'y': 200.0, 'how': 'xy', 'input': to_spec,
                  'dpr': 1.0, 'element': None}
        side = [_patched(None, []), ]
        calls = []
        with _Patched(calls,
                      _point_from_spec=None,
                      _frame_at={'known': True, 'scrollX': 0, 'scrollY': 0},
                      _element_at=at_start if at_start is not None else {'tag': 'CANVAS', 'text': ''},
                      _dpr_now=1.0) as c:
            with mock.patch.object(A, '_point_from_spec',
                                   side_effect=[(point, None), (point2, None)]):
                r = A.cdp_drag(from_spec, to_spec, steps=steps)
        return r, calls

    def test_event_sequence_shape(self):
        r, calls = self._drag(steps=4)
        types = [p['type'] for m, p in calls if m == 'Input.dispatchMouseEvent']
        self.assertEqual(types[0], 'mousePressed')
        self.assertEqual(types[-1], 'mouseReleased')
        self.assertEqual(types.count('mouseMoved'), 4)
        self.assertEqual(len(types), 6)
        self.assertEqual(r['evidence']['dispatched_events'], 6)

    def test_moves_converge_on_target(self):
        r, calls = self._drag(steps=4)
        moves = [p for m, p in calls
                 if m == 'Input.dispatchMouseEvent' and p['type'] == 'mouseMoved']
        self.assertAlmostEqual(moves[0]['x'], 125.0)    # 100 + 100/4
        self.assertAlmostEqual(moves[-1]['x'], 200.0)
        self.assertAlmostEqual(moves[-1]['y'], 200.0)
        for mv in moves:
            self.assertEqual(mv['buttons'], 1)          # button held during move

    def test_single_step_still_moves(self):
        r, calls = self._drag(steps=1)
        moves = [p for m, p in calls
                 if m == 'Input.dispatchMouseEvent' and p['type'] == 'mouseMoved']
        self.assertEqual(len(moves), 1)
        self.assertAlmostEqual(moves[0]['x'], 200.0)

    def test_zero_steps_is_clamped_not_dropped(self):
        r, calls = self._drag(steps=0)
        moves = [p for m, p in calls
                 if m == 'Input.dispatchMouseEvent' and p['type'] == 'mouseMoved']
        self.assertEqual(len(moves), 1)
        self.assertEqual(r['steps'], 1)

    def test_bare_xy_source_cannot_claim_landed(self):
        r, _ = self._drag()
        self.assertTrue(r['resolved'])
        self.assertIsNone(r['landed'])
        self.assertFalse(r['verified'])
        self.assertEqual(r['effected'], 'unknown')
        self.assertEqual(r['evidence']['element_at_start']['tag'], 'CANVAS')

    def test_effected_is_never_claimed(self):
        r, _ = self._drag()
        self.assertEqual(r['effected'], 'unknown')
        self.assertIn('no readback', r['evidence']['reason'].lower()
                      .replace('read-back', 'readback'))

    def test_frame_anchors_ride_along(self):
        r, _ = self._drag()
        self.assertTrue(r['evidence']['frame_before']['known'])
        self.assertTrue(r['evidence']['frame_after']['known'])


class TestPointSpec(unittest.TestCase):
    def test_xy_is_divided_by_dpr(self):
        with _Patched([]) as calls:
            pt, err = A._point_from_spec(None, 'xy:200,100')
        self.assertIsNone(err)
        self.assertEqual(pt['how'], 'xy')
        self.assertEqual(pt['dpr'], 1.0)
        self.assertEqual(pt['x'], 200.0)
        self.assertEqual(pt['y'], 100.0)

    def test_bad_xy_names_the_expected_shape(self):
        with _Patched([]):
            pt, err = A._point_from_spec(None, 'xy:abc')
        self.assertIsNone(pt)
        self.assertIn('expected "xy:X,Y"', err)

    def test_empty_spec_is_refused(self):
        with _Patched([]):
            pt, err = A._point_from_spec(None, '  ')
        self.assertIsNone(pt)
        self.assertIn('empty spec', err)


if __name__ == '__main__':
    unittest.main()
